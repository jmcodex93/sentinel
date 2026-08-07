"""Contract tests for panel/tools/standard_* (v1.37).

The fakes model exactly what the ops touch: document path/name, fps,
min time, render-data names, top-level object list, GetClone, and the
module-level SaveDocument. What they do NOT model is written in their
docstrings (real QC checks — scoring is monkeypatched; C4D file I/O).

Uses the fake-c4d harness (``sentinel_module`` fixture, tests/conftest.py):
``standard_ops.py`` does ``import c4d`` at module scope (via ``panel_ops``),
same as every sibling ``ui/*_ops.py`` module, so — like
``test_panel_render_ops.py``/``test_panel_tools_ops.py`` — it is imported
lazily inside each test, after requesting ``sentinel_module``. A top-level
``from sentinel.ui import standard_ops`` would resolve ``import c4d``
against the on-disk ``plugin/c4d/`` asset folder (a namespace package,
since it has no ``__init__.py``) instead of the fake, because the fake is
only installed when the ``sentinel_module`` fixture runs."""
import json

import pytest


class _FakeObj:
    def __init__(self, name, children=0):
        self._name, self._children = name, children
        self.removed = False
        self._next = None
    def GetName(self):
        return self._name
    def GetNext(self):
        return self._next
    def GetDown(self):
        return object() if self._children else None
    def Remove(self):
        self.removed = True


class _FakeRd:
    def __init__(self, name):
        self._name = name
        self._next = None
    def GetName(self):
        return self._name
    def GetNext(self):
        return self._next


def _link(nodes):
    for a, b in zip(nodes, nodes[1:]):
        a._next = b
    return nodes[0] if nodes else None


class _FakeTime:
    def __init__(self, frame):
        self._frame = frame
    def GetFrame(self, fps):
        return self._frame


class _FakeDoc:
    def __init__(self, path="/prj/shots/SH010", name="SH010_v012.c4d",
                 fps=25, start=1001, presets=("previz", "render"),
                 objects=()):
        self._path, self._name, self._fps, self._start = path, name, fps, start
        self._first_rd = _link([_FakeRd(p) for p in presets])
        self._objects = list(objects)
        self._first_obj = _link(self._objects)
        self.clone = None
    def GetDocumentPath(self):
        return self._path
    def GetDocumentName(self):
        return self._name
    def GetFps(self):
        return self._fps
    def GetMinTime(self):
        return _FakeTime(self._start)
    def GetFirstRenderData(self):
        return self._first_rd
    def GetFirstObject(self):
        return self._first_obj
    def GetClone(self, flags):
        self.clone = _FakeDoc(self._path, self._name, self._fps, self._start,
                              [], [])
        self.clone._objects = [_FakeObj(o.GetName(),
                                        1 if o.GetDown() else 0)
                               for o in self._objects]
        self.clone._first_obj = _link(self.clone._objects)
        return self.clone


def _passing_qc(standard_ops, monkeypatch, failing=()):
    checks = [{"label": lab, "status": "fail"} for lab in failing]
    passed = 12 - len(failing)
    report = {"score": {"passed": passed, "total": 12}, "checks": checks}
    monkeypatch.setattr(standard_ops.panel_ops, "_run_qc_scoring",
                        lambda doc: (None, None, report))


