"""Shared value types, factories, object handles, and animation tracks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from .ai_native import SceneAPI
else:
    SceneAPI = Any

def _vector3(value: Sequence[float], label: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a three-number sequence, not text.")
    try:
        parts = tuple(value)
    except TypeError as exc:
        raise TypeError(f"{label} must be a three-number sequence.") from exc
    if len(parts) != 3:
        raise ValueError(f"{label} must contain exactly three numbers.")
    if any(type(part) not in {int, float} for part in parts):
        raise TypeError(f"{label} values must be integers or floats (booleans and numeric strings are not accepted).")
    result = tuple(float(part) for part in parts)
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
    if isinstance(value, (str, bytes)):
        raise TypeError("Colors must be RGB/RGBA numeric sequences or #RRGGBB hex strings.")
    try:
        parts = tuple(value)
    except TypeError as exc:
        raise TypeError("Colors must be RGB/RGBA numeric sequences or #RRGGBB hex strings.") from exc
    if len(parts) not in (3, 4):
        raise ValueError("Colors must contain three or four channels.")
    if any(type(part) not in {int, float} for part in parts):
        raise TypeError("Color channels must be integers or floats; booleans and numeric strings are not accepted.")
    channels = tuple(float(part) for part in parts)
    if not all(math.isfinite(part) and 0 <= part <= 1 for part in channels):
        raise ValueError("Color channels must be finite values between 0 and 1.")
    return channels if len(channels) == 4 else (*channels, 1.0)




def _normalize_bone_definitions(bones: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a bounded, acyclic armature skeleton before creating Blender data."""
    if isinstance(bones, (str, bytes)) or not isinstance(bones, Sequence):
        raise TypeError("bones must be a sequence of bone dictionaries.")
    if not 1 <= len(bones) <= 64:
        raise ValueError("An armature must contain between 1 and 64 bones.")

    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(bones):
        if not isinstance(raw, dict):
            raise TypeError(f"Bone at index {index} must be a dictionary.")
        unknown = set(raw) - {"name", "head", "tail", "parent"}
        if unknown:
            raise ValueError(f"Unknown bone properties at index {index}: {', '.join(sorted(unknown))}")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 63:
            raise ValueError(f"Bone at index {index} needs a name of 1 to 63 characters.")
        if name in names:
            raise ValueError(f"Duplicate bone name: {name}")
        names.add(name)
        head = _vector3(raw.get("head", (0, 0, 0)), f"{name}.head")
        tail = _vector3(raw.get("tail", (0, 0, 1)), f"{name}.tail")
        if all(math.isclose(head[axis], tail[axis], abs_tol=1e-9) for axis in range(3)):
            raise ValueError(f"Bone '{name}' head and tail must be different.")
        parent = raw.get("parent")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            raise ValueError(f"Bone '{name}' parent must be another bone name or None.")
        normalized.append({"name": name, "head": head, "tail": tail, "parent": parent})

    by_name = {bone["name"]: bone for bone in normalized}
    for bone in normalized:
        parent = bone["parent"]
        if parent is not None and parent not in by_name:
            raise ValueError(f"Bone '{bone['name']}' references missing parent '{parent}'.")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"Armature bone hierarchy contains a cycle at '{name}'.")
        if name in visited:
            return
        visiting.add(name)
        parent = by_name[name]["parent"]
        if parent is not None:
            visit(parent)
        visiting.remove(name)
        visited.add(name)

    for name in by_name:
        visit(name)
    return normalized

