# -*- coding: utf-8 -*-
"""Sentinel Frame camera tag registration and viewport drawing surface."""

import c4d
from c4d import plugins

from sentinel import framing
from sentinel.common.settings import GlobalSettings
from sentinel.multiformat import MULTIFORMAT_DEFS, get_multiformat_def
from sentinel.rules import get_active_rules
from sentinel.safe_areas import format_safe_area_in_master_ndc, resolve_take_projection_params
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

# Per-format params: 1100s+, fixed stride per MULTIFORMAT_DEFS entry.
ID_FORMAT_BASE = 1100
ID_FORMAT_STRIDE = 20

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

COMPOSITION_CYCLE = (
    (COMPOSITION_OFF, "Off"),
    (COMPOSITION_PRESERVE_VERTICAL, "Preserve Vertical"),
    (COMPOSITION_PRESERVE_HORIZONTAL, "Preserve Horizontal"),
    (COMPOSITION_CROP, "Crop"),
    (COMPOSITION_RESIZE_CANVAS, "Resize Canvas"),
)

COMPOSITION_MODE_TO_FRAMING = {
    COMPOSITION_OFF: framing.COMPENSATE_OFF,
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

_RECT_CACHE_BY_NODE = {}


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


def _node_cache_key(node):
    try:
        guid = node.GetGUID()
        if guid is not None:
            return str(guid)
    except Exception:
        pass
    return id(node)


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
        entries.append((fmt, color, nudge))
    return entries


def _params_signature(node):
    signature = [
        bool(_get_node_value(node, ID_ENABLED, True)),
        bool(_get_node_value(node, ID_SHOW_GUIDES, True)),
        bool(_get_node_value(node, ID_SHOW_MASK, False)),
        bool(_get_node_value(node, ID_SHOW_PLATFORM, False)),
        bool(_get_node_value(node, ID_SHOW_HUD, True)),
    ]
    for fmt, color, nudge in _enabled_format_entries(node):
        try:
            color_sig = (
                round(float(color.x), 4),
                round(float(color.y), 4),
                round(float(color.z), 4),
            )
        except Exception:
            color_sig = (0.6, 0.6, 0.6)
        signature.append((fmt.get("id"), color_sig, round(nudge[0], 4), round(nudge[1], 4)))
    return tuple(signature)


def _compute_rect_cache(node, doc):
    rules_context = _active_rules_for_doc(doc)
    master_aspect = _master_aspect_for_doc(doc)
    formats = []
    for fmt, color, nudge in _enabled_format_entries(node):
        fmt_id = fmt.get("id")
        try:
            guide = framing.crop_rect_in_master_ndc(
                fmt.get("width", 1),
                fmt.get("height", 1),
                master_aspect,
                nudge,
            )
            safe_rect = format_safe_area_in_master_ndc(
                fmt_id,
                master_aspect,
                rules_context,
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
    return {
        "signature": _params_signature(node),
        "rules_identity": getattr(rules_context, "identity", None),
        "master_aspect": master_aspect,
        "formats": formats,
    }


def _invalidate_rect_cache(node):
    _RECT_CACHE_BY_NODE.pop(_node_cache_key(node), None)


def _refresh_rect_cache_if_needed(node, force=False):
    if node is None or not _is_main_thread():
        return False
    doc = _doc_from_node(node)
    if doc is None:
        return False
    key = _node_cache_key(node)
    current = _RECT_CACHE_BY_NODE.get(key)
    signature = _params_signature(node)
    try:
        rules_identity = getattr(_active_rules_for_doc(doc), "identity", None)
    except Exception:
        rules_identity = None
    if (
        not force
        and current is not None
        and current.get("signature") == signature
        and current.get("rules_identity") == rules_identity
    ):
        return False
    cache = _compute_rect_cache(node, doc)
    _RECT_CACHE_BY_NODE[key] = cache
    return True


def _cached_rects(node):
    cache = _RECT_CACHE_BY_NODE.get(_node_cache_key(node))
    if not cache:
        return []
    return list(cache.get("formats") or [])


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


def _draw_mask(bd, safe_frame, guide_rect, color):
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
            bd.SetTransparency(MASK_TRANSPARENCY)
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

        _set_node_value(node, ID_ENABLED, True)
        _set_node_value(node, ID_COMPOSITION, COMPOSITION_OFF)
        _set_node_value(node, ID_SHOW_GUIDES, True)
        _set_node_value(node, ID_SHOW_MASK, False)
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

        _invalidate_rect_cache(node)
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
            (ID_SHOW_PLATFORM, c4d.DTYPE_BOOL, "Show Platform Zones", None, None, None, None),
            (ID_SHOW_HUD, c4d.DTYPE_BOOL, "Show HUD", None, None, None, None),
            (ID_SCHEMA_VERSION, c4d.DTYPE_LONG, "Schema Version", None, None, None, None),
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
            if not self._set_description_parameter(
                node, description, ids["nudge_x"], c4d.DTYPE_REAL, "Nudge X %", format_group, -100.0, 100.0, 1.0
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["nudge_y"], c4d.DTYPE_REAL, "Nudge Y %", format_group, -100.0, 100.0, 1.0
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

        rects = _cached_rects(tag)
        if not rects:
            return True

        safe_frame = _safe_frame_rect(bd)
        if safe_frame is None:
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
                _draw_mask(bd, safe_frame, mask_px, c4d.Vector(0.0, 0.0, 0.0))

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
            if bool(getattr(tag, "_stale", False)):
                _draw_hud_text(bd, safe_frame[0] + 8, safe_frame[1] + 26, "Takes out of date")

        _DRAW_CALLS += 1
        return True

    def Message(self, node, mid, data):
        force_refresh = False
        post_set = getattr(c4d, "MSG_DESCRIPTION_POSTSETPARAMETER", None)
        if post_set is not None and mid == post_set:
            force_refresh = True
            _invalidate_rect_cache(node)
        cache_refreshed = _refresh_rect_cache_if_needed(node, force=force_refresh)
        if force_refresh or cache_refreshed:
            _notify_overlay_suppression_changed(node)
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
