# -*- coding: utf-8 -*-
"""v1.36.2: capturar también por DESCRIPCIÓN, y un informe que no miente.

El bug, reproducido end-to-end por el artista y por el coordinador: un pin
sobre un setup de luces devolvía las POSICIONES y no las INTENSIDADES, y la
fila decía ``3 restaurados``. La causa no era de escritura sino de CAPTURA —
``_store_pin`` guardaba los parámetros con ``child_obj.GetData()``, y la luz
nativa de C4D guarda ``LIGHT_BRIGHTNESS``/``LIGHT_COLOR``/``LIGHT_TYPE``
FUERA de su ``BaseContainer``: sólo son accesibles por ``GetParameter``/
``SetParameter``. Nunca llegaron al pin.

**Por qué este arnés necesitaba un doble nuevo, y qué prueba de verdad**:
los ``FakeObject``/``FakeTrackObject`` de los otros dos suites de pin
modelan el contenedor y NADA más — ``GetData()`` es la única fuente de
parámetros que conocen. Contra ellos, "parámetro que existe en la
descripción pero no en el contenedor" no es un estado representable, así
que el test de regresión del bug no habría probado nada (novena vez en este
repo que el arnés habla un contrato distinto al de C4D). ``FakeDescribedObject``
de abajo separa las dos superficies a propósito: ``_data`` es el contenedor
y ``_desc`` los parámetros que SÓLO viven en la descripción, y un test elige
en cuál de las dos pone cada parámetro — que es exactamente la diferencia
medida entre una luz nativa (87 de 112 parámetros fuera del contenedor) y un
RS Light (107/107 dentro).

Lo que este arnés NO puede afirmar, y por eso sigue siendo verificación en
vivo: qué parámetros expone realmente la descripción de una luz de C4D
2026, qué devuelve ``SetParameter`` cuando el objeto rechaza un valor
(aquí se modela ``False``, que es lo que documenta la API), y si la lista
de ``DTYPE_*`` excluidos deja fuera algo que el artista sí querría de
vuelta.
"""

import importlib


# --- Fakes -----------------------------------------------------------------

class FakeDoc:
    def __init__(self):
        self.undo_ops = []

    def StartUndo(self):
        pass

    def EndUndo(self):
        pass

    def AddUndo(self, undo_type, target):
        self.undo_ops.append((undo_type, target))


class FakeDescription(list):
    """Modela ``c4d.Description`` para lo único que el barrido hace con
    ella: iterarla. La real produce ternas ``(bc, DescID, group_id)``; ésta
    también."""


class FakeDescribedObject:
    """Objeto con DOS superficies de parámetros, deliberadamente separadas:

    - ``_data`` — su ``BaseContainer`` propio, lo que ``GetData()`` devuelve
      y ``SetData()`` reemplaza. El camino principal del pin.
    - ``_desc`` — parámetros que su DESCRIPCIÓN expone y que el contenedor
      NO trae, leídos/escritos sólo por ``GetParameter``/``SetParameter``.
      La luz nativa de C4D en miniatura.

    ``rejected`` es el conjunto de ids cuyo ``SetParameter`` devuelve
    ``False`` (el objeto vivo rechaza el valor) — para probar que un
    parámetro que no vuelve se VE en la fila en vez de asumirse.
    ``unreadable`` es el conjunto de ids cuyo ``GetParameter`` lanza.
    """

    def __init__(self, name, c4d_module, container=None, described=None,
                 doc=None, obj_type=5102, rejected=None, unreadable=None,
                 children=None):
        self._name = name
        self._c4d = c4d_module
        self._type = obj_type
        self._doc = doc
        self._data = c4d_module.BaseContainer()
        for key, value in (container or {}).items():
            self._data[key] = value
        # {param_id: (dtype, value)}
        self._desc = dict(described or {})
        self._rejected = set(rejected or ())
        self._unreadable = set(unreadable or ())
        self._matrix = c4d_module.Matrix()
        self._tags = []
        self._children = list(children or [])
        for i, child in enumerate(self._children):
            child._next = self._children[i + 1] if i + 1 < len(self._children) else None
        self._next = None
        self.set_parameter_calls = []

    # -- identity / traversal
    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetType(self):
        return self._type

    def GetDown(self):
        return self._children[0] if self._children else None

    def GetNext(self):
        return self._next

    def GetDocument(self):
        return self._doc

    def GetTags(self):
        return list(self._tags)

    def MakeTag(self, plugin_id):
        # PREPENDS, como el MakeTag real (medido en vivo, ver el mismo
        # comentario en test_pin_tag.py).
        tag = FakeTag(self, plugin_id, self._c4d, self._doc)
        self._tags.insert(0, tag)
        return tag

    # -- container surface
    def GetData(self):
        return self._data

    def SetData(self, bc):
        self._data = bc

    def GetMl(self):
        return self._matrix

    def SetMl(self, m):
        self._matrix = m

    # -- description surface
    def GetDescription(self, flags):
        c4d = self._c4d
        out = FakeDescription()
        for param_id, (dtype, _value) in self._desc.items():
            desc_id = c4d.DescID(c4d.DescLevel(param_id, dtype, self._type))
            out.append((c4d.BaseContainer(), desc_id, None))
        return out

    def GetParameter(self, desc_id, flags):
        param_id = desc_id[0].id
        if param_id in self._unreadable:
            raise RuntimeError("no legible")
        entry = self._desc.get(param_id)
        return None if entry is None else entry[1]

    def SetParameter(self, desc_id, value, flags):
        param_id = desc_id[0].id
        self.set_parameter_calls.append((param_id, value))
        if param_id in self._rejected:
            return False
        dtype = self._desc.get(param_id, (0, None))[0]
        self._desc[param_id] = (dtype, value)
        return True

    # -- lectura de conveniencia para las aserciones
    def described(self, param_id):
        entry = self._desc.get(param_id)
        return None if entry is None else entry[1]


