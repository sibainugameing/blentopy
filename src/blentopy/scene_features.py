"""Blender-native extensions for the AI-facing scene API.

All operations are invoked through SceneAPI and remain subordinate to the
blentopy CLI/worker. File operations are deliberately confined to the workspace.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any


class SceneFeatureMixin:
    """Additional production features implemented with Blender's native APIs."""

    def _workspace_path(
        self,
        filepath: str,
        *,
        must_exist: bool,
        allowed_suffixes: set[str],
        label: str,
    ) -> Path:
        if not isinstance(filepath, str) or not filepath.strip():
            raise ValueError(f"{label} filepath must be a non-empty string.")
        workspace = Path(self._backend._workspace).expanduser().resolve()
        candidate = Path(filepath).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            candidate = candidate.resolve(strict=must_exist)
            candidate.relative_to(workspace)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"{label} files must remain inside the blentopy workspace: {workspace}"
            ) from exc
        if candidate.suffix.lower() not in allowed_suffixes:
            expected = ", ".join(sorted(allowed_suffixes))
            raise ValueError(f"Unsupported {label} extension '{candidate.suffix}'. Use: {expected}.")
        if must_exist and not candidate.is_file():
            raise ValueError(f"{label} filepath must point to an existing regular file: {candidate}")
        return candidate

    def configure_render(
        self,
        engine: str = "eevee",
        samples: int = 64,
        resolution_percent: int = 100,
        transparent: bool = False,
        motion_blur: bool = False,
        color_transform: str = "AgX",
    ) -> dict[str, Any]:
        """Configure the active scene's render engine and quality settings."""
        if engine not in {"eevee", "cycles"}:
            raise ValueError("engine must be 'eevee' or 'cycles'.")
        if type(samples) is not int or not 1 <= samples <= 4096:
            raise ValueError("samples must be an integer between 1 and 4096.")
        if type(resolution_percent) is not int or not 1 <= resolution_percent <= 100:
            raise ValueError("resolution_percent must be an integer between 1 and 100.")
        if type(transparent) is not bool or type(motion_blur) is not bool:
            raise TypeError("transparent and motion_blur must be booleans.")
        if not isinstance(color_transform, str) or not color_transform.strip():
            raise ValueError("color_transform must be a non-empty string.")

        scene = self._backend.scene
        render = scene.render
        if engine == "cycles":
            render.engine = "CYCLES"
            cycles = getattr(scene, "cycles", None)
            if cycles is None or not hasattr(cycles, "samples"):
                raise RuntimeError("This Blender installation does not expose Cycles sample settings.")
            cycles.samples = samples
        else:
            selected_engine = None
            for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
                try:
                    render.engine = candidate
                    selected_engine = candidate
                    break
                except (TypeError, ValueError):
                    continue
            if selected_engine is None:
                raise RuntimeError("This Blender installation does not expose an Eevee render engine.")
            eevee = getattr(scene, "eevee", None)
            if eevee is not None:
                for setting in ("taa_render_samples", "taa_samples"):
                    if hasattr(eevee, setting):
                        setattr(eevee, setting, samples)
                        break

        render.resolution_percentage = resolution_percent
        render.film_transparent = transparent
        if hasattr(render, "use_motion_blur"):
            render.use_motion_blur = motion_blur
        elif motion_blur:
            raise RuntimeError("Motion blur is not supported by this Blender render configuration.")
        try:
            scene.view_settings.view_transform = color_transform
        except (AttributeError, TypeError, ValueError) as exc:
            available = []
            try:
                available = [
                    item.identifier
                    for item in scene.view_settings.bl_rna.properties["view_transform"].enum_items
                ]
            except (AttributeError, KeyError, TypeError, ValueError):
                pass
            raise ValueError(
                f"Unsupported color transform '{color_transform}'. Available: {available or 'unknown'}."
            ) from exc

        return {
            "engine": render.engine,
            "samples": samples,
            "resolution_percent": render.resolution_percentage,
            "transparent": bool(render.film_transparent),
            "motion_blur": bool(getattr(render, "use_motion_blur", False)),
            "color_transform": scene.view_settings.view_transform,
        }

    def environment(
        self,
        filepath: str,
        strength: float = 1.0,
        rotation: float = 0.0,
    ) -> str:
        """Load a workspace-local HDR/EXR environment map into the world shader."""
        for label, value in (("strength", strength), ("rotation", rotation)):
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError(f"{label} must be a finite number.")
        if strength < 0 or strength > 100:
            raise ValueError("strength must be between 0 and 100.")
        if abs(rotation) > math.tau * 1000:
            raise ValueError("rotation magnitude is outside the supported range.")
        path = self._workspace_path(
            filepath, must_exist=True, allowed_suffixes={".hdr", ".exr"}, label="Environment map"
        )
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("Environment maps must not exceed 128 MiB.")

        bpy = self._backend._bpy
        image = bpy.data.images.load(str(path), check_existing=True)
        width, height = (int(value) for value in image.size)
        if width <= 0 or height <= 0 or max(width, height) > 16384:
            if image.users == 0:
                bpy.data.images.remove(image)
            raise ValueError("Environment maps must have dimensions from 1x1 up to 16384x16384.")
        image.pack()

        world = self._backend.scene.world
        if world is None:
            world = bpy.data.worlds.new("Blentopy Environment")
            self._backend.scene.world = world
        world.use_nodes = True
        nodes = world.node_tree.nodes
        links = world.node_tree.links
        output = nodes.get("World Output") or nodes.new("ShaderNodeOutputWorld")
        background = nodes.get("Background") or nodes.new("ShaderNodeBackground")
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.label = "Blentopy Environment Coordinates"
        mapping = nodes.new("ShaderNodeMapping")
        mapping.label = "Blentopy Environment Rotation"
        mapping.inputs["Rotation"].default_value = (0.0, 0.0, float(rotation))
        texture = nodes.new("ShaderNodeTexEnvironment")
        texture.label = "Blentopy HDR Environment"
        texture.image = image
        coordinate_output = texcoord.outputs.get("Generated") or texcoord.outputs.get("Normal")
        if coordinate_output is None:
            raise RuntimeError("Blender did not expose a world direction output for the environment map.")
        links.new(coordinate_output, mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
        links.new(texture.outputs["Color"], background.inputs["Color"])
        background.inputs["Strength"].default_value = float(strength)
        surface = output.inputs.get("Surface")
        if surface is None:
            raise RuntimeError("Blender World Output node has no Surface input.")
        for link in list(links):
            if link.to_node == output and link.to_socket == surface:
                links.remove(link)
        links.new(background.outputs["Background"], surface)
        return str(path)

    def post_process(
        self,
        bloom: float = 0.0,
        lens_distortion: float = 0.0,
        exposure: float = 0.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
    ) -> dict[str, Any]:
        """Build a labelled compositor chain for common screen-space effects."""
        values = {
            "bloom": (bloom, 0.0, 1.0),
            "lens_distortion": (lens_distortion, -0.5, 0.5),
            "exposure": (exposure, -10.0, 10.0),
            "contrast": (contrast, 0.0, 2.0),
            "saturation": (saturation, 0.0, 2.0),
        }
        for label, (value, low, high) in values.items():
            if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{label} must be finite and between {low} and {high}.")

        scene = self._backend.scene
        scene.use_nodes = True
        tree = scene.node_tree
        nodes = tree.nodes
        links = tree.links
        for node in list(nodes):
            try:
                if node.get("blentopy_feature") == "post_process":
                    nodes.remove(node)
            except (AttributeError, ReferenceError, TypeError):
                continue

        render_layers = next((node for node in nodes if node.type == "R_LAYERS"), None)
        if render_layers is None:
            render_layers = nodes.new("CompositorNodeRLayers")
        composite = next((node for node in nodes if node.type == "COMPOSITE"), None)
        if composite is None:
            composite = nodes.new("CompositorNodeComposite")
        image_input = composite.inputs.get("Image")
        image_output = render_layers.outputs.get("Image")
        if image_input is None or image_output is None:
            raise RuntimeError("Blender compositor does not expose the expected Image sockets.")
        for link in list(links):
            if link.to_node == composite and link.to_socket == image_input:
                links.remove(link)

        active_socket = image_output
        created: list[str] = []

        def mark(node, label: str):
            node.label = f"blentopy · {label}"
            node["blentopy_feature"] = "post_process"
            created.append(label)
            return node

        if exposure != 0:
            node = mark(nodes.new("CompositorNodeExposure"), "Exposure")
            node.inputs["Exposure"].default_value = float(exposure)
            links.new(active_socket, node.inputs["Image"])
            active_socket = node.outputs["Image"]
        if contrast != 1.0:
            node = mark(nodes.new("CompositorNodeBrightContrast"), "Contrast")
            node.inputs["Contrast"].default_value = (float(contrast) - 1.0) * 100.0
            links.new(active_socket, node.inputs["Image"])
            active_socket = node.outputs["Image"]
        if saturation != 1.0:
            node = mark(nodes.new("CompositorNodeHueSat"), "Saturation")
            node.inputs["Saturation"].default_value = float(saturation)
            links.new(active_socket, node.inputs["Image"])
            active_socket = node.outputs["Image"]
        if bloom > 0:
            node = mark(nodes.new("CompositorNodeGlare"), "Bloom")
            if hasattr(node, "glare_type"):
                node.glare_type = "FOG_GLOW"
            if hasattr(node, "quality"):
                node.quality = "HIGH"
            if "Threshold" in node.inputs:
                node.inputs["Threshold"].default_value = 2.0 - float(bloom) * 1.5
            if "Size" in node.inputs:
                node.inputs["Size"].default_value = 8
            if "Mix" in node.inputs:
                node.inputs["Mix"].default_value = min(0.75, float(bloom) * 1.5 - 0.75)
            links.new(active_socket, node.inputs["Image"])
            active_socket = node.outputs["Image"]
        if lens_distortion != 0:
            node = mark(nodes.new("CompositorNodeLensdist"), "Lens Distortion")
            node.inputs["Distortion"].default_value = float(lens_distortion)
            links.new(active_socket, node.inputs["Image"])
            active_socket = node.outputs["Image"]
        links.new(active_socket, image_input)
        return {"enabled_effects": created, "compositor_nodes": len(created)}

    def camera_dof(
        self,
        camera: Any,
        focus: Any = None,
        focus_distance: float = 10.0,
        f_stop: float = 2.8,
        enabled: bool = True,
    ) -> None:
        """Configure camera depth of field with an object target or fixed distance."""
        camera_handle = self._resolve(camera)
        if camera_handle.kind != "camera":
            raise ValueError("camera_dof expects a camera object.")
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean.")
        if type(f_stop) not in {int, float} or not math.isfinite(f_stop) or not 0.1 <= f_stop <= 128:
            raise ValueError("f_stop must be finite and between 0.1 and 128.")
        if type(focus_distance) not in {int, float} or not math.isfinite(focus_distance) or focus_distance <= 0:
            raise ValueError("focus_distance must be finite and greater than zero.")
        dof = camera_handle._object.data.dof
        dof.use_dof = enabled
        dof.aperture_fstop = float(f_stop)
        if focus is not None:
            dof.focus_object = self._resolve(focus)._object
        else:
            dof.focus_object = None
            dof.focus_distance = float(focus_distance)

    def set_visibility(
        self,
        target: Any,
        viewport: bool | None = None,
        render: bool | None = None,
    ) -> None:
        """Set viewport and render visibility independently."""
        if viewport is None and render is None:
            raise ValueError("set_visibility requires viewport and/or render.")
        if viewport is not None and type(viewport) is not bool:
            raise TypeError("viewport visibility must be a boolean.")
        if render is not None and type(render) is not bool:
            raise TypeError("render visibility must be a boolean.")
        obj = self._resolve(target)._object
        if viewport is not None:
            obj.hide_viewport = not viewport
        if render is not None:
            obj.hide_render = not render

    def import_model(
        self,
        filepath: str,
        format: str = "auto",
        id_prefix: str = "imported",
        role: str = "imported",
    ) -> list[Any]:
        """Import a workspace model file and register each created object."""
        allowed = {".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply", ".usd", ".usdz"}
        path = self._workspace_path(
            filepath, must_exist=True, allowed_suffixes=allowed, label="Model import"
        )
        if not isinstance(format, str) or not format.strip():
            raise ValueError("format must be 'auto' or a supported model format.")
        resolved_format = path.suffix.lower().lstrip(".") if format == "auto" else format.lower()
        aliases = {"gltf": "gltf", "glb": "gltf", "obj": "obj", "fbx": "fbx",
                   "stl": "stl", "ply": "ply", "usd": "usd", "usdz": "usd"}
        if resolved_format not in aliases:
            raise ValueError(f"Unsupported model import format: {format}.")
        if not isinstance(id_prefix, str) or not id_prefix.strip() or len(id_prefix) > 64:
            raise ValueError("id_prefix must be a non-empty string of at most 64 characters.")
        if not isinstance(role, str) or len(role) > 64:
            raise ValueError("role must be a string of at most 64 characters.")
        prefix = id_prefix.strip().replace(" ", "_")
        before = set(self._backend.scene.objects)
        operator_sets = {
            "gltf": (("import_scene", "gltf", {}),),
            "obj": (("wm", "obj_import", {}), ("import_scene", "obj", {})),
            "fbx": (("import_scene", "fbx", {}),),
            "stl": (("wm", "stl_import", {}), ("import_mesh", "stl", {})),
            "ply": (("wm", "ply_import", {}), ("import_mesh", "ply", {})),
            "usd": (("wm", "usd_import", {}),),
        }
        self._run_file_operator(operator_sets[aliases[resolved_format]], path)
        imported = [obj for obj in self._backend.scene.objects if obj not in before]
        if not imported:
            raise RuntimeError(
                f"Blender's {resolved_format.upper()} importer completed but created no objects. "
                "Check whether the file contains supported scene data."
            )
        bpy = self._backend._bpy
        try:
            from .resource_limits import scene_resource_usage

            usage = scene_resource_usage(self._backend.scene)
            limits = {"objects": 1000, "polygons": 300_000, "modifiers": 1500}
            exceeded = [
                f"{key}={usage[key]:,} (limit {limit:,})"
                for key, limit in limits.items()
                if usage.get(key, 0) > limit
            ]
            if exceeded:
                raise RuntimeError("Imported model exceeds scene resource limits: " + ", ".join(exceeded))
            kind_by_type = {
                "MESH": "mesh", "CURVE": "curve", "FONT": "text", "EMPTY": "group",
                "CAMERA": "camera", "LIGHT": "light", "ARMATURE": "armature",
            }
            handles = []
            for index, object_ref in enumerate(imported, start=1):
                object_id = f"{prefix}.{index:04d}"
                while object_id in self._objects:
                    object_id = self._allocate_id(prefix)
                kind = kind_by_type.get(object_ref.type, object_ref.type.lower())
                handle = self._register(object_id, object_ref, kind, role or None)
                if object_ref == self._backend.scene.camera:
                    self._camera = handle
                handles.append(handle)
            return handles
        except Exception:
            for object_ref in imported:
                try:
                    bpy.data.objects.remove(object_ref, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass
            raise

    def export_model(
        self,
        filepath: str,
        format: str = "auto",
        selected_only: bool = False,
    ) -> str:
        """Export the scene to an interchange format inside the workspace."""
        if type(selected_only) is not bool:
            raise TypeError("selected_only must be a boolean.")
        suffixes = {".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply", ".usd"}
        path = self._workspace_path(
            filepath, must_exist=False, allowed_suffixes=suffixes, label="Model export"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if not isinstance(format, str) or not format.strip():
            raise ValueError("format must be 'auto' or a supported model format.")
        resolved_format = path.suffix.lower().lstrip(".") if format == "auto" else format.lower()
        if resolved_format not in {"glb", "gltf", "obj", "fbx", "stl", "ply", "usd"}:
            raise ValueError(f"Unsupported model export format: {format}.")
        if selected_only and not self._backend._bpy.context.selected_objects:
            raise ValueError("selected_only=True requires at least one selected object.")
        if path.exists():
            raise FileExistsError(
                f"Export destination already exists; refusing to overwrite it: {path}. "
                "Choose a new filename or move the existing file first."
            )

        option_sets = {
            "glb": (("export_scene", "gltf", {"export_format": "GLB", "use_selection": selected_only}),),
            "gltf": (("export_scene", "gltf", {"export_format": "GLTF_SEPARATE", "use_selection": selected_only}),),
            "obj": (("wm", "obj_export", {"export_selected_objects": selected_only}),
                    ("export_scene", "obj", {"use_selection": selected_only})),
            "fbx": (("export_scene", "fbx", {"use_selection": selected_only, "apply_unit_scale": True}),),
            "stl": (("wm", "stl_export", {"export_selected_objects": selected_only}),
                    ("export_mesh", "stl", {"use_selection": selected_only})),
            "ply": (("wm", "ply_export", {"export_selected_objects": selected_only}),
                    ("export_mesh", "ply", {"use_selection": selected_only})),
            "usd": (("wm", "usd_export", {"selected_objects_only": selected_only}),),
        }
        self._run_file_operator(option_sets[resolved_format], path)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(
                f"Blender's {resolved_format.upper()} exporter did not create a non-empty file at {path}."
            )
        return str(path)

    def _run_file_operator(self, candidates, path: Path) -> None:
        bpy = self._backend._bpy
        failures: list[str] = []
        for namespace, name, options in candidates:
            group = getattr(bpy.ops, namespace, None)
            operator = getattr(group, name, None) if group is not None else None
            if operator is None:
                failures.append(f"{namespace}.{name} is unavailable")
                continue
            try:
                result = operator(filepath=str(path), **options)
            except TypeError as exc:
                failures.append(f"{namespace}.{name}: {exc}")
                continue
            except Exception as exc:
                raise RuntimeError(
                    f"Blender {namespace}.{name} failed for '{path}': {type(exc).__name__}: {exc}"
                ) from exc
            if isinstance(result, set) and "FINISHED" not in result:
                failures.append(f"{namespace}.{name} returned {sorted(result)}")
                continue
            return
        raise RuntimeError(
            f"No compatible Blender file operator succeeded for '{path}'. "
            + "; ".join(failures)
        )


def build_geometry_mesh(kind: str, values: dict[str, Any]):
    """Build bounded parametric mesh data for additional primitives."""
    if kind == "ring":
        segments = values["segments"]
        inner = values["inner_radius"]
        outer = values["outer_radius"]
        vertices = []
        for radius in (inner, outer):
            for index in range(segments):
                angle = math.tau * index / segments
                vertices.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))
        faces = [
            (index, segments + index, segments + (index + 1) % segments, (index + 1) % segments)
            for index in range(segments)
        ]
        return vertices, faces

    if kind == "capsule":
        radius = values["radius"]
        height = values["height"]
        radial_segments = values["radial_segments"]
        cap_segments = values["cap_segments"]
        straight_half = max(0.0, (height - 2.0 * radius) * 0.5)
        rows: list[list[tuple[float, float, float]]] = [[(0.0, 0.0, -height * 0.5)]]
        for index in range(1, cap_segments + 1):
            angle = -math.pi * 0.5 + (math.pi * 0.5) * index / cap_segments
            row_radius = radius * math.cos(angle)
            z = -straight_half + radius * math.sin(angle)
            rows.append([
                (row_radius * math.cos(math.tau * part / radial_segments),
                 row_radius * math.sin(math.tau * part / radial_segments), z)
                for part in range(radial_segments)
            ])
        if straight_half > 1e-9:
            rows.append([
                (radius * math.cos(math.tau * part / radial_segments),
                 radius * math.sin(math.tau * part / radial_segments), straight_half)
                for part in range(radial_segments)
            ])
        for index in range(1, cap_segments):
            angle = math.pi * 0.5 * index / cap_segments
            row_radius = radius * math.cos(angle)
            z = straight_half + radius * math.sin(angle)
            rows.append([
                (row_radius * math.cos(math.tau * part / radial_segments),
                 row_radius * math.sin(math.tau * part / radial_segments), z)
                for part in range(radial_segments)
            ])
        rows.append([(0.0, 0.0, height * 0.5)])
        vertices = [vertex for row in rows for vertex in row]
        offsets = []
        total = 0
        for row in rows:
            offsets.append(total)
            total += len(row)
        faces = []
        for row_index in range(len(rows) - 1):
            lower = rows[row_index]
            upper = rows[row_index + 1]
            lower_start = offsets[row_index]
            upper_start = offsets[row_index + 1]
            if len(lower) == 1:
                faces.extend(
                    (lower_start, upper_start + next_index, upper_start + index)
                    for index in range(radial_segments)
                    for next_index in ((index + 1) % radial_segments,)
                )
            elif len(upper) == 1:
                faces.extend(
                    (lower_start + index, lower_start + (index + 1) % radial_segments, upper_start)
                    for index in range(radial_segments)
                )
            else:
                faces.extend(
                    (lower_start + index,
                     lower_start + (index + 1) % radial_segments,
                     upper_start + (index + 1) % radial_segments,
                     upper_start + index)
                    for index in range(radial_segments)
                )
        return vertices, faces

    if kind == "torus_knot":
        radius = values["radius"]
        tube = values["tube"]
        tubular_segments = values["tubular_segments"]
        radial_segments = values["radial_segments"]
        p = values["p"]
        q = values["q"]

        def center(t):
            phase = q * t
            ring_radius = radius * (1.0 + 0.35 * math.cos(phase))
            return (
                ring_radius * math.cos(p * t),
                ring_radius * math.sin(p * t),
                radius * 0.35 * math.sin(phase),
            )

        vertices = []
        epsilon = 1e-4
        for index in range(tubular_segments):
            t = math.tau * index / tubular_segments
            point = center(t)
            before = center(t - epsilon)
            after = center(t + epsilon)
            tangent = tuple(after[axis] - before[axis] for axis in range(3))
            tangent_length = math.sqrt(sum(part * part for part in tangent)) or 1.0
            tangent = tuple(part / tangent_length for part in tangent)
            reference = (0.0, 0.0, 1.0)
            normal = (
                tangent[1] * reference[2] - tangent[2] * reference[1],
                tangent[2] * reference[0] - tangent[0] * reference[2],
                tangent[0] * reference[1] - tangent[1] * reference[0],
            )
            normal_length = math.sqrt(sum(part * part for part in normal))
            if normal_length < 1e-8:
                reference = (1.0, 0.0, 0.0)
                normal = (
                    tangent[1] * reference[2] - tangent[2] * reference[1],
                    tangent[2] * reference[0] - tangent[0] * reference[2],
                    tangent[0] * reference[1] - tangent[1] * reference[0],
                )
                normal_length = math.sqrt(sum(part * part for part in normal)) or 1.0
            normal = tuple(part / normal_length for part in normal)
            binormal = (
                tangent[1] * normal[2] - tangent[2] * normal[1],
                tangent[2] * normal[0] - tangent[0] * normal[2],
                tangent[0] * normal[1] - tangent[1] * normal[0],
            )
            for radial_index in range(radial_segments):
                angle = math.tau * radial_index / radial_segments
                offset = tuple(
                    tube * (math.cos(angle) * normal[axis] + math.sin(angle) * binormal[axis])
                    for axis in range(3)
                )
                vertices.append(tuple(point[axis] + offset[axis] for axis in range(3)))
        faces = []
        for index in range(tubular_segments):
            next_index = (index + 1) % tubular_segments
            for radial_index in range(radial_segments):
                next_radial = (radial_index + 1) % radial_segments
                a = index * radial_segments + radial_index
                b = next_index * radial_segments + radial_index
                c = next_index * radial_segments + next_radial
                d = index * radial_segments + next_radial
                faces.append((a, d, c, b))
        return vertices, faces

    raise ValueError(f"Unsupported parametric geometry kind: {kind}")
