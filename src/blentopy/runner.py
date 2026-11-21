"""Run validated scene code in a separate Blender process."""

from __future__ import annotations

import json
import re
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .discovery import find_blender
from .validation import validate_script


@dataclass(frozen=True)
class RenderResult:
    blender_executable: str
    output_path: Path
    blend_path: Path
    return_code: int
    log: str


@dataclass(frozen=True)
class PreviewResult:
    blender_executable: str
    blend_path: Path
    log_path: Path
    process_id: int


class RenderError(RuntimeError):
    def __init__(self, message: str, *, log: str = "") -> None:
        super().__init__(message)
        self.log = log


def format_error_report(exc: Exception, *, script_path: str | Path | None = None) -> str:
    """Explain Blender failures using traceback, source context, and likely fixes."""
    lines = [f"Error: {exc}"]
    log = getattr(exc, "log", "") or ""
    if not log:
        return "\n".join(lines)
    log_lines = log.splitlines()
    frames = list(re.finditer(r'File "([^"]+)", line (\\d+)(?:, in ([^"]+))?', log))
    if script_path:
        preferred = [frame for frame in frames if Path(frame.group(1)).name == Path(script_path).name]
        if preferred:
            frames = preferred
    if frames:
        frame = frames[-1]
        filename, line_no = frame.group(1), int(frame.group(2))
        func = frame.group(3) or "<module>"
        lines.extend(["", "Details:", f"  Location: {filename}:{line_no} ({func})"])
        source = Path(filename)
        if script_path and source.name == Path(script_path).name:
            source = Path(script_path)
        try:
            source_lines = source.read_text(encoding="utf-8").splitlines()
            lo, hi = max(1, line_no - 2), min(len(source_lines), line_no + 2)
            lines.append("  Code context:")
            for n in range(lo, hi + 1):
                lines.append(f"    {'>>' if n == line_no else '  '} {n:4}: {source_lines[n - 1]}")
        except OSError:
            pass
    exception = next((s.strip() for s in reversed(log_lines)
                     if re.match(r"^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):", s.strip())), "")
    if exception:
        lines.extend(["", "  Exception:", f"    {exception}"])
    lower = log.lower()
    if "syntaxerror" in lower:
        advice = "Check missing parentheses, quotes, commas, or indentation at the reported line."
    elif "nameerror" in lower:
        advice = "A variable or API name is undefined or misspelled; check its spelling and assignment."
    elif "attributeerror" in lower:
        advice = "The object does not expose that property or method; verify the blentopy API."
    elif "typeerror" in lower:
        advice = "The call received an incompatible value or argument; check argument names and types."
    elif "keyerror" in lower:
        advice = "The requested key is absent; verify the available keys."
    elif "filenotfounderror" in lower or "no such file or directory" in lower:
        advice = "A referenced path does not exist; check the path and asset availability."
    elif "permissionerror" in lower or "permission denied" in lower:
        advice = "Access was denied; check folder permissions."
    elif "out of memory" in lower or "memoryerror" in lower:
        advice = "Reduce resolution, scene complexity, or memory-heavy assets."
    else:
        advice = "Review the final Blender log lines to identify whether the issue is scene setup, rendering, or an asset."
    lines.extend(["", "  Suggested fix:", f"    - {advice}", "", "Blender log (last 12 lines):"])
    lines.extend(f"  {s}" for s in log_lines[-12:])
    return "\n".join(lines)


def validate_render_settings(width: int, height: int, fps: int, duration_seconds: int) -> None:
    if not (256 <= width <= 1920 and 256 <= height <= 1920):
        raise ValueError("width and height must each be between 256 and 1920 pixels.")
    if width * height > 4_194_304:
        raise ValueError("Output resolution is too large.")
    if not (1 <= fps <= 60):
        raise ValueError("fps must be between 1 and 60.")
    if not (1 <= duration_seconds <= 120):
        raise ValueError("duration_seconds must be between 1 and 120.")
    if fps * duration_seconds > 3_600:
        raise ValueError("A render may not exceed 3,600 frames.")


def _prepare_scene_environment(
    script_path: Path, output: Path, blend: Path, workspace: Path,
    width: int, height: int, fps: int, duration_seconds: int,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "BLENTOPY_SCRIPT": str(script_path),
        "BLENTOPY_WORKSPACE": str(workspace),
        "BLENTOPY_OUTPUT": str(output),
        "BLENTOPY_BLEND": str(blend),
        "BLENTOPY_WIDTH": str(width),
        "BLENTOPY_HEIGHT": str(height),
        "BLENTOPY_FPS": str(fps),
        "BLENTOPY_DURATION": str(duration_seconds),
    })
    return env


