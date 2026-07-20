# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/hub_ops.py — the Hub SPA op layer.

Uses the fake-c4d harness (``sentinel_module`` fixture): hub_ops imports c4d
at module scope, so it is imported lazily inside each test (same pattern as
tests/test_web_ops.py). GetActiveDocument() is None in the harness, so these
tests pin the no-document contract + the op-table shape; the payload logic
itself is pure and tested in tests/test_webbridge.py.
"""


class TestHubOpsTable:
    def test_read_ops_registered(self, sentinel_module):
        from sentinel.ui import hub_ops
        for op in ("hub/inventory", "hub/state_stamp", "hub/presets",
                   "hub/presets/save", "hub/preflight"):
            assert op in hub_ops.HUB_OPS

    def test_inventory_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/inventory"]({}) == {"error": "no_document"}

    def test_state_stamp_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/state_stamp"]({}) == {"error": "no_document"}

    def test_preflight_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/preflight"]({}) == {"error": "no_document"}
