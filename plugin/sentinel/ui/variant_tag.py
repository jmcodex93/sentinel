# -*- coding: utf-8 -*-
"""Sentinel Variants tag: crear un conjunto de opciones y cambiar de opción.

Un tag Sentinel Variants = un CONJUNTO de opciones, puesto sobre el null de
**anclaje** cuyo contenido varía. El anclaje tiene exactamente un hijo: el
null de la opción montada; las demás opciones viven fuera de la jerarquía,
dentro de un contenedor de aparcado en la raíz con la visibilidad de editor
y render apagadas.

Sacar la opción inactiva de la jerarquía (en vez de ocultarla o
desactivarla) es la única vía que cumple la promesa del sistema — medido en
``docs/research/2026-08-05-variant-isolation-spike.md``: un Cloner sigue
clonando la rama invisible, y desactivarla produce un resultado DISTINTO al
de sacarla.

Hechos MEDIDOS en vivo (``docs/research/2026-08-05-variants-reparenting-spike.md``,
C4D 2026.303) que este módulo da por ciertos y no re-deriva:

1. Un reparentado se revierte con **UN solo paso de deshacer** registrando
   ``doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)`` **antes** de ``obj.Remove()`` +
   ``obj.InsertUnder(nuevo_padre)``. Sin ningún ``AddUndo`` el undo no
   revierte nada (control medido). Las variantes sobre los padres o el par
   DELETEOBJ/NEWOBJ también funcionan; se adopta ésta por simple y por no
   abrir un par desbalanceable (un par así causó un bug real en matwire
   v1.32).
2. Los ``BaseLink`` que apuntan DENTRO de lo que se mueve sobreviven a
   mover de padre, a aparcar en la raíz con la visibilidad apagada, y a
   guardar+cargar. **No hay límite de enlaces rotos que declarar** en la
   fila del tag.
3. Reparentar a un null **en identidad** conserva exactamente la
   transformación en el mundo (a uno transformado, no). Por eso el null de
   anclaje y el de cada opción nacen en identidad **por necesidad medida**,
   y NO hace falta recomponer matrices con ``SetMg``. Las claves de
   animación tampoco se recomponen.

El motor puro (nombres de opción, plan de cambio, textos de las filas) vive
en ``sentinel/variants.py`` y no importa c4d. Aquí vive todo lo que toca
escena viva.
"""

import c4d
from c4d import plugins

from sentinel import variants
from sentinel.common.helpers import safe_print

SENTINEL_VARIANT_TAG_PLUGIN_ID = 2099079
SENTINEL_VARIANT_TAG_DESCRIPTION = "Tsentinelvariants"

#: El string exacto pasado a ``RegisterTagPlugin(str=...)`` en
#: ``sentinel_panel.pyp`` — reusado, nunca retecleado, porque la igualdad
#: contra este literal es la ÚNICA señal que ``_sync_display_name`` tiene
#: para "acabo de cargar, C4D reseteó el nombre" (ver esa función). Si
#: alguna vez diverge del ``str=`` real de allí, la detección de reset
#: diverge con él en silencio.
VARIANT_TAG_DEFAULT_NAME = "Sentinel Variants"

#: Nombre del contenedor de aparcado. Es sólo la etiqueta que ve el
#: artista: el contenedor se reencuentra por el ``BaseLink`` del payload,
#: NUNCA por nombre (un null que el artista renombró seguiría siendo el
#: bueno, y uno que llamó igual no lo sería).
VARIANT_PARK_DEFAULT_NAME = "Sentinel Variants (aparcadas)"

# --- Description id layout ------------------------------------------------
# Una sola columna de filas/grupos. Lo que truncó el texto de estado en el
# Pin (v1.35) fue un grid multi-columna repartiendo ancho entre campos que
# compiten; aquí no se repite.
#
# El NOMBRE del conjunto es el nombre del tag (pestaña Basic /
# ``node.GetName()``) y el COLOR es ``ID_BASELIST_ICON_COLORIZE_MODE`` +
# ``ID_BASELIST_ICON_COLOR``, nativos. Ninguno de los dos se construye aquí:
# en el Pin se construyeron ambos y los dos resultaron ser algo que el host
# ya daba — el campo de nombre propio además competía con el nativo y
# revertía los renombrados un tick después.
ID_GROUP_OPTIONS = 1100   # DTYPE_GROUP, 1 columna — la lista de opciones
ID_OPTION_BASE = 1200     # primer id de fila; stride ID_OPTION_STRIDE
ID_OPTION_STRIDE = 10     # +0 botón "montar", +1 nombre, +2 duplicar,
                          # +3 borrar (Tarea 4). Stride 10 deja sitio sin
                          # tocar los ids de arriba si una fila crece.
