# Block 5B — Structured Console Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add failure-proof, structured JSON events to Sentinel's Cinema 4D console while preserving every existing `safe_print(msg)` caller.

**Architecture:** A stdlib-only logger serializes stable one-line events and swallows its own failures. `safe_print` becomes a compatibility adapter; only registration, HTTP/queue/job failures, and guarded panel blocks migrate to named structured events in this block.

**Tech Stack:** Python stdlib (`datetime`, `json`, `traceback`); pytest; Cinema 4D stdout console.

**Spec:** `docs/superpowers/specs/2026-08-25-block5-maintainability-design.md`

## Global Constraints

- No log file, rotation, retention, transmission, setting, or UI.
- Stable top-level keys are exactly `ts`, `level`, `event`, `component`, and `fields`.
- Logging never raises, including broken `repr`, JSON encoding, or `print`.
- API clients never receive tracebacks or local diagnostic fields.
- `safe_print(msg)` keeps its current signature and null-safety.
- Migrate only the boundaries listed by the spec; ordinary progress messages stay behind `safe_print`.
- Run Python tests with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`.
- Block 5A must already be green before execution.

---

### Task 1: Failure-proof structured event encoder

**Files:**
- Create: `plugin/sentinel/common/logging.py`
- Create: `tests/test_structured_logging.py`

**Interfaces:**
- Produces: `emit(level, event, component, **fields) -> None`
- Produces: `debug(event, component, **fields) -> None`
- Produces: `info(event, component, **fields) -> None`
- Produces: `warning(event, component, **fields) -> None`
- Produces: `error(event, component, **fields) -> None`
- Produces: `exception(event, component, exc, **fields) -> None`

- [ ] **Step 1: Write RED tests for the observable console contract**

```python
# tests/test_structured_logging.py
import json


def _payload(line):
    assert line.startswith("[Sentinel] ")
    return json.loads(line[len("[Sentinel] "):])


