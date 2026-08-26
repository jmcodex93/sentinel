# Block 5C — Webbridge Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Sentinel's monolithic `webbridge.py` into responsibility-focused, C4D-free modules while preserving the exact `sentinel.webbridge` import surface and runtime behaviour.

**Architecture:** Add a private implementation package at `sentinel.bridge` with `runtime`, `reports`, `forms`, `hub`, and `http` modules. Keep `sentinel.webbridge` as the compatibility facade and owner of the mutable process-wide `JOBS` registry. Extract one responsibility at a time behind characterization tests; do not redesign endpoints, payloads, or threading.

**Tech Stack:** Python stdlib (`http.server`, `queue`, `threading`); pytest; existing live localhost server tests.

**Spec:** `docs/superpowers/specs/2026-08-25-block5-maintainability-design.md`

## Global Constraints

- Block 5A and 5B must already be green before execution.
- `import sentinel.webbridge` remains the supported import path; every currently consumed public or private symbol remains reachable there.
- `sentinel.webbridge.JOBS` remains assignable and remains the registry consumed by UI code. Do not create a second authoritative registry inside `sentinel.bridge.runtime`.
- No C4D import anywhere under `plugin/sentinel/bridge/`.
- No endpoint, HTTP method, authentication, payload shape, timeout, queue budget, status transition, or content type changes.
- No SPA changes and no opportunistic cleanup.
- Use explicit facade imports; avoid wildcard imports and import-time side effects.
- Run Python tests with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`.

---

### Task 1: Pin the compatibility facade contract

**Files:**
- Create: `tests/test_webbridge_facade.py`

**Interfaces:**
- Pins symbols imported by tests, panel adapters, and other Sentinel modules.
- Pins `JOBS` as a facade-owned, assignable module attribute.
- Pins the implementation package as C4D-free.

- [ ] **Step 1: Inventory consumers before writing the test**

Run: `rg -n "from sentinel\.webbridge import|import sentinel\.webbridge|webbridge\." plugin tests --glob '*.py' --glob '*.pyp'`

Record every consumed name in a literal `EXPECTED_FACADE_NAMES` set. At minimum it must include queue/job types and `JOBS`; HTTP constants, handler, and lifecycle helpers; report mappers; form validators/constants; QC grouping; palette data; and hub helpers/constants.

- [ ] **Step 2: Write the facade characterization tests**

```python
# tests/test_webbridge_facade.py
def test_facade_exports_the_pinned_legacy_surface():
    import sentinel.webbridge as webbridge

    missing = EXPECTED_FACADE_NAMES.difference(vars(webbridge))
    assert missing == set()


def test_jobs_is_assignable_at_the_legacy_import_path():
    import sentinel.webbridge as webbridge

    original = webbridge.JOBS
    replacement = webbridge.JobRegistry()
    try:
        webbridge.JOBS = replacement
        assert webbridge.JOBS is replacement
    finally:
        webbridge.JOBS = original


def test_bridge_implementation_never_imports_c4d():
    from pathlib import Path

    bridge_dir = Path(__file__).parents[1] / "plugin" / "sentinel" / "bridge"
    for source in bridge_dir.glob("*.py"):
        assert "import c4d" not in source.read_text(encoding="utf-8")
```

- [ ] **Step 3: Run against the monolith and verify GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py -q -p no:cacheprovider`

Expected: the facade-symbol and assignment tests pass. The no-C4D loop is vacuously green until the package exists; later tasks make it meaningful.

- [ ] **Step 4: Commit**

```bash
git add tests/test_webbridge_facade.py
git commit -m "test(webbridge): pin compatibility facade"
```

---

### Task 2: Extract queue and job runtime

**Files:**
- Create: `plugin/sentinel/bridge/__init__.py`
- Create: `plugin/sentinel/bridge/runtime.py`
- Modify: `plugin/sentinel/webbridge.py`
- Modify: `tests/test_webbridge_facade.py`

**Interfaces:**
- Moves unchanged: `_QueuedRequest`, `MainThreadQueue`, `JobRegistry`.
- Consumes Block-5B structured boundary logging.
- Keeps: `JOBS = JobRegistry()` in `sentinel.webbridge`.

- [ ] **Step 1: Add provenance assertions that fail before extraction**

