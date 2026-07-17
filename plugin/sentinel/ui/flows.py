# -*- coding: utf-8 -*-
"""UI-orchestration flows for Sentinel (Phase 4 extraction from ui/panel.py).

These functions legitimately open dialogs and drive multi-step workflows
(smart save version, quality gate, scene collector, snapshot save). They sit
in the ui/ layer: they may import engine modules, sentinel.ui.dialogs and
sentinel.ui.user_areas, but must NOT import sentinel.ui.panel (avoids a cycle).
"""
import c4d
import os
import sys

from sentinel import baseline
from sentinel import gate as quality_gate
from sentinel import PLUGIN_NAME
from sentinel.common.cache import check_cache
from sentinel.common.constants import MAX_OBJECTS_PER_CHECK
from sentinel.common.helpers import _iter_objs, open_in_explorer, safe_print
from sentinel.checks.scene import _is_light_obj
from sentinel.fixes import apply_fixes
from sentinel.qc.registry import CHECK_REGISTRY, resolve_function
from sentinel.qc.results import material_identity, object_identity
from sentinel.qc.score import compute_score, run_all_checks
from sentinel.ui.reports import build_baseline_artifact_details
from sentinel.snapshots import (
    _convert_exr_to_png,
    _find_latest_exr,
    _get_stills_dir,
    build_slate_data,
)
from sentinel.versioning import (
    _sanitize_status,
    append_history_entry,
    build_versioned_filename,
    compute_next_version,
    get_history_path,
    parse_version_filename,
)
from sentinel.notes import get_notes_path, load_notes, summarize_notes
from sentinel.ui.dialogs import GateTriageDialog
from sentinel.ui.user_areas import _accepted_entry_payload


# ---- Rules/path helpers (private copies; panel keeps its own — no cycle) ----
from sentinel.rules_context import active_rules_for_doc as _active_rules_for_doc


def _doc_full_path(doc):
    if not doc:
        return ""
    try:
        doc_path = doc.GetDocumentPath() or ""
        doc_name = doc.GetDocumentName() or ""
    except Exception:
        return ""
    if not doc_path or not doc_name:
        return ""
    return os.path.join(doc_path, doc_name)


def _baseline_path_for_doc(doc, only_existing=False):
    path = baseline.get_baseline_path(_doc_full_path(doc))
    if only_existing and (not path or not os.path.exists(path)):
        return None
    return path



def get_scene_stats(doc):
    """Get scene complexity statistics"""
    cached = check_cache.get(doc, "stats")
    if cached is not None:
        return cached

    stats = {"objects": 0, "polygons": 0, "materials": 0, "lights": 0}

    try:
        stats["materials"] = len(doc.GetMaterials() or [])

        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                stats["objects"] += 1
                try:
                    cache = obj.GetDeformCache() or obj.GetCache()
                    target = cache if cache else obj
                    if target.IsInstanceOf(c4d.Opolygon):
                        stats["polygons"] += target.GetPolygonCount()
                except Exception:
                    pass
                if _is_light_obj(obj):
                    stats["lights"] += 1

    except Exception as e:
        safe_print(f"Error getting scene stats: {e}")

    check_cache.set(doc, "stats", stats)
    return stats



def _current_module():
    return sys.modules.get(__name__)


def _build_qc_summary(doc):
    """Run all QC checks (using cache) and return a compact summary dict."""
    rules_context = _active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    if baseline_path:
        return compute_score(
            registry_results,
            rules_context,
            baseline_path=baseline_path,
            current_params=rules_context.params,
        )
    return compute_score(registry_results, rules_context)



def _compute_gate_snapshot(doc, rules_context, doc_full_path):
    """Compute the gate verdict through the baseline-aware recovered path."""
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    path = baseline.get_baseline_path(doc_full_path)
    baseline.merge_conflict_copies(path)
    entries, status = baseline.load_baseline(path)
    gate_entries = entries if status == baseline.STATUS_OK else []
    score = compute_score(
        registry_results,
        rules_context,
        baseline_entries=gate_entries,
        current_params=getattr(rules_context, "params", {}),
    )
    gate_result = quality_gate.evaluate_gate(score, rules_context)
    return {
        "registry_results": registry_results,
        "baseline_path": path,
        "baseline_status": status,
        "score": score,
        "gate_result": gate_result,
    }



def _gate_new_violations(gate_result, check_id):
    for bucket_name in ("fixable", "blocking", "advisory"):
        for item in gate_result.get(bucket_name, []) or []:
            if item.get("check_id") == check_id:
                return list(item.get("violations") or [])
    return []


def _gate_new_counts(gate_result):
    counts = {}
    for bucket_name in ("fixable", "blocking", "advisory"):
        for item in gate_result.get(bucket_name, []) or []:
            counts[item.get("check_id")] = int(item.get("new_count") or 0)
    return counts


def _gate_fix_payload(check_id, registry_results, gate_result):
    entry = next((e for e in CHECK_REGISTRY if e.check_id == check_id), None)
    if entry is not None and entry.fix_scope == "document":
        return {"check_id": check_id, "objects": []}

    new_keys = {
        quality_gate.identity_key(violation.get("identity"))
        for violation in _gate_new_violations(gate_result, check_id)
        if isinstance(violation, dict)
    }
    result_pair = (registry_results or {}).get(check_id, {}) or {}
    legacy_objs = result_pair.get("legacy_result") or []
    identity_fn = material_identity if check_id == "unused_mats" else object_identity
    objs = quality_gate.filter_to_new(
        legacy_objs,
        new_keys,
        identity_fn,
        quality_gate.identity_key,
    )
    return {"check_id": check_id, "objects": objs}


