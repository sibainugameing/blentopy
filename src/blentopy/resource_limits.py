"""Conservative scene resource budgets for AI-generated Blender projects."""

from __future__ import annotations

MAX_SCENE_OBJECTS = 1_000
MAX_SCENE_POLYGONS = 300_000
MAX_SCENE_MODIFIERS = 1_500


class ResourceLimitError(ValueError):
    """Raised before a scene operation would exceed a resource budget."""

    code = "resource-limit-exceeded"


def _modifier_factor(modifier: object) -> int:
    """Return a bounded polygon multiplier for an unevaluated Blender modifier."""
    cap = MAX_SCENE_POLYGONS + 1
    kind = str(getattr(modifier, "type", ""))
    if kind == "ARRAY":
        return min(cap, max(1, int(getattr(modifier, "count", 1))))
    if kind == "SUBSURF":
        levels = max(
            int(getattr(modifier, "levels", 0)),
            int(getattr(modifier, "render_levels", 0)),
        )
        # 4**10 already exceeds the complete scene polygon budget.
        return cap if levels >= 10 else 4 ** max(0, levels)
    if kind == "MIRROR":
        axes = getattr(modifier, "use_axis", (True, False, False))
        enabled = sum(bool(value) for value in axes)
        return 2 ** max(0, enabled)
    if kind == "SOLIDIFY":
        return 2
    if kind == "BEVEL":
        segments = max(1, int(getattr(modifier, "segments", 1)))
        return min(cap, 1 + 2 * segments)
    if kind == "BOOLEAN":
        return 2
    if kind in {"WEIGHTED_NORMAL", "NORMAL_EDIT", "SMOOTH_BY_ANGLE"}:
        return 1
    # Unknown modifiers are budgeted conservatively instead of being free.
    return 4


def _mesh_polygon_count(obj: object) -> int:
    if getattr(obj, "type", None) != "MESH":
        return 0
    data = getattr(obj, "data", None)
    return len(getattr(data, "polygons", ()))


def estimate_object_polygons(obj: object, *, extra_modifier: object | None = None) -> int:
    """Estimate post-modifier polygon count without evaluating a Blender depsgraph."""
    base = _mesh_polygon_count(obj)
    if base <= 0:
        return 0
    factor = 1
    for modifier in getattr(obj, "modifiers", ()):
        multiplier = _modifier_factor(modifier)
        if multiplier > MAX_SCENE_POLYGONS // max(1, base * factor):
            return MAX_SCENE_POLYGONS + 1
        factor *= multiplier
    if extra_modifier is not None:
        multiplier = _modifier_factor(extra_modifier)
        if multiplier > MAX_SCENE_POLYGONS // max(1, base * factor):
            return MAX_SCENE_POLYGONS + 1
        factor *= multiplier
    return base * factor


def modifier_polygon_delta(obj: object, modifier_type: str, **settings: object) -> int:
    """Return the additional estimated polygons contributed by one new modifier."""
    base = _mesh_polygon_count(obj)
    if base <= 0:
        return 0

    class PlannedModifier:
        def __init__(self, kind: str, values: dict[str, object]) -> None:
            self.type = kind
            for key, value in values.items():
                setattr(self, key, value)

    before = estimate_object_polygons(obj)
    after = estimate_object_polygons(
        obj, extra_modifier=PlannedModifier(modifier_type, settings)
    )
    return max(0, after - before)


def scene_resource_usage(scene: object) -> dict[str, int]:
    objects = list(getattr(scene, "objects", ()))
    return {
        "objects": len(objects),
        "polygons": sum(estimate_object_polygons(obj) for obj in objects),
        "modifiers": sum(len(getattr(obj, "modifiers", ())) for obj in objects),
    }


def ensure_scene_capacity(
    scene: object,
    *,
    added_objects: int = 0,
    added_polygons: int = 0,
    added_modifiers: int = 0,
) -> dict[str, int]:
    """Check planned work before creating objects or adding modifiers."""
    for label, value in (
        ("added_objects", added_objects),
        ("added_polygons", added_polygons),
        ("added_modifiers", added_modifiers),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{label} must be a non-negative integer.")
    usage = scene_resource_usage(scene)
    planned = {
        "objects": usage["objects"] + added_objects,
        "polygons": usage["polygons"] + added_polygons,
        "modifiers": usage["modifiers"] + added_modifiers,
    }
    limits = {
        "objects": MAX_SCENE_OBJECTS,
        "polygons": MAX_SCENE_POLYGONS,
        "modifiers": MAX_SCENE_MODIFIERS,
    }
    for resource, value in planned.items():
        limit = limits[resource]
        if value > limit:
            raise ResourceLimitError(
                f"Scene {resource} budget exceeded: planned {value:,}, limit {limit:,}. "
                "Reduce object count, mesh density, subdivision levels, or repeated arrays."
            )
    return usage
