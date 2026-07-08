# -*- coding: utf-8 -*-
"""Render and parametric QC checks with structured result values."""

import c4d
from collections import defaultdict

from sentinel.common.constants import PRESETS
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.qc.results import (
    CheckResult,
    cached_result as _cached_result,
    legacy_items,
    param_identity,
    store_result as _store_result,
)
from sentinel.rules_context import active_rules_for_doc


def _rules_context(doc, rules_context=None):
    if rules_context is not None:
        return rules_context
    return active_rules_for_doc(doc)


def normalize_preset_name(name):
    """Normalize preset name: lowercase, replace hyphens/spaces with underscores"""
    if not name:
        return ""
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _render_conflicts_result(legacy_value, violations_data=None):
    result = CheckResult(
        check_id="render_conflicts",
        metadata={"legacy_count": int(legacy_value or 0)},
        legacy_items=int(legacy_value or 0),
    )
    for item in violations_data or []:
        result.add_violation(
            param_identity(
                "render_preset",
                item.get("value"),
                preset=item.get("preset"),
                field=item.get("field"),
            ),
            item.get("message", "Render preset conflict"),
            item.get("extras"),
        )
    return result


# ---------------- render preset conflicts (optimized) ----------------
def check_render_conflicts(doc, rules_context=None):
    """Check for render setting conflicts - accepts pre_render, pre-render, Pre-Render etc."""
    context = _rules_context(doc, rules_context)
    cached_result = _cached_result(doc, "rdc", _render_conflicts_result)
    if cached_result is not None:
        return cached_result

    allowed = {
        normalize_preset_name(name)
        for name in context.params.get("approved_presets", PRESETS)
    }
    name_counts = defaultdict(int)
    extras = 0
    violations_data = []

    try:
        rd = doc.GetFirstRenderData()
        count = 0
        max_check = 100  # Limit iterations

        while rd and count < max_check:
            try:
                # Normalize the name (lowercase, replace hyphens/spaces with underscores)
                name = normalize_preset_name(rd.GetName() or "")
                if name in allowed:
                    name_counts[name] += 1
                    if name_counts[name] > 1:
                        violations_data.append({
                            "preset": name,
                            "field": "duplicate",
                            "value": name,
                            "message": f"Duplicate render preset: {name}",
                            "extras": {"preset": name, "normalized_name": name},
                        })
                else:
                    extras += 1
                    violations_data.append({
                        "preset": name,
                        "field": "extra",
                        "value": name,
                        "message": f"Non-standard render preset: {name}",
                        "extras": {"preset": name, "normalized_name": name},
                    })
            except Exception:
                pass

            rd = rd.GetNext()
            count += 1

        dups = sum(max(0, c - 1) for c in name_counts.values())
        result = extras + dups

    except Exception as e:
        safe_print(f"Error checking render conflicts: {e}")
        result = 0
        violations_data = []

    return _store_result(doc, "rdc", result, _render_conflicts_result(result, violations_data))


def _output_paths_result(issues, violations_data=None):
    result = CheckResult(
        check_id="output_paths",
        metadata={"legacy_count": len(issues)},
        legacy_items=issues,
    )
    items = violations_data if violations_data is not None else issues
    for item in items:
        result.add_violation(
            param_identity(
                "output_path",
                item.get("value", item.get("issue")),
                preset=item.get("preset"),
                field=item.get("field", "path"),
            ),
            item.get("issue", "Output path issue"),
            {"preset": item.get("preset"), "issue": item.get("issue")},
        )
    return result


