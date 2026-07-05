# -*- coding: utf-8 -*-
"""Sentinel Frame camera tag registration surface.

This module intentionally keeps U2 minimal: parameter/default wiring,
host gating, and a draw-thread smoke counter. Actual guide/mask/HUD drawing
and button command handling land in later units.
"""

import c4d
from c4d import plugins

from sentinel import framing
from sentinel.multiformat import MULTIFORMAT_DEFS, get_multiformat_def


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


def _vector(rgb):
    try:
        return c4d.Vector(float(rgb[0]), float(rgb[1]), float(rgb[2]))
    except Exception:
        return rgb


def _node_creator_type(node):
    try:
        return node.GetType()
    except Exception:
        return SENTINEL_FRAME_TAG_PLUGIN_ID


def _description_parent(param_id, dtype, node):
    return c4d.DescID(c4d.DescLevel(param_id, dtype, _node_creator_type(node)))


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

        _DRAW_CALLS += 1
        return True

    def Message(self, node, mid, data):
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
