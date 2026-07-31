import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS_PATH = ROOT / "plugin" / "sentinel" / "pins.py"
spec = importlib.util.spec_from_file_location("sentinel_pins_under_test", PINS_PATH)
pins = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pins
spec.loader.exec_module(pins)


def node(name, children=(), geometry=False):
    return {"name": name, "geometry": geometry, "children": list(children)}


def test_keys_are_relative_to_the_pinned_root():
    """Keys start at the tag's object, NOT at the scene root, so moving the
    whole rig somewhere else does not invalidate its pins."""
    tree = node("rig", [node("ctrl"), node("geo")])
    assert pins.location_keys(tree) == ["", "ctrl", "geo"]


def test_same_named_siblings_get_indices_in_traversal_order():
    tree = node("rig", [node("Cube"), node("Cube"), node("Sphere")])
    assert pins.location_keys(tree) == ["", "Cube[0]", "Cube[1]", "Sphere"]


def test_nesting_is_encoded_in_the_path():
    tree = node("rig", [node("arm", [node("hand")])])
    assert pins.location_keys(tree) == ["", "arm", "arm/hand"]


def test_traversal_is_depth_first_and_stable():
    """Restore pairs by key, but the ORDER also has to be stable so a pin
    written today lines up with a plan computed tomorrow."""
    tree = node("rig", [node("a", [node("a1"), node("a2")]), node("b")])
    assert pins.location_keys(tree) == ["", "a", "a/a1", "a/a2", "b"]


def test_restore_plan_reports_missing_and_extra():
    """Restore never creates or deletes: what vanished is reported, what
    appeared since is left alone."""
    plan = pins.plan_restore(["", "ctrl", "geo"], ["", "ctrl", "newthing"])
    assert plan["matched"] == ["", "ctrl"]
    assert plan["missing"] == ["geo"]
    assert plan["extra"] == ["newthing"]


def test_restore_plan_with_nothing_left_matches_nothing():
    plan = pins.plan_restore(["", "ctrl"], [])
    assert plan["matched"] == []
    assert plan["missing"] == ["", "ctrl"]


def test_slot_summary_of_an_empty_slot():
    assert pins.slot_summary(None) == {
        "filled": False, "label": "", "count": 0, "has_geometry": False}


def test_slot_summary_reports_geometry_so_the_row_can_warn():
    """The row must say "geometry not included" at STORE time — the artist
    who pins a polygon object will otherwise expect the modelling back."""
    slot = {"label": "wide", "entries": [
        {"key": "", "geometry": False}, {"key": "geo", "geometry": True}]}
    summary = pins.slot_summary(slot)
    assert summary == {
        "filled": True, "label": "wide", "count": 2, "has_geometry": True}


def test_reserved_slot_is_the_seventh_and_not_an_artist_slot():
    assert pins.MAX_SLOTS == 6
    assert pins.RESERVED_SLOT == 6
