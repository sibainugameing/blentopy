"""Validation for the deliberately small Python scene language.

This is a capability restriction, not an operating-system sandbox.
"""

from __future__ import annotations

import ast
import math

MAX_SCRIPT_CHARS = 100_000
MAX_AST_NODES = 5_000
MAX_LOOP_ITERATIONS = 128
MAX_TOTAL_LOOP_ITERATIONS = 256
MAX_LOOP_EXPANSION_COST = 20_000

STUDIO_METHODS = frozenset({
    "set_timeline", "set_world_color", "add_plane", "add_cube",
    "add_uv_sphere", "add_ico_sphere", "add_cylinder", "add_cone",
    "add_torus", "add_text", "add_camera", "set_active_camera",
    "add_area_light", "add_sun_light", "animate_location",
    "animate_rotation", "animate_scale", "animate_camera",
    "add_audio", "fade_audio",
})
MATH_ATTRIBUTES = frozenset({
    "pi", "tau", "e", "sin", "cos", "tan", "radians", "degrees", "sqrt",
})
_ALLOWED_BINARY_OPERATORS = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
)
_ALLOWED_NODE_TYPES = (
    ast.Module, ast.Expr, ast.Assign, ast.For, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.UnaryOp, ast.UAdd,
    ast.USub, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Attribute, ast.Call, ast.keyword,
)


class ScriptValidationError(ValueError):
    """Raised when code uses syntax outside the documented scene language."""


def _literal_range(node: ast.For) -> range:
    call = node.iter
    if (
        not isinstance(call, ast.Call)
        or not isinstance(call.func, ast.Name)
        or call.func.id != "range"
        or call.keywords
        or not 1 <= len(call.args) <= 3
    ):
        raise ScriptValidationError(
            "Loops must use range() with one to three literal integer arguments."
        )
    values = []
    for argument in call.args:
        if not isinstance(argument, ast.Constant) or type(argument.value) is not int:
            raise ScriptValidationError("range() arguments must be literal integers.")
        if abs(argument.value) > 256:
            raise ScriptValidationError("range() arguments may not exceed 256 in magnitude.")
        values.append(argument.value)
    try:
        result = range(*values)
        count = len(result)
    except (ValueError, OverflowError) as exc:
        raise ScriptValidationError(f"Invalid range(): {exc}") from exc
    if count > MAX_LOOP_ITERATIONS:
        raise ScriptValidationError(
            f"A loop may run at most {MAX_LOOP_ITERATIONS} times."
        )
    return result


def validate_script(source: str) -> ast.Module:
    """Parse and validate a bounded scene script before executing it in Blender."""
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

    parents = {
        child: parent
        for parent in nodes
        for child in ast.iter_child_nodes(parent)
    }
    loops = [node for node in nodes if isinstance(node, ast.For)]
    allowed_range_calls: set[int] = set()
    total_iterations = 0
    expansion_cost = 0
    loop_targets: set[str] = set()

    for loop in loops:
        if loop.orelse:
            raise ScriptValidationError("Loop else clauses are not supported.")
        if not isinstance(loop.target, ast.Name):
            raise ScriptValidationError("A loop target must be one simple variable name.")
        target_name = loop.target.id
        if target_name.startswith("_") or target_name in {"studio", "math", "range"}:
            raise ScriptValidationError(f"Invalid loop variable: {target_name}")
        loop_targets.add(target_name)
        iterations = len(_literal_range(loop))
        allowed_range_calls.add(id(loop.iter))
        total_iterations += iterations
        expansion_cost += iterations * len(list(ast.walk(loop)))
        if total_iterations > MAX_TOTAL_LOOP_ITERATIONS:
            raise ScriptValidationError(
                f"All loops combined may run at most {MAX_TOTAL_LOOP_ITERATIONS} times."
            )
        if expansion_cost > MAX_LOOP_EXPANSION_COST:
            raise ScriptValidationError("The expanded loop body is too large.")
        ancestor = parents.get(loop)
        while ancestor is not None:
            if isinstance(ancestor, ast.For):
                raise ScriptValidationError("Nested loops are not supported.")
            ancestor = parents.get(ancestor)

    assigned: set[str] = set(loop_targets)
    for node in nodes:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise ScriptValidationError("Only simple variable assignments are supported.")
            target = node.targets[0].id
            if target.startswith("_") or target in {"studio", "math", "range"}:
                raise ScriptValidationError(f"Cannot assign to reserved name: {target}")
            assigned.add(target)

    for node in nodes:
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise ScriptValidationError(
                f"Unsupported Python syntax: {type(node).__name__}. "
                "Use studio.* calls, bounded range() loops, variables, literals, and basic arithmetic."
            )

        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ScriptValidationError("Names beginning with '_' are not allowed.")
            if node.id == "range":
                parent = parents.get(node)
                if not isinstance(parent, ast.Call) or id(parent) not in allowed_range_calls:
                    raise ScriptValidationError("range() is only allowed as a bounded for-loop iterator.")
            elif node.id not in {"studio", "math"} and node.id not in assigned:
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

        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINARY_OPERATORS):
                raise ScriptValidationError("Only +, -, *, /, //, and % arithmetic is supported.")

        elif isinstance(node, ast.For):
            if not isinstance(node.target, ast.Name):
                raise ScriptValidationError("A loop target must be one simple variable name.")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "range":
                if id(node) not in allowed_range_calls:
                    raise ScriptValidationError("range() is only allowed as a bounded for-loop iterator.")
                if any(keyword.arg is None for keyword in node.keywords):
                    raise ScriptValidationError("Keyword unpacking is not supported.")
                continue
            if not isinstance(node.func, ast.Attribute):
                raise ScriptValidationError("Only studio.*, math.*, and bounded range() calls are allowed.")
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
