"""Contrato del adaptador de Sentinel Variants (``sentinel/ui/variant_tag.py``)
contra el arnés falso — el contrato DEL MÓDULO, no el comportamiento de C4D.

LO QUE ESTE ARNÉS NO PUEDE PROBAR, dicho aquí para que nadie lea verde donde
no lo hay (los fakes de este repo han dado verde sobre código roto siete
veces esta semana):

- **Que el movimiento real conserve la jerarquía y la transformación en el
  mundo.** ``FakeObject.Remove``/``InsertUnder`` mueven punteros en listas de
  Python; no hay matrices ni evaluación de escena. Que reparentar a un null
  en identidad conserve ``GetMg()`` es un hecho MEDIDO en vivo (spike §3),
  no algo que estos tests observen.
- **Que el undo del menú revierta en un paso.** Aquí sólo se cuenta que se
  abra exactamente un bracket ``StartUndo``/``EndUndo``, que el ``AddUndo``
  de **cada uno** de los objetos movidos se registre ANTES de moverlo (en LOS
  TRES caminos que mueven: crear el conjunto, cambiar de opción, y vaciar el
  anclaje al duplicar o al borrar la opción montada —``_evacuate_anchor``—, y
  en los tres con **más de un** objeto en movimiento — con uno solo, un
  ``AddUndo`` fijado fuera del bucle pasa por bueno, que es el modo de fallo
  exacto que costó un bug real en matwire v1.32), y que cada objeto creado y
  el payload lleven el suyo. Si C4D realmente colapsa eso en un paso es cosa de C4D y se verifica
  en vivo (Step 8 del brief).
- **Que los ``BaseLink`` sobrevivan a guardar+cargar.** El fake guarda el
  objeto tal cual (ver ``BaseContainer.SetLink`` en conftest). Un enlace
  "perdido" se modela poniendo ``None``: eso prueba cómo REACCIONA el
  código a un enlace que no resuelve, nunca cuándo un enlace real deja de
  resolver.
- **Que ``MakeTag`` ponga de verdad el tag, y que dos conjuntos puedan
  convivir sobre el mismo objeto.** ``FakeObject.MakeTag`` fabrica un
  ``FakeTag`` y lo mete en una lista; el ``TAG_MULTIPLE`` del registro (sin
  él C4D EXPULSA el segundo tag del mismo tipo — medido en vivo en la v1.35)
  vive en ``sentinel_panel.pyp`` y no lo ejercita nada de aquí.
- **Que los ids de visibilidad sean los de C4D.**
  ``_PermissiveModule.__getattr__`` (``tests/conftest.py:25``) auto-vivifica
  ``ID_BASEOBJECT_VISIBILITY_EDITOR``/``_RENDER`` como enteros inventados, así
  que la aserción del contenedor de aparcado prueba que se escribió *algo* en
  dos claves y ``OBJECT_OFF`` en ellas — nunca que sean los parámetros que
  apagan la visibilidad en C4D.
- **Que C4D entregue los mensajes y las consultas de la descripción, y que
  pinte lo que se le pide.** Que ``MSG_DESCRIPTION_COMMAND`` llegue con el id
  de la fila pulsada, que el Attribute Manager llame a ``GetDEnabling`` por
  cada control, o que una fila declarada salga dibujada, es contrato de C4D.
  Lo que sí se prueba aquí es qué hace este módulo CON ese mensaje y con esa
  consulta, y QUÉ pide pintar — llamando a
  ``Message``/``_handle_command``/``GetDEnabling``/``GetDDescription``/
  ``GetDParameter``/``Execute`` directamente contra un ``FakeDescription``
  que anota lo pedido. No es un límite del arnés, son funciones llamables:
  toda esta capa estuvo sin ejecutar bajo test y cinco mutaciones que dejaban
  la feature sin UI sobrevivían la suite entera.

OCTAVA RECURRENCIA (Tarea 3, cazada en vivo, no por esta suite): ``FakeObject``
tiene identidad Python ESTABLE — ``GetUp()``/``GetDown()``/``GetNext()``/
``doc.GetFirstObject()`` devuelven siempre el MISMO objeto para el mismo
nodo, porque son punteros directos. C4D real no: cada lectura del mismo
nodo entrega un envoltorio Python NUEVO (``id()`` distinto, medido en vivo),
con ``hash()``/``==`` estables entre lecturas. El código de producción
comparaba con ``id(obj)``/``is`` — que bajo el arnés normal SIEMPRE
"funciona" (nunca hay dos lecturas distintas del mismo nodo que comparar),
así que la suite daba verde con el bug ya en el código. ``_Reread`` (más
abajo) tapa esa brecha, opt-in, sólo donde un test lo usa explícitamente —
sigue sin modelar que TODAS las lecturas de C4D sean así siempre; sólo
permite construir el escenario puntual de "dos caminos de lectura del mismo
nodo" que expone el bug.
"""

import importlib
import os

import pytest


# --- Arnés de escena --------------------------------------------------------

class FakeDoc:
    def __init__(self):
        self.start_undo_count = 0
        self.end_undo_count = 0
        self.undo_ops = []
        self.root = []
        # Registro ORDENADO de todo lo que pasa (undo + movimientos), para
        # poder afirmar que el AddUndo de un objeto precede a su Remove —
        # el orden ES la propiedad que el spike midió.
        self.events = []
        # Identidad en disco. Vacías por defecto = documento SIN GUARDAR,
        # que es el caso que ``render_all_options`` tiene que rechazar.
        self.doc_path = ""
        self.doc_name = ""
        self.render_data = None

    def GetDocumentPath(self):
        return self.doc_path

    def GetDocumentName(self):
        return self.doc_name

    def GetActiveRenderData(self):
        return self.render_data

    def StartUndo(self):
        self.start_undo_count += 1

    def EndUndo(self):
        self.end_undo_count += 1

    def AddUndo(self, undo_type, target):
        self.undo_ops.append((undo_type, target))
        self.events.append(("undo", undo_type, target))

    def GetFirstObject(self):
        # El punto de entrada del recorrido del Object Manager, que es como
        # ``_in_scene_order`` ordena la selección.
        return self.root[0] if self.root else None

    def InsertObject(self, op, parent=None, pred=None):
        siblings = self.root if parent is None else parent._children
        index = 0 if pred is None else siblings.index(pred) + 1
        siblings.insert(index, op)
        op._parent = parent
        op._doc = self
        self.events.append(("insert", op, parent))


class FakeTag:
    def __init__(self, host, plugin_id, name, c4d, doc):
        self._host = host
        self._type = plugin_id
        self._name = name
        self._bc = c4d.BaseContainer()
        self._doc = doc

    def GetObject(self):
        return self._host

    def GetType(self):
        return self._type

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetDataInstance(self):
        return self._bc

    def GetDocument(self):
        return self._doc


class FakeObject:
    def __init__(self, name, c4d, doc=None, children=None):
        self._name = name
        self._c4d = c4d
        self._doc = doc
        self._parent = None
        self._children = []
        self._tags = []
        self._params = {}
        for child in list(children or []):
            self._children.append(child)
            child._parent = self

    # -- identidad / nombre
    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetDocument(self):
        return self._doc

    def GetDataInstance(self):
        return None

    # -- jerarquía
    def GetUp(self):
        return self._parent

    def GetDown(self):
        return self._children[0] if self._children else None

    def _siblings(self):
        if self._parent is not None:
            return self._parent._children
        if self._doc is not None:
            return self._doc.root
        return [self]

    def GetNext(self):
        siblings = self._siblings()
        if self not in siblings:
            return None
        index = siblings.index(self)
        return siblings[index + 1] if index + 1 < len(siblings) else None

    def GetPred(self):
        siblings = self._siblings()
        if self not in siblings:
            return None
        index = siblings.index(self)
        return siblings[index - 1] if index > 0 else None

    def Remove(self):
        siblings = self._siblings()
        if self in siblings:
            siblings.remove(self)
        self._parent = None
        if self._doc is not None:
            self._doc.events.append(("remove", self))

    def InsertUnder(self, parent):
        # C4D inserta como PRIMER hijo (medido en la v1.30 para InsertObject
        # y el mismo contrato aquí) — que es justo por qué el writer recorre
        # la selección al revés.
        parent._children.insert(0, self)
        self._parent = parent
        self._doc = parent._doc
        if self._doc is not None:
            self._doc.events.append(("insert_under", self, parent))

    # -- copia
    def GetClone(self, flags=0):
        """Copia PROFUNDA del subárbol — aditivo al arnés, porque sin él la
        rama de duplicar no se puede ejercitar bajo test EN ABSOLUTO
        (``c4d.BaseObject`` ya está parcheado por el fixture; ``GetClone`` no
        existía en ningún sitio).

        Lo que NO modela, y por eso el límite nº2 del spec se verifica en
        vivo y no aquí: que los tags de material del clon apunten a los
        MISMOS materiales que el original (la razón por la que el Material
        Manager no engorda al duplicar). En este arnés no hay materiales que
        compartir, así que ese hecho no lo prueba ningún test de este
        fichero."""
        clone = FakeObject(self._name, self._c4d, None)
        clone._params = dict(self._params)
        for child in self._children:
            child_clone = child.GetClone(flags)
            child_clone._parent = clone
            clone._children.append(child_clone)
        return clone

    # -- tags
    def GetTags(self):
        return list(self._tags)

    def MakeTag(self, plugin_id):
        tag = FakeTag(self, plugin_id, "Sentinel Variants", self._c4d, self._doc)
        self._tags.insert(0, tag)
        return tag

    # -- parámetros nativos (visibilidad)
    def __setitem__(self, key, value):
        self._params[key] = value

    def __getitem__(self, key):
        return self._params.get(key)


class _Reread:
    """Una lectura NUEVA del mismo nodo — aditivo, sólo para los tests que
    ejercitan el bug de identidad cazado en vivo en la Tarea 3 (ver
    ``docs/superpowers/sdd/task-3-report.md``).

    ``FakeObject`` normal tiene identidad Python ESTABLE: ``GetUp()``/
    ``GetDown()``/``GetNext()``/``doc.GetFirstObject()`` siempre devuelven el
    MISMO objeto Python para el mismo nodo, porque son punteros directos a
    ``_parent``/``_children``. C4D real no hace eso — medido en vivo: dos
    llamadas a ``d.GetFirstObject()`` sobre el MISMO documento devuelven dos
    envoltorios con ``id()`` distinto del MISMO nodo, con ``hash()`` y
    ``==`` estables entre ellos. Esa es la brecha exacta que ``FakeObject``
    solo (identidad Python estable) no puede abrir: bajo el arnés normal,
    comparar por ``id()`` en vez de por valor siempre "funciona", porque
    nunca hay dos lecturas distintas del mismo nodo que comparar.

    ``_Reread(node)`` envuelve un ``FakeObject`` YA existente y delega TODO
    en él vía ``__getattr__``/``__getitem__``/``__setitem__`` — mismo nodo,
    mismos hijos, mismo padre — salvo identidad: ``id(_Reread(node)) !=
    id(node)`` siempre (dos objetos Python distintos), pero
    ``_Reread(node) == node`` y ``hash(_Reread(node)) == hash(node)`` (calca
    lo medido: hash/== estables, ``is`` no). Se usa envolviendo SÓLO uno de
    los dos "caminos de lectura" que un test quiere hacer divergir (p.ej. la
    selección que entra en una función vs. lo que la jerarquía entrega al
    subir por ``GetUp()``), dejando el otro camino con el ``FakeObject`` raw
    — igual que en C4D real, donde nunca hay ninguna garantía de qué camino
    entrega qué envoltorio, sólo la garantía de que sean iguales POR VALOR."""

    def __init__(self, node):
        self._node = node

    def __getattr__(self, name):
        return getattr(self._node, name)

    def __getitem__(self, key):
        return self._node[key]

    def __setitem__(self, key, value):
        self._node[key] = value

    def __eq__(self, other):
        return self._node is getattr(other, "_node", other)

    def __hash__(self):
        return hash(self._node)

    def __repr__(self):
        return "_Reread(%r)" % (self._node,)


