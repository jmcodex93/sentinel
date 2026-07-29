"""Tests for panel/tools ops (Fase 6.4). Uses the fake-c4d harness
(``sentinel_module`` fixture, tests/conftest.py) — panel_tools_ops.py does
``import c4d`` at module scope, same as panel_render_ops.py."""


class _FakeDoc:
    def __init__(self):
        self._events = 0


class TestMergeCore:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog allowed in a *_core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._merge_c4d_file_core(None, "nulls.c4d") == {
            "ok": False, "error": "no_document"}

    def test_file_not_found(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(scene_tools.os.path, "exists", lambda p: False)
        r = scene_tools._merge_c4d_file_core(_FakeDoc(), "cam_simple.c4d")
        assert r == {"ok": False, "error": "file_not_found", "filename": "cam_simple.c4d"}

    def test_merge_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(scene_tools.os.path, "exists", lambda p: True)
        monkeypatch.setattr(scene_tools.c4d.documents, "MergeDocument", lambda *a: True)
        monkeypatch.setattr(scene_tools.c4d, "EventAdd", lambda *a, **k: None)
        r = scene_tools._merge_c4d_file_core(_FakeDoc(), "cam_w_shakel.c4d")
        assert r["ok"] is True
        assert r["camera_name"] == "W Shakel"  # filename → title-cased label

    def test_merge_failed(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(scene_tools.os.path, "exists", lambda p: True)
        monkeypatch.setattr(scene_tools.c4d.documents, "MergeDocument", lambda *a: None)
        r = scene_tools._merge_c4d_file_core(_FakeDoc(), "nulls.c4d")
        assert r == {"ok": False, "error": "merge_failed"}


class TestMergeOps:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/hierarchy", "panel/tools/vibrate_null",
                    "panel/tools/cam_simple", "panel/tools/cam_shakel"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_merged_into_reports_ops(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert "panel/tools/hierarchy" in reports_dialog._OPS

    def test_hierarchy_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_tool_hierarchy({}) == {
            "ok": False, "error": "no_document"}

    def test_cam_simple_passes_filename(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        captured = {}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: _FakeDoc())
        monkeypatch.setattr(scene_tools, "_merge_c4d_file_core",
                            lambda doc, fn: captured.setdefault("fn", fn) or {"ok": True, "camera_name": "Simple"})
        panel_tools_ops._op_tool_cam_simple({})
        assert captured["fn"] == "cam_simple.c4d"


class TestLayerFloorCores:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in a *_core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_h_to_layers_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._hierarchy_to_layers_core(None) == {
            "ok": False, "error": "no_document"}

    def test_solo_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._solo_layers_core(None) == {
            "ok": False, "error": "no_document"}

    def test_drop_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._drop_to_floor_core(None) == {
            "ok": False, "error": "no_document"}

    def test_drop_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        assert scene_tools._drop_to_floor_core(_Doc()) == {
            "ok": False, "error": "no_selection"}

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/h_to_layers", "panel/tools/solo",
                    "panel/tools/drop_to_floor"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_drop_op_maps_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: _Doc())
        assert panel_tools_ops._op_tool_drop_to_floor({}) == {
            "ok": False, "error": "no_selection"}


class TestAbcMarkCores:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in a *_core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_abc_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._apply_abc_retime_tag_core(None) == {
            "ok": False, "error": "no_document"}

    def test_abc_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        assert scene_tools._apply_abc_retime_tag_core(_Doc()) == {
            "ok": False, "error": "no_selection"}

    def test_mark_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._toggle_safe_area_mark_core(None) == {
            "ok": False, "error": "no_document"}

    def test_mark_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        assert scene_tools._toggle_safe_area_mark_core(_Doc()) == {
            "ok": False, "error": "no_selection"}

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/abc_retime", "panel/tools/mark_safe_area"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_mark_op_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: _Doc())
        assert panel_tools_ops._op_tool_mark_safe_area({})["error"] == "no_selection"

    def test_mark_core_success_marks_unmarked_object(self, sentinel_module, monkeypatch):
        # Regression test: _toggle_safe_area_mark_core used to have its
        # console-feedback line stranded as dead code after `return result`
        # in the wrapper (unreachable + referencing wrapper-local names that
        # don't exist there). Locks the success-path dict shape so a future
        # refactor can't silently drop it again.
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Obj:
            pass

        obj = _Obj()

        class _Doc:
            def GetActiveObjects(self, flags):
                return [obj]

            def StartUndo(self):
                pass

            def EndUndo(self):
                pass

        monkeypatch.setattr(scene_tools, "is_object_marked_safe_area",
                            lambda o: False)
        monkeypatch.setattr(scene_tools, "mark_object_safe_area",
                            lambda o, state, doc: True)
        monkeypatch.setattr(scene_tools, "unmark_object_safe_area",
                            lambda o, doc: True)
        monkeypatch.setattr(scene_tools.check_cache, "clear", lambda: None)
        monkeypatch.setattr(scene_tools.c4d, "EventAdd", lambda *a, **k: None)

        result = scene_tools._toggle_safe_area_mark_core(_Doc())
        assert result == {
            "ok": True,
            "verb": "mark",
            "marked": 1,
            "unmarked": 0,
            "failed": 0,
        }


class TestParityOps:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        assert "panel/tools/open_settings" in panel_tools_ops.PANEL_TOOLS_OPS
        assert "panel/tools/open_palette" in panel_tools_ops.PANEL_TOOLS_OPS
        assert "panel/open_external" in panel_tools_ops.PANEL_TOOLS_OPS

    def test_open_palette_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_open_palette({}) == {
            "ok": False, "error": "no_document"}

    def test_open_external_github(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        opened = {}
        monkeypatch.setattr(panel_tools_ops.webbrowser, "open",
                            lambda url: opened.setdefault("url", url))
        assert panel_tools_ops._op_open_external({"target": "github"}) == {"ok": True}
        assert opened["url"] == "https://github.com/jmcodex93/sentinel"

    def test_open_external_bug(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        opened = {}
        monkeypatch.setattr(panel_tools_ops.webbrowser, "open",
                            lambda url: opened.setdefault("url", url))
        panel_tools_ops._op_open_external({"target": "bug"})
        assert opened["url"] == "https://github.com/jmcodex93/sentinel/issues/new"

    def test_open_external_bad_target(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        monkeypatch.setattr(panel_tools_ops.webbrowser, "open",
                            lambda url: (_ for _ in ()).throw(AssertionError("must not open")))
        assert panel_tools_ops._op_open_external({"target": "nope"}) == {
            "ok": False, "error": "bad_target"}

    def test_open_settings_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_open_settings({}) == {
            "ok": False, "error": "no_document"}


class _FakeTag:
    """Minimal texture-tag fake keyed off the fake-c4d constants
    (``c4d.TEXTURETAG_MATERIAL`` / ``c4d.TEXTURETAG_RESTRICTION``, added in
    tests/conftest.py as distinct ints) — never strings, so ``__getitem__``
    honestly exercises the same DescID-style lookup production code does."""

    def __init__(self, sentinel_module, type_id=None, material=None, restriction=""):
        self._c4d = sentinel_module.c4d
        self._type = type_id if type_id is not None else self._c4d.Ttexture
        self._material = material
        self._restriction = restriction
        self.removed = False

    def GetType(self):
        return self._type

    def __getitem__(self, key):
        if key == self._c4d.TEXTURETAG_MATERIAL:
            return self._material
        if key == self._c4d.TEXTURETAG_RESTRICTION:
            return self._restriction
        return None

    def Remove(self):
        self.removed = True


class _FakeMaterial:
    """Fake BaseMaterial with GetGUID — pins ``_material_key`` to use the
    real GUID (not id()) when it's available, per the brief."""

    def __init__(self, guid):
        self._guid = guid

    def GetGUID(self):
        return self._guid


class _FakeObj:
    def __init__(self, type_id, name, children=None, tags=None):
        self._type = type_id
        self._name = name
        self._children = list(children or [])
        self._tags = list(tags or [])
        self.removed = False
        for c in self._children:
            c._parent = self

    def GetType(self):
        return self._type

    def GetName(self):
        return self._name

    def GetDown(self):
        return self._children[0] if self._children else None

    def GetNext(self):
        parent = getattr(self, "_parent", None)
        if parent is None:
            return None
        siblings = parent._children
        i = siblings.index(self)
        return siblings[i + 1] if i + 1 < len(siblings) else None

    def GetFirstTag(self):
        return self._tags[0] if self._tags else None

    def GetTags(self):
        return list(self._tags)

    def Remove(self):
        self.removed = True
        parent = getattr(self, "_parent", None)
        if parent is not None and self in parent._children:
            parent._children.remove(self)


class _FakeDocFactory:
    """Linked-list root wired from a flat objects list, wiring
    ``_parent``/siblings like ``_FakeObj`` expects. StartUndo/EndUndo/AddUndo
    are no-ops that record calls (mirrors ``_FakeDoc``/``BaseDocument``
    conventions used elsewhere in this file / conftest)."""

    def __init__(self, objects):
        self._objects = list(objects)
        self.start_undo_count = 0
        self.end_undo_count = 0
        self.undo_operations = []

    def GetFirstObject(self):
        return self._objects[0] if self._objects else None

    def StartUndo(self):
        self.start_undo_count += 1

    def EndUndo(self):
        self.end_undo_count += 1

    def AddUndo(self, undo_type, target):
        self.undo_operations.append((undo_type, target))


import pytest as _pytest  # noqa: E402


class _FakeRoot:
    """Synthetic parent for top-level objects so ``_FakeObj.GetNext()`` can
    walk siblings via ``parent._children`` — matches how a real C4D
    hierarchy's top level are siblings under an implicit document root."""

    def __init__(self, children):
        self._children = children


@_pytest.fixture
def fake_doc_factory():
    def _make(objects):
        # top-level objects are siblings of each other under a synthetic
        # root (so GetNext() can walk them), not parentless.
        root = _FakeRoot(objects)
        for obj in objects:
            obj._parent = root
        return _FakeDocFactory(objects)
    return _make


def test_delete_empty_nulls_cascade_and_tag_guard(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    c4d = sentinel_module.c4d
    ONULL = c4d.Onull
    # tree: keeper(cube) ; empty_leaf(null) ; group(null){inner(null)} -> both fall (cascade)
    # tagged(null with tag) -> saved ; parent_of_keeper(null){cube} -> saved (has child)
    empty_leaf = _FakeObj(ONULL, "empty_leaf")
    inner = _FakeObj(ONULL, "inner")
    group = _FakeObj(ONULL, "group", children=[inner])
    tagged = _FakeObj(ONULL, "tagged", tags=[_FakeTag(sentinel_module)])
    cube = _FakeObj(5159, "cube")
    parent = _FakeObj(ONULL, "parent", children=[cube])
    doc = fake_doc_factory(objects=[empty_leaf, group, tagged, parent])
    result = scene_tools._delete_empty_nulls_core(doc)
    assert result == {"ok": True, "removed": 3}  # empty_leaf, inner, group
    assert empty_leaf.removed and inner.removed and group.removed
    assert not tagged.removed and not parent.removed and not cube.removed


def test_delete_empty_nulls_none_found(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    cube = _FakeObj(5159, "cube")
    doc = fake_doc_factory(objects=[cube])
    assert scene_tools._delete_empty_nulls_core(doc) == {"ok": False, "error": "none_found"}


def test_delete_empty_nulls_no_document(sentinel_module):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    assert scene_tools._delete_empty_nulls_core(None) == {
        "ok": False, "error": "no_document"}


def test_clean_material_tags_broken_and_exact_dupes(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    mat = _FakeMaterial(guid="guid-A")
    broken = _FakeTag(sentinel_module, material=None)
    dup_a = _FakeTag(sentinel_module, material=mat, restriction="SelA")
    dup_b = _FakeTag(sentinel_module, material=mat, restriction="SelA")   # exact dupe -> dup_a removed, dup_b (LAST) kept
    different = _FakeTag(sentinel_module, material=mat, restriction="SelB")  # different restriction -> kept
    obj = _FakeObj(5159, "cube", tags=[broken, dup_a, dup_b, different])
    doc = fake_doc_factory(objects=[obj])
    result = scene_tools._clean_material_tags_core(doc)
    assert result == {"ok": True, "removed_broken": 1, "removed_dupes": 1}
    assert broken.removed and dup_a.removed
    assert not dup_b.removed and not different.removed


def test_clean_material_tags_different_material_guids_not_deduped(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    mat_a = _FakeMaterial(guid="guid-A")
    mat_b = _FakeMaterial(guid="guid-B")
    tag_a = _FakeTag(sentinel_module, material=mat_a, restriction="")
    tag_b = _FakeTag(sentinel_module, material=mat_b, restriction="")
    obj = _FakeObj(5159, "cube", tags=[tag_a, tag_b])
    doc = fake_doc_factory(objects=[obj])
    result = scene_tools._clean_material_tags_core(doc)
    assert result == {"ok": False, "error": "none_found"}
    assert not tag_a.removed and not tag_b.removed


def test_clean_material_tags_no_document(sentinel_module):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    assert scene_tools._clean_material_tags_core(None) == {
        "ok": False, "error": "no_document"}
