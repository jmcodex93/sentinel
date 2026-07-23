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


class TestPanelFrameBlockFormatCount:
    """``_panel_frame_block`` must populate ``format_count`` with the number of
    enabled delivery formats in the Sentinel Frame tag (via
    ``_enabled_format_ids_from_params``), or None on failure."""

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

    def test_no_tag_returns_format_count_none(self, sentinel_module):
        from sentinel.ui import panel_render_ops

        class _FakeDoc:
            def GetFirstObject(self):
                return None

        result = panel_render_ops._panel_frame_block(_FakeDoc())
        assert result["has_tag"] is False
        assert result["camera_name"] is None
        assert result["format_count"] is None

    def test_tag_with_enabled_formats_returns_count(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui.frame_tag import SENTINEL_FRAME_TAG_PLUGIN_ID

        tag = self._FakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        cam = self._FakeObj("Camera", tags=[tag])
        null_ = self._FakeObj("Null", down=cam)

        class _FakeDoc:
            def GetFirstObject(self):
                return null_

        def _fake_enabled(node):
            return ["16x9", "9x16", "1x1"]  # 3 enabled formats

        monkeypatch.setattr(panel_render_ops, "_enabled_format_ids_from_params", _fake_enabled)

        result = panel_render_ops._panel_frame_block(_FakeDoc())
        assert result["has_tag"] is True
        assert result["camera_name"] == "Camera"
        assert result["format_count"] == 3

    def test_tag_with_zero_enabled_formats_returns_zero(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui.frame_tag import SENTINEL_FRAME_TAG_PLUGIN_ID

        tag = self._FakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        cam = self._FakeObj("Camera", tags=[tag])
        null_ = self._FakeObj("Null", down=cam)

        class _FakeDoc:
            def GetFirstObject(self):
                return null_

        def _fake_enabled(node):
            return []  # 0 enabled formats

        monkeypatch.setattr(panel_render_ops, "_enabled_format_ids_from_params", _fake_enabled)

        result = panel_render_ops._panel_frame_block(_FakeDoc())
        assert result["has_tag"] is True
        assert result["camera_name"] == "Camera"
        assert result["format_count"] == 0

    def test_tag_with_enabled_formats_failure_returns_none(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui.frame_tag import SENTINEL_FRAME_TAG_PLUGIN_ID

        tag = self._FakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        cam = self._FakeObj("Camera", tags=[tag])
        null_ = self._FakeObj("Null", down=cam)

        class _FakeDoc:
            def GetFirstObject(self):
                return null_

        def _fake_broken(node):
            raise RuntimeError("tag parsing failed")

        monkeypatch.setattr(panel_render_ops, "_enabled_format_ids_from_params", _fake_broken)

        result = panel_render_ops._panel_frame_block(_FakeDoc())
        assert result["has_tag"] is True
        assert result["camera_name"] == "Camera"
        assert result["format_count"] is None


class TestPanelRenderOpsTableTask2:
    def test_task2_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        for op in ("panel/render/aov_tier", "panel/render/set_light_groups",
                   "panel/render/set_multipart",
                   "panel/render/aov_list", "panel/render/toggle_watchfolder",
                   "panel/render/save_still", "panel/render/open_folder"):
            assert op in panel_render_ops.PANEL_RENDER_OPS


class TestAovTierNoDocument:
    def test_aov_tier_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_tier"](
            {"tier": "essentials"})
        assert response == {"ok": False, "error": "no_document"}

    def test_set_light_groups_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_light_groups"](
            {"enabled": True})
        assert response == {"ok": False, "error": "no_document"}

    def test_set_multipart_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_multipart"]({"enabled": True})
        assert response == {"ok": False, "error": "no_document"}

    def test_aov_list_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_list"]({})
        assert response == {"error": "no_document"}

    def test_toggle_watchfolder_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/toggle_watchfolder"]({})
        assert response == {"ok": False, "error": "no_document"}

    def test_save_still_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/save_still"]({})
        assert response == {"ok": False, "error": "no_document"}

    def test_open_folder_without_document(self, sentinel_module):
        from sentinel.ui import panel_render_ops
        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/open_folder"]({})
        assert response == {"ok": False, "error": "no_document"}


class _FakeDocBase:
    """Minimal fake doc — enough for ops that don't reach real GetActiveRenderData
    walks in this test class (aov_tier/set_multipart/toggle_watchfolder gate
    tests only need a doc object that is truthy)."""


class TestAovTierConfirmGateAndValidation:
    """Essentials/Production are additive coverage-level actions (each ADDS
    the missing AOVs up to that tier) — Fase 6.2 Task reorganization drops
    the confirm gate entirely for ``aov_tier``; only an invalid tier name is
    still rejected."""

    def test_invalid_tier_rejected(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: _FakeDocBase())

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_tier"]({"tier": "bogus"})
        assert response == {"ok": False, "error": "invalid_tier"}

    def test_light_groups_no_longer_a_valid_tier(self, sentinel_module, monkeypatch):
        """``light_groups`` was never an AOV tier — it's the independent
        toggle op now (``panel/render/set_light_groups``)."""
        from sentinel.ui import panel_render_ops
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: _FakeDocBase())

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_tier"]({"tier": "light_groups"})
        assert response == {"ok": False, "error": "invalid_tier"}

    def test_essentials_tier_runs_force_aov_tier_no_confirm_needed(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {"probe": True})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "stamp-1")

        calls = []

        def _fake_force(d, tier_list):
            calls.append(("force", d, tuple(tier_list)))
            return 3, None

        monkeypatch.setattr(panel_render_ops, "force_aov_tier", _fake_force)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_tier"]({"tier": "essentials"})

        assert response == {"ok": True, "stamp": "stamp-1", "render": {"probe": True}}
        assert calls[0][0] == "force"
        assert calls[0][1] is doc
        from sentinel.aovs import AOV_TIER_ESSENTIALS
        assert calls[0][2] == tuple(AOV_TIER_ESSENTIALS)

    def test_production_tier_runs_force_aov_tier_no_confirm_needed(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        calls = []
        monkeypatch.setattr(panel_render_ops, "force_aov_tier",
                             lambda d, tier_list: (calls.append(tuple(tier_list)), (5, None))[1])

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_tier"]({"tier": "production"})

        assert response["ok"] is True
        from sentinel.aovs import AOV_TIER_PRODUCTION
        assert calls[0] == tuple(AOV_TIER_PRODUCTION)

    def test_force_aov_tier_error_propagates(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "force_aov_tier",
                             lambda d, tier_list: (0, "Redshift module not available"))

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_tier"]({"tier": "essentials"})
        assert response == {"ok": False, "error": "Redshift module not available"}


class TestSetLightGroups:
    """``panel/render/set_light_groups`` — the independent on/off toggle
    (state), separated from the additive ``aov_tier`` coverage actions.
    Sets to the EXPLICIT ``enabled`` value, never a blind flip."""

    def test_redshift_unavailable(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", False)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_light_groups"]({"enabled": True})
        assert response == {"ok": False, "error": "redshift_unavailable"}

    def test_already_in_requested_state_is_a_noop_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: True)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        def _fail_if_called(d):
            raise AssertionError("core toggle must not run when already in the requested state")

        monkeypatch.setattr(scene_tools, "_toggle_light_groups_core", _fail_if_called)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_light_groups"]({"enabled": True})
        assert response["ok"] is True

    def test_flips_when_state_differs(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: False)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")
        monkeypatch.setattr(scene_tools, "_toggle_light_groups_core",
                             lambda d: {"status": "activated", "groups": ["Key"]})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_light_groups"]({"enabled": True})
        assert response["ok"] is True

    def test_no_groups_assigned_reported_as_explicit_failure(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: False)
        monkeypatch.setattr(scene_tools, "_toggle_light_groups_core",
                             lambda d: {"status": "no_groups_assigned", "ungrouped": ["Light1"]})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_light_groups"]({"enabled": True})
        assert response == {"ok": False, "error": "no_groups_assigned"}

    def test_other_failure_status_reported(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.ui import scene_tools

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: False)
        monkeypatch.setattr(scene_tools, "_toggle_light_groups_core",
                             lambda d: {"status": "no_beauty_aov"})

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_light_groups"]({"enabled": True})
        assert response == {"ok": False, "error": "no_beauty_aov"}


