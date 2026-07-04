# -*- coding: utf-8 -*-
import c4d
from c4d import plugins, gui, documents
import os
import json
import time
import sys
import webbrowser
import math as _math

_ROOT = os.path.dirname(__file__)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sentinel
from sentinel import baseline
from sentinel import PLUGIN_NAME, PLUGIN_VERSION
from sentinel.common.cache import CheckCache, check_cache
from sentinel.common.constants import (
    CACHE_DURATION,
    CHECK_COOLDOWN,
    LEGACY_SETTINGS_FILE,
    MAX_OBJECTS_PER_CHECK,
    PLUGIN_ID,
    PRESETS,
    SAFE_AREA_OVERLAY_PLUGIN_ID,
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
    object_identity,
    structured_cache_key,
)
from sentinel.qc.registry import CHECK_REGISTRY, CheckDisplayView, RowKeysView
from sentinel.qc.registry import entry_severity
from sentinel.qc.score import compute_score, count_violations, run_all_checks
from sentinel.rules import get_active_rules

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


def _violation_label(violation):
    if not isinstance(violation, dict):
        return str(violation)
    message = violation.get("message")
    if message:
        return str(message)
    identity = violation.get("identity") or {}
    if isinstance(identity, dict):
        for key in ("path", "name", "param", "preset", "take", "field"):
            if identity.get(key) is not None:
                return str(identity.get(key))
    return str(violation)


def _entry_label(entry):
    if not isinstance(entry, dict):
        return str(entry)
    identity = entry.get("identity") or {}
    if isinstance(identity, dict):
        parts = []
        for key in ("path", "name", "param", "preset", "take", "field"):
            if identity.get(key) is not None:
                parts.append(str(identity.get(key)))
        if parts:
            return " / ".join(parts)
    return str(entry.get("check_id", "acceptance"))


def _accepted_entry_payload(entry, violation=None):
    return {
        "item": _violation_label(violation) if violation is not None else _entry_label(entry),
        "author": entry.get("author", "") if isinstance(entry, dict) else "",
        "reason": entry.get("reason", "") if isinstance(entry, dict) else "",
        "date": entry.get("date", "") if isinstance(entry, dict) else "",
    }


def format_baseline_row_message(new_count, accepted_count, stale_count=0):
    message = f"{int(new_count or 0)} nuevas ({int(accepted_count or 0)} aceptadas)"
    if int(stale_count or 0):
        message += f" · {int(stale_count or 0)} obsoletas"
    return message


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


def fix_fps_range(doc):
    """Auto-fix FPS/range across ALL render presets. Aligns timeline to active preset."""
    fixes = []
    if not doc.GetFirstRenderData():
        return fixes

    rules_context = _active_rules_for_doc(doc)
    standard_fps = int(rules_context.params.get("standard_fps", GlobalSettings.get_standard_fps()))
    start_frame = int(rules_context.params.get("start_frame", 1001))
    active_rd = doc.GetActiveRenderData()

    doc.StartUndo()
    try:
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

    except Exception as e:
        safe_print(f"Error fixing FPS/range: {e}")
    finally:
        doc.EndUndo()

    check_cache.clear()
    c4d.EventAdd()
    return fixes

# ---------------- auto-fix functions ----------------
def fix_lights(doc, lights_bad):
    """Move stray lights into a 'lights' group null"""
    if not lights_bad:
        return 0

    doc.StartUndo()

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

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return moved

def fix_camera_shift(doc, cam_bad):
    """Reset camera shift to 0 on all flagged cameras"""
    if not cam_bad:
        return 0

    doc.StartUndo()
    fixed = 0
    for cam in cam_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, cam)
        try:
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
            fixed += 1
        except Exception:
            pass

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return fixed

def fix_unused_materials(doc, unused_mats):
    """Delete unused materials from the scene"""
    if not unused_mats:
        return 0

    doc.StartUndo()
    deleted = 0
    for mat in unused_mats:
        doc.AddUndo(c4d.UNDOTYPE_DELETE, mat)
        mat.Remove()
        deleted += 1

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return deleted

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

    # Summary
    total = len(report["checks"])
    passed = sum(1 for c in report["checks"].values() if c["status"] == "PASS")
    report["summary"] = {
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "score": f"{passed}/{total}"
    }

    baseline_details = build_baseline_artifact_details(qc_summary)
    if baseline_details:
        for check_id, details in baseline_details.items():
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
        report["summary"] = {
            "total_checks": qc_summary.get("total", total),
            "passed": qc_summary.get("passed", passed),
            "failed": qc_summary.get("total", total) - qc_summary.get("passed", passed),
            "score": qc_summary.get("score", f"{passed}/{total}"),
            "new": qc_summary.get("new", 0),
            "accepted": qc_summary.get("accepted", 0),
            "stale": qc_summary.get("stale", 0),
            "schema": 2,
        }
        report["baseline"] = {
            "path": qc_summary.get("baseline_path", ""),
            "checks": baseline_details,
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


class SaveVersionDialog(gui.GeDialog):
    """Modal dialog: comment + run-QC + review status tag.

    After Open(c4d.DLG_TYPE_MODAL), check `confirmed`. If True, read
    `result_comment`, `result_run_qc`, `result_status`.
    """

    # Widget IDs (local to this dialog)
    EDT_COMMENT = 1001
    CHK_RUN_QC = 1002
    BTN_SAVE = 1003
    BTN_CANCEL = 1004
    LBL_INFO = 1005
    COMBO_STATUS = 1006
    EDT_CUSTOM = 1007

    def __init__(self, doc=None, run_qc_default=True):
        super().__init__()
        self._doc = doc
        self._run_qc_default = bool(run_qc_default)
        self.result_comment = ""
        self.result_run_qc = run_qc_default
        self.result_status = ""
        self.confirmed = False

    def _current_status(self):
        """Compute the effective status from current widget state.
        Custom field takes priority if non-empty."""
        custom = (self.GetString(self.EDT_CUSTOM) or "").strip()
        if custom:
            return _sanitize_status(custom)
        try:
            idx = int(self.GetInt32(self.COMBO_STATUS))
        except Exception:
            idx = 0
        if 0 <= idx < len(STATUS_OPTIONS):
            return STATUS_OPTIONS[idx][1]
        return ""

    def _refresh_preview(self):
        """Update the 'Will save as: ...' label based on current status selection."""
        status = self._current_status()
        preview = preview_next_filename(self._doc, status=status) if self._doc else None
        if preview:
            self.SetString(self.LBL_INFO, f"Will save as:  {preview}")
        else:
            self.SetString(self.LBL_INFO, "Will save as:  scene_v001.c4d")

    def CreateLayout(self):
        self.SetTitle("Save Version")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)

        # Header: filename preview (updates on status change)
        self.AddStaticText(self.LBL_INFO, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddSeparatorH(6)

        # Status row: combo + custom
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 4, 0)
        self.GroupSpace(8, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Status:", 0)
        self.AddComboBox(self.COMBO_STATUS, c4d.BFH_LEFT, 180, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 80, 0, "Custom:", 0)
        self.AddEditText(self.EDT_CUSTOM, c4d.BFH_SCALEFIT, 100, 0)
        self.GroupEnd()

        self.AddSeparatorH(6)

        # Comment label + multiline input
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Comment (required):", 0)
        try:
            multiline_flags = c4d.DR_MULTILINE_WORDWRAP
        except AttributeError:
            multiline_flags = 0
        self.AddMultiLineEditText(
            self.EDT_COMMENT,
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
            440, 100,
            multiline_flags,
        )

        self.AddSeparatorH(6)

        # Run QC checkbox
        self.AddCheckbox(
            self.CHK_RUN_QC, c4d.BFH_LEFT, 0, 0,
            "Run quality checks and record QC score with this version"
        )

        self.AddSeparatorH(8)

        # Action buttons (right-aligned)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(self.BTN_SAVE, c4d.BFH_RIGHT, 110, 0, "Save Version")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        # Populate status combo
        for i, (label, _suffix) in enumerate(STATUS_OPTIONS):
            self.AddChild(self.COMBO_STATUS, i, label)
        self.SetInt32(self.COMBO_STATUS, 0)  # default: WIP
        self.SetString(self.EDT_CUSTOM, "")
        self.SetBool(self.CHK_RUN_QC, self._run_qc_default)
        self.SetString(self.EDT_COMMENT, "")
        self._refresh_preview()
        return True

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.confirmed = False
            self.Close()
            return True

        # Live preview update on status changes
        if cid in (self.COMBO_STATUS, self.EDT_CUSTOM):
            self._refresh_preview()
            return True

        if cid == self.BTN_SAVE:
            comment = (self.GetString(self.EDT_COMMENT) or "").strip()
            if not comment:
                c4d.gui.MessageDialog(
                    "Please enter a comment describing this version.\n\n"
                    "A short note like 'rim lights pass' or 'client feedback' is enough."
                )
                return True

            # Soft warning if user wrote 'final' in comment — should use status tag
            if "final" in comment.lower():
                c4d.gui.MessageDialog(
                    "Tip: instead of writing 'final' in the comment, use the\n"
                    "'Final Delivery' status tag — it bakes the marker into the\n"
                    "filename (e.g. scene_v007_FINAL.c4d) and the history log.\n\n"
                    "(continuing — your comment will be saved as-is)"
                )
                # Don't return — let the save proceed

            self.result_comment = comment
            self.result_run_qc = self.GetBool(self.CHK_RUN_QC)
            self.result_status = self._current_status()
            self.confirmed = True
            self.Close()
            return True

        return True


class BaselineActionDialog(gui.GeDialog):
    """Modal row action dialog for accepting or removing QC baseline entries."""

    EDT_REASON = 1001
    TXT_ITEMS = 1002
    BTN_ACCEPT = 1003
    BTN_RETIRE = 1004
    BTN_CANCEL = 1005

    def __init__(self, row_label, new_items, accepted_count, stale_count):
        super().__init__()
        self.row_label = row_label or "QC check"
        self.new_items = list(new_items or [])
        self.accepted_count = int(accepted_count or 0)
        self.stale_count = int(stale_count or 0)
        self.action = None
        self.reason = ""

    def _items_text(self):
        if not self.new_items:
            return "No hay violaciones nuevas para aceptar."
        lines = [f"Se aceptaran {len(self.new_items)} violacion(es) nueva(s):", ""]
        for index, item in enumerate(self.new_items[:20], 1):
            lines.append(f"{index}. {_violation_label(item)}")
        if len(self.new_items) > 20:
            lines.append(f"... y {len(self.new_items) - 20} mas")
        if self.accepted_count or self.stale_count:
            lines.append("")
            lines.append(f"Aceptadas actuales: {self.accepted_count}")
            lines.append(f"Obsoletas: {self.stale_count}")
        return "\n".join(lines)

    def CreateLayout(self):
        self.SetTitle(f"Baseline - {self.row_label}")
        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        try:
            multiline_flags = c4d.DR_MULTILINE_WORDWRAP
        except AttributeError:
            multiline_flags = 0
        self.AddMultiLineEditText(
            self.TXT_ITEMS,
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
            460,
            140,
            multiline_flags,
        )
        self.AddSeparatorH(6)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Reason (required for Aceptar):", 0)
        self.AddEditText(self.EDT_REASON, c4d.BFH_SCALEFIT, 0, 0)
        self.AddSeparatorH(8)
        self.GroupBegin(0, c4d.BFH_RIGHT, 3, 0)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(self.BTN_RETIRE, c4d.BFH_RIGHT, 150, 0, "Retirar aceptaciones")
        self.AddButton(self.BTN_ACCEPT, c4d.BFH_RIGHT, 100, 0, "Aceptar")
        self.GroupEnd()
        self.GroupEnd()
        return True

    def InitValues(self):
        self.SetString(self.TXT_ITEMS, self._items_text())
        try:
            self.Enable(self.TXT_ITEMS, False)
        except Exception:
            pass
        try:
            self.Enable(self.BTN_ACCEPT, bool(self.new_items))
            self.Enable(self.BTN_RETIRE, bool(self.accepted_count or self.stale_count))
        except Exception:
            pass
        return True

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.action = None
            self.Close()
            return True
        if cid == self.BTN_ACCEPT:
            reason = (self.GetString(self.EDT_REASON) or "").strip()
            if not reason:
                c4d.gui.MessageDialog("Reason is required before accepting baseline violations.")
                return True
            confirm = self._items_text() + f"\n\nReason:\n{reason}\n\nAceptar estas violaciones?"
            if not c4d.gui.QuestionDialog(confirm):
                return True
            self.reason = reason
            self.action = "accept"
            self.Close()
            return True
        if cid == self.BTN_RETIRE:
            if not c4d.gui.QuestionDialog(
                f"Retirar todas las aceptaciones de {self.row_label}?\n\n"
                "El check volvera a contar esas violaciones como nuevas."
            ):
                return True
            self.action = "retire"
            self.Close()
            return True
        return True


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

# ---------------- TodoArea (GeUserArea for the TODO list) ----------------
# Renders TODOs with checkbox + text + delete affordance. Two click zones per
# row: left (CHECKBOX_W px) toggles done; right (DELETE_W px) deletes.

_COL_TODO_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_TODO_ROW = c4d.Vector(0.14, 0.14, 0.14)
_COL_TODO_ROW_ALT = c4d.Vector(0.16, 0.16, 0.16)
_COL_TODO_TEXT = c4d.Vector(0.85, 0.85, 0.85)
_COL_TODO_TEXT_DONE = c4d.Vector(0.40, 0.40, 0.40)
_COL_TODO_CHECK = c4d.Vector(0.60, 0.60, 0.60)
_COL_TODO_CHECK_ON = c4d.Vector(0.30, 0.75, 0.35)
_COL_TODO_DELETE = c4d.Vector(0.55, 0.30, 0.30)


class TodoArea(gui.GeUserArea):
    """Custom-drawn TODO list with click zones for toggle and delete."""

    ROW_HEIGHT = 22
    ROW_PAD = 2
    CHECKBOX_W = 26          # left click zone width
    DELETE_W = 26            # right click zone width
    EMPTY_HEIGHT = 30

    def __init__(self):
        super().__init__()
        self.todos = []
        self.toggle_callback = None  # callable(todo_id)
        self.delete_callback = None  # callable(todo_id)
        self.font = c4d.FONT_DEFAULT

    def GetMinSize(self):
        n = len(self.todos)
        if n == 0:
            return 400, self.EMPTY_HEIGHT
        h = n * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 2
        return 400, h

    def set_todos(self, todos):
        self.todos = list(todos) if todos else []
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    def _y_to_index(self, y):
        try:
            y = int(y) - self.ROW_PAD
            if y < 0:
                return -1
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            idx = y // row_pixel
            if 0 <= idx < len(self.todos):
                return idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            idx = self._y_to_index(int(local_y))
            if idx < 0:
                return False
            todo = self.todos[idx]
            todo_id = todo.get("id")
            w = self.GetWidth()
            # Left zone → toggle
            if int(local_x) <= self.CHECKBOX_W and self.toggle_callback is not None:
                self.toggle_callback(todo_id)
                return True
            # Right zone → delete
            if int(local_x) >= w - self.DELETE_W and self.delete_callback is not None:
                self.delete_callback(todo_id)
                return True
            # Middle: also toggle (forgiving UX)
            if self.toggle_callback is not None:
                self.toggle_callback(todo_id)
                return True
        except Exception as e:
            safe_print(f"TodoArea.InputEvent error: {e}")
        return False

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_TODO_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self.todos:
                self.DrawSetTextCol(_COL_TODO_TEXT_DONE, _COL_TODO_BG)
                self.DrawText("No TODOs yet — add one below", 8, (h - 12) // 2)
                return

            x = self.ROW_PAD
            y = self.ROW_PAD
            for i, todo in enumerate(self.todos):
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                bg = _COL_TODO_ROW_ALT if (i % 2) else _COL_TODO_ROW
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top), int(w - self.ROW_PAD), int(row_bot))

                done = bool(todo.get("done"))
                text = todo.get("text", "") or ""
                text_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)

                # Checkbox
                cb_x = int(x + 6)
                cb_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)
                cb_size = 12
                # Outer box (frame)
                self.DrawSetPen(_COL_TODO_CHECK)
                self.DrawRectangle(cb_x, cb_y, cb_x + cb_size, cb_y + cb_size)
                # Inner fill (bg or checked)
                if done:
                    self.DrawSetPen(_COL_TODO_CHECK_ON)
                else:
                    self.DrawSetPen(bg)
                self.DrawRectangle(cb_x + 1, cb_y + 1, cb_x + cb_size - 1, cb_y + cb_size - 1)

                # Text
                text_x = int(x + self.CHECKBOX_W + 4)
                avail_w = w - self.CHECKBOX_W - self.DELETE_W - 12
                truncated = text
                try:
                    if int(self.DrawGetTextWidth(truncated)) > avail_w:
                        while truncated and int(self.DrawGetTextWidth(truncated + "...")) > avail_w:
                            truncated = truncated[:-1]
                        truncated = truncated + "..." if truncated != text else truncated
                except Exception:
                    if len(truncated) > 50:
                        truncated = truncated[:47] + "..."
                text_color = _COL_TODO_TEXT_DONE if done else _COL_TODO_TEXT
                self.DrawSetTextCol(text_color, bg)
                self.DrawText(truncated, text_x, text_y)

                # Delete affordance: × on the right
                del_x = int(w - self.DELETE_W + 8)
                self.DrawSetTextCol(_COL_TODO_DELETE, bg)
                self.DrawText("×", del_x, text_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"TodoArea.DrawMsg error: {e}")


