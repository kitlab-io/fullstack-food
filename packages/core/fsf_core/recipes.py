"""Recipe resolution: species defaults -> recipe stage -> goal overlay -> planting overrides."""

from __future__ import annotations

import copy
from typing import Any

STAGE_KEYS = ("targets", "control", "alerts")


def deep_merge(base: Any, over: Any, add_new_list_items: bool = True) -> Any:
    """Merge `over` onto `base`.

    Dicts merge key by key. Lists of dicts that carry an `id` merge by id.
    Any other value in `over` replaces the one in `base`.
    """
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for key, value in over.items():
            out[key] = deep_merge(base[key], value, add_new_list_items) if key in base else copy.deepcopy(value)
        return out
    if _is_id_list(base) and _is_id_list(over):
        out_list = [copy.deepcopy(item) for item in base]
        index = {item["id"]: i for i, item in enumerate(out_list)}
        for item in over:
            if item["id"] in index:
                out_list[index[item["id"]]] = deep_merge(out_list[index[item["id"]]], item, add_new_list_items)
            elif add_new_list_items:
                out_list.append(copy.deepcopy(item))
        return out_list
    return copy.deepcopy(over)


def _is_id_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(i, dict) and "id" in i for i in value)


def _stage_body(source: dict) -> dict:
    return {k: copy.deepcopy(source[k]) for k in STAGE_KEYS if k in source}


def _apply_overlay(stage: dict, overlay: dict) -> dict:
    """Overlays tune existing loops; they never add a control loop a stage did not have."""
    body = deep_merge(stage, _stage_body(overlay), add_new_list_items=False)
    per_stage = (overlay.get("stages") or {}).get(stage["id"])
    if per_stage:
        body = deep_merge(body, _stage_body(per_stage), add_new_list_items=False)
    return body


def resolve_recipe(recipe: dict, species: dict | None = None, goal: dict | None = None,
                   overrides: dict | None = None) -> dict:
    """Return {"id", "stages": [...], "layers": [...]} with every layer applied.

    A steady recipe becomes a single stage called `steady` that never advances.
    `layers` names what was applied, in order, so a setpoint can be traced.
    """
    if recipe["mode"] == "steady":
        stages = [{"id": "steady", **_stage_body(recipe)}]
    else:
        stages = copy.deepcopy(recipe["stages"])

    layers = []
    defaults = (species or {}).get("defaults")
    if defaults:
        # Species defaults sit underneath the recipe, so the recipe wins on conflict.
        stages = [deep_merge({"id": s["id"], **_stage_body(defaults)}, s) for s in stages]
        layers.append(f"species:{species['id']}")
    layers.append(f"recipe:{recipe['id']}")
    if goal and goal.get("overlay"):
        stages = [_apply_overlay(s, goal["overlay"]) for s in stages]
        layers.append(f"goal:{goal['id']}")
    if overrides:
        stages = [_apply_overlay(s, overrides) for s in stages]
        layers.append("planting:overrides")

    for stage in stages:
        stage.setdefault("targets", {})
        stage.setdefault("control", [])
        stage.setdefault("alerts", [])
    return {"id": recipe["id"], "mode": recipe["mode"], "stages": stages, "layers": layers}
