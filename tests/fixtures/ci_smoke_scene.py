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

rotation = scene.motion(hero).track("rotation")
rotation.key(at=0, value=(0, 0, 0))
rotation.key(at=1, value=(0, 0, 0.25), ease="smooth")
