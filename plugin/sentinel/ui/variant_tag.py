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

import os

import c4d
from c4d import plugins

from sentinel import postrender
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
ID_OPTION_STRIDE = 10     # +0 botón "montar", +1 nombre, +2 borrar, +9 el
                          # grupo de la fila. Stride 10 deja sitio sin tocar
                          # los ids de arriba si una fila crece.

#: Offsets DENTRO del stride de una fila. Duplicar NO está aquí: es un solo
#: botón para todo el conjunto (``ID_VARIANTS_NEW``), porque lo que se
#: duplica es la opción MONTADA — la que el artista está mirando — y un
#: botón por fila prometería duplicar una que ni siquiera está en la escena.
_OPTION_ACTION_MOUNT = 0
_OPTION_ACTION_NAME = 1
_OPTION_ACTION_DELETE = 2
#: El grupo que mete los tres controles de una opción EN UNA LÍNEA. Va en el
#: último hueco del stride para dejar los primeros a controles de verdad. El
#: grupo de opciones sigue a UNA columna (ver ID_GROUP_OPTIONS): quien
#: reparte ancho es este sub-grupo, dentro de la fila, así que el texto de
#: estado —que cuelga de la raíz— no compite con nada (la lección del Pin
#: era sobre el estado, no sobre las filas).
_OPTION_ACTION_GROUP = 9
ID_VARIANTS_STATUS = 1002   # DTYPE_STATICTEXT — resumen (variants.status_text)
ID_VARIANTS_WARNING = 1003  # DTYPE_STATICTEXT — límites (variants.warning_text),
                            # SEPARADO del resumen a propósito (lección del
                            # Pin: concatenada detrás del conteo, la
                            # advertencia es lo primero que se trunca).
ID_VARIANTS_NEW = 1004         # DTYPE_BUTTON — "Duplicar opción activa"
# Ambos POR DEBAJO de ID_OPTION_BASE por necesidad: un id por encima quedaría
# inerte hasta que el conjunto tuviera bastantes opciones y entonces se lo
# tragaría el bloque de filas.
ID_VARIANTS_RENDER_ALL = 1005  # DTYPE_BUTTON — "Renderizar todas las opciones"
#: RESERVADO, todavía sin pintar — un botón (o un separador) que no hace nada
#: es peor que uno ausente: el artista lo ve en la verificación en vivo y no
#: puede saber si está roto o sin hacer. Reservado sólo para que nadie
#: reutilice el id.
ID_VARIANTS_SEPARATOR = 1006   # DTYPE_SEPARATOR
#: DTYPE_STATICTEXT — lo que el recorrido del render deja detrás (un bloque
#: de deshacer, la escena como estaba), dicho ANTES de pulsarlo. Va pegado a
#: su botón y no al bloque de estado: es información sobre una acción, no
#: sobre el conjunto (ver variants.render_hint_text).
ID_VARIANTS_RENDER_HINT = 1007

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
    pertenencia se comprueba contra el conjunto COMPLETO de seleccionados
    (no contra un barrido hacia delante de "ya vistos"), así que un hijo
    listado ANTES que su padre tampoco se cuela.

    Identidad por VALOR, nunca por ``id()``: C4D devuelve un envoltorio
    Python NUEVO en cada lectura del mismo nodo (medido en vivo —
    ``d.GetFirstObject()`` dos veces da ``id()`` distinto del mismo objeto),
    así que un ``obj`` de la selección y el ``ancestor`` que ``GetUp()``
    entrega al subir por la jerarquía pueden ser dos envoltorios distintos
    del MISMO nodo. ``hash()``/``==`` sí coinciden entre lecturas (también
    medido), así que el propio ``BaseObject`` sirve como elemento de
    ``set`` — comparar por ``id()`` aquí dejaba pasar hijos anidados como si
    fueran raíces."""
    roots = [obj for obj in (objects or []) if obj is not None]
    selected = set(roots)
    seen = set()
    out = []
    for obj in roots:
        if obj in seen:
            continue  # entrada duplicada literal en la selección
        seen.add(obj)
        ancestor = _get_up(obj)
        nested = False
        while ancestor is not None:
            if ancestor in selected:
                nested = True
                break
            ancestor = _get_up(ancestor)
        if not nested:
            out.append(obj)
    return out


def _document_order(doc):
    """``{obj: posición}`` en el recorrido del Object Manager (primero en
    profundidad), para poder ordenar una selección como se LEE la escena.

    Clave por VALOR (``obj`` en sí, no ``id(obj)``): el recorrido lee sus
    propios envoltorios frescos vía ``GetDown()``/``GetNext()``, y el
    llamador (``_in_scene_order``) busca en este mapa con los objetos de SU
    propia selección — una lectura distinta del mismo nodo, con ``id()``
    propio (medido en vivo). ``hash()``/``==`` sí coinciden entre lecturas,
    así que el diccionario funciona con el ``BaseObject`` como clave
    directamente; con ``id()`` la búsqueda fallaba siempre y todo caía al
    "al final" de abajo, dejando el orden de clic intacto en vez del de
    escena.

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
        order[node] = counter
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
    return sorted(roots, key=lambda obj: order.get(obj, fallback))


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


