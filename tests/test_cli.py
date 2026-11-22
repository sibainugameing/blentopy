import contextlib
import io
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from blentopy import __version__
from blentopy.cli import _version_supported, main
from blentopy.templates import TEMPLATES
from blentopy.validation import validate_script


class StarterTemplateTests(unittest.TestCase):
    def test_every_template_is_valid_python_and_renderable_by_contract(self):
        for name, source in TEMPLATES.items():
            with self.subTest(template=name):
                validate_script(source)
                self.assertIn("scene.camera(", source)
                self.assertIn("scene.frame(", source)
                self.assertIn("scene.light(", source)
                self.assertIn("scene.configure(", source)

    def test_minimal_template_has_camera_and_lighting(self):
        source = TEMPLATES["minimal"]
        self.assertIn('id="camera.main"', source)
        self.assertIn('id="light.key"', source)
        self.assertIn("scene.frame(camera, targets=[cube]", source)

    def test_spinner_template_animates_the_orbit_and_hero(self):
        source = TEMPLATES["spinner"]
        self.assertIn('orbit = scene.group(id="details.orbit"', source)
        self.assertIn("scene.attach(bead, orbit)", source)
        self.assertIn('scene.motion(orbit).track("rotation")', source)
        self.assertIn("math.tau", source)


class NewCommandTests(unittest.TestCase):
    def test_new_creates_parent_directories_and_adds_python_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "nested" / "scene"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["new", str(target)])
            created = target.with_suffix(".py")
            self.assertEqual(code, 0)
            self.assertTrue(created.is_file())
            self.assertIn("Created", output.getvalue())
            validate_script(created.read_text(encoding="utf-8"))

    def test_new_refuses_to_overwrite_without_force_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scene.py"
            target.write_text("original = True\n", encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                code = main(["new", str(target)])
            self.assertEqual(code, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "original = True\n")
            self.assertIn("--force", error.getvalue())

    def test_new_force_replaces_file_with_a_valid_template(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scene.py"
            target.write_text("invalid = (", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["new", str(target), "--template", "spinner", "--force"])
            self.assertEqual(code, 0)
            source = target.read_text(encoding="utf-8")
            validate_script(source)
            self.assertIn("details.orbit", source)

    def test_new_lists_templates_without_a_target(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["new", "--list"])
        self.assertEqual(code, 0)
        for name in ("minimal", "spinner"):
            self.assertIn(name, output.getvalue())


class JsonCliTests(unittest.TestCase):
    def test_check_json_reports_success(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "scene.py"
            script.write_text("import bpy\nvalue = bpy.context.scene\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["check", str(script), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload, {"ok": True, "file": str(script)})

    def test_check_json_reports_syntax_location_and_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "broken.py"
            script.write_text("import bpy\ncube = bpy.data.objects[\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["check", str(script), "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["code"], "python-syntax-error")
            self.assertIsInstance(payload["line"], int)
            self.assertIsInstance(payload["column"], int)
            self.assertIsNotNone(payload["source_line"])
            self.assertIsNotNone(payload["suggestion"])

    def test_check_json_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.py"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["check", str(missing), "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertIn("Cannot read", payload["error"])

    def test_doctor_json_reports_supported_and_unsupported_versions(self):
        with patch("blentopy.cli.importlib.util.find_spec", return_value=None), patch(
            "blentopy.cli.find_blender", return_value="/blender"
        ), patch("blentopy.cli.blender_version", return_value="Blender 4.2.0"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["doctor", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["minimum_version"], "4.2")
            self.assertEqual(payload["blentopy_version"], __version__)

        with patch("blentopy.cli.importlib.util.find_spec", return_value=None), patch(
            "blentopy.cli.find_blender", return_value="/blender"
        ), patch("blentopy.cli.blender_version", return_value="Blender 4.1.9"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["doctor", "--json"])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])


class VersionConsistencyTests(unittest.TestCase):
    def test_project_metadata_matches_runtime_version(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(metadata["project"]["version"], __version__)
        self.assertEqual(__version__, "0.3.0")

    def test_blender_version_gate(self):
        self.assertTrue(_version_supported("4.2.0"))
        self.assertTrue(_version_supported("Blender 4.3.1"))
        self.assertFalse(_version_supported("4.1.9"))
        self.assertFalse(_version_supported("unknown"))


if __name__ == "__main__":
    unittest.main()