def _run_quality_gate(doc, rules_context, artist_name, doc_full_path):
    """Run the modal quality gate. Returns a result dict or abort marker."""
    snapshot = _compute_gate_snapshot(doc, rules_context, doc_full_path)
    gate_result = snapshot["gate_result"]
    gate_overrides = []
    baseline_changed = False
    disabled_fix_ids = set()
    cap = len(gate_result.get("fixable") or [])
    fix_iterations = 0

    while not gate_result.get("passed"):
        if fix_iterations >= cap:
            disabled_fix_ids.update(
                item.get("check_id")
                for item in gate_result.get("fixable", []) or []
                if item.get("check_id")
            )

        dlg = GateTriageDialog(
            gate_result,
            sidecar_invalid=(snapshot["baseline_status"] == baseline.STATUS_INVALID),
            disabled_fix_ids=disabled_fix_ids,
        )
        try:
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=620, defaulth=420)
        except Exception as e:
            safe_print(f"GateTriageDialog open error: {e}")
            return {"proceed": False, "overrides": gate_overrides, "baseline_changed": baseline_changed}

        if not dlg.proceed:
            return {"proceed": False, "overrides": gate_overrides, "baseline_changed": baseline_changed}

        previous_counts = _gate_new_counts(gate_result)
        attempted_fix_ids = list(dlg.fixes or [])
        fixes = [
            _gate_fix_payload(check_id, snapshot["registry_results"], gate_result)
            for check_id in attempted_fix_ids
        ]
        if attempted_fix_ids:
            apply_fixes(doc, fixes)

        path = snapshot["baseline_path"]
        for check_id in dlg.baseline_accepts or []:
            for violation in _gate_new_violations(gate_result, check_id):
                acceptance = baseline.entry_from_violation(
                    violation,
                    artist_name,
                    dlg.reason or "",
                    current_params=getattr(rules_context, "params", {}),
                )
                if acceptance and baseline.add_acceptance(path, acceptance):
                    baseline_changed = True

        for check_id in dlg.overrides or []:
            gate_overrides.extend(
                quality_gate.build_override_records(
                    _gate_new_violations(gate_result, check_id),
                    artist_name,
                    dlg.reason,
                )
            )

        if baseline_changed or attempted_fix_ids:
            check_cache.clear()
            c4d.EventAdd()

        if not attempted_fix_ids:
            break

        snapshot = _compute_gate_snapshot(doc, rules_context, doc_full_path)
        gate_result = snapshot["gate_result"]
        current_counts = _gate_new_counts(gate_result)
        for check_id in attempted_fix_ids:
            if current_counts.get(check_id, 0) >= previous_counts.get(check_id, 0):
                disabled_fix_ids.add(check_id)
        fix_iterations += 1

    return {
        "proceed": True,
        "overrides": gate_overrides,
        "baseline_changed": baseline_changed,
        "baseline_path": snapshot.get("baseline_path"),
    }





