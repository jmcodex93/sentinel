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

import c4d
from c4d import documents

from sentinel import webbridge
from sentinel import assets as assets_engine
from sentinel import gate as quality_gate
from sentinel.common.settings import GlobalSettings
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


def _stamp_for(doc):
    """Cheap, comparable fingerprint of ``doc``'s asset-relevant state —
    shared by ``hub/state_stamp`` and every mutation op. ``GetDirty``
    support on ``BaseDocument`` is unverified live (per the task's own
    note) so it is wrapped defensively, falling back to ``GetChanged()``.

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
    except Exception:
        dirty = int(bool(doc.GetChanged()))

    return "%s|%s|%s|%s" % (
        doc.GetDocumentPath() or "",
        doc.GetDocumentName() or "",
        dirty,
        len(doc.GetMaterials()),
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
    place."""
    taken = webbridge.JOBS.take_pending()
    if taken is None:
        return None
    job_id, spec = taken

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
}
