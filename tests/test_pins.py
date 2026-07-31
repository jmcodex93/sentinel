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
    assert pins.location_keys(tree) == ["", "ctrl[0]", "geo[0]"]


def test_same_named_siblings_get_indices_in_traversal_order():
    tree = node("rig", [node("Cube"), node("Cube"), node("Sphere")])
    assert pins.location_keys(tree) == ["", "Cube[0]", "Cube[1]", "Sphere[0]"]


def test_nesting_is_encoded_in_the_path():
    tree = node("rig", [node("arm", [node("hand")])])
    assert pins.location_keys(tree) == ["", "arm[0]", "arm[0]/hand[0]"]


def test_traversal_is_depth_first_and_stable():
    """Restore pairs by key, but the ORDER also has to be stable so a pin
    written today lines up with a plan computed tomorrow."""
    tree = node("rig", [node("a", [node("a1"), node("a2")]), node("b")])
    assert pins.location_keys(tree) == [
        "", "a[0]", "a[0]/a1[0]", "a[0]/a2[0]", "b[0]"]


def test_indexing_is_unconditional_so_a_lone_sibling_stays_stable():
    """Before the escaping fix, a lone `ctrl` keyed as bare `ctrl`, and the
    moment a second `ctrl` sibling appeared the first one silently renamed
    itself to `ctrl[0]` — breaking every pin stored before the rename.
    Indexing every child unconditionally means a lone sibling is already
    `ctrl[0]`, so adding a second `ctrl` never changes the first one's key."""
    lone = node("rig", [node("ctrl")])
    with_sibling = node("rig", [node("ctrl"), node("ctrl")])
    assert pins.location_keys(lone)[1] == "ctrl[0]"
    assert pins.location_keys(with_sibling)[1] == "ctrl[0]"


def test_name_with_brackets_does_not_collide_with_auto_index():
    """An object named `Cube[0]` sitting next to two plain `Cube` siblings
    must not collide with the auto-generated index of either of them."""
    tree = node("rig", [node("Cube[0]"), node("Cube"), node("Cube")])
    keys = pins.location_keys(tree)
    assert keys == ["", "Cube\\[0][0]", "Cube[0]", "Cube[1]"]
    assert len(set(keys)) == len(keys)


def test_name_with_slash_does_not_collide_with_nested_path():
    """An object literally named `a/b` must not collide with a nested child
    `b` under a sibling named `a`."""
    tree = node("rig", [node("a/b"), node("a", [node("b")])])
    keys = pins.location_keys(tree)
    assert keys == ["", "a\\/b[0]", "a[0]", "a[0]/b[0]"]
    assert len(set(keys)) == len(keys)


def test_lone_empty_named_child_does_not_collide_with_its_parent():
    tree = node("rig", [node("")])
    keys = pins.location_keys(tree)
    assert keys == ["", "[0]"]
    assert len(set(keys)) == len(keys)


def test_two_nameless_children_get_distinct_keys():
    """A node missing the "name" key entirely (not just empty-string) must
    still key distinctly from its siblings."""
    tree = {"name": "rig", "geometry": False, "children": [
        {"geometry": False, "children": []},
        {"geometry": False, "children": []},
    ]}
    keys = pins.location_keys(tree)
    assert keys == ["", "[0]", "[1]"]
    assert len(set(keys)) == len(keys)


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


def test_pin_summary_of_an_empty_pin():
    assert pins.pin_summary(None) == {
        "filled": False, "label": "", "count": 0,
        "has_geometry": False, "has_keyframes": False}


def test_pin_summary_reports_geometry_so_the_row_can_warn():
    """The row must say "geometry not included" at STORE time — the artist
    who pins a polygon object will otherwise expect the modelling back."""
    pin = {"label": "wide", "entries": [
        {"key": "", "geometry": False, "keyframes": False},
        {"key": "geo", "geometry": True, "keyframes": False}]}
    summary = pins.pin_summary(pin)
    assert summary == {
        "filled": True, "label": "wide", "count": 2,
        "has_geometry": True, "has_keyframes": False}


def test_pin_summary_reports_keyframes_so_a_restore_is_never_a_silent_no_op():
    """An animated parameter overwrites its restored value on the very next
    frame — the restore silently does nothing on exactly the rigs the tool
    exists for, unless the row says so."""
    pin = {"label": "", "entries": [
        {"key": "", "geometry": False, "keyframes": False},
        {"key": "ctrl", "geometry": False, "keyframes": True}]}
    summary = pins.pin_summary(pin)
    assert summary["has_keyframes"] is True
    assert summary["has_geometry"] is False


def test_safety_pin_name_is_the_tool_owned_restore_backup():
    assert pins.SAFETY_PIN_NAME == "↩ Antes de restaurar"
