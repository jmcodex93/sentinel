# -*- coding: utf-8 -*-
"""Tests for the snapshot watchfolder pure logic (scan_snapshot_candidates,
parse_rv_snapshot_dir, next_snapshot_name).

The engine lives in sentinel.snapshots and is importable outside C4D (conftest
stubs the c4d module). These tests exercise only the pure settle/registry +
non-EXR-alert semantics, the redshift_rv.cfg parser, and the unique-naming
helper; the Timer wiring and captions need live C4D.
"""
import os

from sentinel.snapshots import (
    _find_latest_exr,
    next_snapshot_name,
    parse_rv_snapshot_dir,
    scan_snapshot_candidates,
)


def _write(path, content=b"x", mtime=None):
    with open(path, "wb") as f:
        f.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _touch_exr(dir_, name, size=10, mtime=1000.0):
    return _write(os.path.join(dir_, name), b"y" * size, mtime=mtime)


def test_first_sighting_not_ready(tmp_path):
    d = str(tmp_path)
    _touch_exr(d, "a_image.exr")
    ready, reg, alert = scan_snapshot_candidates(d, {})
    assert ready == []
    assert "a_image.exr" in reg
    assert reg["a_image.exr"][2] == "pending"
    assert alert is False


def test_stable_across_two_scans_ready_once(tmp_path):
    d = str(tmp_path)
    p = _touch_exr(d, "a_image.exr")

    ready1, reg1, _ = scan_snapshot_candidates(d, {})
    assert ready1 == []

    ready2, reg2, _ = scan_snapshot_candidates(d, reg1)
    assert ready2 == [p]
    assert reg2["a_image.exr"][2] == "processed"

    # Third scan: identical -> never returned again.
    ready3, reg3, _ = scan_snapshot_candidates(d, reg2)
    assert ready3 == []
    assert reg3["a_image.exr"][2] == "processed"


def test_changing_size_resets_settle(tmp_path):
    d = str(tmp_path)
    name = "a_image.exr"
    _touch_exr(d, name, size=10, mtime=1000.0)
    _, reg1, _ = scan_snapshot_candidates(d, {})

    # File grows (still being written) before the second scan -> not ready.
    _touch_exr(d, name, size=50, mtime=1000.0)
    ready2, reg2, _ = scan_snapshot_candidates(d, reg1)
    assert ready2 == []
    assert reg2[name][2] == "pending"

    # Now stable across two scans -> ready.
    ready3, reg3, _ = scan_snapshot_candidates(d, reg2)
    assert len(ready3) == 1


def test_changing_mtime_resets_settle(tmp_path):
    d = str(tmp_path)
    name = "a_image.exr"
    _touch_exr(d, name, size=10, mtime=1000.0)
    _, reg1, _ = scan_snapshot_candidates(d, {})

    _touch_exr(d, name, size=10, mtime=2000.0)
    ready2, reg2, _ = scan_snapshot_candidates(d, reg1)
    assert ready2 == []
    assert reg2[name][2] == "pending"


def test_reused_name_new_mtime_reconverts(tmp_path):
    d = str(tmp_path)
    name = "a_image.exr"
    _touch_exr(d, name, size=10, mtime=1000.0)
    _, reg1, _ = scan_snapshot_candidates(d, {})
    ready2, reg2, _ = scan_snapshot_candidates(d, reg1)
    assert len(ready2) == 1  # processed

    # A brand-new snapshot overwrites the same name with a newer mtime.
    _touch_exr(d, name, size=10, mtime=3000.0)
    ready3, reg3, _ = scan_snapshot_candidates(d, reg2)
    assert ready3 == []                      # re-armed, awaiting settle
    assert reg3[name][2] == "pending"
    ready4, reg4, _ = scan_snapshot_candidates(d, reg3)
    assert len(ready4) == 1                   # settled -> converts again


# NOTE on the three tests below: since the streamlined-flow change, non-EXR
# files (b_image.png) now ALSO enter the settle registry (previously only
# .exr files were tracked at all — a non-EXR file was invisible to the
# registry and only fed the newest_any/newest_exr alert bookkeeping). These
# tests still discard the registry/ready values (`_`) and only assert on
# non_exr_alert, whose semantics are UNCHANGED by design (still "newest file
# overall is non-EXR and newer than the newest EXR") — so the assertions
# below are unchanged even though the engine now does more work per scan.
# Coverage for the new "non-EXR also settles" behavior lives in
# test_png_settles_and_becomes_ready below.

def test_non_exr_newer_than_newest_exr_alerts(tmp_path):
    d = str(tmp_path)
    _touch_exr(d, "a_image.exr", mtime=1000.0)
    _write(os.path.join(d, "b_image.png"), mtime=2000.0)
    _, _, alert = scan_snapshot_candidates(d, {})
    assert alert is True


def test_exr_newest_no_alert(tmp_path):
    d = str(tmp_path)
    _write(os.path.join(d, "b_image.png"), mtime=1000.0)
    _touch_exr(d, "a_image.exr", mtime=2000.0)
    _, _, alert = scan_snapshot_candidates(d, {})
    assert alert is False


