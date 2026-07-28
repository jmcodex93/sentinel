# -*- coding: utf-8 -*-
"""panel/frame op (Fase 6.6) — Frame sub-view read model (multi-format).

Consolidates the three formerly-scattered cross-aspect touchpoints —
Sentinel Frame presence (Render), marked subjects (was Tools), and QC #12
(QC) — into ONE read for the in-panel Frame sub-view. Read-only, isolated
blocks (a failing block never blanks the others). Every ACTION the sub-view
performs reuses an existing op — this module adds no action ops.

Payload shape::

    { "frame": {"has_tag": bool, "camera_name": str|None,
                "format_count": int|None, "stale": bool} | None,
      "subjects": {"marked_count": int} | None,
      "qc12": {"pass": bool, "violations": int} | None }
"""
import c4d

from sentinel.ui.panel_ops import _guarded_block, _run_qc_scoring
from sentinel.ui import panel_render_ops
from sentinel import safe_areas


def _frame_block(doc):
    """Sentinel Frame presence + host camera + enabled-format count +
    current Viewing state. Reuses ``panel_render_ops._panel_frame_block``
    for the first three (zero duplication).

    Frame v2: ``stale`` is kept as a constant ``False`` for one release (the
    auto-sync engine makes staleness a sub-second transient, and an older SPA
    bundle may still read the key) — it is no longer an actionable signal.
    ``viewing`` mirrors the tag's Viewing cycle: "master", a format id, or a
    slice id ("fmt:sNN") when a slice take is active (v1.29)."""
    base = panel_render_ops._panel_frame_block(doc)
    base["stale"] = False
    base["viewing"] = "master"
    base["viewing_options"] = ["master"]
    if base.get("has_tag"):
        found = panel_render_ops._find_sentinel_frame_tag(doc)
        if found:
            try:
                from sentinel.ui.frame_tag import (
                    _current_own_take_info,
                    viewing_targets,
                )
                info = _current_own_take_info(found[0], doc)
                if info:
                    fmt, sfx = info
                    base["viewing"] = f"{fmt}:{sfx}" if sfx else fmt
                base["viewing_options"] = viewing_targets(found[0])
            except Exception:
                pass
    return base


def _subjects_block(doc):
    """Count of objects marked as Safe Area Subjects (the QC #12 opt-in)."""
    return {"marked_count": len(safe_areas.find_marked_safe_area_objects(doc) or [])}


def _qc12_from_report(qc_report):
    """Pure: extract the cross_aspect (QC #12) row from a qc_report and
    reduce it to ``{pass, violations}``. A missing or disabled row is a
    trivial pass (QC #12 is not applicable). Baseline-aware: prefer ``new``
    (unaccepted subset) over the raw ``count`` — same preference the score
    itself uses."""
    row = next((c for c in (qc_report.get("checks") or []) if c.get("id") == "cross_aspect"), None)
    if row is None or row.get("status") == "disabled":
        return {"pass": True, "violations": 0}
    violations = row.get("new")
    if violations is None:
        violations = row.get("count") or 0
    return {"pass": violations == 0, "violations": violations}


def _qc12_block(doc):
    """QC #12 status via the SHARED scoring pass (never re-derived), plus
    ``has_takes``: whether any multi-format delivery Takes exist. QC #12
    only evaluates when they do (the check early-returns a trivial pass
    otherwise) — so ``has_takes=False`` lets the SPA distinguish "not
    evaluated (no Takes yet)" from a real pass, instead of showing a
    misleading all-clear for subjects that were never checked."""
    has_takes = bool(safe_areas.find_active_multiformat_takes(doc))
    _rules, _results, qc_report = _run_qc_scoring(doc)
    result = _qc12_from_report(qc_report)
    result["has_takes"] = has_takes
    return result


def build_panel_frame(doc):
    return {
        "frame": _guarded_block("frame", _frame_block, doc),
        "subjects": _guarded_block("subjects", _subjects_block, doc),
        "qc12": _guarded_block("qc12", _qc12_block, doc),
    }


def _op_panel_frame(payload):
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"frame": None, "subjects": None, "qc12": None}
    return build_panel_frame(doc)


def _op_panel_frame_set_viewing(payload):
    """Mutation: activate the take behind a Viewing selection ("master" or a
    format id). Thin adapter over the tag's dialog-free ``set_viewing`` core
    — the same routine the AM cycle uses (two-way by construction)."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "viewing": None, "error": "no_document"}
    found = panel_render_ops._find_sentinel_frame_tag(doc)
    if not found:
        return {"ok": False, "viewing": None, "error": "no_tag"}
    from sentinel.ui.frame_tag import set_viewing
    target = (payload or {}).get("target") or "master"
    return set_viewing(doc, found[0], target)


PANEL_FRAME_OPS = {
    "panel/frame": _op_panel_frame,
    "panel/frame/set_viewing": _op_panel_frame_set_viewing,
}
