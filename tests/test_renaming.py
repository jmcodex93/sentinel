import importlib

import pytest


@pytest.fixture
def renaming(sentinel_module):
    return importlib.import_module("sentinel.renaming")


def _items(*names, parent="", type_name="Cube"):
    return [{"name": n, "parent": parent, "type_name": type_name} for n in names]


def test_pattern_counter_start_and_padding(renaming):
    ops = renaming.normalize_ops({"pattern": "luz_$n", "num_start": 5, "num_padding": 2})
    plan = renaming.rename_plan(_items("a", "b", "c"), ops)
    assert [r["new"] for r in plan] == ["luz_05", "luz_06", "luz_07"]
    assert [r["old"] for r in plan] == ["a", "b", "c"]


def test_token_order_name_before_n(renaming):
    # "$name" must not be corrupted by the "$n" replacement.
    ops = renaming.normalize_ops({"pattern": "$name_$n"})
    plan = renaming.rename_plan(_items("Cubo"), ops)
    assert plan[0]["new"] == "Cubo_001"


def test_parent_and_type_tokens(renaming):
    ops = renaming.normalize_ops({"pattern": "$parent/$type_$n"})
    plan = renaming.rename_plan(
        [{"name": "x", "parent": "GRP", "type_name": "Light"}], ops)
    assert plan[0]["new"] == "GRP/Light_001"


def test_find_replace_case_insensitive_default_and_match_case(renaming):
    items = _items("Hero_CAM", "hero_cam")
    ops = renaming.normalize_ops({"find": "hero", "replace": "Villain"})
    assert [r["new"] for r in renaming.rename_plan(items, ops)] == [
        "Villain_CAM", "Villain_cam"]
    ops_cs = renaming.normalize_ops(
        {"find": "hero", "replace": "Villain", "match_case": True})
    assert [r["new"] for r in renaming.rename_plan(items, ops_cs)] == [
        "Hero_CAM", "Villain_cam"]


def test_replace_with_backslashes_stays_literal(renaming):
    ops = renaming.normalize_ops({"find": "a", "replace": r"C:\1"})
    assert renaming.rename_plan(_items("a"), ops)[0]["new"] == r"C:\1"


def test_pipeline_order_pattern_then_replace_then_fixes(renaming):
    ops = renaming.normalize_ops({
        "pattern": "cam_$n", "find": "cam", "replace": "shot",
        "prefix": "PRE_", "suffix": "_POST"})
    assert renaming.rename_plan(_items("whatever"), ops)[0]["new"] == "PRE_shot_001_POST"


def test_collisions_flagged_not_blocked(renaming):
    ops = renaming.normalize_ops({"pattern": "same"})
    plan = renaming.rename_plan(_items("a", "b"), ops)
    assert all(r["new"] == "same" and r["collision"] for r in plan)
    plan2 = renaming.rename_plan(_items("a", "b"), renaming.normalize_ops({"pattern": "u_$n"}))
    assert not any(r["collision"] for r in plan2)


def test_noop_and_neutral_config(renaming):
    assert renaming.ops_is_noop(renaming.normalize_ops({})) is True
    assert renaming.ops_is_noop(renaming.normalize_ops({"suffix": "_x"})) is False
    plan = renaming.rename_plan(_items("keep"), renaming.normalize_ops({}))
    assert plan[0]["old"] == plan[0]["new"] == "keep"


def test_normalize_ops_defensive(renaming):
    ops = renaming.normalize_ops(
        {"num_start": "nope", "num_padding": 99, "match_case": 1, "pattern": 5})
    assert ops["num_start"] == 1        # malformed -> default
    assert ops["num_padding"] == 8      # clamped
    assert ops["match_case"] is True
    assert ops["pattern"] == "5"
    assert renaming.normalize_ops(None) == renaming.DEFAULT_OPS
