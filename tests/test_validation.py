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
'''
        validate_script(valid)

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
        )
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ScriptValidationError):
                    validate_script(source)

    def test_rejects_control_flow_and_functions(self):
        cases = (
            "for x in range(3):\n    studio.add_cube(str(x))",
            "items = [x for x in (1, 2, 3)]",
            "def go():\n    studio.add_cube('x')",
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
