# -*- coding: utf-8 -*-
"""Sentinel UI widget IDs."""

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


class GateTriageIds:
    """Widget ID ranges for the modal quality-gate triage dialog."""

    BTN_PROCEED = 2001
    BTN_CANCEL = 2002
    EDT_REASON = 2003
    TXT_SUMMARY = 2004

    FIX_BASE = 2100
    OVERRIDE_BASE = 2200
    BASELINE_BASE = 2300
