"""Scene inspection and pre-render diagnostics."""

from __future__ import annotations

import math
from typing import Any

from .resource_limits import scene_resource_usage

class SceneDiagnosticsMixin:
    """Inspect both facade-created and native Blender scene objects."""

    def inspect(self) -> dict[str, Any]:
        scene = self._backend.scene
        usage = scene_resource_usage(scene)
        registered = {
            item._object.name: item
            for item in self._objects.values()
        }
        objects: list[dict[str, Any]] = []
        for obj in scene.objects:
            item = registered.get(obj.name)
            data = getattr(obj, "data", None)
            materials = getattr(data, "materials", ()) if data is not None else ()
            objects.append({
                "id": item.id if item is not None else str(obj.get("blentopy_id", obj.name)),
                "name": obj.name,
                "kind": item.kind if item is not None else obj.type.lower(),
                "role": item.role if item is not None else obj.get("blentopy_role"),
                "position": tuple(float(part) for part in obj.matrix_world.translation),
                "rotation": tuple(float(part) for part in obj.rotation_euler),
                "scale": tuple(float(part) for part in obj.scale),
                "dimensions": tuple(float(part) for part in obj.dimensions),
                "parent": obj.parent.name if obj.parent else None,
                "visible": (
                    item.visible if item is not None
                    else not obj.hide_render and not obj.hide_viewport
                ),
                "modifiers": [
                    {"name": modifier.name, "type": modifier.type}
                    for modifier in obj.modifiers
                ],
                "materials": [
                    material.name for material in materials if material is not None
                ],
                "native_blender_object": item is None,
            })
        return {
            "object_count": len(scene.objects),
            "registered_object_count": len(self._objects),
            "resource_usage": usage,
            "camera": (
                self._camera.id if self._camera else
                (scene.camera.name if scene.camera else None)
            ),
            "objects": objects,
        }

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        scene = self._backend.scene
        usage = scene_resource_usage(scene)

        limits = {"objects": 1_000, "polygons": 300_000, "modifiers": 1_500}
        for resource, value in usage.items():
            if value > limits[resource]:
                warnings.append(
                    f"Scene {resource} usage is {value:,}, above the convenience API "
                    f"budget of {limits[resource]:,}. Native bpy operations are not "
                    "blocked by this facade budget; check memory, cache size, and render time."
                )

        render = scene.render
        if (
            type(render.resolution_x) is not int or render.resolution_x < 16
            or type(render.resolution_y) is not int or render.resolution_y < 16
        ):
            errors.append("Render resolution must be at least 16x16 pixels.")
        if (
            type(render.resolution_percentage) is not int
            or not 1 <= render.resolution_percentage <= 100
        ):
            errors.append("Render resolution percentage must be an integer from 1 to 100.")
        fps_value = float(render.fps) / max(float(render.fps_base), 1e-9)
        if not math.isfinite(fps_value) or fps_value <= 0:
            errors.append("Render frame rate must be finite and greater than zero.")
        if scene.frame_start < 0 or scene.frame_end < scene.frame_start:
            errors.append("Render frame range is invalid.")

        camera = scene.camera
        if camera is None:
            errors.append("No active camera is configured.")
        elif camera.type != "CAMERA":
            errors.append("The active scene camera is not a camera object.")
        else:
            camera_data = camera.data
            if camera.hide_render:
                errors.append("The active camera is hidden from rendering.")
            if (
                not math.isfinite(float(camera_data.clip_start))
                or not math.isfinite(float(camera_data.clip_end))
                or camera_data.clip_start <= 0
                or camera_data.clip_end <= camera_data.clip_start
            ):
                errors.append("Camera clipping range is invalid; require 0 < clip_start < clip_end.")
            if camera_data.type == "ORTHO":
                if not math.isfinite(float(camera_data.ortho_scale)) or camera_data.ortho_scale <= 0:
                    errors.append("Orthographic camera scale must be finite and greater than zero.")
            elif not math.isfinite(float(camera_data.lens)) or camera_data.lens <= 0:
                errors.append("Perspective camera lens must be finite and greater than zero.")

        geometry = [
            obj for obj in scene.objects
            if obj.type in {"MESH", "CURVE", "FONT"} and not obj.hide_render
        ]
        renderable_geometry = [
            obj for obj in geometry
            if obj.type != "MESH" or len(getattr(obj.data, "polygons", ())) > 0
        ]
        if not renderable_geometry:
            errors.append("The scene contains no visible renderable geometry.")

        visible_lights = [
            obj for obj in scene.objects if obj.type == "LIGHT" and not obj.hide_render
        ]
        if not visible_lights:
            warnings.append("No visible lights are configured; the scene may render dark.")
        for light in visible_lights:
            energy = float(light.data.energy)
            color = tuple(float(channel) for channel in light.data.color)
            if not math.isfinite(energy) or energy <= 0:
                errors.append(f"Light '{light.name}' energy must be finite and greater than zero.")
            if len(color) != 3 or not all(math.isfinite(channel) and 0 <= channel <= 1 for channel in color):
                errors.append(f"Light '{light.name}' color must contain finite RGB channels in [0, 1].")

        registered_objects = [
            item._object for item in self._objects.values()
        ]
        for item in self._objects.values():
            if not item.visible:
                warnings.append(f"Object '{item.id}' is hidden.")
        for obj in scene.objects:
            if obj in registered_objects or not hasattr(obj, "matrix_world"):
                continue
            try:
                matrix_values = [
                    float(value)
                    for row in obj.matrix_world
                    for value in row
                ]
            except (ReferenceError, TypeError, ValueError):
                errors.append(f"Object '{obj.name}' has an invalid transform matrix.")
            else:
                if not all(math.isfinite(value) for value in matrix_values):
                    errors.append(f"Object '{obj.name}' has a non-finite world transform.")

        registered_heroes = [
            item._object for item in self._objects.values() if item.role == "hero"
        ]
        native_heroes = []
        for obj in scene.objects:
            if obj in registered_heroes:
                continue
            get_property = getattr(obj, "get", None)
            if get_property is not None and get_property("blentopy_role") == "hero":
                native_heroes.append(obj)
        heroes = registered_heroes + native_heroes
        if not heroes:
            warnings.append("No object has role='hero' (set hero['blentopy_role'] = 'hero' for native bpy objects).")
        elif camera is not None and camera.type == "CAMERA":
            try:
                from bpy_extras.object_utils import world_to_camera_view

                depsgraph = self._backend._bpy.context.evaluated_depsgraph_get()
                visible_hero = False
                for hero in heroes:
                    evaluated = hero.evaluated_get(depsgraph)
                    points = [
                        evaluated.matrix_world @ self._backend._Vector(corner)
                        for corner in evaluated.bound_box
                    ]
                    projected = [
                        world_to_camera_view(scene, camera, point)
                        for point in points
                    ]
                    if any(
                        0 <= point.x <= 1 and 0 <= point.y <= 1 and point.z > 0
                        for point in projected
                    ):
                        visible_hero = True
                        break
                if not visible_hero:
                    warnings.append("The hero object may be outside the active camera frame.")
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError):
                warnings.append("Hero framing could not be verified automatically.")

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "object_count": len(scene.objects),
            "registered_object_count": len(self._objects),
            "resource_usage": usage,
            "resource_limits": limits,
            "render_settings": {
                "resolution": [render.resolution_x, render.resolution_y],
                "resolution_percentage": render.resolution_percentage,
                "fps": fps_value,
                "frame_start": scene.frame_start,
                "frame_end": scene.frame_end,
            },
            "camera": camera.name if camera is not None else None,
            "visible_light_count": len(visible_lights),
        }
