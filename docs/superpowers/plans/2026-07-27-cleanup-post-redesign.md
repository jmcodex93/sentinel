# Limpieza post-rediseño — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the loose ends left after the UI-redesign arc: delete the now-dead native Asset Hub fallback, fix the `⇄` switch-res bug on non-repathable rows, and correct stale docs.

**Architecture:** The SPA is the sole UI. The native `AssetHubDialog` was the last Hub fallback (`web_ops._palette_open_hub`); we commit 100% to the SPA and delete it + its exclusive UserAreas. A pure-logic frontend gate stops `⇄`/switch-res from touching non-repathable rows.

**Tech Stack:** Python 3 (fake-c4d pytest harness), React/TS (vitest). No SPA behavior change beyond the `⇄` gate → rebuild only in the frontend task.

## Global Constraints

- `TodoArea` (used by `NotesDialog`), all other form-fallback dialogs, and the pure helpers in `user_areas.py` stay.
- No test references the deleted symbols except in docstrings; `tests/test_hub_ops.py::test_palette_open_hub_still_registered` tests the no-document contract of `_palette_open_hub` and must stay green after the fallback is removed (verify what it asserts).
- Version bump to `1.25.1` (patch — cleanup).
- Baseline: pytest 848, vitest 128.

---

### Task 1: Delete the native Asset Hub fallback

**Files:**
- Modify: `plugin/sentinel/ui/dialogs.py` (delete `class AssetHubDialog` ~1070-2078; remove the deleted UserAreas from its `from .user_areas import (...)`)
- Modify: `plugin/sentinel/ui/user_areas.py` (delete `AssetHubHeaderArea`, `AssetListArea`, `PreflightStripArea`, `TextureListArea` — exclusive to the deleted dialog; KEEP `TodoArea`, `_ua_local_coords`, `_format_path_compact`, and all pure helpers)
- Modify: `plugin/sentinel/ui/web_ops.py` (`_palette_open_hub` ~516-528: drop the `except`-branch native fallback so it only tries `open_form(doc,"hub")`; on failure return an error dict instead of opening `AssetHubDialog`)
- Test: `tests/test_hub_ops.py` (verify/adjust `test_palette_open_hub_still_registered`)

- [ ] **Step 1: Confirm no live consumer of the deletion targets**

```bash
cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian"
grep -rn "AssetHubDialog(\|AssetHubHeaderArea\|AssetListArea\|PreflightStripArea\|TextureListArea" plugin/ tests/ | grep -vE "#|\"\"\"|class AssetHubDialog|user_areas.py:|import"
```
Expected: only the `web_ops.py:526` fallback call (being removed) and the `dialogs.py` import line (being edited). If a NON-docstring live consumer appears elsewhere, STOP and report. (`assets.py`/`settings.py`/`webbridge.py`/`test_assets.py` references are docstrings/comments about the pure `fit_column_widths` helper — NOT code deps — leave them.)

- [ ] **Step 2: Read `_palette_open_hub` and rewrite it without the native fallback**

Read `web_ops.py:516-528`. It currently does `try: open_form(doc,"hub") except: AssetHubDialog(...)`. Rewrite so it tries `open_form(doc,"hub")` and on exception returns `{"ok": False, "error": str(exc)}` (no native dialog). Keep the no-document guard (`if not doc: return {"ok": False, "error": "No active document"}`) EXACTLY as-is — that's what the test checks.

- [ ] **Step 3: Delete `AssetHubDialog` from `dialogs.py`**

Remove the entire `class AssetHubDialog(gui.GeDialog):` (~1070-2078). Then edit dialogs.py's `from .user_areas import (...)` block to remove `AssetHubHeaderArea, AssetListArea, PreflightStripArea, TextureListArea` (keep `TodoArea, _violation_label`). Verify no other code in dialogs.py references the removed names.

- [ ] **Step 4: Delete the 4 exclusive UserAreas from `user_areas.py`**

