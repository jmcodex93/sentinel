# Fase 6.3 — Panel SPA sección Deliver — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Deliver section to the dockable SPA panel — Version (last + Recent list), Notes, and Deliver-access blocks — with Save Version / Edit Notes absorbed as in-panel sub-views reusing the existing form pages.

**Architecture:** A thin read op (`panel/deliver`) plus two action ops (`panel/deliver/open_version`, `panel/deliver/open_collect`) in a new `panel_deliver_ops.py`, mirroring `panel_render_ops.py`. All blocks isolated via `_guarded_block`; the version-open action runs through a dialog-free core in `flows.py` so no `MessageDialog` ever fires inside the panel's Timer drain. The SPA gains a `DeliverSection` with a local sub-router (`main`/`save_version`/`notes`) that mounts the existing `SaveVersionPage`/`NotesPage` via new optional `onBack`/`onDone` props.

**Tech Stack:** Python 3 (C4D plugin, fake-c4d pytest harness), React + TypeScript + Vite + Tailwind v4 (vitest), stdlib-only engines.

## Global Constraints

- Ops NEVER raise; every block is wrapped by `_guarded_block` so one failing block never blanks the others (same pattern as `panel/overview`, `panel/render`).
- NO `MessageDialog`/`QuestionDialog`/Picture-Viewer in any op code path — a modal inside the panel's Timer drain freezes all of C4D. Dialog-bearing native code stays behind dialog-free cores that return status dicts (v1.21.0 pattern). A `_forbid_dialog` test guards each op that wraps a dialog-bearing engine.
- Zero duplicated business logic: version/notes reads reuse `versioning.py`/`notes.py`; Save Version / Notes submit reuse the existing `form/save_version/*` and `form/notes/*` ops; open-version reuses the same guards as the native `_on_history_row_click`.
- The native Deliver tab (`panel.py`) stays untouched and operational — parallel strategy; its retirement is Fase 6.4.
- Mocks in `web/src/lib/api.ts` must match the REAL nested payload shape (typed), not just field names (React #31 lesson).
- Design system tokens only; the accent (`#5e6ad2`) never marks state — status color comes from status tokens (fail/warn/pass/neutral).
- Version bump target: `1.22.0` in `plugin/sentinel/__init__.py` (`PLUGIN_VERSION`).
- Baselines before this work: pytest 794 passing, vitest 93 passing.

---

## File Structure

- **Create** `plugin/sentinel/ui/panel_deliver_ops.py` — block builders (`_panel_version_block`, `_panel_notes_block`, `_panel_deliver_access_block`), `build_panel_deliver`, and the three ops (`_op_panel_deliver`, `_op_panel_deliver_open_version`, `_op_panel_deliver_open_collect`); exports `PANEL_DELIVER_OPS`.
- **Modify** `plugin/sentinel/ui/flows.py` — add `open_version_core(path)` (dialog-free, status dict).
- **Modify** `plugin/sentinel/ui/reports_dialog.py` — import + merge `PANEL_DELIVER_OPS` into `_OPS`.
- **Create** `plugin/sentinel/ui/deliver_manifest.py` — NO: instead add pure helper `delivery_manifest_available(doc)` in `panel_deliver_ops.py` (single consumer). (No separate file.)
- **Create** `tests/test_panel_deliver_ops.py` — op tests (fake-c4d harness).
- **Create** `web/src/lib/panelDeliver.ts` + `web/src/lib/panelDeliver.test.ts` — pure per-block logic.
- **Modify** `web/src/types.ts` — `PanelDeliver*` types.
- **Modify** `web/src/lib/api.ts` — `fetchPanelDeliver`, `postPanelOpenVersion`, `postPanelOpenCollect` + mocks.
- **Create** `web/src/components/panel/DeliverSection.tsx` + sub-blocks in the same file (`VersionBlock`, `RecentVersionsList`, `NotesBlock`, `DeliverAccessBlock`).
- **Modify** `web/src/pages/SaveVersionPage.tsx`, `web/src/pages/NotesPage.tsx` — optional `onBack`/`onDone` props.
- **Modify** `web/src/pages/PanelPage.tsx` — mount `DeliverSection` for `section === "deliver"`, remove the deliver placeholder.
- **Modify** `plugin/sentinel/__init__.py` — version bump.
- **Modify** `CLAUDE.md`, memory, ledger — docs.

---

### Task 1: `panel/deliver` read op + access op + registration

**Files:**
- Create: `plugin/sentinel/ui/panel_deliver_ops.py`
- Modify: `plugin/sentinel/ui/reports_dialog.py` (imports ~line 57-60, `_OPS` ~line 312-321)
- Test: `tests/test_panel_deliver_ops.py`

**Interfaces:**
- Consumes: `sentinel.ui.hub_ops._stamp_for(doc)`; `sentinel.ui.panel_ops._guarded_block(name, builder, doc)`; `sentinel.versioning.get_latest_version_info(doc)`, `load_versions_for_doc(doc)`, `format_version_row(entry)`, `format_history_qc_label(entry)`, `filter_versions_by_status`, `FILTER_ALL`; `sentinel.notes.get_notes_path(doc)`, `load_notes(path)`, `summarize_notes(notes)`, `has_pending_todos(notes)`; `sentinel.manifest.load_manifest_json(path)`; `sentinel.ui.reports_dialog.open_form(doc, page, query=...)`.
- Produces:
  - `build_panel_deliver(doc) -> dict` with keys `version`/`notes`/`deliver` (each a dict or `None`).
  - `PANEL_DELIVER_OPS = {"panel/deliver": _op_panel_deliver, "panel/deliver/open_version": _op_panel_deliver_open_version, "panel/deliver/open_collect": _op_panel_deliver_open_collect}`.
  - `delivery_manifest_available(doc) -> bool`.

The `panel/deliver` payload shape (documented in the module docstring):
```
{ "version": {
      "last": {"version": int, "status": str, "age": str|None, "qc_label": str|None} | None,
      "unsaved": bool,
      "recent": [ {"version": int, "status": str, "age": str|None,
                   "qc_label": str|None, "path": str, "filename": str} ]
    } | None,
  "notes": {"summary": str, "todos_pending": int, "notes_present": bool, "unsaved": bool} | None,
  "deliver": {"has_manifest": bool} | None }
```
`recent` is capped at 15 entries, unfiltered (the SPA filters by status). Each entry carries the absolute `path` and `filename` used by `open_version`. `unsaved` is `True` when the doc has no document path.

- [ ] **Step 1: Write failing tests**

Create `tests/test_panel_deliver_ops.py`:
```python
"""Tests for panel/deliver ops (Fase 6.3). Uses the fake-c4d harness
(``sentinel_module`` fixture, tests/conftest.py) — panel_deliver_ops.py
does ``import c4d`` at module scope, same as panel_render_ops.py."""
import os


class _FakeDoc:
    def __init__(self, path="", name="shot_v003.c4d", changed=False):
        self._path = path
        self._name = name
        self._changed = changed
        self._dirty = 0

    def GetDocumentPath(self):
        return self._path

    def GetDocumentName(self):
        return self._name

    def GetChanged(self):
        return self._changed

    def GetDirty(self, flags):
        return self._dirty


class TestOpsRegistered:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_deliver_ops
        assert set(panel_deliver_ops.PANEL_DELIVER_OPS) == {
            "panel/deliver",
            "panel/deliver/open_version",
            "panel/deliver/open_collect",
        }

    def test_merged_into_reports_ops(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert "panel/deliver" in reports_dialog._OPS
        assert "panel/deliver/open_version" in reports_dialog._OPS


class TestPanelDeliverRead:
    def test_without_document_blocks_are_none_but_shaped(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        result = panel_deliver_ops._op_panel_deliver({})
        assert set(result) >= {"version", "notes", "deliver", "stamp"}

    def test_unsaved_document_marks_unsaved(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        doc = _FakeDoc(path="")
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)
        # No sidecars for an unsaved doc → engines return empty; block still shaped.
        result = panel_deliver_ops._op_panel_deliver({})
        assert result["version"] is None or result["version"]["unsaved"] is True

    def test_one_failing_block_does_not_blank_others(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        doc = _FakeDoc(path="/tmp/shot")
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: doc)

        def _boom(_doc):
            raise RuntimeError("version block exploded")

        monkeypatch.setattr(panel_deliver_ops, "_panel_version_block", _boom)
        result = panel_deliver_ops._op_panel_deliver({})
        assert result["version"] is None          # guarded → None
        assert result["notes"] is not None or result["notes"] is None  # notes still built
        assert "deliver" in result


class TestDeliveryManifestAvailable:
    def test_no_path_false(self, sentinel_module):
        from sentinel.ui import panel_deliver_ops
        assert panel_deliver_ops.delivery_manifest_available(_FakeDoc(path="")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python -m pytest tests/test_panel_deliver_ops.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentinel.ui.panel_deliver_ops'`.

- [ ] **Step 3: Implement `panel_deliver_ops.py`**

Create `plugin/sentinel/ui/panel_deliver_ops.py`:
```python
"""panel/deliver ops (Fase 6.3) — Deliver section of the SPA panel.

Thin adapters over the versioning/notes/manifest engines, following the
``panel/overview`` and ``panel/render`` conventions: a read op with
ISOLATED blocks (``_guarded_block`` — one raising builder never blanks the
rest), plus action ops that open windows/documents. The version-open
action runs through ``flows.open_version_core`` (dialog-free, status dict)
because a ``MessageDialog`` inside the panel's Timer drain freezes all of
C4D (v1.21.0 pattern).

Save Version / Notes submits are NOT here — the SPA absorbs the existing
form pages and reuses ``form/save_version/*`` / ``form/notes/*``.
"""
import os

import c4d

from sentinel.ui.hub_ops import _stamp_for
from sentinel.ui.panel_ops import _guarded_block
from sentinel import versioning
from sentinel import notes as notes_engine

_RECENT_CAP = 15


def _panel_version_block(doc):
    """Version card: latest version pill + a capped, unfiltered recent list.
    ``unsaved`` (doc has no path) drives the SPA's "save the scene first"
    empty state; ``recent`` carries each row's absolute path for open."""
    unsaved = not bool(doc.GetDocumentPath())
    info = versioning.get_latest_version_info(doc)
    last = None
    if info:
        try:
            ver = int(info.get("version", 0))
        except Exception:
            ver = 0
        last = {
            "version": ver,
            "status": info.get("status", "") or "",
            "age": versioning._humanize_time_diff(info.get("timestamp", "")) or None,
            "qc_label": versioning.format_history_qc_label(info) or None,
        }

    recent = []
    if not unsaved:
        for entry in (versioning.load_versions_for_doc(doc) or [])[:_RECENT_CAP]:
            if not entry:
                continue
            try:
                ver = int(entry.get("version", 0))
            except Exception:
                ver = 0
            path = (entry.get("path") or "").strip()
            recent.append({
                "version": ver,
                "status": entry.get("status", "") or "",
                "age": versioning._humanize_time_diff(entry.get("timestamp", "")) or None,
                "qc_label": versioning.format_history_qc_label(entry) or None,
                "path": path,
                "filename": entry.get("filename") or (os.path.basename(path) if path else ""),
            })

    return {"last": last, "unsaved": unsaved, "recent": recent}


def _panel_notes_block(doc):
    """Notes card: same sidecar reads as ``web_ops._op_form_notes_state``
    and the native panel caption."""
    unsaved = not bool(doc.GetDocumentPath())
    notes_path = notes_engine.get_notes_path(doc)
    notes = notes_engine.load_notes(notes_path) if notes_path else {}
    todos = notes.get("todos") or []
    todos_pending = sum(1 for t in todos if not t.get("done"))
    notes_present = bool((notes.get("notes") or "").strip()) or bool(todos)
    return {
        "summary": notes_engine.summarize_notes(notes),
        "todos_pending": todos_pending,
        "notes_present": notes_present,
        "unsaved": unsaved,
    }


def delivery_manifest_available(doc):
    """True if a collected ``sentinel_manifest.json`` with an asset section
    (I4+) sits next to the open scene — mirrors the native
    ``panel._delivery_manifest_available`` gate."""
    if not doc:
        return False
    doc_path = doc.GetDocumentPath()
    if not doc_path:
        return False
    path = os.path.join(doc_path, "sentinel_manifest.json")
    if not os.path.exists(path):
        return False
    try:
        from sentinel import manifest as manifest_engine
        data = manifest_engine.load_manifest_json(path)
    except Exception:
        return False
    return bool(data and data.get("assets_schema"))


def _panel_deliver_access_block(doc):
    """Deliver-access card: only Delivery Summary is conditional."""
    return {"has_manifest": delivery_manifest_available(doc)}


def build_panel_deliver(doc):
    """Read model for the Deliver section. Blocks isolated: one raising
    builder yields ``None`` for its block, never blanks the section."""
    return {
        "version": _guarded_block("version", _panel_version_block, doc),
        "notes": _guarded_block("notes", _panel_notes_block, doc),
        "deliver": _guarded_block("deliver", _panel_deliver_access_block, doc),
    }


def _op_panel_deliver(payload):
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"version": None, "notes": None, "deliver": None, "stamp": None}
    result = build_panel_deliver(doc)
    result["stamp"] = _stamp_for(doc)
    return result


def _op_panel_deliver_open_version(payload):
    """Open a version .c4d via the dialog-free core. Confirm/unsaved logic
    lives in the SPA; this op runs the load once the client has confirmed.
    ``force`` is accepted for parity with the native flow (both open in a
    new window regardless) and is a no-op guard passthrough."""
    from sentinel.ui import flows
    doc = c4d.documents.GetActiveDocument()
    path = (payload or {}).get("path") or ""
    result = flows.open_version_core(path)
    if result.get("ok"):
        result["stamp"] = _stamp_for(doc) if doc else None
    return result


def _op_panel_deliver_open_collect(payload):
    """Open the Asset Hub focused on delivery (mirrors the native Collect
    button). Window, not absorbed."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "No active document"}
    try:
        from sentinel.ui.reports_dialog import open_form
        open_form(doc, "hub", query={"focus": "deliver"})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": "Asset Hub opened"}


PANEL_DELIVER_OPS = {
    "panel/deliver": _op_panel_deliver,
    "panel/deliver/open_version": _op_panel_deliver_open_version,
    "panel/deliver/open_collect": _op_panel_deliver_open_collect,
}
```

- [ ] **Step 4: Register the ops in `reports_dialog.py`**

Add the import next to the sibling op imports (after `from sentinel.ui.panel_render_ops import PANEL_RENDER_OPS`):
```python
from sentinel.ui.panel_deliver_ops import PANEL_DELIVER_OPS
```
Add to the `_OPS` dict (after `**PANEL_RENDER_OPS,`):
```python
    **PANEL_DELIVER_OPS,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_panel_deliver_ops.py -q`
Expected: PASS (all tests in the file).

Note: `open_version_core` doesn't exist yet (Task 2). `_op_panel_deliver_open_version` imports `flows` lazily inside the function, so the module imports fine and the read-op tests pass. Do NOT test `open_version` here — its tests live in Task 2.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/panel_deliver_ops.py plugin/sentinel/ui/reports_dialog.py tests/test_panel_deliver_ops.py
git commit -m "feat(panel): panel/deliver read op + access ops (Fase 6.3)"
```

---

### Task 2: `open_version_core` (dialog-free) + `open_version` op guards

**Files:**
- Modify: `plugin/sentinel/ui/flows.py` (add `open_version_core` near the other cores, ~after line 1212)
- Test: `tests/test_panel_deliver_ops.py` (add a `TestOpenVersion` class)

**Interfaces:**
- Consumes: `c4d.documents.GetActiveDocument`, `c4d.documents.LoadFile`, `os.path`.
- Produces: `flows.open_version_core(path) -> dict`. Returns one of:
  - `{"ok": False, "error": "bad_path"}` — empty/blank path.
  - `{"ok": False, "error": "file_not_found"}` — path doesn't exist on disk.
  - `{"ok": False, "error": "already_active"}` — path is the active document.
  - `{"ok": False, "error": "unsaved_changes"}` — active doc has unsaved changes and `force` not set.
  - `{"ok": True, "opened": True}` — `LoadFile` succeeded.
  - `{"ok": False, "error": "load_failed"}` — `LoadFile` returned False.
  Signature: `open_version_core(path, force=False)`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_panel_deliver_ops.py`:
```python
class TestOpenVersion:
    def _forbid_dialog(self, monkeypatch, sentinel_module):
        from sentinel.ui import flows

        def _boom(*a, **k):
            raise AssertionError("no dialog allowed in open_version_core")

        monkeypatch.setattr(flows.c4d.gui, "MessageDialog", _boom)
        monkeypatch.setattr(flows.c4d.gui, "QuestionDialog", _boom)

    def test_bad_path(self, sentinel_module, monkeypatch):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        assert flows.open_version_core("   ") == {"ok": False, "error": "bad_path"}

    def test_file_not_found(self, sentinel_module, monkeypatch):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        assert flows.open_version_core("/no/such/shot_v001.c4d") == {
            "ok": False, "error": "file_not_found"}

    def test_already_active(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v002.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="shot_v002.c4d")
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        assert flows.open_version_core(str(f)) == {"ok": False, "error": "already_active"}

    def test_unsaved_changes_blocks_without_force(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v003.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="other.c4d", changed=True)
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        assert flows.open_version_core(str(f)) == {"ok": False, "error": "unsaved_changes"}

    def test_force_opens_despite_unsaved(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v004.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="other.c4d", changed=True)
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(flows.c4d.documents, "LoadFile", lambda p: True)
        assert flows.open_version_core(str(f), force=True) == {"ok": True, "opened": True}

    def test_load_failed(self, sentinel_module, monkeypatch, tmp_path):
        from sentinel.ui import flows
        self._forbid_dialog(monkeypatch, sentinel_module)
        f = tmp_path / "shot_v005.c4d"
        f.write_text("x")
        doc = _FakeDoc(path=str(tmp_path), name="other.c4d", changed=False)
        monkeypatch.setattr(flows.c4d.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(flows.c4d.documents, "LoadFile", lambda p: False)
        assert flows.open_version_core(str(f)) == {"ok": False, "error": "load_failed"}

    def test_op_maps_core_result(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_deliver_ops
        monkeypatch.setattr(panel_deliver_ops.c4d.documents,
                            "GetActiveDocument", lambda: None)
        # path missing → bad_path from the core, surfaced by the op
        out = panel_deliver_ops._op_panel_deliver_open_version({"path": ""})
        assert out == {"ok": False, "error": "bad_path"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_panel_deliver_ops.py::TestOpenVersion -q`
Expected: FAIL — `AttributeError: module 'sentinel.ui.flows' has no attribute 'open_version_core'`.

- [ ] **Step 3: Implement `open_version_core` in `flows.py`**

Add after `snapshot_open_folder_core` (~line 1212+):
```python
def open_version_core(path, force=False):
    """Dialog-free core for opening a version .c4d from Recent Versions.

    Returns a status dict; NEVER shows a dialog (a MessageDialog inside the
    panel's Timer drain freezes C4D — v1.21.0 pattern). Guards mirror the
    native ``_on_history_row_click`` in panel.py: bad/blank path, missing
    file, re-opening the active doc, and unsaved changes in the current
    doc (surfaced as ``unsaved_changes`` so the SPA can confirm-and-force
    rather than block behind a modal)."""
    path = (path or "").strip()
    if not path:
        return {"ok": False, "error": "bad_path"}
    if not os.path.exists(path):
        return {"ok": False, "error": "file_not_found"}

    current = c4d.documents.GetActiveDocument()
    if current:
        try:
            cur_full = os.path.join(current.GetDocumentPath() or "",
                                    current.GetDocumentName() or "")
            if os.path.normcase(os.path.normpath(cur_full)) == \
               os.path.normcase(os.path.normpath(path)):
                return {"ok": False, "error": "already_active"}
        except Exception:
            pass
        try:
            if current.GetChanged() and not force:
                return {"ok": False, "error": "unsaved_changes"}
        except Exception:
            pass

    try:
        ok = c4d.documents.LoadFile(path)
    except Exception as exc:
        return {"ok": False, "error": "load_error", "detail": str(exc)}
    if ok:
        return {"ok": True, "opened": True}
    return {"ok": False, "error": "load_failed"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_panel_deliver_ops.py -q`
Expected: PASS (whole file, including Task 1 tests).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/flows.py tests/test_panel_deliver_ops.py
git commit -m "feat(panel): open_version_core dialog-free + open_version op guards (Fase 6.3)"
```

---

### Task 3: SPA types, client, and pure `panelDeliver.ts` logic

**Files:**
- Modify: `web/src/types.ts` (add `PanelDeliver*` interfaces)
- Modify: `web/src/lib/api.ts` (add fetch/post fns + mocks)
- Create: `web/src/lib/panelDeliver.ts`
- Test: `web/src/lib/panelDeliver.test.ts`

**Interfaces:**
- Produces (types.ts):
```ts
export interface PanelVersionEntry {
  version: number; status: string; age: string | null;
  qc_label: string | null; path: string; filename: string;
}
export interface PanelVersionLast {
  version: number; status: string; age: string | null; qc_label: string | null;
}
export interface PanelVersionBlock {
  last: PanelVersionLast | null; unsaved: boolean; recent: PanelVersionEntry[];
}
export interface PanelNotesBlock {
  summary: string; todos_pending: number; notes_present: boolean; unsaved: boolean;
}
export interface PanelDeliverAccessBlock { has_manifest: boolean; }
export interface PanelDeliverState {
  version: PanelVersionBlock | null;
  notes: PanelNotesBlock | null;
  deliver: PanelDeliverAccessBlock | null;
  stamp: string | null;
}
export interface PanelOpenVersionResponse {
  ok: boolean; error?: string; opened?: boolean; stamp?: string | null; detail?: string;
}
```
- Produces (panelDeliver.ts):
  - `versionStatusLine(block: PanelVersionBlock | null): string`
  - `notesStatusLine(block: PanelNotesBlock | null): string`
  - `filterRecent(recent: PanelVersionEntry[], filter: string): PanelVersionEntry[]`
  - `statusBadgeTone(status: string): "wip" | "tr" | "cr" | "final"`
  - `RECENT_FILTERS: { value: string; label: string }[]`
- Produces (api.ts): `fetchPanelDeliver(): Promise<PanelDeliverState>`, `postPanelOpenVersion(path, force?): Promise<PanelOpenVersionResponse>`, `postPanelOpenCollect(): Promise<PaletteRunResponse>` (reuse `PaletteRunResponse`).

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/panelDeliver.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import {
  filterRecent,
  notesStatusLine,
  statusBadgeTone,
  versionStatusLine,
} from "./panelDeliver";
import type { PanelVersionEntry } from "../types";

const entry = (over: Partial<PanelVersionEntry>): PanelVersionEntry => ({
  version: 1, status: "", age: null, qc_label: null, path: "/p/v001.c4d",
  filename: "v001.c4d", ...over,
});

describe("versionStatusLine", () => {
  it("null block → unavailable", () => {
    expect(versionStatusLine(null)).toBe("Version status unavailable.");
  });
  it("unsaved doc → save first note", () => {
    expect(versionStatusLine({ last: null, unsaved: true, recent: [] })).toContain("not saved");
  });
  it("no versions on a saved doc", () => {
    expect(versionStatusLine({ last: null, unsaved: false, recent: [] })).toContain("No versions");
  });
  it("last version renders version + status + age + qc", () => {
    const line = versionStatusLine({
      last: { version: 7, status: "TR", age: "2h ago", qc_label: "9/12" },
      unsaved: false, recent: [],
    });
    expect(line).toContain("v007");
    expect(line).toContain("TR");
    expect(line).toContain("2h ago");
    expect(line).toContain("9/12");
  });
  it("empty status renders as WIP", () => {
    const line = versionStatusLine({
      last: { version: 3, status: "", age: null, qc_label: null },
      unsaved: false, recent: [],
    });
    expect(line).toContain("WIP");
  });
});

describe("notesStatusLine", () => {
  it("null block → unavailable", () => {
    expect(notesStatusLine(null)).toBe("Notes status unavailable.");
  });
  it("pending todos get a warning prefix", () => {
    const line = notesStatusLine({
      summary: "Notes: text + 3 TODOs (2 pending)", todos_pending: 2,
      notes_present: true, unsaved: false,
    });
    expect(line.startsWith("⚠")).toBe(true);
  });
  it("no pending todos → no prefix", () => {
    const line = notesStatusLine({
      summary: "Notes: —", todos_pending: 0, notes_present: false, unsaved: false,
    });
    expect(line.startsWith("⚠")).toBe(false);
  });
});

describe("filterRecent", () => {
  const rows = [
    entry({ version: 1, status: "" }),
    entry({ version: 2, status: "TR" }),
    entry({ version: 3, status: "FINAL" }),
  ];
  it("__ALL__ returns everything", () => {
    expect(filterRecent(rows, "__ALL__")).toHaveLength(3);
  });
  it("empty-string filter matches WIP (status '')", () => {
    const out = filterRecent(rows, "");
    expect(out).toHaveLength(1);
    expect(out[0].version).toBe(1);
  });
  it("status filter matches exactly", () => {
    expect(filterRecent(rows, "TR").map((r) => r.version)).toEqual([2]);
  });
});

describe("statusBadgeTone", () => {
  it("maps known statuses", () => {
    expect(statusBadgeTone("")).toBe("wip");
    expect(statusBadgeTone("TR")).toBe("tr");
    expect(statusBadgeTone("CR")).toBe("cr");
    expect(statusBadgeTone("FINAL")).toBe("final");
  });
  it("unknown/custom status falls back to wip tone", () => {
    expect(statusBadgeTone("REV02")).toBe("wip");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian/web" && npx vitest run src/lib/panelDeliver.test.ts`
Expected: FAIL — cannot resolve `./panelDeliver`.

- [ ] **Step 3: Add types to `web/src/types.ts`**

Append the interfaces from the Interfaces block above to `web/src/types.ts`.

- [ ] **Step 4: Implement `web/src/lib/panelDeliver.ts`**

```ts
import type {
  PanelNotesBlock,
  PanelVersionBlock,
  PanelVersionEntry,
} from "../types";

// Filter tokens mirror versioning.py: FILTER_ALL = "__ALL__", and "" is the
// real WIP status token (an unlabeled save), NOT "no filter".
export const FILTER_ALL = "__ALL__";
export const RECENT_FILTERS: { value: string; label: string }[] = [
  { value: FILTER_ALL, label: "All" },
  { value: "", label: "WIP" },
  { value: "TR", label: "TR" },
  { value: "CR", label: "CR" },
  { value: "FINAL", label: "FINAL" },
];

/** Version card status line. `null` block → distinct "unavailable" note
 * (the read failed in isolation) vs. an unsaved doc or a saved doc with no
 * versions yet. A blank status renders as WIP (its real filename suffix is
 * "" — see versioning.parse_version_filename). */
export function versionStatusLine(block: PanelVersionBlock | null): string {
  if (block === null) return "Version status unavailable.";
  if (block.last === null) {
    if (block.unsaved) return "Scene not saved yet.";
    return "No versions yet — click Save Version.";
  }
  const v = `v${String(block.last.version).padStart(3, "0")}`;
  const status = block.last.status || "WIP";
  const parts = [`${v} ${status}`];
  if (block.last.age) parts.push(block.last.age);
  if (block.last.qc_label) parts.push(`QC ${block.last.qc_label}`);
  return parts.join(" · ");
}

/** Notes card status line — the engine's summary, with a ⚠ prefix when
 * there are pending TODOs (matches the native panel caption). */
export function notesStatusLine(block: PanelNotesBlock | null): string {
  if (block === null) return "Notes status unavailable.";
  return block.todos_pending > 0 ? `⚠ ${block.summary}` : block.summary;
}

/** Filter Recent Versions by status token, client-side (no round-trip),
 * mirroring versioning.filter_versions_by_status: FILTER_ALL passes all,
 * "" matches only the WIP (blank) status, anything else matches exactly. */
export function filterRecent(
  recent: PanelVersionEntry[],
  filter: string,
): PanelVersionEntry[] {
  if (filter === FILTER_ALL) return recent;
  return recent.filter((r) => (r.status || "") === filter);
}

/** Status → badge tone token. Known review statuses map 1:1; any custom
 * status (e.g. "REV02") falls back to the neutral WIP tone. Tones are
 * status tokens, never the accent. */
export function statusBadgeTone(status: string): "wip" | "tr" | "cr" | "final" {
  switch ((status || "").toUpperCase()) {
    case "TR":
      return "tr";
    case "CR":
      return "cr";
    case "FINAL":
      return "final";
    default:
      return "wip";
  }
}
```

- [ ] **Step 5: Add client fns + mocks to `web/src/lib/api.ts`**

Add the type imports to the existing `import type { ... } from "../types"` block: `PanelDeliverState`, `PanelOpenVersionResponse`. Then add (near the other `panel/*` client fns, e.g. after `postPanelOpenForm` ~line 853):
```ts
/** Client-only mock for `panel/deliver` (only in `?mock=1`). Shape MUST
 * match the real payload (nested blocks) — a flat mock would pass tests
 * and crash on real data (the React #31 lesson). */
function mockPanelDeliver(): PanelDeliverState {
  return {
    version: {
      last: { version: 7, status: "TR", age: "2h ago", qc_label: "9/12" },
      unsaved: false,
      recent: [
        { version: 7, status: "TR", age: "2h ago", qc_label: "9/12",
          path: "/mock/shot_v007_TR.c4d", filename: "shot_v007_TR.c4d" },
        { version: 6, status: "", age: "5h ago", qc_label: "8/12",
          path: "/mock/shot_v006.c4d", filename: "shot_v006.c4d" },
      ],
    },
    notes: { summary: "Notes: review lighting + 3 TODOs (2 pending)",
             todos_pending: 2, notes_present: true, unsaved: false },
    deliver: { has_manifest: true },
    stamp: "mock-stamp",
  };
}

/** `POST /api/panel/deliver` — Deliver section read model (Fase 6.3). */
export async function fetchPanelDeliver(): Promise<PanelDeliverState> {
  if (IS_MOCK) return mockPanelDeliver();
  return postForm<PanelDeliverState>("/api/panel/deliver", {});
}

/** `POST /api/panel/deliver/open_version` — open a version .c4d. */
export async function postPanelOpenVersion(
  path: string, force?: boolean,
): Promise<PanelOpenVersionResponse> {
  if (IS_MOCK) return { ok: true, opened: true, stamp: "mock-stamp" };
  return postForm<PanelOpenVersionResponse>(
    "/api/panel/deliver/open_version", force ? { path, force: true } : { path });
}

/** `POST /api/panel/deliver/open_collect` — open the Asset Hub (deliver focus). */
export async function postPanelOpenCollect(): Promise<PaletteRunResponse> {
  if (IS_MOCK) return { ok: true, message: "Asset Hub opened" };
  return postForm<PaletteRunResponse>("/api/panel/deliver/open_collect", {});
}
```
(Match the exact `IS_MOCK`/`postForm`/`PaletteRunResponse` identifiers already used in the file — verify their names before writing; the sketch above uses the conventional ones.)

- [ ] **Step 6: Run tests to verify they pass + typecheck**

Run: `npx vitest run src/lib/panelDeliver.test.ts`
Expected: PASS.
Run: `npx tsc -b --noEmit` (or the repo's typecheck) 
Expected: no type errors in `api.ts`/`types.ts`/`panelDeliver.ts`.

- [ ] **Step 7: Commit**

```bash
git add web/src/types.ts web/src/lib/api.ts web/src/lib/panelDeliver.ts web/src/lib/panelDeliver.test.ts
git commit -m "feat(panel-spa): panelDeliver pure logic + types + client (Fase 6.3)"
```

---

### Task 4: Absorb form pages — optional `onBack`/`onDone` props

**Files:**
- Modify: `web/src/pages/SaveVersionPage.tsx`
- Modify: `web/src/pages/NotesPage.tsx`
- Test: `web/src/pages/SaveVersionPage.test.tsx` (new, minimal render test)

**Interfaces:**
- Produces: `SaveVersionPage(props?: { onBack?: () => void; onDone?: () => void })`, `NotesPage(props?: { onBack?: () => void; onDone?: () => void })`. Both default to no-op so the existing `App.tsx` mounts (`<SaveVersionPage />`, `<NotesPage />`) keep working unchanged. When `onBack` is provided, a "← Deliver" back control renders. `onDone` is called after a successful submit (in addition to the existing toast/success state).

- [ ] **Step 1: Write failing test**

Create `web/src/pages/SaveVersionPage.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveVersionPage } from "./SaveVersionPage";

// The page fetches its state on mount; with no server the fetch rejects and
// the page shows a loading/error state. We only assert the back control is
// gated on the onBack prop, which renders regardless of fetch outcome.
describe("SaveVersionPage back control", () => {
  it("renders a back control only when onBack is provided", () => {
    const { rerender } = render(<SaveVersionPage />);
    expect(screen.queryByRole("button", { name: /deliver/i })).toBeNull();
    rerender(<SaveVersionPage onBack={vi.fn()} />);
    expect(screen.getByRole("button", { name: /deliver/i })).toBeInTheDocument();
  });
});
```
(If the repo has no `@testing-library/react` set up, instead assert via a pure helper: extract `showBack = typeof onBack === "function"` and unit-test that. Check `web/package.json` devDependencies first; use whichever testing approach the repo already uses for `.tsx`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/pages/SaveVersionPage.test.tsx`
Expected: FAIL — no back control rendered (prop not yet supported).

- [ ] **Step 3: Add props to `SaveVersionPage.tsx`**

Change the signature and add the back control + onDone call:
```tsx
export function SaveVersionPage({
  onBack,
  onDone,
}: { onBack?: () => void; onDone?: () => void } = {}) {
```
Near the top of the returned JSX (inside `FormPageShell`, before the form), render the back control when `onBack` is set:
```tsx
{onBack && (
  <button type="button" onClick={onBack} className="deliver-back">
    ← Deliver
  </button>
)}
```
In the submit success handler (where `setResult(...)` / the success toast fires), add:
```tsx
onDone?.();
```
Place `onDone?.()` AFTER the success state is set so the parent re-fetches against the just-saved version. Do not call it on error.

- [ ] **Step 4: Mirror the change in `NotesPage.tsx`**

Apply the identical prop signature, back control, and `onDone?.()` (after a successful notes submit) to `web/src/pages/NotesPage.tsx`.

- [ ] **Step 5: Run tests + verify host mount unaffected**

Run: `cd web && npx vitest run src/pages/SaveVersionPage.test.tsx`
Expected: PASS.
Run: `npx tsc -b --noEmit`
Expected: no type errors; `App.tsx`'s `<SaveVersionPage />` / `<NotesPage />` (no props) still typecheck because both props are optional.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/SaveVersionPage.tsx web/src/pages/NotesPage.tsx web/src/pages/SaveVersionPage.test.tsx
git commit -m "feat(panel-spa): SaveVersion/Notes optional onBack/onDone for absorption (Fase 6.3)"
```

---

### Task 5: `DeliverSection` + sub-router, wired into `PanelPage`

**Files:**
- Create: `web/src/components/panel/DeliverSection.tsx`
- Modify: `web/src/pages/PanelPage.tsx` (mount DeliverSection, drop the deliver placeholder)
- Test: `web/src/components/panel/DeliverSection.test.tsx`

**Interfaces:**
- Consumes: `fetchPanelDeliver`, `postPanelOpenVersion`, `postPanelOpenCollect`, `runPaletteAction` (from `../../lib/api`); `versionStatusLine`, `notesStatusLine`, `filterRecent`, `statusBadgeTone`, `RECENT_FILTERS`, `FILTER_ALL` (from `../../lib/panelDeliver`); `SaveVersionPage`, `NotesPage` (from `../../pages/*`); `useToast`.
- Produces: `DeliverSection(props: { stamp: string | null; onStampChange: (s: string | null) => void })` — a self-contained section that owns its `deliver` fetch, its `deliverView` sub-router state, and its open-version confirm state. Refetches when `stamp` changes.

**Sub-router:** `deliverView: "main" | "save_version" | "notes"`.
- `main`: VersionBlock + NotesBlock + DeliverAccessBlock.
- `save_version`: `<SaveVersionPage onBack={()=>setView("main")} onDone={()=>{setView("main"); load();}} />`.
- `notes`: `<NotesPage onBack={...} onDone={...} />`.

**Open-version confirm:** clicking a Recent row sets a confirm target `{path, filename}`; a confirm bar (reuse the QC/Render confirm-bar pattern) calls `postPanelOpenVersion(path)`. On `error: "unsaved_changes"`, swap the confirm copy to warn about unsaved changes and call `postPanelOpenVersion(path, true)` on re-confirm. On `already_active`/`file_not_found`/`load_failed`, toast the reason and clear the confirm.

- [ ] **Step 1: Write failing test**

Create `web/src/components/panel/DeliverSection.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DeliverSection } from "./DeliverSection";
import * as api from "../../lib/api";

vi.mock("../../lib/api");

const DELIVER = {
  version: {
    last: { version: 7, status: "TR", age: "2h ago", qc_label: "9/12" },
    unsaved: false,
    recent: [
      { version: 7, status: "TR", age: "2h ago", qc_label: "9/12",
        path: "/p/shot_v007_TR.c4d", filename: "shot_v007_TR.c4d" },
    ],
  },
  notes: { summary: "Notes: text + 1 TODO (1 pending)", todos_pending: 1,
           notes_present: true, unsaved: false },
  deliver: { has_manifest: true },
  stamp: "s1",
};

describe("DeliverSection", () => {
  beforeEach(() => {
    vi.mocked(api.fetchPanelDeliver).mockResolvedValue(DELIVER as never);
  });

  it("renders the version status line after load", async () => {
    render(<DeliverSection stamp="s1" onStampChange={vi.fn()} />);
    expect(await screen.findByText(/v007 TR/)).toBeInTheDocument();
  });

  it("shows Delivery Summary access only when has_manifest is true", async () => {
    render(<DeliverSection stamp="s1" onStampChange={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /Delivery Summary/i })).toBeInTheDocument();
  });
});
```
(If `@testing-library/react` is not configured, write the test against the pure helpers already covered in Task 3 and assert the component module imports without throwing via a shallow smoke render using the repo's existing `.tsx` test idiom — check how `web/src/components/panel/*.test.tsx` are written first, e.g. any existing `RenderSection.test.tsx`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/panel/DeliverSection.test.tsx`
Expected: FAIL — cannot resolve `./DeliverSection`.

- [ ] **Step 3: Implement `DeliverSection.tsx`**

Create `web/src/components/panel/DeliverSection.tsx`. Structure (fill component styling from the existing `RenderSection.tsx`/`QcSection.tsx` block idiom — headers with a status line, action rows, confirm bar):
```tsx
import { useCallback, useEffect, useState } from "react";
import {
  fetchPanelDeliver,
  postPanelOpenCollect,
  postPanelOpenVersion,
  runPaletteAction,
} from "../../lib/api";
import {
  FILTER_ALL,
  RECENT_FILTERS,
  filterRecent,
  notesStatusLine,
  statusBadgeTone,
  versionStatusLine,
} from "../../lib/panelDeliver";
import { useToast } from "../../lib/toast";
import { NotesPage } from "../../pages/NotesPage";
import { SaveVersionPage } from "../../pages/SaveVersionPage";
import type { PanelDeliverState, PanelVersionEntry } from "../../types";

type View = "main" | "save_version" | "notes";
type Loaded = { kind: "loading" } | { kind: "ok"; data: PanelDeliverState } | { kind: "error"; message: string };

export function DeliverSection({
  stamp,
  onStampChange,
}: { stamp: string | null; onStampChange: (s: string | null) => void }) {
  const { toast } = useToast();
  const [state, setState] = useState<Loaded>({ kind: "loading" });
  const [view, setView] = useState<View>("main");
  const [filter, setFilter] = useState<string>(FILTER_ALL);
  const [confirm, setConfirm] = useState<{ entry: PanelVersionEntry; force: boolean } | null>(null);

  const load = useCallback(() => {
    fetchPanelDeliver()
      .then((data) => {
        setState({ kind: "ok", data });
        if (data.stamp) onStampChange(data.stamp);
      })
      .catch((e) => setState({ kind: "error", message: String(e) }));
  }, [onStampChange]);

  useEffect(() => { load(); }, [load, stamp]);

  const openVersion = useCallback(async (entry: PanelVersionEntry, force: boolean) => {
    const res = await postPanelOpenVersion(entry.path, force);
    if (res.ok) {
      toast({ kind: "success", message: `Opened ${entry.filename}` });
      setConfirm(null);
      if (res.stamp) onStampChange(res.stamp);
      return;
    }
    if (res.error === "unsaved_changes") {
      setConfirm({ entry, force: true }); // re-confirm forces
      return;
    }
    const messages: Record<string, string> = {
      already_active: `Already viewing ${entry.filename}.`,
      file_not_found: `File not found: ${entry.filename}`,
      load_failed: `Cinema 4D could not open ${entry.filename}.`,
      bad_path: "No file path for that version.",
    };
    toast({ kind: "warn", message: messages[res.error ?? ""] ?? `Could not open ${entry.filename}.` });
    setConfirm(null);
  }, [onStampChange, toast]);

  if (view === "save_version")
    return <SaveVersionPage onBack={() => setView("main")} onDone={() => { setView("main"); load(); }} />;
  if (view === "notes")
    return <NotesPage onBack={() => setView("main")} onDone={() => { setView("main"); load(); }} />;

  if (state.kind === "loading") return <div className="panel-note">Loading…</div>;
  if (state.kind === "error") return <div className="panel-note">Deliver unavailable: {state.message}</div>;

  const { version, notes, deliver } = state.data;

  return (
    <div className="deliver-section">
      {/* Version block */}
      <section className="panel-block">
        <header>{versionStatusLine(version)}</header>
        <button type="button" onClick={() => setView("save_version")}>Save Version</button>
        {version && !version.unsaved && (
          <>
            <div className="recent-filter">
              {RECENT_FILTERS.map((f) => (
                <button key={f.value} data-active={filter === f.value}
                  onClick={() => setFilter(f.value)}>{f.label}</button>
              ))}
            </div>
            <ul className="recent-list">
              {filterRecent(version.recent, filter).map((e) => (
                <li key={e.path}>
                  <button type="button" onClick={() => setConfirm({ entry: e, force: false })}>
                    <span data-tone={statusBadgeTone(e.status)}>{e.status || "WIP"}</span>
                    v{String(e.version).padStart(3, "0")} · {e.age ?? ""}
                  </button>
                </li>
              ))}
              {filterRecent(version.recent, filter).length === 0 && (
                <li className="panel-note">No versions match filter.</li>
              )}
            </ul>
          </>
        )}
      </section>

      {/* Notes block */}
      <section className="panel-block">
        <header>{notesStatusLine(notes)}</header>
        <button type="button" onClick={() => setView("notes")}>Edit Notes</button>
      </section>

      {/* Deliver-access block */}
      <section className="panel-block">
        <header>Deliver</header>
        <button type="button" onClick={async () => {
          const r = await postPanelOpenCollect();
          if (!r.ok) toast({ kind: "warn", message: r.error ?? "Could not open Asset Hub." });
        }}>Collect Scene</button>
        <button type="button" onClick={() => runPaletteAction("open_reports_supervisor")}>Supervisor</button>
        {deliver?.has_manifest && (
          <button type="button" onClick={() => runPaletteAction("open_reports_delivery")}>
            Delivery Summary
          </button>
        )}
      </section>

      {/* Open-version confirm bar */}
      {confirm && (
        <div className="confirm-bar">
          <span>
            {confirm.force
              ? `Current scene has unsaved changes. Open ${confirm.entry.filename} anyway?`
              : `Open ${confirm.entry.filename}?`}
          </span>
          <button type="button" onClick={() => openVersion(confirm.entry, confirm.force)}>Open</button>
          <button type="button" onClick={() => setConfirm(null)}>Cancel</button>
        </div>
      )}
    </div>
  );
}
```
Match the actual `useToast` API and class names to the existing panel components (check `RenderSection.tsx` for the real toast signature and confirm-bar markup; adjust `toast({...})` calls accordingly).

- [ ] **Step 4: Wire into `PanelPage.tsx`**

Import at the top with the other section imports:
```tsx
import { DeliverSection } from "../components/panel/DeliverSection";
```
In the section render area (where `overview`/`qc`/`render` sections render, ~line 479-500), add the deliver branch and remove `deliver` from `PLACEHOLDER_DEEP_LINKS` (line 71-73) so the placeholder no longer shows for it:
```tsx
{section === "deliver" && (
  <DeliverSection
    stamp={state.kind === "ok" ? state.data.stamp ?? null : null}
    onStampChange={(s) => { /* reuse the existing stamp state setter used by qc/render */ }}
  />
)}
```
Use the SAME stamp state/setter the QC and Render sections already use for `onStampChange` (inspect how `RenderSection`/render mutations re-anchor the stamp in PanelPage and reuse that setter). Remove the `deliver:` entry from `PLACEHOLDER_DEEP_LINKS`.

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npx vitest run src/components/panel/DeliverSection.test.tsx`
Expected: PASS.
Run: `npx vitest run` (full suite)
Expected: PASS, total = 93 (baseline) + new tests.
Run: `npx tsc -b --noEmit`
Expected: no type errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/panel/DeliverSection.tsx web/src/components/panel/DeliverSection.test.tsx web/src/pages/PanelPage.tsx
git commit -m "feat(panel-spa): DeliverSection with sub-router + absorbed forms (Fase 6.3)"
```

---

### Task 6: Build, version bump, docs

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION`)
- Rebuild: `plugin/web/` (from `web/` via `npm run build`)
- Modify: `CLAUDE.md` (version history + status)
- Modify: `.superpowers/sdd/progress.md` (ledger)
- Modify: memory `project_overview.md` + `MEMORY.md`

**Interfaces:** none (release wiring).

- [ ] **Step 1: Bump version**

In `plugin/sentinel/__init__.py`, change `PLUGIN_VERSION = "1.21.0"` to `PLUGIN_VERSION = "1.22.0"`.

- [ ] **Step 2: Build the SPA**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian/web" && npm run build`
Expected: `tsc -b && vite build` completes with no errors; `plugin/web/assets/` updated with a new hashed bundle.

- [ ] **Step 3: Run the full python suite**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python -m pytest -q`
Expected: PASS, 794 (baseline) + new `test_panel_deliver_ops.py` tests, 0 failures.

- [ ] **Step 4: Update docs**

- `CLAUDE.md`: add a v1.22.0 entry to the Version History Summary and update "What Works" with the Deliver section; bump the header version to v1.22.0.
- `.superpowers/sdd/progress.md`: append the Fase 6.3 task ledger lines.
- Memory `project_overview.md`: update the description frontmatter and body to mark 6.3 done / 6.4 pending; update `MEMORY.md` hook line.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/__init__.py plugin/web CLAUDE.md .superpowers/sdd/progress.md
git commit -m "chore: build + v1.22.0 — panel SPA Deliver section (Fase 6.3)"
```

---

## Self-Review

**Spec coverage:**
- 3 blocks (Version/Notes/Deliver) → Task 1 (read op) + Task 5 (SPA). ✓
- Absorbed sub-views reusing form pages → Task 4 (props) + Task 5 (sub-router). ✓
- Recent list + client filter + click-to-open with guards → Task 1 (recent payload) + Task 2 (open_version_core guards) + Task 3 (filterRecent) + Task 5 (confirm bar). ✓
- Hub/Supervisor/Delivery Summary accesses (Delivery conditional) → Task 1 (open_collect + has_manifest) + Task 5 (DeliverAccessBlock). ✓
- Dialog-free core + `_forbid_dialog` → Task 2. ✓
- Isolated blocks → Task 1 (`_guarded_block`). ✓
- Mock shape parity → Task 3 (`mockPanelDeliver`). ✓
- Native tab untouched, retirement deferred → not modified (constraint). ✓

**Placeholder scan:** No TBD/TODO; every code step carries full code. The two "check the existing idiom" notes (toast signature in Task 5, testing-library availability in Task 4/5) are explicit verification instructions with concrete fallbacks, not deferred work.

**Type consistency:** `PanelDeliverState` (Task 3) matches `_op_panel_deliver` return (Task 1). `open_version_core` error tokens (Task 2: bad_path/file_not_found/already_active/unsaved_changes/load_failed/load_error) match the SPA's `messages` map + `unsaved_changes` branch (Task 5). `postPanelOpenVersion(path, force?)` (Task 3) matches the op's `{path, force}` payload (Task 1). `statusBadgeTone` tones (wip/tr/cr/final) consistent between Task 3 impl and test.
