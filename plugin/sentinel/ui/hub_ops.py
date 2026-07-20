# -*- coding: utf-8 -*-
"""Asset Hub SPA ops (fase 5) — read-only ops (inventory, state_stamp,
presets, preflight). Thin c4d adapters over the same engines the native
``AssetHubDialog`` uses — zero duplicated logic. Sibling of
``ui/reports_dialog.py`` / ``ui/web_ops.py`` (same ``MainThreadQueue``
dispatch-target contract — see ``webbridge.MainThreadQueue.drain`` for the
invariant every handler must honor). Host-agnostic: no dialog imports here;
merged into ``reports_dialog._OPS`` by whichever task wires the route.

Read-only ops never mutate; every op re-reads the active document at
dispatch time (mutation/job ops for repath/collect land in Tasks 5/6).
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


HUB_OPS = {
    "hub/inventory": _op_hub_inventory,
    "hub/state_stamp": _op_hub_state_stamp,
    "hub/presets": _op_hub_presets,
    "hub/presets/save": _op_hub_presets_save,
    "hub/preflight": _op_hub_preflight,
}