# ---------------- NotesDialog (modal: free-form notes + TODO list) ----------------
class NotesDialog(gui.GeDialog):
    """Modal dialog for editing per-scene notes and TODOs.

    After Open(c4d.DLG_TYPE_MODAL), check `confirmed`. If True, read
    `result_notes` (a dict matching the load_notes shape).
    """

    EDT_NOTES = 1001
    AREA_TODOS = 1002
    EDT_NEW_TODO = 1003
    BTN_ADD_TODO = 1004
    BTN_CANCEL = 1005
    BTN_SAVE = 1006
    LBL_SUMMARY = 1007
    LBL_HINT = 1008

    def __init__(self, notes_data):
        super().__init__()
        # Work on a deep copy so Cancel discards changes
        import copy
        self._working = copy.deepcopy(notes_data) if notes_data else _empty_notes()
        self._working.setdefault("notes", "")
        self._working.setdefault("todos", [])
        self.todo_ua = TodoArea()
        self.confirmed = False
        self.result_notes = None

    def CreateLayout(self):
        scene_label = self._working.get("scene") or "scene"
        self.SetTitle(f"Scene Notes — {scene_label}  (shared across all versions)")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.GroupSpace(0, 6)

        # Summary line
        self.AddStaticText(self.LBL_SUMMARY, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        # Hint: explains the model so users don't get confused about scope
        self.AddStaticText(
            self.LBL_HINT, c4d.BFH_SCALEFIT, 0, 0,
            "These notes apply to ALL versions of this scene. "
            "For version-specific commentary, use the Save Version comment field.",
            0
        )

        self.AddSeparatorH(4)

        # Notes section
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Notes (free-form):", 0)
        try:
            multiline_flags = c4d.DR_MULTILINE_WORDWRAP
        except AttributeError:
            multiline_flags = 0
        self.AddMultiLineEditText(
            self.EDT_NOTES,
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
            500, 130,
            multiline_flags,
        )

        self.AddSeparatorH(4)

        # TODOs list
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "TODOs (click to toggle, × to delete):", 0)
        self.AddUserArea(self.AREA_TODOS, c4d.BFH_SCALEFIT | c4d.BFV_FIT, 0, TodoArea.EMPTY_HEIGHT)
        self.AttachUserArea(self.todo_ua, self.AREA_TODOS)

        # Add new TODO row
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddEditText(self.EDT_NEW_TODO, c4d.BFH_SCALEFIT, 0, 0)
        self.AddButton(self.BTN_ADD_TODO, c4d.BFH_RIGHT, 80, 0, "+ Add")
        self.GroupEnd()

        self.AddSeparatorH(8)

        # Action buttons (right-aligned)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(self.BTN_SAVE, c4d.BFH_RIGHT, 90, 0, "Save")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        self.SetString(self.EDT_NOTES, self._working.get("notes", "") or "")
        self.SetString(self.EDT_NEW_TODO, "")
        # Wire TodoArea callbacks (after Attach)
        self.todo_ua.toggle_callback = self._on_toggle_todo
        self.todo_ua.delete_callback = self._on_delete_todo
        self._refresh_todos()
        self._update_summary()
        return True

    def _refresh_todos(self):
        self.todo_ua.set_todos(self._working.get("todos", []))

    def _update_summary(self):
        # Pull live notes text from the edit field so summary reflects what user typed
        live = dict(self._working)
        live["notes"] = self.GetString(self.EDT_NOTES) or ""
        self.SetString(self.LBL_SUMMARY, summarize_notes(live))

    def _on_toggle_todo(self, todo_id):
        if toggle_todo(self._working, todo_id):
            self._refresh_todos()
            self._update_summary()

    def _on_delete_todo(self, todo_id):
        if delete_todo(self._working, todo_id):
            self._refresh_todos()
            self._update_summary()

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.confirmed = False
            self.Close()
            return True

        if cid == self.BTN_ADD_TODO:
            text = (self.GetString(self.EDT_NEW_TODO) or "").strip()
            if text:
                add_todo(self._working, text)
                self.SetString(self.EDT_NEW_TODO, "")
                self._refresh_todos()
                self._update_summary()
            return True

        if cid == self.EDT_NOTES:
            # Live summary update as user types (cheap)
            self._update_summary()
            return True

        if cid == self.EDT_NEW_TODO:
            return True  # no-op; pressing Enter doesn't auto-add (avoid surprise)

        if cid == self.BTN_SAVE:
            # Pull notes text + return the working copy
            self._working["notes"] = (self.GetString(self.EDT_NOTES) or "").strip()
            self.result_notes = self._working
            self.confirmed = True
            self.Close()
            return True

        return True


