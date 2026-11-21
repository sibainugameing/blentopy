import io
import os
import json
import tempfile
import threading
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
    _stream_blender_process,
    _resolve_scene_paths,
    _locked_paths,
    _find_compatible_blender,
    _validate_staged_artifacts,
    _publish_render_artifacts,
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
    def test_rejects_source_output_and_blend_path_collisions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.mp4"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "File path collision"):
                _resolve_scene_paths(
                    script, script, root / "scene.blend", root / "workspace"
                )
            blend_script = root / "project.blend"
            blend_script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different paths"):
                _resolve_scene_paths(
                    blend_script, root / "scene.mp4", blend_script, root / "workspace"
                )

    def test_rejects_non_blend_project_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, ".blend extension"):
                _resolve_scene_paths(
                    script, root / "scene.mp4", root / "project.data", root / "workspace"
                )

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
                Path(env["BLENTOPY_OUTPUT"]).write_bytes(b"\x00\x00\x00\x18ftypisom0000")
                Path(env["BLENTOPY_BLEND"]).write_bytes(b"BLENDER-v300")
                return _StreamingRenderProcess()

            class SynchronousReaderThread:
                def __init__(self, *, target, **_kwargs):
                    self.target = target

                def start(self):
                    self.target()

                def is_alive(self):
                    return False

                def join(self, timeout=None):
                    return None

            with patch("blentopy.runner.threading.Thread", SynchronousReaderThread):
                with patch("blentopy.runner._find_compatible_blender", return_value="/fake/Blender"):
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