def smart_save_version(doc, comment, run_qc=True, artist_name="", status=None):
    """Save the document as a numbered version + append metadata to sidecar history.

    Args:
      status: optional review-status tag (e.g. 'TR', 'CR', 'FINAL', or any custom alphanumeric)
              -> appears as suffix _<STATUS> in filename. None or '' = no suffix (WIP).

    Returns a dict:
      { 'success': bool,
        'message': str,
        'path': str (new file path on success),
        'version': int (the version number written),
        'status': str ('' if WIP),
        'history_path': str,
        'qc_summary': dict | None,
      }
    """
    from datetime import datetime

    result = {"success": False, "message": "", "path": None, "version": None,
              "status": "", "history_path": None, "qc_summary": None}

    if not doc:
        result["message"] = "No active document"
        return result

    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""

    # Sanitize status — uppercase alphanumeric only
    clean_status = _sanitize_status(status) if status else ""

    # ── Resolve target folder + base name ──
    if not doc_path:
        # First-time save: ask the user where to put the scene
        suggested_base = os.path.splitext(doc_name)[0] if doc_name else "scene"
        suggested_base, _v, _s = parse_version_filename(suggested_base)
        if not suggested_base or suggested_base.lower().startswith("untitled"):
            suggested_base = "scene"
        suggested_filename = build_versioned_filename(suggested_base, 1, status=clean_status)

        save_path = None
        try:
            save_path = c4d.storage.SaveDialog(
                title="Save Versioned Scene (will be saved as scene_vNNN.c4d)",
                force_suffix="c4d",
                def_file=suggested_filename,
            )
        except TypeError:
            save_path = c4d.storage.SaveDialog(
                title="Save Versioned Scene",
                force_suffix="c4d",
            )

        if not save_path:
            result["message"] = "Save cancelled by user"
            return result

        folder = os.path.dirname(save_path)
        chosen_name = os.path.splitext(os.path.basename(save_path))[0]
        base, _user_ver, _user_status = parse_version_filename(chosen_name)
        if not base:
            base = "scene"
        next_version = 1  # always start fresh from v001 when first saving
    else:
        folder = doc_path
        full_doc_path = os.path.join(folder, doc_name) if doc_name else folder
        base, next_version = compute_next_version(full_doc_path)
        if not base:
            base = os.path.splitext(doc_name or "scene")[0] or "scene"

    # ── Build new filename + full path ──
    new_filename = build_versioned_filename(base, next_version, status=clean_status)
    new_path = os.path.join(folder, new_filename)

    # Refuse to overwrite an existing file (defensive — should not happen)
    if os.path.exists(new_path):
        result["message"] = f"Target already exists: {new_filename} (refusing to overwrite)"
        return result

    gate_overrides = []
    rules_context = _active_rules_for_doc(doc)
    if (
        getattr(rules_context, "params", {}).get("gates_enabled", False)
        and clean_status.upper() in ("TR", "CR", "FINAL")
    ):
        gate_result = _run_quality_gate(doc, rules_context, artist_name, new_path)
        if not gate_result.get("proceed"):
            result["message"] = "Quality gate cancelled"
            return result
        gate_overrides = list(gate_result.get("overrides") or [])

    # ── Capture metadata BEFORE saving (so QC reflects pre-save state) ──
    qc_summary = _build_qc_summary(doc) if run_qc else None
    stats = get_scene_stats(doc) or {}
    active_take = ""
    try:
        td = doc.GetTakeData()
        if td:
            cur = td.GetCurrentTake()
            if cur:
                active_take = cur.GetName() or ""
    except Exception:
        pass

    # ── Save the document ──
    try:
        ok = c4d.documents.SaveDocument(
            doc,
            new_path,
            c4d.SAVEDOCUMENTFLAGS_NONE,
            c4d.FORMAT_C4DEXPORT,
        )
        if not ok:
            result["message"] = f"SaveDocument returned False (path: {new_path})"
            return result
    except Exception as e:
        result["message"] = f"Save error: {e}"
        return result

    # ── Update the active document's path/name so C4D's title bar + future
    # saves reflect the new versioned file (SaveDocument doesn't always
    # propagate this in C4D 2026). ──
    try:
        doc.SetDocumentPath(os.path.dirname(new_path))
        doc.SetDocumentName(os.path.basename(new_path))
        c4d.EventAdd()
    except Exception as e:
        safe_print(f"Could not update document path metadata: {e}")

    # ── Append history entry ──
    history_path = get_history_path(new_path)
    entry = {
        "version": next_version,
        "filename": new_filename,
        "path": new_path,
        "status": clean_status,           # NEW: review status tag
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "artist": artist_name or "",
        "comment": (comment or "").strip(),
        "active_take": active_take,
        "scene": base,
        "stats": stats,
    }
    if qc_summary:
        entry["qc_score"] = qc_summary["score"]
        entry["qc_pass"] = qc_summary["pass"]
        # qc_counts IS the per-check trajectory vector (check_id -> new-violation
        # count, baseline-aware; disabled checks omitted) — consumed by the
        # future supervisor view. Pinned by tests (test_qc_registry_score.py,
        # test_version_helpers.py).
        entry["qc_counts"] = qc_summary["counts"]
        if qc_summary.get("schema") == 2:
            entry["schema"] = 2
            entry["passed"] = qc_summary["passed"]
            entry["total"] = qc_summary["total"]
            entry["new"] = qc_summary.get("new", sum(qc_summary.get("counts", {}).values()))
            entry["accepted"] = qc_summary.get("accepted", 0)
            entry["qc_baseline"] = build_baseline_artifact_details(qc_summary)
        entry["disabled_checks"] = list(qc_summary.get("disabled", []) or [])
    if gate_overrides:
        entry["gate_overrides"] = gate_overrides

    appended = append_history_entry(history_path, entry)

    result.update({
        "success": True,
        "message": f"Saved {new_filename}" + (" (history updated)" if appended else " (history write failed)"),
        "path": new_path,
        "version": next_version,
        "status": clean_status,
        "history_path": history_path,
        "qc_summary": qc_summary,
    })
    return result