class FakeTag:
    def __init__(self, host, plugin_id, c4d_module, doc):
        self._host = host
        self._type = plugin_id
        self._name = "Sentinel Pin"
        self._bc = c4d_module.BaseContainer()
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

    def GetTags(self):
        return []


#: Los ids reales de la luz nativa que el bug perdía (ver el docstring del
#: módulo): brillo, color y tipo. Literales, no ``getattr`` contra el fake
#: permisivo, para que el test hable de los mismos números que C4D.
LIGHT_BRIGHTNESS = 90001
LIGHT_COLOR = 90000


def _pin_on(host, doc, c4d):
    tag = host.MakeTag(1)  # el tipo real da igual aquí: _store_pin no lo mira
    tag._type = importlib.import_module(
        "sentinel.ui.pin_tag").SENTINEL_PIN_TAG_PLUGIN_ID
    return tag


# --- Pieza 1: capturar también por descripción ------------------------------

def test_restore_brings_back_a_light_parameter_the_container_never_carried(
        sentinel_module):
    """EL CASO DEL ARTISTA, end-to-end: pin sobre un null con luces
    nativas, se cambia intensidad Y posición, se restaura — y la
    intensidad vuelve. Que este test no existiera es la razón de que el
    bug llegara a producción."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    fill = FakeDescribedObject(
        "fill", c4d, doc=doc,
        described={LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45)})
    key = FakeDescribedObject(
        "key", c4d, doc=doc,
        described={LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 1.0)})
    rig = FakeDescribedObject("rig", c4d, doc=doc, obj_type=c4d.Onull,
                              children=[fill, key])
    tag = _pin_on(rig, doc, c4d)

    assert pin_tag._store_pin(tag) is True

    # El artista destroza el setup: intensidades Y posiciones.
    fill._desc[LIGHT_BRIGHTNESS] = (c4d.DTYPE_REAL, 1.35)
    key._desc[LIGHT_BRIGHTNESS] = (c4d.DTYPE_REAL, 0.1)
    moved = c4d.Matrix()
    fill.SetMl(moved)

    report = pin_tag._restore(tag)

    assert fill.described(LIGHT_BRIGHTNESS) == 0.45, (
        "la intensidad de la luz nativa tiene que volver — vive fuera del "
        "BaseContainer que SetData restaura")
    assert key.described(LIGHT_BRIGHTNESS) == 1.0
    assert "3 restaurados" in report


def test_capture_skips_parameters_the_container_already_carries(sentinel_module):
    """El contenedor es el camino principal y el barrido sólo el
    complemento: un parámetro que ``GetData()`` YA trae no se captura dos
    veces. Es lo que mantiene el coste a cero en los objetos que restauran
    100% por SetData (RS Light 107/107, cámara nativa 95/95, generadores
    99/99 — auditoría)."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    obj = FakeDescribedObject(
        "rs_light", c4d,
        container={5000: 0.5},
        described={5000: (c4d.DTYPE_REAL, 0.5),
                   LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45)})

    params_bc, captured, skipped = pin_tag._capture_node_params(
        obj, obj.GetData())

    assert captured == 1, "sólo el parámetro que el contenedor NO trae"
    assert skipped == 0
    assert params_bc.GetContainerInstance(0).GetInt32(
        pin_tag._PARAM_ID) == LIGHT_BRIGHTNESS


