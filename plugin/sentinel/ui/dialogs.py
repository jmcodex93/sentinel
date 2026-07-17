# -*- coding: utf-8 -*-
"""Sentinel modal and async dialogs."""

import os
import re

import c4d
from c4d import gui

from sentinel import assets as assets_engine
from sentinel import baseline
from sentinel import doctor
from sentinel import supervisor
from sentinel.common.cache import check_cache
from sentinel.common.helpers import open_in_explorer, safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.fixes import apply_fixes
from sentinel.notes import (
    _empty_notes,
    add_todo,
    delete_todo,
    summarize_notes,
    toggle_todo,
)
from sentinel.qc.registry import CHECK_REGISTRY
from sentinel.qc.score import compute_score, run_all_checks
from sentinel.versioning import (
    STATUS_OPTIONS,
    _sanitize_status,
    preview_next_filename,
)
from sentinel.textures import (
    apply_texture_path_change,
    compute_relative_texture_path,
    find_missing_texture_candidates,
    scan_all_texture_paths,
)

from .ids import GateTriageIds
from .reports import build_baseline_artifact_details
from .user_areas import (
    AssetHubHeaderArea,
    AssetListArea,
    PreflightStripArea,
    TextureListArea,
    TodoArea,
    _violation_label,
)


def gate_dialog_can_proceed(blocking_items, fixable_items, decisions, reason):
    """Return whether the gate dialog state has resolved every FAIL row.

    ``decisions`` maps check_id to one of: fix, override, baseline, acknowledge.
    Advisory rows never block; WARN fixables may proceed without a decision.
    """
    decisions = decisions or {}
    reason = (reason or "").strip()

    def _decision(check_id):
        value = decisions.get(check_id)
        if isinstance(value, dict):
            return value.get("action")
        return value

    for item in blocking_items or []:
        action = _decision(item.get("check_id"))
        if action == "baseline":
            continue
        if action == "override" and reason:
            continue
        return False

    for item in fixable_items or []:
        if not item.get("blocks"):
            continue
        action = _decision(item.get("check_id"))
        if action == "fix":
            continue
        if action == "baseline":
            continue
        if action == "override" and reason:
            continue
        return False

    return True


from sentinel.rules_context import active_rules_for_doc as _active_rules_for_doc

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
            return "No new violations to accept."
        lines = [f"Accepting {len(self.new_items)} new violation(s):", ""]
        for index, item in enumerate(self.new_items[:20], 1):
            lines.append(f"{index}. {_violation_label(item)}")
        if len(self.new_items) > 20:
            lines.append(f"... and {len(self.new_items) - 20} more")
        if self.accepted_count or self.stale_count:
            lines.append("")
            lines.append(f"Currently accepted: {self.accepted_count}")
            lines.append(f"Stale: {self.stale_count}")
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
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Reason (required for Accept):", 0)
        self.AddEditText(self.EDT_REASON, c4d.BFH_SCALEFIT, 0, 0)
        self.AddSeparatorH(8)
        self.GroupBegin(0, c4d.BFH_RIGHT, 3, 0)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(self.BTN_RETIRE, c4d.BFH_RIGHT, 150, 0, "Retire acceptances")
        self.AddButton(self.BTN_ACCEPT, c4d.BFH_RIGHT, 100, 0, "Accept")
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
            confirm = self._items_text() + f"\n\nReason:\n{reason}\n\nAccept these violations?"
            if not c4d.gui.QuestionDialog(confirm):
                return True
            self.reason = reason
            self.action = "accept"
            self.Close()
            return True
        if cid == self.BTN_RETIRE:
            if not c4d.gui.QuestionDialog(
                f"Retire all acceptances for {self.row_label}?\n\n"
                "The check will count those violations as new again."
            ):
                return True
            self.action = "retire"
            self.Close()
            return True
        return True