class FakeDescription:
    """Anota lo que la descripción del tag PIDE pintar, igual que
    ``FakeDoc.undo_ops`` anota los undos.

    Lo que NO modela: que C4D acepte esos ids o esos dtypes, el dibujo real,
    el ancho de nada, ni ``LoadDescription`` (que aquí sólo se apunta). Lo
    que sí fija: qué filas se declaran, con qué etiqueta, de qué tipo y
    colgando de qué grupo — que es lo único de esta capa decidible sin C4D.
    """

    def __init__(self, reject=()):
        self.loaded = []
        self.rows = []          # (param_id, dtype, name, parent_id, bc)
        self.reject = set(reject)  # ids cuyo SetParameter falla

    def LoadDescription(self, type_id):
        self.loaded.append(type_id)
        return True

    def SetParameter(self, desc_id, bc, parent):
        import c4d

        param_id = desc_id[0].id
        if param_id in self.reject:
            return False
        self.rows.append((
            param_id,
            desc_id[0].dtype,
            bc.GetString(c4d.DESC_NAME, ""),
            parent[0].id,
            bc,
        ))
        return True

    def names_under(self, parent_id):
        return [row[2] for row in self.rows if row[3] == parent_id]

    def row_ids_under(self, parent_id):
        return [row[0] for row in self.rows if row[3] == parent_id]

    def name_of(self, param_id):
        for row in self.rows:
            if row[0] == param_id:
                return row[2]
        return None

    def bc_of(self, param_id):
        """El ``BaseContainer`` que se le pasó a ``SetParameter`` para esta
        fila — lo que ANTES este fake descartaba. Sin él, un test sólo podía
        afirmar el ``dtype`` de una fila, nunca las claves (``DESC_CUSTOMGUI``,
        ``DESC_ANIMATE``, ``DESC_COLUMNS``...) que C4D exige además del
        dtype para que la fila se pinte/comporte como el código dice que
        debe."""
        for row in self.rows:
            if row[0] == param_id:
                return row[4]
        return None


@pytest.fixture
def variant_tag(sentinel_module, monkeypatch):
    module = importlib.import_module("sentinel.ui.variant_tag")
    import c4d

    # c4d.BaseObject no existe en el fake (el módulo permisivo devolvería un
    # int, que no es llamable como constructor). Se parchea sólo durante el
    # test, con la forma real: un objeto NUEVO, sin padre, sin hijos.
    def _make(type_id):
        return FakeObject("Null", c4d, None)

    monkeypatch.setattr(c4d, "BaseObject", _make, raising=False)
    return module


def _scene(c4d):
    doc = FakeDoc()
    return doc


def _insert(doc, obj, parent=None):
    """Inserta AL FINAL de sus hermanos, para que la escena se construya en
    el mismo orden en que se lee. ``InsertObject`` con ``pred=None`` inserta
    como PRIMER hijo (contrato real de C4D, modelado en ``FakeDoc``), así
    que hay que pasarle el último hermano como predecesor."""
    siblings = doc.root if parent is None else parent._children
    doc.InsertObject(obj, parent, siblings[-1] if siblings else None)
    return obj


def _add_second_option(variant_tag, tag, c4d, doc, name, node):
    """Añade una segunda opción APARCADA al payload a mano (duplicar es la
    Tarea 4; aquí sólo hace falta el estado del que parte un cambio)."""
    payload = variant_tag._read_payload_bc(tag)
    options = payload.GetContainerInstance(variant_tag._PAYLOAD_OPTIONS)
    option = c4d.BaseContainer()
    option.SetString(variant_tag._OPTION_NAME, name)
    option.SetLink(variant_tag._OPTION_LINK, node)
    options.SetContainer(1, option)
    payload.SetInt32(variant_tag._PAYLOAD_COUNT, 2)
    return payload


def _first_touch(doc, node, since=0):
    """El PRIMER evento que toca ``node`` a partir de ``since``: ``("undo",
    tipo)`` o ``("remove",)``. El orden entre esos dos ES la propiedad que el
    spike midió; ``since`` deja mirar sólo un gesto (los objetos creados ya
    llevan su ``AddUndo`` de creación mucho antes)."""
    for event in doc.events[since:]:
        if event[0] == "undo" and event[2] is node:
            return ("undo", event[1])
        if event[0] == "remove" and event[1] is node:
            return ("remove",)
    return None


# --- 1. Selección vacía -----------------------------------------------------

def test_create_variant_set_rejects_an_empty_selection_without_a_bracket(variant_tag):
    import c4d

    doc = _scene(c4d)

    result = variant_tag.create_variant_set(doc, [])

    assert result["ok"] is False
    assert result["reason"] == "no_selection"
    assert result["tag"] is None
    # Un paso de deshacer que no deshace nada es peor que ninguno: el
    # siguiente Cmd+Z del artista se lo gasta sin que la escena cambie.
    assert (doc.start_undo_count, doc.end_undo_count) == (0, 0)
    assert doc.root == []


# --- 2. Padre + hijo seleccionados a la vez ---------------------------------

def test_create_variant_set_wraps_a_selected_parent_and_child_only_once(variant_tag):
    import c4d

    doc = _scene(c4d)
    child = FakeObject("hijo", c4d, doc)
    parent = FakeObject("padre", c4d, doc, children=[child])
    _insert(doc, parent)

    # El HIJO va primero en la selección a propósito: un barrido hacia
    # delante de "ya vistos" no lo descartaría (lección de v1.30).
    result = variant_tag.create_variant_set(doc, [child, parent])

    assert result["ok"] is True
    anchor = doc.root[0]
    option = anchor._children[0]
    assert [obj.GetName() for obj in option._children] == ["padre"], (
        "el hijo entra dentro de su padre, no como segunda raíz de la opción"
    )
    assert child._parent is parent, "el hijo no puede acabar en dos sitios"
    assert doc.root == [anchor], "el padre ya no cuelga de la raíz"


def test_create_variant_set_takes_the_place_of_the_first_selected_object(variant_tag):
    import c4d

    doc = _scene(c4d)
    before = _insert(doc, FakeObject("antes", c4d, doc))
    target = _insert(doc, FakeObject("objetivo", c4d, doc))
    _insert(doc, FakeObject("despues", c4d, doc))

    result = variant_tag.create_variant_set(doc, [target])

    assert result["ok"] is True
    names = [obj.GetName() for obj in doc.root]
    assert names[0] == "antes"
    assert names[1].startswith("Opciones"), (
        "el anclaje ocupa el sitio del objeto envuelto, no el final del OM"
    )
    assert names[2] == "despues"
    assert before is doc.root[0]


def test_create_variant_set_preserves_sibling_order_inside_the_option(variant_tag):
    import c4d

    doc = _scene(c4d)
    a = _insert(doc, FakeObject("luz_a", c4d, doc))
    b = _insert(doc, FakeObject("luz_b", c4d, doc))
    c = _insert(doc, FakeObject("luz_c", c4d, doc))

    variant_tag.create_variant_set(doc, [a, b, c])

    option = doc.root[0]._children[0]
    assert [obj.GetName() for obj in option._children] == ["luz_a", "luz_b", "luz_c"]


def test_create_variant_set_registers_the_move_undo_before_moving(variant_tag):
    """El ``AddUndo(UNDOTYPE_CHANGE, obj)`` va ANTES del ``Remove()`` — es
    literalmente lo que el spike midió (sin él, el undo no revierte nada) y
    lo único de la cadena de undo que este arnés sí puede fijar."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))

    variant_tag.create_variant_set(doc, [obj])

    order = [e for e in doc.events
             if (e[0] == "undo" and e[2] is obj) or (e[0] == "remove" and e[1] is obj)]
    assert order[0][0] == "undo" and order[0][1] == c4d.UNDOTYPE_CHANGE
    assert order[1][0] == "remove"
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)


# --- 3. Cambiar a la opción ya montada --------------------------------------

def test_switch_to_the_active_option_opens_no_bracket(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.switch_to_option(tag, 0)

    assert result["ok"] is False
    assert result["reason"] == "already_active"
    assert (doc.start_undo_count, doc.end_undo_count) == (0, 0)


# --- 4. Un cambio válido ----------------------------------------------------

def test_switch_to_option_parks_and_mounts_in_exactly_one_bracket(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]

    option_b = FakeObject("Opción B", c4d, doc)
    _insert(doc, option_b)
    _insert(doc, FakeObject("cubo_b", c4d, doc), option_b)
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.switch_to_option(tag, 1)

    assert result["ok"] is True
    assert result["name"] == "Opción B"
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1), (
        "aparcar y montar son medio gesto cada una: un solo bracket"
    )
    assert anchor._children == [option_b], "el anclaje tiene exactamente un hijo"
    park = option_a._parent
    assert park is not None and park.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME
    assert park in doc.root, "el contenedor de aparcado vive en la raíz"
    assert park[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] == c4d.OBJECT_OFF
    assert park[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] == c4d.OBJECT_OFF

    payload = variant_tag._read_payload_bc(tag)
    assert payload.GetInt32(variant_tag._PAYLOAD_ACTIVE, -1) == 1
    state = variant_tag.read_state(tag)
    assert state["active"] == 1
    assert state["parked_objects"] == 1, "el cubo de A sigue en la escena, y se dice"


def test_switch_reuses_the_same_park_container_on_the_way_back(variant_tag):
    """El contenedor se reencuentra por el ``BaseLink`` del payload — nunca
    por nombre. Una ida y vuelta no puede dejar dos cajones."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    variant_tag.switch_to_option(tag, 1)
    park_first = option_a._parent
    park_first.SetName("mi cajón renombrado")
    variant_tag.switch_to_option(tag, 0)

    assert option_b._parent is park_first, (
        "renombrar el contenedor no puede hacer que se cree otro"
    )
    assert anchor._children == [option_a]
    containers = [o for o in doc.root if o is park_first]
    assert len(containers) == 1


# --- 5. La opción a montar se perdió ----------------------------------------

