import importlib

import pytest


def test_frame_tag_imports_under_fake_c4d(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.SentinelFrameTag is not None
    assert frame_tag._DRAW_CALLS == 0


def test_is_valid_camera_host_accepts_standard_and_redshift_cameras(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.is_valid_camera_host(5103) is True
    assert frame_tag.is_valid_camera_host(1057516) is True


def test_is_valid_camera_host_rejects_non_cameras(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.is_valid_camera_host(5159) is False
    assert frame_tag.is_valid_camera_host(5140) is False


def test_composition_mode_maps_tag_cycle_to_engine_string(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.composition_mode_for_engine(frame_tag.COMPOSITION_CROP) == "crop"
    assert frame_tag.composition_mode_for_engine(frame_tag.COMPOSITION_OFF) == "none"
    assert frame_tag.composition_mode_for_engine(frame_tag.COMPOSITION_RESIZE_CANVAS) == "resize_canvas"
    assert (
        frame_tag.composition_mode_for_engine(frame_tag.COMPOSITION_PRESERVE_VERTICAL)
        == frame_tag.framing.COMPENSATE_PRESERVE_VERTICAL
    )
    # Unknown -> the default mode (crop), not "none".
    assert frame_tag.composition_mode_for_engine(99999) == "crop"


def test_film_offsets_include_only_enabled_formats(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_OFF}
    for index, _fmt in enumerate(frame_tag._format_defs()):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = False
        tag[ids["nudge_x"]] = 0.99
        tag[ids["nudge_y"]] = -0.99

    first = frame_tag._format_ids(0)
    third = frame_tag._format_ids(2)
    tag[first["enabled"]] = True
    tag[first["nudge_x"]] = 0.05
    tag[first["nudge_y"]] = -0.03
    tag[third["enabled"]] = True
    tag[third["nudge_x"]] = -0.10
    tag[third["nudge_y"]] = 0.20

    assert frame_tag._film_offsets_from_params(tag) == {
        "16x9": (0.05, -0.03),
        "1x1": (-0.10, 0.20),
    }


def test_params_signature_for_takes_is_stable_and_changes_with_nudge(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_RESIZE_CANVAS}
    for index, _fmt in enumerate(frame_tag._format_defs()):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = index in (0, 1)
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0

    first_hash = frame_tag._params_signature_for_takes(dict(tag))
    second_hash = frame_tag._params_signature_for_takes(dict(tag))
    assert first_hash == second_hash

    tag[frame_tag._format_ids(1)["nudge_x"]] = 0.01
    assert frame_tag._params_signature_for_takes(tag) != first_hash


def test_is_stale_from_signature_tracks_param_drift(sentinel_module):
    # The "Takes out of date" HUD is computed inline in Draw from the
    # BaseContainer signature (not a transient Python attribute), so it must
    # survive the draw-thread document clone. This locks that contract.
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_OFF}
    for index, _fmt in enumerate(frame_tag._format_defs()):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = index in (0, 1)
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0

    # A fresh tag with no generated Takes is never "out of date".
    assert frame_tag._is_stale_from_signature(tag) is False

    # After generation, saved signature matches current params -> fresh.
    frame_tag._write_takes_signature(tag, frame_tag._params_signature_for_takes(tag))
    assert frame_tag._is_stale_from_signature(tag) is False

    # Drifting a nudge after generation -> stale.
    tag[frame_tag._format_ids(1)["nudge_x"]] = 0.02
    assert frame_tag._is_stale_from_signature(tag) is True


def test_current_take_is_own_format_gates_guides_in_format_takes(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    class FakeTake:
        def __init__(self, name):
            self._n = name

        def GetName(self):
            return self._n

    class FakeTD:
        def __init__(self, cur, main):
            self._cur = cur
            self._main = main

        def GetCurrentTake(self):
            return self._cur

        def GetMainTake(self):
            return self._main

    class FakeCam:
        def GetName(self):
            return "Hero"

    class FakeDoc:
        def __init__(self, cur, main):
            self._td = FakeTD(cur, main)

        def GetTakeData(self):
            return self._td

    class FakeTag:
        def GetObject(self):
            return FakeCam()

    tag = FakeTag()
    main = FakeTake("Main")
    fmt_id = frame_tag._format_defs()[0].get("id")
    fmt_take = FakeTake(f"Hero_{fmt_id}")

    # Main take -> guides DO draw (composition view).
    assert frame_tag._current_take_is_own_format(tag, FakeDoc(main, main)) is False
    # Our own format take -> guides suppressed (camera already cropped).
    assert frame_tag._current_take_is_own_format(tag, FakeDoc(fmt_take, main)) is True
    # A non-Sentinel take -> guides draw.
    assert frame_tag._current_take_is_own_format(tag, FakeDoc(FakeTake("Whatever"), main)) is False
    # Right prefix but unknown suffix -> not one of ours, guides draw.
    assert frame_tag._current_take_is_own_format(tag, FakeDoc(FakeTake("Hero_foo"), main)) is False
    # A SLICE take of our own format (v1.29) -> also own-format, guides
    # suppressed; the info tuple carries the slice suffix.
    slice_take = FakeTake(f"Hero_{fmt_id}_s02")
    assert frame_tag._current_take_is_own_format(tag, FakeDoc(slice_take, main)) is True
    assert frame_tag._current_own_take_info(tag, FakeDoc(slice_take, main)) == (fmt_id, "s02")
    assert frame_tag._current_own_take_info(tag, FakeDoc(fmt_take, main)) == (fmt_id, None)
    assert frame_tag._current_own_format_id(tag, FakeDoc(slice_take, main)) == fmt_id


def test_selected_output_format_uses_first_enabled_format(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    tag = {}
    for index, _fmt in enumerate(frame_tag._format_defs()):
        tag[frame_tag._format_ids(index)["enabled"]] = False

    assert frame_tag._selected_output_format_id(tag) is None

    tag[frame_tag._format_ids(2)["enabled"]] = True
    tag[frame_tag._format_ids(4)["enabled"]] = True
    assert frame_tag._selected_output_format_id(tag) == "1x1"


def test_frame_tag_ndc_to_pixel_mapping_flips_y(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    rect = {"left": -0.5, "right": 0.5, "bottom": -0.25, "top": 0.75}

    assert frame_tag._ndc_rect_to_pixels(rect, (100, 20, 500, 220)) == (
        200.0,
        45.0,
        400.0,
        145.0,
    )


def test_frame_tag_intersection_uses_all_guides(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    rect = frame_tag._intersect_ndc_rects(
        [
            {"left": -1.0, "right": 1.0, "bottom": -0.5, "top": 0.5},
            {"left": -0.25, "right": 0.25, "bottom": -1.0, "top": 1.0},
        ]
    )

    assert rect == {"left": -0.25, "right": 0.25, "bottom": -0.5, "top": 0.5}


def test_frame_tag_inline_rects_compute_from_tag_params_without_rect_cache(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    tag = {}
    for index, _fmt in enumerate(frame_tag._format_defs()):
        tag[frame_tag._format_ids(index)["enabled"]] = False

    vertical_index = 1
    ids = frame_tag._format_ids(vertical_index)
    tag[ids["enabled"]] = True
    tag[ids["nudge_x"]] = 0.25
    tag[ids["nudge_y"]] = -0.5

    custom_insets = {
        "9x16": {"top": 0.10, "bottom": 0.20, "left": 0.03, "right": 0.12},
    }
    frame_tag._write_platform_insets_to_node(tag, custom_insets)

    rects = frame_tag._compute_inline_rects(tag, 16.0 / 9.0)

    assert not hasattr(frame_tag, "_RECT_CACHE_BY_NODE")
    assert len(rects) == 1
    entry = rects[0]
    assert entry["id"] == "9x16"
    assert entry["width"] == 1080
    assert entry["height"] == 1920

    expected_guide = frame_tag.framing.crop_rect_in_master_ndc(
        1080,
        1920,
        16.0 / 9.0,
        (0.25, -0.5),
    )
    assert entry["guide"] == {
        "left": pytest.approx(expected_guide[0]),
        "bottom": pytest.approx(expected_guide[1]),
        "right": pytest.approx(expected_guide[2]),
        "top": pytest.approx(expected_guide[3]),
    }

    expected_platform = frame_tag.format_safe_area_in_master_ndc(
        "9x16",
        16.0 / 9.0,
        frame_tag._InlineRulesContext(custom_insets),
        offset=(0.25, -0.5),
    )
    assert entry["platform"] == {
        "left": pytest.approx(expected_platform["left"]),
        "right": pytest.approx(expected_platform["right"]),
        "bottom": pytest.approx(expected_platform["bottom"]),
        "top": pytest.approx(expected_platform["top"]),
    }


def _base_tag(frame_tag, enabled_indexes=(0,)):
    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_CROP}
    for index in range(frame_tag.FORMAT_ROW_COUNT):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = index in enabled_indexes
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0
        tag[ids["slice_x"]] = 1
        tag[ids["slice_y"]] = 1
    return tag


def test_format_defs_without_node_are_the_five_standard(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    assert [d["id"] for d in frame_tag._format_defs()] == [
        "16x9", "9x16", "1x1", "4x5", "21x9"]


def test_format_defs_include_custom_when_enabled(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0, frame_tag.CUSTOM_FORMAT_INDEX))
    ids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[ids["width"]] = 9000
    tag[ids["height"]] = 500
    defs = frame_tag._format_defs(tag)
    assert defs[-1] == {"id": "custom", "label": "Custom", "width": 9000, "height": 500}
    # Disabled custom -> absent.
    tag[ids["enabled"]] = False
    assert [d["id"] for d in frame_tag._format_defs(tag)] == [
        "16x9", "9x16", "1x1", "4x5", "21x9"]
    # Canonical standard defs are never mutated by per-tag resolution.
    from sentinel.multiformat import MULTIFORMAT_DEFS
    assert "slices" not in MULTIFORMAT_DEFS[0]


def test_engine_format_defs_inject_slices(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(1, frame_tag.CUSTOM_FORMAT_INDEX))
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    tag[cids["slice_x"]] = 3
    defs = frame_tag._engine_format_defs(tag)
    by_id = {d["id"]: d for d in defs}
    assert by_id["custom"]["slices"] == (3, 1)
    assert by_id["9x16"]["slices"] == (1, 1)
    assert frame_tag._total_slice_count(tag) == 3
    # Re-assert AFTER the mutation-capable calls: the shared canonical defs
    # must never have been polluted with a per-tag "slices" key.
    from sentinel.multiformat import MULTIFORMAT_DEFS
    assert "slices" not in MULTIFORMAT_DEFS[0]


def test_signature_changes_with_slices_and_custom_size(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0, frame_tag.CUSTOM_FORMAT_INDEX))
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    base_sig = frame_tag._params_signature_for_takes(dict(tag))
    tag[frame_tag._format_ids(0)["slice_x"]] = 2
    assert frame_tag._params_signature_for_takes(dict(tag)) != base_sig
    tag[frame_tag._format_ids(0)["slice_x"]] = 1
    tag[cids["width"]] = 9001
    assert frame_tag._params_signature_for_takes(dict(tag)) != base_sig


def test_slices_default_to_1x1_for_v128_tags(sentinel_module):
    # A v1.28 scene has NO slice/custom params stored: defaults must resolve
    # to slices (1,1) and custom disabled, i.e. the same defs as before.
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_CROP}
    for index in range(5):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = True
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0
    assert [d["id"] for d in frame_tag._format_defs(tag)] == [
        "16x9", "9x16", "1x1", "4x5", "21x9"]
    assert all(d["slices"] == (1, 1) for d in frame_tag._engine_format_defs(tag))
    assert frame_tag._slices_for_index(tag, 0) == (1, 1)


def test_parse_own_format_suffix(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    defs = [{"id": "9x16"}, {"id": "custom"}]
    assert frame_tag._parse_own_format_suffix("9x16", defs) == ("9x16", None)
    assert frame_tag._parse_own_format_suffix("custom_s02", defs) == ("custom", "s02")
    assert frame_tag._parse_own_format_suffix("custom", defs) == ("custom", None)
    assert frame_tag._parse_own_format_suffix("foo", defs) is None
    assert frame_tag._parse_own_format_suffix("9x16_s2x", defs) is None


def test_slice_link_ids_disjoint_per_format(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    ids = {frame_tag._slice_link_id(i, o)
           for i in range(frame_tag.FORMAT_ROW_COUNT)
           for o in range(1, 257)}
    assert len(ids) == frame_tag.FORMAT_ROW_COUNT * 256
    assert min(ids) == frame_tag.ID_PRIVATE_SLICE_LINK_BASE
    # Never collides with any declared description id or the existing
    # private id neighborhoods: groups (incl. custom), format rows (incl.
    # custom), insets, take-link/signature/focus, actions.
    reserved = set(range(900, 905))
    reserved |= set(range(1000, 1014))
    reserved |= set(range(1100, 1220))
    reserved |= set(range(2000, 2060))
    reserved |= set(range(2400, 2406))
    reserved |= set(range(2500, 2503))
    reserved |= set(range(3000, 3005))
    assert ids.isdisjoint(reserved)


def test_link_for_key_roundtrip(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0,))
    frame_tag._write_link_for_key(tag, "16x9", "TAKE_WHOLE")
    frame_tag._write_link_for_key(tag, "16x9:s03", "TAKE_S3")
    assert frame_tag._read_link_for_key(tag, "16x9", None) == "TAKE_WHOLE"
    assert frame_tag._read_link_for_key(tag, "16x9:s03", None) == "TAKE_S3"
    assert frame_tag._read_link_for_key(tag, "16x9:s04", None) is None


def test_viewing_targets_list_slices(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0, frame_tag.CUSTOM_FORMAT_INDEX))
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    tag[cids["slice_x"]] = 3
    assert frame_tag.viewing_targets(tag) == [
        "master", "16x9", "custom:s01", "custom:s02", "custom:s03"]


def test_expected_take_names_and_shrunk_grid_prune(sentinel_module):
    # Prune contract (carried-over from Task 3's review): a 16x9 row sliced
    # 2x1 expects ONLY Hero_16x9_s01/s02. The old whole-format take
    # (Hero_16x9) AND a leftover slice take from a bigger grid
    # (Hero_16x9_s03, e.g. after shrinking 3x1 -> 2x1) are both orphans;
    # Hero_16x9_s02 is expected and must never be pruned.
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    class FakeCam:
        def GetName(self):
            return "Hero"

    class FakeTagDict(dict):
        def GetObject(self):
            return FakeCam()

    class FakeTake:
        def __init__(self, name):
            self._n = name
            self._down = None
            self._next = None

        def GetName(self):
            return self._n

        def GetDown(self):
            return self._down

        def GetNext(self):
            return self._next

    class FakeTD:
        def __init__(self, main):
            self._main = main

        def GetMainTake(self):
            return self._main

        def GetCurrentTake(self):
            return self._main

    class FakeDoc:
        def __init__(self, main):
            self._td = FakeTD(main)

        def GetTakeData(self):
            return self._td

    tag = FakeTagDict(_base_tag(frame_tag, enabled_indexes=(0,)))
    tag[frame_tag._format_ids(0)["slice_x"]] = 2

    assert frame_tag._expected_take_names(tag) == {
        "Hero_16x9_s01": "16x9:s01",
        "Hero_16x9_s02": "16x9:s02",
    }

    main = FakeTake("Main")
    whole = FakeTake("Hero_16x9")
    s02 = FakeTake("Hero_16x9_s02")
    s03 = FakeTake("Hero_16x9_s03")
    main._down = whole
    whole._next = s02
    s02._next = s03

    orphans = frame_tag._find_orphaned_takes_for_tag(tag, FakeDoc(main))
    by_name = {take.GetName(): key for key, take in orphans}
    assert sorted(by_name) == ["Hero_16x9", "Hero_16x9_s03"]
    assert by_name["Hero_16x9"] == "16x9"
    assert by_name["Hero_16x9_s03"] == "16x9:s03"


def test_prune_finds_disabled_custom_takes(sentinel_module):
    # A DISABLED custom row's takes must still be pruned: the name-parse defs
    # include {"id": "custom"} unconditionally.
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    class FakeCam:
        def GetName(self):
            return "Hero"

    class FakeTagDict(dict):
        def GetObject(self):
            return FakeCam()

    class FakeTake:
        def __init__(self, name):
            self._n = name
            self._down = None
            self._next = None

        def GetName(self):
            return self._n

        def GetDown(self):
            return self._down

        def GetNext(self):
            return self._next

    class FakeTD:
        def __init__(self, main):
            self._main = main

        def GetMainTake(self):
            return self._main

        def GetCurrentTake(self):
            return self._main

    class FakeDoc:
        def __init__(self, main):
            self._td = FakeTD(main)

        def GetTakeData(self):
            return self._td

    tag = FakeTagDict(_base_tag(frame_tag, enabled_indexes=(0,)))
    main = FakeTake("Main")
    custom_whole = FakeTake("Hero_custom")
    custom_slice = FakeTake("Hero_custom_s01")
    kept = FakeTake("Hero_16x9")
    main._down = custom_whole
    custom_whole._next = custom_slice
    custom_slice._next = kept

    orphans = frame_tag._find_orphaned_takes_for_tag(tag, FakeDoc(main))
    by_name = {take.GetName(): key for key, take in orphans}
    assert sorted(by_name) == ["Hero_custom", "Hero_custom_s01"]
    assert by_name["Hero_custom"] == "custom"
    assert by_name["Hero_custom_s01"] == "custom:s01"


def test_run_takes_generation_passes_format_defs_and_key_callbacks(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    class FakeCam:
        def GetName(self):
            return "Hero"

        def GetType(self):
            return 5103

    class FakeTagDict(dict):
        def GetObject(self):
            return FakeCam()

    class FakeDoc:
        def __init__(self):
            self.undos = []

        def AddUndo(self, undo_type, target):
            self.undos.append((undo_type, target))

    tag = FakeTagDict(_base_tag(frame_tag, enabled_indexes=(0,)))
    tag[frame_tag._format_ids(0)["slice_x"]] = 2
    captured = {}

    def _fake_generate(doc, options):
        captured.update(options)
        # Engine contract: keys are fmt_id or "<fmt>:sNN".
        options["tag_link_writer"]("16x9:s01", "TAKE_S1")
        return {"errors": []}

    doc = FakeDoc()
    original = frame_tag.generate_multiformat_takes
    frame_tag.generate_multiformat_takes = _fake_generate
    try:
        frame_tag._run_takes_generation(doc, tag)
    finally:
        frame_tag.generate_multiformat_takes = original

    defs_by_id = {d["id"]: d for d in captured["format_defs"]}
    assert defs_by_id["16x9"]["slices"] == (2, 1)
    # The writer stored the take under the slice link, readable by key.
    assert frame_tag._read_link_for_key(tag, "16x9:s01", None) == "TAKE_S1"
    assert captured["existing_take_resolver"]("16x9:s01") == "TAKE_S1"
    # Undo anchor bookkeeping preserved: the tag was anchored exactly once.
    assert doc.undos.count((frame_tag._undo_type_change(), tag)) == 1


def test_set_viewing_accepts_slice_targets(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    class FakeTake:
        def __init__(self, name):
            self._n = name

        def GetName(self):
            return self._n

    class FakeTD:
        def __init__(self, main):
            self._main = main
            self.current = None

        def GetMainTake(self):
            return self._main

        def SetCurrentTake(self, take):
            self.current = take

    class FakeDoc:
        def __init__(self, main):
            self._td = FakeTD(main)

        def GetTakeData(self):
            return self._td

    tag = _base_tag(frame_tag, enabled_indexes=(0,))
    tag[frame_tag._format_ids(0)["slice_x"]] = 2
    slice_take = FakeTake("Hero_16x9_s02")
    frame_tag._write_link_for_key(tag, "16x9:s02", slice_take)

    doc = FakeDoc(FakeTake("Main"))
    result = frame_tag.set_viewing(doc, tag, "16x9:s02")
    assert result == {"ok": True, "viewing": "16x9:s02", "error": None}
    assert doc.GetTakeData().current is slice_take

    # Unknown slice target -> rejected, never activates anything.
    assert frame_tag.set_viewing(doc, tag, "16x9:s09")["ok"] is False
