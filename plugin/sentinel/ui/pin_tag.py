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
# SIN campo de nombre propio: cada tag de C4D YA trae uno, en su pestaña
# Basic — el mismo sitio donde el artista renombra cualquier otro tag. Un
# segundo campo "Nombre" aquí competía por la misma información con el
# nombre real del tag (ver ID_PIN_NAME más abajo, degradado a espejo).
ID_PIN_STATUS = 1002    # DTYPE_STATICTEXT — "12 obj · hace 2 h · ..." (solo
                         # lectura: un DTYPE_STRING pinta una caja que
                         # compite por ancho con el resto de la fila, y fue
                         # justo eso lo que truncó el texto en la v6-slots)
ID_PIN_STORE = 1003     # DTYPE_BUTTON     — "Pin aquí" / "Re-pin"
ID_PIN_GO = 1004        # DTYPE_BUTTON     — "Ir"
ID_PIN_COLOR = 1005     # DTYPE_LONG cycle — badge color, default "none"
                         # (index 0 of pins.PIN_COLORS). Falls through to
                         # C4D's own default container storage in
                         # GetDParameter/SetDParameter (same as every other
                         # untouched id below) — it needs no read/write code
                         # here, only the description entry and the
                         # MSG_GETCUSTOMICON reader (_pin_color_index).

#: Cycle entries for ID_PIN_COLOR, built once from pins.PIN_COLORS so the
#: two never drift apart — the cycle's integer VALUES are the same indices
#: _pin_color_index reads back and pins.PIN_COLORS is keyed by.
_COLOR_CYCLE = tuple(
    (i, name.capitalize()) for i, (name, _rgb) in enumerate(pins.PIN_COLORS)
)

#: Icon canvas side, in pixels — matches what the Task 1 spike measured
#: working end to end (GeClipMap.Init(32, 32, 32), §5).
_ICON_SIZE = 32

#: Generated-icon cache, keyed by (color_index, badge_char) rather than by
#: node: MSG_GETCUSTOMICON fires on every Object Manager repaint, so two
#: pins that happen to share a color and a badge letter share one bitmap
#: instead of each regenerating their own on every paint (per-frame cost,
#: called out explicitly in the brief).
_ICON_CACHE = {}

#: El string exacto pasado a ``RegisterTagPlugin(str=...)`` en
#: ``sentinel_panel.pyp`` — reusado, nunca retecleado, porque la igualdad
#: contra este literal es la ÚNICA señal que ``_sync_display_name`` tiene
#: para "acabo de cargar, C4D reseteó el nombre" (ver esa función). Si
#: alguna vez diverge del ``str=`` real de ahí, la detección de reset
#: diverge con él en silencio.
PIN_TAG_DEFAULT_NAME = "Sentinel Pin"

#: El payload vive bajo un id de contenedor privado dentro del contenedor
#: propio del tag, así viaja con el .c4d (la Tarea 1 probó el round-trip).
#: Lejos del rango de ids de descripción de arriba.
ID_PIN_PAYLOAD = 20000

#: Espejo del nombre REAL del tag (``node.GetName()``, editado en la
#: pestaña Basic) — ya NO es un campo de descripción (ver arriba). Existe
#: por una única razón, medida en vivo: C4D resetea el nombre de un tag
#: de plugin Python al string de registro en cada carga, y el nombre real
#: es la única pieza de este feature que NO sobrevive el ciclo
#: guardar/recargar por sí sola (todo lo demás — payload, flags — vive en
#: el contenedor propio y sí sobrevive). ``_sync_display_name`` escribe
#: aquí cuando ve el nombre real cambiado (nunca al revés salvo el caso
#: de reset) — ver esa función para la política completa. Se conserva el
#: mismo id numérico (1001) que tenía como campo de descripción: ya no es
#: uno, pero renumerar no aporta nada y sí ensucia el diff.
ID_PIN_NAME = 1001

