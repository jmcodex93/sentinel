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
        "has_geometry": False, "has_keyframes": False,
        "tracks_captured": 0, "tracks_skipped": 0}


def test_pin_summary_reports_geometry_so_the_row_can_warn():
    """The row must say "geometry not included" at STORE time — the artist
    who pins a polygon object will otherwise expect the modelling back."""
    pin = {"label": "wide", "entries": [
        {"key": "", "geometry": False, "tracks_captured": 0, "tracks_skipped": 0},
        {"key": "geo", "geometry": True, "tracks_captured": 0, "tracks_skipped": 0}]}
    summary = pins.pin_summary(pin)
    assert summary == {
        "filled": True, "label": "wide", "count": 2,
        "has_geometry": True, "has_keyframes": False,
        "tracks_captured": 0, "tracks_skipped": 0}


def test_pin_summary_reports_skipped_tracks_so_a_restore_is_never_a_silent_no_op():
    """A DATA/PLUGIN track (or a track this build simply can't parse) can't
    be captured at all — the restore silently does nothing for exactly the
    animation the tool exists to protect, unless the row says so."""
    pin = {"label": "", "entries": [
        {"key": "", "geometry": False, "tracks_captured": 3, "tracks_skipped": 0},
        {"key": "ctrl", "geometry": False, "tracks_captured": 0, "tracks_skipped": 1}]}
    summary = pins.pin_summary(pin)
    assert summary["has_keyframes"] is True
    assert summary["has_geometry"] is False
    assert summary["tracks_captured"] == 3
    assert summary["tracks_skipped"] == 1


def test_pin_summary_captured_tracks_alone_do_not_trigger_the_warning():
    """VALUE tracks that WERE captured must not read as "not captured" —
    only genuinely skipped tracks should light up has_keyframes."""
    pin = {"label": "", "entries": [
        {"key": "ctrl", "geometry": False, "tracks_captured": 2, "tracks_skipped": 0}]}
    summary = pins.pin_summary(pin)
    assert summary["has_keyframes"] is False
    assert summary["tracks_captured"] == 2


def test_safety_pin_name_is_the_tool_owned_restore_backup():
    assert pins.SAFETY_PIN_NAME == "↩ Antes de restaurar"


# --- Task 6: which track categories are in scope, and how they're keyed --

def test_only_value_category_tracks_are_captured():
    assert pins.is_captured_track_category(pins.TRACK_CATEGORY_VALUE) is True
    assert pins.is_captured_track_category(pins.TRACK_CATEGORY_OTHER) is False
    assert pins.is_captured_track_category("something_unrecognized") is False


def test_track_capture_counts_splits_captured_and_skipped():
    categories = [
        pins.TRACK_CATEGORY_VALUE,
        pins.TRACK_CATEGORY_VALUE,
        pins.TRACK_CATEGORY_OTHER,
    ]
    assert pins.track_capture_counts(categories) == {"captured": 2, "skipped": 1}


def test_track_capture_counts_of_nothing_is_all_zero():
    assert pins.track_capture_counts([]) == {"captured": 0, "skipped": 0}
    assert pins.track_capture_counts(None) == {"captured": 0, "skipped": 0}


def test_track_key_combines_owner_and_description_id():
    key = pins.track_key("", [(903, 23, 5155), (1000, 19, 23)])
    assert key == "::903.23.5155/1000.19.23"


def test_track_key_distinguishes_object_from_tag_owner():
    """The SAME parameter id on the object vs. on a tag must key
    differently — otherwise a restore could write an object-level track's
    keys onto a same-shaped tag track (or vice versa)."""
    object_key = pins.track_key("", [(1000, 19, 23)])
    tag_key = pins.track_key("tag[0]", [(1000, 19, 23)])
    assert object_key != tag_key


def test_track_key_of_a_root_level_track_has_no_nesting_ambiguity():
    """A track with a single DescID level still produces a valid, distinct
    key — no accidental collision with an empty desc_id_parts list."""
    key = pins.track_key("", [(1000, 0, 0)])
    empty_key = pins.track_key("", [])
    assert key != empty_key