ID_VARIANTS_STATUS = 1002   # DTYPE_STATICTEXT — resumen (variants.status_text)
ID_VARIANTS_WARNING = 1003  # DTYPE_STATICTEXT — límites (variants.warning_text),
                            # SEPARADO del resumen a propósito (lección del
                            # Pin: concatenada detrás del conteo, la
                            # advertencia es lo primero que se trunca).
# --- Ids RESERVADOS, todavía sin pintar -----------------------------------
# Reservados aquí para que nadie los reutilice, pero NO se declaran en la
# descripción todavía: sus acciones son de las Tareas 4 y 5, y un botón
# pintado que no hace nada es peor que un botón ausente (el artista lo
# pulsa en la verificación en vivo y no pasa nada, sin forma de saber si
# está roto o sin hacer).
ID_VARIANTS_NEW = 1004         # DTYPE_BUTTON — "Duplicar opción activa" (T4)
ID_VARIANTS_RENDER_ALL = 1005  # DTYPE_BUTTON — "Renderizar todas" (T5)
ID_VARIANTS_SEPARATOR = 1006   # DTYPE_SEPARATOR — antes de lo destructivo (T4)

#: El payload vive bajo un id de contenedor privado dentro del contenedor
#: propio del tag, así viaja con el .c4d. Lejos del rango de ids de
#: descripción de arriba.
ID_VARIANTS_PAYLOAD = 20000

#: Espejo del nombre REAL del tag (``node.GetName()``). Existe por una
#: única razón, medida en vivo en la v1.35: C4D repone el nombre de un tag
#: de plugin Python desde su string de registro en CADA carga, y el nombre
#: es la única pieza que no sobrevive el ciclo guardar/recargar por sí sola
#: (el payload sí). Ver ``_sync_display_name``.
ID_VARIANTS_NAME_MIRROR = 20001

#: Se sube sólo si cambia la forma del payload. Un conjunto cuyo esquema
#: esta build no reconoce se lee como vacío — nunca a medias.
VARIANT_SCHEMA = 1

# Sub-keys dentro del BaseContainer del payload (namespace privado a esa
# instancia de contenedor — sin riesgo de colisión con los ids de arriba).
_PAYLOAD_SCHEMA = 1        # int32, VARIANT_SCHEMA
_PAYLOAD_ACTIVE = 2        # int32, índice de la opción montada (-1 = ninguna)
_PAYLOAD_COUNT = 3         # int32
_PAYLOAD_OPTIONS = 4       # BaseContainer indexado 0..N-1
_PAYLOAD_PARK = 5          # BaseLink al contenedor de aparcado
_OPTION_NAME = 1           # string
_OPTION_LINK = 2           # BaseLink al null de la opción


# --- Small c4d helpers (patrón copiado de pin_tag.py, no importado: estos
# tags son plugins independientes y no deben acoplarse por helpers
# privados) -----------------------------------------------------------------

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
        return SENTINEL_VARIANT_TAG_PLUGIN_ID


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


def _report(text):
    """Entrega el resultado de un gesto al artista. Barra de estado primero
    (entrega primaria in-C4D, lección de la v1.30: los banners del sistema
    se los traga macOS en silencio) y consola siempre, que es donde cabe el
    detalle. Best-effort las dos: reportar nunca puede tumbar el gesto que
    ya se hizo."""
    if not text:
        return
    message = "Sentinel Variants: %s" % text
    try:
        c4d.gui.StatusSetText(message)
    except Exception:
        pass
    safe_print(message)


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


def _children_of(obj):
    out = []
    try:
        child = obj.GetDown()
    except Exception:
        return out
    while child is not None:
        out.append(child)
        try:
            child = child.GetNext()
        except Exception:
            break
    return out


def _get_up(obj):
    try:
        return obj.GetUp()
    except Exception:
        return None


def _get_pred(obj):
    try:
        return obj.GetPred()
    except Exception:
        return None


