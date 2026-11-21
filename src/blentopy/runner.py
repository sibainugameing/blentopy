"""Run validated scene code in a separate Blender process."""

from __future__ import annotations

import json
import os
import queue
import re
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Callable

from .discovery import BlenderNotFoundError, blender_version, find_blender
from .validation import validate_script


@dataclass(frozen=True)
class RenderResult:
    blender_executable: str
    output_path: Path
    blend_path: Path
    return_code: int
    log: str


@dataclass(frozen=True)
class RenderProgress:
    stage: str
    frame: int | None = None
    total_frames: int | None = None


@dataclass(frozen=True)
class PreviewResult:
    blender_executable: str
    blend_path: Path
    log_path: Path
    process_id: int


@dataclass(frozen=True)
class SceneEditResult:
    blender_executable: str
    blend_path: Path
    snapshot: dict[str, object]
    log: str


class RenderError(RuntimeError):
    def __init__(
        self, message: str, *, log: str = "",
        code: str = "blender-execution-failed",
    ) -> None:
        super().__init__(message)
        self.log = log
        self.code = code


_MIN_BLENDER_VERSION = (4, 2, 0)


def _find_compatible_blender(explicit: str | None = None) -> str:
    """Resolve Blender and reject versions older than the supported VSE baseline."""
    executable = find_blender(explicit)
    version = blender_version(executable)
    match = re.search(r"(?:Blender\s+)?(\d+)\.(\d+)(?:\.(\d+))?", version)
    if match is None:
        raise BlenderNotFoundError(
            f"Could not determine Blender's version from: {version!r}. "
            "Run 'blentopy doctor' and verify the Blender executable."
        )
    parsed = tuple(int(part or 0) for part in match.groups())
    if parsed < _MIN_BLENDER_VERSION:
        required = ".".join(str(part) for part in _MIN_BLENDER_VERSION)
        raise BlenderNotFoundError(
            f"Blender {version} is not supported. blentopy requires Blender {required} or newer."
        )
    return executable


class _OperationLock:
    """Cross-platform exclusive lock file for one project or output path."""

    def __init__(self, target: str | Path) -> None:
        resolved = Path(target).expanduser().resolve()
        self.target = resolved
        self.path = resolved.with_name(f".{resolved.name}.blentopy.lock")
        self._identity: tuple[int, int] | None = None
        self._payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "target": str(resolved),
            "created": time.time(),
        }

    def _remove_stale(self) -> bool:
        try:
            before = self.path.stat()
        except FileNotFoundError:
            return True
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stale = time.time() - before.st_mtime > 3600
        else:
            stale = False
            if payload.get("host") == socket.gethostname():
                try:
                    pid = int(payload.get("pid", 0))
                except (TypeError, ValueError):
                    pid = 0
                if pid > 0:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        stale = True
                    except PermissionError:
                        stale = False
                    except OSError:
                        stale = False
                elif time.time() - before.st_mtime > 3600:
                    stale = True
        if not stale:
            return False
        try:
            after = self.path.stat()
            if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_mtime_ns
            ):
                return False
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                if self._remove_stale():
                    continue
                raise RenderError(
                    f"Another blentopy operation is already using '{self.target}'. "
                    "Wait for that operation to finish, or inspect the lock file if the "
                    "previous process crashed.",
                    code="operation-conflict",
                )
            try:
                payload = json.dumps(self._payload, ensure_ascii=False).encode("utf-8")
                os.write(descriptor, payload)
                stat = os.fstat(descriptor)
                self._identity = (stat.st_dev, stat.st_ino)
            finally:
                os.close(descriptor)
            return
        raise RenderError(
            f"Could not acquire an operation lock for '{self.target}'.",
            code="operation-conflict",
        )

    def release(self) -> None:
        if self._identity is None:
            return
        try:
            stat = self.path.stat()
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                (stat.st_dev, stat.st_ino) == self._identity
                and payload.get("pid") == os.getpid()
                and payload.get("target") == str(self.target)
            ):
                self.path.unlink()
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass
        finally:
            self._identity = None


@contextmanager
def _locked_paths(*targets: str | Path):
    """Acquire several path locks in a stable order to avoid lock-order deadlocks."""
    locks = [
        _OperationLock(path)
        for path in sorted(
            {str(Path(item).expanduser().resolve()) for item in targets}
        )
    ]
    acquired: list[_OperationLock] = []
    try:
        for lock in locks:
            lock.acquire()
            acquired.append(lock)
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()


