# Block 5 — Maintainability design

**Date:** 2026-08-25  
**Branch:** `refactor/block5-maintainability`  
**Status:** completed and live-verified on 2026-08-26

## Goal

Reduce maintenance risk in three areas without changing Sentinel's user-visible
behaviour:

1. consolidate the Cinema 4D `TagData` primitives duplicated by Sentinel Frame,
   Sentinel Pin, and Sentinel Variants;
2. introduce structured, best-effort console logging;
3. split `webbridge.py` into modules with one responsibility while preserving
   its current import surface.

This is a refactor. Existing scenes, tag payloads, HTTP routes, JSON payloads,
plugin IDs, UI copy, and C4D callbacks must behave exactly as before.

## Global constraints

- No new feature, endpoint, setting, sidecar, dialog, or UI control.
- No tag schema or stored `BaseContainer` layout changes.
- No common `TagData` base class or mixin. Each registered plugin keeps its own
  concrete class and lifecycle callbacks.
- No log file. Structured events go only to the Cinema 4D console/stdout.
- Existing imports from `sentinel.webbridge` continue to work. Consumers are
  not forced to know the new internal module layout.
- `webbridge` remains pure stdlib and importable without `c4d`.
- Logging must never raise into production logic, including when a field cannot
  be JSON encoded or stdout is unavailable.
- Refactoring is delivered as 5A, 5B, and 5C. Each sub-block is independently
  tested and committed before the next begins.

## 5A — Shared TagData primitives

### Boundary

Create `plugin/sentinel/ui/tag_support.py`. It may import `c4d`, but it contains
only host-adaptation primitives; no Frame, Pin, or Variants business rules.

The shared surface consists of free functions, not inherited methods:

- extracting a top-level description ID from a `DescID` or integer;
- best-effort `BaseContainer` writes with typed setter/fallback assignment;
- reading a node type with a caller-provided fallback plugin ID;
- building a description parent `DescID`;
- resolving a document from a node with active-document fallback;
- main-thread detection across the two C4D API locations used by supported
  builds;
- safe node-name lookup;
- best-effort `EventAdd`;
- extracting a command ID from C4D message data;
- adding a dynamic description parameter;
- adding a dynamic description group.

The parameter builder accepts explicit options for animation, min/max, slider
bounds, step, unit, cycle, and custom GUI. This preserves Frame's richer
numeric controls without teaching the shared helper that `ID_LINE_WIDTH` or any
other domain ID is special. Callers decide those options.

### Deliberate exclusions

The following remain in their owning modules:

- availability probes and each `_TagDataBase` binding;
- `Init`, `GetDDescription`, `GetDParameter`, `SetDParameter`,
  `GetDEnabling`, `Execute`, `Draw`, and `Message`;
- tag-specific status reporting and display-name mirroring;
- storage, undo, take, pin, variant, and drawing logic;
- helpers that only two tags happen to share but have domain meaning, such as
  object-tree traversal.

This line prevents a mechanical deduplication from coupling three independently
registered C4D plugins through lifecycle behaviour.

### Compatibility

The three tag modules import the new functions under their existing private
names where practical. That keeps their call sites small and makes the diff
reviewable. Fallback plugin IDs are passed explicitly so a failed `GetType()`
continues to produce the same `DescID` creator as before.

## 5B — Structured console logging

### API

Create `plugin/sentinel/common/logging.py` with a small, stdlib-only API:

- `emit(level, event, component, **fields)`;
- convenience functions `debug`, `info`, `warning`, and `error`;
- `exception(event, component, exc, **fields)` for caught exceptions.

Each event is emitted as one console line:

```text
[Sentinel] {"ts":"...","level":"ERROR","event":"http.handler_failed","component":"webbridge.http","fields":{...}}
```

The stable top-level keys are `ts`, `level`, `event`, `component`, and
`fields`. JSON output uses deterministic key ordering. Unknown field values are
converted to a safe string representation; a broken `repr`, JSON encoder, or
console cannot escape the logger.

`exception()` records the exception type, message, and formatted traceback in
fields. The traceback remains local to the C4D console and is never returned by
the localhost API.

### Compatibility and first migration

`sentinel.common.helpers.safe_print(msg)` remains callable with its current
signature and becomes a compatibility adapter that emits a
`legacy.message`/`legacy` event. This avoids a repository-wide logging rewrite
inside a maintainability block.

The first structured call sites are system boundaries where fields are useful:

- plugin/tag registration;
- HTTP request-handler failures and server lifecycle failures;
- main-thread queue dispatch failures and job failures;
- guarded panel/report blocks.

Ordinary progress copy and domain messages remain behind `safe_print` for now.
There is no file handler, rotation, retention, remote transmission, or runtime
configuration in Block 5.

## 5C — Split `webbridge.py`

### Package layout

Create a pure-stdlib package at `plugin/sentinel/bridge/`:

- `runtime.py` — `_QueuedRequest`, `MainThreadQueue`, and `JobRegistry`;
- `http.py` — request handler, security policy, static/thumb/API serving,
  `create_server`, `start_server_thread`, and `stop_server`;
- `reports.py` — Delivery, QC, Doctor, Supervisor, and Render Validation payload
  mappers plus `top_qc_checks` and `group_qc_by_severity`;
- `forms.py` — Save Version, Notes, Settings, Gate, and Command Palette
  constants/validators/payloads;
