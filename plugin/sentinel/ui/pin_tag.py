# -*- coding: utf-8 -*-
"""Sentinel Pin tag: registration, Attribute Manager row, and storing a pin.

One tag = one pin (rehecho tras ver en vivo el modelo de seis slots: el
texto de estado se truncaba y con él la advertencia de geometría, porque las
columnas del grid del Attribute Manager reparten ancho entre campos que
compiten. Y la interfaz real de Recall usa un tag por estado, que además
cumple mejor la promesa de fondo — "ves los estados en el Object Manager" —
sin necesitar layout alguno). Un pin guarda el estado (transform + parámetros,
por objeto, del objeto etiquetado y cada descendiente) directamente en el
contenedor propio del tag — sin sidecar. El round-trip de BaseContainer
anidado por save/reload, el contrato de un solo paso de undo, y el test de
geometría ``isinstance(obj, c4d.PointObject)`` son hechos medidos en el
spike de la Tarea 1 (docs/research/2026-07-31-pin-storage-spike.md), no
suposiciones.

Restaurar un pin sobre la escena es la Tarea 4 — el botón "Ir" está cableado
a la descripción pero su handler es deliberadamente un no-op.
"""

import datetime

import c4d
from c4d import plugins

from sentinel import pins
from sentinel.common.helpers import safe_print

SENTINEL_PIN_TAG_PLUGIN_ID = 2099078
SENTINEL_PIN_TAG_DESCRIPTION = "Tsentinelpin"

# --- Description id layout ------------------------------------------------
# Una sola fila: sin stride, porque no hay filas que derivar unas de otras.
ID_PIN_NAME = 1001      # DTYPE_STRING     — nombre del pin (= nombre del tag)
ID_PIN_STATUS = 1002    # DTYPE_STATICTEXT — "12 obj · hace 2 h · ..." (solo
                         # lectura: un DTYPE_STRING pinta una caja que
                         # compite por ancho con el resto de la fila, y fue
                         # justo eso lo que truncó el texto en la v6-slots)
ID_PIN_STORE = 1003     # DTYPE_BUTTON     — "Pin aquí" / "Re-pin"
ID_PIN_GO = 1004        # DTYPE_BUTTON     — "Ir"

#: El payload vive bajo un id de contenedor privado dentro del contenedor
#: propio del tag, así viaja con el .c4d (la Tarea 1 probó el round-trip).
#: Lejos del rango de ids de descripción de arriba.
ID_PIN_PAYLOAD = 20000

#: Resultado en texto de la última restauración desde ESTE tag (p.ej. "9 de
#: 12 restaurados · 3 no encontrados"). Se escribe directo en el contenedor
#: del tag — no forma parte de ``ID_PIN_PAYLOAD`` ni de su schema, así que
#: un build más nuevo nunca la confunde con datos de restauración. Se limpia
#: en cada (re-)pin para que la fila vuelva a mostrar el resumen del pin en
#: vez de dejar clavado el resultado de una restauración ya vieja.
ID_PIN_LAST_RESTORE = 20001

#: Se sube solo si cambia la forma del payload. Un pin cuyo esquema esta
#: build no reconoce se IGNORA con una nota en su fila — nunca se aplica a
#: medias, porque un rig medio-aplicado es peor que uno intacto.
PIN_SCHEMA = 1

# Sub-keys dentro del BaseContainer del payload (namespace privado a esa
# instancia de contenedor — sin riesgo de colisión con los ids de arriba).
# El contenedor y la matriz propios del objeto se guardan ENTEROS
# (SetContainer/SetMatrix, ambos verificados en el spike de la Tarea 1),
# nunca descompuestos.
_PAYLOAD_SCHEMA = 1
_PAYLOAD_TIMESTAMP = 2
_PAYLOAD_COUNT = 3
_PAYLOAD_ENTRIES = 4
_ENTRY_KEY = 1
_ENTRY_NAME = 2
_ENTRY_GEOMETRY = 3
_ENTRY_CONTAINER = 4
_ENTRY_MATRIX = 5
#: Cualquier CTrack (objeto o de sus tags) vuelve el valor guardado en un
#: no-op silencioso: la pista lo pisa en el siguiente frame. Es la mitad de
#: la advertencia obligatoria del spec, y la más fácil de pasar por alto
#: porque no hay nada visible que la delate en el momento de guardar.
_ENTRY_KEYFRAMES = 6


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