class TestSetMultipart:
    def test_sets_explicit_true(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        calls = []

        def _fake_set(d, enabled):
            calls.append(enabled)
            return True, None

        monkeypatch.setattr(panel_render_ops, "set_scene_multipart", _fake_set)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_multipart"]({"enabled": True})
        assert response["ok"] is True
        assert calls == [True]

    def test_sets_explicit_false(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        calls = []

        def _fake_set(d, enabled):
            calls.append(enabled)
            return True, None

        monkeypatch.setattr(panel_render_ops, "set_scene_multipart", _fake_set)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_multipart"]({"enabled": False})
        assert response["ok"] is True
        assert calls == [False]

    def test_missing_enabled_defaults_to_false(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        calls = []
        monkeypatch.setattr(panel_render_ops, "set_scene_multipart",
                             lambda d, enabled: (calls.append(enabled), (True, None))[1])

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_multipart"]({})
        assert response["ok"] is True
        assert calls == [False]

    def test_set_scene_multipart_error_propagates(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "set_scene_multipart",
                             lambda d, enabled: (False, "Redshift VideoPost not found"))

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/set_multipart"]({"enabled": True})
        assert response == {"ok": False, "error": "Redshift VideoPost not found"}


class TestAovListRedshiftUnavailable:
    def test_redshift_unavailable_degrades_cleanly(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        # Fake harness has no real `redshift` module importable, so
        # REDSHIFT_AVAILABLE is already False — assert the degrade path
        # explicitly rather than relying on import-time luck.
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", False)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_list"]({})
        assert response == {"error": "redshift_unavailable"}

    def test_available_reshapes_check_rs_aovs(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)

        def _fake_check(d, tier):
            from sentinel.aovs import AOV_TIER_ESSENTIALS, AOV_TIER_PRODUCTION
            if tier == AOV_TIER_ESSENTIALS:
                return {"available": True, "aovs": [{"name": "Beauty", "type": 0, "enabled": True}],
                        "missing": ["GI"], "tier": tier}
            return {"available": True, "aovs": [{"name": "Beauty", "type": 0, "enabled": True}],
                    "missing": ["GI", "Normals"], "tier": tier}

        monkeypatch.setattr(panel_render_ops, "check_rs_aovs", _fake_check)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: True)
        monkeypatch.setattr(panel_render_ops, "_scan_light_groups", lambda d: ({"Key": ["Light1"]}, []))
        monkeypatch.setattr(panel_render_ops.GlobalSettings, "get", lambda key, default=0: 0)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_list"]({})
        assert response["aovs"] == [{"name": "Beauty", "type": 0}]
        assert response["target"] == "Nuke"
        assert response["light_groups"] is True
        assert response["tier_coverage"]["essentials_missing"] == ["GI"]
        assert response["tier_coverage"]["production_missing"] == ["Normals"]

    def test_unnamed_aov_resolves_friendly_display_name(self, sentinel_module, monkeypatch):
        """A standard AOV the artist never manually renamed has an empty
        REDSHIFT_AOV_NAME — the fix under test resolves that back to the
        friendly Sentinel name via aov_type_name instead of surfacing the
        raw type int as the primary label."""
        from sentinel.ui import panel_render_ops
        from sentinel.aovs import _resolve_aov_type

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)

        beauty_type = _resolve_aov_type("Beauty")

        def _fake_check(d, tier):
            aovs = [{"name": "", "type": beauty_type, "enabled": True}]
            return {"available": True, "aovs": aovs, "missing": [], "tier": tier}

        monkeypatch.setattr(panel_render_ops, "check_rs_aovs", _fake_check)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: False)
        monkeypatch.setattr(panel_render_ops, "_scan_light_groups", lambda d: ({}, []))
        monkeypatch.setattr(panel_render_ops.GlobalSettings, "get", lambda key, default=0: 0)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_list"]({})
        assert response["aovs"] == [{"name": "Beauty", "type": beauty_type}]

    def test_unresolvable_type_falls_back_to_aov_hash_number(self, sentinel_module, monkeypatch):
        """A type int outside _AOV_DEFS entirely (a custom AOV) with no
        name still gets a usable, non-crashing label."""
        from sentinel.ui import panel_render_ops

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "REDSHIFT_AVAILABLE", True)

        def _fake_check(d, tier):
            aovs = [{"name": "", "type": 999999, "enabled": True}]
            return {"available": True, "aovs": aovs, "missing": [], "tier": tier}

        monkeypatch.setattr(panel_render_ops, "check_rs_aovs", _fake_check)
        monkeypatch.setattr(panel_render_ops, "_is_lg_active_on_beauty", lambda d: False)
        monkeypatch.setattr(panel_render_ops, "_scan_light_groups", lambda d: ({}, []))
        monkeypatch.setattr(panel_render_ops.GlobalSettings, "get", lambda key, default=0: 0)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/aov_list"]({})
        assert response["aovs"] == [{"name": "AOV #999999", "type": 999999}]