- `hub.py` — inventory/repath/thumbnail/collect pure helpers.

`plugin/sentinel/webbridge.py` becomes a compatibility facade. It reexports the
same public and intentionally consumed private names as the current module and
owns the mutable singleton `JOBS = JobRegistry()`. Keeping `JOBS` on the facade
preserves existing tests and consumers that deliberately replace
`webbridge.JOBS`.

### Dependency direction

- `runtime`, `reports`, `forms`, and `hub` depend only on stdlib plus the new
  console logger where needed.
- `http` depends on stdlib and the logger, not on UI modules or `c4d`.
- the facade depends on the five bridge modules;
- existing UI adapters continue to depend on the facade during Block 5.

There are no imports from a bridge submodule back into `webbridge.py`. This
keeps the facade acyclic and makes each extracted module independently
testable.

### Compatibility contract

Before extraction, pin the names consumed outside `webbridge.py`, including
private names intentionally used by tests/UI (`_QueuedRequest` and
`_THUMB_EXTS`). After extraction:

- all current `sentinel.webbridge.<name>` lookups resolve;
- constants retain their current values and identity where relevant;
- `JOBS` replacement through `webbridge.JOBS = JobRegistry()` still affects
  every UI consumer;
- HTTP status codes, headers, token/Host/Origin enforcement, body limits,
  payload shapes, and error envelopes are byte-for-byte or value-for-value
  unchanged.

## Delivery order

1. **5A Tag support:** characterize duplicated behaviour, extract free
   functions, migrate Frame/Pin/Variants, run tag-focused and full pytest.
2. **5B Logging:** test failure-proof serialization first, add the compatibility
   adapter and selected boundary events, run logging/HTTP/tag-focused and full
   pytest.
3. **5C Web bridge:** pin facade exports, move one responsibility at a time in
   the order runtime → reports → forms → hub → HTTP, running the relevant
   section of `test_webbridge.py` after each move and the full suite at the end.
4. Run a final whole-branch review and live C4D smoke test before syncing the
   worktree build to the installed plugin.

## Verification

### Automated

- Start from the current full-suite baseline: 1589 passing tests.
- New `tag_support` tests exercise real shared functions against the existing
  fake-C4D contract. Each realistic mutation of a shared branch must be caught
  by a named test.
- Existing Frame, Pin, and Variants tests remain unchanged unless an import
  boundary requires an additive fixture change. Production is never adapted to
  a permissive fake.
- Logging tests cover stable fields, deterministic one-line JSON, unknown
  values, broken representations, console failure, and exception tracebacks.
- A facade contract test pins every external `webbridge` symbol discovered
  before the split.
- Existing socket-backed security/lifecycle tests exercise the extracted HTTP
  module through the `sentinel.webbridge` facade.
- Full command: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
  -p no:cacheprovider`, outside the sandbox where localhost sockets are needed.
- No SPA source changes are planned. If implementation unexpectedly touches
  `web/`, Vitest and a production bundle rebuild become mandatory; otherwise
  the committed bundle must remain byte-identical.

### Live Cinema 4D smoke test

After all automated tests pass:

- MCP ping and plugin registration enumerate Frame, Pin, Variants, Panel, and
  Palette commands/plugins as before;
- create the three tag types in a throwaway document and confirm their dynamic
  descriptions load;
- open Panel, QC, Render, Tools, Settings, Doctor, and Command Palette and
  confirm their API requests succeed;
- trigger one safe, reversible action per tag in the throwaway document and
  undo it;
- compare the user's original document state before/after and leave it active;
- inspect the C4D console for structured boundary events and absence of
  uncaught tracebacks.

## Completion criteria

Block 5 is complete when:

- the nine duplicated host primitives and description builders have one
  implementation, with no shared tag lifecycle base class;
- structured console events are available and used at the selected system
  boundaries, while `safe_print` callers remain functional;
- `webbridge.py` contains compatibility/reexport wiring rather than the five
  implementations listed above;
- all existing observable contracts pass through the old import surface;
- the full suite and live C4D smoke test pass without altering the user's
  working scene.

## Completion record

Implemented in commits `ce90417` through `30eb5be`, following the three
implementation plans linked from this spec. The compatibility contract remains
the public boundary: existing consumers import from `sentinel.webbridge`, tag
plugin IDs and persisted payloads are unchanged, and logging is console-only.

Final evidence on 2026-08-26:

- full pytest suite: `1618 passed`;
- SPA Vitest suite: `233 passed` (the Block-5 SPA diff is empty);
- webbridge/facade selection: `157 passed`;
- `plugin/sentinel/webbridge.py`: 75-line compatibility facade;
- SPA build diff against the pre-Block-5 base: empty;
- installed plugin payload matched the worktree after sync;
- Cinema 4D 2026.3.4 restart: Frame, Pin, Variants, Panel and Command Palette
  registered with their existing IDs;
- Overview, QC, Render, Deliver, Tools, Settings, Doctor, Help and Command
  Palette loaded successfully;
- Sentinel Doctor passed every applicable diagnostic; the unsaved-scene folder
  check was correctly neutral;
- the Cinema 4D console showed structured Sentinel events and no traceback or
  import error;
- the active document's FPS, frame range, camera, take and render data were
  identical before and after the non-destructive smoke test.

The detailed implementation and verification ledger is stored at
`docs/audit/2026-08-26_block5_maintainability_completion.md`.
