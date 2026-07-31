# -*- coding: utf-8 -*-
"""Sentinel Pin tag: registration, Attribute Manager rows, and storing a pin.

Stores up to six named states (transform + parameters, per object, for the
tagged object and every descendant) directly in the tag's own container —
no sidecar file. The nested-BaseContainer round-trip through save/reload,
the single-undo-step contract, and the ``isinstance(obj, c4d.PointObject)``
geometry test are all measured facts from the Task 1 spike
(docs/research/2026-07-31-pin-storage-spike.md), not assumptions.

Restoring a stored pin back onto the scene is Task 4 — the "Ir" button here
is wired to the description but its handler is intentionally a no-op.
"""

import datetime

import c4d
from c4d import plugins

from sentinel import pins

SENTINEL_PIN_TAG_PLUGIN_ID = 2099078
SENTINEL_PIN_TAG_DESCRIPTION = "Tsentinelpin"

# --- Description id layout ------------------------------------------------
# Slots are strided so a row's ids are derivable, same discipline as
# frame_tag._format_ids: nothing here is hand-numbered per row.
ID_GROUP_SLOTS = 1000
ID_SLOT_SEPARATOR = 1900  # full-width DTYPE_SEPARATOR before the reserved row
ID_SLOT_BASE = 2000       # slot i occupies ID_SLOT_BASE + i * ID_SLOT_STRIDE
ID_SLOT_STRIDE = 10
ID_SLOT_LABEL = 0         # DTYPE_STRING  — editable name (artist slots only)
ID_SLOT_INFO = 1          # DTYPE_STRING  — derived, "12 obj · hace 2 h"
ID_SLOT_STORE = 2         # DTYPE_BUTTON  — "Pin aquí" / "Re-pin"
ID_SLOT_GO = 3            # DTYPE_BUTTON  — "Ir"
ID_SLOT_CLEAR = 4         # DTYPE_BUTTON  — "✕"

#: Pin payloads live under a private container id inside the tag's own
#: container, so they travel with the .c4d (Task 1 step 1 proved the
#: round-trip). Kept well clear of the description id range above.
ID_PIN_STORE_BASE = 20000

#: Bumped only if the payload shape changes. A pin whose schema this build
#: does not know is IGNORED with a note in its row — never applied
#: partially, because a half-applied rig is worse than an untouched one.
PIN_SCHEMA = 1

# Sub-keys inside each stored payload BaseContainer (namespace is private to
# that container instance — no collision risk with the ids above). The
# object's own container and matrix are stored WHOLE (SetContainer/SetMatrix,
# both verified round-trip in the Task 1 spike), never decomposed.
_PAYLOAD_SCHEMA = 1
_PAYLOAD_TIMESTAMP = 2
_PAYLOAD_COUNT = 3
_PAYLOAD_ENTRIES = 4
_ENTRY_KEY = 1
_ENTRY_NAME = 2
_ENTRY_GEOMETRY = 3
_ENTRY_CONTAINER = 4
_ENTRY_MATRIX = 5


def _slot_ids(index):
    base = ID_SLOT_BASE + index * ID_SLOT_STRIDE
    return {"label": base + ID_SLOT_LABEL, "info": base + ID_SLOT_INFO,
            "store": base + ID_SLOT_STORE, "go": base + ID_SLOT_GO,
            "clear": base + ID_SLOT_CLEAR}


def _slot_from_id(param_id):
    """(slot index, action) for a pressed button id, or (None, None)."""
    offset = param_id - ID_SLOT_BASE
    if offset < 0:
        return None, None
    index, action = divmod(offset, ID_SLOT_STRIDE)
    if index > pins.RESERVED_SLOT:
        return None, None
    return index, {ID_SLOT_STORE: "store", ID_SLOT_GO: "go",
                   ID_SLOT_CLEAR: "clear"}.get(action)


def _slot_index_for_info_id(param_id):
    """Row index for an INFO cell id, or None — the info text is a derived
    field (like frame_tag's ID_SYNC_STATUS), never a real stored value, so
    it needs its own lookup distinct from the button action map above."""
    offset = param_id - ID_SLOT_BASE
    if offset < 0:
        return None
    index, action = divmod(offset, ID_SLOT_STRIDE)
    if action != ID_SLOT_INFO or index > pins.RESERVED_SLOT:
        return None
    return index


# --- Small c4d helpers (copied pattern from frame_tag.py, not imported —
# these two tags are independent plugins and should not couple through
# private helpers) ----------------------------------------------------------

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


