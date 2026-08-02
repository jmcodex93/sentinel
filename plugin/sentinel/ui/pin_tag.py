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

Restaurar un pin sobre la escena está implementado (Tarea 4, con la captura
real de pistas de animación de la Tarea 6 encima): el botón "Ir" está
cableado a la descripción y su handler llama a ``_restore`` — ver esa
función más abajo para el contrato completo (red de seguridad, plan de
reemparejamiento por ubicación, un solo undo).
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

# Task 5 tried a per-pin icon (colored GeClipMap bitmap + badge letter,
# generated on MSG_GETCUSTOMICON) so several pins on one object would be
# distinguishable in the Object Manager without opening anything. Measured
# live and removed: MSG_GETCUSTOMICON never reaches a TagData in C4D
# 2026.303 (no way to confirm from a script either — C4DAtom.Message from
# Python takes a dict, so a real c4d.IconData can't be constructed and
# passed by hand; only C4D itself sends this message). Separately, C4D
# already ships the feature natively — every tag's Basic tab has an ICON
# group with an "Icon Color" checkbox that tints the OM icon — so this
# would have been a second, non-functional control duplicating a working
# one. Do not rebuild this.

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
#: DEPRECATED (Task 6): antes de la captura real de pistas, esto era solo
#: un bool "algo está animado". Ya no se escribe — la captura real vive en
#: _ENTRY_TRACKS de abajo — pero el id NUNCA se reutiliza para otra cosa,
#: porque un pin guardado con una build anterior a esta todavía lo trae, y
#: _pin_status_text lo sigue leyendo como último recurso (ver esa función)
#: para no volverse silencioso justo en los pins más viejos.
_ENTRY_KEYFRAMES = 6
#: Pistas CTRACK_CATEGORY_VALUE capturadas para este nodo (objeto propio Y
#: sus tags — mismas dos fuentes que keyframes.py camina para offset/
#: stagger, v1.30: un rig se desincroniza en silencio si solo se mira el
#: objeto). BaseContainer indexado 0..N-1, cada entrada un registro de
#: pista (ver _TRACK_* más abajo). Ninguna pista DATA/PLUGIN vive aquí —
#: ver pins.TRACK_CATEGORY_OTHER — solo se cuentan en _ENTRY_TRACKS_SKIPPED.
_ENTRY_TRACKS = 7
_ENTRY_TRACKS_COUNT = 8
#: Pistas encontradas en este nodo que NO se pudieron capturar (categoría
#: != CTRACK_CATEGORY_VALUE: PLA, morphs, sonido, de terceros). Contadas,
#: nunca calladas — es la mitad "queda fuera" de la regla de honestidad del
#: spec, la misma que ya cubre geometría.
_ENTRY_TRACKS_SKIPPED = 9

# Sub-keys de UN registro de pista, dentro de su propio BaseContainer
# (namespace privado, sin riesgo de colisión con los ids de arriba).
_TRACK_KEY = 1          # string — pins.track_key(owner, desc_id_parts)
_TRACK_KEY_COUNT = 2    # int32 — nº de claves en _TRACK_KEYS
_TRACK_KEYS = 3         # BaseContainer indexado 0..N-1, cada uno una clave

# Sub-keys de UNA clave (CKey), medidas en el spike de la Tarea 6 — todo
# cabe en un BaseContainer, incluido el BaseTime de GetTime() (el
# contenedor lo admite directamente, sin descomponerlo).
_KEY_TIME = 1
_KEY_VALUE = 2
_KEY_INTERPOLATION = 3
_KEY_VALUE_LEFT = 4
_KEY_VALUE_RIGHT = 5
_KEY_TIME_LEFT = 6
_KEY_TIME_RIGHT = 7
_KEY_AUTO_TANGENT = 8


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