Assert `MainThreadQueue.__module__ == "sentinel.bridge.runtime"` and `JobRegistry.__module__ == "sentinel.bridge.runtime"`, while `webbridge.JOBS` remains an instance of the re-exported class.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py -q -p no:cacheprovider`

Expected: provenance assertions report `sentinel.webbridge`.

- [ ] **Step 3: Move runtime code without semantic edits**

Move the three definitions and only their required imports (`itertools`, `queue`, `threading`, `time`, `traceback`, and Block-5B logging). Re-export the definitions explicitly from `webbridge.py`; instantiate `JOBS` there after the imports. Keep queue limits, cancellation locking, drain telemetry, job states, and returned dictionaries byte-for-byte equivalent.

- [ ] **Step 4: Run queue/job and facade tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py tests/test_webbridge.py -q -p no:cacheprovider -k 'facade or MainThreadQueue or JobRegistry or DrainBudget'`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/bridge/__init__.py plugin/sentinel/bridge/runtime.py plugin/sentinel/webbridge.py tests/test_webbridge_facade.py
git commit -m "refactor(webbridge): extract queue and job runtime"
```

---

### Task 3: Extract report payload mappers

**Files:**
- Create: `plugin/sentinel/bridge/reports.py`
- Modify: `plugin/sentinel/webbridge.py`
- Modify: `tests/test_webbridge_facade.py`

**Interfaces:**
- Moves report constants/helpers: `_MATERIAL_SOURCE_TYPES`, `_QC_DETAIL_CAP`, `_FIX_ACTION_ID_BY_CHECK_ID`, `_asset_provenance`, `_delivery_asset`, `_delivery_version`, `_delivery_qc`, `_delivery_summary`, `_delivery_zip`, `_qc_violation_detail`, `_qc_check_details`, `_qc_check_row`, `_doctor_item`, `_supervisor_shot`, `_render_validation_check`.
- Moves report entry points: `delivery_report_payload`, `qc_report_payload`, `top_qc_checks`, `doctor_report_payload`, `supervisor_report_payload`, `render_validation_payload`, `group_qc_by_severity`.
- Consumes: `sentinel.qc.registry.CHECK_REGISTRY` only.

- [ ] **Step 1: Add RED provenance assertions for report entry points**

Assert representative functions (`delivery_report_payload`, `qc_report_payload`, `doctor_report_payload`, `supervisor_report_payload`, `render_validation_payload`) come from `sentinel.bridge.reports`.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py -q -p no:cacheprovider`

Expected: representative functions still report `sentinel.webbridge`.

- [ ] **Step 3: Move the complete report slice and explicitly re-export it**

Preserve constants, iteration order, caps, default values, severity logic, and dictionary construction exactly. Do not share new helpers with forms or hub in this task.

- [ ] **Step 4: Run report and facade characterization tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py tests/test_webbridge.py -q -p no:cacheprovider -k 'facade or DeliveryReportPayload or QcReportPayload or GroupQcBySeverity or DoctorReportPayload or SupervisorReportPayload or RenderValidationPayload'`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/bridge/reports.py plugin/sentinel/webbridge.py tests/test_webbridge_facade.py
git commit -m "refactor(webbridge): extract report payloads"
```

---

### Task 4: Extract form, gate, and palette transformations

**Files:**
- Create: `plugin/sentinel/bridge/forms.py`
- Modify: `plugin/sentinel/webbridge.py`
- Modify: `tests/test_webbridge_facade.py`

**Interfaces:**
- Moves constants: `SAVE_VERSION_FINAL_HINT`, `SETTINGS_FPS_OPTIONS`, `SETTINGS_COMPOSITOR_OPTIONS`, `SETTINGS_HISTORY_OPTIONS`, `_CHECK_ENTRY_BY_ID`, `PALETTE_ACTIONS`, `PALETTE_ACTION_BY_ID`.
- Moves functions: `resolve_save_version_status`, `validate_save_version_submit`, `save_version_status_options`, `merge_notes_submission`, `validate_settings_submit`, `_coerce_int`, `_gate_item_payload`, `gate_state_payload`, `gate_can_proceed`, `palette_actions_payload`.
- Consumes: `sentinel.notes`, `sentinel.qc.registry`, and `sentinel.versioning`.

- [ ] **Step 1: Add RED provenance assertions**

Pin representative form, gate, and palette functions to `sentinel.bridge.forms`.

- [ ] **Step 2: Run RED, then move the complete slice unchanged**

Run before extraction: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py -q -p no:cacheprovider`

Preserve validation messages, normalization order, tuple contents, IDs, gate status semantics, and palette ordering. Re-export every moved name explicitly.

- [ ] **Step 3: Run focused tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py tests/test_webbridge.py -q -p no:cacheprovider -k 'facade or SaveVersion or Notes or Settings or Gate or Palette'`

Expected: all selected tests pass.

- [ ] **Step 4: Commit**

```bash
git add plugin/sentinel/bridge/forms.py plugin/sentinel/webbridge.py tests/test_webbridge_facade.py
git commit -m "refactor(webbridge): extract forms gates and palette"
```

---

### Task 5: Extract Asset Hub transformations

**Files:**
- Create: `plugin/sentinel/bridge/hub.py`
- Modify: `plugin/sentinel/webbridge.py`
- Modify: `tests/test_webbridge_facade.py`

**Interfaces:**
- Moves constants: `_THUMB_EXTS`, `_COLLECT_PHASES`.
- Moves functions: `hub_inventory_payload`, `resolve_repath_targets`, `thumb_cache_name`, `collect_phase_pct`.
- Consumes: `sentinel.assets`.

- [ ] **Step 1: Add RED provenance assertions**

Pin all four hub functions to `sentinel.bridge.hub` and keep constants reachable through the facade.

- [ ] **Step 2: Run RED, then move the hub slice unchanged**

