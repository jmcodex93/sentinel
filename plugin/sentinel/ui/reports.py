# -*- coding: utf-8 -*-
"""QC report assembly for Sentinel.

Pure data layer extracted from ui/panel.py (Phase 4): builds the QC report
dict. The SaveDialog + file write wrapper stays in the panel. No c4d.gui
imports here (engine layering).
"""
import os

from sentinel import PLUGIN_NAME
from sentinel.common.helpers import safe_print
from sentinel.qc.registry import CHECK_REGISTRY
from sentinel.notes import get_notes_path, load_notes, summarize_notes
from sentinel.ui.user_areas import _accepted_entry_payload, _violation_label


def _report_key_by_check_id():
    """check_id -> report section key, derived from the registry."""
    return {entry.check_id: entry.report_key for entry in CHECK_REGISTRY}


def build_baseline_artifact_details(qc_summary):
    """Return JSON-safe baseline split details for reports/manifests."""
    if not isinstance(qc_summary, dict) or qc_summary.get("schema") != 2:
        return {}

    details = {}
    matches = qc_summary.get("baseline_matches", {}) or {}
    for check_id, match in matches.items():
        new_items = [_violation_label(item) for item in (match.get("new") or [])]
        accepted = []
        accepted_entries = match.get("accepted_entries") or []
        accepted_violations = match.get("accepted") or []
        for index, entry in enumerate(accepted_entries):
            violation = accepted_violations[index] if index < len(accepted_violations) else None
            accepted.append(_accepted_entry_payload(entry, violation))
        stale = [_accepted_entry_payload(entry) for entry in (match.get("stale_entries") or [])]
        details[check_id] = {
            "new_count": len(new_items),
            "accepted_count": len(accepted),
            "stale_count": len(stale),
            "new": new_items,
            "accepted": accepted,
            "stale": stale,
        }
    return details


