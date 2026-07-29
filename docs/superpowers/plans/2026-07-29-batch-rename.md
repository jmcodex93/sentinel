# Batch Rename (v1.31) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch Rename for objects + materials with a token pipeline and live preview, per the approved spec `docs/superpowers/specs/2026-07-29-batch-rename-design.md`.

**Architecture:** A PURE `renaming.py` engine (`rename_plan` drives BOTH preview and apply — WYSIWYG by construction), two ops in `panel_tools_ops.py` (`rename_preview` read-only, `rename_apply` re-derives the plan server-side and applies in one undo), and a `RenameSubview` inside the Tools section (local sub-router, Render→Frame pattern), with a debounced live preview that follows scene selection via the stamp poll.

**Tech Stack:** Python 3 (pure module + fake-c4d pytest harness), Vite+React+TS SPA (vitest), bundle committed to `plugin/web/`.

**Branch:** `feat/batch-rename` (create from `main` before Task 1).

## Global Constraints

- **Pipeline order is FIXED**: (1) pattern (empty → keep current name) → (2) find/replace (literal, case-insensitive by default, Match case toggle) → (3) prefix/suffix. Tokens: `$n` (counter, `num_start` default 1 + `num_padding` default 3 via zfill), `$name`, `$parent`, `$type`. **Token expansion replaces longer tokens FIRST** (`$name`, `$parent`, `$type`, then `$n`) — replacing `$n` first would corrupt `$name` (`"$name"` → `"001ame"`).
- **Find/replace uses `re.sub(re.escape(find), lambda m: replace, ...)`** — the lambda keeps backslashes in `replace` literal (the v1.5.7 repathing lesson).
- `$n` order: objects = `GETACTIVEOBJECTFLAGS_SELECTIONORDER`; materials = `GetActiveMaterials()` order. `$parent` = `GetUp().GetName()` or `""`; `$type` = `GetTypeName()` or `""`.
- **Apply NEVER trusts client rows** — it re-derives the plan from the payload ops against the CURRENT selection. Collisions (duplicate final names within the batch) warn, never block.
- One undo per apply (`StartUndo`/`AddUndo(UNDOTYPE_CHANGE, node)` before each `SetName`/`EndUndo` in finally). Dialog-free ops (`_forbid_dialog`).
- Preview capped at 500 rows (`truncated` flag). Errors: `no_document`, `no_selection`, `nothing_to_do` (neutral ops config).
- Takes and layers are NEVER touched. No QC/registry changes. Existing Tools ops/copys unchanged.
- Preview is NEVER computed client-side — the SPA always calls `rename_preview` (single source of truth).
- Commands: pytest `python3 -m pytest tests/ -q`; vitest `cd web && npx vitest run`; build `cd web && npm run build` (bundle in `plugin/web/` committed, never hand-edited).

## File Structure

- `plugin/sentinel/renaming.py` — NEW pure engine.
- `plugin/sentinel/ui/panel_tools_ops.py` — 2 new ops + item-collection adapter.
- `web/src/lib/panelRename.ts` — NEW pure client logic (default ops, payload shape, toast copy) + test.
- `web/src/components/panel/RenameSubview.tsx` — NEW; `web/src/components/panel/ToolsSection.tsx` — local sub-router; `web/src/lib/api.ts` — fetch helpers; `web/src/types.ts` — types.
- Tests: `tests/test_renaming.py` (NEW), `tests/test_panel_tools_ops.py` (append), `web/src/lib/panelRename.test.ts` (NEW).

---

### Task 1: Pure engine — `renaming.py`

**Files:**
- Create: `plugin/sentinel/renaming.py`
- Test: `tests/test_renaming.py` (create)

**Interfaces:**
- Produces: `DEFAULT_OPS: dict` — `{"pattern": "", "find": "", "replace": "", "match_case": False, "prefix": "", "suffix": "", "num_start": 1, "num_padding": 3}`.
- Produces: `normalize_ops(raw) -> dict` — merges a possibly-partial/malformed payload over `DEFAULT_OPS` (strings coerced via `str`, bools via `bool`, ints via `int` with try/except → default; `num_padding` clamped 0..8, `num_start` clamped ≥0).
- Produces: `ops_is_noop(ops) -> bool` — True when pattern, find, prefix and suffix are all empty strings.
- Produces: `rename_plan(items, ops) -> list[{"old": str, "new": str, "collision": bool}]` — `items` = `[{"name", "parent", "type_name"}]` in final order.