def test_info_emits_one_deterministic_json_line(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    lines = []
    monkeypatch.setattr("builtins.print", lines.append)
    sentinel_logging.info("server.started", "webbridge.http", port=8347, host="127.0.0.1")
    assert len(lines) == 1
    payload = _payload(lines[0])
    assert list(payload) == ["component", "event", "fields", "level", "ts"]
    assert payload["level"] == "INFO"
    assert payload["event"] == "server.started"
    assert payload["component"] == "webbridge.http"
    assert payload["fields"] == {"host": "127.0.0.1", "port": 8347}
    assert "\n" not in lines[0]


def test_unknown_values_and_broken_repr_never_escape(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    class Broken:
        def __repr__(self):
            raise RuntimeError("repr failed")

    lines = []
    monkeypatch.setattr("builtins.print", lines.append)
    sentinel_logging.warning("value.bad", "tests", target=Broken())
    assert _payload(lines[0])["fields"]["target"] == "<unrepresentable>"


def test_console_failure_is_swallowed(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    def broken_print(_line):
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "broken")

    monkeypatch.setattr("builtins.print", broken_print)
    assert sentinel_logging.error("console.failed", "tests", value=1) is None


def test_exception_keeps_traceback_local_and_structured(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    lines = []
    monkeypatch.setattr("builtins.print", lines.append)
    try:
        raise ValueError("bad payload")
    except ValueError as exc:
        sentinel_logging.exception("queue.dispatch_failed", "webbridge.runtime", exc, op="panel/qc")
    fields = _payload(lines[0])["fields"]
    assert fields["exception_type"] == "ValueError"
    assert fields["exception_message"] == "bad payload"
    assert "ValueError: bad payload" in fields["traceback"]
    assert fields["op"] == "panel/qc"
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_structured_logging.py -q -p no:cacheprovider`

Expected: import failure because `sentinel.common.logging` does not exist.

- [ ] **Step 3: Implement the encoder and convenience functions**

Use UTC ISO timestamps ending in `Z`, `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, recursive safe conversion for dictionaries/lists/tuples/scalars, and `"<unrepresentable>"` when both conversion and `repr` fail. `exception()` must call `traceback.format_exception(type(exc), exc, exc.__traceback__)` and join it into one escaped JSON string.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_structured_logging.py -q -p no:cacheprovider`

Expected: all pass.

- [ ] **Step 5: Mutation-check the no-raise and one-line contracts**

Temporarily remove the outer print guard and verify `test_console_failure_is_swallowed` fails. Restore it. Temporarily print the traceback separately and verify `test_exception_keeps_traceback_local_and_structured` or `test_info_emits_one_deterministic_json_line` fails; restore and rerun green.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/common/logging.py tests/test_structured_logging.py
git commit -m "feat(logging): add structured console events"
```

---

### Task 2: `safe_print` compatibility adapter

**Files:**
- Modify: `plugin/sentinel/common/helpers.py:1-15`
- Modify: `tests/test_structured_logging.py`

**Interfaces:**
- Consumes: `sentinel.common.logging.info`
- Preserves: `safe_print(msg) -> None`
- Produces event: level `INFO`, event `legacy.message`, component `legacy`, fields `{"message": str(msg)}`

- [ ] **Step 1: Add RED compatibility tests**

```python
def test_safe_print_uses_the_legacy_structured_event(monkeypatch):
    from sentinel.common import helpers

    calls = []
    monkeypatch.setattr(helpers, "_log_info", lambda event, component, **fields: calls.append((event, component, fields)))
    helpers.safe_print("hello")
    assert calls == [("legacy.message", "legacy", {"message": "hello"})]


def test_safe_print_none_remains_silent(monkeypatch):
    from sentinel.common import helpers

    calls = []
    monkeypatch.setattr(helpers, "_log_info", lambda *args, **kwargs: calls.append((args, kwargs)))
    helpers.safe_print(None)
    assert calls == []
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_structured_logging.py -q -p no:cacheprovider`

Expected: failure because `helpers._log_info` and the structured adapter do not exist.

- [ ] **Step 3: Implement the adapter**

```python
from .logging import info as _log_info


def safe_print(msg):
    """Compatibility console logger; new code should emit named events."""
    if msg is None:
        return
    _log_info("legacy.message", "legacy", message=str(msg))
```

Do not retain a second `print` fallback: `logging.emit` already owns the only failure-proof console boundary.

- [ ] **Step 4: Run compatibility and representative legacy callers**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_structured_logging.py tests/test_snapshot_watch.py tests/test_scene_check_results.py tests/test_version_helpers.py -q -p no:cacheprovider`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/common/helpers.py tests/test_structured_logging.py
git commit -m "refactor(logging): route safe_print through structured console"
```

---

### Task 3: Queue, jobs, and HTTP boundary events

**Files:**
- Modify: `plugin/sentinel/webbridge.py:18-28,108-238,243-312,321-580`
- Modify: `tests/test_webbridge.py`

**Interfaces:**
- Consumes: `exception`, `info`, and `warning` from `sentinel.common.logging`
- Produces events:
  - `queue.dispatch_failed` / `webbridge.runtime` with `op`
  - `job.failed` / `webbridge.runtime` with `job_id` and `error`
  - `http.handler_failed` / `webbridge.http` with `method` and `path`
  - `http.server_started` / `webbridge.http` with `host` and `port`
  - `http.server_stop_failed` / `webbridge.http` with `phase`

- [ ] **Step 1: Add RED tests that assert named events, not logger mocks**

Add a queue test that installs a real logger sink by monkeypatching `builtins.print`, makes dispatch raise, parses the emitted JSON, and asserts `queue.dispatch_failed` plus the request op. Add a `JobRegistry.fail` test asserting `job.failed`. Extend the existing raising-handler live-server fixture with a captured console line and assert the HTTP response remains exactly `{"error":"internal_error"}` while the console event is `http.handler_failed`.

- [ ] **Step 2: Run the three tests and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge.py -q -p no:cacheprovider -k 'structured or handler_error_does_not_leak_traceback'`

Expected: event assertions fail; the existing no-traceback response assertion stays green.

- [ ] **Step 3: Add structured calls without changing control flow**

In `MainThreadQueue.drain`, emit before building the existing result dict and retain both `error` and internal `traceback` fields because that dict travels only from the main-thread queue to Sentinel's own API adapter. In `_RequestHandler`, replace `traceback.print_exc()` with `log_exception(...)` and keep the client envelope unchanged. In `JobRegistry.fail`, emit after state update. Log server start after a successful bind/start; log stop exceptions separately for `shutdown` and `server_close` while preserving idempotence.

- [ ] **Step 4: Run all webbridge tests outside the socket sandbox**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_webbridge.py -q -p no:cacheprovider`

Expected: all pass.

- [ ] **Step 5: Mutation-check client traceback isolation**

Temporarily return the formatted traceback from `_RequestHandler` and verify `test_handler_error_does_not_leak_traceback` fails. Restore and rerun green.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/webbridge.py tests/test_webbridge.py
git commit -m "refactor(logging): instrument bridge boundaries"
```

---

### Task 4: C4D registration and guarded-block events

**Files:**
- Modify: `plugin/sentinel_panel.pyp:15,140-337`
- Modify: `plugin/sentinel/ui/panel_ops.py:68,350-367`
- Create: `tests/test_logging_boundaries.py`

**Interfaces:**
- Produces events:
  - `plugin.registration` / `bootstrap` with `plugin`, `plugin_id`, `ok`
  - `plugin.registration_failed` / `bootstrap` with exception fields
  - `panel.block_failed` / `panel.overview` with `block`
- Keeps icon/progress/banner text behind `safe_print`.

- [ ] **Step 1: Write a RED test for the guarded block event**

```python
def test_guarded_block_logs_component_and_block(sentinel_module, monkeypatch):
    from sentinel.ui import panel_ops

    calls = []
    monkeypatch.setattr(panel_ops, "log_exception", lambda event, component, exc, **fields: calls.append((event, component, type(exc).__name__, fields)))

    def broken(_doc):
        raise ValueError("bad card")

    assert panel_ops._guarded_block("assets", broken, object()) is None
    assert calls == [("panel.block_failed", "panel.overview", "ValueError", {"block": "assets"})]
```

Also add a bootstrap import smoke test that asserts the fixture still registers Frame `2099073`, Palette `2099075`, Panel `2099076`, Frame Sync `2099077`, Pin `2099078`, and Variants `2099079`; this pins behaviour while registration output changes.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_logging_boundaries.py -q -p no:cacheprovider`

Expected: guarded-block assertion fails because it still calls `safe_print`.

- [ ] **Step 3: Migrate only registration outcomes and guarded failures**

Import `exception as log_exception`, `info as log_info`, and `warning as log_warning`. Replace success/failure/crash registration messages for Panel, Palette, Frame, Pin, Variants, and Frame Sync with the named events and fields above. Do not migrate icon discovery, the startup banner, AOV progress, or scene-tool progress.

- [ ] **Step 4: Run boundary, bootstrap, panel, and full suites**

Run focused: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_logging_boundaries.py tests/test_panel_ops.py tests/test_panel_spa.py -q -p no:cacheprovider`

Run full outside socket sandbox: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider`

Expected: at least the post-5A count plus Block-5B tests, zero failures.

- [ ] **Step 5: Confirm no file logging or SPA changes**

Run: `rg -n "FileHandler|RotatingFileHandler|basicConfig|open\(.*log" plugin/sentinel plugin/sentinel_panel.pyp` and `git diff --exit-code ab8f5f6 -- plugin/web web`.

Expected: first command has no Block-5 logging implementation matches; second has no output.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel_panel.pyp plugin/sentinel/ui/panel_ops.py tests/test_logging_boundaries.py
git commit -m "refactor(logging): name C4D boundary events"
```
