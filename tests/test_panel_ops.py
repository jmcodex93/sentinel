# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/panel_ops.py — the Panel SPA op layer
(Fase 6.0 Task 1: state stamp + overview + open_form).

Uses the fake-c4d harness (``sentinel_module`` fixture, tests/conftest.py):
``panel_ops.py`` does ``import c4d`` at module scope, same as ``hub_ops.py``/
``web_ops.py``, so it is imported lazily inside each test.
``documents.GetActiveDocument()`` is None in the harness, so these tests pin
the no-document contract + the op-table shape; the two payload-shaping
helpers that ARE pure (``_validate_form_page`` here,
``webbridge.top_qc_checks``) are tested directly without the harness.
"""


class TestPanelOpsTable:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_ops
        for op in ("panel/state_stamp", "panel/overview", "panel/open_form"):
            assert op in panel_ops.PANEL_OPS

    def test_state_stamp_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops.PANEL_OPS["panel/state_stamp"]({}) == {"error": "no_document"}

    def test_overview_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops.PANEL_OPS["panel/overview"]({}) == {"error": "no_document"}

    def test_open_form_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        response = panel_ops.PANEL_OPS["panel/open_form"]({"page": "form/save_version"})
        assert response == {"ok": False, "error": "no_document"}


class TestOverviewBlockIsolation:
    """``build_panel_overview`` (panel_ops.py) must isolate each of the 5
    card builders: one raising builder degrades to ``None`` for that key
    only, the other 4 still populate normally — mirrors the per-field
    ``try/except`` isolation ``ui/panel.py`` ``_sync_ui_from_doc`` uses
    (~985-1013). Tested via monkeypatched builders + a sentinel ``doc``
    object rather than a real ``c4d.documents.BaseDocument`` (the harness
    has none) — the aggregation/isolation logic itself doesn't care what
    ``doc`` actually is, only that it's threaded through unchanged.
    """

    def test_one_raising_block_becomes_null_others_survive(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        doc = object()
        monkeypatch.setattr(panel_ops, "_panel_scene_block", lambda d: {"name": "ok"})
        monkeypatch.setattr(panel_ops, "_panel_assets_block", lambda d: {"count": 1})
        monkeypatch.setattr(panel_ops, "_panel_render_block", lambda d: {"fps": 25})
        monkeypatch.setattr(panel_ops, "_panel_deliver_block", lambda d: {"todos_pending": 0})

        def _boom(d):
            raise RuntimeError("assets scan exploded")

        monkeypatch.setattr(panel_ops, "_panel_qc_block", _boom)

        result = panel_ops.build_panel_overview(doc)

        assert result["qc"] is None
        assert result["scene"] == {"name": "ok"}
        assert result["assets"] == {"count": 1}
        assert result["render"] == {"fps": 25}
        assert result["deliver"] == {"todos_pending": 0}

    def test_all_blocks_healthy_none_are_null(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        doc = object()
        for name in ("_panel_scene_block", "_panel_qc_block", "_panel_assets_block",
                     "_panel_render_block", "_panel_deliver_block"):
            monkeypatch.setattr(panel_ops, name, lambda d, name=name: {"probe": name})

        result = panel_ops.build_panel_overview(doc)

        assert None not in result.values()
        assert len(result) == 5

    def test_op_panel_overview_survives_a_block_exception(self, sentinel_module, monkeypatch):
        """End-to-end through the op itself would need a real document
        (blocked doc-guard-first in the harness), so this exercises
        ``_op_panel_overview``'s own aggregation call by monkeypatching
        ``documents.GetActiveDocument`` to return a truthy sentinel and
        ``build_panel_overview`` to simulate one failed block — proving the
        op returns the aggregated dict rather than propagating."""
        from sentinel.ui import panel_ops

        monkeypatch.setattr(panel_ops.documents, "GetActiveDocument", lambda: object())
        monkeypatch.setattr(
            panel_ops, "build_panel_overview",
            lambda d: {"scene": {}, "qc": None, "assets": {}, "render": {}, "deliver": {}})

        response = panel_ops.PANEL_OPS["panel/overview"]({})

        assert response["qc"] is None
        assert "error" not in response


class TestValidateFormPage:
    """Pure — reachable without the fake-c4d harness or a document, since
    ``panel/open_form`` itself is doc-guard-first (matching every sibling op
    in hub_ops.py/web_ops.py), which makes ``invalid_page`` unreachable
    through the op under the harness (GetActiveDocument() is always None).
    The validator is split out and tested directly instead.
    """

    def test_valid_pages_pass(self, sentinel_module):
        from sentinel.ui import panel_ops
        for page in ("form/save_version", "form/notes", "form/settings"):
            assert panel_ops._validate_form_page(page) is None

    def test_invalid_page_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_form_page("form/gate") == "invalid_page"
        assert panel_ops._validate_form_page("hub") == "invalid_page"
        assert panel_ops._validate_form_page("") == "invalid_page"
        assert panel_ops._validate_form_page(None) == "invalid_page"


class TestTopQcChecks:
    """Pure — no c4d import in webbridge.py, no harness needed."""

    def _check(self, check_id, label, count=None, new=None):
        return {"id": check_id, "label": label, "severity": "FAIL",
                "has_fix": False, "status": "fail" if (count or new) else "ok",
                "count": count, "new": new, "accepted": None, "details": []}

    def test_picks_worst_three_by_new_then_count(self):
        from sentinel import webbridge

        checks = [
            self._check("a", "A", count=1),
            self._check("b", "B", new=5),
            self._check("c", "C", count=0),
            self._check("d", "D", new=3),
            self._check("e", "E", count=2),
        ]
        top = webbridge.top_qc_checks(checks)
        assert top == [
            {"check_id": "b", "label": "B", "count": 5},
            {"check_id": "d", "label": "D", "count": 3},
            {"check_id": "e", "label": "E", "count": 2},
        ]

    def test_zero_and_none_counts_excluded(self):
        from sentinel import webbridge

        checks = [self._check("a", "A", count=0), self._check("b", "B")]
        assert webbridge.top_qc_checks(checks) == []

    def test_respects_custom_limit(self):
        from sentinel import webbridge

        checks = [self._check(str(i), str(i), count=i) for i in range(1, 6)]
        assert len(webbridge.top_qc_checks(checks, limit=2)) == 2
