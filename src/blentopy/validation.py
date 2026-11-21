"""AST validation for the constrained, AI-authored scene language."""

from __future__ import annotations

import ast
import inspect
import math
import types
from collections.abc import Sequence as ABCSequence
from typing import Any, get_args, get_origin, get_type_hints

from .ai_native import (
    AIStudio, GeometryFactory, GeometrySpec, MaterialFactory, MaterialSpec,
    MotionAPI, MotionTrack, Object3D, SceneAPI, VectorProxy,
)
from .studio import Studio

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
    "place", "look_at", "frame", "align", "camera", "light", "curve", "text",
    "duplicate", "instance", "set_dimensions", "bevel", "subdivide", "solidify", "mirror",
    "array", "boolean", "shade_smooth", "find", "update", "set_material",
    "motion", "inspect", "validate", "armature", "bind_armature", "rigid_body",
    "configure_render", "environment", "post_process", "camera_dof", "set_visibility",
    "import_model", "export_model",
})
GEOMETRY_METHODS = frozenset({
    "box", "rounded_box", "sphere", "plane", "cylinder", "cone", "torus", "mesh",
    "ico_sphere", "circle", "ring", "capsule", "torus_knot",
})
MATERIAL_METHODS = frozenset({"pbr", "emissive", "image_texture", "noise", "physical", "glass", "toon"})
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
    ast.Subscript, ast.Slice, ast.UnaryOp, ast.UAdd, ast.USub, ast.Not, ast.BinOp, ast.Add, ast.Sub,
    ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Attribute, ast.Call,
    ast.keyword, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
    ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn, ast.BoolOp, ast.And, ast.Or,
)


class ScriptValidationError(ValueError):
    """A scene-script validation error with editor-friendly source diagnostics."""

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


MAX_RANGE_ARGUMENT = 1_000_000_000


def _is_range_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and not node.keywords
        and 1 <= len(node.args) <= 3
    )


def _is_integer_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return type(node.value) is int
    if isinstance(node, ast.Name):
        return not node.id.startswith("_")
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub)) and _is_integer_expression(node.operand)
    if isinstance(node, ast.BinOp):
        return (
            isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod))
            and _is_integer_expression(node.left)
            and _is_integer_expression(node.right)
        )
    return False


