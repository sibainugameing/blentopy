"""AI-native scene API.

This module exposes a small, composable object model to generated scene scripts.
Blender objects stay behind this facade; scene scripts receive handles and specs,
not bpy objects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .resource_limits import (
    ensure_scene_capacity, estimate_object_polygons,
    modifier_polygon_delta, scene_resource_usage,
)
from .scene_features import SceneFeatureMixin, build_geometry_mesh


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


class SceneAPI(SceneFeatureMixin):
    """AI-facing scene graph and spatial operations."""

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

    def curve(
        self,
        id: str | None = None,
        points: Sequence[Sequence[float]] = (),
        material: MaterialSpec | None = None,
        bevel_depth: float = 0.025,
        cyclic: bool = False,
        spline: str = "poly",
        resolution: int = 12,
        role: str | None = None,
    ) -> Object3D:
        """Create an editable 3D polyline or auto-handle Bezier curve."""
        if isinstance(points, (str, bytes)) or not 2 <= len(points) <= 4096:
            raise ValueError("A curve needs between 2 and 4096 control points.")
        coordinates = tuple(_vector3(point, "curve point") for point in points)
        if not math.isfinite(bevel_depth) or not 0 <= bevel_depth <= 100:
            raise ValueError("bevel_depth must be finite and between 0 and 100.")
        if spline not in {"poly", "bezier"}:
            raise ValueError("spline must be 'poly' or 'bezier'.")
        if type(resolution) is not int or not 1 <= resolution <= 64:
            raise ValueError("resolution must be an integer between 1 and 64.")
        object_id = self._allocate_id("curve") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(objects=1)
        bpy = self._backend._bpy
        data = bpy.data.curves.new(f"{object_id} Data", type="CURVE")
        data.dimensions = "3D"
        data.resolution_u = resolution
        data.bevel_depth = float(bevel_depth)
        data.bevel_resolution = min(8, max(0, resolution // 3))
        curve_spline = data.splines.new("BEZIER" if spline == "bezier" else "POLY")
        if spline == "bezier":
            curve_spline.bezier_points.add(len(coordinates) - 1)
            for index, coordinate in enumerate(coordinates):
                point = curve_spline.bezier_points[index]
                point.co = coordinate
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
        else:
            curve_spline.points.add(len(coordinates) - 1)
            for index, coordinate in enumerate(coordinates):
                curve_spline.points[index].co = (*coordinate, 1.0)
        curve_spline.use_cyclic_u = bool(cyclic)
        object_ref = bpy.data.objects.new(object_id, data)
        self._backend.scene.collection.objects.link(object_ref)
        data.materials.append(self._material(material, object_id))
        return self._register(object_id, object_ref, "curve", role)

    def text(
        self,
        id: str | None = None,
        body: str = "Text",
        size: float = 1,
        extrude: float = 0,
        align: str = "center",
        material: MaterialSpec | None = None,
        position: Sequence[float] = (0, 0, 0),
        rotation: Sequence[float] = (0, 0, 0),
        role: str | None = None,
    ) -> Object3D:
        """Create editable Blender text geometry."""
        if not isinstance(body, str) or len(body) > 4096:
            raise ValueError("Text body must be a string of at most 4096 characters.")
        if not math.isfinite(size) or size <= 0:
            raise ValueError("Text size must be finite and greater than zero.")
        if not math.isfinite(extrude) or extrude < 0:
            raise ValueError("Text extrusion must be finite and non-negative.")
        alignments = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
        if align not in alignments:
            raise ValueError("align must be left, center, or right.")
        object_id = self._allocate_id("text") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(objects=1)
        bpy = self._backend._bpy
        data = bpy.data.curves.new(f"{object_id} Data", type="FONT")
        data.body = body
        data.size = float(size)
        data.extrude = float(extrude)
        data.align_x = alignments[align]
        object_ref = bpy.data.objects.new(object_id, data)
        self._backend.scene.collection.objects.link(object_ref)
        object_ref.location = _vector3(position, "position")
        object_ref.rotation_euler = _vector3(rotation, "rotation")
        data.materials.append(self._material(material, object_id))
        return self._register(object_id, object_ref, "text", role)

    def duplicate(
        self,
        target: Object3D | str,
        id: str | None = None,
        offset: Sequence[float] = (1, 0, 0),
        role: str | None = None,
    ) -> Object3D:
        """Duplicate an object and its data, preserving its world transform."""
        source = self._resolve(target)
        object_id = self._allocate_id(source.kind) if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(
            objects=1,
            polygons=estimate_object_polygons(source._object),
            modifiers=len(source._object.modifiers),
        )
        duplicate_ref = source._object.copy()
        if source._object.data is not None:
            duplicate_ref.data = source._object.data.copy()
        self._backend.scene.collection.objects.link(duplicate_ref)
        world_matrix = source._object.matrix_world.copy()
        world_matrix.translation += self._backend._Vector(_vector3(offset, "offset"))
        duplicate_ref.matrix_world = world_matrix
        duplicate_ref.name = object_id
        duplicate_role = source.role if role is None else role
        return self._register(object_id, duplicate_ref, source.kind, duplicate_role)

    def instance(
        self,
        target: Object3D | str,
        id: str | None = None,
        offset: Sequence[float] = (1, 0, 0),
        role: str | None = None,
    ) -> Object3D:
        """Create a lightweight linked-data instance sharing the source mesh/material data."""
        source = self._resolve(target)
        object_id = self._allocate_id(source.kind) if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(
            objects=1,
            polygons=estimate_object_polygons(source._object),
            modifiers=len(source._object.modifiers),
        )
        instance_ref = source._object.copy()
        # Unlike duplicate(), do not copy object data: mesh, curve and material
        # datablocks remain shared until the user explicitly makes them single-user.
        self._backend.scene.collection.objects.link(instance_ref)
        world_matrix = source._object.matrix_world.copy()
        world_matrix.translation += self._backend._Vector(_vector3(offset, "offset"))
        instance_ref.matrix_world = world_matrix
        instance_ref.name = object_id
        instance_role = source.role if role is None else role
        return self._register(object_id, instance_ref, source.kind, instance_role)

    def set_dimensions(self, target: Object3D | str, dimensions: Sequence[float]) -> Object3D:
        obj = self._resolve(target)
        if obj.kind not in {"mesh", "curve", "text"}:
            raise ValueError("Dimensions can only be set on mesh, curve, or text objects.")
        values = _vector3(dimensions, "dimensions")
        if any(value <= 0 for value in values):
            raise ValueError("Object dimensions must be greater than zero.")
        obj._object.dimensions = values
        return obj

    def _mesh_modifier(
        self,
        target: Object3D | str,
        name: str,
        modifier_type: str,
        **settings: object,
    ):
        obj = self._resolve(target)
        if obj.kind != "mesh":
            raise ValueError(f"{name} can only be applied to mesh objects.")
        delta = modifier_polygon_delta(obj._object, modifier_type, **settings)
        self._ensure_capacity(modifiers=1, polygons=delta)
        return obj, obj._object.modifiers.new(name=f"Blentopy {name}", type=modifier_type)

    def bevel(self, target: Object3D | str, width: float = 0.05, segments: int = 3) -> Object3D:
        if not math.isfinite(width) or width <= 0:
            raise ValueError("Bevel width must be finite and greater than zero.")
        if type(segments) is not int or not 1 <= segments <= 12:
            raise ValueError("Bevel segments must be between 1 and 12.")
        obj, modifier = self._mesh_modifier(target, "Bevel", "BEVEL", segments=segments)
        modifier.width = float(width)
        modifier.segments = segments
        modifier.limit_method = "ANGLE"
        modifier.use_clamp_overlap = True
        return obj

    def subdivide(
        self,
        target: Object3D | str,
        levels: int = 2,
        render_levels: int | None = None,
    ) -> Object3D:
        if type(levels) is not int or not 1 <= levels <= 6:
            raise ValueError("Subdivision levels must be between 1 and 6.")
        resolved_render = levels if render_levels is None else render_levels
        if type(resolved_render) is not int or not 1 <= resolved_render <= 6:
            raise ValueError("Subdivision render levels must be between 1 and 6.")
        obj, modifier = self._mesh_modifier(
            target, "Subdivision", "SUBSURF",
            levels=levels, render_levels=resolved_render,
        )
        modifier.subdivision_type = "CATMULL_CLARK"
        modifier.levels = levels
        modifier.render_levels = resolved_render
        return obj

    def solidify(self, target: Object3D | str, thickness: float = 0.05, offset: float = -1) -> Object3D:
        if not math.isfinite(thickness) or thickness == 0:
            raise ValueError("Solidify thickness must be finite and non-zero.")
        if not math.isfinite(offset) or not -1 <= offset <= 1:
            raise ValueError("Solidify offset must be between -1 and 1.")
        obj, modifier = self._mesh_modifier(target, "Solidify", "SOLIDIFY")
        modifier.thickness = float(thickness)
        modifier.offset = float(offset)
        return obj

    def mirror(
        self,
        target: Object3D | str,
        axis: str = "x",
        merge: bool = True,
        bisect: bool = False,
    ) -> Object3D:
        if axis not in {"x", "y", "z"}:
            raise ValueError("Mirror axis must be x, y, or z.")
        obj, modifier = self._mesh_modifier(
            target, "Mirror", "MIRROR",
            use_axis=tuple(axis == candidate for candidate in ("x", "y", "z")),
        )
        modifier.use_axis = tuple(axis == candidate for candidate in ("x", "y", "z"))
        modifier.use_bisect_axis = tuple(bisect and axis == candidate for candidate in ("x", "y", "z"))
        modifier.use_mirror_merge = bool(merge)
        return obj

    def array(
        self,
        target: Object3D | str,
        count: int = 2,
        offset: Sequence[float] = (1, 0, 0),
    ) -> Object3D:
        if type(count) is not int or not 1 <= count <= 256:
            raise ValueError("Array count must be between 1 and 256.")
        delta = _vector3(offset, "array offset")
        if not any(abs(value) > 1e-9 for value in delta):
            raise ValueError("Array offset must move the repeated object.")
        obj, modifier = self._mesh_modifier(target, "Array", "ARRAY", count=count)
        modifier.count = count
        modifier.use_relative_offset = False
        modifier.use_constant_offset = True
        modifier.constant_offset_displace = delta
        return obj

    def boolean(
        self,
        target: Object3D | str,
        operand: Object3D | str,
        operation: str = "DIFFERENCE",
    ) -> Object3D:
        obj = self._resolve(target)
        cutter = self._resolve(operand)
        if obj is cutter or obj.kind != "mesh" or cutter.kind != "mesh":
            raise ValueError("Boolean operations require two different mesh objects.")
        if operation not in {"DIFFERENCE", "UNION", "INTERSECT"}:
            raise ValueError("operation must be DIFFERENCE, UNION, or INTERSECT.")
        self._ensure_capacity(
            modifiers=1,
            polygons=modifier_polygon_delta(obj._object, "BOOLEAN"),
        )
        modifier = obj._object.modifiers.new(name="Blentopy Boolean", type="BOOLEAN")
        modifier.operation = operation
        modifier.object = cutter._object
        try:
            modifier.solver = "EXACT"
        except (AttributeError, TypeError, ValueError):
            pass
        return obj

    def shade_smooth(self, target: Object3D | str) -> Object3D:
        obj = self._resolve(target)
        if obj.kind != "mesh":
            raise ValueError("Smooth shading is supported for mesh objects.")
        for polygon in obj._object.data.polygons:
            polygon.use_smooth = True
        return obj

    def set_material(self, target: Object3D | str, material: MaterialSpec) -> Object3D:
        obj = self._resolve(target)
        if obj.kind not in {"mesh", "curve", "text"}:
            raise ValueError("Materials can only be assigned to mesh, curve, or text objects.")
        new_material = self._material(material, obj.id)
        obj._object.data.materials.clear()
        obj._object.data.materials.append(new_material)
        return obj

    def remove(self, target: Object3D | str) -> None:
        obj = self._resolve(target)
        self._owner._backend._bpy.data.objects.remove(obj._object, do_unlink=True)
        self._objects.pop(obj.id, None)
        if self._camera is obj:
            self._camera = None

    def attach(self, child: Object3D, to: Object3D) -> None:
        self._require_object(child)
        self._require_object(to)
        if child is to:
            raise ValueError("An object cannot be parented to itself.")
        ancestor = to._object
        while ancestor is not None:
            if ancestor == child._object:
                raise ValueError("Parenting would create a cycle in the scene graph.")
            ancestor = ancestor.parent
        world_matrix = child._object.matrix_world.copy()
        child._object.parent = to._object
        child._object.matrix_world = world_matrix

    def _world_bounds(self, target: Object3D) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return evaluated world-space AABB bounds, including rotation and parenting."""
        candidates = [target]
        if target.kind == "group":
            descendants: list[Object3D] = []
            for candidate in self._objects.values():
                parent = candidate._object.parent
                while parent is not None:
                    if parent == target._object:
                        if candidate.kind in {"mesh", "curve", "text"}:
                            descendants.append(candidate)
                        break
                    parent = parent.parent
            if descendants:
                candidates = descendants

        depsgraph = self._backend._bpy.context.evaluated_depsgraph_get()
        points = []
        for candidate in candidates:
            object_ref = candidate._object
            try:
                evaluated = object_ref.evaluated_get(depsgraph)
                matrix_world = evaluated.matrix_world
                corners = evaluated.bound_box
                transformed = [
                    matrix_world @ self._backend._Vector(corner)
                    for corner in corners
                ]
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                center = object_ref.matrix_world.translation
                dimensions = object_ref.dimensions
                transformed = [
                    self._backend._Vector((
                        center[0] + sx * dimensions[0] / 2,
                        center[1] + sy * dimensions[1] / 2,
                        center[2] + sz * dimensions[2] / 2,
                    ))
                    for sx in (-1, 1)
                    for sy in (-1, 1)
                    for sz in (-1, 1)
                ]
            points.extend(tuple(float(value) for value in point) for point in transformed)

        if not points:
            raise ValueError(f"Object '{target.id}' has no measurable world-space bounds.")
        low = tuple(min(point[axis] for point in points) for axis in range(3))
        high = tuple(max(point[axis] for point in points) for axis in range(3))
        return low, high

    def place(
        self,
        obj: Object3D,
        on: Object3D | None = None,
        anchor: str = "center",
        offset: Sequence[float] = (0, 0, 0),
    ) -> None:
        self._require_object(obj)
        delta = _vector3(offset, "offset")
        self._backend._bpy.context.view_layer.update()
        obj_low, obj_high = self._world_bounds(obj)
        obj_center = tuple((obj_low[index] + obj_high[index]) / 2 for index in range(3))
        obj_size = tuple(obj_high[index] - obj_low[index] for index in range(3))
        if on is None:
            base = (0.0, 0.0, 0.0)
            support = (0.0, 0.0, 0.0)
        else:
            self._require_object(on)
            support_low, support_high = self._world_bounds(on)
            base = tuple((support_low[index] + support_high[index]) / 2 for index in range(3))
            support = tuple(support_high[index] - support_low[index] for index in range(3))
        result = list(base)
        if anchor == "top":
            result[2] += (support[2] + obj_size[2]) * 0.5
        elif anchor == "bottom":
            result[2] -= (support[2] + obj_size[2]) * 0.5
        elif anchor == "left":
            result[0] -= (support[0] + obj_size[0]) * 0.5
        elif anchor == "right":
            result[0] += (support[0] + obj_size[0]) * 0.5
        elif anchor == "front":
            result[1] -= (support[1] + obj_size[1]) * 0.5
        elif anchor == "back":
            result[1] += (support[1] + obj_size[1]) * 0.5
        elif anchor != "center":
            raise ValueError("anchor must be center, top, bottom, left, right, front, or back.")
        target_center = tuple(result[index] + delta[index] for index in range(3))
        world_matrix = obj._object.matrix_world.copy()
        world_matrix.translation = world_matrix.translation + self._backend._Vector(
            tuple(target_center[index] - obj_center[index] for index in range(3))
        )
        obj._object.matrix_world = world_matrix

    def look_at(self, camera: Object3D, target: Object3D | Sequence[float]) -> None:
        self._require_object(camera)
        if camera.kind != "camera":
            raise ValueError("look_at expects a camera object.")
        if isinstance(target, Object3D):
            self._require_object(target)
            point = target._object.matrix_world.translation
        else:
            point = _vector3(target, "target")
        world_location = camera._object.matrix_world.translation
        direction = self._backend._Vector(point) - self._backend._Vector(world_location)
        if direction.length == 0:
            raise ValueError("Camera location and target must differ.")
        world_rotation = direction.to_track_quat("-Z", "Y")
        parent = camera._object.parent
        if parent is not None:
            parent_rotation = parent.matrix_world.to_quaternion()
            local_rotation = parent_rotation.inverted() @ world_rotation
            camera._object.rotation_euler = local_rotation.to_euler(camera._object.rotation_mode)
        else:
            camera._object.rotation_euler = world_rotation.to_euler(camera._object.rotation_mode)

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
        self._backend._bpy.context.view_layer.update()
        bounds = [self._world_bounds(item) for item in objects]
        lows = [min(bound[0][axis] for bound in bounds) for axis in range(3)]
        highs = [max(bound[1][axis] for bound in bounds) for axis in range(3)]
        center = tuple((lows[axis] + highs[axis]) / 2 for axis in range(3))
        extent = tuple(max(0.1, highs[axis] - lows[axis]) for axis in range(3))
        camera_position = self._backend._Vector(camera._object.matrix_world.translation)
        direction = camera_position - self._backend._Vector(center)
        if direction.length == 0:
            direction = self._backend._Vector((0, -1, 0.5))
        direction.normalize()
        data = camera._object.data
        forward = -direction
        world_up = self._backend._Vector((0, 0, 1))
        right = forward.cross(world_up)
        if right.length < 1e-6:
            right = forward.cross(self._backend._Vector((0, 1, 0)))
        right.normalize()
        up = right.cross(forward).normalized()
        if data.type == "ORTHO":
            render = self._backend.scene.render
            aspect = (
                render.resolution_x * render.pixel_aspect_x
            ) / max(1, render.resolution_y * render.pixel_aspect_y)
            half_width = 0.5 * (
                abs(right.x) * extent[0]
                + abs(right.y) * extent[1]
                + abs(right.z) * extent[2]
            )
            half_height = 0.5 * (
                abs(up.x) * extent[0]
                + abs(up.y) * extent[1]
                + abs(up.z) * extent[2]
            )
            data.ortho_scale = max(2 * half_width, 2 * half_height * aspect) * margin
        else:
            render = self._backend.scene.render
            aspect = (
                render.resolution_x * render.pixel_aspect_x
            ) / max(1, render.resolution_y * render.pixel_aspect_y)
            aspect = max(0.01, aspect)
            half_width = 0.5 * (
                abs(right.x) * extent[0]
                + abs(right.y) * extent[1]
                + abs(right.z) * extent[2]
            )
            half_height = 0.5 * (
                abs(up.x) * extent[0]
                + abs(up.y) * extent[1]
                + abs(up.z) * extent[2]
            )
            half_depth = 0.5 * (
                abs(forward.x) * extent[0]
                + abs(forward.y) * extent[1]
                + abs(forward.z) * extent[2]
            )
            half_vertical_fov = math.atan(data.sensor_height / (2 * max(10, data.lens)))
            half_horizontal_fov = math.atan(math.tan(half_vertical_fov) * aspect)
            distance = max(
                half_width / max(0.01, math.tan(half_horizontal_fov)),
                half_height / max(0.01, math.tan(half_vertical_fov)),
            ) + half_depth
            desired_position = self._backend._Vector(center) + direction * distance * margin
            world_matrix = camera._object.matrix_world.copy()
            world_matrix.translation = desired_position
            camera._object.matrix_world = world_matrix
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
        first_world_position = objects[0]._object.matrix_world.translation
        origin = float(first_world_position[index]) if start is None else float(start)
        for offset, item in enumerate(objects):
            world_matrix = item._object.matrix_world.copy()
            world_position = list(world_matrix.translation)
            world_position[index] = origin + offset * spacing
            world_matrix.translation = self._backend._Vector(world_position)
            item._object.matrix_world = world_matrix

    def armature(
        self,
        bones: Sequence[dict[str, Any]],
        id: str | None = None,
        role: str | None = "rig",
    ) -> Object3D:
        """Create an armature from a validated hierarchy of at most 64 bones."""
        definitions = _normalize_bone_definitions(bones)
        object_id = self._allocate_id("armature") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(objects=1)

        bpy = self._backend._bpy
        scene = self._backend.scene
        context = bpy.context
        view_layer = context.view_layer
        previous_active = view_layer.objects.active
        previous_selected = list(context.selected_objects)
        armature_data = bpy.data.armatures.new(f"{object_id} Data")
        armature_object = bpy.data.objects.new(object_id, armature_data)
        scene.collection.objects.link(armature_object)
        try:
            for item in previous_selected:
                item.select_set(False)
            armature_object.select_set(True)
            view_layer.objects.active = armature_object
            bpy.ops.object.mode_set(mode="EDIT")
            edit_bones = {}
            for definition in definitions:
                bone = armature_data.edit_bones.new(definition["name"])
                bone.head = definition["head"]
                bone.tail = definition["tail"]
                edit_bones[definition["name"]] = bone
            for definition in definitions:
                parent = definition["parent"]
                if parent is not None:
                    edit_bones[definition["name"]].parent = edit_bones[parent]
            bpy.ops.object.mode_set(mode="OBJECT")
            result = self._register(object_id, armature_object, "armature", role)
        except Exception:
            if armature_object.mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.data.objects.remove(armature_object, do_unlink=True)
            if armature_data.users == 0:
                bpy.data.armatures.remove(armature_data)
            raise
        finally:
            for item in list(context.selected_objects):
                item.select_set(False)
            for item in previous_selected:
                if item.name in bpy.data.objects:
                    item.select_set(True)
            view_layer.objects.active = (
                previous_active
                if previous_active is not None and previous_active.name in bpy.data.objects
                else None
            )
        return result

    def bind_armature(
        self,
        target: Object3D | str,
        armature: Object3D | str,
        bone: str,
        weight: float = 1.0,
    ) -> Object3D:
        """Bind every vertex of a mesh to one bone for rigid/prop-style deformation."""
        mesh = self._resolve(target)
        rig = self._resolve(armature)
        if mesh.kind != "mesh":
            raise ValueError("bind_armature target must be a mesh object.")
        if rig.kind != "armature":
            raise ValueError("bind_armature armature argument must be an armature.")
        if not isinstance(bone, str) or bone not in rig._object.data.bones:
            raise ValueError(f"Bone '{bone}' does not exist in armature '{rig.id}'.")
        if weight.__class__ not in {int, float} or not math.isfinite(weight) or not 0 < weight <= 1:
            raise ValueError("Bone weight must be finite and in the range (0, 1].")
        vertex_count = len(mesh._object.data.vertices)
        if vertex_count == 0:
            raise ValueError(f"Mesh '{mesh.id}' has no vertices to bind.")
        self._ensure_capacity(modifiers=1)
        group = mesh._object.vertex_groups.get(bone)
        if group is None:
            group = mesh._object.vertex_groups.new(name=bone)
        group.add(list(range(vertex_count)), float(weight), "REPLACE")
        modifier = mesh._object.modifiers.new(name=f"Blentopy Armature {rig.id}", type="ARMATURE")
        modifier.object = rig._object
        modifier.use_deform_preserve_volume = True
        return mesh

    def rigid_body(
        self,
        target: Object3D | str,
        body_type: str = "ACTIVE",
        mass: float = 1.0,
        collision_shape: str = "CONVEX_HULL",
        friction: float = 0.5,
        restitution: float = 0.0,
    ) -> Object3D:
        """Configure a Blender rigid body and a bounded per-scene simulation cache."""
        obj = self._resolve(target)
        if obj.kind != "mesh":
            raise ValueError("Rigid bodies can currently be assigned only to mesh objects.")
        if body_type not in {"ACTIVE", "PASSIVE"}:
            raise ValueError("body_type must be ACTIVE or PASSIVE.")
        if collision_shape not in {
            "CONVEX_HULL", "MESH", "SPHERE", "CAPSULE",
            "CYLINDER", "CONE", "BOX", "COMPOUND",
        }:
            raise ValueError("Unsupported rigid-body collision shape.")
        for label, value, low, high in (
            ("mass", mass, 0.001, 100_000.0),
            ("friction", friction, 0.0, 1.0),
            ("restitution", restitution, 0.0, 1.0),
        ):
            if value.__class__ not in {int, float} or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{label} must be finite and in [{low}, {high}].")

        bpy = self._backend._bpy
        scene = self._backend.scene
        context = bpy.context
        view_layer = context.view_layer
        previous_active = view_layer.objects.active
        previous_selected = list(context.selected_objects)
        try:
            for item in previous_selected:
                item.select_set(False)
            obj._object.select_set(True)
            view_layer.objects.active = obj._object
            with context.temp_override(
                scene=scene,
                view_layer=view_layer,
                object=obj._object,
                active_object=obj._object,
                selected_objects=[obj._object],
                selected_editable_objects=[obj._object],
            ):
                if scene.rigidbody_world is None:
                    bpy.ops.rigidbody.world_add()
                if obj._object.rigid_body is None:
                    bpy.ops.rigidbody.object_add()
            rigid_body = obj._object.rigid_body
            if rigid_body is None:
                raise RuntimeError("Blender did not create a rigid-body component.")
            rigid_body.type = body_type
            rigid_body.collision_shape = collision_shape
            rigid_body.friction = float(friction)
            rigid_body.restitution = float(restitution)
            if body_type == "ACTIVE":
                rigid_body.mass = float(mass)
            world = scene.rigidbody_world
            world.substeps_per_frame = 8
            world.solver_iterations = 10
            world.point_cache.frame_start = scene.frame_start
            world.point_cache.frame_end = scene.frame_end
        finally:
            for item in list(context.selected_objects):
                item.select_set(False)
            for item in previous_selected:
                if item.name in bpy.data.objects:
                    item.select_set(True)
            view_layer.objects.active = (
                previous_active
                if previous_active is not None and previous_active.name in bpy.data.objects
                else None
            )
        return obj

    def camera(
        self,
        id: str | None = None,
        projection: str = "perspective",
        lens: float = 50,
        position: Sequence[float] = (0, -10, 4),
        target: Sequence[float] = (0, 0, 0),
        ortho_scale: float = 8,
    ) -> Object3D:
        object_id = self._allocate_id("camera") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(objects=1)
        if projection not in {"perspective", "orthographic"}:
            raise ValueError("projection must be perspective or orthographic.")
        if type(lens) not in {int, float} or not math.isfinite(lens) or not 10 <= lens <= 300:
            raise ValueError("lens must be a finite number between 10 and 300 mm.")
        if type(ortho_scale) not in {int, float} or not math.isfinite(ortho_scale) or ortho_scale <= 0:
            raise ValueError("ortho_scale must be finite and greater than zero.")
        camera_position = _vector3(position, "position")
        camera_target = _vector3(target, "target")
        if all(math.isclose(camera_position[i], camera_target[i], abs_tol=1e-9) for i in range(3)):
            raise ValueError("Camera position and target must differ.")
        bpy = self._backend._bpy
        data = bpy.data.cameras.new(f"{object_id} Data")
        camera = bpy.data.objects.new(object_id, data)
        self._backend.scene.collection.objects.link(camera)
        camera.location = camera_position
        camera.rotation_euler = self._backend._camera_rotation(camera_position, camera_target)
        data.lens = float(lens)
        if projection == "orthographic":
            data.type = "ORTHO"
            data.ortho_scale = float(ortho_scale)
        result = self._register(object_id, camera, "camera", "camera")
        self._backend.scene.camera = camera
        self._camera = result
        return result

    def light(
        self,
        id: str | None = None,
        type: str = "area",
        target: Object3D | Sequence[float] = (0, 0, 0),
        position: Sequence[float] = (4, -5, 7),
        color: str | Sequence[float] = "#FFFFFF",
        energy: float = 1200,
        size: float = 4,
    ) -> Object3D:
        object_id = self._allocate_id("light") if id is None else _identifier(id)
        if object_id in self._objects:
            raise ValueError(f"Duplicate scene object id: {object_id}")
        self._ensure_capacity(objects=1)
        kinds = {"area": "AREA", "point": "POINT", "spot": "SPOT", "directional": "SUN"}
        if type not in kinds:
            raise ValueError("Light type must be area, point, spot, or directional.")
        if energy.__class__ not in {int, float} or not math.isfinite(energy) or energy <= 0:
            raise ValueError("Light energy must be finite and greater than zero.")
        if size.__class__ not in {int, float} or not math.isfinite(size) or size <= 0:
            raise ValueError("Light size must be finite and greater than zero.")
        position_value = _vector3(position, "position")
        color_value = _color(color)[:3]
        if isinstance(target, Object3D):
            self._require_object(target)
            target_point = target._object.matrix_world.translation
        else:
            target_point = _vector3(target, "target")
        bpy = self._backend._bpy
        data = bpy.data.lights.new(f"{object_id} Data", type=kinds[type])
        data.energy = float(energy)
        data.color = color_value
        if type == "area":
            data.shape = "DISK"
            data.size = float(size)
        elif type == "spot":
            data.spot_size = math.radians(45)
            data.spot_blend = 0.25
        light_obj = bpy.data.objects.new(object_id, data)
        self._backend.scene.collection.objects.link(light_obj)
        light_obj.location = position_value
        result = self._register(object_id, light_obj, "light", "lighting")
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
        usage = scene_resource_usage(self._backend.scene)
        return {
            "object_count": len(self._objects),
            "resource_usage": usage,
            "camera": (
                self._camera.id if self._camera else
                (self._backend.scene.camera.name if self._backend.scene.camera else None)
            ),
            "objects": [
                {
                    "id": item.id,
                    "name": item._object.name,
                    "kind": item.kind,
                    "role": item.role,
                    "position": tuple(float(part) for part in item._object.matrix_world.translation),
                    "rotation": tuple(float(part) for part in item._object.rotation_euler),
                    "scale": tuple(float(part) for part in item._object.scale),
                    "dimensions": tuple(float(part) for part in item._object.dimensions),
                    "parent": item._object.parent.name if item._object.parent else None,
                    "visible": item.visible,
                    "modifiers": [
                        {"name": modifier.name, "type": modifier.type}
                        for modifier in item._object.modifiers
                    ],
                    "materials": [
                        material.name
                        for material in getattr(item._object.data, "materials", ())
                        if material is not None
                    ],
                }
                for item in self._objects.values()
            ],
        }

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        scene = self._backend.scene
        usage = scene_resource_usage(scene)

        limits = {"objects": 1_000, "polygons": 300_000, "modifiers": 1_500}
        for resource, value in usage.items():
            if value > limits[resource]:
                errors.append(
                    f"Scene {resource} limit exceeded: {value:,} > {limits[resource]:,}."
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

        for item in self._objects.values():
            if not item.visible:
                warnings.append(f"Object '{item.id}' is hidden.")
            try:
                matrix_values = [
                    float(value)
                    for row in item._object.matrix_world
                    for value in row
                ]
            except (ReferenceError, TypeError, ValueError):
                errors.append(f"Object '{item.id}' has an invalid transform matrix.")
            else:
                if not all(math.isfinite(value) for value in matrix_values):
                    errors.append(f"Object '{item.id}' has a non-finite world transform.")

        heroes = [item for item in self._objects.values() if item.role == "hero"]
        if not heroes:
            warnings.append("No object has role='hero'.")
        elif camera is not None and camera.type == "CAMERA":
            try:
                from bpy_extras.object_utils import world_to_camera_view

                depsgraph = self._backend._bpy.context.evaluated_depsgraph_get()
                visible_hero = False
                for hero in heroes:
                    evaluated = hero._object.evaluated_get(depsgraph)
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
            "object_count": len(self._objects),
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
