import bpy
import mathutils

scene = studio.scene

geometry = studio.geo.rounded_box(size=(1.6, 1.0, 1.2), bevel=0.06)
material = studio.mat.noise(
    color_a="#17395F",
    color_b="#6EA2E8",
    scale=7,
    detail=4,
    roughness=0.38,
    metallic=0.15,
    bump_strength=0.12,
)
hero = scene.mesh(
    id="ci.hero",
    geometry=geometry,
    material=material,
    role="hero",
)
ground_material = studio.mat.image_texture(
    "ci_texture.png",
    roughness=0.9,
)
ground = scene.surface(
    id="ci.ground",
    size=(6, 6),
    material=ground_material,
)
scene.place(hero, on=ground, anchor="top")

rig = scene.armature(
    id="ci.rig",
    bones=[
        {"name": "Root", "head": (0, 0, 0), "tail": (0, 0, 1.2)},
        {"name": "Tip", "head": (0, 0, 1.2), "tail": (0, 0, 1.6), "parent": "Root"},
    ],
)
scene.bind_armature(hero, rig, bone="Root")
scene.rigid_body(ground, body_type="PASSIVE", collision_shape="MESH")
scene.rigid_body(hero, body_type="ACTIVE", mass=1.5, collision_shape="CONVEX_HULL")

camera = scene.camera(
    id="ci.camera",
    position=(4.5, -6.0, 4.0),
    target=(0, 0, 0.6),
    lens=50,
)
scene.frame(camera, targets=[hero, ground], margin=1.15)
scene.light(
    id="ci.key",
    type="area",
    target=hero,
    position=(3.5, -4.0, 5.0),
    energy=1400,
    size=4.0,
)
scene.light(
    id="ci.fill",
    type="area",
    target=hero,
    position=(-3.0, -2.0, 2.5),
    energy=450,
    size=3.0,
)

def add_native_marker(index):
    x = 1.15 + index * 0.18
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=16,
        ring_count=8,
        radius=0.07,
        location=(x, -0.15, 0.08),
    )
    marker = bpy.context.object
    marker.name = f"ci.native_marker.{index}"
    marker["blentopy_id"] = f"ci.native_marker.{index}"
    marker["blentopy_role"] = "decoration"
    marker.location += mathutils.Vector((0.0, 0.0, 0.02))
    return marker


native_markers = [add_native_marker(index) for index in range(3)]
for marker in native_markers:
    marker.scale *= 1.1

rotation = scene.motion(hero).track("rotation")
rotation.key(at=0, value=(0, 0, 0))
rotation.key(at=1, value=(0, 0, 0.25), ease="smooth")
