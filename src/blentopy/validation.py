"""AST validation for the constrained, AI-authored scene language."""

from __future__ import annotations

import ast
import math

MAX_SCRIPT_CHARS = 100_000
MAX_AST_NODES = 8_000
MAX_LOOP_ITERATIONS = 128
MAX_TOTAL_LOOP_ITERATIONS = 4_096
MAX_LOOP_DEPTH = 3
MAX_LOOP_EXPANSION_COST = 50_000

STUDIO_METHODS = frozenset({
    "set_timeline", "set_world_color", "add_plane", "add_cube",
    "add_uv_sphere", "add_ico_sphere", "add_cylinder", "add_cone",
    "add_torus", "add_text", "add_camera", "set_active_camera",
    "add_area_light", "add_sun_light", "animate_location",
    "animate_rotation", "animate_scale", "animate_camera",
    "add_audio", "fade_audio",
})
SCENE_METHODS = frozenset({
    "configure", "mesh", "surface", "group", "add", "remove", "attach",
    "place", "look_at", "frame", "align", "camera", "light", "find",
    "motion", "inspect", "validate",
})
GEOMETRY_METHODS = frozenset({
    "box", "rounded_box", "sphere", "plane", "cylinder", "cone", "torus", "mesh",
})
MATERIAL_METHODS = frozenset({"pbr", "emissive"})
OBJECT_PROPERTIES = frozenset({
    "id", "kind", "role", "position", "rotation", "scale", "visible",
})
OBJECT_METHODS = frozenset({"move_to", "rotate_by", "add"})
VECTOR_PROPERTIES = frozenset({"x", "y", "z"})
VECTOR_METHODS = frozenset({"set"})
MOTION_METHODS = frozenset({"track"})
TRACK_METHODS = frozenset({"key"})
MATH_ATTRIBUTES = frozenset({
    "pi", "tau", "e", "sin", "cos", "tan", "radians", "degrees", "sqrt",
})
_MATH_FUNCTIONS = MATH_ATTRIBUTES - {"pi", "tau", "e"}
_ALLOWED_BINARY_OPERATORS = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
)
_ALLOWED_COMPARE_OPERATORS = (
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
    ast.In, ast.NotIn,
)
_ALLOWED_NODE_TYPES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.If,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict,
    ast.UnaryOp, ast.UAdd, ast.USub, ast.Not, ast.BinOp, ast.Add, ast.Sub,
    ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Attribute, ast.Call,
    ast.keyword, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
    ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn, ast.BoolOp, ast.And, ast.Or,
)


class ScriptValidationError(ValueError):
    """Raised when code uses syntax or API access outside the scene language."""


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


def _attribute_chain(node: ast.AST) -> tuple[str, tuple[str, ...]] | None:
    attributes: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        attributes.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    attributes.reverse()
    if any(not part or part.startswith("_") for part in attributes):
        return None
    return current.id, tuple(attributes)


def _attribute_allowed(root: str, attributes: tuple[str, ...]) -> bool:
    if root == "math":
        return len(attributes) == 1 and attributes[0] in MATH_ATTRIBUTES
    if root == "studio":
        if len(attributes) == 1:
            return attributes[0] in STUDIO_METHODS or attributes[0] in {"scene", "geo", "mat"}
        if len(attributes) == 2:
            return (
                attributes[0] == "geo" and attributes[1] in GEOMETRY_METHODS
            ) or (
                attributes[0] == "mat" and attributes[1] in MATERIAL_METHODS
            )
        return False

    if len(attributes) == 1:
        name = attributes[0]
        return name in (
            SCENE_METHODS | GEOMETRY_METHODS | MATERIAL_METHODS |
            OBJECT_PROPERTIES | OBJECT_METHODS | VECTOR_PROPERTIES |
            VECTOR_METHODS | MOTION_METHODS | TRACK_METHODS
        )
    if len(attributes) == 2:
        first, second = attributes
        return (
            first in {"position", "rotation", "scale"} and second in (VECTOR_PROPERTIES | VECTOR_METHODS)
        )
    return False


def _target_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    return None