def _has_ctracks(node):
    """True si ``node`` o cualquiera de sus tags trae al menos una CTrack —
    mismo criterio de "está animado" que ``keyframes._shift_track_list``
    (Tools → keyframe offset/stagger, v1.30): CTracks de objeto Y de tags,
    porque un rig suele animar por el tag (constraints, XPresso) tanto como
    por el propio objeto."""
    try:
        if node.GetCTracks():
            return True
    except Exception:
        pass
    tag = node.GetFirstTag() if hasattr(node, "GetFirstTag") else None
    while tag is not None:
        try:
            if tag.GetCTracks():
                return True
        except Exception:
            pass
        tag = tag.GetNext()
    return False


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

def _read_payload_bc(node):
    bc = node.GetDataInstance()
    if bc is None:
        return None
    return bc.GetContainerInstance(ID_PIN_PAYLOAD)


def _pin_is_filled(node):
    return _read_payload_bc(node) is not None


def _read_last_restore(node):
    bc = node.GetDataInstance()
    if bc is None:
        return ""
    return bc.GetString(ID_PIN_LAST_RESTORE, "")


def _write_last_restore(node, text):
    bc = node.GetDataInstance()
    if bc is None:
        return
    bc.SetString(ID_PIN_LAST_RESTORE, text or "")


def _clear_last_restore(node):
    _write_last_restore(node, "")


def _pin_status_text(node):
    """Text for the row's status cell, built from ``pins.pin_summary`` per
    el spec: conteo + tiempo relativo, y — OBLIGATORIO, no opcional — una
    nota de "geometría no incluida" siempre que algún nodo pineado tenga
    geometría editable (los puntos/polígonos viven fuera del contenedor del
    objeto y no vuelven al restaurar), MÁS una nota de "N con keyframes"
    cuando algún nodo pineado está animado (restaurar su valor no cambia
    nada visible — la pista lo pisa en el siguiente frame).

    Esto se SINTETIZA, nunca se guarda: ``GetDParameter`` llama a esto en
    cada lectura en vez de que la celda de estado tenga un valor escrito en
    el contenedor propio del nodo (verificado en vivo —
    ``GetDataInstance().GetString(id)`` para este id lee vacío, que es
    correcto, no un bug). Guardar el texto dejaría que la parte de tiempo
    relativo ("hace 2 h") se quedara obsoleta en cuanto el AM dejara de
    repintarla; derivarlo la mantiene honesta gratis."""
    payload = _read_payload_bc(node)
    if payload is None:
        return ""
    schema = payload.GetInt32(_PAYLOAD_SCHEMA, 0)
    if schema != PIN_SCHEMA:
        # Checked before the last-restore note on purpose: a mismatched
        # schema is never applied, so this message must win over whatever
        # a previous (older-build) restore happened to leave behind.
        return "pin de una versión anterior — no se aplicará"
    last_restore = _read_last_restore(node)
    if last_restore:
        return last_restore
    count = payload.GetInt32(_PAYLOAD_COUNT, 0)
    entries_bc = payload.GetContainerInstance(_PAYLOAD_ENTRIES)
    entries = []
    for i in range(count):
        entry_bc = entries_bc.GetContainerInstance(i) if entries_bc is not None else None
        geometry = bool(entry_bc.GetBool(_ENTRY_GEOMETRY, False)) if entry_bc is not None else False
        keyframes = bool(entry_bc.GetBool(_ENTRY_KEYFRAMES, False)) if entry_bc is not None else False
        entries.append({"geometry": geometry, "keyframes": keyframes})
    summary = pins.pin_summary({"label": "", "entries": entries})
    text = "%d obj · %s" % (summary["count"], _relative_time_es(payload.GetString(_PAYLOAD_TIMESTAMP, "")))
    if summary["has_geometry"]:
        text += " · geometría no incluida"
    if summary["has_keyframes"]:
        text += " · %d con keyframes" % sum(1 for e in entries if e["keyframes"])
    return text


