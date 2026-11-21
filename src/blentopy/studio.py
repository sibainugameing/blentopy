"""High-level Blender scene API, imported only inside Blender."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from .resource_limits import ensure_scene_capacity

Color = Sequence[float]
Vector3 = Sequence[float]

_ALLOWED_INTERPOLATIONS = frozenset({"BEZIER", "LINEAR", "CONSTANT"})

def _normalize_rendered_mp4(output_path: Path) -> Path:
    """Find Blender's FFmpeg output, including version-specific frame-range suffixes."""
    output_path = Path(output_path)
    candidates = {output_path, Path(f"{output_path}.mp4")}
    try:
        candidates.update(
            path for path in output_path.parent.glob(f"{output_path.stem}*.mp4")
            if path.is_file()
        )
    except OSError:
        pass

    valid: list[Path] = []
    invalid: list[str] = []
    for candidate in sorted(candidates, key=lambda item: str(item)):
        if not candidate.is_file():
            continue
        try:
            with candidate.open("rb") as stream:
                header = stream.read(12)
        except OSError as exc:
            invalid.append(f"{candidate.name}: {exc}")
            continue
        if len(header) >= 12 and header[4:8] == b"ftyp":
            valid.append(candidate)
        else:
            invalid.append(f"{candidate.name}: missing MP4 ftyp header")

    if len(valid) > 1:
        raise RuntimeError(
            "Blender produced multiple candidate MP4 files for one render: "
            + ", ".join(path.name for path in valid)
        )
    if not valid:
        try:
            nearby = sorted(
                path.name for path in output_path.parent.iterdir()
                if path.name.startswith(output_path.stem)
            )[:20]
        except OSError as exc:
            nearby = [f"<cannot list output directory: {exc}>"]
        details = "; ".join(invalid) if invalid else "no candidate MP4 files found"
        raise RuntimeError(
            f"MP4 output was not created at '{output_path}'. "
            f"Blender FFmpeg may append a frame-range suffix. "
            f"Nearby files: {nearby}. Candidate diagnostics: {details}."
        )

    actual = valid[0]
    if actual != output_path:
        if output_path.exists():
            raise RuntimeError(
                f"Cannot normalize Blender MP4 output '{actual}' because destination "
                f"already exists: '{output_path}'."
            )
        actual.replace(output_path)
    return output_path