class TestStandardOps:
    @pytest.fixture(autouse=True)
    def _forbid_dialog(self, sentinel_module, monkeypatch):
        from sentinel.ui import standard_ops
        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")
        monkeypatch.setattr(standard_ops.c4d.gui, "MessageDialog", _boom)
        monkeypatch.setattr(standard_ops.c4d.gui, "QuestionDialog", _boom)

    def _setup(self, standard_ops, monkeypatch, doc, saved=True):
        monkeypatch.setattr(standard_ops.c4d.documents, "GetActiveDocument",
                            lambda: doc)
        monkeypatch.setattr(standard_ops.c4d.documents, "SaveDocument",
                            lambda d, p, f, fmt: saved)
        monkeypatch.setattr(standard_ops.c4d.documents, "KillDocument",
                            lambda d: None)

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import standard_ops
        from sentinel.ui import reports_dialog
        assert "panel/tools/standard_preview" in standard_ops.STANDARD_OPS
        assert "panel/tools/standard_publish" in reports_dialog._OPS

    def test_preview_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import standard_ops
        monkeypatch.setattr(standard_ops.c4d.documents, "GetActiveDocument",
                            lambda: None)
        assert standard_ops._op_standard_preview({}) == {
            "ok": False, "error": "no_document"}

    def test_preview_unsaved_doc_refuses(self, sentinel_module, monkeypatch):
        from sentinel.ui import standard_ops
        doc = _FakeDoc(path="")
        self._setup(standard_ops, monkeypatch, doc)
        assert standard_ops._op_standard_preview({})["error"] == "unsaved"

    def test_preview_reports_scene_and_qc(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 2), _FakeObj("petals", 1)])
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        out = standard_ops._op_standard_preview({"folder": str(tmp_path)})
        assert out["ok"] and out["qc"]["pass"]
        assert out["scene"]["fps"] == 25
        assert out["scene"]["start_frame"] == 1001
        assert out["scene"]["presets"] == ["previz", "render"]
        assert out["scene"]["objects"] == [
            {"name": "Cameras", "index": 0, "children": True},
            {"name": "petals", "index": 1, "children": True},
        ]
        assert out["existing_rules"] is False and out["diff"] == []

    def test_preview_failing_qc_lists_labels(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        doc = _FakeDoc()
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch, failing=["Lights Organization"])
        out = standard_ops._op_standard_preview({"folder": str(tmp_path)})
        assert out["qc"]["pass"] is False
        assert out["qc"]["failing"] == ["Lights Organization"]

    def test_preview_diff_against_existing_rules(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        (tmp_path / "sentinel_rules.json").write_text(
            json.dumps({"standard_fps": 24}))
        doc = _FakeDoc()
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        out = standard_ops._op_standard_preview({"folder": str(tmp_path)})
        assert out["existing_rules"] is True
        assert any("fps" in l for l in out["diff"])

    def test_publish_refuses_failing_qc(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        doc = _FakeDoc()
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch, failing=["Default Names"])
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out == {"ok": False, "error": "qc_failing",
                       "failing": ["Default Names"]}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_writes_scene_and_rules(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 1), _FakeObj("petals", 1)])
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        monkeypatch.setattr(standard_ops.GlobalSettings, "load_artist_name",
                            staticmethod(lambda: "Javier"))
        out = standard_ops._op_standard_publish({
            "folder": str(tmp_path),
            "exclude": [["petals", 1]],
            "pattern": "shots/{shot}/{shot}_v001.c4d"})
        assert out["ok"]
        raw = json.loads((tmp_path / "sentinel_rules.json").read_text())
        assert raw["standard_fps"] == 25
        assert raw["template_scene"] == "sentinel_standard.c4d"
        assert raw["shot_pattern"] == "shots/{shot}/{shot}_v001.c4d"
        assert raw["published"]["by"] == "Javier"
        # the excluded branch was removed from the CLONE, not the live doc
        assert doc.clone._objects[1].removed is True
        assert doc._objects[1].removed is False

    def test_publish_preserves_manual_keys_on_republish(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        (tmp_path / "sentinel_rules.json").write_text(
            json.dumps({"gates_enabled": True, "standard_fps": 24}))
        doc = _FakeDoc()
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        # Not the property under test (manual-key survival) — stubbed only
        # because a module elsewhere in the suite (test_asset_hub_col_widths.py)
        # imports sentinel.common.settings at collection time, before the
        # fake c4d is installed, permanently binding that module's own
        # `c4d` name to the real plugin/c4d/ namespace package (no
        # `.storage`). GlobalSettings.load_artist_name() is the only path
        # in this file that reaches c4d.storage for real.
        monkeypatch.setattr(standard_ops.GlobalSettings, "load_artist_name",
                            staticmethod(lambda: ""))
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out["ok"]
        raw = json.loads((tmp_path / "sentinel_rules.json").read_text())
        assert raw["gates_enabled"] is True      # manual key survives
        assert raw["standard_fps"] == 25         # derived key wins

    def test_publish_stale_exclude_refuses(self, sentinel_module, monkeypatch, tmp_path):
        """Preview rows are never trusted: an exclude that no longer matches
        the live scene refuses instead of silently dropping."""
        from sentinel.ui import standard_ops
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 1)])
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        out = standard_ops._op_standard_publish({
            "folder": str(tmp_path), "exclude": [["gone", 5]]})
        assert out == {"ok": False, "error": "scene_changed"}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_in_bounds_name_mismatch_refuses(self, sentinel_module, monkeypatch, tmp_path):
        """Exclude guard checks both index bounds AND name identity: in-bounds
        name mismatch (stale preview row) refuses instead of silently dropping."""
        from sentinel.ui import standard_ops
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 1)])
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        out = standard_ops._op_standard_publish({
            "folder": str(tmp_path), "exclude": [["wrong", 0]]})
        assert out == {"ok": False, "error": "scene_changed"}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_save_failure_does_not_write_rules(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        doc = _FakeDoc()
        self._setup(standard_ops, monkeypatch, doc, saved=False)
        _passing_qc(standard_ops, monkeypatch)
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out == {"ok": False, "error": "save_failed"}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_unreadable_rules_refuses(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import standard_ops
        (tmp_path / "sentinel_rules.json").write_text("{not json")
        doc = _FakeDoc()
        self._setup(standard_ops, monkeypatch, doc)
        _passing_qc(standard_ops, monkeypatch)
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out == {"ok": False, "error": "rules_unreadable"}
        assert (tmp_path / "sentinel_rules.json").read_text() == "{not json"