# ---------------- Sentinel Settings Dialog ----------------
class SentinelSettingsDialog(gui.GeDialog):
    """Modal dialog for editing Sentinel's per-computer preferences.

    All values persist to `sentinel_settings.json`. After save, the caller
    should rebuild the active tab so combos/checkboxes reflect new values.
    """

    # Widget IDs (local to this dialog)
    COMBO_FPS = 1001
    COMBO_COMP = 1002
    CHK_MULTIPART = 1003
    EDT_SNAP_DIR = 1004
    BTN_BROWSE_DIR = 1005
    COMBO_HISTORY_MAX = 1006
    BTN_CANCEL = 1007
    BTN_SAVE = 1008
    LABEL_STANDARD_FPS = 1009

    # FPS choices in the combo
    FPS_OPTIONS = [24, 25, 30, 60]
    HISTORY_OPTIONS = [5, 10, 20]
    COMP_OPTIONS = ["Nuke", "After Effects"]

    def __init__(self):
        super().__init__()
        self.confirmed = False
        self._standard_fps_overridden = False

    def CreateLayout(self):
        self.SetTitle("Sentinel Settings")

        self.GroupBegin(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(12, 10, 12, 10)
        self.GroupSpace(0, 6)

        # ── Studio Defaults ──
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "▸ Studio Defaults", 0)

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(8, 4)
        self.AddStaticText(self.LABEL_STANDARD_FPS, c4d.BFH_LEFT, 260, 0, "Standard FPS:", 0)
        self.AddComboBox(self.COMBO_FPS, c4d.BFH_LEFT, 100, 0)

        self.AddStaticText(0, c4d.BFH_LEFT, 180, 0, "Default Compositor:", 0)
        self.AddComboBox(self.COMBO_COMP, c4d.BFH_LEFT, 140, 0)

        self.AddStaticText(0, c4d.BFH_LEFT, 180, 0, "", 0)
        self.AddCheckbox(self.CHK_MULTIPART, c4d.BFH_LEFT, 0, 0,
                         "Multi-Part EXR (default for new scenes)")
        self.GroupEnd()

        self.AddSeparatorH(8)

        # ── Paths ──
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "▸ Paths", 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "RS Snapshot directory:", 0)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddEditText(self.EDT_SNAP_DIR, c4d.BFH_SCALEFIT, 0, 0)
        self.AddButton(self.BTN_BROWSE_DIR, c4d.BFH_RIGHT, 80, 0, "Browse...")
        self.GroupEnd()

        self.AddSeparatorH(8)

        # ── History ──
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "▸ History", 0)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(8, 4)
        self.AddStaticText(0, c4d.BFH_LEFT, 200, 0, "Recent versions to show:", 0)
        self.AddComboBox(self.COMBO_HISTORY_MAX, c4d.BFH_LEFT, 80, 0)
        self.GroupEnd()

        self.AddSeparatorH(12)

        # ── Action buttons (right-aligned) ──
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(8, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 100, 0, "Cancel")
        self.AddButton(self.BTN_SAVE, c4d.BFH_RIGHT, 100, 0, "Save")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        # Populate FPS combo + select current value
        for i, fps in enumerate(self.FPS_OPTIONS):
            self.AddChild(self.COMBO_FPS, i, f"{fps} fps")
        try:
            current_fps = GlobalSettings.get_standard_fps()
            doc = c4d.documents.GetActiveDocument()
            rules_context = _active_rules_for_doc(doc)
            self._standard_fps_overridden = (
                rules_context.field_sources.get("standard_fps") == "project"
            )
            if self._standard_fps_overridden:
                current_fps = rules_context.params.get("standard_fps", current_fps)
        except Exception:
            current_fps = 25
            self._standard_fps_overridden = False
        try:
            idx = self.FPS_OPTIONS.index(int(current_fps))
        except ValueError:
            idx = self.FPS_OPTIONS.index(25) if 25 in self.FPS_OPTIONS else 0
        self.SetInt32(self.COMBO_FPS, idx)
        if self._standard_fps_overridden:
            self.SetString(
                self.LABEL_STANDARD_FPS,
                "Standard FPS (overridden by project rules):",
            )
            try:
                self.Enable(self.COMBO_FPS, False)
            except Exception:
                pass

        # Compositor combo
        for i, comp in enumerate(self.COMP_OPTIONS):
            self.AddChild(self.COMBO_COMP, i, comp)
        self.SetInt32(self.COMBO_COMP, int(GlobalSettings.get('comp_target', 0)))

        # Multi-Part checkbox
        self.SetBool(self.CHK_MULTIPART, bool(int(GlobalSettings.get('aov_multipart', 1))))

        # Snapshot dir
        self.SetString(self.EDT_SNAP_DIR, GlobalSettings.get_snapshot_dir())

        # Recent versions max
        for i, n in enumerate(self.HISTORY_OPTIONS):
            self.AddChild(self.COMBO_HISTORY_MAX, i, str(n))
        try:
            current_max = int(GlobalSettings.get('history_max_rows', 5))
        except Exception:
            current_max = 5
        try:
            h_idx = self.HISTORY_OPTIONS.index(current_max)
        except ValueError:
            h_idx = 0
        self.SetInt32(self.COMBO_HISTORY_MAX, h_idx)

        return True

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.confirmed = False
            self.Close()
            return True

        if cid == self.BTN_BROWSE_DIR:
            try:
                chosen = c4d.storage.LoadDialog(
                    title="Select RS Snapshot directory",
                    flags=c4d.FILESELECT_DIRECTORY,
                )
                if chosen:
                    self.SetString(self.EDT_SNAP_DIR, chosen)
            except Exception as e:
                safe_print(f"Browse dialog error: {e}")
            return True

        if cid == self.BTN_SAVE:
            try:
                # Standard FPS
                fps_idx = int(self.GetInt32(self.COMBO_FPS))
                if not self._standard_fps_overridden and 0 <= fps_idx < len(self.FPS_OPTIONS):
                    GlobalSettings.set_standard_fps(self.FPS_OPTIONS[fps_idx])

                # Compositor
                comp_idx = int(self.GetInt32(self.COMBO_COMP))
                GlobalSettings.set('comp_target', comp_idx)

                # Multi-Part
                GlobalSettings.set('aov_multipart', 1 if self.GetBool(self.CHK_MULTIPART) else 0)

                # Snapshot dir
                snap_dir = (self.GetString(self.EDT_SNAP_DIR) or "").strip()
                if snap_dir:
                    GlobalSettings.set_snapshot_dir(snap_dir)

                # History max rows
                h_idx = int(self.GetInt32(self.COMBO_HISTORY_MAX))
                if 0 <= h_idx < len(self.HISTORY_OPTIONS):
                    GlobalSettings.set('history_max_rows', self.HISTORY_OPTIONS[h_idx])
            except Exception as e:
                safe_print(f"Settings save error: {e}")
                c4d.gui.MessageDialog(f"Could not save settings:\n\n{e}")
                return True
            self.confirmed = True
            self.Close()
            return True

        return True


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
# Implementation: one ObjectData marker object per document, auto-
# created at scene root when the panel toggle is enabled. The marker
# draws each active multi-format Take's safe-area rectangle in the
# active camera viewport using screen-space lines positioned via
# `bd.GetSafeFrame()`.
#
# Two-piece architecture:
#   - `_SafeAreaOverlayState` singleton — module-level state shared
#     between the Sentinel panel (CommandData) and the marker object's
#     Draw method. The panel mutates it, the marker reads it.
#   - `SafeAreaOverlayObject(plugins.ObjectData)` — registered with a
#     unique plugin ID. Auto-created in the scene by Sentinel when the
#     overlay toggle is enabled.
#
# Why not TagData on the active camera (originally proposed):
#   TagData.Draw is NOT routed by C4D 2026's Python viewport pipeline —
#   Init and Execute fire as expected, but Draw is never invoked.
#   Verified empirically with the v1.5.6 probe round. ObjectData.Draw
#   on the other hand fires reliably in DRAWPASS_OBJECT regardless of
#   selection, which matches our use case (always-on overlay).
#
# Why a marker object and not a scene-level draw hook:
#   `SceneHookData` was removed in C4D 2026 (the original v1.5.5
#   intent). The ObjectData marker is the closest "always-on" Draw
#   API available in 2026 Python.


# Per-format outline colors. Matched to the cross-platform delivery
# convention (warm/orange for vertical social, cool for square/feed,
# white for the broadcast master, yellow for cinema).
_SAFE_AREA_COLORS = {
    "16x9": c4d.Vector(0.95, 0.95, 0.95),  # white — master/broadcast
    "9x16": c4d.Vector(0.95, 0.55, 0.15),  # orange — IG Reels / TikTok
    "1x1":  c4d.Vector(0.50, 0.85, 0.95),  # cyan — IG Square
    "4x5":  c4d.Vector(0.85, 0.35, 0.85),  # magenta — IG Feed portrait
    "21x9": c4d.Vector(0.95, 0.85, 0.20),  # yellow — cinema
}


class _SafeAreaOverlayState:
    """Module-level singleton for sharing viewport-overlay state between
    the Sentinel panel and the `SafeAreaOverlayObject` marker.

    The panel calls `update_from_doc(doc)` whenever scene topology
    likely changed (overlay toggle, Multi-Format regeneration). The
    marker's Draw reads `enabled` + `format_rects` on every redraw.

    Threading note: C4D runs Draw on the viewport thread. Plain bool
    + list-of-tuples reads are safe; we never mutate from the draw
    side, only read.
    """

    def __init__(self):
        self.enabled = False
        self.master_aspect = 16.0 / 9.0
        # list of (fmt_id, c4d.Vector color, dict safe_box_in_master_ndc)
        self.format_rects = []

    def update_from_doc(self, doc):
        """Recompute cached per-format master-NDC rectangles from the
        current document state."""
        self.format_rects = []
        if doc is None:
            return
        try:
            td = doc.GetTakeData()
            if td is None:
                return
            main_take = td.GetMainTake()
            if main_take is None:
                return
            params = resolve_take_projection_params(main_take, td, doc)
            aspect = params.get("aspect") if params else None
            if aspect is None or aspect <= 0:
                # Fallback: doc's active render data
                rd = doc.GetActiveRenderData()
                if rd:
                    try:
                        w = int(rd[c4d.RDATA_XRES])
                        h = int(rd[c4d.RDATA_YRES])
                        aspect = float(w) / float(h) if h > 0 else (16.0 / 9.0)
                    except Exception:
                        aspect = 16.0 / 9.0
                else:
                    aspect = 16.0 / 9.0
            self.master_aspect = float(aspect)
            rules_context = _active_rules_for_doc(doc)

            mf_takes = find_active_multiformat_takes(doc)
            rects = []
            for fmt_id, _take in mf_takes:
                safe_box = format_safe_area_in_master_ndc(fmt_id,
                                                          self.master_aspect,
                                                          rules_context)
                color = _SAFE_AREA_COLORS.get(fmt_id,
                                              c4d.Vector(0.6, 0.6, 0.6))
                rects.append((fmt_id, color, safe_box))
            self.format_rects = rects
        except Exception as e:
            safe_print(f"SafeAreaOverlay state update error: {e}")


# Module-level singleton instance. Both the panel and the ObjectData
# marker reference it through this name.
_overlay_state = _SafeAreaOverlayState()


# Defensive check: confirm ObjectData + the draw constants we rely on
# exist before defining the class. Falls back to `object` so the
# module still parses if any of these is missing (panel still works,
# just no overlay).
try:
    _ObjectDataBase = plugins.ObjectData
    _ = c4d.DRAWPASS_OBJECT
    _ = c4d.DRAWRESULT_OK
    _ = c4d.DRAWRESULT_SKIP
    _ = c4d.OBJECT_GENERATOR
    _SAFE_AREA_OBJECT_AVAILABLE = True
except Exception as _exc:
    _ObjectDataBase = object
    _SAFE_AREA_OBJECT_AVAILABLE = False
    safe_print(f"ObjectData API not available ({_exc}) — safe-area "
               "viewport overlay disabled. Panel still works.")


class SafeAreaOverlayObject(_ObjectDataBase):
    """ObjectData plugin: a marker null whose Draw renders the cross-
    aspect safe-area rectangles into the active camera viewport.

    Auto-created by the Sentinel panel when the "Show Safe-Area
    Overlay" toggle is enabled. Reads from `_overlay_state` — when
    `enabled` is False or no formats are active, the Draw body skips
    immediately (sub-millisecond overhead).
    """

    def Init(self, node, isCloneInit=False):
        return True

    def Draw(self, op, drawpass, bd, bh):
        # Only do work on DRAWPASS_OBJECT — confirmed via probe that
        # this pass fires regardless of selection. DRAWPASS_HANDLES
        # only fires when the object is selected, which isn't what we
        # want for an always-on overlay.
        if drawpass != c4d.DRAWPASS_OBJECT:
            return c4d.DRAWRESULT_OK

        try:
            if not _overlay_state.enabled:
                return c4d.DRAWRESULT_SKIP
            rects = _overlay_state.format_rects
            if not rects:
                return c4d.DRAWRESULT_SKIP

            # `bd.GetSafeFrame()` returns the safe-frame rectangle in
            # viewport pixel coordinates — i.e. where the camera's
            # actual rendered frame lands (handles letterbox/pillarbox
            # automatically). We position the format rectangles inside
            # this area.
            safe = bd.GetSafeFrame()
            if not safe:
                return c4d.DRAWRESULT_SKIP
            cl = int(safe.get("cl", 0))
            ct = int(safe.get("ct", 0))
            cr = int(safe.get("cr", 0))
            cb = int(safe.get("cb", 0))
            master_w = cr - cl
            master_h = cb - ct
            if master_w < 4 or master_h < 4:
                return c4d.DRAWRESULT_SKIP

            # Switch to 2D screen-space drawing. After this, DrawLine
            # treats Vector(x, y, 0) as pixel coordinates.
            bd.SetMatrix_Screen()

            for fmt_id, color, safe_box in rects:
                # Map master NDC ([-1, +1]) → pixel coords inside the
                # safe-frame rectangle. NDC y=+1 is top, -1 is bottom;
                # screen y increases downward → flip.
                px_left = cl + (safe_box["left"] + 1.0) * 0.5 * master_w
                px_right = cl + (safe_box["right"] + 1.0) * 0.5 * master_w
                px_top = ct + (1.0 - safe_box["top"]) * 0.5 * master_h
                px_bot = ct + (1.0 - safe_box["bottom"]) * 0.5 * master_h

                # Skip degenerate
                if px_right - px_left < 1.0 or px_bot - px_top < 1.0:
                    continue

                bd.SetPen(color)
                p_tl = c4d.Vector(px_left, px_top, 0)
                p_tr = c4d.Vector(px_right, px_top, 0)
                p_br = c4d.Vector(px_right, px_bot, 0)
                p_bl = c4d.Vector(px_left, px_bot, 0)
                bd.DrawLine(p_tl, p_tr, 0)
                bd.DrawLine(p_tr, p_br, 0)
                bd.DrawLine(p_br, p_bl, 0)
                bd.DrawLine(p_bl, p_tl, 0)

                # Format label in the top-left corner of each rect.
                try:
                    bd.DrawHUDText(int(px_left + 4),
                                   int(px_top + 4),
                                   fmt_id)
                except Exception:
                    pass

            return c4d.DRAWRESULT_OK
        except Exception as e:
            safe_print(f"SafeAreaOverlayObject.Draw error: {e}")
            return c4d.DRAWRESULT_SKIP


def find_or_create_safe_area_overlay_object(doc):
    """Locate the existing overlay marker in `doc`, or create one at
    scene root if none exists. Identified by plugin TYPE
    (`SAFE_AREA_OVERLAY_PLUGIN_ID`), so renames don't break detection.

    Returns the BaseObject, or None on failure / when the plugin isn't
    registered (e.g. ObjectData API missing in this C4D build).
    """
    if doc is None or not _SAFE_AREA_OBJECT_AVAILABLE:
        return None

    # Search existing
    def _find(start):
        op = start
        while op is not None:
            if op.GetType() == SAFE_AREA_OVERLAY_PLUGIN_ID:
                return op
            child = op.GetDown()
            if child is not None:
                found = _find(child)
                if found is not None:
                    return found
            op = op.GetNext()
        return None

    existing = _find(doc.GetFirstObject())
    if existing is not None:
        return existing

    # Create new at scene root
    try:
        obj = c4d.BaseObject(SAFE_AREA_OVERLAY_PLUGIN_ID)
        if obj is None:
            return None
        obj.SetName("Sentinel Safe-Area Overlay")
        doc.StartUndo()
        doc.InsertObject(obj)
        doc.AddUndo(c4d.UNDOTYPE_NEW, obj)
        doc.EndUndo()
        c4d.EventAdd()
        return obj
    except Exception as e:
        safe_print(f"Could not create safe-area overlay object: {e}")
        return None


