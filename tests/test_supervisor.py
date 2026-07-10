# -*- coding: utf-8 -*-
"""Tests for the Supervisor engine (I5-A) — pure, no Cinema 4D required."""

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_PATH = ROOT / "plugin" / "sentinel" / "supervisor.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_supervisor_under_test", SUPERVISOR_PATH
)
supervisor = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = supervisor
spec.loader.exec_module(supervisor)


NOW = datetime(2026, 7, 10, 12, 0, 0)


def _ts(days_ago, now=NOW):
    return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _entry(version, status="", score="12/12", counts=None, days_ago=1,
           schema=2, filename=None):
    """Build one schema-2 history entry (newest-first list order)."""
    base = "shot"
    fn = filename or "%s_v%03d%s.c4d" % (base, version, ("_" + status) if status else "")
    entry = {
        "version": version,
        "filename": fn,
        "status": status,
        "timestamp": _ts(days_ago),
        "scene": base,
        "qc_score": score,
    }
    if schema == 2:
        entry["schema"] = 2
        passed, total = score.split("/")
        entry["passed"] = int(passed)
        entry["total"] = int(total)
        entry["new"] = sum((counts or {}).values())
        entry["accepted"] = 0
    if counts is not None:
        entry["qc_counts"] = counts
    return entry


def _write_history(folder, base, versions, scene=None):
    path = os.path.join(str(folder), "%s_history.json" % base)
    with open(path, "w") as fh:
        json.dump({"scene": scene or base, "versions": versions}, fh)
    return path


def _write_notes(folder, base, notes="", todos=None):
    path = os.path.join(str(folder), "%s_notes.json" % base)
    with open(path, "w") as fh:
        json.dump({"scene": base, "notes": notes, "todos": todos or []}, fh)
    return path


# ── Criterion 1: 5-scene aggregation ─────────────────────────────────────────
def test_five_scene_aggregation(tmp_path):
    # robot_010: two versions, one pending TODO
    _write_history(tmp_path, "robot_010", [
        _entry(8, status="TR", score="11/12", counts={"textures": 1}, days_ago=1),
        _entry(7, status="", score="12/12", counts={}, days_ago=3),
    ])
    _write_notes(tmp_path, "robot_010", notes="hold for review",
                 todos=[{"id": 1, "text": "fix rig", "done": False},
                        {"id": 2, "text": "done thing", "done": True}])
    # A legacy (schema-1) shot with no qc_counts
    _write_history(tmp_path, "logo_intro", [
        {"version": 3, "filename": "logo_intro_v003.c4d", "status": "FINAL",
         "timestamp": _ts(2), "scene": "logo_intro", "qc_score": "10/12"},
    ])
    # three more plain shots
    _write_history(tmp_path, "alpha", [_entry(1, score="12/12", counts={}, days_ago=1)])
    _write_history(tmp_path, "beta", [_entry(2, status="CR", score="9/12",
                                             counts={"lights": 2}, days_ago=1)])
    _write_history(tmp_path, "gamma", [_entry(1, score="12/12", counts={}, days_ago=1)])

    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)

    assert meta["shot_count"] == 5
    assert len(shots) == 5
    assert not meta["warnings"]

    by_base = {s["base"]: s for s in shots}
    robot = by_base["robot_010"]
    assert robot["last_version"] == "v008"
    assert robot["status"] == "TR"
    assert robot["score"] == "11/12"
    assert robot["todos_total"] == 2
    assert robot["todos_pending"] == 1
    assert robot["version_count"] == 2

    # legacy score renders with "(legacy)" via versioning helper
    assert "legacy" in by_base["logo_intro"]["qc_label"]


def test_render_history_sidecar_is_ignored(tmp_path):
    # The post-render sidecar must not be treated as a version history.
    with open(os.path.join(str(tmp_path), "robot_010_render_history.json"), "w") as fh:
        json.dump({"validations": []}, fh)
    _write_history(tmp_path, "robot_010",
                   [_entry(1, score="12/12", counts={}, days_ago=1)])
    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert meta["shot_count"] == 1
    assert shots[0]["base"] == "robot_010"


# ── Criterion 2: regression + stale flags ────────────────────────────────────
def test_regression_flag(tmp_path):
    # Descending score across the last 3 versions -> regression.
    _write_history(tmp_path, "declining", [
        _entry(3, score="9/12", counts={"lights": 1, "textures": 2}, days_ago=1),
        _entry(2, score="10/12", counts={"lights": 1}, days_ago=2),
        _entry(1, score="12/12", counts={}, days_ago=3),
    ])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert "regression" in shots[0]["flags"]


def test_no_regression_when_not_strictly_descending(tmp_path):
    _write_history(tmp_path, "steady", [
        _entry(3, score="11/12", counts={"lights": 1}, days_ago=1),
        _entry(2, score="11/12", counts={"lights": 1}, days_ago=2),
        _entry(1, score="12/12", counts={}, days_ago=3),
    ])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert "regression" not in shots[0]["flags"]


def test_stale_flag(tmp_path):
    # Latest is WIP and 9 days old -> stale.
    _write_history(tmp_path, "abandoned", [
        _entry(2, status="", score="12/12", counts={}, days_ago=9),
        _entry(1, status="", score="12/12", counts={}, days_ago=20),
    ])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert "stale" in shots[0]["flags"]


def test_not_stale_when_recent_or_reviewed(tmp_path):
    # Recent WIP -> not stale.
    _write_history(tmp_path, "fresh",
                   [_entry(1, status="", score="12/12", counts={}, days_ago=2)])
    # Old but FINAL -> not stale (status gate).
    _write_history(tmp_path, "delivered",
                   [_entry(5, status="FINAL", score="12/12", counts={}, days_ago=40)])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    by_base = {s["base"]: s for s in shots}
    assert "stale" not in by_base["fresh"]["flags"]
    assert "stale" not in by_base["delivered"]["flags"]


