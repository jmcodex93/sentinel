# Fase 6.5 — Jubilar el panel nativo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the native panel (`YSPanel`/`YSPanelCmd`) — extract the few live helpers `panel.py`/`user_areas.py` still share with the SPA/tests, delete the native dialog + drawing code, unregister the command, and migrate the affected tests to the real modules.

**Architecture:** A staged teardown: (1) relocate live helpers to proper homes, (2) migrate tests off the panel compat surface, (3) delete `panel.py` + trim `user_areas.py` + update the `.pyp`. Each task ends green. `dialogs.py` (SPA form fallbacks) is untouched.

**Tech Stack:** Python 3 (C4D plugin, fake-c4d pytest harness). No SPA/TS change → no bundle rebuild.

## Global Constraints

- The SPA panel + all `*_ops.py` + `frame_tag.py` + `dialogs.py` (form fallbacks) stay untouched.
- Relocations are behaviour-preserving: a moved function keeps its exact body + imports.
- No compat shim: tests are re-pointed at the real modules, never a re-export stub.
- Invariant after teardown: `grep -rn "from sentinel.ui.panel import\|from sentinel.ui import panel\b\|ui\.panel\." plugin/ tests/` returns NOTHING live (only comments/docstrings).
- The fake-c4d test harness (`sentinel_module` fixture = the loaded `.pyp`) must keep loading — the `.pyp` compat-surface loop drops `_panel` only once `panel.py` is gone (Task 4).
- Version bump to `1.25.0`.
- Baselines before this work: pytest 849 passing.

**Symbol homes (resolved during design — use these exact targets):**
- `check_cache` → `sentinel.common.cache`
- `build_baseline_artifact_details`, `build_qc_report` → `sentinel.ui.reports`
- `check_render_conflicts` (+ all `check_*`) → `sentinel.checks.scene` / `sentinel.checks.render` (per `qc/registry.py` `resolve_function` mapping)
- `format_baseline_row_message` → `sentinel.ui.user_areas` (survives the trim)
- `_iter_objs` → `sentinel.common.helpers`

---

### Task 1: Extract `export_qc_report` → `ui/report_export.py` + migrate its tests

**Files:**
- Create: `plugin/sentinel/ui/report_export.py`
- Modify: `plugin/sentinel/ui/panel.py` (delete `export_qc_report` ~260 + `_scene_snapshot_b64` ~225)
- Modify: `tests/test_baseline_artifacts.py`, `tests/test_qc_action_registry.py`