def _new_null(name):
    """Un null NUEVO, en IDENTIDAD. La identidad no se escribe: un
    ``BaseObject`` recién construido ya nace ahí, y es un requisito con
    consecuencia MEDIDA (spike §3: reparentar a un null en identidad
    conserva la transformación en el mundo; a uno transformado, no), no una
    preferencia de estilo."""
    obj = c4d.BaseObject(c4d.Onull)
    try:
        obj.SetName(name)
    except Exception:
        pass
    return obj


def _hide_everywhere(obj):
    """Visibilidad de editor Y render apagadas. Best-effort: el contenedor
    de aparcado sigue aislando aunque esto falle — lo que aísla es estar
    FUERA de la jerarquía (spike de aislamiento), no estar oculto; esto es
    sólo para que no estorbe en el viewport."""
    for param in ("ID_BASEOBJECT_VISIBILITY_EDITOR",
                  "ID_BASEOBJECT_VISIBILITY_RENDER"):
        param_id = getattr(c4d, param, None)
        if param_id is None:
            continue
        try:
            obj[param_id] = c4d.OBJECT_OFF
        except Exception:
            pass


# --- Payload: lectura y escritura -------------------------------------------

def _read_payload_bc(node):
    try:
        bc = node.GetDataInstance()
    except Exception:
        return None
    if bc is None:
        return None
    return bc.GetContainerInstance(ID_VARIANTS_PAYLOAD)


def _store_payload_bc(node, payload):
    """Re-escribe el payload en el contenedor del tag. ``GetContainerInstance``
    devuelve una referencia viva, así que las mutaciones en sitio ya se ven;
    esto lo sella igualmente para no depender de ese detalle."""
    try:
        bc = node.GetDataInstance()
    except Exception:
        return
    if bc is not None:
        bc.SetContainer(ID_VARIANTS_PAYLOAD, payload)


def _option_bc(payload, index):
    if payload is None or index is None or index < 0:
        return None
    options = payload.GetContainerInstance(_PAYLOAD_OPTIONS)
    if options is None:
        return None
    return options.GetContainerInstance(int(index))


def _option_link(payload, index, doc):
    opt = _option_bc(payload, index)
    if opt is None:
        return None
    try:
        return opt.GetLink(_OPTION_LINK, doc)
    except Exception:
        return None


def _subtree_object_count(node):
    """Objetos del subárbol de ``node``, SIN contar ``node`` mismo (el null
    de la opción es andamiaje del sistema, no trabajo del artista).

    Aquí NO se detecta geometría. Se detectaba (``isinstance(obj,
    c4d.PointObject)``, el test del Pin) y no lo leía ningún consumidor:
    ``read_state`` corre desde ``GetDDescription`` y DOS veces desde
    ``GetDParameter`` en cada repintado del Attribute Manager, así que era un
    recorrido por cada nodo de cada opción por repintado a cambio de nada."""
    total = 0
    for child in _children_of(node):
        total += 1 + _subtree_object_count(child)
    return total


def read_state(tag):
    """La forma que consumen ``variants.status_text`` y
    ``variants.warning_text``: ``{"options": [{"name", "resolved",
    "objects"}...], "active", "parked_objects", "orphans"}``.

    Derivada en cada lectura, nunca almacenada — igual que el estado del
    Pin: un conteo guardado se queda viejo en cuanto el artista mete un
    objeto dentro de una opción, y nadie lo volvería a mirar."""
    state = {"options": [], "active": None, "parked_objects": 0, "orphans": 0}
    payload = _read_payload_bc(tag)
    if payload is None:
        return state
    if payload.GetInt32(_PAYLOAD_SCHEMA, 0) != VARIANT_SCHEMA:
        # Un conjunto de otra versión del esquema se lee como vacío — nunca
        # a medias, misma regla que el Pin.
        return state
    doc = _doc_from_node(tag)
    count = payload.GetInt32(_PAYLOAD_COUNT, 0)
    active = payload.GetInt32(_PAYLOAD_ACTIVE, -1)
    for index in range(count):
        opt = _option_bc(payload, index)
        name = opt.GetString(_OPTION_NAME, "") if opt is not None else ""
        node = _option_link(payload, index, doc)
        resolved = node is not None
        objects = _subtree_object_count(node) if resolved else 0
        state["options"].append({
            "name": name,
            "resolved": resolved,
            "objects": objects,
        })
        if not resolved:
            state["orphans"] += 1
        elif index != active:
            state["parked_objects"] += objects
    state["active"] = active if 0 <= active < count else None
    return state


# --- Crear el conjunto ------------------------------------------------------

