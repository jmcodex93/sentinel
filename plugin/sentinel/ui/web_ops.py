# -*- coding: utf-8 -*-
"""C4D adapter for the Sentinel form pages + command palette (Phase 4 Task 2
of the UI redesign — see docs/superpowers/plans/2026-07-19-ui-phase4-forms.md).

Sibling of ``ui/reports_dialog.py`` (split out once that file's op count
grew past ~600 lines, per the plan's own instruction). Same contract:
every handler here is a ``MainThreadQueue`` dispatch target — see
``webbridge.MainThreadQueue.drain`` for the invariant every handler must
honor (mutations are safe post-commit 69d7a7a, but a handler must still
tolerate the client retrying the same mutation after its own timeout).

Every op below is grounded in — and calls straight through to — the exact
engine/dialog helpers the native GeDialogs already use, per the Phase 4
mandate: "los motores (versioning, notes, gate, settings) NO se duplican".
Pure request/response shaping and validation live in ``sentinel.webbridge``
(no c4d there); this module is only the seam that touches ``c4d`` to read
the active document and call those pure functions + the native engines.

Op inventory added here: ``form/save_version/state|submit``,
``form/notes/state|submit``, ``form/settings/state|submit``,
``form/gate/state|submit``, ``palette/actions``, ``palette/run``. Merged
into ``ui/reports_dialog.py``'s ``_OPS`` dict (see ``FORM_OPS`` below) —
this module deliberately does NOT import ``reports_dialog`` at module
scope (it would be circular, since ``reports_dialog`` imports
``FORM_OPS`` from here); any need to reach back into it (``open_reports``)
is a local import inside the function that needs it.
"""
import os

import c4d
from c4d import documents

from sentinel import baseline as baseline_engine
from sentinel import webbridge
from sentinel.common.cache import check_cache
from sentinel.common.settings import GlobalSettings
from sentinel.fixes import (
    apply_fixes,
    fix_camera_shift,
    fix_fps_range,
    fix_lights,
    fix_unused_materials,
)
from sentinel.notes import get_notes_path, load_notes, save_notes
from sentinel.qc.score import count_violations, run_all_checks
from sentinel.rules_context import active_rules_for_doc
from sentinel.versioning import (
    format_version_row,
    get_latest_version_info,
    parse_version_filename,
    preview_next_filename,
)


def _notes_scene_base(doc):
    """Fallback scene-base name for a notes sidecar with no ``scene`` field
    yet — mirrors ``ui/panel.py`` ``_handle_edit_notes``'s stamping logic
    exactly (strip ``_v###[_status]``, fall back to the raw basename, then
    to ``"scene"``)."""
    doc_name = doc.GetDocumentName() or ""
    name_no_ext = os.path.splitext(doc_name)[0]
    base, _ver, _status = parse_version_filename(name_no_ext)
    return base or name_no_ext or "scene"


# ---------------------------------------------------------------------------
# Save Version — mirrors ui/dialogs.py SaveVersionDialog + ui/panel.py
# _handle_save_version + ui/flows.py smart_save_version
# ---------------------------------------------------------------------------

def _op_form_save_version_state(payload):
    """``form/save_version/state`` — everything ``SaveVersionDialog``
    shows on open, computed fresh (no caching): the current QC score
    preview, the last saved version (for the "Last version" pillbox this
    form replaces), and the per-status filename preview
    (``preview_next_filename``) for every entry in ``STATUS_OPTIONS`` so
    the SPA never needs a round trip just to update the "Will save as: ..."
    label when the user changes the status dropdown.

    Read-only: never mutates, never opens a dialog.
    """
    from sentinel.ui.flows import _build_qc_summary

    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    qc_summary = _build_qc_summary(doc)
    last_version = format_version_row(get_latest_version_info(doc))

    status_options = [
        dict(option, preview_filename=preview_next_filename(doc, status=option["suffix"]))
        for option in webbridge.save_version_status_options()
    ]

    return {
        "scene": doc.GetDocumentName() or "Untitled",
        "last_version": last_version,
        "qc": {"score": qc_summary.get("score", ""), "pass": bool(qc_summary.get("pass"))},
        "status_options": status_options,
    }


