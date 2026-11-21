import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blentopy.cli import build_parser
from blentopy.runner import (
    RenderError,
    RenderProgress,
    format_error_report,
    preview_script,
    render_script,
    validate_render_settings,
)


class _StreamingRenderProcess:
    def __init__(self):
        self.stdout = io.StringIO(
            "Blender startup output\n"
            "BLENTOPY_STAGE=building_scene\n"
            "BLENTOPY_PROGRESS=0/8\n"
            "BLENTOPY_PROGRESS=3/8\n"
            "BLENTOPY_STAGE=completed\n"
        )

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


class _RunningProcess:
    pid = 4321

    def poll(self):
        return None


class _ExitedProcess:
    pid = 4322

    def poll(self):
        return 17


class RenderSettingsTests(unittest.TestCase):
    def test_accepts_portrait_defaults(self):
        validate_render_settings(720, 1280, 30, 8)

    def test_rejects_large_dimensions(self):
        with self.assertRaises(ValueError):
            validate_render_settings(2048, 1080, 30, 10)

    def test_rejects_too_many_frames(self):
        with self.assertRaises(ValueError):
            validate_render_settings(720, 1280, 60, 61)

    def test_rejects_invalid_fps(self):
        with self.assertRaises(ValueError):
            validate_render_settings(720, 1280, 0, 8)


class RenderProgressTests(unittest.TestCase):
    def test_render_streams_stage_and_completed_frame_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")
            events = []

            def launch(_command, **kwargs):
                env = kwargs["env"]
                Path(env["BLENTOPY_OUTPUT"]).write_bytes(b"video")
                Path(env["BLENTOPY_BLEND"]).write_bytes(b"project")
                return _StreamingRenderProcess()

            with patch("blentopy.runner.find_blender", return_value="/fake/Blender"):
                with patch("blentopy.runner.subprocess.Popen", side_effect=launch):
                    result = render_script(
                        script,
                        output_path=root / "renders" / "scene.mp4",
                        workspace=root / "workspace",
                        progress_callback=events.append,
                    )

            self.assertEqual(
                events,
                [
                    RenderProgress(stage="building_scene"),
                    RenderProgress(stage="rendering", frame=0, total_frames=8),
                    RenderProgress(stage="rendering", frame=3, total_frames=8),
                    RenderProgress(stage="completed"),
                ],
            )
            self.assertEqual(result.return_code, 0)
            self.assertIn("Blender startup output", result.log)
            self.assertNotIn("BLENTOPY_", result.log)
            self.assertTrue(result.output_path.is_file())
            self.assertTrue(result.blend_path.is_file())


class PreviewRunnerTests(unittest.TestCase):
    def test_error_report_shows_validation_location_and_fix(self):
        error = ValueError("Unsupported chained API call: scene.foo().bar().")
        error.lineno = 12
        error.col_offset = 8
        error.source_line = "result = scene.foo().bar()"
        error.suggestion = "Assign intermediate API results to variables."
        report = format_error_report(error, script_path="scene.py")
        self.assertIn("scene.py:12:9", report)
        self.assertIn("result = scene.foo().bar()", report)
        self.assertIn("^", report)
        self.assertIn("Suggested fix:", report)
        self.assertIn("Assign intermediate API results", report)

    def test_error_report_includes_location_context_and_advice(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "scene.py"
            script.write_text("studio.add_cube('Cube')\nmissing_name()\n", encoding="utf-8")
            log = "Traceback (most recent call last):\n  File \"" + str(script) + "\", line 2, in <module>\nNameError: name 'missing_name' is not defined\n"
            report = format_error_report(RenderError("Blender failed", log=log), script_path=script)
            self.assertIn(str(script) + ":2", report)
            self.assertIn("missing_name()", report)
            self.assertIn("Suggested fix", report)
            self.assertIn("undefined or misspelled", report)

    def test_preview_waits_for_saved_blend_and_keeps_gui_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")
            captured = {}

            def launch(command, **kwargs):
                captured["command"] = command
                env = kwargs["env"]
                blend = Path(env["BLENTOPY_BLEND"])
                blend.write_text("test blend", encoding="utf-8")
                Path(env["BLENTOPY_PREVIEW_STATUS"]).write_text(
                    json.dumps({"status": "ready", "blend": str(blend)}),
                    encoding="utf-8",
                )
                kwargs["stdout"].write("preview saved\n")
                kwargs["stdout"].flush()
                return _RunningProcess()

            with patch("blentopy.runner.find_blender", return_value="/fake/Blender"):
                with patch("blentopy.runner.subprocess.Popen", side_effect=launch) as popen:
                    result = preview_script(
                        script,
                        output_path=root / "preview.mp4",
                        blend_path=root / "preview.blend",
                        workspace=root / "workspace",
                        startup_timeout_seconds=2,
                    )

            self.assertEqual(result.blender_executable, "/fake/Blender")
            self.assertEqual(result.process_id, 4321)
            self.assertTrue(result.blend_path.is_file())
            self.assertTrue(result.log_path.is_file())
            self.assertIn("--factory-startup", captured["command"])
            self.assertIn("--python-exit-code", captured["command"])
            self.assertNotIn("--background", captured["command"])
            self.assertEqual(popen.call_count, 1)

    def test_preview_reports_blender_exit_before_scene_is_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")

            def launch(command, **kwargs):
                kwargs["stdout"].write("Blender failed to initialize\n")
                kwargs["stdout"].flush()
                return _ExitedProcess()

            with patch("blentopy.runner.find_blender", return_value="/fake/Blender"):
                with patch("blentopy.runner.subprocess.Popen", side_effect=launch):
                    with self.assertRaisesRegex(RenderError, "exited before the preview"):
                        preview_script(
                            script,
                            output_path=root / "preview.mp4",
                            blend_path=root / "preview.blend",
                            workspace=root / "workspace",
                            startup_timeout_seconds=2,
                        )

    def test_cli_exposes_preview_and_startup_timeout(self):
        args = build_parser().parse_args([
            "preview", "scene.py", "--startup-timeout", "45",
        ])
        self.assertEqual(args.command, "preview")
        self.assertEqual(args.startup_timeout, 45)


if __name__ == "__main__":
    unittest.main()