def _switch_work(tag, index):
    """``(reason, work)`` — TODO lo que un cambio de opción necesita resolver
    ANTES de abrir un bracket de deshacer, sin tocar la escena. ``reason`` es
    "" cuando el cambio se puede hacer.

    Existe separado de ``switch_to_option`` porque hay DOS llamadores con
    brackets distintos: un cambio a mano abre el suyo (un gesto = un paso de
    deshacer) y el recorrido de ``render_all_options`` mete todos los suyos
    en UNO solo (sus cambios no son gestos del artista, y N+1 pasos que
    deshacer uno a uno serían inaceptables). La preparación y la aplicación
    son las MISMAS en los dos casos: duplicarlas era garantizar que un fix en
    una no llegara a la otra."""
    state = read_state(tag)
    plan = variants.plan_switch(len(state["options"]), state["active"], index)
    if not plan["ok"]:
        return plan["reason"], None

    anchor = tag.GetObject()
    if anchor is None:
        return "no_anchor", None
    doc = _doc_from_node(tag)
    if doc is None:
        return "no_document", None
    payload = _read_payload_bc(tag)
    if payload is None:
        return "no_payload", None

    # Los enlaces se resuelven ANTES de abrir el bracket. Si el de la
    # opción a montar no resuelve no se toca NADA: mejor un conjunto que no
    # cambia y lo dice, que un anclaje vacío.
    mount_node = _option_link(payload, plan["mount"], doc)
    if mount_node is None:
        return "lost_option", None
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
    #
    # Identidad por VALOR en todo este bloque, nunca ``id()``/``is``: los
    # nodos de ``_children_of(anchor)`` (jerarquía) y ``mount_node``/
    # ``park_node`` (``GetLink`` sobre el payload) son lecturas DISTINTAS —
    # C4D entrega un envoltorio Python nuevo cada vez (medido en vivo), así
    # que la opción ya montada, leída por las dos vías, puede llegar aquí
    # como dos objetos con ``id()`` propio. ``hash()``/``==`` sí coinciden
    # entre lecturas: comparar por valor es lo único que dedupa de verdad y
    # reconoce que ``park_node`` es el mismo nodo que su hijo del anclaje —
    # con ``is``/``id()`` la opción activa se colaba dos veces en
    # ``evacuate`` y salía reportada como un "stray" fantasma.
    evacuate = []
    seen = set()
    for node in _children_of(anchor) + ([park_node] if park_node is not None else []):
        if node is None or node == mount_node or node in seen:
            continue
        seen.add(node)
        evacuate.append(node)

    # Lo que sale del anclaje SIN ser la opción que tocaba aparcar: objetos
    # que el artista puso ahí a mano y que van a acabar en un contenedor de
    # la raíz con la visibilidad apagada. Los nombres se leen ANTES de
    # mover nada, mientras siguen donde el artista los dejó.
    strays = [_safe_node_name(node, "") for node in evacuate
              if node != park_node]

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
            return "no_park_container", None

    return "", {
        "doc": doc,
        "anchor": anchor,
        "payload": payload,
        "mount": int(plan["mount"]),
        "mount_node": mount_node,
        "evacuate": evacuate,
        "container": container,
        "strays": strays,
        "name": state["options"][plan["mount"]]["name"],
    }


def _apply_switch(tag, work):
    """El movimiento en sí. **No abre bracket**: quien llama decide en qué
    paso de deshacer cae (ver ``_switch_work``)."""
    doc = work["doc"]
    doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
    for node in work["evacuate"]:
        _reparent(doc, node, work["container"])
    _reparent(doc, work["mount_node"], work["anchor"])
    work["payload"].SetInt32(_PAYLOAD_ACTIVE, work["mount"])
    _store_payload_bc(tag, work["payload"])


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
    reason, work = _switch_work(tag, index)
    if reason:
        return {"ok": False, "reason": reason, "name": "", "evacuated": []}

    doc = work["doc"]
    doc.StartUndo()
    try:
        _apply_switch(tag, work)
    finally:
        doc.EndUndo()

    _event_add()
    return {
        "ok": True,
        "reason": "",
        "name": work["name"],
        "evacuated": work["strays"],
    }


# --- Duplicar, renombrar y borrar -------------------------------------------

def _tag_context(tag):
    """``(anchor, doc, payload, reason)`` — las tres piezas que todo gesto que
    toca la escena necesita, resueltas ANTES de abrir ningún bracket (misma
    regla que ``switch_to_option``: un paso de deshacer que no deshace nada
    es peor que ninguno). ``reason`` es "" cuando las tres están."""
    anchor = tag.GetObject() if tag is not None else None
    if anchor is None:
        return None, None, None, "no_anchor"
    doc = _doc_from_node(tag)
    if doc is None:
        return anchor, None, None, "no_document"
    payload = _read_payload_bc(tag)
    if payload is None:
        return anchor, doc, None, "no_payload"
    return anchor, doc, payload, ""


