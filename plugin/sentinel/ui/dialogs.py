# -*- coding: utf-8 -*-
"""Sentinel modal and async dialogs."""

import os
import re

import c4d
from c4d import gui

from sentinel import assets as assets_engine
from sentinel import baseline
from sentinel import doctor
from sentinel import gate as quality_gate
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
    LABEL_SNAP_DIR = 1012
    LABEL_SNAP_DIR_HINT = 1013

    # FPS choices in the combo
    FPS_OPTIONS = [24, 25, 30, 60]
    HISTORY_OPTIONS = [5, 10, 20]
    COMP_OPTIONS = ["Nuke", "After Effects"]

    def __init__(self):
        super().__init__()
        self.confirmed = False
        self._standard_fps_overridden = False
        self._snap_dir_overridden = False

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
        self.AddStaticText(self.LABEL_SNAP_DIR, c4d.BFH_LEFT, 0, 0, "RS Snapshot directory:", 0)
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddEditText(self.EDT_SNAP_DIR, c4d.BFH_SCALEFIT, 0, 0)
        self.AddButton(self.BTN_BROWSE_DIR, c4d.BFH_RIGHT, 80, 0, "Browse...")
        self.GroupEnd()
        # Populated in InitValues only when auto-detect succeeds (IA
        # consolidation, Phase 3) — empty otherwise, no layout gap either way.
        self.AddStaticText(self.LABEL_SNAP_DIR_HINT, c4d.BFH_SCALEFIT, 0, 0, "", 0)

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

        # Snapshot dir — auto-detect (RenderView's redshift_rv.cfg) takes
        # precedence over the manual value (IA consolidation, Phase 3);
        # mirrors the Standard FPS / project-rules override pattern above.
        # Local import: sentinel.ui.flows imports sentinel.ui.dialogs at
        # module level (GateTriageDialog), so importing flows at module
        # level here would be circular.
        try:
            from sentinel.ui.flows import detect_rv_snapshot_dir
            detected_snap_dir = detect_rv_snapshot_dir()
        except Exception:
            detected_snap_dir = None
        self._snap_dir_overridden = bool(detected_snap_dir)
        if self._snap_dir_overridden:
            self.SetString(self.EDT_SNAP_DIR, detected_snap_dir)
            self.SetString(
                self.LABEL_SNAP_DIR_HINT,
                "↳ auto-detected from RenderView — manual value used only as fallback",
            )
            try:
                self.Enable(self.EDT_SNAP_DIR, False)
                self.Enable(self.BTN_BROWSE_DIR, False)
            except Exception:
                pass
        else:
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

                # Snapshot dir — disabled (auto-detected) means the field
                # shows the detected path, not the manual fallback; don't
                # overwrite the fallback value with it (mirrors Standard FPS).
                if not self._snap_dir_overridden:
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
                "Save a version from the Deliver tab (or point the scan at a "
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
