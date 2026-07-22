# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/panel_render_ops.py — Fase 6.2 Task 1:
``panel/render`` (per-block isolated read) + preset/frame block mutations
(``set_preset``, ``reset_all``, ``force_vertical``, ``add_frame_tag``,
``select_frame_tag``).

Uses the fake-c4d harness (``sentinel_module`` fixture, tests/conftest.py):
``panel_render_ops.py`` does ``import c4d`` at module scope, same as
``panel_ops.py``, so it is imported lazily inside each test.
``documents.GetActiveDocument()`` is ``None`` in the harness, so these tests
pin the no-document contract + the op-table shape; the pure confirm gate and
per-block isolation are tested directly via a fake/monkeypatched ``doc``,
same convention as ``test_panel_ops.py``'s ``TestOverviewBlockIsolation``.
"""


class TestPanelRenderOpsTable:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        for op in ("panel/render", "panel/render/set_preset",
                   "panel/render/reset_all", "panel/render/force_vertical",
                   "panel/render/add_frame_tag", "panel/render/select_frame_tag"):
            assert op in panel_render_ops.PANEL_RENDER_OPS

    def test_panel_render_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        assert panel_render_ops.PANEL_RENDER_OPS["panel/render"]({}) == {"error": "no_document"}

    def test_set_preset_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_preset"]({"preset": "render"})
        assert response == {"ok": False, "error": "no_document"}

    def test_reset_all_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/reset_all"]({"confirm": True})
        assert response == {"ok": False, "error": "no_document"}

    def test_force_vertical_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/force_vertical"]({"confirm": True})
        assert response == {"ok": False, "error": "no_document"}

    def test_add_frame_tag_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/add_frame_tag"]({})
        assert response == {"ok": False, "error": "no_document"}

    def test_select_frame_tag_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/select_frame_tag"]({})
        assert response == {"ok": False, "error": "no_document"}


class TestConfirmGate:
    """Pure — the ``requires_confirm``/``confirm: true`` contract gate
    (mirrors ``web_ops._op_palette_run``'s check), reachable without a
    document, tested directly."""

    def test_missing_confirm_needs_confirm(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        assert panel_render_ops._needs_confirm({}) is True
        assert panel_render_ops._needs_confirm({"confirm": False}) is True
        assert panel_render_ops._needs_confirm({"confirm": "true"}) is True

    def test_confirm_true_satisfies_gate(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        assert panel_render_ops._needs_confirm({"confirm": True}) is False

    def test_reset_all_rejected_without_confirm_true(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        class _FakeDoc:
            pass

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: _FakeDoc())
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/reset_all"]({})
        assert response["ok"] is False
        assert response["error"] == "confirm_required"
        assert "confirm_label" in response

    def test_force_vertical_rejected_without_confirm_true(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        class _FakeDoc:
            pass

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: _FakeDoc())
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/force_vertical"]({})
        assert response["ok"] is False
        assert response["error"] == "confirm_required"
        assert "confirm_label" in response


class TestAddFrameTagCore:
    """``scene_tools._add_sentinel_frame_tag_core`` — the dialog-free core
    (Fase 6.2 Task 1 CRITICAL fix). Must return a status dict and NEVER call
    ``c4d.gui.MessageDialog`` — a headless HTTP caller running inside the
    ``MainThreadQueue`` drain could never dismiss a dialog it can't see,
    which would otherwise freeze all of C4D."""

    class _FakeCam:
        def __init__(self, type_id, tags=None, name="Camera"):
            self._type = type_id
            self._tags = tags or []
            self._name = name

        def GetType(self):
            return self._type

        def GetTags(self):
            return self._tags

        def GetName(self):
            return self._name

    class _FakeTag:
        def __init__(self, type_id):
            self._type = type_id

        def GetType(self):
            return self._type

    class _FakeDoc:
        def __init__(self, active_object=None):
            self._active_object = active_object
            self.active_tag = None

        def GetActiveObject(self):
            return self._active_object

        def GetActiveBaseDraw(self):
            return None

        def SetActiveTag(self, tag, mode):
            self.active_tag = tag

    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*args, **kwargs):
            raise AssertionError("MessageDialog must never be called from the core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_no_document_returns_status_without_dialog(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools

        self._forbid_dialog(monkeypatch)
        assert scene_tools._add_sentinel_frame_tag_core(None) == {"status": "no_document"}

    def test_no_camera_never_dialogs(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools

        self._forbid_dialog(monkeypatch)
        doc = self._FakeDoc(active_object=None)
        assert scene_tools._add_sentinel_frame_tag_core(doc) == {"status": "no_camera"}

    def test_already_tagged_never_dialogs(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        from sentinel.ui.frame_tag import OCAMERA, SENTINEL_FRAME_TAG_PLUGIN_ID

        self._forbid_dialog(monkeypatch)
        existing_tag = self._FakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        cam = self._FakeCam(OCAMERA, tags=[existing_tag])
        doc = self._FakeDoc(active_object=cam)

        result = scene_tools._add_sentinel_frame_tag_core(doc)
        assert result["status"] == "already_tagged"
        assert result["tag"] is existing_tag
        assert result["camera"] is cam
        assert doc.active_tag is existing_tag  # still selects it, just no dialog

    def test_import_failure_never_dialogs(self, sentinel_module, monkeypatch):
        import builtins

        from sentinel.ui import scene_tools

        self._forbid_dialog(monkeypatch)
        doc = self._FakeDoc(active_object=None)

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "sentinel.ui.frame_tag":
                raise ImportError("boom")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        result = scene_tools._add_sentinel_frame_tag_core(doc)
        assert result["status"] == "import_failure"
        assert "boom" in result["error"]


class TestAddFrameTagOpStatusMapping:
    """``panel/render/add_frame_tag`` must propagate the core's real
    status — never a hardcoded ``ok: True`` — so the SPA never toasts
    success for a click that created nothing."""

    class _FakeDoc:
        pass

    def test_ok_status_returns_ok_true_with_render(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        doc = self._FakeDoc()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(scene_tools, "_add_sentinel_frame_tag_core",
                             lambda d: {"status": "ok", "tag": object(), "camera": object()})
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {"probe": True})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "stamp123")

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/add_frame_tag"]({})
        assert response == {"ok": True, "stamp": "stamp123", "render": {"probe": True}}

    def test_no_camera_status_is_not_reported_as_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: self._FakeDoc())
        monkeypatch.setattr(scene_tools, "_add_sentinel_frame_tag_core",
                             lambda d: {"status": "no_camera"})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/add_frame_tag"]({})
        assert response == {"ok": False, "error": "no_camera"}

    def test_already_tagged_status_is_not_reported_as_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: self._FakeDoc())
        monkeypatch.setattr(scene_tools, "_add_sentinel_frame_tag_core",
                             lambda d: {"status": "already_tagged", "tag": object(), "camera": object()})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/add_frame_tag"]({})
        assert response == {"ok": False, "error": "already_tagged"}

    def test_import_failure_status_is_not_reported_as_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: self._FakeDoc())
        monkeypatch.setattr(scene_tools, "_add_sentinel_frame_tag_core",
                             lambda d: {"status": "import_failure", "error": "no module"})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/add_frame_tag"]({})
        assert response == {"ok": False, "error": "import_failure"}

    def test_create_failed_status_is_not_reported_as_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: self._FakeDoc())
        monkeypatch.setattr(scene_tools, "_add_sentinel_frame_tag_core",
                             lambda d: {"status": "create_failed", "camera": object()})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/add_frame_tag"]({})
        assert response == {"ok": False, "error": "create_failed"}


class TestPresetBlockReusesPanelRenderBlock:
    """``_panel_preset_block`` must CALL ``panel_ops._panel_render_block``
    rather than duplicate its ``GetActiveRenderData``/XRES/YRES/fps reads —
    verified by monkeypatching that function and checking its output flows
    through unchanged (plus ``preset_names`` added on top)."""

    def test_delegates_to_panel_render_block(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        monkeypatch.setattr(
            panel_render_ops, "_panel_render_block",
            lambda d: {"preset_name": "render", "fps": 25, "resolution": "1920x1080",
                       "multiformat": None})

        class _FakeRd:
            def __init__(self, name, nxt=None):
                self._name = name
                self._next = nxt

            def GetName(self):
                return self._name

            def GetNext(self):
                return self._next

        class _FakeDoc:
            def GetFirstRenderData(self):
                return _FakeRd("Render")

        result = panel_render_ops._panel_preset_block(_FakeDoc())
        assert result["preset_name"] == "render"
        assert result["fps"] == 25
        assert result["resolution"] == "1920x1080"
        assert "multiformat" not in result
        assert result["preset_names"] == ["render"]


class TestSelectFrameTagNoTag:
    def test_no_tag_in_scene_returns_no_tag_error(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        class _FakeDoc:
            pass

        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: _FakeDoc())
        monkeypatch.setattr(panel_render_ops, "_find_sentinel_frame_tag", lambda doc: None)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/select_frame_tag"]({})
        assert response == {"ok": False, "error": "no_tag"}


class TestBuildPanelRenderIsolation:
    """``build_panel_render`` must isolate each of the 5 card builders — one
    raising builder degrades to ``None`` for that key only, mirrors
    ``panel_ops.build_panel_overview``'s ``_guarded_block`` isolation."""

    def test_one_raising_block_becomes_null_others_survive(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = object()
        monkeypatch.setattr(panel_render_ops, "_panel_preset_block", lambda d: {"preset_name": "render"})
        monkeypatch.setattr(panel_render_ops, "_panel_frame_block", lambda d: {"has_tag": False})
        monkeypatch.setattr(panel_render_ops, "_panel_snapshots_block", lambda d: {"dir": "/x"})
        monkeypatch.setattr(panel_render_ops, "_panel_postrender_block", lambda d: {"available": False})

        def _boom(d):
            raise RuntimeError("aov scan exploded")

        monkeypatch.setattr(panel_render_ops, "_panel_aovs_block", _boom)

        result = panel_render_ops.build_panel_render(doc)

        assert result["aovs"] is None
        assert result["preset"] == {"preset_name": "render"}
        assert result["frame"] == {"has_tag": False}
        assert result["snapshots"] == {"dir": "/x"}
        assert result["postrender"] == {"available": False}

    def test_all_blocks_healthy_none_are_null(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = object()
        for name in ("_panel_preset_block", "_panel_frame_block", "_panel_aovs_block",
                     "_panel_snapshots_block", "_panel_postrender_block"):
            monkeypatch.setattr(panel_render_ops, name, lambda d, name=name: {"probe": name})

        result = panel_render_ops.build_panel_render(doc)

        assert None not in result.values()
        assert len(result) == 5


class TestFindSentinelFrameTag:
    """``_find_sentinel_frame_tag`` walks the object hierarchy looking for a
    tag of type ``SENTINEL_FRAME_TAG_PLUGIN_ID`` — pure enough to test with
    fake objects (no real c4d document needed)."""

    class _FakeTag:
        def __init__(self, type_id):
            self._type = type_id

        def GetType(self):
            return self._type

    class _FakeObj:
        def __init__(self, name, tags=None, down=None, next_=None):
            self._name = name
            self._tags = tags or []
            self._down = down
            self._next = next_

        def GetName(self):
            return self._name

        def GetTags(self):
            return self._tags

        def GetDown(self):
            return self._down

        def GetNext(self):
            return self._next

    def test_finds_tag_on_nested_object(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        from sentinel.ui.frame_tag import SENTINEL_FRAME_TAG_PLUGIN_ID

        tag = self._FakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        cam = self._FakeObj("Camera", tags=[tag])
        null_ = self._FakeObj("Null", down=cam)

        class _FakeDoc:
            def GetFirstObject(self):
                return null_

        result = panel_render_ops._find_sentinel_frame_tag(_FakeDoc())
        assert result is not None
        found_tag, found_host = result
        assert found_tag is tag
        assert found_host is cam

    def test_no_tag_anywhere_returns_none(self, sentinel_module):
        from sentinel.ui import panel_render_ops

        cam = self._FakeObj("Camera", tags=[])
        null_ = self._FakeObj("Null", down=cam)

        class _FakeDoc:
            def GetFirstObject(self):
                return null_

        assert panel_render_ops._find_sentinel_frame_tag(_FakeDoc()) is None

    def test_empty_scene_returns_none(self, sentinel_module):
        from sentinel.ui import panel_render_ops

        class _FakeDoc:
            def GetFirstObject(self):
                return None

        assert panel_render_ops._find_sentinel_frame_tag(_FakeDoc()) is None