def test_switch_to_a_lost_option_touches_nothing(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    # Enlace que no resuelve — lo que devuelve un BaseLink cuyo objetivo ya
    # no está.
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", None)

    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.switch_to_option(tag, 1)

    assert result["ok"] is False
    assert result["reason"] == "lost_option"
    assert (doc.start_undo_count, doc.end_undo_count) == (0, 0)
    # Mejor un conjunto que no cambia y lo dice, que un anclaje vacío.
    assert anchor._children == [option_a]
    assert option_a._parent is anchor
    payload = variant_tag._read_payload_bc(tag)
    assert payload.GetInt32(variant_tag._PAYLOAD_ACTIVE, -1) == 0


# --- 6. read_state con un enlace roto ---------------------------------------

def test_read_state_reports_a_broken_link_as_an_orphan(variant_tag):
    import c4d
    from sentinel import variants

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", None)

    state = variant_tag.read_state(tag)

    assert state["orphans"] == 1
    assert state["options"][1]["resolved"] is False
    assert state["options"][1]["objects"] == 0
    assert state["options"][0]["resolved"] is True
    # Y los textos derivados no revientan sobre ese estado.
    assert variants.status_text(state) == "Opción A · 2 opciones · 1 objeto montado"
    assert variants.warning_text(state) == "⚠ 1 opción no encontrada"


# --- El nombre del conjunto sobrevive a cargar ------------------------------

def test_sync_display_name_restores_the_set_name_after_a_simulated_reload(variant_tag):
    """C4D repone el nombre de un tag de plugin desde su string de registro
    en cada carga (medido en la v1.35). El espejo del contenedor es lo único
    que puede devolverlo."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]

    tag.SetName("con y sin bend")
    variant_tag._sync_display_name(tag)  # el espejo sigue al nombre vivo

    tag.SetName(variant_tag.VARIANT_TAG_DEFAULT_NAME)  # lo que hace una carga
    variant_tag._sync_display_name(tag)

    assert tag.GetName() == "con y sin bend"


def test_sync_display_name_never_reverts_a_live_rename(variant_tag):
    """El bug medido en la v1.35: confiar en el espejo cuando discrepa
    revierte un renombrado real un tick después (Execute tickea sin parar)."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]

    # Dos renombrados: el primero deja el espejo con un valor NO vacío y
    # distinto del segundo — que es exactamente el estado en el que una
    # política de "manda el espejo" revierte lo que el artista acaba de
    # escribir. Con un solo renombrado el espejo empieza vacío y esa
    # política sobreviviría al test sin que nadie se enterara.
    tag.SetName("primer nombre")
    variant_tag._sync_display_name(tag)

    tag.SetName("con y sin bend")
    for _ in range(5):
        variant_tag._sync_display_name(tag)
        assert tag.GetName() == "con y sin bend"


# --- La cadena de undo, en TODOS los caminos que mueven ----------------------

def test_switch_registers_each_move_undo_before_moving(variant_tag):
    """El mismo hecho medido que fija ``create_variant_set``, en el camino que
    de verdad usa ``_reparent``: cambiar de opción. Sin el ``AddUndo`` delante
    del ``Remove()``, C4D no revierte el reparentado y el artista se queda con
    B montada y el payload diciendo A."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    mark = len(doc.events)
    assert variant_tag.switch_to_option(tag, 1)["ok"] is True

    # La que se aparca y la que se monta: las DOS se mueven, las dos necesitan
    # su undo por delante.
    assert _first_touch(doc, option_a, mark) == ("undo", c4d.UNDOTYPE_CHANGE)
    assert _first_touch(doc, option_b, mark) == ("undo", c4d.UNDOTYPE_CHANGE)


def test_switch_registers_the_payload_undo_on_the_tag(variant_tag):
    """Sin el ``AddUndo`` sobre el tag, un Cmd+Z devuelve la escena pero deja
    el payload diciendo que está montada otra: con tres opciones, el siguiente
    cambio deja el anclaje con DOS hijos."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    doc.undo_ops = []
    variant_tag.switch_to_option(tag, 1)

    assert (c4d.UNDOTYPE_CHANGE, tag) in doc.undo_ops


def test_create_variant_set_registers_new_object_undos_for_the_nulls_it_creates(variant_tag):
    """El anclaje y el null de la opción NACEN en este gesto: sin su
    ``UNDOTYPE_NEWOBJ``, un Cmd+Z deshace los movimientos y deja los dos nulls
    colgando — y con el anclaje se queda vivo su tag, apuntando a una opción
    que ya no contiene nada."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))

    tag = variant_tag.create_variant_set(doc, [obj])["tag"]

    anchor = tag.GetObject()
    option = anchor._children[0]
    assert (c4d.UNDOTYPE_NEWOBJ, anchor) in doc.undo_ops
    assert (c4d.UNDOTYPE_NEWOBJ, option) in doc.undo_ops


def test_switch_registers_a_new_object_undo_for_the_park_container(variant_tag):
    """El cajón se crea perezosamente en el primer cambio. Sin su
    ``UNDOTYPE_NEWOBJ``, un Cmd+Z tras ese cambio deja un null oculto
    permanente en la raíz de la escena."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    option_a = tag.GetObject()._children[0]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    doc.undo_ops = []
    variant_tag.switch_to_option(tag, 1)

    park = option_a._parent
    assert park.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME
    assert (c4d.UNDOTYPE_NEWOBJ, park) in doc.undo_ops


# --- El despacho de los botones de fila -------------------------------------

def _tag_data(variant_tag):
    return variant_tag.SentinelVariantsTag()


def _two_option_set(variant_tag, c4d):
    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)
    return doc, tag, option_b


def test_pressing_an_option_row_switches_to_that_option(variant_tag):
    """Si el despacho no casa, TODOS los botones de opción quedan inertes y
    la feature entera no hace nada al pulsarla."""
    import c4d

    doc, tag, option_b = _two_option_set(variant_tag, c4d)
    row_id = variant_tag.ID_OPTION_BASE + 1 * variant_tag.ID_OPTION_STRIDE

    _tag_data(variant_tag)._handle_command(tag, {"id": row_id})

    assert tag.GetObject()._children == [option_b]
    assert variant_tag.read_state(tag)["active"] == 1


def test_message_routes_a_description_command_to_the_row_dispatch(variant_tag):
    import c4d

    doc, tag, option_b = _two_option_set(variant_tag, c4d)
    row_id = variant_tag.ID_OPTION_BASE + 1 * variant_tag.ID_OPTION_STRIDE

    _tag_data(variant_tag).Message(tag, c4d.MSG_DESCRIPTION_COMMAND, {"id": row_id})

    assert variant_tag.read_state(tag)["active"] == 1


def test_a_row_id_beyond_the_painted_rows_is_not_ours(variant_tag):
    """Sin cota superior, cualquier id ≥ ID_OPTION_BASE múltiplo del stride se
    lee como fila: ``GetDEnabling`` apagaría un control ajeno y ``Message`` se
    tragaría su comando. Las Tareas 4 y 5 añaden ids."""
    import c4d

    doc, tag, option_b = _two_option_set(variant_tag, c4d)
    stranger = variant_tag.ID_OPTION_BASE + 180 * variant_tag.ID_OPTION_STRIDE

    assert variant_tag._option_command(stranger, 2) is None
    assert variant_tag._option_command(variant_tag.ID_OPTION_BASE, 2) == (0, 0)

    # Y el efecto que importa: el control ajeno no se apaga ni se traga su
    # comando (el conjunto sigue en A).
    tag_data = _tag_data(variant_tag)
    assert tag_data.GetDEnabling(tag, stranger, None, 0, None) is True
    tag_data._handle_command(tag, {"id": stranger})
    assert variant_tag.read_state(tag)["active"] == 0


def test_get_denabling_only_offers_the_rows_that_can_be_mounted(variant_tag):
    """La montada no se re-monta y una perdida tampoco: el botón dice la
    verdad en vez de aceptar el clic y no hacer nada."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", None)  # perdida
    tag_data = _tag_data(variant_tag)

    def enabled(index):
        cid = variant_tag.ID_OPTION_BASE + index * variant_tag.ID_OPTION_STRIDE
        return tag_data.GetDEnabling(tag, cid, None, 0, None)

    assert enabled(0) is False, "la opción montada no se puede volver a montar"
    assert enabled(1) is False, "una opción cuyo enlace no resuelve tampoco"


# --- La guarda de esquema ---------------------------------------------------

def test_read_state_reads_an_unknown_schema_as_empty_never_half_way(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    payload = variant_tag._read_payload_bc(tag)
    payload.SetInt32(variant_tag._PAYLOAD_SCHEMA, variant_tag.VARIANT_SCHEMA + 7)

    state = variant_tag.read_state(tag)

    assert state["options"] == []
    assert state["active"] is None


# --- Orden de escena, no orden de clic --------------------------------------

def test_create_variant_set_uses_scene_order_not_click_order(variant_tag):
    """Decisión de contrato (ver ``_in_scene_order``): envolver es contención,
    no autoría, así que el resultado depende sólo de la escena. Con el orden
    de clic, la misma selección daría un orden distinto dentro de la opción y
    aterrizaría el anclaje en un sitio distinto del Object Manager."""
    import c4d

    doc = _scene(c4d)
    a = _insert(doc, FakeObject("luz_a", c4d, doc))
    b = _insert(doc, FakeObject("luz_b", c4d, doc))
    c = _insert(doc, FakeObject("luz_c", c4d, doc))
    after = _insert(doc, FakeObject("despues", c4d, doc))

    variant_tag.create_variant_set(doc, [c, a, b])

    anchor = doc.root[0]
    assert anchor.GetName().startswith("Opciones"), (
        "el anclaje ocupa el sitio del primero EN LA ESCENA, no del primero pinchado"
    )
    assert doc.root[1] is after
    option = anchor._children[0]
    assert [obj.GetName() for obj in option._children] == [
        "luz_a", "luz_b", "luz_c",
    ]


# --- El invariante del anclaje ----------------------------------------------

def test_switch_evacuates_anything_the_artist_dropped_under_the_anchor(variant_tag):
    """El anclaje es un null corriente en el Object Manager: lo que el artista
    arrastre ahí dentro quedaría, si no se saca, dentro de TODAS las opciones
    e invisible para el resumen. El invariante se impone leyendo la escena."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    stray = _insert(doc, FakeObject("arrastrado a mano", c4d, doc), anchor)
    assert len(anchor._children) == 2

    assert variant_tag.switch_to_option(tag, 1)["ok"] is True

    assert anchor._children == [option_b], "el anclaje tiene exactamente un hijo"
    park = option_a._parent
    assert stray._parent is park, "lo arrastrado sale con lo aparcado, no se queda"


# --- La cadena de undo con MÁS DE UN objeto en movimiento --------------------
# Con uno solo, un AddUndo fijado fuera del bucle pasa por bueno: es el modo
# de fallo exacto de matwire v1.32 (validado con un material, roto con dos).

def test_create_variant_set_registers_a_move_undo_for_EVERY_object_it_moves(variant_tag):
    """Tres luces envueltas de una vez: si sólo la primera lleva su
    ``AddUndo``, un Cmd+Z revierte el movimiento de una y deja las otras dos
    dentro de la opción mientras el anclaje desaparece con su ``NEWOBJ`` —
    dos luces enterradas en un null suelto."""
    import c4d

    doc = _scene(c4d)
    roots = [_insert(doc, FakeObject(name, c4d, doc))
             for name in ("luz_a", "luz_b", "luz_c")]

    mark = len(doc.events)
    assert variant_tag.create_variant_set(doc, roots)["ok"] is True

    for obj in roots:
        assert _first_touch(doc, obj, mark) == ("undo", c4d.UNDOTYPE_CHANGE), (
            "%s se movió sin su AddUndo delante" % obj.GetName()
        )
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)