#: Resultado en texto de la última restauración desde ESTE tag (p.ej. "9 de
#: 12 restaurados · 3 no encontrados"). Se escribe directo en el contenedor
#: del tag — no forma parte de ``ID_PIN_PAYLOAD`` ni de su schema, así que
#: un build más nuevo nunca la confunde con datos de restauración. Se limpia
#: en cada (re-)pin para que la fila vuelva a mostrar el resumen del pin en
#: vez de dejar clavado el resultado de una restauración ya vieja.
ID_PIN_LAST_RESTORE = 20001

#: Marca que ESTE tag es la red de seguridad — nunca el nombre. Un nombre
#: es texto editable por el artista: si la identidad dependiera de él,
#: renombrar CUALQUIER pin a "↩ Antes de restaurar" lo convertiría en la
#: red de seguridad por accidente (y viceversa, renombrar la red de
#: seguridad la dejaría de reconocer como tal). Se escribe una sola vez,
#: al crear el tag en ``_capture_safety_pin`` — nunca en ``_store_pin``,
#: que esa función sirve tanto para pines normales como para la red de
#: seguridad y no debe decidir cuál es cuál.
ID_PIN_IS_SAFETY = 20002

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


def _is_safety_tag(node):
    """Identity check for the safety tag — the ``ID_PIN_IS_SAFETY`` flag in
    its OWN container, never the name. A name is artist-editable text:
    matching on it would let renaming any ordinary pin to
    ``pins.SAFETY_PIN_NAME`` turn it into the safety tag by accident (and
    renaming the real safety tag away from that string would un-safety
    it)."""
    bc = node.GetDataInstance()
    if bc is None:
        return False
    return bool(bc.GetBool(ID_PIN_IS_SAFETY, False))


