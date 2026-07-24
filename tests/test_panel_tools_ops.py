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
