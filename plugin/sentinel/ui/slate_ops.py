# -*- coding: utf-8 -*-
"""Panel ops for the visual slate editor (Render → Snapshots → Slate…).

``panel/slate/state``   — the effective slate (on/off + ``slate_style``) and
                          where it comes from.
``panel/slate/preview`` — the slate drawn by C4D with an UNSAVED style on the
                          newest snapshot (or a grey frame), as a data URI.
``panel/slate/save``    — writes ``slate`` + ``slate_style`` to the project's
                          ``sentinel_rules.json`` after a server-owned confirm
                          that names the file and every change.

The style always goes through ``slate.validate_style`` on the server; the
client's copy is never trusted. Saving reuses Publish standard's safety: an
unreadable ruleset is never overwritten, manual keys survive, only what
differs from the default slate is written, tmp + ``os.replace``.
"""
import base64
import json
import os

import c4d

from sentinel import rules as rules_module
from sentinel import slate as slate_layout
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings


def _doc():
    return c4d.documents.GetActiveDocument()


def _context(doc):
    from sentinel.ui.flows import _active_rules_for_doc
    return _active_rules_for_doc(doc)


def _state(doc):
    context = _context(doc)
    return {
        "enabled": bool(context.params.get("slate", False)),
        "enabled_source": context.field_sources.get("slate", "defaults"),
        "style": context.params.get("slate_style") or slate_layout.default_style(),
        "style_source": context.field_sources.get("slate_style", "defaults"),
        "rules_path": context.rules_path or "",
        "scene_saved": bool(doc.GetDocumentPath()),
        "tokens": list(slate_layout.TOKENS),
        "warnings": [w for w in context.warnings if "slate" in w],
    }


def _op_slate_state(payload):
    doc = _doc()
    if doc is None:
        return {"ok": False, "error": "no_document"}
    return dict(_state(doc), ok=True)


def _op_slate_preview(payload):
    payload = payload or {}
    doc = _doc()
    if doc is None:
        return {"ok": False, "error": "no_document"}
    ok, style, reason = slate_layout.validate_style(payload.get("style") or {})
    if not ok:
        return {"ok": False, "error": "bad_style", "detail": reason}
    from sentinel import snapshot_c4d
    if not snapshot_c4d.ocio_available():
        return {"ok": False, "error": "needs_2025_2"}
    from sentinel.ui import flows
    context = _context(doc)
    slate_data = flows.build_slate_data(doc, GlobalSettings.load_artist_name() or "",
                                        project=flows._rules_project(context))
    font, font_name = snapshot_c4d.resolve_slate_font()
    snap_dir, _origin = flows.get_effective_snapshot_dir()
    exr_path, _ = flows._find_latest_exr(snap_dir) if snap_dir else (None, None)
    converter = snapshot_c4d.color_converter(doc) if exr_path else None
    enabled = payload.get("enabled", True) is not False
    full_size = bool(payload.get("open"))
    try:
        png, info = snapshot_c4d.preview_png(slate_data, font, style, exr_path=exr_path,
                                             converter=converter, enabled=enabled,
                                             max_width=None if full_size else 960)
    except Exception as exc:
        safe_print("Slate preview failed: %s" % exc)
        return {"ok": False, "error": "preview_failed", "detail": str(exc)}
    if full_size:
        # "View at 100 %": the DRAFT, full size, in the system viewer — the
        # temp folder, never the stills folder.
        import tempfile
        from sentinel.common.helpers import open_in_explorer
        path = os.path.join(tempfile.gettempdir(), "sentinel_slate_preview.png")
        with open(path, "wb") as fh:
            fh.write(png)
        open_in_explorer(path)
        return dict(info, ok=True, path=path, font=font_name)
    return dict(info, ok=True, font=font_name,
                image="data:image/png;base64," + base64.b64encode(png).decode("ascii"))


def _read_raw(path):
    """``(raw dict | None, readable)`` — an existing file that cannot be read
    is never overwritten (it would destroy the project's manual keys)."""
    if not os.path.exists(path):
        return None, True
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return None, False
    return (raw, True) if isinstance(raw, dict) else (None, False)


def _short(path):
    """``…/<parent>/sentinel_rules.json`` — the full path rides in ``path``."""
    parent = os.path.basename(os.path.dirname(path))
    return "…/%s/%s" % (parent, os.path.basename(path)) if parent else path


def _same_dir(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _op_slate_save(payload):
    payload = payload or {}
    doc = _doc()
    if doc is None:
        return {"ok": False, "error": "no_document"}
    scene_dir = doc.GetDocumentPath()
    if not scene_dir:
        return {"ok": False, "error": "unsaved"}
    ok, style, reason = slate_layout.validate_style(payload.get("style") or {})
    if not ok:
        return {"ok": False, "error": "bad_style", "detail": reason}
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        return {"ok": False, "error": "bad_style", "detail": "enabled must be true or false"}

    # Where to write is re-derived here. An active ruleset is always the
    # target (writing elsewhere would be shadowed by it); only a scene with no
    # ruleset accepts a folder, and only one the rules discovery will read.
    context = _context(doc)
    searched = rules_module.discovery_dirs(scene_dir)
    if context.rules_path:
        folder = os.path.dirname(context.rules_path)
    else:
        folder = str(payload.get("folder") or "").strip()
        if not folder:
            return {"ok": False, "error": "need_folder", "searched": searched}
        if not os.path.isdir(folder):
            return {"ok": False, "error": "bad_folder"}
        if not any(_same_dir(folder, d) for d in searched):
            return {"ok": False, "error": "folder_out_of_reach", "searched": searched}
    path = os.path.join(folder, rules_module.RULES_FILENAME)

    existing, readable = _read_raw(path)
    if not readable:
        return {"ok": False, "error": "rules_unreadable", "path": path}
    existing = existing or {}
    ok_old, old_style, _ = slate_layout.validate_style(existing.get("slate_style") or {})
    if not ok_old:
        old_style = slate_layout.default_style()
    old_enabled = existing.get("slate") if isinstance(existing.get("slate"), bool) else None
    lines = []
    if old_enabled is not enabled:
        lines.append("slate: %s → %s" % ({True: "on", False: "off", None: "not set"}[old_enabled],
                                         "on" if enabled else "off"))
    lines += slate_layout.style_diff(old_style, style)
    if not lines:
        return {"ok": True, "unchanged": True, "path": path, "state": _state(doc)}
    if not payload.get("confirm"):
        return {"ok": False, "error": "confirm_required",
                "confirm_label": "Save the slate to %s — it changes for everyone in this "
                                 "project:\n%s" % (_short(path), "\n".join("• " + l for l in lines)),
                "confirm_verb": "Save for the project", "destructive": False,
                "path": path, "changes": lines}

    new_raw = dict(existing)
    compact = slate_layout.compact_style(style)
    if compact:
        new_raw["slate_style"] = compact
    else:
        new_raw.pop("slate_style", None)
    new_raw["slate"] = enabled
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(new_raw, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "error": "write_failed", "detail": str(exc)}
    rules_module.invalidate()
    safe_print("Slate saved to %s: %s" % (path, "; ".join(lines)))
    return {"ok": True, "path": path, "changes": lines, "state": _state(doc)}


SLATE_OPS = {
    "panel/slate/state": _op_slate_state,
    "panel/slate/preview": _op_slate_preview,
    "panel/slate/save": _op_slate_save,
}