class RenderProcessLifecycleTests(unittest.TestCase):
    def test_file_lock_rejects_concurrent_writers_and_releases_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scene.blend"
            with _locked_paths(target):
                with self.assertRaisesRegex(RenderError, "already using"):
                    with _locked_paths(target):
                        pass
            with _locked_paths(target):
                pass

    def test_cancel_event_terminates_running_blender(self):
        class CancellableProcess:
            def __init__(self):
                self.stdout = io.StringIO("")
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        process = CancellableProcess()
        cancelled = threading.Event()
        cancelled.set()
        with patch("blentopy.runner.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(RenderError, "cancelled"):
                _stream_blender_process(
                    ["blender"], env={}, timeout_seconds=5,
                    progress_callback=None, cancel_event=cancelled,
                )
        self.assertTrue(process.terminated)

    def test_callback_failure_does_not_abort_render_or_leak_blender(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")

            def launch(_command, **kwargs):
                env = kwargs["env"]
                Path(env["BLENTOPY_OUTPUT"]).write_bytes(b"\x00\x00\x00\x18ftypisom0000")
                Path(env["BLENTOPY_BLEND"]).write_bytes(b"BLENDER-v300")
                return _StreamingRenderProcess()

            def broken_callback(_event):
                raise RuntimeError("progress UI is unavailable")

            with patch("blentopy.runner._find_compatible_blender", return_value="/fake/Blender"):
                with patch("blentopy.runner.subprocess.Popen", side_effect=launch):
                    result = render_script(
                        script,
                        output_path=root / "renders" / "scene.mp4",
                        workspace=root / "workspace",
                        progress_callback=broken_callback,
                    )

            self.assertIn("Progress callback disabled", result.log)
            self.assertTrue(result.output_path.is_file())
            self.assertTrue(result.blend_path.is_file())

    def test_stdout_eof_does_not_bypass_blender_process_timeout(self):
        class StuckProcess:
            def __init__(self):
                self.stdout = io.StringIO("")
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        process = StuckProcess()

        class SynchronousReaderThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

            def is_alive(self):
                return False

            def join(self, timeout=None):
                return None

        with patch("blentopy.runner.threading.Thread", SynchronousReaderThread):
            with patch("blentopy.runner.subprocess.Popen", return_value=process):
                with self.assertRaisesRegex(RenderError, "timeout"):
                    _stream_blender_process(
                        ["blender"], env={}, timeout_seconds=1, progress_callback=None,
                    )
        self.assertTrue(process.terminated)


    def test_artifact_pair_publish_failure_restores_previous_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "scene.mp4"
            blend = root / "scene.blend"
            staged_output = root / ".scene.staged.mp4"
            staged_blend = root / ".scene.staged.blend"
            output.write_bytes(b"previous video")
            blend.write_bytes(b"previous project")
            staged_output.write_bytes(b"\x00\x00\x00\x18ftypisom0000")
            staged_blend.write_bytes(b"BLENDER-v300")

            real_replace = os.replace

            def fail_new_blend(source, destination):
                if Path(source) == staged_blend and Path(destination) == blend:
                    raise OSError("simulated sharing violation")
                return real_replace(source, destination)

            with patch("blentopy.runner.os.replace", side_effect=fail_new_blend):
                with self.assertRaisesRegex(RenderError, "previous files were restored"):
                    _publish_render_artifacts(
                        staged_output, staged_blend, output, blend
                    )

            self.assertEqual(output.read_bytes(), b"previous video")
            self.assertEqual(blend.read_bytes(), b"previous project")
            self.assertFalse(any(path.suffix == ".backup" for path in root.iterdir()))

    def test_artifact_headers_are_validated_before_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "scene.mp4"
            blend = root / "scene.blend"
            output.write_bytes(b"not an mp4 container")
            blend.write_bytes(b"BLENDER-v300")
            with self.assertRaisesRegex(RenderError, "valid MP4"):
                _validate_staged_artifacts(output, blend)

            output.write_bytes(b"\x00\x00\x00\x18ftypisom0000")
            blend.write_bytes(b"not a blend file")
            with self.assertRaisesRegex(RenderError, "valid Blender file signature"):
                _validate_staged_artifacts(output, blend)

    def test_failed_render_preserves_existing_output_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")
            output = root / "renders" / "scene.mp4"
            blend = root / "renders" / "scene.blend"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"previous video")
            blend.write_bytes(b"previous project")

            with patch("blentopy.runner._find_compatible_blender", return_value="/fake/Blender"):
                with patch(
                    "blentopy.runner.subprocess.Popen",
                    return_value=_StreamingRenderProcess(),
                ):
                    with self.assertRaisesRegex(RenderError, "MP4 output was not created"):
                        render_script(
                            script, output_path=output, blend_path=blend,
                            workspace=root / "workspace",
                        )

            self.assertEqual(output.read_bytes(), b"previous video")
            self.assertEqual(blend.read_bytes(), b"previous project")

    def test_empty_render_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / "scene.py"
            script.write_text('studio.add_cube("Cube")\n', encoding="utf-8")

            def launch(_command, **kwargs):
                env = kwargs["env"]
                Path(env["BLENTOPY_OUTPUT"]).write_bytes(b"")
                Path(env["BLENTOPY_BLEND"]).write_bytes(b"BLENDER-v300")
                return _StreamingRenderProcess()

            with patch("blentopy.runner._find_compatible_blender", return_value="/fake/Blender"):
                with patch("blentopy.runner.subprocess.Popen", side_effect=launch):
                    with self.assertRaisesRegex(RenderError, "MP4 output is empty"):
                        render_script(
                            script, output_path=root / "renders" / "scene.mp4",
                            workspace=root / "workspace",
                        )


class PreviewRunnerTests(unittest.TestCase):
    def test_error_report_includes_stable_error_code(self):
        report = format_error_report(RenderError("conflict", code="operation-conflict"))
        self.assertIn("Error code: operation-conflict", report)


    def test_error_report_reads_structured_worker_diagnostics(self):
        payload = {
            "code": "api-argument-type-mismatch",
            "type": "ScriptValidationError",
            "message": "Argument 'location' has an incompatible type.",
            "lineno": 7,
            "col_offset": 18,
            "source_line": 'studio.add_cube("Cube", location="left")',
            "suggestion": "Pass a three-number vector such as (0, 0, 0).",
        }
        log = "BLENTOPY_ERROR=" + json.dumps(payload)
        report = format_error_report(
            RenderError("Blender failed", log=log),
            script_path="scene.py",
        )
        self.assertIn("Error code: api-argument-type-mismatch", report)
        self.assertIn("Error type: ScriptValidationError", report)
        self.assertIn("scene.py:7:19", report)
        self.assertIn("studio.add_cube", report)
        self.assertIn("three-number vector", report)

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

            with patch("blentopy.runner._find_compatible_blender", return_value="/fake/Blender"):
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

            with patch("blentopy.runner._find_compatible_blender", return_value="/fake/Blender"):
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