# Retired from the panel in v1.11 — superseded by AssetHubDialog +
# run_collect_pipeline. Kept one release.
def collect_scene(doc, artist_name):
    """Pre-flight QC + Save Project with Assets + Verify + Manifest"""
    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    doc_path = doc.GetDocumentPath()
    if not doc_path:
        c4d.gui.MessageDialog("Please save the scene first before collecting.")
        return

    original_full_path = _doc_full_path(doc)

    # Baseline snapshot used both by the quality gate below (which may accept
    # violations and change it) and by the manifest generated in the pipeline —
    # captured here, before any SaveProject/gate side effects, and forwarded
    # via preflight_payload.
    baseline_path_for_payload = _baseline_path_for_doc(doc, only_existing=True)
    baseline_entries_for_payload = []
    if baseline_path_for_payload:
        entries, status = baseline.load_baseline(baseline_path_for_payload)
        if status == baseline.STATUS_OK:
            baseline_entries_for_payload = entries
        else:
            safe_print(f"Scene Collector: baseline sidecar not loaded ({status})")

    # ── Phase 1: Pre-flight QC ──
    safe_print("Scene Collector: Running pre-flight checks...")

    issues = []
    rules_context = _active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    if baseline_path:
        preflight_score = compute_score(
            registry_results,
            rules_context,
            baseline_path=baseline_path,
            current_params=rules_context.params,
        )
    else:
        preflight_score = compute_score(registry_results, rules_context)
    legacy_by_id = {
        check_id: pair.get("legacy_result")
        for check_id, pair in registry_results.items()
    }
    preflight_entries = sorted(
        enumerate(CHECK_REGISTRY),
        key=lambda item: (
            item[1].preflight_order
            if item[1].preflight_order is not None
            else item[0]
        ),
    )
    for _idx, entry in preflight_entries:
        count = preflight_score["counts"].get(entry.check_id, 0)
        if count:
            issues.append(entry.preflight_template.format(n=count))

    # Show pre-flight results
    if issues:
        msg = f"PRE-FLIGHT: {len(issues)} issue(s) found\n\n"
        msg += "\n".join(issues)
        msg += "\n\nFix issues before collecting?"
        msg += "\n\nYes = Fix auto-fixable issues, then collect"
        msg += "\nNo = Collect anyway"

        # 3-way: fix + collect, collect anyway, cancel
        result = c4d.gui.MessageDialog(msg, c4d.GEMB_YESNOCANCEL)
        if result == c4d.GEMB_R_CANCEL:
            safe_print("Scene Collector: Cancelled")
            return
        if result == c4d.GEMB_R_YES:
            # Auto-fix what we can — object-scoped fixable checks resolved through
            # the registry. Document-scoped fixes (fps_range) take no object list
            # and were never auto-fixed by the collector.
            fixed = 0
            for entry in CHECK_REGISTRY:
                if not entry.has_fix or entry.fix_scope != "objects":
                    continue
                objs = legacy_by_id.get(entry.check_id) or []
                if not objs:
                    continue
                fix_fn = resolve_function(entry.fix_fn, _current_module())
                fixed += fix_fn(doc, objs)
            safe_print(f"Scene Collector: Auto-fixed {fixed} issues")
    else:
        if not c4d.gui.QuestionDialog("Pre-flight: All checks passed!\n\nProceed with Save Project with Assets?"):
            return

    gate_overrides = []
    gate_evaluated = False
    if getattr(rules_context, "params", {}).get("gates_enabled", False):
        gate_evaluated = True
        gate_result = _run_quality_gate(doc, rules_context, artist_name, original_full_path)
        if not gate_result.get("proceed"):
            safe_print("Scene Collector: Quality gate cancelled")
            return
        gate_overrides = list(gate_result.get("overrides") or [])
        if gate_result.get("baseline_changed"):
            refreshed_path = gate_result.get("baseline_path") or baseline.get_baseline_path(original_full_path)
            refreshed_entries, refreshed_status = baseline.load_baseline(refreshed_path)
            if refreshed_status == baseline.STATUS_OK:
                baseline_path_for_payload = refreshed_path
                baseline_entries_for_payload = refreshed_entries

    # ── Phase 2: target folder (Hub — Task 12 — will choose it and skip this) ──
    target_dir = c4d.storage.LoadDialog(
        title="Select folder to collect project into",
        flags=c4d.FILESELECT_DIRECTORY
    )
    if not target_dir:
        safe_print("Scene Collector: No folder selected")
        return

    preflight_payload = {
        "issues": issues,
        "preflight_score": preflight_score,
        "rules_context": rules_context,
        "gate_overrides": gate_overrides,
        "gate_evaluated": gate_evaluated,
        "baseline_path": baseline_path_for_payload,
        "baseline_entries": baseline_entries_for_payload,
    }

    pipeline_result = run_collect_pipeline(
        doc, artist_name, target_dir, preflight_payload=preflight_payload)
    if pipeline_result is None:
        return

    manifest = pipeline_result["manifest"]
    assets_collected = pipeline_result["assets_collected"]
    assets_missing = pipeline_result["assets_missing"]

    # ── Summary ──
    msg = f"Scene Collected!\n\n"
    msg += f"Location: {pipeline_result['target_dir']}\n"
    msg += f"Assets: {assets_collected} collected"
    if assets_missing:
        msg += f"\nMissing: {assets_missing} (check manifest)"
    msg += f"\nSize: {manifest['total_size_mb']} MB"
    msg += f"\nManifest: sentinel_manifest.json"

    summary = manifest.get("asset_summary", {})
    if manifest.get("scan_status") == "failed":
        msg += "\n\n⚠ RE-SCAN FAILED — manifest has no asset verification!"
    else:
        msg += (f"\n\nPackage re-scan: {summary.get('total', 0)} assets — "
                f"{summary.get('collected', 0)} in package, "
                f"{summary.get('missing', 0)} missing, "
                f"{summary.get('external', 0)} external")
        if summary.get("missing", 0) or summary.get("external", 0):
            problem = [e["path"] for e in manifest.get("assets", [])
                       if e["state"] != "collected"][:10]
            msg += "\n  " + "\n  ".join(problem)

    notes_pending = pipeline_result.get("pending_todos", 0)
    if notes_pending:
        msg += f"\n⚠ {notes_pending} pending TODO(s) in scene notes"

    c4d.gui.MessageDialog(msg)
    safe_print("Scene Collector: Complete")


