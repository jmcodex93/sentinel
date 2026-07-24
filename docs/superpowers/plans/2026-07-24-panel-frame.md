# Fase 6.6 — Panel SPA sub-vista Frame (multi-formato consolidado) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the fragmented cross-aspect workflow (Sentinel Frame / Mark subjects / QC #12) into one in-panel Frame sub-view opened from the Render section's Frame block, with light next-step hints.

**Architecture:** A new read-only `panel/frame` op assembles the three touchpoints into one isolated-block payload, reusing existing engines (frame-tag detector, marked-subject collector, shared QC scoring). The SPA `RenderSection` gains a local sub-router (`main`/`frame`); the Frame sub-view's actions all reuse EXISTING ops (`add_frame_tag`/`select_frame_tag`/`mark_safe_area`/`qc select`). Mark Safe Area moves out of Tools.

**Tech Stack:** Python 3 (C4D plugin, fake-c4d pytest harness), React + TypeScript + Vite + Tailwind v4 (vitest).

## Global Constraints

- Ops NEVER raise; every read-block wrapped by `_guarded_block` so one failing block never blanks the others (isolation, like `panel/overview`/`panel/render`/`panel/deliver`).
- `panel/frame` is READ-ONLY. Zero new action ops — the sub-view reuses `panel/render/add_frame_tag`, `panel/render/select_frame_tag`, `panel/tools/mark_safe_area`, `panel/qc/select`.
- Zero duplicated business logic: reuse `panel_render_ops._panel_frame_block` (camera/format_count), `frame_tag._is_stale_from_signature` (staleness), `safe_areas.find_marked_safe_area_objects` (marked count), `panel_ops._run_qc_scoring` (the shared scoring — never re-derive QC).
- QC #12 stays a card in the QC section; the sub-view only REFLECTS it.
- The tag's heavy actions (Create/Update Takes, Set Output, Remove Stale) + fine config stay in the tag's Attribute Manager (reached via Select tag) — NOT brought into the SPA.
- The native panel (`panel.py`) is NOT touched (retirement is Fase 6.5, independent).
- Mocks match the REAL nested payload shape (React #31 lesson).
- Version bump to `1.24.0`.
- Baselines before this work: pytest 835 passing, vitest 114 passing.

---

## File Structure

- **Create** `plugin/sentinel/ui/panel_frame_ops.py` — `panel/frame` read op; `PANEL_FRAME_OPS`.
- **Modify** `plugin/sentinel/ui/reports_dialog.py` — import + merge `PANEL_FRAME_OPS`.
- **Create** `tests/test_panel_frame_ops.py`.
- **Create** `web/src/lib/panelFrame.ts` (+ `.test.ts`) — types, `frameHint`, status lines.
- **Modify** `web/src/types.ts` — `PanelFrameState`.
- **Modify** `web/src/lib/api.ts` — `fetchPanelFrame` + mock.
- **Create** `web/src/components/panel/FrameSubview.tsx`.
- **Modify** `web/src/components/panel/RenderSection.tsx` — sub-router + Frame block hint + "Manage frame →".
- **Modify** `web/src/pages/PanelPage.tsx` — `frameState`/`loadFrame`/stamp wiring + pass Frame handlers.
- **Modify** `web/src/lib/panelTools.ts` (+ `.test.ts`) — remove the "QC Marking" group.
- **Modify** `plugin/sentinel/__init__.py`, `CLAUDE.md`, memory, ledger.

---

### Task 1: `panel/frame` read op

**Files:**
- Create: `plugin/sentinel/ui/panel_frame_ops.py`
- Modify: `plugin/sentinel/ui/reports_dialog.py` (imports ~57-60, `_OPS` ~312-322)
- Test: `tests/test_panel_frame_ops.py`

**Interfaces:**
- Consumes: `panel_ops._guarded_block`, `panel_ops._run_qc_scoring`; `panel_render_ops._panel_frame_block`, `panel_render_ops._find_sentinel_frame_tag`; `frame_tag._is_stale_from_signature`; `safe_areas.find_marked_safe_area_objects`.
- Produces:
  - `_qc12_from_report(qc_report) -> {"pass": bool, "violations": int}` (pure).
  - `build_panel_frame(doc) -> {"frame":..., "subjects":..., "qc12":...}`.
  - `PANEL_FRAME_OPS = {"panel/frame": _op_panel_frame}`.

Payload shape (module docstring):
```
{ "frame": {"has_tag": bool, "camera_name": str|None, "format_count": int|None, "stale": bool} | None,
  "subjects": {"marked_count": int} | None,
  "qc12": {"pass": bool, "violations": int} | None }
```

- [ ] **Step 1: Write failing tests**

Create `tests/test_panel_frame_ops.py`:
```python
"""Tests for the panel/frame read op (Fase 6.6). Fake-c4d harness
(``sentinel_module`` fixture, tests/conftest.py) — panel_frame_ops.py does
``import c4d`` at module scope, same as panel_render_ops.py."""


class TestQc12FromReport:
    def test_no_cross_aspect_row_is_trivial_pass(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        assert panel_frame_ops._qc12_from_report({"checks": []}) == {"pass": True, "violations": 0}

    def test_disabled_is_trivial_pass(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        report = {"checks": [{"id": "cross_aspect", "status": "disabled", "count": None, "new": None}]}
        assert panel_frame_ops._qc12_from_report(report) == {"pass": True, "violations": 0}

    def test_legacy_count_violations(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        report = {"checks": [{"id": "cross_aspect", "status": "fail", "count": 3, "new": None}]}
        assert panel_frame_ops._qc12_from_report(report) == {"pass": False, "violations": 3}

    def test_baseline_new_zero_passes(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        report = {"checks": [{"id": "cross_aspect", "status": "pass", "count": 5, "new": 0}]}
        # baseline-aware: new=0 (all accepted) → pass, violations 0
        assert panel_frame_ops._qc12_from_report(report) == {"pass": True, "violations": 0}


class TestPanelFrameRead:
    def test_no_document_blocks_none(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: None)
        assert panel_frame_ops._op_panel_frame({}) == {"frame": None, "subjects": None, "qc12": None}

    def test_blocks_isolated(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops

        class _Doc:
            pass

        monkeypatch.setattr(panel_frame_ops.c4d.documents, "GetActiveDocument", lambda: _Doc())
        monkeypatch.setattr(panel_frame_ops, "_frame_block", lambda d: {"has_tag": False, "camera_name": None, "format_count": None, "stale": False})
        monkeypatch.setattr(panel_frame_ops, "_subjects_block", lambda d: {"marked_count": 2})

        def _boom(_d):
            raise RuntimeError("qc12 exploded")

        monkeypatch.setattr(panel_frame_ops, "_qc12_block", _boom)
        result = panel_frame_ops._op_panel_frame({})
        assert result["frame"] is not None
        assert result["subjects"] == {"marked_count": 2}
        assert result["qc12"] is None  # guarded → None

    def test_subjects_block_counts_marked(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel import safe_areas
        monkeypatch.setattr(safe_areas, "find_marked_safe_area_objects", lambda doc: ["a", "b", "c"])
        assert panel_frame_ops._subjects_block(object()) == {"marked_count": 3}

    def test_frame_block_no_tag(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_frame_ops
        from sentinel.ui import panel_render_ops
        monkeypatch.setattr(panel_render_ops, "_panel_frame_block",
                            lambda doc: {"has_tag": False, "camera_name": None, "format_count": None})
        out = panel_frame_ops._frame_block(object())
        assert out == {"has_tag": False, "camera_name": None, "format_count": None, "stale": False}


class TestRegistration:
    def test_ops_registered_and_merged(self, sentinel_module):
        from sentinel.ui import panel_frame_ops
        from sentinel.ui import reports_dialog
        assert "panel/frame" in panel_frame_ops.PANEL_FRAME_OPS
        assert "panel/frame" in reports_dialog._OPS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python3 -m pytest tests/test_panel_frame_ops.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentinel.ui.panel_frame_ops'`.

- [ ] **Step 3: Implement `panel_frame_ops.py`**

```python
"""panel/frame op (Fase 6.6) — Frame sub-view read model (multi-format).

Consolidates the three formerly-scattered cross-aspect touchpoints —
Sentinel Frame presence (Render), marked subjects (was Tools), and QC #12
(QC) — into ONE read for the in-panel Frame sub-view. Read-only, isolated
blocks (a failing block never blanks the others). Every ACTION the sub-view
performs reuses an existing op — this module adds no action ops.
"""
import c4d

from sentinel.ui.panel_ops import _guarded_block, _run_qc_scoring
from sentinel.ui import panel_render_ops
from sentinel import safe_areas


def _frame_block(doc):
    """Sentinel Frame presence + host camera + enabled-format count +
    staleness. Reuses ``panel_render_ops._panel_frame_block`` for the first
    three (zero duplication) and adds the tag's own staleness signal."""
    base = panel_render_ops._panel_frame_block(doc)
    base["stale"] = False
    if base.get("has_tag"):
        found = panel_render_ops._find_sentinel_frame_tag(doc)
        if found:
            try:
                from sentinel.ui.frame_tag import _is_stale_from_signature
                base["stale"] = bool(_is_stale_from_signature(found[0]))
            except Exception:
                pass
    return base


def _subjects_block(doc):
    """Count of objects marked as Safe Area Subjects (the QC #12 opt-in)."""
    return {"marked_count": len(safe_areas.find_marked_safe_area_objects(doc) or [])}


def _qc12_from_report(qc_report):
    """Pure: extract the cross_aspect (QC #12) row from a qc_report and
    reduce it to ``{pass, violations}``. A missing or disabled row is a
    trivial pass (QC #12 is not applicable). Baseline-aware: prefer ``new``
    (unaccepted subset) over the raw ``count`` — same preference the score
    itself uses."""
    row = next((c for c in (qc_report.get("checks") or []) if c.get("id") == "cross_aspect"), None)
    if row is None or row.get("status") == "disabled":
        return {"pass": True, "violations": 0}
    violations = row.get("new")
    if violations is None:
        violations = row.get("count") or 0
    return {"pass": violations == 0, "violations": violations}


def _qc12_block(doc):
    """QC #12 status via the SHARED scoring pass (never re-derived)."""
    _rules, _results, qc_report = _run_qc_scoring(doc)
    return _qc12_from_report(qc_report)


def build_panel_frame(doc):
    return {
        "frame": _guarded_block("frame", _frame_block, doc),
        "subjects": _guarded_block("subjects", _subjects_block, doc),
        "qc12": _guarded_block("qc12", _qc12_block, doc),
    }


def _op_panel_frame(payload):
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"frame": None, "subjects": None, "qc12": None}
    return build_panel_frame(doc)


PANEL_FRAME_OPS = {"panel/frame": _op_panel_frame}
```

- [ ] **Step 4: Register in `reports_dialog.py`**

Import after `from sentinel.ui.panel_tools_ops import PANEL_TOOLS_OPS`:
```python
from sentinel.ui.panel_frame_ops import PANEL_FRAME_OPS
```
Add to `_OPS` after `**PANEL_TOOLS_OPS,`:
```python
    **PANEL_FRAME_OPS,
```

- [ ] **Step 5: Run tests + full suite**

Run: `python3 -m pytest tests/test_panel_frame_ops.py -q` → PASS.
Run: `python3 -m pytest -q` → 835 baseline + new, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/panel_frame_ops.py plugin/sentinel/ui/reports_dialog.py tests/test_panel_frame_ops.py
git commit -m "feat(panel-frame): panel/frame read op — consolidated multi-format state (Fase 6.6)"
```

---

### Task 2: SPA `panelFrame.ts` (types, hint, status) + client

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/lib/api.ts`
- Create: `web/src/lib/panelFrame.ts` (+ `web/src/lib/panelFrame.test.ts`)

**Interfaces:**
- Produces (types.ts):
```ts
export interface PanelFrameBlock { has_tag: boolean; camera_name: string | null; format_count: number | null; stale: boolean; }
export interface PanelFrameSubjects { marked_count: number; }
export interface PanelFrameQc12 { pass: boolean; violations: number; }
export interface PanelFrameState {
  frame: PanelFrameBlock | null;
  subjects: PanelFrameSubjects | null;
  qc12: PanelFrameQc12 | null;
}
```
- Produces (panelFrame.ts):
  - `frameHint(state: PanelFrameState): string` — priority stale > violations > no-subjects > pass > no-tag.
  - `frameStatusLine(frame: PanelFrameBlock | null): string`
  - `qc12StatusLine(qc12: PanelFrameQc12 | null): string`
- Produces (api.ts): `fetchPanelFrame(): Promise<PanelFrameState>` + `mockPanelFrame()`.

- [ ] **Step 1: Write failing tests**

Create `web/src/lib/panelFrame.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { frameHint, frameStatusLine, qc12StatusLine } from "./panelFrame";
import type { PanelFrameState } from "../types";

const state = (over: Partial<PanelFrameState>): PanelFrameState => ({
  frame: { has_tag: true, camera_name: "cam", format_count: 5, stale: false },
  subjects: { marked_count: 2 },
  qc12: { pass: true, violations: 0 },
  ...over,
});

describe("frameHint", () => {
  it("no tag → add-a-frame", () => {
    expect(frameHint(state({ frame: { has_tag: false, camera_name: null, format_count: null, stale: false } })).toLowerCase())
      .toContain("add a sentinel frame");
  });
  it("tag but no subjects → mark-your-subjects", () => {
    expect(frameHint(state({ subjects: { marked_count: 0 } })).toLowerCase()).toContain("mark your key subjects");
  });
  it("subjects + pass → all-inside", () => {
    expect(frameHint(state({}))).toContain("stay inside");
  });
  it("violations → warns with counts", () => {
    const h = frameHint(state({ qc12: { pass: false, violations: 3 } }));
    expect(h).toContain("3");
    expect(h).toContain("safe area");
  });
  it("stale takes priority over violations", () => {
    const h = frameHint(state({ frame: { has_tag: true, camera_name: "cam", format_count: 5, stale: true }, qc12: { pass: false, violations: 3 } }));
    expect(h.toLowerCase()).toContain("out of date");
  });
});

describe("frameStatusLine", () => {
  it("null → unavailable", () => {
    expect(frameStatusLine(null)).toContain("unavailable");
  });
  it("no tag", () => {
    expect(frameStatusLine({ has_tag: false, camera_name: null, format_count: null, stale: false })).toContain("No Sentinel Frame");
  });
  it("tag with camera + formats", () => {
    const s = frameStatusLine({ has_tag: true, camera_name: "heroCam", format_count: 5, stale: false });
    expect(s).toContain("heroCam");
    expect(s).toContain("5");
  });
});

describe("qc12StatusLine", () => {
  it("null → unavailable", () => {
    expect(qc12StatusLine(null)).toContain("unavailable");
  });
  it("pass", () => {
    expect(qc12StatusLine({ pass: true, violations: 0 }).toLowerCase()).toContain("no violations");
  });
  it("violations", () => {
    expect(qc12StatusLine({ pass: false, violations: 2 })).toContain("2");
  });
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd web && npx vitest run src/lib/panelFrame.test.ts`
Expected: FAIL — cannot resolve `./panelFrame`.

- [ ] **Step 3: Add types + panelFrame.ts**

Append the interfaces to `web/src/types.ts`. Create `web/src/lib/panelFrame.ts`:
```ts
import type { PanelFrameBlock, PanelFrameQc12, PanelFrameState } from "../types";

/** The single next-step hint for the Frame sub-view — derived from state,
 * NOT a forced wizard. Priority: stale takes-out-of-date first (blocks a
 * correct QC read), then QC #12 violations, then "no subjects yet", then
 * the all-clear, then "no tag yet". */
export function frameHint(state: PanelFrameState): string {
  const { frame, subjects, qc12 } = state;
  if (!frame || !frame.has_tag) {
    return "Add a Sentinel Frame to your camera to start.";
  }
  if (frame.stale) {
    return "Takes out of date — update them from the tag.";
  }
  if (qc12 && !qc12.pass && qc12.violations > 0) {
    const f = qc12.violations === 1 ? "format" : "formats";
    // violations is the subject×format violation count; keep the copy simple.
    return `⚠ ${qc12.violations} subject/format violation${qc12.violations === 1 ? "" : "s"} — subjects leave the safe area.`;
  }
  if (!subjects || subjects.marked_count === 0) {
    return "Mark your key subjects (logo, title, character) so QC #12 can verify them.";
  }
  return "✓ All marked subjects stay inside every format's safe area.";
}

/** Frame block status: `"On <camera> · N formats"` / `"No Sentinel Frame tag."` */
export function frameStatusLine(frame: PanelFrameBlock | null): string {
  if (frame === null) return "Frame status unavailable.";
  if (!frame.has_tag || !frame.camera_name) return "No Sentinel Frame tag.";
  const n = frame.format_count;
  const formats = typeof n === "number" ? ` · ${n} format${n === 1 ? "" : "s"}` : "";
  return `On ${frame.camera_name}${formats}.`;
}

/** QC #12 block status. */
export function qc12StatusLine(qc12: PanelFrameQc12 | null): string {
  if (qc12 === null) return "QC #12 status unavailable.";
  if (qc12.pass || qc12.violations === 0) return "No violations.";
  return `${qc12.violations} subject/format violation${qc12.violations === 1 ? "" : "s"}.`;
}
```
(The `f`/`format` unused local in the sketch: drop it — keep `frameHint`'s violations branch to the single template shown. Ensure no unused vars for `tsc --noUnusedLocals`.)

- [ ] **Step 4: Add client + mock in `api.ts`**

Add `PanelFrameState` to the type imports. Then (near the other panel clients):
```ts
/** Client-only mock for `panel/frame` (`?mock=1`). Nested shape, matching
 * the real payload (React #31 lesson). */
function mockPanelFrame(): PanelFrameState {
  return {
    frame: { has_tag: true, camera_name: "heroCam", format_count: 5, stale: false },
    subjects: { marked_count: 2 },
    qc12: { pass: false, violations: 3 },
  };
}

/** `POST /api/panel/frame` — Frame sub-view read model (Fase 6.6). */
export async function fetchPanelFrame(): Promise<PanelFrameState> {
  if (isMock()) return mockPanelFrame();
  let response: Response;
  try {
    response = await fetch("/api/panel/frame", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
    });
  } catch {
    return { frame: null, subjects: null, qc12: null };
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    return { frame: null, subjects: null, qc12: null };
  }
  if (!response.ok || (data && typeof data === "object" && "error" in data && (data as { error?: unknown }).error)) {
    return { frame: null, subjects: null, qc12: null };
  }
  return data as PanelFrameState;
}
```
(Mirror `fetchPanelDeliver`'s error-envelope guard exactly — the op never emits an `{error}` envelope on the happy path, but the dispatch layer can on a raise/timeout, and null blocks must render "unavailable" rather than crash.)

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npx vitest run src/lib/panelFrame.test.ts` → PASS.
Run: `npx tsc -b --noEmit` → clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/types.ts web/src/lib/api.ts web/src/lib/panelFrame.ts web/src/lib/panelFrame.test.ts
git commit -m "feat(panel-spa): panelFrame pure logic + types + client (Fase 6.6)"
```

---

### Task 3: FrameSubview + RenderSection sub-router + wiring + Tools removal

**Files:**
- Create: `web/src/components/panel/FrameSubview.tsx`
- Modify: `web/src/components/panel/RenderSection.tsx` (sub-router + Frame block hint + "Manage frame →")
- Modify: `web/src/pages/PanelPage.tsx` (`frameState`/`loadFrame`/stamp + Frame handlers)
- Modify: `web/src/lib/panelTools.ts` (+ `web/src/lib/panelTools.test.ts`) — remove "QC Marking" group
- Test: covered by `panelFrame.test.ts` (Task 2) + `panelTools.test.ts` update

**Interfaces:**
- Consumes: `fetchPanelFrame`, existing action clients (`postPanelTool` for `mark_safe_area`, `runPaletteAction`/`postPanel*` for add/select frame tag, `postPanelQcSelect`-equivalent for `qc/select`); `frameHint`/`frameStatusLine`/`qc12StatusLine`.
- Produces: `FrameSubview` component; RenderSection sub-router `renderView: "main" | "frame"`.

**Sub-router:** `RenderSection` gains local `renderView` state (mirror `DeliverSection`'s `deliverView`). In `main`, the Frame block shows `frameStatusLine` + the hint (warn tint when qc12 violates) + **Manage frame →** (sets `renderView="frame"`). In `frame`, render `<FrameSubview onBack=... />`.

**FrameSubview blocks** (reuse the same block shell as RenderSection/DeliverSection):
1. Hint line = `frameHint(frame)` (top; warn tone when it starts with ⚠ or mentions "out of date").
2. Frame block: `frameStatusLine` + **Add to camera** (`add_frame_tag` action) + **Select tag** (`select_frame_tag`, disabled if `!has_tag`) + the static note "Formats, output & Take generation live on the tag — Select to edit."
3. Subjects block: `${marked_count} subjects marked` + **Mark / Unmark selected** (`mark_safe_area` action).
4. QC #12 block: `qc12StatusLine` + **Select** (`qc/select` with `cross_aspect`, disabled if no violations) + **Details in QC →** (navigate to the QC section).

- [ ] **Step 1: Write the failing test (Tools removal)**

Update `web/src/lib/panelTools.test.ts` — change the groups assertion:
```ts
  it("has the scene-authoring groups (Mark subjects moved to the Frame sub-view)", () => {
    expect(TOOL_GROUPS.map((g) => g.title)).toEqual([
      "Layout & Hierarchy", "Animation",
    ]);
  });
  it("carries no mark_safe_area entry (moved to Frame sub-view)", () => {
    const allIds = TOOL_GROUPS.flatMap((g) => g.tools.map((t) => t.id));
    expect(allIds).not.toContain("panel/tools/mark_safe_area");
  });
```

- [ ] **Step 2: Run to verify fail**

Run: `cd web && npx vitest run src/lib/panelTools.test.ts`
Expected: FAIL — TOOL_GROUPS still has "QC Marking".

- [ ] **Step 3: Remove the "QC Marking" group from `panelTools.ts`**

Delete the `{ title: "QC Marking", tools: [{ id: "panel/tools/mark_safe_area", ... }] }` group object from `TOOL_GROUPS`. (The `panel/tools/mark_safe_area` op stays; it's now called from FrameSubview.)

- [ ] **Step 4: Create `FrameSubview.tsx`**

Model it on `DeliverSection`'s block shell + confirm/toast idiom. Skeleton (fill styling from the sibling blocks; wire the four actions to the props):
```tsx
import { Button } from "../form/Button";
import { frameHint, frameStatusLine, qc12StatusLine } from "../../lib/panelFrame";
import type { PanelFrameState } from "../../types";

/** Frame sub-view (Fase 6.6) — consolidates the cross-aspect workflow that
 * used to be scattered across Render (Sentinel Frame), Tools (Mark subjects)
 * and QC (#12). Read-only state from `panel/frame`; every action reuses an
 * existing op. The tag's heavy actions + fine config stay in its Attribute
 * Manager (reached via Select tag). */
export function FrameSubview({
  frame,
  busy,
  onBack,
  onAddTag,
  onSelectTag,
  onMarkSubjects,
  onSelectViolations,
  onOpenQc,
}: {
  frame: PanelFrameState;
  busy: string | null;
  onBack: () => void;
  onAddTag: () => void;
  onSelectTag: () => void;
  onMarkSubjects: () => void;
  onSelectViolations: () => void;
  onOpenQc: () => void;
}) {
  const isBusy = busy !== null;
  const hint = frameHint(frame);
  const warnHint = hint.startsWith("⚠") || hint.toLowerCase().includes("out of date");
  const hasTag = !!frame.frame?.has_tag;
  const violations = frame.qc12?.violations ?? 0;

  return (
    <div className="flex flex-col gap-3 p-3">
      <Button variant="secondary" onClick={onBack}>← Render</Button>

      <p className="text-body rounded-lg border p-3"
         style={{ borderColor: "var(--color-hairline)",
                  backgroundColor: warnHint ? "var(--color-status-warn-tint-10)" : "var(--color-surface-1)",
                  color: warnHint ? "var(--color-status-warn)" : "var(--color-ink)" }}>
        {hint}
      </p>

      {/* Sentinel Frame */}
      <section className="flex flex-col gap-2 rounded-lg border p-3"
               style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}>
        <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>SENTINEL FRAME</p>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>{frameStatusLine(frame.frame)}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={isBusy} onClick={onAddTag}>Add to camera</Button>
          <Button variant="secondary" disabled={isBusy || !hasTag} onClick={onSelectTag}>Select tag</Button>
        </div>
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Formats, output & Take generation live on the tag — Select to edit.
        </p>
      </section>

      {/* Subjects */}
      <section className="flex flex-col gap-2 rounded-lg border p-3"
               style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}>
        <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>SUBJECTS</p>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {frame.subjects ? `${frame.subjects.marked_count} subject${frame.subjects.marked_count === 1 ? "" : "s"} marked` : "Subjects unavailable."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={isBusy} onClick={onMarkSubjects}>Mark / Unmark selected</Button>
        </div>
      </section>

      {/* QC #12 */}
      <section className="flex flex-col gap-2 rounded-lg border p-3"
               style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}>
        <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>QC #12 · CROSS-ASPECT SAFE AREA</p>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>{qc12StatusLine(frame.qc12)}</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" disabled={isBusy || violations === 0} onClick={onSelectViolations}>Select violating</Button>
          <button type="button" onClick={onOpenQc} className="text-caption" style={{ color: "var(--color-primary)" }}>Details in QC →</button>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 5: RenderSection sub-router + Frame block hint + "Manage frame →"**

In `RenderSection.tsx`: add local `const [renderView, setRenderView] = useState<"main" | "frame">("main")`. When `renderView === "frame"`, return `<FrameSubview frame={frameData} busy={busy} onBack={() => setRenderView("main")} ... />` (the Frame handlers come from PanelPage props — see Step 6). In the `main` Frame block, add the hint text (warn tint if qc12 violates — read from the frame data PanelPage passes) and a "Manage frame →" control that sets `renderView="frame"`. RenderSection now also needs the `panel/frame` data + Frame action handlers as props (add them to its props, mirroring how it already takes render data + handlers).

- [ ] **Step 6: PanelPage wiring**

- Add `const [frameState, setFrameState] = useState<PanelFrameState | null>(null)` and a `loadFrame(silent)` that calls `fetchPanelFrame()` and re-anchors `stampRef` on success (mirror `loadRender`). Fetch on entering the render section (the Frame sub-view lives under render) — reuse the existing `section === "render"` effect to also `loadFrame(false)`, and the poll to `loadFrame(true)`.
- Frame action handlers (reuse existing ops): `handleAddFrameTag` → `postPanelRender...add_frame_tag` (already exists as a render handler — reuse it), `handleSelectFrameTag` (exists), `handleMarkSubjects` → `postPanelTool("panel/tools/mark_safe_area")` + `toolToast`, `handleSelectViolations` → the QC select client with `cross_aspect`, `onOpenQc` → `setSection("qc")`. After each mutation: toast + `loadFrame(true)` (+ `loadRender(true)` so the Render Frame block's hint refreshes).
- Pass `frameState` + these handlers into `RenderSection`.

- [ ] **Step 7: Run tests + typecheck + build check**

Run: `cd web && npx vitest run` → 114 baseline + panelFrame's + updated panelTools, all pass.
Run: `npx tsc -b --noEmit` → clean.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/panel/FrameSubview.tsx web/src/components/panel/RenderSection.tsx web/src/pages/PanelPage.tsx web/src/lib/panelTools.ts web/src/lib/panelTools.test.ts
git commit -m "feat(panel-spa): FrameSubview + Render sub-router; move Mark Safe Area out of Tools (Fase 6.6)"
```

---

### Task 4: Build, version bump, docs

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION`)
- Rebuild: `plugin/web/`
- Modify: `CLAUDE.md`, `.superpowers/sdd/progress.md`, memory

- [ ] **Step 1: Bump version**

`plugin/sentinel/__init__.py`: `PLUGIN_VERSION = "1.23.1"` → `PLUGIN_VERSION = "1.24.0"`.

- [ ] **Step 2: Build**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian/web" && npm run build` → completes, `plugin/web/assets/` updated.

- [ ] **Step 3: Run both suites**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python3 -m pytest -q` → 0 failures.
Run: `cd web && npx vitest run` → 0 failures.

- [ ] **Step 4: Update docs**

- `CLAUDE.md`: header → v1.24.0; add a "What Works" bullet for the Frame sub-view; add a v1.24.0 Version History entry (note QC #12 still in QC; tag heavy actions still in AM; Mark Safe Area moved out of Tools).
- `.superpowers/sdd/progress.md`: append the Fase 6.6 ledger lines.
- Memory `project_overview.md` + `MEMORY.md`: mark 6.6 done; remaining = 6.5 (retire native).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/__init__.py plugin/web CLAUDE.md .superpowers/sdd/progress.md
git commit -m "chore: build + v1.24.0 — panel SPA Frame sub-view (Fase 6.6)"
```

---

## Self-Review

**Spec coverage:**
- Frame sub-view (hint + Frame + Subjects + QC #12) → Task 2 (logic) + Task 3 (component). ✓
- Consolidated read `panel/frame`, isolated blocks, reuse of scoring/frame-detector/subject-collector → Task 1. ✓
- Zero new action ops (reuse add/select/mark/qc-select) → Task 3 wiring. ✓
- Light hints (priority stale>violations>no-subjects>pass>no-tag) → Task 2 `frameHint`. ✓
- Entry from Render Frame block (hint + Manage frame →) → Task 3 Steps 5-6. ✓
- Mark Safe Area moves out of Tools → Task 3 Steps 1-3. ✓
- QC #12 stays in QC (only reflected) → not removed anywhere; "Details in QC →" navigates. ✓
- Tag heavy actions stay in AM → FrameSubview note + no core extraction. ✓
- Native panel untouched → no task edits `panel.py`. ✓
- Version + docs → Task 4. ✓

**Placeholder scan:** No TBD. The `frameHint` violations copy sketch flags a dead local (`f`) to drop — the implementer removes it for `--noUnusedLocals`. RenderSection/PanelPage wiring (Task 3 Steps 5-6) is described as a pattern to mirror `DeliverSection`/`loadRender` (existing, referenceable), not re-transcribed — consistent with how the Deliver plan handled the same integration.

**Type consistency:** `PanelFrameState` (Task 2) matches `_op_panel_frame`'s return (Task 1: frame/subjects/qc12, each nullable). `frameHint`/`frameStatusLine`/`qc12StatusLine` read exactly the block fields the op emits (`has_tag`/`camera_name`/`format_count`/`stale`; `marked_count`; `pass`/`violations`). The reused action ops (`panel/tools/mark_safe_area`, `panel/qc/select`, `panel/render/add_frame_tag`, `panel/render/select_frame_tag`) all exist on this branch's base (v1.23.1).