class MultiFormatDialog(gui.GeDialog):
    """Modal dialog: which formats to generate + output mode + composition mode.

    After Open(c4d.DLG_TYPE_MODAL), check `confirmed`. If True, read:
        result_formats          -> list[str] of fmt_id values
        result_output_mode      -> 'subfolder' | 'suffix'
        result_composition_mode -> 'none' | 'resize_canvas'
        result_update_existing  -> bool
    """

    # Widget IDs (local to this dialog)
    LBL_HINT = 1001
    LBL_SOURCE = 1002
    CHK_FORMAT_BASE = 1100  # one checkbox per format: 1100, 1101, ...
    COMBO_OUTPUT_MODE = 1010
    COMBO_COMPOSITION_MODE = 1011
    CHK_UPDATE_EXISTING = 1012
    BTN_CANCEL = 1020
    BTN_GENERATE = 1021

    OUTPUT_MODES = ["subfolder", "suffix"]
    OUTPUT_MODE_LABELS = [
        "Per-format subfolder (output/16x9/, output/9x16/, ...)",
        "Format suffix in filename (file_16x9, file_9x16, ...)",
    ]

    # Composition Mode (camera dimension behavior across formats)
    COMPOSITION_MODES = [COMPOSITION_MODE_NONE, COMPOSITION_MODE_RESIZE_CANVAS]
    COMPOSITION_MODE_LABELS = [
        "None — camera unchanged, just resolution (compose for intersection)",
        "Resize Canvas — sensor-size override (rotates angular field, AR-style)",
    ]

    def __init__(self, source_take_name="Main", source_resolution=None):
        super().__init__()
        self.source_take_name = source_take_name or "Main"
        self.source_resolution = source_resolution  # tuple (w, h) or None
        # Results filled on Generate
        self.confirmed = False
        self.result_formats = []
        self.result_output_mode = "subfolder"
        self.result_composition_mode = COMPOSITION_MODE_NONE
        self.result_update_existing = True

    def CreateLayout(self):
        self.SetTitle("Multi-Format Render Setup")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(12, 10, 12, 10)
        self.GroupSpace(0, 6)

        # Workflow hint — neutral, points to the Composition Mode below
        hint = ("Generates a child Take per delivery format with cloned Render Data\n"
                "(resolution + output path). Camera behavior between formats is\n"
                "controlled by Composition Mode below.")
        self.AddStaticText(self.LBL_HINT, c4d.BFH_SCALEFIT, 0, 0, hint, 0)

        self.AddSeparatorH(8)

        # Source info
        self.AddStaticText(self.LBL_SOURCE, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        self.AddSeparatorH(8)

        # Format checkboxes (3-column grid: checkbox + resolution + description)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "Generate Takes for:", 0)

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupSpace(10, 4)
        for i, fmt in enumerate(MULTIFORMAT_DEFS):
            wid = self.CHK_FORMAT_BASE + i
            self.AddCheckbox(wid, c4d.BFH_LEFT, 0, 0, fmt["label"])
            self.AddStaticText(0, c4d.BFH_LEFT, 110, 0,
                               f"{fmt['width']}×{fmt['height']}", 0)
            self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, fmt["description"], 0)
        self.GroupEnd()

        self.AddSeparatorH(8)

        # Output structure
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Output structure:", 0)
        self.AddComboBox(self.COMBO_OUTPUT_MODE, c4d.BFH_SCALEFIT, 0, 0)

        self.AddSeparatorH(8)

        # Composition mode
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Composition mode:", 0)
        self.AddComboBox(self.COMBO_COMPOSITION_MODE, c4d.BFH_SCALEFIT, 0, 0)

        self.AddSeparatorH(8)

        # Update-existing toggle
        self.AddCheckbox(self.CHK_UPDATE_EXISTING, c4d.BFH_LEFT, 0, 0,
                         "Update existing Takes with same name (skip otherwise)")

        self.AddSeparatorH(12)

        # Action buttons (right-aligned)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(8, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 100, 0, "Cancel")
        self.AddButton(self.BTN_GENERATE, c4d.BFH_RIGHT, 120, 0, "Generate")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        # All formats checked by default
        for i in range(len(MULTIFORMAT_DEFS)):
            self.SetBool(self.CHK_FORMAT_BASE + i, True)

        # Output mode combo
        for i, label in enumerate(self.OUTPUT_MODE_LABELS):
            self.AddChild(self.COMBO_OUTPUT_MODE, i, label)
        self.SetInt32(self.COMBO_OUTPUT_MODE, 0)  # subfolder default

        # Composition mode combo
        for i, label in enumerate(self.COMPOSITION_MODE_LABELS):
            self.AddChild(self.COMBO_COMPOSITION_MODE, i, label)
        self.SetInt32(self.COMBO_COMPOSITION_MODE, 0)  # "none" default

        # Update existing default ON
        self.SetBool(self.CHK_UPDATE_EXISTING, True)

        # Source info caption
        if self.source_resolution:
            w, h = self.source_resolution
            src_txt = f"Source: Take '{self.source_take_name}'  ·  {int(w)}×{int(h)}"
        else:
            src_txt = f"Source: Take '{self.source_take_name}'"
        self.SetString(self.LBL_SOURCE, src_txt)

        return True

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.confirmed = False
            self.Close()
            return True

        if cid == self.BTN_GENERATE:
            # Collect selected format ids
            selected = []
            for i, fmt in enumerate(MULTIFORMAT_DEFS):
                if self.GetBool(self.CHK_FORMAT_BASE + i):
                    selected.append(fmt["id"])

            if not selected:
                c4d.gui.MessageDialog(
                    "Select at least one format to generate."
                )
                return True

            self.result_formats = selected

            # Output mode
            out_idx = int(self.GetInt32(self.COMBO_OUTPUT_MODE))
            if 0 <= out_idx < len(self.OUTPUT_MODES):
                self.result_output_mode = self.OUTPUT_MODES[out_idx]

            # Composition mode
            comp_idx = int(self.GetInt32(self.COMBO_COMPOSITION_MODE))
            if 0 <= comp_idx < len(self.COMPOSITION_MODES):
                self.result_composition_mode = self.COMPOSITION_MODES[comp_idx]

            self.result_update_existing = self.GetBool(self.CHK_UPDATE_EXISTING)

            self.confirmed = True
            self.Close()
            return True

        return True


# ============================================================
# Texture Repathing Dialog (v1.5.7)
# ============================================================

# Persisted Find / Replace history — last 5 pairs, newest first.
TEXTURE_REPATH_PRESETS_KEY = "texture_repath_presets"
TEXTURE_REPATH_PRESETS_MAX = 5


def load_repath_presets():
    """Return the persisted Find/Replace history as a list of
    (find, replace) tuples — newest first, capped at 5.

    Stored in `sentinel_settings.json` as a list of [find, replace]
    pairs. Defensive against a malformed/legacy value.
    """
    raw = GlobalSettings.get(TEXTURE_REPATH_PRESETS_KEY, [])
    out = []
    if isinstance(raw, list):
        for item in raw:
            if (isinstance(item, (list, tuple)) and len(item) == 2):
                f, r = str(item[0]), str(item[1])
                if f:
                    out.append((f, r))
    return out[:TEXTURE_REPATH_PRESETS_MAX]


def save_repath_preset(find_str, replace_str):
    """Push a (find, replace) pair to the front of the persisted
    history. De-dupes an identical existing pair and caps at 5."""
    find_str = (find_str or "").strip()
    if not find_str:
        return
    replace_str = (replace_str or "").strip()
    presets = [p for p in load_repath_presets()
               if not (p[0] == find_str and p[1] == replace_str)]
    presets.insert(0, (find_str, replace_str))
    presets = presets[:TEXTURE_REPATH_PRESETS_MAX]
    try:
        GlobalSettings.set(TEXTURE_REPATH_PRESETS_KEY,
                           [list(p) for p in presets])
    except Exception as e:
        safe_print(f"save_repath_preset error: {e}")