def _store_button_label(filled):
    return "Re-pin" if filled else "Pin aquí"


def _store_pin(node):
    """Store the tag's object + every descendant into the tag's own pin.

    One undo step (StartUndo/AddUndo(CHANGE, node)/EndUndo) per the spec and
    the Task 1 spike's measured undo contract. Re-pinning keeps whatever
    name the artist already gave the tag; a fresh pin is left with the
    tag's default name for them to rename — neither case needs code here,
    since this function never touches the name id at all.
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
        entry_bc.SetBool(_ENTRY_KEYFRAMES, _has_ctracks(child_obj))
        entry_bc.SetContainer(_ENTRY_CONTAINER, child_obj.GetData())
        entry_bc.SetMatrix(_ENTRY_MATRIX, child_obj.GetMl())
        entries_bc.SetContainer(i, entry_bc)
    payload_bc.SetContainer(_PAYLOAD_ENTRIES, entries_bc)

    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
        node.GetDataInstance().SetContainer(ID_PIN_PAYLOAD, payload_bc)
        # A (re-)pin overwrites what this tag now holds, so any leftover
        # "N restaurados" note from a previous restore is stale the moment
        # this write lands — otherwise the row would keep showing that old
        # result forever instead of the fresh pin summary.
        _clear_last_restore(node)
    finally:
        doc.EndUndo()
    return True


# --- Restore ----------------------------------------------------------------

def _read_pinned_entries(payload_bc):
    """Unpack a stored payload's entries into an ORDERED key list (the order
    the writer applied in, per the docstring of ``pins.location_keys``) plus
    a key -> {name, container, matrix} lookup for applying them."""
    count = payload_bc.GetInt32(_PAYLOAD_COUNT, 0)
    entries_container = payload_bc.GetContainerInstance(_PAYLOAD_ENTRIES)
    keys = []
    by_key = {}
    for i in range(count):
        entry_bc = entries_container.GetContainerInstance(i) if entries_container is not None else None
        if entry_bc is None:
            continue
        key = entry_bc.GetString(_ENTRY_KEY, "")
        keys.append(key)
        by_key[key] = {
            "name": entry_bc.GetString(_ENTRY_NAME, ""),
            "container": entry_bc.GetContainerInstance(_ENTRY_CONTAINER),
            "matrix": entry_bc.GetMatrix(_ENTRY_MATRIX, c4d.Matrix()),
        }
    return keys, by_key


def _restore_report_text(matched_count, total_count):
    missing_count = total_count - matched_count
    if missing_count <= 0:
        return "%d restaurados" % matched_count
    return "%d de %d restaurados · %d no encontrados" % (
        matched_count, total_count, missing_count)


def _find_safety_tag(obj):
    """The safety tag is identified by TYPE + its reserved name, same rule
    the overlay/frame tags use elsewhere in the plugin to find their own
    tag rather than trust a Python-side cache that a document reload would
    invalidate."""
    getter = getattr(obj, "GetTags", None)
    tags = getter() if callable(getter) else None
    for tag in (tags or []):
        try:
            if tag.GetType() == SENTINEL_PIN_TAG_PLUGIN_ID and tag.GetName() == pins.SAFETY_PIN_NAME:
                return tag
        except Exception:
            continue
    return None


def _capture_safety_pin(node, obj, doc):
    """Snapshot the object's subtree AS IT IS RIGHT NOW into the ``↩ Antes
    de restaurar`` tag on the same host — creating it if it doesn't exist
    yet, overwriting it (via ``_store_pin``, same as a manual Re-pin) if it
    does. Called BEFORE the caller touches anything else: this is the whole
    safety property, not a nicety, so a failure here must abort the
    restore rather than proceed net-less."""
    tag = _find_safety_tag(obj)
    if tag is None:
        try:
            tag = obj.MakeTag(SENTINEL_PIN_TAG_PLUGIN_ID)
        except Exception:
            tag = None
        if tag is None:
            return False
        # SetName lives INSIDE this bracket, not after it: a plain mutation
        # made once the bracket has already closed is not undo-tracked at
        # all (nothing to attach it to), which would leave the rename
        # permanent even if the NEW tag itself gets undone later.
        doc.StartUndo()
        try:
            doc.AddUndo(c4d.UNDOTYPE_NEW, tag)
            try:
                tag.SetName(pins.SAFETY_PIN_NAME)
            except Exception:
                return False
        finally:
            doc.EndUndo()
    return _store_pin(tag)


def _restore(node):
    """Apply this tag's pinned state back onto the live scene.

    The order below IS the safety property (see the module's callers and
    the brief): capture the net before touching anything, verify the
    schema before planning, plan against the scene as it stands NOW, then
    apply every matched key inside one undo bracket — nothing is created or
    deleted, and a schema this build doesn't recognise is never applied,
    not even partially.

    Writes its own outcome into the row (``_write_last_restore``) for every
    path except the schema mismatch — ``_pin_status_text`` already shows
    that one unconditionally, so writing it here too would just be a second
    source of truth for the same message. Missing keys go to
    ``safe_print`` instead of the row — no room for a list there. Also
    returns the report text, for callers that want it directly.
    """
    obj = node.GetObject()
    if obj is None:
        report = "no se pudo restaurar — el tag no está sobre un objeto"
        _write_last_restore(node, report)
        return report
    doc = _doc_from_node(node)
    if doc is None:
        report = "no se pudo restaurar — sin documento"
        _write_last_restore(node, report)
        return report

    # 1. The subtree as it stands right now, and its keys.
    current_tree, current_flat_nodes = _walk_object_tree(obj)
    current_keys = pins.location_keys(current_tree)
    current_by_key = dict(zip(current_keys, current_flat_nodes))

    # 2. Safety net FIRST. Skip only when THIS tag IS the safety net —
    # overwriting it here would destroy the one copy of the state the
    # artist is restoring away FROM.
    is_safety_tag = _safe_node_name(node, "") == pins.SAFETY_PIN_NAME
    if not is_safety_tag:
        if not _capture_safety_pin(node, obj, doc):
            report = "no se pudo respaldar el estado actual — restauración cancelada"
            safe_print("Sentinel Pin: %s" % report)
            _write_last_restore(node, report)
            return report

    # 3. Schema gate. A payload this build doesn't recognise is never
    # applied, not even partially — and the row already says so on every
    # read via ``_pin_status_text``, so there is nothing further to write.
    payload = _read_payload_bc(node)
    if payload is None:
        return ""
    schema = payload.GetInt32(_PAYLOAD_SCHEMA, 0)
    if schema != PIN_SCHEMA:
        return ""

    pinned_keys, pinned_by_key = _read_pinned_entries(payload)

    # 4. Plan against the scene as it is now.
    plan = pins.plan_restore(pinned_keys, current_keys)
    matched = plan["matched"]
    missing = plan["missing"]

    # 5. Nothing matched: report, touch nothing, open no undo bracket for
    # a no-op.
    if not matched:
        report = _restore_report_text(0, len(pinned_keys))
        if missing:
            safe_print("Sentinel Pin: no encontrados — %s" % ", ".join(missing))
        _write_last_restore(node, report)
        return report

    # 6. One undo bracket for the whole matched subtree.
    doc.StartUndo()
    try:
        for key in matched:
            live_obj = current_by_key.get(key)
            entry = pinned_by_key.get(key)
            if live_obj is None or entry is None:
                continue
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, live_obj)
            try:
                live_obj.SetData(entry["container"])
            except Exception:
                pass
            try:
                live_obj.SetMl(entry["matrix"])
            except Exception:
                pass
            try:
                live_obj.SetName(entry["name"])
            except Exception:
                pass
        report = _restore_report_text(len(matched), len(pinned_keys))
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
        _write_last_restore(node, report)
    finally:
        doc.EndUndo()

    # 7.
    _event_add()

    if missing:
        safe_print("Sentinel Pin: no encontrados — %s" % ", ".join(missing))
    return report


try:
    _TagDataBase = plugins.TagData
    if not isinstance(_TagDataBase, type):
        raise TypeError("plugins.TagData is not a class")
    _SENTINEL_PIN_TAG_AVAILABLE = True
except Exception:
    _TagDataBase = object
    _SENTINEL_PIN_TAG_AVAILABLE = False


class SentinelPinTag(_TagDataBase):
    """TagData shell for the Sentinel Pin single-pin state store."""

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

    def Init(self, node, isCloneInit=False):
        self._init_attr(node, str, ID_PIN_NAME)
        _set_node_value(node, ID_PIN_NAME, _safe_node_name(node, ""))
        return True

    def GetDDescription(self, node, description, flags):
        try:
            description.LoadDescription(node.GetType())
        except Exception:
            pass

        root = c4d.DescID(c4d.DescLevel(c4d.ID_TAGPROPERTIES))

        # Una sola fila, sin grupo multi-columna: sin columnas que
        # competir por ancho, no hay nada que desalinear ni truncar (la
        # razón entera de este rehecho — ver el docstring del módulo).
        if not self._set_description_parameter(
            node, description, ID_PIN_NAME, c4d.DTYPE_STRING, "Nombre", root,
            animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_PIN_STATUS, c4d.DTYPE_STATICTEXT, "Estado", root,
            animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_PIN_STORE, c4d.DTYPE_BUTTON,
            _store_button_label(_pin_is_filled(node)), root, animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_PIN_GO, c4d.DTYPE_BUTTON, "Ir", root,
            animatable=False
        ):
            return False

        return True, flags | c4d.DESCFLAGS_DESC_LOADED

    def GetDParameter(self, node, id, flags):
        # El estado es un campo derivado (mismo patrón que ID_SYNC_STATUS de
        # frame_tag): nunca se escribe en el dato real del nodo, así que su
        # texto está siempre fresco — incluido el tiempo relativo, que debe
        # seguir avanzando aunque no se haya vuelto a pinear nada.
        parameter_id = _desc_level_id(id)
        if parameter_id == ID_PIN_STATUS:
            return True, _pin_status_text(node), flags | c4d.DESCFLAGS_GET_PARAM_GET
        return False

    def SetDParameter(self, node, id, data, flags):
        parameter_id = _desc_level_id(id)
        if parameter_id == ID_PIN_STATUS:
            # Read-only derived string: swallow writes.
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        if parameter_id == ID_PIN_NAME:
            # Propagar al nombre del TAG (no del objeto etiquetado): es lo
            # que hace que el Object Manager muestre el pin sin abrir nada,
            # que es media razón de que esto sea un tag y no un diálogo.
            try:
                node.SetName(str(data))
            except Exception:
                pass
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        if parameter_id in (ID_PIN_GO,):
            return _pin_is_filled(node)
        return True

    def _handle_command(self, node, data):
        if not _is_main_thread():
            return True
        command_id = _command_id_from_data(data)
        if command_id == ID_PIN_STORE:
            _store_pin(node)
            _event_add()
        elif command_id == ID_PIN_GO:
            # GetDEnabling already gates the button to a filled pin; the
            # explicit check here is a defensive mirror of the same guard
            # (cheap, and it's exactly what protects the MSG_EDIT path
            # below, which has no button-enable state to lean on). A pin
            # whose schema this build does not recognise still passes this
            # check (the pin IS filled) — _restore's own schema gate is
            # what refuses to apply it, not this one.
            if _pin_is_filled(node):
                _restore(node)
        return True

    def Message(self, node, mid, data):
        description_command = getattr(c4d, "MSG_DESCRIPTION_COMMAND", None)
        if description_command is not None and mid == description_command:
            return self._handle_command(node, data)
        edit_message = getattr(c4d, "MSG_EDIT", None)
        if edit_message is not None and mid == edit_message:
            # Double-click shortcut (Recall's UX, id 21) — NOT known to
            # reach a TagData in C4D 2026 (unmeasured in the Task 1 spike).
            # The "Ir" button above is the guaranteed path; this is only an
            # accelerator on top of it, so a silent no-op here if the
            # message never arrives costs nothing but the shortcut itself.
            if _is_main_thread() and _pin_is_filled(node):
                _restore(node)
            return True
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
