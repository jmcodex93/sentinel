# -*- coding: utf-8 -*-
"""Sentinel Frame camera tag registration and viewport drawing surface."""

import hashlib
import json

import c4d
from c4d import plugins

from sentinel import framing
from sentinel.common.settings import GlobalSettings
from sentinel.multiformat import (
    MULTIFORMAT_DEFS,
    compute_format_output_path,
    generate_multiformat_takes,
    get_multiformat_def,
)
from sentinel.rules import get_active_rules
from sentinel.safe_areas import (
    SAFE_AREA_INSETS,
    format_safe_area_in_master_ndc,
    is_object_marked_safe_area,
    mark_object_safe_area,
    resolve_take_projection_params,
    unmark_object_safe_area,
)
from sentinel.ui.overlay import _SAFE_AREA_COLORS


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

# Per-format params: 1100s+, fixed stride per MULTIFORMAT_DEFS entry.
ID_FORMAT_BASE = 1100
ID_FORMAT_STRIDE = 20

# Private per-format platform insets: stored on the tag container so Draw can
# stay read-only and avoid resolving sentinel_rules.json on the draw thread.
ID_PLATFORM_INSET_BASE = 2000
ID_PLATFORM_INSET_STRIDE = 10

# Private tag-owned state. These are intentionally not in the dynamic AM
# description: they are implementation details for U5 tracking/staleness.
ID_PRIVATE_TAKE_LINK_BASE = 2400
ID_PRIVATE_TAKE_LINK_STRIDE = 1
ID_PRIVATE_TAKES_SIGNATURE = 2500

# Actions: 3000s. Declared only in U2; command logic is U5.
ID_GROUP_ACTIONS = 3000
ID_CREATE_UPDATE_TAKES = 3001
ID_SET_OUTPUT = 3002
ID_REMOVE_STALE = 3003
ID_MARK_SUBJECT = 3004

COMPOSITION_OFF = 0
COMPOSITION_PRESERVE_VERTICAL = 1
COMPOSITION_PRESERVE_HORIZONTAL = 2
COMPOSITION_CROP = 3
COMPOSITION_RESIZE_CANVAS = 4

# Labels lead with what happens to the CAMERA so an artist can choose without
# reading docs. "Preserve Horizontal" is intentionally NOT offered: its focal
# math is a no-op (same in the C4DMultiFrame reference), so it would behave
# identically to "None" and only confuse. The constant + mapping below stay for
# forward-compat but the cycle does not expose it.
COMPOSITION_CYCLE = (
    (COMPOSITION_OFF, "None (camera unchanged)"),
    (COMPOSITION_PRESERVE_VERTICAL, "Preserve Vertical FOV (adjust lens)"),
    (COMPOSITION_CROP, "Fill / Zoom to Cover (adjust lens)"),
    (COMPOSITION_RESIZE_CANVAS, "Resize Sensor (keep lens & DOF)"),
)

COMPOSITION_MODE_TO_FRAMING = {
    COMPOSITION_OFF: "none",
    COMPOSITION_PRESERVE_VERTICAL: framing.COMPENSATE_PRESERVE_VERTICAL,
    COMPOSITION_PRESERVE_HORIZONTAL: framing.COMPENSATE_PRESERVE_HORIZONTAL,
    COMPOSITION_CROP: framing.COMPENSATE_CROP,
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
}


def is_valid_camera_host(obj_type_int):
    """Return True when ``obj_type_int`` is a supported camera type id."""
    return int(obj_type_int or 0) in (OCAMERA, ORSCAMERA)


def _format_defs():
    """Return the canonical multi-format definitions without duplicating data."""
    defs = []
    for fmt in MULTIFORMAT_DEFS:
        canonical = get_multiformat_def(fmt.get("id"))
        if canonical:
            defs.append(canonical)
    return defs


def _format_ids(index):
    base = ID_FORMAT_BASE + (index * ID_FORMAT_STRIDE)
    return {
        "group": base,
        "enabled": base + 1,
        "color": base + 2,
        "nudge_x": base + 3,
        "nudge_y": base + 4,
    }


def _format_param_map():
    mapping = {}
    for index, fmt in enumerate(_format_defs()):
        ids = _format_ids(index)
        mapping[ids["color"]] = ids["enabled"]
        mapping[ids["nudge_x"]] = ids["enabled"]
        mapping[ids["nudge_y"]] = ids["enabled"]
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
    for index, fmt in enumerate(_format_defs()):
        ids = _format_ids(index)
        if not _as_bool(_get_node_value(node, ids["enabled"], True), True):
            continue
        fmt_id = fmt.get("id")
        fallback = _SAFE_AREA_COLORS.get(fmt_id, _vector(_FORMAT_COLORS.get(fmt_id, (0.6, 0.6, 0.6))))
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


