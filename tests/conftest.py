import importlib.machinery
import importlib.util
import itertools
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = ROOT / "plugin" / "sentinel_panel.pyp"

# Make the sentinel package importable in every test without PYTHONPATH.
_PLUGIN_DIR = str(ROOT / "plugin")
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)


class _PermissiveModule(types.ModuleType):
    """Tiny attribute-permissive module for importing Sentinel outside C4D."""

    _counter = itertools.count(100000)

    def __getattr__(self, name):
        value = next(self._counter)
        setattr(self, name, value)
        return value


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def __repr__(self):
        return f"Vector({self.x!r}, {self.y!r}, {self.z!r})"


class Matrix:
    def __mul__(self, other):
        return other

    def __invert__(self):
        return self


class BaseTime:
    def __init__(self, frame=0, fps=25):
        self._frame = int(frame)
        self._fps = int(fps or 25)

    def GetFrame(self, fps):
        if not fps or fps == self._fps:
            return self._frame
        return int(round(self._frame * float(fps) / float(self._fps)))


class DescLevel:
    def __init__(self, level_id, dtype=0, creator=0):
        self.id = level_id
        self.dtype = dtype
        self.creator = creator


class DescID:
    def __init__(self, *levels):
        self._levels = levels

    def __getitem__(self, index):
        return self._levels[index]

    def __hash__(self):
        return hash(self._levels)

    def __eq__(self, other):
        return isinstance(other, DescID) and self._levels == other._levels

    def GetDepth(self):
        return len(self._levels)


class BaseContainer(dict):
    def GetFilename(self, key):
        return self.get(key, "")

    def GetLink(self, key, doc=None):
        return self.get(key)

    def SetLink(self, key, value):
        # Honest about what it is NOT: the real BaseContainer stores a
        # BaseLink that resolves against a document (and comes back None
        # when its target is gone or the document was reloaded). This fake
        # just holds the object, so "the link survived save/load" is NOT
        # something any test here can claim — only "the code asked for the
        # link and reacted to what came back" (a test can hand it None to
        # model an unresolvable link).
        self[key] = value

    # Typed accessors modeled after the real c4d.BaseContainer API — added
    # for the Sentinel Pin harness (nested containers, ints, strings,
    # bools, matrices), purely additive on top of the dict this already
    # is, so nothing that only used GetFilename/GetLink is affected.
    def GetInt32(self, key, default=0):
        return self.get(key, default)

    def SetInt32(self, key, value):
        self[key] = value

    def GetString(self, key, default=""):
        return self.get(key, default)

    def SetString(self, key, value):
        self[key] = value

    def GetBool(self, key, default=False):
        return self.get(key, default)

    def SetBool(self, key, value):
        self[key] = value

    def GetContainerInstance(self, key):
        return self.get(key)

    def SetContainer(self, key, value):
        self[key] = value

    def GetMatrix(self, key, default=None):
        return self.get(key, default)

    def SetMatrix(self, key, value):
        self[key] = value

    def GetClone(self, flags=0):
        """Shallow copy, like the real BaseContainer.GetClone(COPYFLAGS_*).
        Honest about what it is NOT: the real one deep-copies nested
        containers, this one shares them. What a test CAN claim with it is
        the thing it exists for — that code wrote into a copy and left the
        live container alone."""
        return BaseContainer(self)


class BaseDocument(dict):
    def __init__(self, render_datas=None):
        super().__init__()
        self.render_datas = list(render_datas or [])
        self.start_undo_count = 0
        self.end_undo_count = 0
        self.undo_operations = []

    def StartUndo(self):
        self.start_undo_count += 1

    def EndUndo(self):
        self.end_undo_count += 1

    def AddUndo(self, undo_type, target):
        self.undo_operations.append((undo_type, target))

    def GetFirstRenderData(self):
        return self.render_datas[0] if self.render_datas else None

    def GetActiveRenderData(self):
        return self.GetFirstRenderData()


class AliasTrans:
    """Modelo mínimo de ``c4d.AliasTrans`` — el traductor de enlaces que
    ``GetClone`` necesita para que los ``BaseLink`` INTERNOS de un subárbol
    copiado apunten a la copia y no al original.

    Aditivo: sin él ``c4d.AliasTrans`` se auto-vivificaba como un entero del
    ``_PermissiveModule`` y ``c4d.AliasTrans()`` reventaba, así que el camino
    correcto de duplicar no se podía ejercitar bajo test EN ABSOLUTO.

    Lo que modela: quien clona registra cada pareja (original, copia) y
    ``Translate`` reapunta, en las copias, los enlaces cuyo destino esté en
    ese registro. Es la MECÁNICA de C4D (medida en vivo: sin traductor el
    enlace del clon sigue apuntando al nodo del original, con el MISMO
    nombre; con traductor apunta al del clon).

    Lo que NO modela, y por eso sigue siendo un hecho a verificar en vivo:
    cuándo C4D considera un alias "traducible", qué pasa con enlaces a nodos
    de FUERA del subárbol (aquí se dejan intactos, que es lo medido, pero no
    lo prueba este fake), ni la interacción con el documento que recibe
    ``Init``.
    """

    def __init__(self):
        self._pairs = []
        self._initialized = False
        self.translated = False

    def Init(self, doc):
        self._initialized = True
        return True

    def register(self, original, clone):
        """Llamado por el clonador del arnés, no por C4D: en el real esto lo
        hace ``GetClone`` por dentro al recibir el ``AliasTrans``."""
        self._pairs.append((original, clone))

    def Translate(self, connect_oldnew=True):
        if not self._initialized:
            return False
        mapping = {id(original): clone for original, clone in self._pairs}
        for _original, clone in self._pairs:
            links = getattr(clone, "_links", None)
            if not links:
                continue
            for key, target in list(links.items()):
                mapped = mapping.get(id(target))
                if mapped is not None:
                    links[key] = mapped
        self.translated = True
        return True


