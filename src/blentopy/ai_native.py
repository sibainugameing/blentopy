"""AI-facing scene API composed from focused implementation modules."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from .resource_limits import ensure_scene_capacity, estimate_object_polygons, modifier_polygon_delta
from .scene_features import SceneFeatureMixin, build_geometry_mesh
from .scene_types import (
    GeometryFactory, GeometrySpec, MaterialFactory, MaterialSpec, MotionAPI,
    MotionTrack, Object3D, VectorProxy, _color, _identifier, _vector3,
    _normalize_bone_definitions,
)
from .scene_modeling import SceneModelingMixin
from .scene_spatial import SceneSpatialMixin
from .scene_rigging import SceneRiggingMixin
from .scene_visuals import SceneVisualMixin
from .scene_diagnostics import SceneDiagnosticsMixin

class SceneAPI(
    SceneFeatureMixin,
    SceneModelingMixin,
    SceneSpatialMixin,
    SceneRiggingMixin,
    SceneVisualMixin,
    SceneDiagnosticsMixin,
):
    """Stable public facade; specialized operations live in focused mixins."""

    __slots__ = ("_owner", "_objects", "_camera", "_duration", "_fps", "_materials", "_counters")

    def __init__(self, owner: AIStudio, *, duration: float = 8, fps: int = 30) -> None:
        self._owner = owner
        self._objects: dict[str, Object3D] = {}
        self._camera: Object3D | None = None
        self._duration = float(duration)
        self._fps = int(fps)
        self._materials: dict[tuple[Any, ...], Any] = {}
        self._counters: dict[str, int] = {}
        self._adopt_existing_objects()

    def _adopt_existing_objects(self) -> None:
        """Register objects loaded from a .blend so AI edits can target them."""
        backend = getattr(self._owner, "_backend", None)
        blender_scene = getattr(backend, "scene", None)
        if blender_scene is None:
            # SceneAPI is also unit-tested without an active Blender backend.
            return
        kind_by_type = {
            "MESH": "mesh", "CURVE": "curve", "FONT": "text",
            "EMPTY": "group", "CAMERA": "camera", "LIGHT": "light",
            "ARMATURE": "armature",
        }
        for object_ref in blender_scene.objects:
            kind = kind_by_type.get(object_ref.type, object_ref.type.lower())
            raw_id = object_ref.get("blentopy_id")
            object_id = str(raw_id) if raw_id else f"existing.{object_ref.name}"
            if (
                not object_id or len(object_id) > 96
                or object_id.startswith("_") or object_id in self._objects
            ):
                object_id = self._allocate_id("existing")
            raw_role = object_ref.get("blentopy_role")
            role = str(raw_role) if raw_role is not None else None
            handle = self._register(object_id, object_ref, kind, role)
            if object_ref == blender_scene.camera:
                self._camera = handle

    @property
    def _backend(self):
        return self._owner._backend

    def _ensure_capacity(
        self,
        *,
        objects: int = 0,
        polygons: int = 0,
        modifiers: int = 0,
    ) -> None:
        ensure_scene_capacity(
            self._backend.scene,
            added_objects=objects,
            added_polygons=polygons,
            added_modifiers=modifiers,
        )

    def configure(
        self,
        duration: float | None = None,
        fps: int | None = None,
        background: str | Sequence[float] = "#101522",
    ) -> None:
        # Inherit the render job's timebase unless the script explicitly overrides it.
        resolved_duration = self._duration if duration is None else duration
        resolved_fps = self._fps if fps is None else fps
        if not math.isfinite(resolved_duration) or not 0 < resolved_duration <= 120:
            raise ValueError("duration must be greater than 0 and at most 120 seconds.")
        if type(resolved_fps) is not int or not 1 <= resolved_fps <= 60:
            raise ValueError("fps must be an integer between 1 and 60.")
        if round(float(resolved_duration) * resolved_fps) < 1:
            raise ValueError("duration and fps must produce at least one frame.")
        self._duration = float(resolved_duration)
        self._fps = resolved_fps
        self._backend.set_timeline(self._duration, self._fps)
        self._backend.set_world_color(_color(background), strength=0.35)

    def _allocate_id(self, prefix: str) -> str:
        """Generate a deterministic ID for incidental repeated objects."""
        counter = self._counters.get(prefix, 0)
        while True:
            counter += 1
            candidate = f"{prefix}.{counter:04d}"
            if candidate not in self._objects:
                self._counters[prefix] = counter
                return candidate

    def _register(self, object_id: str, object_ref: Any, kind: str, role: str | None) -> Object3D:
        key = _identifier(object_id)
        if key in self._objects:
            raise ValueError(f"Duplicate scene object id: {key}")
        if role is not None and (not isinstance(role, str) or len(role) > 64):
            raise ValueError("role must be a string of at most 64 characters.")
        result = Object3D(self, object_ref, key, kind, role)
        self._objects[key] = result
        object_ref["blentopy_id"] = key
        if role:
            object_ref["blentopy_role"] = role
        return result

    def _material(self, spec: MaterialSpec | None, object_id: str):
        if spec is None:
            spec = MaterialFactory.pbr()
        if not isinstance(spec, MaterialSpec) or spec.model not in {
            "pbr", "emissive", "image_texture", "noise", "physical", "toon"
        }:
            raise TypeError(
                "material must be created with studio.mat.pbr(), emissive(), "
                "image_texture(), or noise()."
            )
        key = (spec.model, *spec.values)
        cached = self._materials.get(key)
        if cached is not None:
            return cached
        values = spec.options()

        texture_path = None
        if spec.model == "image_texture":
            workspace = Path(self._backend._workspace).expanduser().resolve()
            candidate = Path(values["filepath"]).expanduser()
            candidate = candidate if candidate.is_absolute() else workspace / candidate
            try:
                texture_path = candidate.resolve(strict=True)
                texture_path.relative_to(workspace)
            except (OSError, ValueError) as exc:
                raise ValueError(
                    "Image textures must be existing files inside the blentopy workspace."
                ) from exc
            if not texture_path.is_file():
                raise ValueError("Image texture path must point to a regular file.")
            if texture_path.suffix.lower() not in {
                ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".exr", ".hdr", ".webp"
            }:
                raise ValueError("Image textures must use PNG, JPEG, TIFF, BMP, EXR, HDR, or WebP.")
            if texture_path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("Image texture files must not exceed 32 MiB.")

        color = values["color"]
        material = self._backend._material(
            object_id,
            color,
            metallic=values["metallic"],
            roughness=values["roughness"],
            emission_color=values["emission"],
            emission_strength=values["emission_strength"],
            coat=values["coat"],
        )
        bpy = self._backend._bpy
        nodes = material.node_tree.nodes
        shader = nodes.get("Principled BSDF")
        if shader is None:
            raise RuntimeError("The material has no Principled BSDF node.")

        if spec.model == "physical":
            sockets = {
                "transmission": ("Transmission Weight", "Transmission"),
                "ior": ("IOR",),
                "thickness": ("Thickness",),
                "alpha": ("Alpha",),
                "subsurface": ("Subsurface Weight", "Subsurface"),
                "sheen": ("Sheen Weight", "Sheen"),
                "anisotropy": ("Anisotropic IOR Level", "Anisotropic"),
            }
            for key_name, socket_names in sockets.items():
                socket = next((shader.inputs.get(name) for name in socket_names if shader.inputs.get(name) is not None), None)
                if socket is not None:
                    socket.default_value = values[key_name]

        if spec.model == "toon":
            output = next((node for node in nodes if node.type == "OUTPUT_MATERIAL"), None)
            if output is None:
                output = nodes.new("ShaderNodeOutputMaterial")
            surface = output.inputs.get("Surface")
            for link in list(material.node_tree.links):
                if link.to_node == output and link.to_socket == surface:
                    material.node_tree.links.remove(link)
            toon = nodes.new("ShaderNodeBsdfToon")
            toon.label = "Blentopy Toon Shader"
            toon.inputs["Color"].default_value = values["color"]
            toon.inputs["Size"].default_value = values["size"]
            toon.inputs["Smooth"].default_value = values["smooth"]
            material.node_tree.links.new(toon.outputs["BSDF"], surface)

        if texture_path is not None:
            image = bpy.data.images.load(str(texture_path), check_existing=True)
            width, height = (int(value) for value in image.size)
            if width <= 0 or height <= 0 or max(width, height) > 8192:
                if image.users == 0:
                    bpy.data.images.remove(image)
                raise ValueError("Image textures must have dimensions from 1x1 up to 8192x8192.")
            image.pack()
            texcoord = nodes.new("ShaderNodeTexCoord")
            texcoord.label = "Blentopy Generated Coordinates"
            texture = nodes.new("ShaderNodeTexImage")
            texture.label = "Blentopy Image Texture"
            texture.image = image
            material.node_tree.links.new(texcoord.outputs["Generated"], texture.inputs["Vector"])
            material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])

        if spec.model == "noise":
            texture = nodes.new("ShaderNodeTexNoise")
            texture.label = "Blentopy Procedural Noise"
            texture.inputs["Scale"].default_value = values["scale"]
            texture.inputs["Detail"].default_value = values["detail"]
            ramp = nodes.new("ShaderNodeValToRGB")
            ramp.label = "Blentopy Color Ramp"
            ramp.color_ramp.elements[0].color = values["color"]
            ramp.color_ramp.elements[1].color = values["color_b"]
            material.node_tree.links.new(texture.outputs["Fac"], ramp.inputs["Fac"])
            material.node_tree.links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
            if values["bump_strength"] > 0:
                bump = nodes.new("ShaderNodeBump")
                bump.label = "Blentopy Procedural Bump"
                bump.inputs["Strength"].default_value = values["bump_strength"]
                material.node_tree.links.new(texture.outputs["Fac"], bump.inputs["Height"])
                material.node_tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])

        self._materials[key] = material
        return material

    def _create_mesh_object(self, object_id: str, geometry: GeometrySpec, material: MaterialSpec | None):
        if not isinstance(geometry, GeometrySpec):
            raise TypeError("geometry must be created with studio.geo.*().")
        bpy = self._backend._bpy
        values = geometry.options()
        kind = geometry.kind
        polygon_estimates = {
            "box": 6,
            "sphere": values.get("segments", 32) * max(1, values.get("rings", 16) - 1) * 2,
            "plane": 1,
            "cylinder": values.get("segments", 32) + 2,
            "cone": values.get("segments", 32) + 1,
            "torus": values.get("major_segments", 48) * values.get("minor_segments", 12),
            "ico_sphere": 20 * (4 ** values.get("subdivisions", 2)),
            "circle": values.get("vertices", 64) if values.get("fill", True) else 0,
            "ring": values.get("segments", 64),
            "capsule": values.get("radial_segments", 32) * (2 * values.get("cap_segments", 8) + 1),
            "torus_knot": values.get("tubular_segments", 128) * values.get("radial_segments", 12),
            "custom": len(values.get("faces", ())),
        }
        estimated_polygons = polygon_estimates.get(kind)
        if estimated_polygons is None:
            raise ValueError(f"Unsupported geometry kind: {kind}")
        bevel_enabled = kind == "box" and values.get("bevel", 0) > 0
        modifier_count = 2 if bevel_enabled else 0
        if bevel_enabled:
            estimated_polygons *= 1 + 2 * 4
        self._ensure_capacity(
            objects=1, polygons=estimated_polygons, modifiers=modifier_count
        )

        if kind == "box":
            bpy.ops.mesh.primitive_cube_add(size=1)
            obj = self._backend._active_object()
            obj.scale = values["size"]
            bevel = values["bevel"]
            if bevel > 0:
                modifier = obj.modifiers.new(name="Blentopy Bevel", type="BEVEL")
                modifier.width = min(bevel, min(values["size"]) * 0.49)
                modifier.segments = 4
                modifier.limit_method = "ANGLE"
                obj.modifiers.new(name="Blentopy Weighted Normals", type="WEIGHTED_NORMAL")
        elif kind == "sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=values["segments"], ring_count=values["rings"], radius=values["radius"],
            )
            obj = self._backend._active_object()
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
        elif kind == "plane":
            bpy.ops.mesh.primitive_plane_add(size=1)
            obj = self._backend._active_object()
            obj.scale = (values["size"][0], values["size"][1], 1)
        elif kind == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=values["segments"], radius=values["radius"], depth=values["height"],
            )
            obj = self._backend._active_object()
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
        elif kind == "cone":
            bpy.ops.mesh.primitive_cone_add(
                vertices=values["segments"], radius1=values["radius"],
                radius2=0, depth=values["height"],
            )
            obj = self._backend._active_object()
        elif kind == "torus":
            bpy.ops.mesh.primitive_torus_add(
                major_segments=values["major_segments"],
                minor_segments=values["minor_segments"],
                major_radius=values["major_radius"],
                minor_radius=values["minor_radius"],
            )
            obj = self._backend._active_object()
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
        elif kind == "ico_sphere":
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=values["subdivisions"], radius=values["radius"],
            )
            obj = self._backend._active_object()
        elif kind == "circle":
            bpy.ops.mesh.primitive_circle_add(
                vertices=values["vertices"],
                radius=values["radius"],
                fill_type="NGON" if values["fill"] else "NOTHING",
            )
            obj = self._backend._active_object()
        elif kind in {"ring", "capsule", "torus_knot"}:
            vertices, faces = build_geometry_mesh(kind, values)
            mesh_data = bpy.data.meshes.new(f"{object_id} Geometry")
            mesh_data.from_pydata(vertices, [], faces)
            mesh_data.update()
            obj = bpy.data.objects.new(object_id, mesh_data)
            self._backend.scene.collection.objects.link(obj)
            if kind in {"capsule", "torus_knot"}:
                for polygon in mesh_data.polygons:
                    polygon.use_smooth = True
        elif kind == "custom":
            mesh_data = bpy.data.meshes.new(f"{object_id} Geometry")
            mesh_data.from_pydata(values["vertices"], [], values["faces"])
            mesh_data.update()
            obj = bpy.data.objects.new(object_id, mesh_data)
            self._backend.scene.collection.objects.link(obj)
        else:
            raise ValueError(f"Unsupported geometry kind: {kind}")

        obj.name = object_id
        obj.data.materials.append(self._material(material, object_id))
        return obj

    def mesh(
        self,
        id: str | GeometrySpec | None = None,
        geometry: GeometrySpec | None = None,
        material: MaterialSpec | None = None,
        role: str | None = None,
    ) -> Object3D:
        # A geometry may be supplied as the first positional argument; IDs are optional.
        if isinstance(id, GeometrySpec) and geometry is None:
            geometry = id
            id = None
        if geometry is None:
            raise TypeError("scene.mesh() requires a GeometrySpec via geometry=...")
        object_id = self._allocate_id("mesh") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        object_ref = self._create_mesh_object(object_id, geometry, material)
        return self._register(object_id, object_ref, "mesh", role)

    def surface(
        self,
        id: str | None = None,
        size: Sequence[float] = (10, 10),
        material: MaterialSpec | None = None,
        role: str | None = "environment",
    ) -> Object3D:
        object_id = self._allocate_id("surface") if id is None else _identifier(id)
        return self.mesh(object_id, GeometryFactory.plane(size), material, role)

    def group(
        self,
        id: str | None = None,
        children: Sequence[Object3D] = (),
        role: str | None = None,
    ) -> Object3D:
        object_id = self._allocate_id("group") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(objects=1)
        bpy = self._backend._bpy
        empty = bpy.data.objects.new(object_id, None)
        empty.empty_display_type = "PLAIN_AXES"
        self._backend.scene.collection.objects.link(empty)
        group_ref = self._register(object_id, empty, "group", role)
        for child in children:
            self.attach(child, group_ref)
        return group_ref

    def add(self, obj: Object3D) -> Object3D:
        self._require_object(obj)
        if obj._object.parent is not None:
            world_matrix = obj._object.matrix_world.copy()
            obj._object.parent = None
            obj._object.matrix_world = world_matrix
        return obj

    def _require_object(self, obj: Object3D) -> None:
        if not isinstance(obj, Object3D) or obj._scene is not self:
            raise TypeError("Expected an object created by this blentopy scene.")

    def _resolve(self, obj: Object3D | str) -> Object3D:
        if isinstance(obj, str):
            try:
                return self._objects[obj]
            except KeyError as exc:
                raise ValueError(f"Scene object not found: {obj}") from exc
        self._require_object(obj)
        return obj

    def update(
        self,
        target: Object3D | str,
        position: Sequence[float] | None = None,
        rotation: Sequence[float] | None = None,
        scale: Sequence[float] | None = None,
        visible: bool | None = None,
        material: MaterialSpec | None = None,
        role: str | None = None,
    ) -> Object3D:
        """Update selected properties without recreating the scene object."""
        obj = self._resolve(target)
        if position is not None:
            obj.position.set(position)
        if rotation is not None:
            obj.rotation.set(rotation)
        if scale is not None:
            values = _vector3(scale, "scale")
            if any(part <= 0 for part in values):
                raise ValueError("Scale values must be greater than zero.")
            obj.scale.set(values)
        if visible is not None:
            obj.visible = visible
        if material is not None:
            self.set_material(obj, material)
        if role is not None:
            if not isinstance(role, str) or len(role) > 64:
                raise ValueError("role must be a string of at most 64 characters.")
            obj.role = role
            obj._object["blentopy_role"] = role
        return obj

class AIStudio:
    """AI-facing entry point that retains the legacy Studio API."""

    __slots__ = ("_backend", "scene", "geo", "mat")

    def __init__(
        self,
        *,
        workspace: str,
        output_path: str,
        blend_path: str,
        width: int,
        height: int,
        fps: int,
        duration_seconds: int,
        existing_project: str | None = None,
    ) -> None:
        from .studio import Studio

        self._backend = Studio(
            workspace=workspace,
            output_path=output_path,
            blend_path=blend_path,
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration_seconds,
            existing_project_path=existing_project,
        )
        scene_duration = getattr(self._backend, "_duration", duration_seconds)
        scene_fps = getattr(self._backend, "_fps", fps)
        if not isinstance(scene_duration, (int, float)):
            scene_duration = duration_seconds
        if type(scene_fps) is not int:
            scene_fps = fps
        self.scene = SceneAPI(self, duration=float(scene_duration), fps=scene_fps)
        self.geo = GeometryFactory()
        self.mat = MaterialFactory()

    @property
    def blender_scene(self):
        """The actual Blender scene, reserved for the trusted worker."""
        return self._backend.scene

    def render(self):
        return self._backend.render()

    def __getattr__(self, name: str):
        # Backward compatibility for existing studio.add_cube() scripts.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._backend, name)
