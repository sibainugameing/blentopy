"""AI-native scene API.

This module exposes a small, composable object model to generated scene scripts.
Blender objects stay behind this facade; scene scripts receive handles and specs,
not bpy objects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


def _vector3(value: Sequence[float], label: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{label} must contain exactly three numbers.")
    result = tuple(float(part) for part in value)
    if not all(math.isfinite(part) for part in result):
        raise ValueError(f"{label} values must be finite.")
    return result  # type: ignore[return-value]


def _color(value: str | Sequence[float]) -> tuple[float, float, float, float]:
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) not in (6, 8):
            raise ValueError("Hex colors must use #RRGGBB or #RRGGBBAA.")
        try:
            channels = tuple(int(text[index:index + 2], 16) / 255 for index in range(0, len(text), 2))
        except ValueError as exc:
            raise ValueError(f"Invalid hex color: {value}") from exc
        if len(channels) == 3:
            return (*channels, 1.0)
        return channels  # type: ignore[return-value]
    if isinstance(value, (str, bytes)) or len(value) not in (3, 4):
        raise ValueError("Colors must be RGB/RGBA values or #RRGGBB hex strings.")
    channels = tuple(float(part) for part in value)
    if not all(math.isfinite(part) and 0 <= part <= 1 for part in channels):
        raise ValueError("Color channels must be finite values between 0 and 1.")
    return channels if len(channels) == 4 else (*channels, 1.0)


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Object id must be a non-empty string.")
    if len(value) > 96 or value.startswith("_"):
        raise ValueError("Object id must be at most 96 characters and may not start with '_'.")
    return value


@dataclass(frozen=True)
class GeometrySpec:
    """Serializable description of a mesh geometry."""

    kind: str
    values: tuple[tuple[str, Any], ...]

    def options(self) -> dict[str, Any]:
        return dict(self.values)


@dataclass(frozen=True)
class MaterialSpec:
    """Serializable description of a surface material."""

    model: str
    values: tuple[tuple[str, Any], ...]

    def options(self) -> dict[str, Any]:
        return dict(self.values)


class GeometryFactory:
    """Creates geometry descriptions without touching Blender."""

    @staticmethod
    def box(size: Sequence[float] = (1, 1, 1), bevel: float = 0) -> GeometrySpec:
        dimensions = _vector3(size, "size")
        if any(part <= 0 for part in dimensions):
            raise ValueError("Box dimensions must be greater than zero.")
        if not math.isfinite(bevel) or bevel < 0:
            raise ValueError("bevel must be finite and non-negative.")
        return GeometrySpec("box", (("size", dimensions), ("bevel", float(bevel))))

    @staticmethod
    def rounded_box(size: Sequence[float] = (1, 1, 1), bevel: float = 0.06) -> GeometrySpec:
        return GeometryFactory.box(size=size, bevel=bevel)

    @staticmethod
    def sphere(radius: float = 0.5, segments: int = 32, rings: int = 16) -> GeometrySpec:
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError("sphere radius must be greater than zero.")
        return GeometrySpec("sphere", (
            ("radius", float(radius)),
            ("segments", max(8, min(int(segments), 128))),
            ("rings", max(4, min(int(rings), 64))),
        ))

    @staticmethod
    def plane(size: Sequence[float] = (10, 10)) -> GeometrySpec:
        if isinstance(size, (str, bytes)) or len(size) != 2:
            raise ValueError("Plane size must contain width and depth.")
        dimensions = tuple(float(part) for part in size)
        if not all(math.isfinite(part) and part > 0 for part in dimensions):
            raise ValueError("Plane dimensions must be finite and greater than zero.")
        return GeometrySpec("plane", (("size", dimensions),))

    @staticmethod
    def cylinder(radius: float = 0.5, height: float = 1, segments: int = 32) -> GeometrySpec:
        if not all(math.isfinite(part) and part > 0 for part in (radius, height)):
            raise ValueError("Cylinder radius and height must be greater than zero.")
        return GeometrySpec("cylinder", (
            ("radius", float(radius)), ("height", float(height)),
            ("segments", max(8, min(int(segments), 128))),
        ))

    @staticmethod
    def cone(radius: float = 0.5, height: float = 1, segments: int = 32) -> GeometrySpec:
        if not all(math.isfinite(part) and part > 0 for part in (radius, height)):
            raise ValueError("Cone radius and height must be greater than zero.")
        return GeometrySpec("cone", (
            ("radius", float(radius)), ("height", float(height)),
            ("segments", max(8, min(int(segments), 128))),
        ))

    @staticmethod
    def torus(
        major_radius: float = 1,
        minor_radius: float = 0.1,
        major_segments: int = 48,
        minor_segments: int = 12,
    ) -> GeometrySpec:
        if not math.isfinite(major_radius) or major_radius <= 0:
            raise ValueError("major_radius must be greater than zero.")
        if not math.isfinite(minor_radius) or not 0 < minor_radius < major_radius:
            raise ValueError("minor_radius must be positive and smaller than major_radius.")
        return GeometrySpec("torus", (
            ("major_radius", float(major_radius)),
            ("minor_radius", float(minor_radius)),
            ("major_segments", max(12, min(int(major_segments), 128))),
            ("minor_segments", max(6, min(int(minor_segments), 64))),
        ))

    @staticmethod
    def mesh(
        vertices: Sequence[Sequence[float]],
        faces: Sequence[Sequence[int]],
    ) -> GeometrySpec:
        if not vertices or not faces or len(vertices) > 10000 or len(faces) > 20000:
            raise ValueError("Custom meshes need 1–10000 vertices and 1–20000 faces.")
        points = tuple(_vector3(vertex, "vertex") for vertex in vertices)
        polygons: list[tuple[int, ...]] = []
        for face in faces:
            if any(type(index) is not int for index in face):
                raise ValueError("Face indices must be integers.")
            indices = tuple(face)
            if len(indices) < 3 or any(index < 0 or index >= len(points) for index in indices):
                raise ValueError("Each face needs at least three valid vertex indices.")
            polygons.append(indices)
        return GeometrySpec("custom", (("vertices", points), ("faces", tuple(polygons))))


class MaterialFactory:
    """Creates reusable material descriptions."""

    @staticmethod
    def pbr(
        color: str | Sequence[float] = "#B8C4D8",
        roughness: float = 0.45,
        metallic: float = 0,
        coat: float = 0,
        emission: str | Sequence[float] | None = None,
        emission_strength: float = 0,
    ) -> MaterialSpec:
        for label, value in (("roughness", roughness), ("metallic", metallic), ("coat", coat)):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label} must be between 0 and 1.")
        if not math.isfinite(emission_strength) or emission_strength < 0:
            raise ValueError("emission_strength must be finite and non-negative.")
        values = (
            ("color", _color(color)),
            ("roughness", float(roughness)),
            ("metallic", float(metallic)),
            ("coat", float(coat)),
            ("emission", _color(emission) if emission is not None else None),
            ("emission_strength", float(emission_strength)),
        )
        return MaterialSpec("pbr", values)

    @staticmethod
    def emissive(
        color: str | Sequence[float] = "#FFFFFF",
        strength: float = 2,
    ) -> MaterialSpec:
        if not math.isfinite(strength) or strength < 0:
            raise ValueError("Emission strength must be finite and non-negative.")
        rgba = _color(color)
        return MaterialSpec("emissive", (
            ("color", rgba), ("roughness", 0.4), ("metallic", 0.0),
            ("coat", 0.0), ("emission", rgba), ("emission_strength", float(strength)),
        ))


class VectorProxy:
    """A constrained mutable view of an object's location, rotation, or scale."""

    __slots__ = ("_owner", "_attribute")

    def __init__(self, owner: Object3D, attribute: str) -> None:
        self._owner = owner
        self._attribute = attribute

    def _read(self) -> tuple[float, float, float]:
        return tuple(float(part) for part in getattr(self._owner._object, self._attribute))

    def set(
        self,
        x: float | Sequence[float],
        y: float | None = None,
        z: float | None = None,
    ) -> None:
        if y is None and z is None and not isinstance(x, (int, float)):
            value = _vector3(x, self._attribute)
        elif y is not None and z is not None:
            value = _vector3((x, y, z), self._attribute)  # type: ignore[arg-type]
        else:
            raise ValueError("VectorProxy.set expects (x, y, z) or one three-value sequence.")
        setattr(self._owner._object, self._attribute, value)

    @property
    def x(self) -> float:
        return self._read()[0]

    @x.setter
    def x(self, value: float) -> None:
        current = list(self._read())
        current[0] = float(value)
        self.set(current)

    @property
    def y(self) -> float:
        return self._read()[1]

    @y.setter
    def y(self, value: float) -> None:
        current = list(self._read())
        current[1] = float(value)
        self.set(current)

    @property
    def z(self) -> float:
        return self._read()[2]

    @z.setter
    def z(self, value: float) -> None:
        current = list(self._read())
        current[2] = float(value)
        self.set(current)


