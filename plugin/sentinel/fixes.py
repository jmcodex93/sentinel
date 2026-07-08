# -*- coding: utf-8 -*-
"""Auto-fix engine for Sentinel QC checks.

Pure fix machinery extracted from ui/panel.py (Phase 4). Uses c4d + the QC
cache + safe_print, but never c4d.gui — dialog wrappers stay in the panel.
"""
import c4d

from sentinel.common.cache import check_cache
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.checks.render import normalize_preset_name
from sentinel.qc.registry import CHECK_REGISTRY, resolve_function
from sentinel.rules import get_active_rules


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


def fix_fps_range(doc, manage_undo=True):
    """Auto-fix FPS/range across ALL render presets. Aligns timeline to active preset.

    ``manage_undo=False`` lets a caller (e.g. batched ``apply_fixes``) own the
    single StartUndo/EndUndo + cache/EventAdd so the whole batch is one undo step.
    """
    fixes = []
    if not doc.GetFirstRenderData():
        return fixes

    if manage_undo:
        doc.StartUndo()
    try:
        fixes = _apply_fps_range(doc)
    except Exception as e:
        # Standalone (button) path degrades gracefully; a batching caller
        # (apply_fixes / gate) must see the failure, not a silent empty result.
        if not manage_undo:
            raise
        safe_print(f"Error fixing FPS/range: {e}")
    finally:
        if manage_undo:
            doc.EndUndo()

    if manage_undo:
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


def fix_lights(doc, lights_bad, manage_undo=True):
    """Move stray lights into a 'lights' group null"""
    if not lights_bad:
        return 0

    if manage_undo:
        doc.StartUndo()
    moved = _apply_lights(doc, lights_bad)
    if manage_undo:
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


def fix_camera_shift(doc, cam_bad, manage_undo=True):
    """Reset camera shift to 0 on all flagged cameras"""
    if not cam_bad:
        return 0

    if manage_undo:
        doc.StartUndo()
    fixed = _apply_camera_shift(doc, cam_bad)
    if manage_undo:
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


def fix_unused_materials(doc, unused_mats, manage_undo=True):
    """Delete unused materials from the scene"""
    if not unused_mats:
        return 0

    if manage_undo:
        doc.StartUndo()
    deleted = _apply_unused_materials(doc, unused_mats)
    if manage_undo:
        doc.EndUndo()
        check_cache.clear()
        c4d.EventAdd()
    return deleted


def apply_fixes(doc, fixes):
    """Apply selected auto-fixes as one undo step.

    ``fixes`` items have shape {"check_id": str, "objects": list}. The caller
    is responsible for passing only live objects/materials filtered to new
    violations. ``fps_range`` ignores ``objects`` and normalizes all presets.

    Which check_ids are fixable, and the fix function for each, come from the
    registry (``entry.has_fix`` + ``entry.fix_fn``). The public fix_* functions
    are invoked with ``manage_undo=False`` so the whole batch is a single undo
    step owned here.
    """
    entries_by_id = {entry.check_id: entry for entry in CHECK_REGISTRY}
    results = []

    try:
        doc.StartUndo()
        try:
            for item in fixes or []:
                check_id = item.get("check_id")
                entry = entries_by_id.get(check_id)
                if not entry or not entry.has_fix:
                    continue
                fix_fn = resolve_function(entry.fix_fn)
                objects = item.get("objects") or []
                if entry.fix_scope == "document":
                    result = fix_fn(doc, manage_undo=False)
                else:
                    if not objects:
                        continue
                    result = fix_fn(doc, objects, manage_undo=False)
                results.append({"check_id": check_id, "result": result})
        finally:
            doc.EndUndo()
    finally:
        check_cache.clear()
        c4d.EventAdd()
    return results