def run_collect_pipeline(doc, artist_name, target_dir, make_zip=False,
                          on_status=None, preflight_payload=None):
    """Phases 2 onward of Scene Collector: SaveProject with assets, clean
    delivery rename, re-scan of the collected package, manifest generation,
    sidecar copies, and an optional zip archive.

    target_dir is chosen by the caller (no LoadDialog here); pre-flight/gate
    results are supplied via preflight_payload — a dict with keys `issues`,
    `preflight_score`, `rules_context`, `gate_overrides`, `gate_evaluated`,
    `baseline_path`, `baseline_entries` (all optional; the manifest degrades
    gracefully when a key is absent).

    Returns a result dict, or None if SaveProject failed / errored.
    """
    from datetime import datetime

    def _status(msg):
        safe_print(f"Collect: {msg}")
        if on_status:
            on_status(msg)

    payload = preflight_payload or {}
    issues = payload.get("issues", [])
    preflight_score = payload.get("preflight_score", {})
    rules_context = payload.get("rules_context")
    gate_overrides = payload.get("gate_overrides", [])
    gate_evaluated = payload.get("gate_evaluated", False)
    original_baseline_path = payload.get("baseline_path")
    original_baseline_entries = payload.get("baseline_entries") or []

    original_full_path = _doc_full_path(doc)

    # Capture original metadata BEFORE SaveProject runs — SaveProject changes
    # the doc's path/name to the delivery folder, losing the original identity.
    original_doc_name = doc.GetDocumentName() or "scene.c4d"
    original_name_no_ext = os.path.splitext(original_doc_name)[0]
    original_base, original_version_int, original_status = parse_version_filename(original_name_no_ext)
    if not original_base:
        original_base = original_name_no_ext
    # The "clean" delivery name strips _v###[_status] — pure scene identity.
    delivery_filename = f"{original_base}.c4d"

    # Capture the notes sidecar path/data BEFORE SaveProject so we don't lose them.
    original_notes_path = get_notes_path(doc)
    original_notes_data = None
    if original_notes_path and os.path.exists(original_notes_path):
        try:
            original_notes_data = load_notes(original_notes_path)
        except Exception as e:
            safe_print(f"Scene Collector: Could not pre-load notes: {e}")

    # Capture the client report sidecar (<base>_report.html) before SaveProject
    # moves the doc — its base is already version-stripped, so it copies into the
    # delivery under the clean <original_base>_report.html name unchanged.
    from sentinel.versioning import report_html_path
    original_report_path = report_html_path(original_full_path)
    if original_report_path and not os.path.exists(original_report_path):
        original_report_path = None

    # ── Phase 2: Collect via C4D native ──
    _status("Saving project with assets…")

    assets = []
    missing_assets = []

    try:
        flags = (c4d.SAVEPROJECT_ASSETS |
                 c4d.SAVEPROJECT_SCENEFILE |
                 c4d.SAVEPROJECT_PROGRESSALLOWED |
                 c4d.SAVEPROJECT_DONTFAILONMISSINGASSETS)

        result = c4d.documents.SaveProject(doc, flags, target_dir, assets, missing_assets)

        if not result:
            c4d.gui.MessageDialog("Save Project failed!\n\nCheck console for details.")
            safe_print("Scene Collector: SaveProject returned False")
            return None

    except Exception as e:
        c4d.gui.MessageDialog(f"Save Project error:\n{e}")
        safe_print(f"Scene Collector error: {e}")
        return None

    safe_print(f"Scene Collector: Collected {len(assets)} assets")
    if missing_assets:
        safe_print(f"Scene Collector: {len(missing_assets)} missing assets!")

    # ── Phase 2.5: Rename the saved file to the clean delivery name ──
    # C4D's SaveProject saves to <target_dir>/<folder_basename>.c4d. We rename
    # it to the clean original scene base (stripped of _v### suffix) so the
    # delivery has a clean identity matching the notes sidecar naming.
    saved_folder_basename = os.path.basename(target_dir.rstrip(os.sep)) + ".c4d"
    saved_at = os.path.join(target_dir, saved_folder_basename)
    desired_at = os.path.join(target_dir, delivery_filename)

    if saved_at != desired_at:
        if os.path.exists(saved_at):
            try:
                if os.path.exists(desired_at):
                    # Defensive: refuse to overwrite an existing file
                    safe_print(f"Scene Collector: refused to overwrite existing {delivery_filename}")
                else:
                    os.rename(saved_at, desired_at)
                    safe_print(f"Scene Collector: Renamed {saved_folder_basename} -> {delivery_filename}")
                    # Update the active doc's identity so the panel + future Cmd+S
                    # reflect the renamed file
                    try:
                        doc.SetDocumentPath(target_dir)
                        doc.SetDocumentName(delivery_filename)
                        c4d.EventAdd()
                    except Exception as e:
                        safe_print(f"Scene Collector: Could not update doc metadata: {e}")
            except Exception as e:
                safe_print(f"Scene Collector: Could not rename to delivery name: {e}")
        else:
            safe_print(f"Scene Collector: expected file {saved_folder_basename} not found after SaveProject")

    # ── Phase 2.6: Re-scan the collected package (Collect Confiable, I4) ──
    _status("Re-scanning package…")
    # saved_at only survives when the rename to the clean delivery name was
    # refused (a stale delivery already sat in target_dir) — in that case it
    # is the FRESH SaveProject output and must win, or the re-scan would
    # audit the previous delivery instead of this one.
    delivered_c4d = saved_at if os.path.exists(saved_at) else desired_at
    asset_entries, scan_status, required_plugins = \
        _rescan_collected_package(delivered_c4d, target_dir)

    # ── Phase 3: Generate manifest ──
    _status("Writing manifest…")

    manifest = {
        "sentinel_manifest": True,
        "version": PLUGIN_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # Delivery identity (clean name, what the receiver sees)
        "scene": delivery_filename,
        # Original version metadata (traceability — where this came from)
        "original_filename": original_doc_name,
        "original_version": original_version_int,
        "original_status": (original_status or ""),
        "artist": artist_name or "",
        "shot_id": "",
        "collected_to": target_dir,
        "assets_collected": len(assets),
        "assets_missing": len(missing_assets),
        "missing_list": [],
        "pre_flight_issues": issues,
    }
    if gate_evaluated:
        manifest["gate_overrides"] = gate_overrides
    baseline_collection_active = bool(original_baseline_path)
    rules_collection_active = bool(rules_context and rules_context.rules_path)
    if rules_collection_active:
        manifest["ruleset"] = {
            "source": rules_context.source,
            "path": rules_context.rules_path or "",
            "identity": list(rules_context.identity or (None, None)),
            "shadowed_paths": list(rules_context.shadowed_paths or []),
            "warnings": list(rules_context.warnings or []),
        }
        manifest["qc"] = {
            "score": preflight_score.get("score", ""),
            "passed": preflight_score.get("passed", 0),
            "total": preflight_score.get("total", 0),
            "new": preflight_score.get("new", sum(preflight_score.get("counts", {}).values())),
            "accepted": preflight_score.get("accepted", 0),
            "stale": preflight_score.get("stale", 0),
            "schema": preflight_score.get("schema", 2),
            "disabled_checks": list(preflight_score.get("disabled", []) or []),
            "disabled_count": preflight_score.get("disabled_count", 0),
            "checks": build_baseline_artifact_details(preflight_score),
        }

    # Get shot ID
    try:
        td = doc.GetTakeData()
        if td:
            main_take = td.GetMainTake()
            if main_take:
                manifest["shot_id"] = main_take.GetName() or ""
    except Exception:
        pass

    # Log missing assets
    for m in missing_assets:
        try:
            manifest["missing_list"].append(str(m))
        except Exception:
            pass

    # Calculate total size
    total_size = 0
    for a in assets:
        try:
            filepath = str(a.get("filename", ""))
            if filepath and os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
        except Exception:
            pass
    manifest["total_size_mb"] = round(total_size / (1024 * 1024), 1)

    # ── Include scene notes + TODOs in manifest (and copy sidecar to delivery) ──
    # Uses original_notes_path/data captured before SaveProject moved the doc.
    if original_notes_data is not None:
        manifest["notes"] = {
            "summary": summarize_notes(original_notes_data),
            "text": original_notes_data.get("notes", "") or "",
            "todos": original_notes_data.get("todos", []) or [],
            "pending_count": sum(1 for t in (original_notes_data.get("todos") or []) if not t.get("done")),
            "updated": original_notes_data.get("updated", ""),
        }
        # Also copy the sidecar file alongside the .c4d so it travels with delivery
        if original_notes_path:
            try:
                import shutil
                shutil.copy2(original_notes_path, target_dir)
                safe_print(f"Scene Collector: Notes sidecar copied to delivery: {os.path.basename(original_notes_path)}")
            except Exception as e:
                safe_print(f"Scene Collector: Could not copy notes sidecar: {e}")
    else:
        manifest["notes"] = {"summary": "Notes: empty", "text": "", "todos": [], "pending_count": 0}

    if baseline_collection_active and original_baseline_entries:
        manifest["baseline"] = {
            "sidecar": os.path.basename(original_baseline_path),
            "acceptances": [
                _accepted_entry_payload(entry)
                for entry in original_baseline_entries
            ],
        }
        try:
            import shutil
            shutil.copy2(original_baseline_path, target_dir)
            safe_print(f"Scene Collector: Baseline sidecar copied to delivery: {os.path.basename(original_baseline_path)}")
        except Exception as e:
            safe_print(f"Scene Collector: Could not copy baseline sidecar: {e}")
    else:
        if baseline_collection_active:
            manifest["baseline"] = {"sidecar": os.path.basename(original_baseline_path or ""), "acceptances": []}

    # ── Copy the client HTML report into the delivery (clean name) ──
    if original_report_path:
        try:
            import shutil
            delivery_report_name = f"{original_base}_report.html"
            shutil.copy2(original_report_path, os.path.join(target_dir, delivery_report_name))
            manifest["client_report"] = delivery_report_name
            safe_print(f"Scene Collector: Client report copied to delivery: {delivery_report_name}")
        except Exception as e:
            safe_print(f"Scene Collector: Could not copy client report: {e}")

    if rules_collection_active:
        try:
            import shutil
            copied_rules_path = os.path.join(target_dir, "sentinel_rules.json")
            shutil.copy2(rules_context.rules_path, copied_rules_path)
            manifest["ruleset"]["copied_to"] = copied_rules_path
            safe_print("Scene Collector: effective sentinel_rules.json copied to delivery")
        except Exception as e:
            manifest["ruleset"]["copy_error"] = str(e)
            safe_print(f"Scene Collector: Could not copy sentinel_rules.json: {e}")

    # Save manifest
    manifest_path = os.path.join(target_dir, "sentinel_manifest.json")
    from sentinel import manifest as manifest_engine
    manifest_engine.merge_into_manifest(
        manifest, asset_entries, scan_status, required_plugins)
    if not manifest_engine.write_manifest_json(manifest, manifest_path):
        safe_print("Scene Collector: Could not save manifest atomically")
    else:
        safe_print(f"Scene Collector: Manifest saved to {manifest_path}")

    # ── Optional zip archive ──
    zip_result = None
    zip_error = None
    if make_zip:
        _status("Zipping…")
        from sentinel import assets as assets_engine
        try:
            zip_result = assets_engine.create_zip_archive(
                target_dir,
                on_progress=lambda i, n: _status(f"Zipping {i}/{n}…"))
        except Exception as e:
            zip_error = str(e)
            safe_print(f"Scene Collector: Zip failed: {e}")

    return {
        "target_dir": target_dir,
        "delivery_filename": delivery_filename,
        "assets_collected": len(assets),
        "assets_missing": len(missing_assets),
        "manifest_path": manifest_path,
        "manifest": manifest,
        "zip": zip_result,
        "zip_error": zip_error,
        "pending_todos": manifest.get("notes", {}).get("pending_count", 0),
    }


