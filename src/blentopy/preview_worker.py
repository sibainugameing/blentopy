"""Prepare a scene in interactive Blender and leave the GUI open."""

from __future__ import annotations

import builtins
import json
import math
import os
import sys
import traceback
from pathlib import Path


def _write_status(status_path: str | None, payload: dict[str, str]) -> None:
    if not status_path:
        return
    destination = Path(status_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, destination)


def main() -> int:
    status_path = os.environ.get("BLENTOPY_PREVIEW_STATUS")
    try:
        package_parent = str(Path(__file__).resolve().parents[1])
        if package_parent not in sys.path:
            sys.path.insert(0, package_parent)

        import bpy
        import mathutils
        from blentopy.ai_native import AIStudio
        from blentopy.validation import validate_script

        script_path = Path(os.environ["BLENTOPY_SCRIPT"]).resolve(strict=True)
        workspace = Path(os.environ["BLENTOPY_WORKSPACE"]).resolve()
        output = Path(os.environ["BLENTOPY_OUTPUT"]).resolve()
        blend = Path(os.environ["BLENTOPY_BLEND"]).resolve()
        width = int(os.environ["BLENTOPY_WIDTH"])
        height = int(os.environ["BLENTOPY_HEIGHT"])
        fps = int(os.environ["BLENTOPY_FPS"])
        duration = int(os.environ["BLENTOPY_DURATION"])

        tree = validate_script(script_path.read_text(encoding="utf-8"))
        studio = AIStudio(
            workspace=str(workspace), output_path=str(output), blend_path=str(blend),
            width=width, height=height, fps=fps, duration_seconds=duration,
        )
        code = compile(tree, str(script_path), "exec")
        namespace = {
            "__name__": "__blentopy_scene__",
            "__file__": str(script_path),
            "__package__": None,
            "__builtins__": builtins.__dict__,
            "studio": studio,
            "bpy": bpy,
            "math": math,
            "mathutils": mathutils,
        }
        exec(code, namespace, namespace)
        scene_snapshot = studio.scene.inspect()
        report = studio.scene.validate()
        print("BLENTOPY_SCENE_SNAPSHOT=" + json.dumps(scene_snapshot, ensure_ascii=False), flush=True)
        print("BLENTOPY_SCENE_REPORT=" + json.dumps(report, ensure_ascii=False), flush=True)
        if not report.get("ok", False):
            errors = "; ".join(str(item) for item in report.get("errors", []))
            raise RuntimeError("AI-native scene validation failed: " + (errors or "report.ok is false"))

        for window in bpy.context.window_manager.windows:
            window.scene = studio.blender_scene

        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                space = area.spaces.active
                if studio.blender_scene.camera is not None:
                    space.region_3d.view_perspective = "CAMERA"
                try:
                    space.shading.color_type = "MATERIAL"
                except (AttributeError, TypeError, ValueError):
                    pass

        studio.blender_scene.frame_set(studio.blender_scene.frame_start)
        bpy.context.view_layer.update()
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        if not blend.is_file():
            raise RuntimeError(f"Blender did not create the project file: {blend}")

        _write_status(status_path, {"status": "ready", "blend": str(blend)})
        print(f"BLENTOPY_PREVIEW_READY={blend}", flush=True)
        return 0
    except Exception as exc:
        from blentopy.error_diagnostics import emit_worker_error

        emit_worker_error(exc)
        error = traceback.format_exc()
        print(error, file=sys.stderr, flush=True)
        try:
            _write_status(
                status_path,
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
            )
        except Exception:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    main()
