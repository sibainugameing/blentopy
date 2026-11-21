"""Entry point launched by Blender in background mode."""

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
        namespace = {"studio": studio, "math": math, "range": range, "__builtins__": {}}
        exec(code, namespace, namespace)
        rendered, saved_blend = studio.render()
        print(f"BLENTOPY_RENDER_OK={rendered}", flush=True)
        print(f"BLENTOPY_BLEND_OK={saved_blend}", flush=True)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
