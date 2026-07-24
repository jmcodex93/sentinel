# Fase 6.4 — Panel SPA sección Tools + paridad + limpieza — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Tools section to the dockable SPA panel (action grid + dialog-free cores → toasts), expose Settings/Doctor/Help in a persistent rail footer for full parity with the native panel, and delete the already-dead `collect_scene` / `TextureRepathingDialog`.

**Architecture:** A new `panel_tools_ops.py` holds thin `panel/tools/*` ops that each call a dialog-free core extracted from `scene_tools.py` (native wrappers keep their `MessageDialog`; ops return status dicts → SPA toasts — the v1.21.0 anti-freeze pattern). The SPA gains a `ToolsSection` (grouped action buttons, no read op) and a `PanelRail` footer with Settings/Doctor/Help. The native panel is untouched (parallel; retirement is Fase 6.5).

**Tech Stack:** Python 3 (C4D plugin, fake-c4d pytest harness), React + TypeScript + Vite + Tailwind v4 (vitest), stdlib-only engines.

## Global Constraints

- Ops NEVER raise; a precondition failure returns `{ok: False, error: "<token>"}`, success returns `{ok: True, ...}`.
- NO `MessageDialog`/`QuestionDialog`/Picture-Viewer in any op code path — a modal inside the panel's Timer drain freezes all of C4D. Each dialog-bearing tool gets a dialog-free `_<fn>_core` returning a status dict; the native `_<fn>` wrapper keeps its dialogs. A `_forbid_dialog` test guards each op that wraps a dialog-bearing core.
- Zero duplicated business logic: cores hold the scene work once; native wrappers map the core's error token back to the original `MessageDialog` text; ops map it to a toast.
- Tools are ACTION-ONLY: no read op, no per-button enablement/selection polling, no confirm (nothing destructive; all Cmd+Z-reversible).
- Native scene behavior stays byte-equivalent: extracting a core must not change what the native wrapper does (same dialogs, same scene effects, same undo grouping).
- The native panel (`panel.py`, `user_areas.py`, `YSPanelCmd`) is NOT touched — retirement is Fase 6.5.
- Version bump to `1.23.0` in `plugin/sentinel/__init__.py`.
- Baselines before this work: pytest 808 passing, vitest 106 passing.

---

## File Structure

- **Create** `plugin/sentinel/ui/panel_tools_ops.py` — `panel/tools/*` + `panel/open_external` ops; `PANEL_TOOLS_OPS`.
- **Modify** `plugin/sentinel/ui/scene_tools.py` — add dialog-free cores; rewrite native wrappers to call them.
- **Modify** `plugin/sentinel/ui/reports_dialog.py` — import + merge `PANEL_TOOLS_OPS` into `_OPS`.
- **Create** `tests/test_panel_tools_ops.py` — op + core tests (fake-c4d).
- **Modify** `web/src/types.ts` — `PanelToolResult` type.
- **Modify** `web/src/lib/api.ts` — `postPanelTool`, `postPanelOpenExternal`, `postPanelOpenSettings` clients + mocks.
- **Create** `web/src/lib/panelTools.ts` (+ `.test.ts`) — the tool catalog (id→label/group) pure data.
- **Create** `web/src/components/panel/ToolsSection.tsx`.
- **Modify** `web/src/components/panel/PanelRail.tsx` — persistent footer (Settings/Doctor/Help).
- **Modify** `web/src/pages/PanelPage.tsx` — mount `ToolsSection`, wire footer, drop the tools placeholder.
- **Modify** `plugin/sentinel/ui/flows.py` — delete `collect_scene`.
- **Modify** `plugin/sentinel/ui/dialogs.py` — delete `TextureRepathingDialog` + its launcher.
- **Modify** `plugin/sentinel/__init__.py`, `CLAUDE.md`, memory, ledger — docs/version.

---

## Core Contracts (shared reference for Tasks 1–3)

Each core returns a dict. Native wrappers map `error` → the original `MessageDialog` text; ops map the whole dict → a toast. Exact tokens:

- `_merge_c4d_file_core(doc, filename)` → `no_document` | `file_not_found` (+`filename`) | `merge_failed` | `merge_error` (+`detail`) | `{ok:True, camera_name}`.
- `_hierarchy_to_layers_core(doc)` → `no_document` | `orphans` (+`count`,`names`) | `no_groups` | `no_layer_root` | `{ok:True, created, updated, nulls}`.
- `_solo_layers_core(doc)` → `no_document` | `no_layer_root` | `{ok:True, unsolo:True}` | `no_layers` | `no_selection` | `{ok:True, soloed}`.
- `_drop_to_floor_core(doc)` → `no_document` | `no_selection` | `{ok:True, dropped}`.
- `_apply_abc_retime_tag_core(doc)` → `no_document` | `no_selection` | `apply_failed` | `{ok:True, applied, skipped, failed}`.
- `_toggle_safe_area_mark_core(doc)` → `no_document` | `no_selection` | `{ok:True, verb, marked, unmarked, failed}`.

Extraction rule (applies to every core): take the existing `scene_tools._<fn>`, replace each `c4d.gui.MessageDialog(...)` + `return` early-exit with `return {"ok": False, "error": "<token>", ...}`, replace the terminal `safe_print(success)` with `return {"ok": True, ...}`, and leave the middle scene-work (loops, undo blocks, EventAdd) unchanged. Rename to `_<fn>_core`. Then rewrite the native `_<fn>` as a thin wrapper that calls the core and, on `not ok`, shows the ORIGINAL dialog text for that token (see each task for the exact mapping).

---

### Task 1: `_merge_c4d_file_core` + merge-based tool ops + module scaffold