def _iter_node_tracks(node):
    """Yield ``(owner, track)`` for every CTrack belonging to ``node``
    itself (owner ``""``) and every one of its TAGS (owner ``"tag[N]"``,
    N = position among the node's NON-Sentinel-Pin tags at capture time)
    — the same two sources ``keyframes.py`` walks for offset/stagger
    (v1.30, see ``_shift_track_list``): a rig desyncs silently if only the
    object-level tracks are considered, because constraints/XPresso/
    UserData animate through tags as often as through the object itself.

    Sentinel Pin tags (own type ``SENTINEL_PIN_TAG_PLUGIN_ID``) are
    excluded from the index entirely — not merely skipped for their own
    (nonexistent) CTracks. MEASURED LIVE: ``BaseObject.MakeTag`` with no
    ``pred`` PREPENDS, so creating the ``↩ Antes de restaurar`` safety tag
    during a restore (``_capture_safety_pin``, which runs BEFORE this is
    called again to resolve live tracks) shifts every other tag's position
    in ``GetTags()`` by one — and the same shift happens permanently the
    moment an artist adds a second Sentinel Pin tag to the same object.
    Either way, a ``tag[N]`` computed at capture time would then pair
    against a DIFFERENT tag's tracks at restore time — a wrong-object
    write, not merely a missed one, and ``plan_restore`` cannot tell a
    coincidental string match from a correct one (see ``pins.track_key``).
    Excluding Sentinel Pin tags from the count makes every other tag's
    index invariant to how many pins exist on the object or when they were
    created, closing both causes at once instead of reducing their odds."""
    try:
        for track in node.GetCTracks() or []:
            yield "", track
    except Exception:
        pass
    try:
        tags = node.GetTags() or []
    except Exception:
        tags = []
    non_pin_tags = []
    for tag in tags:
        try:
            if tag.GetType() == SENTINEL_PIN_TAG_PLUGIN_ID:
                continue
        except Exception:
            pass
        non_pin_tags.append(tag)
    for index, tag in enumerate(non_pin_tags):
        try:
            tag_tracks = tag.GetCTracks() or []
        except Exception:
            continue
        for track in tag_tracks:
            yield "tag[%d]" % index, track


def _track_category_name(track):
    """Normalize a CTrack's ``GetTrackCategory()`` to the plain strings
    ``pins.py`` reasons about (that module never imports c4d — see its
    module docstring). Measured categories: only ``CTRACK_CATEGORY_VALUE``
    tracks are simple per-key scalar data (docs/research/
    2026-07-31-pin-storage-spike.md §6); everything else (DATA/PLUGIN —
    PLA, morphs, sound, third-party) is a different structure entirely."""
    try:
        category = track.GetTrackCategory()
    except Exception:
        return pins.TRACK_CATEGORY_OTHER
    value_category = getattr(c4d, "CTRACK_CATEGORY_VALUE", None)
    if value_category is not None and category == value_category:
        return pins.TRACK_CATEGORY_VALUE
    return pins.TRACK_CATEGORY_OTHER


def _track_desc_id_parts(track):
    """Flatten a CTrack's ``GetDescriptionID()`` into the shape the spike
    measured live: one ``(id, dtype, creator)`` triple per DescLevel —
    the parameter identity ``pins.track_key`` re-pairs a restore by."""
    desc_id = track.GetDescriptionID()
    depth_getter = getattr(desc_id, "GetDepth", None)
    depth = depth_getter() if callable(depth_getter) else 0
    parts = []
    for i in range(depth):
        level = desc_id[i]
        parts.append((int(level.id), int(level.dtype), int(level.creator)))
    return parts


def _bc_get(bc, key):
    """Generic typed read (BaseTime/float/int all round-trip through plain
    ``__getitem__`` on a BaseContainer, per the Task 1 spike) that never
    raises when ``key`` was never written — a stored key record from an
    OLDER build of this same schema may simply be missing a field this
    build now also reads."""
    try:
        return bc[key]
    except Exception:
        return None


def _apply_key_setter(setter, curve, value):
    """Every CKey setter used here — ``SetTime`` (confirmed live in
    keyframes.py, v1.30) and, MEASURED LIVE in this task's own spike,
    ``SetValue``/``SetInterpolation``/``SetTimeLeft``/``SetValueLeft``/
    ``SetAutomaticTangentMode`` — takes the owning curve as its first
    argument so C4D can re-sort/renormalize; the one-arg, value-only shape
    an earlier version of this function also tried does not exist on any
    of them and always raised. Never raises itself: a setter failure just
    means that one field didn't restore, not that the whole key should
    abort."""
    try:
        setter(curve, value)
        return True
    except Exception:
        return False


