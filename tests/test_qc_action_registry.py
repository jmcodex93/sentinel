"""Phase 3: declarative QC action registry — fields, dispatch, id scheme, report keys."""

import json

import pytest


def test_every_entry_has_valid_actions_report_key_and_fix(sentinel_module):
    from sentinel.qc.registry import (
        ALLOWED_ACTIONS,
        CHECK_REGISTRY,
        resolve_function,
    )

    panel = sentinel_module._panel
    seen_report_keys = set()
    for entry in CHECK_REGISTRY:
        # actions non-empty, subset of allowed
        assert entry.actions, f"{entry.check_id} has no actions"
        for action in entry.actions:
            assert action in ALLOWED_ACTIONS, f"{entry.check_id}: bad action {action}"

        # report_key present + unique
        assert entry.report_key, f"{entry.check_id} has no report_key"
        assert entry.report_key not in seen_report_keys, (
            f"duplicate report_key {entry.report_key}"
        )
        seen_report_keys.add(entry.report_key)

        # has_fix <=> fix_fn set, and fix_fn resolves to a callable
        assert bool(entry.has_fix) == bool(entry.fix_fn), (
            f"{entry.check_id}: has_fix/fix_fn mismatch"
        )
        if entry.has_fix:
            fn = resolve_function(entry.fix_fn, panel)
            assert callable(fn), f"{entry.check_id}: fix_fn does not resolve to callable"

        # row_click_action, when set, must be one of the entry's actions
        if entry.row_click_action is not None:
            assert entry.row_click_action in entry.actions, (
                f"{entry.check_id}: row_click_action not in actions"
            )
        assert entry.fix_scope in ("objects", "document"), (
            f"{entry.check_id}: bad fix_scope {entry.fix_scope}"
        )


def test_row_click_and_fix_scope_overrides(sentinel_module):
    """cross_aspect row click runs the sweep (info); fps_range fix is document-scoped."""
    from sentinel.qc.registry import CHECK_REGISTRY

    by_id = {entry.check_id: entry for entry in CHECK_REGISTRY}
    assert by_id["cross_aspect"].row_click_action == "info"
    assert by_id["fps_range"].fix_scope == "document"
    for entry in CHECK_REGISTRY:
        if entry.check_id != "fps_range":
            assert entry.fix_scope == "objects"


def test_panel_has_handler_method_for_every_action(sentinel_module):
    from sentinel.qc.registry import CHECK_REGISTRY

    YSPanel = sentinel_module._panel.YSPanel
    for entry in CHECK_REGISTRY:
        for action in entry.actions:
            name = f"_qc_{action}_{entry.check_id}"
            method = getattr(YSPanel, name, None)
            assert callable(method), f"missing handler {name}"


def test_qc_action_id_round_trip_for_all_entries(sentinel_module):
    from sentinel.qc.registry import CHECK_REGISTRY
    from sentinel.ui.ids import decode_qc_action, qc_action_id

    seen_ids = set()
    for index, entry in enumerate(CHECK_REGISTRY):
        for action in entry.actions:
            cid = qc_action_id(index, action)
            assert cid not in seen_ids, "QC action ids must be unique"
            seen_ids.add(cid)
            assert decode_qc_action(cid) == (index, action)


def test_decode_rejects_unknown_ids(sentinel_module):
    from sentinel.ui.ids import QC_ACTION_BASE, decode_qc_action

    assert decode_qc_action(QC_ACTION_BASE - 1) is None      # below base
    assert decode_qc_action(QC_ACTION_BASE + 3) is None      # reserved slot 3
    assert decode_qc_action(0) is None
    assert decode_qc_action(1310) is None                    # a real non-QC widget id
    assert decode_qc_action(True) is None                    # bool is not a valid id
    assert decode_qc_action("1400") is None


def test_qc_action_id_rejects_unknown_action(sentinel_module):
    from sentinel.ui.ids import qc_action_id

    with pytest.raises(ValueError):
        qc_action_id(0, "delete")


class _FakeDoc:
    def GetDocumentName(self):
        return "untitled.c4d"

    def GetDocumentPath(self):
        return ""

    def GetTakeData(self):
        return None


def test_report_section_keys_match_registry_report_keys(sentinel_module, tmp_path, monkeypatch):
    panel = sentinel_module._panel
    from sentinel.qc.registry import CHECK_REGISTRY

    out = tmp_path / "qc_report.json"
    monkeypatch.setattr(panel.c4d.storage, "SaveDialog", lambda *a, **k: str(out))

    save_path = panel.export_qc_report(_FakeDoc(), {}, "Tester", None)
    assert save_path == str(out)

    report = json.loads(out.read_text(encoding="utf-8"))
    expected = {entry.report_key for entry in CHECK_REGISTRY}
    assert set(report["checks"].keys()) == expected