**Interfaces:**
- Produces: `report_export.export_qc_report(doc, results, artist_name, qc_summary=None) -> str|None` and `report_export._scene_snapshot_b64(doc, artist_name) -> str|None`, byte-equivalent to the panel.py originals.
- Consumes (imports the new module needs): `sentinel.ui.reports.build_qc_report`, `sentinel.versioning.{parse_version_filename, report_html_path, load_versions_for_doc}` (or `sentinel.ui.flows.load_versions_for_doc` — match the original's import), `sentinel.client_report.write_client_report_html`, `sentinel.common.settings.GlobalSettings` (if the snapshot helper uses it), `c4d`, `json`, `os`, `base64`.

- [ ] **Step 1: Create `report_export.py` by moving the two functions verbatim**

Read `panel.py:225-340` (the `_scene_snapshot_b64` + `export_qc_report` bodies). Create `plugin/sentinel/ui/report_export.py` with:
- A module docstring: "QC report export (JSON + client HTML) — extracted from the retired `ui/panel.py` (Fase 6.5). Test-covered; not currently wired to an SPA op."
- The two functions copied VERBATIM (bodies unchanged).
- All imports those bodies reference, resolved to their real modules (see the original panel.py imports for the exact source of each name: `build_qc_report` from `sentinel.ui.reports`, `load_versions_for_doc` from wherever panel.py imported it, etc.). Do NOT change any logic.

- [ ] **Step 2: Delete the two functions from `panel.py`**

Remove `def _scene_snapshot_b64` (~225-259) and `def export_qc_report` (~260-340) from `panel.py`. Leave everything else in panel.py intact for now.

- [ ] **Step 3: Migrate `test_baseline_artifacts.py`**

It uses `sentinel_module.export_qc_report` and `sentinel_module.build_baseline_artifact_details`. Change:
- `sentinel_module.export_qc_report(...)` → `from sentinel.ui.report_export import export_qc_report` + `export_qc_report(...)`.
- `sentinel_module.build_baseline_artifact_details` → `from sentinel.ui.reports import build_baseline_artifact_details`.
- Keep the SaveDialog monkeypatch/mock as-is (it now patches `report_export.c4d.storage.SaveDialog` — adjust the monkeypatch target module accordingly).

- [ ] **Step 4: Migrate `test_qc_action_registry.py`**

It uses `panel.export_qc_report`, `panel.c`, `sentinel_module._panel`. Change `export_qc_report` to import from `report_export`; drop the `_panel`/`panel.c` references (use `c4d` directly or the report_export module's `c4d`). Whatever the test asserts about the report output stays; only the source module changes.

- [ ] **Step 5: Run the migrated tests + full suite**

Run: `cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian" && python3 -m pytest tests/test_baseline_artifacts.py tests/test_qc_action_registry.py -q` → PASS.
Run: `python3 -m pytest -q` → 849 baseline, 0 failures (the compat surface still re-exports panel's remaining symbols).

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/report_export.py plugin/sentinel/ui/panel.py tests/test_baseline_artifacts.py tests/test_qc_action_registry.py
git commit -m "refactor: extract export_qc_report to ui/report_export.py; migrate tests (Fase 6.5)"
```

---

### Task 2: Extract `_select_objects` → `panel_ops`, `SentinelPaletteCmd` → `panel_spa`

**Files:**
- Modify: `plugin/sentinel/ui/panel_ops.py` (add `_select_objects`; update `_op_panel_qc_select`)
- Modify: `plugin/sentinel/ui/panel_spa.py` (add `SentinelPaletteCmd`)
- Modify: `plugin/sentinel/ui/panel.py` (delete `_select_objects` ~2853, `SentinelPaletteCmd` ~2892)
- Modify: `plugin/sentinel_panel.pyp` (palette import from `panel_spa`)

**Interfaces:**
- Produces: `panel_ops._select_objects(doc, objs)` (verbatim from panel.py, using `_iter_objs` from `common.helpers`); `panel_spa.SentinelPaletteCmd` (verbatim; opens `open_form(doc, "palette")`).

- [ ] **Step 1: Move `_select_objects` into `panel_ops.py`**

Copy `def _select_objects(doc, objs)` (panel.py:2853-2871) into `panel_ops.py` verbatim. Ensure `panel_ops` imports `_iter_objs` from `sentinel.common.helpers` (add if missing) and `c4d` (already imported). Change `panel_ops._op_panel_qc_select` (~line 549) from `from sentinel.ui.panel import _select_objects` / `_select_objects(doc, ...)` to call the now-local `_select_objects(doc, ...)`.

- [ ] **Step 2: Move `SentinelPaletteCmd` into `panel_spa.py`**

Copy the `class SentinelPaletteCmd(plugins.CommandData)` (panel.py:2892-end) into `panel_spa.py` verbatim (it only needs `plugins`, `c4d`, `safe_print`, and `open_form` — all lazy/available in panel_spa). Keep its docstring.

- [ ] **Step 3: Delete both from `panel.py`**

Remove `_select_objects` and `SentinelPaletteCmd` (and the `# -------------- registration --------------` comment stub if now orphaned) from `panel.py`. `YSPanel` + `YSPanelCmd` + `check_*` stay for now.

- [ ] **Step 4: Update the `.pyp` palette import**

In `sentinel_panel.pyp`: change `from sentinel.ui.panel import YSPanelCmd, SentinelPaletteCmd` → `from sentinel.ui.panel import YSPanelCmd` and `from sentinel.ui.panel_spa import SentinelPanelSPACmd, SentinelPaletteCmd` (SentinelPanelSPACmd is already imported there — just add SentinelPaletteCmd). The `SentinelPaletteCmd()` registration block (~line 121) is unchanged (same class, new import source).

- [ ] **Step 5: Run suite + verify no panel import from panel_ops**

Run: `python3 -m pytest -q` → 0 failures.
Run: `grep -n "from sentinel.ui.panel import\|ui\.panel\." plugin/sentinel/ui/panel_ops.py` → nothing (panel_ops no longer imports from panel).

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/panel_ops.py plugin/sentinel/ui/panel_spa.py plugin/sentinel/ui/panel.py plugin/sentinel_panel.pyp
git commit -m "refactor: move _select_objects→panel_ops, SentinelPaletteCmd→panel_spa (Fase 6.5)"
```

---

### Task 3: Trim `user_areas.py` (native-panel drawing) + migrate its test

**Files:**
- Modify: `plugin/sentinel/ui/user_areas.py` (delete `ScoreHeader`, `CheckDisplayView`/`_CHECK_DISPLAY`, `StatusArea`, `HistoryArea`, `_badge_color_for_status`)
- Modify: `tests/test_qc_registry_score.py`

**Interfaces:**
- Removed (native-panel-only drawing): `ScoreHeader`, `StatusArea`, `HistoryArea`, `CheckDisplayView`, `_CHECK_DISPLAY`, `_badge_color_for_status`.
- Kept (survive the trim — pure helpers + dialog UserAreas): `_violation_label`, `_entry_label`, `_accepted_entry_payload`, `_stale_suffix`, `format_baseline_row_message`, `TodoArea`, `_ua_local_coords`, `TextureListArea`, `AssetListArea`, `AssetHubHeaderArea`, `PreflightStripArea`, `_format_path_compact`.

- [ ] **Step 1: Confirm the deletion targets have no live (non-panel, non-test) consumers**

Run:
```bash
cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian"
grep -rn "ScoreHeader\|StatusArea\|HistoryArea\|CheckDisplayView\|_CHECK_DISPLAY\|_badge_color_for_status" plugin/ tests/ | grep -v "plugin/sentinel/ui/user_areas.py:\|plugin/sentinel/ui/panel.py:"
```
Expected: only `tests/test_qc_registry_score.py` (migrated below) and — if present — references inside `panel.py` (which is deleted in Task 4). If ANY other live module (dialogs.py, a live op) references them, STOP and report.

- [ ] **Step 2: Delete the drawing classes from `user_areas.py`**

Remove `ScoreHeader` (~266), `CheckDisplayView` + `_CHECK_DISPLAY` (~369), `StatusArea` (~371), `HistoryArea` (~553), `_badge_color_for_status` (~539). Read the file to get exact boundaries — delete each class/helper fully, leaving the pure helpers (top) and the dialog UserAreas (`TodoArea` onward, minus the ones deleted) intact. Preserve `_ua_local_coords` and `_format_path_compact` if the surviving UserAreas use them.

- [ ] **Step 3: Migrate `test_qc_registry_score.py`**

It asserts `list(sentinel_module.StatusArea.ROW_KEYS)[-1] == "fake_registry_check"` and that a removed check is absent — i.e. it validates that the CHECK_REGISTRY drives the displayed rows. Rewrite it to assert directly against the registry: `from sentinel.qc.registry import CHECK_REGISTRY` and check that a registered fake check id appears in `[e.check_id for e in CHECK_REGISTRY]` (match the test's existing fake-registry setup). Drop the `_CHECK_DISPLAY`/`StatusArea` references. `format_baseline_row_message` stays importable from `sentinel.ui.user_areas`.

- [ ] **Step 4: Run the migrated test + full suite**

Run: `python3 -m pytest tests/test_qc_registry_score.py -q` → PASS.
Run: `python3 -m pytest -q` → 0 failures.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/user_areas.py tests/test_qc_registry_score.py
git commit -m "refactor: trim native-panel drawing from user_areas; migrate registry test (Fase 6.5)"
```

---

### Task 4: Delete `panel.py` + migrate `check_*` tests + update `.pyp`

**Files:**
- Delete: `plugin/sentinel/ui/panel.py`
- Modify: `tests/test_scene_check_results.py`, `tests/c4d_runner/run_fixtures.py`
- Modify: `plugin/sentinel_panel.pyp`

**Interfaces:** none produced (removal). After this task, `sentinel.ui.panel` no longer exists.

- [ ] **Step 1: Migrate `test_scene_check_results.py`**

It uses `sentinel_module.check_render_conflicts` and `sentinel_module.check_cache`. Change:
- `check_render_conflicts` → `from sentinel.checks.render import check_render_conflicts` (verify the real name/signature; the registry maps `render.check_render_conflicts`).
- `check_cache` → `from sentinel.common.cache import check_cache`.
Keep the assertions; only re-point the imports.

- [ ] **Step 2: Migrate `tests/c4d_runner/run_fixtures.py`**

It resolves check functions by name (`check_lights`, `check_render_conflicts`, …) — currently off the panel/`sentinel_module` surface. Re-point resolution to the real check modules via the registry's `resolve_function`: for each `(fixture, check_name)`, resolve through `sentinel.qc.registry.resolve_function` using the registry entry's `structured_fn`/`legacy_fn`, OR import directly from `sentinel.checks.scene`/`render`/`assets`/`safe_areas` per the `qc/registry.py` source mapping. Read the current resolution code and replace the panel-module lookup with the real-module lookup. (This is the frozen-oracle fixture runner — keep the fixture list + expected outputs identical.)

- [ ] **Step 3: Update the `.pyp`**

In `sentinel_panel.pyp`:
- Remove `from sentinel.ui import panel as _panel` and `from sentinel.ui.panel import YSPanelCmd`.
- Remove `_panel` from the compat-surface loop: `for _module in (_dialogs, _ids, _user_areas):`.
- Remove the `YSPanelCmd` `RegisterCommandPlugin(...)` block (~line 87-93) and any `ok`-var wiring specific to it (keep the SPA panel + palette + frame-tag registrations).
- Verify no other reference to `YSPanel`/`_panel` remains in the `.pyp`.

- [ ] **Step 4: Delete `panel.py`**

```bash
git rm plugin/sentinel/ui/panel.py
```

- [ ] **Step 5: Invariant + parse + suite**

Run:
```bash
cd "/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian"
grep -rn "from sentinel.ui.panel import\|from sentinel.ui import panel\b\|ui\.panel\." plugin/ tests/ | grep -vE "#|\"\"\"|panel_ops|panel_render|panel_deliver|panel_tools|panel_frame|panel_spa"
```
Expected: NOTHING (no live import of the deleted module).
Run: `python3 -c "import ast; ast.parse(open('plugin/sentinel_panel.pyp').read()); print('pyp parse OK')"` → `pyp parse OK`.
Run: `python3 -m pytest -q` → 0 failures (the whole suite, now fully off `panel.py`).

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel_panel.pyp tests/test_scene_check_results.py tests/c4d_runner/run_fixtures.py
git rm plugin/sentinel/ui/panel.py 2>/dev/null; git add -A
git commit -m "feat: retire native panel — delete panel.py, unregister YSPanelCmd, migrate check tests (Fase 6.5)"
```

---

### Task 5: Version bump + docs

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION`)
- Modify: `CLAUDE.md`, `.superpowers/sdd/progress.md`, memory

- [ ] **Step 1: Bump version**

`plugin/sentinel/__init__.py`: `PLUGIN_VERSION = "1.24.0"` → `PLUGIN_VERSION = "1.25.0"`.

- [ ] **Step 2: Run the full suite once more**

Run: `python3 -m pytest -q` → 0 failures. (No SPA/TS change → no vitest/build needed; confirm `git status` shows no `plugin/web` changes.)

- [ ] **Step 3: Update docs**

- `CLAUDE.md`: bump header to v1.25.0; update Core Files (remove `panel.py` from the "thin UI layer" description, note the SPA panel is now the only panel); update "Known Limitations" (the docked-panel/native-panel notes that reference the native tabs); add a v1.25.0 Version History entry (native panel retired; helpers relocated to `report_export.py`/`panel_ops`/`panel_spa`; `user_areas.py` trimmed; `dialogs.py` fallbacks kept).
- `.superpowers/sdd/progress.md`: append the Fase 6.5 ledger lines.
- Memory `project_overview.md` + `MEMORY.md`: mark 6.5 done — the SPA panel is now the sole panel; UI redesign arc complete.

- [ ] **Step 4: Commit**

```bash
git add plugin/sentinel/__init__.py CLAUDE.md .superpowers/sdd/progress.md
git commit -m "chore: v1.25.0 — native panel retired (Fase 6.5)"
```

---

## Self-Review

**Spec coverage:**
- Extract `_select_objects`/`SentinelPaletteCmd`/`export_qc_report` → Tasks 1-2. ✓
- Delete `panel.py` entirely → Task 4. ✓
- Trim `user_areas.py` (drawing only) → Task 3. ✓
- Unregister `YSPanelCmd` + `.pyp` compat surface → Tasks 2 (palette import) + 4 (unregister + drop `_panel`). ✓
- Migrate ~5 tests to real modules → Tasks 1 (baseline, action_registry), 3 (registry_score), 4 (scene_check_results, run_fixtures). ✓
- `dialogs.py` untouched → no task edits it. ✓
- Invariant (no live `ui.panel` import) → Task 4 Step 5. ✓
- Version + docs → Task 5. ✓

**Placeholder scan:** No TBD. Large-block deletions (YSPanel ~2400 lines, drawing classes) are described by boundary + verified by grep/pytest, not transcribed — the moved code is relocated verbatim and the deletions are proven by the invariant grep + green suite. Each "read the file to get exact boundaries" is a concrete instruction, not deferred work.

**Type/name consistency:** New homes match consumers: `panel_ops._select_objects` (consumed by `_op_panel_qc_select`, same file); `panel_spa.SentinelPaletteCmd` (imported by the `.pyp`); `report_export.export_qc_report` (imported by the two migrated tests). Symbol homes for test migration (`common.cache.check_cache`, `reports.build_baseline_artifact_details`, `checks.render.check_render_conflicts`, `user_areas.format_baseline_row_message`, `qc.registry.CHECK_REGISTRY`) were each resolved against the current source during design.
