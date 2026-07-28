"""Tests for the panel/frame read op (Fase 6.6). Fake-c4d harness
(``sentinel_module`` fixture, tests/conftest.py) — panel_frame_ops.py does
``import c4d`` at module scope, same as panel_render_ops.py."""


class TestQc12FromReport:
    def test_no_cross_aspect_row_is_trivial_pass(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        assert panel_frame_ops._qc12_from_report({"checks": []}) == {"pass": True, "violations": 0}

    def test_disabled_is_trivial_pass(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        report = {"checks": [{"id": "cross_aspect", "status": "disabled", "count": None, "new": None}]}
        assert panel_frame_ops._qc12_from_report(report) == {"pass": True, "violations": 0}

    def test_legacy_count_violations(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        report = {"checks": [{"id": "cross_aspect", "status": "fail", "count": 3, "new": None}]}
        assert panel_frame_ops._qc12_from_report(report) == {"pass": False, "violations": 3}

    def test_baseline_new_zero_passes(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        report = {"checks": [{"id": "cross_aspect", "status": "pass", "count": 5, "new": 0}]}
        # baseline-aware: new=0 (all accepted) → pass, violations 0
        assert panel_frame_ops._qc12_from_report(report) == {"pass": True, "violations": 0}


class TestPanelFrameRead:
    def test_no_document_blocks_none(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: None)
        assert panel_frame_ops._op_panel_frame({}) == {"frame": None, "subjects": None, "qc12": None}

    def test_blocks_isolated(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops

        class _Doc:
            pass

        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: _Doc())
        monkeypatch.setattr(panel_frame_ops, "_frame_block", lambda d: {"has_tag": False, "camera_name": None, "format_count": None, "stale": False})
        monkeypatch.setattr(panel_frame_ops, "_subjects_block", lambda d: {"marked_count": 2})

        def _boom(_d):
            raise RuntimeError("qc12 exploded")

        monkeypatch.setattr(panel_frame_ops, "_qc12_block", _boom)
        result = panel_frame_ops._op_panel_frame({})
        assert result["frame"] is not None
        assert result["subjects"] == {"marked_count": 2}
        assert result["qc12"] is None  # guarded → None

    def test_subjects_block_counts_marked(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel import safe_areas
        monkeypatch.setattr(safe_areas, "find_marked_safe_area_objects", lambda doc: ["a", "b", "c"])
        assert panel_frame_ops._subjects_block(object()) == {"marked_count": 3}

    def test_frame_block_no_tag(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel.ui import panel_render_ops
        monkeypatch.setattr(panel_render_ops, "_panel_frame_block",
                            lambda doc: {"has_tag": False, "camera_name": None, "format_count": None})
        out = panel_frame_ops._frame_block(object())
        # Frame v2: `stale` is a constant False (auto-sync made it transient;
        # kept one release for older bundles) and `viewing` mirrors the tag's
        # Viewing state ("master" with no tag).
        assert out == {"has_tag": False, "camera_name": None, "format_count": None,
                       "stale": False, "viewing": "master",
                       "viewing_options": ["master"]}

    def test_qc12_block_reports_has_takes(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel import safe_areas
        # No delivery Takes → QC #12 is trivially a pass, but has_takes=False
        # lets the SPA say "not evaluated" instead of a misleading all-clear.
        monkeypatch.setattr(safe_areas, "find_active_multiformat_takes", lambda doc: [])
        monkeypatch.setattr(panel_frame_ops, "_run_qc_scoring",
                            lambda doc: (None, None, {"checks": []}))
        assert panel_frame_ops._qc12_block(object()) == {"pass": True, "violations": 0, "has_takes": False}

    def test_qc12_block_has_takes_true(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel import safe_areas
        monkeypatch.setattr(safe_areas, "find_active_multiformat_takes", lambda doc: [("9x16", object())])
        monkeypatch.setattr(panel_frame_ops, "_run_qc_scoring",
                            lambda doc: (None, None, {"checks": [{"id": "cross_aspect", "status": "fail", "count": 2, "new": None}]}))
        assert panel_frame_ops._qc12_block(object()) == {"pass": False, "violations": 2, "has_takes": True}


class TestRegistration:
    def test_ops_registered_and_merged(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        from sentinel.ui import reports_dialog
        assert "panel/frame" in panel_frame_ops.PANEL_FRAME_OPS
        assert "panel/frame" in reports_dialog._OPS


class TestSetViewing:
    """panel/frame/set_viewing — thin adapter over frame_tag.set_viewing
    (the same dialog-free core the AM Viewing cycle uses)."""

    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import panel_frame_ops

        def _boom(*args, **kwargs):
            raise AssertionError("dialogs must never be called from the op path")

        monkeypatch.setattr(panel_frame_ops.c4d.gui, "MessageDialog", _boom, raising=False)
        monkeypatch.setattr(panel_frame_ops.c4d.gui, "QuestionDialog", _boom, raising=False)

    def test_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: None)
        assert panel_frame_ops._op_panel_frame_set_viewing({"target": "9x16"}) == {
            "ok": False, "viewing": None, "error": "no_document"}

    def test_no_tag(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: object())
        monkeypatch.setattr(panel_frame_ops.panel_render_ops, "_find_sentinel_frame_tag", lambda doc: [])
        assert panel_frame_ops._op_panel_frame_set_viewing({"target": "master"}) == {
            "ok": False, "viewing": None, "error": "no_tag"}

    def test_delegates_to_core_with_payload_target(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel.ui import frame_tag
        self._forbid_dialog(monkeypatch)
        seen = {}

        def _fake_core(doc, tag, target):
            seen["target"] = target
            return {"ok": True, "viewing": target, "error": None}

        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: object())
        monkeypatch.setattr(panel_frame_ops.panel_render_ops, "_find_sentinel_frame_tag", lambda doc: ["tag"])
        monkeypatch.setattr(frame_tag, "set_viewing", _fake_core)
        result = panel_frame_ops._op_panel_frame_set_viewing({"target": "9x16"})
        assert result == {"ok": True, "viewing": "9x16", "error": None}
        assert seen["target"] == "9x16"

    def test_missing_target_defaults_to_master(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel.ui import frame_tag
        self._forbid_dialog(monkeypatch)
        seen = {}

        def _fake_core(doc, tag, target):
            seen["target"] = target
            return {"ok": True, "viewing": target, "error": None}

        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: object())
        monkeypatch.setattr(panel_frame_ops.panel_render_ops, "_find_sentinel_frame_tag", lambda doc: ["tag"])
        monkeypatch.setattr(frame_tag, "set_viewing", _fake_core)
        assert panel_frame_ops._op_panel_frame_set_viewing({})["ok"] is True
        assert seen["target"] == "master"


def _slice_tag(frame_tag):
    """Fake dict-tag (same idiom as tests/test_frame_tag.py's _base_tag):
    16x9 enabled whole, custom 9000x500 enabled and sliced 3x1."""
    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_CROP}
    for index in range(frame_tag.FORMAT_ROW_COUNT):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = index in (0, frame_tag.CUSTOM_FORMAT_INDEX)
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0
        tag[ids["slice_x"]] = 1
        tag[ids["slice_y"]] = 1
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    tag[cids["slice_x"]] = 3
    return tag


class TestFrameBlockSlices:
    """v1.29 (Task 8): the frame block carries ``slice_count`` and its
    ``viewing_options``/``viewing`` include slice ids (``fmt:sNN``)."""

    def _wire(self, monkeypatch, tag, base=None):
        from sentinel.ui import panel_frame_ops, panel_render_ops
        monkeypatch.setattr(
            panel_render_ops, "_panel_frame_block",
            lambda doc: dict(base or {"has_tag": True, "camera_name": "Hero",
                                      "format_count": 2, "slice_count": 3}))
        monkeypatch.setattr(panel_render_ops, "_find_sentinel_frame_tag",
                            lambda doc: (tag, object()))
        return panel_frame_ops

    def test_viewing_options_include_slices(self, sentinel_module, monkeypatch):
        from sentinel.ui import frame_tag
        tag = _slice_tag(frame_tag)
        panel_frame_ops = self._wire(monkeypatch, tag)
        out = panel_frame_ops._frame_block(object())
        assert out["slice_count"] == 3
        assert out["viewing_options"] == [
            "master", "16x9", "custom:s01", "custom:s02", "custom:s03"]
        assert out["viewing"] == "master"

    def test_viewing_reports_slice_take(self, sentinel_module, monkeypatch):
        from sentinel.ui import frame_tag
        tag = _slice_tag(frame_tag)
        panel_frame_ops = self._wire(monkeypatch, tag)
        monkeypatch.setattr(frame_tag, "_current_own_take_info",
                            lambda t, d: ("custom", "s02"))
        out = panel_frame_ops._frame_block(object())
        assert out["viewing"] == "custom:s02"

    def test_viewing_reports_whole_format_take(self, sentinel_module, monkeypatch):
        from sentinel.ui import frame_tag
        tag = _slice_tag(frame_tag)
        panel_frame_ops = self._wire(monkeypatch, tag)
        monkeypatch.setattr(frame_tag, "_current_own_take_info",
                            lambda t, d: ("16x9", None))
        out = panel_frame_ops._frame_block(object())
        assert out["viewing"] == "16x9"


class TestSetViewingCore:
    """frame_tag.set_viewing — target resolution against the format defs."""

    def test_unknown_format_rejected(self, sentinel_module, monkeypatch):
        from sentinel.ui import frame_tag
        result = frame_tag.set_viewing(object(), object(), "5x4")
        assert result == {"ok": False, "viewing": None, "error": "unknown_format"}