def _finite_number(value: Any, label: str, *, minimum: float | None = None,
                   maximum: float | None = None, minimum_exclusive: bool = False) -> float:
    if type(value) not in {int, float}:
        raise TypeError(f"{label} must be an integer or float (booleans and numeric strings are not accepted).")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    if minimum is not None:
        invalid = number <= minimum if minimum_exclusive else number < minimum
        if invalid:
            comparator = "greater than" if minimum_exclusive else "at least"
            raise ValueError(f"{label} must be {comparator} {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return number


def _bounded_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{label} must be an integer.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return value


def _validate_role(role: str | None) -> None:
    if role is not None and (not isinstance(role, str) or len(role) > 64):
        raise ValueError("role must be a string of at most 64 characters.")


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
        bevel = _finite_number(bevel, "bevel", minimum=0)
        return GeometrySpec("box", (("size", dimensions), ("bevel", bevel)))

    @staticmethod
    def rounded_box(size: Sequence[float] = (1, 1, 1), bevel: float = 0.06) -> GeometrySpec:
        return GeometryFactory.box(size=size, bevel=bevel)

    @staticmethod
    def sphere(radius: float = 0.5, segments: int = 32, rings: int = 16) -> GeometrySpec:
        radius = _finite_number(radius, "sphere radius", minimum=0, minimum_exclusive=True)
        segments = _bounded_integer(segments, "sphere segments", 8, 128)
        rings = _bounded_integer(rings, "sphere rings", 4, 64)
        return GeometrySpec("sphere", (
            ("radius", radius), ("segments", segments), ("rings", rings),
        ))

    @staticmethod
    def plane(size: Sequence[float] = (10, 10)) -> GeometrySpec:
        if isinstance(size, (str, bytes)) or len(size) != 2:
            raise ValueError("Plane size must contain width and depth.")
        if any(type(part) not in {int, float} for part in size):
            raise TypeError("Plane dimensions must be numeric (booleans and numeric strings are not accepted).")
        dimensions = tuple(float(part) for part in size)
        if not all(math.isfinite(part) and part > 0 for part in dimensions):
            raise ValueError("Plane dimensions must be finite and greater than zero.")
        return GeometrySpec("plane", (("size", dimensions),))

    @staticmethod
    def cylinder(radius: float = 0.5, height: float = 1, segments: int = 32) -> GeometrySpec:
        radius = _finite_number(radius, "Cylinder radius", minimum=0, minimum_exclusive=True)
        height = _finite_number(height, "Cylinder height", minimum=0, minimum_exclusive=True)
        segments = _bounded_integer(segments, "Cylinder segments", 8, 128)
        return GeometrySpec("cylinder", (
            ("radius", radius), ("height", height), ("segments", segments),
        ))

    @staticmethod
    def cone(radius: float = 0.5, height: float = 1, segments: int = 32) -> GeometrySpec:
        radius = _finite_number(radius, "Cone radius", minimum=0, minimum_exclusive=True)
        height = _finite_number(height, "Cone height", minimum=0, minimum_exclusive=True)
        segments = _bounded_integer(segments, "Cone segments", 8, 128)
        return GeometrySpec("cone", (
            ("radius", radius), ("height", height), ("segments", segments),
        ))

    @staticmethod
    def torus(
        major_radius: float = 1,
        minor_radius: float = 0.1,
        major_segments: int = 48,
        minor_segments: int = 12,
    ) -> GeometrySpec:
        major_radius = _finite_number(major_radius, "major_radius", minimum=0, minimum_exclusive=True)
        minor_radius = _finite_number(minor_radius, "minor_radius", minimum=0, minimum_exclusive=True)
        if minor_radius >= major_radius:
            raise ValueError("minor_radius must be smaller than major_radius.")
        major_segments = _bounded_integer(major_segments, "major_segments", 12, 128)
        minor_segments = _bounded_integer(minor_segments, "minor_segments", 6, 64)
        return GeometrySpec("torus", (
            ("major_radius", major_radius), ("minor_radius", minor_radius),
            ("major_segments", major_segments), ("minor_segments", minor_segments),
        ))

    @staticmethod
    def ico_sphere(radius: float = 0.5, subdivisions: int = 2) -> GeometrySpec:
        if type(radius) not in {int, float} or not math.isfinite(radius) or radius <= 0:
            raise ValueError("Icosphere radius must be finite and greater than zero.")
        if type(subdivisions) is not int or not 1 <= subdivisions <= 6:
            raise ValueError("Icosphere subdivisions must be between 1 and 6.")
        return GeometrySpec("ico_sphere", (("radius", float(radius)), ("subdivisions", subdivisions)))

    @staticmethod
    def circle(radius: float = 1.0, vertices: int = 64, fill: bool = True) -> GeometrySpec:
        if type(radius) not in {int, float} or not math.isfinite(radius) or radius <= 0:
            raise ValueError("Circle radius must be finite and greater than zero.")
        if type(vertices) is not int or not 3 <= vertices <= 512:
            raise ValueError("Circle vertices must be an integer from 3 to 512.")
        if type(fill) is not bool:
            raise TypeError("Circle fill must be a boolean.")
        return GeometrySpec("circle", (("radius", float(radius)), ("vertices", vertices), ("fill", fill)))

    @staticmethod
    def ring(inner_radius: float = 0.8, outer_radius: float = 1.0, segments: int = 64) -> GeometrySpec:
        if (
            type(inner_radius) not in {int, float}
            or type(outer_radius) not in {int, float}
            or not math.isfinite(inner_radius)
            or not math.isfinite(outer_radius)
            or not 0 < inner_radius < outer_radius
        ):
            raise ValueError("Ring radii must satisfy 0 < inner_radius < outer_radius.")
        if type(segments) is not int or not 8 <= segments <= 512:
            raise ValueError("Ring segments must be an integer from 8 to 512.")
        return GeometrySpec("ring", (
            ("inner_radius", float(inner_radius)),
            ("outer_radius", float(outer_radius)),
            ("segments", segments),
        ))

    @staticmethod
    def capsule(
        radius: float = 0.5,
        height: float = 2.0,
        radial_segments: int = 32,
        cap_segments: int = 8,
    ) -> GeometrySpec:
        if (
            type(radius) not in {int, float}
            or type(height) not in {int, float}
            or not math.isfinite(radius)
            or not math.isfinite(height)
            or radius <= 0
            or height < 2 * radius
        ):
            raise ValueError("Capsule dimensions must be finite, with height >= 2 * radius > 0.")
        if type(radial_segments) is not int or not 8 <= radial_segments <= 128:
            raise ValueError("Capsule radial_segments must be between 8 and 128.")
        if type(cap_segments) is not int or not 2 <= cap_segments <= 24:
            raise ValueError("Capsule cap_segments must be between 2 and 24.")
        return GeometrySpec("capsule", (
            ("radius", float(radius)), ("height", float(height)),
            ("radial_segments", radial_segments), ("cap_segments", cap_segments),
        ))

    @staticmethod
    def torus_knot(
        radius: float = 1.0,
        tube: float = 0.2,
        tubular_segments: int = 128,
        radial_segments: int = 12,
        p: int = 2,
        q: int = 3,
    ) -> GeometrySpec:
        if (
            type(radius) not in {int, float}
            or type(tube) not in {int, float}
            or not math.isfinite(radius)
            or not math.isfinite(tube)
            or radius <= 0
            or not 0 < tube < radius
        ):
            raise ValueError("Torus knot dimensions must satisfy 0 < tube < radius.")
        if type(tubular_segments) is not int or not 24 <= tubular_segments <= 512:
            raise ValueError("tubular_segments must be between 24 and 512.")
        if type(radial_segments) is not int or not 6 <= radial_segments <= 48:
            raise ValueError("radial_segments must be between 6 and 48.")
        if type(p) is not int or type(q) is not int or not 1 <= p <= 8 or not 1 <= q <= 8:
            raise ValueError("Torus knot p and q must be integers from 1 to 8.")
        return GeometrySpec("torus_knot", (
            ("radius", float(radius)), ("tube", float(tube)),
            ("tubular_segments", tubular_segments), ("radial_segments", radial_segments),
            ("p", p), ("q", q),
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
    def image_texture(
        filepath: str,
        roughness: float = 0.55,
        metallic: float = 0.0,
        coat: float = 0.0,
    ) -> MaterialSpec:
        """Create a workspace-local image-texture material using UV/generated coordinates."""
        if not isinstance(filepath, str) or not filepath.strip():
            raise ValueError("filepath must be a non-empty string.")
        for label, value in (("roughness", roughness), ("metallic", metallic), ("coat", coat)):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label} must be a finite number between 0 and 1.")
        return MaterialSpec("image_texture", (
            ("filepath", filepath),
            ("color", _color("#FFFFFF")),
            ("roughness", float(roughness)),
            ("metallic", float(metallic)),
            ("coat", float(coat)),
            ("emission", None),
            ("emission_strength", 0.0),
        ))

    @staticmethod
    def noise(
        color_a: str | Sequence[float] = "#17253D",
        color_b: str | Sequence[float] = "#D9E3F5",
        scale: float = 5.0,
        detail: float = 3.0,
        roughness: float = 0.55,
        metallic: float = 0.0,
        bump_strength: float = 0.15,
    ) -> MaterialSpec:
        """Create a procedural Noise Texture -> Color Ramp material with optional bump."""
        for label, value in (("scale", scale), ("detail", detail)):
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError(f"{label} must be a finite number.")
        if not 0.1 <= scale <= 1000 or not 0 <= detail <= 15:
            raise ValueError("Noise scale must be in [0.1, 1000] and detail in [0, 15].")
        for label, value in (("roughness", roughness), ("metallic", metallic), ("bump_strength", bump_strength)):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label} must be a finite number between 0 and 1.")
        return MaterialSpec("noise", (
            ("color", _color(color_a)),
            ("color_b", _color(color_b)),
            ("roughness", float(roughness)),
            ("metallic", float(metallic)),
            ("coat", 0.0),
            ("emission", None),
            ("emission_strength", 0.0),
            ("scale", float(scale)),
            ("detail", float(detail)),
            ("bump_strength", float(bump_strength)),
        ))

    @staticmethod
    def physical(
        color: str | Sequence[float] = "#FFFFFF",
        roughness: float = 0.08,
        metallic: float = 0.0,
        transmission: float = 1.0,
        ior: float = 1.45,
        thickness: float = 0.2,
        alpha: float = 1.0,
        coat: float = 0.0,
        subsurface: float = 0.0,
        sheen: float = 0.0,
        anisotropy: float = 0.0,
    ) -> MaterialSpec:
        for label, value in (
            ("roughness", roughness), ("metallic", metallic), ("transmission", transmission),
            ("alpha", alpha), ("coat", coat), ("subsurface", subsurface),
            ("sheen", sheen), ("anisotropy", anisotropy),
        ):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label} must be finite and between 0 and 1.")
        if type(ior) not in {int, float} or not math.isfinite(ior) or not 1 <= ior <= 3:
            raise ValueError("ior must be finite and between 1 and 3.")
        if type(thickness) not in {int, float} or not math.isfinite(thickness) or not 0 <= thickness <= 100:
            raise ValueError("thickness must be finite and between 0 and 100.")
        return MaterialSpec("physical", (
            ("color", _color(color)), ("roughness", float(roughness)),
            ("metallic", float(metallic)), ("coat", float(coat)),
            ("emission", None), ("emission_strength", 0.0),
            ("transmission", float(transmission)), ("ior", float(ior)),
            ("thickness", float(thickness)), ("alpha", float(alpha)),
            ("subsurface", float(subsurface)), ("sheen", float(sheen)),
            ("anisotropy", float(anisotropy)),
        ))

    @staticmethod
    def glass(
        color: str | Sequence[float] = "#FFFFFF",
        roughness: float = 0.04,
        ior: float = 1.45,
        thickness: float = 0.2,
    ) -> MaterialSpec:
        return MaterialFactory.physical(
            color=color, roughness=roughness, transmission=1.0,
            ior=ior, thickness=thickness,
        )

    @staticmethod
    def toon(
        color: str | Sequence[float] = "#FFFFFF",
        size: float = 0.5,
        smooth: float = 0.1,
    ) -> MaterialSpec:
        for label, value in (("size", size), ("smooth", smooth)):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Toon {label} must be finite and between 0 and 1.")
        return MaterialSpec("toon", (
            ("color", _color(color)), ("roughness", 0.6), ("metallic", 0.0),
            ("coat", 0.0), ("emission", None), ("emission_strength", 0.0),
            ("size", float(size)), ("smooth", float(smooth)),
        ))

    @staticmethod
    def pbr(
        color: str | Sequence[float] = "#B8C4D8",
        roughness: float = 0.45,
        metallic: float = 0,
        coat: float = 0,
        emission: str | Sequence[float] | None = None,
        emission_strength: float = 0,
    ) -> MaterialSpec:
        roughness = _finite_number(roughness, "roughness", minimum=0, maximum=1)
        metallic = _finite_number(metallic, "metallic", minimum=0, maximum=1)
        coat = _finite_number(coat, "coat", minimum=0, maximum=1)
        emission_strength = _finite_number(emission_strength, "emission_strength", minimum=0)
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
        strength = _finite_number(strength, "Emission strength", minimum=0)
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
        if type(value) is not bool:
            raise TypeError("visible must be a boolean.")
        self._object.hide_render = not value
        self._object.hide_viewport = not value

    def move_to(self, position: Sequence[float]) -> Object3D:
        self.position.set(position)
        return self

    def rotate_by(self, rotation: Sequence[float]) -> Object3D:
        delta = _vector3(rotation, "rotation")
        current = self.rotation._read()
        self.rotation.set(tuple(current[index] + delta[index] for index in range(3)))
        return self

    def add(self, child: Object3D) -> None:
        if self.kind != "group":
            raise TypeError("Only Group objects can add children; use scene.attach() for other parents.")
        self._scene.attach(child, self)

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
        if type(at) not in {int, float} or not math.isfinite(at) or at < 0 or at > self._scene._duration:
            raise ValueError("Keyframe time must be a finite number inside the configured scene duration.")
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
                        # Interpolation belongs to the outgoing segment of this
                        # keyframe. Do not overwrite the other keys' easing modes.
                        if abs(float(point.co.x) - frame) < 1e-4:
                            point.interpolation = interpolation[ease]
                            if ease == "smooth":
                                point.handle_left_type = "AUTO_CLAMPED"
                                point.handle_right_type = "AUTO_CLAMPED"