def _capture_node_tracks(node):
    """Every ``CTRACK_CATEGORY_VALUE`` CTrack on ``node`` (its own + its
    tags'), captured key-by-key into containers per the Task 6 spike's
    measured shape. Returns ``(tracks_bc, captured_count, skipped_count)``
    — ``skipped_count`` is every OTHER track found (DATA/PLUGIN category —
    a different structure entirely, see the spike), counted so the row can
    say so instead of silently restoring nothing for it. A VALUE track
    with zero keys is neither captured nor skipped — there is nothing to
    lose and nothing to warn about."""
    tracks_bc = c4d.BaseContainer()
    captured = 0
    skipped = 0
    for owner, track in _iter_node_tracks(node):
        if _track_category_name(track) != pins.TRACK_CATEGORY_VALUE:
            skipped += 1
            continue
        try:
            curve = track.GetCurve()
        except Exception:
            curve = None
        key_count = curve.GetKeyCount() if curve is not None else 0
        if not key_count:
            continue
        try:
            desc_parts = _track_desc_id_parts(track)
        except Exception:
            skipped += 1
            continue
        keys_bc = c4d.BaseContainer()
        for i in range(key_count):
            key = curve.GetKey(i)
            if key is None:
                continue
            key_bc = c4d.BaseContainer()
            key_bc[_KEY_TIME] = key.GetTime()
            key_bc[_KEY_VALUE] = key.GetValue()
            key_bc[_KEY_INTERPOLATION] = key.GetInterpolation()
            key_bc[_KEY_VALUE_LEFT] = key.GetValueLeft()
            key_bc[_KEY_VALUE_RIGHT] = key.GetValueRight()
            key_bc[_KEY_TIME_LEFT] = key.GetTimeLeft()
            key_bc[_KEY_TIME_RIGHT] = key.GetTimeRight()
            key_bc[_KEY_AUTO_TANGENT] = key.GetAutomaticTangentMode()
            keys_bc.SetContainer(i, key_bc)
        track_bc = c4d.BaseContainer()
        track_bc.SetString(_TRACK_KEY, pins.track_key(owner, desc_parts))
        track_bc.SetInt32(_TRACK_KEY_COUNT, key_count)
        track_bc.SetContainer(_TRACK_KEYS, keys_bc)
        tracks_bc.SetContainer(captured, track_bc)
        captured += 1
    return tracks_bc, captured, skipped


def _live_tracks_by_key(node):
    """Live VALUE-category CTracks on ``node`` (own + tags), keyed the
    SAME way ``_capture_node_tracks`` keyed them at pin time — so a
    restore can look one up by the identity that survives save/reload
    (``pins.track_key``), never by any live C4D handle."""
    out = {}
    for owner, track in _iter_node_tracks(node):
        if _track_category_name(track) != pins.TRACK_CATEGORY_VALUE:
            continue
        try:
            desc_parts = _track_desc_id_parts(track)
        except Exception:
            continue
        out[pins.track_key(owner, desc_parts)] = track
    return out