def _desc_level_id(cid):
    try:
        return int(cid[0].id)
    except Exception:
        try:
            return int(cid)
        except Exception:
            return 0


def _node_creator_type(node):
    try:
        return node.GetType()
    except Exception:
        return SENTINEL_PIN_TAG_PLUGIN_ID


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


def _event_add():
    try:
        c4d.EventAdd()
    except Exception:
        pass


def _command_id_from_data(data):
    try:
        cid = data["id"]
    except Exception:
        cid = None
    return _desc_level_id(cid)


# --- Timestamp formatting (Spanish, matches the rest of the row's copy) ---

def _now_iso():
    return datetime.datetime.now().isoformat()


def _relative_time_es(timestamp_iso):
    if not timestamp_iso:
        return ""
    try:
        then = datetime.datetime.fromisoformat(str(timestamp_iso))
    except Exception:
        return ""
    seconds = max(0, int((datetime.datetime.now() - then).total_seconds()))
    if seconds < 60:
        return "hace %ds" % seconds
    minutes = seconds // 60
    if minutes < 60:
        return "hace %d min" % minutes
    hours = minutes // 60
    if hours < 24:
        return "hace %d h" % hours
    days = hours // 24
    return "hace %d d" % days


# --- Object-tree walk (the c4d-side half of pins.location_keys' contract) -

def _children_of(obj):
    out = []
    child = obj.GetDown()
    while child is not None:
        out.append(child)
        child = child.GetNext()
    return out


def _walk_object_tree(obj):
    """Depth-first pre-order walk producing ``(location_tree, flat_nodes)``
    in the SAME order ``pins.location_keys`` assigns keys to
    ``location_tree`` — ``zip(pins.location_keys(location_tree), flat_nodes)``
    pairs each live c4d node with its own key. ``pins.location_keys`` is pure
    and knows nothing about c4d; this is the c4d-side half of that contract,
    mirroring its "append self, then walk children in order" traversal."""
    flat_nodes = []

    def visit(node):
        flat_nodes.append(node)
        return {
            "name": _safe_node_name(node, ""),
            "geometry": isinstance(node, c4d.PointObject),
            "children": [visit(child) for child in _children_of(node)],
        }

    tree = visit(obj)
    return tree, flat_nodes


# --- Stored payload: read + write ------------------------------------------

def _read_payload_bc(node, index):
    bc = node.GetDataInstance()
    if bc is None:
        return None
    return bc.GetContainerInstance(ID_PIN_STORE_BASE + index)


def _slot_is_filled(node, index):
    return _read_payload_bc(node, index) is not None


def _slot_info_text(node, index):
    """Text for the row's info cell, built from ``pins.slot_summary`` per
    the spec: count + relative time, and — REQUIRED, not optional — a
    "geometría no incluida" note whenever any pinned node has editable
    geometry, since points/polygons live outside the object's container and
    will not come back on restore.

    This is SYNTHESIZED, never stored: ``GetDParameter`` calls this on every
    read instead of the info cell holding a written value in the node's own
    container (verified live — ``GetDataInstance().GetString(id)`` for this
    id reads back empty, which is correct, not a bug). Storing the text
    would let the relative-time part ("hace 2 h") go stale the moment the
    AM stops repainting it; deriving it keeps it honest for free."""
    payload = _read_payload_bc(node, index)
    if payload is None:
        return ""
    schema = payload.GetInt32(_PAYLOAD_SCHEMA, 0)
    if schema != PIN_SCHEMA:
        return "pin de una versión anterior — no se aplicará"
    count = payload.GetInt32(_PAYLOAD_COUNT, 0)
    entries_bc = payload.GetContainerInstance(_PAYLOAD_ENTRIES)
    entries = []
    for i in range(count):
        entry_bc = entries_bc.GetContainerInstance(i) if entries_bc is not None else None
        geometry = bool(entry_bc.GetBool(_ENTRY_GEOMETRY, False)) if entry_bc is not None else False
        entries.append({"geometry": geometry})
    summary = pins.slot_summary({"label": "", "entries": entries})
    text = "%d obj · %s" % (summary["count"], _relative_time_es(payload.GetString(_PAYLOAD_TIMESTAMP, "")))
    if summary["has_geometry"]:
        text += " · geometría no incluida"
    return text


def _store_button_label(filled):
    return "Re-pin" if filled else "Pin aquí"


