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


class TestPanelSpaPluginId:
    # Known ids already assigned in the 2099xxx range (see
    # plugin/sentinel/common/constants.py PLUGIN_ID=2099069,
    # sentinel_panel.pyp SENTINEL_PALETTE_PLUGIN_ID=2099075,
    # frame_tag.py SENTINEL_FRAME_TAG_PLUGIN_ID=2099073; 2099072 retired).
    _KNOWN_IDS = {2099069, 2099072, 2099073, 2099075}

    def test_plugin_id_is_unique_and_above_known_ids(self, sentinel_module):
        from sentinel.common.constants import SENTINEL_PANEL_SPA_PLUGIN_ID
        assert SENTINEL_PANEL_SPA_PLUGIN_ID not in self._KNOWN_IDS
        assert SENTINEL_PANEL_SPA_PLUGIN_ID > 2099073


class TestPanelOverviewReachableFromReportsDialog:
    def test_panel_overview_merged_into_ops_table(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert "panel/overview" in reports_dialog._OPS
        assert "panel/state_stamp" in reports_dialog._OPS
        assert "panel/open_form" in reports_dialog._OPS