def _rescan_collected_package(delivery_c4d_path, target_dir):
    """Reopen the collected .c4d and re-scan its dependencies.

    This is the step SaveProject skips: verifying the *result*. Loads the
    delivered scene into a temp document (never added to the GUI), scans
    every texture/cache reference on that copy, classifies against the
    package root, and inventories third-party plugin object/tag types.

    Returns (asset_entries, scan_status, required_plugins). On any load
    failure returns ([], "failed", []) — never a silently-empty result.
    """
    from sentinel import manifest as manifest_engine
    from sentinel.textures import scan_all_texture_paths

    tmp_doc = None
    try:
        tmp_doc = c4d.documents.LoadDocument(
            delivery_c4d_path,
            c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS,
            None,
        )
        if tmp_doc is None:
            safe_print("Scene Collector: re-scan LoadDocument failed")
            return [], "failed", []

        records = scan_all_texture_paths(tmp_doc) or []
        # Flatten: drop live C4D refs before handing to the pure engine.
        flat = [{
            "current_path": r.get("current_path", ""),
            "resolved": r.get("resolved"),
            "status": r.get("status", ""),
            "source_type": r.get("source_type", ""),
            "channel": r.get("channel", ""),
            "host_name": r.get("host_name", ""),
        } for r in records]
        entries = manifest_engine.build_asset_entries(flat, target_dir)

        # Plugin inventory: object/tag types in the plugin-ID range
        # (>= 1,000,000 — C4D built-ins live below; Redshift/Alembic/
        # third-party all show up here, which is exactly the point:
        # "this scene needs X to open correctly").
        required = {}
        first = tmp_doc.GetFirstObject()
        if first:
            stack = [first]
            while stack:
                obj = stack.pop()
                while obj:
                    type_id = obj.GetType()
                    if type_id >= 1_000_000 and type_id not in required:
                        required[type_id] = obj.GetTypeName() or "<plugin>"
                    tag = obj.GetFirstTag()
                    while tag:
                        tag_id = tag.GetType()
                        if tag_id >= 1_000_000 and tag_id not in required:
                            required[tag_id] = tag.GetTypeName() or "<plugin>"
                        tag = tag.GetNext()
                    child = obj.GetDown()
                    if child:
                        stack.append(child)
                    obj = obj.GetNext()
        for mat in tmp_doc.GetMaterials() or []:
            type_id = mat.GetType()
            if type_id >= 1_000_000 and type_id not in required:
                required[type_id] = mat.GetTypeName() or "<plugin>"
        required_plugins = manifest_engine.filter_native_plugins([
            {"plugin_id": pid, "name": name}
            for pid, name in sorted(required.items())
        ])
        return entries, "ok", required_plugins
    except Exception as e:
        safe_print(f"Scene Collector: re-scan error: {e}")
        return [], "failed", []
    finally:
        if tmp_doc is not None:
            try:
                c4d.documents.KillDocument(tmp_doc)
            except Exception:
                pass