- [ ] **Step 1: Write the failing tests** — create `tests/test_renaming.py`:

```python
import importlib

import pytest


@pytest.fixture
def renaming(sentinel_module):
    return importlib.import_module("sentinel.renaming")


def _items(*names, parent="", type_name="Cube"):
    return [{"name": n, "parent": parent, "type_name": type_name} for n in names]


def test_pattern_counter_start_and_padding(renaming):
    ops = renaming.normalize_ops({"pattern": "luz_$n", "num_start": 5, "num_padding": 2})
    plan = renaming.rename_plan(_items("a", "b", "c"), ops)
    assert [r["new"] for r in plan] == ["luz_05", "luz_06", "luz_07"]
    assert [r["old"] for r in plan] == ["a", "b", "c"]


def test_token_order_name_before_n(renaming):
    # "$name" must not be corrupted by the "$n" replacement.
    ops = renaming.normalize_ops({"pattern": "$name_$n"})
    plan = renaming.rename_plan(_items("Cubo"), ops)
    assert plan[0]["new"] == "Cubo_001"


def test_parent_and_type_tokens(renaming):
    ops = renaming.normalize_ops({"pattern": "$parent/$type_$n"})
    plan = renaming.rename_plan(
        [{"name": "x", "parent": "GRP", "type_name": "Light"}], ops)
    assert plan[0]["new"] == "GRP/Light_001"


def test_find_replace_case_insensitive_default_and_match_case(renaming):
    items = _items("Hero_CAM", "hero_cam")
    ops = renaming.normalize_ops({"find": "hero", "replace": "Villain"})
    assert [r["new"] for r in renaming.rename_plan(items, ops)] == [
        "Villain_CAM", "Villain_cam"]
    ops_cs = renaming.normalize_ops(
        {"find": "hero", "replace": "Villain", "match_case": True})
    assert [r["new"] for r in renaming.rename_plan(items, ops_cs)] == [
        "Hero_CAM", "Villain_cam"]


def test_replace_with_backslashes_stays_literal(renaming):
    ops = renaming.normalize_ops({"find": "a", "replace": r"C:\1"})
    assert renaming.rename_plan(_items("a"), ops)[0]["new"] == r"C:\1"


def test_pipeline_order_pattern_then_replace_then_fixes(renaming):
    ops = renaming.normalize_ops({
        "pattern": "cam_$n", "find": "cam", "replace": "shot",
        "prefix": "PRE_", "suffix": "_POST"})
    assert renaming.rename_plan(_items("whatever"), ops)[0]["new"] == "PRE_shot_001_POST"


def test_collisions_flagged_not_blocked(renaming):
    ops = renaming.normalize_ops({"pattern": "same"})
    plan = renaming.rename_plan(_items("a", "b"), ops)
    assert all(r["new"] == "same" and r["collision"] for r in plan)
    plan2 = renaming.rename_plan(_items("a", "b"), renaming.normalize_ops({"pattern": "u_$n"}))
    assert not any(r["collision"] for r in plan2)


def test_noop_and_neutral_config(renaming):
    assert renaming.ops_is_noop(renaming.normalize_ops({})) is True
    assert renaming.ops_is_noop(renaming.normalize_ops({"suffix": "_x"})) is False
    plan = renaming.rename_plan(_items("keep"), renaming.normalize_ops({}))
    assert plan[0]["old"] == plan[0]["new"] == "keep"


def test_normalize_ops_defensive(renaming):
    ops = renaming.normalize_ops(
        {"num_start": "nope", "num_padding": 99, "match_case": 1, "pattern": 5})
    assert ops["num_start"] == 1        # malformed -> default
    assert ops["num_padding"] == 8      # clamped
    assert ops["match_case"] is True
    assert ops["pattern"] == "5"
    assert renaming.normalize_ops(None) == renaming.DEFAULT_OPS
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_renaming.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** — create `plugin/sentinel/renaming.py`:

```python
# -*- coding: utf-8 -*-
"""Batch Rename engine (v1.31) — PURE, no ``import c4d``.

``rename_plan`` drives BOTH the SPA preview and the apply op — WYSIWYG by
construction, not by discipline. Pipeline order is fixed: (1) pattern (when
non-empty it replaces the whole name; tokens ``$name``/``$parent``/``$type``
are expanded BEFORE ``$n`` so the counter substitution can't corrupt them),
(2) literal find/replace (case-insensitive unless ``match_case``; the
replacement goes through a lambda so backslashes stay literal — the v1.5.7
repathing lesson), (3) prefix/suffix. Collisions (duplicate FINAL names
within the batch) are flagged, never blocking — C4D allows duplicate names;
Sentinel warns, the artist decides.
"""