**Files:**
- Modify: `plugin/sentinel/ui/scene_tools.py` (`_merge_c4d_file` ~357-385; `_create_hierarchy` ~349, `_create_vibrate_null` ~271, `_merge_camera_file` ~353)
- Create: `plugin/sentinel/ui/panel_tools_ops.py`
- Modify: `plugin/sentinel/ui/reports_dialog.py` (imports ~57-60, `_OPS` ~312-321)
- Test: `tests/test_panel_tools_ops.py`

**Interfaces:**
- Produces: `scene_tools._merge_c4d_file_core(doc, filename) -> dict`.
- Produces: `PANEL_TOOLS_OPS` (dict) with keys `panel/tools/hierarchy`, `panel/tools/vibrate_null`, `panel/tools/cam_simple`, `panel/tools/cam_shakel` (this task); more added in Tasks 2–4.
- Consumes: `scene_tools._ROOT`, `os`, `c4d.documents.MergeDocument`, `c4d.SCENEFILTER_OBJECTS|MATERIALS`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_panel_tools_ops.py`:
```python
"""Tests for panel/tools ops (Fase 6.4). Uses the fake-c4d harness
(``sentinel_module`` fixture, tests/conftest.py) — panel_tools_ops.py does
``import c4d`` at module scope, same as panel_render_ops.py."""


class _FakeDoc:
    def __init__(self):
        self._events = 0


