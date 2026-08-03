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
real de pistas de animación de la Tarea 6 encima): el botón "Restaurar"
está cableado a la descripción y su handler llama a ``_restore`` — ver esa
función más abajo para el contrato completo (red de seguridad, plan de
reemparejamiento por ubicación, un solo undo).

Segunda pasada de usabilidad (v1.35.2, docs/superpowers/sdd/task-9-report.md):
verbos que dicen lo que hacen ("Ir" -> "Restaurar", "Pin aquí"/"Re-pin" ->
"Guardar estado", sin relabel condicional), el Estado partido en dos líneas
(resumen + advertencia con ⚠, nunca concatenadas detrás del conteo), Color
reducido a UNA fila que expone los parámetros NATIVOS del tag
(ID_BASELIST_ICON_COLORIZE_MODE/ID_BASELIST_ICON_COLOR — el picker real de
C4D, no ocho botones de texto ni una paleta propia), y un separador antes de
"Quitar todos los pins de este objeto" para que la acción destructiva deje
de sentarse a ras con el resto de controles.
"""

import datetime

import c4d
from c4d import plugins

from sentinel import pins
from sentinel.common.helpers import safe_print

SENTINEL_PIN_TAG_PLUGIN_ID = 2099078
SENTINEL_PIN_TAG_DESCRIPTION = "Tsentinelpin"

# --- Description id layout ------------------------------------------------
# Second usability pass (v1.35.2, docs/superpowers/sdd/task-9-report.md):
# fixes the hierarchy that survived v1.35.1 — Estado (the only feedback
# this tool gives, read every time) now sits right under the actions,
# split into a summary line and a SEPARATE binding-warning line; Color
# drops from eight buttons to one row of the tag's own NATIVE parameters;
# and a separator sets the destructive "remove all" action apart from
# everything else. Still a single column of rows/groups — no multi-column
# grid competing for width, which is what truncated the status text in the
# original six-slot design this tag replaced.
ID_GROUP_ACTIONS = 1005  # DTYPE_GROUP, 2 columns, no titlebar — Restaurar |
                          # Guardar estado
ID_PIN_GO = 1004         # DTYPE_BUTTON — "Restaurar" (FIRST in the row: the
                          # button pressed far more than anything else here
                          # is configured). Named for what it DOES, not
                          # "Ir" (go where?).
ID_PIN_STORE = 1003      # DTYPE_BUTTON — "Guardar estado", ALWAYS this
                          # label whether the pin is empty or already
                          # filled — "Re-pin" was jargon a first-time
                          # artist has no reason to know, and the relabel
                          # logic it needed is gone (see _handle_command).
ID_PIN_STATUS = 1002     # DTYPE_STATICTEXT — the summary line only ("12
                          # objetos · hace 2 h", or a restore's own report
                          # text): read-only, since a DTYPE_STRING paints a
                          # box that competes for width with the rest of
                          # the row, and that's exactly what truncated the
                          # status text in the v6-slots design.
ID_PIN_WARNING = 1017    # DTYPE_STATICTEXT — the SEPARATE binding-warning
                          # line ("⚠ geometría no incluida · N pistas de
                          # animación"), computed independently of
                          # ID_PIN_STATUS so it survives every path
                          # (including after a restore) — see
                          # _pin_warning_text. Empty string, not a hidden
                          # row, when there is nothing to warn about (no
                          # per-row visibility toggle in the description
                          # API used here).
ID_PIN_NAME_FIELD = 1006  # DTYPE_STRING — "Nombre". NOT our own data: reads
                           # node.GetName(), writes node.SetName() (see
                           # GetDParameter/SetDParameter below) — the exact
                           # same call the Basic tab's own name field makes,
                           # so editing here or there writes the same place
                           # and neither can revert the other.
ID_GROUP_COLOR = 1007      # DTYPE_GROUP, 2 columns, no titlebar — "Color".
                            # ONE row exposing the tag's NATIVE
                            # ID_BASELIST_ICON_COLORIZE_MODE (checkbox) +
                            # ID_BASELIST_ICON_COLOR (swatch/picker)
                            # DIRECTLY — the exact ids the Basic tab's own
                            # "Icon Color" checkbox + picker already edit,
                            # so this gives C4D's real color picker instead
                            # of a fixed set of words. No command handler
                            # and no data of our own: GetDParameter/
                            # SetDParameter never intercept these ids, so
                            # the base class's default read/write handles
                            # them (see the "Color" section of
                            # GetDDescription).
ID_PIN_SEPARATOR = 1018   # DTYPE_SEPARATOR — sets "Quitar todos los pins de
                           # este objeto" apart from every other control:
                           # that button is destructive (deletes every
                           # Sentinel Pin tag on the host), everything above
                           # it is not.
ID_PIN_REMOVE_ALL = 1016  # DTYPE_BUTTON — "Quitar todos los pins de este
                           # objeto": deletes EVERY Sentinel Pin tag on the
                           # host (this one, every sibling pin, AND the
                           # safety net) in one undo step. Recall has the
                           # equivalent ("Remove All Recall Tags"). Always
                           # LAST, below the separator above.

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

#: The tag's NATIVE icon-tint parameters (Basic tab's "Icon Color" group) —
#: never our own storage, and exposed DIRECTLY in this tag's own
#: description since v1.35.2 (see GetDDescription's "Color" section), not
#: through a command handler writing to them by hand. Numeric fallbacks are
#: the values measured live in the design spec's spike (mode became 1,
#: colour became Vector(0.85, 0.3, 0.25)); ``getattr`` only matters for a
#: C4D build old enough that the symbol is missing from the ``c4d`` module,
#: not for the test harness (whose permissive fake auto-vivifies any
#: attribute).
_ICON_COLORIZE_MODE_ID = getattr(c4d, "ID_BASELIST_ICON_COLORIZE_MODE", 1041670)
_ICON_COLOR_ID = getattr(c4d, "ID_BASELIST_ICON_COLOR", 1041671)

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
#: Tipo (``obj.GetType()``) y nombre del objeto ANFITRIÓN en el momento de
#: capturar. Arrastrar un tag de un objeto a otro es trivial en C4D, y la
#: clave de la raíz del subárbol es la cadena vacía — que empareja con
#: CUALQUIER anfitrión — así que sin esto un pin de un Cube arrastrado a una
#: Light restauraría el contenedor y la matriz del cubo sobre la luz
#: cantando "1 restaurado". Se compara por TIPO, nunca por nombre
#: (renombrar es normal y el emparejamiento por ubicación ya lo acusa por su
#: cuenta); el nombre guardado solo alimenta el texto del aviso. ``0`` =
#: dato ausente (pin de una build anterior, o un anfitrión sin GetType):
#: nunca se avisa por ausencia del dato, solo por un desajuste real.
_PAYLOAD_HOST_TYPE = 5
_PAYLOAD_HOST_NAME = 6
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


def _safe_node_type(node):
    """``node.GetType()`` or ``0`` when it can't be read. ``0`` is never a
    real object type in C4D, so it doubles as "type not recorded" for a pin
    stored by a build older than this field (see ``_PAYLOAD_HOST_TYPE``)."""
    getter = getattr(node, "GetType", None)
    if callable(getter):
        try:
            return int(getter())
        except Exception:
            return 0
    return 0


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
    itself (owner ``""``) and every one of its TAGS (owner
    ``pins.tag_owner_key(...)`` = ``"tag[<type>:<escaped name>:N]"``,
    N = position among the node's NON-Sentinel-Pin tags sharing that same
    (type, name) pair, at capture time) — the same two sources
    ``keyframes.py`` walks for offset/stagger (v1.30, see
    ``_shift_track_list``): a rig desyncs silently if only the
    object-level tracks are considered, because constraints/XPresso/
    UserData animate through tags as often as through the object itself.

    Sentinel Pin tags (own type ``SENTINEL_PIN_TAG_PLUGIN_ID``) are
    excluded from the index entirely — not merely skipped for their own
    (nonexistent) CTracks. MEASURED LIVE: ``BaseObject.MakeTag`` with no
    ``pred`` PREPENDS, so creating the ``↩ Antes de restaurar`` safety tag
    during a restore (``_capture_safety_pin``, which runs BEFORE this is
    called again to resolve live tracks) shifts where every other tag
    sits in ``GetTags()`` — and the same shift happens permanently the
    moment an artist adds a second Sentinel Pin tag to the same object.

    The index is additionally scoped to tags sharing the same TYPE and
    NAME (rather than a flat position among ALL non-pin tags), closing
    narrower but real mis-pairings that the type-blind ``tag[N]`` left
    open — all reproduced, none of which had a test before their fix:

    - Deleting a non-pin tag that sits BEFORE the animated ones (e.g. a
      Phong tag ahead of two constraint tags) shifts every later tag's
      flat position by one, same shape as the Sentinel-Pin-prepend case
      above but for an ordinary tag deletion.
    - Adding a NEW tag ahead of the animated ones — including via
      Sentinel's OWN tooling, e.g. "Add Sentinel Frame to camera"
      (``scene_tools.py``) or ABC Retime (``scene_tools.py``) — has the
      exact same effect for any pin already sitting on that host.

    - Reordering two tags of the SAME type (two Constraint tags on one
      host swapping order) shifted each one's position-within-type, so
      each track's pinned keys were applied to the OTHER tag and the
      report still read as a clean success.

    Neither of the first two touches how many tags of the SAME type
    exist, so keying by type made the index invariant to both; the third
    is closed by the NAME entering the key ahead of the index. The
    residual case — two tags of the same type AND the same name,
    reordered — is genuinely ambiguous from position alone, and renaming
    a tag re-arms its tracks; see ``pins.track_key`` for what both mean
    for a restore's honesty."""
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
    counts = {}
    for tag in non_pin_tags:
        try:
            tag_type = tag.GetType()
        except Exception:
            tag_type = 0
        try:
            tag_name = tag.GetName()
        except Exception:
            tag_name = ""
        # Counted per (type, name) pair, not per type: that is what makes
        # a tag's index independent of how many OTHER tags of its type
        # exist, where they sit, and whether one of them is deleted.
        # Grouping on the raw name is equivalent to grouping on the
        # escaped one — ``_escape_name_for_key`` is injective (it escapes
        # the backslash first) — so the pair below and the string
        # ``tag_owner_key`` builds always agree.
        pair = (tag_type, tag_name)
        index = counts.get(pair, 0)
        counts[pair] = index + 1
        try:
            tag_tracks = tag.GetCTracks() or []
        except Exception:
            continue
        owner = pins.tag_owner_key(tag_type, tag_name, index)
        for track in tag_tracks:
            yield owner, track


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
    (``pins.track_key``), never by any live C4D handle.

    Every VALUE track is included here, REGARDLESS of its current key
    count — including one that has been emptied since it was pinned (an
    artist can select every key in the Timeline and delete them; the
    CTrack itself survives, empty). An N1 fix once filtered zero-key
    tracks out of THIS function to silence a permanent false "extra" —
    but that conflated two different situations: a track that was
    ALREADY empty when it was pinned (nothing captured, nothing to
    restore, nothing to warn about — still true) versus a track that WAS
    captured with keys and has since been emptied (a genuine restore
    target: ``stored_tracks`` still holds its keys). Filtering the
    lookup table made the second case invisible to ``plan_restore``, so
    its pinned keys fell into ``missing`` instead of being applied — a
    silent failure to apply on exactly the "un-wreck a wrecked animated
    parameter" case this capture/restore mechanism exists for (N5
    regression). The zero-key filter belongs on the ``extra`` side only
    — see ``_restore``, the one place that can tell "empty at pin time"
    apart from "empty now, captured with keys" by consulting
    ``stored_tracks`` alongside this table."""
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


def _live_track_key_count(track):
    """0 for anything that isn't a usable live CTrack (``None``, a curve
    that can't be fetched, or a curve reporting 0). Used only to decide
    whether a track in ``plan_restore``'s ``extra`` bucket is genuinely
    NEW animation (has keys, worth reporting) versus a track that was
    already keyless — never used to gate the restore lookup itself (see
    ``_live_tracks_by_key``'s docstring for why that distinction lives
    here, not there)."""
    try:
        curve = track.GetCurve()
    except Exception:
        curve = None
    if curve is None:
        return 0
    try:
        return curve.GetKeyCount()
    except Exception:
        return 0


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


def _pin_entries_summary(node):
    """Shared read: the stored pin's schema state plus (when valid)
    ``pins.pin_summary`` and the raw payload — used by BOTH
    ``_pin_status_text`` (the count+time line) and ``_pin_warning_text``
    (the binding geometry/tracks notes) so neither re-walks the payload's
    entries on its own, and so the two rows can never drift apart on what
    counts as "this pin's entries".

    Returns ``None`` when the tag has no pin at all. Otherwise a dict
    ``{"schema_ok": bool, "summary": dict|None, "payload": BaseContainer}``
    — ``summary`` is ``None`` when the schema doesn't match this build's
    ``PIN_SCHEMA`` (a payload that will never be applied has nothing
    meaningful to summarize either)."""
    payload = _read_payload_bc(node)
    if payload is None:
        return None
    schema = payload.GetInt32(_PAYLOAD_SCHEMA, 0)
    if schema != PIN_SCHEMA:
        return {"schema_ok": False, "summary": None, "payload": payload}
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
    return {"schema_ok": True, "summary": summary, "payload": payload}


def _pin_status_text(node):
    """Text for the row's SUMMARY line only: the pin's count + relative
    time ("12 objetos · hace 2 h"), or a restore's own report text once
    one has run from this tag (``_read_last_restore``). The binding
    geometry/tracks-not-included notes used to be appended here too — see
    ``_pin_warning_text`` below, which computes them independently on its
    OWN description row now, so they read as a warning instead of trivia
    stapled behind the count with a middle dot.

    This is SYNTHESIZED, never stored: ``GetDParameter`` calls this on
    every read instead of the status cell having a value written into the
    node's own container (verified live — ``GetDataInstance().GetString(id)``
    for this id reads empty, which is correct, not a bug). Storing the text
    would let the relative-time part ("hace 2 h") go stale the moment the
    AM stops repainting it; deriving it keeps it honest for free."""
    info = _pin_entries_summary(node)
    if info is None:
        return ""
    if not info["schema_ok"]:
        # Checked before the last-restore note on purpose: a mismatched
        # schema is never applied, so this message must win over whatever
        # a previous (older-build) restore happened to leave behind.
        return "pin de una versión anterior — no se aplicará"
    last_restore = _read_last_restore(node)
    if last_restore:
        return last_restore
    summary = info["summary"]
    payload = info["payload"]
    return "%s · %s" % (
        pins.pluralize_es(summary["count"], "objeto", "objetos"),
        _relative_time_es(payload.GetString(_PAYLOAD_TIMESTAMP, "")))


def _matched_live_nodes(node, payload):
    """The live nodes a restore FROM ``payload`` would actually touch
    right now — the object-tree walk (``_restore``'s step 1) intersected
    with the pin's own matched keys (``_restore``'s step 4), via the same
    ``pins.plan_restore`` a real restore uses. Never the whole live
    subtree: a brand-new child the pin never captured is not something
    this restore will ever touch, so it is not this function's business
    (see the live-geometry brief's Cambio 1, "Precisión requerida").

    Returns ``[]`` — never raises — whenever the object or document can't
    be resolved, mirroring ``_restore``'s own guards for the same two
    reads."""
    obj = node.GetObject()
    if obj is None:
        return []
    doc = _doc_from_node(node)
    if doc is None:
        return []
    current_tree, current_flat_nodes = _walk_object_tree(obj)
    current_keys = pins.location_keys(current_tree)
    current_by_key = dict(zip(current_keys, current_flat_nodes))
    pinned_keys = _read_pinned_keys(payload)
    matched = pins.plan_restore(pinned_keys, current_keys)["matched"]
    return [current_by_key[key] for key in matched if key in current_by_key]


def _live_geometry_among_matched(node, payload):
    """Whether any node a restore would actually touch is EDITABLE
    geometry right now (``isinstance(obj, c4d.PointObject)`` — the same
    test ``_walk_object_tree``/``_store_pin`` use, measured live in the
    Task 1 spike). Short-circuits on the first hit. Never raises: an
    unexpected shape from the live scene degrades to "no live geometry
    found" rather than breaking the row — the payload-derived flag this
    is only ever OR'd with already covers the common case."""
    try:
        for live_obj in _matched_live_nodes(node, payload):
            if isinstance(live_obj, c4d.PointObject):
                return True
    except Exception:
        return False
    return False


def _foreign_host_name(node, payload):
    """The name the pin's host had AT CAPTURE TIME when the tag now sits on
    an object of a DIFFERENT type — ``None`` when the types agree, when the
    payload predates this field, or when either type can't be read.

    Dragging a tag from one object to another is trivial and everyday in
    C4D, and nothing in the location keys catches it: the root of the
    subtree keys as the empty string, which ``pins.plan_restore`` matches
    against ANY host. So a pin taken on a Cube, dragged onto a Light,
    restores the cube's container and matrix onto the light and reports
    "1 restaurado" — the exact silent-success the honesty contract forbids.

    Type, not name: renaming an object is normal and already re-arms the
    pairing through the location keys; a different TYPE is what means "this
    is another object". This only WARNS — it never blocks the restore. The
    artist may well have dragged it there on purpose, and a pin whose
    container/matrix are close enough to be worth reusing is their call to
    make, not ours to veto."""
    stored_type = payload.GetInt32(_PAYLOAD_HOST_TYPE, 0)
    if not stored_type:
        return None
    obj = node.GetObject()
    if obj is None:
        return None
    live_type = _safe_node_type(obj)
    if not live_type or live_type == stored_type:
        return None
    return payload.GetString(_PAYLOAD_HOST_NAME, "")


def _pin_warning_text(node):
    """Text for the row's SEPARATE warning line — never concatenated
    behind the count, so it reads as a warning instead of trivia. Both
    notes are a binding compromise of the spec, not decoration of the pin
    summary, so they are computed the SAME way regardless of what
    ``_pin_status_text`` is currently showing (the pin's own summary, or a
    restore's report text): before this split, a non-empty
    ``last_restore`` made the single status string return early and the
    notes disappeared from the row for good the moment "Restaurar" was
    pressed once — exactly when the artist most needs to know what did
    NOT come back.

    "geometría no incluida" fires whenever any pinned entry's SAVED
    payload has editable geometry, OR — live-geometry brief, Cambio 1 —
    any live node the restore would actually touch is editable geometry
    RIGHT NOW even though it wasn't at pin time (measured live in C4D
    2026.303: a parametric object pinned, then made editable via
    CallCommand MAKEEDITABLE, then restored, silently keeps its wrecked
    shape while the row still says "N restaurados" — the payload-only
    check missed this because the object genuinely wasn't geometry when
    it was captured). The live check only runs when the payload alone
    didn't already answer yes — walking the scene on every AM repaint is
    wasted work the common case doesn't need. "N pistas de animación"
    fires whenever any pinned node has an animation track this build
    could not capture (category DATA/PLUGIN, or a pin from a build old
    enough to have only written the deprecated bool) — VALUE tracks are
    captured and restored for real since Task 6, so they are never
    counted here. "pin capturado sobre otro objeto" fires when the tag now
    sits on an object of a different TYPE than the one it was captured on
    (see ``_foreign_host_name``) — a warning only, never a block. Empty
    string, never ``None``, when there is nothing to warn about — the description row reads blank rather than being
    hidden (see ID_PIN_WARNING)."""
    info = _pin_entries_summary(node)
    if info is None or not info["schema_ok"]:
        return ""
    summary = info["summary"]
    has_geometry = summary["has_geometry"]
    if not has_geometry:
        has_geometry = _live_geometry_among_matched(node, info["payload"])
    parts = []
    foreign_host = _foreign_host_name(node, info["payload"])
    if foreign_host is not None:
        # First on purpose: it reframes every other note on this row — if
        # the pin was captured over a DIFFERENT object, what "geometría no
        # incluida" or "N pistas de animación" refer to isn't this host's
        # state at all.
        parts.append("pin capturado sobre otro objeto («%s»)" % foreign_host)
    if has_geometry:
        parts.append("geometría no incluida")
    if summary["has_keyframes"]:
        parts.append(pins.pluralize_es(
            summary["tracks_skipped"], "pista de animación", "pistas de animación"))
    homonyms = pins.homonym_tag_group_count(
        _read_pinned_track_keys(info["payload"]))
    if homonyms:
        # Last: unlike the notes above it, this one doesn't say something
        # was left out — it says the tracks that WERE captured may come
        # back on the wrong tag if the artist reorders two identically
        # named ones. Nothing can close that (see
        # pins.homonym_tag_group_count), so the row declares it.
        parts.append("%s (renómbralos para restaurar exacto)" % pins.pluralize_es(
            homonyms, "tag homónimo", "tags homónimos"))
    if not parts:
        return ""
    return "⚠ " + " · ".join(parts)


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
    payload_bc.SetInt32(_PAYLOAD_HOST_TYPE, _safe_node_type(obj))
    payload_bc.SetString(_PAYLOAD_HOST_NAME, _safe_node_name(obj, ""))
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


def _read_pinned_keys(payload_bc):
    """Just the ORDERED location keys of a stored payload — nothing else
    read, nothing else built.

    ``_matched_live_nodes`` (the live-geometry warning, which the AM calls
    on EVERY repaint) only ever needed this list, but used to get it from
    ``_read_pinned_entries`` and throw the whole ``by_key`` half away —
    including ``_read_pinned_tracks``, which builds one dict per key of
    per track of per node. A 300-object rig with 8 tracks of 60 keys meant
    ~144.000 dicts built and dropped per repaint, and precisely in the
    common case: the live check only runs when the payload says there is
    no geometry, i.e. the normal state of a parametric rig.
    ``_read_pinned_entries`` itself is unchanged — a real restore does
    need all of it."""
    count = payload_bc.GetInt32(_PAYLOAD_COUNT, 0)
    entries_container = payload_bc.GetContainerInstance(_PAYLOAD_ENTRIES)
    keys = []
    for i in range(count):
        entry_bc = entries_container.GetContainerInstance(i) if entries_container is not None else None
        if entry_bc is None:
            continue
        keys.append(entry_bc.GetString(_ENTRY_KEY, ""))
    return keys


def _read_pinned_track_keys(payload_bc):
    """One list of stored ``pins.track_key`` strings PER ENTRY — the track
    identities only, none of their key records.

    Per node rather than flattened because that is what
    ``pins.homonym_tag_group_count`` needs to keep two objects' identical
    homonym pairs from collapsing into one. Light on purpose, for the same
    reason ``_read_pinned_keys`` exists: this runs from
    ``_pin_warning_text`` on every AM repaint, and ``_read_pinned_tracks``
    would build a dict per animation key of every track of every node just
    to have its keys read."""
    count = payload_bc.GetInt32(_PAYLOAD_COUNT, 0)
    entries_container = payload_bc.GetContainerInstance(_PAYLOAD_ENTRIES)
    per_entry = []
    for i in range(count):
        entry_bc = entries_container.GetContainerInstance(i) if entries_container is not None else None
        if entry_bc is None:
            continue
        tracks_container = entry_bc.GetContainerInstance(_ENTRY_TRACKS)
        keys = []
        for t in range(entry_bc.GetInt32(_ENTRY_TRACKS_COUNT, 0)):
            track_bc = tracks_container.GetContainerInstance(t) if tracks_container is not None else None
            if track_bc is None:
                continue
            keys.append(track_bc.GetString(_TRACK_KEY, ""))
        per_entry.append(keys)
    return per_entry


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


def _restore_report_text(matched_count, total_count, extra_tracks_count=0,
                         missing_tracks_count=0):
    missing_count = total_count - matched_count
    if missing_count <= 0:
        text = pins.pluralize_es(matched_count, "restaurado", "restaurados")
    else:
        # "N de M restaurados" always keeps the plural "restaurados" here
        # regardless of N or M (live-geometry brief, Cambio 2: forcing a
        # concordance on this compound form reads worse, not better) —
        # only the trailing "no encontrado(s)" clause concords with its
        # own count.
        text = "%d de %d restaurados · %s" % (
            matched_count, total_count,
            pins.pluralize_es(missing_count, "no encontrado", "no encontrados"))
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
        text += " · %s sin restaurar" % pins.pluralize_es(
            extra_tracks_count, "pista nueva", "pistas nuevas")
    if missing_tracks_count:
        # A track the pin KNEW about and the live node no longer has (the
        # artist deleted the whole Position.Y track in the Timeline, say).
        # It used to leave the row entirely and go only to ``safe_print``
        # — so a restore that could not bring the animation back still
        # read "1 restaurado", and the only mention of what did NOT come
        # back sat in the Python console, which an artist never opens.
        # Missing OBJECTS have always reached the row; missing TRACKS now
        # do too. The full list still goes to ``safe_print`` — it doesn't
        # fit here.
        text += " · %s" % pins.pluralize_es(
            missing_tracks_count, "pista no encontrada", "pistas no encontradas")
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

    ``SetName``/``SetBool`` run BEFORE the ``UNDOTYPE_NEW`` undo is ever
    registered, not after — registering it first (an earlier version of
    this function did) is undo-unsafe: ``UNDOTYPE_DELETE`` restores an
    object from a CLONE taken at registration time, so if a Cmd+Z landed
    after a failed restore that clone would be of the half-made,
    unflagged tag — undoing the delete would then re-insert that stale
    clone right back, which the surrounding ``NEW`` undo never accounted
    for removing again. Registering ``NEW`` only once the tag is fully
    formed means the failure path never needs an undo at all: a bare
    ``tag.Remove()`` with nothing yet registered to unwind.
    """
    tag = _find_safety_tag(obj)
    if tag is None:
        try:
            tag = obj.MakeTag(SENTINEL_PIN_TAG_PLUGIN_ID)
        except Exception:
            tag = None
        if tag is None:
            return False
        try:
            tag.SetName(pins.SAFETY_PIN_NAME)
            tag.GetDataInstance().SetBool(ID_PIN_IS_SAFETY, True)
        except Exception:
            # A half-made tag must never linger unflagged: the NEXT
            # attempt's `_find_safety_tag` would not recognise it (the
            # flag never got set), so it would create ANOTHER tag on top
            # of it every single time this fails — an unbounded pile of
            # dead tags instead of one clean retry. Nothing was ever
            # registered for this tag yet, so a bare Remove is undo-safe
            # on its own.
            remover = getattr(tag, "Remove", None)
            if callable(remover):
                try:
                    remover()
                except Exception:
                    pass
            return False
        doc.StartUndo()
        try:
            doc.AddUndo(c4d.UNDOTYPE_NEW, tag)
        finally:
            doc.EndUndo()
    return _store_pin(tag)


# --- "Remove all" escape hatch (usability pass) ---------------------------
#
# The color shortcut this section used to hold (``_apply_pin_color``, a
# command handler dispatching one of ``pins.PIN_COLOR_PALETTE``'s eight
# swatches) is gone in v1.35.2: the Color row now declares
# ID_BASELIST_ICON_COLORIZE_MODE/ID_BASELIST_ICON_COLOR directly in the
# description (see GetDDescription) and neither GetDParameter nor
# SetDParameter intercept those ids — the base class's own default
# read/write handles them exactly the same way it already does for the
# Basic tab's "Icon Color" checkbox + picker, so there is no command to
# dispatch and nothing left to write by hand.

def _pin_tags_on_host(obj):
    """Every Sentinel Pin tag on ``obj`` — ordinary pins AND the safety
    net alike, identified by TYPE only (never by name or by
    ``ID_PIN_IS_SAFETY``, since removing all of them is exactly the one
    operation that must not discriminate between the two)."""
    getter = getattr(obj, "GetTags", None)
    tags = getter() if callable(getter) else None
    out = []
    for tag in (tags or []):
        try:
            if tag.GetType() == SENTINEL_PIN_TAG_PLUGIN_ID:
                out.append(tag)
        except Exception:
            continue
    return out


def _remove_all_pins(node):
    """Delete EVERY Sentinel Pin tag on this tag's host — this pin, every
    sibling pin, and the ``↩ Antes de restaurar`` safety net — in ONE undo
    step. Recall has the exact equivalent ("Remove All Recall Tags").

    Guarded: a host that can't be resolved, or one that (somehow) carries
    no Sentinel Pin tag at all, is a no-op — no undo bracket opened, so a
    stray click never shows up as an empty step in the Edit menu. In
    practice the button's OWN tag always counts as at least one while it
    exists, so the empty case is defensive rather than reachable from the
    UI, but ``GetDEnabling`` still consults this so the button never
    dangles clickable-but-pointless if that ever changes."""
    obj = node.GetObject()
    if obj is None:
        return False
    doc = _doc_from_node(node)
    if doc is None:
        return False
    tags = _pin_tags_on_host(obj)
    if not tags:
        return False
    doc.StartUndo()
    try:
        for tag in tags:
            try:
                doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, tag)
            except Exception:
                pass
            try:
                tag.Remove()
            except Exception:
                pass
    finally:
        doc.EndUndo()
    return True


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

    # 2. Schema gate, BEFORE anything is written anywhere. A payload this
    # build doesn't recognise is never applied, not even partially — and
    # the row already says so on every read via ``_pin_status_text``, so
    # there is nothing further to write. This runs ahead of the safety
    # capture below on purpose: a path that will apply NOTHING must not
    # overwrite the safety net either, or the artist's one way back (the
    # state the previous restore backed up) is gone with no dialog, no
    # note and no undo.
    payload = _read_payload_bc(node)
    if payload is None:
        return ""
    schema = payload.GetInt32(_PAYLOAD_SCHEMA, 0)
    if schema != PIN_SCHEMA:
        return ""

    # 3. Safety net, still BEFORE the scene is touched — that order IS the
    # safety property. Skipped only when THIS tag IS the safety net (by its
    # ID_PIN_IS_SAFETY flag, never its name — see _is_safety_tag):
    # overwriting it here would destroy the one copy of the state the
    # artist is restoring away FROM.
    if not _is_safety_tag(node):
        if not _capture_safety_pin(node, obj, doc):
            report = "no se pudo respaldar el estado actual — restauración cancelada"
            safe_print("Sentinel Pin: %s" % report)
            _write_last_restore(node, report)
            return report

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
                # A track in "extra" with zero keys right now was never
                # captured (capture skips zero-key tracks — nothing to
                # lose) and was never a restore target either — it must
                # not count as "N pistas nuevas sin restaurar" (that was
                # N1's bug; N5 moved the fix here instead of filtering
                # it out of ``live_tracks``, which broke restoring an
                # emptied PINNED track — see ``_live_tracks_by_key``).
                extra_tracks_total += sum(
                    1 for tk in track_plan["extra"]
                    if _live_track_key_count(live_tracks.get(tk)) > 0
                )
        report = _restore_report_text(
            len(matched), len(pinned_keys), extra_tracks_total,
            len(missing_tracks))
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

    def _set_description_group(self, node, description, group_id, name, parent,
                                columns=None, titlebar=True):
        # Copied pattern from frame_tag.py, not imported — these two tags
        # are independent plugins and should not couple through private
        # helpers (same rule the module docstring states for the small
        # c4d helpers above).
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
        return True

    def GetDDescription(self, node, description, flags):
        try:
            description.LoadDescription(node.GetType())
        except Exception:
            pass

        root = c4d.DescID(c4d.DescLevel(c4d.ID_TAGPROPERTIES))

        # Target layout (second usability pass, v1.35.2):
        #   [ Restaurar ]   [ Guardar estado ]
        #      12 objetos · hace 2 h
        #      ⚠ geometría no incluida · N pistas de animación
        #   Nombre   [ ... ]
        #   Color    ☑ [███]
        #   ────────────────────────────────
        #   [ Quitar todos los pins de este objeto ]
        # Estado moved right under the actions — it is the ONLY feedback
        # this tool gives and the thing read every time, so it no longer
        # sits below a whole color block reading like the more important
        # control. Color drops to a single row of the tag's own native
        # parameters (see the ID layout comment). A single column of
        # rows/groups throughout — no multi-column grid competing for
        # width across UNRELATED fields, which is what truncated the
        # status text in the six-slot design this tag replaced.

        # --- Actions: Restaurar first, side by side, no titlebar ----------
        actions_group = _description_parent(ID_GROUP_ACTIONS, c4d.DTYPE_GROUP, node)
        if not self._set_description_group(
            node, description, ID_GROUP_ACTIONS, "", root, columns=2, titlebar=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_PIN_GO, c4d.DTYPE_BUTTON, "Restaurar", actions_group,
            animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_PIN_STORE, c4d.DTYPE_BUTTON,
            "Guardar estado", actions_group, animatable=False
        ):
            return False

        # --- Estado: summary line, then a SEPARATE warning line — see ----
        # --- _pin_status_text / _pin_warning_text for why they must never
        # --- be one concatenated string again ------------------------------
        if not self._set_description_parameter(
            node, description, ID_PIN_STATUS, c4d.DTYPE_STATICTEXT, "Estado", root,
            animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_PIN_WARNING, c4d.DTYPE_STATICTEXT, "", root,
            animatable=False
        ):
            return False

        # --- Nombre: a shortcut to the tag's OWN name, not a field of ----
        # --- our own (see GetDParameter/SetDParameter) -------------------
        if not self._set_description_parameter(
            node, description, ID_PIN_NAME_FIELD, c4d.DTYPE_STRING, "Nombre", root,
            animatable=False
        ):
            return False

        # --- Color: ONE row, the tag's NATIVE icon-tint parameters -------
        # --- exposed directly — C4D's real picker, not a palette of our --
        # --- own (see the ID layout comment and pins.py's "Icon color" ---
        # --- section) -------------------------------------------------------
        color_group = _description_parent(ID_GROUP_COLOR, c4d.DTYPE_GROUP, node)
        if not self._set_description_group(
            node, description, ID_GROUP_COLOR, "Color", root, columns=2, titlebar=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, _ICON_COLORIZE_MODE_ID, c4d.DTYPE_BOOL, "", color_group,
            animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, _ICON_COLOR_ID, c4d.DTYPE_COLOR, "", color_group,
            animatable=False
        ):
            return False

        # --- Separator: sets the destructive action apart from every -----
        # --- ordinary control above it --------------------------------------
        if not self._set_description_parameter(
            node, description, ID_PIN_SEPARATOR, c4d.DTYPE_SEPARATOR, "", root,
            animatable=False
        ):
            return False

        # --- Quitar todos los pins de este objeto -------------------------
        if not self._set_description_parameter(
            node, description, ID_PIN_REMOVE_ALL, c4d.DTYPE_BUTTON,
            "Quitar todos los pins de este objeto", root, animatable=False
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
        if parameter_id == ID_PIN_WARNING:
            # Same derived-field pattern as ID_PIN_STATUS, computed by its
            # OWN function (_pin_warning_text) so the two lines can never
            # be accidentally recombined into one concatenated string
            # again — see that function's docstring for why they must
            # stay independent.
            return True, _pin_warning_text(node), flags | c4d.DESCFLAGS_GET_PARAM_GET
        if parameter_id == ID_PIN_NAME_FIELD:
            # Proxy read, not a mirror: this IS node.GetName(), the exact
            # same data the Basic tab's name field shows — see the ID
            # layout comment for why a copy here would be the mistake
            # this pass exists to undo.
            return True, _safe_node_name(node, ""), flags | c4d.DESCFLAGS_GET_PARAM_GET
        return False

    def SetDParameter(self, node, id, data, flags):
        parameter_id = _desc_level_id(id)
        if parameter_id == ID_PIN_STATUS or parameter_id == ID_PIN_WARNING:
            # Read-only derived strings: swallow writes.
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        if parameter_id == ID_PIN_NAME_FIELD:
            # Proxy write: node.SetName(), the SAME call the Basic tab's
            # name field makes — editing here or there writes the same
            # underlying data, so they cannot compete or revert each
            # other. _sync_display_name is called immediately (rather
            # than waiting for the next Execute tick) so the container
            # mirror it maintains for the reload-reset case (see that
            # function's docstring) stays current the instant an artist
            # types here, not one evaluation later.
            text = str(data) if data is not None else ""
            try:
                node.SetName(text)
            except Exception:
                pass
            _sync_display_name(node)
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        if parameter_id == ID_PIN_GO:
            return _pin_is_filled(node)
        if parameter_id == ID_PIN_REMOVE_ALL:
            obj = node.GetObject()
            return obj is not None and bool(_pin_tags_on_host(obj))
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
        elif command_id == ID_PIN_REMOVE_ALL:
            if _remove_all_pins(node):
                _event_add()
        # No color branch here anymore: ID_BASELIST_ICON_COLORIZE_MODE/
        # ID_BASELIST_ICON_COLOR are native BOOL/COLOR description
        # parameters (see GetDDescription's "Color" section), not buttons
        # — they never reach MSG_DESCRIPTION_COMMAND at all, the base
        # class's own SetParameter handles them.
        return True

    def Message(self, node, mid, data):
        description_command = getattr(c4d, "MSG_DESCRIPTION_COMMAND", None)
        if description_command is not None and mid == description_command:
            return self._handle_command(node, data)
        edit_message = getattr(c4d, "MSG_EDIT", None)
        if edit_message is not None and mid == edit_message:
            # Double-click shortcut (Recall's UX, id 21). MEASURED in C4D
            # 2026.303: double-clicking the tag in the Object Manager DOES
            # route here and restores — verified by the user on a cube
            # parked far from its pinned origin, which snapped back. So
            # this is a real shortcut, not a hopeful one. The "Restaurar"
            # button above remains the guaranteed path; keep the
            # main-thread and filled-pin guards, since this fires from
            # C4D's own gesture handling rather than from a button whose
            # enable state already gates it.
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
