"""Pure form, gate, and command-palette transformations."""

from sentinel.notes import add_todo, toggle_todo
from sentinel.qc.registry import CHECK_REGISTRY
from sentinel.versioning import STATUS_OPTIONS, _sanitize_status
from sentinel.bridge.reports import _qc_violation_detail

SAVE_VERSION_FINAL_HINT = (
    "Tip: instead of writing 'final' in the comment, use the 'Final Delivery' "
    "status tag — it bakes the marker into the filename (e.g. scene_v007_FINAL.c4d) "
    "and the history log."
)


def resolve_save_version_status(status, custom_status):
    """Pure port of ``SaveVersionDialog._current_status``: a non-empty
    custom status always wins over the combo selection, sanitized the same
    way (``versioning._sanitize_status`` — strip non-alphanumerics,
    uppercase). Returns ``""`` (WIP) if both are empty."""
    custom = (custom_status or "").strip()
    if custom:
        return _sanitize_status(custom)
    return _sanitize_status(status or "")


def validate_save_version_submit(payload):
    """Pure validation for ``POST /api/form/save_version/submit``, mirroring
    ``ui/dialogs.py`` ``SaveVersionDialog.Command``'s ``BTN_SAVE`` branch:

    - an empty (or whitespace-only) comment is rejected — the native dialog
      shows a blocking ``MessageDialog``; here it is
      ``{"ok": False, "error": str}`` for the SPA to render inline (no
      popup, per the Phase 4 popup-triage direction).
    - "final" anywhere in the comment (case-insensitive) is a *non-blocking*
      soft warning — the native dialog still lets the save proceed after
      showing it; here it rides along on a successful response as
      ``warning`` for the caller to toast, never gating the save.
    - ``status``/``custom_status`` resolve via ``resolve_save_version_status``.

    Returns ``{"ok": True, "comment", "status", "run_qc", "warning"}`` or
    ``{"ok": False, "error": str}``. Never raises.
    """
    comment = (payload.get("comment") or "").strip()
    if not comment:
        return {
            "ok": False,
            "error": "Please enter a comment describing this version.",
        }

    status = resolve_save_version_status(
        payload.get("status"), payload.get("custom_status"))
    warning = SAVE_VERSION_FINAL_HINT if "final" in comment.lower() else None

    return {
        "ok": True,
        "comment": comment,
        "status": status,
        "run_qc": bool(payload.get("run_qc", True)),
        "warning": warning,
    }


def save_version_status_options():
    """The ``status_options`` list for ``form/save_version/state`` —
    ``versioning.STATUS_OPTIONS`` reshaped to ``{"label", "suffix"}`` dicts
    (the SPA contract; the per-status filename preview is attached by the
    caller, which alone can call ``preview_next_filename`` — it needs the
    live document)."""
    return [{"label": label, "suffix": suffix} for label, suffix in STATUS_OPTIONS]


# ---------------------------------------------------------------------------
# Notes form — mirrors ui/dialogs.py NotesDialog + notes.py primitives
# ---------------------------------------------------------------------------

