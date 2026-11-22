"""Camera, lighting, object lookup, and animation entry points."""

from __future__ import annotations

import math
from typing import Sequence

from .scene_types import MotionAPI, Object3D, _color, _identifier, _vector3

class SceneVisualMixin:
    """Camera, lighting, and motion methods for SceneAPI."""

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