def test_no_exr_at_all_but_non_exr_present_alerts(tmp_path):
    d = str(tmp_path)
    _write(os.path.join(d, "b_image.png"), mtime=1000.0)
    _, _, alert = scan_snapshot_candidates(d, {})
    assert alert is True


def test_png_settles_and_becomes_ready(tmp_path):
    """New contract: display-referred exts (.png/.jpg/.jpeg/.tif/.tiff) go
    through the SAME two-scan settle rule as .exr, so a stable PNG becomes
    ready just like a stable EXR (streamlined flow: these are copied instead
    of ACES-converted, but the watchfolder settle logic is identical)."""
    d = str(tmp_path)
    p = _write(os.path.join(d, "a_image.png"), mtime=1000.0)

    ready1, reg1, _ = scan_snapshot_candidates(d, {})
    assert ready1 == []
    assert reg1["a_image.png"][2] == "pending"

    ready2, reg2, _ = scan_snapshot_candidates(d, reg1)
    assert ready2 == [p]
    assert reg2["a_image.png"][2] == "processed"

    ready3, _, _ = scan_snapshot_candidates(d, reg2)
    assert ready3 == []  # already processed; never returned again


def test_mixed_exts_settle_independently(tmp_path):
    """A .exr and a .jpg in the same directory each go through their own
    settle cycle but share one registry dict (no cross-contamination)."""
    d = str(tmp_path)
    exr = _touch_exr(d, "a_image.exr", mtime=1000.0)
    jpg = _write(os.path.join(d, "b_image.jpg"), mtime=1000.0)

    _, reg1, _ = scan_snapshot_candidates(d, {})
    ready2, reg2, _ = scan_snapshot_candidates(d, reg1)
    assert sorted(ready2) == sorted([exr, jpg])
    assert reg2["a_image.exr"][2] == "processed"
    assert reg2["b_image.jpg"][2] == "processed"


def test_empty_dir_no_crash_no_alert(tmp_path):
    d = str(tmp_path)
    ready, reg, alert = scan_snapshot_candidates(d, {})
    assert ready == []
    assert reg == {}
    assert alert is False


def test_missing_dir_no_crash(tmp_path):
    d = os.path.join(str(tmp_path), "does_not_exist")
    ready, reg, alert = scan_snapshot_candidates(d, {"stale": (1, 2, "processed")})
    assert ready == []
    assert alert is False
    # Registry passed through unchanged (as a dict), never raises.
    assert reg == {"stale": (1, 2, "processed")}


def test_none_registry_ok(tmp_path):
    d = str(tmp_path)
    _touch_exr(d, "a_image.exr")
    ready, reg, alert = scan_snapshot_candidates(d, None)
    assert ready == []
    assert isinstance(reg, dict)


# ── parse_rv_snapshot_dir ───────────────────────────────────────────────

def test_parse_rv_snapshot_dir_real_format_line():
    """VERIFIED real redshift_rv.cfg shape (JSON-like, tab-indented, trailing
    comma) — the regex fallback handles this since a trailing comma makes
    the whole text invalid strict JSON."""
    cfg_text = (
        "{\n"
        "\t\"someOtherKey\" : 1,\n"
        "\t\t\"snapshotDir\" : \"/Users/javiermelgar/Documents/RS Snapshots\",\n"
        "\t\"yetAnotherKey\" : false,\n"
        "}\n"
    )
    assert parse_rv_snapshot_dir(cfg_text) == "/Users/javiermelgar/Documents/RS Snapshots"


def test_parse_rv_snapshot_dir_full_json_variant():
    """Strict JSON (no trailing comma) — takes the json.loads fast path."""
    cfg_text = '{"snapshotDir": "/Users/artist/Snaps", "other": 1}'
    assert parse_rv_snapshot_dir(cfg_text) == "/Users/artist/Snaps"


def test_parse_rv_snapshot_dir_absent_key():
    cfg_text = '{"someOtherKey": "value", "another": 42}'
    assert parse_rv_snapshot_dir(cfg_text) is None


def test_parse_rv_snapshot_dir_empty_value():
    cfg_text = '{"snapshotDir": ""}'
    assert parse_rv_snapshot_dir(cfg_text) is None


def test_parse_rv_snapshot_dir_malformed_text():
    cfg_text = "this is not json or anything parseable {{{ garbage ]]"
    assert parse_rv_snapshot_dir(cfg_text) is None


def test_parse_rv_snapshot_dir_empty_or_none():
    assert parse_rv_snapshot_dir("") is None
    assert parse_rv_snapshot_dir(None) is None


# ── next_snapshot_name ──────────────────────────────────────────────────

def test_next_snapshot_name_empty_dir():
    assert next_snapshot_name([], "myscene") == "myscene_snap_001.png"


def test_next_snapshot_name_increments_past_highest():
    existing = ["myscene_snap_001.png", "myscene_snap_002.png"]
    assert next_snapshot_name(existing, "myscene") == "myscene_snap_003.png"