class GateTriageDialog(gui.GeDialog):
    """Modal quality-gate triage dialog.

    After Open(c4d.DLG_TYPE_MODAL), read `proceed`, `fixes`,
    `baseline_accepts`, `overrides`, and `reason`.
    """

    def __init__(self, buckets, sidecar_invalid=False, disabled_fix_ids=None):
        super().__init__()
        buckets = buckets or {}
        self.blocking_items = list(buckets.get("blocking") or [])
        self.fixable_items = list(buckets.get("fixable") or [])
        self.advisory_items = list(buckets.get("advisory") or [])
        self.sidecar_invalid = bool(sidecar_invalid)
        self.disabled_fix_ids = set(disabled_fix_ids or [])
        self.proceed = False
        self.fixes = []
        self.baseline_accepts = []
        self.overrides = []
        self.reason = ""
        self._row_order = []

    def _label_for_item(self, item):
        check_id = item.get("check_id") or "check"
        count = int(item.get("new_count") or 0)
        lines = [f"{check_id}: {count} new violation(s)"]
        for violation in list(item.get("violations") or [])[:3]:
            lines.append(f"  - {_violation_label(violation)}")
        extra = count - min(count, 3)
        if extra > 0:
            lines.append(f"  - ... and {extra} more")
        return "\n".join(lines)

    def _fix_id(self, index):
        return GateTriageIds.FIX_BASE + index

    def _override_id(self, index):
        return GateTriageIds.OVERRIDE_BASE + index

    def _baseline_id(self, index):
        return GateTriageIds.BASELINE_BASE + index

    def _add_section_header(self, text):
        self.AddSeparatorH(6)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, text, 0)

    def _add_fixable_row(self, item, index):
        check_id = item.get("check_id")
        disabled = check_id in self.disabled_fix_ids
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(8, 0)
        self.AddCheckbox(self._fix_id(index), c4d.BFH_LEFT, 70, 0, "Fix")
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, self._label_for_item(item), 0)
        self.GroupEnd()
        if disabled:
            self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
            self.GroupSpace(8, 0)
            self.AddStaticText(0, c4d.BFH_LEFT, 90, 0, check_id, 0)
            self.AddStaticText(
                0,
                c4d.BFH_SCALEFIT,
                0,
                0,
                "Fix did not resolve this violation - requires override or accept into baseline",
                0,
            )
            self.GroupEnd()
        if item.get("blocks"):
            self.GroupBegin(0, c4d.BFH_SCALEFIT, 4, 0)
            self.GroupSpace(8, 0)
            self.AddStaticText(0, c4d.BFH_LEFT, 90, 0, check_id, 0)
            self.AddCheckbox(self._override_id(index), c4d.BFH_LEFT, 90, 0, "Override")
            self.AddCheckbox(self._baseline_id(index), c4d.BFH_LEFT, 150, 0, "Accept into baseline")
            self.GroupEnd()

    def _add_blocking_row(self, item, index):
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, self._label_for_item(item), 0)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(8, 0)
        self.AddCheckbox(self._override_id(index), c4d.BFH_LEFT, 90, 0, "Override")
        self.AddCheckbox(self._baseline_id(index), c4d.BFH_LEFT, 170, 0, "Accept into baseline")
        self.GroupEnd()

    def _add_advisory_row(self, item):
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, self._label_for_item(item), 0)

    def CreateLayout(self):
        self.SetTitle("Quality Gate")
        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.GroupSpace(0, 5)
        self.AddStaticText(
            GateTriageIds.TXT_SUMMARY,
            c4d.BFH_SCALEFIT,
            0,
            0,
            "Resolve new QC violations before continuing.",
            0,
        )

        row_index = 0
        if self.fixable_items:
            self._add_section_header("Fixable")
            for item in self.fixable_items:
                self._row_order.append((row_index, item))
                self._add_fixable_row(item, row_index)
                row_index += 1

        if self.blocking_items:
            self._add_section_header("Blocking")
            for item in self.blocking_items:
                self._row_order.append((row_index, item))
                self._add_blocking_row(item, row_index)
                row_index += 1

        if self.advisory_items:
            self._add_section_header("Advisory")
            for item in self.advisory_items:
                self._add_advisory_row(item)

        self.AddSeparatorH(6)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Shared reason for overrides:", 0)
        self.AddEditText(GateTriageIds.EDT_REASON, c4d.BFH_SCALEFIT, 0, 0)

        self.AddSeparatorH(8)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddButton(GateTriageIds.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(GateTriageIds.BTN_PROCEED, c4d.BFH_RIGHT, 100, 0, "Proceed")
        self.GroupEnd()
        self.GroupEnd()
        return True

    def InitValues(self):
        for index, item in self._row_order:
            check_id = item.get("check_id")
            if item in self.fixable_items:
                fix_enabled = check_id not in self.disabled_fix_ids
                self.SetBool(self._fix_id(index), fix_enabled)
                try:
                    self.Enable(self._fix_id(index), fix_enabled)
                except Exception:
                    pass
            if item.get("blocks"):
                self.SetBool(self._override_id(index), False)
                self.SetBool(self._baseline_id(index), False)
                try:
                    self.Enable(self._baseline_id(index), not self.sidecar_invalid)
                except Exception:
                    pass
        self.SetString(GateTriageIds.EDT_REASON, "")
        self._refresh_proceed()
        return True

    def _decisions(self):
        decisions = {}
        for index, item in self._row_order:
            check_id = item.get("check_id")
            if not check_id:
                continue
            if item in self.fixable_items:
                try:
                    if self.GetBool(self._fix_id(index)) and check_id not in self.disabled_fix_ids:
                        decisions[check_id] = "fix"
                        continue
                except Exception:
                    pass
            if item.get("blocks"):
                try:
                    if self.GetBool(self._baseline_id(index)) and not self.sidecar_invalid:
                        decisions[check_id] = "baseline"
                        continue
                except Exception:
                    pass
                try:
                    if self.GetBool(self._override_id(index)):
                        decisions[check_id] = "override"
                        continue
                except Exception:
                    pass
        return decisions

    def _refresh_proceed(self):
        can = gate_dialog_can_proceed(
            self.blocking_items,
            self.fixable_items,
            self._decisions(),
            self.GetString(GateTriageIds.EDT_REASON) or "",
        )
        try:
            self.Enable(GateTriageIds.BTN_PROCEED, can)
        except Exception:
            pass
        return can

    def _set_exclusive(self, cid):
        for index, item in self._row_order:
            override_id = self._override_id(index)
            baseline_id = self._baseline_id(index)
            fix_id = self._fix_id(index)
            if cid == override_id:
                self.SetBool(override_id, True)
                self.SetBool(baseline_id, False)
                if item in self.fixable_items:
                    self.SetBool(fix_id, False)
                return True
            if cid == baseline_id:
                if self.sidecar_invalid:
                    self.SetBool(baseline_id, False)
                    return True
                self.SetBool(baseline_id, True)
                self.SetBool(override_id, False)
                if item in self.fixable_items:
                    self.SetBool(fix_id, False)
                return True
            if cid == fix_id and item in self.fixable_items:
                if item.get("check_id") in self.disabled_fix_ids:
                    self.SetBool(fix_id, False)
                    return True
                if self.GetBool(fix_id):
                    if item.get("blocks"):
                        self.SetBool(override_id, False)
                        self.SetBool(baseline_id, False)
                return True
        return False

    def _capture_results(self):
        self.reason = (self.GetString(GateTriageIds.EDT_REASON) or "").strip()
        decisions = self._decisions()
        self.fixes = []
        self.baseline_accepts = []
        self.overrides = []
        for item in self.fixable_items:
            check_id = item.get("check_id")
            if decisions.get(check_id) == "fix":
                self.fixes.append(check_id)
            elif decisions.get(check_id) == "baseline":
                self.baseline_accepts.append(check_id)
            elif decisions.get(check_id) == "override":
                self.overrides.append(check_id)
        for item in self.blocking_items:
            check_id = item.get("check_id")
            if decisions.get(check_id) == "baseline":
                self.baseline_accepts.append(check_id)
            elif decisions.get(check_id) == "override":
                self.overrides.append(check_id)

    def Command(self, cid, msg):
        if cid == GateTriageIds.BTN_CANCEL:
            self.proceed = False
            self.Close()
            return True
        if cid == GateTriageIds.BTN_PROCEED:
            if not self._refresh_proceed():
                c4d.gui.MessageDialog(
                    "Resolve every blocking FAIL row before proceeding.\n\n"
                    "Overrides require a non-empty reason."
                )
                return True
            self._capture_results()
            self.proceed = True
            self.Close()
            return True
        if cid == GateTriageIds.EDT_REASON or self._set_exclusive(cid):
            self._refresh_proceed()
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
    EDT_MV_MAX_MOTION = 1010
    CHK_SLATE = 1011

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
                         "Multi-Part EXR default (applied when adding AOV tiers)")
        # This is only the default used when Essentials/Production add AOVs. To
        # change Multi-Part on the CURRENT scene, use the Render tab button.
        self.AddStaticText(0, c4d.BFH_LEFT, 180, 0, "", 0)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "↳ change the current scene from the Render tab", 0)

        # Review slate burn-in on snapshots (project rules key "slate" overrides).
        self.AddStaticText(0, c4d.BFH_LEFT, 180, 0, "", 0)
        self.AddCheckbox(self.CHK_SLATE, c4d.BFH_LEFT, 0, 0,
                         "Review slate on snapshots (burn-in)")
        self.AddStaticText(0, c4d.BFH_LEFT, 180, 0, "", 0)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "↳ project rules key \"slate\" overrides this", 0)

        # Motion Vectors Max Motion for the AE/RSMB path (0 = auto by render width).
        # Compositor must set RSMB "Max Displace" to the same effective value.
        self.AddStaticText(0, c4d.BFH_LEFT, 260, 0,
                           "MV Max Motion (px, 0 = auto):", 0)
        self.AddEditNumberArrows(self.EDT_MV_MAX_MOTION, c4d.BFH_LEFT, 100, 0)
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

        # Review slate burn-in checkbox
        self.SetBool(self.CHK_SLATE, GlobalSettings.get_snapshot_slate())

        # MV Max Motion (0 = auto by render width)
        try:
            mv_max = int(GlobalSettings.get('mv_max_motion', 0))
        except (TypeError, ValueError):
            mv_max = 0
        self.SetInt32(self.EDT_MV_MAX_MOTION, max(mv_max, 0), min=0)

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

                # Review slate burn-in
                GlobalSettings.set_snapshot_slate(self.GetBool(self.CHK_SLATE))

                # MV Max Motion (0 = auto by render width)
                mv_max = int(self.GetInt32(self.EDT_MV_MAX_MOTION))
                GlobalSettings.set('mv_max_motion', max(mv_max, 0))

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


# Retired from the panel in v1.11 — superseded by AssetHubDialog. Kept one release.
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