def _evacuate_anchor(doc, anchor, container, keep=None):
    """Saca del anclaje todo lo que no sea ``keep``. El invariante ("el
    anclaje tiene exactamente un hijo") se impone leyendo la escena, no
    confiando en el payload — el anclaje es un null corriente en el Object
    Manager y el artista puede haber arrastrado algo dentro.

    Identidad por VALOR (``==``, nunca ``is``/``id()``): ``keep`` llega de un
    ``GetLink`` del payload y los hijos de ``_children_of``; en C4D real son
    lecturas distintas del MISMO nodo, con ``id()`` propio."""
    moved = []
    for node in _children_of(anchor):
        if node is None or (keep is not None and node == keep):
            continue
        _reparent(doc, node, container)
        moved.append(node)
    return moved


def _write_option(payload, index, name, node):
    options = payload.GetContainerInstance(_PAYLOAD_OPTIONS)
    if options is None:
        options = c4d.BaseContainer()
        payload.SetContainer(_PAYLOAD_OPTIONS, options)
        options = payload.GetContainerInstance(_PAYLOAD_OPTIONS)
    option = c4d.BaseContainer()
    option.SetString(_OPTION_NAME, name)
    option.SetLink(_OPTION_LINK, node)
    options.SetContainer(int(index), option)


def duplicate_active_option(tag):
    """Copia la opción montada CON su subárbol y deja al artista trabajando
    sobre la copia — es el gesto que sustituye al "Cmd+C y arrastrar al
    backup" de hoy, y dejar montada la original haría que el artista editara
    justo la que quería conservar.

    ``GetClone`` se lleva jerarquía, parámetros, pistas de animación y los
    tags de material apuntando a los MISMOS materiales (por eso el Material
    Manager no engorda) — hecho a verificar en vivo, no aquí: el arnés de
    tests no tiene materiales que compartir.

    Devuelve ``{"ok", "reason", "action", "name", "evacuated"}``.
    ``evacuated`` lleva los NOMBRES de lo que salió del anclaje sin ser la
    opción que se copia — este gesto hace la MISMA evacuación silenciosa que
    ``switch_to_option`` (un objeto que el artista había arrastrado al
    anclaje acaba en un null oculto de la raíz), y sin este canal no aparece
    en ninguna superficie: ``read_state`` sólo suma subárboles de opciones
    resueltas, así que ``warning_text`` tampoco lo ve."""
    fail = {"ok": False, "action": "duplicate", "name": "", "evacuated": []}
    state = read_state(tag)
    active = state["active"]
    if active is None:
        return dict(fail, reason="no_active")
    anchor, doc, payload, reason = _tag_context(tag)
    if reason:
        return dict(fail, reason=reason)

    source = _option_link(payload, active, doc)
    if source is None:
        return dict(fail, reason="lost_option")
    try:
        clone = source.GetClone(c4d.COPYFLAGS_0)
    except Exception:
        clone = None
    if clone is None:
        return dict(fail, reason="clone_failed")

    names = [option["name"] for option in state["options"]]
    name = variants.dedupe_option_name(variants.next_option_name(names), names)
    try:
        clone.SetName(name)
    except Exception:
        pass

    # El cajón se resuelve ANTES del bracket, igual que en switch_to_option:
    # la opción que está puesta tiene que salir del anclaje, y sin sitio
    # donde ponerla montar la copia lo dejaría con DOS hijos. Sólo si hay
    # algo que sacar: un anclaje vacío no justifica un null de más en la
    # raíz de la escena.
    container = None
    strays = []
    if _children_of(anchor):
        container = _ensure_park_container(doc, payload)
        if container is None:
            return dict(fail, reason="no_park_container")
        # Los nombres se leen ANTES de mover nada, mientras siguen donde el
        # artista los dejó (mismo patrón que switch_to_option). La opción
        # que se copia no cuenta: aparcarla es el gesto, no una sorpresa.
        strays = [_safe_node_name(node, "") for node in _children_of(anchor)
                  if node is not None and node != source]

    index = len(state["options"])
    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
        if container is not None:
            _evacuate_anchor(doc, anchor, container)
        doc.InsertObject(clone, anchor, None)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, clone)
        _write_option(payload, index, name, clone)
        payload.SetInt32(_PAYLOAD_COUNT, index + 1)
        payload.SetInt32(_PAYLOAD_ACTIVE, index)
        _store_payload_bc(tag, payload)
    finally:
        doc.EndUndo()

    _event_add()
    return {"ok": True, "reason": "", "action": "duplicate", "name": name,
            "evacuated": strays}