def snapshot_save_still(doc, artist_name):
    """Main entry point: find latest EXR, convert with ACES, save to project"""
    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return

    # Find latest EXR
    exr_path, error = _find_latest_exr()
    if not exr_path:
        c4d.gui.MessageDialog(error)
        return

    # Build output path
    output_dir = _get_stills_dir(doc, artist_name)
    doc_name = doc.GetDocumentName() or "untitled"
    scene_name = os.path.splitext(doc_name)[0]
    png_path = os.path.join(output_dir, f"{scene_name}.png")

    safe_print(f"Converting {os.path.basename(exr_path)} -> {png_path}")

    # Resolve opt-in review slate (project rules > machine setting > default OFF)
    slate_data = None
    try:
        rules_context = _active_rules_for_doc(doc)
        if bool(rules_context.params.get("slate", False)):
            slate_data = build_slate_data(doc, artist_name)
    except Exception as e:
        safe_print(f"Slate resolution skipped: {e}")

    # Convert
    success, error = _convert_exr_to_png(exr_path, png_path, slate_data=slate_data)
    if not success:
        c4d.gui.MessageDialog(f"Conversion failed:\n{error}")
        return

    # Show in Picture Viewer
    bmp = c4d.bitmaps.BaseBitmap()
    if bmp.InitWith(png_path)[0] == c4d.IMAGERESULT_OK:
        c4d.bitmaps.ShowBitmap(bmp)
        w, h = bmp.GetBw(), bmp.GetBh()
        c4d.gui.MessageDialog(f"Still saved!\n\nFile: {os.path.basename(png_path)}\nResolution: {w}x{h}\nFolder: {output_dir}")
    else:
        c4d.gui.MessageDialog(f"Still saved!\n\n{png_path}")

    safe_print(f"Still saved: {png_path}")