class Object3D:
    """Stable handle for a Blender object; never exposes the bpy object itself."""

    __slots__ = (
        "_scene", "_object", "id", "kind", "role",
        "position", "rotation", "scale",
    )

    def __init__(self, scene: SceneAPI, object_ref: Any, object_id: str, kind: str, role: str | None) -> None:
        self._scene = scene
        self._object = object_ref
        self.id = object_id
        self.kind = kind
        self.role = role
        self.position = VectorProxy(self, "location")
        self.rotation = VectorProxy(self, "rotation_euler")
        self.scale = VectorProxy(self, "scale")

    @property
    def visible(self) -> bool:
        return not bool(self._object.hide_render or self._object.hide_viewport)

    @visible.setter
    def visible(self, value: bool) -> None:
        self._object.hide_render = not bool(value)
        self._object.hide_viewport = not bool(value)

    def move_to(self, position: Sequence[float]) -> Object3D:
        self.position.set(position)
        return self

    def rotate_by(self, rotation: Sequence[float]) -> Object3D:
        delta = _vector3(rotation, "rotation")
        current = self.rotation._read()
        self.rotation.set(tuple(current[index] + delta[index] for index in range(3)))
        return self

    def add(self, child: Object3D) -> None:
        self._scene.attach(child, self)


class SceneAPI:
    """AI-facing scene graph and spatial operations."""

    __slots__ = ("_owner", "_objects", "_camera", "_duration", "_fps")

    def __init__(self, owner: AIStudio) -> None:
        self._owner = owner
        self._objects: dict[str, Object3D] = {}
        self._camera: Object3D | None = None
        self._duration = 8.0
        self._fps = 30

    @property
    def _backend(self):
        return self._owner._backend

    def configure(
        self,
        duration: float = 8,
        fps: int = 30,
        background: str | Sequence[float] = "#101522",
    ) -> None:
        if not math.isfinite(duration) or not 0 < duration <= 120:
            raise ValueError("duration must be greater than 0 and at most 120 seconds.")
        if not 1 <= int(fps) <= 60:
            raise ValueError("fps must be between 1 and 60.")
        self._duration = float(duration)
        self._fps = int(fps)
        self._backend.set_timeline(self._duration, self._fps)
        self._backend.set_world_color(_color(background), strength=0.35)

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
        if not isinstance(spec, MaterialSpec):
            raise TypeError("material must be created with studio.mat.pbr() or studio.mat.emissive().")
        values = spec.options()
        return self._backend._material(
            object_id,
            values["color"],
            metallic=values["metallic"],
            roughness=values["roughness"],
            emission_color=values["emission"],
            emission_strength=values["emission_strength"],
            coat=values["coat"],
        )

    def _create_mesh_object(self, object_id: str, geometry: GeometrySpec, material: MaterialSpec | None):
        if not isinstance(geometry, GeometrySpec):
            raise TypeError("geometry must be created with studio.geo.*().")
        bpy = self._backend._bpy
        values = geometry.options()
        kind = geometry.kind

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
        id: str,
        geometry: GeometrySpec,
        material: MaterialSpec | None = None,
        role: str | None = None,
    ) -> Object3D:
        object_ref = self._create_mesh_object(id, geometry, material)
        return self._register(id, object_ref, "mesh", role)

    def surface(
        self,
        id: str,
        size: Sequence[float] = (10, 10),
        material: MaterialSpec | None = None,
        role: str | None = "environment",
    ) -> Object3D:
        return self.mesh(id, GeometryFactory.plane(size), material, role)

    def group(
        self,
        id: str,
        children: Sequence[Object3D] = (),
        role: str | None = None,
    ) -> Object3D:
        object_id = _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
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

    def remove(self, target: Object3D | str) -> None:
        obj = self._resolve(target)
        self._owner._backend._bpy.data.objects.remove(obj._object, do_unlink=True)
        self._objects.pop(obj.id, None)

    def attach(self, child: Object3D, to: Object3D) -> None:
        self._require_object(child)
        self._require_object(to)
        if child is to:
            raise ValueError("An object cannot be parented to itself.")
        world_matrix = child._object.matrix_world.copy()
        child._object.parent = to._object
        child._object.matrix_world = world_matrix

    def place(
        self,
        obj: Object3D,
        on: Object3D | None = None,
        anchor: str = "center",
        offset: Sequence[float] = (0, 0, 0),
    ) -> None:
        self._require_object(obj)
        delta = _vector3(offset, "offset")
        if on is None:
            base = (0.0, 0.0, 0.0)
            support = (0.0, 0.0, 0.0)
        else:
            self._require_object(on)
            base = tuple(float(part) for part in on._object.location)
            support = tuple(float(part) for part in on._object.dimensions)
        size = tuple(float(part) for part in obj._object.dimensions)
        result = list(base)
        if anchor == "top":
            result[2] += (support[2] + size[2]) * 0.5
        elif anchor == "bottom":
            result[2] -= (support[2] + size[2]) * 0.5
        elif anchor == "left":
            result[0] -= (support[0] + size[0]) * 0.5
        elif anchor == "right":
            result[0] += (support[0] + size[0]) * 0.5
        elif anchor == "front":
            result[1] -= (support[1] + size[1]) * 0.5
        elif anchor == "back":
            result[1] += (support[1] + size[1]) * 0.5
        elif anchor != "center":
            raise ValueError("anchor must be center, top, bottom, left, right, front, or back.")
        obj.position.set(tuple(result[index] + delta[index] for index in range(3)))

    def look_at(self, camera: Object3D, target: Object3D | Sequence[float]) -> None:
        self._require_object(camera)
        if camera.kind != "camera":
            raise ValueError("look_at expects a camera object.")
        point = target._object.location if isinstance(target, Object3D) else _vector3(target, "target")
        camera._object.rotation_euler = self._backend._camera_rotation(camera._object.location, point)

    def frame(
        self,
        camera: Object3D,
        targets: Object3D | Sequence[Object3D],
        margin: float = 1.2,
    ) -> None:
        self._require_object(camera)
        if camera.kind != "camera":
            raise ValueError("frame expects a camera object.")
        objects = [targets] if isinstance(targets, Object3D) else list(targets)
        if not objects:
            raise ValueError("frame requires at least one target.")
        for item in objects:
            self._require_object(item)
        if not math.isfinite(margin) or margin < 1:
            raise ValueError("margin must be finite and at least 1.")
        lows = [min(float(item._object.location[axis]) - float(item._object.dimensions[axis]) / 2 for item in objects) for axis in range(3)]
        highs = [max(float(item._object.location[axis]) + float(item._object.dimensions[axis]) / 2 for item in objects) for axis in range(3)]
        center = tuple((lows[axis] + highs[axis]) / 2 for axis in range(3))
        extent = tuple(max(0.1, highs[axis] - lows[axis]) for axis in range(3))
        direction = self._backend._Vector(camera._object.location) - self._backend._Vector(center)
        if direction.length == 0:
            direction = self._backend._Vector((0, -1, 0.5))
        direction.normalize()
        data = camera._object.data
        if data.type == "ORTHO":
            data.ortho_scale = max(extent[0], extent[2], extent[1]) * margin
        else:
            half_fov = math.atan(data.sensor_height / (2 * max(10, data.lens)))
            distance = max(extent) * margin / max(0.1, 2 * math.tan(half_fov))
            camera._object.location = self._backend._Vector(center) + direction * distance
        self.look_at(camera, center)

    def align(
        self,
        objects: Sequence[Object3D],
        axis: str = "x",
        spacing: float = 1,
        start: float | None = None,
    ) -> None:
        if axis not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        if not objects:
            return
        if not math.isfinite(spacing):
            raise ValueError("spacing must be finite.")
        index = {"x": 0, "y": 1, "z": 2}[axis]
        for item in objects:
            self._require_object(item)
        origin = float(objects[0].position._read()[index]) if start is None else float(start)
        for offset, item in enumerate(objects):
            values = list(item.position._read())
            values[index] = origin + offset * spacing
            item.position.set(values)

    def camera(
        self,
        id: str,
        projection: str = "perspective",
        lens: float = 50,
        position: Sequence[float] = (0, -10, 4),
        target: Sequence[float] = (0, 0, 0),
        ortho_scale: float = 8,
    ) -> Object3D:
        object_id = _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        if projection not in {"perspective", "orthographic"}:
            raise ValueError("projection must be perspective or orthographic.")
        bpy = self._backend._bpy
        data = bpy.data.cameras.new(f"{object_id} Data")
        camera = bpy.data.objects.new(object_id, data)
        self._backend.scene.collection.objects.link(camera)
        camera.location = _vector3(position, "position")
        camera.rotation_euler = self._backend._camera_rotation(camera.location, _vector3(target, "target"))
        data.lens = max(10, min(float(lens), 300))
        if projection == "orthographic":
            data.type = "ORTHO"
            data.ortho_scale = max(0.1, float(ortho_scale))
        result = self._register(object_id, camera, "camera", "camera")
        self._backend.scene.camera = camera
        self._camera = result
        return result

    def light(
        self,
        id: str,
        type: str = "area",
        target: Object3D | Sequence[float] = (0, 0, 0),
        position: Sequence[float] = (4, -5, 7),
        color: str | Sequence[float] = "#FFFFFF",
        energy: float = 1200,
        size: float = 4,
    ) -> Object3D:
        object_id = _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        kinds = {"area": "AREA", "point": "POINT", "spot": "SPOT", "directional": "SUN"}
        if type not in kinds:
            raise ValueError("Light type must be area, point, spot, or directional.")
        if not math.isfinite(energy) or energy < 0 or not math.isfinite(size) or size <= 0:
            raise ValueError("Light energy and size must be finite and positive.")
        if isinstance(target, Object3D):
            self._require_object(target)
        bpy = self._backend._bpy
        data = bpy.data.lights.new(f"{object_id} Data", type=kinds[type])
        data.energy = float(energy)
        data.color = _color(color)[:3]
        if type == "area":
            data.shape = "DISK"
            data.size = float(size)
        elif type == "spot":
            data.spot_size = math.radians(45)
            data.spot_blend = 0.25
        light_obj = bpy.data.objects.new(object_id, data)
        self._backend.scene.collection.objects.link(light_obj)
        light_obj.location = _vector3(position, "position")
        result = self._register(object_id, light_obj, "light", "lighting")
        if isinstance(target, Object3D):
            target_point = target._object.location
        else:
            target_point = _vector3(target, "target")
        direction = self._backend._Vector(target_point) - self._backend._Vector(light_obj.location)
        if direction.length:
            light_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return result

    def find(self, role: str | None = None, id: str | None = None):
        if id is not None:
            return self._objects.get(id)
        return [item for item in self._objects.values() if role is None or item.role == role]

    def motion(self, target: Object3D) -> MotionAPI:
        self._require_object(target)
        return MotionAPI(self, target)

    def inspect(self) -> dict[str, Any]:
        return {
            "object_count": len(self._objects),
            "camera": self._camera.id if self._camera else None,
            "objects": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "role": item.role,
                    "position": item.position._read(),
                    "visible": item.visible,
                }
                for item in self._objects.values()
            ],
        }

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        if self._camera is None or self._backend.scene.camera is None:
            errors.append("No active camera is configured.")
        if not self._objects:
            errors.append("The scene contains no objects.")
        if not any(item.role == "hero" for item in self._objects.values()):
            warnings.append("No object has role='hero'.")
        for item in self._objects.values():
            if not item.visible:
                warnings.append(f"Object '{item.id}' is hidden.")
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "object_count": len(self._objects),
        }


