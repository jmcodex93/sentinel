"""Tests for panel/deliver ops (Fase 6.3). Uses the fake-c4d harness
(``sentinel_module`` fixture, tests/conftest.py) — panel_deliver_ops.py
does ``import c4d`` at module scope, same as panel_render_ops.py."""
import os


class _FakeDoc:
    def __init__(self, path="", name="shot_v003.c4d", changed=False):
        self._path = path
        self._name = name
        self._changed = changed
        self._dirty = 0

    def GetDocumentPath(self):
        return self._path

    def GetDocumentName(self):
        return self._name

    def GetChanged(self):
        return self._changed

    def GetDirty(self, flags):
        return self._dirty


class TestOpsRegistered:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_deliver_ops
        assert set(panel_deliver_ops.PANEL_DELIVER_OPS) == {
            "panel/deliver",
            "panel/deliver/open_version",
            "panel/deliver/open_collect",
        }

    def test_merged_into_reports_ops(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert "panel/deliver" in reports_dialog._OPS
        assert "panel/deliver/open_version" in reports_dialog._OPS


class TestPanelDeliverRead:
    def test_without_document_blocks_are_none_but_shaped(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        result = panel_deliver_ops._op_panel_deliver({})
        assert set(result) >= {"version", "notes", "deliver", "stamp"}

    def test_unsaved_document_marks_unsaved(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        doc = _FakeDoc(path="")
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        # No sidecars for an unsaved doc → engines return empty; block still shaped.
        result = panel_deliver_ops._op_panel_deliver({})
        assert result["version"] is None or result["version"]["unsaved"] is True

    def test_one_failing_block_does_not_blank_others(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        doc = _FakeDoc(path="/tmp/shot")
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _boom(_doc):
            raise RuntimeError("version block exploded")

        monkeypatch.setattr(panel_deliver_ops, "_panel_version_block", _boom)
        result = panel_deliver_ops._op_panel_deliver({})
        assert result["version"] is None          # guarded → None
        assert result["notes"] is not None        # unaffected block still built
        assert result["deliver"] is not None       # unaffected block still built


class TestDeliveryManifestAvailable:
    def test_no_path_false(self, sentinel_module):
        from sentinel.ui import panel_deliver_ops
        assert panel_deliver_ops.delivery_manifest_available(_FakeDoc(path="")) is False


class TestOpenVersion:
    def _forbid_dialog(self, monkeypatch, sentinel_module):
        from sentinel.ui import flows

        def _boom(*a, **k):
            raise AssertionError("no dialog allowed in open_version_core")

        monkeypatch.setattr(flows.c4d.gui, "MessageDialog", _boom)
        monkeypatch.setattr(flows.c4d.gui, "QuestionDialog", _boom)

    def test_bad_path(self, sentinel_module, monkeypatch):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        assert flows.open_version_core("   ") == {"ok": False, "error": "bad_path"}

    def test_file_not_found(self, sentinel_module, monkeypatch):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        assert flows.open_version_core("/no/such/shot_v001.c4d") == {
            "ok": False, "error": "file_not_found"}

    def test_already_active(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v002.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="shot_v002.c4d")
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        assert flows.open_version_core(str(f)) == {"ok": False, "error": "already_active"}

    def test_unsaved_changes_blocks_without_force(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v003.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="other.c4d", changed=True)
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        assert flows.open_version_core(str(f)) == {"ok": False, "error": "unsaved_changes"}

    def test_force_opens_despite_unsaved(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v004.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="other.c4d", changed=True)
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(flows.c4d.documents, "LoadFile", lambda p: True)
        assert flows.open_version_core(str(f), force=True) == {"ok": True, "opened": True}

    def test_load_failed(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v005.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="other.c4d", changed=False)
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(flows.c4d.documents, "LoadFile", lambda p: False)
        assert flows.open_version_core(str(f)) == {"ok": False, "error": "load_failed"}

    def test_op_maps_core_result(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        # path missing → bad_path from the core, surfaced by the op
        out = panel_deliver_ops._op_panel_deliver_open_version({"path": ""})
        assert out == {"ok": False, "error": "bad_path"}

    def test_op_forwards_force_true(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        from sentinel.ui import flows
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        captured = {}

        def _fake_core(path, force=False):
            captured["path"] = path
            captured["force"] = force
            return {"ok": False, "error": "unsaved_changes"}

        monkeypatch.setattr(flows, "open_version_core", _fake_core)
        panel_deliver_ops._op_panel_deliver_open_version(
            {"path": "/some/shot_v002.c4d", "force": True})
        assert captured == {"path": "/some/shot_v002.c4d", "force": True}

    def test_op_forwards_force_false_when_absent(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        from sentinel.ui import flows
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        captured = {}

        def _fake_core(path, force=False):
            captured["path"] = path
            captured["force"] = force
            return {"ok": False, "error": "unsaved_changes"}

        monkeypatch.setattr(flows, "open_version_core", _fake_core)
        panel_deliver_ops._op_panel_deliver_open_version({"path": "/some/shot_v002.c4d"})
        assert captured == {"path": "/some/shot_v002.c4d", "force": False}
