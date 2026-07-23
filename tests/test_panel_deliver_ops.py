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