def _store_pin(node, slot_index):
    """Store the tag's object + every descendant into slot ``slot_index``.

    One undo step (StartUndo/AddUndo(CHANGE, node)/EndUndo) per the spec and
    the Task 1 spike's measured undo contract. Re-pinning an existing slot
    keeps whatever label the artist already gave it; a fresh slot is left
    with an empty label for them to fill — neither case needs code here,
    since this function never touches the label id at all.
    """
    obj = node.GetObject()
    if obj is None:
        return False
    doc = _doc_from_node(node)
    if doc is None:
        return False

    tree, flat_nodes = _walk_object_tree(obj)
    keys = pins.location_keys(tree)
    entries = list(zip(flat_nodes, keys))

    payload_bc = c4d.BaseContainer()
    payload_bc.SetInt32(_PAYLOAD_SCHEMA, PIN_SCHEMA)
    payload_bc.SetString(_PAYLOAD_TIMESTAMP, _now_iso())
    payload_bc.SetInt32(_PAYLOAD_COUNT, len(entries))
    entries_bc = c4d.BaseContainer()
    for i, (child_obj, key) in enumerate(entries):
        entry_bc = c4d.BaseContainer()
        entry_bc.SetString(_ENTRY_KEY, key)
        entry_bc.SetString(_ENTRY_NAME, _safe_node_name(child_obj, ""))
        entry_bc.SetBool(_ENTRY_GEOMETRY, isinstance(child_obj, c4d.PointObject))
        entry_bc.SetContainer(_ENTRY_CONTAINER, child_obj.GetData())
        entry_bc.SetMatrix(_ENTRY_MATRIX, child_obj.GetMl())
        entries_bc.SetContainer(i, entry_bc)
    payload_bc.SetContainer(_PAYLOAD_ENTRIES, entries_bc)

    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
        node.GetDataInstance().SetContainer(ID_PIN_STORE_BASE + slot_index, payload_bc)
    finally:
        doc.EndUndo()
    return True


def _clear_pin(node, slot_index):
    """Erase a stored slot. The inverse of storing, not a restore — nothing
    here touches the scene graph, only the tag's own container."""
    doc = _doc_from_node(node)
    if doc is None:
        return False
    bc = node.GetDataInstance()
    if bc is None:
        return False
    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
        bc.RemoveData(ID_PIN_STORE_BASE + slot_index)
    finally:
        doc.EndUndo()
    return True


try:
    _TagDataBase = plugins.TagData
    if not isinstance(_TagDataBase, type):
        raise TypeError("plugins.TagData is not a class")
    _SENTINEL_PIN_TAG_AVAILABLE = True
except Exception:
    _TagDataBase = object
    _SENTINEL_PIN_TAG_AVAILABLE = False