def _format_index_for_id(fmt_id):
    for index, fmt in enumerate(_format_defs()):
        if fmt.get("id") == fmt_id:
            return index
    return None


def composition_mode_for_engine(composition_id):
    """Map the tag LONG cycle value to the multiformat engine mode string."""
    try:
        mode_id = int(composition_id)
    except Exception:
        mode_id = COMPOSITION_OFF
    return COMPOSITION_MODE_TO_FRAMING.get(mode_id, "none")


def _enabled_format_ids_from_params(node):
    """Return enabled format ids in canonical UI order."""
    enabled = []
    for index, fmt in enumerate(_format_defs()):
        ids = _format_ids(index)
        if _as_bool(_get_node_value(node, ids["enabled"], True), True):
            enabled.append(fmt.get("id"))
    return enabled


def _film_offsets_from_params(node):
    """Build the engine film_offsets dict from enabled per-format nudges."""
    offsets = {}
    for index, fmt in enumerate(_format_defs()):
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
    for index, fmt in enumerate(_format_defs()):
        ids = _format_ids(index)
        if not _as_bool(_get_node_value(node, ids["enabled"], True), True):
            continue
        formats.append(
            {
                "id": fmt.get("id"),
                "nudge": [
                    round(_as_float(_get_node_value(node, ids["nudge_x"], 0.0), 0.0), 8),
                    round(_as_float(_get_node_value(node, ids["nudge_y"], 0.0), 0.0), 8),
                ],
            }
        )
    return {
        "composition_mode": composition_mode_for_engine(
            _get_node_value(node, ID_COMPOSITION, COMPOSITION_OFF)
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


def _standard_platform_insets_by_format():
    return {
        fmt.get("id"): _coerce_insets(SAFE_AREA_INSETS.get(fmt.get("id")), None)
        for fmt in _format_defs()
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
    for index, fmt in enumerate(_format_defs()):
        fmt_id = fmt.get("id")
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


def _ndc_rect_to_pixels(rect, safe_frame):
    cl, ct, cr, cb = safe_frame
    master_w = cr - cl
    master_h = cb - ct
    left = float(rect["left"])
    right = float(rect["right"])
    bottom = float(rect["bottom"])
    top = float(rect["top"])
    return (
        cl + (left + 1.0) * 0.5 * master_w,
        ct + (1.0 - top) * 0.5 * master_h,
        cl + (right + 1.0) * 0.5 * master_w,
        ct + (1.0 - bottom) * 0.5 * master_h,
    )


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


def _notify_overlay_suppression_changed(node):
    doc = _doc_from_node(node)
    if doc is None:
        return
    try:
        from sentinel.ui.overlay import _overlay_state

        _overlay_state.update_suppression_from_doc(doc)
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


def _write_take_link(node, fmt_id, take):
    index = _format_index_for_id(fmt_id)
    if index is None:
        return False
    bc = _node_data_container(node)
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
    return _bc_set_data(bc, _format_take_link_id(index), value)


def _read_take_link(node, fmt_id, doc=None):
    index = _format_index_for_id(fmt_id)
    if index is None:
        return None
    bc = _node_data_container(node)
    key = _format_take_link_id(index)
    getter = getattr(bc, "GetLink", None)
    if callable(getter):
        try:
            linked = getter(key, doc)
            if linked is not None:
                return linked
        except Exception:
            pass
    value = _bc_get_data(bc, key)
    link_getter = getattr(value, "GetLink", None)
    if callable(link_getter):
        try:
            return link_getter(doc)
        except Exception:
            return None
    return value


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


def _find_orphaned_takes_for_tag(node, doc):
    """Find disabled-format takes owned by this tag, never deleting them."""
    host = _tag_host(node)
    prefix = _safe_node_name(host, "")
    enabled = set(_enabled_format_ids_from_params(node))
    disabled_ids = {fmt.get("id") for fmt in _format_defs()} - enabled
    found = []
    seen = set()

    def _add(fmt_id, take):
        if take is None or fmt_id not in disabled_ids:
            return
        # Dedup by take name, not id(): the same take is reached by two paths
        # (stored BaseLink + name walk) and C4D hands out a fresh Python wrapper
        # per access, so id() would list — and then double-Remove() — one take
        # twice. Distinct takes keep distinct names, so this stays correct.
        try:
            marker = take.GetName()
        except Exception:
            marker = id(take)
        if marker in seen:
            return
        seen.add(marker)
        found.append((fmt_id, take))

    for fmt_id in disabled_ids:
        _add(fmt_id, _read_take_link(node, fmt_id, doc))

    try:
        take_data = doc.GetTakeData()
    except Exception:
        take_data = None
    name_to_id = {f"{prefix}_{fmt_id}": fmt_id for fmt_id in disabled_ids if prefix}
    for take in _walk_child_takes(take_data):
        try:
            _add(name_to_id.get(take.GetName()), take)
        except Exception:
            pass
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
    errors = report.get("errors") or []
    if errors:
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {err}" for err in errors)
    return "\n".join(lines)


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
        if dtype == c4d.DTYPE_REAL:
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

    def _set_description_group(self, node, description, group_id, name, parent):
        desc_id = _description_parent(group_id, c4d.DTYPE_GROUP, node)
        bc = c4d.GetCustomDatatypeDefault(c4d.DTYPE_GROUP)
        _set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
        _set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
        _set_bc_value(bc, "SetBool", c4d.DESC_TITLEBAR, True)
        _set_bc_value(bc, "SetBool", c4d.DESC_DEFAULT, False)
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

        _set_node_value(node, ID_ENABLED, True)
        _set_node_value(node, ID_COMPOSITION, COMPOSITION_OFF)
        _set_node_value(node, ID_SHOW_GUIDES, True)
        _set_node_value(node, ID_SHOW_MASK, False)
        _set_node_value(node, ID_MASK_OPACITY, 0.5)
        _set_node_value(node, ID_SHOW_PLATFORM, False)
        _set_node_value(node, ID_SHOW_HUD, True)
        _set_node_value(node, ID_SCHEMA_VERSION, SCHEMA_VERSION)

        for index, fmt in enumerate(_format_defs()):
            ids = _format_ids(index)
            self._init_attr(node, bool, ids["enabled"])
            self._init_attr(node, c4d.Vector, ids["color"])
            self._init_attr(node, float, ids["nudge_x"])
            self._init_attr(node, float, ids["nudge_y"])
            _set_node_value(node, ids["enabled"], True)
            _set_node_value(node, ids["color"], _vector(_FORMAT_COLORS.get(fmt["id"], (0.6, 0.6, 0.6))))
            _set_node_value(node, ids["nudge_x"], 0.0)
            _set_node_value(node, ids["nudge_y"], 0.0)

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
        try:
            description.LoadDescription(node.GetType())
        except Exception:
            pass

        root = c4d.DescID(c4d.DescLevel(c4d.ID_TAGPROPERTIES))
        core_group = _description_parent(ID_GROUP_CORE, c4d.DTYPE_GROUP, node)
        actions_group = _description_parent(ID_GROUP_ACTIONS, c4d.DTYPE_GROUP, node)

        if not self._set_description_group(node, description, ID_GROUP_CORE, "Sentinel Frame", root):
            return False

        core_params = (
            (ID_ENABLED, c4d.DTYPE_BOOL, "Enabled", None, None, None, None),
            (ID_COMPOSITION, c4d.DTYPE_LONG, "Composition Mode", None, None, None, COMPOSITION_CYCLE),
            (ID_SHOW_GUIDES, c4d.DTYPE_BOOL, "Show Guides", None, None, None, None),
            (ID_SHOW_MASK, c4d.DTYPE_BOOL, "Show Mask", None, None, None, None),
            (ID_MASK_OPACITY, c4d.DTYPE_REAL, "Mask Opacity", 0.0, 1.0, 0.01, None),
            (ID_SHOW_PLATFORM, c4d.DTYPE_BOOL, "Show Platform Zones", None, None, None, None),
            (ID_SHOW_HUD, c4d.DTYPE_BOOL, "Show HUD", None, None, None, None),
            # ID_SCHEMA_VERSION is internal migration state — kept in the tag
            # container (set in Init) but intentionally NOT exposed in the AM.
        )
        for parameter_id, dtype, name, minimum, maximum, step, cycle in core_params:
            if not self._set_description_parameter(
                node, description, parameter_id, dtype, name, core_group, minimum, maximum, step, cycle
            ):
                return False

        color_dtype = getattr(c4d, "DTYPE_COLOR", c4d.DTYPE_VECTOR)
        for index, fmt in enumerate(_format_defs()):
            ids = _format_ids(index)
            label = fmt.get("label") or fmt.get("id", "Format")
            format_group = _description_parent(ids["group"], c4d.DTYPE_GROUP, node)
            if not self._set_description_group(node, description, ids["group"], label, root):
                return False
            if not self._set_description_parameter(
                node, description, ids["enabled"], c4d.DTYPE_BOOL, "Enabled", format_group
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["color"], color_dtype, "Color", format_group
            ):
                return False
            # Nudge is a film-offset FRACTION (percent unit: raw 1.0 == 100%),
            # so the clamp is -1.0..1.0 (=-100%..100%), step 0.01 (=1%). Using
            # -100..100 here would read as +/-10000% under the percent unit.
            if not self._set_description_parameter(
                node, description, ids["nudge_x"], c4d.DTYPE_REAL, "Nudge X %", format_group, -1.0, 1.0, 0.01
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["nudge_y"], c4d.DTYPE_REAL, "Nudge Y %", format_group, -1.0, 1.0, 0.01
            ):
                return False

        if not self._set_description_group(node, description, ID_GROUP_ACTIONS, "Actions", root):
            return False
        action_params = (
            (ID_CREATE_UPDATE_TAKES, "Create/Update Takes"),
            (ID_SET_OUTPUT, "Set Output"),
            (ID_REMOVE_STALE, "Remove Stale Takes"),
            (ID_MARK_SUBJECT, "Mark Subject"),
        )
        for parameter_id, name in action_params:
            if not self._set_description_parameter(
                node, description, parameter_id, c4d.DTYPE_BUTTON, name, actions_group
            ):
                return False

        return True, flags | c4d.DESCFLAGS_DESC_LOADED

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

        prefix = _safe_node_name(host, "Camera")
        signature = _params_signature_for_takes(node)
        undo_added = [False]

        def _tag_link_writer(fmt_id, take):
            if not undo_added[0]:
                try:
                    doc.AddUndo(_undo_type_change(), node)
                except Exception:
                    pass
                undo_added[0] = True
            _write_take_link(node, fmt_id, take)

        options = {
            "formats": formats,
            "update_existing": True,
            "name_prefix": prefix,
            # This handler owns the undo block (StartUndo/EndUndo below) so the
            # take generation + BaseLink/signature writes revert as ONE Cmd+Z;
            # the engine must not open its own nested block.
            "external_undo": True,
            # Bind the generated Takes to THIS tag's host camera, not whatever
            # the viewport/Main take resolves to — the tag is per-camera.
            "source_cam": host,
            "composition_mode": composition_mode_for_engine(
                _get_node_value(node, ID_COMPOSITION, COMPOSITION_OFF)
            ),
            "film_offsets": _film_offsets_from_params(node),
            "tag_link_writer": _tag_link_writer,
            # Rename-safe re-run: re-find our own Takes by stored BaseLink even
            # if the take or the host camera was renamed (KTD4).
            "existing_take_resolver": lambda fmt_id: _read_take_link(node, fmt_id, doc),
        }

        doc.StartUndo()
        try:
            report = generate_multiformat_takes(doc, options)
            if not undo_added[0]:
                try:
                    doc.AddUndo(_undo_type_change(), node)
                except Exception:
                    pass
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
        for fmt_id, take in orphans:
            lines.append(f"- {_safe_node_name(take, fmt_id)}")
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
            for fmt_id, take in orphans:
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
                    _write_take_link(node, fmt_id, None)
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
            for entry, guide_px in pixel_guides:
                _draw_rect(bd, guide_px, entry["color"], width=2)

        if show_platform:
            for entry, _guide_px in pixel_guides:
                platform_px = _ndc_rect_to_pixels(entry["platform"], safe_frame)
                platform_color = _dim_color(entry["color"], 0.62)
                _draw_rect(bd, platform_px, platform_color, width=1, dashed=True)
                _draw_hud_text(
                    bd,
                    platform_px[0] + 4,
                    max(safe_frame[1] + 4, platform_px[1] + 18),
                    f"as of {PLATFORM_SAFE_AREA_AS_OF}",
                )

        if show_hud:
            for entry, guide_px in pixel_guides:
                text = f"{entry['id']}  {entry['width']}x{entry['height']}"
                _draw_hud_text(bd, guide_px[0] + 5, guide_px[1] + 5, text)
            if _is_stale_from_signature(tag):
                _draw_hud_text(bd, safe_frame[0] + 8, safe_frame[1] + 26, "Takes out of date")

        _DRAW_CALLS += 1
        return True

    def Message(self, node, mid, data):
        description_command = getattr(c4d, "MSG_DESCRIPTION_COMMAND", None)
        if description_command is not None and mid == description_command:
            return self._handle_command(node, data)

        force_refresh = False
        post_set = getattr(c4d, "MSG_DESCRIPTION_POSTSETPARAMETER", None)
        if post_set is not None and mid == post_set:
            force_refresh = True
        insets_refreshed = _refresh_platform_insets(node)
        if force_refresh or insets_refreshed:
            _notify_overlay_suppression_changed(node)
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