def _resolve_scene_paths(
    script_path: str | Path, output_path: str | Path,
    blend_path: str | Path | None, workspace: str | Path | None,
) -> tuple[Path, Path, Path, Path]:
    source = Path(script_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise FileNotFoundError(f"Scene script is not a regular file: {source}")
    validate_script(source.read_text(encoding="utf-8"))
    workspace_dir = Path(workspace or source.parent).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        output = output.with_suffix(".mp4")
    blend = Path(blend_path).expanduser().resolve() if blend_path else output.with_suffix(".blend")
    output.parent.mkdir(parents=True, exist_ok=True)
    blend.parent.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return source, output, blend, workspace_dir


def render_script(
    script_path: str | Path, *, output_path: str | Path,
    blend_path: str | Path | None = None, workspace: str | Path | None = None,
    blender: str | None = None, width: int = 1080, height: int = 1920,
    fps: int = 30, duration_seconds: int = 8, timeout_seconds: int = 3_600,
) -> RenderResult:
    validate_render_settings(width, height, fps, duration_seconds)
    source, output, blend, workspace_dir = _resolve_scene_paths(
        script_path, output_path, blend_path, workspace
    )
    executable = find_blender(blender)
    worker = Path(__file__).with_name("worker.py").resolve()
    command = [
        executable, "--background", "--factory-startup",
        "--python-exit-code", "1", "--python", str(worker),
    ]
    env = _prepare_scene_environment(
        source, output, blend, workspace_dir, width, height, fps, duration_seconds
    )

    try:
        completed = subprocess.run(
            command, env=env, text=True, capture_output=True,
            check=False, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raise RenderError(
            f"Blender exceeded the {timeout_seconds}-second timeout.",
            log=(stdout + "\n" + stderr).strip(),
        ) from exc
    except OSError as exc:
        raise RenderError(f"Failed to start Blender: {exc}") from exc

    log = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode != 0:
        raise RenderError(f"Blender failed with exit code {completed.returncode}.", log=log)
    if not output.exists():
        alternate = Path(f"{output}.mp4")
        if alternate.exists():
            output = alternate
        else:
            raise RenderError(f"MP4 output was not found: {output}", log=log)
    if not blend.exists():
        raise RenderError(f"Blend project was not found: {blend}", log=log)
    return RenderResult(executable, output, blend, completed.returncode, log)


def _read_preview_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _stop_preview_process(process: subprocess.Popen[str]) -> None:
    """Stop a GUI process that failed to become ready within the startup deadline."""
    try:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


def preview_script(
    script_path: str | Path, *, output_path: str | Path,
    blend_path: str | Path | None = None, workspace: str | Path | None = None,
    blender: str | None = None, width: int = 1080, height: int = 1920,
    fps: int = 30, duration_seconds: int = 8,
    startup_timeout_seconds: int = 120,
) -> PreviewResult:
    """Open Blender's GUI and return only after the editable scene is saved."""
    validate_render_settings(width, height, fps, duration_seconds)
    if not 1 <= startup_timeout_seconds <= 600:
        raise ValueError("startup_timeout_seconds must be between 1 and 600 seconds.")

    source, output, blend, workspace_dir = _resolve_scene_paths(
        script_path, output_path, blend_path, workspace
    )
    executable = find_blender(blender)
    worker = Path(__file__).with_name("preview_worker.py").resolve()
    if not worker.is_file():
        raise RenderError(
            "The installed blentopy package is missing preview_worker.py. "
            "Update the repository and reinstall it with: "
            "python -m pip install -e . --force-reinstall"
        )

    token = uuid.uuid4().hex
    status_path = workspace_dir / f".blentopy-preview-{token}.json"
    log_path = blend.with_name(f"{blend.stem}-{token}.preview.log")
    env = _prepare_scene_environment(
        source, output, blend, workspace_dir, width, height, fps, duration_seconds
    )
    env["BLENTOPY_PREVIEW_STATUS"] = str(status_path)
    command = [
        executable, "--factory-startup", "--python-exit-code", "1",
        "--python", str(worker),
    ]

    try:
        with log_path.open("w", encoding="utf-8") as log_stream:
            try:
                process = subprocess.Popen(
                    command,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                )
            except OSError as exc:
                raise RenderError(f"Failed to launch Blender GUI: {exc}") from exc

            deadline = time.monotonic() + startup_timeout_seconds
            while True:
                if status_path.is_file():
                    try:
                        status = json.loads(status_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        log_stream.flush()
                        raise RenderError(
                            f"Could not read Blender preview status: {exc}",
                            log=_read_preview_log(log_path),
                        ) from exc
                    finally:
                        status_path.unlink(missing_ok=True)

                    log_stream.flush()
                    log = _read_preview_log(log_path)
                    if status.get("status") == "error":
                        detail = status.get("error", "Unknown scene setup error.")
                        raise RenderError(
                            f"Blender opened, but scene setup failed: {detail}",
                            log=log,
                        )
                    if status.get("status") != "ready":
                        raise RenderError(
                            "Blender returned an invalid preview status.",
                            log=log,
                        )
                    if not blend.is_file():
                        raise RenderError(
                            f"Blender reported success but the .blend file is missing: {blend}",
                            log=log,
                        )
                    if process.poll() is not None:
                        raise RenderError(
                            "Blender saved the scene but the GUI process closed unexpectedly.",
                            log=log,
                        )
                    return PreviewResult(
                        blender_executable=executable,
                        blend_path=blend,
                        log_path=log_path,
                        process_id=process.pid,
                    )

                return_code = process.poll()
                if return_code is not None:
                    log_stream.flush()
                    raise RenderError(
                        "Blender exited before the preview scene was ready "
                        f"(exit code {return_code}).",
                        log=_read_preview_log(log_path),
                    )

                if time.monotonic() >= deadline:
                    _stop_preview_process(process)
                    log_stream.flush()
                    raise RenderError(
                        f"Blender did not finish opening the preview within "
                        f"{startup_timeout_seconds} seconds.",
                        log=_read_preview_log(log_path),
                    )

                time.sleep(0.1)
    finally:
        status_path.unlink(missing_ok=True)
