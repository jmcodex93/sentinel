"""panel/deliver ops (Fase 6.3) — Deliver section of the SPA panel.

Thin adapters over the versioning/notes/manifest engines, following the
``panel/overview`` and ``panel/render`` conventions: a read op with
ISOLATED blocks (``_guarded_block`` — one raising builder never blanks the
rest), plus action ops that open windows/documents. The version-open
action runs through ``flows.open_version_core`` (dialog-free, status dict)
because a ``MessageDialog`` inside the panel's Timer drain freezes all of
C4D (v1.21.0 pattern).

Save Version / Notes submits are NOT here — the SPA absorbs the existing
form pages and reuses ``form/save_version/*`` / ``form/notes/*``.

``panel/deliver`` payload shape::

    { "version": {
          "last": {"version": int, "status": str, "age": str|None, "qc_label": str|None} | None,
          "unsaved": bool,
          "recent": [ {"version": int, "status": str, "age": str|None,
                       "qc_label": str|None, "path": str, "filename": str} ]
        } | None,
      "notes": {"summary": str, "todos_pending": int, "notes_present": bool, "unsaved": bool} | None,
      "deliver": {"has_manifest": bool} | None }

``recent`` is capped at 15 entries, unfiltered (the SPA filters by status).
Each entry carries the absolute ``path`` and ``filename`` used by
``open_version``. ``unsaved`` is ``True`` when the doc has no document path.
"""
import os

import c4d

from sentinel.ui.hub_ops import _stamp_for
from sentinel.ui.panel_ops import _guarded_block
from sentinel import versioning
from sentinel import notes as notes_engine

_RECENT_CAP = 15


def _panel_version_block(doc):
    """Version card: latest version pill + a capped, unfiltered recent list.
    ``unsaved`` (doc has no path) drives the SPA's "save the scene first"
    empty state; ``recent`` carries each row's absolute path for open."""
    unsaved = not bool(doc.GetDocumentPath())
    info = versioning.get_latest_version_info(doc)
    last = None
    if info:
        try:
            ver = int(info.get("version", 0))
        except Exception:
            ver = 0
        last = {
            "version": ver,
            "status": info.get("status", "") or "",
            "age": versioning._humanize_time_diff(info.get("timestamp", "")) or None,
            "qc_label": versioning.format_history_qc_label(info) or None,
        }

    recent = []
    if not unsaved:
        for entry in (versioning.load_versions_for_doc(doc) or [])[:_RECENT_CAP]:
            if not entry:
                continue
            try:
                ver = int(entry.get("version", 0))
            except Exception:
                ver = 0
            path = (entry.get("path") or "").strip()
            recent.append({
                "version": ver,
                "status": entry.get("status", "") or "",
                "age": versioning._humanize_time_diff(entry.get("timestamp", "")) or None,
                "qc_label": versioning.format_history_qc_label(entry) or None,
                "path": path,
                "filename": entry.get("filename") or (os.path.basename(path) if path else ""),
            })

    return {"last": last, "unsaved": unsaved, "recent": recent}


def _panel_notes_block(doc):
    """Notes card: same sidecar reads as ``web_ops._op_form_notes_state``
    and the native panel caption."""
    unsaved = not bool(doc.GetDocumentPath())
    notes_path = notes_engine.get_notes_path(doc)
    notes = notes_engine.load_notes(notes_path) if notes_path else {}
    todos = notes.get("todos") or []
    todos_pending = sum(1 for t in todos if not t.get("done"))
    notes_present = bool((notes.get("notes") or "").strip()) or bool(todos)
    return {
        "summary": notes_engine.summarize_notes(notes),
        "todos_pending": todos_pending,
        "notes_present": notes_present,
        "unsaved": unsaved,
    }


def delivery_manifest_available(doc):
    """True if a collected ``sentinel_manifest.json`` with an asset section
    (I4+) sits next to the open scene — mirrors the native
    ``panel._delivery_manifest_available`` gate."""
    if not doc:
        return False
    doc_path = doc.GetDocumentPath()
    if not doc_path:
        return False
    path = os.path.join(doc_path, "sentinel_manifest.json")
    if not os.path.exists(path):
        return False
    try:
        from sentinel import manifest as manifest_engine
        data = manifest_engine.load_manifest_json(path)
    except Exception:
        return False
    return bool(data and data.get("assets_schema"))


def _panel_deliver_access_block(doc):
    """Deliver-access card: only Delivery Summary is conditional."""
    return {"has_manifest": delivery_manifest_available(doc)}


def build_panel_deliver(doc):
    """Read model for the Deliver section. Blocks isolated: one raising
    builder yields ``None`` for its block, never blanks the section."""
    return {
        "version": _guarded_block("version", _panel_version_block, doc),
        "notes": _guarded_block("notes", _panel_notes_block, doc),
        "deliver": _guarded_block("deliver", _panel_deliver_access_block, doc),
    }


def _op_panel_deliver(payload):
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"version": None, "notes": None, "deliver": None, "stamp": None}
    result = build_panel_deliver(doc)
    try:
        result["stamp"] = _stamp_for(doc)
    except Exception:
        result["stamp"] = None
    return result


def _op_panel_deliver_open_version(payload):
    """Open (or re-activate) a version .c4d via the dialog-free core.

    Non-destructive: an already-open version is re-activated
    (``switched``), an unopened one is loaded from disk (``opened``) as a
    new document with the current one left untouched — so there's no
    confirm/force step (see ``flows.open_version_core``)."""
    from sentinel.ui import flows
    path = (payload or {}).get("path") or ""
    result = flows.open_version_core(path)
    if result.get("ok"):
        # Re-stamp against the NOW-active doc (the load/switch changed it).
        active = c4d.documents.GetActiveDocument()
        result["stamp"] = _stamp_for(active) if active else None
    return result


def _op_panel_deliver_open_collect(payload):
    """Open the Asset Hub focused on delivery (mirrors the native Collect
    button). Window, not absorbed."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "No active document"}
    try:
        from sentinel.ui.reports_dialog import open_form
        open_form(doc, "hub", query={"focus": "deliver"})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": "Asset Hub opened"}


PANEL_DELIVER_OPS = {
    "panel/deliver": _op_panel_deliver,
    "panel/deliver/open_version": _op_panel_deliver_open_version,
    "panel/deliver/open_collect": _op_panel_deliver_open_collect,
}
