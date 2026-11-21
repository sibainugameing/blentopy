"""Prepare a scene in interactive Blender and leave the GUI open."""

from __future__ import annotations

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
        from blentopy.studio import Studio
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
        studio = Studio(
            workspace=str(workspace), output_path=str(output), blend_path=str(blend),
            width=width, height=height, fps=fps, duration_seconds=duration,
        )
        code = compile(tree, str(script_path), "exec")
        namespace = {"studio": studio, "math": math, "__builtins__": {}}
        exec(code, namespace, namespace)

        # Keep the content scene active so the GUI opens on the editable 3D scene.
        if bpy.context.window is not None:
            bpy.context.window.scene = studio.scene
        studio.scene.frame_set(studio.scene.frame_start)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        print(f"BLENTOPY_PREVIEW_READY={blend}", flush=True)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