# ---------------- output path validation ----------------
def check_output_paths(doc):
    """Check render output paths are configured with proper tokens"""
    cached_result = _cached_result(doc, "output", _output_paths_result)
    if cached_result is not None:
        return cached_result

    issues = []
    violations_data = []
    try:
        rd = doc.GetFirstRenderData()
        count = 0
        while rd and count < 100:
            name = rd.GetName() or "unnamed"
            path = rd[c4d.RDATA_PATH] or ""

            if not path.strip():
                issues.append({"preset": name, "issue": "empty output path"})
                violations_data.append({"preset": name, "issue": "empty output path", "field": "path", "value": path})
            elif "$prj" not in path and "$take" not in path:
                issues.append({"preset": name, "issue": f"no tokens in path: {path}"})
                violations_data.append({"preset": name, "issue": f"no tokens in path: {path}", "field": "path", "value": path})

            # Check multi-pass path if enabled
            try:
                if rd[c4d.RDATA_MULTIPASS_SAVEIMAGE]:
                    mp_path = rd[c4d.RDATA_MULTIPASS_FILENAME] or ""
                    if not mp_path.strip():
                        issues.append({"preset": name, "issue": "empty multi-pass path"})
                        violations_data.append({"preset": name, "issue": "empty multi-pass path", "field": "multi_pass_path", "value": mp_path})
            except Exception:
                pass

            rd = rd.GetNext()
            count += 1

    except Exception as e:
        safe_print(f"Error checking output paths: {e}")

    return _store_result(doc, "output", issues, _output_paths_result(issues, violations_data))


def _takes_result(issues, violations_data=None):
    result = CheckResult(
        check_id="takes",
        metadata={"legacy_count": len(issues)},
        legacy_items=issues,
    )
    items = violations_data if violations_data is not None else issues
    for item in items:
        result.add_violation(
            param_identity(
                "take",
                item.get("value", item.get("issue")),
                take=item.get("take"),
                field=item.get("field", "take"),
            ),
            item.get("issue", "Take configuration issue"),
            {"take": item.get("take"), "issue": item.get("issue")},
        )
    return result


# ---------------- take validation ----------------
def check_takes(doc):
    """Validate all takes have camera and output path configured"""
    cached_result = _cached_result(doc, "takes", _takes_result)
    if cached_result is not None:
        return cached_result

    issues = []
    violations_data = []
    try:
        td = doc.GetTakeData()
        if not td:
            return _store_result(doc, "takes", issues, _takes_result(issues))

        main_take = td.GetMainTake()
        if not main_take:
            return _store_result(doc, "takes", issues, _takes_result(issues))

        # Iterate child takes (skip Main — it's not a renderable shot)
        take = main_take.GetDown()
        while take:
            take_name = take.GetName() or "unnamed"

            # Check camera
            cam = take.GetCamera(td)
            if not cam:
                issues.append({"take": take_name, "issue": "No camera assigned"})
                violations_data.append({"take": take_name, "issue": "No camera assigned", "field": "camera", "value": None})

            # Check render data output path
            rd = take.GetRenderData(td)
            if rd:
                path = rd[c4d.RDATA_PATH] or ""
                if not path.strip():
                    issues.append({"take": take_name, "issue": "Empty output path"})
                    violations_data.append({"take": take_name, "issue": "Empty output path", "field": "path", "value": path})
                elif "$take" not in path:
                    issues.append({"take": take_name, "issue": f"Output path missing $take token"})
                    violations_data.append({"take": take_name, "issue": f"Output path missing $take token", "field": "path", "value": path})
            else:
                # No override — inherits from main, check main's path
                main_rd = doc.GetActiveRenderData()
                if main_rd:
                    path = main_rd[c4d.RDATA_PATH] or ""
                    if "$take" not in path:
                        issues.append({"take": take_name, "issue": "Inherited path missing $take token"})
                        violations_data.append({"take": take_name, "issue": "Inherited path missing $take token", "field": "inherited_path", "value": path})

            take = take.GetNext()

    except Exception as e:
        safe_print(f"Error checking takes: {e}")

    return _store_result(doc, "takes", issues, _takes_result(issues, violations_data))


def _fps_range_result(issues, violations_data=None):
    result = CheckResult(
        check_id="fps_range",
        metadata={"legacy_count": len(issues)},
        legacy_items=issues,
    )
    items = violations_data if violations_data is not None else issues
    for item in items:
        result.add_violation(
            param_identity(
                "fps_range",
                item.get("value", item.get("issue")),
                preset=item.get("preset"),
                field=item.get("type"),
            ),
            item.get("issue", "FPS/range issue"),
            {
                "preset": item.get("preset"),
                "issue": item.get("issue"),
                "type": item.get("type"),
            },
        )
    return result