def _static_integer(node: ast.AST, values: dict[str, int | None]) -> int | None:
    """Evaluate a deliberately small integer-expression subset for early limits."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name):
        return values.get(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _static_integer(node.operand, values)
        if value is not None:
            return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _static_integer(node.left, values)
        right = _static_integer(node.right, values)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            elif isinstance(node.op, ast.FloorDiv):
                result = left // right
            elif isinstance(node.op, ast.Mod):
                result = left % right
            else:
                return None
        except (ArithmeticError, ValueError):
            return None
        return result
    return None


def _static_loop_count(node: ast.For, values: dict[str, int | None]) -> int | None:
    iterable = node.iter
    if _is_range_call(iterable):
        assert isinstance(iterable, ast.Call)
        arguments = [_static_integer(argument, values) for argument in iterable.args]
        if any(value is None for value in arguments):
            return None
        integer_arguments = [int(value) for value in arguments]
        if any(abs(value) > MAX_RANGE_ARGUMENT for value in integer_arguments):
            raise ScriptValidationError(
                f"range() arguments may not exceed {MAX_RANGE_ARGUMENT:,} in magnitude."
            )
        try:
            return len(range(*integer_arguments))
        except (ValueError, OverflowError) as exc:
            raise ScriptValidationError(f"Invalid range(): {exc}") from exc
    if isinstance(iterable, (ast.List, ast.Tuple)):
        return len(iterable.elts)
    return None


def _collect_static_loop_counts(tree: ast.Module) -> dict[int, int | None]:
    """Resolve loop sizes when their bounds are statically knowable."""
    counts: dict[int, int | None] = {}

    def visit_block(
        statements: list[ast.stmt],
        values: dict[str, int | None],
    ) -> dict[str, int | None]:
        state = dict(values)
        for statement in statements:
            if isinstance(statement, ast.Assign):
                value = _static_integer(statement.value, state)
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        state[target.id] = value
            elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                name = statement.target.id
                left = state.get(name)
                right = _static_integer(statement.value, state)
                if left is None or right is None:
                    state[name] = None
                else:
                    try:
                        if isinstance(statement.op, ast.Add):
                            state[name] = left + right
                        elif isinstance(statement.op, ast.Sub):
                            state[name] = left - right
                        elif isinstance(statement.op, ast.Mult):
                            state[name] = left * right
                        elif isinstance(statement.op, ast.FloorDiv):
                            state[name] = left // right
                        elif isinstance(statement.op, ast.Mod):
                            state[name] = left % right
                        else:
                            state[name] = None
                    except ArithmeticError:
                        state[name] = None
            elif isinstance(statement, ast.If):
                first = visit_block(statement.body, dict(state))
                second = visit_block(statement.orelse, dict(state)) if statement.orelse else dict(state)
                merged: dict[str, int | None] = {}
                for name in first.keys() | second.keys():
                    left = first.get(name, state.get(name))
                    right = second.get(name, state.get(name))
                    merged[name] = left if left == right else None
                state = merged
            elif isinstance(statement, ast.For):
                counts[id(statement)] = _static_loop_count(statement, state)
                nested = dict(state)
                if isinstance(statement.target, ast.Name):
                    nested[statement.target.id] = None
                visit_block(statement.body, nested)
        return state

    visit_block(tree.body, {})
    return counts


def _is_bounded_iterable_type(value: object | None) -> bool:
    if value in {list, tuple, range}:
        return True
    return get_origin(value) in {list, tuple, ABCSequence}


def _iterable_item_type(
    node: ast.AST,
    environment: dict[str, object],
) -> object | None:
    value = _infer_expression_type(node, environment)
    arguments = get_args(value)
    if arguments:
        return arguments[0]
    if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
        item_types = [_infer_expression_type(item, environment) for item in node.elts]
        known_types = {item for item in item_types if isinstance(item, type)}
        if len(known_types) == 1 and all(item is not None for item in item_types):
            return next(iter(known_types))
    return None


def _bounded_range(*args: int) -> range:
    """Runtime range() guard used by Blender's script namespace."""
    if not 1 <= len(args) <= 3:
        raise TypeError("range() requires one to three integer arguments.")
    if any(type(value) is not int for value in args):
        raise TypeError("range() arguments must evaluate to integers (bool is not accepted).")
    if any(abs(value) > MAX_RANGE_ARGUMENT for value in args):
        raise ValueError(
            f"range() arguments may not exceed {MAX_RANGE_ARGUMENT:,} in magnitude."
        )
    result = range(*args)
    if len(result) > MAX_LOOP_ITERATIONS:
        raise ValueError(
            f"Each for-loop is limited to {MAX_LOOP_ITERATIONS} iterations; "
            f"the requested range contains {len(result)}."
        )
    return result


def _bounded_loop_iterator(
    iterable: object,
    node_cost: int,
    budget: dict[str, int],
):
    """Enforce actual iteration and expanded-AST budgets while a script runs."""
    if type(iterable) not in {range, list, tuple}:
        raise TypeError(
            "for-loops may iterate only over range(), lists, tuples, or "
            "a scene.find() result."
        )
    try:
        count = len(iterable)
    except OverflowError as exc:
        raise ValueError("The loop iterable is too large to evaluate safely.") from exc
    if count > MAX_LOOP_ITERATIONS:
        raise ValueError(
            f"Each for-loop is limited to {MAX_LOOP_ITERATIONS} iterations; "
            f"the iterable contains {count}."
        )
    for item in iterable:
        budget["iterations"] += 1
        budget["expansion_cost"] += node_cost
        if budget["iterations"] > MAX_TOTAL_LOOP_ITERATIONS:
            raise RuntimeError(
                f"Scene script exceeded the total loop budget of "
                f"{MAX_TOTAL_LOOP_ITERATIONS:,} iterations."
            )
        if budget["expansion_cost"] > MAX_LOOP_EXPANSION_COST:
            raise RuntimeError(
                f"Scene script exceeded the expanded loop-work budget of "
                f"{MAX_LOOP_EXPANSION_COST:,}."
            )
        yield item


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


