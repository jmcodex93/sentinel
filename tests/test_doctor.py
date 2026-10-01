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
    """Use the complete distributable, including the committed frontend."""
    import shutil
    source = Path(__file__).resolve().parents[1] / 'plugin'
    shutil.copytree(source, root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))


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


def test_python_item_bare_name_resolved_on_path(tmp_path, monkeypatch):
    """Windows acceptance round 2 (2026-09-30): discovery returns the bare
    name ``python`` when the interpreter comes from PATH, and the EXR
    converter ran fine with it — but Doctor tested ``os.path.exists("python")``
    and warned that no Python was found. A bare name is resolved on PATH, the
    way the converter's subprocess resolves it."""
    real = tmp_path / "Scripts" / "python.exe"
    real.parent.mkdir()
    real.write_text("x")
    monkeypatch.setattr(doctor.shutil, "which",
                        lambda name: str(real) if name == "python" else None)
    item = doctor.build_python_item("python")
    assert item["status"] == doctor.OK
    assert str(real) in item["detail"]


def test_python_item_bare_name_not_on_path_warns(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    item = doctor.build_python_item("python")
    assert item["status"] == doctor.WARN


def test_python_item_absolute_path_that_is_gone_warns(tmp_path):
    item = doctor.build_python_item(str(tmp_path / "gone" / "python3"))
    assert item["status"] == doctor.WARN


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


# ── Known host issues ────────────────────────────────────────────────────────


def test_windows_2026_3_warns_about_the_frame_tag_crash():
    """Windows acceptance (2026-09-30 / 2026-10-01): on Windows with C4D
    2026.3.4, expanding the Sentinel Frame tag in the Attribute Manager closed
    C4D (native null call, reproduced by hand); 2026.4.0 is fine. The studio
    standardised on 2026.4.0, so a machine left on 2026.3.x must be told."""
    items = doctor.build_known_issue_items(2026304, "Windows")
    assert len(items) == 1
    assert items[0]["status"] == doctor.WARN
    assert "2026.4" in items[0]["hint"]
    assert "Frame" in items[0]["detail"]


def test_no_known_issue_elsewhere():
    assert doctor.build_known_issue_items(2026400, "Windows") == []
    assert doctor.build_known_issue_items(2026299, "Windows") == []
    assert doctor.build_known_issue_items(2026304, "Darwin") == []
    assert doctor.build_known_issue_items(None, "Windows") == []
