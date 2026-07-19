# -*- coding: utf-8 -*-
"""Sentinel UI widget IDs."""

# Deterministic per-check QC action button IDs, derived from the registry index.
# id = QC_ACTION_BASE + index*4 + slot. Slots: select=0, info=1, fix=2 (slot 3
# reserved/unused). With 12 checks this spans 1400..1446 — verified collision-free
# against every G / GateTriageIds id below.
QC_ACTION_BASE = 1400
_QC_ACTION_SLOTS = {"select": 0, "info": 1, "fix": 2}
_QC_SLOT_ACTIONS = {slot: action for action, slot in _QC_ACTION_SLOTS.items()}


def qc_action_id(index, action):
    """Return the widget id for the (row index, action) QC button."""
    slot = _QC_ACTION_SLOTS.get(action)
    if slot is None:
        raise ValueError(f"Unknown QC action: {action}")
    return QC_ACTION_BASE + index * 4 + slot


def decode_qc_action(cid):
    """Inverse of qc_action_id: (index, action) or None for non-QC-action ids."""
    if not isinstance(cid, int) or isinstance(cid, bool):
        return None
    offset = cid - QC_ACTION_BASE
    if offset < 0:
        return None
    index, slot = divmod(offset, 4)
    action = _QC_SLOT_ACTIONS.get(slot)
    if action is None:
        return None
    return (index, action)


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

    # Per-check QC action buttons are no longer hand-numbered — they are
    # generated from the registry via qc_action_id()/decode_qc_action() above.

    # Export
    BTN_EXPORT_QC = 1150
    BTN_OPEN_QC_REPORT = 1316  # QC tab: open the Reports QC page (Phase 2 Task 3)

    # Render preset
    PRESET_DROPDOWN = 1002
    LABEL_RESOLUTION = 1170
    BTN_FORCE_VERTICAL = 1204  # Force 9:16
    BTN_RESET_ALL = 1206      # Reset all presets from template
    BTN_ADD_FRAME_TAG = 1214  # Add Sentinel Frame tag to the active/selected camera (v1.8.0)
    BTN_VALIDATE_RENDER = 1215  # Post-render validation (U7)

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
    BTN_INFO_AOVS = 1155
    BTN_LIGHT_GROUPS = 1158
    BTN_FORCE_ESSENTIALS = 1156
    BTN_FORCE_PRODUCTION = 1157
    BTN_APPLY_MULTIPART = 1159   # Render tab: flip Multi-Part EXR on the LIVE scene
    # 1160 (BTN_SET_SNAPSHOT_DIR) retired in Phase 3 IA consolidation — Browse
    # now lives only in Settings; the panel caption is read-only.
    LABEL_SNAPSHOT_DIR = 1161
    BTN_GITHUB = 1306
    BTN_BUG_REPORT = 1307
    BTN_SETTINGS = 1308
    LABEL_AOV_INFO = 1309   # read-only summary of comp + multi-part in Render tab
    BTN_TEXTURE_REPATH = 1310  # Tools tab: open Texture Repathing dialog (v1.5.7)
    BTN_DOCTOR = 1311  # Footer: open Sentinel Doctor self-diagnostic (I6)
    BTN_SUPERVISOR = 1312  # Deliver tab: open Supervisor folder QC aggregator (I5-A)
    BTN_DELIVERY_SUMMARY = 1313  # Deliver tab: Delivery Summary + receiver-side verify (I4)
    CHK_SNAPSHOT_WATCH = 1314  # Render tab: toggle snapshot watchfolder auto-convert
    LABEL_SNAPSHOT_WATCH = 1315  # Render tab: auto-convert status/alert caption
    BTN_COMMAND_PALETTE = 1316  # Help menu: open the Sentinel Command Palette (Phase 4 Task 4)


class GateTriageIds:
    """Widget ID ranges for the modal quality-gate triage dialog."""

    BTN_PROCEED = 2001
    BTN_CANCEL = 2002
    EDT_REASON = 2003
    TXT_SUMMARY = 2004

    FIX_BASE = 2100
    OVERRIDE_BASE = 2200
    BASELINE_BASE = 2300
