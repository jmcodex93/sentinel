# -*- coding: utf-8 -*-
"""Asset Hub SPA ops (fase 5) — read ops (inventory, state_stamp, presets,
preflight) plus mutation ops (apply_repath, select_owner, pick_path, thumb).
Thin c4d adapters over the same engines the native ``AssetHubDialog`` uses —
zero duplicated logic. Sibling of ``ui/reports_dialog.py`` / ``ui/web_ops.py``
(same ``MainThreadQueue`` dispatch-target contract — see
``webbridge.MainThreadQueue.drain`` for the invariant every handler must
honor). Host-agnostic: no dialog imports here; merged into
``reports_dialog._OPS`` by whichever task wires the route.

Every op re-reads the active document at dispatch time (HTTP is stateless).
Collect/delivery job ops land in Task 6.
"""

import os

import c4d
from c4d import documents

from sentinel import webbridge
from sentinel import assets as assets_engine
from sentinel.qc.score import compute_score, run_all_checks
from sentinel.rules_context import active_rules_for_doc


def _op_hub_inventory(payload):
    """``hub/inventory`` — full asset scan the same way
    ``AssetHubDialog`` builds its table: ``ui.flows.scan_scene_assets``
    (structured texture scan + ``GetAllAssetsNew`` merge) -> stat every
    record's size on disk -> ``assets.compute_totals`` -> shaped for the
    SPA via ``webbridge.hub_inventory_payload``. Imported locally, same as
    the native dialog, to avoid pulling ``ui.flows``'s import chain into
    this module at load time.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    from sentinel.ui.flows import scan_scene_assets

    records, _tex_records, skipped = scan_scene_assets(doc)
    start = 0
    while start < len(records):
        start = assets_engine.stat_sizes_batch(records, start, 64)
    totals = assets_engine.compute_totals(records)
    return webbridge.hub_inventory_payload(
        records, totals, scene_name=doc.GetDocumentName() or "", skipped=skipped)


def _op_hub_state_stamp(payload):
    """``hub/state_stamp`` — a cheap, comparable fingerprint of the active
    document's asset-relevant state, so the SPA can poll and only re-fetch
    ``hub/inventory`` when something actually changed. ``GetDirty`` support
    on ``BaseDocument`` is unverified live (per the task's own note) so it
    is wrapped defensively, falling back to ``GetChanged()``.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    try:
        dirty = doc.GetDirty(c4d.DIRTYFLAGS_DATA | c4d.DIRTYFLAGS_CHILDREN)
    except Exception:
        dirty = int(bool(doc.GetChanged()))

    stamp = "%s|%s|%s|%s" % (
        doc.GetDocumentPath() or "",
        doc.GetDocumentName() or "",
        dirty,
        len(doc.GetMaterials()),
    )
    return {"stamp": stamp}


def _op_hub_presets(payload):
    """``hub/presets`` — the persisted Texture Repathing Find/Replace
    history (``ui.dialogs.load_repath_presets``), reshaped as objects for
    the SPA. Imported locally per this module's own header note (avoids
    pulling ``ui.dialogs``'s much larger import chain at load time)."""
    from sentinel.ui.dialogs import load_repath_presets

    return {"presets": [{"find": f, "replace": r}
                         for (f, r) in load_repath_presets()]}


def _op_hub_presets_save(payload):
    """``hub/presets/save`` — push a (find, replace) pair to the front of
    the persisted history, same as ``ui.dialogs.save_repath_preset``
    (de-dupes, caps at 5)."""
    find_str = (payload.get("find") or "").strip()
    replace_str = payload.get("replace") or ""
    if not find_str:
        return {"ok": False, "error": "empty find"}

    from sentinel.ui.dialogs import save_repath_preset

    save_repath_preset(find_str, replace_str)
    return {"ok": True}


def _op_hub_preflight(payload):
    """``hub/preflight`` — run the 12 QC checks and score them exactly the
    way ``ui/reports_dialog.py`` ``_op_report_qc`` does (itself matching
    ``AssetHubDialog._refresh_preflight``'s own documented source of
    truth): ``active_rules_for_doc`` -> ``run_all_checks`` ->
    ``compute_score`` (baseline kwargs only added when a baseline sidecar
    already exists on disk), shaped via ``webbridge.qc_report_payload``.
    ``_baseline_path_for_doc``/``_current_module`` are private to
    ``ui.flows`` and imported locally for the same load-order reason
    ``reports_dialog.py`` does it locally (``ui.flows`` imports
    ``ui.dialogs`` at module scope for ``GateTriageDialog``).
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    from sentinel.ui.flows import _baseline_path_for_doc, _current_module

    rules_context = active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    score_kwargs = {"baseline_path": baseline_path,
                     "current_params": rules_context.params} if baseline_path else {}
    score = compute_score(registry_results, rules_context, **score_kwargs)

    structured_by_check = {
        check_id: pair.get("structured_result")
        for check_id, pair in registry_results.items()
    }
    ruleset = {
        "name": (os.path.basename(rules_context.rules_path)
                 if rules_context.rules_path else "defaults"),
        "path": rules_context.rules_path,
        "shadowed": list(rules_context.shadowed_paths or []),
        "severity_overrides": (rules_context.params or {}).get("check_severity", {}),
    }
    scene_name = doc.GetDocumentName() or "Untitled"

    return webbridge.qc_report_payload(scene_name, ruleset, score, structured_by_check)


def _op_hub_apply_repath(payload):
    """``hub/apply_repath`` — bulk-write pending Find/Replace / relink
    changes. HTTP is stateless, so the client's ``key``s are re-resolved
    against a *fresh* ``scan_scene_assets`` right here (same canonical keys
    ``hub/inventory`` handed out) via ``webbridge.resolve_repath_targets`` —
    a scene that changed between fetch and submit surfaces as a per-key
    "unknown key" error, never a mis-write. Every live write goes through
    ``textures.apply_texture_path_change`` (its own ``doc.AddUndo`` anchor
    lives inside, per shader) — this op only brackets the whole batch in
    one ``StartUndo``/``EndUndo`` (matching ``AssetHubDialog``'s Apply All)
    so a single Cmd+Z reverts every row.
    """
    changes = payload.get("changes") or []
    if not changes:
        return {"ok": False, "error": "no_changes"}
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.ui.flows import scan_scene_assets
    from sentinel.textures import apply_texture_path_change

    records, tex_records, _skipped = scan_scene_assets(doc)
    targets, errors = webbridge.resolve_repath_targets(records, changes)
    applied = 0
    doc.StartUndo()
    try:
        for target in targets:
            row_ok = True
            for tex_idx in target["tex_idxs"]:
                try:
                    live = tex_records[tex_idx]
                except IndexError:
                    row_ok = False
                    continue
                if not apply_texture_path_change(live, target["new_path"], doc=doc):
                    row_ok = False
            if row_ok:
                applied += 1
            else:
                errors.append({"key": target["key"], "error": "writer failed"})
    finally:
        doc.EndUndo()
    c4d.EventAdd()
    return {"ok": True, "applied": applied, "errors": errors}


def _op_hub_select_owner(payload):
    """``hub/select_owner`` — select the record's owning material/object in
    the scene, so an SPA row click behaves like the native table row click.
    Owner-selection idiom copied verbatim from
    ``AssetHubDialog._select_owner_in_scene`` (dialogs.py ~2108): rows with
    no ``tex_idx`` (generic ``GetAllAssetsNew`` entries not backed by a
    structured TextureRecord) are a documented no-op — same known debt as
    the native dialog (see ``assets.merge_asset_records``). Material vs.
    object dispatch is a plain ``isinstance(host, c4d.BaseMaterial)``
    branch — no selection-flag juggling, matching the native code exactly.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    key = payload.get("key") or ""

    from sentinel.ui.flows import scan_scene_assets

    records, tex_records, _skipped = scan_scene_assets(doc)
    rec = next((r for r in records if r.get("key") == key), None)
    if rec is None:
        return {"ok": False, "error": "unknown key"}
    tex_idx = rec.get("tex_idx")
    if tex_idx is None:
        return {"ok": True}
    try:
        host = tex_records[tex_idx].get("host")
    except IndexError:
        host = None
    if host is None:
        return {"ok": True}
    if isinstance(host, c4d.BaseMaterial):
        doc.SetActiveMaterial(host)
    else:
        doc.SetActiveObject(host)
    c4d.EventAdd()
    return {"ok": True}


def _op_hub_pick_path(payload):
    """``hub/pick_path`` — native file/directory picker for relink and
    Search-Folder-for-Missing. Runs inside the ``MainThreadQueue`` drain
    (the dialog ``Timer``), so this modal ``LoadDialog`` call blocks the
    queue while open — safe because of the fase-4 per-request lock in
    ``MainThreadQueue``: the SPA's ``submit()`` blocks on that same lock
    with its own timeout and still gets the real result once the artist
    closes the dialog, instead of racing a stale/cancelled response.
    """
    flags = c4d.FILESELECT_DIRECTORY if payload.get("directory") else c4d.FILESELECT_LOAD
    path = c4d.storage.LoadDialog(title=payload.get("title") or "Choose", flags=flags)
    if not path:
        return {"ok": False, "error": "cancelled"}
    return {"ok": True, "path": path}


_THUMB_SIZE = 64


def _thumb_cache_dir():
    prefs = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
    cache_dir = os.path.join(prefs, "sentinel_thumbs")
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir)
    return cache_dir


def _op_hub_thumb(payload):
    """``hub/thumb`` — lazy per-asset PNG thumbnail, disk-cached by
    (resolved_path, mtime) via ``webbridge.thumb_cache_name`` so repeat
    requests for an unchanged file are a stat + return, not a re-decode.
    Re-scans the scene per request (stateless HTTP, same as every other
    hub op) — if live verification shows this too slow with many visible
    rows, add a module-level ``{key: resolved_path}`` memo refreshed by
    ``hub/inventory``, but only then (YAGNI, per the task brief).
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    key = payload.get("key") or ""

    from sentinel.ui.flows import scan_scene_assets

    records, _tex, _skipped = scan_scene_assets(doc)
    rec = next((r for r in records if r.get("key") == key), None)
    resolved = (rec or {}).get("resolved_path")
    if not resolved or not os.path.isfile(resolved):
        return {"error": "no_thumb"}
    try:
        mtime = os.path.getmtime(resolved)
        cache_path = os.path.join(
            _thumb_cache_dir(), webbridge.thumb_cache_name(resolved, mtime))
        if os.path.isfile(cache_path):
            return {"png_path": cache_path}
        bmp = c4d.bitmaps.BaseBitmap()
        if bmp.InitWith(resolved)[0] != c4d.IMAGERESULT_OK:
            return {"error": "unreadable"}
        small = c4d.bitmaps.BaseBitmap()
        small.Init(_THUMB_SIZE, _THUMB_SIZE)
        bmp.ScaleIt(small, 256, True, False)
        if not small.Save(cache_path, c4d.FILTER_PNG):
            return {"error": "save_failed"}
        return {"png_path": cache_path}
    except Exception as exc:
        return {"error": "thumb error: %s" % exc}


HUB_OPS = {
    "hub/inventory": _op_hub_inventory,
    "hub/state_stamp": _op_hub_state_stamp,
    "hub/presets": _op_hub_presets,
    "hub/presets/save": _op_hub_presets_save,
    "hub/preflight": _op_hub_preflight,
    "hub/apply_repath": _op_hub_apply_repath,
    "hub/select_owner": _op_hub_select_owner,
    "hub/pick_path": _op_hub_pick_path,
    "hub/thumb": _op_hub_thumb,
}
