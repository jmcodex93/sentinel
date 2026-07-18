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
from sentinel import postrender
from sentinel import PLUGIN_NAME, PLUGIN_VERSION
from sentinel.common.cache import CheckCache, check_cache
from sentinel.common.constants import (
    CACHE_DURATION,
    CHECK_COOLDOWN,
    EVMSG_TAKECHANGED,
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
from sentinel.qc.registry import entry_severity, resolve_function
from sentinel.qc.score import compute_score, count_violations, run_all_checks
from sentinel.rules import get_active_rules
from sentinel.ui.ids import G, decode_qc_action, qc_action_id
from sentinel.ui.user_areas import (
    HistoryArea,
    ScoreHeader,
    StatusArea,
    _CHECK_DISPLAY,
    _accepted_entry_payload,
    _entry_label,
    _violation_label,
    format_baseline_row_message,
)
from sentinel.ui.dialogs import (
    AssetHubDialog,
    BaselineActionDialog,
    GateTriageDialog,
    NotesDialog,
    SaveVersionDialog,
    SentinelDoctorDialog,
    SentinelSettingsDialog,
    SupervisorDialog,
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

# normalize_preset_name lives in sentinel.checks.render; re-exported here for
# panel-internal callers and the .pyp compatibility surface.
from sentinel.checks.render import normalize_preset_name


# Rules/path helpers moved to sentinel.ui.flows (shared by save/collect flows).
from sentinel.rules_context import active_rules_for_doc as _active_rules_for_doc
from sentinel.ui.flows import (
    _baseline_path_for_doc,
    _doc_full_path,
)




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


# ---------------- scene complexity (moved to sentinel.ui.flows) ----------------
from sentinel.ui.flows import get_scene_stats

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
    _is_lg_active_on_beauty,
    _scan_light_groups,
    _resolve_aov_type,
    check_rs_aovs,
    force_aov_tier,
    get_aov_multipart,
    get_rs_aovs,
    set_scene_multipart,
)

def check_takes(doc):
    return render_checks.legacy_items(render_checks.check_takes(doc))

def check_fps_range(doc):
    return render_checks.legacy_items(render_checks.check_fps_range(doc))

# ---------------- auto-fix engine (moved to sentinel.fixes) ----------------
from sentinel.fixes import (
    apply_fixes,
    fix_camera_shift,
    fix_fps_range,
    fix_lights,
    fix_unused_materials,
)

# Button label per QC action; drives the generated QC button matrix.
_QC_ACTION_LABELS = {"select": "Select", "info": "Info", "fix": "Fix"}


# ---------------- QC report (assembly moved to sentinel.ui.reports) ----------------
from sentinel.ui import reports
from sentinel.ui.reports import build_baseline_artifact_details, build_qc_report


def _scene_snapshot_b64(doc, artist_name):
    """Return base64 of the newest review still for this scene, or None.

    Read-only: searches the artist's stills tree for ``<scene>.png`` (never
    creates folders). Embedded into the client report when present.
    """
    import base64

    try:
        doc_path = doc.GetDocumentPath() or ""
        if not doc_path:
            return None
        project_root = os.path.dirname(os.path.dirname(doc_path))
        stills_root = os.path.join(project_root, "output", "stills")
        if not os.path.isdir(stills_root):
            return None
        scene_name = os.path.splitext(doc.GetDocumentName() or "untitled")[0]
        target = f"{scene_name}.png"
        newest = None
        newest_mtime = -1.0
        for root, _dirs, files in os.walk(stills_root):
            if target in files:
                full = os.path.join(root, target)
                mtime = os.path.getmtime(full)
                if mtime > newest_mtime:
                    newest, newest_mtime = full, mtime
        if not newest:
            return None
        with open(newest, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    except Exception as e:
        safe_print(f"Could not embed snapshot in client report: {e}")
        return None


def export_qc_report(doc, results, artist_name, qc_summary=None):
    """Export QC report as JSON + a self-contained client HTML report.

    Returns the JSON path (or None if cancelled). The ``<base>_report.html``
    companion is written next to the JSON via atomic tmp+rename.
    """
    report = build_qc_report(doc, results, artist_name, qc_summary)

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

    # ── Client-readable HTML report (I7) ──
    # Written next to the chosen JSON, and (when the scene is saved) also as the
    # canonical <base>_report.html sidecar next to the .c4d so Scene Collector
    # can transport it into the delivery alongside the other sidecars.
    try:
        from sentinel.client_report import write_client_report_html
        from sentinel.versioning import parse_version_filename, report_html_path

        json_dir = os.path.dirname(save_path)
        scene_no_ext = os.path.splitext(doc.GetDocumentName() or "scene")[0]
        base, _v, _s = parse_version_filename(scene_no_ext)
        if not base:
            base = scene_no_ext or "scene"

        versions = load_versions_for_doc(doc)
        snapshot_b64 = _scene_snapshot_b64(doc, artist_name)

        targets = {os.path.join(json_dir, f"{base}_report.html")}
        doc_full = os.path.join(doc.GetDocumentPath() or "", doc.GetDocumentName() or "")
        if doc.GetDocumentPath():
            sidecar = report_html_path(doc_full)
            if sidecar:
                targets.add(sidecar)

        for html_path in targets:
            write_client_report_html(report, html_path, snapshot_b64=snapshot_b64, versions=versions)
            safe_print(f"Client HTML report written: {html_path}")
    except Exception as e:
        safe_print(f"Could not write client HTML report: {e}")

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


# ---------------- Quality gate + Smart Save (moved to sentinel.ui.flows) ----------------
from sentinel.ui.flows import _run_quality_gate, smart_save_version


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
# Collect now runs through AssetHubDialog (focus="deliver"), which reuses
# run_collect_pipeline internally — collect_scene is no longer called
# directly from the panel (v1.11, superseded by the Asset Hub).


# ---------------- Snapshot System (moved to sentinel.snapshots + ui.flows) ----------------
from sentinel import snapshots as snapshot_engine
from sentinel.ui.flows import snapshot_auto_convert, snapshot_open_folder, snapshot_save_still
from sentinel.ui import scene_tools

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

        # Snapshot watchfolder (auto-convert) — session-only state
        self._snap_registry = {}       # filename -> (mtime, size, state)
        self._snap_last_scan = 0.0     # monotonic-ish throttle (time.time)
        self._snap_watch_primed = False  # skip converting the pre-existing backlog
        self._snap_watch_caption = ""  # status/alert text for LABEL_SNAPSHOT_WATCH

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
        # Populate the freshly-rebuilt tab's widgets. Only re-run QC when the
        # scene actually changed (self._dirty, set by CoreMessage) or when no
        # QC has been computed yet (first run). Otherwise repaint from cache —
        # a tab switch on an unchanged scene must not trigger a full 12-check
        # recompute (that stalled switches on heavy scenes). QC results only
        # feed the QC tab's StatusArea; other tabs need no QC run at all.
        try:
            if self._dirty or self._registry_results is None:
                self._last_check_time = 0   # bypass 0.5s cooldown for the immediate run
                self._refresh()             # fresh compute: repaints ua + score + labels
                self._dirty = False         # serviced here; don't double-run on next Timer
            elif idx == 0:
                # Clean switch, valid cache: the QC tab's StatusArea was just
                # rebuilt blank — repaint it from cache (no recompute).
                self._repopulate_qc_from_cache()
        except Exception as e:
            safe_print(f"Tab-switch refresh error: {e}")
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
        # Generated from the registry: primary action button (width 50) in the
        # left column, secondary action button (width 35) or a filler in the
        # right column — same 2×12 visual layout as before.
        flags = c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT
        for index, entry in enumerate(CHECK_REGISTRY):
            actions = entry.actions
            self.AddButton(qc_action_id(index, actions[0]), flags, 50, 0,
                           _QC_ACTION_LABELS[actions[0]])
            if len(actions) > 1:
                self.AddButton(qc_action_id(index, actions[1]), flags, 35, 0,
                               _QC_ACTION_LABELS[actions[1]])
            else:
                self.AddStaticText(0, flags, 35, 0, "", 0)
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
        # in v1.8.0 (superseded by the Sentinel Frame tag): the overlay ObjectData
        # is unregistered and the MultiFormatDialog UI is removed. The shared
        # engine (multiformat.generate_multiformat_takes) stays — the tag uses it —
        # so Takes already generated by the old dialog keep working.

        # ── Redshift AOVs ──
        # Compositor is a studio-level default edited in Settings. Multi-Part EXR
        # is a per-scene render choice: LABEL_AOV_INFO reflects the live scene's
        # actual flag and BTN_APPLY_MULTIPART flips it on the current scene (the
        # Settings checkbox is only the default applied when adding AOV tiers).
        self._add_section_label("Redshift AOVs")
        self.AddStaticText(G.LABEL_AOV_INFO, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        self.GroupBegin(82, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_INFO_AOVS, c4d.BFH_SCALEFIT, 0, 0, "Show AOVs")
        self.AddButton(G.BTN_APPLY_MULTIPART, c4d.BFH_SCALEFIT, 0, 0, "Multi-Part…")
        self.GroupEnd()

        self.GroupBegin(85, c4d.BFH_SCALEFIT, 3, 0)
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
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0)
        self.AddCheckbox(G.CHK_SNAPSHOT_WATCH, c4d.BFH_LEFT, 0, 0,
                         "Auto-convert snapshots")
        self.SetBool(G.CHK_SNAPSHOT_WATCH, GlobalSettings.get_snapshot_watch())
        self.AddStaticText(G.LABEL_SNAPSHOT_WATCH, c4d.BFH_SCALEFIT, 0, 0,
                           self._snap_watch_caption, 0)
        self.GroupEnd()

        # ── Post-Render (U7) ──
        self._add_section_label("Post-Render")
        self.GroupBegin(84, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_VALIDATE_RENDER, c4d.BFH_SCALEFIT, 0, 0, "Validate Render Output...")
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
        self.AddButton(G.BTN_SUPERVISOR, c4d.BFH_SCALEFIT, 0, 0,
                       "Supervisor... (folder QC)")

        # Delivery reception (I4): only when a collected manifest with an
        # asset section sits next to the open scene.
        if self._delivery_manifest_available():
            self.AddButton(G.BTN_DELIVERY_SUMMARY, c4d.BFH_SCALEFIT, 0, 0,
                           "Delivery Summary...")

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

        # ── Asset Management ── (v1.11 Asset Hub — supersedes Texture Repathing)
        self._add_section_label("Asset Management")
        self.GroupBegin(53, c4d.BFH_SCALEFIT, 1, 0)
        self.AddButton(G.BTN_TEXTURE_REPATH, c4d.BFH_SCALEFIT, 0, 0,
                       "Asset Hub...")
        self.GroupEnd()

        # Spacer
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _update_aov_info_label(self):
        """Render tab: refresh the Comp + Multi-Part summary from the LIVE scene.

        Multi-Part is read from the active scene's RS videopost (the real render
        state) — NOT the saved default — and BTN_APPLY_MULTIPART flips it on the
        scene. Compositor stays a studio default from Settings.
        """
        try:
            comp_idx = int(GlobalSettings.get('comp_target', 0))
            comp_name = "Nuke" if comp_idx == 0 else "After Effects"

            doc = c4d.documents.GetActiveDocument()
            vp = _get_rs_videopost(doc) if doc else None
            if vp is None:
                self.SetString(
                    G.LABEL_AOV_INFO,
                    f"Compositor: {comp_name}    ·    Multi-Part EXR: (no Redshift render data)")
                try:
                    self.SetString(G.BTN_APPLY_MULTIPART, "Multi-Part…")
                    self.Enable(G.BTN_APPLY_MULTIPART, False)
                except Exception:
                    pass
                return

            live_multipart = bool(get_aov_multipart(doc))
            mp_str = "ON" if live_multipart else "OFF"
            self.SetString(
                G.LABEL_AOV_INFO,
                f"Compositor: {comp_name}    ·    Multi-Part EXR: {mp_str} (scene)")
            # Button label spells out the action it performs (the opposite state).
            try:
                self.Enable(G.BTN_APPLY_MULTIPART, True)
                self.SetString(
                    G.BTN_APPLY_MULTIPART,
                    "Switch to Direct Output" if live_multipart else "Switch to Multi-Part EXR")
            except Exception:
                pass
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
            self._set_filename_caption("▸ Scene:  (no document)")
            return
        name = doc.GetDocumentName() or ""
        if not name:
            text = "▸ Scene:  Untitled  ·  not saved yet"
        else:
            # Full filename including version + status — the user is working ON
            # this exact file; transparency over abstraction.
            text = f"▸ Scene:  {name}"
        self._set_filename_caption(text)

    def _add_filename_row(self, text):
        """Add the [spacer][caption][spacer] row into the filename group.
        The scalefit spacers center the content-sized caption; the caption is
        created WITH its text so it sizes to fit instead of truncating."""
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "", 0)  # left spacer
        self.AddStaticText(G.LABEL_FILENAME, c4d.BFH_LEFT, 0, 0, text, 0)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "", 0)  # right spacer

    def _set_filename_caption(self, text):
        """Set the centered scene caption, re-creating the static text so it
        sizes to the (possibly long) name instead of truncating. Guarded so the
        header only re-lays-out when the caption actually changes."""
        if getattr(self, "_filename_label_text", None) == text:
            return
        self._filename_label_text = text
        try:
            self.LayoutFlushGroup(11)
            self._add_filename_row(text)
            self.LayoutChanged(11)
        except Exception as e:
            safe_print(f"Filename caption error: {e}")

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
                    # Mark dirty so a fast switch to QC recomputes preset
                    # compliance without waiting for the async EVMSG_CHANGE.
                    self._dirty = True
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

    def _build_qc_state_dict(self, score_summary, registry_results, rules_context):
        """Assemble the decorated StatusArea state dict from a (summary,
        results, rules) triple. Single source for both the fresh-run path
        (_refresh) and the cache-repaint path (_repopulate_qc_from_cache),
        so a clean tab switch repaints identically without re-running checks."""
        counts_by_id = score_summary.get("counts", {})
        legacy_by_id = {
            check_id: pair.get("legacy_result")
            for check_id, pair in (registry_results or {}).items()
        }
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
        return state

    def _repopulate_qc_from_cache(self):
        """Repaint the QC StatusArea from already-cached QC state, no re-run.
        Fills a freshly-(re)attached StatusArea on a clean tab switch. Keyed on
        the widget existing (self.ua), NOT on cache-emptiness — a brand-new
        blank StatusArea must be filled even though the cache is already full.
        No-op if the QC tab was never built or QC has never been computed."""
        if self.ua is None:
            return
        if (self._qc_summary is None or self._registry_results is None
                or self._rules_context is None):
            return
        try:
            state = self._build_qc_state_dict(
                self._qc_summary, self._registry_results, self._rules_context)
            self.ua.set_state(state, self.ua.show)
        except Exception as e:
            safe_print(f"QC cache repaint error: {e}")

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
                state = self._build_qc_state_dict(score_summary, registry_results, rules_context)
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

        # Filename caption — read-only, prominent, centered. Its own full-width
        # 3-column group [scalefit spacer][caption][scalefit spacer]: the two
        # spacers absorb equal leftover space and center the content-sized
        # caption (BFH_CENTER on the static text alone does not center it here).
        # _update_filename_label flushes + re-adds the row with the real name as
        # the caption's creation text, because a static text created empty
        # freezes its width and truncates long names on SetString.
        self.GroupBegin(11, c4d.BFH_SCALEFIT, 3, 0)
        self._add_filename_row("")
        self.GroupEnd()

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
        self.GroupBegin(70, c4d.BFH_SCALEFIT, 4, 0)
        self.AddButton(G.BTN_SETTINGS, c4d.BFH_SCALEFIT, 0, 0, "⚙ Settings")
        # Plain text label: emoji glyphs (🩺) don't render in C4D's UI font
        # (showed as "_" — verified live). GitHub/Report Bug are plain too.
        self.AddButton(G.BTN_DOCTOR, c4d.BFH_SCALEFIT, 0, 0, "Doctor")
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
            c4d.gui.MessageDialog(f"Accepted {written} violation(s) for {row_label}.")
            return True

        if dlg.action == "retire":
            ok = baseline.remove_acceptances_for_check(baseline_path, row_key)
            check_cache.clear()
            self._last_check_time = 0
            self._dirty = True
            self._refresh()
            if ok:
                c4d.gui.MessageDialog(f"Acceptances retired for {row_label}.")
            else:
                c4d.gui.MessageDialog("Could not update the baseline sidecar.")
            return True

        return True

    def _on_qc_row_click(self, row_key):
        """Called by StatusArea when the user clicks a QC row.
        Routes to the entry's row_click_action (defaults to its first action)
        by synthesizing that button's command id."""
        if self._show_baseline_actions(row_key):
            return
        index = next(
            (i for i, entry in enumerate(CHECK_REGISTRY) if entry.check_id == row_key),
            None,
        )
        if index is None:
            return
        entry = CHECK_REGISTRY[index]
        primary_action = entry.row_click_action or entry.actions[0]
        try:
            self.Command(qc_action_id(index, primary_action), c4d.BaseContainer())
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

    # ── Snapshot watchfolder (auto-convert) ──
    _SNAP_WATCH_INTERVAL = 2.5  # seconds; throttle independent of Timer cadence

    def _prime_snap_watch(self):
        """Seed the registry with all existing EXRs marked processed so the
        pre-existing backlog is NOT converted — only files that land after
        enabling trigger a conversion."""
        import time
        snap_dir = GlobalSettings.get_snapshot_dir()
        registry = {}
        try:
            if snap_dir and os.path.isdir(snap_dir):
                for e in os.scandir(snap_dir):
                    try:
                        if not e.is_file() or e.name.startswith("."):
                            continue
                        if not e.name.lower().endswith(".exr"):
                            continue
                        st = e.stat()
                    except OSError:
                        continue
                    registry[e.name] = (st.st_mtime, st.st_size, "processed")
        except OSError:
            pass
        self._snap_registry = registry
        self._snap_watch_primed = True
        self._snap_last_scan = time.time()

    def _tick_snapshot_watch(self):
        """Called from Timer. Throttled to ~_SNAP_WATCH_INTERVAL. No-op unless
        the 'Auto-convert snapshots' toggle is on."""
        import time
        if not GlobalSettings.get_snapshot_watch():
            self._snap_watch_primed = False  # re-prime next time it's enabled
            return

        if not self._snap_watch_primed:
            self._prime_snap_watch()
            return

        now = time.time()
        if now - self._snap_last_scan < self._SNAP_WATCH_INTERVAL:
            return
        self._snap_last_scan = now

        snap_dir = GlobalSettings.get_snapshot_dir()
        try:
            ready, registry, non_exr_alert = snapshot_engine.scan_snapshot_candidates(
                snap_dir, self._snap_registry, now
            )
        except Exception as e:
            safe_print(f"Snapshot watch scan error: {e}")
            return
        self._snap_registry = registry

        caption = ""
        if non_exr_alert:
            caption = ("Snapshots are not saving as EXR — re-enable "
                       "'Save snapshots as EXR' in RenderView")
        for exr_path in ready:
            doc = c4d.documents.GetActiveDocument()
            ok, message = snapshot_auto_convert(doc, self._artist_name, exr_path)
            if ok:
                caption = f"Auto: converted {os.path.basename(exr_path)} -> {message}"
            elif not non_exr_alert:
                caption = f"Auto-convert skipped: {message}"

        if caption and caption != self._snap_watch_caption:
            self._snap_watch_caption = caption
            try:
                self.SetString(G.LABEL_SNAPSHOT_WATCH, caption)
            except Exception:
                pass

    def Timer(self, msg):
        doc = c4d.documents.GetActiveDocument()

        try:
            self._tick_snapshot_watch()
        except Exception as e:
            safe_print(f"Snapshot watch tick error: {e}")

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

        if id == EVMSG_TAKECHANGED:
            doc = c4d.documents.GetActiveDocument()
            if doc:
                self._sync_from_doc(doc)
            self._dirty = True
            return True

        return gui.GeDialog.CoreMessage(self, id, msg)

    # ── Per-check QC action handlers (dispatched by naming convention from
    # Command via decode_qc_action → _qc_{action}_{check_id}). Bodies moved
    # verbatim from the former per-check Command elif branches. ──
    def _qc_select_lights(self, doc):
        if self._lights_bad:
            _select_objects(doc, self._lights_bad)
            safe_print(f"Selected {len(self._lights_bad)} lights outside group")
        else:
            safe_print("No light issues found")

    def _qc_select_vis(self, doc):
        if self._vis_bad:
            _select_objects(doc, self._vis_bad)
            safe_print(f"Selected {len(self._vis_bad)} objects with visibility mismatch")
        else:
            safe_print("No visibility issues found")

    def _qc_select_keys(self, doc):
        if self._keys_bad:
            _select_objects(doc, self._keys_bad)
            safe_print(f"Selected {len(self._keys_bad)} objects with multi-axis keyframes")
        else:
            safe_print("No keyframe issues found")

    def _qc_select_cam(self, doc):
        if self._cam_bad:
            _select_objects(doc, self._cam_bad)
            safe_print(f"Selected {len(self._cam_bad)} cameras with non-zero shift")
        else:
            safe_print("No camera shift issues found")

    def _qc_info_rdc(self, doc):
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

    def _qc_info_textures(self, doc):
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
            info_msg += ("Open the Asset Hub to fix these "
                         "in bulk (find/replace, make relative, "
                         "auto-find missing)?")
            if c4d.gui.QuestionDialog(info_msg):
                self._open_asset_hub(doc)
        else:
            c4d.gui.MessageDialog(
                "All assets OK. No absolute paths or missing files.")

    def _qc_select_unused_mats(self, doc):
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

            msg = f"Unused material [{self._unused_mats_idx + 1}/{len(self._unused_mats_bad)}]: '{mat.GetName()}'"
            safe_print(msg)
            c4d.gui.StatusSetText(msg)
            self._unused_mats_idx += 1
        else:
            safe_print("No unused materials found")

    def _qc_select_names(self, doc):
        if self._names_bad:
            # Cycle through default-named objects one by one
            if self._names_idx >= len(self._names_bad):
                self._names_idx = 0

            obj = self._names_bad[self._names_idx]
            _select_objects(doc, [obj])

            msg = f"Default name [{self._names_idx + 1}/{len(self._names_bad)}]: '{obj.GetName()}'"
            safe_print(msg)
            c4d.gui.StatusSetText(msg)
            self._names_idx += 1
        else:
            safe_print("No naming issues found")

    def _qc_info_output(self, doc):
        if hasattr(self, '_output_bad') and self._output_bad:
            info_msg = f"OUTPUT PATH ISSUES: {len(self._output_bad)}\n\n"
            for i, issue in enumerate(self._output_bad[:10], 1):
                info_msg += f"{i}. [{issue['preset']}] {issue['issue']}\n"
            info_msg += "\nUse $prj and $take tokens in output paths."
        else:
            info_msg = "All output paths are properly configured."
        c4d.gui.MessageDialog(info_msg)

    def _qc_info_takes(self, doc):
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

    def _qc_info_fps_range(self, doc):
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

    def _qc_fix_lights(self, doc):
        # Reversible, low-impact fix: status bar + console, no popup.
        if self._lights_bad:
            count = fix_lights(doc, self._lights_bad)
            msg = f"Moved {count} light(s) into 'lights' group"
            safe_print(msg)
            c4d.gui.StatusSetText(msg)
        else:
            safe_print("No light issues to fix")

    def _qc_fix_cam(self, doc):
        # Reversible, low-impact fix: status bar + console, no popup.
        if self._cam_bad:
            count = fix_camera_shift(doc, self._cam_bad)
            msg = f"Reset shift to 0 on {count} camera(s)"
            safe_print(msg)
            c4d.gui.StatusSetText(msg)
        else:
            safe_print("No camera shift issues to fix")

    def _qc_fix_unused_mats(self, doc):
        # Destructive: keep the pre-confirm; report the result on the status bar.
        if self._unused_mats_bad:
            count = len(self._unused_mats_bad)
            if c4d.gui.QuestionDialog(f"Delete {count} unused material(s)?\n\nThis can be undone (Ctrl+Z)."):
                deleted = fix_unused_materials(doc, self._unused_mats_bad)
                msg = f"Deleted {deleted} unused material(s)"
                safe_print(msg)
                c4d.gui.StatusSetText(msg)
                self._unused_mats_idx = 0
        else:
            safe_print("No unused materials to delete")

    def _qc_fix_fps_range(self, doc):
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

    def _qc_select_cross_aspect(self, doc):
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

    def _qc_info_cross_aspect(self, doc):
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


    def Command(self, cid, msg):
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return True

        # Generic per-check QC action dispatch: decode the registry-derived
        # button id and route to _qc_{action}_{check_id} by naming convention.
        # Only ids that map to a real (check, action) pair are consumed here;
        # anything else in the >=1400 range falls through to the elif chain so
        # future widget ids are never silently swallowed.
        decoded = decode_qc_action(cid)
        if decoded is not None:
            index, action = decoded
            if 0 <= index < len(CHECK_REGISTRY) and action in CHECK_REGISTRY[index].actions:
                entry = CHECK_REGISTRY[index]
                method = getattr(self, f"_qc_{action}_{entry.check_id}", None)
                if method is not None:
                    method(doc)
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

        elif cid == G.BTN_VALIDATE_RENDER:
            self._handle_validate_render(doc)

        elif cid == G.ARTIST:
            # Artist name changed - save to global settings
            new_artist_name = self.GetString(G.ARTIST).strip()
            if new_artist_name != self._artist_name:
                self._artist_name = new_artist_name
                GlobalSettings.save_artist_name(self._artist_name)

        elif cid == G.BTN_SNAPSHOT:
            self._take_renderview_snapshot()

        elif cid == G.CHK_SNAPSHOT_WATCH:
            enabled = bool(self.GetBool(G.CHK_SNAPSHOT_WATCH))
            GlobalSettings.set_snapshot_watch(enabled)
            self._snap_watch_primed = False  # (re)prime the backlog on next tick
            if enabled:
                self._prime_snap_watch()
                self._snap_watch_caption = "Auto-convert on — watching for new EXRs"
            else:
                self._snap_watch_caption = ""
            try:
                self.SetString(G.LABEL_SNAPSHOT_WATCH, self._snap_watch_caption)
            except Exception:
                pass

        # Note: Compositor Target and Multi-Part used to live in the Render tab
        # as editable widgets (their ids are now retired). They were moved to
        # Settings (single source of truth) — the Render tab now shows them as
        # info via LABEL_AOV_INFO.

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
                lg_status = "ON" if _is_lg_active_on_beauty(doc) else "OFF"
                groups, _ = _scan_light_groups(doc)
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

        elif cid == G.BTN_APPLY_MULTIPART:
            self._apply_multipart_to_scene(doc)

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
            self._open_asset_hub(doc)

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

        elif cid == G.BTN_DOCTOR:
            # Open the Sentinel Doctor self-diagnostic (I6)
            dlg = SentinelDoctorDialog()
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=560, defaulth=560)
            safe_print("Sentinel Doctor closed")

        elif cid == G.BTN_SUPERVISOR:
            # Open the Supervisor folder-QC aggregator (I5-A)
            dlg = SupervisorDialog()
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=680, defaulth=560)
            safe_print("Supervisor closed")

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
            self._open_asset_hub(doc, focus="deliver")

        elif cid == G.BTN_SAVE_VERSION:
            self._handle_save_version(doc)

        elif cid == G.BTN_EDIT_NOTES:
            self._handle_edit_notes(doc)

        elif cid == G.BTN_DELIVERY_SUMMARY:
            self._show_delivery_summary(doc)

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

    # ── Delivery reception (I4) ──
    def _delivery_manifest_available(self):
        """True if a collected sentinel_manifest.json with an asset section
        (I4+) sits next to the currently open scene."""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return False
        doc_path = doc.GetDocumentPath()
        if not doc_path:
            return False
        path = os.path.join(doc_path, "sentinel_manifest.json")
        if not os.path.exists(path):
            return False
        from sentinel import manifest as manifest_engine
        data = manifest_engine.load_manifest_json(path)
        # Solo manifiestos con sección de assets (I4+); los antiguos no
        # ofrecen nada que verificar.
        return bool(data and data.get("assets_schema"))

    def _show_delivery_summary(self, doc):
        """Show the collect-time delivery summary and offer a receiver-side
        re-verify of the package's assets against sentinel_manifest.json."""
        from sentinel import manifest as manifest_engine
        doc_path = doc.GetDocumentPath() if doc else None
        if not doc_path:
            return
        data = manifest_engine.load_manifest_json(
            os.path.join(doc_path, "sentinel_manifest.json"))
        if not data:
            c4d.gui.MessageDialog("Could not read sentinel_manifest.json.")
            return

        qc = data.get("qc", {})
        summary = data.get("asset_summary", {})
        notes = data.get("notes", {})
        lines = ["DELIVERY SUMMARY", ""]
        original = data.get("original_filename") or data.get("scene", "")
        if original:
            lines.append(f"Origin: {original}")
        if qc:
            lines.append(f"QC at collect: {qc.get('passed', '?')}/"
                         f"{qc.get('total', '?')}")
        baseline_info = data.get("baseline", {})
        acceptances = baseline_info.get("acceptances") or []
        if acceptances:
            lines.append(f"Accepted violations: {len(acceptances)} "
                         f"(see baseline sidecar for author + reason)")
        pending = notes.get("pending_count", 0)
        if pending:
            lines.append(f"Pending TODOs: {pending}")
        scan_failed = data.get("scan_status") == "failed"
        if scan_failed:
            lines.append("")
            lines.append("⚠ Package re-scan FAILED at collect time — "
                         "asset list not verified by sender!")
        else:
            lines.append("")
            lines.append(f"Assets: {summary.get('total', 0)} — "
                         f"{summary.get('collected', 0)} in package, "
                         f"{summary.get('missing', 0)} missing at collect, "
                         f"{summary.get('external', 0)} external")
        plugins = data.get("required_plugins") or []
        if plugins:
            names = ", ".join(p.get("name", "?") for p in plugins[:8])
            lines.append(f"Requires plugins: {names}")

        if scan_failed:
            c4d.gui.MessageDialog("\n".join(lines))
            return

        lines.append("")
        lines.append("Verify package integrity on this machine now?")

        if c4d.gui.QuestionDialog("\n".join(lines)):
            result = manifest_engine.verify_package(data, doc_path)
            if result["lost"]:
                lost = "\n  ".join(result["lost"][:15])
                c4d.gui.MessageDialog(
                    f"VERIFY: {len(result['lost'])} asset(s) LOST in "
                    f"transfer (were in package at collect):\n  {lost}")
            else:
                c4d.gui.MessageDialog(
                    f"VERIFY OK: {result['ok']}/{result['checked']} "
                    f"collected assets present."
                    + (f"\n{len(result['still_missing'])} were already "
                       f"missing at collect time." if result["still_missing"]
                       else ""))

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

    def _toggle_light_groups(self, doc):
        scene_tools._toggle_light_groups(doc)

    def _force_aov_tier(self, doc, tier_list, tier_name):
        scene_tools._force_aov_tier(doc, tier_list, tier_name)

    def _apply_multipart_to_scene(self, doc):
        """Flip Multi-Part EXR on the LIVE scene from the Render tab.

        Reads the scene's current flag, confirms the flip (spelling out the
        compression consequence), applies it via the engine (single undo), then
        refreshes the caption + button label.
        """
        vp = _get_rs_videopost(doc)
        if vp is None:
            c4d.gui.MessageDialog(
                "No Redshift render data in this scene.\n\n"
                "Add Redshift AOVs first (Essentials / Production).")
            return
        target = not bool(get_aov_multipart(doc))
        if target:
            msg = ("Switch this scene to Multi-Part EXR?\n\n"
                   "All AOVs are bundled into one .exr under a single global\n"
                   "compression: 32-bit Float, ZIP (lossless).\n\n"
                   "Data passes (Depth, Motion Vectors, World Position, Normals)\n"
                   "stay intact — ZIP is lossless. Larger files than per-AOV\n"
                   "Direct Output, but everything in one file.")
        else:
            msg = ("Switch this scene to Direct Output?\n\n"
                   "Each AOV is written to its own .exr with its own settings —\n"
                   "data passes keep PIZ (lossless). Beauty + lighting are no\n"
                   "longer bundled into a single combined file.")
        if not c4d.gui.QuestionDialog(msg):
            return
        ok, error = set_scene_multipart(doc, target)
        if not ok:
            c4d.gui.MessageDialog(f"Could not change Multi-Part EXR:\n\n{error}")
            return
        # Rebuild the tab (not a bare _update_aov_info_label): a SetString on a
        # live button doesn't force a redraw, so the dynamic button label only
        # refreshes on a full tab rebuild — the same path a tab switch takes,
        # which is why switching tabs "fixed" the stale text.
        self._set_active_tab(self._active_tab)
        c4d.gui.MessageDialog(
            f"Multi-Part EXR: {'ON' if target else 'OFF'} — applied to scene.")

    def _handle_validate_render(self, doc):
        scene_tools._handle_validate_render(doc)

    def _open_artist_folder(self):
        scene_tools._open_artist_folder(self._artist_name)

    def _create_vibrate_null(self, doc):
        scene_tools._create_vibrate_null(doc)

    def _toggle_safe_area_mark(self, doc):
        scene_tools._toggle_safe_area_mark(doc, refresh=self._refresh)

    def _open_asset_hub(self, doc, focus="assets"):
        """Open the Sentinel Asset Hub (v1.11).

        Unified asset inventory + repathing + collect — supersedes the
        standalone Texture Repathing dialog and the chained collect_scene
        flow (single entry point for Tools → Asset Hub, QC #6 Assets Info,
        and Collect Scene; the latter opens with focus="deliver").

        Opened ASYNC (not modal) so Cinema 4D's main window stays
        interactive while the tool is open — critically, this keeps the
        Cmd+Z shortcut working. A modal dialog captures the keyboard, so
        after applying changes the user could not undo them with Cmd+Z
        until the dialog closed. The panel holds a reference so the dialog
        object isn't garbage-collected while open (same pattern as the
        retired Texture Repathing dialog). QC check #6 refreshes on its
        own via the CoreMessage dirty-flag once changes hit the scene, so
        no explicit refresh is needed here.
        """
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return
        try:
            existing = getattr(self, "_asset_hub", None)
            if existing is not None:
                try:
                    if existing.IsOpen():
                        existing.Close()
                except Exception:
                    pass
            dlg = AssetHubDialog(doc, focus=focus)
            dlg._artist_name = self._artist_name
            self._asset_hub = dlg
            dlg.Open(c4d.DLG_TYPE_ASYNC, defaultw=980, defaulth=560)
        except Exception as e:
            c4d.gui.MessageDialog(f"Asset Hub failed to open:\n{e}")
            safe_print(f"Asset Hub error: {e}")

    def _create_hierarchy(self, doc):
        scene_tools._create_hierarchy(doc)

    def _merge_camera_file(self, doc, filename):
        scene_tools._merge_camera_file(doc, filename)

    def _force_render_settings(self, doc):
        def update_ui():
            self._active_preset = "previz"
            self._update_preset_buttons()
        scene_tools._force_render_settings(doc, update_ui=update_ui)

    def _toggle_aspect(self, doc):
        def update_ui():
            self._update_preset_buttons()
            self._update_aspect_button()
        scene_tools._toggle_aspect(doc, update_ui=update_ui)
        # Mark dirty so a fast switch to QC recomputes preset compliance
        # without waiting for the async EVMSG_CHANGE from the resolution edit.
        self._dirty = True

    def _add_sentinel_frame_tag(self, doc):
        scene_tools._add_sentinel_frame_tag(doc)

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
        scene_tools._hierarchy_to_layers(doc)

    def _solo_layers(self, doc):
        scene_tools._solo_layers(doc)

    def _drop_to_floor(self, doc):
        scene_tools._drop_to_floor(doc)

    def _take_renderview_snapshot(self):
        scene_tools._take_renderview_snapshot(self._artist_name)

    def _apply_abc_retime_tag(self):
        scene_tools._apply_abc_retime_tag()

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
