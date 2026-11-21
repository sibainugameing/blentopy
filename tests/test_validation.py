import unittest
from pathlib import Path

from blentopy.validation import ScriptValidationError, validate_script


class ScriptValidationTests(unittest.TestCase):
    def test_accepts_legacy_studio_api_script(self):
        valid = '''
size = 1.5
studio.add_cube("Cube", location=(0, 0, 0), scale=(size, size, size))
studio.animate_rotation("Cube", (0, 0, 0), (0, 360, 0))
studio.add_text("Title", "Hello", location=(0, 0, 2), size=math.radians(45))
studio.add_cone("Roof", location=(0, 0, 2), bevel=0.02)
studio.add_torus("Ring", major_radius=2, minor_radius=0.1)
studio.animate_camera(
    "Camera", (0, -8, 3), (2, -7, 3),
    (0, 0, 1), (0, 0, 1), interpolation="BEZIER"
)
'''
        validate_script(valid)

    def test_accepts_ai_native_scene_graph(self):
        valid = '''
scene = studio.scene
geo = studio.geo
mat = studio.mat
shape = geo.rounded_box(size=(1, 2, 1), bevel=0.08)
blue = mat.pbr(color="#2878FF", roughness=0.3, metallic=0.5)
hero = scene.mesh(id="hero", geometry=shape, material=blue, role="hero")
hero.position.set((0, 0, 1))
hero.position.x = 0.5
hero.visible = True
scene.update(hero, position=(0, 0, 1.2), material=blue, role="main")
scene.set_material(hero, blue)
ground = scene.surface(id="ground", size=(12, 12))
scene.place(hero, on=ground, anchor="top")
camera = scene.camera(id="camera", position=(0, -8, 3))
scene.frame(camera, targets=[hero, ground], margin=1.2)
motion = scene.motion(hero)
position_track = motion.track("position")
position_track.key(at=0, value=(0, 0, 1))
position_track.key(at=2, value=(0, 0, 3), ease="smooth")
if hero.visible and 2 > 1:
    hero.rotation.z = math.radians(15)
'''
        validate_script(valid)

    def test_accepts_repository_ai_native_example(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "ai_native_scene.py"
        validate_script(example.read_text(encoding="utf-8"))

    def test_accepts_direct_scene_motion_track_chain(self):
        valid = '''
scene = studio.scene
hero = scene.mesh(geometry=studio.geo.box())
position_track = scene.motion(hero).track("position")
position_track.key(at=0, value=(0, 0, 0))
position_track.key(at=1, value=(0, 0, 1), ease="smooth")
'''
        validate_script(valid)

    def test_accepts_find_results_as_bulk_api_arguments(self):
        valid = '''
scene = studio.scene
camera = scene.camera(id="camera")
hero_a = scene.mesh(id="hero.a", geometry=studio.geo.box(), role="hero")
hero_b = scene.mesh(id="hero.b", geometry=studio.geo.sphere(), role="hero")
heroes = scene.find(role="hero")
scene.frame(camera, targets=heroes)
scene.align(heroes, axis="x", spacing=1.25)
scene.frame(camera, targets=scene.find(role="hero"))
'''
        validate_script(valid)

    def test_accepts_direct_studio_scene_motion_track_chain(self):
        valid = '''
hero = studio.scene.mesh(geometry=studio.geo.box())
rotation_track = studio.scene.motion(hero).track("rotation")
rotation_track.key(at=0, value=(0, 0, 0))
'''
        validate_script(valid)

    def test_rejects_unsupported_calls_with_line_and_actionable_hint(self):
        source = "scene = studio.scene\nresult = max(1, 2)\n"
        with self.assertRaises(ScriptValidationError) as caught:
            validate_script(source)
        error = caught.exception
        self.assertEqual(error.lineno, 2)
        self.assertEqual(error.source_line, "result = max(1, 2)")
        self.assertEqual(error.code, "unsupported-function")
        self.assertIn("max()", str(error))
        self.assertIn("Python built-ins", error.suggestion)

    def test_accepts_bounded_nested_loops_and_arithmetic(self):
        valid = '''
for row in range(4):
    for column in range(5):
        x = column * 1.25
        y = row * 1.25
        tile = studio.scene.mesh(geometry=studio.geo.box(size=(1, 1, 0.1)))
        tile.position.set((x, y, 0))
'''
        validate_script(valid)

    def test_rejects_unbounded_or_excessive_loops(self):
        cases = (
            "for i in range(count):\n    studio.add_cube('x')",
            "for i in range(1000):\n    studio.add_cube('x')",
            "for i in range(65):\n    for j in range(65):\n        studio.add_cube('x')",
            "for a in range(2):\n    for b in range(2):\n        for c in range(2):\n            for d in range(2):\n                studio.add_cube('x')",
            "while True:\n    studio.add_cube('x')",
            "for i in range(8):\n    pass",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_import_raw_bpy_and_private_access(self):
        cases = (
            "import math",
            "bpy.ops.wm.save_as_mainfile(filepath='/tmp/x.blend')",
            "studio._bpy.ops.wm.quit_blender()",
            "math.__class__",
            "scene = studio.scene\nscene._backend",
            "hero = scene.find(role='hero')\nhero._object",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_filesystem_and_dynamic_python(self):
        cases = (
            "open('/tmp/file', 'w')",
            "x = range(10)",
            "__import__('os').system('echo unsafe')",
            "def go():\n    studio.add_cube('x')",
            "items = [x for x in (1, 2, 3)]",
            "x = [1, 2, 3][0]",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_unknown_api_and_names(self):
        cases = (
            "studio.delete_everything()",
            "studio.scene.execute_arbitrary_code()",
            "scene = studio.scene\nscene.mesh(unknown_name)",
            "studio.add_cube(unknown_name)",
            "hero = studio.scene.mesh(id='hero', geometry=studio.geo.box())\nhero.system('x')",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)


    def test_rejects_forward_reference_and_branch_only_assignment(self):
        with self.assertRaises(ScriptValidationError) as forward:
            validate_script('studio.add_cube(name)\nname = "Cube"\n')
        self.assertEqual(forward.exception.code, "undefined-name")

        with self.assertRaises(ScriptValidationError) as branch:
            validate_script(
                'if True:\n'
                '    name = "Cube"\n'
                'studio.add_cube(name)\n'
            )
        self.assertEqual(branch.exception.code, "undefined-name")

    def test_accepts_variable_assigned_in_both_branches(self):
        validate_script(
            'if True:\n'
            '    name = "Cube A"\n'
            'else:\n'
            '    name = "Cube B"\n'
            'studio.add_cube(name)\n'
        )

    def test_rejects_unknown_keyword_and_missing_required_api_arguments(self):
        with self.assertRaises(ScriptValidationError) as keyword:
            validate_script('studio.add_cube("Cube", unknown_option=True)\n')
        self.assertEqual(keyword.exception.code, "invalid-api-arguments")

        with self.assertRaises(ScriptValidationError) as missing:
            validate_script('studio.add_camera()\n')
        self.assertEqual(missing.exception.code, "invalid-api-arguments")

    def test_rejects_known_literal_argument_type_mismatch(self):
        with self.assertRaises(ScriptValidationError) as mismatch:
            validate_script('studio.add_cube(123)\n')
        self.assertEqual(mismatch.exception.code, "api-argument-type-mismatch")

    def test_limits_source_size(self):
        with self.assertRaises(ScriptValidationError):
            validate_script("#" + "x" * 100001)


if __name__ == "__main__":
    unittest.main()
