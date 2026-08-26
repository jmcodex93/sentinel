"""Compatibility contract for the sentinel.webbridge facade."""

from pathlib import Path


EXPECTED_FACADE_NAMES = {
    "CONTENT_TYPES",
    "_API_PREFIX",
    "_THUMB_PATH",
    "MAX_BODY_BYTES",
    "_GET_OPS",
    "_QueuedRequest",
    "MainThreadQueue",
    "JobRegistry",
    "JOBS",
    "_RequestHandler",
    "create_server",
    "start_server_thread",
    "stop_server",
    "_MATERIAL_SOURCE_TYPES",
    "_asset_provenance",
    "_delivery_asset",
    "_delivery_version",
    "_delivery_qc",
    "_delivery_summary",
    "_delivery_zip",
    "delivery_report_payload",
    "_QC_DETAIL_CAP",
    "_qc_violation_detail",
    "_qc_check_details",
    "_qc_check_row",
    "qc_report_payload",
    "top_qc_checks",
    "_doctor_item",
    "doctor_report_payload",
    "_supervisor_shot",
    "supervisor_report_payload",
    "_render_validation_check",
    "render_validation_payload",
    "SAVE_VERSION_FINAL_HINT",
    "resolve_save_version_status",
    "validate_save_version_submit",
    "save_version_status_options",
    "merge_notes_submission",
    "SETTINGS_FPS_OPTIONS",
    "SETTINGS_COMPOSITOR_OPTIONS",
    "SETTINGS_HISTORY_OPTIONS",
    "validate_settings_submit",
    "_coerce_int",
    "_CHECK_ENTRY_BY_ID",
    "_gate_item_payload",
    "gate_state_payload",
    "gate_can_proceed",
    "PALETTE_ACTIONS",
    "PALETTE_ACTION_BY_ID",
    "palette_actions_payload",
    "_FIX_ACTION_ID_BY_CHECK_ID",
    "group_qc_by_severity",
    "_THUMB_EXTS",
    "hub_inventory_payload",
    "resolve_repath_targets",
    "thumb_cache_name",
    "_COLLECT_PHASES",
    "collect_phase_pct",
}


def test_facade_exports_the_pinned_legacy_surface():
    import sentinel.webbridge as webbridge

    assert EXPECTED_FACADE_NAMES.difference(vars(webbridge)) == set()


def test_jobs_is_assignable_at_the_legacy_import_path():
    import sentinel.webbridge as webbridge

    original = webbridge.JOBS
    replacement = webbridge.JobRegistry()
    try:
        webbridge.JOBS = replacement
        assert webbridge.JOBS is replacement
    finally:
        webbridge.JOBS = original


def test_runtime_types_are_implemented_in_the_runtime_module():
    import sentinel.webbridge as webbridge

    assert webbridge._QueuedRequest.__module__ == "sentinel.bridge.runtime"
    assert webbridge.MainThreadQueue.__module__ == "sentinel.bridge.runtime"
    assert webbridge.JobRegistry.__module__ == "sentinel.bridge.runtime"
    assert isinstance(webbridge.JOBS, webbridge.JobRegistry)


def test_report_entry_points_are_implemented_in_the_reports_module():
    import sentinel.webbridge as webbridge

    for name in (
        "delivery_report_payload",
        "qc_report_payload",
        "doctor_report_payload",
        "supervisor_report_payload",
        "render_validation_payload",
        "top_qc_checks",
        "group_qc_by_severity",
    ):
        assert getattr(webbridge, name).__module__ == "sentinel.bridge.reports"


def test_bridge_implementation_never_imports_c4d():
    bridge_dir = Path(__file__).parents[1] / "plugin" / "sentinel" / "bridge"
    for source in bridge_dir.glob("*.py"):
        assert "import c4d" not in source.read_text(encoding="utf-8")