class TestMergeCore:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog allowed in a *_core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._merge_c4d_file_core(None, "nulls.c4d") == {
            "ok": False, "error": "no_document"}

    def test_file_not_found(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(scene_tools.os.path, "exists", lambda p: False)
        r = scene_tools._merge_c4d_file_core(_FakeDoc(), "cam_simple.c4d")
        assert r == {"ok": False, "error": "file_not_found", "filename": "cam_simple.c4d"}

    def test_merge_success(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(scene_tools.os.path, "exists", lambda p: True)
        monkeypatch.setattr(scene_tools.c4d.documents, "MergeDocument", lambda *a: True)
        monkeypatch.setattr(scene_tools.c4d, "EventAdd", lambda *a, **k: None)
        r = scene_tools._merge_c4d_file_core(_FakeDoc(), "cam_w_shakel.c4d")
        assert r["ok"] is True
        assert r["camera_name"] == "W Shakel"  # filename → title-cased label

    def test_merge_failed(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(scene_tools.os.path, "exists", lambda p: True)
        monkeypatch.setattr(scene_tools.c4d.documents, "MergeDocument", lambda *a: None)
        r = scene_tools._merge_c4d_file_core(_FakeDoc(), "nulls.c4d")
        assert r == {"ok": False, "error": "merge_failed"}


class TestMergeOps:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/hierarchy", "panel/tools/vibrate_null",
                    "panel/tools/cam_simple", "panel/tools/cam_shakel"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_merged_into_reports_ops(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert "panel/tools/hierarchy" in reports_dialog._OPS

    def test_hierarchy_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        self._forbid_dialog(monkeypatch)
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_tool_hierarchy({}) == {
            "ok": False, "error": "no_document"}

    def test_cam_simple_passes_filename(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        captured = {}
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: _FakeDoc())
        monkeypatch.setattr(scene_tools, "_merge_c4d_file_core",
                            lambda doc, fn: captured.setdefault("fn", fn) or {"ok": True, "camera_name": "Simple"})
        panel_tools_ops._op_tool_cam_simple({})
        assert captured["fn"] == "cam_simple.c4d"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python3 -m pytest tests/test_panel_tools_ops.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentinel.ui.panel_tools_ops'` (and `_merge_c4d_file_core` missing).

- [ ] **Step 3: Extract `_merge_c4d_file_core` in `scene_tools.py`**

Replace the existing `_merge_c4d_file` (lines ~357-385) with a dialog-free core plus a thin dialog wrapper:
```python
def _merge_c4d_file_core(doc, filename):
    """Dialog-free core of ``_merge_c4d_file`` (Fase 6.4) — merges a bundled
    template .c4d (nulls / vibrate null / camera rigs) into the doc. Returns
    a status dict; NEVER shows a dialog (a MessageDialog inside the panel's
    Timer drain freezes C4D — v1.21.0 pattern)."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    c4d_file = os.path.join(_ROOT, "c4d", filename)
    if not os.path.exists(c4d_file):
        safe_print(f"{filename} not found at: {c4d_file}")
        return {"ok": False, "error": "file_not_found", "filename": filename}
    try:
        merged = c4d.documents.MergeDocument(
            doc, c4d_file, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)
    except Exception as e:
        safe_print(f"Error merging camera file {filename}: {e}")
        return {"ok": False, "error": "merge_error", "detail": str(e)}
    if not merged:
        safe_print(f"Failed to merge {filename}")
        return {"ok": False, "error": "merge_failed"}
    c4d.EventAdd()
    camera_name = filename.replace(".c4d", "").replace("cam_", "").replace("_", " ").title()
    safe_print(f"Merged {camera_name} setup from {filename}")
    return {"ok": True, "camera_name": camera_name}


def _merge_c4d_file(doc, filename):
    """Merge a bundled template .c4d. Thin dialog wrapper over
    ``_merge_c4d_file_core`` — keeps the native MessageDialog UX."""
    result = _merge_c4d_file_core(doc, filename)
    if result.get("error") == "file_not_found":
        c4d.gui.MessageDialog(f"{filename} file not found in c4d folder")
    elif result.get("error") == "merge_error":
        c4d.gui.MessageDialog(f"Error loading camera setup: {result.get('detail')}")
    return result
```
(`_create_hierarchy`, `_create_vibrate_null`, `_merge_camera_file` already delegate to `_merge_c4d_file` — leave them unchanged; they now get the wrapper's behavior transparently.)

- [ ] **Step 4: Create `panel_tools_ops.py` with the merge-based ops + scaffold**

```python
"""panel/tools ops (Fase 6.4) — Tools section of the SPA panel.

Thin adapters over the scene_tools engines. Each tool that shows a
MessageDialog gets a dialog-free ``_<fn>_core`` (a MessageDialog inside the
panel's Timer drain freezes all of C4D — v1.21.0 pattern); the op calls the
core and returns its status dict, which the SPA renders as a toast. Tools
are action-only: no read op, no confirm (nothing destructive)."""
import c4d

from sentinel.ui import scene_tools


def _tool(core_call):
    """Run a tool core against the active document; ``no_document`` when
    there's none. ``core_call`` takes the doc and returns a status dict."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    return core_call(doc)


def _op_tool_hierarchy(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "nulls.c4d"))


def _op_tool_vibrate_null(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "VibrateNull.c4d"))


def _op_tool_cam_simple(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "cam_simple.c4d"))


def _op_tool_cam_shakel(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "cam_w_shakel.c4d"))


PANEL_TOOLS_OPS = {
    "panel/tools/hierarchy": _op_tool_hierarchy,
    "panel/tools/vibrate_null": _op_tool_vibrate_null,
    "panel/tools/cam_simple": _op_tool_cam_simple,
    "panel/tools/cam_shakel": _op_tool_cam_shakel,
}
```

- [ ] **Step 5: Register in `reports_dialog.py`**

Add the import after `from sentinel.ui.panel_deliver_ops import PANEL_DELIVER_OPS`:
```python
from sentinel.ui.panel_tools_ops import PANEL_TOOLS_OPS
```
Add to `_OPS` after `**PANEL_DELIVER_OPS,`:
```python
    **PANEL_TOOLS_OPS,
```

- [ ] **Step 6: Run tests + full suite**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q` → PASS.
Run: `python3 -m pytest -q` → 808 baseline + new, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add plugin/sentinel/ui/scene_tools.py plugin/sentinel/ui/panel_tools_ops.py plugin/sentinel/ui/reports_dialog.py tests/test_panel_tools_ops.py
git commit -m "feat(panel-tools): _merge_c4d_file_core + merge-based tool ops (Fase 6.4)"
```

---

### Task 2: Layer/floor cores + ops (`h_to_layers`, `solo`, `drop_to_floor`)

**Files:**
- Modify: `plugin/sentinel/ui/scene_tools.py` (`_hierarchy_to_layers` ~699, `_solo_layers` ~837, `_drop_to_floor` ~1091)
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py`

**Interfaces:**
- Produces: `_hierarchy_to_layers_core(doc)`, `_solo_layers_core(doc)`, `_drop_to_floor_core(doc)` (contracts in the shared reference above); ops `panel/tools/h_to_layers`, `panel/tools/solo`, `panel/tools/drop_to_floor`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_panel_tools_ops.py` a `TestLayerFloorCores` class. Because these cores do real layer/object walks, test the guard branches (the dialog-free contract) with fake docs, not the full scene work:
```python
class TestLayerFloorCores:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in a *_core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_h_to_layers_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._hierarchy_to_layers_core(None) == {
            "ok": False, "error": "no_document"}

    def test_solo_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._solo_layers_core(None) == {
            "ok": False, "error": "no_document"}

    def test_drop_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._drop_to_floor_core(None) == {
            "ok": False, "error": "no_document"}

    def test_drop_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        assert scene_tools._drop_to_floor_core(_Doc()) == {
            "ok": False, "error": "no_selection"}

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/h_to_layers", "panel/tools/solo",
                    "panel/tools/drop_to_floor"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_drop_op_maps_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: _Doc())
        assert panel_tools_ops._op_tool_drop_to_floor({}) == {
            "ok": False, "error": "no_selection"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_panel_tools_ops.py::TestLayerFloorCores -q`
Expected: FAIL — `_hierarchy_to_layers_core` etc. don't exist.

- [ ] **Step 3: Extract the three cores in `scene_tools.py`**

For EACH of `_hierarchy_to_layers`, `_solo_layers`, `_drop_to_floor`: rename to `_<fn>_core`, apply the extraction rule (every `MessageDialog(...)`+`return` → `return {"ok": False, "error": "<token>"}` per the contracts; every silent early `return` → the matching dict; the terminal `safe_print` success → `return {"ok": True, ...}`); leave the middle scene-work unchanged. Then add a thin wrapper `_<fn>(doc)` that calls the core and re-shows the original dialog text on the tokened errors. Exact token→dialog mapping:

- `_hierarchy_to_layers`: `orphans` → the original multi-line "Found N object(s) outside of null groups…" (reconstruct from `result["count"]`/`result["names"]`); `no_groups` → `"No null groups found in the scene."`. (`no_document`/`no_layer_root` had no dialog — wrapper does nothing for those.)
- `_solo_layers`: `no_layers` → `"No layers found in the scene.\nCreate layers first using Hierarchy→Layers."`; `no_selection` → `"Please select one or more layers to solo."`. (`no_document`/`no_layer_root` silent.) The solo-mode-active branch returns `{"ok": True, "unsolo": True}` after calling `_unsolo_layers(doc)` — unchanged.
- `_drop_to_floor`: `no_selection` had only a `safe_print` (no dialog) — wrapper does nothing; keep the `safe_print`. Success returns `{"ok": True, "dropped": dropped_count}`.

Wrapper shape (example for solo):
```python
def _solo_layers(doc):
    result = _solo_layers_core(doc)
    if result.get("error") == "no_layers":
        c4d.gui.MessageDialog(
            "No layers found in the scene.\nCreate layers first using Hierarchy→Layers.")
    elif result.get("error") == "no_selection":
        c4d.gui.MessageDialog("Please select one or more layers to solo.")
    return result
```

- [ ] **Step 4: Add the three ops in `panel_tools_ops.py`**

```python
def _op_tool_h_to_layers(payload):
    return _tool(scene_tools._hierarchy_to_layers_core)


def _op_tool_solo(payload):
    return _tool(scene_tools._solo_layers_core)


def _op_tool_drop_to_floor(payload):
    return _tool(scene_tools._drop_to_floor_core)
```
Add to `PANEL_TOOLS_OPS`:
```python
    "panel/tools/h_to_layers": _op_tool_h_to_layers,
    "panel/tools/solo": _op_tool_solo,
    "panel/tools/drop_to_floor": _op_tool_drop_to_floor,
```

- [ ] **Step 5: Run tests + full suite**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q` → PASS.
Run: `python3 -m pytest -q` → 0 failures.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/scene_tools.py plugin/sentinel/ui/panel_tools_ops.py tests/test_panel_tools_ops.py
git commit -m "feat(panel-tools): layer/floor cores + ops (Fase 6.4)"
```

---

### Task 3: `abc_retime` + `mark_safe_area` cores + ops

**Files:**
- Modify: `plugin/sentinel/ui/scene_tools.py` (`_toggle_safe_area_mark` ~275, `_apply_abc_retime_tag` ~1253)
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py`

**Interfaces:**
- Produces: `_apply_abc_retime_tag_core(doc)`, `_toggle_safe_area_mark_core(doc)` (contracts above); ops `panel/tools/abc_retime`, `panel/tools/mark_safe_area`.
- Note: `_apply_abc_retime_tag()` currently takes NO doc arg (calls `documents.GetActiveDocument()` itself). The core takes `doc` for testability; the native wrapper `_apply_abc_retime_tag()` keeps its no-arg signature, fetching the doc then calling `_apply_abc_retime_tag_core(doc)`.

- [ ] **Step 1: Write failing tests**

Append `TestAbcMarkCores`:
```python
class TestAbcMarkCores:
    def _forbid_dialog(self, monkeypatch):
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in a *_core")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

    def test_abc_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._apply_abc_retime_tag_core(None) == {
            "ok": False, "error": "no_document"}

    def test_abc_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        assert scene_tools._apply_abc_retime_tag_core(_Doc()) == {
            "ok": False, "error": "no_selection"}

    def test_mark_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)
        assert scene_tools._toggle_safe_area_mark_core(None) == {
            "ok": False, "error": "no_document"}

    def test_mark_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import scene_tools
        self._forbid_dialog(monkeypatch)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        assert scene_tools._toggle_safe_area_mark_core(_Doc()) == {
            "ok": False, "error": "no_selection"}

    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        for key in ("panel/tools/abc_retime", "panel/tools/mark_safe_area"):
            assert key in panel_tools_ops.PANEL_TOOLS_OPS

    def test_mark_op_no_selection(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        from sentinel.ui import scene_tools

        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")

        monkeypatch.setattr(scene_tools.c4d.gui, "MessageDialog", _boom)

        class _Doc:
            def GetActiveObjects(self, flags):
                return []

        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: _Doc())
        assert panel_tools_ops._op_tool_mark_safe_area({})["error"] == "no_selection"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_panel_tools_ops.py::TestAbcMarkCores -q`
Expected: FAIL — cores don't exist.

- [ ] **Step 3: Extract the two cores in `scene_tools.py`**

`_toggle_safe_area_mark_core(doc)`: rename from `_toggle_safe_area_mark(doc, refresh=None)` — DROP the `refresh` param from the core (the op doesn't refresh; the SPA polls). Guards: `no_document`, `no_selection` (per contract). Keep the StartUndo/mark/unmark loop + `check_cache.clear()` unchanged. Terminal: return `{"ok": True, "verb": verb, "marked": marked_count, "unmarked": unmarked_count, "failed": failed_count}`. The native wrapper `_toggle_safe_area_mark(doc, refresh=None)` calls the core, shows the two original dialogs on `no_document`/`no_selection`, and — on success — still calls `refresh()` if provided (the native panel passes one; the op passes nothing):
```python
def _toggle_safe_area_mark(doc, refresh=None):
    result = _toggle_safe_area_mark_core(doc)
    if result.get("error") == "no_document":
        c4d.gui.MessageDialog("No active document.")
    elif result.get("error") == "no_selection":
        c4d.gui.MessageDialog(
            "Select one or more objects first, then click again.\n\n"
            "Tip: mark important compositional elements (logo, title, "
            "character) so QC #12 can verify they stay inside the safe "
            "area of every multi-format delivery Take.")
    elif result.get("ok") and refresh is not None:
        try:
            refresh()
        except Exception:
            pass
    return result
```
NOTE: move the `check_cache.clear()` call INTO the core (it's not a dialog and the op needs the cache invalidated so the SPA's next QC read is fresh); drop only the `refresh()` call from the core.

`_apply_abc_retime_tag_core(doc)`: extract from `_apply_abc_retime_tag()` — take `doc` as a param. Guards: `no_document`, `no_selection`. Keep the per-object tag loop + `EventAdd`. Terminal: if `applied_count == 0 and skipped_count == 0` → `return {"ok": False, "error": "apply_failed"}`; else `return {"ok": True, "applied": applied_count, "skipped": skipped_count, "failed": failed_count}`. The native wrapper:
```python
def _apply_abc_retime_tag():
    doc = documents.GetActiveDocument()
    result = _apply_abc_retime_tag_core(doc)
    if result.get("error") == "no_document":
        c4d.gui.MessageDialog("No active document")
    elif result.get("error") == "no_selection":
        c4d.gui.MessageDialog("Please select an object first\n\n(Works with Alembic, Point Cache, Mograph Cache, or X-Particles Cache objects)")
    elif result.get("error") == "apply_failed":
        c4d.gui.MessageDialog("ABC Retime tag could not be applied\n\nPossible reasons:\n- ABC Retime plugin not installed\n- Invalid object type\n\nManual access: Right-click Tags → Extensions → Alembic Retime")
    return result
```

- [ ] **Step 4: Add the two ops**

```python
def _op_tool_abc_retime(payload):
    return _tool(scene_tools._apply_abc_retime_tag_core)


def _op_tool_mark_safe_area(payload):
    return _tool(scene_tools._toggle_safe_area_mark_core)
```
Add to `PANEL_TOOLS_OPS`:
```python
    "panel/tools/abc_retime": _op_tool_abc_retime,
    "panel/tools/mark_safe_area": _op_tool_mark_safe_area,
```

- [ ] **Step 5: Run tests + full suite**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q` → PASS.
Run: `python3 -m pytest -q` → 0 failures.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/scene_tools.py plugin/sentinel/ui/panel_tools_ops.py tests/test_panel_tools_ops.py
git commit -m "feat(panel-tools): abc_retime + mark_safe_area cores + ops (Fase 6.4)"
```

---

### Task 4: Parity ops — `open_settings` + `open_external`

**Files:**
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py`

**Interfaces:**
- Produces: ops `panel/tools/open_settings`, `panel/open_external`.
- `panel/open_external {target}` — `target ∈ {"github", "bug"}`. URLs (verbatim from `panel.py:2238`/`2244`): github `https://github.com/jmcodex93/sentinel`, bug `https://github.com/jmcodex93/sentinel/issues/new`. Opens via `webbrowser.open` (non-blocking OS launch; safe in the drain). Unknown target → `{ok:False, error:"bad_target"}`.
- `panel/tools/open_settings` — `open_form(doc, "form/settings")` (the SPA Settings page, App.tsx `form/settings`); `{ok:False, error:"no_document"}` when none.

- [ ] **Step 1: Write failing tests**

Append `TestParityOps`:
```python
class TestParityOps:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_tools_ops
        assert "panel/tools/open_settings" in panel_tools_ops.PANEL_TOOLS_OPS
        assert "panel/open_external" in panel_tools_ops.PANEL_TOOLS_OPS

    def test_open_external_github(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        opened = {}
        monkeypatch.setattr(panel_tools_ops.webbrowser, "open",
                            lambda url: opened.setdefault("url", url))
        assert panel_tools_ops._op_open_external({"target": "github"}) == {"ok": True}
        assert opened["url"] == "https://github.com/jmcodex93/sentinel"

    def test_open_external_bug(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        opened = {}
        monkeypatch.setattr(panel_tools_ops.webbrowser, "open",
                            lambda url: opened.setdefault("url", url))
        panel_tools_ops._op_open_external({"target": "bug"})
        assert opened["url"] == "https://github.com/jmcodex93/sentinel/issues/new"

    def test_open_external_bad_target(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        monkeypatch.setattr(panel_tools_ops.webbrowser, "open",
                            lambda url: (_ for _ in ()).throw(AssertionError("must not open")))
        assert panel_tools_ops._op_open_external({"target": "nope"}) == {
            "ok": False, "error": "bad_target"}

    def test_open_settings_no_document(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_tools_ops
        monkeypatch.setattr(panel_tools_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        assert panel_tools_ops._op_open_settings({}) == {
            "ok": False, "error": "no_document"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_panel_tools_ops.py::TestParityOps -q`
Expected: FAIL — ops + `webbrowser` import missing.

- [ ] **Step 3: Implement the parity ops**

Add `import webbrowser` at the top of `panel_tools_ops.py` (alongside `import c4d`). Then:
```python
_EXTERNAL_URLS = {
    "github": "https://github.com/jmcodex93/sentinel",
    "bug": "https://github.com/jmcodex93/sentinel/issues/new",
}


def _op_open_external(payload):
    """Open a fixed help URL in the OS browser (GitHub / Report Bug).
    ``webbrowser.open`` is a non-blocking OS launch — safe in the drain."""
    target = (payload or {}).get("target")
    url = _EXTERNAL_URLS.get(target)
    if not url:
        return {"ok": False, "error": "bad_target"}
    webbrowser.open(url)
    return {"ok": True}


def _op_open_settings(payload):
    """Open the Settings form page in its own window (mirrors the native
    footer Settings button)."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    try:
        from sentinel.ui.reports_dialog import open_form
        open_form(doc, "form/settings")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}
```
Add to `PANEL_TOOLS_OPS`:
```python
    "panel/tools/open_settings": _op_open_settings,
    "panel/open_external": _op_open_external,
```

- [ ] **Step 4: Run tests + full suite**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q` → PASS.
Run: `python3 -m pytest -q` → 0 failures.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/panel_tools_ops.py tests/test_panel_tools_ops.py
git commit -m "feat(panel-tools): parity ops open_settings + open_external (Fase 6.4)"
```

---

### Task 5: SPA — ToolsSection + rail footer + wiring

**Files:**
- Create: `web/src/lib/panelTools.ts` (+ `web/src/lib/panelTools.test.ts`)
- Modify: `web/src/types.ts`
- Modify: `web/src/lib/api.ts`
- Create: `web/src/components/panel/ToolsSection.tsx`
- Modify: `web/src/components/panel/PanelRail.tsx`
- Modify: `web/src/pages/PanelPage.tsx`

**Interfaces:**
- Produces (types.ts): `export interface PanelToolResult { ok: boolean; error?: string; detail?: string; camera_name?: string; dropped?: number; soloed?: number; unsolo?: boolean; created?: number; updated?: number; nulls?: number; applied?: number; skipped?: number; failed?: number; marked?: number; unmarked?: number; verb?: string; }`
- Produces (panelTools.ts): `export interface ToolDef { id: string; label: string } ` and `export const TOOL_GROUPS: { title: string; tools: ToolDef[] }[]` — the 4 native groups (Layout & Hierarchy: hierarchy/h_to_layers/solo/drop_to_floor; Animation: vibrate_null/abc_retime/cam_simple/cam_shakel; QC Marking: mark_safe_area; Asset: a special "open_hub" entry). Plus `export function toolToast(id: string, r: PanelToolResult): { message: string; variant: "success" | "warn" }` — maps a tool result to toast copy (success counts where useful; error tokens → human copy).
- Produces (api.ts): `postPanelTool(op: string): Promise<PanelToolResult>` (POST `/api/<op>`, `{}` body), `postPanelOpenExternal(target: "github" | "bug"): Promise<{ok:boolean; error?:string}>`, `postPanelOpenSettings(): Promise<{ok:boolean; error?:string}>`; mocks return `{ok:true}`.

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/panelTools.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { TOOL_GROUPS, toolToast } from "./panelTools";

describe("TOOL_GROUPS", () => {
  it("has the four native groups", () => {
    expect(TOOL_GROUPS.map((g) => g.title)).toEqual([
      "Layout & Hierarchy", "Animation", "QC Marking", "Asset",
    ]);
  });
  it("Layout group has the four hierarchy tools", () => {
    const ids = TOOL_GROUPS[0].tools.map((t) => t.id);
    expect(ids).toEqual([
      "panel/tools/hierarchy", "panel/tools/h_to_layers",
      "panel/tools/solo", "panel/tools/drop_to_floor",
    ]);
  });
});

describe("toolToast", () => {
  it("success with a count reads naturally", () => {
    const t = toolToast("panel/tools/drop_to_floor", { ok: true, dropped: 3 });
    expect(t.variant).toBe("success");
    expect(t.message).toContain("3");
  });
  it("no_selection → warn with actionable copy", () => {
    const t = toolToast("panel/tools/abc_retime", { ok: false, error: "no_selection" });
    expect(t.variant).toBe("warn");
    expect(t.message.toLowerCase()).toContain("select");
  });
  it("file_not_found → warn", () => {
    const t = toolToast("panel/tools/cam_simple", { ok: false, error: "file_not_found" });
    expect(t.variant).toBe("warn");
  });
  it("mark toggle reports marked vs unmarked", () => {
    expect(toolToast("panel/tools/mark_safe_area", { ok: true, verb: "Marked", marked: 2 }).message)
      .toContain("2");
  });
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd web && npx vitest run src/lib/panelTools.test.ts`
Expected: FAIL — cannot resolve `./panelTools`.

- [ ] **Step 3: Add the type + panelTools.ts**

Add `PanelToolResult` to `web/src/types.ts` (shape above). Create `web/src/lib/panelTools.ts`:
```ts
import type { PanelToolResult } from "../types";

export interface ToolDef {
  id: string;
  label: string;
}

/** The Tools section mirrors the native panel's four groups. "Asset" opens
 * the Hub window (via the existing `open_hub` palette action, not a
 * `panel/tools/*` op) — flagged by the `open_hub` sentinel id. */
export const TOOL_GROUPS: { title: string; tools: ToolDef[] }[] = [
  {
    title: "Layout & Hierarchy",
    tools: [
      { id: "panel/tools/hierarchy", label: "Hierarchy" },
      { id: "panel/tools/h_to_layers", label: "H → Layers" },
      { id: "panel/tools/solo", label: "Solo Layers" },
      { id: "panel/tools/drop_to_floor", label: "Drop to Floor" },
    ],
  },
  {
    title: "Animation",
    tools: [
      { id: "panel/tools/vibrate_null", label: "Vibrate Null" },
      { id: "panel/tools/abc_retime", label: "ABC Retime" },
      { id: "panel/tools/cam_simple", label: "Cam Simple" },
      { id: "panel/tools/cam_shakel", label: "Cam Shakel" },
    ],
  },
  {
    title: "QC Marking",
    tools: [{ id: "panel/tools/mark_safe_area", label: "Mark / Unmark Safe Area Subject" }],
  },
  {
    title: "Asset",
    tools: [{ id: "open_hub", label: "Asset Hub" }],
  },
];

const ERROR_COPY: Record<string, string> = {
  no_document: "No active document.",
  no_selection: "Select one or more objects first.",
  no_layers: "No layers found — create them with H → Layers first.",
  no_groups: "No null groups found in the scene.",
  orphans: "Some objects sit outside null groups — organize them first.",
  file_not_found: "Template file not found in the plugin's c4d folder.",
  merge_failed: "Couldn't merge the template.",
  merge_error: "Error loading the template.",
  apply_failed: "ABC Retime tag couldn't be applied (plugin installed? valid object?).",
  bad_target: "Unknown link.",
};

/** Tool result → toast. Success uses a count when the op returns one; errors
 * map to actionable copy (mirroring the native MessageDialog intent). */
export function toolToast(id: string, r: PanelToolResult): { message: string; variant: "success" | "warn" } {
  if (!r.ok) {
    return { message: ERROR_COPY[r.error ?? ""] ?? "Couldn't run that tool.", variant: "warn" };
  }
  if (id === "panel/tools/drop_to_floor" && typeof r.dropped === "number") {
    return { message: `Dropped ${r.dropped} object${r.dropped === 1 ? "" : "s"} to floor.`, variant: "success" };
  }
  if (id === "panel/tools/solo") {
    return { message: r.unsolo ? "Restored all layers." : `Soloed ${r.soloed ?? 0} layer(s).`, variant: "success" };
  }
  if (id === "panel/tools/mark_safe_area") {
    const n = r.verb === "Unmarked" ? r.unmarked : r.marked;
    return { message: `${r.verb ?? "Marked"} ${n ?? 0} object(s) as Safe Area Subject(s).`, variant: "success" };
  }
  if (id === "panel/tools/h_to_layers") {
    return { message: `Synced layers: ${r.created ?? 0} new, ${r.updated ?? 0} updated.`, variant: "success" };
  }
  if ((id === "panel/tools/cam_simple" || id === "panel/tools/cam_shakel" || id === "panel/tools/hierarchy" || id === "panel/tools/vibrate_null") && r.camera_name) {
    return { message: `Merged ${r.camera_name}.`, variant: "success" };
  }
  if (id === "panel/tools/abc_retime") {
    return { message: `ABC Retime: ${r.applied ?? 0} applied, ${r.skipped ?? 0} skipped.`, variant: "success" };
  }
  return { message: "Done.", variant: "success" };
}
```

- [ ] **Step 4: Add API clients + mocks in `api.ts`**

Add `PanelToolResult` to the type imports. Then (near the other panel clients):
```ts
/** `POST /api/panel/tools/<id>` — run a Tools action; returns a status dict
 * the SPA turns into a toast (see `toolToast`). */
export async function postPanelTool(op: string): Promise<PanelToolResult> {
  if (isMock()) return { ok: true };
  return postForm<PanelToolResult>(`/api/${op}`, {});
}

/** `POST /api/panel/open_external` — GitHub / Report Bug. */
export async function postPanelOpenExternal(
  target: "github" | "bug",
): Promise<{ ok: boolean; error?: string }> {
  if (isMock()) return { ok: true };
  return postForm<{ ok: boolean; error?: string }>("/api/panel/open_external", { target });
}

/** `POST /api/panel/tools/open_settings` — open the Settings window. */
export async function postPanelOpenSettings(): Promise<{ ok: boolean; error?: string }> {
  if (isMock()) return { ok: true };
  return postForm<{ ok: boolean; error?: string }>("/api/panel/tools/open_settings", {});
}
```

- [ ] **Step 5: Create `ToolsSection.tsx`**

```tsx
import { Button } from "../form/Button";
import { TOOL_GROUPS, toolToast } from "../../lib/panelTools";

/** Tools section (Fase 6.4) — grouped action buttons mirroring the native
 * Tools tab. Action-only: each button runs its op and toasts the result;
 * no read state, no confirm (nothing destructive). "Asset Hub" opens the
 * Hub window via the `open_hub` palette action instead of a tools op. */
export function ToolsSection({
  busy,
  onRunTool,
  onOpenHub,
}: {
  busy: string | null;
  onRunTool: (id: string) => void;
  onOpenHub: () => void;
}) {
  const isBusy = busy !== null;
  return (
    <div className="flex flex-col gap-3 p-3">
      {TOOL_GROUPS.map((group) => (
        <div
          key={group.title}
          className="flex flex-col gap-2 rounded-lg border p-3"
          style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
        >
          <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
            {group.title.toUpperCase()}
          </p>
          <div className="flex flex-wrap gap-2">
            {group.tools.map((tool) => (
              <Button
                key={tool.id}
                variant="secondary"
                disabled={isBusy}
                onClick={() => (tool.id === "open_hub" ? onOpenHub() : onRunTool(tool.id))}
              >
                {tool.label}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
```
Suppress the unused `toolToast` import if the toast is applied in PanelPage (below) — import `toolToast` only where used. (If ToolsSection doesn't call it, don't import it here.)

- [ ] **Step 6: Wire into `PanelPage.tsx`**

- Import `ToolsSection`, `postPanelTool`, `postPanelOpenExternal`, `postPanelOpenSettings`, `toolToast`, `runPaletteAction`.
- Add a `busyTool` state (or reuse the existing per-section busy pattern) and a handler:
```tsx
async function handleRunTool(id: string) {
  setBusyTool(id);
  const r = await postPanelTool(id);
  setBusyTool(null);
  const t = toolToast(id, r);
  toast({ message: t.message, variant: t.variant });
}
```
- Render the section (replace the tools placeholder, remove `tools` from `PLACEHOLDER_DEEP_LINKS` if present):
```tsx
{section === "tools" && (
  <ToolsSection
    busy={busyTool}
    onRunTool={handleRunTool}
    onOpenHub={() => runPaletteAction("open_hub")}
  />
)}
```
- Pass footer handlers to `PanelRail` (next step): `onSettings={() => postPanelOpenSettings()}`, `onDoctor={() => runPaletteAction("open_reports_doctor")}`, `onGithub={() => postPanelOpenExternal("github")}`, `onBug={() => postPanelOpenExternal("bug")}`.

- [ ] **Step 7: Add the rail footer in `PanelRail.tsx`**

Extend `PanelRail`'s props with `onSettings`, `onDoctor`, `onGithub`, `onBug` (all `() => void`). Replace the static "acciones" footer block with a small vertical stack of footer buttons (Settings, Doctor, GitHub, Report Bug) plus the existing Command-palette hint, adaptive (icon-only <560px via `isSidebar`, labeled ≥560px) — reuse the existing footer markup style. Use `lucide-react` icons already available (e.g. `Settings`, `Stethoscope`/`Activity`, `Github`, `Bug`). Each button calls its handler; keep them `title`-tooltipped for the icon-only mode.

- [ ] **Step 8: Run tests + typecheck**

Run: `cd web && npx vitest run src/lib/panelTools.test.ts` → PASS.
Run: `npx vitest run` → 106 baseline + new, all pass.
Run: `npx tsc -b --noEmit` → clean.

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/panelTools.ts web/src/lib/panelTools.test.ts web/src/types.ts web/src/lib/api.ts web/src/components/panel/ToolsSection.tsx web/src/components/panel/PanelRail.tsx web/src/pages/PanelPage.tsx
git commit -m "feat(panel-spa): ToolsSection + rail footer (Settings/Doctor/Help) (Fase 6.4)"
```

---

### Task 6: Delete dead code (`collect_scene`, `TextureRepathingDialog`)

**Files:**
- Modify: `plugin/sentinel/ui/flows.py` (delete `collect_scene`, ~478)
- Modify: `plugin/sentinel/ui/dialogs.py` (delete `TextureRepathingDialog` class ~1070 + its launcher function)

**Interfaces:** none (removal).

- [ ] **Step 1: Confirm no live callers**

Run:
```bash
cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian"
grep -rn "\.collect_scene(\|flows\.collect_scene\| collect_scene(" plugin/ tests/ | grep -v "run_collect_pipeline\|def collect_scene\|# \|\"\"\""
grep -rn "TextureRepathingDialog(" plugin/ tests/ | grep -v "class TextureRepathingDialog"
```
Expected: the only `collect_scene(` hits are inside its own body / comments; the only `TextureRepathingDialog(` hit is its own launcher (the one you're deleting). If any OTHER live caller appears, STOP and report — do not delete.

- [ ] **Step 2: Delete `collect_scene` from `flows.py`**

Remove the entire `def collect_scene(doc, artist_name):` function body (~478 to its end). Leave `run_collect_pipeline` and every other symbol untouched. Do NOT edit the prose comments elsewhere that mention `collect_scene` by name (historical references, harmless).

- [ ] **Step 3: Delete `TextureRepathingDialog` from `dialogs.py`**

Remove the `class TextureRepathingDialog(gui.GeDialog):` class (from ~1070 to the end of the class) AND its launcher function (the standalone function that does `dlg = TextureRepathingDialog(doc)` — identify its `def` and remove the whole function). Leave `AssetHubDialog` and its comment references to the old dialog untouched.

- [ ] **Step 4: Verify nothing broke**

Run: `python3 -m pytest -q`
Expected: 0 failures (the deleted symbols had no test coverage and no live callers).
Run:
```bash
python3 -c "import ast; ast.parse(open('plugin/sentinel/ui/flows.py').read()); ast.parse(open('plugin/sentinel/ui/dialogs.py').read()); print('parse OK')"
```
Expected: `parse OK` (both files still parse).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/flows.py plugin/sentinel/ui/dialogs.py
git commit -m "chore: delete dead collect_scene + TextureRepathingDialog (Fase 6.4)"
```

---

### Task 7: Build, version bump, docs

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION`)
- Rebuild: `plugin/web/`
- Modify: `CLAUDE.md`, `.superpowers/sdd/progress.md`, memory

- [ ] **Step 1: Bump version**

`plugin/sentinel/__init__.py`: `PLUGIN_VERSION = "1.22.0"` → `PLUGIN_VERSION = "1.23.0"`.

- [ ] **Step 2: Build the SPA**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian/web" && npm run build`
Expected: `tsc -b && vite build` completes; `plugin/web/assets/` updated with a new hashed bundle.

- [ ] **Step 3: Run both suites**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python3 -m pytest -q` → 0 failures.
Run: `cd web && npx vitest run` → 0 failures.

- [ ] **Step 4: Update docs**

- `CLAUDE.md`: header version → v1.23.0; add a "What Works" bullet for the Tools section + rail-footer parity; add a v1.23.0 Version History entry (note native panel still present, retirement is 6.5).
- `.superpowers/sdd/progress.md`: append the Fase 6.4 ledger lines.
- Memory `project_overview.md` + `MEMORY.md`: mark 6.4 done, 6.5 (retire native + delete panel.py/user_areas) as the only remaining phase.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/__init__.py plugin/web CLAUDE.md .superpowers/sdd/progress.md
git commit -m "chore: build + v1.23.0 — panel SPA Tools section + parity (Fase 6.4)"
```

---

## Self-Review

**Spec coverage:**
- Tools section (4 groups, action-only, toasts) → Tasks 1–3 (cores+ops) + Task 5 (SPA). ✓
- Dialog-free cores + `_forbid_dialog` → Tasks 1–3. ✓
- Parity (Settings/Doctor/Help in rail footer) → Task 4 (ops) + Task 5 (rail footer; Doctor reuses `open_reports_doctor`). ✓
- No read op / no confirm / not destructive → ops have no confirm; ToolsSection has no fetch. ✓
- Dead-code deletion (collect_scene, TextureRepathingDialog) → Task 6. ✓
- Native panel untouched → no task edits `panel.py`/`user_areas.py`/`YSPanelCmd`. ✓
- Version bump + docs → Task 7. ✓

**Placeholder scan:** No TBD/TODO. Long cores (solo/h_to_layers/drop_to_floor) are transformed in place via the explicit extraction rule + exact token→dialog mapping, not re-transcribed — the implementer edits the existing function with the contract pinned by tests. `_merge_c4d_file_core` (the shared, representative core) is given in full.

**Type consistency:** `PanelToolResult` (Task 5) is a superset covering every core's success keys (Task 1–3 contracts: camera_name/dropped/soloed/unsolo/created/updated/nulls/applied/skipped/failed/marked/unmarked/verb). Op keys `panel/tools/<id>` match between `PANEL_TOOLS_OPS` (Python), `TOOL_GROUPS` ids (TS), and `postPanelTool` calls. `open_hub`/`open_reports_doctor` are existing palette ids reused via `runPaletteAction` (not new ops). `panel/open_external` target union `"github"|"bug"` matches `_EXTERNAL_URLS` keys.
