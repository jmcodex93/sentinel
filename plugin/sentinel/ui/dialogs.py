# -*- coding: utf-8 -*-
"""Sentinel modal and async dialogs."""

import os
import re

import c4d
from c4d import gui

from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.notes import (
    _empty_notes,
    add_todo,
    delete_todo,
    summarize_notes,
    toggle_todo,
)
from sentinel.versioning import (
    STATUS_OPTIONS,
    _sanitize_status,
    preview_next_filename,
)
from sentinel.multiformat import (
    COMPOSITION_MODE_NONE,
    COMPOSITION_MODE_RESIZE_CANVAS,
    MULTIFORMAT_DEFS,
)
from sentinel.textures import (
    apply_texture_path_change,
    compute_relative_texture_path,
    find_missing_texture_candidates,
    scan_all_texture_paths,
)
from sentinel.rules import get_active_rules

from .user_areas import TextureListArea, TodoArea, _violation_label


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
