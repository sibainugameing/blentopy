"""Prepare a scene in interactive Blender and leave the GUI open."""

from __future__ import annotations

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

        # Keep the editable content scene active in every Blender window.
        for window in bpy.context.window_manager.windows:
            window.scene = studio.scene

        # Open in camera view when the scene defines a camera and show material colors.
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                space = area.spaces.active
                if studio.scene.camera is not None:
                    space.region_3d.view_perspective = "CAMERA"
                try:
                    space.shading.color_type = "MATERIAL"
                except (AttributeError, TypeError, ValueError):
                    pass

        studio.scene.frame_set(studio.scene.frame_start)
        bpy.context.view_layer.update()
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
        if not blend.is_file():
            raise RuntimeError(f"Blender did not create the project file: {blend}")

        _write_status(status_path, {"status": "ready", "blend": str(blend)})
        print(f"BLENTOPY_PREVIEW_READY={blend}", flush=True)
        return 0
    except Exception as exc:
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
    # Do not raise SystemExit here: Blender treats it as an application exit.
    # Returning from the script leaves the interactive GUI event loop running.
    main()