def _op_form_save_version_submit(payload):
    """``form/save_version/submit`` — validate (``webbridge.
    validate_save_version_submit``, the exact rules ``SaveVersionDialog.
    Command``'s ``BTN_SAVE`` branch enforces) then call ``ui/flows.py``
    ``smart_save_version`` — the SAME function the native panel button
    calls, so gates/history/QC-capture behavior is identical.

    Note: for a never-saved document, ``smart_save_version`` opens a
    native ``c4d.storage.SaveDialog`` file picker — a blocking native OS
    dialog, not one of the "12 popups" the Phase 4 redesign retires (those
    are informational/confirmation MessageDialogs; a file picker for a
    brand-new file has no SPA equivalent and is left exactly as-is).

    A validation failure or a save failure both return
    ``{"ok": False, "error": str}`` — never raises.
    """
    from sentinel.ui.flows import smart_save_version

    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    validated = webbridge.validate_save_version_submit(payload)
    if not validated.get("ok"):
        return {"ok": False, "error": validated.get("error")}

    result = smart_save_version(
        doc,
        comment=validated["comment"],
        run_qc=validated["run_qc"],
        artist_name=GlobalSettings.load_artist_name(),
        status=validated["status"],
    )

    if not result.get("success"):
        return {"ok": False, "error": result.get("message") or "Save failed"}

    response = {
        "ok": True,
        "message": result.get("message", ""),
        "version": result.get("version"),
        "status": result.get("status", ""),
        "path": result.get("path"),
    }
    if validated.get("warning"):
        response["warning"] = validated["warning"]
    return response


# ---------------------------------------------------------------------------
# Notes — mirrors ui/dialogs.py NotesDialog + ui/panel.py _handle_edit_notes
# ---------------------------------------------------------------------------

def _op_form_notes_state(payload):
    """``form/notes/state`` — load the sidecar (or the empty default) and
    stamp ``scene`` the same way ``_handle_edit_notes`` does when it is
    still blank. ``{"error": "no_scene_path"}`` when the document has never
    been saved to a folder — same gate ``_handle_edit_notes`` enforces via
    its "Save the scene first" MessageDialog, here surfaced for the SPA to
    render inline instead.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    notes_path = get_notes_path(doc)
    if not notes_path:
        return {"error": "no_scene_path"}

    notes = load_notes(notes_path)
    scene_base = notes.get("scene") or _notes_scene_base(doc)

    todos = [
        {"id": t.get("id"), "text": t.get("text", ""), "done": bool(t.get("done"))}
        for t in notes.get("todos") or []
    ]
    return {
        "notes_text": notes.get("notes", ""),
        "todos": todos,
        "scene_base": scene_base,
    }


def _op_form_notes_submit(payload):
    """``form/notes/submit`` — reconcile against a FRESHLY loaded sidecar
    (``webbridge.merge_notes_submission``, never trusting the client's
    copy as the source of truth for existing todos) and persist via
    ``notes.save_notes`` — the exact same writer ``_handle_edit_notes``
    uses on ``NotesDialog`` confirm.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    notes_path = get_notes_path(doc)
    if not notes_path:
        return {"error": "no_scene_path"}

    original = load_notes(notes_path)
    merged = webbridge.merge_notes_submission(
        original, payload.get("notes_text"), payload.get("todos"))
    if not merged.get("scene"):
        merged["scene"] = _notes_scene_base(doc)

    if not save_notes(notes_path, merged):
        return {"ok": False, "error": "Failed to save notes file."}
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings — mirrors ui/dialogs.py SentinelSettingsDialog
# ---------------------------------------------------------------------------