import re

DEFAULT_OPS = {
    "pattern": "",
    "find": "",
    "replace": "",
    "match_case": False,
    "prefix": "",
    "suffix": "",
    "num_start": 1,
    "num_padding": 3,
}

MAX_PADDING = 8


def _as_str(value, default=""):
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _as_int(value, default, low, high):
    try:
        value = int(value)
    except Exception:
        return default
    return max(low, min(high, value))


def normalize_ops(raw):
    """Merge a possibly-partial/malformed payload over DEFAULT_OPS."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "pattern": _as_str(raw.get("pattern", "")),
        "find": _as_str(raw.get("find", "")),
        "replace": _as_str(raw.get("replace", "")),
        "match_case": bool(raw.get("match_case", False)),
        "prefix": _as_str(raw.get("prefix", "")),
        "suffix": _as_str(raw.get("suffix", "")),
        "num_start": _as_int(raw.get("num_start", 1), 1, 0, 10 ** 9),
        "num_padding": _as_int(raw.get("num_padding", 3), 3, 0, MAX_PADDING),
    }


def ops_is_noop(ops):
    return not (ops["pattern"] or ops["find"] or ops["prefix"] or ops["suffix"])


def _expand_pattern(pattern, item, counter, padding):
    out = pattern
    out = out.replace("$name", item.get("name") or "")
    out = out.replace("$parent", item.get("parent") or "")
    out = out.replace("$type", item.get("type_name") or "")
    out = out.replace("$n", str(counter).zfill(padding))
    return out


def rename_plan(items, ops):
    """[{"old", "new", "collision"}] for ``items`` in their given order."""
    rows = []
    for index, item in enumerate(items or []):
        name = item.get("name") or ""
        new = name
        if ops["pattern"]:
            new = _expand_pattern(
                ops["pattern"], item, ops["num_start"] + index, ops["num_padding"])
        if ops["find"]:
            flags = 0 if ops["match_case"] else re.IGNORECASE
            new = re.sub(
                re.escape(ops["find"]), lambda _m: ops["replace"], new, flags=flags)
        new = ops["prefix"] + new + ops["suffix"]
        rows.append({"old": name, "new": new, "collision": False})

    counts = {}
    for row in rows:
        counts[row["new"]] = counts.get(row["new"], 0) + 1
    for row in rows:
        row["collision"] = counts[row["new"]] > 1
    return rows
```

- [ ] **Step 4: Run** — `python3 -m pytest tests/test_renaming.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/renaming.py tests/test_renaming.py
git commit -m "feat(renaming): pure batch-rename engine (fixed pipeline, tokens, collisions)"
```

---

### Task 2: Ops — `rename_preview` + `rename_apply`

**Files:**
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py` (append)

**Interfaces:**
- Consumes: Task 1's `renaming.normalize_ops` / `ops_is_noop` / `rename_plan`.
- Produces: `panel/tools/rename_preview` — payload `{"source": "objects"|"materials", "ops": {...}}` → `{"ok": True, "rows": [...≤500], "truncated": bool, "total": int}` or `{"ok": False, "error": "no_document"|"bad_source"|"no_selection"|"nothing_to_do"}`.
- Produces: `panel/tools/rename_apply` — same payload → `{"ok": True, "renamed": int, "collisions": int, "source": str}` or the same errors. Re-derives the plan server-side; one undo.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_panel_tools_ops.py`, in that file's concrete idiom — fakes with `GetActiveObjects`/`GetActiveMaterials`, `GetName`/`SetName`/`GetUp`/`GetTypeName`, undo recording; plus `_forbid_dialog` coverage for both routes):

```python
# Behavioral requirements (write as real tests in the file's mechanics):
# 1. preview objects: 3 fake selected objects + pattern "u_$n" -> rows u_001..u_003,
#    truncated False, total 3; source "materials" reads GetActiveMaterials().
# 2. preview with >500 selected (fake 501) -> 500 rows, truncated True, total 501.
# 3. preview neutral ops -> {"ok": False, "error": "nothing_to_do"}; empty selection
#    -> "no_selection"; source "layers" -> "bad_source".
# 4. apply: renames only rows where old != new via SetName, records ONE
#    StartUndo/EndUndo pair and AddUndo per renamed node, returns renamed count
#    + collisions count. Apply IGNORES any "rows" key smuggled into the payload
#    (assert a poisoned payload with fake rows still renames from the REAL
#    selection-derived plan).
# 5. _forbid_dialog on both routes (no-document AND happy paths).
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement** (append to `panel_tools_ops.py`):

```python
PREVIEW_CAP = 500


def _rename_items(doc, source):
    """(items, nodes) in final order, or (None, None) on bad source.
    Objects follow the artist's SELECTION order (spec decision 3)."""
    if source == "objects":
        try:
            nodes = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_SELECTIONORDER) or []
        except Exception:
            nodes = []
    elif source == "materials":
        try:
            nodes = doc.GetActiveMaterials() or []
        except Exception:
            nodes = []
    else:
        return None, None
    items = []
    for node in nodes:
        parent = ""
        try:
            up = node.GetUp() if hasattr(node, "GetUp") else None
            parent = up.GetName() if up is not None else ""
        except Exception:
            parent = ""
        try:
            type_name = node.GetTypeName() or ""
        except Exception:
            type_name = ""
        items.append({"name": node.GetName() or "", "parent": parent,
                      "type_name": type_name})
    return items, nodes


