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
    """Fake BaseMaterial exposing ``FindUniqueID(creator_id)`` with stable
    per-material bytes — NOT ``GetGUID``: real materials don't have it
    (BaseObject-only API; third recurrence of the mock-shape lesson). Pins
    ``_material_key`` to the FindUniqueID identity, not ``id()``."""

    def __init__(self, uid):
        self._uid = uid.encode("utf-8") if isinstance(uid, str) else bytes(uid)

    def FindUniqueID(self, creator_id):
        return self._uid


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
    mat = _FakeMaterial(uid="guid-A")
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


def test_clean_material_tags_dedupes_across_fresh_wrappers(sentinel_module, fake_doc_factory):
    """Regression (final-review C1): in real C4D every link read returns a
    FRESH BaseMaterial wrapper — two reads of the same material are distinct
    Python objects with distinct id(). The dupe key must still collide via
    FindUniqueID bytes, or removed_dupes is forever 0."""
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")

    class _FreshWrapperTag(_FakeTag):
        def __getitem__(self, key):
            if key == self._c4d.TEXTURETAG_MATERIAL:
                return _FakeMaterial(uid="guid-A")  # NEW wrapper per read
            return super().__getitem__(key)

    dup_a = _FreshWrapperTag(sentinel_module, restriction="SelA")
    dup_b = _FreshWrapperTag(sentinel_module, restriction="SelA")
    # sanity: the two wrapper objects really are distinct per read
    w1 = dup_a[sentinel_module.c4d.TEXTURETAG_MATERIAL]
    w2 = dup_a[sentinel_module.c4d.TEXTURETAG_MATERIAL]
    assert w1 is not w2
    obj = _FakeObj(5159, "cube", tags=[dup_a, dup_b])
    doc = fake_doc_factory(objects=[obj])
    result = scene_tools._clean_material_tags_core(doc)
    assert result == {"ok": True, "removed_broken": 0, "removed_dupes": 1}
    assert dup_a.removed and not dup_b.removed  # LAST wins