def _top_level_only(objects):
    """La selección sin los objetos que ya son descendientes de otro
    seleccionado: envolver a un padre y a su hijo por separado metería al
    hijo dos veces. Mismo problema que ``keyframes.collect_shift_set``
    (v1.30) resolvió para el stagger, y con su misma corrección: la
    pertenencia se comprueba contra el conjunto COMPLETO de ids
    seleccionados (no contra un barrido hacia delante de "ya vistos"), así
    que un hijo listado ANTES que su padre tampoco se cuela."""
    roots = [obj for obj in (objects or []) if obj is not None]
    selected_ids = {id(obj) for obj in roots}
    seen = set()
    out = []
    for obj in roots:
        marker = id(obj)
        if marker in seen:
            continue  # entrada duplicada literal en la selección
        seen.add(marker)
        ancestor = _get_up(obj)
        nested = False
        while ancestor is not None:
            if id(ancestor) in selected_ids:
                nested = True
                break
            ancestor = _get_up(ancestor)
        if not nested:
            out.append(obj)
    return out


def _document_order(doc):
    """``{id(obj): posición}`` en el recorrido del Object Manager (primero en
    profundidad), para poder ordenar una selección como se LEE la escena.

    Un objeto que no aparezca en el recorrido (documento que no expone
    ``GetFirstObject``, objeto fuera de él) simplemente no sale en el mapa;
    el llamador lo trata como "al final", con un orden estable."""
    order = {}
    getter = getattr(doc, "GetFirstObject", None)
    if not callable(getter):
        return order
    try:
        node = getter()
    except Exception:
        return order
    counter = 0
    while node is not None:
        order[id(node)] = counter
        counter += 1
        child = None
        try:
            child = node.GetDown()
        except Exception:
            child = None
        if child is not None:
            node = child
            continue
        nxt = None
        while node is not None:
            try:
                nxt = node.GetNext()
            except Exception:
                nxt = None
            if nxt is not None:
                break
            node = _get_up(node)
        node = nxt
    return order


def _in_scene_order(doc, roots):
    """La selección reordenada según el Object Manager.

    **Decisión de contrato (orden jerárquico, no orden de selección).** En la
    v1.31 (Batch Rename) se eligió deliberadamente lo contrario — el orden en
    que el artista fue haciendo clic — porque allí ese orden ES el dato: el
    token ``$n`` numera lo que el artista quiso numerar. Aquí no: envolver una
    selección es una operación de CONTENCIÓN, no de autoría, y nada en la UI
    le pide al artista que ordene nada. Con el orden de clic, la misma
    selección da resultados distintos según en qué orden se pinchó — el orden
    entre hermanos dentro de la opción, y además el sitio del Object Manager
    donde aterriza el anclaje (ocupa el sitio de ``roots[0]``). Ordenar por
    escena hace que el resultado dependa sólo de la escena: los objetos
    conservan su orden entre hermanos (que en C4D es semántico: Boole, Loft,
    Sweep, Symmetry leen a sus hijos por posición) y el anclaje aterriza donde
    empezaba el grupo. Es también lo que pedía el brief de la Tarea 3
    ("conservando el orden entre hermanos").
    """
    order = _document_order(doc)
    fallback = len(order)
    return sorted(roots, key=lambda obj: order.get(id(obj), fallback))


def _anchor_name(first_object):
    return "Opciones · %s" % _safe_node_name(first_object, "")


def _write_new_payload(tag, option_node, option_name):
    payload = c4d.BaseContainer()
    payload.SetInt32(_PAYLOAD_SCHEMA, VARIANT_SCHEMA)
    payload.SetInt32(_PAYLOAD_ACTIVE, 0)
    payload.SetInt32(_PAYLOAD_COUNT, 1)
    option = c4d.BaseContainer()
    option.SetString(_OPTION_NAME, option_name)
    option.SetLink(_OPTION_LINK, option_node)
    options = c4d.BaseContainer()
    options.SetContainer(0, option)
    payload.SetContainer(_PAYLOAD_OPTIONS, options)
    _store_payload_bc(tag, payload)
    return payload


