# -*- coding: utf-8 -*-
"""Tests for GlobalSettings.get/set_asset_hub_col_widths (Asset Hub UI
polish, item 3 — user-resizable columns). Same in-memory _load/_save
monkeypatch pattern as test_snapshot_watch.py's test_settings_watch_roundtrip.
"""
from sentinel.common import settings as settings_mod
from sentinel.common.settings import ASSET_HUB_COL_WIDTHS_DEFAULT


def _patched_settings(store):
    orig_load = settings_mod.GlobalSettings._load
    orig_save = settings_mod.GlobalSettings._save
    settings_mod.GlobalSettings._load = staticmethod(lambda: dict(store))

    def _save(data):
        store.clear()
        store.update(data)
        return True

    settings_mod.GlobalSettings._save = staticmethod(_save)
    return orig_load, orig_save


def _restore_settings(orig_load, orig_save):
    settings_mod.GlobalSettings._load = staticmethod(orig_load)
    settings_mod.GlobalSettings._save = staticmethod(orig_save)


def test_col_widths_default_when_unset():
    store = {}
    orig = _patched_settings(store)
    try:
        widths = settings_mod.GlobalSettings.get_asset_hub_col_widths()
        assert widths == ASSET_HUB_COL_WIDTHS_DEFAULT
        # Returned dict must be a copy — mutating it must not corrupt the
        # module-level default used as the fallback for every other caller.
        widths["name"] = 999
        assert settings_mod.GlobalSettings.get_asset_hub_col_widths()["name"] == \
            ASSET_HUB_COL_WIDTHS_DEFAULT["name"]
    finally:
        _restore_settings(*orig)


def test_col_widths_roundtrip():
    store = {}
    orig = _patched_settings(store)
    try:
        settings_mod.GlobalSettings.set_asset_hub_col_widths(
            {"name": 260, "type": 90, "size": 70, "used": 150})
        widths = settings_mod.GlobalSettings.get_asset_hub_col_widths()
        assert widths == {"name": 260, "type": 90, "size": 70, "used": 150}
    finally:
        _restore_settings(*orig)


def test_col_widths_per_key_validation_falls_back_to_defaults():
    """A malformed/legacy value never crashes — each bad key falls back to
    its own default individually, valid sibling keys are kept."""
    store = {}
    orig = _patched_settings(store)
    try:
        settings_mod.GlobalSettings.set_asset_hub_col_widths({
            "name": 260,          # valid
            "type": "wide",       # wrong type -> default
            "size": -5,           # below the drag-clamp floor -> default
            "used": 5,            # below MIN_COL_WIDTH (40) -> default
            "bogus": 999,         # unknown key -> ignored
        })
        widths = settings_mod.GlobalSettings.get_asset_hub_col_widths()
        assert widths["name"] == 260
        assert widths["type"] == ASSET_HUB_COL_WIDTHS_DEFAULT["type"]
        assert widths["size"] == ASSET_HUB_COL_WIDTHS_DEFAULT["size"]
        assert widths["used"] == ASSET_HUB_COL_WIDTHS_DEFAULT["used"]
        assert "bogus" not in widths
    finally:
        _restore_settings(*orig)


def test_col_widths_non_dict_value_falls_back_entirely():
    store = {"asset_hub_col_widths": "not-a-dict"}
    orig = _patched_settings(store)
    try:
        widths = settings_mod.GlobalSettings.get_asset_hub_col_widths()
        assert widths == ASSET_HUB_COL_WIDTHS_DEFAULT
    finally:
        _restore_settings(*orig)
