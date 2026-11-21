"""Built-in vertical video demo for blentopy."""

studio.set_timeline(duration_seconds=8, fps=30)
studio.set_world_color((0.018, 0.026, 0.055))

studio.add_plane(
    "Ground", location=(0, 0, -0.18), scale=(12, 12, 1),
    color=(0.035, 0.05, 0.085),
)
studio.add_cylinder(
    "DisplayPlatform", location=(0, 0, 0.02), scale=(2.25, 2.25, 0.22),
    color=(0.08, 0.13, 0.22),
)
studio.add_cube(
    "HeroCube", location=(0, 0, 1.35), scale=(1.55, 1.55, 1.55),
    color=(0.08, 0.32, 0.78), metallic=0.35, roughness=0.24,
)
studio.add_text(
    "MainTitle", "BLENTOPY", location=(0, -0.08, 3.25), size=0.68,
    color=(0.91, 0.96, 1),
)
studio.add_text(
    "Subtitle", "PYTHON  /  BLENDER  /  VIDEO",
    location=(0, -0.08, -0.72), size=0.19, color=(0.42, 0.72, 1),
)

studio.add_camera(
    "MainCamera", location=(0, -15, 2.1), target=(0, 0, 1.2),
    orthographic_scale=8.1,
)
studio.add_area_light(
    "KeyLight", location=(-4, -5, 7), target=(0, 0, 1),
    energy=1650, size=5, color=(0.72, 0.84, 1),
)
studio.add_area_light(
    "RimLight", location=(4, 3, 4.5), target=(0, 0, 1),
    energy=2100, size=3, color=(0.16, 0.42, 1),
)

studio.animate_rotation("HeroCube", (0, 0, 0), (22, 360, 28))
studio.animate_location("HeroCube", (0, 0, 1.35), (0, 0, 1.62))
