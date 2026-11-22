"""Mesh, curve, text, modifier, and object-editing operations."""

from __future__ import annotations

import math
from typing import Sequence

from .resource_limits import estimate_object_polygons, modifier_polygon_delta
from .scene_types import MaterialSpec, Object3D, _identifier, _vector3

class SceneModelingMixin:
    """Create and edit scene geometry without changing the public SceneAPI."""

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