def rename_option(tag, index, name):
    """Escribe el nombre de la opción en el payload Y en su null a la vez —
    el segundo es lo que el artista ve en el Object Manager.

    El nombre del CONJUNTO es el del tag y no se toca aquí (lección del Pin:
    un campo propio compitiendo con el nativo revertía los renombrados un
    tick después). El de la opción es dato propio, y sí.

    Pasa siempre por ``dedupe_option_name`` contra las DEMÁS opciones: dos
    con el mismo nombre son indistinguibles en la fila y en los nombres de
    archivo del render."""
    fail = {"ok": False, "action": "rename", "name": ""}
    state = read_state(tag)
    count = len(state["options"])
    if index is None or not (0 <= int(index) < count):
        return dict(fail, reason="bad_index")
    index = int(index)
    anchor, doc, payload, reason = _tag_context(tag)
    if reason:
        return dict(fail, reason=reason)

    others = [option["name"] for position, option in enumerate(state["options"])
              if position != index]
    final = variants.dedupe_option_name(name, others)
    if final == state["options"][index]["name"]:
        # Se pidió el nombre que ya tenía. El Attribute Manager reescribe el
        # campo con lo que acaba de leer en cada repintado, así que abrir un
        # bracket aquí gastaría un paso de deshacer por repintado.
        return {"ok": False, "reason": "unchanged", "action": "rename",
                "name": final}

    node = _option_link(payload, index, doc)
    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
        option = _option_bc(payload, index)
        if option is not None:
            option.SetString(_OPTION_NAME, final)
        _store_payload_bc(tag, payload)
        if node is not None:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
            try:
                node.SetName(final)
            except Exception:
                pass
    finally:
        doc.EndUndo()

    _event_add()
    return {"ok": True, "reason": "", "action": "rename", "name": final}


def delete_option(tag, index):
    """Borra una opción y su contenido. SIN confirmación: es revertible con
    un Cmd+Z como todo lo demás, y un diálogo por borrado convierte el gesto
    en una ceremonia.

    ``variants.plan_delete`` decide qué se borra y QUÉ QUEDA ACTIVO — la
    segunda mitad es la que se equivoca sola, porque borrar una opción
    anterior a la activa desplaza su índice.

    Devuelve ``{"ok", "reason", "action", "name", "mounted", "evacuated"}``;
    ``mounted`` lleva el nombre de la que quedó puesta cuando el borrado
    obligó a montar otra, y "" cuando no cambió nada más. ``evacuated`` lleva
    los NOMBRES de lo que salió del anclaje para hacerle sitio — la misma
    evacuación silenciosa que reporta ``switch_to_option``, y que sin este
    canal no aparecería en ninguna superficie."""
    fail = {"ok": False, "action": "delete", "name": "", "mounted": "",
            "evacuated": []}
    state = read_state(tag)
    count = len(state["options"])
    plan = variants.plan_delete(count, state["active"], index)
    if not plan["ok"]:
        return dict(fail, reason=plan["reason"])
    anchor, doc, payload, reason = _tag_context(tag)
    if reason:
        return dict(fail, reason=reason)

    target = plan["delete"]
    new_active = plan["new_active"]
    victim = _option_link(payload, target, doc)
    name = state["options"][target]["name"]

    # Se borra la que está puesta: hay que montar otra ANTES, o el anclaje se
    # queda vacío. El índice del plan es el de DESPUÉS de borrar; el nodo hay
    # que buscarlo con el de AHORA (los índices por debajo del borrado no se
    # desplazan, los de encima sí).
    mount_node = None
    mounted_name = ""
    if state["active"] is not None and int(state["active"]) == target:
        before = new_active if new_active < target else new_active + 1
        mount_node = _option_link(payload, before, doc)
        if mount_node is None:
            return dict(fail, reason="lost_option")
        mounted_name = state["options"][before]["name"]

    # Lo que cuelga del anclaje sin ser la víctima tiene que salir para poder
    # montar la que promociona — y sin cajón no hay dónde. Resuelto ANTES del
    # bracket (misma regla que switch_to_option).
    container = None
    stray_names = []
    if mount_node is not None:
        strays = [node for node in _children_of(anchor)
                  if node is not None and (victim is None or node != victim)]
        if strays:
            # Nombres leídos ANTES de mover nada, mientras siguen donde el
            # artista los dejó (mismo patrón que switch_to_option).
            stray_names = [_safe_node_name(node, "") for node in strays]
            container = _ensure_park_container(doc, payload)
            if container is None:
                return dict(fail, reason="no_park_container")

    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
        if mount_node is not None:
            if container is not None:
                _evacuate_anchor(doc, anchor, container, keep=victim)
            _reparent(doc, mount_node, anchor)
        if victim is not None:
            # DELETEOBJ antes del Remove, patrón de fixes.py/scene_tools.py:
            # sin él un Cmd+Z no trae de vuelta el subárbol borrado.
            doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, victim)
            victim.Remove()
        kept = [_option_bc(payload, position) for position in range(count)
                if position != target]
        # La lista se COMPACTA: una entrada que no existe (payload escrito a
        # mano, esquema a medias) se descarta y las siguientes bajan de
        # índice. Saltarse su posición dejaría un hueco dentro de
        # ``0..count-2`` donde ``_option_bc`` devuelve None y la fila sale
        # vacía y no resuelta para siempre — protegerse del None sin
        # manejarlo después.
        options = c4d.BaseContainer()
        written = 0
        active_after = 0
        for position, option in enumerate(kept):
            if position == int(new_active):
                # Dónde acaba la que el plan deja activa: su índice en
                # ``kept`` deja de ser el suyo en cuanto se descarta algo
                # por delante.
                active_after = written
            if option is None:
                continue
            options.SetContainer(written, option)
            written += 1
        payload.SetContainer(_PAYLOAD_OPTIONS, options)
        payload.SetInt32(_PAYLOAD_COUNT, written)
        payload.SetInt32(_PAYLOAD_ACTIVE,
                         min(active_after, written - 1) if written else -1)
        _store_payload_bc(tag, payload)
    finally:
        doc.EndUndo()

    _event_add()
    return {"ok": True, "reason": "", "action": "delete", "name": name,
            "mounted": mounted_name, "evacuated": stray_names}