class AssetHubDialog(gui.GeDialog):
    """Sentinel Asset Hub — unified asset inventory + repathing + collect.

    Replaces TextureRepathingDialog and the chained collect_scene dialogs.
    Async (Cmd+Z must reach C4D) — same rationale as TextureRepathingDialog:
    a modal dialog captures the keyboard, so Cmd+Z would never reach C4D
    while the tool is open. Zones:
      1 header (scene, totals, Rescan)   4 repathing (find/replace, smart)
      2 filters (+ search)               5 pre-flight strip (Task 10)
      3 AssetListArea table              6 delivery bar (Task 12)

    Zone 6 (delivery bar) reuses run_collect_pipeline (Task 7) exactly —
    this dialog only gathers a preflight_payload with the same keys
    collect_scene builds, runs the missing-asset gate, and renders the
    result. No SaveProject/manifest/zip logic is duplicated here.
    """

    LBL_HEADER = 2001
    BTN_RESCAN = 2002
    FILTER_TAB = 2015  # QuickTab CustomGUI: All | Missing | Absolute | OK
    EDIT_SEARCH = 2014
    SCROLL_LIST, USERAREA_LIST = 2020, 2021
    EDIT_FIND, EDIT_REPLACE = 2030, 2031
    BTN_PREVIEW, COMBO_RECENT, CHK_MATCH_CASE = 2032, 2033, 2034
    BTN_SEARCH_FOLDER, BTN_MAKE_RELATIVE, BTN_CLEAR = 2040, 2041, 2042
    LBL_PENDING, BTN_APPLY_ALL = 2043, 2044
    BTN_RELINK = 2045  # "Relink Selected..." — replaces the removed per-row browse glyph
    LBL_PREFLIGHT = 2050
    BTN_PF_FIX, BTN_PF_ACCEPT, BTN_PF_DETAILS = 2051, 2052, 2053
    EDIT_DEST, BTN_CHOOSE_DEST = 2060, 2061
    COMBO_OUTPUT, BTN_COLLECT = 2062, 2063
    LBL_COLLECT_STATUS = 2064

    # FILTER_TAB tab index -> filter_status, in AppendString order (item 1).
    FILTER_TAB_STATUSES = (None, "missing", "absolute", "ok")

    THUMB_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".tga",
                  ".exr", ".hdr", ".psd", ".webp"}
    THUMB_CAP = 200
    THUMB_BATCH = 8
    # Ticks of quiet (no new EVMSG_CHANGE) at 250ms/tick before a pending
    # rescan fires — see the debounce comment on self._quiet_ticks.
    QUIET_TICKS_THRESHOLD = 4

    def __init__(self, doc, focus="assets"):
        super().__init__()
        self.doc = doc
        self.focus = focus
        self.records = []          # AssetRecords (merged)
        self.tex_records = []      # live TextureRecords (writers / owner_ref)
        self.skipped = 0
        self.pending = {}          # {record_key: new_path}
        self.list_ua = None
        self.header_ua = None      # AssetHubHeaderArea (item 2)
        self.preflight_ua = None   # PreflightStripArea (item 3)
        self._filter_tab = None    # FILTER_TAB QuickTab CustomGUI (item 1)
        self.filter_status = None
        self._needs_rescan = False
        # Debounce counter for the rescan-on-scene-change path (Timer runs
        # every 250ms). A busy scene edit (e.g. dragging a slider, or a
        # multi-step script) fires EVMSG_CHANGE repeatedly; rescanning on
        # every tick would re-run the full texture scan + GetAllAssetsNew +
        # all 12 QC checks dozens of times per second. Instead each new
        # change resets the counter to 0, and the rescan only fires once
        # the scene has been quiet for QUIET_TICKS_THRESHOLD ticks
        # (~1s) — a trailing-edge debounce.
        self._quiet_ticks = 0
        # Self-inflicted-event suppression: a row click's
        # SetActiveMaterial/SetActiveObject + EventAdd (_select_owner_in_scene)
        # makes C4D broadcast EVMSG_CHANGE right back at us, which would
        # otherwise arm _needs_rescan and trigger a full rescan (texture
        # scan + GetAllAssetsNew + all 12 QC checks) ~1s after every single
        # row click. Set to a few Timer ticks right before our own
        # EventAdd(); CoreMessage consumes EVMSG_CHANGE silently (without
        # arming _needs_rescan) while this is > 0. The manual Rescan
        # button is unaffected — it calls _rescan() directly.
        self._suppress_ticks = 0
        self._stat_cursor = 0      # batched size stat progress
        self._recent_presets = []
        # Zone 5 pre-flight QC payload, refreshed by _refresh_preflight().
        # Shape: {"rules_context", "registry_results", "score"} — this is
        # the exact interface Task 12's delivery bar (zone 6) consumes.
        self._preflight = {}
        # Set by the panel at open time (Task 13); default keeps _do_collect
        # safe to call standalone (e.g. from tests or before that wiring).
        self._artist_name = ""

    # ── layout ──────────────────────────────────────────
    def CreateLayout(self):
        self.SetTitle("Sentinel — Asset Hub")
        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(12, 10, 12, 10)
        self.GroupSpace(0, 6)

        # zone 1: header — colored UserArea (item 2) instead of a plain
        # StaticText, same AddUserArea/AttachUserArea pattern as the panel's
        # ScoreHeader (panel.py ~1290-1292).
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddUserArea(self.LBL_HEADER, c4d.BFH_SCALEFIT,
                         0, AssetHubHeaderArea.HEIGHT)
        if self.header_ua is None:
            self.header_ua = AssetHubHeaderArea()
        self.AttachUserArea(self.header_ua, self.LBL_HEADER)
        self.AddButton(self.BTN_RESCAN, c4d.BFH_RIGHT, 0, 0, "↻ Rescan")
        self.GroupEnd()

        # zone 2: filters (QuickTab, item 1) + search
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupSpace(6, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Filter:", 0)
        filter_bc = c4d.BaseContainer()
        filter_bc.SetBool(c4d.QUICKTAB_BAR, False)
        filter_bc.SetBool(c4d.QUICKTAB_SHOWSINGLE, True)
        filter_bc.SetBool(c4d.QUICKTAB_NOMULTISELECT, True)
        # Explicit minw: this quicktab shares a row with the "Filter:" label
        # and the search field (unlike the panel's TAB_BAR, which owns its
        # whole row — panel.py ~1298-1312). With minw=0 + BFH_LEFT the
        # widget collapsed to its bare minimum and the tab-style QuickTab
        # wrapped vertically instead of laying out 4 tabs side by side.
        # 280px still wrapped "OK" to a second row at real font size;
        # 400px fits all 4 tabs ("All | Missing | Absolute | OK") on one
        # horizontal row (verified against the panel's own TAB_BAR pattern).
        self._filter_tab = self.AddCustomGui(
            self.FILTER_TAB, c4d.CUSTOMGUI_QUICKTAB, "",
            c4d.BFH_LEFT, 400, 0, filter_bc)
        if self._filter_tab is not None:
            self._filter_tab.AppendString(0, "All", self.filter_status is None)
            self._filter_tab.AppendString(1, "Missing", self.filter_status == "missing")
            self._filter_tab.AppendString(2, "Absolute", self.filter_status == "absolute")
            self._filter_tab.AppendString(3, "OK", self.filter_status == "ok")
        self.AddEditText(self.EDIT_SEARCH, c4d.BFH_SCALEFIT, 0, 0)
        self.GroupEnd()

        # zone 3: table
        self.ScrollGroupBegin(self.SCROLL_LIST,
                              c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                              c4d.SCROLLGROUP_VERT | c4d.SCROLLGROUP_AUTOVERT,
                              0, 300)
        self.AddUserArea(self.USERAREA_LIST,
                         c4d.BFH_SCALEFIT | c4d.BFV_TOP, 700, 420)
        if self.list_ua is None:
            self.list_ua = AssetListArea()
        self.AttachUserArea(self.list_ua, self.USERAREA_LIST)
        self.list_ua.click_callback = self._on_row_click
        self.GroupEnd()

        self.AddSeparatorH(8)

        # zone 4: repathing
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0, "Repathing")
        self.GroupBorderSpace(8, 8, 8, 8)
        self.GroupSpace(6, 4)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 5, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Find:", 0)
        self.AddEditText(self.EDIT_FIND, c4d.BFH_SCALEFIT, 0, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 90, 0, "Replace:", 0)
        self.AddEditText(self.EDIT_REPLACE, c4d.BFH_SCALEFIT, 0, 0)
        self.AddButton(self.BTN_PREVIEW, c4d.BFH_LEFT, 0, 0, "Preview")
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 4, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Recent:", 0)
        self.AddComboBox(self.COMBO_RECENT, c4d.BFH_SCALEFIT, 0, 0)
        self.AddCheckbox(self.CHK_MATCH_CASE, c4d.BFH_LEFT, 0, 0, "Match case")
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 7, 0)
        self.AddButton(self.BTN_SEARCH_FOLDER, c4d.BFH_LEFT, 0, 0,
                       "Search Folder for Missing…")
        # Relink a single selected row (Crate reference-UI pattern) — the
        # per-row "…" glyph it replaces was removed after three rounds of
        # fixes (fixed slot, drag clamp, fit-to-viewport, scrollbar
        # padding) still couldn't make it reliably visible. Always
        # enabled; the handler's own guard messages cover no-selection /
        # read-only rather than a disabled-state affordance.
        self.AddButton(self.BTN_RELINK, c4d.BFH_LEFT, 0, 0,
                       "Relink Selected…")
        self.AddButton(self.BTN_MAKE_RELATIVE, c4d.BFH_LEFT, 0, 0,
                       "Make All Relative")
        self.AddButton(self.BTN_CLEAR, c4d.BFH_LEFT, 0, 0, "Clear Pending")
        self.AddStaticText(self.LBL_PENDING, c4d.BFH_SCALEFIT | c4d.BFH_RIGHT,
                           0, 0, "", 0)
        self.AddButton(self.BTN_APPLY_ALL, c4d.BFH_RIGHT, 0, 0,
                       "Apply All (1 undo)")
        self.GroupEnd()
        self.GroupEnd()  # repathing

        # Breathing room between Repathing and Pre-flight QC (item 5) —
        # mirrors the AddSeparatorH(4) rhythm TextureRepathingDialog uses
        # between its "Bulk Find & Replace" and "Smart Actions" groups.
        self.AddSeparatorH(6)

        # zone 5: pre-flight QC strip — colored UserArea (item 3) instead
        # of a plain StaticText.
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 4, 0, "Pre-flight QC")
        self.GroupBorderSpace(8, 6, 8, 6)
        self.AddUserArea(self.LBL_PREFLIGHT, c4d.BFH_SCALEFIT,
                         0, PreflightStripArea.HEIGHT)
        if self.preflight_ua is None:
            self.preflight_ua = PreflightStripArea()
        self.AttachUserArea(self.preflight_ua, self.LBL_PREFLIGHT)
        self.AddButton(self.BTN_PF_FIX, c4d.BFH_RIGHT, 0, 0, "Fix auto-fixables")
        self.AddButton(self.BTN_PF_ACCEPT, c4d.BFH_RIGHT, 0, 0, "Accept…")
        self.AddButton(self.BTN_PF_DETAILS, c4d.BFH_RIGHT, 0, 0, "Details")
        self.GroupEnd()

        # zone 6: delivery bar
        self.AddSeparatorH(8)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 6, 0, "Deliver")
        self.GroupBorderSpace(8, 6, 8, 6)
        self.AddStaticText(0, c4d.BFH_LEFT, 90, 0, "Deliver to:", 0)
        self.AddEditText(self.EDIT_DEST, c4d.BFH_SCALEFIT, 0, 0)
        self.AddButton(self.BTN_CHOOSE_DEST, c4d.BFH_LEFT, 0, 0, "Choose…")
        self.AddComboBox(self.COMBO_OUTPUT, c4d.BFH_LEFT, 90, 0)
        self.AddButton(self.BTN_COLLECT, c4d.BFH_LEFT, 0, 0, "Collect ▸")
        self.GroupEnd()
        self.AddStaticText(self.LBL_COLLECT_STATUS, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        self.GroupEnd()  # main
        return True

    def InitValues(self):
        self.SetBool(self.CHK_MATCH_CASE, False)
        self._load_recent_presets()
        self.AddChild(self.COMBO_OUTPUT, 0, "Folder")
        self.AddChild(self.COMBO_OUTPUT, 1, "Zip")
        self.SetInt32(self.COMBO_OUTPUT, 0)
        self._rescan()
        # Poll for scene changes (external undo/redo, edits) the same way
        # TextureRepathingDialog does, so the list stays in sync without
        # the user reopening the dialog.
        self.SetTimer(250)
        if self.focus == "deliver":
            self.Activate(self.EDIT_DEST)
        return True

    # ── recent Find/Replace presets ────────────────────
    # Reuses the EXACT same module-level helpers (and therefore the same
    # `sentinel_settings.json` key, TEXTURE_REPATH_PRESETS_KEY) that
    # TextureRepathingDialog already persists to — the user's existing
    # presets carry over untouched, nothing is reimplemented here.
    def _load_recent_presets(self):
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

    def _save_recent_preset(self, find_str, replace_str):
        save_repath_preset(find_str, replace_str)
        self._load_recent_presets()

    # ── data ────────────────────────────────────────────
    def _rescan(self):
        # Deferred import: sentinel.ui.flows imports GateTriageDialog from
        # this module (dialogs.py), so importing flows at module scope here
        # would create a circular import. Same constraint scan_scene_assets
        # itself documents for its own use of sentinel.ui.dialogs.
        from sentinel.ui.flows import scan_scene_assets
        self.records, self.tex_records, self.skipped = \
            scan_scene_assets(self.doc)
        self.pending = {}
        self._stat_cursor = 0
        self._push_state()
        # Single call site: InitValues and _apply_all both route through
        # _rescan(), so refreshing the pre-flight strip here satisfies the
        # "InitValues and after _apply_all/_rescan" requirement without
        # running the QC pass twice per trigger.
        self._refresh_preflight()

    def _push_state(self):
        totals = assets_engine.compute_totals(self.records)
        doc_name = self.doc.GetDocumentName() or "(unsaved)"
        suffix_parts = []
        if self._stat_cursor < len(self.records):
            suffix_parts.append("sizing…")
        if self.skipped:
            suffix_parts.append(f"{self.skipped} skipped")
        self.header_ua.set_header_state(
            doc_name, totals["count"], totals["missing"], totals["absolute"],
            assets_engine.format_size(totals["total_bytes"]),
            " · ".join(suffix_parts))
        self.SetString(self.LBL_PENDING,
                       f"{len(self.pending)} pending changes"
                       if self.pending else "")
        self.list_ua.set_state(self.records, self.filter_status,
                               self.GetString(self.EDIT_SEARCH) or "",
                               self.pending)
        self.LayoutChanged(self.SCROLL_LIST)

    def _load_thumbs_batch(self):
        # Loads up to THUMB_BATCH thumbnails per Timer tick — never from
        # DrawMsg, which must stay a pure read of thumb_cache (see
        # AssetListArea.DrawMsg / Task 8). A None cache entry is a
        # permanent placeholder: a failed/unsupported load is recorded
        # once and never retried on subsequent ticks.
        cache = self.list_ua.thumb_cache
        loaded = 0
        first, last = self.list_ua.get_visible_range()
        for idx in self.list_ua.visible[first:last]:
            rec = self.records[idx]
            path = rec.get("resolved_path")
            if (not path or path in cache or rec["status"] == "missing"
                    or os.path.splitext(path)[1].lower() not in self.THUMB_EXTS):
                continue
            try:
                bmp = c4d.bitmaps.BaseBitmap()
                if bmp.InitWith(path)[0] == c4d.IMAGERESULT_OK:
                    small = c4d.bitmaps.BaseBitmap()
                    small.Init(22, 22)
                    bmp.ScaleIt(small, 256, True, False)
                    cache[path] = small
                else:
                    cache[path] = None  # permanent placeholder, no retry
            except Exception:
                cache[path] = None
            loaded += 1
            if loaded >= self.THUMB_BATCH:
                break
        # FIFO eviction: dicts preserve insertion order, so the oldest
        # entries (by first-load order) are the ones dropped first.
        if len(cache) > self.THUMB_CAP:
            for k in list(cache.keys())[: len(cache) - self.THUMB_CAP]:
                del cache[k]
        if loaded:
            self.list_ua.Redraw()
        return loaded

    # ── events ──────────────────────────────────────────
    def Timer(self, msg):
        # Decrement the self-inflicted-event suppression window (see the
        # comment on self._suppress_ticks in __init__) — independent of
        # the pending-edits early return below, so it counts down even
        # while a repathing preview is in progress.
        if self._suppress_ticks > 0:
            self._suppress_ticks -= 1
        # Skip the rescan while there are pending (un-applied) repathing
        # edits, same guard as TextureRepathingDialog.Timer — otherwise an
        # unrelated scene change (or even our own Apply All mid-batch)
        # would silently wipe the user's preview edits before they get a
        # chance to hit Apply All. The brief's reference code rescanned
        # unconditionally on _needs_rescan; that's a data-loss regression
        # from the proven pattern, fixed here.
        # Debounced rescan: only fires once the scene has been quiet for
        # QUIET_TICKS_THRESHOLD ticks since the last EVMSG_CHANGE (reset in
        # CoreMessage below) — see the comment on self._quiet_ticks.
        if self._needs_rescan and not self.pending:
            self._quiet_ticks += 1
            if self._quiet_ticks >= self.QUIET_TICKS_THRESHOLD:
                self._needs_rescan = False
                self._quiet_ticks = 0
                self._rescan()
            return
        if self._stat_cursor < len(self.records):
            self._stat_cursor = assets_engine.stat_sizes_batch(
                self.records, self._stat_cursor, 12)
            self._push_state()
        self._load_thumbs_batch()

    def CoreMessage(self, cid, msg):
        if cid == c4d.EVMSG_CHANGE:
            if self._suppress_ticks > 0:
                # Self-echo from our own row-click selection
                # (_select_owner_in_scene's EventAdd) — consume silently,
                # do NOT arm _needs_rescan. See self._suppress_ticks.
                return gui.GeDialog.CoreMessage(self, cid, msg)
            self._needs_rescan = True
            # Any new change restarts the quiet period — the rescan only
            # fires after QUIET_TICKS_THRESHOLD ticks with no further
            # changes (trailing-edge debounce, see Timer).
            self._quiet_ticks = 0
        return gui.GeDialog.CoreMessage(self, cid, msg)

    def Command(self, cid, msg):
        if cid == self.BTN_RESCAN:
            self._rescan()
        elif cid == self.FILTER_TAB:
            # QuickTab selection (item 1) — find which tab is selected and
            # map its index to a filter_status, same IsSelected() scan the
            # panel's TAB_BAR handler uses (panel.py Command, cid == G.TAB_BAR).
            if self._filter_tab is not None:
                for i, status in enumerate(self.FILTER_TAB_STATUSES):
                    try:
                        if self._filter_tab.IsSelected(i):
                            self.filter_status = status
                            break
                    except Exception:
                        pass
            self._push_state()
        elif cid == self.EDIT_SEARCH:
            self._push_state()
        elif cid == self.COMBO_RECENT:
            # Wired up per the proven pattern (TextureRepathingDialog):
            # selecting a recent preset fills Find/Replace, then the combo
            # snaps back to the placeholder row. The brief laid out this
            # widget but never dispatched its Command — left it dead.
            idx = int(self.GetInt32(self.COMBO_RECENT))
            if 1 <= idx <= len(self._recent_presets):
                find_str, repl_str = self._recent_presets[idx - 1]
                self.SetString(self.EDIT_FIND, find_str)
                self.SetString(self.EDIT_REPLACE, repl_str)
            self.SetInt32(self.COMBO_RECENT, 0)
        elif cid == self.BTN_PREVIEW:
            self._preview_bulk()
        elif cid == self.BTN_SEARCH_FOLDER:
            self._search_folder_for_missing()
        elif cid == self.BTN_RELINK:
            self._relink_selected()
        elif cid == self.BTN_MAKE_RELATIVE:
            self._make_all_relative()
        elif cid == self.BTN_CLEAR:
            self.pending = {}; self._push_state()
        elif cid == self.BTN_APPLY_ALL:
            self._apply_all()
        elif cid == self.BTN_PF_FIX:
            self._fix_preflight()
        elif cid == self.BTN_PF_ACCEPT:
            self._accept_preflight()
        elif cid == self.BTN_PF_DETAILS:
            self._show_preflight_details()
        elif cid == self.BTN_CHOOSE_DEST:
            chosen = c4d.storage.LoadDialog(
                title="Select folder to collect project into",
                flags=c4d.FILESELECT_DIRECTORY)
            if chosen:
                self.SetString(self.EDIT_DEST, chosen)
        elif cid == self.BTN_COLLECT:
            self._do_collect()
        return True

    # ── actions ─────────────────────────────────────────
    def _record_by_key(self, key):
        for r in self.records:
            if r["key"] == key:
                return r
        return None

    def _on_row_click(self, key, region):
        # No "browse" region anymore — the per-row "…" glyph was removed
        # (see AssetListArea's class docstring); relinking is the
        # dedicated "Relink Selected..." button (_relink_selected) now,
        # driven by AssetListArea.selected_key instead of a click region.
        rec = self._record_by_key(key)
        if rec is None:
            return
        if region in ("used_by", "row"):
            # Clicking anywhere in the row body selects the owning
            # material/object, same as clicking "Used by" specifically —
            # the highlight itself was already set by
            # AssetListArea.InputEvent before this callback runs.
            self._select_owner_in_scene(rec)

    def _select_owner_in_scene(self, rec):
        """Select the record's owning material/object in the scene.

        Rows with no tex_idx (generic GetAllAssetsNew entries that aren't
        backed by a structured TextureRecord — e.g. some Alembic caches)
        are a no-op: highlight only, no owner_ref is retained for them to
        select (known debt, see assets.merge_asset_records).
        """
        if rec["tex_idx"] is None:
            return
        host = self.tex_records[rec["tex_idx"]].get("host")
        if host is None:
            return
        if isinstance(host, c4d.BaseMaterial):
            self.doc.SetActiveMaterial(host)
        else:
            self.doc.SetActiveObject(host)
        # Arm the self-inflicted-event suppression window right before our
        # own EventAdd() — the SetActive* call above makes C4D broadcast
        # EVMSG_CHANGE back at us via CoreMessage; without this, every row
        # click would arm _needs_rescan and trigger a full rescan (texture
        # scan + GetAllAssetsNew + all 12 QC checks) ~1s later.
        self._suppress_ticks = 3
        c4d.EventAdd()

    def _relink_selected(self):
        """Relink the row currently selected in AssetListArea — replaces
        the removed per-row "…" browse glyph (Crate reference-UI pattern:
        a dedicated "Relink Selected..." button instead of a per-row
        affordance that three rounds of fixes couldn't make reliably
        visible). Same semantics the browse dots had: stages a pending
        change, Apply All commits it.
        """
        key = self.list_ua.selected_key
        if key is None:
            c4d.gui.MessageDialog("Select an asset row first.")
            return
        rec = self._record_by_key(key)
        if rec is None:
            c4d.gui.MessageDialog("Select an asset row first.")
            return
        if not rec["repathable"]:
            c4d.gui.MessageDialog(
                "This asset is read-only — it cannot be relinked.")
            return
        path = c4d.storage.LoadDialog(title="Choose replacement file")
        if path:
            self.pending[key] = path
            self._push_state()

    def _preview_bulk(self):
        import re
        find = self.GetString(self.EDIT_FIND)
        repl = self.GetString(self.EDIT_REPLACE)
        if not find:
            c4d.gui.MessageDialog("Enter a string in the 'Find' field.")
            return
        flags = 0 if self.GetBool(self.CHK_MATCH_CASE) else re.IGNORECASE
        pattern = re.compile(re.escape(find), flags)
        matched = 0
        for rec in self.records:
            # Same status gate as TextureRepathingDialog._do_find_replace_
            # preview: "asset_uri" (RS Asset Manager asset:/preset: URIs)
            # and "empty" paths are not real filesystem strings — rewriting
            # them with a text substitution would produce a broken literal
            # path instead of leaving the URI alone. The brief's reference
            # code only gated on `repathable`, which both statuses satisfy,
            # so it would have corrupted those records; fixed here.
            if not rec["repathable"] or rec["status"] in ("asset_uri", "empty"):
                continue
            new = pattern.sub(lambda _m: repl, rec["path"])
            if new != rec["path"]:
                self.pending[rec["key"]] = new
                matched += 1
        self._save_recent_preset(find, repl)
        self._push_state()
        if matched == 0:
            case_note = ("matching is case-insensitive; "
                         if not self.GetBool(self.CHK_MATCH_CASE) else "")
            c4d.gui.MessageDialog(
                f"No repathable paths contain '{find}' "
                f"({case_note}read-only assets are not repathed).")

    def _make_all_relative(self):
        doc_path = self.doc.GetDocumentPath() or ""
        if not doc_path:
            c4d.gui.MessageDialog(
                "The document must be saved first — relative paths "
                "are computed against the document folder.")
            return
        converted = 0
        skipped_cross_drive = 0
        for rec in self.records:
            if not rec["repathable"] or rec["status"] != "absolute":
                continue
            # rec["path"] may be a raw absolute path OR a maxon `file://`
            # URL (both classify as "absolute" — see textures._classify_
            # texture_path). compute_relative_texture_path expects a plain
            # filesystem path; feeding it the raw `file://...` string (as
            # the brief's reference code does) makes os.path.relpath treat
            # the whole URL as an opaque path segment and emit a bogus
            # relative string. Strip the scheme first, same as
            # TextureRepathingDialog._do_make_all_relative.
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
            self.pending[rec["key"]] = rel
            converted += 1
        self._push_state()
        msg = f"{converted} absolute path(s) → relative."
        if skipped_cross_drive:
            msg += (f"\n\n{skipped_cross_drive} path(s) skipped (cross-drive "
                    f"— can't be made relative).")
        c4d.gui.MessageDialog(msg)

    def _search_folder_for_missing(self):
        root = c4d.storage.LoadDialog(
            title="Search this folder for missing assets",
            flags=c4d.FILESELECT_DIRECTORY)
        if not root:
            return
        index, truncated = assets_engine.build_file_index(root)
        matches = assets_engine.match_missing_in_folder(self.records, index)
        found = ambiguous = 0
        for key, m in matches.items():
            rec = self._record_by_key(key)
            if rec is None or not rec["repathable"]:
                continue
            if "match" in m:
                self.pending[key] = m["match"]; found += 1
            else:
                ambiguous += 1
        msg = f"Matched {found} missing asset(s)."
        if ambiguous:
            msg += (f"\n{ambiguous} ambiguous (2+ candidates) — use the row"
                    " […] picker to choose manually.")
        if truncated:
            msg += "\n\nWarning: folder had >50k files, index truncated."
        c4d.gui.MessageDialog(msg)
        self._push_state()

    def _apply_all(self):
        if not self.pending:
            c4d.gui.MessageDialog("No pending changes to apply.")
            return
        n_total = len(self.pending)
        if not c4d.gui.QuestionDialog(
                f"Apply {n_total} change(s) to the scene?\n\n"
                "All changes are wrapped in a single undo step — "
                "Cmd+Z reverts the whole batch."):
            return
        applied = 0
        failed = []
        self.doc.StartUndo()
        try:
            for key, new_path in list(self.pending.items()):
                rec = self._record_by_key(key)
                # A merged row can represent several shaders sharing one path
                # (e.g. 3 materials referencing the same file) — repath every
                # one of them, not just the first tex_idx.
                idxs = rec.get("tex_idxs") if rec else None
                if not idxs:
                    idxs = ([rec["tex_idx"]]
                            if rec and rec.get("tex_idx") is not None else [])
                if not idxs:
                    failed.append((key, "not repathable"))
                    continue
                # Tally per ROW, not per shader write: n_total is len(pending),
                # so a row with 3 shaders must count as 1 applied (all wrote
                # OK) or 1 failed (any wrote wrong) — never as 3 applieds.
                row_err = None
                for tex_idx in idxs:
                    live = self.tex_records[tex_idx]
                    try:
                        if not apply_texture_path_change(live, new_path, doc=self.doc):
                            row_err = row_err or "writer returned False"
                    except Exception as e:
                        row_err = row_err or str(e)
                if row_err is None:
                    applied += 1
                else:
                    failed.append((key, row_err))
        finally:
            self.doc.EndUndo()
        c4d.EventAdd()
        lines = [f"Applied {applied} of {n_total} change(s)."]
        if failed:
            lines.append("")
            lines.append(f"Failed ({len(failed)}):")
            for key, err in failed[:8]:
                lines.append(f"  • [{key}] {err}")
            if len(failed) > 8:
                lines.append(f"  ... +{len(failed) - 8} more")
        c4d.gui.MessageDialog("\n".join(lines))
        self._rescan()

    # ── zone 5: pre-flight QC strip ─────────────────────
    def _refresh_preflight(self):
        """Re-run QC + score the same way `collect_scene` does (flows.py
        Phase 1) and refresh the strip's label + button states.

        `_baseline_path_for_doc`/`_current_module` are private helpers that
        only live in ui.flows — imported locally (not at module scope) to
        avoid the same flows<->dialogs circular import _rescan() already
        works around (flows imports GateTriageDialog from this module).
        `_active_rules_for_doc`, `run_all_checks` and `compute_score` have
        no such constraint and are already imported at module scope above.
        """
        from sentinel.ui.flows import _baseline_path_for_doc, _current_module
        rules_context = _active_rules_for_doc(self.doc)
        registry_results = run_all_checks(self.doc, _current_module(), rules_context)
        baseline_path = _baseline_path_for_doc(self.doc, only_existing=True)
        kwargs = {"baseline_path": baseline_path,
                  "current_params": rules_context.params} if baseline_path else {}
        score = compute_score(registry_results, rules_context, **kwargs)
        self._preflight = {"rules_context": rules_context,
                           "registry_results": registry_results,
                           "score": score}
        failing = {cid: n for cid, n in score["counts"].items() if n}
        label = (f"✓ {score['passed']}/{score['total']} — all clear"
                 if not failing else
                 f"⚠ {score['passed']}/{score['total']} — " +
                 " · ".join(f"{cid}: {n}" for cid, n in failing.items()))
        self.preflight_ua.set_state(not failing, label)
        self.Enable(self.BTN_PF_FIX, bool(failing))
        self.Enable(self.BTN_PF_ACCEPT, bool(failing))

    def _fix_preflight(self):
        """Auto-fix the object-scoped fixable checks in one undo step.

        Gathers the fix payload exactly the way `collect_scene`'s Phase 1
        "Yes" branch does (flows.py ~529-536: has_fix + fix_scope=="objects"
        checks, objects taken from the legacy result list) — but applies it
        through `sentinel.fixes.apply_fixes`, which wraps the whole batch in
        a single StartUndo/EndUndo (collect_scene's own loop calls each
        fix_fn with its default manage_undo=True, i.e. one undo step PER
        check — not the single atomic undo this strip's interface requires).
        Document-scoped fixes (fps_range) are skipped, matching
        collect_scene, which never auto-fixes them from this loop either.
        """
        registry_results = (self._preflight or {}).get("registry_results") or {}
        legacy_by_id = {
            check_id: pair.get("legacy_result")
            for check_id, pair in registry_results.items()
        }
        fixes = []
        for entry in CHECK_REGISTRY:
            if not entry.has_fix or entry.fix_scope != "objects":
                continue
            objs = legacy_by_id.get(entry.check_id) or []
            if not objs:
                continue
            fixes.append({"check_id": entry.check_id, "objects": objs})
        if not fixes:
            c4d.gui.MessageDialog("No auto-fixable issues found.")
            return
        results = apply_fixes(self.doc, fixes)
        fixed_total = sum(int(r.get("result") or 0) for r in results)
        c4d.gui.MessageDialog(
            f"Auto-fixed {fixed_total} issue(s) across {len(results)} check(s).")
        self._refresh_preflight()

    def _new_violations_for_check(self, check_id):
        """Return the new-violation dicts for one check_id.

        Mirrors panel.py's `_new_violations_for_row`: prefer the baseline
        diff (`score["baseline_matches"]`) when a baseline sidecar exists,
        else fall back to the raw structured violations tagged with their
        check_id.
        """
        score = (self._preflight or {}).get("score") or {}
        if score.get("baseline_matches"):
            match = score["baseline_matches"].get(check_id, {}) or {}
            return list(match.get("new") or [])
        registry_results = (self._preflight or {}).get("registry_results") or {}
        result_pair = registry_results.get(check_id, {}) or {}
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
                item["check_id"] = check_id
                items.append(item)
        return items

    def _accept_preflight(self):
        """Accept (or retire) baseline acceptances for every failing check.

        The strip has no per-row table (unlike the QC panel), so this walks
        every check_id with new violations and opens one `BaselineActionDialog`
        per check — the exact same dialog + accept/retire logic as panel.py's
        `_show_baseline_actions(row_key)`, just looped instead of triggered
        by a single row click. Cancelling a dialog stops the batch rather
        than silently skipping to the next check.
        """
        score = (self._preflight or {}).get("score") or {}
        failing_ids = [cid for cid, n in (score.get("counts") or {}).items() if n]
        if not failing_ids:
            c4d.gui.MessageDialog("No failing checks to accept.")
            return

        from sentinel.ui.flows import _baseline_path_for_doc
        baseline_path = _baseline_path_for_doc(self.doc, only_existing=False)
        if not baseline_path:
            c4d.gui.MessageDialog(
                "Save the scene first — the baseline sidecar path is "
                "derived from the file location.")
            return

        rules_context = (self._preflight or {}).get("rules_context")
        author = baseline.resolve_author(self._artist_name or None)
        accepted_checks = 0
        written_total = 0
        for check_id in failing_ids:
            new_items = self._new_violations_for_check(check_id)
            accepted_count = (score.get("accepted_counts") or {}).get(check_id, 0)
            stale_count = (score.get("stale_counts") or {}).get(check_id, 0)
            if not new_items and not accepted_count and not stale_count:
                continue
            entry = next((e for e in CHECK_REGISTRY if e.check_id == check_id), None)
            row_label = entry.row_label if entry else check_id
            dlg = BaselineActionDialog(row_label, new_items, accepted_count, stale_count)
            try:
                dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=520, defaulth=320)
            except Exception as e:
                safe_print(f"BaselineActionDialog open error: {e}")
                continue
            if dlg.action == "accept":
                for item in new_items:
                    acceptance = baseline.entry_from_violation(
                        item, author=author, reason=dlg.reason,
                        current_params=getattr(rules_context, "params", {}))
                    if acceptance and baseline.add_acceptance(baseline_path, acceptance):
                        written_total += 1
                accepted_checks += 1
            elif dlg.action == "retire":
                baseline.remove_acceptances_for_check(baseline_path, check_id)
                accepted_checks += 1
            elif dlg.action is None:
                break  # user cancelled — stop the batch, don't force the rest

        if accepted_checks:
            check_cache.clear()
            c4d.gui.MessageDialog(
                f"Baseline updated for {accepted_checks} check(s), "
                f"{written_total} violation(s) accepted.")
        self._refresh_preflight()

    def _show_preflight_details(self):
        """MessageDialog with the per-check violation breakdown.

        Uses `build_baseline_artifact_details(score)` — the exact helper the
        Scene Collector manifest uses for its `qc.checks` block — so the
        detail lines match what ships in the delivery manifest. That helper
        only returns per-violation labels when the score carries baseline
        schema 2 data (i.e. a baseline sidecar exists); without one this
        still shows the per-check counts from `score["counts"]`.
        """
        if not self._preflight:
            c4d.gui.MessageDialog("Run a pre-flight scan first.")
            return
        score = self._preflight.get("score") or {}
        counts = score.get("counts") or {}
        details = build_baseline_artifact_details(score)
        lines = []
        for entry in CHECK_REGISTRY:
            n = counts.get(entry.check_id, 0)
            if not n:
                continue
            lines.append(f"{entry.row_label} ({entry.check_id}): {n} new violation(s)")
            detail = details.get(entry.check_id)
            if detail:
                for label in detail.get("new", [])[:10]:
                    lines.append(f"  - {label}")
                extra = detail.get("new_count", 0) - min(detail.get("new_count", 0), 10)
                if extra > 0:
                    lines.append(f"  ... and {extra} more")
        if not lines:
            lines = ["All checks passed — no violations."]
        c4d.gui.MessageDialog("\n".join(lines))

    # ── zone 6: delivery bar ────────────────────────────
    def _build_collect_preflight_payload(self, rules_context, score):
        """Assemble the preflight_payload dict `run_collect_pipeline` expects,
        with the same keys `collect_scene` (flows.py Phase 1) builds:
        issues, preflight_score, rules_context, gate_overrides,
        gate_evaluated, baseline_path, baseline_entries.

        `issues` is derived from `score["counts"]` + each registry entry's
        `preflight_template`, in `preflight_order` — the exact loop
        collect_scene runs, duplicated here because that loop is entangled
        with collect_scene's own MessageDialog flow (not factored out into
        a reusable helper) and the Hub drives its own missing-asset gate
        instead of that dialog.

        Runs `_run_quality_gate` (the same modal gate collect_scene uses)
        BEFORE the pipeline when `gates_enabled` is set in the resolved
        rules; returns None if the gate is cancelled (proceed=False), same
        as collect_scene aborting the collect.
        """
        from sentinel.ui.flows import (
            _run_quality_gate, _doc_full_path, _baseline_path_for_doc)

        issues = []
        preflight_entries = sorted(
            enumerate(CHECK_REGISTRY),
            key=lambda item: (
                item[1].preflight_order
                if item[1].preflight_order is not None
                else item[0]
            ),
        )
        for _idx, entry in preflight_entries:
            count = (score.get("counts") or {}).get(entry.check_id, 0)
            if count:
                issues.append(entry.preflight_template.format(n=count))

        baseline_path_for_payload = _baseline_path_for_doc(self.doc, only_existing=True)
        baseline_entries_for_payload = []
        if baseline_path_for_payload:
            entries, status = baseline.load_baseline(baseline_path_for_payload)
            if status == baseline.STATUS_OK:
                baseline_entries_for_payload = entries

        gate_overrides = []
        gate_evaluated = False
        if getattr(rules_context, "params", {}).get("gates_enabled", False):
            gate_evaluated = True
            original_full_path = _doc_full_path(self.doc)
            gate_result = _run_quality_gate(
                self.doc, rules_context, self._artist_name, original_full_path)
            if not gate_result.get("proceed"):
                return None
            gate_overrides = list(gate_result.get("overrides") or [])
            if gate_result.get("baseline_changed"):
                refreshed_path = (gate_result.get("baseline_path")
                                  or baseline.get_baseline_path(original_full_path))
                refreshed_entries, refreshed_status = baseline.load_baseline(refreshed_path)
                if refreshed_status == baseline.STATUS_OK:
                    baseline_path_for_payload = refreshed_path
                    baseline_entries_for_payload = refreshed_entries

        return {
            "issues": issues,
            "preflight_score": score,
            "rules_context": rules_context,
            "gate_overrides": gate_overrides,
            "gate_evaluated": gate_evaluated,
            "baseline_path": baseline_path_for_payload,
            "baseline_entries": baseline_entries_for_payload,
        }

    def _do_collect(self):
        from sentinel.ui.flows import run_collect_pipeline

        # Unsaved-doc guard — mirrors collect_scene's legacy guard
        # (flows.py:458): the delivery path, baseline sidecar, and manifest
        # location are all derived from the document's saved path.
        if not self.doc.GetDocumentPath():
            c4d.gui.MessageDialog(
                "Please save the scene first before collecting.")
            return

        target = self.GetString(self.EDIT_DEST).strip()
        if not target:
            c4d.gui.MessageDialog("Choose a delivery folder first.")
            return

        # Pending-edits warning: unapplied repathing changes never make it
        # into the collected package (only self.records feeds the pipeline),
        # so surface that before the user loses the edits silently.
        if self.pending:
            if not c4d.gui.QuestionDialog(
                    f"{len(self.pending)} pending repathing change(s) are "
                    "NOT applied and will not be in the package.\n\n"
                    "Continue anyway?"):
                return

        # Missing gate: warn & continue (spec) — never a hard block, since
        # the pipeline itself tolerates missing assets (SAVEPROJECT_DONT
        # FAILONMISSINGASSETS) and records them in the manifest.
        missing = [r for r in self.records if r["status"] == "missing"]
        if missing:
            names = "\n".join(
                f"  • {os.path.basename(r['path'])}" for r in missing[:12])
            more = f"\n  … +{len(missing) - 12} more" if len(missing) > 12 else ""
            if not c4d.gui.QuestionDialog(
                    f"{len(missing)} missing asset(s) will NOT be in the "
                    f"package:\n\n{names}{more}\n\nContinue anyway?"):
                return

        if not self._preflight:
            self._refresh_preflight()
        rules_context = self._preflight.get("rules_context")
        score = self._preflight.get("score") or {}
        preflight_payload = self._build_collect_preflight_payload(rules_context, score)
        if preflight_payload is None:
            return  # quality gate cancelled — mirrors collect_scene's abort

        make_zip = self.GetInt32(self.COMBO_OUTPUT) == 1
        result = run_collect_pipeline(
            self.doc, self._artist_name, target,
            make_zip=make_zip,
            preflight_payload=preflight_payload,
            on_status=lambda m: self.SetString(self.LBL_COLLECT_STATUS, m))
        if result is None:
            c4d.gui.MessageDialog("Collect failed — see console.")
            return
        self._show_collect_summary(result)

    def _show_collect_summary(self, result):
        lines = [
            "Collect complete.",
            "",
            f"Destination : {result['target_dir']}",
            f"Scene file  : {result['delivery_filename']}",
            f"Assets      : {result['assets_collected']} collected, "
            f"{result['assets_missing']} missing",
        ]
        if result.get("zip"):
            z = result["zip"]
            lines.append(f"Zip         : {z['zip_path']} "
                         f"({assets_engine.format_size(z['bytes'])}, {z['files']} files)")
        if result.get("zip_error"):
            # Zip failure never invalidates the folder delivery — SaveProject
            # + manifest already succeeded by the time zipping runs.
            lines.append(f"Zip FAILED  : {result['zip_error']} "
                         "(folder delivery is intact)")
        if result.get("pending_todos"):
            lines.append(f"⚠ {result['pending_todos']} pending TODO(s) "
                         "in scene notes")
        lines += ["", "Open delivery folder?"]
        if c4d.gui.QuestionDialog("\n".join(lines)):
            open_in_explorer(result["target_dir"])

    def refresh(self):
        """Public method: full re-scan, for callers outside the dialog
        (e.g. a future 'Rescan after Collect' hook in zones 5-6)."""
        self._rescan()