Remove `AssetHubHeaderArea`, `AssetListArea`, `PreflightStripArea`, `TextureListArea` classes fully (read boundaries). KEEP `TodoArea` and the shared helpers `_ua_local_coords`/`_format_path_compact` (confirm the survivors don't reference the deleted classes).

- [ ] **Step 5: Verify the test + suite**

Read `tests/test_hub_ops.py::test_palette_open_hub_still_registered` — if it only asserts the no-document contract, it stays green (the fallback removal doesn't touch that path). If it asserts something about the AssetHubDialog fallback specifically, update it to the new contract (open_form only). Run:
```bash
python3 -c "import ast; ast.parse(open('plugin/sentinel/ui/dialogs.py').read()); ast.parse(open('plugin/sentinel/ui/user_areas.py').read()); print('parse OK')"
python3 -m pytest -q
```
Expected: `parse OK` and 0 failures (baseline 848; count may stay 848).
Then the invariant:
```bash
grep -rn "AssetHubDialog\|AssetHubHeaderArea\|AssetListArea\|PreflightStripArea\|TextureListArea" plugin/ | grep -vE "#|\"\"\""
```
Expected: nothing live (only comments remain).

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/dialogs.py plugin/sentinel/ui/user_areas.py plugin/sentinel/ui/web_ops.py tests/test_hub_ops.py
git commit -m "chore: delete native AssetHubDialog fallback + its exclusive UserAreas (SPA is sole Hub)"
```

---

### Task 2: Fix `⇄` switch-res on non-repathable rows

**Files:**
- Modify: `web/src/lib/hubTable.ts` (`switchTargets` — exclude non-repathable rows)
- Modify: `web/src/components/hub/HubAssetsTable.tsx` (~500: gate the `⇄` indicator on `a.repathable`)
- Test: `web/src/lib/hubTable.test.ts`

**Interfaces:** `switchTargets(selectedKeys, variants, assets?)` — a non-repathable asset is never a switch target. The exact signature change depends on whether `switchTargets` already sees repathable; read it first (it may need the assets/records to know `repathable`, OR the caller should pre-filter selected keys to repathable ones).

- [ ] **Step 1: Read `switchTargets` (hubTable.ts:264) + the ⇄ render (HubAssetsTable.tsx:500) + how switch-res selection is built**

Determine the cleanest gate: either (a) `switchTargets` filters out keys whose asset is non-repathable (needs access to `repathable` — pass the assets/records or a `repathableKeys: Set`), or (b) the caller (HubPage) pre-filters the selected keys to repathable before calling `switchTargets`, and the ⇄ indicator is gated on `a.repathable && variantGroup`. Pick the one that keeps `switchTargets` pure and testable.

- [ ] **Step 2: Write the failing test**

Add to `web/src/lib/hubTable.test.ts` a case: a selected key whose asset is `repathable: false` (but has variants on disk) is NOT a switch target (or `switchTargets`/the filter excludes it), so switch-res never sends it to the op (which previously errored). Assert the target list excludes it. Match the real `switchTargets` signature you chose in Step 1.

Run: `cd web && npx vitest run src/lib/hubTable.test.ts` → FAIL.

- [ ] **Step 3: Implement the gate**

Apply the chosen approach: exclude non-repathable rows from switch-res, and gate the `⇄` indicator render on `a.repathable` (a non-repathable row can't be switched, so the indicator was misleading). Keep it pure/testable.

- [ ] **Step 4: Verify**

Run: `cd web && npx vitest run src/lib/hubTable.test.ts` → PASS.
Run: `npx vitest run` → baseline 128 + new, all pass.
Run: `npx tsc -b --noEmit` → clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/hubTable.ts web/src/lib/hubTable.test.ts web/src/components/hub/HubAssetsTable.tsx
git commit -m "fix(hub): don't offer ⇄/switch-res on non-repathable rows (skip, not error)"
```

---

### Task 3: Docs + build + version bump

**Files:**
- Modify: `CLAUDE.md` (remove stale `MultiFormatDialog`/`TextureRepathingDialog` "kept in code" references now that they're gone; add a v1.25.1 note; fix stale "Pendiente de verificación live" markers on the v1.23.0 Tools entries — that work WAS live-verified)
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION` → `1.25.1`)
- Rebuild: `plugin/web/` (Task 2 changed TS)
- Modify: `.superpowers/sdd/progress.md`, memory

- [ ] **Step 1: Bump version**

`plugin/sentinel/__init__.py`: `1.25.0` → `1.25.1`.

- [ ] **Step 2: Build the SPA**

Run: `cd web && npm run build` → completes; `plugin/web/assets/` updated.

- [ ] **Step 3: Run both suites**

Run: `python3 -m pytest -q` → 0 failures. `cd web && npx vitest run` → 0 failures.

- [ ] **Step 4: Docs**

- `CLAUDE.md`: bump header to v1.25.1; in the Version History correct the two v1.23.0 (Fase 6.4) entries' trailing "**Pendiente de verificación live**." to note they were live-verified (that work shipped and was confirmed); remove the "MultiFormatDialog kept in code"/"TextureRepathingDialog kept" phrasings where they now misstate reality (those classes are gone); add a short v1.25.1 entry (native AssetHubDialog fallback deleted, `⇄` non-repathable fix).
- `.superpowers/sdd/progress.md`: append the cleanup ledger lines.
- Memory `project_overview.md`: note the SPA is now the sole Hub too (no native fallback), v1.25.1.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/__init__.py plugin/web CLAUDE.md .superpowers/sdd/progress.md
git commit -m "chore: v1.25.1 — cleanup (AssetHubDialog fallback removed, ⇄ fix, docs)"
```

---

## Self-Review

- Delete dead AssetHubDialog + exclusive UserAreas + fallback → Task 1. ✓
- `⇄` non-repathable skip-not-error → Task 2. ✓
- Docs/version → Task 3. ✓
- `TodoArea`/form fallbacks/pure helpers preserved → Task 1 constraints. ✓
- No placeholder; each deletion is boundary + grep/pytest-verified; the `⇄` gate is a pure-logic vitest-covered change.
