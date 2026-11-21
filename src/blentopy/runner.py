"""Run validated scene code in a separate Blender process."""

from __future__ import annotations

import os
import subprocess
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


class RenderError(RuntimeError):
    def __init__(self, message: str, *, log: str = "") -> None:
        super().__init__(message)
        self.log = log


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


def render_script(
    script_path: str | Path, *, output_path: str | Path,
    blend_path: str | Path | None = None, workspace: str | Path | None = None,
    blender: str | None = None, width: int = 720, height: int = 1280,
    fps: int = 30, duration_seconds: int = 8, timeout_seconds: int = 3_600,
) -> RenderResult:
    validate_render_settings(width, height, fps, duration_seconds)
    source_path = Path(script_path).expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise FileNotFoundError(f"Scene script is not a regular file: {source_path}")
    validate_script(source_path.read_text(encoding="utf-8"))

    workspace_path = Path(workspace or source_path.parent).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if output.suffix.lower() != ".mp4":
        output = output.with_suffix(".mp4")
    blend = Path(blend_path).expanduser().resolve() if blend_path else output.with_suffix(".blend")
    output.parent.mkdir(parents=True, exist_ok=True)
    blend.parent.mkdir(parents=True, exist_ok=True)
    workspace_path.mkdir(parents=True, exist_ok=True)

    executable = find_blender(blender)
    worker = Path(__file__).with_name("worker.py").resolve()
    command = [
        executable, "--background", "--factory-startup",
        "--python-exit-code", "1", "--python", str(worker),
    ]
    env = os.environ.copy()
    env.update({
        "BLENTOPY_SCRIPT": str(source_path),
        "BLENTOPY_WORKSPACE": str(workspace_path),
        "BLENTOPY_OUTPUT": str(output),
        "BLENTOPY_BLEND": str(blend),
        "BLENTOPY_WIDTH": str(width),
        "BLENTOPY_HEIGHT": str(height),
        "BLENTOPY_FPS": str(fps),
        "BLENTOPY_DURATION": str(duration_seconds),
    })

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
