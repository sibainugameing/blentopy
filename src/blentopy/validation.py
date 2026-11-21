"""Syntax preflight for standard Blender Python scene scripts.

This module deliberately does not implement an AST/API whitelist. Scene scripts
run as ordinary Python inside a separate Blender process. Process deadlines,
staged output publication, and post-execution scene checks belong to the runner.
"""

from __future__ import annotations

import ast


MAX_SCRIPT_CHARS = 1_000_000


class ScriptValidationError(ValueError):
    """Python syntax/input error with editor-friendly source diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        lineno: int | None = None,
        col_offset: int | None = None,
        source_line: str | None = None,
        suggestion: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.lineno = lineno
        self.col_offset = col_offset
        self.source_line = source_line
        self.suggestion = suggestion
        self.code = code


def validate_script(source: str) -> ast.Module:
    """Parse a scene script without restricting valid Python or Blender APIs.

    This is a syntax preflight, not a sandbox. Imports, normal Python syntax,
    built-ins, bpy, mathutils, and Blender's complete Python API are available
    when the returned AST is executed by the Blender worker.
    """
    if not isinstance(source, str):
        raise ScriptValidationError(
            "Python code must be a string.",
            code="invalid-script-type",
        )
    if not source.strip():
        raise ScriptValidationError(
            "Python code is empty.",
            code="empty-script",
        )
    if len(source) > MAX_SCRIPT_CHARS:
        raise ScriptValidationError(
            f"Python code exceeds the {MAX_SCRIPT_CHARS:,}-character limit. "
            "Split very large scripts into imported modules in the workspace.",
            code="script-too-large",
        )

    source_lines = source.splitlines()
    try:
        return ast.parse(source, mode="exec")
    except SyntaxError as exc:
        line_no = exc.lineno
        source_line = (
            source_lines[line_no - 1]
            if isinstance(line_no, int) and 1 <= line_no <= len(source_lines)
            else None
        )
        offset = max(0, (exc.offset or 1) - 1)
        raise ScriptValidationError(
            f"Python syntax error: {exc.msg}",
            lineno=line_no,
            col_offset=offset,
            source_line=source_line,
            suggestion=(
                "Check the reported line for a Python syntax issue. "
                "The validator does not restrict Python constructs or Blender API calls."
            ),
            code="python-syntax-error",
        ) from exc
