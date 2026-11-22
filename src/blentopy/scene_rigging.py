"""Armature and Blender rigid-body operations."""

from __future__ import annotations

import math
from typing import Any, Sequence

from .scene_types import Object3D, _identifier, _normalize_bone_definitions

class SceneRiggingMixin:
    """Character rigging and physics helpers backed by Blender APIs."""

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
