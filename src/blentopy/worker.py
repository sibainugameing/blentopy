"""Entry point launched by Blender in background mode."""

from __future__ import annotations

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

        from blentopy.ai_native import AIStudio
        from blentopy.validation import validate_script, _bounded_range, _bounded_loop_iterator

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
        loop_budget = {"iterations": 0, "expansion_cost": 0}
        namespace = {
            "studio": studio,
            "math": math,
            "range": _bounded_range,
            "__blentopy_bounded_iter__": lambda iterable, node_cost: (
                _bounded_loop_iterator(iterable, node_cost, loop_budget)
            ),
            "__builtins__": {},
        }
        print("BLENTOPY_STAGE=building_scene", flush=True)
        exec(code, namespace, namespace)
        print("BLENTOPY_STAGE=validating_scene", flush=True)
        scene_snapshot = studio.scene.inspect()
        report = studio.scene.validate()
        print("BLENTOPY_SCENE_SNAPSHOT=" + json.dumps(scene_snapshot, ensure_ascii=False), flush=True)
        print("BLENTOPY_SCENE_REPORT=" + json.dumps(report, ensure_ascii=False), flush=True)
        if not report.get("ok", False):
            errors = "; ".join(str(item) for item in report.get("errors", []))
            raise RuntimeError("AI-native scene validation failed: " + (errors or "report.ok is false"))
        rendered, saved_blend = studio.render()
        print(f"BLENTOPY_RENDER_OK={rendered}", flush=True)
        print(f"BLENTOPY_BLEND_OK={saved_blend}", flush=True)
        print("BLENTOPY_STAGE=completed", flush=True)
        return 0
    except Exception as exc:
        from blentopy.error_diagnostics import emit_worker_error

        emit_worker_error(exc)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
