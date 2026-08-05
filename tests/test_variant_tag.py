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
  DOS caminos que mueven: crear el conjunto y cambiar de opción, y en los dos
  con **más de un** objeto en movimiento — con uno solo, un ``AddUndo`` fijado
  fuera del bucle pasa por bueno, que es el modo de fallo exacto que costó un
  bug real en matwire v1.32), y que cada objeto creado y el payload lleven el
  suyo. Si C4D realmente colapsa eso en un paso es cosa de C4D y se verifica
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
"""

import importlib

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
    row_ids = description.row_ids_under(variant_tag.ID_GROUP_OPTIONS)
    assert row_ids == [
        variant_tag.ID_OPTION_BASE,
        variant_tag.ID_OPTION_BASE + variant_tag.ID_OPTION_STRIDE,
    ]
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

    assert description.names_under(variant_tag.ID_GROUP_OPTIONS) == [
        "● Opción A", "○ Opción B",
    ]

    # Y tras cambiar, el ● se mueve con la opción montada.
    assert variant_tag.switch_to_option(tag, 1)["ok"] is True
    description, _ = _describe(variant_tag, tag)
    assert description.names_under(variant_tag.ID_GROUP_OPTIONS) == [
        "○ Opción A", "● Opción B",
    ]


def test_a_lost_option_says_so_in_its_own_row(variant_tag):
    import c4d

    doc = _scene(c4d)
    obj = _insert(doc, FakeObject("cubo", c4d, doc))
    tag = variant_tag.create_variant_set(doc, [obj])["tag"]
    _add_second_option(variant_tag, tag, c4d, doc, "Opción B", None)

    description, _ = _describe(variant_tag, tag)

    assert description.names_under(variant_tag.ID_GROUP_OPTIONS) == [
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