# Tag prefixes for the item rows, mirrors doctor.build_copyable_report.
_DOCTOR_STATUS_TAG = {
    doctor.OK: "[OK]",
    doctor.WARN: "[WARN]",
    doctor.FAIL: "[FAIL]",
    doctor.INFO: "[INFO]",
}


class SentinelDoctorDialog(gui.GeDialog):
    """Modal environment self-diagnostic (feature I6).

    ALL logic lives in ``sentinel.doctor`` — this dialog only renders the item
    list and exposes a copyable diagnostic block. Copy strategy: a read-only
    multiline edit field shows the full report AND a "Copy to Clipboard" button
    calls ``c4d.CopyStringToClipboard`` (belt and suspenders — the field lets the
    user select/scroll, the button is the one-click path). The optional update
    check is a separate button (never automatic) that appends its result.
    """

    GRP_ITEMS = 3001
    TXT_REPORT = 3002
    BTN_COPY = 3003
    BTN_UPDATE = 3004
    BTN_CLOSE = 3005

    def __init__(self):
        super().__init__()
        try:
            self._items, self._meta = doctor.run_all_diagnostics()
        except Exception as exc:
            safe_print("Sentinel Doctor failed to run diagnostics: %s" % exc)
            self._items, self._meta = [], {}

    def _report_text(self):
        return doctor.build_copyable_report(self._items, self._meta)

    def _build_item_rows(self):
        if not self._items:
            self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                               "No diagnostics available.", 0)
            return
        for it in self._items:
            tag = _DOCTOR_STATUS_TAG.get(it.get("status"), "[??]")
            label = it.get("label", "")
            self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                               "%s  %s" % (tag, label), 0)
            detail = it.get("detail")
            if detail:
                self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                                   "        %s" % detail, 0)
            hint = it.get("hint")
            if hint and it.get("status") in (doctor.WARN, doctor.FAIL):
                self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                                   "        ↳ %s" % hint, 0)

    def CreateLayout(self):
        self.SetTitle("Sentinel Doctor")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(12, 10, 12, 10)
        self.GroupSpace(0, 6)

        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "▸ Environment diagnostic", 0)

        # Item rows live in a flushable group so "Check for Updates" can re-render.
        self.GroupBegin(self.GRP_ITEMS, c4d.BFH_SCALEFIT, 1, 0)
        self._build_item_rows()
        self.GroupEnd()

        self.AddSeparatorH(8)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "Copy the block below into a GitHub bug report:", 0)

        multiline_flags = c4d.DR_MULTILINE_READONLY | c4d.DR_MULTILINE_MONOSPACED
        self.AddMultiLineEditText(self.TXT_REPORT,
                                  c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                                  0, 200, multiline_flags)

        self.AddSeparatorH(10)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupSpace(8, 0)
        self.AddButton(self.BTN_COPY, c4d.BFH_LEFT, 160, 0, "Copy to Clipboard")
        self.AddButton(self.BTN_UPDATE, c4d.BFH_LEFT, 160, 0, "Check for Updates")
        self.AddButton(self.BTN_CLOSE, c4d.BFH_RIGHT, 100, 0, "Close")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        self.SetString(self.TXT_REPORT, self._report_text())
        return True

    def Command(self, cid, msg):
        if cid == self.BTN_COPY:
            try:
                c4d.CopyStringToClipboard(self._report_text())
                gui.MessageDialog("Diagnostic copied to clipboard.")
            except Exception as exc:
                safe_print("Copy to clipboard failed: %s" % exc)
                gui.MessageDialog("Could not copy to clipboard — select the text "
                                  "manually and copy it.")
            return True

        if cid == self.BTN_UPDATE:
            item = doctor.check_for_update(
                current_version=self._meta.get("sentinel_version"))
            # Replace any prior update item, then re-render rows + report.
            self._items = [i for i in self._items if i.get("id") != "update"]
            self._items.append(item)
            self.LayoutFlushGroup(self.GRP_ITEMS)
            self._build_item_rows()
            self.LayoutChanged(self.GRP_ITEMS)
            self.SetString(self.TXT_REPORT, self._report_text())
            gui.MessageDialog("%s\n\n%s" % (item.get("detail", ""),
                                            item.get("hint", "")))
            return True

        if cid == self.BTN_CLOSE:
            self.Close()
            return True

        return True


