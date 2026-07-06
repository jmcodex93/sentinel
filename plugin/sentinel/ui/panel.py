# -*- coding: utf-8 -*-
import c4d
from c4d import plugins, gui, documents
import os
import json
import time
import sys
import webbrowser
import math as _math

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sentinel
from sentinel import baseline
from sentinel import gate as quality_gate
from sentinel import PLUGIN_NAME, PLUGIN_VERSION
from sentinel.common.cache import CheckCache, check_cache
from sentinel.common.constants import (
    CACHE_DURATION,
    CHECK_COOLDOWN,
    LEGACY_SETTINGS_FILE,
    MAX_OBJECTS_PER_CHECK,
    PLUGIN_ID,
    PRESETS,
    SETTINGS_FILE,
)
from sentinel.checks import render as render_checks
from sentinel.checks import scene as scene_checks
from sentinel.checks.scene import _is_light_obj
from sentinel.common.helpers import (
    _iter_objs,
    _safe_name,
    open_in_explorer,
    safe_print,
)
from sentinel.common.settings import GlobalSettings
from sentinel.qc.results import (
    CheckResult,
    material_identity,
    object_identity,
    structured_cache_key,
)
from sentinel.qc.registry import CHECK_REGISTRY, CheckDisplayView, RowKeysView
from sentinel.qc.registry import entry_severity
from sentinel.qc.score import compute_score, count_violations, run_all_checks
from sentinel.rules import get_active_rules
from sentinel.ui.ids import G
from sentinel.ui.user_areas import (
    HistoryArea,
    ScoreHeader,
    StatusArea,
    TextureListArea,
    _CHECK_DISPLAY,
    _accepted_entry_payload,
    _entry_label,
    _violation_label,
    format_baseline_row_message,
)
from sentinel.ui.dialogs import (
    BaselineActionDialog,
    GateTriageDialog,
    MultiFormatDialog,
    NotesDialog,
    SaveVersionDialog,
    SentinelSettingsDialog,
    TextureRepathingDialog,
    load_repath_presets,
    save_repath_preset,
)

# Import maxon for node material access
try:
    import maxon
    MAXON_AVAILABLE = True
except ImportError:
    MAXON_AVAILABLE = False

# Import Redshift module for AOV management
try:
    import redshift
    REDSHIFT_AVAILABLE = True
except ImportError:
    REDSHIFT_AVAILABLE = False

def normalize_preset_name(name):
    """Normalize preset name: lowercase, replace hyphens/spaces with underscores"""
    if not name:
        return ""
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _doc_path_for_rules(doc):
    if doc is None:
        return ""
    try:
        return doc.GetDocumentPath() or ""
    except Exception:
        return ""


def _machine_rule_settings():
    try:
        return {"standard_fps": GlobalSettings.get_standard_fps()}
    except Exception:
        return {}


def _active_rules_for_doc(doc):
    return get_active_rules(_doc_path_for_rules(doc), _machine_rule_settings())


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




def _rules_header_text(rules_context):
    if rules_context is None:
        return "Rules: defaults"
    if rules_context.rules_path:
        text = f"Rules: {os.path.basename(rules_context.rules_path)} (project)"
    else:
        text = "Rules: defaults"
    shadow_count = len(rules_context.shadowed_paths or [])
    if shadow_count:
        text += f" - shadows {shadow_count}"
    return text

# ---------------- migrated scene QC wrappers ----------------
def check_lights(doc):
    return scene_checks.legacy_items(scene_checks.check_lights(doc))


def check_visibility_traps(doc):
    return scene_checks.legacy_items(scene_checks.check_visibility_traps(doc))


def check_keys(doc):
    return scene_checks.legacy_items(scene_checks.check_keys(doc))


def check_camera_shift(doc):
    return scene_checks.legacy_items(scene_checks.check_camera_shift(doc))


def check_render_conflicts(doc):
    return render_checks.legacy_items(render_checks.check_render_conflicts(doc))

from sentinel import textures as texture_engine
from sentinel.checks import assets as assets_checks
from sentinel.textures import (
    _classify_texture_path,
    _is_absolute_path,
    _looks_like_texture_path,
    _resolve_relative_texture,
    apply_texture_path_change,
    compute_relative_texture_path,
    find_missing_texture_candidates,
    scan_all_texture_paths,
)

def check_textures_unified_structured(doc):
    return assets_checks.check_textures_unified_structured(doc)

def check_textures_unified(doc):
    return assets_checks.check_textures_unified(doc)

def check_unused_materials(doc):
    return scene_checks.legacy_items(scene_checks.check_unused_materials(doc))


def check_default_names(doc):
    return scene_checks.legacy_items(scene_checks.check_default_names(doc))


def check_output_paths(doc):
    return render_checks.legacy_items(render_checks.check_output_paths(doc))


# ---------------- scene complexity ----------------
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

# ---------------- RS AOV management ----------------
from sentinel import aovs as aov_engine
from sentinel.aovs import (
    AOV_TIER_ESSENTIALS,
    AOV_TIER_PRODUCTION,
    REDSHIFT_AVAILABLE as AOV_REDSHIFT_AVAILABLE,
    RS_CAUSTICS_ENABLED_ID,
    RS_ENVIRONMENT_ID,
    RS_VOLUME_ID,
    _AOV_DEFS,
    _APPLY_COLOR_PROCESSING,
    _COMP_MAP,
    _DEPTH_CAMERA_NEARFAR,
    _DEPTH_FILTER_TYPE,
    _DEPTH_MODE,
    _MV_FILTERING,
    _MV_MAX_MOTION,
    _MV_NO_CLAMP,
    _MV_RAW_VECTORS,
    _are_caustics_enabled,
    _build_tier_list,
    _get_rs_videopost,
    _has_volumes_in_scene,
    _resolve_aov_type,
    check_rs_aovs,
    force_aov_tier,
    get_rs_aovs,
)

def check_takes(doc):
    return render_checks.legacy_items(render_checks.check_takes(doc))

def check_fps_range(doc):
    return render_checks.legacy_items(render_checks.check_fps_range(doc))

