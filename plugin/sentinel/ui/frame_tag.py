# -*- coding: utf-8 -*-
"""Sentinel Frame camera tag registration and viewport drawing surface."""

import hashlib
import json

import c4d
from c4d import plugins

from sentinel import framing
from sentinel.multiformat import (
    MULTIFORMAT_DEFS,
    compute_format_output_path,
    generate_multiformat_takes,
    get_multiformat_def,
)
from sentinel.safe_areas import (
    SAFE_AREA_INSETS,
    format_safe_area_in_master_ndc,
    is_object_marked_safe_area,
    mark_object_safe_area,
    resolve_take_projection_params,
    unmark_object_safe_area,
)
SENTINEL_FRAME_TAG_PLUGIN_ID = 2099073
SENTINEL_FRAME_TAG_DESCRIPTION = "Tsentinelframe"
SCHEMA_VERSION = 1

OCAMERA = 5103
ORSCAMERA = 1057516

# Core params: 1000s.
ID_GROUP_CORE = 1000
ID_ENABLED = 1001
ID_COMPOSITION = 1002
ID_SHOW_GUIDES = 1003
ID_SHOW_MASK = 1004
ID_SHOW_PLATFORM = 1005
ID_SHOW_HUD = 1006
ID_SCHEMA_VERSION = 1007
ID_MASK_OPACITY = 1008
# Frame v2 (control strip). 1009+ continue the stable-ID discipline: existing
# ids above keep their meaning forever; new params get fresh ids.
ID_VIEWING = 1009          # LONG cycle: 0=Master, i+1 = _format_defs()[i]
ID_SYNC_STATUS = 1010      # STRING, read-only derived (never stored)
ID_LINE_WIDTH = 1011       # REAL, guide line width (Task 5 wires into Draw)
ID_LINE_OPACITY = 1012     # REAL 0..1
ID_DIM_NONVIEWED = 1013    # REAL 0..1 — focus dimming for non-viewed formats

# Frame v2 tab groups (top-level DTYPE_GROUPs render as AM tabs).
ID_GROUP_MAIN = 900
ID_GROUP_DISPLAY = 901
ID_GROUP_ADVANCED = 902
ID_GROUP_FORMATS = 903     # sub-group of Main holding the per-format rows

# Per-format params: 1100s+, fixed stride per MULTIFORMAT_DEFS entry.
ID_FORMAT_BASE = 1100
ID_FORMAT_STRIDE = 20

# Frame v2.1 (custom ratio + render slices). Row indexes: 0..4 follow
# MULTIFORMAT_DEFS order, 5 = the Custom row. The custom row's `enabled`
# defaults to False everywhere (v1.28 scenes must not sprout a custom
# format); standard rows keep default True — see _row_enabled.
FORMAT_ROW_COUNT = 6
CUSTOM_FORMAT_INDEX = 5
CUSTOM_FORMAT_ID = "custom"
ID_GROUP_CUSTOM = 904            # 8-column sub-grid under the formats grid
# Slice take BaseLinks. Base sits above ALL declared description ids (the
# highest is ID_MARK_SUBJECT = 3004) so that 6 rows x 256 ordinals — ids
# 10000..11535 (10000 + 5*256 + 255) — can never collide with a real
# description field, however many rows/ordinals grow. id = 10000 +
# row_index*256 + (ordinal-1).
ID_PRIVATE_SLICE_LINK_BASE = 10000
MAX_SLICE_ORDINALS = 256
VIEWING_SLICE_STRIDE = 1000        # ID_VIEWING encoding for slices (Task 5)

# Private per-format platform insets: stored on the tag container so Draw can
# stay read-only and avoid resolving sentinel_rules.json on the draw thread.
ID_PLATFORM_INSET_BASE = 2000
ID_PLATFORM_INSET_STRIDE = 10

# Private tag-owned state. These are intentionally not in the dynamic AM
# description: they are implementation details for U5 tracking/staleness.
ID_PRIVATE_TAKE_LINK_BASE = 2400
ID_PRIVATE_TAKE_LINK_STRIDE = 1
ID_PRIVATE_TAKES_SIGNATURE = 2500
# Last takes-signature OBSERVED by the POSTSETPARAMETER hook (Frame v2
# auto-sync). Distinct from 2500 (signature of the last GENERATED takes):
# 2501 exists so the hook only requests a sync when the takes-relevant
# signature actually changed — display toggles leave it untouched, and a
# fresh tag / v1.8.0 scene seeds it silently on first touch (adoption)
# instead of regenerating takes just because the AM was poked.
ID_PRIVATE_LAST_SEEN_SIGNATURE = 2501
# Focus format for the viewport dimming (Frame v2): format INDEX + 1 of the
# last per-format row the artist touched in the AM (0 = no focus, all guides
# full intensity). Touching any non-row param (display toggles, Enabled,
# composition) clears it — the natural "back to all-equal" gesture. Private
# container data so Draw can read it on the cloned draw thread.
ID_PRIVATE_FOCUS_FORMAT = 2502

# Actions: 3000s. Declared only in U2; command logic is U5.
ID_GROUP_ACTIONS = 3000
ID_CREATE_UPDATE_TAKES = 3001
ID_SET_OUTPUT = 3002
ID_REMOVE_STALE = 3003
ID_MARK_SUBJECT = 3004

# Crop is the default: a true inscribed crop that matches the viewport guides
# exactly (WYSIWYG) on BOTH standard C4D cameras and native Redshift cameras
# (ORSCAMERA) — each camera type has its own parameter namespace, so the
# writer scales the type's own sensor lever (APERTURE for Ocamera, SENSOR_SIZE
# for ORSCAMERA) and pans with that type's own gate-relative offset
# (FILM_OFFSET for Ocamera, SENSOR_SHIFT for ORSCAMERA — Ocamera's ids are
# inert on ORSCAMERA, a confirmed production bug). Focal length is untouched
# by either lever, so DOF/zoom are intact. See
# docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md.
# "None" leaves the camera alone (C4D keeps horizontal FOV; narrower formats
# EXTEND vertically rather than crop, so guides are only a reference there).
# The legacy focal/resize modes are kept as constants for back-compat mapping
# but are intentionally NOT offered in the cycle (they broke WYSIWYG).
COMPOSITION_CROP = 0
COMPOSITION_OFF = 1
COMPOSITION_PRESERVE_VERTICAL = 2
COMPOSITION_PRESERVE_HORIZONTAL = 3
COMPOSITION_RESIZE_CANVAS = 4

COMPOSITION_CYCLE = (
    (COMPOSITION_CROP, "Crop to Guides (default)"),
    (COMPOSITION_OFF, "None (camera unchanged)"),
)

COMPOSITION_MODE_TO_FRAMING = {
    COMPOSITION_CROP: "crop",
    COMPOSITION_OFF: "none",
    COMPOSITION_PRESERVE_VERTICAL: framing.COMPENSATE_PRESERVE_VERTICAL,
    COMPOSITION_PRESERVE_HORIZONTAL: framing.COMPENSATE_PRESERVE_HORIZONTAL,
    COMPOSITION_RESIZE_CANVAS: "resize_canvas",
}

_DRAW_CALLS = 0
PLATFORM_SAFE_AREA_AS_OF = "2026-07"
MASK_TRANSPARENCY = -128

_FORMAT_COLORS = {
    "16x9": (0.95, 0.95, 0.95),
    "9x16": (0.95, 0.55, 0.15),
    "1x1": (0.50, 0.85, 0.95),
    "4x5": (0.85, 0.35, 0.85),
    "21x9": (0.95, 0.85, 0.20),
    "custom": (0.35, 0.95, 0.55),
}


def is_valid_camera_host(obj_type_int):
    """Return True when ``obj_type_int`` is a supported camera type id."""
    return int(obj_type_int or 0) in (OCAMERA, ORSCAMERA)


def _format_defs(node=None):
    """Canonical defs — the 5 standard entries plus, when ``node`` is given
    and its Custom row is enabled, a FRESH custom def dict (v1.29). The
    standard entries are the shared MULTIFORMAT_DEFS dicts and must never be
    mutated; the custom def is rebuilt per call from the tag params."""
    defs = []
    for fmt in MULTIFORMAT_DEFS:
        canonical = get_multiformat_def(fmt.get("id"))
        if canonical:
            defs.append(canonical)
    if node is not None:
        custom = _custom_def_from_params(node)
        if custom is not None:
            defs.append(custom)
    return defs


def _custom_def_from_params(node):
    ids = _format_ids(CUSTOM_FORMAT_INDEX)
    if not _as_bool(_get_node_value(node, ids["enabled"], False), False):
        return None
    width = max(16, _as_int(_get_node_value(node, ids["width"], 1920), 1920))
    height = max(16, _as_int(_get_node_value(node, ids["height"], 1080), 1080))
    return {"id": CUSTOM_FORMAT_ID, "label": "Custom",
            "width": width, "height": height}


def _row_enabled(node, index):
    """Per-row enabled with the migration-safe default: standard rows (0-4)
    default True (v1.8.0 behavior), the Custom row defaults False (a v1.28
    tag with no stored custom params must NOT sprout a custom format)."""
    default = index != CUSTOM_FORMAT_INDEX
    return _as_bool(_get_node_value(node, _format_ids(index)["enabled"], default), default)


def _format_ids(index):
    base = ID_FORMAT_BASE + (index * ID_FORMAT_STRIDE)
    return {
        "group": base,
        "enabled": base + 1,
        "color": base + 2,
        "nudge_x": base + 3,
        "nudge_y": base + 4,
        "slice_x": base + 5,
        "slice_y": base + 6,
        "width": base + 7,   # custom row only
        "height": base + 8,  # custom row only
    }


def _slices_for_index(node, index):
    """Effective slice grid for a format row. Returns (1, 1) whenever the
    tag's composition mode is not Crop: slices are a tiling of the CROP
    window, and in "None" mode the camera is never cropped, so a slice
    window is meaningless — the engine applies the exact same rule
    (multiformat degrades slice grids to 1x1 outside Crop mode and creates
    the whole-format take). Neutralizing here, at the single choke point,
    keeps `_engine_format_defs`, `_expected_take_names`,
    `_viewing_entry_pairs`, `_total_slice_count`,
    `_params_payload_for_takes` and Draw coherent with what the engine
    actually generates (otherwise `_prune_orphaned_takes` inside the same
    `run_full_sync` would delete the freshly created whole-format take),
    and stops the takes signature churning on Sx/Sy edits in None mode."""
    if composition_mode_for_engine(
        _get_node_value(node, ID_COMPOSITION, COMPOSITION_CROP)
    ) != "crop":
        return (1, 1)
    ids = _format_ids(index)
    sx = max(1, min(16, _as_int(_get_node_value(node, ids["slice_x"], 1), 1)))
    sy = max(1, min(16, _as_int(_get_node_value(node, ids["slice_y"], 1), 1)))
    return (sx, sy)


