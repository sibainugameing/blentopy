"""Starter scene scripts used by ``blentopy new``."""

from __future__ import annotations

MINIMAL = '''"""Minimal blentopy scene: one beveled cube on a ground plane."""

scene = studio.scene
geo = studio.geo
mat = studio.mat

scene.configure(duration=4, background="#0B1020")

ground = scene.surface(
    id="stage.ground",
    size=(20, 20),
    material=mat.pbr(color="#1A2238", roughness=0.8),
)

cube = scene.mesh(
    id="subject.cube",
    geometry=geo.rounded_box(size=(1, 1, 1), bevel=0.08),
    material=mat.pbr(color="#3B82F6", metallic=0.4, roughness=0.3),
    role="hero",
)
cube.position.set((0, 0, 0.5))

camera = scene.camera(
    id="camera.main",
    position=(4, -6, 4),
    target=(0, 0, 0.5),
)
scene.frame(camera, targets=[cube], margin=1.45)
scene.light(
    id="light.key",
    type="area",
    target=cube,
    position=(4, -4, 5),
    energy=1500,
    size=4,
)
'''

SPINNER = '''"""Spinning showcase: a rotating hero and an orbiting ring of beads."""

scene = studio.scene
geo = studio.geo
mat = studio.mat

scene.configure(duration=6, background="#060B18")

ground = scene.surface(
    id="stage.ground",
    size=(30, 30),
    material=mat.pbr(color="#101827", roughness=0.78),
)

hero = scene.mesh(
    id="subject.hero",
    geometry=geo.rounded_box(size=(1.2, 1.2, 1.2), bevel=0.1),
    material=mat.pbr(color="#2878FF", metallic=0.55, roughness=0.22, coat=0.25),
    role="hero",
)
hero.position.set((0, 0, 0.8))

orbit = scene.group(id="details.orbit", role="accent")
beads = []
for index in range(12):
    angle = index * math.tau / 12
    bead = scene.mesh(
        geometry=geo.sphere(radius=0.055, segments=16, rings=10),
        material=mat.emissive(color="#8ADFFF", strength=1.5),
        role="accent",
    )
    bead.position.set((math.cos(angle) * 1.55, math.sin(angle) * 1.55, 0.8))
    scene.attach(bead, orbit)
    beads.append(bead)

# Rotate the parent empty so all beads follow a circular orbit together.
orbit_motion = scene.motion(orbit).track("rotation")
orbit_motion.key(at=0, value=(0, 0, 0), ease="linear")
orbit_motion.key(at=6, value=(0, 0, math.tau), ease="linear")

hero_motion = scene.motion(hero).track("rotation")
hero_motion.key(at=0, value=(0, 0, 0))
hero_motion.key(at=6, value=(0, 0, math.tau), ease="linear")

camera = scene.camera(
    id="camera.main",
    position=(5, -8, 5.2),
    target=(0, 0, 0.8),
)
scene.frame(camera, targets=[hero, *beads], margin=1.55)
scene.light(
    id="light.key",
    type="area",
    target=hero,
    position=(4, -5, 6),
    energy=1800,
    size=4.5,
)
scene.light(
    id="light.fill",
    type="area",
    target=hero,
    position=(-4, -2, 3),
    energy=550,
    size=3.5,
)
'''

TEMPLATES: dict[str, str] = {"minimal": MINIMAL, "spinner": SPINNER}
