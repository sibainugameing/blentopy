"""Starter scene scripts used by ``blentopy new``."""

from __future__ import annotations

MINIMAL = '''"""Minimal blentopy scene: one beveled cube on a ground plane."""

scene = studio.scene
geo = studio.geo
mat = studio.mat

scene.configure(duration=4, fps=30, background="#0B1020")

scene.surface(
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
'''

SPINNER = '''"""Spinning showcase: a hero object with an orbiting ring of beads."""

scene = studio.scene
geo = studio.geo
mat = studio.mat

scene.configure(duration=6, fps=30, background="#060B18")

scene.surface(
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

for index in range(12):
    angle = index * math.tau / 12
    bead = scene.mesh(
        geometry=geo.sphere(radius=0.05, segments=12, rings=8),
        material=mat.emissive(color="#8ADFFF", strength=1.5),
        role="accent",
    )
    bead.position.set((math.cos(angle) * 1.4, math.sin(angle) * 1.4, 0.8))
'''

TEMPLATES: dict[str, str] = {"minimal": MINIMAL, "spinner": SPINNER}