def _engine_format_defs(node):
    """Resolved defs for the multiformat engine: enabled formats only is NOT
    the contract here — the engine filters by options['formats']; this returns
    ALL per-tag defs (5 standard + custom-if-enabled) as shallow copies with
    the per-row slice grid injected."""
    out = []
    for index, fmt in enumerate(_format_defs(node)):
        d = dict(fmt)
        d["slices"] = _slices_for_index(node, index)
        out.append(d)
    return out


def _total_slice_count(node):
    total = 0
    for index, fmt in enumerate(_format_defs(node)):
        if not _row_enabled(node, index):
            continue
        sx, sy = _slices_for_index(node, index)
        if sx * sy > 1:
            total += sx * sy
    return total


def _format_param_map():
    # Covers all 6 rows and every per-row param regardless of custom state
    # (it gates AM enabling), so it is built from the row count, not defs.
    mapping = {}
    for index in range(FORMAT_ROW_COUNT):
        ids = _format_ids(index)
        for key in ("color", "nudge_x", "nudge_y", "slice_x", "slice_y",
                    "width", "height"):
            mapping[ids[key]] = ids["enabled"]
    return mapping


_FORMAT_PARAM_TO_ENABLE = _format_param_map()
_ACTION_IDS = {
    ID_CREATE_UPDATE_TAKES,
    ID_SET_OUTPUT,
    ID_REMOVE_STALE,
    ID_MARK_SUBJECT,
}


def _node_type(obj):
    if obj is None:
        return 0
    try:
        return int(obj.GetType())
    except Exception:
        return 0


def _tag_host(tag):
    try:
        return tag.GetObject()
    except Exception:
        return None


def _host_is_valid_camera(tag):
    return is_valid_camera_host(_node_type(_tag_host(tag)))


def _desc_level_id(cid):
    try:
        return int(cid[0].id)
    except Exception:
        try:
            return int(cid)
        except Exception:
            return 0


def _set_bc_value(bc, method_name, key, value):
    method = getattr(bc, method_name, None)
    if callable(method):
        method(key, value)
    else:
        try:
            bc[key] = value
        except Exception:
            pass


def _set_node_value(node, param_id, value):
    try:
        node[param_id] = value
    except Exception:
        try:
            node.SetParameter(param_id, value, c4d.DESCFLAGS_SET_0)
        except Exception:
            pass


def _get_node_value(node, param_id, default=None):
    try:
        return node[param_id]
    except Exception:
        try:
            return node.GetParameter(param_id, c4d.DESCFLAGS_GET_0)
        except Exception:
            return default


def _as_bool(value, default=False):
    if value is None:
        return bool(default)
    return bool(value)


def _as_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def _vector(rgb):
    try:
        return c4d.Vector(float(rgb[0]), float(rgb[1]), float(rgb[2]))
    except Exception:
        return rgb


def _color_vector(value, fallback):
    try:
        return c4d.Vector(float(value.x), float(value.y), float(value.z))
    except Exception:
        return fallback


def _dim_color(color, factor=0.58):
    try:
        return c4d.Vector(
            max(0.0, min(1.0, float(color.x) * factor)),
            max(0.0, min(1.0, float(color.y) * factor)),
            max(0.0, min(1.0, float(color.z) * factor)),
        )
    except Exception:
        return color


def _node_creator_type(node):
    try:
        return node.GetType()
    except Exception:
        return SENTINEL_FRAME_TAG_PLUGIN_ID


def _description_parent(param_id, dtype, node):
    return c4d.DescID(c4d.DescLevel(param_id, dtype, _node_creator_type(node)))


def _doc_from_node(node):
    getter = getattr(node, "GetDocument", None)
    if callable(getter):
        try:
            doc = getter()
            if doc is not None:
                return doc
        except Exception:
            pass
    try:
        return c4d.documents.GetActiveDocument()
    except Exception:
        return None


from sentinel.rules_context import active_rules_for_doc as _active_rules_for_doc