def _is_scene_motion_call(node: ast.AST) -> bool:
    """Return True only for a direct scene.motion(...) API call."""
    if not isinstance(node, ast.Call):
        return False
    chain = _attribute_chain(node.func)
    return chain in {
        ("scene", ("motion",)),
        ("studio", ("scene", "motion")),
    }


def _is_motion_track_chain(node: ast.AST) -> bool:
    """Allow scene.motion(object).track(channel), a documented API shortcut."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "track"
        and _is_scene_motion_call(node.value)
    )


def _attribute_allowed(root: str, attributes: tuple[str, ...]) -> bool:
    if root == "math":
        return len(attributes) == 1 and attributes[0] in MATH_ATTRIBUTES
    if root == "studio":
        if len(attributes) == 1:
            return attributes[0] in STUDIO_METHODS or attributes[0] in {"scene", "geo", "mat"}
        if len(attributes) == 2:
            return (
                attributes[0] == "scene" and attributes[1] in SCENE_METHODS
            ) or (
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




def _owner_type_for_method(owner_type: type | None) -> type | None:
    if owner_type is AIStudio:
        return Studio
    return owner_type


def _infer_expression_type(node: ast.AST, environment: dict[str, object]) -> object | None:
    """Infer only types that are safe and useful for API argument diagnostics."""
    if isinstance(node, ast.Constant):
        return type(node.value)
    if isinstance(node, ast.Name):
        return environment.get(node.id)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple if isinstance(node, ast.Tuple) else list
    if isinstance(node, ast.Dict):
        return dict
    if isinstance(node, ast.Subscript):
        container_type = _infer_expression_type(node.value, environment)
        if container_type in {list, tuple, str}:
            if isinstance(node.value, (ast.List, ast.Tuple)) and isinstance(node.slice, ast.Constant) and type(node.slice.value) is int:
                items = node.value.elts
                index = node.slice.value
                if -len(items) <= index < len(items):
                    return _infer_expression_type(items[index], environment)
            if isinstance(node.value, (ast.List, ast.Tuple)) and node.value.elts:
                item_types = {_infer_expression_type(item, environment) for item in node.value.elts}
                if len(item_types) == 1:
                    return next(iter(item_types))
            return None
        if container_type is dict and isinstance(node.value, ast.Dict):
            for key, value in zip(node.value.keys, node.value.values):
                if key is not None and isinstance(node.slice, ast.Constant) and key.value == node.slice.value:
                    return _infer_expression_type(value, environment)
        return None
    if isinstance(node, ast.Attribute):
        owner = _infer_expression_type(node.value, environment)
        if owner is AIStudio:
            return {
                "scene": SceneAPI,
                "geo": GeometryFactory,
                "mat": MaterialFactory,
            }.get(node.attr)
        if owner is Object3D and node.attr in {"position", "rotation", "scale"}:
            return VectorProxy
        if owner is types.ModuleType and node.attr in {"pi", "tau", "e"}:
            return float
        return None
    if isinstance(node, ast.UnaryOp):
        return _infer_expression_type(node.operand, environment)
    if isinstance(node, ast.BinOp):
        left = _infer_expression_type(node.left, environment)
        right = _infer_expression_type(node.right, environment)
        if left in {int, float} and right in {int, float}:
            return float if float in {left, right} or isinstance(node.op, ast.Div) else int
        return None
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return range if node.func.id == "range" else None
        if not isinstance(node.func, ast.Attribute):
            return None
        owner = _infer_expression_type(node.func.value, environment)
        if owner is types.ModuleType:
            callable_object = getattr(math, node.func.attr, None)
        elif owner is SceneAPI and node.func.attr == "find":
            has_id = len(node.args) >= 2 or any(keyword.arg == "id" for keyword in node.keywords)
            return Object3D if has_id else list[Object3D]
        else:
            resolved_owner = _owner_type_for_method(owner if isinstance(owner, type) else None)
            callable_object = getattr(resolved_owner, node.func.attr, None) if resolved_owner else None
        if callable_object is None:
            return None
        try:
            return get_type_hints(callable_object).get("return")
        except (NameError, TypeError, ValueError):
            return getattr(getattr(callable_object, "__annotations__", {}), "get", lambda _key: None)("return")
    return None


def _is_argument_type_compatible(actual: object | None, expected: object) -> bool:
    if actual is None or expected in {inspect.Signature.empty, Any}:
        return True
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin in {types.UnionType, __import__("typing").Union}:
        return any(_is_argument_type_compatible(actual, item) for item in arguments)
    if origin in {ABCSequence, list, tuple}:
        return actual in {list, tuple, range}
    if expected is float:
        return actual in {int, float}
    if expected is int:
        return actual is int
    if expected is bool:
        return actual is bool
    if expected in {str, type(None)}:
        return actual is expected
    if isinstance(expected, type) and isinstance(actual, type):
        try:
            return issubclass(actual, expected)
        except TypeError:
            return True
    return True


def _call_signature(node: ast.Call, environment: dict[str, object]):
    if not isinstance(node.func, ast.Attribute):
        return None, None
    owner = _infer_expression_type(node.func.value, environment)
    if owner is types.ModuleType:
        method = getattr(math, node.func.attr, None)
        return method, method
    owner_type = _owner_type_for_method(owner if isinstance(owner, type) else None)
    if owner_type is None:
        return None, None
    method = getattr(owner_type, node.func.attr, None)
    return method, method


def _validate_call_arguments(
    node: ast.Call,
    environment: dict[str, object],
    fail,
    source: str,
) -> None:
    method, callable_object = _call_signature(node, environment)
    if callable_object is None:
        return
    try:
        call_signature = inspect.signature(callable_object)
    except (TypeError, ValueError):
        return

    parameters = list(call_signature.parameters.values())
    if parameters and parameters[0].name == "self":
        parameters = parameters[1:]
        call_signature = call_signature.replace(parameters=parameters)

    keyword_values = {
        keyword.arg: keyword.value
        for keyword in node.keywords
        if keyword.arg is not None
    }
    try:
        call_signature.bind(
            *([None] * len(node.args)),
            **{name: None for name in keyword_values},
        )
    except TypeError as exc:
        expression = ast.get_source_segment(source, node.func) or "API call"
        fail(
            node,
            f"Invalid arguments for {expression}(): {exc}",
            suggestion=f"Use the documented argument names and signature: {expression}{call_signature}.",
            code="invalid-api-arguments",
        )

    try:
        annotations = get_type_hints(method)
    except (NameError, TypeError, ValueError):
        annotations = getattr(method, "__annotations__", {})

    values: dict[str, ast.AST] = {}
    positional_parameters = [
        parameter for parameter in parameters
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    for index, argument in enumerate(node.args):
        if index < len(positional_parameters):
            values[positional_parameters[index].name] = argument
    values.update(keyword_values)

    for parameter_name, argument in values.items():
        expected = annotations.get(parameter_name)
        if expected is None or isinstance(expected, str):
            continue
        actual = _infer_expression_type(argument, environment)
        if not _is_argument_type_compatible(actual, expected):
            expression = ast.get_source_segment(source, node.func) or "API call"
            fail(
                argument,
                f"Argument '{parameter_name}' for {expression}() has an incompatible type.",
                suggestion=(
                    f"Expected {expected!r}; received {actual.__name__ if isinstance(actual, type) else actual!r}. "
                    "Check the method signature in docs/AI_SYSTEM_PROMPT.md."
                ),
                code="api-argument-type-mismatch",
            )


def _validate_subscript(
    node: ast.Subscript,
    environment: dict[str, object],
    fail,
    source: str,
) -> None:
    container_type = _infer_expression_type(node.value, environment)
    if container_type not in {list, tuple, dict, str}:
        expression = ast.get_source_segment(source, node.value) or "this value"
        fail(
            node,
            f"Indexing is only supported on lists, tuples, dictionaries, and strings; {expression} is not a recognized container.",
            suggestion="Store values in a list, tuple, or dictionary before indexing.",
            code="unsupported-subscript-container",
        )
    if isinstance(node.slice, ast.Slice):
        if container_type not in {list, tuple, str}:
            fail(
                node.slice,
                "Slices are only supported on lists, tuples, and strings.",
                suggestion="Use a single key when indexing a dictionary.",
                code="invalid-subscript-slice",
            )
        for bound in (node.slice.lower, node.slice.upper, node.slice.step):
            if bound is not None and _infer_expression_type(bound, environment) not in {int, None}:
                fail(
                    bound,
                    "Slice bounds must be integers.",
                    suggestion="Use integer slice bounds, such as values[:3] or values[1:4].",
                    code="invalid-subscript-slice",
                )
    else:
        index_type = _infer_expression_type(node.slice, environment)
        if index_type not in {int, str, None}:
            fail(
                node.slice,
                "Indices must be integers or strings.",
                suggestion="Use an integer index or a string/integer dictionary key.",
                code="invalid-subscript-index",
            )
        if container_type in {list, tuple, str} and index_type not in {int, None}:
            fail(
                node.slice,
                "List, tuple, and string indices must be integers.",
                suggestion="Use an integer index such as items[0] or items[index].",
                code="invalid-subscript-index",
            )

def _validate_dataflow(tree: ast.Module, fail, source: str) -> None:
    """Reject forward references and names that are not defined on every path."""
    environment: dict[str, object] = {
        "studio": AIStudio,
        "math": types.ModuleType,
        "range": range,
    }

    def check_expression(expression: ast.AST, current: dict[str, object]) -> None:
        for child in ast.walk(expression):
            if isinstance(child, ast.Subscript):
                _validate_subscript(child, current, fail, source)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id not in current:
                    fail(
                        child,
                        f"Name '{child.id}' is used before it is assigned or is not defined on every path.",
                        suggestion="Assign the variable before use, and assign it in every branch where it is later read.",
                        code="undefined-name",
                    )
            elif isinstance(child, ast.Call):
                _validate_call_arguments(child, current, fail, source)

    def merge_branches(
        before: dict[str, object],
        first: dict[str, object],
        second: dict[str, object],
    ) -> dict[str, object]:
        merged: dict[str, object] = {}
        for name in first.keys() & second.keys():
            left, right = first[name], second[name]
            merged[name] = left if left == right else None
        # Preserve incoming types even when a branch refines a variable differently.
        for name in before:
            if name in merged and merged[name] is None:
                merged[name] = before[name]
        return merged

    def visit_block(statements: list[ast.stmt], current: dict[str, object]) -> dict[str, object]:
        state = dict(current)
        for statement in statements:
            if isinstance(statement, ast.Assign):
                check_expression(statement.value, state)
                value_type = _infer_expression_type(statement.value, state)
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        state[target.id] = value_type
                    elif isinstance(target, ast.Attribute):
                        check_expression(target.value, state)
            elif isinstance(statement, ast.AugAssign):
                if isinstance(statement.target, ast.Name) and statement.target.id not in state:
                    fail(
                        statement.target,
                        f"Variable '{statement.target.id}' is incremented before it is assigned.",
                        suggestion="Initialize the variable before using +=, -=, *=, or another augmented assignment.",
                        code="undefined-name",
                    )
                check_expression(statement.value, state)
            elif isinstance(statement, ast.Expr):
                check_expression(statement.value, state)
            elif isinstance(statement, ast.If):
                check_expression(statement.test, state)
                first = visit_block(statement.body, dict(state))
                second = visit_block(statement.orelse, dict(state)) if statement.orelse else dict(state)
                state = merge_branches(state, first, second)
            elif isinstance(statement, ast.For):
                check_expression(statement.iter, state)
                iterator_type = _infer_expression_type(statement.iter, state)
                if _is_range_call(statement.iter):
                    assert isinstance(statement.iter, ast.Call)
                    for argument in statement.iter.args:
                        actual = _infer_expression_type(argument, state)
                        if actual is not None and actual is not int:
                            fail(
                                argument,
                                "range() arguments must evaluate to integers.",
                                suggestion="Use integer variables or integer arithmetic in range(start, stop, step).",
                                code="invalid-range-argument",
                            )
                    item_type: object | None = int
                else:
                    if not _is_bounded_iterable_type(iterator_type):
                        fail(
                            statement.iter,
                            "A for-loop must iterate over range(), a list, a tuple, or a scene.find() result.",
                            suggestion=(
                                "Use range(count), iterate over a list/tuple assigned earlier, "
                                "or use scene.find(role='...'). The iterable is checked again at runtime."
                            ),
                            code="invalid-loop-iterator",
                        )
                    item_type = _iterable_item_type(statement.iter, state)
                loop_state = dict(state)
                if isinstance(statement.target, ast.Name):
                    loop_state[statement.target.id] = item_type
                visit_block(statement.body, loop_state)
                # A loop can execute zero times; assignments in its body are not definite.
        return state

    visit_block(tree.body, environment)

def validate_script(source: str) -> ast.Module:
    """Parse and validate a scene script before executing it inside Blender.

    The language supports safe API handles, assignments, conditionals, and
    runtime-bounded loops. Statically knowable limits are checked before
    execution; dynamic iterables are guarded by the worker at runtime. This is
    a capability restriction, not an operating-system sandbox.
    """
    if not isinstance(source, str):
        raise ScriptValidationError("Python code must be a string.")
    if not source.strip():
        raise ScriptValidationError("Python code is empty.")
    if len(source) > MAX_SCRIPT_CHARS:
        raise ScriptValidationError(f"Python code exceeds {MAX_SCRIPT_CHARS:,} characters.")

    source_lines = source.splitlines()

    def fail(node: ast.AST, message: str, *, suggestion: str | None = None, code: str | None = None) -> None:
        line_no = getattr(node, "lineno", None)
        col_offset = getattr(node, "col_offset", None)
        source_line = source_lines[line_no - 1] if isinstance(line_no, int) and 1 <= line_no <= len(source_lines) else None
        raise ScriptValidationError(
            message, lineno=line_no, col_offset=col_offset,
            source_line=source_line, suggestion=suggestion, code=code,
        )

    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        line_no = exc.lineno
        source_line = source_lines[line_no - 1] if isinstance(line_no, int) and 1 <= line_no <= len(source_lines) else None
        raise ScriptValidationError(
            f"Python syntax error: {exc.msg}",
            lineno=line_no, col_offset=max(0, (exc.offset or 1) - 1),
            source_line=source_line,
            suggestion="Check the indicated line for missing brackets, quotes, commas, or indentation.",
            code="python-syntax-error",
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
    loop_counts = _collect_static_loop_counts(tree)
    loop_costs = {id(loop): len(list(ast.walk(loop))) for loop in loops}
    total_iterations = 0
    expansion_cost = 0
    assigned: set[str] = set()

    for loop in loops:
        if loop.orelse:
            fail(loop, "Loop else clauses are not supported.", code="unsupported-loop-else")
        if not isinstance(loop.target, ast.Name):
            fail(loop.target, "A loop target must be one simple variable name.", code="invalid-loop-target")
        target_name = loop.target.id
        if target_name.startswith("_") or target_name in {"studio", "math", "range"}:
            fail(loop.target, f"Invalid loop variable: {target_name}", code="invalid-loop-target")
        assigned.add(target_name)

        if _is_range_call(loop.iter):
            assert isinstance(loop.iter, ast.Call)
            if not all(_is_integer_expression(argument) for argument in loop.iter.args):
                fail(
                    loop.iter,
                    "range() accepts one to three integer expressions.",
                    suggestion="Use integer literals, previously assigned integer variables, or integer arithmetic.",
                    code="invalid-range-argument",
                )
            allowed_range_calls.add(id(loop.iter))
        elif not isinstance(loop.iter, (ast.Name, ast.List, ast.Tuple, ast.Call)):
            fail(
                loop.iter,
                "A for-loop must use range(), a list, a tuple, or a supported scene API sequence.",
                code="invalid-loop-iterator",
            )

        iterations = loop_counts.get(id(loop))
        if iterations is not None and iterations > MAX_LOOP_ITERATIONS:
            fail(
                loop.iter,
                f"A loop may run at most {MAX_LOOP_ITERATIONS} times; its bound resolves to {iterations}.",
                suggestion="Reduce the loop count or split the work across separate render jobs.",
                code="loop-iteration-limit",
            )

        ancestor = parents.get(loop)
        enclosing_iterations = 1
        depth = 1
        static_chain = iterations is not None
        while ancestor is not None:
            if isinstance(ancestor, ast.For):
                depth += 1
                ancestor_count = loop_counts.get(id(ancestor))
                if ancestor_count is None:
                    static_chain = False
                else:
                    enclosing_iterations *= ancestor_count
            ancestor = parents.get(ancestor)
        if depth > MAX_LOOP_DEPTH:
            fail(
                loop,
                f"Loop nesting may not exceed {MAX_LOOP_DEPTH} levels.",
                code="loop-depth-limit",
            )
        if static_chain:
            total_iterations += iterations * enclosing_iterations
            expansion_cost += iterations * enclosing_iterations * loop_costs[id(loop)]
            if total_iterations > MAX_TOTAL_LOOP_ITERATIONS:
                fail(
                    loop,
                    f"All loops combined may execute at most {MAX_TOTAL_LOOP_ITERATIONS:,} iterations.",
                    code="loop-total-iteration-limit",
                )
            if expansion_cost > MAX_LOOP_EXPANSION_COST:
                fail(
                    loop,
                    "The expanded loop body is too large.",
                    suggestion="Reduce nested loop counts or simplify the repeated body.",
                    code="loop-expansion-limit",
                )

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
            if chain is not None and _attribute_allowed(*chain):
                continue
            if _is_motion_track_chain(node):
                continue
            expression = ast.get_source_segment(source, node) or ast.dump(node, include_attributes=False)
            fail(
                node, f"Unsupported attribute access: {expression}",
                suggestion="Use documented handle properties. Animation tracks support scene.motion(object).track('position' | 'rotation' | 'scale').",
                code="unsupported-attribute",
            )

        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINARY_OPERATORS):
                raise ScriptValidationError("Only +, -, *, /, //, and % arithmetic is supported.")

        elif isinstance(node, ast.AugAssign):
            if not isinstance(node.op, _ALLOWED_BINARY_OPERATORS):
                raise ScriptValidationError("Unsupported augmented assignment operator.")

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
                        fail(node, "range() can only be used directly as a bounded for-loop iterator.", suggestion="Use: for index in range(10):", code="invalid-range-call")
                else:
                    fail(
                        node, f"Unsupported function call: {node.func.id}().",
                        suggestion="Python built-ins and custom functions are not exposed. Use documented blentopy API calls and math functions; range() is allowed only in a bounded for-loop.",
                        code="unsupported-function",
                    )
            else:
                chain = _attribute_chain(node.func)
                if chain is None and _is_motion_track_chain(node.func):
                    root, attributes = "motion", ("track",)
                elif chain is None:
                    expression = ast.get_source_segment(source, node.func) or ast.dump(node.func, include_attributes=False)
                    fail(
                        node, f"Unsupported chained API call: {expression}().",
                        suggestion="Assign intermediate API results to variables. The supported direct chain is scene.motion(object).track(channel).",
                        code="unsupported-call-chain",
                    )
                else:
                    root, attributes = chain
                    if not _attribute_allowed(root, attributes):
                        expression = ast.get_source_segment(source, node.func) or ".".join(attributes)
                        if root == "scene":
                            available = ", ".join(sorted(SCENE_METHODS))
                        elif root == "geo":
                            available = ", ".join(sorted(GEOMETRY_METHODS))
                        elif root == "mat":
                            available = ", ".join(sorted(MATERIAL_METHODS))
                        else:
                            available = "documented scene, object, vector, motion, track, or math methods"
                        fail(node, f"Unknown or unsupported API call: {expression}().", suggestion=f"Available methods for this API handle: {available}.", code="unknown-api-method")
                method = attributes[-1]
                if root == "math":
                    if len(attributes) != 1 or method not in _MATH_FUNCTIONS:
                        fail(node, f"math.{method}() is not a callable math function.", suggestion="Use math.sin, math.cos, math.tan, math.radians, math.degrees, or math.sqrt.", code="invalid-math-call")
                elif root == "studio":
                    allowed = (
                        method in STUDIO_METHODS
                        if len(attributes) == 1
                        else (attributes[0] == "scene" and method in SCENE_METHODS)
                        or (attributes[0] == "geo" and method in GEOMETRY_METHODS)
                        or (attributes[0] == "mat" and method in MATERIAL_METHODS)
                    )
                    if not allowed:
                        fail(node, f"Unknown blentopy API method: {ast.get_source_segment(source, node.func) or method}().", suggestion="Check docs/AI_SYSTEM_PROMPT.md for the exact method name and argument list.", code="unknown-api-method")
                elif method not in (
                    SCENE_METHODS | GEOMETRY_METHODS | MATERIAL_METHODS |
                    OBJECT_METHODS | VECTOR_METHODS | MOTION_METHODS | TRACK_METHODS
                ):
                    fail(node, f"Method '{method}' is not available on this blentopy handle.", suggestion="Use documented scene, geometry/material, Object3D, vector .set(), motion .track(), or track .key() methods.", code="unsupported-handle-method")
            if any(keyword.arg is None for keyword in node.keywords):
                fail(node, "Keyword argument unpacking (**mapping) is not supported.", suggestion="Pass each supported keyword argument explicitly.", code="keyword-unpacking")

        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                raise ScriptValidationError("Only simple string, numeric, boolean, and None literals are allowed.")
            if isinstance(node.value, str) and len(node.value) > 10_000:
                raise ScriptValidationError("A string literal is too long.")
            if isinstance(node.value, (int, float)) and abs(node.value) > 10**9:
                raise ScriptValidationError("A numeric literal is too large.")
            if isinstance(node.value, float) and not math.isfinite(node.value):
                raise ScriptValidationError("Non-finite numeric literals are not allowed.")

    _validate_dataflow(tree, fail, source)

    # Wrap every loop iterator after validation. The injected helper is not
    # addressable by authored scripts and applies the same runtime budget to
    # range(), literal sequences, and scene.find() results.
    for loop in loops:
        loop.iter = ast.copy_location(
            ast.Call(
                func=ast.Name(id="__blentopy_bounded_iter__", ctx=ast.Load()),
                args=[loop.iter, ast.Constant(value=loop_costs[id(loop)])],
                keywords=[],
            ),
            loop.iter,
        )
    ast.fix_missing_locations(tree)
    return tree