class SupervisorDialog(gui.GeDialog):
    """Modal folder-QC aggregator (feature I5-A).

    ALL logic lives in ``sentinel.supervisor`` — this dialog only picks a folder,
    renders the aggregated per-shot table + trajectories into a read-only
    monospaced field (the Doctor pattern), and exports one self-contained HTML
    file. No scene is ever opened; sidecars on disk are the only data source.
    """

    BTN_SCAN = 3101
    BTN_EXPORT = 3102
    BTN_CLOSE = 3103
    TXT_REPORT = 3104
    LABEL_FOLDER = 3105

    _LAST_FOLDER_KEY = "supervisor_last_folder"

    def __init__(self):
        super().__init__()
        self._folder = GlobalSettings.get(self._LAST_FOLDER_KEY, "") or ""
        self._shots = []
        self._meta = {}

    def _report_text(self):
        if not self._meta:
            return ("Pick a project folder and press \"Scan Folder...\".\n\n"
                    "Sentinel aggregates every scene's version/notes sidecars "
                    "without opening any .c4d file.")
        return supervisor.build_supervisor_report(self._shots, self._meta)

    def CreateLayout(self):
        self.SetTitle("Sentinel Supervisor")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(12, 10, 12, 10)
        self.GroupSpace(0, 6)

        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "▸ Folder QC — aggregate every scene's sidecars", 0)
        self.AddStaticText(self.LABEL_FOLDER, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        self.AddSeparatorH(6)
        multiline_flags = c4d.DR_MULTILINE_READONLY | c4d.DR_MULTILINE_MONOSPACED
        self.AddMultiLineEditText(self.TXT_REPORT,
                                  c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
                                  0, 320, multiline_flags)

        self.AddSeparatorH(10)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 3, 0)
        self.GroupSpace(8, 0)
        self.AddButton(self.BTN_SCAN, c4d.BFH_LEFT, 150, 0, "Scan Folder...")
        self.AddButton(self.BTN_EXPORT, c4d.BFH_LEFT, 150, 0, "Export HTML...")
        self.AddButton(self.BTN_CLOSE, c4d.BFH_RIGHT, 100, 0, "Close")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        self._refresh_folder_label()
        self.SetString(self.TXT_REPORT, self._report_text())
        return True

    def _refresh_folder_label(self):
        label = ("Folder: %s" % self._folder) if self._folder else "No folder selected."
        self.SetString(self.LABEL_FOLDER, label)

    def _scan(self):
        try:
            self._shots, self._meta = supervisor.scan_folder(self._folder)
        except Exception as exc:
            safe_print("Supervisor scan failed: %s" % exc)
            gui.MessageDialog("Could not scan the folder:\n%s" % exc)
            return
        self.SetString(self.TXT_REPORT, self._report_text())
        warnings = self._meta.get("warnings") or []
        if not self._shots and not warnings:
            gui.MessageDialog(
                "No scene sidecars found in this folder.\n\n"
                "Save a version from the Versions tab (or point the scan at a "
                "folder that contains versioned scenes) to populate this view.")

    def Command(self, cid, msg):
        if cid == self.BTN_SCAN:
            chosen = c4d.storage.LoadDialog(
                title="Select project folder to scan",
                flags=c4d.FILESELECT_DIRECTORY,
            )
            if chosen:
                self._folder = chosen
                GlobalSettings.set(self._LAST_FOLDER_KEY, chosen)
                self._refresh_folder_label()
                self._scan()
            return True

        if cid == self.BTN_EXPORT:
            if not self._meta:
                gui.MessageDialog("Scan a folder first, then export.")
                return True
            default_name = supervisor.DEFAULT_EXPORT_NAME
            try:
                save_path = c4d.storage.SaveDialog(
                    title="Export Supervisor HTML",
                    force_suffix="html",
                    def_file=default_name,
                )
            except TypeError:
                save_path = c4d.storage.SaveDialog(
                    title="Export Supervisor HTML",
                    force_suffix="html",
                )
            if not save_path:
                return True
            try:
                written = supervisor.write_supervisor_html(
                    self._shots, self._meta, save_path)
            except Exception as exc:
                safe_print("Supervisor HTML export failed: %s" % exc)
                gui.MessageDialog("Could not write the HTML export:\n%s" % exc)
                return True
            try:
                c4d.storage.ShowInFinder(written)
            except Exception:
                pass
            gui.MessageDialog("Supervisor report exported:\n\n%s" % written)
            return True

        if cid == self.BTN_CLOSE:
            self.Close()
            return True

        return True