class Studio:
    """High-level scene API for constrained AI-authored Blender projects."""

    __slots__ = (
        "_bpy", "_Vector", "_workspace", "_output_path", "_blend_path",
        "_width", "_height", "_fps", "_duration", "_audio_strips", "scene",
        "output_scene", "_sequence_editor", "_scene_strip",
    )

    def __init__(
        self, *, workspace: str, output_path: str, blend_path: str,
        width: int, height: int, fps: int, duration_seconds: int,
        existing_project_path: str | Path | None = None,
    ) -> None:
        import bpy
        from mathutils import Vector

        self._bpy = bpy
        self._Vector = Vector
        self._workspace = Path(workspace).expanduser().resolve()
        self._output_path = Path(output_path).expanduser().resolve()
        self._blend_path = Path(blend_path).expanduser().resolve()
        self._width, self._height, self._fps = width, height, fps
        self._duration = float(duration_seconds)
        self._audio_strips: dict[str, object] = {}

        self._workspace.mkdir(parents=True, exist_ok=True)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._blend_path.parent.mkdir(parents=True, exist_ok=True)

        if existing_project_path is not None:
            self._load_existing_project(Path(existing_project_path).expanduser().resolve(strict=True))
            return

        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.name = "Blentopy Content"
        self.scene.frame_start = 1
        self.scene.render.engine = self._choose_render_engine()
        self.scene.render.resolution_x = width
        self.scene.render.resolution_y = height
        self.scene.render.resolution_percentage = 100
        self.scene.render.fps = fps
        self.scene.render.fps_base = 1.0
        self.scene.render.image_settings.color_mode = "RGB"
        self.scene.render.film_transparent = False
        self._configure_render_defaults()

        self.output_scene = bpy.data.scenes.new("Blentopy Output")
        self.output_scene.frame_start = 1
        self.output_scene.frame_end = fps * duration_seconds
        self.output_scene.render.engine = self.scene.render.engine
        self.output_scene.render.resolution_x = width
        self.output_scene.render.resolution_y = height
        self.output_scene.render.resolution_percentage = 100
        self.output_scene.render.fps = fps
        self.output_scene.render.fps_base = 1.0
        self._sequence_editor = self.output_scene.sequence_editor_create()
        self.set_timeline(duration_seconds, fps)
        self._scene_strip = self._new_scene_strip()
        self.set_world_color((0.025, 0.03, 0.05), strength=0.35)

    def _load_existing_project(self, project_path: Path) -> None:
        """Load an existing .blend while preserving its editable scene."""
        if project_path.suffix.lower() != ".blend" or not project_path.is_file():
            raise ValueError(f"Existing project must be a readable .blend file: {project_path}")
        self._bpy.ops.wm.open_mainfile(filepath=str(project_path))
        self.scene = self._bpy.data.scenes.get("Blentopy Content") or self._bpy.context.scene
        if self.scene is None:
            raise RuntimeError("The Blender project does not contain an active scene.")

        self.output_scene = self._bpy.data.scenes.get("Blentopy Output")
        self._width = int(self.scene.render.resolution_x)
        self._height = int(self.scene.render.resolution_y)
        self._fps = int(round(self.scene.render.fps / max(self.scene.render.fps_base, 1e-6)))
        self._fps = max(1, min(60, self._fps))
        self._duration = max(
            1.0,
            (self.scene.frame_end - self.scene.frame_start + 1) / self._fps,
        )

        if self.output_scene is None:
            self.output_scene = self._bpy.data.scenes.new("Blentopy Output")
            self.output_scene.render.engine = self.scene.render.engine
            self.output_scene.render.resolution_x = self._width
            self.output_scene.render.resolution_y = self._height
            self.output_scene.render.resolution_percentage = self.scene.render.resolution_percentage
            self.output_scene.render.fps = self.scene.render.fps
            self.output_scene.render.fps_base = self.scene.render.fps_base

        self._sequence_editor = self.output_scene.sequence_editor
        if self._sequence_editor is None:
            self._sequence_editor = self.output_scene.sequence_editor_create()
        strips = getattr(self._sequence_editor, "strips", None)
        if strips is None:
            strips = getattr(self._sequence_editor, "sequences", None)
        self._scene_strip = next(
            (strip for strip in strips if getattr(strip, "scene", None) == self.scene),
            None,
        ) if strips is not None else None
        if self._scene_strip is None:
            self._scene_strip = self._new_scene_strip()

        self._restore_audio_strips()
        if self._bpy.context.window is not None:
            self._bpy.context.window.scene = self.scene

    def _check_scene_capacity(
        self,
        *,
        objects: int = 0,
        polygons: int = 0,
        modifiers: int = 0,
    ) -> None:
        ensure_scene_capacity(
            self.scene,
            added_objects=objects,
            added_polygons=polygons,
            added_modifiers=modifiers,
        )

    def _choose_render_engine(self) -> str:
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
            try:
                self._bpy.context.scene.render.engine = engine
                return engine
            except (TypeError, ValueError):
                continue
        raise RuntimeError("No supported Blender render engine was found.")

    def _configure_render_defaults(self) -> None:
        """Use a clean display transform and a practical Eevee sample count."""
        view = self.scene.view_settings
        try:
            view.view_transform = "AgX"
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            available = {
                item.identifier
                for item in view.bl_rna.properties["look"].enum_items
            }
            for look in ("AgX - Medium High Contrast", "AgX - High Contrast"):
                if look in available:
                    view.look = look
                    break
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

        eevee = getattr(self.scene, "eevee", None)
        if eevee is not None:
            if hasattr(eevee, "taa_render_samples"):
                eevee.taa_render_samples = 64
            if hasattr(eevee, "taa_samples"):
                eevee.taa_samples = 32

    def _new_scene_strip(self):
        collection = getattr(self._sequence_editor, "strips", None)
        if collection is not None and hasattr(collection, "new_scene"):
            return collection.new_scene(
                name="3D Scene", scene=self.scene, channel=1,
                frame_start=self.scene.frame_start,
            )
        collection = getattr(self._sequence_editor, "sequences", None)
        if collection is not None and hasattr(collection, "new_scene"):
            return collection.new_scene(
                name="3D Scene", scene=self.scene, channel=1,
                frame_start=self.scene.frame_start,
            )
        raise RuntimeError("This Blender version does not expose a supported VSE scene-strip API.")

    @staticmethod
    def _rgba(color: Color) -> tuple[float, float, float, float]:
        if len(color) not in (3, 4):
            raise ValueError("Color must contain RGB or RGBA values.")
        if any(type(value) not in {int, float} for value in color):
            raise TypeError("Color channels must be integers or floats.")
        values = tuple(float(value) for value in color)
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in values):
            raise ValueError("Color channels must be finite values between 0 and 1.")
        return values if len(values) == 4 else (*values, 1.0)

    @staticmethod
    def _finite_scalar(value: float, label: str) -> float:
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError(f"{label} must be a finite number.")
        return float(value)

    @staticmethod
    def _vector3(value: Vector3, label: str) -> tuple[float, float, float]:
        if isinstance(value, (str, bytes)):
            raise TypeError(f"{label} must be a three-number sequence.")
        try:
            parts = tuple(value)
        except TypeError as exc:
            raise TypeError(f"{label} must be a three-number sequence.") from exc
        if len(parts) != 3 or any(type(part) not in {int, float} for part in parts):
            raise ValueError(f"{label} must contain exactly three numeric components.")
        result = tuple(float(part) for part in parts)
        if not all(math.isfinite(part) for part in result):
            raise ValueError(f"{label} components must be finite.")
        return result

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        number = Studio._finite_scalar(value, "Value")
        return min(max(number, low), high)

    def _restore_audio_strips(self) -> None:
        """Rebuild name-to-strip references after opening an existing .blend."""
        self._audio_strips = {}
        collection = getattr(self._sequence_editor, "strips", None)
        if collection is None:
            collection = getattr(self._sequence_editor, "sequences", None)
        if collection is None:
            return
        for strip in collection:
            if getattr(strip, "type", None) == "SOUND" or getattr(strip, "sound", None) is not None:
                self._audio_strips[str(strip.name)] = strip

    def _material(
        self, name: str, color: Color, metallic: float = 0.0,
        roughness: float = 0.45, emission_color: Color | None = None,
        emission_strength: float = 0.0, coat: float = 0.0,
    ):
        rgba = self._rgba(color)
        material = self._bpy.data.materials.new(name=f"{name} Material")
        material.diffuse_color = rgba
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        if shader:
            shader.inputs["Base Color"].default_value = rgba
            shader.inputs["Metallic"].default_value = self._clamp(metallic, 0, 1)
            shader.inputs["Roughness"].default_value = self._clamp(roughness, 0.02, 1)
            coat_socket = shader.inputs.get("Coat Weight") or shader.inputs.get("Clearcoat")
            if coat_socket is not None:
                coat_socket.default_value = self._clamp(coat, 0, 1)
            if emission_color is not None:
                emission = self._rgba(emission_color)
                emission_socket = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
                if emission_socket is not None:
                    emission_socket.default_value = emission
                strength_socket = shader.inputs.get("Emission Strength")
                if strength_socket is not None:
                    strength_socket.default_value = max(0, float(emission_strength))
        return material

    def _object(self, name: str):
        obj = self._bpy.data.objects.get(name)
        if obj is None:
            raise ValueError(f"Object not found: {name}")
        return obj

    def _active_object(self):
        view_layer = self._bpy.context.view_layer
        obj = view_layer.objects.active
        if obj is None:
            raise RuntimeError("Blender did not make the newly created object active.")
        return obj

    def _finish_mesh(
        self, name: str, location: Vector3, scale: Vector3, color: Color,
        metallic: float, roughness: float, rotation: Vector3 = (0, 0, 0),
        smooth: bool = False, bevel: float = 0, bevel_segments: int = 3,
        emission_color: Color | None = None, emission_strength: float = 0,
        coat: float = 0,
    ) -> str:
        obj = self._active_object()
        obj.name = name
        obj.location = self._vector3(location, "location")
        obj.scale = self._vector3(scale, "scale")
        obj.rotation_euler = self._vector3(rotation, "rotation")
        obj.data.materials.append(self._material(
            name, color, metallic, roughness, emission_color, emission_strength, coat
        ))
        if smooth:
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
        if float(bevel) > 0:
            modifier = obj.modifiers.new(name="Soft Edge Bevel", type="BEVEL")
            modifier.width = max(0.0, float(bevel))
            modifier.segments = max(1, min(int(bevel_segments), 8))
            modifier.limit_method = "ANGLE"
            normal = obj.modifiers.new(name="Weighted Corner Normals", type="WEIGHTED_NORMAL")
            if hasattr(normal, "keep_sharp"):
                normal.keep_sharp = True
        return obj.name

    def set_timeline(self, duration_seconds: float, fps: int | None = None) -> None:
        duration_seconds = self._finite_scalar(duration_seconds, "duration_seconds")
        if not 0 < duration_seconds <= 120:
            raise ValueError("duration_seconds must be > 0 and <= 120.")
        if fps is not None:
            if type(fps) is not int or not 1 <= fps <= 60:
                raise ValueError("fps must be an integer between 1 and 60.")
            self._fps = fps
        frame_end = self.scene.frame_start + round(duration_seconds * self._fps) - 1
        self.scene.frame_end = frame_end
        self.scene.render.fps = self._fps
        self.output_scene.frame_start = self.scene.frame_start
        self.output_scene.frame_end = frame_end
        self.output_scene.render.fps = self._fps

    def set_world_color(self, color: Color, strength: float = 0.35) -> None:
        rgba = self._rgba(color)
        world = self.scene.world
        if world is None:
            world = self._bpy.data.worlds.new("Blentopy World")
            self.scene.world = world
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = rgba
            background.inputs["Strength"].default_value = max(0, float(strength))

    def add_plane(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (5, 5, 1), color: Color = (0.08, 0.10, 0.14),
        roughness: float = 0.8,
    ) -> str:
        self._check_scene_capacity(objects=1, polygons=1)
        self._bpy.ops.mesh.primitive_plane_add(size=1, location=location)
        return self._finish_mesh(name, location, scale, color, 0, roughness)

    def add_cube(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.15, 0.45, 0.9),
        metallic: float = 0.15, roughness: float = 0.35,
        bevel: float = 0.04, bevel_segments: int = 3,
        emission_color: Color | None = None, emission_strength: float = 0,
        coat: float = 0,
    ) -> str:
        self._check_scene_capacity(
            objects=1,
            polygons=6 * (1 + 2 * 3) if bevel > 0 else 6,
            modifiers=2 if bevel > 0 else 0,
        )
        self._bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        return self._finish_mesh(
            name, location, scale, color, metallic, roughness,
            bevel=bevel, bevel_segments=bevel_segments,
            emission_color=emission_color, emission_strength=emission_strength, coat=coat,
        )

    def add_uv_sphere(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.1, 0.65, 0.85),
        segments: int = 64, ring_count: int = 32,
        metallic: float = 0, roughness: float = 0.35,
        emission_color: Color | None = None, emission_strength: float = 0,
        coat: float = 0,
    ) -> str:
        segments = max(16, min(int(segments), 128))
        rings = max(8, min(int(ring_count), 64))
        self._check_scene_capacity(
            objects=1, polygons=segments * max(1, rings - 1) * 2
        )
        self._bpy.ops.mesh.primitive_uv_sphere_add(
            segments=segments, ring_count=rings, location=location,
        )
        return self._finish_mesh(
            name, location, scale, color, metallic, roughness, smooth=True,
            emission_color=emission_color, emission_strength=emission_strength, coat=coat,
        )

    def add_ico_sphere(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.1, 0.65, 0.85),
        subdivisions: int = 3, metallic: float = 0, roughness: float = 0.4,
        emission_color: Color | None = None, emission_strength: float = 0,
    ) -> str:
        subdivisions = max(1, min(int(subdivisions), 6))
        self._check_scene_capacity(
            objects=1, polygons=20 * (4 ** subdivisions)
        )
        self._bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=subdivisions, radius=1, location=location,
        )
        return self._finish_mesh(
            name, location, scale, color, metallic, roughness,
            emission_color=emission_color, emission_strength=emission_strength,
        )

    def add_cylinder(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.12, 0.16, 0.23),
        vertices: int = 64, metallic: float = 0.1, roughness: float = 0.35,
        bevel: float = 0.025, bevel_segments: int = 3,
    ) -> str:
        vertices = max(12, min(int(vertices), 128))
        bevel_modifiers = 2 if bevel > 0 else 0
        self._check_scene_capacity(
            objects=1,
            polygons=(vertices + 2) * (1 + 2 * max(1, bevel_segments)) if bevel_modifiers else vertices + 2,
            modifiers=bevel_modifiers,
        )
        self._bpy.ops.mesh.primitive_cylinder_add(
            vertices=vertices, radius=1, depth=1, location=location,
        )
        return self._finish_mesh(
            name, location, scale, color, metallic, roughness, smooth=True,
            bevel=bevel, bevel_segments=bevel_segments,
        )

    def add_cone(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.18, 0.5, 0.3),
        radius1: float = 1, radius2: float = 0, depth: float = 2,
        vertices: int = 48, bevel: float = 0.015,
        metallic: float = 0, roughness: float = 0.55,
    ) -> str:
        vertices = max(12, min(int(vertices), 128))
        bevel_modifiers = 2 if bevel > 0 else 0
        self._check_scene_capacity(
            objects=1,
            polygons=(vertices + 1) * (1 + 2 * 2) if bevel_modifiers else vertices + 1,
            modifiers=bevel_modifiers,
        )
        self._bpy.ops.mesh.primitive_cone_add(
            vertices=vertices,
            radius1=max(0, float(radius1)), radius2=max(0, float(radius2)),
            depth=max(0.01, float(depth)), location=location,
        )
        return self._finish_mesh(
            name, location, scale, color, metallic, roughness, smooth=True,
            bevel=bevel, bevel_segments=2,
        )

    def add_torus(
        self, name: str, location: Vector3 = (0, 0, 0),
        rotation: Vector3 = (0, 0, 0), scale: Vector3 = (1, 1, 1),
        color: Color = (0.1, 0.65, 0.85), major_radius: float = 1,
        minor_radius: float = 0.2, major_segments: int = 64,
        minor_segments: int = 16, metallic: float = 0.35,
        roughness: float = 0.25, emission_color: Color | None = None,
        emission_strength: float = 0, coat: float = 0.2,
    ) -> str:
        major_segments = max(12, min(int(major_segments), 128))
        minor_segments = max(6, min(int(minor_segments), 64))
        self._check_scene_capacity(
            objects=1, polygons=major_segments * minor_segments
        )
        self._bpy.ops.mesh.primitive_torus_add(
            major_segments=major_segments,
            minor_segments=minor_segments,
            major_radius=max(0.01, float(major_radius)),
            minor_radius=max(0.005, min(float(minor_radius), float(major_radius) * 0.95)),
            location=location, rotation=rotation,
        )
        return self._finish_mesh(
            name, location, scale, color, metallic, roughness,
            rotation=rotation, smooth=True,
            emission_color=emission_color, emission_strength=emission_strength, coat=coat,
        )

    def add_text(
        self, name: str, body: str, location: Vector3 = (0, 0, 0),
        size: float = 0.5, color: Color = (0.95, 0.97, 1),
        rotation: Vector3 = (1.57079632679, 0, 0),
        align: str = "CENTER", extrude: float = 0,
        emission_color: Color | None = None, emission_strength: float = 0,
    ) -> str:
        self._check_scene_capacity(objects=1)
        curve = self._bpy.data.curves.new(name=f"{name} Font", type="FONT")
        curve.body = str(body)
        curve.size = float(size)
        curve.align_x = align if align in {"LEFT", "CENTER", "RIGHT"} else "CENTER"
        curve.extrude = max(0, float(extrude))
        obj = self._bpy.data.objects.new(name, curve)
        self.scene.collection.objects.link(obj)
        obj.location = tuple(location)
        obj.rotation_euler = tuple(rotation)
        obj.data.materials.append(self._material(
            name, color, emission_color=emission_color,
            emission_strength=emission_strength,
        ))
        return obj.name

    def _camera_rotation(self, location: Vector3, target: Vector3):
        direction = self._Vector(target) - self._Vector(location)
        if direction.length == 0:
            raise ValueError("Camera location and target must differ.")
        return direction.to_track_quat("-Z", "Y").to_euler()

    def add_camera(
        self, name: str, location: Vector3 = (0, -12, 4),
        target: Vector3 = (0, 0, 0), lens: float = 50,
        orthographic_scale: float | None = None,
        focus_object_name: str | None = None, dof_fstop: float = 2.8,
    ) -> str:
        self._check_scene_capacity(objects=1)
        data = self._bpy.data.cameras.new(f"{name} Data")
        camera = self._bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(camera)
        camera.location = tuple(location)
        camera.rotation_euler = self._camera_rotation(location, target)
        data.lens = max(10, min(float(lens), 300))
        if orthographic_scale is not None:
            data.type = "ORTHO"
            data.ortho_scale = max(0.1, float(orthographic_scale))
        elif focus_object_name is not None:
            data.dof.use_dof = True
            data.dof.focus_object = self._object(focus_object_name)
            data.dof.aperture_fstop = max(0.1, float(dof_fstop))
        self.scene.camera = camera
        return camera.name

    def set_active_camera(self, name: str) -> None:
        camera = self._object(name)
        if camera.type != "CAMERA":
            raise ValueError(f"Object is not a camera: {name}")
        self.scene.camera = camera

    def add_area_light(
        self, name: str, location: Vector3 = (4, -5, 7),
        target: Vector3 = (0, 0, 0), energy: float = 1200,
        size: float = 5, color: Color = (1, 1, 1),
        shape: str = "DISK", size_y: float = 5,
    ) -> str:
        self._check_scene_capacity(objects=1)
        data = self._bpy.data.lights.new(f"{name} Data", type="AREA")
        data.energy = max(0, float(energy))
        supported_shapes = {"DISK", "SQUARE", "RECTANGLE", "ELLIPSE"}
        data.shape = shape if shape in supported_shapes else "DISK"
        data.size = max(0.1, float(size))
        if data.shape in {"RECTANGLE", "ELLIPSE"} and hasattr(data, "size_y"):
            data.size_y = max(0.1, float(size_y))
        data.color = self._rgba(color)[:3]
        light = self._bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(light)
        light.location = tuple(location)
        direction = self._Vector(target) - light.location
        if direction.length:
            light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return light.name

    def add_sun_light(
        self, name: str, rotation: Vector3 = (0.5, -0.5, -0.5),
        energy: float = 2.0, color: Color = (1, 0.92, 0.78),
        angle: float = 0.08,
    ) -> str:
        self._check_scene_capacity(objects=1)
        data = self._bpy.data.lights.new(f"{name} Data", type="SUN")
        data.energy = max(0, float(energy))
        data.color = self._rgba(color)[:3]
        data.angle = max(0, float(angle))
        light = self._bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(light)
        light.rotation_euler = tuple(rotation)
        return light.name

    def _animation_frames(self, start_frame: int, end_frame: int | None) -> tuple[int, int]:
        if type(start_frame) is not int or (end_frame is not None and type(end_frame) is not int):
            raise TypeError("Animation start_frame and end_frame must be integers.")
        start = start_frame
        end = self.scene.frame_end if end_frame is None else end_frame
        if start < self.scene.frame_start or end > self.scene.frame_end or end <= start:
            raise ValueError(
                f"Animation frames must satisfy {self.scene.frame_start} <= start < end <= {self.scene.frame_end}."
            )
        return start, end

    @staticmethod
    def _set_interpolation(obj, interpolation: str, data_paths: tuple[str, ...]) -> None:
        if interpolation not in _ALLOWED_INTERPOLATIONS:
            raise ValueError("interpolation must be BEZIER, LINEAR, or CONSTANT.")
        action = getattr(getattr(obj, "animation_data", None), "action", None)
        curves = getattr(action, "fcurves", None)
        if curves is None:
            return
        for curve in curves:
            if curve.data_path not in data_paths:
                continue
            for point in curve.keyframe_points:
                point.interpolation = interpolation
                if interpolation == "BEZIER":
                    point.handle_left_type = "AUTO_CLAMPED"
                    point.handle_right_type = "AUTO_CLAMPED"

    def animate_location(
        self, name: str, start_location: Vector3, end_location: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
        interpolation: str = "BEZIER",
    ) -> None:
        obj = self._object(name)
        start, end = self._animation_frames(start_frame, end_frame)
        obj.location = self._vector3(start_location, "start_location")
        obj.keyframe_insert(data_path="location", frame=start)
        obj.location = self._vector3(end_location, "end_location")
        obj.keyframe_insert(data_path="location", frame=end)
        self._set_interpolation(obj, interpolation, ("location",))

    def animate_rotation(
        self, name: str, start_degrees: Vector3, end_degrees: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
        interpolation: str = "BEZIER",
    ) -> None:
        from math import radians

        obj = self._object(name)
        start, end = self._animation_frames(start_frame, end_frame)
        obj.rotation_mode = "XYZ"
        start_values = self._vector3(start_degrees, "start_degrees")
        end_values = self._vector3(end_degrees, "end_degrees")
        obj.rotation_euler = tuple(radians(value) for value in start_values)
        obj.keyframe_insert(data_path="rotation_euler", frame=start)
        obj.rotation_euler = tuple(radians(value) for value in end_values)
        obj.keyframe_insert(data_path="rotation_euler", frame=end)
        self._set_interpolation(obj, interpolation, ("rotation_euler",))

    def animate_scale(
        self, name: str, start_scale: Vector3, end_scale: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
        interpolation: str = "BEZIER",
    ) -> None:
        obj = self._object(name)
        start, end = self._animation_frames(start_frame, end_frame)
        obj.scale = self._vector3(start_scale, "start_scale")
        obj.keyframe_insert(data_path="scale", frame=start)
        obj.scale = self._vector3(end_scale, "end_scale")
        obj.keyframe_insert(data_path="scale", frame=end)
        self._set_interpolation(obj, interpolation, ("scale",))

    def animate_camera(
        self, name: str, start_location: Vector3, end_location: Vector3,
        start_target: Vector3, end_target: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
        interpolation: str = "BEZIER",
    ) -> None:
        camera = self._object(name)
        if camera.type != "CAMERA":
            raise ValueError(f"Object is not a camera: {name}")
        start, end = self._animation_frames(start_frame, end_frame)
        camera.rotation_mode = "XYZ"
        start_position = self._vector3(start_location, "start_location")
        end_position = self._vector3(end_location, "end_location")
        start_look_at = self._vector3(start_target, "start_target")
        end_look_at = self._vector3(end_target, "end_target")
        camera.location = start_position
        camera.rotation_euler = self._camera_rotation(start_position, start_look_at)
        camera.keyframe_insert(data_path="location", frame=start)
        camera.keyframe_insert(data_path="rotation_euler", frame=start)
        camera.location = end_position
        camera.rotation_euler = self._camera_rotation(end_position, end_look_at)
        camera.keyframe_insert(data_path="location", frame=end)
        camera.keyframe_insert(data_path="rotation_euler", frame=end)
        self._set_interpolation(camera, interpolation, ("location", "rotation_euler"))

    def add_audio(
        self, name: str, filepath: str, channel: int = 2,
        start_seconds: float = 0, volume: float = 1,
    ) -> str:
        """Add an existing audio file from inside the workspace to the output VSE."""
        if not isinstance(name, str) or not name.strip() or len(name) > 96:
            raise ValueError("Audio name must be a non-empty string of at most 96 characters.")
        if name in self._audio_strips:
            raise ValueError(f"An audio strip named '{name}' already exists.")
        if not isinstance(filepath, str) or not filepath.strip():
            raise ValueError("filepath must be a non-empty path string.")
        if type(channel) is not int or not 2 <= channel <= 128:
            raise ValueError("Audio channel must be an integer between 2 and 128.")
        start_seconds = self._finite_scalar(start_seconds, "start_seconds")
        if not 0 <= start_seconds < self._duration:
            raise ValueError(f"start_seconds must be in [0, {self._duration}).")
        volume = self._finite_scalar(volume, "volume")
        if not 0 <= volume <= 1:
            raise ValueError("Audio volume must be between 0 and 1.")
        candidate = Path(filepath).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace / candidate
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(self._workspace)
        except ValueError as exc:
            raise ValueError("Audio files must be inside the blentopy workspace.") from exc
        if not resolved.is_file():
            raise ValueError(f"Audio file does not exist: {resolved}")

        collection = getattr(self._sequence_editor, "strips", None)
        if collection is None or not hasattr(collection, "new_sound"):
            collection = getattr(self._sequence_editor, "sequences", None)
        if collection is None or not hasattr(collection, "new_sound"):
            raise RuntimeError("This Blender version has no supported VSE sound API.")
        strip = collection.new_sound(
            name=name, filepath=str(resolved), channel=channel,
            frame_start=self.output_scene.frame_start + round(start_seconds * self._fps),
        )
        strip.volume = volume
        self._audio_strips[name] = strip
        return name

    def fade_audio(
        self, name: str, start_volume: float, end_volume: float,
        start_frame: int, end_frame: int,
    ) -> None:
        strip = self._audio_strips.get(name)
        if strip is None:
            raise ValueError(f"Audio strip not found: {name}")
        if type(start_frame) is not int or type(end_frame) is not int:
            raise TypeError("Audio fade frames must be integers.")
        if (
            start_frame < self.output_scene.frame_start
            or end_frame > self.output_scene.frame_end
            or end_frame <= start_frame
        ):
            raise ValueError(
                "Audio fade frames must satisfy output_scene.frame_start <= start < end <= output_scene.frame_end."
            )
        start_value = self._finite_scalar(start_volume, "start_volume")
        end_value = self._finite_scalar(end_volume, "end_volume")
        if not 0 <= start_value <= 1 or not 0 <= end_value <= 1:
            raise ValueError("Audio fade volumes must be between 0 and 1.")
        strip.volume = start_value
        strip.keyframe_insert(data_path="volume", frame=start_frame)
        strip.volume = end_value
        strip.keyframe_insert(data_path="volume", frame=end_frame)

    def render(self) -> tuple[Path, Path]:
        """Save the editable project and render the VSE composition to MP4."""
        content_render = self.scene.render
        content_render.engine = self._choose_render_engine()
        content_render.resolution_x = self._width
        content_render.resolution_y = self._height
        content_render.resolution_percentage = 100
        content_render.fps = self._fps
        content_render.use_sequencer = False

        render = self.output_scene.render
        render.engine = content_render.engine
        render.resolution_x = self._width
        render.resolution_y = self._height
        render.resolution_percentage = 100
        render.fps = self._fps
        render.fps_base = 1
        render.image_settings.file_format = "FFMPEG"
        render.ffmpeg.format = "MPEG4"
        render.ffmpeg.codec = "H264"
        render.ffmpeg.audio_codec = "AAC"
        render.ffmpeg.constant_rate_factor = "HIGH"
        render.ffmpeg.ffmpeg_preset = "GOOD"
        render.use_file_extension = True
        render.use_sequencer = True
        render.filepath = str(self._output_path.with_suffix(""))

        self.scene.frame_set(self.scene.frame_start)
        self.output_scene.frame_set(self.output_scene.frame_start)

        print("BLENTOPY_STAGE=saving_project", flush=True)
        self._bpy.ops.wm.save_as_mainfile(filepath=str(self._blend_path))

        print("BLENTOPY_STAGE=rendering", flush=True)
        render_write_handlers = getattr(self._bpy.app.handlers, "render_write", None)
        total_output_frames = max(
            1, int(self.output_scene.frame_end) - int(self.output_scene.frame_start) + 1
        )
        print(f"BLENTOPY_PROGRESS=0/{total_output_frames}", flush=True)

        def report_rendered_frame(scene, *_args):
            total_frames = max(1, int(scene.frame_end) - int(scene.frame_start) + 1)
            completed_frames = int(scene.frame_current) - int(scene.frame_start) + 1
            completed_frames = max(0, min(completed_frames, total_frames))
            print(
                f"BLENTOPY_PROGRESS={completed_frames}/{total_frames}",
                flush=True,
            )

        if render_write_handlers is not None:
            render_write_handlers.append(report_rendered_frame)
        try:
            self._bpy.ops.render.render(animation=True, scene=self.output_scene.name)
        finally:
            if render_write_handlers is not None and report_rendered_frame in render_write_handlers:
                render_write_handlers.remove(report_rendered_frame)

        ffmpeg_available = bool(getattr(self._bpy.app.build_options, "ffmpeg", False))
        try:
            _normalize_rendered_mp4(self._output_path)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc} Blender build FFmpeg support: {ffmpeg_available}. "
                f"Configured format: {render.image_settings.file_format}; "
                f"container: {render.ffmpeg.format}; codec: {render.ffmpeg.codec}; "
                f"render filepath: {render.filepath}."
            ) from exc
        return self._output_path, self._blend_path