def _find_safety_tag(obj):
    """The safety tag is identified by TYPE + the ``ID_PIN_IS_SAFETY``
    flag in its own container (see ``_is_safety_tag``) — never by name."""
    getter = getattr(obj, "GetTags", None)
    tags = getter() if callable(getter) else None
    for tag in (tags or []):
        try:
            if tag.GetType() == SENTINEL_PIN_TAG_PLUGIN_ID and _is_safety_tag(tag):
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
    restore rather than proceed net-less.

    Requires the tag to be registered with ``c4d.TAG_MULTIPLE`` (see the
    comment in ``sentinel_panel.pyp``): without it, C4D's own
    ``MakeTag``/``InsertTag`` implicitly evicts any existing same-type tag
    on the object the moment a second one is added — which is exactly
    ``node``, the pin this whole function exists to protect. That was the
    Task 4 live Critical: the eviction invalidated ``node`` mid-restore, so
    the very next read of its payload came back empty and nothing applied.
    """
    tag = _find_safety_tag(obj)
    if tag is None:
        try:
            tag = obj.MakeTag(SENTINEL_PIN_TAG_PLUGIN_ID)
        except Exception:
            tag = None
        if tag is None:
            return False
        # SetName + the identity flag live INSIDE this bracket, not after
        # it: a plain mutation made once the bracket has already closed is
        # not undo-tracked at all (nothing to attach it to), which would
        # leave them permanent even if the NEW tag itself gets undone
        # later.
        doc.StartUndo()
        try:
            doc.AddUndo(c4d.UNDOTYPE_NEW, tag)
            try:
                tag.SetName(pins.SAFETY_PIN_NAME)
                tag.GetDataInstance().SetBool(ID_PIN_IS_SAFETY, True)
            except Exception:
                return False
        finally:
            doc.EndUndo()
    return _store_pin(tag)


def _sync_display_name(node):
    """Keep the tag's OWN name (``node.GetName()``, edited in the Basic
    tab like every other C4D tag — no dedicated field on this tag exists
    anymore) as the single source of truth for a pin's name, with the
    ``ID_PIN_NAME`` container mirror existing for ONE reason only:
    surviving the one thing a live rename cannot — a reload.

    MEASURED, twice, live (both facts load-bearing to the policy below):
    1. (Coordinator, first pass) C4D resets a Python-registered plugin
       tag's real name back to its REGISTRATION STRING
       (``PIN_TAG_DEFAULT_NAME``) on every load, discarding whatever the
       artist had typed — even though every other piece of the tag's own
       container round-trips fine. This reset is the ENTIRE reason the
       mirror exists; a tag type whose name round-tripped normally would
       need none of this.
    2. (Coordinator, second pass — the bug this rewrite fixes) an EARLIER
       version of this function trusted the mirror over the live name any
       time the two disagreed. Since ``Execute()`` (the hook this runs
       from) ticks continuously, a live rename disagreed with the
       (stale) mirror for exactly one tick and then got SILENTLY
       REVERTED a moment later — worse than an instant failure, because
       the artist saw the rename work, looked away, and it undid itself
       behind their back.

    Policy, inverted from that first attempt: the TAG NAME wins,
    unconditionally, with exactly one exception — the reset signature
    itself. The mirror is consulted ONLY when the current name reads
    EXACTLY ``PIN_TAG_DEFAULT_NAME``, because that is indistinguishable
    from "a load just erased it" without also being wrong to restore
    from in that case. Any other name — including one the artist typed
    a moment ago — is trusted as-is and copied INTO the mirror, so the
    mirror stays current for the NEXT load without ever fighting the
    CURRENT one.

    Edge case, noted rather than "solved": an artist who names a pin
    literally "Sentinel Pin" is indistinguishable from a fresh load —
    this function will try to "restore" from the mirror every tick. The
    consequence is nil (the mirror holds that exact same string, so the
    restore is a no-op, never a wrong name) — do not "fix" this with
    cleverness later; the ambiguity is genuinely unresolvable from inside
    this function and happens to be harmless.

    SAFETY tag: never goes through the general branch above. Its name is
    unconditionally forced to ``pins.SAFETY_PIN_NAME`` — including
    repairing its OWN mirror to match, since ``_capture_safety_pin`` sets
    it with ``tag.SetName(...)`` directly and never touches the mirror,
    so a fresh safety tag's mirror starts stale too. Renaming the safety
    tag must never be a way to turn it into an ordinary pin.

    Idempotent — safe to call on every ``Execute`` tick without a
    separate dirty flag; the steady state (name already correct, mirror
    already current) is a cheap read-only comparison.
    """
    bc = node.GetDataInstance()
    if bc is None:
        return
    if _is_safety_tag(node):
        target = pins.SAFETY_PIN_NAME
        if bc.GetString(ID_PIN_NAME, "") != target:
            bc.SetString(ID_PIN_NAME, target)
        if _safe_node_name(node, "") != target:
            try:
                node.SetName(target)
            except Exception:
                pass
        return

    current = _safe_node_name(node, "")
    if current == PIN_TAG_DEFAULT_NAME:
        # Reset signature — restore from the mirror, if there is one. A
        # brand-new, never-named pin also reads the default here; its
        # mirror is empty, so this is a correct no-op for that case too.
        mirrored = bc.GetString(ID_PIN_NAME, "")
        if mirrored and mirrored != current:
            try:
                node.SetName(mirrored)
            except Exception:
                pass
        return

    # Any other name is authoritative, including one the artist just
    # typed — never written back to node.SetName here. Only the mirror
    # follows the name, so the NEXT load has something correct to
    # restore from.
    if bc.GetString(ID_PIN_NAME, "") != current:
        bc.SetString(ID_PIN_NAME, current)


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

    # 2. Safety net FIRST. Skip only when THIS tag IS the safety net (by
    # its ID_PIN_IS_SAFETY flag, never its name — see _is_safety_tag) —
    # overwriting it here would destroy the one copy of the state the
    # artist is restoring away FROM.
    if not _is_safety_tag(node):
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


# --- Per-instance icon (Task 5) ---------------------------------------------
#
# The design's own rationale for one-tag-per-pin was "you see the states in
# the Object Manager without opening anything" (module docstring above).
# Without a per-pin icon that promise wasn't kept — several pins on one
# object rendered as identical icons. This section answers MSG_GETCUSTOMICON
# per the Task 1 spike's §5 findings (docs/research/2026-07-31-pin-storage-
# spike.md): the message id, IconData's fields, and that GeClipMap really
# rasterises both the fill and the text were all measured there; what a
# TagData instance actually receiving MSG_GETCUSTOMICON looks like in
# practice was NOT — that is this task's live verification step.

def _pin_color_index(node):
    """0 ("none") unless the artist picked a color — same default C4D
    already gives an unset DTYPE_LONG container field, so nothing has to
    initialise this explicitly at Init time."""
    bc = node.GetDataInstance()
    if bc is None:
        return 0
    try:
        return int(bc.GetInt32(ID_PIN_COLOR, 0))
    except Exception:
        return 0


def _pin_label_for_badge(node):
    """The artist-typed name, or "" if this pin was never renamed away
    from the plugin's registration default (or is the safety tag) — a
    plugin-default name is not an artist label, so pins.pin_badge must see
    it as unlabeled and fall back to the ordinal digit, the same as a
    freshly-created pin with no name at all."""
    name = _safe_node_name(node, "")
    if name in (PIN_TAG_DEFAULT_NAME, pins.SAFETY_PIN_NAME):
        return ""
    return name


def _pin_ordinal(node):
    """0-based position of ``node`` among the OTHER Sentinel Pin tags on
    the same host object (the safety tag excluded — it never shows a
    number badge of its own), in ``GetTags()`` order. Feeds
    ``pins.pin_badge``'s numeric fallback for a pin that has no name yet,
    so the first three unnamed pins on one object read 1/2/3 rather than
    all showing the same digit."""
    obj = node.GetObject()
    if obj is None:
        return 0
    getter = getattr(obj, "GetTags", None)
    tags = getter() if callable(getter) else None
    ordinal = 0
    for tag in (tags or []):
        if tag is node:
            return ordinal
        try:
            if tag.GetType() == SENTINEL_PIN_TAG_PLUGIN_ID and not _is_safety_tag(tag):
                ordinal += 1
        except Exception:
            continue
    return ordinal


def _build_pin_icon_bitmap(rgb, char):
    """Compose a 32x32 icon: a solid ``rgb`` background with ``char`` in
    white on top. The recipe — Init, BeginDraw, SetColor+FillRect,
    GetDefaultFont+SetFont+TextAt, EndDraw, GetBitmap — is exactly what
    the Task 1 spike measured working (§5: FillRect's fill read back
    pixel-identical, TextAt changed 95 pixels from 0 before it). What the
    spike did NOT pin down is glyph size/position — those are tuned live,
    which is why the font/text half is its own try/except: a bad size or
    coordinate there still leaves the colored square (readable by color
    alone) instead of losing the icon entirely."""
    clip = c4d.bitmaps.GeClipMap()
    if clip is None or not clip.Init(_ICON_SIZE, _ICON_SIZE, 32):
        return None
    clip.BeginDraw()
    try:
        clip.SetColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
        clip.FillRect(0, 0, _ICON_SIZE, _ICON_SIZE)
        try:
            font = clip.GetDefaultFont(c4d.GE_FONT_DEFAULT_SYSTEM)
            if font is not None:
                clip.SetFont(font, 18)
                clip.SetColor(255, 255, 255, 255)
                clip.TextAt(9, 8, str(char))
        except Exception:
            pass
    finally:
        clip.EndDraw()
    return clip.GetBitmap()


def _fill_custom_icon(node, data):
    """MSG_GETCUSTOMICON handler body. ``data`` IS the c4d.IconData C4D
    passes in (bmp/x/y/w/h/flags, per the spike) — filled in place.
    Returning False without touching it is the "none" contract: a pin
    with the default color must render the plugin's own registered icon,
    never a color WE chose for the artist (brief's binding constraint)."""
    index = _pin_color_index(node)
    if index <= 0 or index >= len(pins.PIN_COLORS):
        return False
    rgb = pins.PIN_COLORS[index][1]
    if rgb is None:
        return False
    char = pins.pin_badge(_pin_label_for_badge(node), _pin_ordinal(node))
    cache_key = (index, char)
    bmp = _ICON_CACHE.get(cache_key)
    if bmp is None:
        bmp = _build_pin_icon_bitmap(rgb, char)
        if bmp is None:
            return False
        _ICON_CACHE[cache_key] = bmp
    try:
        data.bmp = bmp
        data.x = 0
        data.y = 0
        data.w = _ICON_SIZE
        data.h = _ICON_SIZE
        return True
    except Exception:
        return False


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

    def _set_description_parameter(
        self, node, description, parameter_id, dtype, name, parent,
        animatable=True, cycle=None,
    ):
        desc_id = _description_parent(parameter_id, dtype, node)
        bc = c4d.GetCustomDatatypeDefault(dtype)
        _set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
        _set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
        if cycle is not None:
            cycle_bc = c4d.BaseContainer()
            for value, label in cycle:
                _set_bc_value(cycle_bc, "SetString", int(value), label)
            _set_bc_value(bc, "SetContainer", c4d.DESC_CYCLE, cycle_bc)
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
        # SIN campo de nombre: el nombre del tag YA vive en su pestaña
        # Basic (ver ID_PIN_NAME/PIN_TAG_DEFAULT_NAME arriba) — un
        # segundo campo aquí competía por la misma información y perdía
        # renombrados en vivo (ver _sync_display_name).
        # Color leads the row: it is what makes several pins on one object
        # distinguishable in the Object Manager WITHOUT opening this tag
        # at all (the whole point of Task 5 — see the module docstring's
        # cross-reference), so it earns first position over Estado.
        if not self._set_description_parameter(
            node, description, ID_PIN_COLOR, c4d.DTYPE_LONG, "Color", root,
            cycle=_COLOR_CYCLE, animatable=False
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
        # No ID_PIN_NAME branch anymore: there is no name field in the
        # description to write through (see GetDDescription) — renaming
        # happens in the Basic tab like any other tag, and
        # _sync_display_name (called from Execute) mirrors it into the
        # container on its own, without needing this hook at all.
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        if parameter_id in (ID_PIN_GO,):
            return _pin_is_filled(node)
        return True

    def Execute(self, tag, doc, op, bt, priority, flags):
        # The GUARANTEED path the display-name sync relies on (see
        # _sync_display_name for the two measured bugs and the resulting
        # policy — tag name wins, mirror only feeds it back after a
        # reset): Execute already runs on every scene re-evaluation for
        # this exact reason elsewhere in the plugin (frame_tag.py's own
        # Execute — "every change re-evaluates the scene", same
        # catch-all pattern) — including the evaluation a document load
        # triggers to draw the viewport, and independent of whether the
        # artist ever opens THIS tag in the Attribute Manager, which is
        # the actual requirement: the Object Manager has to show the
        # right label without opening anything.
        _sync_display_name(tag)
        return c4d.EXECUTIONRESULT_OK

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
        custom_icon = getattr(c4d, "MSG_GETCUSTOMICON", None)
        if custom_icon is not None and mid == custom_icon:
            # Whether this actually reaches a TagData at all is the thing
            # Task 5's live verification exists to confirm (see the
            # module-level comment on _fill_custom_icon) — if it turns out
            # NOT to, that is reported as a finding, not silently accepted,
            # per the brief.
            try:
                if _fill_custom_icon(node, data):
                    return True
            except Exception:
                pass
            return False
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
        document_info = getattr(c4d, "MSG_DOCUMENTINFO", None)
        load_type = getattr(c4d, "MSG_DOCUMENTINFO_TYPE_LOAD", None)
        if document_info is not None and mid == document_info:
            # Earlier-firing ACCELERATOR on top of Execute() above, which
            # is the actual guaranteed path the name sync depends on —
            # whether this message reaches a TagData at all is NOT
            # verified (same honesty as the MSG_EDIT accelerator), so a
            # silent no-op here just means the fix lands one evaluation
            # tick later via Execute instead of immediately on load. Not
            # returned early: this message may still matter to whatever
            # the base class does with it.
            try:
                msg_type = data.get("type") if isinstance(data, dict) else None
            except Exception:
                msg_type = None
            if load_type is not None and msg_type == load_type:
                _sync_display_name(node)
        try:
            return super().Message(node, mid, data)
        except AttributeError:
            return True
        except Exception:
            return True
