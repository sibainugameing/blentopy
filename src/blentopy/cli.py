"""Command line interface for blentopy."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from .discovery import BlenderNotFoundError, blender_version, find_blender
from .runner import RenderError, preview_script, render_script

DEFAULT_EXAMPLE = Path(__file__).with_name("demo_scene.py")


def add_render_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--blender", help="Path to Blender executable.")
    parser.add_argument("--output", help="Output MP4 path.")
    parser.add_argument("--blend-output", help="Output .blend path.")
    parser.add_argument("--workspace", help="Workspace for audio assets.")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration", type=int, default=8, help="Duration in seconds.")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blentopy", description="Create Blender scenes and render MP4 videos with Python."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Check the Blender environment.")
    doctor.add_argument("--blender", help="Path to Blender executable.")
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
    preview.add_argument("--width", type=int, default=1080)
    preview.add_argument("--height", type=int, default=1920)
    preview.add_argument("--fps", type=int, default=30)
    preview.add_argument("--duration", type=int, default=8, help="Scene duration in seconds.")
    preview.add_argument(
        "--startup-timeout", type=int, default=120,
        help="Seconds to wait for Blender to save the preview scene (1-600).",
    )
    return parser


def _render(args: argparse.Namespace, script: Path) -> int:
    output = Path(args.output) if args.output else Path("renders") / f"{script.stem}.mp4"
    blend = Path(args.blend_output) if args.blend_output else output.with_suffix(".blend")
    workspace = Path(args.workspace) if args.workspace else Path("blentopy-workspace")
    try:
        result = render_script(
            script, output_path=output, blend_path=blend, workspace=workspace,
            blender=args.blender, width=args.width, height=args.height,
            fps=args.fps, duration_seconds=args.duration, timeout_seconds=args.timeout,
        )
    except (ValueError, FileNotFoundError, BlenderNotFoundError, RenderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        log = getattr(exc, "log", "")
        if log:
            print(log[-12_000:], file=sys.stderr)
        return 1
    print(f"Blender: {result.blender_executable}")
    print(f"Video:   {result.output_path}")
    print(f"Project: {result.blend_path}")
    if result.log:
        print(result.log[-4_000:])
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
        print(f"Error: {exc}", file=sys.stderr)
        log = getattr(exc, "log", "")
        if log:
            print(log[-12_000:], file=sys.stderr)
        return 1
    print(f"Blender GUI ready: {result.blender_executable}")
    print(f"Blender PID: {result.process_id}")
    print(f"Saved scene: {result.blend_path}")
    print(f"Blender log: {result.log_path}")
    print("The GUI remains open. Close Blender normally when finished.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        try:
            executable = find_blender(args.blender)
            version = blender_version(executable)
        except BlenderNotFoundError as exc:
            print(f"Blender: NOT FOUND\n{exc}", file=sys.stderr)
            return 1
        print(f"Blender: {version}\nExecutable: {executable}")
        print(f"CLI module: {Path(__file__).resolve()}")
        print(f"MCP SDK: {'installed' if importlib.util.find_spec('mcp') else 'not installed (optional)'}")
        return 0
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
