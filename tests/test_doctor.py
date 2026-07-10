# -*- coding: utf-8 -*-
"""Pure-function tests for Sentinel Doctor (sentinel/doctor.py).

The engine is stdlib-only with function-local c4d access, so the item builders
and the update-version comparison are all testable without Cinema 4D and without
touching the network (the update check is exercised via build_update_item, which
takes already-fetched inputs).
"""

import json
import os
from pathlib import Path

import pytest

# conftest puts plugin/ on sys.path; doctor imports no c4d at module load.
from sentinel import doctor


# ── c4d version parsing / item ───────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    (2026301, 2026),
    (2024000, 2024),
    (21000, 21),
    (0, None),
    (-5, None),
    (None, None),
    ("bad", None),
])
def test_parse_c4d_major(raw, expected):
    assert doctor.parse_c4d_major(raw) == expected


def test_version_item_supported():
    item = doctor.build_c4d_version_item(2026301)
    assert item["status"] == doctor.OK


def test_version_item_untested_warns():
    item = doctor.build_c4d_version_item(2023100)
    assert item["status"] == doctor.WARN
    assert "2023" in item["detail"]


def test_version_item_unreadable():
    item = doctor.build_c4d_version_item(None)
    assert item["status"] == doctor.WARN


# ── payload integrity ────────────────────────────────────────────────────────
def _make_running_root(root):
    os.makedirs(os.path.join(root, "res", "description"))
    os.makedirs(os.path.join(root, "res", "strings_us"))
    os.makedirs(os.path.join(root, "sentinel"))
    os.makedirs(os.path.join(root, "abc_retime"))
    Path(os.path.join(root, "res", "c4d_symbols.h")).write_text("x")
    Path(os.path.join(root, "sentinel", "__init__.py")).write_text("x")


def test_payload_item_ok(tmp_path):
    root = str(tmp_path / "Sentinel")
    _make_running_root(root)
    item = doctor.build_payload_item(root)
    assert item["status"] == doctor.OK


def test_payload_item_missing_res_names_file(tmp_path):
    root = str(tmp_path / "Sentinel")
    _make_running_root(root)
    os.remove(os.path.join(root, "res", "c4d_symbols.h"))
    item = doctor.build_payload_item(root)
    assert item["status"] == doctor.FAIL
    assert "c4d_symbols.h" in item["detail"]


def test_payload_item_no_root():
    item = doctor.build_payload_item("/nonexistent/xyz")
    assert item["status"] == doctor.FAIL


# ── settings item ────────────────────────────────────────────────────────────
def test_settings_item_ok(tmp_path):
    settings = tmp_path / "sentinel_settings.json"
    settings.write_text(json.dumps({"artist_name": "x"}))
    item = doctor.build_settings_item(str(settings),
                                      str(tmp_path / "ys_guardian_settings.json"))
    assert item["status"] == doctor.OK


def test_settings_item_corrupt_is_fail(tmp_path):
    settings = tmp_path / "sentinel_settings.json"
    settings.write_text("{not json")
    item = doctor.build_settings_item(str(settings), str(tmp_path / "legacy.json"))
    assert item["status"] == doctor.FAIL


def test_settings_item_legacy_only_is_info(tmp_path):
    legacy = tmp_path / "ys_guardian_settings.json"
    legacy.write_text(json.dumps({}))
    item = doctor.build_settings_item(str(tmp_path / "sentinel_settings.json"),
                                      str(legacy))
    assert item["status"] == doctor.INFO
    assert "legacy" in item["detail"].lower()


def test_settings_item_fresh_prefs_dir_is_info(tmp_path):
    item = doctor.build_settings_item(str(tmp_path / "sentinel_settings.json"),
                                      str(tmp_path / "legacy.json"))
    assert item["status"] == doctor.INFO


# ── renderers / python / permissions ─────────────────────────────────────────
def test_renderers_item_found():
    item = doctor.build_renderers_item(["Redshift", "Arnold"])
    assert item["status"] == doctor.OK
    assert "Redshift" in item["detail"]


def test_renderers_item_none_is_info():
    item = doctor.build_renderers_item([])
    assert item["status"] == doctor.INFO


def test_python_item_found(tmp_path):
    py = tmp_path / "python3"
    py.write_text("x")
    item = doctor.build_python_item(str(py))
    assert item["status"] == doctor.OK


def test_python_item_missing_warns():
    item = doctor.build_python_item(None)
    assert item["status"] == doctor.WARN


def test_write_permission_ok(tmp_path):
    item = doctor.build_write_permission_item("p", "Prefs", str(tmp_path))
    assert item["status"] == doctor.OK


def test_write_permission_missing_dir(tmp_path):
    item = doctor.build_write_permission_item(
        "p", "Scene", str(tmp_path / "gone"))
    assert item["status"] == doctor.WARN


# ── update version comparison (network mocked out entirely) ──────────────────
@pytest.mark.parametrize("cur,latest,expected", [
    ("1.9.0", "1.9.0", "current"),
    ("1.9.0", "1.10.0", "outdated"),
    ("1.9.0", "v2.0.0", "outdated"),
    ("v1.9.0", "1.8.5", "current"),   # ahead counts as current
    ("1.9.0", "", "unknown"),
    ("1.9.0", None, "unknown"),
    ("1.9.0", "not-a-version", "unknown"),
])
def test_compare_versions(cur, latest, expected):
    assert doctor.compare_versions(cur, latest) == expected


def test_update_item_outdated_is_info():
    item = doctor.build_update_item("1.9.0", "2.0.0")
    assert item["status"] == doctor.INFO
    assert "2.0.0" in item["detail"]


def test_update_item_up_to_date_ok():
    item = doctor.build_update_item("1.9.0", "1.9.0")
    assert item["status"] == doctor.OK


def test_update_item_offline_is_info_not_error():
    item = doctor.build_update_item("1.9.0", None, error="Network unreachable")
    assert item["status"] == doctor.INFO
    assert "Network" in item["detail"]


def test_update_item_ssl_error_gets_certificate_hint():
    # C4D's embedded Python often lacks CA certs — the item must say so and
    # point at manual release checking, NOT claim the user is offline
    # (verified live in C4D 2026.301: CERTIFICATE_VERIFY_FAILED while online).
    err = "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"
    item = doctor.build_update_item("1.9.0", None, error=err)
    assert item["status"] == doctor.INFO
    assert "certificate" in item["detail"].lower()
    assert "offline" not in item["hint"].lower()
    assert "releases" in item["hint"]


# ── copyable report ──────────────────────────────────────────────────────────
def test_copyable_report_contains_meta_and_items():
    items = [
        doctor._item("a", "Version", doctor.OK, "C4D 2026", ""),
        doctor._item("b", "Payload", doctor.FAIL, "missing res", "reinstall"),
    ]
    meta = {"sentinel_version": "1.9.0", "c4d_version": "2026",
            "os": "Darwin 25", "renderers": "Redshift",
            "settings_path": "/tmp/s.json"}
    text = doctor.build_copyable_report(items, meta)
    assert "Sentinel version : 1.9.0" in text
    assert "[OK]" in text and "[FAIL]" in text
    assert "Redshift" in text
    assert "hint: reinstall" in text  # hint shown for FAIL


def test_check_for_update_offline_degrades(monkeypatch):
    """No network: force urlopen to raise, expect a graceful INFO item."""
    import urllib.request

    def _boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    item = doctor.check_for_update(current_version="1.9.0", timeout=1)
    assert item["status"] == doctor.INFO
    assert item["id"] == "update"