class TextureRepathingDialog(gui.GeDialog):
    """Modal dialog for the Texture Repathing Tool.

    Orchestrates the v1.5.7 feature end-to-end:
      - Scans textures via `scan_all_texture_paths(doc)`
      - Displays them in a `TextureListArea` (scrollable, filterable)
      - Lets the user propose bulk changes (Find / Replace prefix),
        smart actions (Make All Relative, Auto-Find Missing), and
        per-row overrides (file picker via the `[…]` button)
      - Previews changes before commit (pending changes shown in green)
      - Applies all pending changes wrapped in StartUndo / EndUndo so
        a single Cmd+Z reverts the whole batch

    Opened ASYNC (not modal): a modal dialog captures the keyboard, so the
    Cmd+Z shortcut never reaches Cinema 4D and the user cannot undo applied
    changes until the dialog closes. Async keeps C4D interactive.

    Public flow:
        dlg = TextureRepathingDialog(doc)
        dlg.Open(c4d.DLG_TYPE_ASYNC, defaultw=900, defaulth=620)
    """

    # Widget IDs
    LBL_SUMMARY = 1001
    COMBO_FILTER = 1002
    USERAREA_LIST = 1003
    SCROLL_LIST = 1004
    EDIT_FIND = 1010
    EDIT_REPLACE = 1011
    BTN_PREVIEW = 1012
    BTN_APPLY_BULK = 1013
    COMBO_RECENT = 1014
    CHK_MATCH_CASE = 1015
    BTN_MAKE_RELATIVE = 1020
    BTN_AUTO_FIND = 1021
    BTN_CLEAR_PENDING = 1022
    LBL_PENDING_COUNT = 1030
    BTN_CANCEL = 1040
    BTN_APPLY_ALL = 1041

    FILTER_LABELS = [
        ("all",       "All records"),
        ("missing",   "Missing only"),
        ("absolute",  "Absolute only"),
        ("ok",        "OK only"),
        ("asset_uri", "Asset URI only"),
    ]

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.records = []
        # pending changes: dict {record_idx -> new_path_string}
        self.pending_changes = {}
        self.list_ua = None
        self.applied_summary = None  # filled by Apply All for callers
        # Dirty flag set by CoreMessage when the scene changes (e.g. an
        # external Cmd+Z). Consumed by Timer to re-scan and refresh the
        # list so it never shows a stale post-apply state.
        self._needs_rescan = False
        # Find/Replace history shown in the Recent combo (newest first).
        self._recent_presets = []

    # ── Layout ─────────────────────────────────────────
    def CreateLayout(self):
        self.SetTitle("Texture Repathing")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(12, 10, 12, 10)
        self.GroupSpace(0, 6)

        # ── Status summary line ──
        self.AddStaticText(self.LBL_SUMMARY, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        # ── Filter row ──
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupSpace(8, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 50, 0, "Filter:", 0)
        self.AddComboBox(self.COMBO_FILTER, c4d.BFH_LEFT, 180, 0)
        self.AddStaticText(self.LBL_PENDING_COUNT, c4d.BFH_RIGHT, 0, 0, "", 0)
        self.GroupEnd()

        # ── Texture list (scrollable UserArea) ──
        # The UserArea reports its full content height via GetMinSize();
        # the ScrollGroup is the viewport and supplies the scrollbar so
        # long texture lists scroll instead of being clipped.
        self.ScrollGroupBegin(self.SCROLL_LIST,
                              c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                              c4d.SCROLLGROUP_VERT | c4d.SCROLLGROUP_AUTOVERT,
                              0, 260)
        self.AddUserArea(self.USERAREA_LIST, c4d.BFH_SCALEFIT, 600, 400)
        if self.list_ua is None:
            self.list_ua = TextureListArea()
        self.AttachUserArea(self.list_ua, self.USERAREA_LIST)
        self.list_ua.click_callback = self._on_row_click
        self.GroupEnd()

        self.AddSeparatorH(8)

        # ── Bulk Find & Replace ──
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0,
                        "Bulk Find & Replace")
        self.GroupBorderSpace(8, 8, 8, 8)
        self.GroupSpace(6, 4)

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 70, 0, "Find:", 0)
        self.AddEditText(self.EDIT_FIND, c4d.BFH_SCALEFIT, 0, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 70, 0, "Replace with:", 0)
        self.AddEditText(self.EDIT_REPLACE, c4d.BFH_SCALEFIT, 0, 0)
        self.GroupEnd()

        # Recent Find/Replace presets (persisted, last 5)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 70, 0, "Recent:", 0)
        self.AddComboBox(self.COMBO_RECENT, c4d.BFH_SCALEFIT, 0, 0)
        self.GroupEnd()

        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupSpace(6, 0)
        self.AddCheckbox(self.CHK_MATCH_CASE, c4d.BFH_SCALEFIT | c4d.BFV_CENTER,
                         0, 0, "Match case")
        self.AddButton(self.BTN_PREVIEW, c4d.BFH_RIGHT, 110, 0, "Preview")
        self.AddButton(self.BTN_APPLY_BULK, c4d.BFH_RIGHT, 130, 0,
                       "Apply to all matching")
        self.GroupEnd()

        self.GroupEnd()  # bulk

        # ── Smart Actions ──
        self.AddSeparatorH(4)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0, "Smart Actions")
        self.GroupBorderSpace(8, 8, 8, 8)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_AUTO_FIND, c4d.BFH_SCALEFIT, 0, 0,
                       "Auto-Find Missing")
        self.AddButton(self.BTN_MAKE_RELATIVE, c4d.BFH_SCALEFIT, 0, 0,
                       "Make All Relative")
        self.AddButton(self.BTN_CLEAR_PENDING, c4d.BFH_SCALEFIT, 0, 0,
                       "Clear pending")
        self.GroupEnd()

        # ── Footer ──
        self.AddSeparatorH(8)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(8, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 100, 0, "Cancel")
        self.AddButton(self.BTN_APPLY_ALL, c4d.BFH_RIGHT, 160, 0,
                       "Apply All (0)")
        self.GroupEnd()

        self.GroupEnd()  # main
        return True

    def InitValues(self):
        # Populate filter combo
        for i, (val, label) in enumerate(self.FILTER_LABELS):
            self.AddChild(self.COMBO_FILTER, i, label)
        self.SetInt32(self.COMBO_FILTER, 0)

        # Recent Find/Replace history
        self._populate_recent_combo()

        # Find/Replace matching is case-insensitive by default — most
        # users expect "rough" to match "8K_Roughness.jpg".
        self.SetBool(self.CHK_MATCH_CASE, False)

        # Initial scan
        self._rescan()

        # Poll for scene changes (external undo/redo, edits) so the list
        # stays in sync without the user reopening the dialog.
        self.SetTimer(400)
        return True

    # ── Recent Find/Replace presets ────────────────────
    def _populate_recent_combo(self):
        """(Re)build the Recent combo from persisted presets.

        Index 0 is a non-selectable placeholder; indices 1..N map to
        `self._recent_presets[idx-1]`.
        """
        def _clip(s, n=22):
            s = s or ""
            return s if len(s) <= n else s[:n - 1] + "…"

        try:
            self.FreeChildren(self.COMBO_RECENT)
        except Exception:
            pass
        self.AddChild(self.COMBO_RECENT, 0, "Recent find / replace…")
        self._recent_presets = load_repath_presets()
        for i, (f, r) in enumerate(self._recent_presets, start=1):
            label = '"%s"  →  "%s"' % (_clip(f), _clip(r))
            self.AddChild(self.COMBO_RECENT, i, label)
        self.SetInt32(self.COMBO_RECENT, 0)

    # ── Scene-change sync ──────────────────────────────
    def CoreMessage(self, mid, msg):
        """Flag a rescan whenever the scene changes (incl. Cmd+Z)."""
        if mid == c4d.EVMSG_CHANGE:
            self._needs_rescan = True
        return gui.GeDialog.CoreMessage(self, mid, msg)

    def Timer(self, msg):
        """Consume the dirty flag and refresh the list.

        Skipped while there are pending (un-applied) changes so an
        external scene event doesn't wipe an edit the user is mid-way
        through. After a Cmd+Z of our own Apply All, pending_changes is
        already empty, so the reverted state shows up here.
        """
        if self._needs_rescan and not self.pending_changes:
            self._needs_rescan = False
            try:
                self._rescan()
            except Exception:
                pass

    # ── Scan / state ───────────────────────────────────
    def _rescan(self):
        """Re-run the scan and refresh the list area."""
        try:
            self.records = scan_all_texture_paths(self.doc) or []
        except Exception as e:
            safe_print(f"TextureRepathingDialog scan error: {e}")
            self.records = []
        # Drop pending changes that reference indices outside the new
        # range (defensive — if the scene changed between scans).
        self.pending_changes = {
            k: v for k, v in self.pending_changes.items()
            if k < len(self.records)
        }
        self._refresh_summary()
        self._refresh_list()

    def _refresh_summary(self):
        counts = {"missing": 0, "absolute": 0, "asset_uri": 0,
                  "ok": 0, "empty": 0}
        for r in self.records:
            counts[r.get("status", "empty")] = counts.get(
                r.get("status", "empty"), 0) + 1
        total = len(self.records)
        summary = (f"  ✗ {counts['missing']} missing    "
                   f"⚠ {counts['absolute']} absolute    "
                   f"≈ {counts['asset_uri']} asset URI    "
                   f"✓ {counts['ok']} OK    "
                   f"({total} total)")
        try:
            self.SetString(self.LBL_SUMMARY, summary)
        except Exception:
            pass

    def _refresh_list(self):
        if self.list_ua is None:
            return
        filter_idx = int(self.GetInt32(self.COMBO_FILTER))
        filter_val = self.FILTER_LABELS[filter_idx][0] if (
            0 <= filter_idx < len(self.FILTER_LABELS)) else "all"
        self.list_ua.set_state(self.records, filter_val,
                               self.pending_changes)
        # Tell the ScrollGroup to re-query the UserArea's GetMinSize so
        # the scrollbar updates when the row count changes (filter swap,
        # rescan, etc.).
        try:
            self.LayoutChanged(self.SCROLL_LIST)
        except Exception:
            pass
        self._refresh_pending_count()

    def _refresh_pending_count(self):
        n = len(self.pending_changes)
        try:
            self.SetString(self.LBL_PENDING_COUNT,
                           f"Pending changes: {n}")
            # Update the Apply All button label too
            self.SetString(self.BTN_APPLY_ALL, f"Apply All ({n})")
        except Exception:
            pass

    # ── Bulk Find & Replace ────────────────────────────
    def _do_find_replace_preview(self):
        import re
        find_str = self.GetString(self.EDIT_FIND).strip()
        repl_str = self.GetString(self.EDIT_REPLACE).strip()
        if not find_str:
            c4d.gui.MessageDialog("Enter a string in the 'Find' field.")
            return

        # Matching is case-insensitive unless 'Match case' is ticked —
        # most users expect "rough" to match "8K_Roughness.jpg".
        match_case = bool(self.GetBool(self.CHK_MATCH_CASE))

        def _apply_sub(text):
            """Return (matched_bool, new_text) for `text`."""
            if match_case:
                if find_str in text:
                    return True, text.replace(find_str, repl_str)
                return False, text
            # Case-insensitive. A lambda replacement keeps `repl_str`
            # literal — re.sub would otherwise interpret backslashes /
            # group refs in Windows-style replacement paths.
            if find_str.lower() in text.lower():
                return True, re.sub(re.escape(find_str),
                                    lambda m: repl_str, text,
                                    flags=re.IGNORECASE)
            return False, text

        new_pending = dict(self.pending_changes)
        matched = 0
        for i, r in enumerate(self.records):
            status = r.get("status")
            if status in ("asset_uri", "empty"):
                continue
            cur = str(r.get("current_path", ""))
            hit, new_path = _apply_sub(cur)
            if hit:
                new_pending[i] = new_path
                matched += 1
        if matched == 0:
            case_note = ("" if match_case else
                         " (matching is case-insensitive)")
            c4d.gui.MessageDialog(
                f"No paths contain '{find_str}'{case_note}.\n\n"
                "Tip: paths may use 'relative://' or 'file://' URL "
                "prefixes — paste the exact string you see in the list.")
            return
        self.pending_changes = new_pending
        # Persist this Find/Replace pair to the Recent history.
        save_repath_preset(find_str, repl_str)
        self._populate_recent_combo()
        self._refresh_list()
        c4d.gui.MessageDialog(
            f"Previewing {matched} change(s). Review them in the list "
            f"(shown in green below each row) and click 'Apply All' to "
            f"commit, or 'Clear pending' to discard.")

    def _do_make_all_relative(self):
        """Convert every absolute / file:// path to relative-to-doc."""
        doc_path = self.doc.GetDocumentPath() or ""
        if not doc_path:
            c4d.gui.MessageDialog(
                "The document must be saved first — relative paths "
                "are computed against the document folder.")
            return
        new_pending = dict(self.pending_changes)
        converted = 0
        skipped_cross_drive = 0
        for i, r in enumerate(self.records):
            if r.get("status") != "absolute":
                continue
            cur = str(r.get("current_path", ""))
            # If file:// URL, strip the prefix to get the absolute path
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
            new_pending[i] = rel
            converted += 1
        self.pending_changes = new_pending
        self._refresh_list()
        msg = f"{converted} absolute path(s) → relative."
        if skipped_cross_drive:
            msg += (f"\n\n{skipped_cross_drive} path(s) skipped (cross-drive "
                    f"— can't be made relative).")
        c4d.gui.MessageDialog(msg)

    def _do_auto_find_missing(self):
        """For each missing record, search common subdirs by filename."""
        doc_path = self.doc.GetDocumentPath() or ""
        if not doc_path:
            c4d.gui.MessageDialog(
                "The document must be saved first — auto-find searches "
                "subfolders of the document folder.")
            return
        new_pending = dict(self.pending_changes)
        resolved = 0
        ambiguous = 0
        for i, r in enumerate(self.records):
            if r.get("status") != "missing":
                continue
            cur = str(r.get("current_path", ""))
            # Get filename from path / URL
            if cur.startswith("relative://"):
                fname_part = cur[len("relative://"):].lstrip("/")
            elif cur.startswith("file://"):
                fname_part = cur[len("file://"):]
            else:
                fname_part = cur
            fname = os.path.basename(fname_part) if fname_part else ""
            if not fname:
                continue
            candidates = find_missing_texture_candidates(fname, doc_path)
            if len(candidates) == 1:
                # Compute back to a relative URL if possible
                rel = compute_relative_texture_path(candidates[0], doc_path)
                # If the original used relative://, keep that scheme
                if cur.startswith("relative://") and rel:
                    new_pending[i] = "relative:///" + rel
                else:
                    new_pending[i] = rel or candidates[0]
                resolved += 1
            elif len(candidates) > 1:
                ambiguous += 1
        self.pending_changes = new_pending
        self._refresh_list()
        msg = f"Auto-find: {resolved} resolved."
        if ambiguous:
            msg += (f"\n{ambiguous} ambiguous (multiple matches — "
                    f"resolve manually via the [...] button).")
        c4d.gui.MessageDialog(msg)

    def _do_clear_pending(self):
        if not self.pending_changes:
            return
        n = len(self.pending_changes)
        if c4d.gui.QuestionDialog(
                f"Discard {n} pending change(s)?\n\n"
                "(The scene is unchanged — these are just preview changes "
                "that haven't been committed.)"):
            self.pending_changes = {}
            self._refresh_list()

    # ── Per-row file picker (browse callback) ──────────
    def _on_row_click(self, rec_idx, region):
        if rec_idx < 0 or rec_idx >= len(self.records):
            return
        rec = self.records[rec_idx]
        status = rec.get("status")
        if status in ("asset_uri", "empty"):
            return
        # Always open a file picker — the existing path / pending change
        # is just preview info, not the picker target.
        host_name = rec.get("host_name", "<?>")
        cur = str(rec.get("current_path", ""))
        picked = c4d.storage.LoadDialog(
            title=f"Select texture for '{host_name}'",
            flags=c4d.FILESELECT_LOAD,
        )
        if not picked:
            return
        # Try to make it relative to doc; otherwise use as absolute.
        doc_path = self.doc.GetDocumentPath() or ""
        rel = compute_relative_texture_path(picked, doc_path) if doc_path else None
        if rel:
            # Preserve URL scheme when the original was relative://
            if cur.startswith("relative://"):
                self.pending_changes[rec_idx] = "relative:///" + rel
            else:
                self.pending_changes[rec_idx] = rel
        else:
            # Cross-drive or unsaved doc — keep absolute
            self.pending_changes[rec_idx] = picked
        self._refresh_list()

    # ── Apply All ──────────────────────────────────────
    def _do_apply_all(self):
        if not self.pending_changes:
            c4d.gui.MessageDialog("No pending changes to apply.")
            return False

        n_total = len(self.pending_changes)
        if not c4d.gui.QuestionDialog(
                f"Apply {n_total} change(s) to the scene?\n\n"
                "All changes are wrapped in a single undo step — "
                "Cmd+Z reverts the whole batch."):
            return False

        succeeded = 0
        failed = []
        try:
            self.doc.StartUndo()
            for idx, new_path in list(self.pending_changes.items()):
                if idx >= len(self.records):
                    failed.append((idx, "index out of range"))
                    continue
                rec = self.records[idx]
                try:
                    ok = apply_texture_path_change(rec, new_path, self.doc)
                    if ok:
                        succeeded += 1
                    else:
                        failed.append((idx, "writer returned False"))
                except Exception as e:
                    failed.append((idx, str(e)))
        finally:
            try:
                self.doc.EndUndo()
            except Exception:
                pass
            try:
                c4d.EventAdd()
            except Exception:
                pass

        # Build summary
        lines = [f"Applied {succeeded} of {n_total} change(s)."]
        if failed:
            lines.append("")
            lines.append(f"Failed ({len(failed)}):")
            for idx, err in failed[:8]:
                host = "<?>"
                if 0 <= idx < len(self.records):
                    host = self.records[idx].get("host_name", "<?>")
                lines.append(f"  • [{host}] {err}")
            if len(failed) > 8:
                lines.append(f"  ... +{len(failed) - 8} more")
        c4d.gui.MessageDialog("\n".join(lines))

        self.applied_summary = {
            "applied": succeeded,
            "failed": failed,
            "total": n_total,
        }
        # Clear pending + rescan (file system may have changed too)
        self.pending_changes = {}
        self._rescan()
        return True

    # ── Command dispatch ───────────────────────────────
    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.Close()
            return True

        if cid == self.COMBO_FILTER:
            self._refresh_list()
            return True

        if cid == self.COMBO_RECENT:
            # Selecting a recent preset fills the Find/Replace fields,
            # then the combo snaps back to the placeholder.
            idx = int(self.GetInt32(self.COMBO_RECENT))
            if 1 <= idx <= len(self._recent_presets):
                find_str, repl_str = self._recent_presets[idx - 1]
                self.SetString(self.EDIT_FIND, find_str)
                self.SetString(self.EDIT_REPLACE, repl_str)
            self.SetInt32(self.COMBO_RECENT, 0)
            return True

        if cid == self.BTN_PREVIEW:
            self._do_find_replace_preview()
            return True

        if cid == self.BTN_APPLY_BULK:
            # Preview is non-destructive — apply just calls preview which
            # already stores into pending_changes. Same operation.
            self._do_find_replace_preview()
            return True

        if cid == self.BTN_MAKE_RELATIVE:
            self._do_make_all_relative()
            return True

        if cid == self.BTN_AUTO_FIND:
            self._do_auto_find_missing()
            return True

        if cid == self.BTN_CLEAR_PENDING:
            self._do_clear_pending()
            return True

        if cid == self.BTN_APPLY_ALL:
            # Apply and keep the dialog open for further repath rounds.
            # The dialog is opened ASYNC, so Cinema 4D stays interactive —
            # the user can Cmd+Z the applied batch (a single undo step)
            # without closing the tool. _do_apply_all rescans on success
            # so the list reflects the new scene state.
            self._do_apply_all()
            return True

        return True


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
    baseline_collection_active = bool(original_baseline_path)
    if baseline_collection_active:
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

    if baseline_collection_active and rules_context.rules_path:
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
_COL_GREEN = c4d.Vector(0.3, 1, 0.3)
_COL_RED = c4d.Vector(1, 0.3, 0.3)
_COL_YELLOW = c4d.Vector(1, 1, 0.3)
_COL_GRAY = c4d.Vector(0.5, 0.5, 0.5)
_COL_BG = c4d.Vector(0.08, 0.08, 0.08)
_COL_BLACK = c4d.Vector(0, 0, 0)
_COL_BG_OK = c4d.Vector(0.15, 0.15, 0.15)
_COL_BG_WARN = c4d.Vector(0.25, 0.20, 0.10)
_COL_BG_FAIL = c4d.Vector(0.25, 0.10, 0.10)


