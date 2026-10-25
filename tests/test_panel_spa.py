# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/panel_spa.py — the Fase 6.0 Task 2 dockable
host (``PanelSPADialog`` + ``SentinelPanelSPACmd``).

Uses the fake-c4d harness (``sentinel_module`` fixture, tests/conftest.py):
``panel_spa.py`` does ``import c4d`` at module scope (same as
``reports_dialog.py``), so it is imported lazily inside each test. These
tests pin three things only: (1) the module imports cleanly under the fake
harness (no live C4D needed to exercise the class definitions), (2) the new
plugin ID is distinct from every known 2099xxx id and above the highest one
assigned so far, and (3) ``panel/overview`` (merged from ``panel_ops.PANEL_OPS``
in Task 1) is reachable through ``reports_dialog._OPS``, the single table the
server actually dispatches from.
"""


class TestPanelSpaImports:
    def test_module_imports_under_fake_harness(self, sentinel_module):
        from sentinel.ui import panel_spa
        assert hasattr(panel_spa, "PanelSPADialog")
        assert hasattr(panel_spa, "SentinelPanelSPACmd")
        assert hasattr(panel_spa, "open_panel_spa")

    def test_panel_url_carries_api_capability_token(self, sentinel_module):
        from sentinel.ui import panel_spa, reports_dialog

        previous_token = reports_dialog._api_token
        reports_dialog._api_token = "test-capability-token"
        try:
            url = panel_spa.PanelSPADialog()._url(8347)
        finally:
            reports_dialog._api_token = previous_token

        assert url == (
            "http://127.0.0.1:8347/"
            "?page=panel&token=test-capability-token"
        )


class TestPluginIds:
    def test_ids_are_the_registered_ones_and_shared_by_every_module(self, sentinel_module):
        """Plugin Café registration of 2026-10-25 (account jmelpri). Every
        module reads its ID from sentinel.common.constants — none keeps a
        private copy that could drift."""
        from sentinel.common import constants
        from sentinel.ui import frame_sync, frame_tag, pin_tag, variant_tag
        ids = {
            "panel": constants.SENTINEL_PANEL_SPA_PLUGIN_ID,
            "palette": constants.SENTINEL_PALETTE_PLUGIN_ID,
            "frame": constants.SENTINEL_FRAME_TAG_PLUGIN_ID,
            "frame_sync": constants.SENTINEL_FRAME_SYNC_PLUGIN_ID,
            "pin": constants.SENTINEL_PIN_TAG_PLUGIN_ID,
            "variants": constants.SENTINEL_VARIANT_TAG_PLUGIN_ID,
        }
        assert ids == {"panel": 1072205, "palette": 1072206, "frame": 1072207,
                       "frame_sync": 1072208, "pin": 1072209, "variants": 1072210}
        assert frame_tag.SENTINEL_FRAME_TAG_PLUGIN_ID == ids["frame"]
        assert pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID == ids["pin"]
        assert variant_tag.SENTINEL_VARIANT_TAG_PLUGIN_ID == ids["variants"]
        assert frame_sync.PLUGIN_ID == frame_sync.EVENT_ID == ids["frame_sync"]
        assert sentinel_module.SENTINEL_PALETTE_PLUGIN_ID == ids["palette"]


class TestPanelOverviewReachableFromReportsDialog:
    def test_panel_overview_merged_into_ops_table(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert "panel/overview" in reports_dialog._OPS
        assert "panel/state_stamp" in reports_dialog._OPS
        assert "panel/open_form" in reports_dialog._OPS


class TestDialogTimersReturnNone:
    """C4D 2026.304 requires ``GeDialog.Timer`` to return None. Measured live
    (macOS, 2026-10-01): returning True raised ``TypeError: Timer expected
    None, not bool`` on every 25 ms tick — 1410 tracebacks on the console
    within seconds of opening the panel. The tick's work ran before the
    return, so nothing looked broken, but the exception fired ~40 times a
    second for as long as the panel was open."""

    def test_panel_timer_returns_none(self, sentinel_module):
        from sentinel.ui import panel_spa
        assert panel_spa.PanelSPADialog().Timer(None) is None

    def test_reports_and_form_timers_return_none(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert reports_dialog.ReportsDialog(8347).Timer(None) is None
        assert reports_dialog.FormDialog(8347, "settings").Timer(None) is None
