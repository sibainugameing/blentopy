"""Apply a validated scene-edit script to an existing Blender project."""

from __future__ import annotations

import builtins
import json
import math
import os
import sys
import traceback
from pathlib import Path


def main() -> int:
    try:
        package_parent = str(Path(__file__).resolve().parents[1])
        if package_parent not in sys.path:
            sys.path.insert(0, package_parent)

        import bpy
        import mathutils
        from blentopy.ai_native import AIStudio
        from blentopy.validation import validate_script

        mode = os.environ.get("BLENTOPY_MODE", "edit")
        if mode not in {"edit", "inspect"}:
            raise ValueError(f"Unsupported scene-worker mode: {mode}")

        source_blend = Path(os.environ["BLENTOPY_INPUT_BLEND"]).resolve(strict=True)
        output = Path(os.environ["BLENTOPY_BLEND"]).resolve()
        workspace = Path(os.environ["BLENTOPY_WORKSPACE"]).resolve()
        width = int(os.environ["BLENTOPY_WIDTH"])
        height = int(os.environ["BLENTOPY_HEIGHT"])
        fps = int(os.environ["BLENTOPY_FPS"])
        duration = int(os.environ["BLENTOPY_DURATION"])

        code = None
        if mode == "edit":
            script_path = Path(os.environ["BLENTOPY_SCRIPT"]).resolve(strict=True)
            tree = validate_script(script_path.read_text(encoding="utf-8"))
            code = compile(tree, str(script_path), "exec")

        studio = AIStudio(
            workspace=str(workspace),
            output_path=os.environ["BLENTOPY_OUTPUT"],
            blend_path=str(output),
            width=width,
            height=height,
            fps=fps,
            duration_seconds=duration,
            existing_project=str(source_blend),
        )

        bpy = studio._backend._bpy
        if code is not None:
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
            print("BLENTOPY_STAGE=applying_scene_edit", flush=True)
            exec(code, namespace, namespace)

        bpy.context.view_layer.update()
        snapshot = studio.scene.inspect()
        report = studio.scene.validate()
        print("BLENTOPY_SCENE_SNAPSHOT=" + json.dumps(snapshot, ensure_ascii=False), flush=True)
        print("BLENTOPY_SCENE_REPORT=" + json.dumps(report, ensure_ascii=False), flush=True)

        # Inspection is read-only and may report an incomplete scene. Edits,
        # however, must never publish a project that failed scene validation.
        if mode == "edit" and not report.get("ok", False):
            errors = "; ".join(str(item) for item in report.get("errors", []))
            raise RuntimeError(
                "Edited scene failed validation; the staged .blend will not be saved. "
                + (errors or "Validation did not return ok=true.")
            )

        if mode == "edit":
            for window in bpy.context.window_manager.windows:
                window.scene = studio.blender_scene
            bpy.ops.wm.save_as_mainfile(filepath=str(output))
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError(f"Blender did not create the edited project: {output}")
            print(f"BLENTOPY_EDIT_OK={output}", flush=True)
        else:
            print(f"BLENTOPY_INSPECT_OK={source_blend}", flush=True)
        return 0
    except Exception as exc:
        from blentopy.error_diagnostics import emit_worker_error

        emit_worker_error(exc)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
