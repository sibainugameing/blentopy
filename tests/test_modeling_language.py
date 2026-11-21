import unittest

from blentopy.validation import ScriptValidationError, validate_script


class ModelingLanguageTests(unittest.TestCase):
    def test_texture_and_node_material_calls_are_allowed(self):
        validate_script(
            'texture = studio.mat.image_texture("textures/wood.png")\n'
            'noise = studio.mat.noise(scale=8, detail=4)\n'
            'studio.scene.mesh(id="box", geometry=studio.geo.box(), material=noise)\n'
        )

    def test_new_modeling_calls_are_allowed(self):
        validate_script('''
scene = studio.scene
material = studio.mat.pbr(color="#DDEEFF")
path = scene.curve(
    id="cable.main",
    points=((0, 0, 0), (1, 0, 1), (2, 0, 0)),
    material=material,
    bevel_depth=0.04,
    spline="bezier",
)
label = scene.text(id="title", body="BLENTOPY", size=0.5, material=material)
body = scene.mesh(geometry=studio.geo.box(size=(1, 2, 1)))
cutter = scene.mesh(geometry=studio.geo.cylinder(radius=0.2, height=2))
scene.bevel(body, width=0.04, segments=3)
scene.subdivide(body, levels=2)
scene.solidify(body, thickness=0.08)
scene.mirror(body, axis="x", merge=True)
scene.array(body, count=4, offset=(1.5, 0, 0))
scene.duplicate(body, id="body.copy", offset=(0, 2, 0))
scene.boolean(body, cutter, operation="DIFFERENCE")
scene.shade_smooth(body)
''')

    def test_incremental_scene_edits_are_allowed(self):
        validate_script('''
scene = studio.scene
existing = scene.find(id="subject.hero")
scene.update(existing, position=(1, 0, 2), visible=True)
scene.set_dimensions(existing, (2, 2, 2))
scene.remove("old.decoration")
''')

    def test_raw_blender_access_is_accepted(self):
        validate_script(
            "import bpy\n"
            "cube = bpy.data.objects.get('Cube')\n"
            "if cube is not None:\n"
            "    cube.location.x = 2\n"
        )

    def test_unknown_method_calls_are_left_to_runtime(self):
        # The preflight checks Python syntax, not the facade's runtime API.
        validate_script('studio.scene.execute_arbitrary_code("value")')


if __name__ == "__main__":
    unittest.main()