def merge_notes_submission(original_notes, notes_text, submitted_todos):
    """Pure reconciliation for ``POST /api/form/notes/submit``.

    ``original_notes`` must be freshly loaded from disk by the caller (never
    trust a client-supplied full copy as the source of truth — a concurrent
    external edit would otherwise be silently clobbered wholesale). Drives
    the exact same primitives ``NotesDialog``'s ``TodoArea`` callbacks use
    (``notes.add_todo`` / ``notes.toggle_todo`` — see ``ui/dialogs.py``
    ``NotesDialog._on_toggle_todo``/``_on_delete_todo``) so timestamp
    bookkeeping (``added``/``completed``) stays correct instead of being
    reinvented here.

    ``submitted_todos`` is the SPA's desired end-state todo list:
    ``[{"id": int|None, "text": str, "done": bool}, ...]``. The native
    dialog never supported editing an existing TODO's text (only
    add/toggle/delete via the ``TodoArea`` click targets), so this mirrors
    that scope exactly: an existing id's text is left untouched, only its
    done state may flip via ``toggle_todo``. A new item (no id, or an id
    that no longer matches an existing TODO) is created via ``add_todo``,
    then toggled on immediately if submitted with ``done: true``. Any
    existing id NOT present in ``submitted_todos`` is dropped — deletion is
    implicit (the whole list is a replace), not a separate ``delete_todo``
    call, since the final list is built from scratch as ``ordered``.

    Returns a deep-copied notes dict ready for ``notes.save_notes`` — never
    mutates ``original_notes``. Never raises on malformed items (a
    non-dict entry, or one with an empty/whitespace-only text, is skipped).
    """
    import copy

    working = copy.deepcopy(original_notes) if original_notes else {
        "scene": "", "updated": "", "notes": "", "todos": []}
    working.setdefault("todos", [])
    working["notes"] = (notes_text or "").strip()

    def _norm_id(raw):
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    existing_by_id = {_norm_id(t.get("id")): t for t in working["todos"]}

    ordered = []
    for item in submitted_todos or []:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        done = bool(item.get("done"))
        todo = existing_by_id.get(_norm_id(item.get("id")))

        if todo is not None:
            if bool(todo.get("done")) != done:
                toggle_todo(working, todo.get("id"))
            ordered.append(todo)
        else:
            add_todo(working, text)
            new_todo = working["todos"][-1]
            if done:
                toggle_todo(working, new_todo.get("id"))
            ordered.append(new_todo)

    working["todos"] = ordered
    return working


# ---------------------------------------------------------------------------
# Settings form — mirrors ui/dialogs.py SentinelSettingsDialog exactly
# ---------------------------------------------------------------------------

SETTINGS_FPS_OPTIONS = (24, 25, 30, 60)
SETTINGS_COMPOSITOR_OPTIONS = ("Nuke", "After Effects")
SETTINGS_HISTORY_OPTIONS = (5, 10, 20)


def validate_settings_submit(payload, fps_locked=False, snapshot_dir_locked=False):
    """Pure mapper: raw form payload -> the exact fields
    ``SentinelSettingsDialog``'s ``BTN_SAVE`` branch would persist to
    ``GlobalSettings`` (see ``ui/dialogs.py`` ``SentinelSettingsDialog.Command``).

    Honors the same two machine-controlled locks the native dialog disables
    via ``Enable(..., False)``: Standard FPS overridden by project rules
    (``fps_locked``) and the RS snapshot dir auto-detected from RenderView's
    config (``snapshot_dir_locked``) — a locked field is never written here
    even if the payload includes one, exactly like the native dialog's
    ``if not self._standard_fps_overridden: ...`` / ``if not
    self._snap_dir_overridden: ...`` guards.

    Note: unlike FPS/snapshot dir, the native dialog's "Review slate
    burn-in" checkbox is NEVER disabled even though a project ruleset can
    also override it at usage time (``CHK_SLATE`` has no
    ``_slate_overridden`` guard in ``InitValues``/``Command`` — only a
    always-shown static hint line). So ``slate`` here has no lock parameter;
    grounded in the native dialog's actual behavior, not the plan sketch's
    ``slate(+locked)`` shorthand.

    A malformed/out-of-range value is silently skipped (field omitted from
    the returned dict, left unchanged) — mirrors the native dialog's own
    robustness guards (``if 0 <= idx < len(...)``), which never surface an
    error dialog for a bad combo index either. Never raises.

    Returns a dict of only the ``GlobalSettings`` keys to write, e.g.
    ``{"standard_fps": 25, "comp_target": 0, "aov_multipart": 1,
    "snapshot_slate": True, "mv_max_motion": 0, "snapshot_dir": "...",
    "history_max_rows": 10}`` — any subset, never all keys are guaranteed
    present.
    """
    updates = {}

    if not fps_locked:
        fps = _coerce_int(payload.get("fps"))
        if fps in SETTINGS_FPS_OPTIONS:
            updates["standard_fps"] = fps

    compositor = _coerce_int(payload.get("compositor"))
    if compositor in (0, 1):
        updates["comp_target"] = compositor

    if "multipart_default" in payload:
        updates["aov_multipart"] = 1 if payload.get("multipart_default") else 0

    if "slate" in payload:
        updates["snapshot_slate"] = bool(payload.get("slate"))

    # Strict bool only (the SPA sends JSON true/false) — a malformed value
    # (string/number/None) is omitted, never coerced truthy and never raises.
    if "render_notify" in payload and isinstance(payload.get("render_notify"), bool):
        updates["render_notify"] = 1 if payload.get("render_notify") else 0

    mv_max = _coerce_int(payload.get("mv_max_motion"))
    if mv_max is not None:
        updates["mv_max_motion"] = max(mv_max, 0)

    if not snapshot_dir_locked:
        snap_dir = (payload.get("snapshot_dir") or "").strip()
        if snap_dir:
            updates["snapshot_dir"] = snap_dir

    history_max = _coerce_int(payload.get("history_max"))
    if history_max in SETTINGS_HISTORY_OPTIONS:
        updates["history_max_rows"] = history_max

    return updates


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gate form — mirrors gate.py evaluate_gate() + ui/dialogs.py GateTriageDialog
# ---------------------------------------------------------------------------