def create_variant_set(doc, objects):
    """Envuelve la selección en un anclaje + el null de la Opción A, y le
    pone el tag del conjunto. UN solo paso de deshacer para todo.

    La selección se ordena por ESCENA, no por orden de clic (la razón, y por
    qué diverge de Batch Rename v1.31, está en ``_in_scene_order``).

    Devuelve ``{"ok", "reason", "tag"}``. El brief pedía ``tag|None`` en la
    lista de entregables y un dict con ``reason`` en el paso 1 (rechazo de
    selección vacía); esto satisface ambas — el motivo del rechazo es
    información que el llamador necesita y un ``None`` pelado no la lleva.
    """
    if doc is None:
        return {"ok": False, "reason": "no_document", "tag": None}
    roots = _in_scene_order(doc, _top_level_only(objects))
    if not roots:
        # Sin bracket: un paso de deshacer que no deshace nada es peor que
        # ninguno, porque el siguiente Cmd+Z del artista se lo gasta sin
        # que la escena cambie (misma regla que variants.plan_switch).
        return {"ok": False, "reason": "no_selection", "tag": None}

    first = roots[0]
    parent = _get_up(first)
    pred = _get_pred(first)
    anchor = _new_null(_anchor_name(first))
    option_name = variants.next_option_name([])
    option = _new_null(option_name)

    tag = None
    doc.StartUndo()
    try:
        # El anclaje ocupa EL SITIO del primero en orden de escena (mismo
        # padre, misma posición entre hermanos): un anclaje que aparece al
        # final del Object Manager es un anclaje que el artista no
        # encuentra. ``pred`` se lee ANTES de mover nada, cuando ``first``
        # sigue en su sitio.
        doc.InsertObject(anchor, parent, pred)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, anchor)
        doc.InsertObject(option, anchor, None)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, option)
        # En orden INVERSO porque ``InsertUnder`` inserta como PRIMER hijo:
        # recorrer al revés deja dentro de la opción el mismo orden que
        # ``_in_scene_order`` fijó, que es el del Object Manager.
        for obj in reversed(roots):
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
            obj.Remove()
            obj.InsertUnder(option)
        tag = anchor.MakeTag(SENTINEL_VARIANT_TAG_PLUGIN_ID)
        if tag is not None:
            # El tag nace sobre un objeto que también nace dentro de este
            # mismo bracket, así que su creación ya la revierte el
            # ``UNDOTYPE_NEWOBJ`` del anclaje (deshacer borra el anclaje y
            # con él sus tags) — no hace falta un undo propio.
            _write_new_payload(tag, option, option_name)
    finally:
        doc.EndUndo()

    _event_add()
    if tag is None:
        return {"ok": False, "reason": "no_tag", "tag": None}
    return {"ok": True, "reason": "", "tag": tag}


# --- Aparcar y montar -------------------------------------------------------

def _ensure_park_container(doc, payload):
    """El contenedor de aparcado, creado PEREZOSAMENTE la primera vez que
    hace falta aparcar algo: una escena con un conjunto de una sola opción
    no tiene por qué llevar un null de más en la raíz.

    Se reencuentra por el ``BaseLink`` del payload, nunca por nombre (un
    null que el artista renombró seguiría siendo el bueno, y uno que llamó
    igual no lo sería); si el enlace no resuelve se crea otro."""
    try:
        existing = payload.GetLink(_PAYLOAD_PARK, doc)
    except Exception:
        existing = None
    if existing is not None:
        return existing
    container = _new_null(VARIANT_PARK_DEFAULT_NAME)
    _hide_everywhere(container)
    doc.InsertObject(container, None, None)
    doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, container)
    payload.SetLink(_PAYLOAD_PARK, container)
    return container


def _reparent(doc, node, new_parent):
    """El movimiento, con el ``AddUndo`` que la Tarea 1 midió: UNDOTYPE_CHANGE
    sobre el objeto que se mueve, ANTES de moverlo. Sin él, el undo no
    revierte nada (control medido en el spike)."""
    doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
    node.Remove()
    node.InsertUnder(new_parent)