def test_switch_registers_a_move_undo_for_EVERY_object_it_evacuates(variant_tag):
    """Un cambio con varios objetos colgando del anclaje (la opción activa
    más lo que el artista arrastró ahí) mueve N cosas. Si sólo la primera
    pasa por ``_reparent``, el Cmd+Z revierte una y el resto se queda
    aparcado e invisible sin que nada lo diga."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    stray_one = _insert(doc, FakeObject("arrastrado 1", c4d, doc), anchor)
    stray_two = _insert(doc, FakeObject("arrastrado 2", c4d, doc), anchor)
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    doc.start_undo_count = 0
    doc.end_undo_count = 0
    mark = len(doc.events)
    assert variant_tag.switch_to_option(tag, 1)["ok"] is True

    for moved in (option_a, stray_one, stray_two, option_b):
        assert _first_touch(doc, moved, mark) == ("undo", c4d.UNDOTYPE_CHANGE), (
            "%s se movió sin su AddUndo delante" % moved.GetName()
        )
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)


# --- La evacuación se dice, y sin cajón no se monta --------------------------

def test_switch_reports_what_it_pulled_out_of_the_anchor(variant_tag):
    """Un objeto que el artista arrastró bajo el anclaje acaba en un
    contenedor de la raíz con la visibilidad apagada: desaparece de su sitio.
    Política de la casa (v1.35): el resultado siempre se reporta."""
    import c4d
    from sentinel import variants

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    _insert(doc, FakeObject("arrastrado a mano", c4d, doc), anchor)
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    result = variant_tag.switch_to_option(tag, 1)

    assert result["evacuated"] == ["arrastrado a mano"], (
        "la opción aparcada es esperada y ya va en 'name'; lo que hay que "
        "decir es lo OTRO que salió"
    )
    # CAMBIADA (fixes-3, Minor 4): antes fijaba "1 objeto suelto sacados"
    # (concordancia rota — participio en plural fijo con sustantivo
    # singular). El fix mete el participio DENTRO de pluralize_es
    # ("objeto suelto sacado" / "objetos sueltos sacados"), así que el
    # caso de un objeto ahora concuerda en singular.
    assert variants.switch_report_text(result) == (
        'montada "Opción B" · 1 objeto suelto sacado del anclaje: '
        "arrastrado a mano"
    )


def test_pressing_a_row_delivers_the_report_instead_of_dropping_it(variant_tag, monkeypatch):
    """``_handle_command`` descartaba el retorno entero — con él, la
    evacuación silenciosa y también un ``lost_option``.

    Se afirman LOS DOS canales que ``_report`` promete (docstring: "barra
    de estado primero — entrega primaria in-C4D — y consola siempre"),
    no sólo ``safe_print``. Sin un ``StatusSetText`` de mentira, esa línea
    era inejecutable bajo este arnés: ``c4d.gui`` es un módulo permisivo
    que auto-vivifica ``StatusSetText`` a un ``int``, llamarlo lanza
    ``TypeError`` y el ``except Exception: pass`` de ``_report`` se lo
    traga en silencio — el canal que el docstring vende como el primario
    nunca se ejecutaba bajo test (fixes-3, Minor 2)."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    _insert(doc, FakeObject("arrastrado a mano", c4d, doc), tag.GetObject())
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    said = []
    monkeypatch.setattr(variant_tag, "safe_print", said.append)
    status = []
    monkeypatch.setattr(c4d.gui, "StatusSetText", status.append)

    row_id = variant_tag.ID_OPTION_BASE + 1 * variant_tag.ID_OPTION_STRIDE
    _tag_data(variant_tag)._handle_command(tag, {"id": row_id})

    assert said and "arrastrado a mano" in said[0]
    assert status and "arrastrado a mano" in status[0]


def test_pressing_a_row_says_why_when_the_option_is_lost(variant_tag, monkeypatch):
    """Mismo par de canales que el test anterior — barra de estado
    (primaria) + consola — para no dejar cubierta sólo la mitad del
    contrato de ``_report`` en este segundo camino (fixes-3, Minor 2)."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", None)

    said = []
    monkeypatch.setattr(variant_tag, "safe_print", said.append)
    status = []
    monkeypatch.setattr(c4d.gui, "StatusSetText", status.append)

    row_id = variant_tag.ID_OPTION_BASE + 1 * variant_tag.ID_OPTION_STRIDE
    _tag_data(variant_tag)._handle_command(tag, {"id": row_id})

    assert said and "no se encuentra" in said[0]
    assert status and "no se encuentra" in status[0]


def test_switch_without_a_park_container_mounts_nothing(variant_tag, monkeypatch):
    """Sin cajón, el bucle de evacuación no corre; montar igual dejaría el
    anclaje con DOS hijos, justo el estado que el invariante impide. Se
    aborta y se dice, en vez de romperlo callando."""
    import c4d
    from sentinel import variants

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    monkeypatch.setattr(variant_tag, "_ensure_park_container",
                        lambda doc_, payload: None)
    result = variant_tag.switch_to_option(tag, 1)

    assert result["ok"] is False
    assert result["reason"] == "no_park_container"
    assert anchor._children == [option_a], "el anclaje sigue con exactamente un hijo"
    assert option_b._parent is not anchor
    payload = variant_tag._read_payload_bc(tag)
    assert payload.GetInt32(variant_tag._PAYLOAD_ACTIVE, -1) == 0
    # CAMBIADA (fixes-3, Minor 3): antes fijaba (2, 2) — un bracket vacío se
    # abría y cerraba en switch_to_option sin mover nada, el mismo defecto
    # que create_variant_set:517 prohíbe por escrito ("un paso de deshacer
    # que no deshace nada es peor que ninguno"). El fix comprueba el cajón
    # ANTES de abrir el bracket, así que un switch fallido por falta de
    # cajón ya no gasta un paso de deshacer: sólo el (1, 1) del create.
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1), (
        "sin cajón, switch_to_option no abre bracket — sólo el del create"
    )
    assert variants.switch_report_text(result) == (
        "no se cambió de opción — no se pudo crear el contenedor de aparcado"
    )


# --- La descripción: lo que el tag PIDE pintar -------------------------------
# Toda esta capa (GetDDescription/GetDParameter/SetDParameter/Init/Execute y
# la rama de fallback de Message) era código que ningún test ejecutaba, y
# cinco mutaciones que dejan la feature sin UI sobrevivían la suite entera.

def _describe(variant_tag, tag, reject=()):
    description = FakeDescription(reject=reject)
    result = _tag_data(variant_tag).GetDDescription(tag, description, 0)
    return description, result


def _scene_with_two_options(variant_tag, c4d):
    """Conjunto de dos opciones con contenido a los DOS lados, para que el
    resumen y la advertencia salgan los dos no vacíos y DISTINTOS."""
    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _insert(doc, FakeObject("cubo_b", c4d, doc), option_b)
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)
    return doc, tag, option_b


def _row_group_id(variant_tag, index):
    return (variant_tag.ID_OPTION_BASE + index * variant_tag.ID_OPTION_STRIDE
            + variant_tag._OPTION_ACTION_GROUP)


def _mount_labels(variant_tag, description, count=2):
    """Las etiquetas de los botones de MONTAR, en orden de opción. Antes se
    leían con ``names_under(ID_GROUP_OPTIONS)`` porque los botones colgaban
    directamente del grupo; desde la Tarea 4 cada opción tiene su sub-grupo
    de fila (montar · nombre · borrar en una línea), así que hay que mirar
    dentro de él."""
    return [description.name_of(
        variant_tag.ID_OPTION_BASE + index * variant_tag.ID_OPTION_STRIDE)
        for index in range(count)]


def test_get_ddescription_paints_one_row_per_option(variant_tag):
    """Sin fila por opción el tag no tiene UI: la feature entera es
    invisible y no hay nada que pulsar."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)

    description, result = _describe(variant_tag, tag)

    assert result == (True, 0 | c4d.DESCFLAGS_DESC_LOADED)
    assert description.loaded == [tag.GetType()], (
        "sin LoadDescription el Attribute Manager no tiene base sobre la "
        "que pintar filas propias del tag"
    )
    # CAMBIADA (Tarea 4): lo que cuelga del grupo de opciones ya no son los
    # botones de montar sino un SUB-GRUPO por opción (montar · nombre ·
    # borrar en una línea). El botón de montar sigue existiendo con el mismo
    # id, un nivel más adentro — se comprueba igual, ahora dentro de su fila.
    assert description.row_ids_under(variant_tag.ID_GROUP_OPTIONS) == [
        _row_group_id(variant_tag, 0),
        _row_group_id(variant_tag, 1),
    ]
    row_ids = [variant_tag.ID_OPTION_BASE,
               variant_tag.ID_OPTION_BASE + variant_tag.ID_OPTION_STRIDE]
    for index, row_id in enumerate(row_ids):
        assert row_id in description.row_ids_under(_row_group_id(variant_tag, index))
    # Y son botones PULSABLES, no sólo filas con dtype-botón: el propio
    # código (variant_tag.py:811) dice por escrito que sin CUSTOMGUI_BUTTON
    # un DTYPE_BUTTON se pinta como celda vacía en vez de botón
    # (frame_tag.py:1775, confirmado en vivo — no re-descubrir), así que
    # DTYPE_BUTTON solo no basta para afirmar "son botones". Se afirma
    # también DESC_ANIMATE_OFF (ninguna fila de opción es keyframeable —
    # un rombo por fila fue el mayor coste de ancho medido en el Frame
    # v1.29) porque las tres propiedades juntas son lo que hace la fila
    # REAL, no sólo nombrada así.
    for row_id in row_ids:
        bc = description.bc_of(row_id)
        assert bc is not None
        assert bc.GetInt32(c4d.DESC_CUSTOMGUI, None) == c4d.CUSTOMGUI_BUTTON
        assert bc.GetInt32(c4d.DESC_ANIMATE, None) == c4d.DESC_ANIMATE_OFF
    # El grupo de opciones se pinta a una sola columna, para que cada fila
    # de opción no comparta ancho con nada.
    options_group_bc = description.bc_of(variant_tag.ID_GROUP_OPTIONS)
    assert options_group_bc is not None
    assert options_group_bc.GetInt32(c4d.DESC_COLUMNS, None) == 1


def test_the_option_row_marked_with_a_dot_is_the_MOUNTED_one(variant_tag):
    """Con el marcador invertido, el ● señala todas las opciones menos la
    que está puesta — y el artista pulsa la que ya tiene."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)

    description, _ = _describe(variant_tag, tag)

    assert _mount_labels(variant_tag, description) == ["● Opción A", "○ Opción B"]

    # Y tras cambiar, el ● se mueve con la opción montada.
    assert variant_tag.switch_to_option(tag, 1)["ok"] is True
    description, _ = _describe(variant_tag, tag)
    assert _mount_labels(variant_tag, description) == ["○ Opción A", "● Opción B"]


def test_a_lost_option_says_so_in_its_own_row(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", None)

    description, _ = _describe(variant_tag, tag)

    assert _mount_labels(variant_tag, description) == [
        "● Opción A", "⚠ Opción B (no encontrada)",
    ]


def test_get_ddescription_paints_the_summary_and_the_warning_as_two_rows(variant_tag):
    """SEPARADAS a propósito (lección del Pin): concatenada detrás del
    conteo, la advertencia es lo primero que se trunca."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)

    description, _ = _describe(variant_tag, tag)

    painted = [row[0] for row in description.rows]
    assert variant_tag.ID_VARIANTS_STATUS in painted
    assert variant_tag.ID_VARIANTS_WARNING in painted
    assert description.name_of(variant_tag.ID_VARIANTS_STATUS) == "Estado"
    # Las dos cuelgan de la raíz de la descripción, no del grupo de opciones.
    assert variant_tag.ID_VARIANTS_STATUS not in description.row_ids_under(
        variant_tag.ID_GROUP_OPTIONS)


def test_get_ddescription_gives_up_when_a_row_cannot_be_declared(variant_tag):
    """Media descripción pintada es peor que ninguna: el Attribute Manager
    enseñaría un conjunto con menos opciones de las que tiene."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)

    _, result = _describe(
        variant_tag, tag,
        reject=[variant_tag.ID_OPTION_BASE + variant_tag.ID_OPTION_STRIDE])

    assert result is False


def test_get_dparameter_puts_the_summary_and_the_warning_in_their_own_rows(variant_tag):
    """Intercambiados, la fila "Estado" enseña la advertencia y la
    advertencia el resumen — y el tag miente en las dos."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)
    tag_data = _tag_data(variant_tag)

    def value(param_id):
        got = tag_data.GetDParameter(
            tag, c4d.DescID(c4d.DescLevel(param_id)), 0)
        assert got[0] is True
        return got[1]

    assert value(variant_tag.ID_VARIANTS_STATUS) == (
        "Opción A · 2 opciones · 1 objeto montado")
    assert value(variant_tag.ID_VARIANTS_WARNING).startswith("⚠ 1 objeto aparcado")
    # Un id que no es nuestro se deja pasar al host.
    assert tag_data.GetDParameter(
        tag, c4d.DescID(c4d.DescLevel(variant_tag.ID_GROUP_OPTIONS)), 0) is False


def test_set_dparameter_swallows_writes_to_the_derived_rows(variant_tag):
    """Son texto derivado: si la escritura llegara al dato real, el resumen
    se quedaría congelado en lo que se escribió."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)
    tag_data = _tag_data(variant_tag)

    for param_id in (variant_tag.ID_VARIANTS_STATUS, variant_tag.ID_VARIANTS_WARNING):
        got = tag_data.SetDParameter(
            tag, c4d.DescID(c4d.DescLevel(param_id)), "basura", 0)
        assert got[0] is True
    assert tag_data.SetDParameter(
        tag, c4d.DescID(c4d.DescLevel(variant_tag.ID_GROUP_OPTIONS)), "x", 0) is False

    # Y el resumen sigue derivándose de la escena, no de lo escrito.
    assert tag_data.GetDParameter(
        tag, c4d.DescID(c4d.DescLevel(variant_tag.ID_VARIANTS_STATUS)), 0
    )[1] == "Opción A · 2 opciones · 1 objeto montado"


def test_execute_is_what_keeps_the_set_name_alive_across_a_reload(variant_tag):
    """Hay dos tests de ``_sync_display_name`` que dan la sensación de que la
    supervivencia del nombre está fijada, y nadie comprobaba el ÚNICO
    cableado que la hace correr: quitar la llamada de ``Execute`` deja el
    nombre del conjunto muriendo en cada carga con la suite en verde."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    tag_data = _tag_data(variant_tag)

    tag.SetName("con y sin bend")
    tag_data.Execute(tag, doc, tag.GetObject(), None, 0, 0)  # el espejo se llena

    tag.SetName(variant_tag.VARIANT_TAG_DEFAULT_NAME)  # lo que hace una carga
    assert tag_data.Execute(tag, doc, tag.GetObject(), None, 0, 0) == (
        c4d.EXECUTIONRESULT_OK)

    assert tag.GetName() == "con y sin bend"


def test_init_accepts_the_tag(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]

    assert _tag_data(variant_tag).Init(tag) is True


def test_message_leaves_messages_that_are_not_ours_alone(variant_tag):
    """La rama de fallback: un mensaje ajeno no puede acabar despachado como
    si fuera el clic de una fila."""
    import c4d

    doc, tag, option_b = _two_option_set(variant_tag, c4d)

    assert _tag_data(variant_tag).Message(tag, c4d.MSG_MENUPREPARE, None) is True
    assert variant_tag.read_state(tag)["active"] == 0


# --- Bug de identidad cazado en vivo (Tarea 3) -------------------------------
# ``id(obj)`` como identidad de nodo funcionaba en el arnés (identidad Python
# estable) y NUNCA en C4D real (envoltorio nuevo por lectura, medido en
# vivo). Los tres tests de abajo usan ``_Reread`` para reproducir exactamente
# eso: dos "caminos de lectura" del MISMO nodo con ``id()`` propio, que es la
# única forma de que estos tres sitios puedan fallar bajo test.

def test_top_level_only_excludes_a_nested_child_read_via_a_different_wrapper(
    variant_tag,
):
    """El padre entra en ``objects`` como una lectura (``_Reread``); subir
    por ``GetUp()`` desde el hijo entrega OTRA lectura del mismo padre, con
    ``id()`` propio. Comparar por ``id()`` no reconoce que son el mismo nodo
    y deja pasar al hijo como si fuera una raíz propia — el bug medido en
    vivo, aquí para ``_top_level_only`` en vez de para el orden de escena."""
    import c4d

    doc = _scene(c4d)
    parent = _insert(doc, FakeObject("padre", c4d, doc))
    child = _insert(doc, FakeObject("hijo", c4d, doc), parent)

    result = variant_tag._top_level_only([_Reread(parent), child])

    assert len(result) == 1, (
        "el hijo se coló como raíz: la comprobación de anidamiento no "
        "reconoció que _Reread(parent) y el padre real vuelto a leer vía "
        "GetUp() son el MISMO nodo"
    )
    assert result[0] == parent


def test_in_scene_order_reads_the_true_scene_order_not_click_order(variant_tag):
    """Reproduce el caso medido EXACTO del brief: tres luces en la escena en
    orden ``c, b, a`` y un orden de clic ``a, c, b``. Con ``id()`` la
    búsqueda en el mapa de ``_document_order`` fallaba siempre (las
    lecturas de ``roots`` vienen envueltas aparte de las que
    ``doc.GetFirstObject()``/``GetNext()`` producen), así que TODO caía al
    "al final" y el ``sorted()`` estable conservaba el orden de clic
    intacto — el bug live-verified: la opción B salió con las luces en el
    orden en que se pinchó, no en el que vivían en la escena."""
    import c4d

    doc = _scene(c4d)
    luz_c = _insert(doc, FakeObject("luz_c", c4d, doc))
    luz_b = _insert(doc, FakeObject("luz_b", c4d, doc))
    luz_a = _insert(doc, FakeObject("luz_a", c4d, doc))

    click_order = [_Reread(luz_a), _Reread(luz_c), _Reread(luz_b)]
    ordered = variant_tag._in_scene_order(doc, click_order)

    assert [obj.GetName() for obj in ordered] == ["luz_c", "luz_b", "luz_a"], (
        "el orden de escena se perdió: order.get(id(obj), fallback) nunca "
        "encontraba una entrada porque el recorrido de doc.GetFirstObject() "
        "y la selección de roots son lecturas distintas del mismo nodo"
    )


def test_switch_does_not_double_evacuate_the_parked_option_read_via_a_different_wrapper(
    variant_tag,
):
    """La opción A activa se lee dos veces por dos caminos distintos cuando
    se cambia de opción: como hijo del anclaje (``_children_of``) y como el
    ``BaseLink`` del payload (``_option_link`` / ``GetLink``). El test fuerza
    que el segundo camino entregue un ``_Reread`` del mismo nodo — lo que
    mide el brief como comportamiento real de C4D — y comprueba que NO se
    reporta como un objeto "evacuado a mano": es la propia opción aparcada,
    leída dos veces, no algo que el artista arrastrara al anclaje."""
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    anchor = tag.GetObject()
    option_a = anchor._children[0]

    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", option_b)

    # El BaseLink de la opción A pasa a resolver a un ENVOLTORIO nuevo del
    # mismo nodo que ``anchor._children[0]`` — la lectura por GetLink nunca
    # tiene por qué compartir wrapper con la lectura por jerarquía.
    payload = variant_tag._read_payload_bc(tag)
    opt_a_bc = variant_tag._option_bc(payload, 0)
    opt_a_bc.SetLink(variant_tag._OPTION_LINK, _Reread(option_a))

    mark = len(doc.events)
    result = variant_tag.switch_to_option(tag, 1)

    assert result["ok"] is True
    assert result["evacuated"] == [], (
        "la opción A activa, leída dos veces por dos caminos, se reportó "
        "como una fila 'evacuated' fantasma — id()/is no reconoció que "
        "_children_of(anchor)[0] y el park_node vía GetLink son el mismo nodo"
    )
    assert anchor._children == [option_b]
    assert option_a._parent is not None
    assert option_a._parent.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME

    # La comprobación que de verdad aísla el ``seen``/``id(node)`` del bucle
    # de dedupe (líneas 649/651 del brief) de la de ``strays`` de más abajo:
    # ``FakeObject.Remove()`` siempre registra el evento con el nodo CRUDO
    # subyacente (``_Reread`` delega el método, no lo intercepta), así que
    # si el bucle NO dedupe por valor, ``option_a`` se mueve DOS veces —
    # visible aquí aunque ``strays`` (que sí compara por valor) ya saliera
    # vacío por su cuenta.
    removes = [e for e in doc.events[mark:]
               if e[0] == "remove" and e[1] is option_a]
    assert len(removes) == 1, (
        "la opción A se reparentó %d veces: el bucle de dedupe de "
        "'evacuate' no reconoció que el hijo del anclaje y el park_node "
        "leído por GetLink son el MISMO nodo" % len(removes)
    )


# --- Tarea 4: duplicar, renombrar y borrar -----------------------------------

def _add_option(variant_tag, tag, c4d, name, node):
    """Añade una opción APARCADA al final del payload, a mano — la versión
    general de ``_add_second_option`` (que fija el índice 1), para poder
    montar escenarios de tres opciones."""
    payload = variant_tag._read_payload_bc(tag)
    options = payload.GetContainerInstance(variant_tag._PAYLOAD_OPTIONS)
    count = payload.GetInt32(variant_tag._PAYLOAD_COUNT, 0)
    option = c4d.BaseContainer()
    option.SetString(variant_tag._OPTION_NAME, name)
    option.SetLink(variant_tag._OPTION_LINK, node)
    options.SetContainer(count, option)
    payload.SetInt32(variant_tag._PAYLOAD_COUNT, count + 1)
    return payload


def _one_option_set(variant_tag, c4d):
    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    return doc, tag


def _three_option_set(variant_tag, c4d):
    """A montada, B y C aparcadas — el estado mínimo donde un borrado puede
    desplazar índices y equivocarse de opción montada."""
    doc, tag = _one_option_set(variant_tag, c4d)
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    option_c = _insert(doc, FakeObject("Opción C", c4d, doc))
    _add_option(variant_tag, tag, c4d, "Opción B", option_b)
    _add_option(variant_tag, tag, c4d, "Opción C", option_c)
    return doc, tag, option_b, option_c


def test_duplicate_makes_option_b_and_leaves_the_artist_working_on_it(variant_tag):
    """El gesto sustituye al "Cmd+C y arrastrar al backup" de hoy: si dejara
    montada la original, el artista editaría la que quería conservar."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.duplicate_active_option(tag)

    assert result["ok"] is True
    assert result["name"] == "Opción B"
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)

    state = variant_tag.read_state(tag)
    assert [opt["name"] for opt in state["options"]] == ["Opción A", "Opción B"]
    assert state["active"] == 1
    assert len(anchor._children) == 1, "el anclaje sigue teniendo un solo hijo"
    clone = anchor._children[0]
    assert clone is not option_a, "se montó la original, no la copia"
    assert clone.GetName() == "Opción B"
    assert [c.GetName() for c in clone._children] == ["cubo"], (
        "el clon se lleva el subárbol: sin él la copia está vacía"
    )
    assert option_a._parent is not None
    assert option_a._parent.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME
    assert state["options"][1]["objects"] == 1


def test_duplicating_twice_gives_option_c_not_a_second_b(variant_tag):
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)

    variant_tag.duplicate_active_option(tag)
    result = variant_tag.duplicate_active_option(tag)

    assert result["name"] == "Opción C"
    assert [opt["name"] for opt in variant_tag.read_state(tag)["options"]] == [
        "Opción A", "Opción B", "Opción C",
    ]


def test_rename_dedupes_against_the_other_options_in_payload_and_null(variant_tag):
    """Dos opciones con el mismo nombre son indistinguibles en la fila Y en
    los nombres de archivo del render. El null se renombra con el payload
    porque es lo que el artista ve en el Object Manager."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_option(variant_tag, tag, c4d, "Opción B", option_b)

    assert variant_tag.rename_option(tag, 0, "hero")["ok"] is True
    doc.start_undo_count = 0
    doc.end_undo_count = 0
    result = variant_tag.rename_option(tag, 1, "hero")

    assert result["ok"] is True
    assert result["name"] == "hero (2)"
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)
    names = [opt["name"] for opt in variant_tag.read_state(tag)["options"]]
    assert names == ["hero", "hero (2)"]
    assert option_b.GetName() == "hero (2)", (
        "el null de la opción es lo que el artista ve en el Object Manager"
    )