def _settings_locks(doc):
    """Compute the same two machine-controlled locks
    ``SentinelSettingsDialog.InitValues`` computes (Standard FPS overridden
    by project rules; RS snapshot dir auto-detected from RenderView) —
    returns ``(fps_locked, fps_value, snapshot_dir_locked, snapshot_dir_value)``.
    """
    from sentinel.ui.flows import detect_rv_snapshot_dir

    rules_context = active_rules_for_doc(doc)
    fps_locked = bool(
        rules_context and rules_context.field_sources.get("standard_fps") == "project")
    if fps_locked:
        fps_value = int(rules_context.params.get("standard_fps", GlobalSettings.get_standard_fps()))
    else:
        fps_value = GlobalSettings.get_standard_fps()

    detected_snap_dir = detect_rv_snapshot_dir()
    snap_dir_locked = bool(detected_snap_dir)
    snap_dir_value = detected_snap_dir if snap_dir_locked else GlobalSettings.get_snapshot_dir()

    return fps_locked, fps_value, snap_dir_locked, snap_dir_value


def _op_form_settings_state(payload):
    """``form/settings/state`` — every field
    ``SentinelSettingsDialog.InitValues`` populates, plus the option lists
    (``webbridge.SETTINGS_*_OPTIONS``) so the SPA can render the same
    selects without hardcoding them separately.

    Deviation from the plan sketch's ``slate(+locked)``: the native dialog
    never actually disables the slate checkbox (only FPS/snapshot dir are
    ``Enable(..., False)``'d) — see ``webbridge.validate_settings_submit``'s
    docstring for the same grounding note. ``slate`` here is a plain bool,
    no lock.
    """
    doc = documents.GetActiveDocument()
    fps_locked, fps_value, snap_dir_locked, snap_dir_value = _settings_locks(doc)

    try:
        mv_max = int(GlobalSettings.get('mv_max_motion', 0))
    except (TypeError, ValueError):
        mv_max = 0

    try:
        history_max = int(GlobalSettings.get('history_max_rows', 5))
    except (TypeError, ValueError):
        history_max = 5
    if history_max not in webbridge.SETTINGS_HISTORY_OPTIONS:
        history_max = 5

    try:
        compositor = int(GlobalSettings.get('comp_target', 0))
    except (TypeError, ValueError):
        compositor = 0

    return {
        "fps": {
            "value": int(fps_value),
            "options": list(webbridge.SETTINGS_FPS_OPTIONS),
            "locked": fps_locked,
            "locked_reason": "defined by project ruleset" if fps_locked else None,
        },
        "compositor": {
            "value": compositor,
            "options": list(webbridge.SETTINGS_COMPOSITOR_OPTIONS),
        },
        "multipart_default": bool(int(GlobalSettings.get('aov_multipart', 1))),
        "slate": {"value": GlobalSettings.get_snapshot_slate()},
        "mv_max_motion": max(mv_max, 0),
        "snapshot_dir": {
            "value": snap_dir_value,
            "detected": snap_dir_locked,
            "locked": snap_dir_locked,
        },
        "history_max": {
            "value": history_max,
            "options": list(webbridge.SETTINGS_HISTORY_OPTIONS),
        },
    }


def _op_form_settings_submit(payload):
    """``form/settings/submit`` — validate (honoring the same live locks
    ``form/settings/state`` reports) then persist via the exact
    ``GlobalSettings`` setters ``SentinelSettingsDialog.Command``'s
    ``BTN_SAVE`` branch uses.
    """
    doc = documents.GetActiveDocument()
    fps_locked, _fps_value, snap_dir_locked, _snap_dir_value = _settings_locks(doc)

    try:
        updates = webbridge.validate_settings_submit(
            payload, fps_locked=fps_locked, snapshot_dir_locked=snap_dir_locked)

        if "standard_fps" in updates:
            GlobalSettings.set_standard_fps(updates["standard_fps"])
        if "comp_target" in updates:
            GlobalSettings.set('comp_target', updates["comp_target"])
        if "aov_multipart" in updates:
            GlobalSettings.set('aov_multipart', updates["aov_multipart"])
        if "snapshot_slate" in updates:
            GlobalSettings.set_snapshot_slate(updates["snapshot_slate"])
        if "mv_max_motion" in updates:
            GlobalSettings.set('mv_max_motion', updates["mv_max_motion"])
        if "snapshot_dir" in updates:
            GlobalSettings.set_snapshot_dir(updates["snapshot_dir"])
        if "history_max_rows" in updates:
            GlobalSettings.set('history_max_rows', updates["history_max_rows"])
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True}


