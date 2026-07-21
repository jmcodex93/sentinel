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