def _serialized_targets(resolve_targets):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            targets = resolve_targets(args, kwargs)
            with _locked_paths(*targets):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def _normalized_mp4_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    return path if path.suffix.lower() == ".mp4" else path.with_suffix(".mp4")


def _render_targets(args, kwargs):
    output = _normalized_mp4_path(kwargs["output_path"])
    blend_value = kwargs.get("blend_path")
    blend = Path(blend_value).expanduser().resolve() if blend_value else output.with_suffix(".blend")
    return output, blend


def _edit_targets(args, kwargs):
    project = args[1] if len(args) > 1 else kwargs["blend_path"]
    return (Path(project).expanduser().resolve(),)


def _inspect_targets(args, kwargs):
    project = args[0] if args else kwargs["blend_path"]
    return (Path(project).expanduser().resolve(),)


def _preview_targets(args, kwargs):
    output = _normalized_mp4_path(kwargs["output_path"])
    blend_value = kwargs.get("blend_path")
    blend = Path(blend_value).expanduser().resolve() if blend_value else output.with_suffix(".blend")
    return output, blend


def format_error_report(exc: Exception, *, script_path: str | Path | None = None) -> str:
    """Explain Blender failures using traceback, source context, and likely fixes."""
    code = getattr(exc, "code", None) or (
        "script-validation-failed" if type(exc).__name__ == "ScriptValidationError"
        else "blender-execution-failed"
    )
    lines = [f"Error: {exc}", f"Error code: {code}"]
    log = getattr(exc, "log", "") or ""
    structured = None
    for entry in log.splitlines():
        if entry.startswith("BLENTOPY_ERROR="):
            try:
                value = json.loads(entry[len("BLENTOPY_ERROR="):])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("code"), str):
                structured = value
                break
    if structured is not None:
        lines[1] = f"Error code: {structured['code']}"
        error_type = structured.get("type")
        if error_type:
            lines.append(f"Error type: {error_type}")
        if structured.get("message"):
            lines.append(f"Diagnostic: {structured['message']}")
        line_no = structured.get("lineno")
        col_offset = structured.get("col_offset")
        source_line = structured.get("source_line")
        suggestion = structured.get("suggestion")
        if isinstance(line_no, int):
            location = f"{script_path or '<scene script>'}:{line_no}"
            if isinstance(col_offset, int):
                location += f":{col_offset + 1}"
            lines.extend(["", "Location:", f"  {location}"])
        if isinstance(source_line, str) and source_line:
            lines.extend(["", "Code:", f"  {source_line}"])
            if isinstance(col_offset, int):
                lines.append("  " + " " * col_offset + "^")
        if isinstance(suggestion, str) and suggestion:
            lines.extend(["", "Suggested fix:", f"  {suggestion}"])
    if not log:
        line_no = getattr(exc, "lineno", None)
        col_offset = getattr(exc, "col_offset", None)
        source_line = getattr(exc, "source_line", None)
        suggestion = getattr(exc, "suggestion", None)
        if line_no is not None:
            column = col_offset + 1 if isinstance(col_offset, int) else None
            location = f"{script_path or '<scene script>'}:{line_no}"
            if column is not None:
                location += f":{column}"
            lines.extend(["", "Location:", f"  {location}"])
        if source_line:
            prefix = f"{line_no:4} | " if line_no is not None else "     | "
            lines.extend(["", "Code:", f"  {prefix}{source_line}"])
            if isinstance(col_offset, int):
                lines.append("  " + " " * (len(prefix) + col_offset) + "^")
        if suggestion:
            lines.extend(["", "Suggested fix:", f"  {suggestion}"])
        return "\n".join(lines)

    log_lines = log.splitlines()
    frames = list(re.finditer(r'File "([^"]+)", line (\d+)(?:, in ([^"]+))?', log))
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
    if blend.suffix.lower() != ".blend":
        raise ValueError(f"blend_path must use the .blend extension: {blend}")
    if len({source, output, blend}) != 3:
        raise ValueError(
            "File path collision: the source script, MP4 output, and .blend project "
            "must all use different paths. Choose separate output paths to prevent data loss."
        )
    if output.exists() and output.is_dir():
        raise ValueError(f"MP4 output path points to a directory: {output}")
    if blend.exists() and blend.is_dir():
        raise ValueError(f"Blend project path points to a directory: {blend}")
    output.parent.mkdir(parents=True, exist_ok=True)
    blend.parent.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return source, output, blend, workspace_dir


