"""High-level Blender scene API, imported only inside Blender."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

Color = Sequence[float]
Vector3 = Sequence[float]


class Studio:
    """Compact scene API for constrained AI-authored Blender projects."""

    __slots__ = (
        "_bpy", "_Vector", "_workspace", "_output_path", "_blend_path",
        "_width", "_height", "_fps", "_audio_strips", "scene",
        "output_scene", "_sequence_editor", "_scene_strip",
    )

    def __init__(
        self, *, workspace: str, output_path: str, blend_path: str,
        width: int, height: int, fps: int, duration_seconds: int,
    ) -> None:
        import bpy
        from mathutils import Vector

        self._bpy = bpy
        self._Vector = Vector
        self._workspace = Path(workspace).expanduser().resolve()
        self._output_path = Path(output_path).expanduser().resolve()
        self._blend_path = Path(blend_path).expanduser().resolve()
        self._width, self._height, self._fps = width, height, fps
        self._audio_strips: dict[str, object] = {}

        self._workspace.mkdir(parents=True, exist_ok=True)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._blend_path.parent.mkdir(parents=True, exist_ok=True)

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
        try:
            self.scene.view_settings.view_transform = "AgX"
        except (AttributeError, TypeError):
            pass

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
        # Set the content and output frame ranges before creating the scene strip.
        self.set_timeline(duration_seconds, fps)
        self._scene_strip = self._new_scene_strip()

        self.set_world_color((0.025, 0.03, 0.05))

    def _choose_render_engine(self) -> str:
        for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
            try:
                self._bpy.context.scene.render.engine = engine
                return engine
            except (TypeError, ValueError):
                continue
        raise RuntimeError("No supported Blender render engine was found.")

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
        values = tuple(float(value) for value in color)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("Color channels must be between 0 and 1.")
        return values if len(values) == 4 else (*values, 1.0)

    def _material(
        self, name: str, color: Color, metallic: float = 0.0, roughness: float = 0.45
    ):
        rgba = self._rgba(color)
        material = self._bpy.data.materials.new(name=f"{name} Material")
        material.diffuse_color = rgba
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        if shader:
            shader.inputs["Base Color"].default_value = rgba
            shader.inputs["Metallic"].default_value = min(max(metallic, 0), 1)
            shader.inputs["Roughness"].default_value = min(max(roughness, 0), 1)
        return material

    def _object(self, name: str):
        obj = self._bpy.data.objects.get(name)
        if obj is None:
            raise ValueError(f"Object not found: {name}")
        return obj


    def _active_object(self):
        """Return the active object without relying on Context.object."""
        view_layer = self._bpy.context.view_layer
        obj = view_layer.objects.active
        if obj is None:
            raise RuntimeError(
                "Blender did not make the newly created object active. "
                "Check the active scene and view layer."
            )
        return obj

    def set_timeline(self, duration_seconds: float, fps: int | None = None) -> None:
        if not 0 < duration_seconds <= 120:
            raise ValueError("duration_seconds must be > 0 and <= 120.")
        if fps is not None:
            if not 1 <= fps <= 60:
                raise ValueError("fps must be between 1 and 60.")
            self._fps = int(fps)
        frame_end = self.scene.frame_start + round(duration_seconds * self._fps) - 1
        self.scene.frame_end = frame_end
        self.scene.render.fps = self._fps
        self.output_scene.frame_start = self.scene.frame_start
        self.output_scene.frame_end = frame_end
        self.output_scene.render.fps = self._fps

    def set_world_color(self, color: Color) -> None:
        rgba = self._rgba(color)
        world = self.scene.world
        if world is None:
            world = self._bpy.data.worlds.new("Blentopy World")
            self.scene.world = world
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        if background:
            background.inputs["Color"].default_value = rgba

    def add_plane(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (5, 5, 1), color: Color = (0.08, 0.10, 0.14),
    ) -> str:
        self._bpy.ops.mesh.primitive_plane_add(size=1, location=location)
        obj = self._active_object()
        obj.name, obj.scale = name, tuple(scale)
        obj.data.materials.append(self._material(name, color))
        return obj.name

    def add_cube(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.15, 0.45, 0.9),
        metallic: float = 0.15, roughness: float = 0.35,
    ) -> str:
        self._bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        obj = self._active_object()
        obj.name, obj.scale = name, tuple(scale)
        obj.data.materials.append(self._material(name, color, metallic, roughness))
        return obj.name

    def add_uv_sphere(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.1, 0.65, 0.85),
    ) -> str:
        self._bpy.ops.mesh.primitive_uv_sphere_add(
            segments=48, ring_count=24, location=location
        )
        obj = self._active_object()
        obj.name, obj.scale = name, tuple(scale)
        obj.data.materials.append(self._material(name, color))
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        return obj.name

    def add_cylinder(
        self, name: str, location: Vector3 = (0, 0, 0),
        scale: Vector3 = (1, 1, 1), color: Color = (0.12, 0.16, 0.23),
        vertices: int = 64,
    ) -> str:
        self._bpy.ops.mesh.primitive_cylinder_add(
            vertices=max(12, min(int(vertices), 128)), radius=1,
            depth=1, location=location,
        )
        obj = self._active_object()
        obj.name, obj.scale = name, tuple(scale)
        obj.data.materials.append(self._material(name, color, 0.35, 0.3))
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        return obj.name

    def add_text(
        self, name: str, body: str, location: Vector3 = (0, 0, 0),
        size: float = 0.5, color: Color = (0.95, 0.97, 1),
        rotation: Vector3 = (1.57079632679, 0, 0),
        align: str = "CENTER", extrude: float = 0,
    ) -> str:
        curve = self._bpy.data.curves.new(name=f"{name} Font", type="FONT")
        curve.body = str(body)
        curve.size = float(size)
        curve.align_x = align if align in {"LEFT", "CENTER", "RIGHT"} else "CENTER"
        curve.extrude = max(0, float(extrude))
        obj = self._bpy.data.objects.new(name, curve)
        self.scene.collection.objects.link(obj)
        obj.location = tuple(location)
        obj.rotation_euler = tuple(rotation)
        obj.data.materials.append(self._material(name, color))
        return obj.name

    def add_camera(
        self, name: str, location: Vector3 = (0, -12, 4),
        target: Vector3 = (0, 0, 0), lens: float = 50,
        orthographic_scale: float | None = None,
    ) -> str:
        data = self._bpy.data.cameras.new(f"{name} Data")
        camera = self._bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(camera)
        camera.location = tuple(location)
        direction = self._Vector(target) - camera.location
        if direction.length == 0:
            raise ValueError("Camera location and target must differ.")
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        data.lens = max(10, min(float(lens), 300))
        if orthographic_scale is not None:
            data.type = "ORTHO"
            data.ortho_scale = max(0.1, float(orthographic_scale))
        self.scene.camera = camera
        return camera.name

    def add_area_light(
        self, name: str, location: Vector3 = (4, -5, 7),
        target: Vector3 = (0, 0, 0), energy: float = 1200,
        size: float = 5, color: Color = (1, 1, 1),
    ) -> str:
        data = self._bpy.data.lights.new(f"{name} Data", type="AREA")
        data.energy = max(0, float(energy))
        data.shape = "DISK"
        data.size = max(0.1, float(size))
        data.color = self._rgba(color)[:3]
        light = self._bpy.data.objects.new(name, data)
        self.scene.collection.objects.link(light)
        light.location = tuple(location)
        direction = self._Vector(target) - light.location
        if direction.length:
            light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return light.name

    def set_active_camera(self, name: str) -> None:
        camera = self._object(name)
        if camera.type != "CAMERA":
            raise ValueError(f"Object is not a camera: {name}")
        self.scene.camera = camera

    def animate_location(
        self, name: str, start_location: Vector3, end_location: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
    ) -> None:
        obj = self._object(name)
        end_frame = self.scene.frame_end if end_frame is None else int(end_frame)
        obj.location = tuple(start_location)
        obj.keyframe_insert(data_path="location", frame=int(start_frame))
        obj.location = tuple(end_location)
        obj.keyframe_insert(data_path="location", frame=end_frame)

    def animate_rotation(
        self, name: str, start_degrees: Vector3, end_degrees: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
    ) -> None:
        from math import radians

        obj = self._object(name)
        end_frame = self.scene.frame_end if end_frame is None else int(end_frame)
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = tuple(radians(float(v)) for v in start_degrees)
        obj.keyframe_insert(data_path="rotation_euler", frame=int(start_frame))
        obj.rotation_euler = tuple(radians(float(v)) for v in end_degrees)
        obj.keyframe_insert(data_path="rotation_euler", frame=end_frame)

    def animate_scale(
        self, name: str, start_scale: Vector3, end_scale: Vector3,
        start_frame: int = 1, end_frame: int | None = None,
    ) -> None:
        obj = self._object(name)
        end_frame = self.scene.frame_end if end_frame is None else int(end_frame)
        obj.scale = tuple(start_scale)
        obj.keyframe_insert(data_path="scale", frame=int(start_frame))
        obj.scale = tuple(end_scale)
        obj.keyframe_insert(data_path="scale", frame=end_frame)

    def add_audio(
        self, name: str, filepath: str, channel: int = 2,
        start_seconds: float = 0, volume: float = 1,
    ) -> str:
        """Add an existing audio file from inside the workspace to the output VSE."""
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
            name=name, filepath=str(resolved), channel=max(2, int(channel)),
            frame_start=self.scene.frame_start + round(float(start_seconds) * self._fps),
        )
        strip.volume = min(max(float(volume), 0), 1)
        self._audio_strips[name] = strip
        return name

    def fade_audio(
        self, name: str, start_volume: float, end_volume: float,
        start_frame: int, end_frame: int,
    ) -> None:
        strip = self._audio_strips.get(name)
        if strip is None:
            raise ValueError(f"Audio strip not found: {name}")
        strip.volume = min(max(float(start_volume), 0), 1)
        strip.keyframe_insert(data_path="volume", frame=int(start_frame))
        strip.volume = min(max(float(end_volume), 0), 1)
        strip.keyframe_insert(data_path="volume", frame=int(end_frame))

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
        render.ffmpeg.constant_rate_factor = "MEDIUM"
        render.ffmpeg.ffmpeg_preset = "GOOD"
        render.use_file_extension = True
        render.use_sequencer = True
        render.filepath = str(self._output_path.with_suffix(""))

        self.scene.frame_set(self.scene.frame_start)
        self.output_scene.frame_set(self.output_scene.frame_start)
        self._bpy.ops.wm.save_as_mainfile(filepath=str(self._blend_path))
        self._bpy.ops.render.render(animation=True, scene=self.output_scene.name)

        if not self._output_path.exists():
            alternate = Path(f"{self._output_path}.mp4")
            if alternate.exists():
                return alternate, self._blend_path
            raise RuntimeError(f"MP4 output was not created: {self._output_path}")
        return self._output_path, self._blend_path