def validate_script(source: str) -> ast.Module:
    """Parse and validate a scene script before executing it inside Blender.

    The language supports safe API handles, assignments, conditionals, and
    statically bounded nested loops. It is a capability restriction, not an
    operating-system sandbox.
    """
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
    assigned: set[str] = set()

    for loop in loops:
        if loop.orelse:
            raise ScriptValidationError("Loop else clauses are not supported.")
        if not isinstance(loop.target, ast.Name):
            raise ScriptValidationError("A loop target must be one simple variable name.")
        target_name = loop.target.id
        if target_name.startswith("_") or target_name in {"studio", "math", "range"}:
            raise ScriptValidationError(f"Invalid loop variable: {target_name}")
        assigned.add(target_name)
        iterations = len(_literal_range(loop))
        allowed_range_calls.add(id(loop.iter))

        ancestor = parents.get(loop)
        enclosing_iterations = 1
        depth = 1
        while ancestor is not None:
            if isinstance(ancestor, ast.For):
                depth += 1
                enclosing_iterations *= len(_literal_range(ancestor))
            ancestor = parents.get(ancestor)
        if depth > MAX_LOOP_DEPTH:
            raise ScriptValidationError(f"Loop nesting may not exceed {MAX_LOOP_DEPTH} levels.")
        total_iterations += iterations * enclosing_iterations
        expansion_cost += iterations * enclosing_iterations * len(list(ast.walk(loop)))
        if total_iterations > MAX_TOTAL_LOOP_ITERATIONS:
            raise ScriptValidationError(
                f"All loops combined may execute at most {MAX_TOTAL_LOOP_ITERATIONS:,} iterations."
            )
        if expansion_cost > MAX_LOOP_EXPANSION_COST:
            raise ScriptValidationError("The expanded loop body is too large.")

    for node in nodes:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                raise ScriptValidationError("Assignments must have exactly one target.")
            target = node.targets[0]
            name = _target_name(target)
            if name is not None:
                if name.startswith("_") or name in {"studio", "math", "range"}:
                    raise ScriptValidationError(f"Cannot assign to reserved name: {name}")
                assigned.add(name)
            elif isinstance(target, ast.Attribute):
                chain = _attribute_chain(target)
                if chain is None or not _attribute_allowed(*chain):
                    raise ScriptValidationError("Assignment to this object property is not allowed.")
                if not (len(chain[1]) == 1 and chain[1][0] == "visible") and not (
                    len(chain[1]) == 2 and chain[1][0] in {"position", "rotation", "scale"}
                    and chain[1][1] in VECTOR_PROPERTIES
                ):
                    raise ScriptValidationError("Only visible and vector component properties may be assigned.")
            else:
                raise ScriptValidationError("Only simple variables and approved object properties may be assigned.")

        elif isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise ScriptValidationError("Augmented assignment is limited to simple variables.")
            if node.target.id.startswith("_") or node.target.id in {"studio", "math", "range"}:
                raise ScriptValidationError(f"Cannot assign to reserved name: {node.target.id}")
            assigned.add(node.target.id)

    for node in nodes:
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise ScriptValidationError(
                f"Unsupported Python syntax: {type(node).__name__}. "
                "Use the blentopy scene API, variables, conditionals, bounded loops, and basic expressions."
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
            chain = _attribute_chain(node)
            if chain is None or not _attribute_allowed(*chain):
                raise ScriptValidationError("Attribute access is not allowed for this object or property.")

        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINARY_OPERATORS):
                raise ScriptValidationError("Only +, -, *, /, //, and % arithmetic is supported.")

        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
                raise ScriptValidationError("Unsupported unary operator.")

        elif isinstance(node, ast.Compare):
            if any(not isinstance(operator, _ALLOWED_COMPARE_OPERATORS) for operator in node.ops):
                raise ScriptValidationError("Unsupported comparison operator.")

        elif isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)):
                raise ScriptValidationError("Unsupported boolean operator.")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "range":
                    if id(node) not in allowed_range_calls:
                        raise ScriptValidationError("range() is only allowed as a bounded for-loop iterator.")
                else:
                    raise ScriptValidationError("Only approved API methods and bounded range() calls are allowed.")
            else:
                chain = _attribute_chain(node.func)
                if chain is None or not _attribute_allowed(*chain):
                    raise ScriptValidationError("Calls are limited to documented blentopy API methods.")
                root, attributes = chain
                method = attributes[-1]
                if root == "math":
                    if len(attributes) != 1 or method not in _MATH_FUNCTIONS:
                        raise ScriptValidationError("Math constants cannot be called.")
                elif root == "studio":
                    allowed = (
                        method in STUDIO_METHODS
                        if len(attributes) == 1
                        else (attributes[0] == "geo" and method in GEOMETRY_METHODS)
                        or (attributes[0] == "mat" and method in MATERIAL_METHODS)
                    )
                    if not allowed:
                        raise ScriptValidationError("Unknown blentopy API method.")
                elif method not in (
                    SCENE_METHODS | GEOMETRY_METHODS | MATERIAL_METHODS |
                    OBJECT_METHODS | VECTOR_METHODS | MOTION_METHODS | TRACK_METHODS
                ):
                    raise ScriptValidationError("This object method is not available in scene scripts.")
            if any(keyword.arg is None for keyword in node.keywords):
                raise ScriptValidationError("Keyword unpacking is not supported.")

        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise ScriptValidationError("Only simple string, numeric, boolean, and None literals are allowed.")
            if isinstance(node.value, str) and len(node.value) > 10_000:
                raise ScriptValidationError("A string literal is too long.")
            if isinstance(node.value, (int, float)) and abs(node.value) > 10**9:
                raise ScriptValidationError("A numeric literal is too large.")
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ScriptValidationError("Non-finite numeric literals are not allowed.")

    return tree