def test_next_snapshot_name_mixed_exts_share_counter():
    """A .png and a copied .jpg for the same scene must never collide on
    the same index — the counter scans ALL extensions."""
    existing = ["myscene_snap_001.png", "myscene_snap_002.jpg"]
    assert next_snapshot_name(existing, "myscene") == "myscene_snap_003.png"
    assert next_snapshot_name(existing, "myscene", ext=".jpg") == "myscene_snap_003.jpg"


def test_next_snapshot_name_ignores_unrelated_files():
    existing = ["othershot_snap_005.png", "random.txt", "myscene_notes.json"]
    assert next_snapshot_name(existing, "myscene") == "myscene_snap_001.png"


def test_next_snapshot_name_scene_with_regex_special_chars():
    """Scene names may contain regex-special characters (parens, brackets,
    dots) — the prefix match is plain string comparison, not a regex built
    from scene_name, so it must not crash or mis-match."""
    scene = "shot (v2).cool[1]"
    existing = [f"{scene}_snap_001.png"]
    assert next_snapshot_name(existing, scene) == f"{scene}_snap_002.png"
    # And an empty dir with a special-char scene name still starts at 001.
    assert next_snapshot_name([], scene) == f"{scene}_snap_001.png"


def test_settings_watch_roundtrip():
    """GlobalSettings.get/set_snapshot_watch roundtrip (mirrors slate pattern)."""
    from sentinel.common import settings as settings_mod

    store = {}
    orig_load = settings_mod.GlobalSettings._load
    orig_save = settings_mod.GlobalSettings._save
    settings_mod.GlobalSettings._load = staticmethod(lambda: dict(store))

    def _save(data):
        store.clear()
        store.update(data)
        return True

    settings_mod.GlobalSettings._save = staticmethod(_save)
    try:
        assert settings_mod.GlobalSettings.get_snapshot_watch() is False
        settings_mod.GlobalSettings.set_snapshot_watch(True)
        assert settings_mod.GlobalSettings.get_snapshot_watch() is True
        settings_mod.GlobalSettings.set_snapshot_watch(False)
        assert settings_mod.GlobalSettings.get_snapshot_watch() is False
    finally:
        settings_mod.GlobalSettings._load = staticmethod(orig_load)
        settings_mod.GlobalSettings._save = staticmethod(orig_save)


# ── _find_latest_exr snap_dir routing (Phase 3 IA consolidation) ──────────
#
# Regression coverage for the Save Still fix: _find_latest_exr used to read
# ONLY GlobalSettings.get_snapshot_dir() (manual value), inconsistent with
# the watchfolder prime which already auto-detects first. It now accepts an
# optional snap_dir so callers (ui.flows.snapshot_save_still) can pass the
# already-resolved effective dir straight through.

def test_find_latest_exr_uses_snap_dir_param_not_a_decoy(tmp_path):
    """snap_dir, when passed, is read directly — a second dir (standing in
    for whatever GlobalSettings.get_snapshot_dir() would have returned)
    with a chronologically NEWER file must be ignored entirely."""
    passed_dir = tmp_path / "detected"
    decoy_dir = tmp_path / "decoy"
    passed_dir.mkdir()
    decoy_dir.mkdir()

    older = _touch_exr(str(passed_dir), "older.exr", mtime=1000.0)
    newer_in_passed = _touch_exr(str(passed_dir), "newer.exr", mtime=2000.0)
    # Newer than both files above, but in the decoy dir — must not win.
    _touch_exr(str(decoy_dir), "newest_decoy.exr", mtime=9999.0)

    path, error = _find_latest_exr(snap_dir=str(passed_dir))
    assert error is None
    assert path == newer_in_passed
    assert path != older


def test_find_latest_exr_snap_dir_none_falls_back_to_global_settings(tmp_path):
    """Omitting snap_dir (legacy call shape) still resolves the manual
    GlobalSettings value directly — unchanged behavior for any caller that
    hasn't adopted the effective-dir helper."""
    from sentinel.common import settings as settings_mod

    snap_dir = str(tmp_path)
    only_exr = _touch_exr(snap_dir, "only.exr", mtime=1234.0)

    store = {"snapshot_dir": snap_dir}
    orig_load = settings_mod.GlobalSettings._load
    orig_save = settings_mod.GlobalSettings._save
    settings_mod.GlobalSettings._load = staticmethod(lambda: dict(store))

    def _save(data):
        store.clear()
        store.update(data)
        return True

    settings_mod.GlobalSettings._save = staticmethod(_save)
    try:
        path, error = _find_latest_exr()  # snap_dir omitted
        assert error is None
        assert path == only_exr
    finally:
        settings_mod.GlobalSettings._load = staticmethod(orig_load)
        settings_mod.GlobalSettings._save = staticmethod(orig_save)


def test_find_latest_exr_missing_or_empty_dir_returns_none_with_reason(tmp_path):
    """Contract: (None, message) — never raises — for a dir that doesn't
    exist yet, and separately for one that exists but has no EXRs."""
    missing_dir = str(tmp_path / "does_not_exist")
    path, error = _find_latest_exr(snap_dir=missing_dir)
    assert path is None
    assert "not found" in error

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    path, error = _find_latest_exr(snap_dir=str(empty_dir))
    assert path is None
    assert "No EXR snapshots found" in error
