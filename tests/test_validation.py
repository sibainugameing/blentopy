import unittest

from blentopy.validation import ScriptValidationError, validate_script


class ScriptValidationTests(unittest.TestCase):
    def test_accepts_studio_api_script(self):
        with self.assertRaises(ScriptValidationError):
            validate_script("import math")

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

    def test_accepts_bounded_loops_and_arithmetic(self):
        valid = '''
for i in range(12):
    x = i * 1.25
    studio.add_ico_sphere("Particle", location=(x, 0, 2), scale=(0.1, 0.1, 0.1))
'''
        validate_script(valid)

    def test_rejects_unbounded_or_nested_loops(self):
        cases = (
            "for i in range(count):\n    studio.add_cube('x')",
            "for i in range(1000):\n    studio.add_cube('x')",
            "for i in range(8):\n    for j in range(8):\n        studio.add_cube('x')",
            "while True:\n    studio.add_cube('x')",
            "for i in range(8):\n    pass",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_raw_bpy(self):
        with self.assertRaises(ScriptValidationError):
            validate_script("bpy.ops.wm.save_as_mainfile(filepath='/tmp/x.blend')")

    def test_rejects_filesystem_and_private_access(self):
        cases = (
            "open('/tmp/file', 'w')",
            "studio._bpy.ops.wm.quit_blender()",
            "math.__class__",
            'studio.add_text("Huge", "x" * 1000000000)',
            "__import__('os').system('echo unsafe')",
            "x = range(10)",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_control_flow_and_functions(self):
        cases = (
            "if True:\n    studio.add_cube('x')",
            "items = [x for x in (1, 2, 3)]",
            "def go():\n    studio.add_cube('x')",
            "for x in range(3):\n    if x > 1:\n        studio.add_cube('x')",
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_unknown_api_and_names(self):
        with self.assertRaises(ScriptValidationError):
            validate_script("studio.delete_everything()")
        with self.assertRaises(ScriptValidationError):
            validate_script("studio.add_cube(unknown_name)")

    def test_limits_source_size(self):
        with self.assertRaises(ScriptValidationError):
            validate_script("#" + "x" * 100001)


if __name__ == "__main__":
    unittest.main()
