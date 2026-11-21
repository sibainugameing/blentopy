import tempfile
import unittest
from pathlib import Path

from blentopy.cli import build_parser
from blentopy.gui import build_cli_command, build_doctor_command


class GuiCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.script = Path(self.temp_dir.name) / "scene with spaces.py"
        self.script.write_text("# scene script\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preview_command_delegates_to_cli_and_preserves_paths(self):
        command = build_cli_command(
            "preview",
            script=self.script,
            blender="/Applications/Blender App/blender",
            blend_output="/tmp/output scene.blend",
            workspace="/tmp/scene workspace",
            width=720,
            height=1280,
            fps=24,
            duration=10,
            startup_timeout=90,
            python_executable="/tmp/venv/bin/python",
        )
        self.assertEqual(command[:4], [
            "/tmp/venv/bin/python", "-m", "blentopy.cli", "preview"
        ])
        self.assertIn(str(self.script.resolve()), command)
        self.assertEqual(command[command.index("--blender") + 1], "/Applications/Blender App/blender")
        self.assertEqual(command[command.index("--blend-output") + 1], "/tmp/output scene.blend")
        self.assertEqual(command[command.index("--workspace") + 1], "/tmp/scene workspace")
        self.assertEqual(command[command.index("--width") + 1], "720")
        self.assertEqual(command[command.index("--startup-timeout") + 1], "90")
        self.assertNotIn("--output", command)
        self.assertNotIn("--timeout", command)

    def test_render_command_passes_output_and_timeout(self):
        command = build_cli_command(
            "render",
            script=self.script,
            output="renders/final video.mp4",
            blend_output="renders/final.blend",
            timeout=777,
            python_executable="python-test",
        )
        self.assertEqual(command[:4], ["python-test", "-m", "blentopy.cli", "render"])
        self.assertEqual(command[command.index("--output") + 1], "renders/final video.mp4")
        self.assertEqual(command[command.index("--blend-output") + 1], "renders/final.blend")
        self.assertEqual(command[command.index("--timeout") + 1], "777")
        self.assertNotIn("--startup-timeout", command)

    def test_missing_or_non_python_scene_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            build_cli_command("preview", script=self.script.parent / "missing.py")
        invalid = self.script.with_suffix(".txt")
        invalid.write_text("not python", encoding="utf-8")
        with self.assertRaises(ValueError):
            build_cli_command("render", script=invalid)

    def test_unsupported_action_is_rejected(self):
        with self.assertRaises(ValueError):
            build_cli_command("doctor", script=self.script)

    def test_doctor_command_uses_cli_and_optional_blender_path(self):
        self.assertEqual(
            build_doctor_command(blender="/path/to/blender", python_executable="python-test"),
            ["python-test", "-m", "blentopy.cli", "doctor", "--blender", "/path/to/blender"],
        )
        self.assertEqual(
            build_doctor_command(python_executable="python-test"),
            ["python-test", "-m", "blentopy.cli", "doctor"],
        )

    def test_gui_is_an_optional_cli_subcommand(self):
        args = build_parser().parse_args(["gui"])
        self.assertEqual(args.command, "gui")


if __name__ == "__main__":
    unittest.main()
