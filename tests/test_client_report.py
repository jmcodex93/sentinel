# -*- coding: utf-8 -*-
"""Tests for the client-readable HTML report (I7).

client_report.py is a pure stdlib module (no c4d), importable via the package
path added by conftest. Fixture mirrors the shape of
sentinel.ui.reports.build_qc_report.
"""

import html as _html

from sentinel.client_report import build_client_report_html


def _report_fixture():
    """Report dict shaped like sentinel.ui.reports.build_qc_report output."""
    return {
        "report": "Sentinel QC Report",
        "version": "Sentinel v1.9.0",
        "timestamp": "2026-07-10 14:03:11",
        "scene": "robot_010_v007_TR.c4d",
        "path": "/projects/robot/scenes",
        "artist": "Javier",
        "shot_id": "SH010",
        "checks": {
            "lights": {"status": "FAIL", "count": 3, "label": "Lights outside group"},
            "visibility": {"status": "PASS", "count": 0, "label": "Visibility mismatches"},
            "camera_shift": {"status": "PASS", "count": 0, "label": "Camera shift != 0"},
            "textures": {"status": "FAIL", "count": 2,
                          "label": "Texture issues (absolute paths + missing files)"},
            "fps_range": {"status": "PASS", "count": 0, "label": "FPS & frame range validation"},
            "cross_aspect": {"status": "DISABLED", "count": 0, "disabled": True,
                              "label": "Cross-aspect safe-area violations"},
        },
        "summary": {"total_checks": 6, "passed": 3, "failed": 3, "score": "3/6"},
        "notes": {
            "summary": "Notes: text + 2 TODOs (1 pending)",
            "text": "Client wants warmer grade on hero shot.",
            "todos": [
                {"id": 1, "text": "Fix rim light", "done": False},
                {"id": 2, "text": "Re-cache alembic", "done": True},
            ],
            "pending_count": 1,
            "updated": "2026-07-10 13:00:00",
        },
    }


def _versions_fixture():
    return [
        {"version": 7, "status": "TR", "timestamp": "2026-07-10 14:00:00",
         "comment": "Sent for team review", "qc_score": "3/6", "filename": "robot_010_v007_TR.c4d"},
        {"version": 6, "status": "", "timestamp": "2026-07-09 10:00:00",
         "comment": "WIP grade pass", "qc_score": "2/6", "filename": "robot_010_v006.c4d"},
    ]


def test_every_check_row_present_with_state():
    html = build_client_report_html(_report_fixture(), versions=_versions_fixture())
    report = _report_fixture()
    for check in report["checks"].values():
        assert _html.escape(check["label"]) in html
    # Pass/fail/disabled states surface as chips.
    assert "PASS" in html
    assert "FAIL" in html
    assert "OFF" in html  # DISABLED renders as an OFF chip


def test_score_and_status_verdict():
    html = build_client_report_html(_report_fixture(), versions=_versions_fixture())
    assert "3/6" in html
    # Latest version status (TR) drives the verdict badge.
    assert "TR" in html


def test_notes_and_todos_rendered():
    html = build_client_report_html(_report_fixture(), versions=_versions_fixture())
    assert "Client wants warmer grade on hero shot." in html
    assert "Fix rim light" in html
    assert "Re-cache alembic" in html


def test_version_timeline_rendered():
    html = build_client_report_html(_report_fixture(), versions=_versions_fixture())
    assert "v007" in html
    assert "v006" in html
    assert "Sent for team review" in html


def test_snapshot_embedded_when_provided():
    html = build_client_report_html(_report_fixture(), snapshot_b64="QUJDREVG",
                                    versions=_versions_fixture())
    assert "data:image/png;base64,QUJDREVG" in html


def test_snapshot_absent_when_not_provided():
    html = build_client_report_html(_report_fixture(), versions=_versions_fixture())
    assert "data:image/png;base64" not in html


def test_report_is_self_contained():
    html = build_client_report_html(_report_fixture(), snapshot_b64="QUJD",
                                    versions=_versions_fixture())
    assert "<script src" not in html
    assert "<link" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_handles_empty_versions_and_notes():
    minimal = {
        "scene": "untitled",
        "checks": {"lights": {"status": "PASS", "count": 0, "label": "Lights outside group"}},
        "summary": {"total_checks": 1, "passed": 1, "failed": 0, "score": "1/1"},
        "notes": {"text": "", "todos": [], "pending_count": 0},
    }
    html = build_client_report_html(minimal)
    assert "untitled" in html
    assert "1/1" in html
