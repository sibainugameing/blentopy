"""Local stdio MCP server for MCP-capable chat applications."""

import asyncio
import json
import os
import re
import sys
import threading
from importlib.resources import files as package_files
from datetime import datetime
from pathlib import Path

from .discovery import BlenderNotFoundError, blender_version, find_blender
from .runner import (
    RenderError, RenderProgress, edit_scene_script, inspect_scene,
    format_error_report, preview_script, render_script, validate_render_settings,
)
from .validation import ScriptValidationError, validate_script


def _make_render_progress_callback(ctx: object, loop: asyncio.AbstractEventLoop):
    """Bridge runner progress events to MCP notifications from the worker thread."""
    stage_progress = {
        "building_scene": (0.02, "Building scene"),
        "validating_scene": (0.06, "Validating scene"),
        "saving_project": (0.10, "Saving editable Blender project"),
        "rendering": (0.12, "Rendering video"),
        "completed": (1.0, "Render completed"),
    }
    last_progress = 0.0

    def report(event: RenderProgress) -> None:
        nonlocal last_progress
        if event.frame is not None and event.total_frames:
            fraction = min(1.0, max(0.0, event.frame / event.total_frames))
            progress = 0.12 + 0.87 * fraction
            message = f"Rendering frames: {event.frame}/{event.total_frames}"
        else:
            value = stage_progress.get(event.stage)
            if value is None:
                return
            progress, message = value

        if progress <= last_progress:
            return
        last_progress = progress
        future = asyncio.run_coroutine_threadsafe(
            ctx.report_progress(progress, total=1.0, message=message),
            loop,
        )
        try:
            future.result()
        except Exception:
            # A disconnected MCP client must not fail an otherwise valid render.
            future.cancel()

    return report


def workspace_path() -> Path:
    configured = os.environ.get("BLENTOPY_WORKSPACE")
    return (
        Path(configured).expanduser().resolve()
        if configured else (Path.cwd() / "blentopy-workspace").resolve()
    )


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")[:48] or "ai-scene"


def load_ai_system_prompt() -> str:
    """Load the packaged scene-authoring guide for installed and editable clients."""
    try:
        return package_files("blentopy").joinpath("AI_SYSTEM_PROMPT.md").read_text(
            encoding="utf-8"
        ).strip()
    except (OSError, ModuleNotFoundError):
        return (
            "Create composed, animated scenes rather than a single rotating primitive. "
            "Prefer studio.scene, studio.geo, and studio.mat; use stable object IDs, "
            "semantic placement, camera framing, PBR materials, and second-based motion. "
            "Use only documented API calls, conditionals, and statically bounded range() "
            "loops (at most 3 nested levels and 4096 expanded iterations). Never use imports, "
            "raw bpy, filesystem access, shell commands, functions, or unbounded loops."
        )