class SentinelPinTag(_TagDataBase):
    """TagData shell for the Sentinel Pin six-slot state store."""

    def _init_attr(self, node, py_type, param_id):
        init_attr = getattr(self, "InitAttr", None)
        if callable(init_attr):
            try:
                init_attr(node, py_type, param_id)
            except Exception:
                pass

    def _set_description_parameter(
        self, node, description, parameter_id, dtype, name, parent,
        animatable=True,
    ):
        desc_id = _description_parent(parameter_id, dtype, node)
        bc = c4d.GetCustomDatatypeDefault(dtype)
        _set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
        _set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
        if not animatable:
            # Every row param is a state snapshot / an action trigger, never
            # something to keyframe — the Frame tag learned live that
            # animatable params render a diamond per row and the diamonds
            # were the biggest cost in row width (v1.29 polish, carried here
            # as a day-one constraint per the brief, not rediscovered).
            animate_off = getattr(c4d, "DESC_ANIMATE_OFF", None)
            if animate_off is not None:
                _set_bc_value(bc, "SetInt32", c4d.DESC_ANIMATE, animate_off)
        if dtype == c4d.DTYPE_BUTTON:
            # Without CUSTOMGUI_BUTTON a DTYPE_BUTTON renders as an empty
            # cell, not a clickable button (frame_tag.py:1775, confirmed live
            # in that tag — carried here rather than rediscovered).
            button_gui = getattr(c4d, "CUSTOMGUI_BUTTON", None)
            if button_gui is not None:
                _set_bc_value(bc, "SetInt32", c4d.DESC_CUSTOMGUI, button_gui)
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
        # Only the six artist slots have an editable label id — the reserved
        # slot (index pins.RESERVED_SLOT) has no label field at all (spec:
        # the artist does not name it), so there is nothing to init for it.
        for index in range(pins.MAX_SLOTS):
            ids = _slot_ids(index)
            self._init_attr(node, str, ids["label"])
            _set_node_value(node, ids["label"], "")
        return True

    def GetDDescription(self, node, description, flags):
        try:
            description.LoadDescription(node.GetType())
        except Exception:
            pass

        root = c4d.DescID(c4d.DescLevel(c4d.ID_TAGPROPERTIES))
        slots_group = _description_parent(ID_GROUP_SLOTS, c4d.DTYPE_GROUP, node)

        # ONE 5-column grid holds every row's cells directly (label, info,
        # store, go, clear) — per-row sub-groups each size their own columns
        # from their own label width, so nothing lines up vertically across
        # rows (frame_tag.py:1903-1910, the same reason this tag uses a
        # single grid instead of six).
        if not self._set_description_group(
            node, description, ID_GROUP_SLOTS, "Pins", root, columns=5, titlebar=False
        ):
            return False

        for index in range(pins.MAX_SLOTS):
            ids = _slot_ids(index)
            filled = _slot_is_filled(node, index)
            if not self._set_description_parameter(
                node, description, ids["label"], c4d.DTYPE_STRING, "", slots_group,
                animatable=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["info"], c4d.DTYPE_STRING, "", slots_group,
                animatable=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["store"], c4d.DTYPE_BUTTON,
                _store_button_label(filled), slots_group, animatable=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["go"], c4d.DTYPE_BUTTON, "Ir", slots_group,
                animatable=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, ids["clear"], c4d.DTYPE_BUTTON, "✕", slots_group,
                animatable=False
            ):
                return False

        # Reserved row: a full-width separator, then just info + a single
        # "Ir" button — no label (the artist does not name this slot; the
        # tool owns it) and no Store/Clear (nothing to manually pin here
        # until Task 4's restore writes it).
        if not self._set_description_parameter(
            node, description, ID_SLOT_SEPARATOR, c4d.DTYPE_SEPARATOR, "", slots_group
        ):
            return False
        reserved_ids = _slot_ids(pins.RESERVED_SLOT)
        if not self._set_description_parameter(
            node, description, reserved_ids["info"], c4d.DTYPE_STRING, "", slots_group,
            animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, reserved_ids["go"], c4d.DTYPE_BUTTON, "Ir", slots_group,
            animatable=False
        ):
            return False

        return True, flags | c4d.DESCFLAGS_DESC_LOADED

    def GetDParameter(self, node, id, flags):
        # Info is a derived field (same pattern as frame_tag's
        # ID_SYNC_STATUS): it is never written into the node's real data, so
        # its text is always fresh — including the relative-time part, which
        # must keep advancing even when nothing has been re-pinned.
        parameter_id = _desc_level_id(id)
        index = _slot_index_for_info_id(parameter_id)
        if index is not None:
            return True, _slot_info_text(node, index), flags | c4d.DESCFLAGS_GET_PARAM_GET
        return False

    def SetDParameter(self, node, id, data, flags):
        parameter_id = _desc_level_id(id)
        index = _slot_index_for_info_id(parameter_id)
        if index is not None:
            # Read-only derived string: swallow writes.
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        index, action = _slot_from_id(parameter_id)
        if index is None:
            return True
        if index == pins.RESERVED_SLOT:
            # Tool-owned row: only "Ir" is ever actionable, and only once
            # Task 4 has written something into it.
            if action == "go":
                return _slot_is_filled(node, index)
            return False
        if action == "store":
            return True  # a slot that is empty shows only Store enabled
        if action in ("go", "clear"):
            return _slot_is_filled(node, index)
        return True

    def _handle_command(self, node, data):
        if not _is_main_thread():
            return True
        command_id = _command_id_from_data(data)
        index, action = _slot_from_id(command_id)
        if index is None or action is None:
            return True
        if action == "store":
            _store_pin(node, index)
            _event_add()
        elif action == "clear":
            _clear_pin(node, index)
            _event_add()
        elif action == "go":
            # Restore is Task 4 — deliberately not implemented here. A pin
            # whose schema this build does not recognise also lands here
            # forever (GetDEnabling still allows it since the slot IS
            # filled) — that is fine, Task 4 owns the schema-mismatch guard
            # for the actual restore, not this stub.
            pass
        return True

    def Message(self, node, mid, data):
        description_command = getattr(c4d, "MSG_DESCRIPTION_COMMAND", None)
        if description_command is not None and mid == description_command:
            return self._handle_command(node, data)
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
