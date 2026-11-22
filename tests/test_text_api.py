import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from blentopy.scene_features import SceneFeatureMixin
from blentopy.scene_modeling import SceneModelingMixin
from blentopy.scene_types import Object3D


class FakeTextData:
    def __init__(self):
        self.body = ""
        self.size = 1.0
        self.extrude = 0.0
        self.bevel_depth = 0.0
        self.align_x = "LEFT"
        self.align_y = "TOP_BASELINE"
        self.space_character = 1.0
        self.space_word = 1.0
        self.space_line = 1.0
        self.font = None
        self.materials = []


class FakeObject(dict):
    def __init__(self, name, data):
        super().__init__()
        self.name = name
        self.data = data
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.scale = (1.0, 1.0, 1.0)
        self.hide_render = False
        self.hide_viewport = False


class FakeFontCollection:
    def load(self, filepath, check_existing=True):
        return SimpleNamespace(filepath=filepath)


class FakeTextHarness(SceneFeatureMixin, SceneModelingMixin):
    def __init__(self, workspace):
        self._objects = {}
        self._counters = {}
        self.loaded_fonts = []
        curves = SimpleNamespace(new=lambda name, type: FakeTextData())
        objects = SimpleNamespace(new=lambda name, data: FakeObject(name, data))
        fonts = FakeFontCollection()
        bpy = SimpleNamespace(data=SimpleNamespace(curves=curves, objects=objects, fonts=fonts))
        scene_objects = SimpleNamespace(link=lambda obj: None)
        scene = SimpleNamespace(collection=SimpleNamespace(objects=scene_objects))
        self._backend = SimpleNamespace(_bpy=bpy, _workspace=Path(workspace), scene=scene)

    def _allocate_id(self, prefix):
        value = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = value
        return f"{prefix}.{value:04d}"

    def _ensure_capacity(self, **_kwargs):
        return None

    def _material(self, _material, _object_id):
        return "fake-material"

    def _register(self, object_id, object_ref, kind, role):
        handle = Object3D(self, object_ref, object_id, kind, role)
        self._objects[object_id] = handle
        object_ref["blentopy_id"] = object_id
        if role is not None:
            object_ref["blentopy_role"] = role
        return handle

    def _resolve(self, target):
        if isinstance(target, str):
            return self._objects[target]
        if not isinstance(target, Object3D) or target._scene is not self:
            raise TypeError("Expected an object created by this blentopy scene.")
        return target


class TextCreationAndEditingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.scene = FakeTextHarness(self.workspace)

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_text_with_typography_and_update_same_handle(self):
        title = self.scene.text(
            id="title.main",
            body="START",
            size=2,
            extrude=0.08,
            bevel_depth=0.02,
            align="center",
            align_y="center",
            character_spacing=1.2,
            word_spacing=1.1,
            line_spacing=1.3,
            role="hero",
        )
        self.assertEqual(title.id, "title.main")
        self.assertEqual(title.kind, "text")
        self.assertEqual(title._object.data.body, "START")
        self.assertEqual(title._object.data.size, 2.0)
        self.assertEqual(title._object.data.extrude, 0.08)
        self.assertEqual(title._object.data.bevel_depth, 0.02)
        self.assertEqual(title._object.data.align_x, "CENTER")
        self.assertEqual(title._object.data.align_y, "CENTER")
        self.assertEqual(title._object.data.space_character, 1.2)
        self.assertEqual(title._object.data.space_word, 1.1)
        self.assertEqual(title._object.data.space_line, 1.3)

        updated = self.scene.update_text(
            title,
            body="READY",
            size=1.5,
            align="flush",
            align_y="bottom",
            character_spacing=0.9,
        )
        self.assertIs(updated, title)
        self.assertEqual(title._object.data.body, "READY")
        self.assertEqual(title._object.data.size, 1.5)
        self.assertEqual(title._object.data.align_x, "FLUSH")
        self.assertEqual(title._object.data.align_y, "BOTTOM")
        self.assertEqual(title._object.data.space_character, 0.9)
        self.assertEqual(title._object.data.space_word, 1.1)
        self.assertEqual(title._object.data.space_line, 1.3)

    def test_font_path_is_workspace_confined_and_loaded(self):
        font_path = self.workspace / "fonts" / "display.ttf"
        font_path.parent.mkdir()
        font_path.write_bytes(b"fake-font")
        title = self.scene.text(body="TITLE", font_path="fonts/display.ttf")
        self.assertEqual(title._object.data.font.filepath, str(font_path))
        self.assertIsNotNone(title._object.data.font)

    def test_rejects_font_path_outside_workspace(self):
        outside = self.workspace.parent / "outside.ttf"
        outside.write_bytes(b"fake-font")
        try:
            with self.assertRaisesRegex(ValueError, "inside the blentopy workspace"):
                self.scene.text(body="TITLE", font_path=str(outside))
        finally:
            outside.unlink(missing_ok=True)

    def test_validation_happens_before_text_is_mutated(self):
        title = self.scene.text(body="ORIGINAL")
        with self.assertRaisesRegex(ValueError, "Text size"):
            self.scene.update_text(title, body="CHANGED", size=-1)
        self.assertEqual(title._object.data.body, "ORIGINAL")

    def test_rejects_non_text_target_and_invalid_alignment(self):
        mesh = Object3D(self.scene, FakeObject("mesh", FakeTextData()), "mesh", "mesh", None)
        with self.assertRaisesRegex(ValueError, "only supports text"):
            self.scene.update_text(mesh, body="NO")
        with self.assertRaisesRegex(ValueError, "align must be"):
            self.scene.text(body="TITLE", align="diagonal")


if __name__ == "__main__":
    unittest.main()
