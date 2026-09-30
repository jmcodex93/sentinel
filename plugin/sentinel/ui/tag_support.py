# -*- coding: utf-8 -*-
"""Shared Cinema 4D host adapters for Sentinel TagData plugins.

This module deliberately contains no Frame, Pin, or Variants lifecycle or
domain behaviour. Concrete tag modules keep ownership of their plugin IDs,
callbacks, storage, and user-facing actions.
"""

import c4d


def desc_level_id(cid):
    """Return the first level ID from a DescID, or coerce a plain ID."""
    try:
        return int(cid[0].id)
    except Exception:
        try:
            return int(cid)
        except Exception:
            return 0


def set_bc_value(bc, method_name, key, value):
    """Best-effort typed BaseContainer write with mapping fallback."""
    method = getattr(bc, method_name, None)
    if callable(method):
        try:
            method(key, value)
            return
        except Exception:
            pass
    try:
        bc[key] = value
    except Exception:
        pass


def node_creator_type(node, fallback_creator):
    """Resolve a node type for DescLevel.creator without leaking failures."""
    try:
        return node.GetType()
    except Exception:
        return fallback_creator


def description_parent(node, parameter_id, dtype, fallback_creator):
    """Build a one-level DescID with a caller-owned fallback creator."""
    return c4d.DescID(
        c4d.DescLevel(
            parameter_id,
            dtype,
            node_creator_type(node, fallback_creator),
        )
    )


def document_from_node(node):
    """Prefer the node's document, then the active Cinema 4D document."""
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


def is_main_thread():
    """Support both main-thread checker locations exposed by C4D builds."""
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


def safe_node_name(node, fallback=""):
    """Read a node name without allowing a dead C4D wrapper to escape."""
    getter = getattr(node, "GetName", None)
    if callable(getter):
        try:
            name = getter()
            if name:
                return str(name)
        except Exception:
            pass
    return str(fallback or "")


def event_add():
    """Request a C4D refresh on a best-effort basis."""
    try:
        c4d.EventAdd()
    except Exception:
        pass


def command_id_from_data(data):
    """Extract MSG_DESCRIPTION_COMMAND's ID from its message container."""
    try:
        cid = data["id"]
    except Exception:
        cid = None
    return desc_level_id(cid)


def add_description_parameter(
    node,
    description,
    parameter_id,
    dtype,
    name,
    parent,
    fallback_creator,
    *,
    animatable=True,
    minimum=None,
    maximum=None,
    step=None,
    unit=None,
    cycle=None,
    custom_gui=None,
):
    """Add one dynamic parameter using only caller-supplied presentation."""
    desc_id = description_parent(node, parameter_id, dtype, fallback_creator)
    bc = c4d.GetCustomDatatypeDefault(dtype)
    set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
    set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)

    if not animatable:
        animate_off = getattr(c4d, "DESC_ANIMATE_OFF", None)
        if animate_off is not None:
            set_bc_value(bc, "SetInt32", c4d.DESC_ANIMATE, animate_off)
    if minimum is not None:
        minimum = float(minimum)
        set_bc_value(bc, "SetFloat", c4d.DESC_MIN, minimum)
        set_bc_value(bc, "SetFloat", c4d.DESC_MINSLIDER, minimum)
    if maximum is not None:
        maximum = float(maximum)
        set_bc_value(bc, "SetFloat", c4d.DESC_MAX, maximum)
        set_bc_value(bc, "SetFloat", c4d.DESC_MAXSLIDER, maximum)
    if step is not None:
        set_bc_value(bc, "SetFloat", c4d.DESC_STEP, float(step))
    if unit is not None:
        set_bc_value(bc, "SetInt32", c4d.DESC_UNIT, unit)
    if custom_gui is not None:
        set_bc_value(bc, "SetInt32", c4d.DESC_CUSTOMGUI, custom_gui)
    if cycle is not None:
        cycle_bc = c4d.BaseContainer()
        for value, label in cycle:
            set_bc_value(cycle_bc, "SetString", int(value), label)
        set_bc_value(bc, "SetContainer", c4d.DESC_CYCLE, cycle_bc)

    try:
        return bool(description.SetParameter(desc_id, bc, parent))
    except Exception:
        return False


def add_description_group(
    node,
    description,
    group_id,
    name,
    parent,
    fallback_creator,
    *,
    columns=None,
    titlebar=True,
):
    """Add one dynamic description group with explicit layout options."""
    desc_id = description_parent(
        node,
        group_id,
        c4d.DTYPE_GROUP,
        fallback_creator,
    )
    bc = c4d.GetCustomDatatypeDefault(c4d.DTYPE_GROUP)
    set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
    set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
    set_bc_value(bc, "SetBool", c4d.DESC_TITLEBAR, bool(titlebar))
    set_bc_value(bc, "SetBool", c4d.DESC_DEFAULT, False)
    if columns is not None:
        set_bc_value(bc, "SetInt32", c4d.DESC_COLUMNS, int(columns))
    try:
        return bool(description.SetParameter(desc_id, bc, parent))
    except Exception:
        return False