# ---------------------------------------------------------------------------
# Quality Gate — mirrors gate.py + ui/dialogs.py GateTriageDialog +
# ui/flows.py _run_quality_gate / _compute_gate_snapshot
# ---------------------------------------------------------------------------

def _gate_snapshot_for_doc(doc):
    from sentinel.ui.flows import _compute_gate_snapshot, _doc_full_path

    rules_context = active_rules_for_doc(doc)
    doc_full_path = _doc_full_path(doc)
    return rules_context, doc_full_path, _compute_gate_snapshot(doc, rules_context, doc_full_path)


def _gate_state_from_snapshot(snapshot):
    return webbridge.gate_state_payload(
        snapshot["gate_result"],
        sidecar_invalid=(snapshot["baseline_status"] == baseline_engine.STATUS_INVALID),
    )


def _op_form_gate_state(payload):
    """``form/gate/state`` — evaluate the quality gate for the active
    document exactly the way ``ui/flows.py`` ``_run_quality_gate`` does on
    open (``_compute_gate_snapshot``: baseline-aware ``compute_score`` ->
    ``gate.evaluate_gate``), reshaped via ``webbridge.gate_state_payload``.
    Read-only.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    _rules_context, _doc_full_path, snapshot = _gate_snapshot_for_doc(doc)
    return _gate_state_from_snapshot(snapshot)


def _op_form_gate_submit(payload):
    """``form/gate/submit`` — the v1 SPA gate page only offers Fix /
    Accept / Proceed / Cancel (no per-row Override — see the Task 3 plan
    sketch, which lists exactly those three mutating actions). Each
    action is a discrete, independently-dispatched request rather than one
    long-lived modal session like ``GateTriageDialog``; ``fix_all`` and
    ``accept`` recompute a fresh gate snapshot afterward and echo it back
    as ``state`` so the SPA never needs a second round trip.

    - ``fix_all``: batch-fixes every currently fixable check_id via
      ``fixes.apply_fixes`` (single undo step) — same payload shape
      ``_run_quality_gate`` builds via ``_gate_fix_payload``.
    - ``accept``: ``{"ids": [check_id, ...], "author": str, "reason": str}``
      — both author and reason are mandatory here (the SPA gate page's own
      requirement; the native ``BaselineActionDialog`` only requires
      reason and falls back to the OS user for a blank author via
      ``baseline.resolve_author`` — this form is stricter for
      traceability). Adds one baseline acceptance per new violation of
      each requested check_id, same as ``_run_quality_gate``'s
      ``dlg.baseline_accepts`` loop.
    - ``proceed``: recomputes fresh and reports whether every FAIL-severity
      blocking violation is resolved (``webbridge.gate_can_proceed`` — the
      value it returns is what the caller's Task 4 wiring uses to decide
      whether to actually run the save/collect this gate was guarding).
    - ``cancel``: no mutation, just echoes the current state.

    Unlike ``_run_quality_gate``'s return contract, this does not
    accumulate ``overrides``/``baseline_changed`` across a session — there
    is no override action in v1, and each mutating action already
    invalidates the QC cache itself, so there is nothing for ``proceed``
    to accumulate. Out of scope for v1, not a gap: Task 4 decides what
    (if anything) needs that bookkeeping when it wires the actual
    save/collect trigger behind this gate.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    action = payload.get("action")
    rules_context, doc_full_path, snapshot = _gate_snapshot_for_doc(doc)
    gate_result = snapshot["gate_result"]

    if action == "cancel":
        return {"ok": True, "proceed": False, "state": _gate_state_from_snapshot(snapshot)}

    if action == "proceed":
        return {
            "ok": True,
            "proceed": webbridge.gate_can_proceed(gate_result),
            "state": _gate_state_from_snapshot(snapshot),
        }

    if action == "fix_all":
        from sentinel.ui.flows import _gate_fix_payload

        fixable_ids = [item.get("check_id") for item in gate_result.get("fixable") or []]
        if fixable_ids:
            fixes = [
                _gate_fix_payload(check_id, snapshot["registry_results"], gate_result)
                for check_id in fixable_ids
            ]
            apply_fixes(doc, fixes)
            check_cache.clear()
            c4d.EventAdd()
            _rules_context, _doc_full_path, snapshot = _gate_snapshot_for_doc(doc)

        return {
            "ok": True,
            "fixed": fixable_ids,
            "state": _gate_state_from_snapshot(snapshot),
        }

    if action == "accept":
        from sentinel.ui.flows import _gate_new_violations

        ids = [cid for cid in (payload.get("ids") or []) if cid]
        author = (payload.get("author") or "").strip()
        reason = (payload.get("reason") or "").strip()
        if not author or not reason:
            return {"ok": False, "error":
                     "Author and reason are required to accept violations."}
        if not ids:
            return {"ok": False, "error": "Select at least one check to accept."}

        path = snapshot["baseline_path"]
        accepted_any = False
        for check_id in ids:
            for violation in _gate_new_violations(gate_result, check_id):
                acceptance = baseline_engine.entry_from_violation(
                    violation, author, reason,
                    current_params=getattr(rules_context, "params", {}))
                if acceptance and baseline_engine.add_acceptance(path, acceptance):
                    accepted_any = True

        if accepted_any:
            check_cache.clear()
            c4d.EventAdd()
            _rules_context, _doc_full_path, snapshot = _gate_snapshot_for_doc(doc)

        return {
            "ok": True,
            "accepted": accepted_any,
            "state": _gate_state_from_snapshot(snapshot),
        }

    return {"ok": False, "error": f"unknown gate action: {action!r}"}


