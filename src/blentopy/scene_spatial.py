"""Relationship-based placement, alignment, and camera framing."""

from __future__ import annotations

import math
from typing import Sequence

from .scene_types import Object3D, _vector3

class SceneSpatialMixin:
    """Spatial operations shared by AI-authored scene scripts."""

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
        if not isinstance(anchor, str) or anchor not in {"center", "top", "bottom", "left", "right", "front", "back"}:
            raise ValueError("anchor must be center, top, bottom, left, right, front, or back.")
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
        if type(margin) not in {int, float} or not math.isfinite(margin) or not 1 <= margin <= 1000:
            raise ValueError("margin must be a finite number between 1 and 1000.")
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
        if type(spacing) not in {int, float} or not math.isfinite(spacing):
            raise ValueError("spacing must be a finite number (booleans and numeric strings are not accepted).")
        if start is not None and (type(start) not in {int, float} or not math.isfinite(start)):
            raise ValueError("start must be a finite number (booleans and numeric strings are not accepted).")
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