def test_renaming_an_option_to_its_own_name_opens_no_bracket(variant_tag):
    """El Attribute Manager reescribe el campo con lo que acaba de leer: un
    paso de deshacer por repintado se comería los Cmd+Z del artista."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.rename_option(tag, 0, "Opción A")

    assert result["ok"] is False
    assert result["reason"] == "unchanged"
    assert (doc.start_undo_count, doc.end_undo_count) == (0, 0)


def test_deleting_the_option_before_the_active_one_keeps_the_same_one_mounted(
    variant_tag,
):
    """Por NOMBRE, no por índice: borrar una opción anterior a la activa
    desplaza los índices, y sin el ajuste de ``plan_delete`` quedaría montada
    otra opción en silencio."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    assert variant_tag.switch_to_option(tag, 2)["ok"] is True  # C montada
    anchor = tag.GetObject()
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.delete_option(tag, 0)

    assert result["ok"] is True
    assert result["name"] == "Opción A"
    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)
    state = variant_tag.read_state(tag)
    assert [opt["name"] for opt in state["options"]] == ["Opción B", "Opción C"]
    assert state["options"][state["active"]]["name"] == "Opción C"
    assert anchor._children == [option_c]


def test_deleting_the_mounted_option_mounts_the_promoted_one_and_removes_it(
    variant_tag,
):
    """El anclaje no puede quedarse vacío: se monta primero la que promociona
    el plan y se borra después, todo en el mismo paso de deshacer."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    assert variant_tag.switch_to_option(tag, 2)["ok"] is True  # C montada
    anchor = tag.GetObject()
    mark = len(doc.events)

    result = variant_tag.delete_option(tag, 2)

    assert result["ok"] is True
    assert result["name"] == "Opción C"
    assert result["mounted"] == "Opción B"
    assert anchor._children == [option_b]
    assert option_c._parent is None, "la opción borrada sale de la escena"
    state = variant_tag.read_state(tag)
    assert [opt["name"] for opt in state["options"]] == ["Opción A", "Opción B"]
    assert state["options"][state["active"]]["name"] == "Opción B"
    # El undo de borrado va ANTES del Remove, igual que el de movimiento
    # (patrón de fixes.py/scene_tools.py): sin él un Cmd+Z no trae de vuelta
    # el subárbol borrado.
    assert _first_touch(doc, option_c, mark) == ("undo", c4d.UNDOTYPE_DELETEOBJ)


def test_deleting_the_only_option_is_refused_without_a_bracket(variant_tag):
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.delete_option(tag, 0)

    assert result["ok"] is False
    assert result["reason"] == "last_option"
    assert (doc.start_undo_count, doc.end_undo_count) == (0, 0)
    assert anchor._children == [option_a]
    assert len(variant_tag.read_state(tag)["options"]) == 1


def test_deleting_the_mounted_option_at_index_zero_leaves_one_child_mounted(
    variant_tag,
):
    """El caso discriminante del ajuste de índice: ``plan_delete`` devuelve
    ``new_active`` en la numeración de DESPUÉS de borrar, y borrar la
    montada cuando es la primera lo deja en 0 — que en la numeración de AHORA
    es la propia víctima. Leerlo sin el ``+1`` monta la víctima, la borra a
    continuación y deja el anclaje con CERO hijos: el estado exacto que el
    invariante existe para impedir. El resto de tests no lo ve porque el que
    borra una no montada no calcula ``mount_node``, y el que borra la montada
    usa el índice 2, donde las dos ramas coinciden."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    assert variant_tag.read_state(tag)["active"] == 0, "A es la montada"

    result = variant_tag.delete_option(tag, 0)

    assert result["ok"] is True
    assert result["name"] == "Opción A"
    assert result["mounted"] == "Opción B"
    assert len(anchor._children) == 1, (
        "el anclaje quedó con %d hijos: se montó la propia víctima antes de "
        "borrarla" % len(anchor._children)
    )
    state = variant_tag.read_state(tag)
    assert [opt["name"] for opt in state["options"]] == ["Opción B", "Opción C"]
    assert state["options"][state["active"]]["name"] == "Opción B"
    assert anchor._children == [option_b], (
        "el hijo del anclaje no es el que dice el payload"
    )
    assert option_a._parent is None, "la opción borrada sale de la escena"