def switch_to_option(tag, index):
    """Cambia la opción montada. UN solo paso de deshacer para el par
    completo (aparcar la activa + montar la elegida): son medio gesto cada
    una y deshacer sólo la mitad deja el anclaje vacío o con dos opciones
    dentro, que es un estado que el invariante no admite.

    Devuelve ``{"ok", "reason", "name", "evacuated"}``. ``already_active`` no
    es un error: no se dice nada y no se toca nada. ``evacuated`` lleva los
    NOMBRES de lo que salió del anclaje sin ser la opción aparcada — lo
    único que este gesto hace y no se ve (ver ``variants.switch_report_text``).
    """
    state = read_state(tag)
    plan = variants.plan_switch(len(state["options"]), state["active"], index)
    if not plan["ok"]:
        return {"ok": False, "reason": plan["reason"], "name": "",
                "evacuated": []}

    anchor = tag.GetObject()
    if anchor is None:
        return {"ok": False, "reason": "no_anchor", "name": "", "evacuated": []}
    doc = _doc_from_node(tag)
    if doc is None:
        return {"ok": False, "reason": "no_document", "name": "",
                "evacuated": []}
    payload = _read_payload_bc(tag)
    if payload is None:
        return {"ok": False, "reason": "no_payload", "name": "",
                "evacuated": []}

    # Los enlaces se resuelven ANTES de abrir el bracket. Si el de la
    # opción a montar no resuelve no se toca NADA: mejor un conjunto que no
    # cambia y lo dice, que un anclaje vacío.
    mount_node = _option_link(payload, plan["mount"], doc)
    if mount_node is None:
        return {"ok": False, "reason": "lost_option", "name": "",
                "evacuated": []}
    park_node = None
    if plan["park"] is not None:
        park_node = _option_link(payload, plan["park"], doc)

    # Lo que sale del anclaje NO es sólo la opción que el payload dice que
    # está montada: es TODO lo que cuelgue de él. Un ``park`` que no resuelve
    # (opción huérfana) no es motivo para abortar —montar la elegida sigue
    # siendo correcto y ``read_state`` ya reporta la huérfana—, pero SÍ lo es
    # para mirar el anclaje: en el Object Manager es un null corriente, y algo
    # que el artista arrastrara ahí dentro se quedaría dentro de TODAS las
    # opciones, invisible para el resumen. El invariante ("el anclaje tiene
    # exactamente un hijo") se impone leyendo la escena, no confiando en el
    # payload.
    evacuate = []
    seen = set()
    for node in _children_of(anchor) + ([park_node] if park_node is not None else []):
        if node is None or node is mount_node or id(node) in seen:
            continue
        seen.add(id(node))
        evacuate.append(node)

    # Lo que sale del anclaje SIN ser la opción que tocaba aparcar: objetos
    # que el artista puso ahí a mano y que van a acabar en un contenedor de
    # la raíz con la visibilidad apagada. Los nombres se leen ANTES de
    # mover nada, mientras siguen donde el artista los dejó.
    strays = [_safe_node_name(node, "") for node in evacuate
              if node is not park_node]

    # El cajón se resuelve ANTES de abrir el bracket, igual que los enlaces
    # de arriba: sin él no hay dónde vaciar el anclaje, y montar igual lo
    # dejaría con DOS hijos — el estado que el invariante existe para
    # impedir. Comprobarlo dentro del bracket abría y cerraba un paso de
    # deshacer que no deshacía nada — la misma regla que
    # ``create_variant_set:517`` ("un paso de deshacer que no deshace nada
    # es peor que ninguno"), aplicada aquí al revés hasta este fix.
    container = None
    if evacuate:
        container = _ensure_park_container(doc, payload)
        if container is None:
            return {"ok": False, "reason": "no_park_container",
                    "name": "", "evacuated": []}

    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
        if evacuate:
            for node in evacuate:
                _reparent(doc, node, container)
        _reparent(doc, mount_node, anchor)
        payload.SetInt32(_PAYLOAD_ACTIVE, int(plan["mount"]))
        _store_payload_bc(tag, payload)
    finally:
        doc.EndUndo()

    _event_add()
    return {
        "ok": True,
        "reason": "",
        "name": state["options"][plan["mount"]]["name"],
        "evacuated": strays,
    }


# --- Nombre del conjunto: sobrevivir a cargar -------------------------------

def _sync_display_name(node):
    """Mantiene el nombre del conjunto (= el nombre del tag) vivo a través
    de un guardar+cargar.

    Política heredada TAL CUAL de ``pin_tag._sync_display_name`` (v1.35, dos
    bugs medidos en vivo allí — leerla, no re-derivarla): C4D repone el
    nombre de un tag de plugin desde su string de registro en cada carga,
    así que hace falta un espejo en el contenedor propio; pero confiar en
    el espejo siempre que discrepe del nombre vivo REVIERTE un renombrado
    real un tick después (``Execute`` tickea continuamente).

    Por eso: el nombre del tag manda, incondicionalmente, con una sola
    excepción — que lea EXACTAMENTE ``VARIANT_TAG_DEFAULT_NAME``, que es la
    firma indistinguible de "una carga acaba de borrarlo". Cualquier otro
    nombre se copia AL espejo, para que la PRÓXIMA carga tenga de dónde
    restaurar.

    Idempotente: seguro en cada tick de ``Execute``, sin flag de sucio.
    """
    try:
        bc = node.GetDataInstance()
    except Exception:
        return
    if bc is None:
        return
    current = _safe_node_name(node, "")
    if current == VARIANT_TAG_DEFAULT_NAME:
        mirrored = bc.GetString(ID_VARIANTS_NAME_MIRROR, "")
        if mirrored and mirrored != current:
            try:
                node.SetName(mirrored)
            except Exception:
                pass
        return
    if bc.GetString(ID_VARIANTS_NAME_MIRROR, "") != current:
        bc.SetString(ID_VARIANTS_NAME_MIRROR, current)


