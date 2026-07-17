# -*- coding: utf-8 -*-
"""Tests for the snapshot watchfolder pure logic (scan_snapshot_candidates).

The engine lives in sentinel.snapshots and is importable outside C4D (conftest
stubs the c4d module). These tests exercise only the pure settle/registry +
non-EXR-alert semantics; the Timer wiring and captions need live C4D.
"""
import os

from sentinel.snapshots import scan_snapshot_candidates


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