# --- Renderizar todas las opciones ------------------------------------------
#
# Sustituye a la salida a Takes que el spike descartó por mecanismo. La vía
# es la SÍNCRONA, y no por elegancia: está MEDIDA en vivo con el motor real
# de trabajo (Redshift, ``docs/research/2026-08-05-variants-reparenting-spike.md``
# §4) — ``RenderDocument`` devuelve ``RENDERRESULT_OK``, el bitmap trae
# píxeles reales (escena vacía 0 vs. escena con un cubo 8058: el caso base
# era obligatorio, porque un bitmap negro con OK es exactamente el resultado
# nulo que parece una respuesta), ``Save`` escribe, y tres llamadas seguidas
# no cuelgan C4D. La vía asíncrona (ruta por opción + render nativo +
# espera) no hizo falta y no se exploró.

#: La extensión y el filtro van juntos SIEMPRE: escribir un PNG con nombre
#: ``.exr`` (o al revés) produce un archivo que ningún visor abre. PNG
#: porque estas imágenes son para MIRAR las opciones una al lado de otra, no
#: para componer.
_RENDER_EXTENSION = ".png"

#: Las imágenes de las opciones son material de DECISIÓN, no de entrega: no
#: pueden aparecer sueltas en la carpeta de salida del render, mezcladas con
#: los beauties que el artista entrega al cliente. Verificado en vivo: con un
#: preset que guarda en ``.../ENTREGA/shot_beauty``, los PNG de las opciones
#: aparecían sueltos en ``.../ENTREGA/``. Van en su propia subcarpeta, hija de
#: la que ya resuelve ``_render_output_folder``.
_VARIANTS_SUBFOLDER = "variants"


def _current_take(doc):
    """El take activo, o ``None``. Hace falta para resolver ``$take`` en la
    ruta de salida — un preset con ``$take`` en la parte de directorio es
    exactamente el caso que la QC #9 de este mismo plugin EXIGE."""
    try:
        take_data = doc.GetTakeData()
        return take_data.GetCurrentTake() if take_data is not None else None
    except Exception:
        return None


def _current_frame(doc):
    try:
        return int(doc.GetTime().GetFrame(doc.GetFps()))
    except Exception:
        return 0


def _render_output_folder(doc):
    """Dónde van las imágenes: la carpeta de salida del render de la escena;
    si no hay ninguna configurada, la del propio documento; y "" si el
    documento no está guardado — sin sitio donde escribir no se renderiza
    nada (el llamador lo reporta como ``unsaved_scene``).

    Los tokens de la ruta (``$prj``, ``$take``, ``$camera``...) se resuelven
    con el sistema de tokens DE C4D (``postrender.resolve_render_tokens``, la
    misma pieza que usa la validación post-render): no se duplica el sistema,
    se llama. Importa porque el caso con token es el NORMAL, no el raro — la
    QC #9 de este mismo plugin (``checks/render.py``) suspende cualquier
    preset cuya ruta no lleve ``$prj`` o ``$take``, así que toda escena que
    pasa la QC de Sentinel llega aquí con tokens, y en cuanto el token está
    en la parte de directorio (``$prj/images/…``) una carpeta sin resolver se
    descartaría SIEMPRE.

    Sólo si tras resolver SIGUE habiendo un ``$`` (token que este C4D no
    conoce) se cae a la carpeta del documento: crear una carpeta llamada
    literalmente ``$prj`` sería escribir donde el artista no pidió."""
    doc_path = ""
    getter = getattr(doc, "GetDocumentPath", None)
    if callable(getter):
        try:
            doc_path = getter() or ""
        except Exception:
            doc_path = ""

    raw = ""
    try:
        render_data = doc.GetActiveRenderData()
    except Exception:
        render_data = None
    if render_data is not None:
        try:
            raw = render_data[c4d.RDATA_PATH] or ""
        except Exception:
            raw = ""
        if raw:
            raw = postrender.resolve_render_tokens(
                doc, str(raw), render_data,
                _current_take(doc), _current_frame(doc))
    folder = os.path.dirname(str(raw)) if raw else ""
    if folder and "$" not in folder:
        if os.path.isabs(folder):
            return folder
        if doc_path:
            return os.path.join(doc_path, folder)
    return doc_path


def _scene_stem(doc):
    getter = getattr(doc, "GetDocumentName", None)
    if not callable(getter):
        return ""
    try:
        return os.path.splitext(getter() or "")[0]
    except Exception:
        return ""