def _is_main_thread():
    threading_module = getattr(c4d, "threading", None)
    checker = getattr(threading_module, "GeIsMainThread", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    checker = getattr(c4d, "GeIsMainThread", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return True


def _master_aspect_for_doc(doc):
    aspect = None
    try:
        td = doc.GetTakeData()
        main_take = td.GetMainTake() if td is not None else None
        params = resolve_take_projection_params(main_take, td, doc)
        aspect = params.get("aspect") if params else None
    except Exception:
        aspect = None
    if aspect is None or aspect <= 0:
        try:
            rd = doc.GetActiveRenderData()
            w = int(rd[c4d.RDATA_XRES])
            h = int(rd[c4d.RDATA_YRES])
            aspect = float(w) / float(h) if h > 0 else None
        except Exception:
            aspect = None
    return float(aspect) if aspect and aspect > 0 else (16.0 / 9.0)


def _enabled_format_entries(node):
    entries = []
    for index, fmt in enumerate(_format_defs(node)):
        ids = _format_ids(index)
        if not _as_bool(_get_node_value(node, ids["enabled"], True), True):
            continue
        fmt_id = fmt.get("id")
        fallback = _vector(_FORMAT_COLORS.get(fmt_id, (0.6, 0.6, 0.6)))
        color = _color_vector(_get_node_value(node, ids["color"], fallback), fallback)
        nudge = (
            _as_float(_get_node_value(node, ids["nudge_x"], 0.0), 0.0),
            _as_float(_get_node_value(node, ids["nudge_y"], 0.0), 0.0),
        )
        entries.append((index, fmt, color, nudge))
    return entries


def _format_inset_ids(index):
    base = ID_PLATFORM_INSET_BASE + (index * ID_PLATFORM_INSET_STRIDE)
    return {
        "top": base,
        "bottom": base + 1,
        "left": base + 2,
        "right": base + 3,
    }


def _format_take_link_id(index):
    return ID_PRIVATE_TAKE_LINK_BASE + (index * ID_PRIVATE_TAKE_LINK_STRIDE)


def _format_index_for_id(fmt_id, node=None):
    for index, fmt in enumerate(_format_defs(node)):
        if fmt.get("id") == fmt_id:
            return index
    # The custom row keeps its link slots addressable even while DISABLED
    # (its def drops out of _format_defs, but prune must still clear the
    # stored take links of a now-disabled custom row).
    if fmt_id == CUSTOM_FORMAT_ID:
        return CUSTOM_FORMAT_INDEX
    return None


def composition_mode_for_engine(composition_id):
    """Map the tag LONG cycle value to the multiformat engine mode string."""
    try:
        mode_id = int(composition_id)
    except Exception:
        mode_id = COMPOSITION_CROP
    return COMPOSITION_MODE_TO_FRAMING.get(mode_id, "crop")


def _enabled_format_ids_from_params(node):
    """Return enabled format ids in canonical UI order."""
    enabled = []
    for index, fmt in enumerate(_format_defs(node)):
        ids = _format_ids(index)
        if _as_bool(_get_node_value(node, ids["enabled"], True), True):
            enabled.append(fmt.get("id"))
    return enabled


def _film_offsets_from_params(node):
    """Build the engine film_offsets dict from enabled per-format nudges."""
    offsets = {}
    for index, fmt in enumerate(_format_defs(node)):
        ids = _format_ids(index)
        if not _as_bool(_get_node_value(node, ids["enabled"], True), True):
            continue
        offsets[fmt.get("id")] = (
            _as_float(_get_node_value(node, ids["nudge_x"], 0.0), 0.0),
            _as_float(_get_node_value(node, ids["nudge_y"], 0.0), 0.0),
        )
    return offsets


def _params_payload_for_takes(node):
    """Return the stable, pure payload that defines generated take freshness."""
    formats = []
    for index, fmt in enumerate(_format_defs(node)):
        ids = _format_ids(index)
        if not _as_bool(_get_node_value(node, ids["enabled"], True), True):
            continue
        entry = {
            "id": fmt.get("id"),
            "nudge": [
                round(_as_float(_get_node_value(node, ids["nudge_x"], 0.0), 0.0), 8),
                round(_as_float(_get_node_value(node, ids["nudge_y"], 0.0), 0.0), 8),
            ],
            "slices": list(_slices_for_index(node, index)),
        }
        if fmt.get("id") == CUSTOM_FORMAT_ID:
            entry["size"] = [int(fmt.get("width", 0)), int(fmt.get("height", 0))]
        formats.append(entry)
    return {
        "composition_mode": composition_mode_for_engine(
            _get_node_value(node, ID_COMPOSITION, COMPOSITION_CROP)
        ),
        "formats": formats,
    }


def _params_signature_for_takes(node):
    """Hash enabled formats, nudges and composition mode for staleness checks."""
    raw = json.dumps(_params_payload_for_takes(node), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _selected_output_format_id(node):
    """Return the v1 Set Output target: the first enabled format."""
    enabled = _enabled_format_ids_from_params(node)
    return enabled[0] if enabled else None


def _node_data_container(node):
    getter = getattr(node, "GetDataInstance", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return node if isinstance(node, dict) else None


def _bc_get_data(bc, key):
    if bc is None:
        return None
    getter = getattr(bc, "GetData", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            return None
    try:
        return bc[key] if key in bc else None
    except Exception:
        return None


def _bc_set_data(bc, key, value):
    if bc is None:
        return False
    setter = getattr(bc, "SetData", None)
    if callable(setter):
        try:
            setter(key, value)
            return True
        except Exception:
            pass
    try:
        bc[key] = value
        return True
    except Exception:
        return False


def _bc_set_string(bc, key, value):
    if bc is None:
        return False
    setter = getattr(bc, "SetString", None)
    if callable(setter):
        try:
            setter(key, str(value))
            return True
        except Exception:
            pass
    return _bc_set_data(bc, key, str(value))


def _bc_set_float(bc, key, value):
    if bc is None:
        return
    setter = getattr(bc, "SetFloat", None)
    if callable(setter):
        try:
            setter(key, float(value))
            return
        except Exception:
            pass
    setter = getattr(bc, "SetData", None)
    if callable(setter):
        try:
            setter(key, float(value))
            return
        except Exception:
            pass
    try:
        bc[key] = float(value)
    except Exception:
        pass


def _coerce_insets(insets, fallback=None):
    source = insets or fallback or {}
    return {
        "top": _as_float(source.get("top"), 0.0),
        "bottom": _as_float(source.get("bottom"), 0.0),
        "left": _as_float(source.get("left"), 0.0),
        "right": _as_float(source.get("right"), 0.0),
    }


def _row_format_id(index):
    """Row index -> format id for all 6 rows (custom has no MULTIFORMAT def)."""
    if index < len(MULTIFORMAT_DEFS):
        return MULTIFORMAT_DEFS[index]["id"]
    return CUSTOM_FORMAT_ID


def _standard_platform_insets_by_format():
    # All 6 rows: custom insets default to zeros (SAFE_AREA_INSETS has no
    # "custom" key, so .get() -> None -> _coerce_insets zeros).
    return {
        _row_format_id(index): _coerce_insets(
            SAFE_AREA_INSETS.get(_row_format_id(index)), None
        )
        for index in range(FORMAT_ROW_COUNT)
    }


def _resolved_platform_insets_by_format(doc):
    insets_by_format = _standard_platform_insets_by_format()
    try:
        rules_context = _active_rules_for_doc(doc)
        rule_insets = rules_context.params.get("safe_area_insets", {})
    except Exception:
        rule_insets = {}
    for fmt_id, fallback in list(insets_by_format.items()):
        insets_by_format[fmt_id] = _coerce_insets(rule_insets.get(fmt_id), fallback)
    return insets_by_format


def _write_platform_insets_to_node(node, insets_by_format):
    bc = _node_data_container(node)
    if bc is None:
        return False
    changed = False
    for index in range(FORMAT_ROW_COUNT):
        fmt_id = _row_format_id(index)
        insets = _coerce_insets((insets_by_format or {}).get(fmt_id), SAFE_AREA_INSETS.get(fmt_id))
        for side, param_id in _format_inset_ids(index).items():
            value = float(insets[side])
            old = _bc_get_data(bc, param_id)
            try:
                same = old is not None and abs(float(old) - value) <= 1e-9
            except Exception:
                same = False
            if not same:
                changed = True
            _bc_set_float(bc, param_id, value)
    return changed


def _refresh_platform_insets(node):
    if node is None or not _is_main_thread():
        return False
    return _write_platform_insets_to_node(node, _resolved_platform_insets_by_format(_doc_from_node(node)))


class _InlineRulesContext:
    def __init__(self, insets_by_format):
        self.params = {"safe_area_insets": insets_by_format}


def _platform_insets_for_entry(node, index, fmt_id):
    bc = _node_data_container(node)
    ids = _format_inset_ids(index)
    values = {}
    for side, param_id in ids.items():
        value = _bc_get_data(bc, param_id)
        if value is None:
            return _coerce_insets(SAFE_AREA_INSETS.get(fmt_id), None)
        values[side] = _as_float(value, 0.0)
    return _coerce_insets(values, SAFE_AREA_INSETS.get(fmt_id))


def _compute_inline_rects(node, master_aspect):
    formats = []
    for index, fmt, color, nudge in _enabled_format_entries(node):
        fmt_id = fmt.get("id")
        try:
            guide = framing.crop_rect_in_master_ndc(
                fmt.get("width", 1),
                fmt.get("height", 1),
                master_aspect,
                nudge,
            )
            insets = _platform_insets_for_entry(node, index, fmt_id)
            safe_rect = format_safe_area_in_master_ndc(
                fmt_id,
                master_aspect,
                _InlineRulesContext({fmt_id: insets}),
                offset=nudge,
            )
        except Exception:
            continue
        formats.append(
            {
                "id": fmt_id,
                "label": fmt.get("label") or fmt_id,
                "width": int(fmt.get("width", 0) or 0),
                "height": int(fmt.get("height", 0) or 0),
                "color": color,
                "guide": {
                    "left": guide[0],
                    "bottom": guide[1],
                    "right": guide[2],
                    "top": guide[3],
                },
                "platform": safe_rect,
                "slices": _slices_for_index(node, index),
            }
        )
    return formats


def _master_aspect_from_safe_frame(safe_frame):
    try:
        cl, ct, cr, cb = safe_frame
        width = float(cr - cl)
        height = float(cb - ct)
        if width > 0.0 and height > 0.0:
            return width / height
    except Exception:
        pass
    return None


def _safe_frame_rect(bd):
    safe = bd.GetSafeFrame()
    if not safe:
        return None
    cl = int(safe.get("cl", 0))
    ct = int(safe.get("ct", 0))
    cr = int(safe.get("cr", 0))
    cb = int(safe.get("cb", 0))
    if cr - cl < 4 or cb - ct < 4:
        return None
    return (cl, ct, cr, cb)


def _ndc_point_to_pixels(point, safe_frame):
    cl, ct, cr, cb = safe_frame
    master_w = cr - cl
    master_h = cb - ct
    x, y = float(point[0]), float(point[1])
    return (
        cl + (x + 1.0) * 0.5 * master_w,
        ct + (1.0 - y) * 0.5 * master_h,
    )


def _ndc_rect_to_pixels(rect, safe_frame):
    left = float(rect["left"])
    right = float(rect["right"])
    bottom = float(rect["bottom"])
    top = float(rect["top"])
    px1, py1 = _ndc_point_to_pixels((left, top), safe_frame)
    px2, py2 = _ndc_point_to_pixels((right, bottom), safe_frame)
    return (px1, py1, px2, py2)


def _slice_cut_segments(guide, sx, sy, px_w, px_h):
    """Internal slice boundaries of a guide rect (NDC dict) as endpoint
    pairs. Reuses framing.slice_windows' floor-exact boundaries by passing
    the rect as (left, top, right, bottom) — linear interpolation makes the
    y-up NDC convention transparent."""
    windows = framing.slice_windows(
        (guide["left"], guide["top"], guide["right"], guide["bottom"]),
        sx, sy, px_w, px_h)
    if len(windows) <= 1:
        return []
    xs = sorted({round(w[0][0], 9) for w in windows} | {round(w[0][2], 9) for w in windows})
    ys = sorted({round(w[0][1], 9) for w in windows} | {round(w[0][3], 9) for w in windows})
    segs = []
    for x in xs[1:-1]:
        segs.append(((x, guide["top"]), (x, guide["bottom"])))
    for y in ys[1:-1]:
        segs.append(((guide["left"], y), (guide["right"], y)))
    return segs


def _intersect_ndc_rects(rects):
    rects = list(rects or [])
    if not rects:
        return None
    left = max(float(rect["left"]) for rect in rects)
    right = min(float(rect["right"]) for rect in rects)
    bottom = max(float(rect["bottom"]) for rect in rects)
    top = min(float(rect["top"]) for rect in rects)
    if right <= left or top <= bottom:
        return None
    return {"left": left, "right": right, "bottom": bottom, "top": top}


def _draw_line(bd, p1, p2, width=1):
    repeats = max(1, min(4, int(width or 1)))
    for offset in range(repeats):
        delta = float(offset) - float(repeats - 1) * 0.5
        a = c4d.Vector(p1.x + delta, p1.y, 0)
        b = c4d.Vector(p2.x + delta, p2.y, 0)
        try:
            bd.DrawLine2D(a, b)
        except Exception:
            try:
                bd.DrawLine(a, b, 0)
            except Exception:
                pass
        if repeats > 1:
            a = c4d.Vector(p1.x, p1.y + delta, 0)
            b = c4d.Vector(p2.x, p2.y + delta, 0)
            try:
                bd.DrawLine2D(a, b)
            except Exception:
                try:
                    bd.DrawLine(a, b, 0)
                except Exception:
                    pass


def _draw_rect(bd, pixel_rect, color, width=1, dashed=False):
    left, top, right, bottom = pixel_rect
    if right - left < 1.0 or bottom - top < 1.0:
        return
    bd.SetPen(color)
    points = (
        c4d.Vector(left, top, 0),
        c4d.Vector(right, top, 0),
        c4d.Vector(right, bottom, 0),
        c4d.Vector(left, bottom, 0),
    )
    edges = ((points[0], points[1]), (points[1], points[2]), (points[2], points[3]), (points[3], points[0]))
    for p1, p2 in edges:
        if dashed:
            _draw_dashed_line(bd, p1, p2, width)
        else:
            _draw_line(bd, p1, p2, width)


def _draw_color_chip(bd, x, y, size, color):
    """Small solid color swatch for the HUD legend (stacked horizontal lines
    — BaseDraw has no filled-rect primitive for this)."""
    try:
        bd.SetPen(color)
        row = 0
        while row < size:
            _draw_line(
                bd,
                c4d.Vector(x, y + row, 0),
                c4d.Vector(x + size, y + row, 0),
                2,
            )
            row += 2
    except Exception:
        pass


def _draw_dashed_line(bd, p1, p2, width=1, dash=8.0, gap=5.0):
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0.0:
        return
    step = dash + gap
    pos = 0.0
    while pos < length:
        end = min(length, pos + dash)
        a = c4d.Vector(p1.x + dx * (pos / length), p1.y + dy * (pos / length), 0)
        b = c4d.Vector(p1.x + dx * (end / length), p1.y + dy * (end / length), 0)
        _draw_line(bd, a, b, width)
        pos += step


def _draw_mask(bd, safe_frame, guide_rect, color, transparency=MASK_TRANSPARENCY):
    left, top, right, bottom = safe_frame
    gl, gt, gr, gb = guide_rect
    strips = (
        (left, top, right, gt),
        (left, gb, right, bottom),
        (left, gt, gl, gb),
        (gr, gt, right, gb),
    )
    try:
        for sl, st, sr, sb in strips:
            if sr <= sl or sb <= st:
                continue
            pts = (
                c4d.Vector(sl, st, 0),
                c4d.Vector(sr, st, 0),
                c4d.Vector(sr, sb, 0),
                c4d.Vector(sl, sb, 0),
            )
            bd.SetPen(color)
            bd.SetTransparency(transparency)
            bd.DrawPolygon(pts, (color, color, color, color))
    except Exception:
        pass
    finally:
        try:
            bd.SetTransparency(0)
        except Exception:
            pass


def _draw_hud_text(bd, x, y, text):
    try:
        bd.DrawHUDText(int(x), int(y), str(text))
    except Exception:
        pass


def _safe_node_name(node, fallback=""):
    getter = getattr(node, "GetName", None)
    if callable(getter):
        try:
            name = getter()
            if name:
                return str(name)
        except Exception:
            pass
    return str(fallback or "")


def _show_message(text):
    try:
        c4d.gui.MessageDialog(str(text))
    except Exception:
        pass


def _ask_question(text):
    try:
        return bool(c4d.gui.QuestionDialog(str(text)))
    except Exception:
        return False


def _event_add():
    try:
        c4d.EventAdd()
    except Exception:
        pass


def _undo_type_change():
    return getattr(c4d, "UNDOTYPE_CHANGE", 0)


def _undo_type_delete():
    return getattr(c4d, "UNDOTYPE_DELETE", getattr(c4d, "UNDOTYPE_DELETEOBJ", 0))


def _store_link(bc, key_id, take):
    """Shared BaseLink wrap for every take-link slot (per-format + slice)."""
    if bc is None:
        return False
    value = take
    base_link_factory = getattr(c4d, "BaseLink", None)
    if callable(base_link_factory) and take is not None:
        try:
            link = base_link_factory()
            link.SetLink(take)
            value = link
        except Exception:
            value = take
    return _bc_set_data(bc, key_id, value)


def _load_link(bc, key_id, doc=None):
    """Shared BaseLink unwrap for every take-link slot (per-format + slice)."""
    getter = getattr(bc, "GetLink", None)
    if callable(getter):
        try:
            linked = getter(key_id, doc)
            if linked is not None:
                return linked
        except Exception:
            pass
    value = _bc_get_data(bc, key_id)
    link_getter = getattr(value, "GetLink", None)
    if callable(link_getter):
        try:
            return link_getter(doc)
        except Exception:
            return None
    return value


def _write_take_link(node, fmt_id, take):
    index = _format_index_for_id(fmt_id, node)
    if index is None:
        return False
    return _store_link(_node_data_container(node), _format_take_link_id(index), take)


def _read_take_link(node, fmt_id, doc=None):
    index = _format_index_for_id(fmt_id, node)
    if index is None:
        return None
    return _load_link(_node_data_container(node), _format_take_link_id(index), doc)


def _slice_link_id(index, ordinal):
    """Slice take-link slot: 10000 + row_index*256 + (ordinal-1), 1-based
    ordinal. Disjoint from the per-format links (2400+) and the private
    signature/focus keys (2500-2502) because the base starts above them."""
    return ID_PRIVATE_SLICE_LINK_BASE + int(index) * MAX_SLICE_ORDINALS + (int(ordinal) - 1)


def _split_key(key):
    """'custom:s02' -> ('custom', 's02'); 'custom' -> ('custom', None).

    The engine NEVER emits a bare '<fmt>:' — a clamped-to-1x1 grid degrades
    to key = fmt_id with no separator (Task 3 contract)."""
    if ":" in (key or ""):
        fmt_id, _sep, sfx = key.partition(":")
        return fmt_id, sfx
    return key, None


def _ordinal_from_suffix(suffix):
    try:
        return int(str(suffix)[1:])
    except Exception:
        return None


def _write_link_for_key(node, key, take):
    """Key-based take-link writer: key = fmt_id (whole format, 2400+ slot)
    or '<fmt>:sNN' (slice variant, 2600+ slot)."""
    fmt_id, suffix = _split_key(key)
    if suffix is None:
        return _write_take_link(node, fmt_id, take)
    index = _format_index_for_id(fmt_id, node)
    ordinal = _ordinal_from_suffix(suffix)
    if index is None or ordinal is None or not (1 <= ordinal <= MAX_SLICE_ORDINALS):
        return False
    return _store_link(_node_data_container(node), _slice_link_id(index, ordinal), take)


def _read_link_for_key(node, key, doc=None):
    """Key-based take-link reader — mirror of _write_link_for_key."""
    fmt_id, suffix = _split_key(key)
    if suffix is None:
        return _read_take_link(node, fmt_id, doc)
    index = _format_index_for_id(fmt_id, node)
    ordinal = _ordinal_from_suffix(suffix)
    if index is None or ordinal is None or not (1 <= ordinal <= MAX_SLICE_ORDINALS):
        return None
    return _load_link(_node_data_container(node), _slice_link_id(index, ordinal), doc)


def _write_takes_signature(node, signature):
    return _bc_set_string(_node_data_container(node), ID_PRIVATE_TAKES_SIGNATURE, signature)


def _read_takes_signature(node):
    value = _bc_get_data(_node_data_container(node), ID_PRIVATE_TAKES_SIGNATURE)
    return str(value) if value else ""


def _is_stale_from_signature(node):
    """Return True when the tag params drifted from the last generated Takes.

    Pure + read-only: both the saved signature (BaseContainer) and the current
    params signature survive the draw-thread document clone, so this is safe to
    call from Draw. A transient Python attribute would not — attributes set via
    ``setattr`` do not survive C4D's C++ node clone (only BaseContainer data
    does), which is the same failure mode that broke the guide cache in U3.
    """
    saved = _read_takes_signature(node)
    if not saved:
        return False
    return _params_signature_for_takes(node) != saved


def _command_id_from_data(data):
    try:
        cid = data["id"]
    except Exception:
        cid = None
    return _desc_level_id(cid)


def _force_viewport_refresh():
    """Force a synchronous editor redraw. C4D's viewport is LAZY about
    re-deriving the camera projection / render-aspect letterbox when the
    active take (and with it the active RenderData + camera overrides)
    changes — the stale view snaps into place only on a panel resize
    (live-caught: the 'initial crop sometimes wrong until I resize the
    viewport' report). EVENT_FORCEREDRAW + DrawViews recomputes it now."""
    try:
        c4d.EventAdd(c4d.EVENT_FORCEREDRAW)
    except Exception:
        try:
            c4d.EventAdd()
        except Exception:
            pass
    try:
        c4d.DrawViews(
            c4d.DRAWFLAGS_ONLY_ACTIVE_VIEW
            | c4d.DRAWFLAGS_NO_THREAD
            | c4d.DRAWFLAGS_STATICBREAK
        )
    except Exception:
        pass


def _observe_signature_drift(node):
    """Signature-drift detector for the auto-sync — shared by the
    POSTSETPARAMETER hook AND ``Execute`` (belt-and-braces, live-caught bug:
    the AM's right-click "reset to default" on a nudge arrow sets the value
    WITHOUT sending MSG_DESCRIPTION_POSTSETPARAMETER, so the hook alone
    missed it and the Take kept the old nudge; scripts/XPresso writes skip
    the message too). Execute runs on every scene evaluation, so any change
    path lands here. Cheap (small JSON + hash) and non-mutating beyond the
    tag's own BC bookkeeping key; ``request_sync`` is Execute-safe (python
    state + SpecialEventAdd, which is explicitly thread-safe)."""
    try:
        sig = _params_signature_for_takes(node)
        bc = _node_data_container(node)
        last_seen = _bc_get_data(bc, ID_PRIVATE_LAST_SEEN_SIGNATURE)
        last_seen = str(last_seen) if last_seen else ""
        if sig != last_seen:
            _bc_set_data(bc, ID_PRIVATE_LAST_SEEN_SIGNATURE, sig)
            if last_seen:  # seeded before → a real change: sync
                from sentinel.ui import frame_sync
                frame_sync.request_sync(node)
    except Exception:
        pass


def _viewing_entry_pairs(node):
    """[(value, target_str, label)] for the Viewing cycle AND the panel's
    target list — ONE source. Whole formats keep value = index + 1 (stable
    against enable churn, v1.28 encoding); a sliced format replaces its
    whole entry with per-slice entries encoded as
    (index + 1) * VIEWING_SLICE_STRIDE + ordinal."""
    pairs = []
    for index, fmt in enumerate(_format_defs(node)):
        if not _row_enabled(node, index):
            continue
        fmt_id = fmt.get("id")
        label = fmt.get("label") or fmt_id
        sx, sy = _slices_for_index(node, index)
        if sx * sy > 1:
            for ordinal in range(1, sx * sy + 1):
                sfx = "s%02d" % ordinal
                pairs.append(((index + 1) * VIEWING_SLICE_STRIDE + ordinal,
                              f"{fmt_id}:{sfx}",
                              f"{label} · {sfx}"))
        else:
            pairs.append((index + 1, fmt_id, label))
    return pairs


def viewing_targets(node):
    """Ordered viewing targets for the panel (Task 8's source):
    ["master", "16x9", "custom:s01", ...]."""
    return ["master"] + [target for _value, target, _label in _viewing_entry_pairs(node)]


def _viewing_cycle_entries(node):
    """Cycle for ID_VIEWING: 0=Master plus every ENABLED format entry
    (whole formats or their slice variants)."""
    return [(0, "Master")] + [
        (value, label) for value, _target, label in _viewing_entry_pairs(node)
    ]


def _viewing_value_from_takes(node, doc):
    """Derive the SHOWN Viewing value from the document's current take —
    two-way: switching takes in the Take Manager reflects back here."""
    try:
        td = doc.GetTakeData() if doc else None
        current = td.GetCurrentTake() if td else None
    except Exception:
        current = None
    if current is None:
        return 0
    for index, fmt in enumerate(_format_defs(node)):
        linked = _read_take_link(node, fmt.get("id"), doc)
        try:
            # Object identity, not name comparison: take names aren't unique
            # in C4D, and the BaseLink already resolved the real node (review
            # finding — same identity idiom as _current_take_is_own_format).
            if linked is not None and linked == current:
                return index + 1
        except Exception:
            continue
    # Slice links of sliced formats (v1.29): same identity idiom.
    for index, fmt in enumerate(_format_defs(node)):
        sx, sy = _slices_for_index(node, index)
        if sx * sy <= 1:
            continue
        fmt_id = fmt.get("id")
        for ordinal in range(1, sx * sy + 1):
            linked = _read_link_for_key(node, "%s:s%02d" % (fmt_id, ordinal), doc)
            try:
                if linked is not None and linked == current:
                    return (index + 1) * VIEWING_SLICE_STRIDE + ordinal
            except Exception:
                continue
    return 0


def _activate_viewing(node, doc, value):
    """Activate the take behind a Viewing selection (0 = Main). Document
    state, not tag state — mirrors clicking the take in the Take Manager."""
    try:
        td = doc.GetTakeData() if doc else None
    except Exception:
        td = None
    if td is None:
        return False
    target = None
    value = int(value)
    if value <= 0:
        try:
            target = td.GetMainTake()
        except Exception:
            target = None
    elif value >= VIEWING_SLICE_STRIDE:
        index = value // VIEWING_SLICE_STRIDE - 1
        ordinal = value % VIEWING_SLICE_STRIDE
        defs = _format_defs(node)
        if 0 <= index < len(defs) and 1 <= ordinal <= MAX_SLICE_ORDINALS:
            target = _read_link_for_key(
                node, "%s:s%02d" % (defs[index].get("id"), ordinal), doc)
    else:
        index = value - 1
        defs = _format_defs(node)
        if 0 <= index < len(defs):
            target = _read_take_link(node, defs[index].get("id"), doc)
    if target is None:
        return False
    try:
        td.SetCurrentTake(target)
        _event_add()
        _force_viewport_refresh()
        return True
    except Exception:
        return False


def set_viewing(doc, tag, target):
    """Dialog-free core for the Viewing selector (AM cycle AND the panel's
    ``panel/frame/set_viewing`` op share it). ``target`` = "master", a
    format id, or a "<fmt>:sNN" slice; activating a take is DOCUMENT state,
    legitimate from either surface. Returns a status dict, never raises,
    never shows a dialog."""
    if target in (None, "", "master"):
        ok = _activate_viewing(tag, doc, 0)
        return {"ok": bool(ok), "viewing": "master" if ok else None,
                "error": None if ok else "no_take_data"}
    for value, entry_target, _label in _viewing_entry_pairs(tag):
        if entry_target == target:
            ok = _activate_viewing(tag, doc, value)
            return {"ok": bool(ok), "viewing": target if ok else None,
                    "error": None if ok else "take_not_found"}
    return {"ok": False, "viewing": None, "error": "unknown_format"}


def _sync_status_text(node):
    """Derived AM status line: pending window > failed > drift > synced."""
    try:
        from sentinel.ui import frame_sync
        key = frame_sync._tag_key(node)
        if key and frame_sync.scheduler.has_pending(key):
            return "syncing..."
        if key and frame_sync.last_sync_result.get(key) == "failed":
            return "sync failed - see console"
        if _is_stale_from_signature(node):
            return "sync pending"
    except Exception:
        pass
    return "synced"


def _run_takes_generation(doc, node):
    """Dialog-free create/update core shared by the button handler and the
    Frame v2 auto-sync. The CALLER owns the undo block (this passes
    ``external_undo`` to the engine and never opens its own). Returns the
    engine report; raises nothing on its own beyond what the engine raises."""
    host = _tag_host(node)
    formats = _enabled_format_ids_from_params(node)
    prefix = _safe_node_name(host, "Camera")
    undo_added = [False]

    def _tag_link_writer(key, take):
        # key = fmt_id or "<fmt>:sNN" (Task 3 engine contract).
        if not undo_added[0]:
            try:
                doc.AddUndo(_undo_type_change(), node)
            except Exception:
                pass
            undo_added[0] = True
        _write_link_for_key(node, key, take)

    options = {
        "formats": formats,
        "update_existing": True,
        "name_prefix": prefix,
        "external_undo": True,
        "source_cam": host,
        "composition_mode": composition_mode_for_engine(
            _get_node_value(node, ID_COMPOSITION, COMPOSITION_CROP)
        ),
        "film_offsets": _film_offsets_from_params(node),
        "format_defs": _engine_format_defs(node),
        "tag_link_writer": _tag_link_writer,
        "existing_take_resolver": lambda key: _read_link_for_key(node, key, doc),
    }
    report = generate_multiformat_takes(doc, options)
    if not undo_added[0]:
        try:
            doc.AddUndo(_undo_type_change(), node)
        except Exception:
            pass
    return report


def _prune_orphaned_takes(doc, node):
    """Silently remove takes for formats no longer enabled (auto-sync's
    implicit Remove Stale — no confirmation dialog). Caller owns the undo
    block. Returns the number removed.

    Viewing guard (final-review finding): with auto-sync + the Viewing
    selector, "the user is currently looking at the take about to be
    deleted" is routine (view 9:16 → disable 9:16 → debounce fires). Never
    delete the ACTIVE take out from under the viewport — fall back to Main
    first, same SetCurrentTake idiom as _activate_viewing."""
    removed = 0
    try:
        td = doc.GetTakeData()
        current = td.GetCurrentTake() if td else None
    except Exception:
        td, current = None, None
    for key, take in _find_orphaned_takes_for_tag(node, doc):
        if td is not None and current is not None and take == current:
            try:
                td.SetCurrentTake(td.GetMainTake())
                current = td.GetCurrentTake()
            except Exception:
                pass
        try:
            doc.AddUndo(_undo_type_delete(), take)
        except Exception:
            pass
        remover = getattr(take, "Remove", None)
        if callable(remover):
            try:
                remover()
            except Exception:
                continue
            removed += 1
            _write_link_for_key(node, key, None)
    return removed


def run_full_sync(doc, tag):
    """Frame v2 auto-sync unit: regenerate takes + outputs for the enabled
    formats, prune takes of disabled formats, and stamp the signature — all
    in ONE undo step. Strictly dialog-free (runs from a MessageData tick;
    a MessageDialog here would freeze C4D). Returns a status dict, never
    raises for the expected failure modes."""
    host = _tag_host(tag)
    if not is_valid_camera_host(_node_type(host)):
        return {"ok": False, "error": "invalid_host"}
    signature = _params_signature_for_takes(tag)
    formats = _enabled_format_ids_from_params(tag)

    doc.StartUndo()
    try:
        # Unconditional undo anchor for the TAG itself: the prune's
        # take-link clears and the signature stamp below write to the tag's
        # BaseContainer, and with zero enabled formats the generation core
        # (whose _tag_link_writer would otherwise add this) never runs —
        # without this anchor a Cmd+Z would restore the deleted Takes but
        # leave the tag container in the post-sync state (review finding,
        # mirrors _handle_remove_stale's explicit AddUndo).
        try:
            doc.AddUndo(_undo_type_change(), tag)
        except Exception:
            pass
        report = None
        if formats:
            report = _run_takes_generation(doc, tag)
        removed = _prune_orphaned_takes(doc, tag)
        _write_takes_signature(tag, signature)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        doc.EndUndo()
        _event_add()

    errors = list(report.get("errors", [])) if report else []
    return {
        "ok": not errors,
        "error": "; ".join(errors) if errors else None,
        "report": report,
        "removed": removed,
    }


def _walk_child_takes(take_data):
    if take_data is None:
        return
    try:
        main = take_data.GetMainTake()
        node = main.GetDown() if main is not None else None
    except Exception:
        node = None

    def _walk(first):
        current = first
        while current:
            yield current
            child = current.GetDown()
            if child:
                for nested in _walk(child):
                    yield nested
            current = current.GetNext()

    for take in _walk(node):
        yield take


def _expected_take_names(node):
    """Take names this tag SHOULD own right now -> their link key. The prune
    orphan set is everything tag-owned that is NOT in here: disabled formats
    (whole + slices), the whole-format take of a now-sliced format, slice
    takes beyond the current grid (3x1 -> 2x1 leaves s03), disabled custom."""
    host = _tag_host(node)
    prefix = _safe_node_name(host, "")
    expected = {}
    if not prefix:
        return expected
    for index, fmt in enumerate(_format_defs(node)):
        if not _row_enabled(node, index):
            continue
        fmt_id = fmt.get("id")
        sx, sy = _slices_for_index(node, index)
        if sx * sy > 1:
            for ordinal in range(1, sx * sy + 1):
                sfx = "s%02d" % ordinal
                expected[f"{prefix}_{fmt_id}_{sfx}"] = f"{fmt_id}:{sfx}"
        else:
            expected[f"{prefix}_{fmt_id}"] = fmt_id
    return expected


def _all_parse_defs():
    """Name-parse defs for the prune walk: the 5 standard formats plus the
    custom row UNCONDITIONALLY — a disabled custom's takes must still be
    found (its def drops out of _format_defs while its takes linger)."""
    return [{"id": fmt.get("id")} for fmt in MULTIFORMAT_DEFS] + [
        {"id": CUSTOM_FORMAT_ID}
    ]


def _find_orphaned_takes_for_tag(node, doc):
    """Find tag-owned takes that are NOT in the expected set, never deleting
    them. Returns (key, take) pairs; key = fmt_id or '<fmt>:sNN'."""
    host = _tag_host(node)
    prefix = _safe_node_name(host, "")
    expected = _expected_take_names(node)
    found = []
    seen = set()

    def _add(key, take):
        if take is None:
            return
        # Dedup by take name, not id(): the same take is reached by two paths
        # (stored BaseLink + name walk) and C4D hands out a fresh Python wrapper
        # per access, so id() would list — and then double-Remove() — one take
        # twice. Distinct takes keep distinct names, so this stays correct.
        try:
            marker = take.GetName()
        except Exception:
            marker = id(take)
        if marker in expected:
            return
        if marker in seen:
            return
        seen.add(marker)
        found.append((key, take))

    # Link-walk: every per-format link plus every slice link slot (BC misses
    # are cheap dict lookups; MAX_SLICE_ORDINALS = 16x16 caps the loop).
    for parse_def in _all_parse_defs():
        fmt_id = parse_def.get("id")
        _add(fmt_id, _read_link_for_key(node, fmt_id, doc))
        for ordinal in range(1, MAX_SLICE_ORDINALS + 1):
            key = "%s:s%02d" % (fmt_id, ordinal)
            _add(key, _read_link_for_key(node, key, doc))

    # Name-walk: any child take named <prefix>_<suffix> whose suffix parses
    # against ALL defs (standard + custom, regardless of enabled state).
    try:
        take_data = doc.GetTakeData()
    except Exception:
        take_data = None
    if prefix:
        marker_prefix = prefix + "_"
        parse_defs = _all_parse_defs()
        for take in _walk_child_takes(take_data):
            try:
                name = take.GetName() or ""
            except Exception:
                continue
            if not name.startswith(marker_prefix):
                continue
            parsed = _parse_own_format_suffix(name[len(marker_prefix):], parse_defs)
            if parsed is None:
                continue
            fmt_id, suffix = parsed
            _add(f"{fmt_id}:{suffix}" if suffix else fmt_id, take)
    return found


def _renderdata_path(render_data):
    try:
        return render_data[c4d.RDATA_PATH] or ""
    except Exception:
        return ""


def _set_renderdata_for_format(render_data, fmt_id):
    fmt = get_multiformat_def(fmt_id)
    if not fmt:
        return False
    source_path = _renderdata_path(render_data)
    render_data[c4d.RDATA_XRES] = float(fmt["width"])
    render_data[c4d.RDATA_YRES] = float(fmt["height"])
    render_data[c4d.RDATA_PATH] = compute_format_output_path(source_path, fmt_id, "subfolder")
    return True


def _report_summary_text(report):
    lines = ["Sentinel Frame Takes"]
    for key, label in (
        ("created", "Created"),
        ("updated", "Updated"),
        ("adopted", "Adopted"),
        ("skipped", "Skipped"),
        ("orphaned", "Orphaned"),
    ):
        values = report.get(key) or []
        if values:
            lines.append(f"{label}: {len(values)} ({', '.join(str(v) for v in values)})")
        else:
            lines.append(f"{label}: 0")
    notes = report.get("notes") or []
    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in notes)
    errors = report.get("errors") or []
    if errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {err}" for err in errors)
    return "\n".join(lines)


def _parse_own_format_suffix(suffix, defs):
    """Pure suffix parser for tag-owned take names: '16x9' -> ('16x9', None),
    'custom_s02' -> ('custom', 's02'), anything else -> None."""
    ids = {d.get("id") for d in defs}
    if suffix in ids:
        return (suffix, None)
    stem, sep, tail = suffix.rpartition("_s")
    if sep and stem in ids and tail.isdigit():
        return (stem, "s" + tail)
    return None


def _current_own_take_info(tag, doc):
    """(fmt_id, slice_suffix|None) when the active take is one of THIS tag's
    generated format takes (named ``<host camera>_<fmt>[_sNN]``), else None.

    In such a take the host camera is already cropped/zoomed to the format, so
    drawing the multi-format guides would draw a crop-of-a-crop and mislead the
    artist (the guide would no longer align with the framing). Guides belong to
    the master (Main) view where you compose; a format take should show the
    clean final crop. Pure + read-only — safe on the draw thread (only reads
    take names).
    """
    getter = getattr(doc, "GetTakeData", None)
    if not callable(getter):
        return None
    try:
        td = getter()
        current = td.GetCurrentTake()
        main = td.GetMainTake()
    except Exception:
        return None
    if current is None or main is None or current == main:
        return None
    prefix = _safe_node_name(_tag_host(tag), "")
    if not prefix:
        return None
    try:
        name = current.GetName() or ""
    except Exception:
        return None
    marker = prefix + "_"
    if not name.startswith(marker):
        return None
    return _parse_own_format_suffix(name[len(marker):], _format_defs(tag))


def _current_take_is_own_format(tag, doc):
    """True when the active take is one of THIS tag's generated format takes
    (whole or slice) — thin view over ``_current_own_take_info``."""
    return _current_own_take_info(tag, doc) is not None


def _current_own_format_id(tag, doc):
    """Format id of the active own-format take (slice takes report their
    parent format), else None — thin view over ``_current_own_take_info``."""
    info = _current_own_take_info(tag, doc)
    return info[0] if info else None


def _slice_dims(node, fmt_id, suffix):
    """Pixel dims for the own-format-take HUD: the format's full dims when
    ``suffix`` is None, else the dims of that specific slice window. Resolves
    the format def through the per-tag defs (``_format_defs(node)``, never
    ``get_multiformat_def``) so a Custom format resolves correctly."""
    defs = _format_defs(node)
    index = None
    fmt = None
    for i, d in enumerate(defs):
        if d.get("id") == fmt_id:
            index = i
            fmt = d
            break
    if fmt is None:
        return (0, 0)
    width = int(fmt.get("width", 0) or 0)
    height = int(fmt.get("height", 0) or 0)
    if suffix is None:
        return (width, height)
    sx, sy = _slices_for_index(node, index)
    windows = framing.slice_windows((0, 0, 1, 1), sx, sy, width, height)
    for _sub, w_px, h_px, sfx in windows:
        if sfx == suffix:
            return (w_px, h_px)
    return (width, height)


try:
    _TagDataBase = plugins.TagData
    if not isinstance(_TagDataBase, type):
        raise TypeError("plugins.TagData is not a class")
    _ = c4d.DRAWPASS_OBJECT
    _SENTINEL_FRAME_TAG_AVAILABLE = True
except Exception:
    _TagDataBase = object
    _SENTINEL_FRAME_TAG_AVAILABLE = False


class SentinelFrameTag(_TagDataBase):
    """TagData shell for the Sentinel Frame per-camera workflow."""

    def _init_attr(self, node, py_type, param_id):
        init_attr = getattr(self, "InitAttr", None)
        if callable(init_attr):
            try:
                init_attr(node, py_type, param_id)
            except Exception:
                pass

    def _set_description_parameter(
        self,
        node,
        description,
        parameter_id,
        dtype,
        name,
        parent,
        minimum=None,
        maximum=None,
        step=None,
        cycle=None,
    ):
        desc_id = _description_parent(parameter_id, dtype, node)
        bc = c4d.GetCustomDatatypeDefault(dtype)
        _set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
        _set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
        if minimum is not None:
            _set_bc_value(bc, "SetFloat", c4d.DESC_MIN, float(minimum))
            _set_bc_value(bc, "SetFloat", c4d.DESC_MINSLIDER, float(minimum))
        if maximum is not None:
            _set_bc_value(bc, "SetFloat", c4d.DESC_MAX, float(maximum))
            _set_bc_value(bc, "SetFloat", c4d.DESC_MAXSLIDER, float(maximum))
        if step is not None:
            _set_bc_value(bc, "SetFloat", c4d.DESC_STEP, float(step))
        if dtype == c4d.DTYPE_REAL and parameter_id != ID_LINE_WIDTH:
            # Every other REAL here is a genuine 0-1 fraction (opacity, dim,
            # nudge) — but Line Width is a literal pixel-ish thickness (0.5-4)
            # that Draw consumes raw; the percent unit would render 2.0 as
            # "200%" in the AM (review finding).
            _set_bc_value(bc, "SetInt32", c4d.DESC_UNIT, c4d.DESC_UNIT_PERCENT)
        if dtype == c4d.DTYPE_BUTTON:
            # A DTYPE_BUTTON only renders as a clickable button when its
            # customgui is CUSTOMGUI_BUTTON; without this the Actions group
            # shows up empty in the Attribute Manager.
            button_gui = getattr(c4d, "CUSTOMGUI_BUTTON", None)
            if button_gui is not None:
                _set_bc_value(bc, "SetInt32", c4d.DESC_CUSTOMGUI, button_gui)
        if cycle is not None:
            cycle_bc = c4d.BaseContainer()
            for value, label in cycle:
                _set_bc_value(cycle_bc, "SetString", int(value), label)
            _set_bc_value(bc, "SetContainer", c4d.DESC_CYCLE, cycle_bc)
        try:
            return bool(description.SetParameter(desc_id, bc, parent))
        except Exception:
            return False

    def _set_description_group(self, node, description, group_id, name, parent,
                               columns=None, titlebar=True):
        desc_id = _description_parent(group_id, c4d.DTYPE_GROUP, node)
        bc = c4d.GetCustomDatatypeDefault(c4d.DTYPE_GROUP)
        _set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
        _set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
        _set_bc_value(bc, "SetBool", c4d.DESC_TITLEBAR, bool(titlebar))
        _set_bc_value(bc, "SetBool", c4d.DESC_DEFAULT, False)
        if columns is not None:
            _set_bc_value(bc, "SetInt32", c4d.DESC_COLUMNS, int(columns))
        try:
            return bool(description.SetParameter(desc_id, bc, parent))
        except Exception:
            return False

    def Init(self, node, isCloneInit=False):
        for param_id in (
            ID_ENABLED,
            ID_SHOW_GUIDES,
            ID_SHOW_MASK,
            ID_SHOW_PLATFORM,
            ID_SHOW_HUD,
        ):
            self._init_attr(node, bool, param_id)
        for param_id in (ID_COMPOSITION, ID_SCHEMA_VERSION):
            self._init_attr(node, int, param_id)
        self._init_attr(node, float, ID_MASK_OPACITY)
        for param_id in (ID_LINE_WIDTH, ID_LINE_OPACITY, ID_DIM_NONVIEWED):
            self._init_attr(node, float, param_id)
        _set_node_value(node, ID_LINE_WIDTH, 2.0)  # matches the pre-v2 hardcoded width
        _set_node_value(node, ID_LINE_OPACITY, 1.0)
        _set_node_value(node, ID_DIM_NONVIEWED, 0.7)

        _set_node_value(node, ID_ENABLED, True)
        _set_node_value(node, ID_COMPOSITION, COMPOSITION_CROP)
        _set_node_value(node, ID_SHOW_GUIDES, True)
        _set_node_value(node, ID_SHOW_MASK, False)
        _set_node_value(node, ID_MASK_OPACITY, 0.5)
        _set_node_value(node, ID_SHOW_PLATFORM, False)
        _set_node_value(node, ID_SHOW_HUD, True)
        _set_node_value(node, ID_SCHEMA_VERSION, SCHEMA_VERSION)

        for index in range(FORMAT_ROW_COUNT):
            fmt_id = _row_format_id(index)
            ids = _format_ids(index)
            self._init_attr(node, bool, ids["enabled"])
            self._init_attr(node, c4d.Vector, ids["color"])
            self._init_attr(node, float, ids["nudge_x"])
            self._init_attr(node, float, ids["nudge_y"])
            self._init_attr(node, int, ids["slice_x"])
            self._init_attr(node, int, ids["slice_y"])
            _set_node_value(node, ids["enabled"], index != CUSTOM_FORMAT_INDEX)
            _set_node_value(node, ids["color"], _vector(_FORMAT_COLORS.get(fmt_id, (0.6, 0.6, 0.6))))
            _set_node_value(node, ids["nudge_x"], 0.0)
            _set_node_value(node, ids["nudge_y"], 0.0)
            _set_node_value(node, ids["slice_x"], 1)
            _set_node_value(node, ids["slice_y"], 1)
            if index == CUSTOM_FORMAT_INDEX:
                self._init_attr(node, int, ids["width"])
                self._init_attr(node, int, ids["height"])
                _set_node_value(node, ids["width"], 1920)
                _set_node_value(node, ids["height"], 1080)

        priority_factory = getattr(c4d, "PriorityData", None)
        if callable(priority_factory):
            try:
                priority = priority_factory()
                priority.SetPriorityValue(c4d.PRIORITYVALUE_CAMERADEPENDENT, True)
                _set_node_value(node, c4d.EXPRESSION_PRIORITY, priority)
            except Exception:
                pass

        _write_platform_insets_to_node(node, _standard_platform_insets_by_format())
        return True

    def GetDDescription(self, node, description, flags):
        # Frame v2 control strip (spec §1): three top-level tab groups laid
        # out by USE FREQUENCY — Main (daily, no scroll), Display (once, per
        # artist taste), Advanced (almost never). The four workflow buttons
        # are GONE (auto-sync replaces them; Mark Subject lives in the panel's
        # Frame sub-view). Existing param ids keep their meaning — only the
        # description layout changed, so v1.8.0 scenes load losslessly.
        try:
            description.LoadDescription(node.GetType())
        except Exception:
            pass

        root = c4d.DescID(c4d.DescLevel(c4d.ID_TAGPROPERTIES))
        main_group = _description_parent(ID_GROUP_MAIN, c4d.DTYPE_GROUP, node)
        display_group = _description_parent(ID_GROUP_DISPLAY, c4d.DTYPE_GROUP, node)
        advanced_group = _description_parent(ID_GROUP_ADVANCED, c4d.DTYPE_GROUP, node)
        formats_group = _description_parent(ID_GROUP_FORMATS, c4d.DTYPE_GROUP, node)

        # --- Main ---------------------------------------------------------
        if not self._set_description_group(node, description, ID_GROUP_MAIN, "Main", root):
            return False
        if not self._set_description_parameter(
            node, description, ID_ENABLED, c4d.DTYPE_BOOL, "Enabled", main_group
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_VIEWING, c4d.DTYPE_LONG, "Viewing", main_group,
            cycle=_viewing_cycle_entries(node)
        ):
            return False
        sync_bc_ok = self._set_description_parameter(
            node, description, ID_SYNC_STATUS, c4d.DTYPE_STRING, "Takes", main_group
        )
        if not sync_bc_ok:
            return False

        # Per-format rows (Social Frame pattern): ONE 4-column grid group
        # holding every format's cells DIRECTLY (no per-row sub-groups —
        # live-caught polish: per-row groups each sized their own columns
        # from their own label width, so the columns didn't line up
        # vertically across rows; a single grid shares column widths and
        # aligns every row). The enable checkbox CARRIES the format label;
        # swatch identifies the guide; nudge X/Y inline (feedback = the
        # format's rect moves in the master view while dragging).
        if not self._set_description_group(
            node, description, ID_GROUP_FORMATS, "Formats", main_group,
            columns=6, titlebar=False
        ):
            return False
        color_dtype = getattr(c4d, "DTYPE_COLOR", c4d.DTYPE_VECTOR)
        for index, fmt in enumerate(_format_defs()):
            ids = _format_ids(index)
            label = fmt.get("label") or fmt.get("id", "Format")
            if not self._set_description_parameter(
                node, description, ids["enabled"], c4d.DTYPE_BOOL, label, formats_group
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["color"], color_dtype, "", formats_group
            ):
                return False
            # Nudge is a film-offset FRACTION (percent unit: raw 1.0 == 100%),
            # so the clamp is -1.0..1.0 (=-100%..100%), step 0.01 (=1%). Using
            # -100..100 here would read as +/-10000% under the percent unit.
            if not self._set_description_parameter(
                node, description, ids["nudge_x"], c4d.DTYPE_REAL, "X", formats_group, -1.0, 1.0, 0.01
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["nudge_y"], c4d.DTYPE_REAL, "Y", formats_group, -1.0, 1.0, 0.01
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["slice_x"], c4d.DTYPE_LONG, "Sx", formats_group, 1, 16, 1
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["slice_y"], c4d.DTYPE_LONG, "Sy", formats_group, 1, 16, 1
            ):
                return False

        # Custom row (spec: own 8-column sub-grid under the main grid; W/H need
        # two extra cells so the shared 6-column widths can't apply — accepted
        # deviation).
        custom_group = _description_parent(ID_GROUP_CUSTOM, c4d.DTYPE_GROUP, node)
        if not self._set_description_group(
            node, description, ID_GROUP_CUSTOM, "Custom", main_group,
            columns=8, titlebar=False
        ):
            return False
        cids = _format_ids(CUSTOM_FORMAT_INDEX)
        for pid, dtype, name, lo, hi, st in (
            (cids["enabled"], c4d.DTYPE_BOOL, "Custom", None, None, None),
            (cids["color"], color_dtype, "", None, None, None),
            (cids["width"], c4d.DTYPE_LONG, "W", 16, 16384, 1),
            (cids["height"], c4d.DTYPE_LONG, "H", 16, 16384, 1),
            (cids["nudge_x"], c4d.DTYPE_REAL, "X", -1.0, 1.0, 0.01),
            (cids["nudge_y"], c4d.DTYPE_REAL, "Y", -1.0, 1.0, 0.01),
            (cids["slice_x"], c4d.DTYPE_LONG, "Sx", 1, 16, 1),
            (cids["slice_y"], c4d.DTYPE_LONG, "Sy", 1, 16, 1),
        ):
            if not self._set_description_parameter(
                node, description, pid, dtype, name, custom_group, lo, hi, st
            ):
                return False

        # Display toggles row (Main, bottom): quick visibility switches.
        display_toggles = (
            (ID_SHOW_GUIDES, "Guides"),
            (ID_SHOW_MASK, "Mask"),
            (ID_SHOW_PLATFORM, "Zones"),
            (ID_SHOW_HUD, "HUD"),
        )
        for parameter_id, name in display_toggles:
            if not self._set_description_parameter(
                node, description, parameter_id, c4d.DTYPE_BOOL, name, main_group
            ):
                return False

        # --- Display (once-per-taste appearance) --------------------------
        if not self._set_description_group(node, description, ID_GROUP_DISPLAY, "Display", root):
            return False
        display_params = (
            (ID_MASK_OPACITY, "Mask Opacity", 0.0, 1.0, 0.01),
            (ID_LINE_WIDTH, "Line Width", 0.5, 4.0, 0.5),
            (ID_LINE_OPACITY, "Line Opacity", 0.0, 1.0, 0.01),
            (ID_DIM_NONVIEWED, "Dim Non-Viewed Formats", 0.0, 1.0, 0.01),
        )
        for parameter_id, name, minimum, maximum, step in display_params:
            if not self._set_description_parameter(
                node, description, parameter_id, c4d.DTYPE_REAL, name, display_group,
                minimum, maximum, step
            ):
                return False

        # --- Advanced -----------------------------------------------------
        # Composition only: the per-format platform insets stay ruleset-owned
        # (sentinel_rules.json → private container, refreshed each Message
        # pass) — exposing them editable here would fight that resolution.
        if not self._set_description_group(node, description, ID_GROUP_ADVANCED, "Advanced", root):
            return False
        if not self._set_description_parameter(
            node, description, ID_COMPOSITION, c4d.DTYPE_LONG, "Composition Mode",
            advanced_group, cycle=COMPOSITION_CYCLE
        ):
            return False

        return True, flags | c4d.DESCFLAGS_DESC_LOADED

    def GetDParameter(self, node, id, flags):
        parameter_id = _desc_level_id(id)
        if parameter_id == ID_VIEWING:
            doc = _doc_from_node(node)
            value = _viewing_value_from_takes(node, doc)
            return True, value, flags | c4d.DESCFLAGS_GET_PARAM_GET
        if parameter_id == ID_SYNC_STATUS:
            return True, _sync_status_text(node), flags | c4d.DESCFLAGS_GET_PARAM_GET
        return False

    def SetDParameter(self, node, id, data, flags):
        parameter_id = _desc_level_id(id)
        if parameter_id == ID_VIEWING:
            if _is_main_thread():
                doc = _doc_from_node(node)
                _activate_viewing(node, doc, data)
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        if parameter_id == ID_SYNC_STATUS:
            # Read-only derived string: swallow writes.
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        enable_id = _FORMAT_PARAM_TO_ENABLE.get(parameter_id)
        if enable_id is not None:
            return bool(_get_node_value(node, enable_id, True))
        if parameter_id in _ACTION_IDS:
            return _host_is_valid_camera(node)
        return True

    def _handle_create_update_takes(self, node, doc):
        host = _tag_host(node)
        if not is_valid_camera_host(_node_type(host)):
            _show_message("Sentinel Frame must be placed on a supported Camera.")
            return True

        formats = _enabled_format_ids_from_params(node)
        if not formats:
            _show_message("Enable at least one format before creating Takes.")
            return True

        signature = _params_signature_for_takes(node)

        # This handler owns the undo block so the take generation +
        # BaseLink/signature writes revert as ONE Cmd+Z; the shared core
        # (`_run_takes_generation`, also used by the Frame v2 auto-sync)
        # never opens its own.
        doc.StartUndo()
        try:
            report = _run_takes_generation(doc, node)
            _write_takes_signature(node, signature)
        finally:
            doc.EndUndo()
            _event_add()

        _show_message(_report_summary_text(report))
        return True

    def _handle_set_output(self, node, doc):
        fmt_id = _selected_output_format_id(node)
        if not fmt_id:
            _show_message("Enable at least one format before setting output.")
            return True

        render_data = None
        try:
            render_data = doc.GetActiveRenderData()
        except Exception:
            render_data = None
        if render_data is None:
            _show_message("No active Render Settings found.")
            return True

        # v1 escape hatch: apply the first enabled format only, without Takes.
        doc.StartUndo()
        try:
            try:
                doc.AddUndo(_undo_type_change(), render_data)
            except Exception:
                pass
            _set_renderdata_for_format(render_data, fmt_id)
        finally:
            doc.EndUndo()
            _event_add()

        fmt = get_multiformat_def(fmt_id) or {}
        _show_message(
            "Set Output applied:\n"
            f"{fmt_id}  {int(fmt.get('width', 0))}x{int(fmt.get('height', 0))}"
        )
        return True

    def _handle_remove_stale(self, node, doc):
        orphans = _find_orphaned_takes_for_tag(node, doc)
        if not orphans:
            _show_message("No stale Sentinel Frame Takes found for this camera.")
            return True

        lines = [
            "Remove these stale Takes?",
            "",
        ]
        for key, take in orphans:
            lines.append(f"- {_safe_node_name(take, key)}")
        lines.extend(["", "This cannot be done without confirmation."])
        if not _ask_question("\n".join(lines)):
            return True

        doc.StartUndo()
        removed = 0
        try:
            try:
                doc.AddUndo(_undo_type_change(), node)
            except Exception:
                pass
            for key, take in orphans:
                try:
                    doc.AddUndo(_undo_type_delete(), take)
                except Exception:
                    pass
                remover = getattr(take, "Remove", None)
                if callable(remover):
                    try:
                        remover()
                    except Exception:
                        continue
                    removed += 1
                    _write_link_for_key(node, key, None)
        finally:
            doc.EndUndo()
            _event_add()

        _show_message(f"Removed {removed} stale Take(s).")
        return True

    def _handle_mark_subject(self, node, doc):
        try:
            flags = getattr(c4d, "GETACTIVEOBJECTFLAGS_CHILDREN", 0)
            selection = doc.GetActiveObjects(flags) or []
        except Exception:
            selection = []

        if not selection:
            _show_message(
                "Select one or more objects first, then click Mark Subject again."
            )
            return True

        target_state = not all(is_object_marked_safe_area(obj) for obj in selection)
        changed = 0
        failed = 0

        doc.StartUndo()
        try:
            for obj in selection:
                if target_state:
                    ok = mark_object_safe_area(obj, True, doc)
                else:
                    ok = unmark_object_safe_area(obj, doc)
                if ok:
                    changed += 1
                else:
                    failed += 1
        finally:
            doc.EndUndo()
            _event_add()

        verb = "Marked" if target_state else "Unmarked"
        message = f"{verb} {changed} Safe Area Subject(s)."
        if failed:
            message += f"\n{failed} object(s) failed."
        _show_message(message)
        return True

    def _handle_command(self, node, data):
        if not _is_main_thread():
            return True
        doc = _doc_from_node(node)
        if doc is None:
            _show_message("No active document.")
            return True

        command_id = _command_id_from_data(data)
        # Halt the viewport draw / expression threads before mutating the
        # document — MSG_DESCRIPTION_COMMAND can fire while Draw is running, and
        # Take/RenderData mutation is not safe against a live draw thread. Only
        # for the mutating actions (the selection-only paths still guard below).
        if command_id in _ACTION_IDS:
            stop_all = getattr(c4d, "StopAllThreads", None)
            if callable(stop_all):
                try:
                    stop_all()
                except Exception:
                    pass
        if command_id in _ACTION_IDS and not _host_is_valid_camera(node):
            _show_message("Sentinel Frame must be placed on a supported Camera.")
            return True
        if command_id == ID_CREATE_UPDATE_TAKES:
            return self._handle_create_update_takes(node, doc)
        if command_id == ID_SET_OUTPUT:
            return self._handle_set_output(node, doc)
        if command_id == ID_REMOVE_STALE:
            return self._handle_remove_stale(node, doc)
        if command_id == ID_MARK_SUBJECT:
            return self._handle_mark_subject(node, doc)
        return True

    def Draw(self, tag, op, bd, bh):
        global _DRAW_CALLS

        try:
            if bd.GetDrawPass() != c4d.DRAWPASS_OBJECT:
                return True
        except Exception:
            return True

        if not is_valid_camera_host(_node_type(op)):
            return True

        doc = None
        for owner in (tag, op):
            getter = getattr(owner, "GetDocument", None)
            if callable(getter):
                try:
                    doc = getter()
                    if doc is not None:
                        break
                except Exception:
                    pass
        if doc is None:
            try:
                doc = c4d.documents.GetActiveDocument()
            except Exception:
                doc = None

        try:
            if bd.GetSceneCamera(doc) != op:
                return True
        except Exception:
            return True

        # Don't draw guides when viewing one of our own format takes: the camera
        # is already cropped to that format, so the guides would draw a
        # crop-of-a-crop. Guides live in the master (Main) view; format takes
        # show the clean final crop — plus a minimal HUD saying WHAT you are
        # viewing (Frame v2), since without guides there is no other cue.
        own_info = _current_own_take_info(tag, doc)
        if own_info is not None:
            own_fmt, own_sfx = own_info
            if _as_bool(_get_node_value(tag, ID_SHOW_HUD, True), True):
                sf = _safe_frame_rect(bd)
                if sf is not None:
                    w_px, h_px = _slice_dims(tag, own_fmt, own_sfx)
                    try:
                        bd.SetMatrix_Screen()
                    except Exception:
                        return True
                    if own_sfx:
                        text = "Viewing: %s %s  %dx%d  %s" % (
                            own_fmt, own_sfx, w_px, h_px, _sync_status_text(tag),
                        )
                    else:
                        text = "Viewing: %s  %dx%d  %s" % (
                            own_fmt, w_px, h_px, _sync_status_text(tag),
                        )
                    _draw_hud_text(bd, sf[0] + 8, sf[1] + 8, text)
            return True

        if not _as_bool(_get_node_value(tag, ID_ENABLED, True), True):
            return True

        safe_frame = _safe_frame_rect(bd)
        if safe_frame is None:
            return True

        master_aspect = _master_aspect_from_safe_frame(safe_frame) or _master_aspect_for_doc(doc)
        rects = _compute_inline_rects(tag, master_aspect)
        if not rects:
            return True

        show_guides = _as_bool(_get_node_value(tag, ID_SHOW_GUIDES, True), True)
        show_mask = _as_bool(_get_node_value(tag, ID_SHOW_MASK, False), False)
        show_platform = _as_bool(_get_node_value(tag, ID_SHOW_PLATFORM, False), False)
        show_hud = _as_bool(_get_node_value(tag, ID_SHOW_HUD, True), True)

        try:
            bd.SetMatrix_Screen()
        except Exception:
            return True

        pixel_guides = []
        for entry in rects:
            guide_px = _ndc_rect_to_pixels(entry["guide"], safe_frame)
            if guide_px[2] - guide_px[0] < 1.0 or guide_px[3] - guide_px[1] < 1.0:
                continue
            pixel_guides.append((entry, guide_px))

        if show_mask and pixel_guides:
            intersection = _intersect_ndc_rects(entry["guide"] for entry, _guide_px in pixel_guides)
            if intersection is not None:
                mask_px = _ndc_rect_to_pixels(intersection, safe_frame)
                opacity = max(0.0, min(1.0, _as_float(_get_node_value(tag, ID_MASK_OPACITY, 0.5), 0.5)))
                mask_transparency = -int(round(255.0 * (1.0 - opacity)))
                _draw_mask(bd, safe_frame, mask_px, c4d.Vector(0.0, 0.0, 0.0), mask_transparency)

        if show_guides:
            # Frame v2 focus dimming: the last-touched format row draws at full
            # intensity, the rest multiplied by Dim (1.0 = effect off, 0.0 =
            # hidden). Line opacity approximates alpha by scaling the color
            # toward the dark viewport (BaseDraw lines have no true alpha).
            focus = 0
            try:
                focus = int(_bc_get_data(_node_data_container(tag), ID_PRIVATE_FOCUS_FORMAT) or 0)
            except Exception:
                focus = 0
            focus_fmt = None
            defs = _format_defs(tag)
            if 0 < focus <= len(defs):
                focus_fmt = defs[focus - 1].get("id")
            dim = max(0.0, min(1.0, _as_float(_get_node_value(tag, ID_DIM_NONVIEWED, 0.7), 0.7)))
            line_opacity = max(0.0, min(1.0, _as_float(_get_node_value(tag, ID_LINE_OPACITY, 1.0), 1.0)))
            line_width = max(1, int(round(_as_float(_get_node_value(tag, ID_LINE_WIDTH, 2.0), 2.0))))
            for entry, guide_px in pixel_guides:
                color = entry["color"]
                if focus_fmt is not None and entry["id"] != focus_fmt:
                    if dim <= 0.0:
                        continue
                    color = _dim_color(color, dim)
                if line_opacity < 1.0:
                    color = _dim_color(color, line_opacity)
                _draw_rect(bd, guide_px, color, width=line_width)
                sx, sy = entry.get("slices", (1, 1))
                if sx * sy > 1:
                    for (nx1, ny1), (nx2, ny2) in _slice_cut_segments(
                        entry["guide"], sx, sy, entry["width"], entry["height"]
                    ):
                        p1 = c4d.Vector(*_ndc_point_to_pixels((nx1, ny1), safe_frame), 0)
                        p2 = c4d.Vector(*_ndc_point_to_pixels((nx2, ny2), safe_frame), 0)
                        _draw_dashed_line(bd, p1, p2, 1)

        if show_platform and pixel_guides:
            for entry, _guide_px in pixel_guides:
                platform_px = _ndc_rect_to_pixels(entry["platform"], safe_frame)
                platform_color = _dim_color(entry["color"], 0.62)
                _draw_rect(bd, platform_px, platform_color, width=1, dashed=True)
            # ONE vintage footnote for all zones (platform UI specs change over
            # time) at the bottom-left — not repeated on every rectangle, which
            # cluttered the viewport.
            _draw_hud_text(
                bd,
                safe_frame[0] + 8,
                safe_frame[3] - 18,
                f"Platform safe zones · as of {PLATFORM_SAFE_AREA_AS_OF}",
            )

        if show_hud:
            # Frame v2 HUD, iteration 2 (live design feedback): a corner
            # legend DIVORCES each label from its rectangle (mental color→
            # rect mapping). The viewfinder/gate-label convention instead:
            # the label lives ON its own rect — short text (`9x16` + color
            # chip, resolution lives in the AM/panel and in the format-take
            # HUD) anchored at the rect's own top-left corner. Nested rects
            # differ in X, so anchors separate naturally; a deterministic
            # stagger drops a label one line when two would overlap in the
            # same row (the v1 collision cause was long labels + a shared
            # anchor corner).
            hud_x = safe_frame[0] + 8
            hud_y = safe_frame[1] + 8
            _draw_hud_text(bd, hud_x, hud_y, "Viewing: Master  %s" % _sync_status_text(tag))

            label_focus = 0
            try:
                label_focus = int(_bc_get_data(_node_data_container(tag), ID_PRIVATE_FOCUS_FORMAT) or 0)
            except Exception:
                label_focus = 0
            label_focus_fmt = None
            label_defs = _format_defs(tag)
            if 0 < label_focus <= len(label_defs):
                label_focus_fmt = label_defs[label_focus - 1].get("id")
            label_dim = max(0.0, min(1.0, _as_float(_get_node_value(tag, ID_DIM_NONVIEWED, 0.7), 0.7)))

            # Anchor each label at its own rect's inner top-left; stagger a
            # line lower while it would overlap an already-placed label.
            placed = []  # (x_left, x_right, y_row)
            row_h = 18.0
            for entry, guide_px in sorted(pixel_guides, key=lambda p: (p[1][0], p[1][1])):
                lx = guide_px[0] + 5
                ly = guide_px[1] + 5
                approx_w = 16 + 7.5 * len(str(entry["id"]))
                while any(
                    abs(ly - py) < row_h and lx < pr and (lx + approx_w) > pl
                    for pl, pr, py in placed
                ):
                    ly += row_h
                placed.append((lx, lx + approx_w, ly))
                chip_color = entry["color"]
                if label_focus_fmt is not None and entry["id"] != label_focus_fmt:
                    chip_color = _dim_color(chip_color, max(0.25, label_dim))
                _draw_color_chip(bd, lx, ly + 3, 9, chip_color)
                _draw_hud_text(bd, lx + 14, ly, str(entry["id"]))

            # Slice numbering: only for the focused format (or the sole
            # enabled one) — otherwise every slice grid across every visible
            # format would carpet the viewport with labels (spec noise rule).
            for entry, guide_px in pixel_guides:
                sx, sy = entry.get("slices", (1, 1))
                if sx * sy <= 1:
                    continue
                if len(pixel_guides) != 1 and entry["id"] != label_focus_fmt:
                    continue
                windows = framing.slice_windows(
                    (entry["guide"]["left"], entry["guide"]["top"],
                     entry["guide"]["right"], entry["guide"]["bottom"]),
                    sx, sy, entry["width"], entry["height"],
                )
                for ordinal, (sub, _w_px, _h_px, _sfx) in enumerate(windows, start=1):
                    sub_left, sub_top, _sub_right, _sub_bottom = sub
                    px, py = _ndc_point_to_pixels((sub_left, sub_top), safe_frame)
                    _draw_hud_text(bd, px + 4, py + 4, "s%d" % ordinal)

            comp = _get_node_value(tag, ID_COMPOSITION, COMPOSITION_CROP)
            if comp == COMPOSITION_OFF:
                _draw_hud_text(
                    bd, hud_x, hud_y + 22,
                    "None: guides are reference only - no crop",
                )

        _DRAW_CALLS += 1
        return True

    def Execute(self, tag, doc, op, bt, priority, flags):
        # Catch-all drift detection (see _observe_signature_drift): the AM's
        # right-click reset and programmatic writes never send
        # POSTSETPARAMETER, but every change re-evaluates the scene.
        _observe_signature_drift(tag)
        return c4d.EXECUTIONRESULT_OK

    def Message(self, node, mid, data):
        description_command = getattr(c4d, "MSG_DESCRIPTION_COMMAND", None)
        if description_command is not None and mid == description_command:
            return self._handle_command(node, data)

        # Frame v2 auto-sync trigger: after any AM parameter write, compare the
        # takes-relevant signature against the last one this hook OBSERVED
        # (2501). Display toggles never change that signature, so they never
        # trigger; a fresh tag / v1.8.0 scene seeds 2501 silently on first
        # touch (adoption) instead of regenerating takes unprompted. The sync
        # itself runs later, debounced, from the FrameSyncMessageData tick —
        # NEVER here (parameter messages must not mutate document structure).
        post_set = getattr(c4d, "MSG_DESCRIPTION_POSTSETPARAMETER", None)
        if post_set is not None and mid == post_set:
            _observe_signature_drift(node)
            # Viewport focus (dimming): touching a per-format row focuses that
            # format; touching a global param returns to all-equal.
            try:
                changed = None
                try:
                    changed = _desc_level_id(data["descid"])
                except Exception:
                    changed = None
                if changed is not None:
                    span = FORMAT_ROW_COUNT * ID_FORMAT_STRIDE
                    if ID_FORMAT_BASE <= changed < ID_FORMAT_BASE + span:
                        index = (changed - ID_FORMAT_BASE) // ID_FORMAT_STRIDE
                        _bc_set_data(
                            _node_data_container(node),
                            ID_PRIVATE_FOCUS_FORMAT, int(index) + 1)
                    elif changed in (
                        ID_ENABLED, ID_COMPOSITION, ID_SHOW_GUIDES,
                        ID_SHOW_MASK, ID_SHOW_PLATFORM, ID_SHOW_HUD,
                        ID_MASK_OPACITY, ID_VIEWING,
                    ):
                        _bc_set_data(
                            _node_data_container(node),
                            ID_PRIVATE_FOCUS_FORMAT, 0)
            except Exception:
                pass

        # Keep the pre-resolved platform insets on the tag container fresh so
        # Draw stays read-only (it never resolves sentinel_rules.json itself).
        _refresh_platform_insets(node)
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