def snapshot_auto_convert(doc, artist_name, exr_path):
    """Silent watchfolder conversion — same pipeline as snapshot_save_still but
    NO MessageDialogs and NO Picture Viewer (modal/blocking calls would pause
    the driving Timer). Returns (success, message) where message is the PNG
    basename on success or a short error string on failure. Never raises.
    """
    if not artist_name:
        return False, "no artist name set"
    if not exr_path or not os.path.exists(exr_path):
        return False, "EXR vanished before convert"

    try:
        output_dir = _get_stills_dir(doc, artist_name)
        doc_name = (doc.GetDocumentName() if doc else "") or "untitled"
        scene_name = os.path.splitext(doc_name)[0]
        png_path = os.path.join(output_dir, f"{scene_name}.png")

        # Resolve opt-in review slate (project rules > machine setting > default OFF)
        slate_data = None
        try:
            rules_context = _active_rules_for_doc(doc)
            if bool(rules_context.params.get("slate", False)):
                slate_data = build_slate_data(doc, artist_name)
        except Exception as e:
            safe_print(f"Auto-convert slate resolution skipped: {e}")

        success, error = _convert_exr_to_png(exr_path, png_path, slate_data=slate_data)
        if not success:
            safe_print(f"Auto-convert failed for {os.path.basename(exr_path)}: {error}")
            return False, "conversion failed"

        msg = f"{os.path.basename(exr_path)} -> {os.path.basename(png_path)}"
        safe_print(f"Auto: converted {msg}")
        return True, os.path.basename(png_path)
    except Exception as e:
        safe_print(f"Auto-convert error: {e}")
        return False, "conversion error"


def snapshot_open_folder(doc, artist_name):
    """Open the artist's stills folder"""
    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return
    output_dir = _get_stills_dir(doc, artist_name)
    if os.path.exists(output_dir):
        open_in_explorer(output_dir)
    else:
        c4d.gui.MessageDialog(f"Folder not found:\n{output_dir}")


def scan_scene_assets(doc):
    """Unified Asset Hub inventory: structured texture scan (repathable)
    + GetAllAssetsNew sweep (exhaustive, read-only). Per-item failures are
    counted, never fatal — the Hub must never show a silently-empty list.

    Returns (records, tex_records, skipped):
      records     — merged AssetRecords (assets.merge_inventories)
      tex_records — LIVE TextureRecord list; writers resolve back to it via
                    tex_idx, owner_ref = tex_records[r["tex_idx"]]["host"]
      skipped     — count of per-item exceptions (never fatal)
    """
    from sentinel import assets as assets_engine
    from sentinel.textures import scan_all_texture_paths
    # _is_light_obj already imported at module scope (line 19).

    skipped = 0

    try:
        tex_records = scan_all_texture_paths(doc) or []
    except Exception as e:
        safe_print(f"Asset Hub: texture scan failed: {e}")
        tex_records = []
        skipped += 1

    tex_flat = []
    for i, r in enumerate(tex_records):
        try:
            tex_flat.append({
                "path": r.get("current_path", ""),
                "resolved": r.get("resolved"),
                "status": r.get("status", ""),
                "host_name": r.get("host_name", ""),
                "source_type": r.get("source_type", ""),
                "channel": r.get("channel", ""),
                "tex_idx": i,
            })
        except Exception:
            skipped += 1

    # GetAllAssetsNew reports the document's own .c4d as one of its assets
    # (an xref-shaped entry with no owner). Precompute the doc's own path so
    # the loop below can drop that self-reference — otherwise every scene
    # lists itself as an asset row in the Hub. Unsaved docs have no path;
    # in that case doc_own degrades to just the filename and the comparison
    # is skipped entirely (an unsaved doc can't match a resolved filename).
    doc_own = None
    doc_own_path = doc.GetDocumentPath() or ""
    if doc_own_path:
        doc_own = os.path.normcase(os.path.normpath(
            os.path.join(doc_own_path, doc.GetDocumentName() or "")))

    generic = []
    try:
        asset_list = []
        # Real signature (Maxon docs, 2026): GetAllAssetsNew(doc, allowDialogs,
        # lastPath, flags=ASSETDATA_FLAG_NONE, assetList=[]). The brief's
        # `ASSETDATA_FLAG_0` isn't a real constant in the 2026 flag set (verified
        # against Maxon's official docs) — ASSETDATA_FLAG_NONE is the documented
        # "no filtering" value and is what an exhaustive sweep needs.
        c4d.documents.GetAllAssetsNew(
            doc, False, "", flags=c4d.ASSETDATA_FLAG_NONE, assetList=asset_list)
        for item in asset_list:
            try:
                filename = item.get("filename", "")
                if doc_own and filename and \
                        os.path.normcase(os.path.normpath(filename)) == doc_own:
                    continue
                owner = item.get("owner")
                owner_name = owner.GetName() if owner else ""
                kind = "object"
                if owner is not None:
                    if isinstance(owner, c4d.BaseMaterial):
                        kind = "material"
                    # Reuse the repo's own (cached, broader) RS-light detection
                    # — checks.scene._is_light_obj covers more Redshift light
                    # type IDs than a hardcoded 2-id tuple and is already
                    # imported elsewhere in this module's package.
                    elif _is_light_obj(owner):
                        kind = "light"
                generic.append({
                    "path": filename,
                    "exists": bool(item.get("exists", False)),
                    "owner_name": owner_name,
                    "owner_kind": kind,
                })
            except Exception:
                skipped += 1
    except Exception as e:
        safe_print(f"Asset Hub: GetAllAssetsNew failed: {e}")
        skipped += 1

    records = assets_engine.merge_inventories(tex_flat, generic)
    return records, tex_records, skipped