# ---------------------------------------------------------------------------
# Command palette — ids/functions grounded in ui/panel.py Command handlers
# ---------------------------------------------------------------------------

_PALETTE_FIX_CHECK_ID = {
    "fix_lights": "lights",
    "fix_cameras": "cam",
    "fix_materials": "unused_mats",
}

_PALETTE_REPORT_PAGES = {
    "open_reports_qc": "qc",
    "open_reports_doctor": "doctor",
    "open_reports_supervisor": "supervisor",
    "open_reports_render_validation": "render",
    "open_reports_delivery": None,
}


def _op_palette_actions(payload):
    """``palette/actions`` — the full v1 registry (``webbridge.
    PALETTE_ACTIONS``) plus live ``enabled``/``reason`` gating: whether a
    document is open/saved, and the current violation count for each
    Quick Fix action's check_id (a single ``run_all_checks`` pass reused
    across all four — cheaper than four separate QC runs). Read-only.
    """
    from sentinel.ui.flows import _current_module

    doc = documents.GetActiveDocument()
    doc_saved = bool(doc and doc.GetDocumentPath())
    qc_counts = {}
    if doc:
        rules_context = active_rules_for_doc(doc)
        registry_results = run_all_checks(doc, _current_module(), rules_context)
        for check_id in _PALETTE_FIX_CHECK_ID.values():
            pair = registry_results.get(check_id) or {}
            qc_counts[check_id] = count_violations(check_id, pair.get("legacy_result"))
        fps_pair = registry_results.get("fps_range") or {}
        qc_counts["fps_range"] = count_violations("fps_range", fps_pair.get("legacy_result"))

    return {"actions": webbridge.palette_actions_payload(doc is not None, doc_saved, qc_counts)}


def _palette_open_hub(doc):
    if not doc:
        return {"ok": False, "error": "No active document"}
    from sentinel.ui.dialogs import AssetHubDialog

    try:
        dlg = AssetHubDialog(doc, focus="assets")
        dlg._artist_name = GlobalSettings.load_artist_name()
        dlg.Open(c4d.DLG_TYPE_ASYNC, defaultw=980, defaulth=560)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": "Asset Hub opened"}