# --- El TagData -------------------------------------------------------------

try:
    _TagDataBase = plugins.TagData
    if not isinstance(_TagDataBase, type):
        raise TypeError("plugins.TagData is not a class")
    _SENTINEL_VARIANT_TAG_AVAILABLE = True
except Exception:
    _TagDataBase = object
    _SENTINEL_VARIANT_TAG_AVAILABLE = False


def _option_row_label(option, is_active):
    """"● Opción A" para la montada, "○ Opción A" para las demás — cuál
    está puesta se ve en la propia fila, sin leer el resumen. Una opción
    cuyo enlace no resuelve lo dice en su etiqueta en vez de ofrecer un
    botón que no puede funcionar."""
    name = option.get("name") or ""
    if not option.get("resolved", True):
        return "⚠ %s (no encontrada)" % name
    return "%s %s" % ("●" if is_active else "○", name)


def _option_command(command_id, option_count):
    """``(index, action)`` de un id de fila, o ``None`` si el id no cae en
    el rango de filas REALMENTE pintadas.

    La cota superior no es cosmética (patrón de la casa,
    ``frame_tag.py:2485`` acota igual): sin ella cualquier id ≥
    ``ID_OPTION_BASE`` múltiplo de ``ID_OPTION_STRIDE`` se lee como fila de
    opción, así que ``GetDEnabling`` devolvería ``False`` para un control que
    no es nuestro y ``Message`` se tragaría su comando sin dispararlo. Las
    Tareas 4 y 5 añaden ids; esto los deja fuera por construcción.

    Se acota por el número de opciones (que es lo que ``GetDDescription``
    pinta) en vez de por una constante inventada: una constante o deja filas
    reales inertes o deja hueco muerto dentro del bloque."""
    count = int(option_count or 0)
    if count <= 0 or command_id < ID_OPTION_BASE:
        return None
    offset = command_id - ID_OPTION_BASE
    if offset >= count * ID_OPTION_STRIDE:
        return None
    return offset // ID_OPTION_STRIDE, offset % ID_OPTION_STRIDE


def _payload_option_count(node):
    """El número de opciones leído DIRECTO del payload — O(1), sin recorrer
    subárboles. ``_option_command`` se llama desde ``GetDEnabling``, que corre
    por cada parámetro en cada repintado del Attribute Manager; ahí un
    ``read_state`` completo sería el mismo coste que el Minor 8 acaba de
    quitar."""
    payload = _read_payload_bc(node)
    if payload is None:
        return 0
    if payload.GetInt32(_PAYLOAD_SCHEMA, 0) != VARIANT_SCHEMA:
        return 0
    return int(payload.GetInt32(_PAYLOAD_COUNT, 0) or 0)


