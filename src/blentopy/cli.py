"""Command line interface for blentopy."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from . import __version__
from .discovery import BlenderNotFoundError, blender_version, find_blender
from .templates import TEMPLATES
from .validation import ScriptValidationError, validate_script
from .runner import (
    RenderError,
    RenderProgress,
    format_error_report,
    preview_script,
    render_script,
)

DEFAULT_EXAMPLE = Path(__file__).with_name("demo_scene.py")


MIN_BLENDER_LABEL = "4.2"


def _version_supported(version: str) -> bool:
    """True when the reported Blender version meets the runner's minimum."""
    match = re.search(r"(\d+)\.(\d+)", version)
    return bool(match) and (int(match[1]), int(match[2])) >= (4, 2)


def _positive_int(value: str) -> int:
    """argparse type: reject zero, negative, and non-integer values early."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer.") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value!r} must be 1 or greater.")
    return number


def add_render_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--blender", help="Path to Blender executable.")
    parser.add_argument("--output", help="Output MP4 path.")
    parser.add_argument("--blend-output", help="Output .blend path.")
    parser.add_argument("--workspace", help="Workspace for audio assets.")
    parser.add_argument("--width", type=_positive_int, default=1080)
    parser.add_argument("--height", type=_positive_int, default=1920)
    parser.add_argument("--fps", type=_positive_int, default=30)
    parser.add_argument("--duration", type=_positive_int, default=8, help="Duration in seconds.")
    parser.add_argument("--timeout", type=_positive_int, default=3600, help="Timeout in seconds.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blentopy", description="Create Blender scenes and render MP4 videos with Python."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="Create a starter scene script.")
    new.add_argument("name", nargs="?", help="Script name or path (.py is added if missing).")
    new.add_argument(
        "--template", choices=sorted(TEMPLATES), default="minimal",
        help="Starter template (default: minimal).",
    )
    new.add_argument("--force", action="store_true", help="Overwrite an existing file.")
    new.add_argument("--list", action="store_true", help="List templates and exit.")
    check = sub.add_parser(
        "check",
        help="Check scene script syntax without launching Blender (use '-' for stdin).",
    )
    check.add_argument("script", help="Path to a scene script, or '-' to read stdin.")
    check.add_argument(
        "--json", action="store_true",
        help="Print the result as JSON (handy for AI tools and editors).",
    )
    doctor = sub.add_parser("doctor", help="Check the Blender environment.")
    doctor.add_argument("--blender", help="Path to Blender executable.")
    doctor.add_argument("--json", action="store_true", help="Print the result as JSON.")
    demo = sub.add_parser("demo", help="Render the built-in demo scene.")
    add_render_options(demo)
    render = sub.add_parser("render", help="Render a Python scene script.")
    render.add_argument("script", type=Path)
    add_render_options(render)
    preview = sub.add_parser(
        "preview", help="Open the scene in the interactive Blender GUI without rendering a video."
    )
    preview.add_argument("script", type=Path)
    preview.add_argument("--blender", help="Path to Blender executable.")
    preview.add_argument("--blend-output", help="Output .blend path.")
    preview.add_argument("--workspace", help="Workspace for audio assets.")
    preview.add_argument("--width", type=_positive_int, default=1080)
    preview.add_argument("--height", type=_positive_int, default=1920)
    preview.add_argument("--fps", type=_positive_int, default=30)
    preview.add_argument("--duration", type=_positive_int, default=8, help="Scene duration in seconds.")
    preview.add_argument(
        "--startup-timeout", type=int, default=120,
        help="Seconds to wait for Blender to save the preview scene (1-600).",
    )
    sub.add_parser(
        "gui",
        help="Open the optional desktop interface (the GUI delegates to the CLI).",
    )
    return parser


def _check(args: argparse.Namespace) -> int:
    """Run the fast syntax preflight so mistakes surface before a slow render."""
    label = "<stdin>" if args.script == "-" else args.script
    try:
        source = (
            sys.stdin.read()
            if args.script == "-"
            else Path(args.script).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "file": label, "error": f"Cannot read: {exc}"}))
        else:
            print(f"Cannot read {label}: {exc}", file=sys.stderr)
        return 1
    try:
        validate_script(source)
    except ScriptValidationError as exc:
        if args.json:
            print(json.dumps({
                "ok": False, "file": label, "error": str(exc), "code": exc.code,
                "line": exc.lineno, "column": exc.col_offset,
                "source_line": exc.source_line, "suggestion": exc.suggestion,
            }, ensure_ascii=False))
            return 1
        where = f":{exc.lineno}" if exc.lineno else ""
        print(f"{label}{where}: {exc}", file=sys.stderr)
        if exc.source_line is not None:
            print(f"    {exc.source_line.rstrip()}", file=sys.stderr)
            if exc.col_offset is not None:
                print(f"    {' ' * exc.col_offset}^", file=sys.stderr)
        if exc.suggestion:
            print(f"Hint: {exc.suggestion}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "file": label}))
        return 0
    print(f"{label}: syntax OK (Blender-side errors are only found when the scene runs).")
    return 0


def _new(args: argparse.Namespace) -> int:
    """Write a starter scene script so new users never face a blank file."""
    if args.list:
        for name in sorted(TEMPLATES):
            first = TEMPLATES[name].splitlines()[0].strip('"')
            print(f"{name:10s} {first}")
        return 0
    if not args.name:
        print("Give a script name, e.g. 'blentopy new my_scene'.", file=sys.stderr)
        return 2
    target = Path(args.name)
    if target.suffix != ".py":
        target = target.with_suffix(".py") if not target.suffix else Path(f"{target}.py")
    if target.exists() and not args.force:
        print(f"{target} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(TEMPLATES[args.template], encoding="utf-8")
    except OSError as exc:
        print(f"Cannot write {target}: {exc}", file=sys.stderr)
        return 1
    print(f"Created {target} ({args.template} template).")
    print(f"Next: blentopy check {target}  |  blentopy preview {target}  |  blentopy render {target}")
    return 0


def _show_render_progress(progress: RenderProgress) -> None:
    labels = {
        "building_scene": "Building scene",
        "validating_scene": "Validating scene",
        "saving_project": "Saving editable Blender project",
        "rendering": "Rendering video",
        "completed": "Render completed",
    }
    if progress.frame is not None and progress.total_frames:
        percentage = min(100, progress.frame * 100 // progress.total_frames)
        end = "\n" if progress.frame >= progress.total_frames else "\r"
        print(
            f"Frames: {progress.frame}/{progress.total_frames} ({percentage}%)",
            end=end,
            flush=True,
        )
        return
    label = labels.get(progress.stage, progress.stage.replace("_", " ").capitalize())
    print(f"[blentopy] {label}", flush=True)


def _render(args: argparse.Namespace, script: Path) -> int:
    output = Path(args.output) if args.output else Path("renders") / f"{script.stem}.mp4"
    blend = Path(args.blend_output) if args.blend_output else output.with_suffix(".blend")
    workspace = Path(args.workspace) if args.workspace else Path("blentopy-workspace")
    try:
        print(f"Starting Blender render: {script}", flush=True)
        result = render_script(
            script, output_path=output, blend_path=blend, workspace=workspace,
            blender=args.blender, width=args.width, height=args.height,
            fps=args.fps, duration_seconds=args.duration, timeout_seconds=args.timeout,
            progress_callback=_show_render_progress,
        )
    except (ValueError, FileNotFoundError, BlenderNotFoundError, RenderError) as exc:
        print(format_error_report(exc, script_path=script), file=sys.stderr)
        return 1
    print(f"Blender: {result.blender_executable}")
    print(f"Video:   {result.output_path}")
    print(f"Project: {result.blend_path}")
    print("Render completed successfully.")
    return 0


def _preview(args: argparse.Namespace) -> int:
    output = Path("renders") / f"{args.script.stem}.mp4"
    blend = Path(args.blend_output) if args.blend_output else output.with_suffix(".blend")
    workspace = Path(args.workspace) if args.workspace else Path("blentopy-workspace")
    try:
        result = preview_script(
            args.script, output_path=output, blend_path=blend, workspace=workspace,
            blender=args.blender, width=args.width, height=args.height,
            fps=args.fps, duration_seconds=args.duration,
            startup_timeout_seconds=args.startup_timeout,
        )
    except (ValueError, FileNotFoundError, BlenderNotFoundError, RenderError) as exc:
        print(format_error_report(exc, script_path=args.script), file=sys.stderr)
        return 1
    print(f"Blender GUI ready: {result.blender_executable}")
    print(f"Blender PID: {result.process_id}")
    print(f"Saved scene: {result.blend_path}")
    print(f"Blender log: {result.log_path}")
    print("The GUI remains open. Close Blender normally when finished.")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    mcp_installed = importlib.util.find_spec("mcp") is not None
    try:
        executable = find_blender(args.blender)
        version = blender_version(executable)
    except BlenderNotFoundError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "mcp_installed": mcp_installed}))
        else:
            print(f"Blender: NOT FOUND\n{exc}", file=sys.stderr)
        return 1
    supported = _version_supported(version)
    if args.json:
        print(json.dumps({
            "ok": supported, "blender_version": version, "executable": executable,
            "minimum_version": MIN_BLENDER_LABEL, "mcp_installed": mcp_installed,
            "blentopy_version": __version__,
        }))
        return 0 if supported else 1
    print(f"Blender: {version}\nExecutable: {executable}")
    print(f"blentopy: {__version__}")
    print(f"CLI module: {Path(__file__).resolve()}")
    print(f"MCP SDK: {'installed' if mcp_installed else 'not installed (optional)'}")
    if not supported:
        print(
            f"WARNING: Blender {version} is older than the required {MIN_BLENDER_LABEL}; "
            "render and preview will refuse to run.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "gui":
        from .gui import main as gui_main

        return gui_main()
    if args.command == "check":
        return _check(args)
    if args.command == "new":
        return _new(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "demo":
        if not DEFAULT_EXAMPLE.is_file():
            print(f"Demo script not found: {DEFAULT_EXAMPLE}", file=sys.stderr)
            return 1
        return _render(args, DEFAULT_EXAMPLE)
    if args.command == "render":
        return _render(args, args.script)
    if args.command == "preview":
        return _preview(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