Run before extraction: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py -q -p no:cacheprovider`

Move hashing, path normalization, totals, skipped counts, repath matching, thumbnail naming, and collection percentage mapping without semantic changes.

- [ ] **Step 3: Run hub and facade tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py tests/test_webbridge.py tests/test_hub_ops.py -q -p no:cacheprovider -k 'facade or Hub or Thumb or collect_phase or repath'`

Expected: all selected tests pass.

- [ ] **Step 4: Commit**

```bash
git add plugin/sentinel/bridge/hub.py plugin/sentinel/webbridge.py tests/test_webbridge_facade.py
git commit -m "refactor(webbridge): extract hub transformations"
```

---

### Task 6: Extract the authenticated local HTTP server

**Files:**
- Create: `plugin/sentinel/bridge/http.py`
- Modify: `plugin/sentinel/webbridge.py`
- Modify: `tests/test_webbridge_facade.py`

**Interfaces:**
- Moves constants: `CONTENT_TYPES`, `_API_PREFIX`, `_THUMB_PATH`, `MAX_BODY_BYTES`, `_GET_OPS`.
- Moves: `_RequestHandler`, `create_server`, `start_server_thread`, `stop_server`.
- Consumes: `_THUMB_EXTS` from `sentinel.bridge.hub` and Block-5B structured logging.

- [ ] **Step 1: Add RED provenance assertions for the HTTP surface**

Assert handler and lifecycle helpers come from `sentinel.bridge.http`, while authentication token generation and the bound-server contract remain observable through `create_server`.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py -q -p no:cacheprovider`

Expected: provenance assertions still report `sentinel.webbridge`.

- [ ] **Step 3: Move the HTTP slice without changing its security contract**

Move only the required imports (`hashlib`, `http.server`, `json`, `os`, `secrets`, `threading`, `traceback`, `urllib.parse`) and the HTTP definitions. Preserve loopback binding checks, per-instance token handling, request-method allowlists, origin checks, body-size enforcement, static path containment, thumbnail allowlisting, response envelopes, port probing, daemon-thread behaviour, and shutdown idempotence. Explicitly re-export the moved names from `webbridge.py`.

- [ ] **Step 4: Run the full live-server suite outside the socket sandbox**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge_facade.py tests/test_webbridge.py -q -p no:cacheprovider`

Expected: all tests pass, including API hardening, static traversal, token, thumbnail, lifecycle, and traceback-isolation tests.

- [ ] **Step 5: Mutation-check authentication preservation**

Temporarily bypass the token comparison and verify an existing unauthorized API test fails. Restore the comparison and rerun the full live-server suite green.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/bridge/http.py plugin/sentinel/webbridge.py tests/test_webbridge_facade.py
git commit -m "refactor(webbridge): extract local HTTP server"
```

---

### Task 7: Final compatibility and system verification

**Files:**
- Modify only if a test exposes an extraction regression: files already listed in Tasks 1–6.

- [ ] **Step 1: Inspect the facade and dependency direction**

Run: `sed -n '1,240p' plugin/sentinel/webbridge.py` and `rg -n 'import c4d|from sentinel\.webbridge|import sentinel\.webbridge' plugin/sentinel/bridge plugin/sentinel/webbridge.py`.

Expected: the facade is explicit and small; bridge modules never import C4D or import back from the facade; dependency direction is one-way.

- [ ] **Step 2: Run import and syntax checks without writing bytecode**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -c "from pathlib import Path; files = [Path('plugin/sentinel/webbridge.py'), *Path('plugin/sentinel/bridge').glob('*.py')]; [compile(path.read_text(encoding='utf-8'), str(path), 'exec') for path in files]; print('bridge syntax ok')"`

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys; sys.path.insert(0, 'plugin'); import sentinel.webbridge as w; assert w.JOBS.__class__ is w.JobRegistry; print('webbridge facade ok')"`

Expected: the commands print `bridge syntax ok` and `webbridge facade ok`, with no `__pycache__` artifacts.

- [ ] **Step 3: Run the complete suite outside the socket sandbox**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider`

Expected: at least the post-5B count plus facade tests, zero failures.

- [ ] **Step 4: Confirm scope discipline**

Run: `git diff --stat ab8f5f6` and `git diff --exit-code ab8f5f6 -- plugin/web web`.

Expected: changes are limited to the Block-5 Python modules, tests, and documentation; the SPA diff is empty.

- [ ] **Step 5: Run live Cinema 4D QC after syncing the branch build**

Use the repository sync script, restart Cinema 4D so Python modules are not stale, then verify: Sentinel panel opens authenticated; Overview, QC, Render, Deliver, and Tools load; Doctor remains healthy; Frame, Pin, Variants, Palette, and Frame Sync registrations are present; one read-only report and one reversible queue-backed action complete; C4D console shows structured one-line events and no import/circular-import traceback.

- [ ] **Step 6: Record evidence**

Capture the exact pytest result, facade import output, sync result, C4D version, Doctor result, registration IDs, and any intentionally skipped destructive action in the final handoff. Do not claim completion without this evidence.