def _dispatch_render_progress(
    line: str,
    callback: Callable[[RenderProgress], None] | None,
) -> None:
    if callback is None:
        return
    message = line.strip()
    if message.startswith("BLENTOPY_STAGE="):
        callback(RenderProgress(stage=message.partition("=")[2]))
        return
    if message.startswith("BLENTOPY_PROGRESS="):
        match = re.fullmatch(r"(\d+)/(\d+)", message.partition("=")[2])
        if match:
            callback(RenderProgress(
                stage="rendering",
                frame=int(match.group(1)),
                total_frames=int(match.group(2)),
            ))


def _stop_render_process(process: subprocess.Popen[str]) -> None:
    """Terminate Blender and escalate to kill if it does not stop promptly."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _stream_blender_process(
    command: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: int,
    progress_callback: Callable[[RenderProgress], None] | None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, str]:
    """Run Blender with bounded log retention, cancellation, and a process deadline."""
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1 second.")

    try:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise RenderError(f"Failed to start Blender: {exc}") from exc

    output_queue: queue.Queue[str | None] = queue.Queue(maxsize=512)

    def read_output() -> None:
        try:
            if process.stdout is not None:
                for output_line in process.stdout:
                    output_queue.put(output_line)
        finally:
            try:
                if process.stdout is not None:
                    process.stdout.close()
            except OSError:
                pass
            output_queue.put(None)

    reader = threading.Thread(target=read_output, name="blentopy-render-log", daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_seconds
    reader_finished = False
    log_lines: deque[str] = deque()
    log_chars = 0
    max_log_chars = 200_000

    def append_log(output_line: str) -> None:
        nonlocal log_chars
        if len(output_line) > max_log_chars:
            output_line = output_line[-max_log_chars:]
        log_lines.append(output_line)
        log_chars += len(output_line)
        while log_chars > max_log_chars and log_lines:
            log_chars -= len(log_lines.popleft())

    def consume(output_line: str | None) -> None:
        nonlocal reader_finished, progress_callback
        if output_line is None:
            reader_finished = True
            return
        if not output_line.lstrip().startswith(("BLENTOPY_STAGE=", "BLENTOPY_PROGRESS=")):
            append_log(output_line)
        if progress_callback is not None:
            try:
                _dispatch_render_progress(output_line, progress_callback)
            except Exception as exc:
                append_log(
                    "[blentopy] Progress callback disabled after "
                    f"{type(exc).__name__}: {exc}\n"
                )
                progress_callback = None

    def drain_queue() -> None:
        while True:
            try:
                consume(output_queue.get_nowait())
            except queue.Empty:
                return

    def stop_and_drain() -> None:
        _stop_render_process(process)
        drain_deadline = time.monotonic() + 5
        while reader.is_alive() and time.monotonic() < drain_deadline:
            try:
                consume(output_queue.get(timeout=0.05))
            except queue.Empty:
                reader.join(timeout=0.05)
        drain_queue()
        reader.join(timeout=0.1)

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                stop_and_drain()
                raise RenderError(
                    "Blender operation was cancelled; staged files were discarded.",
                    log="".join(log_lines).strip(),
                    code="operation-cancelled",
                )

            return_code = process.poll()
            if reader_finished and return_code is not None:
                # The EOF marker is enqueued immediately before the reader thread
                # returns. Join it explicitly so Windows does not leave a daemon
                # thread racing interpreter shutdown after a successful render.
                reader.join(timeout=2)
                drain_queue()
                return return_code, "".join(log_lines).strip()

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stop_and_drain()
                raise RenderError(
                    f"Blender exceeded the {timeout_seconds}-second timeout.",
                    log="".join(log_lines).strip(),
                    code="blender-timeout",
                )

            try:
                consume(output_queue.get(timeout=min(0.1, remaining)))
            except queue.Empty:
                continue

    except KeyboardInterrupt:
        stop_and_drain()
        raise RenderError(
            "Blender operation was cancelled by the user; staged files were discarded.",
            log="".join(log_lines).strip(),
            code="operation-cancelled",
        ) from None

def _scene_report_from_log(log: str) -> dict[str, object]:
    prefix = "BLENTOPY_SCENE_REPORT="
    for line in log.splitlines():
        if line.startswith(prefix):
            try:
                report = json.loads(line[len(prefix):])
            except json.JSONDecodeError as exc:
                raise RenderError(
                    f"Blender returned an invalid scene validation report: {exc}",
                    log=log, code="scene-validation-report-invalid",
                ) from exc
            if not isinstance(report, dict) or not isinstance(report.get("ok"), bool):
                raise RenderError(
                    "Blender returned a scene validation report with an unexpected shape.",
                    log=log, code="scene-validation-report-invalid",
                )
            return report
    raise RenderError(
        "Blender finished without returning a scene validation report.",
        log=log, code="scene-validation-report-missing",
    )


def _scene_snapshot_from_log(log: str) -> dict[str, object]:
    prefix = "BLENTOPY_SCENE_SNAPSHOT="
    for line in log.splitlines():
        if line.startswith(prefix):
            try:
                snapshot = json.loads(line[len(prefix):])
            except json.JSONDecodeError as exc:
                raise RenderError(f"Blender returned an invalid scene snapshot: {exc}", log=log) from exc
            if not isinstance(snapshot, dict):
                raise RenderError("Blender returned a scene snapshot with an unexpected shape.", log=log)
            return snapshot
    raise RenderError("Blender finished without returning a scene snapshot.", log=log)


def _existing_project_environment(
    project: Path,
    output: Path,
    workspace: Path,
    *,
    mode: str,
    script: Path | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "BLENTOPY_MODE": mode,
        "BLENTOPY_INPUT_BLEND": str(project),
        "BLENTOPY_WORKSPACE": str(workspace),
        "BLENTOPY_OUTPUT": str(project.with_suffix(".mp4")),
        "BLENTOPY_BLEND": str(output),
        "BLENTOPY_WIDTH": "1080",
        "BLENTOPY_HEIGHT": "1080",
        "BLENTOPY_FPS": "30",
        "BLENTOPY_DURATION": "8",
    })
    if script is not None:
        env["BLENTOPY_SCRIPT"] = str(script)
    else:
        env.pop("BLENTOPY_SCRIPT", None)
    return env


@_serialized_targets(_inspect_targets)
def inspect_scene(
    blend_path: str | Path,
    *,
    workspace: str | Path | None = None,
    blender: str | None = None,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Inspect an existing .blend project without saving or modifying it."""
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise ValueError("timeout_seconds must be a positive integer.")
    project = Path(blend_path).expanduser().resolve(strict=True)
    if not project.is_file() or project.suffix.lower() != ".blend":
        raise ValueError(f"blend_path must point to an existing .blend file: {project}")
    workspace_dir = Path(workspace or project.parent).expanduser().resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    executable = _find_compatible_blender(blender)
    worker = Path(__file__).with_name("edit_worker.py").resolve()
    if not worker.is_file():
        raise RenderError("The installed blentopy package is missing edit_worker.py. Reinstall blentopy.")

    env = _existing_project_environment(project, project, workspace_dir, mode="inspect")
    command = [
        executable, "--background", "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(worker),
    ]
    return_code, log = _stream_blender_process(
        command, env=env, timeout_seconds=timeout_seconds, progress_callback=None,
    )
    if return_code != 0:
        raise RenderError(f"Blender scene inspection failed with exit code {return_code}.", log=log)
    return _scene_snapshot_from_log(log)


