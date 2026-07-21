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
The Collect job (``hub/collect_start`` + ``pump_jobs``) is a Task 6
addition — see those functions for the ``webbridge.JOBS`` contract.
"""

import os
import shutil

import c4d
from c4d import documents

from sentinel import webbridge
from sentinel import assets as assets_engine
from sentinel import gate as quality_gate
from sentinel import imagemeta
from sentinel.common.settings import GlobalSettings
from sentinel.qc.score import compute_score, run_all_checks
from sentinel.rules_context import active_rules_for_doc


# Live-verified (2026-07-20): ``hub/thumb`` used to run its own
# ``scan_scene_assets`` per request, so scrolling a table full of rows
# queued dozens of full texture-scan + GetAllAssetsNew passes on the main
# thread back-to-back — scroll jank, late thumbs, and the 2s state-stamp
# poll starved behind them (looked like undo auto-refresh was broken, it
# was actually queue congestion). This memo is refreshed by every op that
# already runs a fresh full scan, so ``hub/thumb`` can look the path up
# for free instead of re-scanning.
_THUMB_PATHS = {}


def _remember_thumb_paths(records):
    """Refresh the ``key -> resolved_path`` memo from a fresh
    ``scan_scene_assets`` result. Replaces (not merges) so stale keys from
    a previous scene state don't linger."""
    _THUMB_PATHS.clear()
    _THUMB_PATHS.update({r.get("key"): r.get("resolved_path") for r in records})


# (path, mtime, size_bytes) -> enriched-meta-dict | None. Never purged
# across requests within a session (same lifetime rule as _THUMB_PATHS) —
# a changed file gets a new key (different mtime/size), so a stale entry
# is simply orphaned, never served.
_META_CACHE = {}

_META_BATCH_CAP = 64