def _two_loose_objects_in(doc, anchor, c4d):
    """Dos objetos que el artista arrastró al anclaje a mano. DOS y no uno:
    con uno solo, un ``AddUndo`` fijado fuera del bucle pasa por bueno (el
    modo de fallo de matwire v1.32)."""
    loose_a = FakeObject("luz_key", c4d, doc)
    loose_b = FakeObject("luz_fill", c4d, doc)
    loose_a.InsertUnder(anchor)
    loose_b.InsertUnder(anchor)
    return loose_a, loose_b


def test_duplicating_undoes_each_evacuated_object_before_moving_it(variant_tag):
    """``_evacuate_anchor`` es el TERCER camino que mueve objetos, y mover sin
    ``AddUndo`` por objeto es literalmente el bug de matwire v1.32: el Cmd+Z
    no devuelve a su sitio lo que el artista tenía dentro del anclaje."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    loose_a, loose_b = _two_loose_objects_in(doc, anchor, c4d)
    mark = len(doc.events)

    result = variant_tag.duplicate_active_option(tag)

    assert result["ok"] is True
    for node in (loose_a, loose_b, option_a):
        assert _first_touch(doc, node, mark) == ("undo", c4d.UNDOTYPE_CHANGE), (
            "%s se movió sin su AddUndo delante" % node.GetName()
        )
    assert len(anchor._children) == 1, "el anclaje se vació entero menos la copia"
    park_names = [c.GetName() for c in loose_a._parent._children]
    assert loose_a._parent.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME
    assert "luz_fill" in park_names


def test_duplicating_reports_what_it_pulled_out_of_the_anchor(variant_tag):
    """Duplicar hace la MISMA evacuación silenciosa que cambiar de opción:
    sin este canal, ``luz_key`` acaba en un null oculto de la raíz y ninguna
    superficie lo dice (``read_state`` sólo suma subárboles de opciones
    resueltas, así que ``warning_text`` tampoco lo ve)."""
    import c4d
    from sentinel import variants

    doc, tag = _one_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    _two_loose_objects_in(doc, anchor, c4d)

    result = variant_tag.duplicate_active_option(tag)

    assert result["evacuated"] == ["luz_fill", "luz_key"], (
        "la opción copiada no es una sorpresa y no se reporta; los objetos "
        "sueltos del artista, sí"
    )
    text = variants.action_report_text(result)
    assert 'duplicada como "Opción B"' in text
    assert "2 objetos sueltos sacados del anclaje: luz_fill, luz_key" in text


def test_deleting_the_mounted_option_undoes_each_evacuated_object(variant_tag):
    """El camino ``keep=victim`` de ``_evacuate_anchor``: hay que vaciar el
    anclaje para montar la que promociona, sin llevarse por delante a la
    víctima (que se borra un momento después)."""
    import c4d
    from sentinel import variants

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    loose_a, loose_b = _two_loose_objects_in(doc, anchor, c4d)
    mark = len(doc.events)

    result = variant_tag.delete_option(tag, 0)

    assert result["ok"] is True
    for node in (loose_a, loose_b):
        assert _first_touch(doc, node, mark) == ("undo", c4d.UNDOTYPE_CHANGE), (
            "%s se movió sin su AddUndo delante" % node.GetName()
        )
    assert anchor._children == [option_b], (
        "el anclaje no se vació antes de montar la que promociona"
    )
    assert loose_a._parent.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME
    assert option_a._parent is None
    assert result["evacuated"] == ["luz_fill", "luz_key"]
    text = variants.action_report_text(result)
    assert 'borrada "Opción A" · montada "Opción B"' in text
    assert "2 objetos sueltos sacados del anclaje: luz_fill, luz_key" in text


def test_duplicate_registers_the_undo_of_the_tag_and_of_the_clone(variant_tag):
    """Los dos ``AddUndo`` que hacen de duplicar UN paso de deshacer, y no
    medio: sin el del tag, Cmd+Z revierte la escena pero no el payload (el
    conjunto lista una "Opción B" cuyo null ya no existe); sin el del clon,
    Cmd+Z deja el clon montado mientras el payload dice que no existe."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    doc.undo_ops = []

    assert variant_tag.duplicate_active_option(tag)["ok"] is True

    clone = anchor._children[0]
    assert (c4d.UNDOTYPE_CHANGE, tag) in doc.undo_ops, (
        "el payload cambia y no lleva su AddUndo: Cmd+Z lo deja divergente "
        "de la escena"
    )
    assert (c4d.UNDOTYPE_NEWOBJ, clone) in doc.undo_ops, (
        "el clon se inserta sin su AddUndo: Cmd+Z lo deja montado"
    )


def test_rename_registers_the_undo_of_the_tag_and_of_the_null(variant_tag):
    """Renombrar escribe en DOS sitios (payload y null) y los dos tienen que
    volver con el mismo Cmd+Z: sin el ``AddUndo`` del null, la fila dice
    "Opción A" y el Object Manager dice "hero", divergentes para siempre."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    option_a = tag.GetObject()._children[0]
    doc.undo_ops = []

    assert variant_tag.rename_option(tag, 0, "hero")["ok"] is True

    assert (c4d.UNDOTYPE_CHANGE, tag) in doc.undo_ops
    assert (c4d.UNDOTYPE_CHANGE, option_a) in doc.undo_ops, (
        "el null se renombra sin su AddUndo: Cmd+Z revierte el payload y "
        "deja el nombre del null"
    )


# Identidad por VALOR en los dos sitios nuevos de la Tarea 4 — el mismo bug
# que la Tarea 3 cazó en vivo: la víctima llega por ``GetLink`` y sus hijos
# por ``_children_of``, que en C4D real son lecturas DISTINTAS del mismo nodo
# (envoltorio Python nuevo cada vez). ``_Reread`` construye ese escenario.

def test_deleting_the_mounted_option_does_not_park_the_victim_itself(variant_tag):
    """``_evacuate_anchor(keep=victim)`` con ``is`` en vez de ``==`` no
    reconocería a la víctima entre los hijos del anclaje y la aparcaría antes
    de borrarla — un movimiento de más, dentro del mismo paso de deshacer,
    sobre el objeto que ya iba a desaparecer."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    _two_loose_objects_in(doc, anchor, c4d)  # obliga a crear el cajón
    payload = variant_tag._read_payload_bc(tag)
    opt_a_bc = variant_tag._option_bc(payload, 0)
    opt_a_bc.SetLink(variant_tag._OPTION_LINK, _Reread(option_a))
    mark = len(doc.events)

    assert variant_tag.delete_option(tag, 0)["ok"] is True

    parked = [event for event in doc.events[mark:]
              if event[0] == "insert_under" and event[1] is option_a]
    assert parked == [], (
        "la víctima se aparcó antes de borrarla: el keep de _evacuate_anchor "
        "no reconoció que el hijo del anclaje y la víctima leída por GetLink "
        "son el MISMO nodo"
    )
    assert anchor._children == [option_b]


def test_deleting_the_mounted_option_without_strays_creates_no_park_container(
    variant_tag,
):
    """El otro lado de la misma comparación: con ``is not``, la víctima
    contaría SIEMPRE como objeto suelto, así que cada borrado de la montada
    crearía un null de aparcado en la raíz de la escena sin nada que
    aparcar."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    anchor = tag.GetObject()
    option_a = anchor._children[0]
    payload = variant_tag._read_payload_bc(tag)
    opt_a_bc = variant_tag._option_bc(payload, 0)
    opt_a_bc.SetLink(variant_tag._OPTION_LINK, _Reread(option_a))

    result = variant_tag.delete_option(tag, 0)

    assert result["ok"] is True
    assert result["evacuated"] == []
    park_names = [obj.GetName() for obj in doc.root
                  if obj.GetName() == variant_tag.VARIANT_PARK_DEFAULT_NAME]
    assert park_names == [], (
        "se creó un contenedor de aparcado sin nada que aparcar: la víctima "
        "se contó como objeto suelto"
    )
    assert anchor._children == [option_b]


def test_deleting_next_to_a_missing_option_entry_leaves_no_gap(variant_tag):
    """Una entrada que no existe se descarta y las siguientes se compactan.
    Saltarse su posición al reconstruir la lista deja un hueco dentro de
    ``0..count-2``: una fila vacía y no resuelta, permanente, que el artista
    no puede ni elegir ni borrar."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    payload = variant_tag._read_payload_bc(tag)
    options = payload.GetContainerInstance(variant_tag._PAYLOAD_OPTIONS)
    # Índice 1 SIN contenedor (payload a medias) y el 2 poblado.
    ghost = _insert(doc, FakeObject("Opción C", c4d, doc))
    option_c_bc = c4d.BaseContainer()
    option_c_bc.SetString(variant_tag._OPTION_NAME, "Opción C")
    option_c_bc.SetLink(variant_tag._OPTION_LINK, ghost)
    options.SetContainer(2, option_c_bc)
    payload.SetInt32(variant_tag._PAYLOAD_COUNT, 3)
    variant_tag._store_payload_bc(tag, payload)

    result = variant_tag.delete_option(tag, 2)

    assert result["ok"] is True
    state = variant_tag.read_state(tag)
    assert [opt["name"] for opt in state["options"]] == ["Opción A"], (
        "quedó una fila fantasma del hueco: la lista no se compactó"
    )
    assert state["orphans"] == 0
    assert state["options"][state["active"]]["name"] == "Opción A"


# --- El cableado de la UI de la Tarea 4 --------------------------------------