# ── Criterion 4: trajectory naming ───────────────────────────────────────────
def test_trajectory_names_broken_check(tmp_path):
    # Between v007 (clean) and v008 the textures check broke -> "Assets".
    _write_history(tmp_path, "shot", [
        _entry(8, status="TR", score="11/12", counts={"textures": 1}, days_ago=1),
        _entry(7, status="", score="12/12", counts={}, days_ago=3),
    ])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    traj = shots[0]["trajectory"]
    assert len(traj) == 1
    hop = traj[0]
    assert hop["from_version"] == "v007"
    assert hop["to_version"] == "v008"
    assert hop["broke"] == ["Assets"]
    assert hop["recovered"] == []
    assert hop["no_data"] is False


def test_trajectory_recovered(tmp_path):
    _write_history(tmp_path, "shot", [
        _entry(2, score="12/12", counts={}, days_ago=1),
        _entry(1, score="11/12", counts={"names": 1}, days_ago=2),
    ])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    hop = shots[0]["trajectory"][0]
    assert hop["recovered"] == ["Naming"]
    assert hop["broke"] == []


def test_trajectory_no_data_for_legacy_hop(tmp_path):
    _write_history(tmp_path, "shot", [
        _entry(2, score="12/12", counts={"lights": 0}, days_ago=1),
        {"version": 1, "filename": "shot_v001.c4d", "status": "",
         "timestamp": _ts(2), "scene": "shot", "qc_score": "10/12"},  # no qc_counts
    ])
    shots, _ = supervisor.scan_folder(str(tmp_path), now=NOW)
    hop = shots[0]["trajectory"][0]
    assert hop["no_data"] is True


# ── Criterion 5: empty folder + corrupted sidecars ───────────────────────────
def test_empty_folder(tmp_path):
    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert shots == []
    assert meta["shot_count"] == 0
    report = supervisor.build_supervisor_report(shots, meta)
    assert "No scene sidecars" in report
    html = supervisor.build_supervisor_html(shots, meta)
    assert "No scene sidecars" in html


def test_corrupted_sidecar_skipped_with_warning(tmp_path):
    good = _write_history(tmp_path, "good",
                          [_entry(1, score="12/12", counts={}, days_ago=1)])
    assert os.path.exists(good)
    bad = os.path.join(str(tmp_path), "bad_history.json")
    with open(bad, "w") as fh:
        fh.write("{ this is not json ]")
    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert meta["shot_count"] == 1
    assert shots[0]["base"] == "good"
    assert len(meta["warnings"]) == 1
    assert "bad_history.json" in meta["warnings"][0]


def test_missing_folder_does_not_crash(tmp_path):
    shots, meta = supervisor.scan_folder(str(tmp_path / "nope"), now=NOW)
    assert shots == []
    assert meta["shot_count"] == 0


# ── Criterion 3: HTML export self-contained ──────────────────────────────────
def test_html_export_is_self_contained(tmp_path):
    _write_history(tmp_path, "robot_010", [
        _entry(8, status="TR", score="11/12", counts={"textures": 1}, days_ago=1),
        _entry(7, status="", score="12/12", counts={}, days_ago=3),
    ])
    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)
    html = supervisor.build_supervisor_html(shots, meta)

    # Table row + trajectory line present.
    assert "robot_010" in html
    assert "v008" in html
    assert "broke: Assets" in html

    # No external assets / network references.
    assert "<script src" not in html
    assert "<link" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_write_supervisor_html_atomic(tmp_path):
    _write_history(tmp_path, "shot",
                   [_entry(1, score="12/12", counts={}, days_ago=1)])
    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)
    out = supervisor.default_export_path(str(tmp_path))
    assert out.endswith("sentinel_supervisor.html")
    written = supervisor.write_supervisor_html(shots, meta, out)
    assert os.path.exists(written)
    assert not os.path.exists(out + ".tmp")
    with open(written) as fh:
        content = fh.read()
    assert "Sentinel Supervisor" in content


# ── Helper-level unit coverage ───────────────────────────────────────────────
def test_parse_score():
    assert supervisor.parse_score("9/12") == (9, 12)
    assert supervisor.parse_score("11/11 · 1 disabled") == (11, 11)
    assert supervisor.parse_score("") is None
    assert supervisor.parse_score(None) is None
    assert supervisor.parse_score("nope") is None


def test_parse_timestamp():
    assert supervisor.parse_timestamp("2026-07-10 12:00:00") == datetime(2026, 7, 10, 12, 0, 0)
    assert supervisor.parse_timestamp("garbage") is None
    assert supervisor.parse_timestamp("") is None


def test_notes_path_for_history():
    p = supervisor.notes_path_for_history("/proj/robot_010_history.json")
    assert p == os.path.join("/proj", "robot_010_notes.json")


def test_check_label_map_maps_textures_to_assets():
    assert supervisor.check_label_map()["textures"] == "Assets"


def test_ui_wiring_imports(sentinel_module):
    """The plugin package (incl. Supervisor dialog + panel wiring) imports clean."""
    from sentinel.ui.dialogs import SupervisorDialog  # noqa: F401
    from sentinel.ui.ids import G
    assert G.BTN_SUPERVISOR == 1312


def test_recursive_walk_depth(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    _write_history(nested, "deep",
                   [_entry(1, score="12/12", counts={}, days_ago=1)])
    shots, meta = supervisor.scan_folder(str(tmp_path), now=NOW)
    assert meta["shot_count"] == 1
    assert shots[0]["base"] == "deep"
