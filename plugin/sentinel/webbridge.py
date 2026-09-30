# -*- coding: utf-8 -*-
"""Compatibility facade for Sentinel's C4D-free web bridge.

Existing UI adapters intentionally continue to import this module. Concrete
implementations live under :mod:`sentinel.bridge`; this facade explicitly
reexports the legacy surface and owns the replaceable process-wide ``JOBS``
registry.
"""

from sentinel.bridge.forms import (
    PALETTE_ACTIONS,
    PALETTE_ACTION_BY_ID,
    SAVE_VERSION_FINAL_HINT,
    SETTINGS_COMPOSITOR_OPTIONS,
    SETTINGS_FPS_OPTIONS,
    SETTINGS_HISTORY_OPTIONS,
    _CHECK_ENTRY_BY_ID,
    _coerce_int,
    _gate_item_payload,
    gate_can_proceed,
    gate_state_payload,
    merge_notes_submission,
    palette_actions_payload,
    resolve_save_version_status,
    save_version_status_options,
    validate_save_version_submit,
    validate_settings_submit,
)
from sentinel.bridge.http import (
    CONTENT_TYPES,
    MAX_BODY_BYTES,
    _API_PREFIX,
    _GET_OPS,
    _RequestHandler,
    _THUMB_PATH,
    create_server,
    start_server_thread,
    stop_server,
)
from sentinel.bridge.hub import (
    _COLLECT_PHASES,
    _THUMB_EXTS,
    collect_phase_pct,
    hub_inventory_payload,
    resolve_repath_targets,
    thumb_cache_name,
)
from sentinel.bridge.reports import (
    _FIX_ACTION_ID_BY_CHECK_ID,
    _MATERIAL_SOURCE_TYPES,
    _QC_DETAIL_CAP,
    _asset_provenance,
    _delivery_asset,
    _delivery_qc,
    _delivery_summary,
    _delivery_version,
    _delivery_zip,
    _doctor_item,
    _qc_check_details,
    _qc_check_row,
    _qc_violation_detail,
    _render_validation_check,
    _supervisor_shot,
    delivery_report_payload,
    doctor_report_payload,
    group_qc_by_severity,
    qc_report_payload,
    render_validation_payload,
    supervisor_report_payload,
    top_qc_checks,
)
from sentinel.bridge.runtime import JobRegistry, MainThreadQueue, _QueuedRequest


JOBS = JobRegistry()
