"""Validation for the deliberately small Python surface exposed to AI tools.

This is a capability restriction, not a general-purpose Python sandbox.
"""

from __future__ import annotations

import ast
import math

MAX_SCRIPT_CHARS = 100_000
MAX_AST_NODES = 5_000

STUDIO_METHODS = frozenset({
    "set_timeline", "set_world_color", "add_plane", "add_cube",
    "add_uv_sphere", "add_cylinder", "add_text", "add_camera",
    "add_area_light", "set_active_camera", "animate_location",
    "animate_rotation", "animate_scale", "add_audio", "fade_audio",
})
MATH_ATTRIBUTES = frozenset({
    "pi", "tau", "e", "sin", "cos", "tan", "radians", "degrees", "sqrt",
})
_ALLOWED_NODE_TYPES = (
    ast.Module, ast.Expr, ast.Assign, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.UnaryOp, ast.UAdd,
    ast.USub, ast.Attribute, ast.Call, ast.keyword,
)


class ScriptValidationError(ValueError):
    """Raised when code uses syntax outside the documented Studio API."""


def validate_script(source: str) -> ast.Module:
    """Parse and validate a scene script before executing it in Blender."""
    if not isinstance(source, str):
        raise ScriptValidationError("Python code must be a string.")
    if not source.strip():
        raise ScriptValidationError("Python code is empty.")
    if len(source) > MAX_SCRIPT_CHARS:
        raise ScriptValidationError(f"Python code exceeds {MAX_SCRIPT_CHARS:,} characters.")

    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ScriptValidationError(
            f"Python syntax error at line {exc.lineno}: {exc.msg}"
        ) from exc

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ScriptValidationError(f"Python code exceeds {MAX_AST_NODES:,} syntax nodes.")

    assigned: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise ScriptValidationError("Only simple variable assignments are supported.")
            target = node.targets[0].id
            if target.startswith("_") or target in {"studio", "math"}:
                raise ScriptValidationError(f"Cannot assign to reserved name: {target}")
            assigned.add(target)

    for node in nodes:
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise ScriptValidationError(
                f"Unsupported Python syntax: {type(node).__name__}. "
                "Use studio.* calls, variables, literals, and math.* helpers."
            )

        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ScriptValidationError("Names beginning with '_' are not allowed.")
            if node.id not in {"studio", "math"} and node.id not in assigned:
                raise ScriptValidationError(f"Unknown name: {node.id}")

        elif isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name):
                raise ScriptValidationError("Attribute chaining is not allowed.")
            if node.value.id == "studio":
                if node.attr not in STUDIO_METHODS:
                    raise ScriptValidationError(f"Unknown Studio API method: {node.attr}")
            elif node.value.id == "math":
                if node.attr not in MATH_ATTRIBUTES:
                    raise ScriptValidationError(f"Unsupported math attribute: {node.attr}")
            else:
                raise ScriptValidationError("Only studio.* and math.* attributes are allowed.")

        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Attribute):
                raise ScriptValidationError("Only studio.* and math.* calls are allowed.")
            if not isinstance(node.func.value, ast.Name):
                raise ScriptValidationError("Chained function calls are not allowed.")
            if node.func.value.id == "studio" and node.func.attr not in STUDIO_METHODS:
                raise ScriptValidationError(f"Unknown Studio API method: {node.func.attr}")
            if node.func.value.id == "math" and node.func.attr not in (
                MATH_ATTRIBUTES - {"pi", "tau", "e"}
            ):
                raise ScriptValidationError(f"Unsupported math function: {node.func.attr}")
            if node.func.value.id not in {"studio", "math"}:
                raise ScriptValidationError("Calls on variables are not allowed.")
            if any(keyword.arg is None for keyword in node.keywords):
                raise ScriptValidationError("Keyword unpacking is not supported.")

        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise ScriptValidationError("Only simple string, numeric, and boolean literals are allowed.")
            if isinstance(node.value, str) and len(node.value) > 10_000:
                raise ScriptValidationError("A string literal is too long.")
            if isinstance(node.value, (int, float)) and abs(node.value) > 10**9:
                raise ScriptValidationError("A numeric literal is too large.")
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ScriptValidationError("Non-finite numeric literals are not allowed.")

    return tree