# Helper: convert msg[BFM_INPUT_X/Y] (window-global in C4D 2026 Python) to
# user-area-local coordinates. GeUserArea.Local2Global() with NO args returns
# the user area's window origin as {'x': ..., 'y': ...}. Subtracting that from
# the raw msg coords gives correct local coords. Verified empirically — the
# documented Global2Local(x, y) does NOT return area-local in C4D 2026.
def _ua_local_coords(user_area, mx, my):
    """Return (local_x, local_y) for a window-global click on the given GeUserArea."""
    try:
        origin = user_area.Local2Global()
    except Exception:
        return mx, my
    try:
        if isinstance(origin, dict):
            ox = origin.get("x", 0)
            oy = origin.get("y", 0)
        else:
            ox, oy = origin[0], origin[1]
        return int(mx) - int(ox), int(my) - int(oy)
    except Exception:
        return mx, my

# Score header colors (lighter palette for the badge area)
_COL_SCORE_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_SCORE_GREEN = c4d.Vector(0.30, 0.80, 0.40)
_COL_SCORE_YELLOW = c4d.Vector(0.95, 0.75, 0.25)
_COL_SCORE_RED = c4d.Vector(0.90, 0.35, 0.35)
_COL_SCORE_TRACK = c4d.Vector(0.20, 0.20, 0.20)
_COL_SCORE_TEXT = c4d.Vector(0.95, 0.95, 0.95)
_COL_SCORE_TEXT_DIM = c4d.Vector(0.60, 0.60, 0.60)


class ScoreHeader(gui.GeUserArea):
    """Visual summary header: progress bar + pass count + scene stats — single line."""

    HEIGHT = 26

    def __init__(self):
        super().__init__()
        self.passed = 0
        self.total = 0
        self.stats_text = ""

    def GetMinSize(self):
        return 400, self.HEIGHT

    def set_state(self, passed, total, stats_text):
        self.passed = max(0, int(passed))
        self.total = max(1, int(total))
        self.stats_text = stats_text or ""
        self.Redraw()

    def _measure(self, text):
        try:
            return int(self.DrawGetTextWidth(text))
        except Exception:
            return len(text) * 6

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            # Background
            self.DrawSetPen(_COL_SCORE_BG)
            self.DrawRectangle(0, 0, w, h)

            # Status color/label
            ratio = self.passed / self.total if self.total > 0 else 0.0
            if ratio >= 0.999:
                bar_color = _COL_SCORE_GREEN
                status_label = "PASS"
            elif ratio >= 0.7:
                bar_color = _COL_SCORE_YELLOW
                status_label = "WARN"
            else:
                bar_color = _COL_SCORE_RED
                status_label = "FAIL"

            # Single-line vertical centering
            text_h = 12
            text_y = (h - text_h) // 2
            bar_h = 6
            bar_y = (h - bar_h) // 2

            margin = 8
            try:
                self.DrawSetFont(c4d.FONT_BOLD)
            except Exception:
                pass

            # 1. "QC X/Y" label (left)
            qc_label = f"QC {self.passed}/{self.total}"
            self.DrawSetTextCol(_COL_SCORE_TEXT, _COL_SCORE_BG)
            self.DrawText(qc_label, margin, text_y)
            qc_w = self._measure(qc_label)

            # 2. Status word right after
            status_x = margin + qc_w + 10
            self.DrawSetTextCol(bar_color, _COL_SCORE_BG)
            self.DrawText(status_label, status_x, text_y)
            status_w = self._measure(status_label)

            try:
                self.DrawSetFont(c4d.FONT_DEFAULT)
            except Exception:
                pass

            # 3. Stats text (right-aligned, dim grey) — measure FIRST to reserve space
            stats_x_start = w - margin
            if self.stats_text:
                tx_w = self._measure(self.stats_text)
                stats_x_start = w - margin - tx_w
                self.DrawSetTextCol(_COL_SCORE_TEXT_DIM, _COL_SCORE_BG)
                self.DrawText(self.stats_text, stats_x_start, text_y)

            # 4. Progress bar fills the middle space between status and stats
            bar_x_start = status_x + status_w + 12
            bar_x_end = stats_x_start - 12

            if bar_x_end > bar_x_start + 20:
                self.DrawSetPen(_COL_SCORE_TRACK)
                self.DrawRectangle(bar_x_start, bar_y, bar_x_end, bar_y + bar_h)
                if ratio > 0:
                    fill_w = max(2, int((bar_x_end - bar_x_start) * ratio))
                    self.DrawSetPen(bar_color)
                    self.DrawRectangle(bar_x_start, bar_y, bar_x_start + fill_w, bar_y + bar_h)

        except Exception as e:
            safe_print(f"Error in ScoreHeader.DrawMsg: {e}")


# Legacy alias: (severity, ok_message, fail_template, name_key_for_first).
# Backed by CHECK_REGISTRY so consumers do not maintain a second check list.
_CHECK_DISPLAY = CheckDisplayView()