def build_qc_report(doc, results, artist_name, qc_summary=None):
    """Build the Sentinel QC report dict (pure; no file I/O)."""
    from datetime import datetime

    # Build report
    report = {
        "report": "Sentinel QC Report",
        "version": PLUGIN_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene": doc.GetDocumentName() or "untitled",
        "path": doc.GetDocumentPath() or "",
        "artist": artist_name or "",
        "shot_id": "",
        "checks": {}
    }

    # Get shot ID
    try:
        td = doc.GetTakeData()
        if td:
            main_take = td.GetMainTake()
            if main_take:
                report["shot_id"] = main_take.GetName() or ""
    except Exception:
        pass

    # Populate checks
    for key, label, items in [
        ("lights", "Lights outside group", results.get("lights_bad", [])),
        ("visibility", "Visibility mismatches", results.get("vis_bad", [])),
        ("keyframes", "Multi-axis keyframes", results.get("keys_bad", [])),
        ("camera_shift", "Camera shift != 0", results.get("cam_bad", [])),
        ("unused_materials", "Unused materials", results.get("unused_mats_bad", [])),
        ("default_names", "Default/generic names", results.get("names_bad", [])),
    ]:
        obj_list = []
        for item in (items or []):
            try:
                obj_list.append(item.GetName() or "unnamed")
            except Exception:
                obj_list.append(str(item))
        report["checks"][key] = {
            "status": "PASS" if not obj_list else "FAIL",
            "count": len(obj_list),
            "label": label,
            "items": obj_list[:50],
        }

    # Unified textures check
    tex_bad = results.get("textures_bad", [])
    report["checks"]["textures"] = {
        "status": "PASS" if not tex_bad else "FAIL",
        "count": len(tex_bad),
        "label": "Texture issues (absolute paths + missing files)",
        "items": [f"[{t['issue'].upper()}] {t['source']}: {t['path']}" for t in tex_bad[:30]],
    }

    # Scene stats
    stats = results.get("scene_stats", {})
    if stats:
        report["scene_stats"] = stats

    # Info-only checks
    for key, label, count in [
        ("render_presets", "Non-standard presets", results.get("rdc_count", 0)),
        ("output_paths", "Output path issues", results.get("output_count", 0)),
        ("takes", "Take configuration issues", len(results.get("takes_bad", []))),
    ]:
        report["checks"][key] = {
            "status": "PASS" if count == 0 else "FAIL",
            "count": count,
            "label": label,
        }

    if results.get("output_bad"):
        report["checks"]["output_paths"]["items"] = [
            f"[{i['preset']}] {i['issue']}" for i in results["output_bad"][:10]
        ]
    if results.get("takes_bad"):
        report["checks"]["takes"]["items"] = [
            f"[{t['take']}] {t['issue']}" for t in results["takes_bad"][:20]
        ]

    # FPS / Frame Range check
    fps_bad = results.get("fps_range_bad", [])
    report["checks"]["fps_range"] = {
        "status": "PASS" if not fps_bad else "FAIL",
        "count": len(fps_bad),
        "label": "FPS & frame range validation",
        "items": [issue["issue"] for issue in fps_bad],
    }

    # Cross-Aspect Safe Area check
    cross_aspect_bad = results.get("cross_aspect_bad", [])
    report["checks"]["cross_aspect"] = {
        "status": "PASS" if not cross_aspect_bad else "FAIL",
        "count": len(cross_aspect_bad),
        "label": "Cross-aspect safe-area violations",
        "items": [
            f"{v.get('object_name', 'unnamed')} [{v.get('fmt_id', '?')}] "
            f"sides={','.join(sorted(v.get('sides', [])))} "
            f"frames={','.join(str(f) for f in v.get('frames', []))}"
            for v in cross_aspect_bad[:30]
        ],
    }

    report_key_by_id = _report_key_by_check_id()

    disabled_checks = []
    if isinstance(qc_summary, dict):
        disabled_checks = list(qc_summary.get("disabled", []) or [])
    for check_id in disabled_checks:
        report_key = report_key_by_id.get(check_id)
        if report_key and report_key in report["checks"]:
            report["checks"][report_key]["status"] = "DISABLED"
            report["checks"][report_key]["disabled"] = True
            report["checks"][report_key]["count"] = 0

    # Summary
    total = len(report["checks"])
    passed = sum(1 for c in report["checks"].values() if c["status"] == "PASS")
    report["summary"] = {
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "score": f"{passed}/{total}"
    }

    if disabled_checks:
        report["disabled_checks"] = disabled_checks

    baseline_details = build_baseline_artifact_details(qc_summary)
    if baseline_details:
        for check_id, details in baseline_details.items():
            if check_id in disabled_checks:
                continue
            report_key = report_key_by_id.get(check_id)
            if not report_key or report_key not in report["checks"]:
                continue
            check = report["checks"][report_key]
            check["status"] = "PASS" if details["new_count"] == 0 else "FAIL"
            check["new_count"] = details["new_count"]
            check["accepted_count"] = details["accepted_count"]
            check["stale_count"] = details["stale_count"]
            check["new"] = details["new"]
            check["accepted"] = details["accepted"]
            check["stale"] = details["stale"]
        report["baseline"] = {
            "path": qc_summary.get("baseline_path", ""),
            "checks": baseline_details,
        }

    if isinstance(qc_summary, dict):
        report["summary"] = {
            "total_checks": qc_summary.get("total", total),
            "passed": qc_summary.get("passed", passed),
            "failed": qc_summary.get("total", total) - qc_summary.get("passed", passed),
            "score": qc_summary.get("score", f"{passed}/{total}"),
            "new": qc_summary.get("new", 0),
            "accepted": qc_summary.get("accepted", 0),
            "stale": qc_summary.get("stale", 0),
            "schema": qc_summary.get("schema", 1),
            "disabled_count": qc_summary.get("disabled_count", len(disabled_checks)),
        }

    # Always include scene notes section in the report (empty defaults if no
    # sidecar exists yet — keeps the JSON shape consistent for tooling)
    notes_path = get_notes_path(doc)
    notes_section = {
        "summary": "Notes: empty",
        "text": "",
        "todos": [],
        "pending_count": 0,
        "updated": "",
    }
    if notes_path and os.path.exists(notes_path):
        try:
            notes_data = load_notes(notes_path)
            notes_section = {
                "summary": summarize_notes(notes_data),
                "text": notes_data.get("notes", "") or "",
                "todos": notes_data.get("todos", []) or [],
                "pending_count": sum(1 for t in (notes_data.get("todos") or []) if not t.get("done")),
                "updated": notes_data.get("updated", ""),
            }
        except Exception as e:
            safe_print(f"Could not include notes in QC report: {e}")
    report["notes"] = notes_section
    return report