class _BaseGui:
    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return True

        return _noop


class _BaseBitmap:
    def InitWith(self, path):
        return (1,)

    def GetBw(self):
        return 0

    def GetBh(self):
        return 0

    def GetBt(self):
        return 0


def _install_fake_c4d():
    for name in list(sys.modules):
        if name == "c4d" or name.startswith("c4d."):
            del sys.modules[name]

    c4d = _PermissiveModule("c4d")
    c4d.Vector = Vector
    c4d.Matrix = Matrix
    c4d.BaseTime = BaseTime
    c4d.DescLevel = DescLevel
    c4d.DescID = DescID
    c4d.BaseContainer = BaseContainer
    c4d.AliasTrans = AliasTrans
    c4d.GetCustomDatatypeDefault = lambda dtype: BaseContainer()
    c4d.EventAdd = lambda *args, **kwargs: None

    class PointObject:
        """Placeholder for c4d.PointObject — a real class (not a
        _PermissiveModule auto-int) so isinstance() checks against it
        (e.g. pin_tag._walk_object_tree's geometry test) don't raise
        TypeError. Fake geometry objects in a test subclass this."""

    c4d.PointObject = PointObject

    gui = _PermissiveModule("c4d.gui")
    gui.GeDialog = _BaseGui
    gui.GeUserArea = _BaseGui
    gui.MessageDialog = lambda *args, **kwargs: True
    gui.QuestionDialog = lambda *args, **kwargs: True

    plugins = _PermissiveModule("c4d.plugins")
    plugins.CommandData = object
    plugins.ObjectData = object
    plugins.RegisterCommandPlugin = lambda *args, **kwargs: True
    plugins.RegisterObjectPlugin = lambda *args, **kwargs: True

    documents = _PermissiveModule("c4d.documents")
    documents.BaseDocument = BaseDocument
    documents.GetActiveDocument = lambda: None

    storage = _PermissiveModule("c4d.storage")
    storage.GeGetC4DPath = lambda path_id: str(ROOT)
    storage.SaveDialog = lambda *args, **kwargs: None
    storage.LoadDialog = lambda *args, **kwargs: None

    bitmaps = _PermissiveModule("c4d.bitmaps")
    bitmaps.BaseBitmap = _BaseBitmap
    bitmaps.ShowBitmap = lambda *args, **kwargs: None

    # c4d.modules.tokensystem — a real submodule chain, not a
    # _PermissiveModule auto-int, so code under test actually REACHES
    # StringConvertTokens instead of tripping AttributeError on an int and
    # silently taking its own except branch. The default resolves nothing
    # (identity): a test that cares about token expansion monkeypatches it.
    modules = _PermissiveModule("c4d.modules")
    tokensystem = _PermissiveModule("c4d.modules.tokensystem")
    tokensystem.StringConvertTokens = lambda path, rpd: path
    modules.tokensystem = tokensystem

    c4d.modules = modules
    c4d.gui = gui
    c4d.plugins = plugins
    c4d.documents = documents
    c4d.storage = storage
    c4d.bitmaps = bitmaps

    # Stable constants referenced at import time or by pure helpers.
    constants = {
        "Olight": 5102,
        "Ocamera": 5103,
        "Onull": 5140,
        "Ocube": 5159,
        "Opolygon": 5100,
        "Mbase": 5702,
        "Ttexture": 5616,
        "Xbitmap": 5833,
        "TEXTURETAG_MATERIAL": 1010,
        "TEXTURETAG_RESTRICTION": 1011,
        "OBJECT_ON": 2,
        "OBJECT_OFF": 1,
        # Real C4D 2026 values (verified live 2026.301): Manual=0, Current=1, All=2.
        "RDATA_FRAMESEQUENCE_MANUAL": 0,
        "RDATA_FRAMESEQUENCE_CURRENTFRAME": 1,
        "RDATA_FRAMESEQUENCE_ALLFRAMES": 2,
        "DRAWPASS_OBJECT": 1,
        "DRAWRESULT_OK": 1,
        "DRAWRESULT_SKIP": 2,
        "OBJECT_GENERATOR": 1,
        "IMAGERESULT_OK": 1,
    }
    for key, value in constants.items():
        setattr(c4d, key, value)

    sys.modules["c4d"] = c4d
    sys.modules["c4d.modules"] = modules
    sys.modules["c4d.modules.tokensystem"] = tokensystem
    sys.modules["c4d.gui"] = gui
    sys.modules["c4d.plugins"] = plugins
    sys.modules["c4d.documents"] = documents
    sys.modules["c4d.storage"] = storage
    sys.modules["c4d.bitmaps"] = bitmaps


@pytest.fixture(scope="session")
def sentinel_module():
    _install_fake_c4d()
    module_name = "sentinel_panel_under_test"
    sys.modules.pop(module_name, None)
    loader = importlib.machinery.SourceFileLoader(module_name, str(PLUGIN_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module