class SentinelVariantsTag(_TagDataBase):
    """TagData del conjunto de opciones: la lista, el resumen y los límites."""

    def _set_description_parameter(
        self, node, description, parameter_id, dtype, name, parent,
        animatable=True,
    ):
        desc_id = _description_parent(parameter_id, dtype, node)
        bc = c4d.GetCustomDatatypeDefault(dtype)
        _set_bc_value(bc, "SetString", c4d.DESC_NAME, name)
        _set_bc_value(bc, "SetString", c4d.DESC_SHORT_NAME, name)
        if not animatable:
            # Ningún parámetro de fila es keyframeable — son estado o
            # disparadores. El Frame tag midió en vivo que los animables
            # pintan un rombo por fila y que los rombos eran el mayor coste
            # de ancho (v1.29); se trae como restricción de día uno, no se
            # re-descubre.
            animate_off = getattr(c4d, "DESC_ANIMATE_OFF", None)
            if animate_off is not None:
                _set_bc_value(bc, "SetInt32", c4d.DESC_ANIMATE, animate_off)
        if dtype == c4d.DTYPE_BUTTON:
            # Sin CUSTOMGUI_BUTTON un DTYPE_BUTTON se pinta como celda
            # vacía, no como botón (frame_tag.py:1775, confirmado en vivo
            # allí — no re-descubrir).
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
        return True

    def GetDDescription(self, node, description, flags):
        try:
            description.LoadDescription(node.GetType())
        except Exception:
            pass

        root = c4d.DescID(c4d.DescLevel(c4d.ID_TAGPROPERTIES))
        state = read_state(node)

        # Layout objetivo:
        #   Opciones
        #     [ ● Opción A ]
        #     [ ○ sin bend, subdiv 3 ]
        #   Estado   Opción A · 2 opciones · 3 objetos montados
        #            ⚠ 4 objetos aparcados siguen en la escena
        # Una sola columna: el grupo de opciones lleva una fila por opción y
        # nada compite por el ancho con el texto de estado.
        options_group = _description_parent(ID_GROUP_OPTIONS, c4d.DTYPE_GROUP, node)
        if not self._set_description_group(
            node, description, ID_GROUP_OPTIONS, "Opciones", root, columns=1
        ):
            return False
        for index, option in enumerate(state["options"]):
            if not self._set_description_parameter(
                node, description, ID_OPTION_BASE + index * ID_OPTION_STRIDE,
                c4d.DTYPE_BUTTON, _option_row_label(option, index == state["active"]),
                options_group, animatable=False
            ):
                return False

        # Resumen y límites en DOS filas separadas — nunca concatenadas
        # (lección del Pin: detrás del conteo, la advertencia es lo primero
        # que se trunca).
        if not self._set_description_parameter(
            node, description, ID_VARIANTS_STATUS, c4d.DTYPE_STATICTEXT,
            "Estado", root, animatable=False
        ):
            return False
        if not self._set_description_parameter(
            node, description, ID_VARIANTS_WARNING, c4d.DTYPE_STATICTEXT,
            "", root, animatable=False
        ):
            return False

        return True, flags | c4d.DESCFLAGS_DESC_LOADED

    def GetDParameter(self, node, id, flags):
        # Ambas líneas son campos DERIVADOS (mismo patrón que ID_PIN_STATUS
        # del Pin y ID_SYNC_STATUS del Frame): nunca se escriben en el dato
        # real del nodo, así que su texto no puede quedarse viejo.
        parameter_id = _desc_level_id(id)
        if parameter_id == ID_VARIANTS_STATUS:
            return (True, variants.status_text(read_state(node)),
                    flags | c4d.DESCFLAGS_GET_PARAM_GET)
        if parameter_id == ID_VARIANTS_WARNING:
            return (True, variants.warning_text(read_state(node)),
                    flags | c4d.DESCFLAGS_GET_PARAM_GET)
        return False

    def SetDParameter(self, node, id, data, flags):
        parameter_id = _desc_level_id(id)
        if parameter_id in (ID_VARIANTS_STATUS, ID_VARIANTS_WARNING):
            # Strings derivados de sólo lectura: se traga la escritura.
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        row = _option_command(parameter_id, _payload_option_count(node))
        if row is not None and row[1] == 0:
            state = read_state(node)
            index = row[0]
            if not (0 <= index < len(state["options"])):
                return False
            # La opción montada no se puede volver a montar, y una cuyo
            # enlace se perdió tampoco: el botón dice la verdad en vez de
            # aceptar el clic y no hacer nada.
            option = state["options"][index]
            return bool(option["resolved"]) and index != state["active"]
        return True

    def Execute(self, tag, doc, op, bt, priority, flags):
        # El camino GARANTIZADO del que depende el nombre del conjunto (ver
        # _sync_display_name): Execute corre en cada re-evaluación de la
        # escena, incluida la que dispara una carga para dibujar el
        # viewport, y sin que el artista abra este tag en el Attribute
        # Manager — que es el requisito real, porque el nombre se lee en el
        # Object Manager.
        _sync_display_name(tag)
        return c4d.EXECUTIONRESULT_OK

    def _handle_command(self, node, data):
        if not _is_main_thread():
            return True
        command_id = _command_id_from_data(data)
        row = _option_command(command_id, _payload_option_count(node))
        if row is not None and row[1] == 0:
            _report(variants.switch_report_text(switch_to_option(node, row[0])))
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