def _preview_render_settings(doc):
    """Una COPIA de los ajustes de render del artista, recortada a lo que
    esta herramienta necesita: un fotograma, en memoria, sin escribir nada
    por su cuenta.

    Renderizar con el contenedor VIVO (``GetDataInstance()`` a secas) es un
    riesgo de producción, no una cuestión de estilo: ese contenedor lleva los
    ``RDATA_SAVEIMAGE``/``RDATA_MULTIPASS_SAVEIMAGE`` y el rango de
    fotogramas del shot, así que en una escena configurada para entregar a
    disco el recorrido escribiría N veces sobre las rutas de entrega REALES
    —pisando beauties y AOVs— y, con el preset en rango de animación, cada
    opción arrancaría una secuencia entera en vez de un fotograma.

    El idiom es el oficial de Maxon (``GetClone(COPYFLAGS_NONE)`` sobre el
    contenedor del render data, ver los ejemplos ``render_document_*`` del
    SDK): la única imagen que se escribe es la que escribe ``Save`` aquí, con
    el nombre de la opción."""
    settings = doc.GetActiveRenderData().GetDataInstance().GetClone(
        c4d.COPYFLAGS_NONE)
    settings[c4d.RDATA_SAVEIMAGE] = False
    settings[c4d.RDATA_MULTIPASS_SAVEIMAGE] = False
    settings[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
    return settings


def _render_to_file(doc, path):
    """Renderiza el documento TAL COMO ESTÁ y escribe la imagen. Devuelve ""
    si salió bien, o el motivo del fallo.

    Los dos pasos se reportan por separado (``render_failed`` /
    ``save_failed``) porque son problemas distintos del artista: uno es la
    escena o el motor, el otro es la carpeta o el disco."""
    try:
        settings = _preview_render_settings(doc)
        width = int(settings[c4d.RDATA_XRES])
        height = int(settings[c4d.RDATA_YRES])
        bitmap = c4d.bitmaps.BaseBitmap()
        bitmap.Init(width, height, 24)
        result = c4d.documents.RenderDocument(
            doc, settings, bitmap, c4d.RENDERFLAGS_EXTERNAL)
    except Exception:
        return "render_failed"
    if result != c4d.RENDERRESULT_OK:
        return "render_failed"
    try:
        if not bitmap.Save(path, c4d.FILTER_PNG, None, c4d.SAVEBIT_0):
            return "save_failed"
    except Exception:
        return "save_failed"
    return ""


def _render_set_name(tag, anchor):
    """Con qué nombre entra el CONJUNTO en el de sus imágenes.

    El del tag, salvo que sea exactamente el de fábrica: ``create_variant_set``
    no nombra el tag, así que **todo conjunto nace llamándose
    ``VARIANT_TAG_DEFAULT_NAME``** y con sus opciones llamadas "Opción A/B/C".
    Dos conjuntos sin renombrar en la misma escena (el sofá y la lámpara, el
    caso de uso del spec) daban EXACTAMENTE los mismos nombres de archivo: el
    segundo recorrido pisaba las imágenes del primero y los dos partes decían
    "3 opciones renderizadas".

    El anclaje es lo que distingue a esos dos conjuntos sin pedirle nada al
    artista: es el objeto que él sí nombró."""
    name = _safe_node_name(tag, "")
    if name and name != VARIANT_TAG_DEFAULT_NAME:
        return name
    return _safe_node_name(anchor, "")


def render_all_options(tag):
    """Una imagen por opción, sin que el artista monte ninguna a mano.

    Contrato, y cada punto está por una razón:

    - La opción que estaba puesta **queda puesta al terminar**, pase lo que
      pase (``try/finally``). Una herramienta de enseñar opciones que deja la
      escena en la última no es aceptable.
    - Las opciones se recorren en el orden de la LISTA, no en el de aparcado.
    - Los cambios del recorrido **no son gestos del artista**: van todos en
      UN bracket de deshacer, y al terminar la escena está como estaba (por
      la restauración de arriba), así que no hay nada que deshacer.
    - Un fallo de una opción **no aborta** el resto (patrón del lote de
      matwire): se anota en ``failed`` y el recorrido sigue.
    - Las imágenes van en la subcarpeta ``_VARIANTS_SUBFOLDER`` de la carpeta
      de salida del render, nunca en ella directamente: esa carpeta es la que
      el artista entrega al cliente, y las opciones son material de
      decisión, no de entrega (verificado en vivo — sin esto, los PNG de las
      opciones aparecían sueltos junto a los beauties de la entrega).
      ``folder`` en el resultado nombra siempre esa subcarpeta, tanto si se
      escribió en ella como si no se pudo ni crear.
    - Todo lo que el recorrido hace y no se ve **se cuenta**: lo que sacó del
      anclaje (``evacuated``, igual que los otros cuatro gestos que lo
      vacían) y el caso en que la opción de partida NO pudo volver a montarse
      (``restore_failed``). La restricción "pase lo que pase" no se puede
      cumplir cuando no hay nada que remontar —una opción de partida
      huérfana, p.ej.—, pero sí se puede DECIR, que es lo que faltaba.

    Devuelve ``{"ok", "reason", "rendered", "failed", "folder", "evacuated",
    "restore_failed"}``, con ``failed`` como lista de ``(nombre, motivo)``."""
    fail = {"ok": False, "rendered": 0, "failed": [], "folder": "",
            "evacuated": [], "restore_failed": ""}
    state = read_state(tag)
    options = state["options"]
    if not options:
        return dict(fail, reason="no_options")
    anchor, doc, payload, reason = _tag_context(tag)
    if reason:
        return dict(fail, reason=reason)

    folder = _render_output_folder(doc)
    if not folder:
        # Sin carpeta no hay dónde escribir: se dice y no se toca NADA — ni
        # un bracket, ni un cambio de opción. Renderizar a ninguna parte y
        # devolver "ok" sería el no-op silencioso de manual.
        return dict(fail, reason="unsaved_scene")
    # Subcarpeta propia, nunca la carpeta de salida del render a secas: esa
    # es la que el artista entrega al cliente (ver ``_VARIANTS_SUBFOLDER``).
    folder = os.path.join(folder, _VARIANTS_SUBFOLDER)
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        # Motivo PROPIO, no ``unsaved_scene``: el fallo de aquí es un share
        # desmontado o de sólo lectura, y decirle al artista "guarda la
        # escena primero" cuando la escena SÍ está guardada le manda a
        # guardarla otra vez y a leer lo mismo. El módulo ya separa
        # ``render_failed`` de ``save_failed`` por esta misma razón. El
        # ``folder`` que se reporta aquí es la subcarpeta que no se pudo
        # crear — ninguna imagen llegó a escribirse en ningún sitio, así que
        # no hay "carpeta donde acabaron" que preferir sobre esta.
        return dict(fail, reason="folder_failed", folder=folder)

    stem_scene = _scene_stem(doc)
    set_name = _render_set_name(tag, anchor)
    original = state["active"]

    rendered = 0
    failed = []
    evacuated = []
    #: Un destino por opción. Sin esto ``rendered`` cuenta RENDERS, no
    #: archivos: dos opciones cuyos nombres colapsan al mismo stem
    #: (``render_image_stem`` mapea ``/ \\ : * ? " < > |`` a "_", así que
    #: ``hero/v1`` y ``hero_v1`` colisionan) daban "3 opciones renderizadas"
    #: con 2 archivos en disco. Una opción sin destino propio no se da por
    #: entregada: se dice.
    taken = set()
    doc.StartUndo()
    try:
        for index, option in enumerate(options):
            name = option.get("name") or ""
            if not option.get("resolved"):
                failed.append((name, "lost_option"))
                continue
            switch_reason, work = _switch_work(tag, index)
            if switch_reason and switch_reason != "already_active":
                # ``already_active`` no es un fallo: es la opción que ya está
                # montada, que es exactamente la que toca renderizar ahora.
                failed.append((name, "switch_failed"))
                continue
            if work is not None:
                _apply_switch(tag, work)
                evacuated.extend(work["strays"])
            stem = variants.render_image_stem(stem_scene, set_name, name)
            if stem in taken:
                failed.append((name, "name_clash"))
                continue
            taken.add(stem)
            problem = _render_to_file(
                doc, os.path.join(folder, stem + _RENDER_EXTENSION))
            if problem:
                failed.append((name, problem))
            else:
                rendered += 1
    finally:
        # La opción original vuelve a su sitio pase lo que pase, dentro del
        # MISMO bracket: si esto quedara fuera, un fallo a mitad dejaría al
        # artista mirando una opción que él no puso.
        restore_failed = ""
        if original is not None:
            restore_reason, restore_work = _switch_work(tag, original)
            if restore_reason and restore_reason != "already_active":
                # No se pudo remontar: la escena se queda en OTRA opción. Es
                # best-effort por fuerza (con la opción de partida huérfana no
                # hay nada que remontar), pero callarlo deja al artista con
                # una escena cambiada y un parte que no lo menciona.
                restore_failed = restore_reason
            elif restore_work is not None:
                _apply_switch(tag, restore_work)
                evacuated.extend(restore_work["strays"])
        doc.EndUndo()

    _event_add()
    return {
        "ok": rendered > 0,
        "reason": "" if rendered else "all_failed",
        "rendered": rendered,
        "failed": failed,
        "folder": folder,
        "evacuated": evacuated,
        "restore_failed": restore_failed,
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
            base = ID_OPTION_BASE + index * ID_OPTION_STRIDE
            # Los tres controles de una opción, EN UNA LÍNEA: montar (la
            # etiqueta dice cuál está puesta), el nombre editable y borrar.
            # El sub-grupo es lo que reparte el ancho dentro de la fila; el
            # grupo de opciones sigue a una columna, así que nada de esto
            # compite con el texto de estado (que cuelga de la raíz).
            row_group = _description_parent(
                base + _OPTION_ACTION_GROUP, c4d.DTYPE_GROUP, node)
            if not self._set_description_group(
                node, description, base + _OPTION_ACTION_GROUP, "",
                options_group, columns=3, titlebar=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, base + _OPTION_ACTION_MOUNT,
                c4d.DTYPE_BUTTON, _option_row_label(option, index == state["active"]),
                row_group, animatable=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, base + _OPTION_ACTION_NAME,
                c4d.DTYPE_STRING, "", row_group, animatable=False
            ):
                return False
            if not self._set_description_parameter(
                node, description, base + _OPTION_ACTION_DELETE,
                c4d.DTYPE_BUTTON, "Borrar", row_group, animatable=False
            ):
                return False

        # Duplicar la opción MONTADA: un solo botón para todo el conjunto, no
        # uno por fila — se duplica lo que el artista está mirando.
        if not self._set_description_parameter(
            node, description, ID_VARIANTS_NEW, c4d.DTYPE_BUTTON,
            "Duplicar opción activa", root, animatable=False
        ):
            return False

        # Una imagen por opción, sin montar ninguna a mano. Va DESPUÉS de
        # duplicar y antes del resumen: es la única acción del conjunto que
        # no cambia la escena (al terminar queda como estaba), así que no
        # compite por atención con las que sí.
        if not self._set_description_parameter(
            node, description, ID_VARIANTS_RENDER_ALL, c4d.DTYPE_BUTTON,
            "Renderizar todas las opciones", root, animatable=False
        ):
            return False

        # Lo que ese recorrido deja detrás, dicho antes de pulsarlo: un
        # bloque de deshacer y la escena como estaba. Pegado a su botón
        # porque habla de la acción, no del conjunto.
        if not self._set_description_parameter(
            node, description, ID_VARIANTS_RENDER_HINT, c4d.DTYPE_STATICTEXT,
            "", root, animatable=False
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
        if parameter_id == ID_VARIANTS_RENDER_HINT:
            return (True, variants.render_hint_text(read_state(node)),
                    flags | c4d.DESCFLAGS_GET_PARAM_GET)
        row = _option_command(parameter_id, _payload_option_count(node))
        if row is not None and row[1] == _OPTION_ACTION_NAME:
            # El nombre de la OPCIÓN, dato propio del conjunto (el del tag es
            # el nombre del conjunto y no se toca aquí).
            state = read_state(node)
            if 0 <= row[0] < len(state["options"]):
                return (True, state["options"][row[0]]["name"],
                        flags | c4d.DESCFLAGS_GET_PARAM_GET)
        return False

    def SetDParameter(self, node, id, data, flags):
        parameter_id = _desc_level_id(id)
        if parameter_id in (ID_VARIANTS_STATUS, ID_VARIANTS_WARNING,
                            ID_VARIANTS_RENDER_HINT):
            # Strings derivados de sólo lectura: se traga la escritura.
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        row = _option_command(parameter_id, _payload_option_count(node))
        if row is not None and row[1] == _OPTION_ACTION_NAME:
            text = str(data) if data is not None else ""
            result = rename_option(node, row[0], text)
            # ``unchanged`` (el Attribute Manager reescribiendo lo que acaba
            # de leer) no dice nada — ver variants.action_report_text.
            _report(variants.action_report_text(result))
            return True, flags | c4d.DESCFLAGS_SET_PARAM_SET
        return False

    def GetDEnabling(self, node, cid, t_data, flags, itemdesc):
        parameter_id = _desc_level_id(cid)
        count = _payload_option_count(node)
        if parameter_id == ID_VARIANTS_NEW:
            # Sin opción montada (o con su enlace perdido) no hay nada que
            # copiar: el botón lo dice apagándose.
            state = read_state(node)
            active = state["active"]
            if active is None:
                return False
            return bool(state["options"][active]["resolved"])
        row = _option_command(parameter_id, count)
        if row is not None and row[1] == _OPTION_ACTION_MOUNT:
            state = read_state(node)
            index = row[0]
            if not (0 <= index < len(state["options"])):
                return False
            # La opción montada no se puede volver a montar, y una cuyo
            # enlace se perdió tampoco: el botón dice la verdad en vez de
            # aceptar el clic y no hacer nada.
            option = state["options"][index]
            return bool(option["resolved"]) and index != state["active"]
        if row is not None and row[1] == _OPTION_ACTION_DELETE:
            # ``plan_delete`` rechaza borrar la última opción del conjunto —
            # misma política que arriba: el botón se apaga en vez de aceptar
            # el clic y no hacer nada.
            return count > 1
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
        if command_id == ID_VARIANTS_NEW:
            _report(variants.action_report_text(duplicate_active_option(node)))
            return True
        if command_id == ID_VARIANTS_RENDER_ALL:
            _report(variants.render_report_text(render_all_options(node)))
            return True
        row = _option_command(command_id, _payload_option_count(node))
        if row is not None and row[1] == _OPTION_ACTION_MOUNT:
            _report(variants.switch_report_text(switch_to_option(node, row[0])))
        elif row is not None and row[1] == _OPTION_ACTION_DELETE:
            _report(variants.action_report_text(delete_option(node, row[0])))
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