@_serialized_targets(_edit_targets)
def edit_scene_script(
    script_path: str | Path,
    blend_path: str | Path,
    *,
    workspace: str | Path | None = None,
    blender: str | None = None,
    timeout_seconds: int = 600,
) -> SceneEditResult:
    """Apply a validated script to an existing .blend and atomically replace it."""
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise ValueError("timeout_seconds must be a positive integer.")
    source = Path(script_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise FileNotFoundError(f"Edit script is not a regular file: {source}")
    validate_script(source.read_text(encoding="utf-8"))

    project = Path(blend_path).expanduser().resolve(strict=True)
    if not project.is_file() or project.suffix.lower() != ".blend":
        raise ValueError(f"blend_path must point to an existing .blend file: {project}")
    if source == project:
        raise ValueError("The edit script and target .blend project must be different files.")
    workspace_dir = Path(workspace or source.parent).expanduser().resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    executable = _find_compatible_blender(blender)
    worker = Path(__file__).with_name("edit_worker.py").resolve()
    if not worker.is_file():
        raise RenderError("The installed blentopy package is missing edit_worker.py. Reinstall blentopy.")

    token = uuid.uuid4().hex
    staged_blend = project.with_name(f".{project.stem}.{token}.edited.blend")
    env = _existing_project_environment(project, staged_blend, workspace_dir, mode="edit", script=source)
    command = [
        executable, "--background", "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(worker),
    ]
    try:
        return_code, log = _stream_blender_process(
            command, env=env, timeout_seconds=timeout_seconds, progress_callback=None,
        )
        if return_code != 0:
            raise RenderError(f"Blender scene edit failed with exit code {return_code}.", log=log)
        snapshot = _scene_snapshot_from_log(log)
        report = _scene_report_from_log(log)
        if not report.get("ok", False):
            raise RenderError(
                "Blender rejected the edited scene during post-save validation: "
                + "; ".join(str(item) for item in report.get("errors", [])),
                log=log,
                code="scene-validation-failed",
            )
        if not staged_blend.is_file() or staged_blend.stat().st_size == 0:
            raise RenderError(f"Blender did not create a valid edited project: {staged_blend}", log=log)
        os.replace(staged_blend, project)
        return SceneEditResult(executable, project, snapshot, log)
    finally:
        staged_blend.unlink(missing_ok=True)


@_serialized_targets(_render_targets)
def render_script(
    script_path: str | Path, *, output_path: str | Path,
    blend_path: str | Path | None = None, workspace: str | Path | None = None,
    blender: str | None = None, width: int = 1080, height: int = 1920,
    fps: int = 30, duration_seconds: int = 8, timeout_seconds: int = 3_600,
    progress_callback: Callable[[RenderProgress], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RenderResult:
    validate_render_settings(width, height, fps, duration_seconds)
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
        raise ValueError("timeout_seconds must be a positive integer.")

    source, output, blend, workspace_dir = _resolve_scene_paths(
        script_path, output_path, blend_path, workspace
    )
    if output == blend:
        raise ValueError("The MP4 output path and .blend project path must be different.")

    executable = _find_compatible_blender(blender)
    worker = Path(__file__).with_name("worker.py").resolve()
    command = [
        executable, "--background", "--factory-startup", "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(worker),
    ]

    # Render to unique staging paths. A failed run must not be reported as
    # successful merely because an older output already exists at the target.
    token = uuid.uuid4().hex
    staged_output = output.with_name(f".{output.stem}.{token}{output.suffix}")
    staged_blend = blend.with_name(f".{blend.stem}.{token}{blend.suffix}")
    try:
        env = _prepare_scene_environment(
            source, staged_output, staged_blend, workspace_dir,
            width, height, fps, duration_seconds,
        )
        return_code, log = _stream_blender_process(
            command,
            env=env,
            timeout_seconds=timeout_seconds,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
        if return_code != 0:
            raise RenderError(f"Blender failed with exit code {return_code}.", log=log)

        if not staged_output.is_file():
            raise RenderError(f"MP4 output was not created: {output}", log=log)
        if staged_output.stat().st_size == 0:
            raise RenderError(f"MP4 output is empty (0 bytes): {output}", log=log)
        if not staged_blend.is_file():
            raise RenderError(f"Blend project was not created: {blend}", log=log)
        if staged_blend.stat().st_size == 0:
            raise RenderError(f"Blend project is empty (0 bytes): {blend}", log=log)

        # Publish only complete artifacts. Existing outputs remain untouched
        # until both newly generated files have passed validation.
        os.replace(staged_output, output)
        os.replace(staged_blend, blend)
        return RenderResult(executable, output, blend, return_code, log)
    finally:
        staged_output.unlink(missing_ok=True)
        staged_blend.unlink(missing_ok=True)

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


@_serialized_targets(_preview_targets)
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
    executable = _find_compatible_blender(blender)
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
        executable, "--factory-startup", "--disable-autoexec",
        "--python-exit-code", "1", "--python", str(worker),
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