def _fix_one_render_data(doc, rd, standard_fps, start_frame=1001):
    """Fix a single render data. Returns list of human-readable change strings.

    Caller is responsible for StartUndo/EndUndo and AddUndo. Returns final
    (start, end) frames after the fix, useful for timeline alignment.
    """
    changes = []
    preset_name = rd.GetName()
    preset_norm = normalize_preset_name(preset_name)
    is_stills = preset_norm == "stills"
    tag = f"[{preset_name}]"

    rd_fps_old = int(rd[c4d.RDATA_FRAMERATE])
    current_start = rd[c4d.RDATA_FRAMEFROM].GetFrame(rd_fps_old)
    current_end = rd[c4d.RDATA_FRAMETO].GetFrame(rd_fps_old)
    frame_mode = rd[c4d.RDATA_FRAMESEQUENCE]
    frame_step = int(rd[c4d.RDATA_FRAMESTEP])

    # Render FPS
    if rd_fps_old != standard_fps:
        rd[c4d.RDATA_FRAMERATE] = float(standard_fps)
        changes.append(f"{tag} Render FPS {rd_fps_old} -> {standard_fps}")

    # Frame step
    if frame_step != 1:
        rd[c4d.RDATA_FRAMESTEP] = 1
        changes.append(f"{tag} Frame step {frame_step} -> 1")

    final_start = start_frame
    final_end = start_frame

    if is_stills:
        if frame_mode == c4d.RDATA_FRAMESEQUENCE_MANUAL and current_start != start_frame:
            duration = max(0, current_end - current_start)
            final_end = start_frame + duration
            rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(start_frame, standard_fps)
            rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(final_end, standard_fps)
            changes.append(f"{tag} Frame range {current_start}-{current_end} -> {start_frame}-{final_end}")
        elif frame_mode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
            rd[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
            changes.append(f"{tag} Frame mode 'All Frames' -> 'Current Frame'")
        elif rd_fps_old != standard_fps:
            # Re-anchor BaseTime to new fps
            rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(current_start, standard_fps)
            rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(current_end, standard_fps)
            final_end = current_end if current_end >= start_frame else start_frame
        else:
            final_end = current_end if current_end >= start_frame else start_frame
    else:
        # Animation: range start at configured project frame, preserve duration
        duration = max(0, current_end - current_start)
        final_end = start_frame + duration
        if current_start != start_frame or rd_fps_old != standard_fps:
            rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(final_start, standard_fps)
            rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(final_end, standard_fps)
            if current_start != start_frame:
                changes.append(f"{tag} Frame range {current_start}-{current_end} -> {final_start}-{final_end}")
        if frame_mode in (c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME, c4d.RDATA_FRAMESEQUENCE_ALLFRAMES):
            rd[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_MANUAL
            changes.append(f"{tag} Frame mode -> 'Manual'")

    return changes, final_start, final_end


def _apply_fps_range(doc):
    """Apply FPS/range fixes. Caller owns undo, cache invalidation, and EventAdd."""
    fixes = []
    if not doc.GetFirstRenderData():
        return fixes

    rules_context = _active_rules_for_doc(doc)
    standard_fps = int(rules_context.params.get("standard_fps", GlobalSettings.get_standard_fps()))
    start_frame = int(rules_context.params.get("start_frame", 1001))
    active_rd = doc.GetActiveRenderData()

    # --- Document-level FPS (once) ---
    doc_fps = doc.GetFps()
    if doc_fps != standard_fps:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, doc)
        doc.SetFps(standard_fps)
        fixes.append(f"Document FPS: {doc_fps} -> {standard_fps}")

    # --- Iterate all render datas ---
    active_final_start = start_frame
    active_final_end = start_frame

    rd = doc.GetFirstRenderData()
    while rd:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, rd)
        changes, final_start, final_end = _fix_one_render_data(
            doc, rd, standard_fps, start_frame)
        fixes.extend(changes)
        if rd == active_rd:
            active_final_start = final_start
            active_final_end = final_end
        rd = rd.GetNext()

    # --- Align timeline + preview to ACTIVE preset's range ---
    tl_min = doc[c4d.DOCUMENT_MINTIME].GetFrame(standard_fps)
    tl_max = doc[c4d.DOCUMENT_MAXTIME].GetFrame(standard_fps)
    loop_min = doc[c4d.DOCUMENT_LOOPMINTIME].GetFrame(standard_fps)
    loop_max = doc[c4d.DOCUMENT_LOOPMAXTIME].GetFrame(standard_fps)

    if tl_min != active_final_start or tl_max != active_final_end:
        # Avoid intermediate min > max state
        if active_final_start >= tl_max:
            doc[c4d.DOCUMENT_MAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
            doc[c4d.DOCUMENT_MINTIME] = c4d.BaseTime(active_final_start, standard_fps)
        else:
            doc[c4d.DOCUMENT_MINTIME] = c4d.BaseTime(active_final_start, standard_fps)
            doc[c4d.DOCUMENT_MAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
        fixes.append(f"Timeline: {tl_min}-{tl_max} -> {active_final_start}-{active_final_end}")

    if loop_min != active_final_start or loop_max != active_final_end:
        if active_final_start >= loop_max:
            doc[c4d.DOCUMENT_LOOPMAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
            doc[c4d.DOCUMENT_LOOPMINTIME] = c4d.BaseTime(active_final_start, standard_fps)
        else:
            doc[c4d.DOCUMENT_LOOPMINTIME] = c4d.BaseTime(active_final_start, standard_fps)
            doc[c4d.DOCUMENT_LOOPMAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
        fixes.append(f"Preview range: {loop_min}-{loop_max} -> {active_final_start}-{active_final_end}")

    # --- Snap playhead to range if it fell outside ---
    playhead = doc.GetTime().GetFrame(standard_fps)
    if playhead < active_final_start or playhead > active_final_end:
        doc.SetTime(c4d.BaseTime(active_final_start, standard_fps))
        fixes.append(f"Playhead: frame {playhead} -> {active_final_start} (out of range)")

    return fixes


def fix_fps_range(doc):
    """Auto-fix FPS/range across ALL render presets. Aligns timeline to active preset."""
    fixes = []
    if not doc.GetFirstRenderData():
        return fixes

    doc.StartUndo()
    try:
        fixes = _apply_fps_range(doc)
    except Exception as e:
        safe_print(f"Error fixing FPS/range: {e}")
    finally:
        doc.EndUndo()

    check_cache.clear()
    c4d.EventAdd()
    return fixes

# ---------------- auto-fix functions ----------------
def _apply_lights(doc, lights_bad):
    """Apply light grouping fix. Caller owns undo, cache invalidation, and EventAdd."""
    # Find or create the lights group
    lights_group = None
    obj = doc.GetFirstObject()
    while obj:
        if obj.GetType() == c4d.Onull and obj.GetName().strip().lower() in {"light", "lights", "lighting"}:
            lights_group = obj
            break
        obj = obj.GetNext()

    if not lights_group:
        lights_group = c4d.BaseObject(c4d.Onull)
        lights_group.SetName("lights")
        doc.InsertObject(lights_group)
        doc.AddUndo(c4d.UNDOTYPE_NEW, lights_group)

    moved = 0
    for light in lights_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        light.Remove()
        light.InsertUnderLast(lights_group)
        moved += 1

    return moved


def fix_lights(doc, lights_bad):
    """Move stray lights into a 'lights' group null"""
    if not lights_bad:
        return 0

    doc.StartUndo()
    moved = _apply_lights(doc, lights_bad)
    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return moved


def _apply_camera_shift(doc, cam_bad):
    """Apply camera shift reset. Caller owns undo, cache invalidation, and EventAdd."""
    fixed = 0
    for cam in cam_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, cam)
        try:
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
            fixed += 1
        except Exception:
            pass

    return fixed


def fix_camera_shift(doc, cam_bad):
    """Reset camera shift to 0 on all flagged cameras"""
    if not cam_bad:
        return 0

    doc.StartUndo()
    fixed = _apply_camera_shift(doc, cam_bad)
    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return fixed


def _apply_unused_materials(doc, unused_mats):
    """Apply unused-material deletion. Caller owns undo, cache invalidation, and EventAdd."""
    deleted = 0
    for mat in unused_mats:
        doc.AddUndo(c4d.UNDOTYPE_DELETE, mat)
        mat.Remove()
        deleted += 1

    return deleted


def fix_unused_materials(doc, unused_mats):
    """Delete unused materials from the scene"""
    if not unused_mats:
        return 0

    doc.StartUndo()
    deleted = _apply_unused_materials(doc, unused_mats)
    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return deleted


def apply_fixes(doc, fixes):
    """Apply selected auto-fixes as one undo step.

    ``fixes`` items have shape {"check_id": str, "objects": list}. The caller
    is responsible for passing only live objects/materials filtered to new
    violations. ``fps_range`` ignores ``objects`` and normalizes all presets.
    """
    dispatch = {
        "lights": _apply_lights,
        "cam": _apply_camera_shift,
        "unused_mats": _apply_unused_materials,
        "fps_range": lambda active_doc, _objects: _apply_fps_range(active_doc),
    }
    results = []

    try:
        doc.StartUndo()
        try:
            for item in fixes or []:
                check_id = item.get("check_id")
                apply_one = dispatch.get(check_id)
                if not apply_one:
                    continue
                objects = item.get("objects") or []
                if check_id != "fps_range" and not objects:
                    continue
                results.append({"check_id": check_id, "result": apply_one(doc, objects)})
        finally:
            doc.EndUndo()
    finally:
        check_cache.clear()
        c4d.EventAdd()
    return results

_REPORT_KEY_BY_CHECK_ID = {
    "lights": "lights",
    "vis": "visibility",
    "keys": "keyframes",
    "cam": "camera_shift",
    "rdc": "render_presets",
    "textures": "textures",
    "unused_mats": "unused_materials",
    "names": "default_names",
    "output": "output_paths",
    "takes": "takes",
    "fps_range": "fps_range",
    "cross_aspect": "cross_aspect",
}


def build_baseline_artifact_details(qc_summary):
    """Return JSON-safe baseline split details for reports/manifests."""
    if not isinstance(qc_summary, dict) or qc_summary.get("schema") != 2:
        return {}

    details = {}
    matches = qc_summary.get("baseline_matches", {}) or {}
    for check_id, match in matches.items():
        new_items = [_violation_label(item) for item in (match.get("new") or [])]
        accepted = []
        accepted_entries = match.get("accepted_entries") or []
        accepted_violations = match.get("accepted") or []
        for index, entry in enumerate(accepted_entries):
            violation = accepted_violations[index] if index < len(accepted_violations) else None
            accepted.append(_accepted_entry_payload(entry, violation))
        stale = [_accepted_entry_payload(entry) for entry in (match.get("stale_entries") or [])]
        details[check_id] = {
            "new_count": len(new_items),
            "accepted_count": len(accepted),
            "stale_count": len(stale),
            "new": new_items,
            "accepted": accepted,
            "stale": stale,
        }
    return details


def export_qc_report(doc, results, artist_name, qc_summary=None):
    """Export QC report as JSON to a user-chosen location"""
    from datetime import datetime

    # Build report
    report = {
        "report": "Sentinel QC Report",
        "version": PLUGIN_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene": doc.GetDocumentName() or "untitled",
        "path": doc.GetDocumentPath() or "",
        "artist": artist_name or "",
        "shot_id": "",
        "checks": {}
    }

    # Get shot ID
    try:
        td = doc.GetTakeData()
        if td:
            main_take = td.GetMainTake()
            if main_take:
                report["shot_id"] = main_take.GetName() or ""
    except Exception:
        pass

    # Populate checks
    for key, label, items in [
        ("lights", "Lights outside group", results.get("lights_bad", [])),
        ("visibility", "Visibility mismatches", results.get("vis_bad", [])),
        ("keyframes", "Multi-axis keyframes", results.get("keys_bad", [])),
        ("camera_shift", "Camera shift != 0", results.get("cam_bad", [])),
        ("unused_materials", "Unused materials", results.get("unused_mats_bad", [])),
        ("default_names", "Default/generic names", results.get("names_bad", [])),
    ]:
        obj_list = []
        for item in (items or []):
            try:
                obj_list.append(item.GetName() or "unnamed")
            except Exception:
                obj_list.append(str(item))
        report["checks"][key] = {
            "status": "PASS" if not obj_list else "FAIL",
            "count": len(obj_list),
            "label": label,
            "items": obj_list[:50],
        }

    # Unified textures check
    tex_bad = results.get("textures_bad", [])
    report["checks"]["textures"] = {
        "status": "PASS" if not tex_bad else "FAIL",
        "count": len(tex_bad),
        "label": "Texture issues (absolute paths + missing files)",
        "items": [f"[{t['issue'].upper()}] {t['source']}: {t['path']}" for t in tex_bad[:30]],
    }

    # Scene stats
    stats = results.get("scene_stats", {})
    if stats:
        report["scene_stats"] = stats

    # Info-only checks
    for key, label, count in [
        ("render_presets", "Non-standard presets", results.get("rdc_count", 0)),
        ("output_paths", "Output path issues", results.get("output_count", 0)),
        ("takes", "Take configuration issues", len(results.get("takes_bad", []))),
    ]:
        report["checks"][key] = {
            "status": "PASS" if count == 0 else "FAIL",
            "count": count,
            "label": label,
        }

    if results.get("output_bad"):
        report["checks"]["output_paths"]["items"] = [
            f"[{i['preset']}] {i['issue']}" for i in results["output_bad"][:10]
        ]
    if results.get("takes_bad"):
        report["checks"]["takes"]["items"] = [
            f"[{t['take']}] {t['issue']}" for t in results["takes_bad"][:20]
        ]

    # FPS / Frame Range check
    fps_bad = results.get("fps_range_bad", [])
    report["checks"]["fps_range"] = {
        "status": "PASS" if not fps_bad else "FAIL",
        "count": len(fps_bad),
        "label": "FPS & frame range validation",
        "items": [issue["issue"] for issue in fps_bad],
    }

    # Cross-Aspect Safe Area check
    cross_aspect_bad = results.get("cross_aspect_bad", [])
    report["checks"]["cross_aspect"] = {
        "status": "PASS" if not cross_aspect_bad else "FAIL",
        "count": len(cross_aspect_bad),
        "label": "Cross-aspect safe-area violations",
        "items": [
            f"{v.get('object_name', 'unnamed')} [{v.get('fmt_id', '?')}] "
            f"sides={','.join(sorted(v.get('sides', [])))} "
            f"frames={','.join(str(f) for f in v.get('frames', []))}"
            for v in cross_aspect_bad[:30]
        ],
    }

    disabled_checks = []
    if isinstance(qc_summary, dict):
        disabled_checks = list(qc_summary.get("disabled", []) or [])
    for check_id in disabled_checks:
        report_key = _REPORT_KEY_BY_CHECK_ID.get(check_id)
        if report_key and report_key in report["checks"]:
            report["checks"][report_key]["status"] = "DISABLED"
            report["checks"][report_key]["disabled"] = True
            report["checks"][report_key]["count"] = 0

    # Summary
    total = len(report["checks"])
    passed = sum(1 for c in report["checks"].values() if c["status"] == "PASS")
    report["summary"] = {
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "score": f"{passed}/{total}"
    }

    if disabled_checks:
        report["disabled_checks"] = disabled_checks

    baseline_details = build_baseline_artifact_details(qc_summary)
    if baseline_details:
        for check_id, details in baseline_details.items():
            if check_id in disabled_checks:
                continue
            report_key = _REPORT_KEY_BY_CHECK_ID.get(check_id)
            if not report_key or report_key not in report["checks"]:
                continue
            check = report["checks"][report_key]
            check["status"] = "PASS" if details["new_count"] == 0 else "FAIL"
            check["new_count"] = details["new_count"]
            check["accepted_count"] = details["accepted_count"]
            check["stale_count"] = details["stale_count"]
            check["new"] = details["new"]
            check["accepted"] = details["accepted"]
            check["stale"] = details["stale"]
        report["baseline"] = {
            "path": qc_summary.get("baseline_path", ""),
            "checks": baseline_details,
        }

    if isinstance(qc_summary, dict):
        report["summary"] = {
            "total_checks": qc_summary.get("total", total),
            "passed": qc_summary.get("passed", passed),
            "failed": qc_summary.get("total", total) - qc_summary.get("passed", passed),
            "score": qc_summary.get("score", f"{passed}/{total}"),
            "new": qc_summary.get("new", 0),
            "accepted": qc_summary.get("accepted", 0),
            "stale": qc_summary.get("stale", 0),
            "schema": qc_summary.get("schema", 1),
            "disabled_count": qc_summary.get("disabled_count", len(disabled_checks)),
        }

    # Always include scene notes section in the report (empty defaults if no
    # sidecar exists yet — keeps the JSON shape consistent for tooling)
    notes_path = get_notes_path(doc)
    notes_section = {
        "summary": "Notes: empty",
        "text": "",
        "todos": [],
        "pending_count": 0,
        "updated": "",
    }
    if notes_path and os.path.exists(notes_path):
        try:
            notes_data = load_notes(notes_path)
            notes_section = {
                "summary": summarize_notes(notes_data),
                "text": notes_data.get("notes", "") or "",
                "todos": notes_data.get("todos", []) or [],
                "pending_count": sum(1 for t in (notes_data.get("todos") or []) if not t.get("done")),
                "updated": notes_data.get("updated", ""),
            }
        except Exception as e:
            safe_print(f"Could not include notes in QC report: {e}")
    report["notes"] = notes_section

    # Ask user where to save
    save_path = c4d.storage.SaveDialog(
        title="Save QC Report",
        force_suffix="json",
    )

    if not save_path:
        return None

    if not save_path.endswith(".json"):
        save_path += ".json"

    with open(save_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return save_path

# ---------------- Smart Incremental Save (versioning + history) ----------------
from sentinel import versioning
from sentinel.versioning import (
    FILTER_ALL,
    STATUS_CR,
    STATUS_FINAL,
    STATUS_NONE,
    STATUS_OPTIONS,
    STATUS_TR,
    _humanize_time_diff,
    _sanitize_status,
    append_history_entry,
    build_versioned_filename,
    compute_next_version,
    filter_versions_by_status,
    format_history_qc_label,
    format_version_row,
    get_history_path,
    get_latest_version_info,
    load_history,
    load_versions_for_doc,
    parse_version_filename,
    preview_next_filename,
    save_history,
)

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
    if check_id == "fps_range":
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


# ---------------- Scene Notes / TODO ----------------
# Pure helpers for managing per-scene notes + TODOs
from sentinel import notes as notes_engine
from sentinel.notes import (
    _empty_notes,
    _next_todo_id,
    add_todo,
    delete_todo,
    get_notes_path,
    has_pending_todos,
    load_notes,
    save_notes,
    summarize_notes,
    toggle_todo,
)



# ---------------- Multi-Format Render Setup ----------------
from sentinel import multiformat
from sentinel.multiformat import (
    COMPOSITION_MODE_NONE,
    COMPOSITION_MODE_RESIZE_CANVAS,
    MULTIFORMAT_DEFS,
    _find_take_by_name,
    _reset_camera_dimensions_to_native,
    _resolve_source_camera,
    _resolve_source_render_data,
    compute_format_output_path,
    compute_target_aperture,
    compute_target_horizontal_fov,
    format_aspect,
    generate_multiformat_takes,
    get_multiformat_def,
    take_name_for_format,
)

# ============================================================
# Cross-Aspect Safe-Area QC (#12) — Safe-area engine aliases
# ============================================================
from sentinel import safe_areas as safe_area_engine
from sentinel.checks import safe_areas as safe_area_checks
from sentinel.safe_areas import (
    SAFE_AREA_INSETS,
    SAFE_AREA_USERDATA_NAME,
    _evaluate_object_at_frame,
    _find_safe_area_userdata_id,
    _gather_keyframe_sample_frames,
    _safe_area_insets,
    _scan_cross_aspect_safe_area,
    corners_violation_sides,
    find_active_multiformat_takes,
    find_marked_safe_area_objects,
    format_safe_area_in_master_ndc,
    get_take_aspect,
    get_take_camera_h_fov_rad,
    get_take_resolution,
    is_object_marked_safe_area,
    mark_object_safe_area,
    project_world_to_ndc,
    resolve_take_projection_params,
    safe_area_ndc_box,
    unmark_object_safe_area,
    world_bbox_corners,
)

def check_cross_aspect_safe_area_structured(doc, sample_strategy="keyframes", rules_context=None):
    if rules_context is None:
        rules_context = _active_rules_for_doc(doc)
    return safe_area_checks.check_cross_aspect_safe_area_structured(
        doc, sample_strategy=sample_strategy, rules_context=rules_context)

def check_cross_aspect_safe_area(doc, sample_strategy="keyframes", rules_context=None):
    if rules_context is None:
        rules_context = _active_rules_for_doc(doc)
    return safe_area_checks.check_cross_aspect_safe_area(
        doc, sample_strategy=sample_strategy, rules_context=rules_context)

# ============================================================
# Cross-Aspect Safe-Area QC (#12) — Viewport overlay (v1.5.6)
# ============================================================




# ---------------- Scene Collector ----------------
def collect_scene(doc, artist_name):
    """Pre-flight QC + Save Project with Assets + Verify + Manifest"""
    from datetime import datetime

    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    doc_path = doc.GetDocumentPath()
    if not doc_path:
        c4d.gui.MessageDialog("Please save the scene first before collecting.")
        return

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

    original_baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    original_baseline_entries = []
    if original_baseline_path:
        entries, status = baseline.load_baseline(original_baseline_path)
        if status == baseline.STATUS_OK:
            original_baseline_entries = entries
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

    lights = legacy_by_id.get("lights") or []
    cam_bad = legacy_by_id.get("cam") or []
    unused = legacy_by_id.get("unused_mats") or []

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
            # Auto-fix what we can
            fixed = 0
            if lights:
                fixed += fix_lights(doc, lights)
            if unused:
                fixed += fix_unused_materials(doc, unused)
            if cam_bad:
                fixed += fix_camera_shift(doc, cam_bad)
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
                original_baseline_path = refreshed_path
                original_baseline_entries = refreshed_entries

    # ── Phase 2: Collect via C4D native ──
    safe_print("Scene Collector: Running Save Project with Assets...")

    target_dir = c4d.storage.LoadDialog(
        title="Select folder to collect project into",
        flags=c4d.FILESELECT_DIRECTORY
    )
    if not target_dir:
        safe_print("Scene Collector: No folder selected")
        return

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
            return

    except Exception as e:
        c4d.gui.MessageDialog(f"Save Project error:\n{e}")
        safe_print(f"Scene Collector error: {e}")
        return

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

    # ── Phase 3: Generate manifest ──
    safe_print("Scene Collector: Generating manifest...")

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
    rules_collection_active = bool(rules_context.rules_path)
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
    try:
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        safe_print(f"Scene Collector: Manifest saved to {manifest_path}")
    except Exception as e:
        safe_print(f"Scene Collector: Could not save manifest: {e}")

    # ── Summary ──
    msg = f"Scene Collected!\n\n"
    msg += f"Location: {target_dir}\n"
    msg += f"Assets: {len(assets)} collected"
    if missing_assets:
        msg += f"\nMissing: {len(missing_assets)} (check manifest)"
    msg += f"\nSize: {manifest['total_size_mb']} MB"
    msg += f"\nManifest: sentinel_manifest.json"
    notes_pending = manifest.get("notes", {}).get("pending_count", 0)
    if notes_pending:
        msg += f"\n⚠ {notes_pending} pending TODO(s) in scene notes"

    c4d.gui.MessageDialog(msg)
    safe_print("Scene Collector: Complete")

# ---------------- UI StatusArea ----------------
# Pre-allocated colors to avoid GC pressure in DrawMsg


# ---------------- Snapshot Handler ----------------
# ---------------- Snapshot System (cross-platform) ----------------

def _get_stills_dir(doc, artist_name):
    """Get output directory: project_root/output/stills/Artist/YYMMDD/"""
    from datetime import datetime
    doc_path = doc.GetDocumentPath() or ""
    if doc_path:
        project_root = os.path.dirname(os.path.dirname(doc_path))
    else:
        project_root = os.path.join(os.path.expanduser("~"), "YS_Guardian_Output")

    output_dir = os.path.join(
        project_root, "output", "stills",
        artist_name or "Unknown",
        datetime.now().strftime("%y%m%d")
    )
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def _find_latest_exr():
    """Find the most recent EXR in the RS snapshot directory"""
    snap_dir = GlobalSettings.get_snapshot_dir()
    if not os.path.exists(snap_dir):
        return None, f"Snapshot directory not found:\n{snap_dir}\n\nConfigure it in Redshift RenderView > Preferences > Snapshots"

    exr_files = []
    for f in os.listdir(snap_dir):
        if f.lower().endswith('.exr'):
            full = os.path.join(snap_dir, f)
            exr_files.append((full, os.path.getmtime(full)))

    if not exr_files:
        return None, f"No EXR snapshots found in:\n{snap_dir}\n\nTake a snapshot in RS RenderView first."

    exr_files.sort(key=lambda x: x[1], reverse=True)
    return exr_files[0][0], None

def _find_system_python():
    """Find a system Python 3 with OpenEXR support (cross-platform)"""
    import subprocess

    candidates = []
    if sys.platform == "darwin":
        candidates = ["/usr/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3"]
    else:
        import glob
        candidates = ["python", "python3"]
        for pattern in [r"C:\Program Files\Python*\python.exe",
                        r"C:\Program Files (x86)\Python*\python.exe"]:
            candidates.extend(glob.glob(pattern))
        user_local = os.path.expanduser("~")
        for pattern in [os.path.join(user_local, r"AppData\Local\Programs\Python\Python*\python.exe")]:
            candidates.extend(glob.glob(pattern))

    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import OpenEXR, numpy, PIL; print('OK')"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and "OK" in result.stdout:
                safe_print(f"Found system Python with OpenEXR: {py}")
                return py
        except Exception:
            continue

    return None

_CACHED_PYTHON = None

def _convert_exr_to_png(exr_path, png_path):
    """Convert EXR to PNG via external Python with OpenEXR + ACES pipeline"""
    import subprocess

    global _CACHED_PYTHON
    if not _CACHED_PYTHON:
        _CACHED_PYTHON = _find_system_python()

    if not _CACHED_PYTHON:
        return False, ("System Python with OpenEXR not found.\n\n"
                       "Install dependencies:\n"
                       "  pip3 install OpenEXR numpy Pillow")

    # Use the existing external converter script
    converter = os.path.join(_ROOT, "exr_converter_external.py")
    if not os.path.exists(converter):
        return False, f"Converter script not found: {converter}"

    try:
        result = subprocess.run(
            [_CACHED_PYTHON, converter, exr_path, png_path, "aces"],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode == 0 and os.path.exists(png_path):
            safe_print(f"Conversion complete: {os.path.basename(png_path)}")
            return True, None
        else:
            error = result.stderr or result.stdout or "Unknown error"
            safe_print(f"Converter error: {error}")
            return False, f"Conversion failed:\n{error[:300]}"

    except subprocess.TimeoutExpired:
        return False, "Conversion timed out (>120s)"
    except Exception as e:
        return False, f"Error running converter: {e}"

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

    # Convert
    success, error = _convert_exr_to_png(exr_path, png_path)
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

# ---------------- UI Widget IDs ----------------

class YSPanel(gui.GeDialog):
    def __init__(self):
        super().__init__()
        self._last_doc = None
        self._last_check_time = 0
        self._last_rules_identity = None
        self.ua = None
        self.score_ua = None  # ScoreHeader instance
        self.history_ua = None  # HistoryArea instance
        self._history_filter = FILTER_ALL
        try:
            self._history_max_rows = int(GlobalSettings.get('history_max_rows', 5))
        except Exception:
            self._history_max_rows = 5
        self._artist_name = ""
        self._quicktab = None  # QuickTab CustomGUI for tabs
        # Restore last-used tab from settings (0..3); fall back to QC if invalid
        try:
            saved_tab = int(GlobalSettings.get('active_tab', 0))
        except Exception:
            saved_tab = 0
        if not 0 <= saved_tab <= 3:
            saved_tab = 0
        self._active_tab = saved_tab
        self._dirty = False  # Set by CoreMessage, consumed by Timer

        # Store selection results
        self._lights_bad = []
        self._vis_bad = []
        self._keys_bad = []
        self._cam_bad = []
        self._textures_bad = []
        self._unused_mats_bad = []
        self._names_bad = []
        self._output_bad = []
        self._takes_bad = []
        self._fps_range_bad = []
        self._cross_aspect_bad = []
        self._scene_stats = {}
        self._registry_results = None
        self._qc_summary = None
        self._rules_context = None

        # Cycling indices for one-by-one selection
        self._unused_mats_idx = 0
        self._names_idx = 0

    # ── Tab switching: dynamic rebuild via LayoutFlushGroup ─────────────────
    # C4D 2026's HideElement returns True but does NOT collapse layout space
    # for hidden groups (verified empirically). The robust solution is to
    # keep only the active tab's content in the layout: flush the container
    # and rebuild on every switch.

    def _set_active_tab(self, idx):
        """Switch to tab `idx` by flushing the container and rebuilding."""
        if not 0 <= idx <= 3:
            return
        previous_tab = self._active_tab
        self._active_tab = idx
        try:
            self.LayoutFlushGroup(G.TAB_CONTAINER)
        except Exception as e:
            safe_print(f"LayoutFlushGroup error: {e}")
            return
        try:
            self._build_active_tab_content()
        except Exception as e:
            safe_print(f"_build_active_tab_content error: {e}")
        try:
            self.LayoutChanged(G.TAB_CONTAINER)
        except Exception as e:
            safe_print(f"LayoutChanged error: {e}")
        # Repopulate per-tab labels with current data (widgets just got created).
        try:
            doc = c4d.documents.GetActiveDocument()
            if idx == 1:  # Render
                self._update_snapshot_dir_label()
            elif idx == 2:  # Versions
                self._update_last_version_label(doc)
                self._update_notes_summary(doc)
                self._update_history_area(doc)
        except Exception as e:
            safe_print(f"Per-tab label refresh error: {e}")
        # Force immediate refresh (bypass Timer cooldown) so the new tab's
        # widgets show current data without waiting up to 3 seconds.
        try:
            self._last_check_time = 0
            self._dirty = True
            self._refresh()
        except Exception as e:
            safe_print(f"Immediate refresh error: {e}")
        # Persist the choice so reopening the plugin lands on the same tab.
        if previous_tab != idx:
            try:
                GlobalSettings.set('active_tab', idx)
            except Exception:
                pass

    def _build_active_tab_content(self):
        """Dispatch to the appropriate tab builder based on self._active_tab."""
        # Consistent spacing inside the tab container (applies to all tabs)
        try:
            self.GroupBorderSpace(4, 6, 4, 4)
            self.GroupSpace(0, 4)
        except Exception:
            pass
        if self._active_tab == 0:
            self._build_tab_qc()
        elif self._active_tab == 1:
            self._build_tab_render()
        elif self._active_tab == 2:
            self._build_tab_versions()
        elif self._active_tab == 3:
            self._build_tab_tools()

    def _add_section_label(self, title, first=False):
        """Sub-section visual divider: separator (unless first) + ▸ Title.

        Used inside tab builders for consistent visual hierarchy.
        """
        if not first:
            self.AddSeparatorH(6)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, f"▸ {title}", 0)

    # ── Tab content builders ─────────────────────────────────────────────────

    def _build_tab_qc(self):
        """Build QC tab content (no outer group; lives inside TAB_CONTAINER)."""
        # No instructional hint — the [Select]/[Fix]/[Info] buttons + the row
        # affordances make the click-to-act behavior discoverable.

        self.GroupBegin(40, c4d.BFH_SCALEFIT|c4d.BFV_TOP, 2, 0)
        self.GroupSpace(4, 0)

        # Left: terminal status display (StatusArea instance persists across rebuilds)
        self.AddUserArea(G.CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 260)
        if self.ua is None:
            self.ua = StatusArea()
        self.AttachUserArea(self.ua, G.CANVAS)
        self.ua.click_callback = self._on_qc_row_click

        # Right: per-check Select + Fix/Info buttons (2 columns × 12 rows)
        self.GroupBegin(407, c4d.BFH_RIGHT|c4d.BFV_SCALEFIT, 2, 12)
        self.GroupBorderSpace(0, 3, 0, 3)
        self.GroupSpace(2, 3)
        self.AddButton(G.BTN_SEL_LIGHTS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_LIGHTS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_SEL_VIS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_SEL_KEYS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_SEL_CAMS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_CAMS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_INFO_PRESET, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_TEXTURES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_SEL_UNUSED_MATS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_UNUSED_MATS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_SEL_NAMES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_OUTPUT, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_TAKES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_FPS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddButton(G.BTN_FIX_FPS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_SEL_CROSS_ASPECT, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_INFO_CROSS_ASPECT, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Info")
        self.GroupEnd()

        self.GroupEnd()  # status row

        self.AddSeparatorH(4)
        self.AddButton(G.BTN_EXPORT_QC, c4d.BFH_SCALEFIT, 0, 0, "Export QC Report")

        # Spacer absorbs remaining vertical space
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _build_tab_render(self):
        """Build Render tab content."""
        # ── Render Preset ──
        self._add_section_label("Render Preset", first=True)
        self.GroupBegin(20, c4d.BFH_SCALEFIT, 4, 0)
        self.AddComboBox(G.PRESET_DROPDOWN, c4d.BFH_SCALEFIT, 100, 0)
        self.AddStaticText(G.LABEL_RESOLUTION, c4d.BFH_LEFT, 100, 0, "", 0)
        self.AddButton(G.BTN_RESET_ALL, c4d.BFH_SCALEFIT, 0, 0, "Reset All")
        self.AddButton(G.BTN_FORCE_VERTICAL, c4d.BFH_SCALEFIT, 0, 0, "Force 9:16")
        self.GroupEnd()
        self.AddChild(G.PRESET_DROPDOWN, 0, "Previz")
        self.AddChild(G.PRESET_DROPDOWN, 1, "Pre-Render")
        self.AddChild(G.PRESET_DROPDOWN, 2, "Render")
        self.AddChild(G.PRESET_DROPDOWN, 3, "Stills")

        # ── Sentinel Frame (v1.8.0) ──
        # The per-camera tag is the recommended entry point: live viewport
        # guides + one-click, rename-safe delivery Takes with true WYSIWYG crop.
        self._add_section_label("Sentinel Frame")
        self.GroupBegin(80, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_ADD_FRAME_TAG, c4d.BFH_SCALEFIT, 0, 0,
                       "Add Sentinel Frame to camera")
        self.GroupEnd()
        # The legacy Multi-Format Setup dialog + Safe-Area Overlay were retired
        # in v1.8.0 (superseded by the Sentinel Frame tag). The Safe-Area Overlay
        # ObjectData is no longer registered; the MultiFormatDialog stays in the
        # code so takes it already generated keep working, but it is no longer
        # surfaced as a new-work entry point.

        # ── Redshift AOVs ──
        # Compositor + Multi-Part are studio-level defaults edited in Settings
        # (single source of truth). Render tab shows them as info only — to
        # change them, the user goes to the footer ⚙ Settings button.
        self._add_section_label("Redshift AOVs")
        self.AddStaticText(G.LABEL_AOV_INFO, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        self.GroupBegin(82, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_INFO_AOVS, c4d.BFH_SCALEFIT, 0, 0, "Show AOVs")
        self.GroupEnd()

        self.GroupBegin(80, c4d.BFH_SCALEFIT, 3, 0)
        self.AddButton(G.BTN_FORCE_ESSENTIALS, c4d.BFH_SCALEFIT, 0, 0, "Essentials")
        self.AddButton(G.BTN_FORCE_PRODUCTION, c4d.BFH_SCALEFIT, 0, 0, "Production")
        self.AddButton(G.BTN_LIGHT_GROUPS, c4d.BFH_SCALEFIT, 0, 0, "Light Groups")
        self.GroupEnd()

        # Populate the AOV info caption with current settings
        self._update_aov_info_label()

        # ── Snapshots ──
        self._add_section_label("Snapshots")
        self.GroupBegin(61, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(G.LABEL_SNAPSHOT_DIR, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddButton(G.BTN_SET_SNAPSHOT_DIR, c4d.BFH_RIGHT, 60, 0, "Browse")
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_SNAPSHOT, c4d.BFH_SCALEFIT, 0, 0, "Save Still")
        self.AddButton(G.BTN_OPEN_FOLDER, c4d.BFH_SCALEFIT, 0, 0, "Open Folder")
        self.GroupEnd()

        # Spacer absorbs remaining vertical space
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _build_tab_versions(self):
        """Build Versions tab content."""
        # ── Scene Notes ──
        self._add_section_label("Scene Notes", first=True)
        self.GroupBegin(64, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddStaticText(G.LABEL_NOTES_SUMMARY, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddButton(G.BTN_EDIT_NOTES, c4d.BFH_RIGHT, 110, 0, "Edit Notes...")
        self.GroupEnd()

        # ── Save & Deliver ──
        self._add_section_label("Save & Deliver")
        self.AddStaticText(G.LABEL_LAST_VERSION, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.GroupBegin(62, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_SAVE_VERSION, c4d.BFH_SCALEFIT, 0, 0, "Save Version")
        self.AddButton(G.BTN_COLLECT_SCENE, c4d.BFH_SCALEFIT, 0, 0, "Collect Scene")
        self.GroupEnd()

        # ── Recent Versions ──
        self._add_section_label("Recent Versions")
        self.GroupBegin(63, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Filter", 0)
        self.AddComboBox(G.COMBO_HISTORY_FILTER, c4d.BFH_RIGHT, 100, 0)
        self.GroupEnd()
        for i, label in enumerate(self._HISTORY_FILTER_LABELS):
            self.AddChild(G.COMBO_HISTORY_FILTER, i, label)
        try:
            current_filter = self._history_filter
            for i, f in enumerate(self._HISTORY_FILTERS):
                if f == current_filter:
                    self.SetInt32(G.COMBO_HISTORY_FILTER, i)
                    break
        except Exception:
            self.SetInt32(G.COMBO_HISTORY_FILTER, 0)

        self.AddUserArea(G.HISTORY_CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_FIT, 0, HistoryArea.EMPTY_HEIGHT)
        if self.history_ua is None:
            self.history_ua = HistoryArea()
        self.AttachUserArea(self.history_ua, G.HISTORY_CANVAS)
        self.history_ua.click_callback = self._on_history_row_click

        # Spacer
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _build_tab_tools(self):
        """Build Tools tab content."""
        # ── Layout & Hierarchy ──
        self._add_section_label("Layout & Hierarchy", first=True)
        self.GroupBegin(50, c4d.BFH_SCALEFIT, 4, 0)
        self.AddButton(G.BTN_CREATE_HIERARCHY, c4d.BFH_SCALEFIT, 0, 0, "Hierarchy")
        self.AddButton(G.BTN_HIERARCHY_TO_LAYERS, c4d.BFH_SCALEFIT, 0, 0, "H -> Layers")
        self.AddButton(G.BTN_SOLO, c4d.BFH_SCALEFIT, 0, 0, "Solo Layers")
        self.AddButton(G.BTN_DROP_TO_FLOOR, c4d.BFH_SCALEFIT, 0, 0, "Drop to Floor")
        self.GroupEnd()

        # ── Animation Helpers ── (combined Object + Camera Rigs into one row of 4)
        self._add_section_label("Animation Helpers")
        self.GroupBegin(51, c4d.BFH_SCALEFIT, 4, 0)
        self.AddButton(G.BTN_VIBRATE_NULL, c4d.BFH_SCALEFIT, 0, 0, "Vibrate Null")
        self.AddButton(G.BTN_ABC_RETIME, c4d.BFH_SCALEFIT, 0, 0, "ABC Retime")
        self.AddButton(G.BTN_CAM_SIMPLE, c4d.BFH_SCALEFIT, 0, 0, "Cam Simple")
        self.AddButton(G.BTN_CAM_SHAKEL, c4d.BFH_SCALEFIT, 0, 0, "Cam Shakel")
        self.GroupEnd()

        # ── QC Marking ── (drives QC #12 Cross-Aspect Safe-Area check)
        self._add_section_label("QC Marking")
        self.GroupBegin(52, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_MARK_SAFE_AREA, c4d.BFH_SCALEFIT, 0, 0,
                       "Mark / Unmark Safe Area Subject")
        self.GroupEnd()

        # ── Asset Management ── (v1.5.7 Texture Repathing tool)
        self._add_section_label("Asset Management")
        self.GroupBegin(53, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_TEXTURE_REPATH, c4d.BFH_SCALEFIT, 0, 0,
                       "Texture Repathing...")
        self.GroupEnd()

        # Spacer
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _update_aov_info_label(self):
        """Render tab: refresh the read-only Comp + Multi-Part summary.

        The values live in Settings (single source of truth). The Render tab
        shows what the AOV tier buttons will apply.
        """
        try:
            comp_idx = int(GlobalSettings.get('comp_target', 0))
            comp_name = "Nuke" if comp_idx == 0 else "After Effects"
            multipart = bool(int(GlobalSettings.get('aov_multipart', 1)))
            mp_str = "ON" if multipart else "OFF"
            self.SetString(G.LABEL_AOV_INFO,
                           f"Compositor: {comp_name}    ·    Multi-Part EXR: {mp_str}")
        except Exception as e:
            safe_print(f"AOV info label update error: {e}")

    def _update_filename_label(self, doc=None):
        """Refresh the scene identity caption in the panel header.

        Uses '▸' (BMP) instead of the folder emoji because C4D's AddStaticText
        on macOS renders supplementary-plane characters (📁 etc.) as fallback
        glyphs. ▸ is a basic-multilingual-plane char that renders cleanly.
        """
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if not doc:
            self.SetString(G.LABEL_FILENAME, "▸ Scene:  (no document)")
            return
        name = doc.GetDocumentName() or ""
        if not name:
            self.SetString(G.LABEL_FILENAME, "▸ Scene:  Untitled  ·  not saved yet")
            return
        # Show the full filename including version + status — the user is
        # working ON this exact file; transparency over abstraction.
        self.SetString(G.LABEL_FILENAME, f"▸ Scene:  {name}")

    def _update_snapshot_dir_label(self):
        snap_dir = GlobalSettings.get_snapshot_dir()
        # Shorten for display: show last 2 path components
        parts = snap_dir.replace("\\", "/").rstrip("/").split("/")
        short = "/".join(parts[-2:]) if len(parts) > 2 else snap_dir
        self.SetString(G.LABEL_SNAPSHOT_DIR, f"Snapshots: .../{short}")

    def _update_last_version_label(self, doc=None):
        """Refresh the 'Last version' caption above Save Version button."""
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if not doc:
            self.SetString(G.LABEL_LAST_VERSION, "Last version: —")
            return

        info = get_latest_version_info(doc)
        if not info:
            if doc.GetDocumentPath():
                txt = "Last version: none yet  ·  click Save Version to start"
            else:
                txt = "Last version: —  ·  scene not saved yet"
            self.SetString(G.LABEL_LAST_VERSION, txt)
            return

        try:
            ver = int(info.get("version", 0))
        except Exception:
            ver = 0
        status = info.get("status", "") or ""
        ts = info.get("timestamp", "")
        rel = _humanize_time_diff(ts)
        status_str = status if status else "WIP"
        rel_part = f"  ·  {rel}" if rel else ""
        qc_label = format_history_qc_label(info)
        qc_part = f"  ·  QC {qc_label}" if qc_label else ""
        self.SetString(G.LABEL_LAST_VERSION, f"Last version: v{ver:03d} {status_str}{rel_part}{qc_part}")

    def _update_notes_summary(self, doc=None):
        """Refresh the Notes summary caption above the Edit Notes button."""
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if not doc:
            self.SetString(G.LABEL_NOTES_SUMMARY, "Notes: —")
            return
        notes_path = get_notes_path(doc)
        if not notes_path:
            self.SetString(G.LABEL_NOTES_SUMMARY, "Notes: —  ·  scene not saved yet")
            return
        notes = load_notes(notes_path)
        summary = summarize_notes(notes)
        if has_pending_todos(notes):
            # Lightweight visual cue that there's something pending
            summary = f"⚠ {summary}"
        self.SetString(G.LABEL_NOTES_SUMMARY, summary)

    # Filter combobox value mapping (combobox index -> filter token)
    _HISTORY_FILTERS = [FILTER_ALL, "", "TR", "CR", "FINAL"]
    _HISTORY_FILTER_LABELS = ["All", "WIP", "TR", "CR", "FINAL"]

    def _update_history_area(self, doc=None):
        """Refresh the Recent Versions list (HistoryArea)."""
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if self.history_ua is None:
            return
        if not doc:
            self.history_ua.set_entries([])
            return
        versions = load_versions_for_doc(doc)
        # Use explicit None check — '' is the valid WIP filter token, not "no filter".
        active_filter = self._history_filter if self._history_filter is not None else FILTER_ALL
        filtered = filter_versions_by_status(versions, active_filter)
        limited = filtered[: self._history_max_rows]
        formatted = [format_version_row(e) for e in limited if e]
        formatted = [f for f in formatted if f]
        # Set empty message based on context
        if not versions:
            if doc.GetDocumentPath():
                self.history_ua.empty_msg = "No versions yet — click Save Version"
            else:
                self.history_ua.empty_msg = "Save the scene first"
        elif not formatted:
            label = "WIP" if active_filter == "" else (active_filter if active_filter != FILTER_ALL else "All")
            self.history_ua.empty_msg = f"No versions match filter ({label})"
        else:
            self.history_ua.empty_msg = "No versions yet"
        self.history_ua.set_entries(formatted)

    # ---- read scene -> UI
    def _sync_from_doc(self, doc):
        """Sync UI with document state"""
        if not doc:
            return

        try:
            td = None
            try:
                td = doc.GetTakeData()
            except Exception:
                try:
                    td = documents.GetTakeData(doc)
                except Exception:
                    pass

            shot = ""
            if td:
                main_take = td.GetMainTake()
                if main_take:
                    shot = main_take.GetName() or ""
            self.SetString(G.SHOT, shot)
        except Exception as e:
            safe_print(f"Error syncing shot name: {e}")

        try:
            ard = doc.GetActiveRenderData()
            if ard:
                name = normalize_preset_name(ard.GetName() or "")
                if name in PRESETS:
                    self._active_preset = name
                self._update_preset_buttons()
        except Exception as e:
            safe_print(f"Error syncing render preset: {e}")

    # ---- write UI -> scene
    def _apply_shot(self, doc):
        if not doc:
            return

        try:
            name = self.GetString(G.SHOT)
            td = None

            try:
                td = doc.GetTakeData()
            except Exception:
                try:
                    td = documents.GetTakeData(doc)
                except Exception:
                    pass

            if td:
                main_take = td.GetMainTake()
                if main_take:
                    main_take.SetName(name)
                    c4d.EventAdd()
        except Exception as e:
            safe_print(f"Error applying shot name: {e}")

    def _apply_preset(self, doc, preset_name):
        """Apply preset - accepts pre_render, pre-render, Pre-Render, etc."""
        if not doc:
            return

        try:
            # Normalize the target preset name
            normalized_target = normalize_preset_name(preset_name)
            rd = doc.GetFirstRenderData()

            while rd:
                # Normalize the render data name for comparison
                normalized_rd = normalize_preset_name(rd.GetName() or "")
                if normalized_rd == normalized_target:
                    doc.SetActiveRenderData(rd)
                    check_cache.clear()  # Clear cache to update compliance check immediately
                    c4d.EventAdd()
                    self._active_preset = normalized_target
                    self._update_preset_buttons()
                    safe_print(f"Switched to render preset: {rd.GetName()} (normalized: {normalized_target})")
                    break
                rd = rd.GetNext()
        except Exception as e:
            safe_print(f"Error applying render preset: {e}")

    def _update_preset_buttons(self):
        """Update preset dropdown and resolution label"""
        preset_to_index = {
            "previz": 0, "pre_render": 1, "render": 2, "stills": 3
        }
        normalized_preset = normalize_preset_name(self._active_preset)
        if normalized_preset in preset_to_index:
            self.SetInt32(G.PRESET_DROPDOWN, preset_to_index[normalized_preset])

        # Update resolution label and aspect button
        doc = c4d.documents.GetActiveDocument()
        if doc:
            rd = doc.GetActiveRenderData()
            if rd:
                try:
                    w = int(rd[c4d.RDATA_XRES])
                    h = int(rd[c4d.RDATA_YRES])
                    self.SetString(G.LABEL_RESOLUTION, f"{w}x{h}")
                    self.SetString(G.BTN_FORCE_VERTICAL, "Force 16:9" if h > w else "Force 9:16")
                except Exception:
                    pass

    def _refresh(self):
        """Throttled refresh with performance optimization"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return

        # Check cooldown
        now = time.time()
        if now - self._last_check_time < CHECK_COOLDOWN:
            return
        rules_context = _active_rules_for_doc(doc)
        rules_identity = rules_context.identity
        self._last_check_time = now
        self._last_rules_identity = rules_identity

        try:
            # Clear stale references before running checks
            check_cache.clear()

            # Run checks from the registry. QC #12 uses "current_frame" via
            # registry kwargs in auto-refresh; click "Info" still upgrades to
            # full keyframe sampling for a complete timeline analysis.
            registry_results = run_all_checks(doc, _current_module(), rules_context)
            baseline_path = _baseline_path_for_doc(doc, only_existing=True)
            if baseline_path:
                score_summary = compute_score(
                    registry_results,
                    rules_context,
                    baseline_path=baseline_path,
                    current_params=rules_context.params,
                )
            else:
                score_summary = compute_score(registry_results, rules_context)
            counts_by_id = score_summary["counts"]
            legacy_by_id = {
                check_id: pair.get("legacy_result")
                for check_id, pair in registry_results.items()
            }
            lights_bad = legacy_by_id.get("lights") or []
            vis_bad = legacy_by_id.get("vis") or []
            keys_bad = legacy_by_id.get("keys") or []
            cam_bad = legacy_by_id.get("cam") or []
            textures_bad = legacy_by_id.get("textures") or []
            unused_mats_bad = legacy_by_id.get("unused_mats") or []
            names_bad = legacy_by_id.get("names") or []
            output_bad = legacy_by_id.get("output") or []
            takes_bad = legacy_by_id.get("takes") or []
            fps_range_bad = legacy_by_id.get("fps_range") or []
            cross_aspect_bad = legacy_by_id.get("cross_aspect") or []
            scene_stats = get_scene_stats(doc)

            # Count issues
            lights_count = counts_by_id.get("lights", 0)
            vis_count = counts_by_id.get("vis", 0)
            keys_count = counts_by_id.get("keys", 0)
            cam_count = counts_by_id.get("cam", 0)
            rdc_count = counts_by_id.get("rdc", 0)
            textures_count = counts_by_id.get("textures", 0)
            unused_mats_count = counts_by_id.get("unused_mats", 0)
            names_count = counts_by_id.get("names", 0)
            output_count = counts_by_id.get("output", 0)
            takes_count = counts_by_id.get("takes", 0)
            fps_range_count = counts_by_id.get("fps_range", 0)
            cross_aspect_count = counts_by_id.get("cross_aspect", 0)

            # Update StatusArea (only if QC tab has been built — when the
            # panel reopens on a non-QC tab, self.ua stays None until the
            # user clicks QC. Score header still updates regardless because
            # it lives in the always-visible Scene Header.)
            if self.ua is not None:
                state = dict(counts_by_id)
                state["_disabled_checks"] = score_summary.get("disabled", [])
                state["_baseline_active"] = bool(score_summary.get("baseline_status"))
                state["_severity_by_id"] = {
                    entry.check_id: entry_severity(entry, rules_context)
                    for entry in CHECK_REGISTRY
                }
                state["_baseline_counts"] = {
                    entry.check_id: {
                        "new": score_summary.get("new_counts", counts_by_id).get(entry.check_id, counts_by_id.get(entry.check_id, 0)),
                        "accepted": score_summary.get("accepted_counts", {}).get(entry.check_id, 0),
                        "stale": score_summary.get("stale_counts", {}).get(entry.check_id, 0),
                    }
                    for entry in CHECK_REGISTRY
                }
                for entry in CHECK_REGISTRY:
                    if entry.names_key:
                        items = legacy_by_id.get(entry.check_id) or []
                        state[entry.names_key] = [_safe_name(o) for o in items[:10]]
                self.ua.set_state(state, self.ua.show)

            # Update Score header — pass count + scene stats summary
            total_checks = score_summary["total"]
            passed = score_summary["passed"]
            stats_str = ""
            if scene_stats:
                # Compact one-liner: "1.2M polys · 47 mats · 12 lights"
                polys = scene_stats.get("polygons", 0)
                if polys >= 1_000_000:
                    poly_str = f"{polys/1_000_000:.1f}M polys"
                elif polys >= 1_000:
                    poly_str = f"{polys/1_000:.0f}K polys"
                else:
                    poly_str = f"{polys} polys"
                stats_str = f"{poly_str}  ·  {scene_stats.get('materials', 0)} mats  ·  {scene_stats.get('lights', 0)} lights"
            baseline_warning = score_summary.get("baseline_warning")
            if baseline_warning:
                stats_str = f"{stats_str}  ·  {baseline_warning}" if stats_str else baseline_warning
            if self.score_ua is not None:
                self.score_ua.set_state(passed, total_checks, stats_str)
            try:
                self.SetString(G.LABEL_RULES, _rules_header_text(rules_context))
            except Exception:
                pass

            # Store results
            self._lights_bad = lights_bad
            self._vis_bad = vis_bad
            self._keys_bad = keys_bad
            self._cam_bad = cam_bad
            self._textures_bad = textures_bad
            self._scene_stats = scene_stats
            # Reset cycling indices when result count changes
            if len(unused_mats_bad) != len(self._unused_mats_bad):
                self._unused_mats_idx = 0
            if len(names_bad) != len(self._names_bad):
                self._names_idx = 0

            self._unused_mats_bad = unused_mats_bad
            self._names_bad = names_bad
            self._output_bad = output_bad
            self._takes_bad = takes_bad
            self._fps_range_bad = fps_range_bad
            self._cross_aspect_bad = cross_aspect_bad
            self._registry_results = registry_results
            self._qc_summary = score_summary
            self._rules_context = rules_context

            # Refresh header captions + Recent Versions list (all cheap reads)
            self._update_filename_label(doc)
            self._update_last_version_label(doc)
            self._update_history_area(doc)
            self._update_notes_summary(doc)

        except Exception as e:
            safe_print(f"Error during refresh: {e}")

    # ---- layout
    def CreateLayout(self):
        self.SetTitle(PLUGIN_NAME)

        # Main container
        self.GroupBegin(1, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(4, 4, 4, 4)

        # ── Scene Header (always visible — scene identity + project meta + QC bar) ──
        self.GroupBegin(9, c4d.BFH_SCALEFIT, 1, 0)
        self.GroupBorder(c4d.BORDER_THIN_IN)
        self.GroupBorderSpace(6, 4, 6, 4)
        self.GroupSpace(0, 4)

        # Filename caption — read-only, prominent, centered
        self.AddStaticText(G.LABEL_FILENAME, c4d.BFH_CENTER, 0, 0, "", 0)

        # Editable project metadata: Shot ID + Artist
        self.GroupBegin(10, c4d.BFH_SCALEFIT, 4, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Shot ID", 0)
        self.AddEditText(G.SHOT, c4d.BFH_SCALEFIT, 80, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Artist  ", 0)
        self.AddEditText(G.ARTIST, c4d.BFH_SCALEFIT, 100, 0)
        self.GroupEnd()

        # Score line (was inside QC group; now in the always-visible header)
        self.AddUserArea(G.SCORE_CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_FIT, 0, ScoreHeader.HEIGHT)
        self.score_ua = ScoreHeader()
        self.AttachUserArea(self.score_ua, G.SCORE_CANVAS)
        self.AddStaticText(G.LABEL_RULES, c4d.BFH_LEFT, 0, 0, "Rules: defaults", 0)

        self.GroupEnd()  # end Scene Header

        # ── Tab bar ──
        self.AddSeparatorH(4)
        tab_bc = c4d.BaseContainer()
        tab_bc.SetBool(c4d.QUICKTAB_BAR, False)         # tab style (not bar)
        tab_bc.SetBool(c4d.QUICKTAB_SHOWSINGLE, True)
        tab_bc.SetBool(c4d.QUICKTAB_NOMULTISELECT, True)
        self._quicktab = self.AddCustomGui(
            G.TAB_BAR, c4d.CUSTOMGUI_QUICKTAB, "",
            c4d.BFH_SCALEFIT, 0, 0, tab_bc
        )
        if self._quicktab is not None:
            # Mark the persisted-active tab as selected on startup
            self._quicktab.AppendString(0, "QC", self._active_tab == 0)
            self._quicktab.AppendString(1, "Render", self._active_tab == 1)
            self._quicktab.AppendString(2, "Versions", self._active_tab == 2)
            self._quicktab.AppendString(3, "Tools", self._active_tab == 3)

        # ── Tab content container — only the active tab's content lives inside.
        # Switching tabs flushes this group and rebuilds with the new content
        # (HideElement does not collapse layout space in C4D 2026).
        self.GroupBegin(G.TAB_CONTAINER, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 1, 0)
        self._build_active_tab_content()
        self.GroupEnd()

        # ───────── Footer (always visible) — secondary actions ─────────
        self.AddSeparatorH(4)
        self.GroupBegin(70, c4d.BFH_SCALEFIT, 3, 0)
        self.AddButton(G.BTN_SETTINGS, c4d.BFH_SCALEFIT, 0, 0, "⚙ Settings")
        self.AddButton(G.BTN_GITHUB, c4d.BFH_SCALEFIT, 0, 0, "GitHub")
        self.AddButton(G.BTN_BUG_REPORT, c4d.BFH_SCALEFIT, 0, 0, "Report Bug")
        self.GroupEnd()

        self.GroupEnd()  # Main container

        self.SetTimer(3000)
        return True

    def InitValues(self):
        # Load artist name from computer-level settings
        self._artist_name = GlobalSettings.load_artist_name()
        if self._artist_name:
            self.SetString(G.ARTIST, self._artist_name)

        # Initialize active preset
        self._active_preset = "previz"
        self._history_filter = FILTER_ALL

        # Header captions (always visible — outside tabs)
        self._update_filename_label()

        # The QC tab was built in CreateLayout — refresh its caption-driven
        # widgets and the cross-tab labels (snapshot dir, last version, notes).
        # Other tabs' widgets are populated when the user switches to them.
        self._update_snapshot_dir_label()
        self._update_last_version_label()
        self._update_notes_summary()
        self._update_history_area()

        doc = c4d.documents.GetActiveDocument()
        self._sync_from_doc(doc)
        self._refresh()
        self._last_doc = doc
        return True

    def _new_violations_for_row(self, row_key):
        if self._qc_summary and self._qc_summary.get("baseline_matches"):
            match = self._qc_summary.get("baseline_matches", {}).get(row_key, {}) or {}
            return list(match.get("new") or [])

        result_pair = (self._registry_results or {}).get(row_key, {}) if self._registry_results else {}
        structured = result_pair.get("structured_result")
        raw = []
        if isinstance(structured, dict):
            raw = structured.get("violations") or []
        elif structured is not None:
            raw = getattr(structured, "violations", []) or []
        items = []
        for violation in raw:
            if isinstance(violation, dict):
                item = dict(violation)
                item["check_id"] = row_key
                items.append(item)
        return items

    def _baseline_counts_for_row(self, row_key):
        summary = self._qc_summary or {}
        return {
            "new": summary.get("new_counts", summary.get("counts", {})).get(row_key, 0),
            "accepted": summary.get("accepted_counts", {}).get(row_key, 0),
            "stale": summary.get("stale_counts", {}).get(row_key, 0),
        }

    def _row_entry(self, row_key):
        for entry in CHECK_REGISTRY:
            if entry.check_id == row_key:
                return entry
        return None

    def _show_baseline_actions(self, row_key):
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return False

        new_items = self._new_violations_for_row(row_key)
        counts = self._baseline_counts_for_row(row_key)
        if not new_items and not counts.get("accepted") and not counts.get("stale"):
            return False

        baseline_path = _baseline_path_for_doc(doc, only_existing=False)
        if not baseline_path:
            return False

        entry = self._row_entry(row_key)
        row_label = entry.row_label if entry else row_key
        dlg = BaselineActionDialog(
            row_label,
            new_items,
            counts.get("accepted", 0),
            counts.get("stale", 0),
        )
        try:
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=520, defaulth=320)
        except Exception as e:
            safe_print(f"BaselineActionDialog open error: {e}")
            return True

        if dlg.action == "accept":
            author = baseline.resolve_author(self._artist_name)
            rules_context = self._rules_context or _active_rules_for_doc(doc)
            written = 0
            for item in new_items:
                acceptance = baseline.entry_from_violation(
                    item,
                    author=author,
                    reason=dlg.reason,
                    current_params=getattr(rules_context, "params", {}),
                )
                if acceptance and baseline.add_acceptance(baseline_path, acceptance):
                    written += 1
            check_cache.clear()
            self._last_check_time = 0
            self._dirty = True
            self._refresh()
            c4d.gui.MessageDialog(f"Aceptadas {written} violacion(es) para {row_label}.")
            return True

        if dlg.action == "retire":
            ok = baseline.remove_acceptances_for_check(baseline_path, row_key)
            check_cache.clear()
            self._last_check_time = 0
            self._dirty = True
            self._refresh()
            if ok:
                c4d.gui.MessageDialog(f"Aceptaciones retiradas para {row_label}.")
            else:
                c4d.gui.MessageDialog("Could not update the baseline sidecar.")
            return True

        return True

    def _on_qc_row_click(self, row_key):
        """Called by StatusArea when the user clicks a QC row.
        Routes to the same handler as the primary button (Select or Info)."""
        if self._show_baseline_actions(row_key):
            return
        primary = {
            "lights":      G.BTN_SEL_LIGHTS,
            "vis":         G.BTN_SEL_VIS,
            "keys":        G.BTN_SEL_KEYS,
            "cam":         G.BTN_SEL_CAMS,
            "rdc":         G.BTN_INFO_PRESET,
            "textures":    G.BTN_INFO_TEXTURES,
            "unused_mats": G.BTN_SEL_UNUSED_MATS,
            "names":       G.BTN_SEL_NAMES,
            "output":       G.BTN_INFO_OUTPUT,
            "takes":        G.BTN_INFO_TAKES,
            "fps_range":    G.BTN_INFO_FPS,
            "cross_aspect": G.BTN_INFO_CROSS_ASPECT,
        }
        btn_id = primary.get(row_key)
        if btn_id is not None:
            try:
                self.Command(btn_id, c4d.BaseContainer())
            except Exception as e:
                safe_print(f"Row click dispatch error: {e}")

    def _on_history_row_click(self, entry):
        """Called by HistoryArea when the user clicks a version row.
        Confirms with the user, then opens the .c4d file via LoadFile.
        Warns about unsaved changes in the current document.
        """
        if not entry:
            return
        path = (entry.get("path") or "").strip()
        filename = entry.get("filename") or os.path.basename(path) or "(unknown)"

        if not path or not os.path.exists(path):
            c4d.gui.MessageDialog(
                f"File not found:\n  {filename}\n\n"
                f"It may have been moved, renamed, or deleted.\n"
                f"The history entry remains in the JSON for reference."
            )
            return

        # Don't reopen the current doc
        current = c4d.documents.GetActiveDocument()
        if current:
            try:
                cur_full = os.path.join(current.GetDocumentPath() or "", current.GetDocumentName() or "")
                if os.path.normcase(os.path.normpath(cur_full)) == os.path.normcase(os.path.normpath(path)):
                    c4d.gui.MessageDialog(f"Already viewing {filename}.")
                    return
            except Exception:
                pass

        # Build confirmation prompt
        version_label = entry.get("version_label", "")
        status_label = entry.get("status_label", "")
        comment = entry.get("comment", "") or "(no comment)"
        ts = entry.get("time_label", "")

        prompt_lines = [
            f"Open {filename}?",
            "",
            f"  {version_label}  [{status_label}]  ·  {ts}",
            f"  \"{comment}\"",
        ]
        # Warn about unsaved changes in the current doc
        try:
            if current and current.GetChanged():
                prompt_lines.append("")
                prompt_lines.append("⚠ Current document has unsaved changes.")
                prompt_lines.append("The new file will open in a separate Cinema 4D window.")
        except Exception:
            pass

        if not c4d.gui.QuestionDialog("\n".join(prompt_lines)):
            return

        # Open the file
        try:
            ok = c4d.documents.LoadFile(path)
            if ok:
                safe_print(f"Opened {filename} via Browse Versions")
                self._dirty = True  # force panel refresh against new doc
            else:
                c4d.gui.MessageDialog(
                    f"Cinema 4D could not open:\n  {filename}\n\n"
                    f"(LoadFile returned False — file may be locked or corrupted)"
                )
        except Exception as e:
            c4d.gui.MessageDialog(f"Error opening file:\n\n{e}")
            safe_print(f"Browse Versions LoadFile error: {e}")

    def Timer(self, msg):
        doc = c4d.documents.GetActiveDocument()

        # Document change detection
        if doc is not self._last_doc:
            check_cache.clear()
            self._sync_from_doc(doc)
            self._dirty = True
            self._last_doc = doc

        # Only refresh if dirty or cache expired
        if self._dirty:
            self._dirty = False
            self._refresh()
        else:
            self._refresh()  # Cache handles skip if still valid

    def CoreMessage(self, id, msg):
        if id == c4d.EVMSG_CHANGE:
            self._dirty = True  # Don't clear cache or refresh here - let Timer handle it
            return True

        if id == 431000159:  # EVMSG_TAKECHANGED
            doc = c4d.documents.GetActiveDocument()
            if doc:
                self._sync_from_doc(doc)
            self._dirty = True
            return True

        return gui.GeDialog.CoreMessage(self, id, msg)

    def Command(self, cid, msg):
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return True

        if cid == G.SHOT:
            self._apply_shot(doc)

        # Handle preset dropdown selection
        elif cid == G.PRESET_DROPDOWN:
            selected_index = self.GetInt32(G.PRESET_DROPDOWN)
            index_to_preset = {0: "previz", 1: "pre_render", 2: "render", 3: "stills"}
            if selected_index in index_to_preset:
                self._apply_preset(doc, index_to_preset[selected_index])

        elif cid == G.BTN_FORCE_VERTICAL:
            self._toggle_aspect(doc)

        elif cid == G.BTN_RESET_ALL:
            self._force_render_settings(doc)

        elif cid == G.BTN_ADD_FRAME_TAG:
            self._add_sentinel_frame_tag(doc)

        elif cid == G.ARTIST:
            # Artist name changed - save to global settings
            new_artist_name = self.GetString(G.ARTIST).strip()
            if new_artist_name != self._artist_name:
                self._artist_name = new_artist_name
                GlobalSettings.save_artist_name(self._artist_name)

        elif cid == G.BTN_SNAPSHOT:
            self._take_renderview_snapshot()

        # Note: G.COMP_TARGET and G.CHK_MULTIPART used to live in the Render tab
        # as editable widgets. They were moved to Settings (single source of
        # truth) — the Render tab now shows them as info via LABEL_AOV_INFO.

        elif cid == G.BTN_LIGHT_GROUPS:
            self._toggle_light_groups(doc)

        elif cid == G.BTN_INFO_AOVS:
            result = check_rs_aovs(doc, AOV_TIER_PRODUCTION)
            if not result["available"]:
                c4d.gui.MessageDialog("Redshift module not available.\n\nMake sure Redshift is installed and active.")
            elif not result["aovs"]:
                c4d.gui.MessageDialog("No AOVs configured.\n\nUse 'Essentials' or 'Production' to add passes.")
            else:
                target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
                lg_status = "ON" if self._is_lg_active_on_beauty(doc) else "OFF"
                groups, _ = self._scan_light_groups(doc)
                lg_info = f"Light Groups: {lg_status}"
                if groups and lg_status == "ON":
                    lg_info += f" ({', '.join(sorted(groups.keys()))})"
                msg = f"REDSHIFT AOVs: {len(result['aovs'])}  |  Target: {target_name}\n{lg_info}\n\n"
                msg += "ACTIVE:\n"
                for aov in result["aovs"]:
                    status = "ON" if aov.get("enabled") else "OFF"
                    msg += f"  [{status}] {aov['name']}\n"

                # Check against both tiers
                ess = check_rs_aovs(doc, AOV_TIER_ESSENTIALS)
                prod = check_rs_aovs(doc, AOV_TIER_PRODUCTION)

                if ess["missing"]:
                    msg += f"\nMISSING ESSENTIALS ({len(ess['missing'])}):\n"
                    for n in ess["missing"]:
                        msg += f"  ! {n}\n"

                prod_only = [n for n in prod["missing"] if n not in ess["missing"]]
                if prod_only:
                    msg += f"\nMISSING PRODUCTION ({len(prod_only)}):\n"
                    for n in prod_only:
                        msg += f"  - {n}\n"

                if not prod["missing"]:
                    msg += "\nAll Production AOVs present."
                elif not ess["missing"]:
                    msg += "\nAll Essentials AOVs present."

                c4d.gui.MessageDialog(msg)

        elif cid == G.BTN_FORCE_ESSENTIALS:
            self._force_aov_tier(doc, AOV_TIER_ESSENTIALS, "Essentials")

        elif cid == G.BTN_FORCE_PRODUCTION:
            self._force_aov_tier(doc, AOV_TIER_PRODUCTION, "Production")

        elif cid == G.BTN_SET_SNAPSHOT_DIR:
            new_dir = c4d.storage.LoadDialog(title="Select RS Snapshot Folder", flags=c4d.FILESELECT_DIRECTORY)
            if new_dir:
                GlobalSettings.set_snapshot_dir(new_dir)
                self._update_snapshot_dir_label()
                safe_print(f"Snapshot directory set to: {new_dir}")

        elif cid == G.BTN_OPEN_FOLDER:
            self._open_artist_folder()

        elif cid == G.BTN_ABC_RETIME:
            self._apply_abc_retime_tag()

        elif cid == G.BTN_VIBRATE_NULL:
            self._create_vibrate_null(doc)

        elif cid == G.BTN_CAM_SIMPLE:
            self._merge_camera_file(doc, "cam_simple.c4d")

        elif cid == G.BTN_CAM_SHAKEL:
            self._merge_camera_file(doc, "cam_w_shakel.c4d")

        elif cid == G.BTN_CAM_PATH:
            self._merge_camera_file(doc, "cam_path.c4d")

        elif cid == G.BTN_CREATE_HIERARCHY:
            self._create_hierarchy(doc)

        elif cid == G.BTN_DROP_TO_FLOOR:
            self._drop_to_floor(doc)

        elif cid == G.BTN_HIERARCHY_TO_LAYERS:
            self._hierarchy_to_layers(doc)

        elif cid == G.BTN_SOLO:
            self._solo_layers(doc)

        elif cid == G.BTN_MARK_SAFE_AREA:
            self._toggle_safe_area_mark(doc)

        elif cid == G.BTN_TEXTURE_REPATH:
            self._open_texture_repathing(doc)

        elif cid == G.BTN_GITHUB:
            # Open GitHub repository
            github_url = "https://github.com/jmcodex93/sentinel"
            webbrowser.open(github_url)
            safe_print(f"Opening GitHub repository: {github_url}")

        elif cid == G.BTN_BUG_REPORT:
            # Open GitHub issues page for bug reports
            bug_url = "https://github.com/jmcodex93/sentinel/issues/new"
            webbrowser.open(bug_url)
            safe_print(f"Opening bug report page: {bug_url}")

        elif cid == G.BTN_SETTINGS:
            # Open the Sentinel Settings modal dialog
            dlg = SentinelSettingsDialog()
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=480, defaulth=380)
            if dlg.confirmed:
                safe_print("Settings saved")
                # Sync runtime values that aren't read on-demand
                try:
                    self._history_max_rows = int(GlobalSettings.get('history_max_rows', 5))
                except Exception:
                    self._history_max_rows = 5
                # Update labels that may have changed
                self._update_snapshot_dir_label()
                # Rebuild active tab so combos/info reflect new settings AND force
                # a full QC refresh (FPS standard may have changed → check #11)
                self._set_active_tab(self._active_tab)
            else:
                safe_print("Settings edit cancelled")

        # Per-check Select buttons (1 click to select problematic objects)
        elif cid == G.BTN_SEL_LIGHTS:
            if self._lights_bad:
                _select_objects(doc, self._lights_bad)
                safe_print(f"Selected {len(self._lights_bad)} lights outside group")
            else:
                safe_print("No light issues found")

        elif cid == G.BTN_SEL_VIS:
            if self._vis_bad:
                _select_objects(doc, self._vis_bad)
                safe_print(f"Selected {len(self._vis_bad)} objects with visibility mismatch")
            else:
                safe_print("No visibility issues found")

        elif cid == G.BTN_SEL_KEYS:
            if self._keys_bad:
                _select_objects(doc, self._keys_bad)
                safe_print(f"Selected {len(self._keys_bad)} objects with multi-axis keyframes")
            else:
                safe_print("No keyframe issues found")

        elif cid == G.BTN_SEL_CAMS:
            if self._cam_bad:
                _select_objects(doc, self._cam_bad)
                safe_print(f"Selected {len(self._cam_bad)} cameras with non-zero shift")
            else:
                safe_print("No camera shift issues found")

        elif cid == G.BTN_INFO_PRESET:
            rules_context = _active_rules_for_doc(doc)
            approved_presets = list(rules_context.params.get("approved_presets", PRESETS))
            approved_set = {normalize_preset_name(name) for name in approved_presets}
            info_msg = "RENDER PRESETS:\n\n"
            info_msg += f"Standard presets: {', '.join(approved_presets)}\n\n"
            rd = doc.GetFirstRenderData()
            while rd:
                name = rd.GetName()
                normalized = normalize_preset_name(name)
                status = "OK" if normalized in approved_set else "NON-STANDARD"
                info_msg += f"  [{status}] {name}\n"
                rd = rd.GetNext()
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_TEXTURES:
            if self._textures_bad:
                absolute = [t for t in self._textures_bad if t["issue"] == "absolute"]
                missing = [t for t in self._textures_bad if t["issue"] == "missing"]
                info_msg = f"ASSET ISSUES: {len(self._textures_bad)}\n\n"
                if absolute:
                    info_msg += f"ABSOLUTE PATHS ({len(absolute)}):\n"
                    for i, t in enumerate(absolute[:10], 1):
                        info_msg += f"  {i}. {t['source']}\n     {t['path']}\n"
                    info_msg += "\n"
                if missing:
                    info_msg += f"MISSING FILES ({len(missing)}):\n"
                    for i, t in enumerate(missing[:10], 1):
                        info_msg += f"  {i}. {t['source']}\n     {t['path']}\n"
                    info_msg += "\n"
                info_msg += ("Open the Texture Repathing tool to fix these "
                             "in bulk (find/replace, make relative, "
                             "auto-find missing)?")
                if c4d.gui.QuestionDialog(info_msg):
                    self._open_texture_repathing(doc)
            else:
                c4d.gui.MessageDialog(
                    "All assets OK. No absolute paths or missing files.")

        elif cid == G.BTN_SEL_UNUSED_MATS:
            if self._unused_mats_bad:
                # Cycle through unused materials one by one
                if self._unused_mats_idx >= len(self._unused_mats_bad):
                    self._unused_mats_idx = 0

                mat = self._unused_mats_bad[self._unused_mats_idx]
                # Deselect all materials first
                for m in doc.GetMaterials():
                    m.DelBit(c4d.BIT_ACTIVE)
                # Select this one
                mat.SetBit(c4d.BIT_ACTIVE)
                c4d.EventAdd()

                safe_print(f"Unused material [{self._unused_mats_idx + 1}/{len(self._unused_mats_bad)}]: '{mat.GetName()}'")
                self._unused_mats_idx += 1
            else:
                safe_print("No unused materials found")

        elif cid == G.BTN_SEL_NAMES:
            if self._names_bad:
                # Cycle through default-named objects one by one
                if self._names_idx >= len(self._names_bad):
                    self._names_idx = 0

                obj = self._names_bad[self._names_idx]
                _select_objects(doc, [obj])

                safe_print(f"Default name [{self._names_idx + 1}/{len(self._names_bad)}]: '{obj.GetName()}'")
                self._names_idx += 1
            else:
                safe_print("No naming issues found")

        elif cid == G.BTN_INFO_OUTPUT:
            if hasattr(self, '_output_bad') and self._output_bad:
                info_msg = f"OUTPUT PATH ISSUES: {len(self._output_bad)}\n\n"
                for i, issue in enumerate(self._output_bad[:10], 1):
                    info_msg += f"{i}. [{issue['preset']}] {issue['issue']}\n"
                info_msg += "\nUse $prj and $take tokens in output paths."
            else:
                info_msg = "All output paths are properly configured."
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_TAKES:
            if self._takes_bad:
                info_msg = f"TAKE ISSUES: {len(self._takes_bad)}\n\n"
                for i, t in enumerate(self._takes_bad[:20], 1):
                    info_msg += f"{i}. [{t['take']}] {t['issue']}\n"
            else:
                # Check if there are any takes at all
                td = doc.GetTakeData()
                has_takes = td and td.GetMainTake() and td.GetMainTake().GetDown()
                if has_takes:
                    info_msg = "All takes properly configured."
                else:
                    info_msg = "No takes found (only Main Take)."
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_FPS:
            rules_context = _active_rules_for_doc(doc)
            standard_fps = int(rules_context.params.get("standard_fps", GlobalSettings.get_standard_fps()))
            start_frame = int(rules_context.params.get("start_frame", 1001))
            doc_fps = doc.GetFps()
            rd = doc.GetActiveRenderData()
            info_msg = f"FPS & FRAME RANGE\n\n"
            info_msg += f"Document FPS: {doc_fps} (standard: {standard_fps})\n"
            if rd:
                preset_name = rd.GetName()
                preset_norm = normalize_preset_name(preset_name)
                is_stills = preset_norm == "stills"
                rd_fps = int(rd[c4d.RDATA_FRAMERATE])
                frame_start = rd[c4d.RDATA_FRAMEFROM].GetFrame(rd_fps)
                frame_end = rd[c4d.RDATA_FRAMETO].GetFrame(rd_fps)
                frame_mode = rd[c4d.RDATA_FRAMESEQUENCE]
                mode_names = {
                    c4d.RDATA_FRAMESEQUENCE_ALLFRAMES: "All Frames",
                    c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME: "Current Frame",
                    c4d.RDATA_FRAMESEQUENCE_MANUAL: "Manual",
                }
                mode_str = mode_names.get(frame_mode, f"Unknown ({frame_mode})")
                info_msg += f"Active preset: {preset_name}"
                info_msg += " (stills mode)\n" if is_stills else "\n"
                info_msg += f"Render FPS: {rd_fps}\n"
                info_msg += f"Render range: {frame_start} - {frame_end} ({frame_end - frame_start + 1} frames)\n"
                info_msg += f"Frame mode: {mode_str}\n"

                # Timeline + loop range + playhead
                tl_min = doc[c4d.DOCUMENT_MINTIME].GetFrame(doc_fps)
                tl_max = doc[c4d.DOCUMENT_MAXTIME].GetFrame(doc_fps)
                loop_min = doc[c4d.DOCUMENT_LOOPMINTIME].GetFrame(doc_fps)
                loop_max = doc[c4d.DOCUMENT_LOOPMAXTIME].GetFrame(doc_fps)
                playhead = doc.GetTime().GetFrame(doc_fps)
                info_msg += f"Timeline: {tl_min} - {tl_max}\n"
                info_msg += f"Preview/loop: {loop_min} - {loop_max}\n"
                info_msg += f"Playhead: frame {playhead}\n"

                if is_stills:
                    info_msg += f"\nStills: 'Current Frame' is OK; range start expected at {start_frame}."
                else:
                    info_msg += f"\nAnimation: timeline + preview must match render range."
            if self._fps_range_bad:
                info_msg += f"\n\nISSUES ({len(self._fps_range_bad)}):\n"
                for i, issue in enumerate(self._fps_range_bad, 1):
                    info_msg += f"  {i}. {issue['issue']}\n"
            else:
                info_msg += "\n\nAll OK."
            info_msg += f"\n\nTo change standard FPS, edit sentinel_settings.json."
            c4d.gui.MessageDialog(info_msg)

        # ── Auto-fix handlers ──
        elif cid == G.BTN_FIX_LIGHTS:
            if self._lights_bad:
                count = fix_lights(doc, self._lights_bad)
                safe_print(f"Moved {count} lights into 'lights' group")
                c4d.gui.MessageDialog(f"Moved {count} light(s) into 'lights' group.\n\nUndo available (Ctrl+Z).")
            else:
                safe_print("No light issues to fix")

        elif cid == G.BTN_FIX_CAMS:
            if self._cam_bad:
                count = fix_camera_shift(doc, self._cam_bad)
                safe_print(f"Reset shift on {count} cameras")
                c4d.gui.MessageDialog(f"Reset shift to 0 on {count} camera(s).\n\nUndo available (Ctrl+Z).")
            else:
                safe_print("No camera shift issues to fix")

        elif cid == G.BTN_FIX_UNUSED_MATS:
            if self._unused_mats_bad:
                count = len(self._unused_mats_bad)
                if c4d.gui.QuestionDialog(f"Delete {count} unused material(s)?\n\nThis can be undone (Ctrl+Z)."):
                    deleted = fix_unused_materials(doc, self._unused_mats_bad)
                    safe_print(f"Deleted {deleted} unused materials")
                    self._unused_mats_idx = 0
            else:
                safe_print("No unused materials to delete")

        elif cid == G.BTN_FIX_FPS:
            if self._fps_range_bad:
                rules_context = _active_rules_for_doc(doc)
                standard_fps = int(rules_context.params.get("standard_fps", GlobalSettings.get_standard_fps()))
                start_frame = int(rules_context.params.get("start_frame", 1001))
                # Build confirmation listing what will change
                count = len(self._fps_range_bad)
                preview = f"FIX FPS / FRAME RANGE\n\n"
                preview += f"Standard: {standard_fps} fps, start frame {start_frame}\n\n"
                preview += f"Issues to fix ({count}):\n"
                for issue in self._fps_range_bad[:15]:
                    preview += f"  - {issue['issue']}\n"
                if count > 15:
                    preview += f"  ... and {count - 15} more\n"
                preview += "\nThis will modify ALL render presets, document FPS, "
                preview += "timeline, and preview range. Undo available (Ctrl+Z).\n\n"
                preview += "Continue?"

                if c4d.gui.QuestionDialog(preview):
                    fixes = fix_fps_range(doc)
                    if fixes:
                        fix_msg = f"Applied {len(fixes)} fix(es):\n\n"
                        for f in fixes[:25]:
                            fix_msg += f"  - {f}\n"
                        if len(fixes) > 25:
                            fix_msg += f"  ... and {len(fixes) - 25} more\n"
                        c4d.gui.MessageDialog(fix_msg)
                        self._dirty = True
                    else:
                        c4d.gui.MessageDialog("No fixes were applied.")
                else:
                    safe_print("FPS/range fix cancelled by user")
            else:
                safe_print("No FPS/range issues to fix")

        # ── QC #12: Cross-Aspect Safe Area ──
        elif cid == G.BTN_SEL_CROSS_ASPECT:
            # Select the unique objects that have at least one violation
            # (across any format). Useful for jumping to "what needs to be
            # fixed" — once selected, the artist can scrub the timeline +
            # check the Info dialog to see which formats / frames violate.
            objs = []
            seen = set()
            for v in (self._cross_aspect_bad or []):
                obj = v.get("object")
                if obj is None:
                    continue
                key = id(obj)
                if key in seen:
                    continue
                seen.add(key)
                objs.append(obj)
            if not objs:
                c4d.gui.MessageDialog(
                    "No cross-aspect safe-area violations.\n\n"
                    "Either no objects are marked as Safe Area subjects, "
                    "no Multi-Format Takes exist, or all marked subjects "
                    "stay inside their per-format safe areas at the current "
                    "frame.\n\nTip: click 'Info' to run a full keyframe sweep."
                )
            else:
                doc.SetActiveObject(None, c4d.SELECTION_NEW)
                for obj in objs:
                    try:
                        doc.SetActiveObject(obj, c4d.SELECTION_ADD)
                    except Exception:
                        pass
                c4d.EventAdd()
                safe_print(f"Selected {len(objs)} cross-aspect violator(s)")

        elif cid == G.BTN_INFO_CROSS_ASPECT:
            # Run a FULL keyframe-sample analysis (more expensive than the
            # current-frame sweep used by the auto-refresh). This gives the
            # artist a per-(object × format × frames) breakdown.
            marked_count = len(find_marked_safe_area_objects(doc) or [])
            mf_count = len(find_active_multiformat_takes(doc) or [])

            if marked_count == 0:
                c4d.gui.MessageDialog(
                    "No objects marked as Safe Area subjects.\n\n"
                    "Mark important compositional elements (logo, title, "
                    "character) via Tools tab → 'Mark as Safe Area Subject' "
                    "with the objects selected. Marks persist with the "
                    "scene file (stored as UserData on each object)."
                )
            elif mf_count == 0:
                c4d.gui.MessageDialog(
                    "No Multi-Format delivery Takes detected.\n\n"
                    "Generate them first via Render tab → 'Generate Format "
                    "Takes...'. The check looks at each Take's safe area "
                    "(per-format insets covering platform UI overlays) and "
                    "verifies your marked subjects stay inside."
                )
            else:
                # Run with full sampling. May take a moment on heavy scenes.
                violations = check_cross_aspect_safe_area(
                    doc, sample_strategy="keyframes")
                # Update the cached state so subsequent Select uses the
                # full-sweep results (more accurate than current_frame).
                self._cross_aspect_bad = violations

                lines = [f"Cross-Aspect Safe-Area Check (full keyframe sweep)",
                         "",
                         f"Marked subjects:    {marked_count}",
                         f"Multi-Format Takes: {mf_count}",
                         ""]

                if not violations:
                    lines.append(
                        "✓ All subjects fit within every active format's safe area."
                    )
                else:
                    # Group violations by object for readability
                    by_obj = {}
                    for v in violations:
                        by_obj.setdefault(v["object_name"], []).append(v)

                    lines.append(f"⚠ {len(violations)} violation(s) "
                                 f"across {len(by_obj)} subject(s):")
                    lines.append("")
                    for obj_name in sorted(by_obj.keys()):
                        lines.append(f"  • {obj_name}")
                        for v in by_obj[obj_name]:
                            sides = ", ".join(sorted(v["sides"]))
                            frames = v["frames"]
                            if len(frames) == 1:
                                fr_str = f"frame {frames[0]}"
                            elif len(frames) <= 6:
                                fr_str = f"frames {','.join(str(f) for f in frames)}"
                            else:
                                fr_str = (f"frames {frames[0]}–{frames[-1]} "
                                          f"({len(frames)} samples)")
                            lines.append(f"      ✗ {v['fmt_id']}: "
                                         f"out by {sides} @ {fr_str}")

                    lines.append("")
                    lines.append("Tip: 'Select' button highlights all violating "
                                 "subjects so you can scrub the timeline.")

                c4d.gui.MessageDialog("\n".join(lines))

        # ── Export QC Report ──
        elif cid == G.BTN_EXPORT_QC:
            results = {
                "lights_bad": self._lights_bad,
                "vis_bad": self._vis_bad,
                "keys_bad": self._keys_bad,
                "cam_bad": self._cam_bad,
                "rdc_count": int(check_render_conflicts(doc) or 0),
                "textures_bad": self._textures_bad,
                "unused_mats_bad": self._unused_mats_bad,
                "names_bad": self._names_bad,
                "output_bad": self._output_bad,
                "takes_bad": self._takes_bad,
                "fps_range_bad": self._fps_range_bad,
                "cross_aspect_bad": self._cross_aspect_bad,
                "output_count": len(self._output_bad) if self._output_bad else 0,
                "scene_stats": self._scene_stats,
            }
            save_path = export_qc_report(doc, results, self._artist_name, self._qc_summary)
            if save_path:
                safe_print(f"QC report saved to: {save_path}")
                c4d.gui.MessageDialog(f"QC Report saved!\n\n{save_path}")

        elif cid == G.BTN_COLLECT_SCENE:
            collect_scene(doc, self._artist_name)

        elif cid == G.BTN_SAVE_VERSION:
            self._handle_save_version(doc)

        elif cid == G.BTN_EDIT_NOTES:
            self._handle_edit_notes(doc)

        elif cid == G.TAB_BAR:
            # Tab clicked — find which one is selected and switch
            if self._quicktab is not None:
                for i in range(4):
                    try:
                        if self._quicktab.IsSelected(i):
                            self._set_active_tab(i)
                            break
                    except Exception:
                        pass

        elif cid == G.COMBO_HISTORY_FILTER:
            try:
                idx = int(self.GetInt32(G.COMBO_HISTORY_FILTER))
            except Exception:
                idx = 0
            if 0 <= idx < len(self._HISTORY_FILTERS):
                self._history_filter = self._HISTORY_FILTERS[idx]
            self._update_history_area()

        return True

    # ── Scene Notes handler ──
    def _handle_edit_notes(self, doc):
        """Open the Notes dialog. On Save, persist to sidecar JSON."""
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return
        notes_path = get_notes_path(doc)
        if not notes_path:
            c4d.gui.MessageDialog(
                "Save the scene first to a folder before adding notes."
            )
            return

        notes = load_notes(notes_path)
        # Stamp scene name from filename (used in dialog title) if not yet set
        if not notes.get("scene"):
            doc_name = doc.GetDocumentName() or ""
            name_no_ext = os.path.splitext(doc_name)[0]
            base, _ver, _status = parse_version_filename(name_no_ext)
            notes["scene"] = base or name_no_ext or "scene"

        dlg = NotesDialog(notes)
        dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=560, defaulth=520)

        if dlg.confirmed and dlg.result_notes is not None:
            ok = save_notes(notes_path, dlg.result_notes)
            if ok:
                safe_print(f"Notes saved: {os.path.basename(notes_path)}")
                self._dirty = True
            else:
                c4d.gui.MessageDialog("Failed to save notes file.")
        else:
            safe_print("Notes edit cancelled by user")

    # ── Smart Save Version handler ──
    def _handle_save_version(self, doc):
        """Open the SaveVersion dialog and dispatch to smart_save_version."""
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return

        dlg = SaveVersionDialog(doc=doc, run_qc_default=True)
        try:
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=520, defaulth=280)
        except Exception as e:
            safe_print(f"SaveVersionDialog open error: {e}")
            return

        if not dlg.confirmed:
            safe_print("Save Version cancelled by user")
            return

        result = smart_save_version(
            doc,
            comment=dlg.result_comment,
            run_qc=dlg.result_run_qc,
            artist_name=self._artist_name or "",
            status=dlg.result_status,
        )

        # Build feedback message
        if result.get("success"):
            lines = [result.get("message", "Saved")]
            if result.get("status"):
                lines.append(f"Status: {result['status']}")
            qc = result.get("qc_summary")
            if qc:
                status_word = "PASS" if qc.get("pass") else "FAIL"
                lines.append(f"QC: {qc.get('score','')}  [{status_word}]")
            hp = result.get("history_path")
            if hp:
                lines.append("")
                lines.append(f"History: {os.path.basename(hp)}")

            saved_status = (result.get("status") or "").upper()
            review_status = saved_status in ("TR", "CR", "FINAL")
            base_msg = "\n".join(lines)
            safe_print(f"Saved version v{result.get('version')} status={saved_status or 'WIP'} -> {result.get('path')}")
            self._dirty = True

            if review_status:
                # Gap 1: offer to immediately create a continuation WIP version
                # so the artist doesn't accidentally overwrite the review snapshot
                # on the next Cmd+S.
                prompt = (
                    base_msg
                    + "\n\n──────────\n"
                    + f"This {saved_status} version is locked-in for review.\n"
                    + "Continue editing in a new WIP version?\n"
                    + "(keeps the current file untouched)"
                )
                if c4d.gui.QuestionDialog(prompt):
                    cont = smart_save_version(
                        doc,
                        comment=f"Continue from v{result.get('version'):03d}_{saved_status}",
                        run_qc=False,
                        artist_name=self._artist_name or "",
                        status="",
                    )
                    if cont.get("success"):
                        safe_print(f"Continued in v{cont.get('version'):03d} WIP")
                        self._dirty = True
                    else:
                        c4d.gui.MessageDialog(
                            f"Could not create continuation version:\n\n"
                            f"{cont.get('message','unknown error')}"
                        )
            else:
                c4d.gui.MessageDialog(base_msg)
        else:
            c4d.gui.MessageDialog(f"Save Version failed:\n\n{result.get('message','unknown error')}")
            safe_print(f"Save Version failed: {result.get('message')}")

    def _scan_light_groups(self, doc):
        """Scan scene lights and return (groups_dict, ungrouped_list)"""
        groups = {}
        ungrouped = []
        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj or not _is_light_obj(obj):
                    continue
                light_name = _safe_name(obj)
                group = ""
                try:
                    group = obj[c4d.REDSHIFT_LIGHT_LIGHT_GROUP] or ""
                except Exception:
                    pass
                if not group:
                    for tag in obj.GetTags():
                        try:
                            g = tag[c4d.REDSHIFT_LIGHT_GROUP_LIGHT_GROUP]
                            if g:
                                group = g
                                break
                        except Exception:
                            pass
                if group:
                    groups.setdefault(group, []).append(light_name)
                else:
                    ungrouped.append(light_name)
        return groups, ungrouped

    def _is_lg_active_on_beauty(self, doc):
        """Check if All Light Groups is active on Beauty AOV"""
        vprs = _get_rs_videopost(doc)
        if not vprs:
            return False
        try:
            for aov in redshift.RendererGetAOVs(vprs):
                if aov.GetParameter(c4d.REDSHIFT_AOV_NAME) == "Beauty":
                    return bool(aov.GetParameter(c4d.REDSHIFT_AOV_LIGHTGROUP_ALL))
        except Exception:
            pass
        return False

    def _toggle_light_groups(self, doc):
        """Toggle Light Groups on Beauty AOV with diagnostic"""
        if not REDSHIFT_AVAILABLE:
            c4d.gui.MessageDialog("Redshift module not available.")
            return

        vprs = _get_rs_videopost(doc)
        if not vprs:
            c4d.gui.MessageDialog("Redshift VideoPost not found.")
            return

        groups, ungrouped = self._scan_light_groups(doc)
        lg_active = self._is_lg_active_on_beauty(doc)

        if not groups and not ungrouped:
            c4d.gui.MessageDialog("No lights found in the scene.")
            return

        # Build diagnostic message
        msg = f"LIGHT GROUPS — {'ACTIVE' if lg_active else 'INACTIVE'}\n\n"
        if groups:
            msg += f"Groups ({len(groups)}):\n"
            for gname, lights in sorted(groups.items()):
                msg += f"  [{gname}]: {', '.join(lights)}\n"
        if ungrouped:
            msg += f"\nUngrouped ({len(ungrouped)}): {', '.join(ungrouped)}\n"
            msg += f"  (These contribute to all groups)\n"

        if not groups:
            msg += "\nNo light groups assigned.\nAssign groups on your RS lights first."
            c4d.gui.MessageDialog(msg)
            return

        if lg_active:
            msg += "\nDeactivate Light Groups on Beauty AOV?"
        else:
            msg += "\nActivate Light Groups on Beauty AOV?"

        if not c4d.gui.QuestionDialog(msg):
            return

        # Toggle on Beauty AOV
        try:
            aovs = redshift.RendererGetAOVs(vprs)
            found = False
            for aov in aovs:
                try:
                    if aov.GetParameter(c4d.REDSHIFT_AOV_NAME) == "Beauty":
                        new_state = not lg_active
                        aov.SetParameter(c4d.REDSHIFT_AOV_LIGHTGROUP_ALL, new_state)
                        found = True
                        break
                except Exception:
                    pass

            if found:
                redshift.RendererSetAOVs(vprs, aovs)
                check_cache.clear()
                c4d.EventAdd()
                if not lg_active:
                    safe_print(f"Light Groups activated ({len(groups)} groups)")
                    c4d.gui.MessageDialog(f"Light Groups ACTIVATED on Beauty\n\n"
                                         f"{len(groups)} group(s): {', '.join(sorted(groups.keys()))}\n"
                                         f"RS will generate Beauty_[GroupName] sub-AOVs.")
                else:
                    safe_print("Light Groups deactivated")
                    c4d.gui.MessageDialog("Light Groups DEACTIVATED on Beauty")
            else:
                c4d.gui.MessageDialog("Beauty AOV not found.\n\nRun Essentials or Production first.")

        except Exception as e:
            safe_print(f"Error toggling light groups: {e}")
            c4d.gui.MessageDialog(f"Error: {e}")

    def _force_aov_tier(self, doc, tier_list, tier_name):
        if not REDSHIFT_AVAILABLE:
            c4d.gui.MessageDialog("Redshift module not available.")
            return
        result = check_rs_aovs(doc, tier_list)
        if not result["missing"]:
            c4d.gui.MessageDialog(f"All {tier_name} AOVs already configured.")
            return
        missing_list = "\n".join(f"  - {n}" for n in result["missing"])
        if c4d.gui.QuestionDialog(f"Add {len(result['missing'])} {tier_name} AOVs?\n\n{missing_list}"):
            added, error = force_aov_tier(doc, tier_list)
            if error:
                c4d.gui.MessageDialog(f"Error: {error}")
            else:
                target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
                multipart = bool(int(GlobalSettings.get('aov_multipart', 1)))
                output_mode = "Multi-Part EXR (32-bit, DWAB)" if multipart else "Direct Output (per-AOV settings)"
                safe_print(f"Added {added} {tier_name} AOVs for {target_name}")
                msg = f"Added {added} {tier_name} AOV(s)\n\n"
                msg += f"Compositor: {target_name}\n"
                msg += f"Output: {output_mode}\n\n"
                if target_name == "Nuke":
                    msg += "Depth: Z raw, Center Sample\nMotion Vectors: Raw, No Clamp, No Filter"
                else:
                    msg += "Depth: Z Normalized Inverted, Center Sample\nMotion Vectors: Normalized 0-1, Max Motion=64"
                c4d.gui.MessageDialog(msg)

    def _open_artist_folder(self):
        """Open the artist's output folder"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document!")
            return

        snapshot_open_folder(doc, self._artist_name)

    def _create_vibrate_null(self, doc):
        self._merge_c4d_file(doc, "VibrateNull.c4d")

    def _toggle_safe_area_mark(self, doc):
        """Mark / unmark the current selection as Safe Area Subjects.

        Drives the QC #12 Cross-Aspect Safe-Area check. Smart toggle:
          - All selected objects ALREADY marked  → unmark them all
          - Any selected object NOT marked       → mark them all
                                                   (aligns toward "marked")
          - Empty selection                      → friendly hint dialog

        Marks persist as UserData boolean on each object — they survive
        save/reload and Cmd+Z reverts the operation as a single undo step.
        """
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return

        sel = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN) or []
        if not sel:
            c4d.gui.MessageDialog(
                "Select one or more objects first, then click again.\n\n"
                "Tip: mark important compositional elements (logo, title, "
                "character) so QC #12 can verify they stay inside the safe "
                "area of every multi-format delivery Take."
            )
            return

        # Detect current state
        all_marked = all(is_object_marked_safe_area(o) for o in sel)
        target_state = not all_marked  # toggle: marked→unmark, otherwise mark

        marked_count = 0
        unmarked_count = 0
        failed_count = 0

        doc.StartUndo()
        try:
            for obj in sel:
                if target_state:
                    # Marking pass
                    ok = mark_object_safe_area(obj, True, doc)
                    if ok:
                        marked_count += 1
                    else:
                        failed_count += 1
                else:
                    # Unmarking pass — fully remove the UserData entry so the
                    # object returns to a "never been marked" state. Avoids
                    # leaving fossil UD checkboxes on objects.
                    ok = unmark_object_safe_area(obj, doc)
                    if ok:
                        unmarked_count += 1
                    else:
                        failed_count += 1
        finally:
            doc.EndUndo()
            c4d.EventAdd()

        # Refresh the QC row immediately so the user sees the count update
        try:
            check_cache.clear()
            self._refresh()
        except Exception:
            pass

        # Brief feedback
        verb = "Marked" if target_state else "Unmarked"
        count = marked_count if target_state else unmarked_count
        msg = f"{verb} {count} object(s) as Safe Area Subject(s)"
        if failed_count:
            msg += f"\n({failed_count} failed — see Console for details)"
        safe_print(msg)

    def _open_texture_repathing(self, doc):
        """Open the Texture Repathing dialog (v1.5.7).

        Bulk find/replace + smart-fix utility for texture paths across all
        renderers (Redshift / Octane / Arnold).

        Opened ASYNC (not modal) so Cinema 4D's main window stays
        interactive while the tool is open — critically, this keeps the
        Cmd+Z shortcut working. A modal dialog captures the keyboard, so
        after applying changes the user could not undo them with Cmd+Z
        until the dialog closed. The panel holds a reference so the dialog
        object isn't garbage-collected while open. QC check #6 refreshes
        on its own via the CoreMessage dirty-flag once changes hit the
        scene, so no explicit refresh is needed here.
        """
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return
        try:
            existing = getattr(self, "_texture_repath_dlg", None)
            if existing is not None:
                try:
                    if existing.IsOpen():
                        existing.Close()
                except Exception:
                    pass
            dlg = TextureRepathingDialog(doc)
            self._texture_repath_dlg = dlg
            dlg.Open(c4d.DLG_TYPE_ASYNC, defaultw=900, defaulth=620)
        except Exception as e:
            c4d.gui.MessageDialog(f"Texture Repathing failed to open:\n{e}")
            safe_print(f"Texture Repathing error: {e}")

    def _create_hierarchy(self, doc):
        self._merge_c4d_file(doc, "nulls.c4d")

    def _merge_camera_file(self, doc, filename):
        self._merge_c4d_file(doc, filename)

    def _merge_c4d_file(self, doc, filename):
        """Merge camera setup from C4D file"""
        if not doc:
            return

        try:
            # Get path to the C4D file (in the same plugin directory)
            plugin_dir = _ROOT
            c4d_file = os.path.join(plugin_dir, "c4d", filename)

            # Check if file exists
            if not os.path.exists(c4d_file):
                safe_print(f"{filename} not found at: {c4d_file}")
                c4d.gui.MessageDialog(f"{filename} file not found in c4d folder")
                return

            # Merge the C4D file into the current document
            merge_doc = c4d.documents.MergeDocument(doc, c4d_file, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)

            if merge_doc:
                c4d.EventAdd()
                camera_name = filename.replace(".c4d", "").replace("cam_", "").replace("_", " ").title()
                safe_print(f"Merged {camera_name} camera setup from {filename}")
            else:
                safe_print(f"Failed to merge {filename}")

        except Exception as e:
            safe_print(f"Error merging camera file {filename}: {e}")
            c4d.gui.MessageDialog(f"Error loading camera setup: {e}")

    def _get_template_path(self):
        return os.path.join(_ROOT, "c4d", "new.c4d")

    def _force_render_settings(self, doc):
        """Reset all 4 render presets from template file"""
        if not doc:
            return

        template_path = self._get_template_path()
        if not os.path.exists(template_path):
            c4d.gui.MessageDialog(f"Template file not found!\n\nExpected at:\n{template_path}")
            return

        if not c4d.gui.QuestionDialog("Reset ALL render presets from template?\n\nThis replaces existing presets with standard settings."):
            return

        template_doc = None
        try:
            template_doc = c4d.documents.LoadDocument(template_path, c4d.SCENEFILTER_NONE)
            if not template_doc:
                c4d.gui.MessageDialog("Failed to load template file")
                return

            # Clone all presets from template
            standard_presets = ["previz", "pre_render", "render", "stills"]
            cloned = []
            template_rd = template_doc.GetFirstRenderData()
            while template_rd:
                name = normalize_preset_name(template_rd.GetName() or "")
                if name in standard_presets:
                    clone = template_rd.GetClone(c4d.COPYFLAGS_NONE)
                    cloned.append(clone)
                template_rd = template_rd.GetNext()

            # Kill template before modifying scene
            c4d.documents.KillDocument(template_doc)
            template_doc = None

            if not cloned:
                c4d.gui.MessageDialog("No standard presets found in template")
                return

            # Remove existing presets
            rd = doc.GetFirstRenderData()
            while rd:
                next_rd = rd.GetNext()
                rd.Remove()
                rd = next_rd

            # Insert cloned presets
            for clone in cloned:
                doc.InsertRenderData(clone)

            doc.SetActiveRenderData(cloned[0])
            self._active_preset = "previz"
            self._update_preset_buttons()
            check_cache.clear()
            c4d.EventAdd()

            safe_print(f"Reset {len(cloned)} presets from template")
            c4d.gui.MessageDialog(f"Reset {len(cloned)} render presets from template\n\n"
                                 f"Active: {cloned[0].GetName()}\n"
                                 f"Resolution: {int(cloned[0][c4d.RDATA_XRES])}x{int(cloned[0][c4d.RDATA_YRES])}")

        except Exception as e:
            safe_print(f"Error resetting presets: {e}")
            c4d.gui.MessageDialog(f"Error: {e}")
        finally:
            if template_doc:
                c4d.documents.KillDocument(template_doc)

    def _toggle_aspect(self, doc):
        """Toggle between 16:9 and 9:16 aspect ratio"""
        if not doc:
            return

        try:
            rd = doc.GetActiveRenderData()
            if not rd:
                c4d.gui.MessageDialog("No active render preset")
                return

            old_w = int(rd[c4d.RDATA_XRES])
            old_h = int(rd[c4d.RDATA_YRES])
            is_vertical = old_h > old_w

            if is_vertical:
                # Currently vertical → switch to horizontal 16:9
                if old_h >= 3840:
                    w, h = 3840, 2160
                elif old_h >= 1920:
                    w, h = 1920, 1080
                else:
                    w, h = 1280, 720
            else:
                # Currently horizontal → switch to vertical 9:16
                if old_w >= 3840:
                    w, h = 2160, 3840
                elif old_w >= 1920:
                    w, h = 1080, 1920
                else:
                    w, h = 720, 1280

            rd[c4d.RDATA_XRES] = w
            rd[c4d.RDATA_YRES] = h

            check_cache.clear()
            c4d.EventAdd()
            self._update_preset_buttons()
            self._update_aspect_button()

            label = "16:9" if w > h else "9:16"
            safe_print(f"Aspect: {old_w}x{old_h} → {w}x{h} ({label})")

        except Exception as e:
            safe_print(f"Error toggling aspect: {e}")

    def _add_sentinel_frame_tag(self, doc):
        """Add a Sentinel Frame tag to the active/selected camera, or select the
        existing one. The tag is the recommended per-camera multi-format entry
        point (live guides + one-click, rename-safe WYSIWYG-crop delivery Takes).
        """
        if doc is None:
            return
        try:
            from sentinel.ui.frame_tag import (
                SENTINEL_FRAME_TAG_PLUGIN_ID, is_valid_camera_host)
        except Exception as e:
            c4d.gui.MessageDialog(f"Sentinel Frame tag unavailable: {e}")
            return

        # Resolve a camera: the active selected object if it's a camera, else
        # the camera the viewport is looking through.
        cam = None
        active = doc.GetActiveObject()
        if active is not None and is_valid_camera_host(active.GetType()):
            cam = active
        if cam is None:
            try:
                bd = doc.GetActiveBaseDraw()
                scene_cam = bd.GetSceneCamera(doc) if bd else None
                if scene_cam is not None and is_valid_camera_host(scene_cam.GetType()):
                    cam = scene_cam
            except Exception:
                cam = None
        if cam is None:
            c4d.gui.MessageDialog(
                "Select a camera (standard or Redshift), or look through one, "
                "then click 'Add Sentinel Frame to camera'.")
            return

        existing = None
        for t in cam.GetTags():
            if t.GetType() == SENTINEL_FRAME_TAG_PLUGIN_ID:
                existing = t
                break
        if existing is not None:
            try:
                doc.SetActiveTag(existing, c4d.SELECTION_NEW)
                c4d.EventAdd()
            except Exception:
                pass
            c4d.gui.MessageDialog(
                f"'{cam.GetName()}' already has a Sentinel Frame tag — "
                "selected it in the Attribute Manager.")
            return

        tag = None
        doc.StartUndo()
        try:
            tag = cam.MakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
            if tag is not None:
                doc.AddUndo(c4d.UNDOTYPE_NEW, tag)
                try:
                    doc.SetActiveTag(tag, c4d.SELECTION_NEW)
                except Exception:
                    pass
        finally:
            doc.EndUndo()
            c4d.EventAdd()

        if tag is None:
            c4d.gui.MessageDialog("Could not create the Sentinel Frame tag.")
            return
        safe_print(f"Sentinel Frame tag added to '{cam.GetName()}'")

    def _open_multiformat_dialog(self, doc):
        """Open Multi-Format Render Setup dialog and dispatch to orchestrator.

        Resolves the source take + resolution from the current document, opens
        the modal MultiFormatDialog, and on confirm calls
        `generate_multiformat_takes(doc, options)`. Reports created/updated/
        skipped/errors via a summary MessageDialog.
        """
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return

        # Resolve source take + resolution to seed the dialog
        source_take_name = "Main"
        source_resolution = None
        source_take = None
        try:
            td = doc.GetTakeData()
            if td:
                source_take = td.GetCurrentTake() or td.GetMainTake()
                if source_take:
                    source_take_name = source_take.GetName() or "Main"
                rd = _resolve_source_render_data(source_take, td, doc) if source_take else None
                if rd:
                    try:
                        source_resolution = (int(rd[c4d.RDATA_XRES]),
                                             int(rd[c4d.RDATA_YRES]))
                    except Exception:
                        source_resolution = None
        except Exception as e:
            safe_print(f"Multi-Format: could not resolve source state: {e}")

        # Open modal
        try:
            dlg = MultiFormatDialog(source_take_name=source_take_name,
                                    source_resolution=source_resolution)
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=520, defaulth=380)
        except Exception as e:
            safe_print(f"Multi-Format dialog failed to open: {e}")
            c4d.gui.MessageDialog(f"Could not open dialog: {e}")
            return

        if not getattr(dlg, "confirmed", False):
            return  # User cancelled

        options = {
            "formats": dlg.result_formats,
            "output_mode": dlg.result_output_mode,
            "composition_mode": dlg.result_composition_mode,
            "update_existing": dlg.result_update_existing,
            "source_take": source_take,
        }

        # Run orchestrator
        try:
            report = generate_multiformat_takes(doc, options)
        except Exception as e:
            safe_print(f"Multi-Format orchestrator crashed: {e}")
            c4d.gui.MessageDialog(f"Generation failed: {e}")
            return

        # Build summary
        lines = []
        if report.get("source_take_name"):
            src_w, src_h = (report.get("source_resolution") or (0, 0))
            if src_w and src_h:
                lines.append(f"Source: '{report['source_take_name']}' "
                             f"({src_w}×{src_h})")
            else:
                lines.append(f"Source: '{report['source_take_name']}'")
            comp_mode = report.get("composition_mode", COMPOSITION_MODE_NONE)
            mode_label = {
                COMPOSITION_MODE_NONE: "Camera unchanged (resolution only)",
                COMPOSITION_MODE_RESIZE_CANVAS: "Resize Canvas (sensor override per format)",
            }.get(comp_mode, comp_mode)
            lines.append(f"Composition mode: {mode_label}")
            lines.append("")

        created = report.get("created") or []
        updated = report.get("updated") or []
        skipped = report.get("skipped") or []
        errors = report.get("errors") or []

        if created:
            lines.append(f"Created ({len(created)}):")
            for n in created:
                lines.append(f"  + {n}")
            lines.append("")
        if updated:
            lines.append(f"Updated ({len(updated)}):")
            for n in updated:
                lines.append(f"  ~ {n}")
            lines.append("")
        if skipped:
            lines.append(f"Skipped (already exist) ({len(skipped)}):")
            for n in skipped:
                lines.append(f"  · {n}")
            lines.append("")
        if errors:
            lines.append(f"Errors ({len(errors)}):")
            for e in errors:
                lines.append(f"  ! {e}")
            lines.append("")

        if not (created or updated or skipped or errors):
            lines.append("No changes were made.")

        if report.get("success") and (created or updated):
            lines.append("Open the Take Manager to review the new Takes.")

        c4d.gui.MessageDialog("\n".join(lines).strip() or "Done.")

        # Refresh panel state (Take system may have updated the active take)
        try:
            check_cache.clear()
        except Exception:
            pass

        c4d.EventAdd()

    def _update_aspect_button(self):
        """Update the aspect button label based on current render data"""
        try:
            doc = c4d.documents.GetActiveDocument()
            if doc:
                rd = doc.GetActiveRenderData()
                if rd:
                    w = int(rd[c4d.RDATA_XRES])
                    h = int(rd[c4d.RDATA_YRES])
                    is_vertical = h > w
                    self.SetString(G.BTN_FORCE_VERTICAL, "Force 16:9" if is_vertical else "Force 9:16")
        except Exception:
            pass

    def _hierarchy_to_layers(self, doc):
        """Link main project nulls and their children to layers with matching names"""
        if not doc:
            return

        safe_print("Starting Hierarchy to Layers sync...")

        # Check for objects outside nulls first
        root_objects = []
        orphan_objects = []

        obj = doc.GetFirstObject()
        while obj:
            # Only consider top-level objects
            if obj.GetUp() is None:
                if obj.GetType() == c4d.Onull:
                    root_objects.append(obj)
                else:
                    # Check if it's a camera or light (they might be allowed outside)
                    obj_type = obj.GetType()
                    if obj_type not in [c4d.Ocamera, c4d.Olight]:
                        orphan_objects.append(obj)
            obj = obj.GetNext()

        # If there are orphan objects, show error
        if orphan_objects:
            orphan_names = [obj.GetName() for obj in orphan_objects[:5]]  # Show first 5
            more = f" and {len(orphan_objects)-5} more" if len(orphan_objects) > 5 else ""

            msg = f"Found {len(orphan_objects)} object(s) outside of null groups:\n"
            msg += "\n".join(orphan_names) + more
            msg += "\n\nPlease organize all objects into null groups first."
            c4d.gui.MessageDialog(msg)
            safe_print(f"Aborted: {len(orphan_objects)} objects found outside null groups")
            return

        # No orphans, proceed with layer sync
        if not root_objects:
            c4d.gui.MessageDialog("No null groups found in the scene.")
            return

        # Start undo
        doc.StartUndo()

        # Get or create layer root
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            safe_print("Error: Could not get layer root")
            doc.EndUndo()
            return

        created_layers = 0
        updated_layers = 0

        for null in root_objects:
            null_name = null.GetName()

            # Find or create layer with matching name (returns layer and is_new flag)
            layer, is_new = self._find_or_create_layer(doc, layer_root, null_name)

            if layer:
                # Assign null and all children to this layer
                self._assign_to_layer_recursive(doc, null, layer)

                if is_new:
                    created_layers += 1
                    safe_print(f"Created new layer '{null_name}' and synced objects")
                else:
                    updated_layers += 1
                    safe_print(f"Updated existing layer '{null_name}' with objects")

        doc.EndUndo()
        c4d.EventAdd()

        # Just report to console, no popup
        safe_print(f"Hierarchy→Layers complete: {created_layers} new, {updated_layers} updated layers, {len(root_objects)} nulls synced")

    def _find_or_create_layer(self, doc, layer_root, name):
        """Find existing layer by name or create new one. Returns (layer, is_new)"""
        # First, search for existing layer
        layer = layer_root.GetDown()
        while layer:
            if layer.GetName() == name:
                return layer, False  # Found existing
            layer = layer.GetNext()

        # Create new layer
        new_layer = c4d.documents.LayerObject()
        new_layer.SetName(name)
        new_layer.InsertUnder(layer_root)

        # Generate unique random color based on layer name hash
        # This ensures same name always gets same color (consistent)
        import hashlib

        # Create hash from name
        name_hash = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)

        # Generate pleasant, distinct colors using golden ratio
        # This creates visually distinct colors that are evenly distributed
        golden_ratio = 0.618033988749895
        hue = (name_hash * golden_ratio) % 1.0

        # Convert HSV to RGB (S=0.6, V=0.95 for pleasant, bright colors)
        saturation = 0.6
        value = 0.95

        def hsv_to_rgb(h, s, v):
            """Convert HSV to RGB"""
            h_i = int(h * 6)
            f = h * 6 - h_i
            p = v * (1 - s)
            q = v * (1 - f * s)
            t = v * (1 - (1 - f) * s)

            if h_i == 0:
                r, g, b = v, t, p
            elif h_i == 1:
                r, g, b = q, v, p
            elif h_i == 2:
                r, g, b = p, v, t
            elif h_i == 3:
                r, g, b = p, q, v
            elif h_i == 4:
                r, g, b = t, p, v
            else:
                r, g, b = v, p, q

            return c4d.Vector(r, g, b)

        unique_color = hsv_to_rgb(hue, saturation, value)
        new_layer[c4d.ID_LAYER_COLOR] = unique_color

        doc.AddUndo(c4d.UNDOTYPE_NEW, new_layer)
        return new_layer, True  # Return new layer and flag

    def _solo_layers(self, doc):
        """Solo selected layers - disable all other layers and their objects"""
        if not doc:
            return

        # Check if any layers are currently disabled (solo is active)
        # If so, restore all layers
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            safe_print("Error: Could not get layer root")
            return

        # Check if we're in solo mode
        def check_solo_mode(layer):
            """Check if any layer is disabled (indicating solo mode)"""
            while layer:
                if not layer[c4d.ID_LAYER_VIEW]:
                    return True
                child = layer.GetDown()
                if child and check_solo_mode(child):
                    return True
                layer = layer.GetNext()
            return False

        first_layer = layer_root.GetDown()
        if first_layer and check_solo_mode(first_layer):
            # We're in solo mode, restore all
            self._unsolo_layers(doc)
            return

        # Get all selected layers
        selected_layers = []

        def collect_selected_layers(layer):
            """Recursively collect selected layers"""
            while layer:
                if layer.GetBit(c4d.BIT_ACTIVE):
                    selected_layers.append(layer)
                # Check children
                child = layer.GetDown()
                if child:
                    collect_selected_layers(child)
                layer = layer.GetNext()

        # Start from first layer
        first_layer = layer_root.GetDown()
        if not first_layer:
            c4d.gui.MessageDialog("No layers found in the scene.\nCreate layers first using Hierarchy→Layers.")
            return

        collect_selected_layers(first_layer)

        if not selected_layers:
            c4d.gui.MessageDialog("Please select one or more layers to solo.")
            return

        safe_print(f"Solo mode: Isolating {len(selected_layers)} layer(s)")

        # Start undo
        doc.StartUndo()

        # Track what we're doing
        layers_disabled = 0
        layers_soloed = 0
        objects_affected = 0

        # First pass: Process all layers
        def process_layer(layer, is_soloed):
            """Process a layer and return count of affected objects"""
            nonlocal layers_disabled, layers_soloed

            doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

            if is_soloed:
                # Enable this layer
                layer[c4d.ID_LAYER_VIEW] = True
                layer[c4d.ID_LAYER_RENDER] = True
                layer[c4d.ID_LAYER_MANAGER] = True
                layer[c4d.ID_LAYER_GENERATORS] = True
                layer[c4d.ID_LAYER_DEFORMERS] = True
                layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = True
                layer[c4d.ID_LAYER_LOCKED] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = True
                layers_soloed += 1
                safe_print(f"  Enabled layer: {layer.GetName()}")
            else:
                # Disable this layer completely
                layer[c4d.ID_LAYER_VIEW] = False
                layer[c4d.ID_LAYER_RENDER] = False
                layer[c4d.ID_LAYER_MANAGER] = False
                layer[c4d.ID_LAYER_GENERATORS] = False
                layer[c4d.ID_LAYER_DEFORMERS] = False
                layer[c4d.ID_LAYER_EXPRESSIONS] = False  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = False
                layers_disabled += 1

        # Process all layers
        def process_all_layers(layer):
            while layer:
                is_selected = layer in selected_layers
                process_layer(layer, is_selected)

                # Process children
                child = layer.GetDown()
                if child:
                    process_all_layers(child)

                layer = layer.GetNext()

        process_all_layers(first_layer)

        # Second pass: Handle objects without layers (disable them too)
        def disable_unassigned_objects(obj):
            """Disable objects not assigned to any layer"""
            nonlocal objects_affected

            while obj:
                # Check if object has no layer assignment
                if not obj.GetLayerObject(doc):
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                    # Disable the object
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 1  # Hide in editor
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 1  # Hide in render

                    # Disable generators and deformers
                    obj.SetDeformMode(False)

                    # If it's a generator, try to disable it
                    if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                        obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = False

                    objects_affected += 1

                # Process children
                child = obj.GetDown()
                if child:
                    disable_unassigned_objects(child)

                obj = obj.GetNext()

        # Disable unassigned objects
        first_object = doc.GetFirstObject()
        if first_object:
            disable_unassigned_objects(first_object)

        doc.EndUndo()
        c4d.EventAdd()

        # Report to console
        safe_print(f"Solo Layers complete: {layers_soloed} soloed, {layers_disabled} disabled, {objects_affected} unassigned objects hidden")

    def _unsolo_layers(self, doc):
        """Restore all layers to their default visible state"""
        if not doc:
            return

        safe_print("Restoring all layers...")

        # Get layer root
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            return

        doc.StartUndo()

        layers_restored = 0

        def restore_layer(layer):
            """Restore a layer to default visible state"""
            nonlocal layers_restored

            while layer:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

                # Enable everything
                layer[c4d.ID_LAYER_VIEW] = True
                layer[c4d.ID_LAYER_RENDER] = True
                layer[c4d.ID_LAYER_MANAGER] = True
                layer[c4d.ID_LAYER_GENERATORS] = True
                layer[c4d.ID_LAYER_DEFORMERS] = True
                layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = True
                layer[c4d.ID_LAYER_LOCKED] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = True

                layers_restored += 1

                # Process children
                child = layer.GetDown()
                if child:
                    restore_layer(child)

                layer = layer.GetNext()

        # Restore all layers
        first_layer = layer_root.GetDown()
        if first_layer:
            restore_layer(first_layer)

        # Restore objects without layers
        def restore_unassigned_objects(obj):
            while obj:
                if not obj.GetLayerObject(doc):
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 2  # Show
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 2  # Show
                    obj.SetDeformMode(True)
                    if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                        obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = True

                child = obj.GetDown()
                if child:
                    restore_unassigned_objects(child)

                obj = obj.GetNext()

        first_object = doc.GetFirstObject()
        if first_object:
            restore_unassigned_objects(first_object)

        doc.EndUndo()
        c4d.EventAdd()

        safe_print(f"Restored {layers_restored} layers to visible state")

    def _assign_to_layer_recursive(self, doc, obj, layer):
        """Assign object and all its children to a layer"""
        if not obj or not layer:
            return

        # Add undo for the object
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

        # Assign to layer
        obj.SetLayerObject(layer)

        # Process all children recursively
        child = obj.GetDown()
        while child:
            self._assign_to_layer_recursive(doc, child, layer)
            child = child.GetNext()

    def _drop_to_floor(self, doc):
        """Drop selected objects to floor (Y=0 plane) - handles rotation and hierarchy correctly"""
        if not doc:
            return

        # Get selected objects
        selected = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_SELECTIONORDER)
        if not selected:
            safe_print("Please select one or more objects to drop to floor")
            return

        # Start undo
        doc.StartUndo()

        dropped_count = 0

        for obj in selected:
            # Get object's global matrix
            mg = obj.GetMg()

            # Get cache (the actual geometry for display/render)
            cache = obj.GetCache()
            if cache is None:
                cache = obj.GetDeformCache()

            # If we have a cache, use it to get the accurate global bounding box
            if cache:
                # Initialize with first point
                min_y = None

                # Recursively process cache and all children
                def process_cache(cache_obj, parent_mg):
                    """Recursively get all points from cache hierarchy"""
                    nonlocal min_y

                    if not cache_obj:
                        return

                    # Get cache's local matrix
                    cache_mg = cache_obj.GetMl()
                    # Combine with parent matrix to get global position
                    global_mg = parent_mg * cache_mg

                    # Get points if this is a PointObject
                    if cache_obj.CheckType(c4d.Opoint):
                        points = cache_obj.GetAllPoints()
                        if points:
                            for point in points:
                                # Transform point to global space
                                global_point = global_mg * point
                                if min_y is None or global_point.y < min_y:
                                    min_y = global_point.y

                    # Process children
                    child = cache_obj.GetDown()
                    if child:
                        process_cache(child, global_mg)

                    # Process siblings
                    next_obj = cache_obj.GetNext()
                    if next_obj:
                        process_cache(next_obj, parent_mg)

                # Process cache hierarchy
                process_cache(cache, mg)

                # If we didn't find any points, fall back to bounding box method
                if min_y is None:
                    # Use bounding box as fallback
                    mp = obj.GetMp()
                    rad = obj.GetRad()

                    if rad.GetLength() == 0:
                        rad = c4d.Vector(50, 50, 50)

                    # Calculate all 8 corners
                    corners = [
                        c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                    ]

                    min_y = float('inf')
                    for corner in corners:
                        world_corner = mg * corner
                        if world_corner.y < min_y:
                            min_y = world_corner.y
            else:
                # No cache - use bounding box method
                mp = obj.GetMp()
                rad = obj.GetRad()

                if rad.GetLength() == 0:
                    rad = c4d.Vector(50, 50, 50)

                # Calculate all 8 corners
                corners = [
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                ]

                min_y = float('inf')
                for corner in corners:
                    world_corner = mg * corner
                    if world_corner.y < min_y:
                        min_y = world_corner.y

            # Calculate how much to move the object
            if min_y is not None and abs(min_y) > 0.001:  # Small threshold to avoid tiny movements
                move_distance = -min_y

                # Record undo for position change
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                # Move the object in global space
                current_pos = obj.GetAbsPos()
                new_pos = c4d.Vector(current_pos.x, current_pos.y + move_distance, current_pos.z)
                obj.SetAbsPos(new_pos)

                dropped_count += 1
                safe_print(f"Dropped '{obj.GetName()}' by {move_distance:.2f} units")

        # End undo
        doc.EndUndo()

        # Update the scene
        c4d.EventAdd()

        # Show result message in console only (no popup for smooth workflow)
        if dropped_count == 1:
            safe_print(f"Dropped 1 object to floor")
        elif dropped_count > 1:
            safe_print(f"Dropped {dropped_count} objects to floor")
        else:
            safe_print("No objects needed dropping - already on floor")

    def _take_renderview_snapshot(self):
        """Take a snapshot from RenderView"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document!")
            return

        if not self._artist_name:
            c4d.gui.MessageDialog("Please set your artist name first!")
            return

        snapshot_save_still(doc, self._artist_name)

    def _apply_abc_retime_tag(self):
        """Apply ABC Retime tag to selected object(s)"""
        doc = documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document")
            return

        selection = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN)
        if not selection:
            c4d.gui.MessageDialog("Please select an object first\n\n(Works with Alembic, Point Cache, Mograph Cache, or X-Particles Cache objects)")
            return

        # ABC Retime plugin ID
        ABC_RETIME_TAG_ID = 1058910

        applied_count = 0
        skipped_count = 0
        failed_count = 0

        for obj in selection:
            # Check if tag already exists
            existing_tag = obj.GetTag(ABC_RETIME_TAG_ID)
            if existing_tag:
                safe_print(f"ABC Retime tag already exists on {obj.GetName()}")
                skipped_count += 1
                continue

            # Apply the tag
            tag = obj.MakeTag(ABC_RETIME_TAG_ID)
            if tag:
                applied_count += 1
                safe_print(f"ABC Retime tag applied to {obj.GetName()}")
            else:
                failed_count += 1
                safe_print(f"Failed to apply ABC Retime tag to {obj.GetName()}")

        # Update the scene
        if applied_count > 0:
            c4d.EventAdd()

        # Show error message only if failed
        if applied_count == 0 and skipped_count == 0:
            c4d.gui.MessageDialog("ABC Retime tag could not be applied\n\nPossible reasons:\n- ABC Retime plugin not installed\n- Invalid object type\n\nManual access: Right-click Tags → Extensions → Alembic Retime")

    def DestroyWindow(self):
        """Clean up when panel closes"""
        pass  # No cleanup needed anymore

def _select_objects(doc, objs):
    """Select objects in the scene"""
    if not doc or not objs:
        return

    first = doc.GetFirstObject()
    if first:
        for o in _iter_objs(first):
            o.DelBit(c4d.BIT_ACTIVE)

    for o in objs:
        try:
            if o:
                o.SetBit(c4d.BIT_ACTIVE)
        except Exception:
            pass

    c4d.EventAdd()

# -------------- registration --------------
class YSPanelCmd(plugins.CommandData):
    dlg = None

    def Execute(self, doc):
        if self.dlg is None:
            self.dlg = YSPanel()
            safe_print(f"{PLUGIN_NAME} initialized")
        # Pass plugin ID as second argument for layout persistence
        return self.dlg.Open(dlgtype=c4d.DLG_TYPE_ASYNC, pluginid=PLUGIN_ID,
                            defaultw=420, defaulth=360)

    def RestoreLayout(self, sec_ref):
        """Required for layout persistence - called when C4D restores layouts"""
        if self.dlg is None:
            self.dlg = YSPanel()
        # Restore the dialog with the plugin ID
        return self.dlg.Restore(pluginid=PLUGIN_ID, secret=sec_ref)
