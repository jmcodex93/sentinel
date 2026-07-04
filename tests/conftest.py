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
    c4d.GetCustomDatatypeDefault = lambda dtype: BaseContainer()
    c4d.EventAdd = lambda *args, **kwargs: None

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
    documents.GetActiveDocument = lambda: None

    storage = _PermissiveModule("c4d.storage")
    storage.GeGetC4DPath = lambda path_id: str(ROOT)
    storage.SaveDialog = lambda *args, **kwargs: None
    storage.LoadDialog = lambda *args, **kwargs: None

    bitmaps = _PermissiveModule("c4d.bitmaps")
    bitmaps.BaseBitmap = _BaseBitmap
    bitmaps.ShowBitmap = lambda *args, **kwargs: None

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
        "OBJECT_ON": 2,
        "OBJECT_OFF": 1,
        "RDATA_FRAMESEQUENCE_CURRENTFRAME": 0,
        "RDATA_FRAMESEQUENCE_ALLFRAMES": 1,
        "RDATA_FRAMESEQUENCE_MANUAL": 2,
        "DRAWPASS_OBJECT": 1,
        "DRAWRESULT_OK": 1,
        "DRAWRESULT_SKIP": 2,
        "OBJECT_GENERATOR": 1,
        "IMAGERESULT_OK": 1,
    }
    for key, value in constants.items():
        setattr(c4d, key, value)

    sys.modules["c4d"] = c4d
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