class TestToggleWatchfolder:
    def test_flips_setting_and_returns_new_state(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        state = {"watch": False}
        monkeypatch.setattr(GlobalSettings, "get_snapshot_watch", lambda: state["watch"])

        def _fake_set(enabled):
            state["watch"] = enabled
            return True

        monkeypatch.setattr(GlobalSettings, "set_snapshot_watch", _fake_set)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/toggle_watchfolder"]({})
        assert response["ok"] is True
        assert state["watch"] is True

        # Round-trip: calling again flips it back off.
        response2 = panel_render_ops.PANEL_RENDER_OPS["panel/render/toggle_watchfolder"]({})
        assert response2["ok"] is True
        assert state["watch"] is False


class TestSaveStillAndOpenFolderNeverDialog:
    """Fase 6.2 Task 2 self-review requirement: no op path may reach
    ``c4d.gui.MessageDialog`` — a modal in the ``MainThreadQueue`` drain
    freezes all of C4D since a headless HTTP caller can never dismiss a
    dialog it can't see. Same treatment as Task 1's frame-tag fix."""

    def test_save_still_no_artist_name_never_shows_dialog(self, sentinel_module, monkeypatch):
        import c4d
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(GlobalSettings, "load_artist_name", lambda: "")

        def _forbid(*args, **kwargs):
            raise AssertionError("MessageDialog must never be reachable from an op path")

        monkeypatch.setattr(c4d.gui, "MessageDialog", _forbid)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/save_still"]({})
        assert response["ok"] is False
        assert response["error"]

    def test_save_still_no_exr_never_shows_dialog(self, sentinel_module, monkeypatch):
        import c4d
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings
        from sentinel.ui import flows

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(GlobalSettings, "load_artist_name", lambda: "Motioneer")
        monkeypatch.setattr(flows, "snapshot_save_still_core",
                             lambda d, artist: {"ok": False, "stage": "exr", "error": "No EXR found"})

        def _forbid(*args, **kwargs):
            raise AssertionError("MessageDialog must never be reachable from an op path")

        monkeypatch.setattr(c4d.gui, "MessageDialog", _forbid)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/save_still"]({})
        assert response == {"ok": False, "error": "No EXR found"}

    def test_save_still_success_returns_render_payload(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings
        from sentinel.ui import flows

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(GlobalSettings, "load_artist_name", lambda: "Motioneer")
        monkeypatch.setattr(flows, "snapshot_save_still_core",
                             lambda d, artist: {"ok": True, "path": "/x/shot.png", "output_dir": "/x"})
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/save_still"]({})
        assert response == {"ok": True, "stamp": "s", "render": {}}

    def test_open_folder_missing_folder_never_shows_dialog(self, sentinel_module, monkeypatch):
        import c4d
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings
        from sentinel.ui import flows

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(GlobalSettings, "load_artist_name", lambda: "Motioneer")
        monkeypatch.setattr(flows, "snapshot_open_folder_core",
                             lambda d, artist: {"ok": False, "error": "folder_not_found", "path": "/x"})

        def _forbid(*args, **kwargs):
            raise AssertionError("MessageDialog must never be reachable from an op path")

        monkeypatch.setattr(c4d.gui, "MessageDialog", _forbid)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/open_folder"]({})
        assert response == {"ok": False, "error": "folder_not_found"}

    def test_open_folder_no_artist_name_never_shows_dialog(self, sentinel_module, monkeypatch):
        import c4d
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(GlobalSettings, "load_artist_name", lambda: "")

        def _forbid(*args, **kwargs):
            raise AssertionError("MessageDialog must never be reachable from an op path")

        monkeypatch.setattr(c4d.gui, "MessageDialog", _forbid)

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/open_folder"]({})
        assert response == {"ok": False, "error": "no_artist_name"}

    def test_open_folder_success_returns_render_payload(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_render_ops
        from sentinel.common.settings import GlobalSettings
        from sentinel.ui import flows

        doc = _FakeDocBase()
        monkeypatch.setattr(panel_render_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(GlobalSettings, "load_artist_name", lambda: "Motioneer")
        monkeypatch.setattr(flows, "snapshot_open_folder_core",
                             lambda d, artist: {"ok": True, "path": "/x"})
        monkeypatch.setattr(panel_render_ops, "build_panel_render", lambda d: {})
        monkeypatch.setattr(panel_render_ops, "_stamp_for", lambda d: "s")

        response = panel_render_ops.PANEL_RENDER_OPS["panel/render/open_folder"]({})
        assert response == {"ok": True, "stamp": "s", "render": {}}