def _rename_request(payload):
    """Shared front half: (doc, nodes, plan, ops) or an error dict."""
    from sentinel import renaming
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    payload = payload or {}
    ops = renaming.normalize_ops(payload.get("ops"))
    if renaming.ops_is_noop(ops):
        return {"ok": False, "error": "nothing_to_do"}
    items, nodes = _rename_items(doc, payload.get("source"))
    if items is None:
        return {"ok": False, "error": "bad_source"}
    if not items:
        return {"ok": False, "error": "no_selection"}
    return {"doc": doc, "nodes": nodes, "plan": renaming.rename_plan(items, ops)}


def _op_rename_preview(payload):
    result = _rename_request(payload)
    if "error" in result:
        return result
    plan = result["plan"]
    return {"ok": True, "rows": plan[:PREVIEW_CAP],
            "truncated": len(plan) > PREVIEW_CAP, "total": len(plan)}


def _op_rename_apply(payload):
    # Re-derives the plan from the CURRENT selection + payload ops — any
    # client-side rows are ignored (a stale preview can never apply
    # misaligned names).
    result = _rename_request(payload)
    if "error" in result:
        return result
    doc, nodes, plan = result["doc"], result["nodes"], result["plan"]
    renamed = 0
    doc.StartUndo()
    try:
        for node, row in zip(nodes, plan):
            if row["old"] == row["new"]:
                continue
            try:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
            except Exception:
                pass
            try:
                node.SetName(row["new"])
            except Exception:
                continue
            renamed += 1
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    return {"ok": True, "renamed": renamed,
            "collisions": sum(1 for r in plan if r["collision"]),
            "source": (payload or {}).get("source")}
```

Register: `"panel/tools/rename_preview": _op_rename_preview`, `"panel/tools/rename_apply": _op_rename_apply`.

- [ ] **Step 4: Run** — `python3 -m pytest tests/test_panel_tools_ops.py tests/test_renaming.py -q` → PASS; full suite → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/panel_tools_ops.py tests/test_panel_tools_ops.py
git commit -m "feat(panel): rename_preview/rename_apply ops (server-derived plan, one undo)"
```

---

### Task 3: SPA — RenameSubview + Tools sub-router

**Files:**
- Create: `web/src/lib/panelRename.ts`, `web/src/lib/panelRename.test.ts`, `web/src/components/panel/RenameSubview.tsx`
- Modify: `web/src/components/panel/ToolsSection.tsx`, `web/src/lib/api.ts`, `web/src/types.ts`, `web/src/pages/PanelPage.tsx` (only if the sub-router needs a prop — prefer keeping the sub-router LOCAL to ToolsSection)

