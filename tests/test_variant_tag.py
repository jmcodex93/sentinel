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
  abra exactamente un bracket ``StartUndo``/``EndUndo`` y que el ``AddUndo``
  de cada objeto movido se registre ANTES de moverlo — que es lo que el
  spike midió que hace falta. Si C4D realmente colapsa eso en un paso es
  cosa de C4D y se verifica en vivo (Step 8 del brief).
- **Que los ``BaseLink`` sobrevivan a guardar+cargar.** El fake guarda el
  objeto tal cual (ver ``BaseContainer.SetLink`` en conftest). Un enlace
  "perdido" se modela poniendo ``None``: eso prueba cómo REACCIONA el
  código a un enlace que no resuelve, nunca cuándo un enlace real deja de
  resolver.
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