# Color palette tests removed (v1.35.2): PIN_COLOR_PALETTE and
# pin_color_palette_is_legible_on_dark are gone — the color row now exposes
# the tag's native ID_BASELIST_ICON_COLORIZE_MODE/ID_BASELIST_ICON_COLOR
# directly (see pins.py's "Icon color" section and pin_tag.py's
# GetDDescription), so there is no palette of our own left to test.


# --- Tag owner keys: type + NAME + position among homonyms ---------------

def test_tag_owner_key_shape():
    assert pins.tag_owner_key(1011, "arriba", 0) == "tag[1011:arriba:0]"


def test_tag_owner_key_distinguishes_same_type_tags_by_name():
    """The whole point of the name entering the key: two tags of the SAME
    type re-pair by name, so swapping their order no longer swaps which
    track each one's pinned keys land on."""
    assert pins.tag_owner_key(1011, "arriba", 0) != pins.tag_owner_key(1011, "abajo", 0)


def test_tag_owner_key_escapes_names_that_mimic_the_key_syntax():
    """A tag name is artist text and can contain the very characters the
    key format uses (``[`` for the index suffix, ``/`` for nesting, ``\\``
    for the escape itself) — the same class of collision
    ``location_keys`` was fixed for. Names are run through the SAME
    escaper, so a tag literally named ``ctrl[0]`` never reads as the
    auto-index of a plain ``ctrl``.

    Honest about what this test can and cannot prove: the distinctness
    assertion below ALSO holds with the escaping removed (verified by
    mutation). That is not a gap in the test — this key format happens to
    be injective on its own, because the index is written unconditionally
    and terminates the string, so the last ``:`` always splits name from
    index unambiguously no matter what the name contains. The escaping is
    therefore consistency with ``location_keys`` plus insurance against a
    future format change, not the thing holding collisions off today; the
    assertion that actually fails when it is removed is the literal-shape
    one at the end."""
    keys = {
        pins.tag_owner_key(1011, "ctrl[0]", 0),
        pins.tag_owner_key(1011, "ctrl", 0),
        pins.tag_owner_key(1011, "ctrl", 1),
        pins.tag_owner_key(1011, "a/b", 0),
        pins.tag_owner_key(1011, "a\\b", 0),
        pins.tag_owner_key(1011, "a\\/b", 0),
    }
    assert len(keys) == 6
    assert pins.tag_owner_key(1011, "ctrl[0]", 0) == "tag[1011:ctrl\\[0]:0]"
    assert pins.tag_owner_key(1011, "a/b", 0) == "tag[1011:a\\/b:0]"


def test_tag_owner_key_indexes_unconditionally():
    """Same rule, same reason as ``location_keys``: a lone tag is already
    ``:0``, so the key it was pinned under does not rewrite itself the day
    a homonym appears."""
    assert pins.tag_owner_key(1011, "ctrl", 0).endswith(":0]")


def test_tag_owner_key_of_an_unnamed_tag_is_still_valid():
    assert pins.tag_owner_key(1011, "", 0) == "tag[1011::0]"
    assert pins.tag_owner_key(1011, None, 0) == "tag[1011::0]"


# --- Homonym tag groups (the residual ambiguity, declared on the row) ----

def _tk(tag_type, name, index, desc=((1000, 19, 5616),)):
    """A track key exactly as ``_capture_node_tracks`` writes one."""
    return pins.track_key(pins.tag_owner_key(tag_type, name, index), list(desc))


def test_homonym_tag_group_count_flags_two_same_named_tags():
    """Two tags of the same type AND the same name are only told apart by
    their position, and a reorder swaps their animation silently — the row
    has to say so."""
    node = [_tk(5616, "mat", 0), _tk(5616, "mat", 1)]
    assert pins.homonym_tag_group_count([node]) == 1


def test_homonym_tag_group_count_ignores_differently_named_tags():
    """The NAME in the key already disambiguates these — nothing to warn
    about (that is exactly what 761cbef bought)."""
    node = [_tk(5616, "arriba", 0), _tk(5616, "abajo", 0)]
    assert pins.homonym_tag_group_count([node]) == 0


