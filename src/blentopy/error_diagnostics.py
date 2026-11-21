"""Structured error context emitted by Blender worker processes."""

from __future__ import annotations

import json
import sys
from typing import TextIO


def emit_worker_error(exc: Exception, *, stream: TextIO | None = None) -> dict[str, object]:
    """Emit machine-readable repair context while preserving normal tracebacks."""
    code = getattr(exc, "code", None)
    if not code:
        if type(exc).__name__ == "ScriptValidationError":
            code = "script-validation-failed"
        elif "validation failed" in str(exc).lower():
            code = "scene-validation-failed"
        elif isinstance(exc, (TypeError, ValueError)):
            code = "invalid-scene-operation"
        else:
            code = "blender-execution-failed"
    payload: dict[str, object] = {
        "code": str(code),
        "type": type(exc).__name__,
        "message": str(exc),
    }
    for name in ("lineno", "col_offset", "source_line", "suggestion"):
        value = getattr(exc, name, None)
        if value is not None:
            payload[name] = value
    print(
        "BLENTOPY_ERROR=" + json.dumps(payload, ensure_ascii=False),
        file=stream or sys.stdout,
        flush=True,
    )
    return payload