def test_capture_excludes_buttons_links_and_the_transform(sentinel_module):
    """Ni acciones, ni enlaces a otros nodos, ni la transformación (ids
    903-927, que el pin ya restaura por matriz — escribirla por dos
    caminos es pedir una discrepancia)."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    obj = FakeDescribedObject(
        "cosas", c4d,
        described={
            2001: (c4d.DTYPE_BUTTON, 0),
            2002: (c4d.DTYPE_BASELISTLINK, object()),
            2003: (c4d.DTYPE_FILENAME, "/tmp/x.png"),
            2004: (c4d.DTYPE_SEPARATOR, 0),
            903: (c4d.DTYPE_VECTOR, c4d.Vector(1, 2, 3)),
            927: (c4d.DTYPE_REAL, 1.0),
            LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45),
        })

    params_bc, captured, skipped = pin_tag._capture_node_params(
        obj, obj.GetData())

    assert captured == 1, "sólo el parámetro de estado real"
    assert skipped == 0, (
        "lo excluido por política nunca se intentó, así que no es una "
        "pérdida y no puede contar como aviso")
    assert params_bc.GetContainerInstance(0).GetInt32(
        pin_tag._PARAM_ID) == LIGHT_BRIGHTNESS


def test_capture_counts_a_parameter_it_could_not_read(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    obj = FakeDescribedObject(
        "raro", c4d,
        described={LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45),
                   LIGHT_COLOR: (c4d.DTYPE_COLOR, c4d.Vector(1, 1, 1))},
        unreadable={LIGHT_COLOR})

    _params_bc, captured, skipped = pin_tag._capture_node_params(
        obj, obj.GetData())

    assert (captured, skipped) == (1, 1)


def test_a_pin_written_before_this_build_still_restores(sentinel_module):
    """El esquema NO sube: una entrada sin ``_ENTRY_PARAMS_COUNT`` se lee
    como "ningún parámetro extra" y el pin se aplica igual. Subirlo habría
    invalidado todos los pins ya guardados del artista para añadir datos
    que sólo complementan."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    entry = c4d.BaseContainer()
    entry.SetString(pin_tag._ENTRY_KEY, "")

    assert pin_tag._read_pinned_params(entry) == []


# --- Pieza 2: el informe deja de mentir -------------------------------------

def test_restore_reports_a_parameter_the_object_rejected(sentinel_module):
    """El agujero que la captura por descripción NO cierra: un parámetro
    que el objeto vivo rechaza al escribirlo tiene que VERSE en la fila, no
    asumirse restaurado."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    light = FakeDescribedObject(
        "fill", c4d, doc=doc,
        described={LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45),
                   LIGHT_COLOR: (c4d.DTYPE_COLOR, c4d.Vector(1, 1, 1))})
    tag = _pin_on(light, doc, c4d)
    assert pin_tag._store_pin(tag) is True

    light._rejected.add(LIGHT_COLOR)
    light._desc[LIGHT_BRIGHTNESS] = (c4d.DTYPE_REAL, 9.9)

    report = pin_tag._restore(tag)

    assert "1 parámetro sin restaurar" in report, report
    assert light.described(LIGHT_BRIGHTNESS) == 0.45, (
        "un parámetro rechazado no puede abortar la restauración del resto")


def test_restore_report_pluralizes_rejected_parameters(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")

    assert pin_tag._restore_report_text(1, 1, 0, 0, 0) == "1 restaurado"
    assert pin_tag._restore_report_text(1, 1, 0, 0, 1) == (
        "1 restaurado · 1 parámetro sin restaurar")
    assert pin_tag._restore_report_text(1, 1, 0, 0, 3) == (
        "1 restaurado · 3 parámetros sin restaurar")


def test_warning_row_declares_parameters_that_could_not_be_captured(
        sentinel_module):
    """Regla de la casa desde v1.35: los límites se muestran en la FILA del
    tag, no en la documentación. Un parámetro que el pin no pudo llevarse
    tiene que saberse ANTES de confiar en él."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    light = FakeDescribedObject(
        "fill", c4d, doc=doc,
        described={LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45),
                   LIGHT_COLOR: (c4d.DTYPE_COLOR, c4d.Vector(1, 1, 1))},
        unreadable={LIGHT_COLOR})
    tag = _pin_on(light, doc, c4d)
    assert pin_tag._store_pin(tag) is True

    assert "1 parámetro sin capturar" in pin_tag._pin_warning_text(tag)


def test_warning_row_is_silent_when_everything_was_captured(sentinel_module):
    """El contrapeso del test de arriba: una fila que avisa siempre no
    avisa de nada."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    light = FakeDescribedObject(
        "fill", c4d, doc=doc,
        described={LIGHT_BRIGHTNESS: (c4d.DTYPE_REAL, 0.45)})
    tag = _pin_on(light, doc, c4d)
    assert pin_tag._store_pin(tag) is True

    assert pin_tag._pin_warning_text(tag) == ""
