scene = studio.scene

geometry = studio.geo.rounded_box(size=(1.6, 1.0, 1.2), bevel=0.06)
material = studio.mat.pbr(
    color="#2867C8",
    roughness=0.34,
    metallic=0.18,
)
hero = scene.mesh(
    id="ci.hero",
    geometry=geometry,
    material=material,
    role="hero",
)
ground = scene.surface(id="ci.ground", size=(6, 6))
scene.place(hero, on=ground, anchor="top")

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
