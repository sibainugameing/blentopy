"""AI-native scene example: a product hero shot with procedural details."""

scene = studio.scene
geo = studio.geo
mat = studio.mat

scene.configure(
    duration=8,
    fps=30,
    background="#060B18",
)

ground = scene.surface(
    id="stage.ground",
    size=(30, 30),
    material=mat.pbr(color="#101827", roughness=0.78),
)

pedestal = scene.mesh(
    id="stage.pedestal",
    geometry=geo.cylinder(radius=1.35, height=0.28, segments=64),
    material=mat.pbr(color="#18263C", metallic=0.55, roughness=0.24),
)
pedestal.position.set((0, 0, 0.14))

hero = scene.mesh(
    id="subject.hero",
    geometry=geo.rounded_box(size=(1.25, 1.25, 1.25), bevel=0.12),
    material=mat.pbr(
        color="#2878FF",
        metallic=0.58,
        roughness=0.22,
        coat=0.25,
    ),
    role="hero",
)
scene.place(hero, on=pedestal, anchor="top", offset=(0, 0, 0.06))

energy_ring = scene.mesh(
    id="subject.energy_ring",
    geometry=geo.torus(
        major_radius=1.15,
        minor_radius=0.025,
        major_segments=72,
        minor_segments=12,
    ),
    material=mat.emissive(color="#31BFFF", strength=2.2),
)
energy_ring.rotation.set((math.radians(68), 0, 0))
energy_ring.position.set((0, 0, 1.55))

# Repeated incidental meshes receive automatic IDs such as mesh.0001.
for index in range(16):
    angle = index * math.tau / 16
    bead = scene.mesh(
        geometry=geo.sphere(radius=0.035, segments=12, rings=8),
        material=mat.emissive(color="#8ADFFF", strength=1.2),
        role="accent",
    )
    bead.position.set((
        math.cos(angle) * 1.58,
        math.sin(angle) * 1.58,
        1.35,
    ))

camera = scene.camera(
    id="camera.main",
    projection="perspective",
    lens=55,
    position=(5.5, -9, 4.2),
    target=(0, 0, 1),
)
scene.frame(camera, targets=[hero, energy_ring], margin=1.55)

scene.light(
    id="light.key",
    type="area",
    target=hero,
    position=(-4, -5, 6),
    color="#FFF0DF",
    energy=1700,
    size=4.5,
)
scene.light(
    id="light.fill",
    type="area",
    target=hero,
    position=(4, -3, 2.5),
    color="#5D9DFF",
    energy=650,
    size=5,
)
scene.light(
    id="light.rim",
    type="area",
    target=hero,
    position=(2, 3, 4.5),
    color="#36BFFF",
    energy=1500,
    size=2.5,
)

hero_motion = scene.motion(hero)
hero_rise = hero_motion.track("position")
hero_rise.key(at=0, value=(0, 0, 1.0), ease="smooth")
hero_rise.key(at=2.2, value=(0, 0, 1.35), ease="smooth")
hero_rise.key(at=4.8, value=(0, 0, 1.0), ease="smooth")
hero_rise.key(at=8, value=(0, 0, 1.0), ease="smooth")

hero_spin = hero_motion.track("rotation")
hero_spin.key(at=0, value=(0, 0, 0), ease="linear")
hero_spin.key(at=8, value=(0, 0, math.tau), ease="linear")

ring_spin = scene.motion(energy_ring).track("rotation")
ring_spin.key(at=0, value=(math.radians(68), 0, 0), ease="linear")
ring_spin.key(at=8, value=(math.radians(68), 0, -math.tau), ease="linear")