def _apply_track_keys(track, key_records):
    """Replace EVERY key of ``track`` with the stored ``key_records`` —
    restore means the pinned set IS the desired state, not something to
    merge with whatever the live curve currently holds (that is exactly
    how a wrecked animated parameter gets un-wrecked). Deletes walk in
    REVERSE (deleting index 0 first would shift every later index — same
    footgun ``keyframes._shift_track_list`` already documents for
    positive-direction shifts). Returns the number of keys written.

    The applicable records (those with a real ``time``) are collected
    FIRST, before the live curve is touched at all — if that list turns
    out empty (every stored record has ``time is None``, e.g. a
    corrupted/partial capture), the track is skipped whole. Deleting the
    live keys up front and only THEN discovering there is nothing to
    rebuild would destroy real animation for a net loss, not a wash."""
    applicable = [r for r in (key_records or []) if r.get("time") is not None]
    if not applicable:
        return 0
    try:
        curve = track.GetCurve()
    except Exception:
        curve = None
    if curve is None:
        return 0
    existing = curve.GetKeyCount()
    for i in range(existing - 1, -1, -1):
        try:
            curve.DelKey(i)
        except Exception:
            pass
    applied = 0
    for record in applicable:
        try:
            result = curve.AddKey(record["time"])
        except Exception:
            result = None
        key = result.get("key") if isinstance(result, dict) else result
        if key is None:
            continue
        if record.get("value") is not None:
            _apply_key_setter(key.SetValue, curve, record["value"])
        if record.get("interpolation") is not None:
            _apply_key_setter(key.SetInterpolation, curve, record["interpolation"])
        if record.get("time_left") is not None:
            _apply_key_setter(key.SetTimeLeft, curve, record["time_left"])
        if record.get("time_right") is not None:
            _apply_key_setter(key.SetTimeRight, curve, record["time_right"])
        if record.get("value_left") is not None:
            _apply_key_setter(key.SetValueLeft, curve, record["value_left"])
        if record.get("value_right") is not None:
            _apply_key_setter(key.SetValueRight, curve, record["value_right"])
        if record.get("auto_tangent") is not None:
            _apply_key_setter(key.SetAutomaticTangentMode, curve, record["auto_tangent"])
        applied += 1
    return applied


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
    objeto y no vuelven al restaurar). Desde la Tarea 6, las pistas
    CTRACK_CATEGORY_VALUE se capturan y restauran de verdad — la fila lo
    refleja con "N pistas" — y solo lo que sigue sin poder capturarse
    (categoría DATA/PLUGIN, o un pin de una build anterior a esta que solo
    guardó el bool viejo) se avisa como "no incluidas", nunca en silencio.

    Estas dos notas son un compromiso vinculante del spec, no decoración
    del resumen de pineo — así que se calculan y se anexan SIEMPRE, tanto
    si la fila abre con el resumen del pin como si abre con el resultado
    de la última restauración (``last_restore``). Antes de este fix, un
    ``last_restore`` no vacío retornaba de inmediato y las notas
    desaparecían de la fila para siempre en cuanto se pulsaba "Ir" una vez
    — justo cuando más importan, porque es el momento en que el artista
    más necesita saber qué NO se restauró.

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
    count = payload.GetInt32(_PAYLOAD_COUNT, 0)
    entries_bc = payload.GetContainerInstance(_PAYLOAD_ENTRIES)
    entries = []
    for i in range(count):
        entry_bc = entries_bc.GetContainerInstance(i) if entries_bc is not None else None
        geometry = bool(entry_bc.GetBool(_ENTRY_GEOMETRY, False)) if entry_bc is not None else False
        tracks_captured = int(entry_bc.GetInt32(_ENTRY_TRACKS_COUNT, 0)) if entry_bc is not None else 0
        tracks_skipped = int(entry_bc.GetInt32(_ENTRY_TRACKS_SKIPPED, 0)) if entry_bc is not None else 0
        if entry_bc is not None and not tracks_captured and not tracks_skipped:
            # This entry predates Task 6 — the old code only ever wrote a
            # bool ("something is animated"), never per-track data. Folded
            # into "skipped" so a LEGACY pin keeps warning honestly instead
            # of going silent the moment this build starts reading it
            # (it has nothing new to restore for that object either way).
            if bool(entry_bc.GetBool(_ENTRY_KEYFRAMES, False)):
                tracks_skipped = 1
        entries.append({
            "geometry": geometry,
            "tracks_captured": tracks_captured,
            "tracks_skipped": tracks_skipped,
        })
    summary = pins.pin_summary({"label": "", "entries": entries})
    last_restore = _read_last_restore(node)
    if last_restore:
        text = last_restore
    else:
        text = "%d obj · %s" % (
            summary["count"], _relative_time_es(payload.GetString(_PAYLOAD_TIMESTAMP, "")))
    if summary["has_geometry"]:
        text += " · geometría no incluida"
    if summary["tracks_captured"]:
        text += " · %d pistas" % summary["tracks_captured"]
    if summary["has_keyframes"]:
        text += " · %d pistas no incluidas" % summary["tracks_skipped"]
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
        tracks_bc, tracks_captured, tracks_skipped = _capture_node_tracks(child_obj)
        entry_bc.SetContainer(_ENTRY_TRACKS, tracks_bc)
        entry_bc.SetInt32(_ENTRY_TRACKS_COUNT, tracks_captured)
        entry_bc.SetInt32(_ENTRY_TRACKS_SKIPPED, tracks_skipped)
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

def _read_pinned_tracks(entry_bc):
    """Unpack one entry's captured tracks into ``{track_key: [key_record,
    ...]}`` — ``key_record`` is a plain dict mirroring the getters the
    Task 6 spike measured, ready for ``_apply_track_keys``. An entry
    written before Task 6 (no ``_ENTRY_TRACKS_COUNT``) reads back as ``{}``
    — nothing to restore, not a crash."""
    count = entry_bc.GetInt32(_ENTRY_TRACKS_COUNT, 0)
    tracks_container = entry_bc.GetContainerInstance(_ENTRY_TRACKS)
    out = {}
    for i in range(count):
        track_bc = tracks_container.GetContainerInstance(i) if tracks_container is not None else None
        if track_bc is None:
            continue
        track_key_str = track_bc.GetString(_TRACK_KEY, "")
        key_count = track_bc.GetInt32(_TRACK_KEY_COUNT, 0)
        keys_container = track_bc.GetContainerInstance(_TRACK_KEYS)
        records = []
        for k in range(key_count):
            key_bc = keys_container.GetContainerInstance(k) if keys_container is not None else None
            if key_bc is None:
                continue
            records.append({
                "time": _bc_get(key_bc, _KEY_TIME),
                "value": _bc_get(key_bc, _KEY_VALUE),
                "interpolation": _bc_get(key_bc, _KEY_INTERPOLATION),
                "value_left": _bc_get(key_bc, _KEY_VALUE_LEFT),
                "value_right": _bc_get(key_bc, _KEY_VALUE_RIGHT),
                "time_left": _bc_get(key_bc, _KEY_TIME_LEFT),
                "time_right": _bc_get(key_bc, _KEY_TIME_RIGHT),
                "auto_tangent": _bc_get(key_bc, _KEY_AUTO_TANGENT),
            })
        out[track_key_str] = records
    return out