class MotionAPI:
    __slots__ = ("_scene", "_target")

    def __init__(self, scene: SceneAPI, target: Object3D) -> None:
        self._scene = scene
        self._target = target

    def track(self, property: str) -> MotionTrack:
        paths = {"position": "location", "rotation": "rotation_euler", "scale": "scale"}
        if property not in paths:
            raise ValueError("Motion property must be position, rotation, or scale.")
        return MotionTrack(self._scene, self._target, paths[property])


class MotionTrack:
    __slots__ = ("_scene", "_target", "_data_path")

    def __init__(self, scene: SceneAPI, target: Object3D, data_path: str) -> None:
        self._scene = scene
        self._target = target
        self._data_path = data_path

    def key(
        self,
        at: float,
        value: Sequence[float],
        ease: str = "smooth",
    ) -> None:
        if not math.isfinite(at) or at < 0 or at > self._scene._duration:
            raise ValueError("Keyframe time must be inside the configured scene duration.")
        interpolation = {"smooth": "BEZIER", "linear": "LINEAR", "constant": "CONSTANT"}
        if ease not in interpolation:
            raise ValueError("ease must be smooth, linear, or constant.")
        vector = _vector3(value, "keyframe value")
        frame_offset = min(round(at * self._scene._fps), round(self._scene._duration * self._scene._fps) - 1)
        frame = self._scene._backend.scene.frame_start + frame_offset
        if not self._scene._backend.scene.frame_start <= frame <= self._scene._backend.scene.frame_end:
            raise ValueError("Keyframe maps outside the scene timeline.")
        setattr(self._target._object, self._data_path, vector)
        self._target._object.keyframe_insert(data_path=self._data_path, frame=frame)
        action = getattr(getattr(self._target._object, "animation_data", None), "action", None)
        curves = getattr(action, "fcurves", None)
        if curves is not None:
            for curve in curves:
                if curve.data_path == self._data_path:
                    for point in curve.keyframe_points:
                        point.interpolation = interpolation[ease]
                        if ease == "smooth":
                            point.handle_left_type = "AUTO_CLAMPED"
                            point.handle_right_type = "AUTO_CLAMPED"


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
        )
        self.scene = SceneAPI(self)
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