_CHECK_ENTRY_BY_ID = {entry.check_id: entry for entry in CHECK_REGISTRY}


def _gate_item_payload(bucket, item):
    entry = _CHECK_ENTRY_BY_ID.get(item.get("check_id"))
    return {
        "check_id": item.get("check_id") or "",
        "label": entry.row_label if entry else (item.get("check_id") or ""),
        "severity": entry.severity if entry else "",
        "bucket": bucket,
        "blocks": bool(item.get("blocks")),
        "has_fix": bool(entry.has_fix) if entry else False,
        "new_count": int(item.get("new_count") or 0),
        "violations": [
            _qc_violation_detail(v) for v in (item.get("violations") or [])
        ],
    }


def gate_state_payload(gate_result, sidecar_invalid=False):
    """Map one ``gate.evaluate_gate()`` result to the SPA's GateState
    contract (``GET/POST /api/form/gate/state``, and echoed back inside
    every ``form/gate/submit`` response so the page never needs a second
    round trip to refresh).

    Pure: no c4d. The caller (see ``ui/web_ops.py``) computes
    ``gate_result`` on the C4D main thread exactly the way
    ``ui/flows.py`` ``_run_quality_gate`` does (``_compute_gate_snapshot``),
    and passes ``sidecar_invalid`` from that same snapshot's
    ``baseline_status``.

    ``bucket`` ("fixable"/"blocking"/"advisory") is ``evaluate_gate``'s own
    English grouping — used directly instead of re-deriving from
    ``gate.classify_gate``'s Spanish level constants
    (``CORREGIBLE``/``BLOQUEANTE``/``AVISO``), which stay internal to
    ``gate.py``/the native dialog.

    Output (TS-ready — Task 3 mirrors this as ``GateState``)::

        {
          "passed": bool,
          "sidecar_invalid": bool,
          "checks": [
            {"check_id": str, "label": str, "severity": "FAIL"|"WARN",
             "bucket": "fixable"|"blocking"|"advisory", "blocks": bool,
             "has_fix": bool, "new_count": int,
             "violations": [{"label", "message", "extras"}, ...]}
          ],
        }

    Never raises on missing/partial input.
    """
    gate_result = gate_result or {}
    checks = []
    for bucket in ("fixable", "blocking", "advisory"):
        for item in gate_result.get(bucket) or []:
            checks.append(_gate_item_payload(bucket, item))

    return {
        "passed": bool(gate_result.get("passed", True)),
        "sidecar_invalid": bool(sidecar_invalid),
        "checks": checks,
    }


def gate_can_proceed(gate_result):
    """Whether the gate may be considered resolved right now — pure re-check
    run fresh after each mutating action (``fix_all``/``accept``), so it
    needs no per-row ``decisions``/``reason`` state like the native
    ``ui/dialogs.py`` ``gate_dialog_can_proceed`` (built for one long-lived
    modal session): a check_id that was successfully fixed or accepted
    simply no longer appears in ``blocking``/``fixable`` once its new-count
    drops to 0 (``evaluate_gate`` only emits checks with ``new_count > 0``).

    Equivalent condition: no ``blocking``-bucket item, AND no
    ``fixable``-bucket item with ``blocks`` True (a WARN-severity fixable
    check, e.g. unused materials, never blocks — same as native). Advisory
    items never block either, in both implementations.
    """
    gate_result = gate_result or {}
    if gate_result.get("blocking"):
        return False
    for item in gate_result.get("fixable") or []:
        if item.get("blocks"):
            return False
    return True