def test_each_option_row_carries_its_name_field_and_its_delete_button(variant_tag):
    """Sin declararlos, renombrar y borrar existen en el módulo y no en la
    pantalla: el artista no tiene nada que pulsar ni donde escribir."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)

    description, _ = _describe(variant_tag, tag)

    for index in (0, 1):
        base = variant_tag.ID_OPTION_BASE + index * variant_tag.ID_OPTION_STRIDE
        row_group = base + variant_tag._OPTION_ACTION_GROUP
        assert description.bc_of(row_group) is not None, "falta el grupo de fila"
        painted = description.row_ids_under(row_group)
        assert base in painted
        assert base + variant_tag._OPTION_ACTION_NAME in painted
        assert base + variant_tag._OPTION_ACTION_DELETE in painted
    # Y el botón de duplicar la activa, uno solo para todo el conjunto.
    assert description.bc_of(variant_tag.ID_VARIANTS_NEW) is not None


def test_pressing_the_delete_button_of_a_row_deletes_that_option(variant_tag):
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)
    row_id = (variant_tag.ID_OPTION_BASE + 1 * variant_tag.ID_OPTION_STRIDE
              + variant_tag._OPTION_ACTION_DELETE)

    _tag_data(variant_tag)._handle_command(tag, {"id": row_id})

    assert [opt["name"] for opt in variant_tag.read_state(tag)["options"]] == [
        "Opción A",
    ]


def test_pressing_the_duplicate_button_duplicates_the_active_option(variant_tag):
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)

    _tag_data(variant_tag)._handle_command(
        tag, {"id": variant_tag.ID_VARIANTS_NEW})

    assert [opt["name"] for opt in variant_tag.read_state(tag)["options"]] == [
        "Opción A", "Opción B",
    ]


def test_the_delete_button_is_off_when_there_is_nothing_left_to_delete(variant_tag):
    """``plan_delete`` rechaza borrar la última opción: el botón lo dice
    apagándose, en vez de aceptar el clic y no hacer nada."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    tag_data = _tag_data(variant_tag)
    delete_id = variant_tag.ID_OPTION_BASE + variant_tag._OPTION_ACTION_DELETE

    assert tag_data.GetDEnabling(tag, delete_id, None, 0, None) is False

    option_b = _insert(doc, FakeObject("Opción B", c4d, doc))
    _add_option(variant_tag, tag, c4d, "Opción B", option_b)
    assert tag_data.GetDEnabling(tag, delete_id, None, 0, None) is True


def test_the_row_name_field_reads_and_writes_the_option_name(variant_tag):
    """El campo es el dato PROPIO de la opción (no el nombre del tag, que es
    el del conjunto y no se toca aquí)."""
    import c4d

    doc, tag = _one_option_set(variant_tag, c4d)
    option_a = tag.GetObject()._children[0]
    tag_data = _tag_data(variant_tag)
    name_id = variant_tag.ID_OPTION_BASE + variant_tag._OPTION_ACTION_NAME
    desc_id = c4d.DescID(c4d.DescLevel(name_id))

    got = tag_data.GetDParameter(tag, desc_id, 0)
    assert got[0] is True and got[1] == "Opción A"

    assert tag_data.SetDParameter(tag, desc_id, "sin bend", 0)[0] is True

    assert variant_tag.read_state(tag)["options"][0]["name"] == "sin bend"
    assert option_a.GetName() == "sin bend"
    assert tag.GetName() == variant_tag.VARIANT_TAG_DEFAULT_NAME, (
        "el nombre del CONJUNTO es el del tag y no se toca al renombrar una "
        "opción (lección del Pin)"
    )


def test_pressing_delete_delivers_the_report_instead_of_dropping_it(
    variant_tag, monkeypatch,
):
    """Borrar se lleva contenido y puede cambiar lo que está montado: los dos
    canales de ``_report`` (barra de estado primero, consola siempre)."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    said = []
    monkeypatch.setattr(variant_tag, "safe_print", said.append)
    status = []
    monkeypatch.setattr(c4d.gui, "StatusSetText", status.append)

    row_id = (variant_tag.ID_OPTION_BASE + 0 * variant_tag.ID_OPTION_STRIDE
              + variant_tag._OPTION_ACTION_DELETE)
    _tag_data(variant_tag)._handle_command(tag, {"id": row_id})

    assert said and 'borrada "Opción A"' in said[0]
    assert status and 'borrada "Opción A"' in status[0]


# --- Tarea 5: renderizar todas las opciones ----------------------------------
#
# LO QUE ESTE ARNÉS NO PUEDE PROBAR, otra vez dicho aquí: que
# ``RenderDocument`` devuelva píxeles, que Redshift responda, que ``Save``
# escriba un PNG legible, ni cuántos pasos de deshacer deja el recorrido en
# C4D. Eso está MEDIDO en vivo (spike §4) o se mide en el Step 4 del brief.
# Lo que sí se fija aquí: QUÉ se renderiza, en qué ORDEN se monta cada
# opción, con qué NOMBRE sale cada archivo, cuántos brackets se abren, y que
# la opción original vuelva a su sitio pase lo que pase.

class FakeRenderData:
    """El render data del artista. Además de la ruta de salida y la
    resolución, trae los ajustes que un shot de producción tiene puestos y
    que este recorrido NO puede honrar: guardar a disco (beauty y multipass)
    y un rango de animación. Renderizar con este contenedor tal cual
    escribiría en las rutas de entrega reales."""

    def __init__(self, c4d, path="", xres=160, yres=120):
        self._path = path
        self._bc = c4d.BaseContainer()
        self._bc[c4d.RDATA_XRES] = xres
        self._bc[c4d.RDATA_YRES] = yres
        self._bc[c4d.RDATA_SAVEIMAGE] = True
        self._bc[c4d.RDATA_MULTIPASS_SAVEIMAGE] = True
        self._bc[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_ALLFRAMES
        self._c4d = c4d

    def __getitem__(self, key):
        if key == self._c4d.RDATA_PATH:
            return self._path
        return None

    def GetDataInstance(self):
        return self._bc


class _RenderHarness:
    """Sustituye ``RenderDocument`` + ``BaseBitmap`` por algo que anota QUÉ
    opción estaba montada en el momento del render y escribe ESE nombre en
    el archivo.

    El detalle importa: un recorrido que renderizara tres veces la misma
    opción y le pusiera tres nombres de archivo distintos pasaría cualquier
    comprobación que sólo cuente archivos. Aquí el contenido delata la
    opción que de verdad estaba en la escena."""

    def __init__(self, anchor, boom=()):
        self.anchor = anchor
        self.boom = set(boom)   # nombres de opción cuyo render revienta
        self.renders = []       # nombre montado en cada llamada, en orden
        self.saved = []         # (ruta, contenido)
        self.settings = []      # el contenedor con el que se renderizó

    def mounted_name(self):
        children = self.anchor._children
        return children[0].GetName() if children else ""

    def install(self, monkeypatch, c4d):
        harness = self

        class FakeBitmap:
            def __init__(self):
                self.payload = ""

            def Init(self, width, height, depth):
                return 1

            def Save(self, path, filter_id, data, flags):
                harness.saved.append((path, self.payload))
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.payload)
                return 1

        def render_document(doc, settings, bitmap, flags):
            name = harness.mounted_name()
            harness.renders.append(name)
            harness.settings.append(settings)
            if name in harness.boom:
                raise RuntimeError("el motor se cayó")
            bitmap.payload = name
            return c4d.RENDERRESULT_OK

        monkeypatch.setattr(c4d.bitmaps, "BaseBitmap", FakeBitmap,
                            raising=False)
        monkeypatch.setattr(c4d.documents, "RenderDocument", render_document,
                            raising=False)
        return self


def _renderable_set(variant_tag, c4d, monkeypatch, tmp_path, boom=()):
    """Tres opciones (A montada, B y C aparcadas), escena guardada y una
    carpeta de salida real en ``tmp_path``."""
    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    doc.doc_path = str(tmp_path)
    doc.doc_name = "SHOT_18.c4d"
    doc.render_data = FakeRenderData(c4d, path=str(tmp_path / "img" / "beauty"))
    harness = _RenderHarness(tag.GetObject(), boom=boom).install(monkeypatch, c4d)
    return doc, tag, harness


def test_render_all_options_on_an_unsaved_scene_renders_nothing(
    variant_tag, monkeypatch, tmp_path,
):
    """Sin documento guardado no hay dónde escribir. Renderizar igual a una
    carpeta cualquiera (la de trabajo del proceso, p.ej.) sería peor que no
    renderizar: el artista se lleva un "ok" y no encuentra las imágenes."""
    import c4d

    doc, tag, option_b, option_c = _three_option_set(variant_tag, c4d)
    harness = _RenderHarness(tag.GetObject()).install(monkeypatch, c4d)
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    result = variant_tag.render_all_options(tag)

    assert result["ok"] is False
    assert result["reason"] == "unsaved_scene"
    assert result["rendered"] == 0
    assert harness.renders == [], "no se renderiza nada sin sitio donde escribir"
    assert (doc.start_undo_count, doc.end_undo_count) == (0, 0)


def test_render_all_options_writes_one_image_per_option_named_after_it(
    variant_tag, monkeypatch, tmp_path,
):
    """Una imagen por opción, con el nombre de SU opción y el contenido de SU
    opción: el segundo es lo que distingue "montó las tres" de "renderizó
    tres veces la misma y les puso tres nombres".

    Las imágenes caen en la subcarpeta ``variants/``, no en la carpeta de
    salida del render a secas: esa es la que el artista entrega al cliente, y
    las opciones son material de decisión, no de entrega (cambio de producto
    tras verlo en vivo — con un preset guardando en ``.../ENTREGA/shot_beauty``
    los PNG de las opciones aparecían sueltos en ``.../ENTREGA/``)."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)

    result = variant_tag.render_all_options(tag)

    assert result["ok"] is True
    assert result["rendered"] == 3
    assert result["failed"] == []
    folder = tmp_path / "img" / "variants"
    assert result["folder"] == str(folder)
    # Recorridas en el orden de la LISTA, no en el de aparcado.
    assert harness.renders == ["Opción A", "Opción B", "Opción C"]
    # El conjunto entra en el nombre por su ANCLAJE ("cubo") y no por el
    # nombre de fábrica del tag: ningún conjunto nace nombrado, así que dos
    # conjuntos sin renombrar escribirían los mismos archivos (ver
    # ``test_two_untouched_sets_do_not_write_the_same_filenames``).
    assert tag.GetName() == variant_tag.VARIANT_TAG_DEFAULT_NAME
    assert tag.GetObject().GetName() == "Opciones · cubo"
    for name in ("Opción A", "Opción B", "Opción C"):
        image = folder / ("SHOT_18_Opciones · cubo_%s.png" % name)
        assert image.exists(), "falta la imagen de %s" % name
        assert image.read_text(encoding="utf-8") == name, (
            "la imagen de %s se renderizó con otra opción montada" % name)


def test_render_all_options_remounts_the_original_option_when_a_render_blows_up(
    variant_tag, monkeypatch, tmp_path,
):
    """La opción que estaba puesta queda puesta al terminar, pase lo que
    pase. Una herramienta de enseñar opciones que deja la escena en la última
    obliga al artista a arreglarla a mano cada vez."""
    import c4d

    doc, tag, harness = _renderable_set(
        variant_tag, c4d, monkeypatch, tmp_path, boom=("Opción C",))
    variant_tag.switch_to_option(tag, 1)   # el artista estaba en la B
    assert variant_tag.read_state(tag)["active"] == 1

    result = variant_tag.render_all_options(tag)

    assert result["rendered"] == 2
    assert result["failed"] == [("Opción C", "render_failed")]
    assert result["ok"] is True, "un fallo de una opción no aborta el resto"
    state = variant_tag.read_state(tag)
    assert state["active"] == 1
    anchor = tag.GetObject()
    assert [child.GetName() for child in anchor._children] == ["Opción B"]


