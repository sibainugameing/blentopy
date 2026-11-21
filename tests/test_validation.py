import unittest

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

    def test_accepts_bounded_nested_loops_and_arithmetic(self):
        valid = '''
for row in range(4):
    for column in range(5):
        x = column * 1.25
        y = row * 1.25
        studio.add_cube("Tile", location=(x, y, 0))
'''
        validate_script(valid)

    def test_rejects_unbounded_or_excessive_loops(self):
        cases = (
            "for i in range(count):\n    studio.add_cube('x')",
            "for i in range(1000):\n    studio.add_cube('x')",
            "for i in range(16):\n    for j in range(16):\n        studio.add_cube('x')",
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

    def test_limits_source_size(self):
        with self.assertRaises(ScriptValidationError):
            validate_script("#" + "x" * 100001)


if __name__ == "__main__":
    unittest.main()
