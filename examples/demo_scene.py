"""Cinematic eight-second showcase demonstrating the quality-focused Studio API."""

studio.set_timeline(8, 30)
studio.set_world_color((0.008, 0.014, 0.035), strength=0.22)

studio.add_plane(
    "Infinite Ground", location=(0, 0, -0.16), scale=(200, 200, 1),
    color=(0.012, 0.022, 0.045), roughness=0.82,
)
studio.add_cylinder(
    "Stage", location=(0, 0, 0.02), scale=(2.8, 2.8, 0.22),
    color=(0.025, 0.045, 0.08), metallic=0.35, roughness=0.28,
    bevel=0.08, bevel_segments=4,
)
studio.add_cube(
    "Hero", location=(0, 0, 1.42), scale=(1.45, 1.45, 1.45),
    color=(0.025, 0.12, 0.32), metallic=0.68, roughness=0.22,
    bevel=0.16, bevel_segments=6, coat=0.45,
)
studio.add_torus(
    "Orbit Ring A", location=(0, 0, 1.42), rotation=(0.55, 0.2, 0),
    scale=(1.48, 1.48, 1.48), major_radius=1.0, minor_radius=0.035,
    color=(0.05, 0.55, 1.0), emission_color=(0.02, 0.35, 1.0),
    emission_strength=2.2,
)
studio.add_torus(
    "Orbit Ring B", location=(0, 0, 1.42), rotation=(1.15, -0.2, 0.4),
    scale=(1.7, 1.7, 1.7), major_radius=1.0, minor_radius=0.018,
    color=(0.1, 0.8, 0.95), emission_color=(0.05, 0.45, 0.9),
    emission_strength=1.4,
)
studio.add_ico_sphere(
    "Core", location=(0, 0, 1.42), scale=(0.18, 0.18, 0.18),
    color=(0.2, 0.75, 1.0), emission_color=(0.08, 0.5, 1.0),
    emission_strength=3.0,
)

for i in range(16):
    angle = i * 0.3926990817
    x = math.cos(angle) * 2.3
    y = math.sin(angle) * 2.3
    studio.add_ico_sphere(
        "Orbit Particle", location=(x, y, 1.35),
        scale=(0.045, 0.045, 0.045), color=(0.3, 0.75, 1.0),
        emission_color=(0.12, 0.5, 1.0), emission_strength=1.2,
    )

studio.add_text(
    "Title", "BLENTOPY", location=(0, -0.15, 3.6),
    size=0.58, color=(0.85, 0.94, 1.0),
    emission_color=(0.25, 0.55, 1.0), emission_strength=0.35,
)
studio.add_text(
    "Subtitle", "A PYTHON-POWERED BLENDER STUDIO",
    location=(0, -0.12, -0.62), size=0.16,
    color=(0.35, 0.68, 0.9), emission_color=(0.1, 0.3, 0.5),
    emission_strength=0.25,
)

studio.add_camera(
    "Main Camera", location=(6.2, -10.5, 5.2), target=(0, 0, 1.35),
    lens=52, focus_object_name="Hero", dof_fstop=5.6,
)
studio.add_area_light(
    "Key Light", location=(-4, -5, 7), target=(0, 0, 1.2),
    energy=1800, size=4.5, color=(0.72, 0.84, 1.0),
)
studio.add_area_light(
    "Warm Fill", location=(5, -3, 3.5), target=(0, 0, 1.2),
    energy=850, size=5, color=(1.0, 0.52, 0.28),
    shape="RECTANGLE", size_y=3,
)
studio.add_area_light(
    "Rim Light", location=(1, 4, 5), target=(0, 0, 1.3),
    energy=2300, size=2.5, color=(0.12, 0.42, 1.0),
)
studio.add_sun_light(
    "Soft Moonlight", rotation=(0.55, -0.45, -0.6),
    energy=0.55, color=(0.36, 0.52, 1.0), angle=0.12,
)

studio.animate_rotation(
    "Hero", (0, 0, 0), (0, 360, 0),
    start_frame=1, end_frame=240, interpolation="LINEAR",
)
studio.animate_rotation(
    "Orbit Ring A", (0, 0, 0), (0, 0, 360),
    start_frame=1, end_frame=240, interpolation="LINEAR",
)
studio.animate_location(
    "Hero", (0, 0, 1.32), (0, 0, 1.55),
    start_frame=1, end_frame=120, interpolation="BEZIER",
)
studio.animate_camera(
    "Main Camera",
    start_location=(6.2, -10.5, 5.2),
    end_location=(4.2, -8.2, 3.7),
    start_target=(0, 0, 1.35),
    end_target=(0, 0, 1.42),
    start_frame=1, end_frame=240, interpolation="BEZIER",
)