def test_render_all_options_opens_exactly_one_undo_bracket(
    variant_tag, monkeypatch, tmp_path,
):
    """Los cambios del recorrido NO son gestos del artista: van todos en UN
    bloque. Con un bracket por opción, deshacer después de renderizar tres
    opciones serían cuatro Cmd+Z que no cambian nada visible."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    doc.start_undo_count = 0
    doc.end_undo_count = 0

    variant_tag.render_all_options(tag)

    assert (doc.start_undo_count, doc.end_undo_count) == (1, 1)


def test_render_all_options_keeps_going_past_an_option_it_cannot_find(
    variant_tag, monkeypatch, tmp_path,
):
    """Una opción cuyo enlace no resuelve sale en ``failed`` y el recorrido
    SIGUE: abortar ahí dejaría sin imagen a opciones perfectamente sanas por
    culpa de una rota."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    payload = variant_tag._read_payload_bc(tag)
    variant_tag._option_bc(payload, 1).SetLink(variant_tag._OPTION_LINK, None)

    result = variant_tag.render_all_options(tag)

    assert result["failed"] == [("Opción B", "lost_option")]
    assert result["rendered"] == 2
    assert harness.renders == ["Opción A", "Opción C"]


def test_pressing_render_all_delivers_the_report_instead_of_dropping_it(
    variant_tag, monkeypatch, tmp_path,
):
    """El botón está cableado y el resultado se dice: un recorrido que
    renderiza en silencio es indistinguible de uno que no hizo nada."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    said = []
    monkeypatch.setattr(variant_tag, "safe_print", said.append)

    _tag_data(variant_tag)._handle_command(
        tag, {"id": variant_tag.ID_VARIANTS_RENDER_ALL})

    assert harness.renders == ["Opción A", "Opción B", "Opción C"]
    assert said and "3 opciones renderizadas" in said[0]


def test_render_all_never_renders_with_the_artists_live_render_settings(
    variant_tag, monkeypatch, tmp_path,
):
    """RIESGO DE PRODUCCIÓN, no estilo: el contenedor vivo del shot lleva
    ``RDATA_SAVEIMAGE``/``RDATA_MULTIPASS_SAVEIMAGE`` y su rango de
    fotogramas. Renderizar con él escribiría N veces sobre las rutas de
    entrega REALES (pisando beauties y AOVs) y, en rango de animación,
    arrancaría una secuencia entera por opción."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    live = doc.render_data.GetDataInstance()

    variant_tag.render_all_options(tag)

    assert len(harness.settings) == 3
    for settings in harness.settings:
        assert settings is not live, (
            "se renderizó con el contenedor VIVO del artista, no con una copia")
        assert settings[c4d.RDATA_SAVEIMAGE] is False
        assert settings[c4d.RDATA_MULTIPASS_SAVEIMAGE] is False
        assert settings[c4d.RDATA_FRAMESEQUENCE] == \
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        # La copia sigue siendo LA del artista en todo lo demás: recortarla
        # de más renderizaría algo que no es lo que él configuró.
        assert settings[c4d.RDATA_XRES] == 160
    # Y el contenedor del artista queda exactamente como estaba.
    assert live[c4d.RDATA_SAVEIMAGE] is True
    assert live[c4d.RDATA_MULTIPASS_SAVEIMAGE] is True
    assert live[c4d.RDATA_FRAMESEQUENCE] == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES


def test_render_all_reports_what_it_pulled_out_of_the_anchor(
    variant_tag, monkeypatch, tmp_path,
):
    """El recorrido es el QUINTO gesto que vacía el anclaje y era el único
    que no lo contaba: la luz que el artista arrastró ahí acaba en un null
    oculto de la raíz, sale en la primera imagen y no en las otras dos, y el
    parte no decía nada."""
    import c4d
    from sentinel import variants

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    anchor = tag.GetObject()
    _insert(doc, FakeObject("luz_key", c4d, doc), anchor)

    result = variant_tag.render_all_options(tag)

    assert result["evacuated"] == ["luz_key"]
    assert "1 objeto suelto sacado del anclaje: luz_key" in \
        variants.render_report_text(result)


def test_render_all_says_when_it_left_the_scene_on_another_option(
    variant_tag, monkeypatch, tmp_path,
):
    """Con la opción de partida huérfana, el artista empieza con el anclaje
    vacío y termina con OTRA opción montada. Remontarla es imposible; callarlo
    no: el parte decía que A no se renderizó y no que la escena cambió."""
    import c4d
    from sentinel import variants

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    payload = variant_tag._read_payload_bc(tag)
    variant_tag._option_bc(payload, 0).SetLink(variant_tag._OPTION_LINK, None)

    result = variant_tag.render_all_options(tag)

    assert result["failed"] == [("Opción A", "lost_option")]
    assert result["restore_failed"] == "lost_option"
    assert variant_tag.read_state(tag)["active"] == 2, (
        "la escena SÍ quedó en otra opción — el parte tiene que decirlo")
    assert "la escena quedó en otra opción" in variants.render_report_text(result)


def test_render_all_does_not_blame_the_artist_for_an_unwritable_folder(
    variant_tag, monkeypatch, tmp_path,
):
    """``os.makedirs`` reventando es un share desmontado o de sólo lectura, no
    una escena sin guardar. El parte mandaba a guardar una escena que YA está
    guardada, así que el artista la guarda, vuelve a pulsar y lee lo mismo."""
    import c4d
    from sentinel import variants

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)

    def boom(path, exist_ok=False):
        raise OSError("Read-only file system")

    monkeypatch.setattr(variant_tag.os, "makedirs", boom)

    result = variant_tag.render_all_options(tag)

    assert result["reason"] == "folder_failed"
    assert harness.renders == []
    # La que reventó al crearse es la subcarpeta ``variants/``, no la carpeta
    # de salida del render a secas — es la que se intentó crear y falló.
    assert result["folder"] == str(tmp_path / "img" / "variants")
    text = variants.render_report_text(result)
    assert "no se pudo crear la carpeta de salida" in text
    assert "guarda la escena" not in text


def test_render_all_options_writes_into_a_variants_subfolder_not_the_delivery_folder(
    variant_tag, monkeypatch, tmp_path,
):
    """Cambio de producto pedido por el artista tras verlo en vivo: con un
    preset que guarda en ``.../ENTREGA/shot_beauty``, los PNG de las opciones
    aparecían sueltos en ``.../ENTREGA/`` — junto a los beauties que se
    entregan al cliente. Las opciones son material de decisión, no de
    entrega, así que van en su propia subcarpeta ``variants/``, y el parte
    apunta a donde de verdad acabaron, no a la carpeta de arriba."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)

    result = variant_tag.render_all_options(tag)

    delivery_folder = tmp_path / "img"
    variants_folder = delivery_folder / "variants"
    assert result["folder"] == str(variants_folder)
    assert sorted(p.name for p in delivery_folder.iterdir()) == ["variants"], (
        "ningún PNG de opción debe quedar suelto en la carpeta de entrega")
    written = sorted(p.name for p in variants_folder.iterdir())
    assert len(written) == 3


def test_two_options_that_want_the_same_file_are_not_both_counted(
    variant_tag, monkeypatch, tmp_path,
):
    """``render_image_stem`` mapea ``/`` a "_", así que "hero/v1" y "hero_v1"
    —distintos para ``dedupe_option_name``— piden el MISMO archivo. Antes
    salía ``rendered=3, failed=[]`` con 2 archivos en disco: el parte contaba
    renders, no entregas."""
    import c4d

    doc, tag, harness = _renderable_set(variant_tag, c4d, monkeypatch, tmp_path)
    payload = variant_tag._read_payload_bc(tag)
    variant_tag._option_bc(payload, 1).SetString(
        variant_tag._OPTION_NAME, "hero/v1")
    variant_tag._option_bc(payload, 2).SetString(
        variant_tag._OPTION_NAME, "hero_v1")

    result = variant_tag.render_all_options(tag)

    assert result["rendered"] == 2
    assert result["failed"] == [("hero_v1", "name_clash")]
    written = sorted(p.name for p in (tmp_path / "img" / "variants").iterdir())
    assert len(written) == result["rendered"], (
        "se cuenta lo entregado, no lo renderizado")


def test_two_untouched_sets_do_not_write_the_same_filenames(
    variant_tag, monkeypatch, tmp_path,
):
    """``create_variant_set`` nunca nombra el tag, así que los dos conjuntos
    del caso de uso del spec (el sofá y la lámpara) nacían con el MISMO nombre
    y con opciones "Opción A/B": el segundo recorrido pisaba las imágenes del
    primero y los dos partes decían lo mismo."""
    import c4d

    doc = _scene(c4d)
    doc.doc_path = str(tmp_path)
    doc.doc_name = "SHOT_18.c4d"
    doc.render_data = FakeRenderData(c4d, path=str(tmp_path / "img" / "beauty"))
    sofa = variant_tag.create_variant_set(
        doc, [_insert(doc, FakeObject("sofá", c4d, doc))])["tag"]
    lampara = variant_tag.create_variant_set(
        doc, [_insert(doc, FakeObject("lámpara", c4d, doc))])["tag"]
    assert sofa.GetName() == lampara.GetName() == \
        variant_tag.VARIANT_TAG_DEFAULT_NAME

    _RenderHarness(sofa.GetObject()).install(monkeypatch, c4d)
    variant_tag.render_all_options(sofa)
    _RenderHarness(lampara.GetObject()).install(monkeypatch, c4d)
    variant_tag.render_all_options(lampara)

    written = sorted(p.name for p in (tmp_path / "img" / "variants").iterdir())
    assert len(written) == 2, (
        "un archivo por conjunto: el segundo recorrido pisó al primero")
    assert any("sofá" in name for name in written)
    assert any("lámpara" in name for name in written)


# --- La carpeta de salida: los tokens se resuelven, no se esquivan -----------

def _folder_for(variant_tag, c4d, tmp_path, path):
    doc = _scene(c4d)
    doc.doc_path = str(tmp_path)
    doc.doc_name = "SHOT_18.c4d"
    doc.render_data = FakeRenderData(c4d, path=path)
    return doc


def test_render_output_folder_resolves_the_tokens_of_the_render_path(
    variant_tag, monkeypatch, tmp_path,
):
    """El caso con token es el NORMAL, no el raro: la QC #9 de este mismo
    plugin suspende cualquier preset cuya ruta no lleve ``$prj`` o ``$take``,
    así que toda escena que pasa la QC de Sentinel llega aquí con tokens. Sin
    resolverlos, la carpeta de render se ignoraba SIEMPRE y los PNG caían
    junto al ``.c4d``."""
    import c4d

    doc = _folder_for(variant_tag, c4d, tmp_path, "$prj/images/beauty")
    monkeypatch.setattr(
        c4d.modules.tokensystem, "StringConvertTokens",
        lambda path, rpd: path.replace("$prj", str(tmp_path / "proyecto")))

    assert variant_tag._render_output_folder(doc) == \
        os.path.join(str(tmp_path / "proyecto"), "images")


def test_render_output_folder_joins_a_relative_render_path_to_the_document(
    variant_tag, monkeypatch, tmp_path,
):
    """Una ruta de salida relativa es relativa AL DOCUMENTO. Devolverla tal
    cual la haría relativa al directorio de trabajo del proceso, que no es un
    sitio que el artista pueda encontrar."""
    import c4d

    doc = _folder_for(variant_tag, c4d, tmp_path, "images/beauty")

    assert variant_tag._render_output_folder(doc) == \
        os.path.join(str(tmp_path), "images")


def test_render_output_folder_gives_up_on_a_token_this_c4d_cannot_resolve(
    variant_tag, monkeypatch, tmp_path,
):
    """Último recurso, no primera opción: sólo si tras pasar por el sistema de
    tokens SIGUE habiendo un ``$`` se cae a la carpeta del documento. Crear
    una carpeta llamada literalmente ``$loquesea`` sería escribir donde el
    artista no pidió."""
    import c4d

    doc = _folder_for(variant_tag, c4d, tmp_path, "$noexiste/images/beauty")
    monkeypatch.setattr(c4d.modules.tokensystem, "StringConvertTokens",
                        lambda path, rpd: path)

    assert variant_tag._render_output_folder(doc) == str(tmp_path)


def test_the_render_all_button_is_painted(variant_tag):
    """Sin declararlo, renderizar existe en el módulo y no en la pantalla."""
    import c4d

    doc, tag, option_b = _scene_with_two_options(variant_tag, c4d)

    description, _ = _describe(variant_tag, tag)

    assert description.bc_of(variant_tag.ID_VARIANTS_RENDER_ALL) is not None