def _stat_cache_key(path):
    """``(path, mtime, size)`` cache key for ``path``, or ``None`` when the
    file can't be stat'd (deleted/inaccessible). No parsing here — callers
    that only want to know "is there a cache entry" (``hub/meta_totals``,
    the inventory vram rollup) use this alone, without ever touching
    ``imagemeta.read_image_meta``."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, st.st_mtime, st.st_size), st.st_size


def _meta_for(path):
    """Read + cache image header metadata for a resolved asset path.

    Cache key is ``(path, mtime, size)`` so an edited file (new mtime/size)
    never serves a stale entry. A parse failure (or a format
    ``imagemeta`` doesn't recognize) is cached as ``None`` too — an
    unparseable file stays unparseable until its stat changes, so it is
    never re-attempted on every request. Enriches a successful parse with
    ``vram_bytes``/``vram_label`` (``imagemeta.vram_bytes`` +
    ``assets_engine.format_size``), ``res_label``/``res_tier``
    (``imagemeta.res_bucket`` of ``max(width, height)``), and
    ``disk_bytes`` (the stat's own size — no second stat needed downstream
    in ``hub/meta_totals``).
    """
    key_size = _stat_cache_key(path)
    if key_size is None:
        return None
    cache_key, size_bytes = key_size
    if cache_key in _META_CACHE:
        return _META_CACHE[cache_key]

    raw = imagemeta.read_image_meta(path)
    if raw is None:
        _META_CACHE[cache_key] = None
        return None

    vram = imagemeta.vram_bytes(raw["width"], raw["height"], raw["channels"], raw["bit_depth"])
    bucket = imagemeta.res_bucket(max(raw["width"], raw["height"]))
    meta = dict(raw)
    meta["vram_bytes"] = vram
    meta["vram_label"] = assets_engine.format_size(vram)
    meta["res_label"] = bucket["label"]
    meta["res_tier"] = bucket["tier"]
    meta["disk_bytes"] = size_bytes
    _META_CACHE[cache_key] = meta
    return meta


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
    _remember_thumb_paths(records)
    totals["vram_bytes"] = _cached_vram_total()
    totals["vram_label"] = assets_engine.format_size(totals["vram_bytes"])
    return webbridge.hub_inventory_payload(
        records, totals, scene_name=doc.GetDocumentName() or "", skipped=skipped)


def _cached_vram_total():
    """Sum ``vram_bytes`` over unique resolved paths already present in
    ``_META_CACHE`` — no parsing, so the inventory scan (and this rollup)
    stays fast even on a scene with hundreds of unfetched textures. Shared
    by ``_op_hub_inventory`` (fresh-scan rollup, only ever reflects
    previously-fetched metas) and ``hub/meta_totals``."""
    total = 0
    for resolved in set(_THUMB_PATHS.values()):
        if not resolved:
            continue
        key_size = _stat_cache_key(resolved)
        if key_size is None:
            continue
        meta = _META_CACHE.get(key_size[0])
        if meta:
            total += meta["vram_bytes"]
    return total


def _stamp_for(doc):
    """Cheap, comparable fingerprint of ``doc``'s asset-relevant state —
    shared by ``hub/state_stamp`` and every mutation op. ``GetDirty``
    support on ``BaseDocument`` is unverified live (per the task's own
    note) so it is wrapped defensively, falling back to ``GetChanged()``.
    Texture-path changes only bump per-material dirty flags (not
    document-level dirty), so ``mat_dirty`` is included in the stamp so
    repaths/undo trigger auto-refresh.

    Mutation ops call this *after* their own ``c4d.EventAdd()`` and hand
    the fresh stamp back in the response. This is the stateless-HTTP
    equivalent of the native ``AssetHubDialog``'s ``_suppress_ticks``
    idiom (dialogs.py ~2130): the native dialog arms a short window to
    swallow the EVMSG_CHANGE its own SetActiveMaterial/SetActiveObject
    broadcasts, so a self-inflicted change never triggers its own
    rescan. There is no persistent dialog state here to arm a window on,
    so instead the SPA re-anchors its polling baseline from the stamp
    returned in the mutation's own response — its own edit never reads
    back as an external scene change.
    """
    try:
        dirty = doc.GetDirty(c4d.DIRTYFLAGS_DATA | c4d.DIRTYFLAGS_CHILDREN)
        mat_dirty = sum(m.GetDirty(c4d.DIRTYFLAGS_DATA) for m in doc.GetMaterials())
    except Exception:
        dirty = int(bool(doc.GetChanged()))
        mat_dirty = 0

    return "%s|%s|%s|%s|%s" % (
        doc.GetDocumentPath() or "",
        doc.GetDocumentName() or "",
        dirty,
        len(doc.GetMaterials()),
        mat_dirty,
    )


def _op_hub_state_stamp(payload):
    """``hub/state_stamp`` — a cheap, comparable fingerprint of the active
    document's asset-relevant state, so the SPA can poll and only re-fetch
    ``hub/inventory`` when something actually changed.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    return {"stamp": _stamp_for(doc)}


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
    _remember_thumb_paths(records)
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
    return {"ok": True, "applied": applied, "errors": errors, "stamp": _stamp_for(doc)}


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
    _remember_thumb_paths(records)
    rec = next((r for r in records if r.get("key") == key), None)
    if rec is None:
        return {"ok": False, "error": "unknown key"}
    tex_idx = rec.get("tex_idx")
    if tex_idx is None:
        return {"ok": True, "stamp": _stamp_for(doc)}
    try:
        host = tex_records[tex_idx].get("host")
    except IndexError:
        host = None
    if host is None:
        return {"ok": True, "stamp": _stamp_for(doc)}
    if isinstance(host, c4d.BaseMaterial):
        doc.SetActiveMaterial(host)
    else:
        doc.SetActiveObject(host)
    c4d.EventAdd()
    return {"ok": True, "stamp": _stamp_for(doc)}


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


_SHRINK_TARGETS = (4096, 2048, 1024)

# Bitmap saver IDs by extension, for the Hub Shrink job (fase 5.2). Everything
# not listed here is a per-row "unsupported format" error, never a silent
# degradation (exr/hdr/psd/webp are not roundtrippable through BaseBitmap's
# 8bpc saver path). ``.tga`` -> ``c4d.FILTER_TGA`` is a documented Cinema 4D
# save-format constant (BaseBitmap::Save) alongside PNG/JPG/TIF/BMP, so it
# stays in the allowlist.
_SAVER_BY_EXT = {
    ".png": c4d.FILTER_PNG,
    ".jpg": c4d.FILTER_JPG,
    ".jpeg": c4d.FILTER_JPG,
    ".tif": c4d.FILTER_TIF,
    ".tiff": c4d.FILTER_TIF,
    ".bmp": c4d.FILTER_BMP,
    ".tga": c4d.FILTER_TGA,
}


def _validate_shrink_payload(payload):
    """Pure: ``hub/shrink_start`` payload validation, split out so it's
    testable without a fake document (``target_px`` is the only thing worth
    validating before touching the scene — ``keys`` emptiness is naturally
    handled by ``shrink_plan`` returning nothing to shrink)."""
    target_px = payload.get("target_px")
    if target_px not in _SHRINK_TARGETS:
        return "invalid_target"
    return None


def _save_shrunk_copy(item, target_px):
    """Save a shrunk sibling copy of ``item`` (a ``shrink_plan`` entry) at
    ``target_px``. Returns ``(True, target_path)`` on success, ``(False,
    error_string)`` otherwise. Never raises — every failure mode (missing
    file, unsupported extension, unreadable/unsavable bitmap) is reported
    back to the caller as a per-row error string, matching the ``hub/thumb``
    error-string convention."""
    resolved = item.get("resolved_path")
    if not resolved:
        return False, "no resolved path"
    ext = os.path.splitext(resolved)[1].lower()
    saver = _SAVER_BY_EXT.get(ext)
    if saver is None:
        return False, "unsupported format"
    target = assets_engine.shrink_target_name(resolved, target_px)
    try:
        bmp = c4d.bitmaps.BaseBitmap()
        if bmp.InitWith(resolved)[0] != c4d.IMAGERESULT_OK:
            return False, "unreadable"
        dst = c4d.bitmaps.BaseBitmap()
        dst.Init(item["new_width"], item["new_height"])
        bmp.ScaleIt(dst, 256, True, False)
        if not dst.Save(target, saver):
            return False, "save_failed"
    except Exception as exc:
        return False, "shrink error: %s" % exc
    return True, target


def _settle_relink_results(planned, write_results):
    """Pure: filters ``planned`` (a list of dicts each with a ``"key"``,
    already narrowed to items that resolved to a relink target) down to
    only the ones whose writer actually succeeded, per ``write_results``
    (``{key: bool}``, one entry per targeted key from the
    ``StartUndo``/``EndUndo`` relink loop — ``True`` only when every
    ``tex_idx`` for that key wrote successfully). A ``False`` return (or a
    missing entry, treated the same as failed) is excluded from the
    returned list and reported as a ``{"key", "error": "writer failed"}``
    row instead — mirrors ``_op_hub_apply_repath``'s own ``row_ok``
    bookkeeping, so a batch shrink/copy job never reports success for a
    file the scene still points at full-size/out-of-project.
    """
    succeeded = []
    errors = []
    for item in planned:
        if write_results.get(item.get("key")):
            succeeded.append(item)
        else:
            errors.append({"key": item.get("key"), "error": "writer failed"})
    return succeeded, errors


def _op_hub_shrink_start(payload):
    """``hub/shrink_start`` — plan + queue a batch texture shrink as a
    background job (``webbridge.JOBS``, same single-slot registry as
    collect). Doc-guard-first, then ``_validate_shrink_payload`` (a bad
    ``target_px`` never touches the scene). Plans only over the requested
    ``keys`` (a fresh ``scan_scene_assets`` filtered down, plus ``_meta_for``
    only for those keys — the SPA already knows which rows it selected, so
    the response's ``skipped`` list stays scoped to that selection instead
    of every unrelated asset in the scene). ``nothing_to_shrink`` when the
    plan's shrink list comes back empty (all selected rows ineligible).
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    error = _validate_shrink_payload(payload)
    if error:
        return {"ok": False, "error": error}
    target_px = payload.get("target_px")
    keys = payload.get("keys") or []
    keys_set = set(keys)

    from sentinel.ui.flows import scan_scene_assets

    records, _tex_records, _skipped = scan_scene_assets(doc)
    _remember_thumb_paths(records)
    selected_records = [r for r in records if r.get("key") in keys_set]

    metas = {}
    for key in keys:
        resolved = _THUMB_PATHS.get(key)
        if not resolved:
            continue
        meta = _meta_for(resolved)
        if meta is not None:
            metas[key] = meta

    plan = assets_engine.shrink_plan(selected_records, metas, target_px)
    if not plan["shrink"]:
        return {"ok": False, "error": "nothing_to_shrink"}

    try:
        job_id = webbridge.JOBS.start({"kind": "shrink", "plan": plan, "target_px": target_px})
    except RuntimeError:
        return {"ok": False, "error": "job_running"}
    return {"ok": True, "job_id": job_id}


def _run_shrink_for_job(job_id, spec):
    """Runs a queued ``hub/shrink_start`` job: phase 1 saves a shrunk
    sibling copy per eligible file (progress published to ``JOBS`` per
    file); phase 2 relinks every successfully-saved copy in ONE
    ``StartUndo``/``EndUndo`` bracket (finally-protected, same convention as
    ``_op_hub_apply_repath``) so a single Cmd+Z reverts the whole batch.
    Originals are never touched or overwritten by the relink — only the
    shader path changes. Never raises: any unexpected failure is reported
    via ``JOBS.fail`` rather than leaving the job stuck in "running"."""
    try:
        plan = spec.get("plan") or {}
        target_px = spec.get("target_px")
        shrink_items = plan.get("shrink") or []
        total = len(shrink_items)
        errors = []
        shrunk = []

        for i, item in enumerate(shrink_items, start=1):
            basename = os.path.basename(item.get("resolved_path") or item.get("path") or "")
            pct = int(round((i - 1) * 80.0 / total)) if total else 0
            webbridge.JOBS.update(job_id, "shrink", "%s %d/%d" % (basename, i, total), pct)
            ok, result = _save_shrunk_copy(item, target_px)
            if ok:
                shrunk.append({"key": item.get("key"), "target_path": result,
                               "resolved_path": item.get("resolved_path")})
            else:
                errors.append({"key": item.get("key"), "error": result})

        bytes_saved = 0
        if shrunk:
            webbridge.JOBS.update(job_id, "relink", "Relinking %d file(s)" % len(shrunk), 85)
            doc = documents.GetActiveDocument()
            if doc is None:
                errors.extend({"key": s["key"], "error": "no_document"} for s in shrunk)
                shrunk = []
            else:
                from sentinel.ui.flows import scan_scene_assets
                from sentinel.textures import apply_texture_path_change

                records, tex_records, _skipped = scan_scene_assets(doc)
                stored_paths = {r.get("key"): r.get("path") for r in records}
                changes = [
                    {"key": s["key"],
                     "new_path": assets_engine.replace_basename_preserving_form(
                         stored_paths.get(s["key"]), os.path.basename(s["target_path"]))}
                    for s in shrunk
                ]
                targets, resolve_errors = webbridge.resolve_repath_targets(records, changes)
                errors.extend(resolve_errors)
                write_results = {}
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
                        write_results[target["key"]] = row_ok
                finally:
                    doc.EndUndo()
                c4d.EventAdd()

                targeted_keys = {t["key"] for t in targets}
                planned = [s for s in shrunk if s["key"] in targeted_keys]
                shrunk, writer_errors = _settle_relink_results(planned, write_results)
                errors.extend(writer_errors)

                for s in shrunk:
                    try:
                        bytes_saved += max(0, os.path.getsize(s["resolved_path"])
                                          - os.path.getsize(s["target_path"]))
                    except OSError:
                        pass

        webbridge.JOBS.finish(job_id, {
            "shrunk": shrunk,
            "skipped": plan.get("skipped") or [],
            "errors": errors,
            "bytes_saved": bytes_saved,
        })
    except Exception as exc:
        webbridge.JOBS.fail(job_id, exc)


def _op_hub_copy_into_project(payload):
    """``hub/copy_into_project`` — synchronous mutation (no job — a handful
    of ``shutil.copy2`` calls doesn't need progress polling). Doc guard,
    then ``unsaved_document`` (no ``doc_dir`` to copy into). Fresh scan ->
    ``assets_engine.copy_plan`` filtered to the requested ``keys``. Same-size
    collision at the target path is treated as "already copied" (``reused``,
    relink only, never re-copied); a different-size collision is a per-row
    error and the existing file on disk is never overwritten. Every
    successful copy/reuse is relinked in ONE ``StartUndo``/``EndUndo``
    bracket (finally-protected), matching ``_op_hub_apply_repath``/
    ``_run_shrink_for_job``.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    doc_dir = doc.GetDocumentPath() or ""
    if not doc_dir:
        return {"ok": False, "error": "unsaved_document"}
    keys_set = set(payload.get("keys") or [])

    from sentinel.ui.flows import scan_scene_assets
    from sentinel.textures import apply_texture_path_change

    records, tex_records, _skipped = scan_scene_assets(doc)
    _remember_thumb_paths(records)
    plan = assets_engine.copy_plan(records, doc_dir)
    copy_items = [item for item in plan["copy"] if item["key"] in keys_set]

    copied = 0
    reused = 0
    errors = []
    pending = []  # staged items (file already on disk at target), awaiting relink
    tex_dir = os.path.join(doc_dir, "tex")
    for item in copy_items:
        target = item["target_path"]
        resolved = item["resolved_path"]
        if os.path.exists(target):
            try:
                same_size = os.path.getsize(target) == os.path.getsize(resolved)
            except OSError:
                same_size = False
            if not same_size:
                errors.append({"key": item["key"], "error": "collision"})
                continue
            kind = "reused"
        else:
            try:
                os.makedirs(tex_dir, exist_ok=True)
                shutil.copy2(resolved, target)
            except OSError as exc:
                errors.append({"key": item["key"], "error": "copy failed: %s" % exc})
                continue
            kind = "copied"
        pending.append({"key": item["key"], "target_path": target, "kind": kind})

    if pending:
        changes = [{"key": p["key"],
                    "new_path": "tex/" + os.path.basename(p["target_path"])}
                   for p in pending]
        targets, resolve_errors = webbridge.resolve_repath_targets(records, changes)
        errors.extend(resolve_errors)
        write_results = {}
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
                write_results[target["key"]] = row_ok
        finally:
            doc.EndUndo()
        c4d.EventAdd()

        targeted_keys = {t["key"] for t in targets}
        planned = [p for p in pending if p["key"] in targeted_keys]
        settled, writer_errors = _settle_relink_results(planned, write_results)
        errors.extend(writer_errors)
        # copied/reused only counted for items whose relink actually
        # succeeded — a failed writer must never inflate the tally for a
        # file the scene still points at the old (out-of-project) path.
        for s in settled:
            if s["kind"] == "reused":
                reused += 1
            else:
                copied += 1

    return {"ok": True, "copied": copied, "reused": reused, "errors": errors,
            "stamp": _stamp_for(doc)}


_THUMB_SIZE = 64


def _thumb_cache_dir():
    prefs = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
    cache_dir = os.path.join(prefs, "sentinel_thumbs")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _op_hub_thumb(payload):
    """``hub/thumb`` — lazy per-asset PNG thumbnail, disk-cached by
    (resolved_path, mtime) via ``webbridge.thumb_cache_name`` so repeat
    requests for an unchanged file are a stat + return, not a re-decode.

    Live-verified (2026-07-20): re-scanning the scene on EVERY ``/thumb``
    request (one per visible row) queued dozens of full texture scans on
    the main thread while scrolling — scroll jank, late thumbs, and the
    2s state-stamp poll starved behind them. Looks up ``_THUMB_PATHS``
    (kept fresh by every op that already runs a full scan) first; only
    falls back to a scan if the key is missing (page opened before any
    inventory fetch populated the memo — rare).
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    key = payload.get("key") or ""

    if key in _THUMB_PATHS:
        resolved = _THUMB_PATHS[key]
    else:
        from sentinel.ui.flows import scan_scene_assets

        records, _tex, _skipped = scan_scene_assets(doc)
        _remember_thumb_paths(records)
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


def _op_hub_match_folder(payload):
    """``hub/match_folder`` — Search Folder for Missing, server-side.
    Mirrors ``AssetHubDialog._search_folder_for_missing`` (dialogs.py
    ~2231) exactly: fresh ``scan_scene_assets`` -> ``assets_engine.
    build_file_index(root)`` -> ``assets_engine.match_missing_in_folder``.
    Ambiguous matches (2+ candidates for the same basename) are never
    auto-picked — only unambiguous single-candidate matches are returned
    in ``matches``; ``ambiguous`` is just a count for the SPA to toast, same
    as the native dialog's summary message.
    """
    root = (payload.get("root") or "").strip()
    if not root:
        return {"ok": False, "error": "no_root"}
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.ui.flows import scan_scene_assets

    records, _tex_records, _skipped = scan_scene_assets(doc)
    _remember_thumb_paths(records)
    index, truncated = assets_engine.build_file_index(root)
    raw_matches = assets_engine.match_missing_in_folder(records, index)

    by_key = {rec["key"]: rec for rec in records}
    matches = []
    ambiguous = 0
    for key, match in raw_matches.items():
        rec = by_key.get(key)
        if rec is None or not rec.get("repathable"):
            continue
        if "match" in match:
            matches.append({"key": key, "match": match["match"]})
        else:
            ambiguous += 1
    return {"ok": True, "matches": matches, "ambiguous": ambiguous, "truncated": truncated}


def _op_hub_make_relative(payload):
    """``hub/make_relative`` — Make All Relative, server-side (read-only:
    stages changes, does not write). Mirrors ``AssetHubDialog.
    _make_all_relative`` (dialogs.py ~2191) exactly, including the
    ``file://`` scheme strip before ``compute_relative_texture_path`` — the
    rule (``os.path.relpath`` + cross-drive/climb-depth rejection) is not
    trivially reproducible in the browser, so it stays server-side rather
    than being re-derived in TypeScript.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    doc_path = doc.GetDocumentPath() or ""
    if not doc_path:
        return {"ok": False, "error": "unsaved_document"}

    from sentinel.textures import compute_relative_texture_path
    from sentinel.ui.flows import scan_scene_assets

    records, _tex_records, _skipped = scan_scene_assets(doc)
    _remember_thumb_paths(records)
    changes = []
    skipped_cross_drive = 0
    for rec in records:
        if not rec.get("repathable") or rec.get("status") != "absolute":
            continue
        cur = rec["path"]
        if cur.startswith("file://"):
            abs_part = cur[len("file://"):]
            if abs_part.startswith("/") and len(abs_part) > 3 and abs_part[2] == ":":
                abs_part = abs_part.lstrip("/")
        else:
            abs_part = cur
        rel = compute_relative_texture_path(abs_part, doc_path)
        if rel is None:
            skipped_cross_drive += 1
            continue
        changes.append({"key": rec["key"], "new_path": rel})
    return {"ok": True, "changes": changes, "skipped_cross_drive": skipped_cross_drive}


def _count_new_fails(score, rules_context):
    """New FAIL-severity violation count for the ``hub/collect_start`` gate
    contract. Thin delegate to ``sentinel.gate.count_new_fails``, which
    mirrors ``gate.classify_gate``/``gate.evaluate_gate``'s
    ``entry_severity(entry, rules_context) == "FAIL"`` accessor exactly —
    the same accessor the native modal quality gate
    (``ui.flows._run_quality_gate`` / ``_compute_gate_snapshot``) uses to
    bucket a check as blocking. Kept as a named function here (rather than
    calling ``quality_gate.count_new_fails`` inline) per this op's own
    checkpoint contract.
    """
    return quality_gate.count_new_fails(score, rules_context)


def _build_preflight_payload_for_collect(doc, rules_context, score, baseline_path,
                                          gate_evaluated=False, gate_ack=False):
    """Assemble the ``preflight_payload`` dict ``run_collect_pipeline``
    expects — the same 7 keys ``AssetHubDialog._build_collect_preflight_payload``
    (dialogs.py) builds: ``issues, preflight_score, rules_context,
    gate_overrides, gate_evaluated, baseline_path, baseline_entries``.

    ``issues`` comes from the shared ``quality_gate.build_preflight_issues``
    helper (extracted from the native dialog's own copy of this loop, see
    ``gate.py``) so both call sites stay byte-identical.

    Deliberate difference from the native dialog: this never opens the
    modal ``GateTriageDialog`` (``ui.flows._run_quality_gate``) — that
    dialog is synchronous/blocking and has no place inside an HTTP request
    handler. Instead, ``_op_hub_collect_start`` enforces the gate itself
    via ``_count_new_fails`` before this function is even called; the SPA
    resolves any FAIL violations beforehand through the existing
    ``form/gate`` ops (fase 4) and retries with ``gate_ack=True``. Because
    there is no synchronous per-delivery override-capture step here (no
    triage dialog runs), ``gate_overrides`` is always empty — any
    acceptance the artist made via ``form/gate`` already lives in the
    baseline sidecar by the time this runs, so ``baseline_entries`` picks
    it up naturally. ``gate_ack`` is accepted for signature symmetry with
    the caller but has no payload key of its own — ``run_collect_pipeline``
    only reads the 7 keys returned below.
    """
    from sentinel import baseline

    baseline_entries = []
    if baseline_path:
        entries, status = baseline.load_baseline(baseline_path)
        if status == baseline.STATUS_OK:
            baseline_entries = entries

    return {
        "issues": quality_gate.build_preflight_issues(score),
        "preflight_score": score,
        "rules_context": rules_context,
        "gate_overrides": [],
        "gate_evaluated": gate_evaluated,
        "baseline_path": baseline_path,
        "baseline_entries": baseline_entries,
    }


def _op_hub_collect_start(payload):
    """``hub/collect_start`` — kick off a Scene Collector run as a
    background job (``webbridge.JOBS``). Payload: ``target_dir``, ``zip``
    (bool), ``gate_ack`` (bool). Runs the same pre-flight QC snapshot
    ``hub/preflight`` does, then enforces the FAIL-severity gate
    (``gates_enabled`` + ``_count_new_fails`` > 0) unless ``gate_ack`` is
    exactly ``True`` — mirroring the fase-4 ``form/gate`` contract
    (``requires_confirm``/``confirm_required``): the gate is enforced
    server-side, not just hidden in the SPA. On success the job is queued;
    ``pump_jobs()`` (called from the host dialog's ``Timer`` after the
    ``MainThreadQueue`` drain) actually runs the collect synchronously.
    """
    target_dir = (payload.get("target_dir") or "").strip()
    if not target_dir:
        return {"ok": False, "error": "no_target"}
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    if not doc.GetDocumentPath():
        return {"ok": False, "error": "unsaved_document"}

    from sentinel.ui.flows import _baseline_path_for_doc, _current_module

    rules_context = active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    score = compute_score(registry_results, rules_context,
                          baseline_path=baseline_path,
                          current_params=rules_context.params)

    gates_enabled = bool(rules_context.params.get("gates_enabled"))
    if gates_enabled and _count_new_fails(score, rules_context) > 0 \
            and payload.get("gate_ack") is not True:
        return {"ok": False, "error": "gate_blocked"}

    preflight_payload = _build_preflight_payload_for_collect(
        doc, rules_context, score, baseline_path,
        gate_evaluated=gates_enabled, gate_ack=bool(payload.get("gate_ack")))
    try:
        job_id = webbridge.JOBS.start({
            "target_dir": target_dir,
            "zip": bool(payload.get("zip")),
            "preflight_payload": preflight_payload,
        })
    except RuntimeError:
        return {"ok": False, "error": "job_running"}
    return {"ok": True, "job_id": job_id}


def _run_collect_for_job(spec, on_status):
    """Isolated for testability (``pump_jobs`` failure-path test
    monkeypatches this). Re-reads the active document (HTTP/job dispatch is
    stateless, same convention as every other hub op)."""
    doc = documents.GetActiveDocument()
    if not doc:
        raise RuntimeError("no_document")
    from sentinel.ui.flows import run_collect_pipeline
    return run_collect_pipeline(
        doc, GlobalSettings.load_artist_name(), spec["target_dir"],
        make_zip=spec.get("zip", False),
        preflight_payload=spec.get("preflight_payload"),
        on_status=on_status)


def pump_jobs():
    """Called from host dialog Timers after the queue drain. Runs at most
    one pending job synchronously on the main thread; progress is
    published to ``JOBS`` (read from the HTTP server thread, so polling
    stays live even while this call blocks the main thread). Note per
    Task 1's review finding: ``JOBS.take_pending()`` returns the spec dict
    BY REFERENCE — this function only reads it, never mutates it in
    place.

    Kind-dispatch (fase 5.2): ``spec["kind"]`` selects the runner —
    ``"shrink"`` -> ``_run_shrink_for_job`` (self-contained: it publishes
    its own ``JOBS.update``/``finish``/``fail`` calls). Absent ``kind``
    defaults to ``"collect"`` — every job queued before this task (and
    every ``hub/collect_start`` spec since) has no ``kind`` key, so this
    keeps the pre-existing collect path byte-identical.
    """
    taken = webbridge.JOBS.take_pending()
    if taken is None:
        return None
    job_id, spec = taken

    if spec.get("kind", "collect") == "shrink":
        _run_shrink_for_job(job_id, spec)
        return job_id

    def on_status(message):
        phase, pct = webbridge.collect_phase_pct(message)
        webbridge.JOBS.update(job_id, phase, detail=message, pct=pct)

    try:
        result = _run_collect_for_job(spec, on_status)
        if not result:
            webbridge.JOBS.fail(job_id, "collect failed (SaveProject)")
            return job_id
        report = webbridge.delivery_report_payload(
            result.get("manifest") or {}, result.get("manifest_path") or "")
        webbridge.JOBS.finish(job_id, {
            "target_dir": result.get("target_dir"),
            "delivery_filename": result.get("delivery_filename"),
            "assets_collected": result.get("assets_collected"),
            "assets_missing": result.get("assets_missing"),
            "zip": result.get("zip"),
            "zip_error": result.get("zip_error"),
            "pending_todos": result.get("pending_todos"),
            "report": report,
        })
    except Exception as exc:
        webbridge.JOBS.fail(job_id, exc)
    return job_id


def _op_hub_meta(payload):
    """``hub/meta`` — batched header metadata for a list of asset keys.
    Doc-guard-first like every sibling op, then the batch cap (the SPA
    batches visible rows, never the world — a request past the cap is a
    client bug, not a scene with a lot of textures). Keys already resolved
    in ``_THUMB_PATHS`` (populated by ``hub/inventory``/other scans) are
    served for free; an unknown key triggers one fresh
    ``scan_scene_assets`` (same fallback policy as ``hub/thumb``), not one
    scan per unknown key. Keys with no resolvable path or an unparseable
    file are simply absent from the response — never an error per-key.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    keys = payload.get("keys") or []
    if len(keys) > _META_BATCH_CAP:
        return {"error": "too_many_keys"}

    if any(key not in _THUMB_PATHS for key in keys):
        from sentinel.ui.flows import scan_scene_assets

        records, _tex, _skipped = scan_scene_assets(doc)
        _remember_thumb_paths(records)

    metas = {}
    for key in keys:
        resolved = _THUMB_PATHS.get(key)
        if not resolved:
            continue
        meta = _meta_for(resolved)
        if meta is not None:
            metas[key] = meta
    return {"metas": metas}


def _totals_from_cache(paths):
    """Pure: VRAM/disk rollup over a collection of resolved paths that
    already have a cache entry. ``total`` counts only paths whose
    extension is a thumbnailable image type (``webbridge._THUMB_EXTS``) —
    non-image assets (.abc, .vdb, ...) never get a parsed meta entry, so
    counting them in ``total`` would keep ``covered < total`` forever and
    the SPA's ``~`` partial marker would never clear. ``covered`` counts
    how many of those image paths have a successfully-parsed cache entry.
    """
    vram_total = 0
    disk_total = 0
    covered = 0
    total = 0
    for resolved in set(paths):
        if not resolved:
            continue
        ext = os.path.splitext(resolved)[1].lower()
        if ext not in webbridge._THUMB_EXTS:
            continue
        key_size = _stat_cache_key(resolved)
        if key_size is None:
            continue
        total += 1
        meta = _META_CACHE.get(key_size[0])
        if not meta:
            continue
        covered += 1
        vram_total += meta["vram_bytes"]
        disk_total += meta.get("disk_bytes", 0)

    return {
        "vram_bytes": vram_total,
        "vram_label": assets_engine.format_size(vram_total),
        "disk_bytes": disk_total,
        "disk_label": assets_engine.format_size(disk_total),
        "covered": covered,
        "total": total,
    }


def _op_hub_meta_totals(payload):
    """``hub/meta_totals`` — VRAM/disk rollup over unique resolved paths
    that already have a cache entry (never triggers a parse itself; the
    SPA fetches ``hub/meta`` in chunks first, so by the time this fires
    the cache is warm). ``total`` counts unique image files that exist on
    disk (non-image assets like .abc/.vdb never get a thumb, so they're
    excluded — see ``_totals_from_cache``); ``covered`` counts how many of
    those have a successfully-parsed cache entry — the SPA prefixes the
    VRAM figure with ``~`` while ``covered < total``.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    return _totals_from_cache(_THUMB_PATHS.values())


def _op_hub_variants(payload):
    """``hub/variants`` — batched read-only resolution-sibling detection for
    a list of asset keys (fase 5.3). Doc-guard-first + the same batch cap
    convention as ``hub/meta`` (a request past the cap is a client bug, not
    a scene with a lot of textures). Keys already resolved in
    ``_THUMB_PATHS`` (populated by ``hub/inventory``/other scans) are
    served for free; an unknown key triggers one fresh
    ``scan_scene_assets`` fallback scan (same policy as ``hub/thumb``/
    ``hub/meta``), never one scan per unknown key. Builds the minimal
    ``[{"key","resolved_path"}]`` shape ``assets_engine.find_res_variants``
    needs, then reshapes its ``{key: [{"path","px"}]}`` result into
    ``{key: [{"basename","px"}]}`` for the SPA — the client only ever
    needs the sibling's filename (to build the relink), never the
    absolute path. Only keys with a detected group (>=2 variants) appear
    in the response, same "absent means nothing to report" convention as
    ``hub/meta``. A "bare base" sibling (the un-tokened original a Shrink
    copy was derived from) comes back from ``find_res_variants`` with
    ``"px": None`` — enriched here via ``_meta_for`` (real pixel
    ``max(width, height)``) when the file parses as an image; left
    ``None`` if it still can't be read.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    keys = payload.get("keys") or []
    if len(keys) > _META_BATCH_CAP:
        return {"error": "too_many_keys"}

    if any(key not in _THUMB_PATHS for key in keys):
        from sentinel.ui.flows import scan_scene_assets

        records, _tex, _skipped = scan_scene_assets(doc)
        _remember_thumb_paths(records)

    minimal_records = []
    for key in keys:
        resolved = _THUMB_PATHS.get(key)
        if not resolved:
            continue
        minimal_records.append({"key": key, "resolved_path": resolved})

    raw_variants = assets_engine.find_res_variants(minimal_records)
    variants = {}
    for key, group in raw_variants.items():
        entries = []
        for v in group:
            px = v["px"]
            if px is None:
                meta = _meta_for(v["path"])
                if meta:
                    px = max(meta.get("width") or 0, meta.get("height") or 0) or None
            entries.append({"basename": os.path.basename(v["path"]), "px": px})
        variants[key] = entries
    return {"variants": variants}


def _validate_switch_target(target):
    """Pure: ``hub/switch_res`` ``target`` validation, split out so it's
    testable without a fake document (same convention as
    ``_validate_shrink_payload``). Valid: the literal string ``"highest"``,
    or a positive ``int``. ``bool`` is rejected explicitly — Python's
    ``bool`` is an ``int`` subclass, so ``True``/``False`` would otherwise
    silently pass the ``isinstance(target, int) and target > 0`` check
    (``True == 1``)."""
    if target == "highest":
        return None
    if isinstance(target, bool):
        return "invalid_target"
    if isinstance(target, int) and target > 0:
        return None
    return "invalid_target"


def _op_hub_switch_res(payload):
    """``hub/switch_res`` — synchronous relink-only mutation (fase 5.3):
    switch every requested key to its ``"highest"``-px sibling or an exact
    ``target`` px, staying within the same on-disk variant family
    ``hub/variants`` already reported. NO file writes — this only ever
    rewrites shader paths, mirroring ``_op_hub_apply_repath``'s single
    ``StartUndo``/``EndUndo`` bracket + ``_settle_relink_results`` writer
    bookkeeping (a failed writer must never report ``switched`` for a key
    the scene still points at the old path).

    Doc guard -> batch cap (same ``hub/meta`` pattern) -> ``_validate_
    switch_target`` (a bad target never touches the scene) -> a *fresh*
    scan (HTTP is stateless — same convention as every mutation op) so
    ``find_res_variants`` sees the current on-disk state, restricted to the
    requested keys. Per key: no detected group -> skip ``no_variant``;
    ``"highest"`` picks ``group[0]`` (``find_res_variants`` already sorts
    px desc); an exact ``target`` px with no matching sibling -> skip
    ``no_variant``; a pick whose basename case-folds to the record's
    current resolved basename -> skip ``already_there`` (covers the
    ``"highest"`` case where the current file already IS the highest px).
    Otherwise the change is staged via ``replace_basename_preserving_form``
    on the record's *stored* ``path`` (not the resolved absolute path) so a
    ``relative:///`` texture stays relative after the switch — same
    lesson as the 5.2 shrink job.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    keys = payload.get("keys") or []
    if len(keys) > _META_BATCH_CAP:
        return {"ok": False, "error": "too_many_keys"}
    target = payload.get("target")
    error = _validate_switch_target(target)
    if error:
        return {"ok": False, "error": error}

    from sentinel.ui.flows import scan_scene_assets
    from sentinel.textures import apply_texture_path_change

    records, tex_records, _skipped = scan_scene_assets(doc)
    _remember_thumb_paths(records)

    keys_set = set(keys)
    by_key = {r.get("key"): r for r in records}
    requested_records = [r for r in records if r.get("key") in keys_set]
    variants = assets_engine.find_res_variants(requested_records)

    skipped = []
    changes = []
    for key in keys:
        rec = by_key.get(key)
        group = variants.get(key) if rec is not None else None
        if not group:
            skipped.append({"key": key, "reason": "no_variant"})
            continue
        if target == "highest":
            # A "bare base" sibling (Shrink's un-tokened original) comes
            # back from find_res_variants with px=None — its real pixel
            # size (if the file parses as an image) can still be the
            # highest in the family, so it must not be excluded from
            # "highest" just because its name carries no token. None
            # that still can't be resolved is treated as the lowest.
            def _px_for(v):
                if v["px"] is not None:
                    return v["px"]
                meta = _meta_for(v["path"])
                if meta:
                    return max(meta.get("width") or 0, meta.get("height") or 0)
                return -1

            pick = max(group, key=_px_for)
        else:
            pick = next((v for v in group if v["px"] == target), None)
        if pick is None:
            skipped.append({"key": key, "reason": "no_variant"})
            continue
        pick_basename = os.path.basename(pick["path"])
        current_basename = os.path.basename(rec.get("resolved_path") or "")
        if pick_basename.lower() == current_basename.lower():
            skipped.append({"key": key, "reason": "already_there"})
            continue
        new_path = assets_engine.replace_basename_preserving_form(
            rec.get("path"), pick_basename)
        changes.append({"key": key, "new_path": new_path})

    targets, resolve_errors = webbridge.resolve_repath_targets(records, changes)
    errors = list(resolve_errors)
    write_results = {}
    doc.StartUndo()
    try:
        for t in targets:
            row_ok = True
            for tex_idx in t["tex_idxs"]:
                try:
                    live = tex_records[tex_idx]
                except IndexError:
                    row_ok = False
                    continue
                if not apply_texture_path_change(live, t["new_path"], doc=doc):
                    row_ok = False
            write_results[t["key"]] = row_ok
    finally:
        doc.EndUndo()
    c4d.EventAdd()

    planned = [{"key": t["key"]} for t in targets]
    succeeded, writer_errors = _settle_relink_results(planned, write_results)
    errors.extend(writer_errors)
    switched = [s["key"] for s in succeeded]

    return {"ok": True, "switched": switched, "skipped": skipped, "errors": errors,
            "stamp": _stamp_for(doc)}


def _op_hub_ui_state(payload):
    """``hub/ui_state`` — read-only. Not scene-dependent (column widths /
    sort are a machine-level UI preference, same tier as
    ``GlobalSettings.get_asset_hub_col_widths``), so no doc guard."""
    return {"state": GlobalSettings.get("hub_spa_ui", {})}


def _op_hub_ui_state_save(payload):
    """``hub/ui_state/save`` — mutation. Stores ``state`` verbatim under
    the ``hub_spa_ui`` settings key; the only validation is "is it a
    dict" — shape (``col_widths``/``sort``) is the SPA's contract with
    itself, not this op's to enforce."""
    state = payload.get("state")
    if not isinstance(state, dict):
        return {"ok": False, "error": "invalid state"}
    GlobalSettings.set("hub_spa_ui", state)
    return {"ok": True}


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
    "hub/match_folder": _op_hub_match_folder,
    "hub/make_relative": _op_hub_make_relative,
    "hub/collect_start": _op_hub_collect_start,
    "hub/shrink_start": _op_hub_shrink_start,
    "hub/copy_into_project": _op_hub_copy_into_project,
    "hub/meta": _op_hub_meta,
    "hub/meta_totals": _op_hub_meta_totals,
    "hub/variants": _op_hub_variants,
    "hub/switch_res": _op_hub_switch_res,
    "hub/ui_state": _op_hub_ui_state,
    "hub/ui_state/save": _op_hub_ui_state_save,
}
