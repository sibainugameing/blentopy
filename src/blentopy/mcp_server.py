"""Local stdio MCP server for MCP-capable chat applications."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .discovery import BlenderNotFoundError, blender_version, find_blender
from .runner import RenderError, format_error_report, preview_script, render_script, validate_render_settings
from .validation import ScriptValidationError, validate_script


def workspace_path() -> Path:
    configured = os.environ.get("BLENTOPY_WORKSPACE")
    return (
        Path(configured).expanduser().resolve()
        if configured else (Path.cwd() / "blentopy-workspace").resolve()
    )


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")[:48] or "ai-scene"


def load_ai_system_prompt() -> str:
    """Load the repository's complete scene-authoring guide for MCP clients."""
    prompt_path = Path(__file__).resolve().parents[2] / "docs" / "AI_SYSTEM_PROMPT.md"
    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
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
            "scene in the Blender GUI. Otherwise render with blentopy_render_scene.\n\n"
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
    def blentopy_render_scene(
        python_code: str, name: str = "ai-scene",
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

            result = render_script(
                script, output_path=video, blend_path=blend, workspace=workspace,
                width=width, height=height, fps=fps,
                duration_seconds=duration_seconds, timeout_seconds=3600,
            )
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