def _read_pinned_entries(payload_bc):
    """Unpack a stored payload's entries into an ORDERED key list (the order
    the writer applied in, per the docstring of ``pins.location_keys``) plus
    a key -> {name, container, matrix, tracks} lookup for applying them."""
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
            "tracks": _read_pinned_tracks(entry_bc),
        }
    return keys, by_key


def _restore_report_text(matched_count, total_count, extra_tracks_count=0):
    missing_count = total_count - matched_count
    if missing_count <= 0:
        text = "%d restaurados" % matched_count
    else:
        text = "%d de %d restaurados · %d no encontrados" % (
            matched_count, total_count, missing_count)
    if extra_tracks_count:
        # Animation added to a covered node AFTER it was pinned — tracks
        # ``plan_restore`` puts in its "extra" bucket, which nothing in
        # this function used to read (thrown away, per the review finding
        # this parameter closes). Worth a note on the row itself, not just
        # a log line: a live VALUE track the pin never knew about can
        # overwrite the container/matrix values a restore JUST wrote back,
        # on the very next frame — the same silent-no-op failure mode
        # Task 6 fixed for the opposite direction (a wrecked track), just
        # facing the other way.
        text += " · %d pistas nuevas sin restaurar" % extra_tracks_count
    return text


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
                # A half-made tag must never linger unflagged: the NEXT
                # attempt's `_find_safety_tag` would not recognise it (the
                # flag never got set), so it would create ANOTHER tag on
                # top of it every single time this fails — an unbounded
                # pile of dead tags instead of one clean retry. Best-effort
                # removal so a failure here stays retryable.
                remover = getattr(tag, "Remove", None)
                if callable(remover):
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_DELETE, tag)
                        remover()
                    except Exception:
                        pass
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
    missing_tracks = []
    extra_tracks_total = 0
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
            # Restoring the container/matrix above is exactly the write an
            # animated parameter overwrites on its very next frame — this
            # is the actual fix for that silent no-op, applied inside the
            # SAME undo bracket as everything else (one Cmd+Z for the lot).
            stored_tracks = entry.get("tracks") or {}
            # Always resolve the live tracks, even when nothing was
            # pinned for this node (`stored_tracks` empty) — an `if
            # stored_tracks:` guard here would skip `plan_restore`
            # entirely for a node whose animation was added AFTER it was
            # pinned, so its "extra" bucket (live VALUE tracks with no
            # pinned counterpart) was computed and thrown away instead of
            # ever being counted.
            live_tracks = _live_tracks_by_key(live_obj)
            if stored_tracks or live_tracks:
                track_plan = pins.plan_restore(
                    list(stored_tracks.keys()), list(live_tracks.keys()))
                for track_key_str in track_plan["matched"]:
                    live_track = live_tracks.get(track_key_str)
                    if live_track is None:
                        continue
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_CHANGE, live_track)
                    except Exception:
                        pass
                    _apply_track_keys(live_track, stored_tracks.get(track_key_str) or [])
                if track_plan["missing"]:
                    missing_tracks.extend(
                        "%s@%s" % (key, tk) for tk in track_plan["missing"])
                extra_tracks_total += len(track_plan["extra"])
        report = _restore_report_text(len(matched), len(pinned_keys), extra_tracks_total)
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
        _write_last_restore(node, report)
    finally:
        doc.EndUndo()

    # 7.
    _event_add()

    if missing:
        safe_print("Sentinel Pin: no encontrados — %s" % ", ".join(missing))
    if missing_tracks:
        safe_print("Sentinel Pin: pistas no encontradas — %s" % ", ".join(missing_tracks))
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