def main() -> None:
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver import Context
    except ImportError:
        print("MCP support is optional. Install with: pip install 'blentopy[mcp]'", file=sys.stderr)
        raise SystemExit(2)

    server = MCPServer(
        "blentopy",
        instructions=(
            "You are the scene director and Blender automation agent for blentopy. "
            "Use the complete authoring guide below as the required scene-generation contract. "
            "Prefer thoughtful art direction, layered composition, camera movement, detailed geometry, "
            "purposeful materials, and deliberate lighting over generic primitive turntables. "
            "Use blentopy_preview_scene only when the user specifically wants to inspect or edit the "
            "scene in the Blender GUI. For follow-up changes to a saved project, call "
            "blentopy_inspect_scene first and then blentopy_edit_scene; preserve unrelated geometry. "
            "Otherwise render with blentopy_render_scene.\n\n"
            + load_ai_system_prompt()
        ),
    )

    @server.tool()
    def blentopy_environment() -> str:
        """Detect Blender and report its version, executable, and workspace."""
        try:
            executable = find_blender()
            return f"Blender {blender_version(executable)}\nExecutable: {executable}\nWorkspace: {workspace_path()}"
        except BlenderNotFoundError as exc:
            return f"Blender not ready: {exc}"

    @server.tool()
    async def blentopy_render_scene(
        python_code: str, ctx: Context, name: str = "ai-scene",
        width: int = 1080, height: int = 1920, fps: int = 30,
        duration_seconds: int = 8,
    ) -> str:
        """Run an AI-native scene script and export MP4 + .blend.

        Prefer studio.scene, studio.geo, and studio.mat. Build Object3D handles
        with scene.mesh()/group()/camera()/light(), compose geometry and PBR
        materials, use semantic placement and scene.motion() tracks, and retain
        stable object IDs. The legacy studio.add_* API remains supported.
        Imports, raw bpy, filesystem/process/network access, functions, while loops,
        and unbounded loops are rejected. Bounded conditionals and nested range loops
        are supported under the validator budgets.
        """
        script: Path | None = None
        try:
            validate_script(python_code)
            validate_render_settings(width, height, fps, duration_seconds)
            workspace = workspace_path()
            scripts, renders = workspace / "scripts", workspace / "renders"
            scripts.mkdir(parents=True, exist_ok=True)
            renders.mkdir(parents=True, exist_ok=True)
            slug = safe_name(name)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            script = scripts / f"{slug}-{stamp}.py"
            video = renders / f"{slug}-{stamp}.mp4"
            blend = renders / f"{slug}-{stamp}.blend"
            script.write_text(python_code.rstrip() + "\n", encoding="utf-8")

            loop = asyncio.get_running_loop()
            progress_callback = _make_render_progress_callback(ctx, loop)
            cancel_event = threading.Event()
            try:
                result = await asyncio.to_thread(
                    render_script,
                    script,
                    output_path=video,
                    blend_path=blend,
                    workspace=workspace,
                    width=width,
                    height=height,
                    fps=fps,
                    duration_seconds=duration_seconds,
                    timeout_seconds=3600,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                )
            except asyncio.CancelledError:
                cancel_event.set()
                raise
            except asyncio.CancelledError:
                cancel_event.set()
                raise
            return (
                f"Render completed.\nVideo: {result.output_path}\n"
                f"Blender project: {result.blend_path}\nSource script: {script}\n"
                f"Log:\n{result.log[-6000:]}"
            )
        except (ScriptValidationError, ValueError, OSError, BlenderNotFoundError, RenderError) as exc:
            return "Render failed:\n" + format_error_report(exc, script_path=script)

    @server.tool()
    def blentopy_preview_scene(
        python_code: str, name: str = "ai-preview",
        width: int = 1080, height: int = 1920, fps: int = 30,
        duration_seconds: int = 8,
    ) -> str:
        """Open an AI-native scene script in the Blender GUI without rendering MP4.

        Prefer studio.scene / studio.geo / studio.mat and stable Object3D handles.
        The legacy Studio API remains supported. Use this when the user wants to
        inspect or edit the scene in Blender; Blender remains open after saving.
        """
        script: Path | None = None
        try:
            validate_script(python_code)
            validate_render_settings(width, height, fps, duration_seconds)
            workspace = workspace_path()
            scripts, renders = workspace / "scripts", workspace / "renders"
            scripts.mkdir(parents=True, exist_ok=True)
            renders.mkdir(parents=True, exist_ok=True)
            slug = safe_name(name)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            script = scripts / f"{slug}-{stamp}.py"
            video = renders / f"{slug}-{stamp}.mp4"
            blend = renders / f"{slug}-{stamp}.blend"
            script.write_text(python_code.rstrip() + "\n", encoding="utf-8")

            result = preview_script(
                script, output_path=video, blend_path=blend, workspace=workspace,
                width=width, height=height, fps=fps, duration_seconds=duration_seconds,
            )
            return (
                f"Blender GUI ready: {result.blender_executable}\n"
                f"Process ID: {result.process_id}\n"
                f"Saved scene: {result.blend_path}\n"
                f"Blender log: {result.log_path}\n"
                "No MP4 render was started. Blender remains open for inspection and editing."
            )
        except (ScriptValidationError, ValueError, OSError, BlenderNotFoundError, RenderError) as exc:
            return "Preview failed:\n" + format_error_report(exc, script_path=script)

    @server.tool()
    async def blentopy_inspect_scene(blend_path: str) -> str:
        """Inspect an existing .blend and report object IDs, transforms, dimensions, modifiers and materials.

        Call this before making follow-up edits so the AI can target existing objects.
        The project must be inside BLENTOPY_WORKSPACE.
        """
        try:
            workspace = workspace_path()
            project = Path(blend_path).expanduser().resolve(strict=True)
            if project.suffix.lower() != ".blend" or not project.is_relative_to(workspace):
                raise ValueError(f"The .blend file must be inside BLENTOPY_WORKSPACE ({workspace}).")
            snapshot = await asyncio.to_thread(inspect_scene, project, workspace=workspace)
            return json.dumps(snapshot, ensure_ascii=False, indent=2)
        except (ValueError, OSError, BlenderNotFoundError, RenderError) as exc:
            return "Scene inspection failed:\n" + format_error_report(exc)

    @server.tool()
    async def blentopy_edit_scene(
        blend_path: str,
        python_code: str,
        name: str = "ai-edit",
    ) -> str:
        """Apply targeted edits to an existing .blend without reconstructing its scene.

        Inspect first, then use scene.find(id=...), scene.update(), scene.set_material(),
        scene.duplicate(), scene.remove(), and the documented modeling API.
        The edit is saved atomically. Reload the .blend in any already-open Blender GUI.
        """
        script: Path | None = None
        try:
            validate_script(python_code)
            workspace = workspace_path()
            project = Path(blend_path).expanduser().resolve(strict=True)
            if project.suffix.lower() != ".blend" or not project.is_relative_to(workspace):
                raise ValueError(f"The .blend file must be inside BLENTOPY_WORKSPACE ({workspace}).")
            scripts = workspace / "scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            script = scripts / f"{safe_name(name)}-{stamp}.py"
            script.write_text(python_code.rstrip() + "\n", encoding="utf-8")
            result = await asyncio.to_thread(
                edit_scene_script, script, project, workspace=workspace,
            )
            return (
                f"Scene edit completed and saved: {result.blend_path}\n"
                "Only the requested changes were applied to the existing scene.\n"
                "Reload the .blend in an already-open Blender GUI to see the saved changes.\n"
                "Updated scene snapshot:\n"
                + json.dumps(result.snapshot, ensure_ascii=False, indent=2)
                + f"\nEdit script: {script}"
            )
        except (ScriptValidationError, ValueError, OSError, BlenderNotFoundError, RenderError) as exc:
            return "Scene edit failed:\n" + format_error_report(exc, script_path=script)

    @server.tool()
    def blentopy_list_outputs() -> str:
        """List recent MP4 and .blend outputs."""
        folder = workspace_path() / "renders"
        if not folder.exists():
            return f"No renders yet. Workspace: {workspace_path()}"
        files = sorted(
            (item for item in folder.iterdir() if item.is_file()),
            key=lambda item: item.stat().st_mtime, reverse=True,
        )[:30]
        if not files:
            return "No render outputs yet."
        return "\n".join(
            f"{item.name} ({item.stat().st_size:,} bytes)" for item in files
        )

    server.run()


if __name__ == "__main__":
    main()
