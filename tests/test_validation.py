import ast
import unittest

from blentopy.validation import MAX_SCRIPT_CHARS, ScriptValidationError, validate_script


class ScriptValidationTests(unittest.TestCase):
    def test_accepts_standard_python_features(self):
        source = """
import math
from collections import Counter

def build_scene(bpy, count=4):
    items = [index * 0.5 for index in range(count)]
    labels = {str(index): value for index, value in enumerate(items)}
    try:
        while len(items) > 2:
            items.pop()
    except (AttributeError, TypeError):
        raise
    return Counter(labels), math.pi

class SceneBuilder:
    def __init__(self, scene):
        self.scene = scene

    def add(self, name):
        return self.scene.objects.new(name, None)
"""
        tree = validate_script(source)
        self.assertIsInstance(tree, ast.Module)
        compile(tree, "<scene-script>", "exec")

    def test_accepts_direct_blender_api_and_mathutils_access(self):
        source = """
import bpy
import mathutils

scene = bpy.context.scene
cube = bpy.data.objects.get("Cube")
if cube is not None:
    cube.location = mathutils.Vector((1.0, 2.0, 3.0))
    cube["custom_property"] = {"nested": [1, 2, 3]}
    cube.modifiers.new(name="Subdivision", type="SUBSURF")
"""
        tree = validate_script(source)
        self.assertIsInstance(tree, ast.Module)
        compile(tree, "<scene-script>", "exec")

    def test_accepts_facade_and_native_bpy_in_the_same_script(self):
        source = """
scene = studio.scene
hero = scene.mesh(geometry=studio.geo.box())
scene.rigid_body(hero, body_type="ACTIVE", mass=2.0)
world = bpy.context.scene.rigidbody_world
if world is not None:
    world.substeps_per_frame = 12
"""
        validate_script(source)

    def test_accepts_private_attributes_and_arbitrary_chained_calls(self):
        validate_script(
            "backend = studio._backend\n"
            "obj = bpy.data.objects.get('Cube')\n"
            "value = obj.data.vertices[0].co.x\n"
            "result = getattr(obj, 'name', None)\n"
        )

    def test_syntax_error_includes_line_column_and_source(self):
        source = "import bpy\ncube = bpy.data.objects[\n"
        with self.assertRaises(ScriptValidationError) as caught:
            validate_script(source)
        error = caught.exception
        self.assertEqual(error.code, "python-syntax-error")
        self.assertEqual(error.lineno, 2)
        self.assertIsInstance(error.col_offset, int)
        self.assertEqual(error.source_line, "cube = bpy.data.objects[")
        self.assertIn("Python syntax error", str(error))
        self.assertIn("does not restrict Python constructs", error.suggestion)

    def test_rejects_empty_input_and_non_string_input(self):
        with self.assertRaisesRegex(ScriptValidationError, "empty"):
            validate_script(" \n\t")
        with self.assertRaisesRegex(ScriptValidationError, "string"):
            validate_script(None)

    def test_keeps_only_a_generous_input_size_guard(self):
        self.assertEqual(MAX_SCRIPT_CHARS, 1_000_000)
        with self.assertRaisesRegex(ScriptValidationError, "character limit"):
            validate_script("#" + "x" * MAX_SCRIPT_CHARS)

    def test_executes_normal_python_when_given_normal_builtins(self):
        source = """
import math
def make_values():
    result = []
    for index in range(5):
        result.append(math.sqrt(index))
    return result
values = make_values()
"""
        namespace = {"__builtins__": __builtins__}
        exec(compile(validate_script(source), "<scene-script>", "exec"), namespace, namespace)
        self.assertEqual(len(namespace["values"]), 5)
        self.assertAlmostEqual(namespace["values"][4], 2.0)


if __name__ == "__main__":
    unittest.main()