# ---------------------------------------------------------------------------
# Command palette — action registry + gating
# ---------------------------------------------------------------------------

# Static action descriptors. "kind": "run" executes server-side work through
# `palette/run`; "kind": "navigate" is pure SPA client-side routing (the
# server only validates whether the target page makes sense right now — see
# `requires_doc`/`requires_saved` below — the FormDialog host that actually
# opens the page is Phase 4 Task 4, not built yet). `check_id` on a "Quick
# Fix" run action ties it to the QC check whose current violation count
# gates `enabled` (see `palette_actions_payload`) — same check_ids the
# panel's own `_qc_fix_*` handlers key off of (`self._lights_bad` etc.).
#
# `requires_confirm` + `confirm_label` mark the two Quick Fix actions whose
# native handlers gate on a real ``QuestionDialog`` decision, per
# docs/superpowers/specs/2026-07-19-popup-triage.md (DECISIÓN, "must stay"):
# panel.py:1891 "Delete N unused material(s)?" (destructive) and panel.py:1918
# the FPS/range fix preview + confirm (destructive — rewrites every render
# preset). ``fix_lights``/``fix_cameras`` never had a native confirm (they
# are reversible, low-impact fixes reported via status bar only — see
# panel.py `_qc_fix_lights`/`_qc_fix_cam`), so they stay unconfirmed. A
# native modal can't be opened mid-``palette/run`` (it would block the
# ``MainThreadQueue`` drain loop and hang the HTTP request under the
# cancellation contract — see webbridge.MainThreadQueue.drain), so the gate
# is a contract-level round trip instead: `palette/run` rejects a
# `requires_confirm` action with ``{"error": "confirm_required"}`` unless
# the payload carries ``confirm: true`` — the SPA must render
# `confirm_label` as an explicit yes/no step before resubmitting with that
# flag (see `palette_actions_payload` / `ui/web_ops.py` `_op_palette_run`).
PALETTE_ACTIONS = (
    {"id": "open_hub", "label": "Open Asset Hub", "group": "Navigate",
     "kind": "run", "requires_doc": True},
    {"id": "open_reports_qc", "label": "Open Reports · QC", "group": "Navigate",
     "kind": "run", "requires_doc": False},
    {"id": "open_reports_doctor", "label": "Open Reports · Doctor", "group": "Navigate",
     "kind": "run", "requires_doc": False},
    {"id": "open_reports_supervisor", "label": "Open Reports · Supervisor",
     "group": "Navigate", "kind": "run", "requires_doc": False},
    {"id": "open_reports_render_validation", "label": "Open Reports · Render Validation",
     "group": "Navigate", "kind": "run", "requires_doc": False},
    {"id": "open_reports_delivery", "label": "Open Reports · Delivery Summary",
     "group": "Navigate", "kind": "run", "requires_doc": False},
    {"id": "save_version", "label": "Save Version…", "group": "Scene",
     "kind": "navigate", "page": "form/save_version", "requires_doc": True},
    {"id": "edit_notes", "label": "Edit Notes…", "group": "Scene",
     "kind": "navigate", "page": "form/notes", "requires_doc": True,
     "requires_saved": True},
    {"id": "settings", "label": "Settings…", "group": "Scene",
     "kind": "navigate", "page": "form/settings", "requires_doc": False},
    {"id": "gate_triage", "label": "Quality Gate Triage…", "group": "Scene",
     "kind": "navigate", "page": "form/gate", "requires_doc": True},
    {"id": "fix_lights", "label": "Fix: Group stray lights", "group": "Quick Fix",
     "kind": "run", "requires_doc": True, "check_id": "lights"},
    {"id": "fix_cameras", "label": "Fix: Reset camera shift", "group": "Quick Fix",
     "kind": "run", "requires_doc": True, "check_id": "cam"},
    {"id": "fix_materials", "label": "Fix: Delete unused materials",
     "group": "Quick Fix", "kind": "run", "requires_doc": True,
     "check_id": "unused_mats", "requires_confirm": True,
     "confirm_label": "Delete {count} unused material(s) — single undo",
     "confirm_verb": "Delete materials", "destructive": True},
    {"id": "fix_fps", "label": "Fix: FPS / frame range", "group": "Quick Fix",
     "kind": "run", "requires_doc": True, "check_id": "fps_range",
     "requires_confirm": True,
     "confirm_label": "Rewrite FPS + frame range on {count} issue(s) "
                       "across ALL render presets — single undo",
     "confirm_verb": "Rewrite FPS + range", "destructive": True},
    {"id": "rescan_qc", "label": "Rescan QC", "group": "Quick Fix",
     "kind": "run", "requires_doc": True},
)