class StatusArea(gui.GeUserArea):
    # Row order matches CHECK_REGISTRY; index here = clickable row index.
    ROW_KEYS = RowKeysView()

    def __init__(self):
        super().__init__()
        self.data = {}
        self.show = {k: True for k in _CHECK_DISPLAY}
        self.pad = 3
        self.rowh = 20
        self.font = c4d.FONT_MONOSPACED
        self.last_draw_time = 0
        self.min_draw_interval = 0.05
        # Click interaction (hover not supported: C4D 2026 Python does not route
        # BFM_GETCURSORINFO to embedded GeUserAreas)
        self.click_callback = None  # set by parent dialog: callable(row_key)

    def GetMinSize(self):
        rows = sum(1 for _, v in self.show.items() if v)
        return 400, max(1, rows) * (self.rowh + self.pad) + self.pad + 4

    def set_state(self, data, show):
        self.data = data or {}
        self.show = show or self.show

        # Throttle redraws
        now = time.time()
        if now - self.last_draw_time > self.min_draw_interval:
            self.Redraw()
            self.last_draw_time = now

    # ---- mouse interaction ----
    def _y_to_row(self, y):
        """Map y coordinate (local) to a visible row index, or -1 if outside."""
        try:
            y = int(y) - self.pad
            if y < 0:
                return -1
            row_pixel = self.rowh + self.pad
            visible_idx = y // row_pixel
            visible_keys = [k for k in self.ROW_KEYS if self.show.get(k, False)]
            if 0 <= visible_idx < len(visible_keys):
                return visible_idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        """Handle clicks. Called by C4D on mouse interaction over the GeUserArea."""
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            row = self._y_to_row(int(local_y))
            if row >= 0 and self.click_callback is not None:
                visible_keys = [k for k in self.ROW_KEYS if self.show.get(k, False)]
                if row < len(visible_keys):
                    self.click_callback(visible_keys[row])
                    return True
        except Exception as e:
            safe_print(f"StatusArea.InputEvent error: {e}")
        return False

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            x = self.pad
            y = self.pad

            for entry in CHECK_REGISTRY:
                label = entry.row_label
                key = entry.check_id
                if not self.show.get(key, False):
                    continue

                val = int(self.data.get(key, 0))
                cfg = _CHECK_DISPLAY.get(key)
                if not cfg:
                    continue

                severity, ok_msg, fail_tpl, name_key = cfg
                severity = self.data.get("_severity_by_id", {}).get(key, severity)
                disabled = key in set(self.data.get("_disabled_checks", []))
                baseline_counts = {}
                if self.data.get("_baseline_active"):
                    baseline_counts = self.data.get("_baseline_counts", {}).get(key, {}) or {}
                accepted_count = int(baseline_counts.get("accepted", 0) or 0)
                stale_count = int(baseline_counts.get("stale", 0) or 0)

                if disabled:
                    status = "[OFF ]"
                    message = "Disabled by project rules"
                    text_col = _COL_GRAY
                    bg = _COL_BG
                elif val > 0:
                    status = f"[{severity}]"
                    first = ""
                    if name_key:
                        names = self.data.get(name_key, [])
                        first = names[0] if names else "object"
                    if accepted_count:
                        message = format_baseline_row_message(val, accepted_count, stale_count)
                    else:
                        message = fail_tpl.format(n=val, first=first)
                    if name_key and val > 1 and not accepted_count:
                        message += f" (+{val-1} more)"
                    if stale_count and not accepted_count:
                        message += f" · {stale_count} obsoletas"
                    text_col = _COL_RED if severity == "FAIL" else _COL_YELLOW
                    bg = _COL_BG_FAIL if severity == "FAIL" else _COL_BG_WARN
                else:
                    status = "[OK*]" if accepted_count else "[ OK ]"
                    message = format_baseline_row_message(0, accepted_count, stale_count) if accepted_count else ok_msg
                    if stale_count and not accepted_count:
                        message += f" · {stale_count} obsoletas"
                    text_col = _COL_GREEN
                    bg = _COL_BG_OK

                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(y), int(w - self.pad), int(y + self.rowh))

                text_y = int(y + (self.rowh - 12) // 2)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(status, int(x + 5), text_y)

                self.DrawSetTextCol(_COL_GRAY, _COL_BLACK)
                self.DrawText(f"{label.ljust(13)}:", int(x + 55), text_y)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(message, int(x + 175), text_y)

                y += self.rowh + self.pad

        except Exception as e:
            safe_print(f"Error in DrawMsg: {e}")


# ---------------- Browse Versions UserArea ----------------
# Color palette for status badges (subtle backgrounds, ~70% saturation)
_COL_BADGE_WIP = c4d.Vector(0.35, 0.35, 0.35)        # neutral grey
_COL_BADGE_TR = c4d.Vector(0.55, 0.42, 0.18)         # amber
_COL_BADGE_CR = c4d.Vector(0.20, 0.40, 0.65)         # blue
_COL_BADGE_FINAL = c4d.Vector(0.25, 0.55, 0.30)      # green
_COL_BADGE_CUSTOM = c4d.Vector(0.45, 0.30, 0.55)     # purple

_COL_HISTORY_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_HISTORY_ROW_BG = c4d.Vector(0.14, 0.14, 0.14)
_COL_HISTORY_ROW_ALT = c4d.Vector(0.16, 0.16, 0.16)
_COL_HISTORY_TEXT = c4d.Vector(0.85, 0.85, 0.85)
_COL_HISTORY_DIM = c4d.Vector(0.55, 0.55, 0.55)


def _badge_color_for_status(status):
    """Pick the badge background color for a status string."""
    s = (status or "").upper()
    if s == "" or s == "WIP":
        return _COL_BADGE_WIP
    if s == "TR":
        return _COL_BADGE_TR
    if s == "CR":
        return _COL_BADGE_CR
    if s == "FINAL":
        return _COL_BADGE_FINAL
    return _COL_BADGE_CUSTOM


class HistoryArea(gui.GeUserArea):
    """Custom-drawn list of recent versions. One row per entry, status-coded badges.

    set_entries(entries) updates the list. click_callback(entry_dict) fires on row click.
    """

    ROW_HEIGHT = 22
    ROW_PAD = 2
    EMPTY_HEIGHT = 28

    def __init__(self):
        super().__init__()
        self.entries = []                # list of formatted dicts (output of format_version_row)
        self.click_callback = None       # callable(entry_dict)
        self.empty_msg = "No versions yet"
        self.font = c4d.FONT_DEFAULT

    def GetMinSize(self):
        rows = max(1, len(self.entries))
        h = rows * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 2
        if not self.entries:
            h = self.EMPTY_HEIGHT
        return 400, h

    def set_entries(self, entries):
        self.entries = list(entries) if entries else []
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    # ── click detection ─────────────────────────────
    def _y_to_index(self, y):
        try:
            y = int(y) - self.ROW_PAD
            if y < 0:
                return -1
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            idx = y // row_pixel
            if 0 <= idx < len(self.entries):
                return idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            idx = self._y_to_index(int(local_y))
            if idx >= 0 and self.click_callback is not None:
                self.click_callback(self.entries[idx])
                return True
        except Exception as e:
            safe_print(f"HistoryArea.InputEvent error: {e}")
        return False

    # ── drawing ─────────────────────────────────────
    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_HISTORY_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self.entries:
                # Empty state
                self.DrawSetTextCol(_COL_HISTORY_DIM, _COL_HISTORY_BG)
                self.DrawText(self.empty_msg, 8, (h - 12) // 2)
                return

            # Layout: [v###] [BADGE] [comment............] [QC] [time]
            COL_VER_W = 50
            COL_BADGE_W = 50
            COL_QC_W = 50
            COL_TIME_W = 70
            margin = 6

            x = self.ROW_PAD
            y = self.ROW_PAD

            for i, entry in enumerate(self.entries):
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                # Alternating row background
                bg = _COL_HISTORY_ROW_ALT if (i % 2) else _COL_HISTORY_ROW_BG
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top), int(w - self.ROW_PAD), int(row_bot))

                text_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)
                cx = int(x + margin)

                # Version label
                self.DrawSetTextCol(_COL_HISTORY_TEXT, bg)
                self.DrawText(entry.get("version_label", "v???"), cx, text_y)
                cx += COL_VER_W

                # Status badge — colored rect with status text inside
                status = entry.get("status_label", "WIP")
                badge_col = _badge_color_for_status(status)
                badge_x0 = cx
                badge_x1 = cx + COL_BADGE_W - 6
                badge_y0 = row_top + 4
                badge_y1 = row_bot - 4
                self.DrawSetPen(badge_col)
                self.DrawRectangle(int(badge_x0), int(badge_y0), int(badge_x1), int(badge_y1))
                # Center the text inside the badge
                try:
                    txt_w = int(self.DrawGetTextWidth(status))
                except Exception:
                    txt_w = len(status) * 6
                badge_text_x = int(badge_x0 + ((badge_x1 - badge_x0) - txt_w) // 2)
                self.DrawSetTextCol(c4d.Vector(1, 1, 1), badge_col)
                self.DrawText(status, badge_text_x, text_y)
                cx += COL_BADGE_W

                # Time (right-aligned)
                tx_right = w - margin
                time_label = entry.get("time_label", "")
                if time_label:
                    try:
                        tw = int(self.DrawGetTextWidth(time_label))
                    except Exception:
                        tw = len(time_label) * 6
                    self.DrawSetTextCol(_COL_HISTORY_DIM, bg)
                    self.DrawText(time_label, int(tx_right - tw), text_y)
                    tx_right -= (tw + margin * 2)

                # QC label (just left of time, if present)
                qc_label = entry.get("qc_label", "")
                if qc_label:
                    try:
                        qw = int(self.DrawGetTextWidth(qc_label))
                    except Exception:
                        qw = len(qc_label) * 6
                    qc_color = _COL_HISTORY_DIM
                    qc_pass = entry.get("qc_pass")
                    if qc_pass is True:
                        qc_color = _COL_GREEN
                    elif qc_pass is False:
                        qc_color = _COL_YELLOW
                    self.DrawSetTextCol(qc_color, bg)
                    self.DrawText(qc_label, int(tx_right - qw), text_y)
                    tx_right -= (qw + margin * 2)

                # Comment (fills remaining space — may need truncation)
                comment = entry.get("comment", "")
                if comment:
                    avail_w = max(20, tx_right - cx - margin)
                    # Crude truncation: clip if too long
                    truncated = comment
                    try:
                        full_w = int(self.DrawGetTextWidth(truncated))
                        if full_w > avail_w:
                            # binary chop
                            while truncated and int(self.DrawGetTextWidth(truncated + "...")) > avail_w:
                                truncated = truncated[:-1]
                            truncated = truncated + "..." if truncated != comment else truncated
                    except Exception:
                        if len(truncated) > 60:
                            truncated = truncated[:57] + "..."
                    self.DrawSetTextCol(_COL_HISTORY_TEXT, bg)
                    self.DrawText(f'"{truncated}"', cx, text_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"Error in HistoryArea.DrawMsg: {e}")


# ============================================================
# Texture Repathing — TextureListArea (v1.5.7)
# ============================================================
# Custom-drawn list of texture records produced by
# `scan_all_texture_paths(doc)`. One row per record:
#
#   [status] host_name (channel)  current_path...  [...]
#   → new_path (only if pending change)
#
# Status glyphs (BMP-compatible):
#   ✗  missing  — red
#   ⚠  absolute — amber
#   ≈  asset_uri — light blue (READ-ONLY, no `[...]` button)
#   ✓  ok        — green
#
# Asset URIs are dimmed and not interactive — they're managed by the
# renderer's internal asset manager (RS Asset Manager, Octane Asset DB,
# Arnold Asset DB) and shouldn't be edited from Sentinel.

_COL_TEXLIST_BG       = c4d.Vector(0.10, 0.10, 0.10)
_COL_TEXLIST_ROW      = c4d.Vector(0.14, 0.14, 0.14)
_COL_TEXLIST_ROW_ALT  = c4d.Vector(0.16, 0.16, 0.16)
_COL_TEXLIST_TEXT     = c4d.Vector(0.85, 0.85, 0.85)
_COL_TEXLIST_DIM      = c4d.Vector(0.55, 0.55, 0.55)
_COL_TEXLIST_GREEN    = c4d.Vector(0.30, 0.80, 0.40)
_COL_TEXLIST_RED      = c4d.Vector(0.95, 0.40, 0.40)
_COL_TEXLIST_AMBER    = c4d.Vector(0.95, 0.75, 0.30)
_COL_TEXLIST_BLUE     = c4d.Vector(0.45, 0.75, 0.95)
_COL_TEXLIST_PENDING  = c4d.Vector(0.40, 0.85, 0.45)
_COL_TEXLIST_BTN_BG   = c4d.Vector(0.22, 0.22, 0.22)


def _format_path_compact(path, max_chars=60):
    """Smart middle-truncate of a path string for display.

    Keeps the start (so the artist sees the prefix that's usually the
    interesting part — `relative://`, `/Users/foo/`, etc.) AND the
    filename at the end. Drops the middle when too long.
    """
    if not path:
        return ""
    s = str(path)
    if len(s) <= max_chars:
        return s
    keep_end = max(20, max_chars // 2)
    keep_start = max(10, max_chars - keep_end - 3)
    return s[:keep_start] + "..." + s[-keep_end:]


class TextureListArea(gui.GeUserArea):
    """Scrollable custom-drawn list of texture records for the
    Repathing dialog.

    State is set via `set_state(records, filter_status, pending_changes)`.
    Clicks are routed through `click_callback(record_idx, region)` where
    `region` is one of:
      - "row"    — click on the row body (open file picker)
      - "browse" — click on the `[...]` browse button
      - None     — click in unfilled area
    Asset URI rows are not clickable (they call back with region=None).
    """

    ROW_HEIGHT = 38      # 2 lines per row: path + optional pending preview
    ROW_PAD = 2
    EMPTY_HEIGHT = 36
    BROWSE_BTN_W = 26
    MARGIN = 6

    # Filter values
    FILTER_ALL = "all"
    FILTER_MISSING = "missing"
    FILTER_ABSOLUTE = "absolute"
    FILTER_OK = "ok"
    FILTER_ASSET_URI = "asset_uri"

    def __init__(self):
        super().__init__()
        self.records = []                 # full list from scan
        self.filter_status = self.FILTER_ALL
        self.pending_changes = {}         # {record_idx: new_path_str}
        self.click_callback = None        # callable(record_idx, region)
        self.empty_msg = "No textures in scene"
        self.font = c4d.FONT_DEFAULT
        # Computed during draw — used by hit-testing
        self._visible_indices = []        # filtered indices in display order

    # ── state ───────────────────────────────────────
    def set_state(self, records, filter_status=None, pending_changes=None):
        self.records = list(records) if records else []
        if filter_status is not None:
            self.filter_status = filter_status
        if pending_changes is not None:
            self.pending_changes = dict(pending_changes)
        self._recompute_visible()
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    def _recompute_visible(self):
        f = self.filter_status
        if f == self.FILTER_ALL:
            self._visible_indices = list(range(len(self.records)))
        else:
            self._visible_indices = [
                i for i, r in enumerate(self.records)
                if r.get("status") == f
            ]

    def GetMinSize(self):
        # Report the FULL content height — the enclosing ScrollGroup is
        # the viewport and supplies the scrollbar. Returning the real
        # height is what tells the scroll group the content overflows.
        if not self._visible_indices:
            return 400, self.EMPTY_HEIGHT
        n = len(self._visible_indices)
        h = n * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 4
        return 400, h

    # ── click detection ─────────────────────────────
    def _hit_test(self, local_x, local_y):
        """Return (record_idx, region) for a click at local coords.
        record_idx is the absolute index into self.records (not the
        filtered display index). region: "row" | "browse" | None.
        """
        try:
            y = int(local_y) - self.ROW_PAD
            if y < 0:
                return -1, None
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            display_idx = y // row_pixel
            if not (0 <= display_idx < len(self._visible_indices)):
                return -1, None
            rec_idx = self._visible_indices[display_idx]
            rec = self.records[rec_idx]
            status = rec.get("status")
            if status in ("asset_uri", "empty"):
                return rec_idx, None  # not interactive

            # Browse button is the rightmost BROWSE_BTN_W pixels
            w = self.GetWidth()
            x = int(local_x)
            if x >= w - self.BROWSE_BTN_W - self.MARGIN:
                return rec_idx, "browse"
            return rec_idx, "row"
        except Exception:
            return -1, None

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            lx, ly = _ua_local_coords(self, mx, my)
            rec_idx, region = self._hit_test(lx, ly)
            if rec_idx >= 0 and region is not None and self.click_callback:
                self.click_callback(rec_idx, region)
                return True
        except Exception as e:
            safe_print(f"TextureListArea.InputEvent error: {e}")
        return False

    # ── drawing ─────────────────────────────────────
    def _status_glyph_color(self, status):
        return {
            "missing":   ("✗", _COL_TEXLIST_RED),
            "absolute":  ("⚠", _COL_TEXLIST_AMBER),
            "asset_uri": ("≈", _COL_TEXLIST_BLUE),
            "ok":        ("✓", _COL_TEXLIST_GREEN),
            "empty":     ("·", _COL_TEXLIST_DIM),
        }.get(status, ("?", _COL_TEXLIST_DIM))

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()
            self.DrawSetPen(_COL_TEXLIST_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self._visible_indices:
                msg_txt = (self.empty_msg if not self.records
                           else f"No textures match filter "
                                f"'{self.filter_status}'")
                self.DrawSetTextCol(_COL_TEXLIST_DIM, _COL_TEXLIST_BG)
                self.DrawText(msg_txt, 8, (h - 12) // 2)
                return

            # Column layout (approximate widths within available width)
            #   [status 22] [host 180] [channel 100] [path expand] [btn 26]
            COL_STATUS = 22
            COL_HOST = 180
            COL_CHAN = 100
            BTN_W = self.BROWSE_BTN_W
            margin = self.MARGIN

            x = self.ROW_PAD
            y = self.ROW_PAD

            for display_idx, rec_idx in enumerate(self._visible_indices):
                rec = self.records[rec_idx]
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                # Skip rows fully outside the redraw clip region — keeps
                # drawing cheap when the scrolled list is long.
                if row_bot < y1 or row_top > y2:
                    y += self.ROW_HEIGHT + self.ROW_PAD
                    continue
                bg = (_COL_TEXLIST_ROW_ALT if (display_idx % 2)
                      else _COL_TEXLIST_ROW)
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top),
                                   int(w - self.ROW_PAD), int(row_bot))

                # Two-line layout: first line = main info, second = pending
                # change (or current path if no pending). 14px line height.
                line1_y = int(row_top + 4)
                line2_y = int(row_top + 4 + 16)
                status = rec.get("status", "")
                glyph, glyph_col = self._status_glyph_color(status)

                # Status glyph
                self.DrawSetTextCol(glyph_col, bg)
                self.DrawText(glyph, int(x + margin), line1_y)

                cx = int(x + margin + COL_STATUS)

                # Host name (truncated if too long)
                host = str(rec.get("host_name", "<?>"))
                if len(host) > 28:
                    host = host[:25] + "..."
                self.DrawSetTextCol(_COL_TEXLIST_TEXT, bg)
                self.DrawText(host, cx, line1_y)
                cx += COL_HOST

                # Channel name
                channel = str(rec.get("channel", ""))[:16]
                self.DrawSetTextCol(_COL_TEXLIST_DIM, bg)
                self.DrawText(channel, cx, line1_y)
                cx += COL_CHAN

                # Source type tag (small, right of channel) — useful at a
                # glance to know which renderer this is from.
                stype = rec.get("source_type", "")
                stype_short = stype.replace("_shader", "").replace(
                    "_node", "/node").replace("_oct_", "/oct ").replace(
                    "_fileref", "/ref")
                self.DrawSetTextCol(_COL_TEXLIST_DIM, bg)
                self.DrawText(f"[{stype_short}]", cx, line1_y)

                # Browse button — rightmost. Hidden for non-interactive
                # rows (asset_uri / empty).
                interactive = status not in ("asset_uri", "empty")
                if interactive:
                    btn_x0 = int(w - BTN_W - margin)
                    btn_y0 = int(row_top + 4)
                    btn_y1 = int(row_top + self.ROW_HEIGHT - 4)
                    self.DrawSetPen(_COL_TEXLIST_BTN_BG)
                    self.DrawRectangle(btn_x0, btn_y0,
                                       int(w - margin), btn_y1)
                    self.DrawSetTextCol(_COL_TEXLIST_TEXT,
                                        _COL_TEXLIST_BTN_BG)
                    self.DrawText("...",
                                  btn_x0 + 6, btn_y0 + 4)

                # Second line: pending change OR current path
                pending = self.pending_changes.get(rec_idx)
                if pending:
                    # Show "→ new_path" in green
                    self.DrawSetTextCol(_COL_TEXLIST_PENDING, bg)
                    pending_short = _format_path_compact(pending, 80)
                    self.DrawText(f"→ {pending_short}",
                                  int(x + margin + COL_STATUS), line2_y)
                else:
                    # Show current path muted
                    cur = _format_path_compact(rec.get("current_path", ""), 80)
                    text_col = (_COL_TEXLIST_DIM if status == "asset_uri"
                                else _COL_TEXLIST_TEXT)
                    self.DrawSetTextCol(text_col, bg)
                    self.DrawText(cur,
                                  int(x + margin + COL_STATUS), line2_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"Error in TextureListArea.DrawMsg: {e}")


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
    converter = os.path.join(os.path.dirname(__file__), "exr_converter_external.py")
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
class G:
    # Scene info
    SHOT = 1001
    ARTIST = 1003
    CANVAS = 1008
    SCORE_CANVAS = 1180  # ScoreHeader UserArea
    LABEL_FILENAME = 1192  # Scene identity caption (filename of active doc)
    LABEL_RULES = 1193     # Active ruleset caption

    # Tabbed layout (Phase 2 of UI redesign)
    TAB_BAR = 1200            # CUSTOMGUI_QUICKTAB widget
    TAB_CONTAINER = 1209      # Single container — only active tab content lives inside
    TAB_GROUP_QC = 1210       # Inner group ID for QC content
    TAB_GROUP_RENDER = 1211   # Inner group ID for Render content
    TAB_GROUP_VERSIONS = 1212 # Inner group ID for Versions content
    TAB_GROUP_TOOLS = 1213    # Inner group ID for Tools content

    # Per-check action buttons (1 click to select/info)
    BTN_SEL_LIGHTS = 1130
    BTN_SEL_VIS = 1131
    BTN_SEL_KEYS = 1132
    BTN_SEL_CAMS = 1133
    BTN_INFO_PRESET = 1134
    BTN_INFO_TEXTURES = 1135
    BTN_SEL_UNUSED_MATS = 1136
    BTN_SEL_NAMES = 1137
    BTN_INFO_OUTPUT = 1138
    BTN_INFO_FPS = 1139
    BTN_SEL_CROSS_ASPECT = 1144  # Select objects with cross-aspect violations
    BTN_INFO_CROSS_ASPECT = 1145  # Detailed cross-aspect safe-area report

    # Auto-fix buttons
    BTN_FIX_LIGHTS = 1140
    BTN_FIX_CAMS = 1141
    BTN_FIX_UNUSED_MATS = 1142
    BTN_FIX_FPS = 1143

    # Export
    BTN_EXPORT_QC = 1150

    # Render preset
    PRESET_DROPDOWN = 1002
    LABEL_RESOLUTION = 1170
    BTN_FORCE_VERTICAL = 1204  # Force 9:16
    BTN_RESET_ALL = 1206      # Reset all presets from template
    BTN_MULTIFORMAT = 1207    # Multi-Format Render Setup (generate Takes for 16:9, 9:16, 1:1, 4:5, 21:9)
    CHK_SAFE_AREA_OVERLAY = 1208  # Viewport overlay toggle (v1.5.6, ObjectData-backed)

    # Quick Actions
    BTN_CREATE_HIERARCHY = 1126
    BTN_HIERARCHY_TO_LAYERS = 1101
    BTN_SOLO = 1103
    BTN_DROP_TO_FLOOR = 1122
    BTN_VIBRATE_NULL = 1120
    BTN_MARK_SAFE_AREA = 1127  # Mark/Unmark selection as Safe Area Subjects (QC #12)
    BTN_ABC_RETIME = 1020
    BTN_CAM_SIMPLE = 1123
    BTN_CAM_SHAKEL = 1124
    BTN_CAM_PATH = 1125

    # Output
    BTN_OPEN_FOLDER = 1010
    BTN_SNAPSHOT = 1009
    BTN_COLLECT_SCENE = 1171
    BTN_SAVE_VERSION = 1172
    LABEL_LAST_VERSION = 1173
    HISTORY_CANVAS = 1181
    COMBO_HISTORY_FILTER = 1182
    LABEL_NOTES_SUMMARY = 1190
    BTN_EDIT_NOTES = 1191
    COMP_TARGET = 1154
    CHK_MULTIPART = 1153
    BTN_INFO_TAKES = 1152
    BTN_INFO_AOVS = 1155
    BTN_LIGHT_GROUPS = 1158
    BTN_FORCE_ESSENTIALS = 1156
    BTN_FORCE_PRODUCTION = 1157
    BTN_SET_SNAPSHOT_DIR = 1160
    LABEL_SNAPSHOT_DIR = 1161
    BTN_GITHUB = 1306
    BTN_BUG_REPORT = 1307
    BTN_SETTINGS = 1308
    LABEL_AOV_INFO = 1309   # read-only summary of comp + multi-part in Render tab
    BTN_TEXTURE_REPATH = 1310  # Tools tab: open Texture Repathing dialog (v1.5.7)

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

        # ── Multi-Format Setup ──
        # Generates a Take per delivery aspect (16:9, 9:16, 1:1, 4:5, 21:9) with
        # cloned RenderData (resolution + output path overrides) and optional
        # camera composition adjustments.
        self._add_section_label("Multi-Format Setup")
        self.GroupBegin(81, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_MULTIFORMAT, c4d.BFH_SCALEFIT, 0, 0,
                       "Generate Format Takes...")
        # Viewport overlay toggle (v1.5.6) — auto-creates a marker
        # ObjectData object in the scene when enabled. The object's
        # Draw renders each active multi-format Take's safe-area
        # rectangle in the active camera viewport. Persists with the
        # .c4d save; survives panel reopens.
        self.AddCheckbox(G.CHK_SAFE_AREA_OVERLAY, c4d.BFH_LEFT, 0, 0,
                         "Show Safe-Area Overlay in viewport")
        # Reflect current session state (singleton survives tab rebuild)
        try:
            self.SetBool(G.CHK_SAFE_AREA_OVERLAY, bool(_overlay_state.enabled))
        except Exception:
            pass
        self.GroupEnd()

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
        rules_context = _active_rules_for_doc(doc)
        rules_identity = rules_context.identity
        rules_changed = self._last_rules_identity != rules_identity
        if now - self._last_check_time < CHECK_COOLDOWN and not rules_changed:
            return
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
            c4d.gui.MessageDialog("Save the scene before accepting QC baseline violations.")
            return True

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

        elif cid == G.BTN_MULTIFORMAT:
            self._open_multiformat_dialog(doc)

        elif cid == G.CHK_SAFE_AREA_OVERLAY:
            # Toggle the safe-area viewport overlay. On enable: ensure
            # the marker object exists in the scene (auto-create at
            # root if missing) + refresh the cached format rectangles.
            # On disable: just flip the flag (Draw becomes a no-op).
            new_state = bool(self.GetBool(G.CHK_SAFE_AREA_OVERLAY))
            _overlay_state.enabled = new_state
            if new_state:
                if _SAFE_AREA_OBJECT_AVAILABLE:
                    find_or_create_safe_area_overlay_object(doc)
                else:
                    safe_print("Safe-Area Overlay: ObjectData API "
                               "unavailable in this C4D build.")
                _overlay_state.update_from_doc(doc)
            c4d.EventAdd()

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
            plugin_dir = os.path.dirname(__file__)
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
        return os.path.join(os.path.dirname(__file__), "c4d", "new.c4d")

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

        # Refresh the safe-area overlay cache — the set of active
        # multi-format Takes likely changed, so the cached rectangles
        # need recomputing for the next viewport redraw.
        try:
            _overlay_state.update_from_doc(doc)
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

def Register():
    # Load plugin icon (PNG format for best Cinema 4D compatibility).
    # Tries the new Sentinel icon first; falls back to legacy YS Guardian icon
    # if the new file is missing (defensive — should never happen in practice).
    icon = c4d.bitmaps.BaseBitmap()
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    candidates = [
        os.path.join(icons_dir, "Sentinel_IC_v02.png"),
        os.path.join(icons_dir, "Sentinel_IC_v01.png"),  # previous Sentinel icon
        os.path.join(icons_dir, "ys-logo-alpha-32.png"),  # legacy YS Guardian fallback
    ]

    icon_path = None
    for candidate in candidates:
        if os.path.exists(candidate):
            icon_path = candidate
            break

    if icon_path:
        result = icon.InitWith(icon_path)
        if result[0] == c4d.IMAGERESULT_OK:
            width = icon.GetBw()
            height = icon.GetBh()
            depth = icon.GetBt()
            safe_print(f"Plugin icon loaded: {os.path.basename(icon_path)} ({width}x{height}, {depth}-bit)")
        else:
            safe_print(f"Warning: Failed to load icon from {icon_path}")
            icon = None
    else:
        safe_print(f"Warning: No icon found in {icons_dir}")
        icon = None

    ok = plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        icon=icon,
        help="Open Sentinel Panel",
        dat=YSPanelCmd()
    )
    if ok:
        safe_print(f"{PLUGIN_NAME} registered successfully")
    else:
        safe_print("Failed to register Guardian panel")

    # Secondary plugin: SafeAreaOverlayObject (ObjectData) for the
    # cross-aspect safe-area viewport overlay (v1.5.6).
    # Failure here is non-fatal — the panel still works, just no overlay.
    if _SAFE_AREA_OBJECT_AVAILABLE:
        try:
            overlay_ok = plugins.RegisterObjectPlugin(
                id=SAFE_AREA_OVERLAY_PLUGIN_ID,
                str="Sentinel Safe-Area Overlay",
                g=SafeAreaOverlayObject,
                description="safearea_overlay",
                info=c4d.OBJECT_GENERATOR,
                icon=None,
            )
            if overlay_ok:
                safe_print("Sentinel Safe-Area Overlay (ObjectData) registered")
            else:
                safe_print("Failed to register Safe-Area Overlay ObjectData — "
                           "overlay disabled, panel still works")
        except Exception as e:
            safe_print(f"Safe-Area Overlay registration crashed: {e} — "
                       "overlay disabled, panel still works")
    else:
        safe_print("ObjectData API unavailable in this C4D — overlay disabled")

    return ok

if __name__ == "__main__":
    # Print setup info using safe_print to avoid None returns in console
    safe_print("\n" + "="*50)
    safe_print(f"{PLUGIN_NAME}")
    safe_print(f"  Snapshot dir: {GlobalSettings.get_snapshot_dir()}")
    safe_print(f"  9 Quality Checks | ACES tone mapping")
    safe_print("="*50 + "\n")

    Register()