def check_fps_range(doc, rules_context=None):
    """Validate FPS, frame range, frame step, and timeline alignment across ALL presets.

    Doc-level FPS is checked once. Each render data is validated independently for
    FPS, frame step (=1), range start (1001), and mode. Timeline + preview alignment
    is validated against the ACTIVE preset (since timeline is shared).
    """
    context = _rules_context(doc, rules_context)
    cached_result = _cached_result(doc, "fps_range", _fps_range_result)
    if cached_result is not None:
        return cached_result

    issues = []
    violations_data = []
    try:
        standard_fps = int(context.params.get("standard_fps", GlobalSettings.get_standard_fps()))
        start_frame = int(context.params.get("start_frame", 1001))
        doc_fps = doc.GetFps()

        # --- Document-level FPS (checked once) ---
        if doc_fps != standard_fps:
            issues.append({
                "issue": f"Document FPS is {doc_fps}, expected {standard_fps}",
                "type": "doc_fps",
                "preset": None,
            })
            violations_data.append({
                "issue": f"Document FPS is {doc_fps}, expected {standard_fps}",
                "type": "doc_fps",
                "preset": None,
                "value": doc_fps,
            })

        active_rd = doc.GetActiveRenderData()
        if not active_rd:
            return _store_result(doc, "fps_range", issues, _fps_range_result(issues))

        # --- Iterate all render datas ---
        rd = doc.GetFirstRenderData()
        while rd:
            preset_name = rd.GetName()
            preset_norm = normalize_preset_name(preset_name)
            is_stills = preset_norm == "stills"
            is_active = (rd == active_rd)
            tag = f"[{preset_name}]"

            rd_fps = int(rd[c4d.RDATA_FRAMERATE])
            if rd_fps != standard_fps:
                issues.append({
                    "issue": f"{tag} Render FPS is {rd_fps}, expected {standard_fps}",
                    "type": "rd_fps",
                    "preset": preset_name,
                })
                violations_data.append({
                    "issue": f"{tag} Render FPS is {rd_fps}, expected {standard_fps}",
                    "type": "rd_fps",
                    "preset": preset_name,
                    "value": rd_fps,
                })

            # Frame step should always be 1 (no skipping)
            frame_step = int(rd[c4d.RDATA_FRAMESTEP])
            if frame_step != 1:
                issues.append({
                    "issue": f"{tag} Frame step is {frame_step}, expected 1 (frame skipping)",
                    "type": "frame_step",
                    "preset": preset_name,
                })
                violations_data.append({
                    "issue": f"{tag} Frame step is {frame_step}, expected 1 (frame skipping)",
                    "type": "frame_step",
                    "preset": preset_name,
                    "value": frame_step,
                })

            frame_start = rd[c4d.RDATA_FRAMEFROM].GetFrame(rd_fps)
            frame_end = rd[c4d.RDATA_FRAMETO].GetFrame(rd_fps)
            frame_mode = rd[c4d.RDATA_FRAMESEQUENCE]

            if is_stills:
                if frame_mode == c4d.RDATA_FRAMESEQUENCE_MANUAL and frame_start != start_frame:
                    issues.append({
                        "issue": f"{tag} Stills start frame is {frame_start}, expected {start_frame}",
                        "type": "start_frame",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Stills start frame is {frame_start}, expected {start_frame}",
                        "type": "start_frame",
                        "preset": preset_name,
                        "value": frame_start,
                    })
                if frame_mode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
                    issues.append({
                        "issue": f"{tag} Stills set to 'All Frames' (use Current Frame or {start_frame})",
                        "type": "mode",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Stills set to 'All Frames' (use Current Frame or {start_frame})",
                        "type": "mode",
                        "preset": preset_name,
                        "value": frame_mode,
                    })
            else:
                if frame_start != start_frame:
                    issues.append({
                        "issue": f"{tag} Start frame is {frame_start}, expected {start_frame}",
                        "type": "start_frame",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Start frame is {frame_start}, expected {start_frame}",
                        "type": "start_frame",
                        "preset": preset_name,
                        "value": frame_start,
                    })
                if frame_end <= frame_start:
                    issues.append({
                        "issue": f"{tag} Frame range invalid: {frame_start}-{frame_end}",
                        "type": "range",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Frame range invalid: {frame_start}-{frame_end}",
                        "type": "range",
                        "preset": preset_name,
                        "value": f"{frame_start}-{frame_end}",
                    })
                if frame_mode == c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME:
                    issues.append({
                        "issue": f"{tag} Animation set to 'Current Frame' only",
                        "type": "mode",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Animation set to 'Current Frame' only",
                        "type": "mode",
                        "preset": preset_name,
                        "value": frame_mode,
                    })
                elif frame_mode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
                    issues.append({
                        "issue": f"{tag} Set to 'All Frames' (may render entire timeline)",
                        "type": "mode",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Set to 'All Frames' (may render entire timeline)",
                        "type": "mode",
                        "preset": preset_name,
                        "value": frame_mode,
                    })
                frame_length = frame_end - frame_start + 1
                if frame_length > 1000 and frame_mode != c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
                    issues.append({
                        "issue": f"{tag} Very long render: {frame_length} frames",
                        "type": "length",
                        "preset": preset_name,
                    })
                    violations_data.append({
                        "issue": f"{tag} Very long render: {frame_length} frames",
                        "type": "length",
                        "preset": preset_name,
                        "value": frame_length,
                    })

            # --- Timeline + preview alignment (against ACTIVE preset only) ---
            if is_active:
                tl_min = doc[c4d.DOCUMENT_MINTIME].GetFrame(doc_fps)
                tl_max = doc[c4d.DOCUMENT_MAXTIME].GetFrame(doc_fps)
                loop_min = doc[c4d.DOCUMENT_LOOPMINTIME].GetFrame(doc_fps)
                loop_max = doc[c4d.DOCUMENT_LOOPMAXTIME].GetFrame(doc_fps)

                if is_stills:
                    if not (tl_min <= start_frame <= tl_max):
                        issues.append({
                            "issue": f"Timeline ({tl_min}-{tl_max}) doesn't include frame {start_frame}",
                            "type": "timeline",
                            "preset": None,
                        })
                        violations_data.append({
                            "issue": f"Timeline ({tl_min}-{tl_max}) doesn't include frame {start_frame}",
                            "type": "timeline",
                            "preset": None,
                            "value": f"{tl_min}-{tl_max}",
                        })
                else:
                    if frame_end > frame_start:
                        if tl_min != frame_start or tl_max != frame_end:
                            issues.append({
                                "issue": f"Timeline ({tl_min}-{tl_max}) doesn't match active render range ({frame_start}-{frame_end})",
                                "type": "timeline",
                                "preset": None,
                            })
                            violations_data.append({
                                "issue": f"Timeline ({tl_min}-{tl_max}) doesn't match active render range ({frame_start}-{frame_end})",
                                "type": "timeline",
                                "preset": None,
                                "value": f"{tl_min}-{tl_max}",
                            })
                        if loop_min != frame_start or loop_max != frame_end:
                            issues.append({
                                "issue": f"Preview range ({loop_min}-{loop_max}) doesn't match active render range ({frame_start}-{frame_end})",
                                "type": "loop",
                                "preset": None,
                            })
                            violations_data.append({
                                "issue": f"Preview range ({loop_min}-{loop_max}) doesn't match active render range ({frame_start}-{frame_end})",
                                "type": "loop",
                                "preset": None,
                                "value": f"{loop_min}-{loop_max}",
                            })

            rd = rd.GetNext()

    except Exception as e:
        safe_print(f"Error checking FPS/range: {e}")

    return _store_result(doc, "fps_range", issues, _fps_range_result(issues, violations_data))