def test_homonym_tag_group_count_groups_by_type_as_well_as_name():
    """A group is (type, name), and the assertion has to be built so a
    type-BLIND implementation actually fails it. Two tags of different
    types sharing a name are both index 0 — a name-only grouping dedupes
    them back to one member and reports 0 either way, so that shape proves
    nothing. Two same-named PAIRS of different types do: the honest answer
    is two independent naming problems, while name-only grouping merges
    the four keys into a single ``{0, 1}`` bucket and reports 1."""
    ok = [_tk(5616, "mat", 0), _tk(1019364, "mat", 0)]
    assert pins.homonym_tag_group_count([ok]) == 0

    two_typed_pairs = [_tk(5616, "mat", 0), _tk(5616, "mat", 1),
                       _tk(1019364, "mat", 0), _tk(1019364, "mat", 1)]
    assert pins.homonym_tag_group_count([two_typed_pairs]) == 2


def test_homonym_tag_group_count_counts_groups_not_members():
    """Three homonyms are ONE ambiguous group, not three: the artist has
    one naming problem to fix, not three."""
    node = [_tk(5616, "mat", 0), _tk(5616, "mat", 1), _tk(5616, "mat", 2)]
    assert pins.homonym_tag_group_count([node]) == 1


def test_homonym_tag_group_count_adds_up_distinct_groups():
    node = [_tk(5616, "mat", 0), _tk(5616, "mat", 1),
            _tk(1019364, "ctrl", 0), _tk(1019364, "ctrl", 1)]
    assert pins.homonym_tag_group_count([node]) == 2


def test_homonym_tag_group_count_sums_over_nodes():
    """Groups are per NODE: two objects each carrying their own pair of
    homonyms are two problems, not one — a flat count over all keys would
    merge them because their keys are literally identical strings."""
    node = [_tk(5616, "mat", 0), _tk(5616, "mat", 1)]
    assert pins.homonym_tag_group_count([node, list(node)]) == 2


def test_homonym_tag_group_count_ignores_a_single_tag_and_object_tracks():
    """A lone tag is already keyed ``:0`` (unconditional index) — being
    indexed is not being ambiguous. Object-level tracks (owner ``""``)
    have no tag identity at all and never form a group."""
    assert pins.homonym_tag_group_count([[_tk(5616, "mat", 0)]]) == 0
    assert pins.homonym_tag_group_count(
        [[pins.track_key("", [(903, 23, 5155)]),
          pins.track_key("", [(904, 23, 5155)])]]) == 0


def test_homonym_tag_group_count_survives_names_made_of_key_syntax():
    """Names are artist text and may contain the very characters the key
    format uses (``:`` is not even escaped). Same collision discipline as
    ``location_keys``: no name may invent a group it doesn't have, and no
    name may hide a real one.

    ``"a:0"`` vs ``"a"`` is the sharp pair: naive parsing that takes the
    FIRST ``:`` after the type reads ``a:0``'s index as ``0`` and its name
    as ``a``, merging it with the genuinely different ``a`` tags."""
    # No false group: five distinct names, one tag each.
    distinct = [_tk(5616, n, 0)
                for n in ("a:0", "a", "a[0]", "a/b", "a\\b")]
    assert pins.homonym_tag_group_count([distinct]) == 0
    # No lost group: the same awkward names, this time genuinely doubled.
    for name in ("a:0", "a[0]", "a/b", "a\\b", "", "mat:"):
        assert pins.homonym_tag_group_count(
            [[_tk(5616, name, 0), _tk(5616, name, 1)]]) == 1, name


def test_homonym_tag_group_count_ignores_malformed_and_empty_input():
    """Never raises on a payload it doesn't recognise — a pin written by
    another build must degrade to "nothing to warn about", not break the
    row. ``obj[0]:0]::…`` is deliberately shaped like a key without being
    one: it reaches the parse and is rejected by the ``tag[`` prefix."""
    assert pins.homonym_tag_group_count([]) == 0
    assert pins.homonym_tag_group_count(None) == 0
    assert pins.homonym_tag_group_count(
        [[""], [None], ["garbage"],
         ["obj[0]:0]::1000.19.5616", "obj[0]:1]::1000.19.5616"]]) == 0