def _palette_open_reports(doc, action_id):
    from sentinel.ui.reports_dialog import open_reports

    page = _PALETTE_REPORT_PAGES.get(action_id)
    try:
        open_reports(doc, page=page)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": "Reports opened"}


def _palette_fix(doc, action_id):
    """Runs the exact same fix_* engine call the panel's own
    ``_qc_fix_lights``/``_qc_fix_cam``/``_qc_fix_unused_mats`` handlers make
    — minus their confirmation ``QuestionDialog``/preview popups, per the
    Phase 4 popup-triage direction those handlers themselves already
    follow for lights/camera/FPS (only the unused-materials delete still
    confirms today; it is undo-safe via a single ``StartUndo``/``EndUndo``
    step exactly like the others, so the palette forgoes that popup too).
    """
    from sentinel.ui.flows import _current_module

    if action_id == "fix_fps":
        fixes = fix_fps_range(doc)
        if not fixes:
            return {"ok": True, "message": "No FPS/range issues to fix"}
        return {"ok": True, "message": f"Applied {len(fixes)} FPS/range fix(es)"}

    check_id = _PALETTE_FIX_CHECK_ID[action_id]
    rules_context = active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    objs = (registry_results.get(check_id) or {}).get("legacy_result") or []
    if not objs:
        return {"ok": True, "message": "Nothing to fix"}

    if action_id == "fix_lights":
        count = fix_lights(doc, objs)
        message = f"Moved {count} light(s) into 'lights' group"
    elif action_id == "fix_cameras":
        count = fix_camera_shift(doc, objs)
        message = f"Reset shift to 0 on {count} camera(s)"
    else:  # fix_materials
        count = fix_unused_materials(doc, objs)
        message = f"Deleted {count} unused material(s)"

    return {"ok": True, "message": message}


def _palette_rescan_qc(doc):
    check_cache.clear()
    c4d.EventAdd()
    return {"ok": True, "message": "QC cache cleared"}


def _op_palette_run(payload):
    """``palette/run`` — ``{"id": <action id>}``, no other params (the
    registry fully resolves each action's behavior by id alone). A
    ``kind: "navigate"`` action does no server work beyond an
    enabled-doc re-check — it is pure SPA client-side routing to a
    ``page`` (the FormDialog host that actually opens it is Phase 4
    Task 4). A ``kind: "run"`` action executes real work on the C4D main
    thread and returns a toast-able ``message``.
    """
    action_id = payload.get("id")
    entry = webbridge.PALETTE_ACTION_BY_ID.get(action_id)
    if entry is None:
        return {"ok": False, "error": f"unknown palette action: {action_id!r}"}

    doc = documents.GetActiveDocument()

    if entry["kind"] == "navigate":
        if entry.get("requires_doc") and not doc:
            return {"ok": False, "error": "No active document"}
        return {"ok": True, "navigate": entry["page"]}

    if action_id == "open_hub":
        return _palette_open_hub(doc)
    if action_id in _PALETTE_REPORT_PAGES:
        return _palette_open_reports(doc, action_id)
    if action_id in _PALETTE_FIX_CHECK_ID or action_id == "fix_fps":
        if not doc:
            return {"ok": False, "error": "No active document"}
        return _palette_fix(doc, action_id)
    if action_id == "rescan_qc":
        if not doc:
            return {"ok": False, "error": "No active document"}
        return _palette_rescan_qc(doc)

    return {"ok": False, "error": f"unhandled palette action: {action_id!r}"}


# op name -> handler(payload), merged into ui/reports_dialog.py's own _OPS.
FORM_OPS = {
    "form/save_version/state": _op_form_save_version_state,
    "form/save_version/submit": _op_form_save_version_submit,
    "form/notes/state": _op_form_notes_state,
    "form/notes/submit": _op_form_notes_submit,
    "form/settings/state": _op_form_settings_state,
    "form/settings/submit": _op_form_settings_submit,
    "form/gate/state": _op_form_gate_state,
    "form/gate/submit": _op_form_gate_submit,
    "palette/actions": _op_palette_actions,
    "palette/run": _op_palette_run,
}