PALETTE_ACTION_BY_ID = {action["id"]: action for action in PALETTE_ACTIONS}


def palette_actions_payload(doc_present, doc_saved=False, qc_counts=None):
    """Pure: build the ``palette/actions`` response — ``PALETTE_ACTIONS``'s
    static descriptors plus per-call ``enabled``/``reason`` gating.

    ``qc_counts`` maps check_id -> current legacy violation count (see
    ``qc.score.count_violations``); a Quick Fix action is disabled with
    reason "Nothing to fix" when its check's count is 0 — mirrors the
    panel's own ``_qc_fix_*`` handlers, which are no-ops printing "No ...
    issues to fix" when their bad-list is empty (Phase 4 Task 2 gives that
    same no-op a disabled, not just a silent-no-op, palette entry).

    Every action carries ``requires_confirm``/``confirm_label`` (False/None
    for most). For the two DECISIÓN-classified destructive fixes
    (``fix_materials``, ``fix_fps`` — see the ``PALETTE_ACTIONS`` comment
    above), ``confirm_label`` is formatted with the live ``qc_counts`` value
    for that action's ``check_id`` so the SPA can show "Delete 3 unused
    material(s) — single undo" instead of static wording; a missing count
    falls back to 0 rather than raising.

    ``confirm_verb`` + ``destructive`` are the button half of that contract
    (the SPA's ``ConfirmBar``): the verb is what the confirm BUTTON says
    ("Delete materials"), so the artist accepts a named action instead of a
    mute "Confirm", and ``destructive`` is what licenses the red variant +
    the non-primary position. The server owns both because the server is
    what knows the consequence — the SPA never marks an action destructive
    on its own. ``confirm_verb`` is None for anything that doesn't confirm
    (the client falls back to "Confirm"), and ``destructive`` is False
    unless the descriptor says otherwise, so no action becomes red by
    accident.

    Never raises: an action with a ``check_id`` not present in
    ``qc_counts`` is treated as 0 (nothing to fix), never a KeyError.
    """
    qc_counts = qc_counts or {}
    actions = []
    for action in PALETTE_ACTIONS:
        enabled = True
        reason = None
        if action.get("requires_doc") and not doc_present:
            enabled = False
            reason = "No active document"
        elif action.get("requires_saved") and not doc_saved:
            enabled = False
            reason = "Save the scene to a folder first"
        elif action.get("check_id") and qc_counts.get(action["check_id"], 0) == 0:
            enabled = False
            reason = "Nothing to fix"

        requires_confirm = bool(action.get("requires_confirm"))
        confirm_label = None
        confirm_verb = None
        if requires_confirm:
            count = qc_counts.get(action.get("check_id"), 0)
            confirm_label = action["confirm_label"].format(count=count)
            confirm_verb = action.get("confirm_verb")

        actions.append({
            "id": action["id"],
            "label": action["label"],
            "group": action["group"],
            "enabled": enabled,
            "reason": reason,
            "requires_confirm": requires_confirm,
            "confirm_label": confirm_label,
            "confirm_verb": confirm_verb,
            "destructive": bool(action.get("destructive")),
        })
    return actions