def test_clean_material_tags_different_material_guids_not_deduped(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    mat_a = _FakeMaterial(uid="guid-A")
    mat_b = _FakeMaterial(uid="guid-B")
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


class TestCleanupKeyframeOps:
    """panel/tools/delete_empty_nulls, clean_material_tags, keyframe_offset,
    keyframe_stagger — thin _tool()/forwarding adapters, mirrors
    TestMergeOps/TestParityOps above."""

    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/delete_empty_nulls",
                    "panel/tools/clean_material_tags",
                    "panel/tools/keyframe_offset",
                    "panel/tools/keyframe_stagger"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_op_delete_empty_nulls_routes_to_core(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        doc = _FakeDoc()
        captured = {}
        sentinel = {"ok": True, "removed": 2}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _fake_core(d):
            captured["doc"] = d
            return sentinel

        monkeypatch.setattr(scene_tools, "_delete_empty_nulls_core", _fake_core)
        result = panel_tools_ops._op_tool_delete_empty_nulls({})
        assert captured["doc"] is doc
        assert result is sentinel

    def test_op_clean_material_tags_routes_to_core(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        doc = _FakeDoc()
        captured = {}
        sentinel = {"ok": True, "removed_broken": 1, "removed_dupes": 0}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _fake_core(d):
            captured["doc"] = d
            return sentinel

        monkeypatch.setattr(scene_tools, "_clean_material_tags_core", _fake_core)
        result = panel_tools_ops._op_tool_clean_material_tags({})
        assert captured["doc"] is doc
        assert result is sentinel

    def test_op_delete_empty_nulls_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_tool_delete_empty_nulls({}) == {
            "ok": False, "error": "no_document"}

    def test_op_clean_material_tags_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_tool_clean_material_tags({}) == {
            "ok": False, "error": "no_document"}

    def test_op_keyframe_offset_forwards_frames(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel import keyframes
        self._forbid_dialog(monkeypatch)
        doc = _FakeDoc()
        captured = {}
        sentinel = {"ok": True, "objects": 2, "keys": 5, "frames": 7}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _fake_run_offset(d, frames):
            captured["doc"] = d
            captured["frames"] = frames
            return sentinel

        monkeypatch.setattr(keyframes, "run_offset", _fake_run_offset)
        result = panel_tools_ops._op_tool_keyframe_offset({"frames": 7})
        assert captured["doc"] is doc
        assert captured["frames"] == 7
        assert result is sentinel

    def test_op_keyframe_stagger_forwards_frames(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel import keyframes
        self._forbid_dialog(monkeypatch)
        doc = _FakeDoc()
        captured = {}
        sentinel = {"ok": True, "objects": 3, "keys": 9, "frames": -4}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _fake_run_stagger(d, frames):
            captured["doc"] = d
            captured["frames"] = frames
            return sentinel

        monkeypatch.setattr(keyframes, "run_stagger", _fake_run_stagger)
        result = panel_tools_ops._op_tool_keyframe_stagger({"frames": -4})
        assert captured["doc"] is doc
        assert captured["frames"] == -4
        assert result is sentinel

    def test_op_keyframe_offset_no_payload_forwards_none(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel import keyframes
        self._forbid_dialog(monkeypatch)
        doc = _FakeDoc()
        captured = {}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _fake_run_offset(d, frames):
            captured["frames"] = frames
            return {"ok": False, "error": "bad_frames"}

        monkeypatch.setattr(keyframes, "run_offset", _fake_run_offset)
        result = panel_tools_ops._op_tool_keyframe_offset(None)
        assert captured["frames"] is None
        assert result == {"ok": False, "error": "bad_frames"}

    def test_op_keyframe_ops_forbid_dialog(self, sentinel_module, monkeypatch):
        """Exercise all 4 new routes with no-document AND happy paths and
        assert no MessageDialog/QuestionDialog is reachable."""
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools
        from sentinel import keyframes

        def _boom_msg(*a, **k):
            raise AssertionError("no MessageDialog allowed in op path")

        def _boom_question(*a, **k):
            raise AssertionError("no QuestionDialog allowed in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom_msg)
        monkeypatch.setattr(scene_tools.c4d.gui, "QuestionDialog", _boom_question)

        # no-document path for all 4 routes
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_tool_delete_empty_nulls({}) == {
            "ok": False, "error": "no_document"}
        assert panel_tools_ops._op_tool_clean_material_tags({}) == {
            "ok": False, "error": "no_document"}
        assert panel_tools_ops._op_tool_keyframe_offset({"frames": 3}) == {
            "ok": False, "error": "no_document"}
        assert panel_tools_ops._op_tool_keyframe_stagger({"frames": 3}) == {
            "ok": False, "error": "no_document"}

        # happy path for all 4 routes, with the real active document
        doc = _FakeDoc()
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(scene_tools, "_delete_empty_nulls_core",
                            lambda d: {"ok": True, "removed": 1})
        monkeypatch.setattr(scene_tools, "_clean_material_tags_core",
                            lambda d: {"ok": True, "removed_broken": 0, "removed_dupes": 1})
        monkeypatch.setattr(keyframes, "run_offset",
                            lambda d, frames: {"ok": True, "objects": 1, "keys": 1, "frames": frames})
        monkeypatch.setattr(keyframes, "run_stagger",
                            lambda d, frames: {"ok": True, "objects": 1, "keys": 1, "frames": frames})

        assert panel_tools_ops._op_tool_delete_empty_nulls({})["ok"] is True
        assert panel_tools_ops._op_tool_clean_material_tags({})["ok"] is True
        assert panel_tools_ops._op_tool_keyframe_offset({"frames": 5})["ok"] is True
        assert panel_tools_ops._op_tool_keyframe_stagger({"frames": 5})["ok"] is True


class _FakeRenameNode:
    """Minimal object/material fake for rename ops: GetName/SetName/GetUp/
    GetTypeName, matching the mechanics rename_plan needs from ``_rename_items``."""

    def __init__(self, name, parent=None, type_name="Cube"):
        self._name = name
        self._parent = parent
        self._type_name = type_name
        self.set_name_calls = []

    def GetName(self):
        return self._name

    def SetName(self, name):
        self.set_name_calls.append(name)
        self._name = name

    def GetUp(self):
        return self._parent

    def GetTypeName(self):
        return self._type_name


class _FakeRenameDoc:
    def __init__(self, objects=None, materials=None):
        self._objects = list(objects or [])
        self._materials = list(materials or [])
        self.start_undo_count = 0
        self.end_undo_count = 0
        self.undo_operations = []

    def GetActiveObjects(self, flags):
        return list(self._objects)

    def GetActiveMaterials(self):
        return list(self._materials)

    def StartUndo(self):
        self.start_undo_count += 1

    def EndUndo(self):
        self.end_undo_count += 1

    def AddUndo(self, undo_type, target):
        self.undo_operations.append((undo_type, target))


class TestRenameOps:
    """panel/tools/rename_preview + rename_apply — server derives the plan
    from renaming.normalize_ops/ops_is_noop/rename_plan (Task 1) against the
    LIVE selection; the client can never supply rows that get applied."""

    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom_msg(*a, **k):
            raise AssertionError("no MessageDialog allowed in rename op path")

        def _boom_question(*a, **k):
            raise AssertionError("no QuestionDialog allowed in rename op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom_msg)
        monkeypatch.setattr(scene_tools.c4d.gui, "QuestionDialog", _boom_question)

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        assert "panel/tools/rename_preview" in panel_tools_ops.PANEL_TOOLS_OPS
        assert "panel/tools/rename_apply" in panel_tools_ops.PANEL_TOOLS_OPS

    # 1. preview objects: 3 fake selected objects + pattern "u_$n" -> rows
    #    u_001..u_003, truncated False, total 3; source "materials" reads
    #    GetActiveMaterials().
    def test_preview_objects_pattern(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        objects = [_FakeRenameNode("a"), _FakeRenameNode("b"), _FakeRenameNode("c")]
        doc = _FakeRenameDoc(objects=objects)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_preview(
            {"source": "objects", "ops": {"pattern": "u_$n"}})
        assert result["ok"] is True
        assert [r["new"] for r in result["rows"]] == ["u_001", "u_002", "u_003"]
        assert result["truncated"] is False
        assert result["total"] == 3

    def test_preview_materials_reads_active_materials(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        mats = [_FakeRenameNode("matA"), _FakeRenameNode("matB")]
        doc = _FakeRenameDoc(materials=mats)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_preview(
            {"source": "materials", "ops": {"pattern": "mat_$n"}})
        assert result["ok"] is True
        assert [r["new"] for r in result["rows"]] == ["mat_001", "mat_002"]
        assert result["total"] == 2

    # 2. preview with >500 selected (fake 501) -> 500 rows, truncated True,
    #    total 501.
    def test_preview_truncates_at_500(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        objects = [_FakeRenameNode(f"obj{i}") for i in range(501)]
        doc = _FakeRenameDoc(objects=objects)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_preview(
            {"source": "objects", "ops": {"pattern": "u_$n"}})
        assert result["ok"] is True
        assert len(result["rows"]) == 500
        assert result["truncated"] is True
        assert result["total"] == 501

    # 3. preview neutral ops -> nothing_to_do; empty selection -> no_selection;
    #    source "layers" -> bad_source.
    def test_preview_neutral_ops_nothing_to_do(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        doc = _FakeRenameDoc(objects=[_FakeRenameNode("a")])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_preview({"source": "objects", "ops": {}})
        assert result == {"ok": False, "error": "nothing_to_do"}

    def test_preview_empty_selection_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        doc = _FakeRenameDoc(objects=[])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_preview(
            {"source": "objects", "ops": {"pattern": "u_$n"}})
        assert result == {"ok": False, "error": "no_selection"}

    def test_preview_bad_source(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        doc = _FakeRenameDoc(objects=[_FakeRenameNode("a")])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_preview(
            {"source": "layers", "ops": {"pattern": "u_$n"}})
        assert result == {"ok": False, "error": "bad_source"}

    def test_preview_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        result = panel_tools_ops._op_rename_preview(
            {"source": "objects", "ops": {"pattern": "u_$n"}})
        assert result == {"ok": False, "error": "no_document"}

    # 4. apply: renames only rows where old != new via SetName, records ONE
    #    StartUndo/EndUndo pair and AddUndo per renamed node, returns renamed
    #    count + collisions count. Apply IGNORES any "rows" key smuggled into
    #    the payload.
    def test_apply_renames_and_records_one_undo_pair(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        a = _FakeRenameNode("a")
        b = _FakeRenameNode("b")
        doc = _FakeRenameDoc(objects=[a, b])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_apply(
            {"source": "objects", "ops": {"pattern": "u_$n"}})
        assert result["ok"] is True
        assert result["renamed"] == 2
        assert result["collisions"] == 0
        assert result["source"] == "objects"
        assert a.set_name_calls == ["u_001"]
        assert b.set_name_calls == ["u_002"]
        assert doc.start_undo_count == 1
        assert doc.end_undo_count == 1
        assert len(doc.undo_operations) == 2

    def test_apply_skips_unchanged_names(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        # prefix "" + suffix "" leaves unmatched names untouched; find/replace
        # that only matches one of the two objects.
        a = _FakeRenameNode("keep_me")
        b = _FakeRenameNode("change_me")
        doc = _FakeRenameDoc(objects=[a, b])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_apply(
            {"source": "objects", "ops": {"find": "change_me", "replace": "changed"}})
        assert result["ok"] is True
        assert result["renamed"] == 1
        assert a.set_name_calls == []
        assert b.set_name_calls == ["changed"]
        assert doc.undo_operations == [(panel_tools_ops.c4d.UNDOTYPE_CHANGE, b)]

    def test_apply_reports_collisions(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        a = _FakeRenameNode("a")
        b = _FakeRenameNode("b")
        doc = _FakeRenameDoc(objects=[a, b])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_apply(
            {"source": "objects", "ops": {"pattern": "same"}})
        assert result["ok"] is True
        assert result["renamed"] == 2
        assert result["collisions"] == 2

    def test_apply_ignores_smuggled_client_rows(self, sentinel_module, monkeypatch):
        """A poisoned payload with fake 'rows' must still rename from the
        REAL selection-derived plan, never the client-supplied rows."""
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        a = _FakeRenameNode("a")
        doc = _FakeRenameDoc(objects=[a])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        poisoned = {
            "source": "objects",
            "ops": {"pattern": "real_$n"},
            "rows": [{"old": "a", "new": "MALICIOUS_NAME", "collision": False}],
        }
        result = panel_tools_ops._op_rename_apply(poisoned)
        assert result["ok"] is True
        assert a.set_name_calls == ["real_001"]
        assert a._name == "real_001"

    def test_apply_neutral_ops_nothing_to_do(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        a = _FakeRenameNode("a")
        doc = _FakeRenameDoc(objects=[a])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_apply({"source": "objects", "ops": {}})
        assert result == {"ok": False, "error": "nothing_to_do"}
        assert a.set_name_calls == []
        assert doc.start_undo_count == 0

    def test_apply_bad_source(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        doc = _FakeRenameDoc(objects=[_FakeRenameNode("a")])
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        result = panel_tools_ops._op_rename_apply(
            {"source": "layers", "ops": {"pattern": "u_$n"}})
        assert result == {"ok": False, "error": "bad_source"}

    def test_apply_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        result = panel_tools_ops._op_rename_apply(
            {"source": "objects", "ops": {"pattern": "u_$n"}})
        assert result == {"ok": False, "error": "no_document"}

    # 5. _forbid_dialog on both routes (no-document AND happy paths) — covered
    #    inline above via self._forbid_dialog(monkeypatch) applied to every
    #    test in this class (both error and happy paths for preview+apply).


class _FakeMatwireMat:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class _FakeMatwireDoc:
    """Doc fake for matwire ops: Material Manager enumeration + undo
    bookkeeping (mirrors _FakeRenameDoc conventions)."""

    def __init__(self, material_names=None):
        self._materials = [_FakeMatwireMat(n) for n in (material_names or [])]
        self.start_undo_count = 0
        self.end_undo_count = 0
        self.undo_operations = []

    def GetMaterials(self):
        return list(self._materials)

    def AddUndo(self, undo_type, target):
        self.undo_operations.append((undo_type, target))

    def StartUndo(self):
        self.start_undo_count += 1

    def EndUndo(self):
        self.end_undo_count += 1


class TestMatwireOps:
    """panel/tools/matwire_preview + matwire_create — server derives the
    scan from the folder on EVERY call (v1.31 rename-ops pattern); the
    writer is always monkeypatched (fakes never build real graphs)."""

    def _setup(self, monkeypatch, doc, rs_available=True):
        from sentinel.ui import panel_tools_ops
        from sentinel import matwire_c4d

        def _boom(*a, **k):
            raise AssertionError("no dialog allowed in matwire op path")

        monkeypatch.setattr(panel_tools_ops.c4d.gui, "MessageDialog", _boom)
        monkeypatch.setattr(panel_tools_ops.c4d.gui, "QuestionDialog", _boom)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(matwire_c4d, "redshift_available",
                            lambda: rs_available)
        return panel_tools_ops

    def _folder(self, tmp_path, *names):
        for n in names:
            (tmp_path / n).write_bytes(b"x")
        return str(tmp_path)

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        assert "panel/tools/matwire_preview" in panel_tools_ops.PANEL_TOOLS_OPS
        assert "panel/tools/matwire_create" in panel_tools_ops.PANEL_TOOLS_OPS

    def test_preview_no_document(self, sentinel_module, monkeypatch):
        ops = self._setup(monkeypatch, None)
        assert ops._op_matwire_preview({"folder": "/x"}) == {
            "ok": False, "error": "no_document"}

    def test_preview_redshift_unavailable(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc(), rs_available=False)
        folder = self._folder(tmp_path, "a_col.png")
        assert ops._op_matwire_preview({"folder": folder}) == {
            "ok": False, "error": "redshift_unavailable"}

    def test_preview_bad_folder(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        missing = str(tmp_path / "nope")
        assert ops._op_matwire_preview({"folder": missing}) == {
            "ok": False, "error": "bad_folder"}
        assert ops._op_matwire_preview({}) == {
            "ok": False, "error": "bad_folder"}

    def test_preview_no_sets(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        folder = self._folder(tmp_path, "readme.txt", "notes.md")
        assert ops._op_matwire_preview({"folder": folder}) == {
            "ok": False, "error": "no_sets"}

    def test_preview_happy_shapes_and_dedupes(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc(material_names=["plaster"]))
        folder = self._folder(
            tmp_path, "plaster_BaseColor.jpg", "plaster_Roughness.jpg",
            "readme.txt")
        result = ops._op_matwire_preview({"folder": folder})
        assert result["ok"] is True
        assert len(result["sets"]) == 1
        s = result["sets"][0]
        assert s["name"] == "plaster"
        rows = {r["channel"]: r for r in s["channels"]}
        assert rows["basecolor"]["colorspace"] == "srgb"
        assert rows["roughness"]["colorspace"] == "raw"
        assert ["readme.txt", "bad_extension"] in result["ignored"]
        # default name deduped against the Material Manager
        assert result["names"] == ["plaster_02"]

    def test_preview_bare_pack_uses_folder_basename(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        pack = tmp_path / "RockCliff"
        pack.mkdir()
        (pack / "albedo.png").write_bytes(b"x")
        (pack / "roughness.png").write_bytes(b"x")
        result = ops._op_matwire_preview({"folder": str(pack)})
        assert result["ok"] is True
        assert result["sets"][0]["name"] == "RockCliff"

    def test_create_redshift_unavailable(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc(), rs_available=False)
        folder = self._folder(tmp_path, "a_col.png")
        assert ops._op_matwire_create({"folder": folder}) == {
            "ok": False, "error": "redshift_unavailable"}

    def test_create_happy_one_undo_pair(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._folder(
            tmp_path, "plaster_col.png", "plaster_rough.png", "wood_col.png")
        calls = []

        def _fake_create(d, f, tex_set, name):
            calls.append((d, f, tex_set["name"], name))
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder})
        assert result == {"ok": True, "created": 2,
                          "materials": ["plaster", "wood"], "errors": []}
        assert [(c[2], c[3]) for c in calls] == [
            ("plaster", "plaster"), ("wood", "wood")]
        assert all(c[0] is doc and c[1] == folder for c in calls)
        assert doc.start_undo_count == 1
        assert doc.end_undo_count == 1

    def test_create_exclude_and_names_rederived(self, sentinel_module, monkeypatch, tmp_path):
        """exclude drops a set; names maps set->custom; poisoned keys that
        don't exist server-side are ignored (server re-derives the scan)."""
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._folder(tmp_path, "plaster_col.png", "wood_col.png")
        calls = []

        def _fake_create(d, f, tex_set, name):
            calls.append((tex_set["name"], name))
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({
            "folder": folder,
            "exclude": ["wood"],
            "names": {"plaster": "Hero_Wall", "GHOST_SET": "Injected"},
        })
        assert result["ok"] is True
        assert result["created"] == 1
        assert result["materials"] == ["Hero_Wall"]
        assert calls == [("plaster", "Hero_Wall")]

    def test_create_dedupes_against_material_manager(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc(material_names=["plaster"])
        ops = self._setup(monkeypatch, doc)
        folder = self._folder(tmp_path, "plaster_col.png")
        calls = []

        def _fake_create(d, f, tex_set, name):
            calls.append(name)
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder})
        assert calls == ["plaster_02"]
        assert result["materials"] == ["plaster_02"]

    def test_create_all_excluded_no_sets(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._folder(tmp_path, "plaster_col.png")
        monkeypatch.setattr(
            matwire_c4d, "create_material_for_set",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
        assert ops._op_matwire_create({"folder": folder,
                                       "exclude": ["plaster"]}) == {
            "ok": False, "error": "no_sets"}
        assert doc.start_undo_count == 0

    def test_create_collects_per_set_errors_never_aborts(self, sentinel_module, monkeypatch, tmp_path):
        """One failing set (error dict) + one raising set never abort the
        batch; the whole run stays a single undo pair."""
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._folder(
            tmp_path, "brick_col.png", "plaster_col.png", "wood_col.png")

        def _fake_create(d, f, tex_set, name):
            if tex_set["name"] == "brick":
                # Mirror the real writer's v1.32.1 failure contract: the
                # graph is built OFF-document and insertion is the last
                # step, so a failing set touches the document not at all —
                # no NEWOBJ, and therefore no balancing DELETE either.
                return {"ok": False, "material_name": name, "error": "apply_failed"}
            if tex_set["name"] == "plaster":
                raise RuntimeError("boom")
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder})
        assert result["ok"] is True
        assert result["created"] == 1
        assert result["materials"] == ["wood"]
        assert ["brick", "apply_failed"] in result["errors"]
        assert any(row[0] == "plaster" for row in result["errors"])
        assert doc.start_undo_count == 1
        assert doc.end_undo_count == 1
        # A failed set leaves NO undo record at all (nothing to undo/redo).
        assert doc.undo_operations == []


class TestListFolderFiles:
    """_list_folder_files — the recursive lister shared by BOTH matwire ops
    (v1.32.1): relative paths with "/" separators, sorted, dot-dirs pruned,
    depth capped at 5 levels below the root, symlinks never followed."""

    def _lister(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        return panel_tools_ops._list_folder_files

    def test_recursive_relative_slash_sorted(self, sentinel_module, tmp_path):
        lister = self._lister(sentinel_module)
        (tmp_path / "b.png").write_bytes(b"x")
        sub = tmp_path / "4k"
        sub.mkdir()
        (sub / "a.png").write_bytes(b"x")
        assert lister(str(tmp_path)) == ["4k/a.png", "b.png"]

    def test_dot_dirs_pruned_dot_files_kept(self, sentinel_module, tmp_path):
        """Dot-DIRS (.git and friends) never contribute files; dot-FILES are
        kept for flat-folder parity with the v1.32 os.listdir behavior
        (.DS_Store falls out downstream as bad_extension, exactly as before)."""
        lister = self._lister(sentinel_module)
        (tmp_path / "a.png").write_bytes(b"x")
        (tmp_path / ".DS_Store").write_bytes(b"x")
        hidden = tmp_path / ".git"
        hidden.mkdir()
        (hidden / "sneaky.png").write_bytes(b"x")
        assert lister(str(tmp_path)) == [".DS_Store", "a.png"]

    def test_depth_capped_at_five_levels(self, sentinel_module, tmp_path):
        lister = self._lister(sentinel_module)
        deep = tmp_path
        for name in ("a", "b", "c", "d", "e"):
            deep = deep / name
        deep.mkdir(parents=True)
        (deep / "in.png").write_bytes(b"x")  # depth 5: included
        beyond = deep / "f"
        beyond.mkdir()
        (beyond / "out.png").write_bytes(b"x")  # depth 6: never reached
        assert lister(str(tmp_path)) == ["a/b/c/d/e/in.png"]

    def test_symlinked_dirs_not_followed(self, sentinel_module, tmp_path):
        import os as _os
        lister = self._lister(sentinel_module)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "far.png").write_bytes(b"x")
        root = tmp_path / "root"
        root.mkdir()
        (root / "near.png").write_bytes(b"x")
        _os.symlink(str(outside), str(root / "link"))
        assert lister(str(root)) == ["near.png"]


class TestMatwireOpsPolish:
    """v1.32.1 additions: recursive preview, ruleset suffixes with
    warnings, leftover assignment in the preview, and opt-in leftover
    import in create."""

    _setup = TestMatwireOps._setup

    def _pack(self, tmp_path, *names):
        pack = tmp_path / "pack"
        pack.mkdir()
        for n in names:
            path = pack / n
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        return str(pack)

    def test_preview_recurses_into_subfolders(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        folder = self._pack(tmp_path, "plaster_col.png", "maps/plaster_rough.png")
        result = ops._op_matwire_preview({"folder": folder})
        assert result["ok"] is True
        rows = {r["channel"]: r["file"] for r in result["sets"][0]["channels"]}
        assert rows == {"basecolor": "plaster_col.png",
                        "roughness": "maps/plaster_rough.png"}

    def test_preview_gains_leftovers_and_empty_warnings(self, sentinel_module, monkeypatch, tmp_path):
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        folder = self._pack(tmp_path, "plaster_col.png",
                            "plaster_custom_mask.png", "stray_data.png")
        result = ops._op_matwire_preview({"folder": folder})
        assert result["ok"] is True
        assert result["suffix_warnings"] == []
        assert result["leftovers"] == [
            {"file": "plaster_custom_mask.png", "set": "plaster"},
            {"file": "stray_data.png", "set": None},
        ]

    def test_preview_ruleset_suffixes_and_warnings(self, sentinel_module, monkeypatch, tmp_path):
        """A project matwire_suffixes ruleset extends the tables (custom
        `difuso` recognized as basecolor); rejected keys surface by name in
        suffix_warnings without dropping the valid ones."""
        import sentinel.rules_context as rules_context

        class _Ctx:
            params = {"matwire_suffixes": {"basecolor": ["difuso"],
                                           "bogus": ["x"]}}

        monkeypatch.setattr(rules_context, "active_rules_for_doc",
                            lambda doc: _Ctx())
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        folder = self._pack(tmp_path, "wall_difuso.png", "wall_rough.png")
        result = ops._op_matwire_preview({"folder": folder})
        assert result["ok"] is True
        rows = {r["channel"]: r["file"] for r in result["sets"][0]["channels"]}
        assert rows["basecolor"] == "wall_difuso.png"
        assert result["suffix_warnings"] == ["bogus"]

    def test_create_import_leftovers_routes_per_set_and_unassigned(self, sentinel_module, monkeypatch, tmp_path):
        """import_leftovers=True: per-set leftovers ride create_material_for_set
        via leftover_files; unassigned ones create the `<root>_leftovers`
        material from an EMPTY set — all inside the SAME undo pair."""
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._pack(tmp_path, "plaster_col.png",
                            "plaster_custom_mask.png", "stray_data.png")
        calls = []

        def _fake_create(d, f, tex_set, name, leftover_files=None):
            calls.append((tex_set["name"], name, dict(tex_set["channels"]),
                          leftover_files))
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder,
                                         "import_leftovers": True})
        assert result == {"ok": True, "created": 2,
                          "materials": ["plaster", "pack_leftovers"],
                          "errors": []}
        assert calls[0][0] == "plaster"
        assert calls[0][3] == ["plaster_custom_mask.png"]
        assert calls[1] == ("pack_leftovers", "pack_leftovers", {},
                            ["stray_data.png"])
        assert doc.start_undo_count == 1
        assert doc.end_undo_count == 1

    def test_create_leftovers_material_name_deduped(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc(material_names=["pack_leftovers"])
        ops = self._setup(monkeypatch, doc)
        folder = self._pack(tmp_path, "plaster_col.png", "stray_data.png")
        calls = []

        def _fake_create(d, f, tex_set, name, leftover_files=None):
            calls.append(name)
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder,
                                         "import_leftovers": True})
        assert calls == ["plaster", "pack_leftovers_02"]
        assert result["materials"] == ["plaster", "pack_leftovers_02"]

    def test_create_default_off_never_passes_leftovers(self, sentinel_module, monkeypatch, tmp_path):
        """Without import_leftovers the writer is called with the v1.32
        4-arg signature (a fake WITHOUT the kwarg proves no kwarg rides) and
        no leftovers material appears — the no-regression pin."""
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._pack(tmp_path, "plaster_col.png", "stray_data.png")
        calls = []

        def _fake_create(d, f, tex_set, name):  # no leftover_files kwarg
            calls.append((tex_set["name"], name))
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder})
        assert result == {"ok": True, "created": 1,
                          "materials": ["plaster"], "errors": []}
        assert calls == [("plaster", "plaster")]

    def test_create_excluded_set_leftovers_dropped(self, sentinel_module, monkeypatch, tmp_path):
        """A leftover assigned to an EXCLUDED set is dropped (its home
        material was excluded on purpose) — it never leaks into the
        `<root>_leftovers` material."""
        from sentinel import matwire_c4d
        doc = _FakeMatwireDoc()
        ops = self._setup(monkeypatch, doc)
        folder = self._pack(tmp_path, "plaster_col.png",
                            "plaster_custom_mask.png", "wood_col.png")
        calls = []

        def _fake_create(d, f, tex_set, name, leftover_files=None):
            calls.append((tex_set["name"], leftover_files))
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(matwire_c4d, "create_material_for_set", _fake_create)
        result = ops._op_matwire_create({"folder": folder,
                                         "exclude": ["plaster"],
                                         "import_leftovers": True})
        assert result["ok"] is True
        assert calls == [("wood", None)]