**Interfaces:**
- `panelRename.ts`: `export interface RenameOps { pattern: string; find: string; replace: string; match_case: boolean; prefix: string; suffix: string; num_start: number; num_padding: number }`; `DEFAULT_RENAME_OPS`; `renameToast(source, r) -> {message, variant}` — success `Renamed 12 object(s).` / `Renamed 3 material(s).` with `+ N duplicate result(s)` warn suffix when collisions>0; errors map `no_selection` → "Select something to rename first.", `nothing_to_do` → "Fill in at least one rename field.", `bad_source`/default → generic.
- `api.ts`: `fetchRenamePreview(source, ops)` → `{ok, rows?, truncated?, total?, error?}`; `postRenameApply(source, ops)`. Types in `types.ts` (`RenameRow {old, new, collision}` etc. — mirror the REAL payload shape, mock-shape law).
- `ToolsSection` grows a LOCAL sub-router (`view: "main" | "rename"`): main gains a "Batch Rename →" button in a new group **Naming** (after Cleanup); `view === "rename"` renders `<RenameSubview onBack={...} />` instead of the groups.
- `RenameSubview` (self-contained, owns its fetches like the absorbed form pages): source toggle Objects/Materials; fields per spec (Pattern with token hint line `$n · $name · $parent · $type`, Find/Replace + Match case checkbox, Prefix, Suffix, Start # + Padding); preview table old→new (collision rows in amber with "duplicate result"); Apply primary + `← Tools`. Preview refetch: 300ms debounce on any field change AND a 2s stamp-poll effect (`fetchPanelStamp`; refetch when it changes — selection changes in C4D reflect in the preview). Apply → `postRenameApply` → toast via `renameToast` (useToast) → refetch preview.

- [ ] **Step 1: Failing vitest** — `panelRename.test.ts`: DEFAULT_RENAME_OPS shape matches the server DEFAULT_OPS field-for-field (pin every key + default value); renameToast success singular/plural, collision suffix, and the three error copys.
- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run`.
- [ ] **Step 3: Implement.** Reuse existing components: `TextInput`, `Checkbox`, `Button`, `SectionGroup`; match the FrameSubview/DeliverSection sub-router idiom for the back navigation; table styled like existing preview/list tables (grep for an existing two-column table to mirror). No client-side name computation anywhere — assert this by code review, the preview text always comes from the op.
- [ ] **Step 4: Run + build** — vitest green; `npm run build` OK; full pytest still green.
- [ ] **Step 5: Commit**

```bash
git add web/src plugin/web
git commit -m "feat(panel): Batch Rename sub-view (live server-driven preview, Naming group)"
```

---

### Task 4: Version bump, docs, full suites

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION = "1.31.0"`), `CLAUDE.md` (header + top What Works + top Version History entries, house style, "PENDIENTE verificación live" marker), `docs/superpowers/specs/2026-07-29-batch-rename-design.md` (Estado → implementado en rama, pendiente live)

**Steps:**
- [ ] **Step 1:** Bump + write entries covering: motor puro con pipeline fijo y tokens (orden de expansión $name antes que $n), preview==apply por construcción (misma función), apply re-deriva server-side (preview stale inofensivo), colisiones avisan sin bloquear, `$n` en orden de selección, sub-vista con preview vivo siguiendo la selección vía stamp, alcance objetos+materiales (takes fuera a propósito — auto-sync del Frame), arco backlog v1.32/v1.33, y cualquier fix de review del ledger.
- [ ] **Step 2:** `python3 -m pytest tests/ -q` + `cd web && npx vitest run` — real counts into CLAUDE.md.
- [ ] **Step 3: Commit**

```bash
git add plugin/sentinel/__init__.py CLAUDE.md docs/superpowers/specs/2026-07-29-batch-rename-design.md
git commit -m "docs: v1.31.0 — Batch Rename (pending live verification)"
```

---

## After the plan (session-level)

1. Final whole-branch adversarial review; fix Critical/Important.
2. Live verification (sync.sh + C4D restart + MCP): 10 cubos `luz_$n` start 5 padding 2 en orden de clic; find/replace ± case; `$parent`/`$type`; materiales; colisión avisada; **renombrar la cámara host de un Sentinel Frame → auto-sync re-nombra sus takes sin duplicar (BaseLink rename-safety)**; un Cmd+Z; preview siguiendo cambios de selección; eyeball UI.
3. Merge `--no-ff` tras confirmación del usuario; memoria; siguiente fase del arco = v1.32 RS auto-wire.
