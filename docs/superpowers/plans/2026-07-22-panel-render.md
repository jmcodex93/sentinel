# Fase 6.2 — Panel SPA sección Render — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The panel's Render section — stacked status-header blocks (Preset · Sentinel Frame · AOVs · Snapshots · Post-Render), each block reusing its existing engine via thin ops, destructive actions confirm-gated inline, Validate deep-links to Reports. Native Render tab untouched (retirement is 6.4).

**Architecture:** Spec `docs/superpowers/specs/2026-07-22-panel-render-design.md`. New `panel_render_ops.py` (read `panel/render` with per-block isolation + ~10 mutation/action ops over `aovs.py`/`scene_tools`/`frame_tag`/`snapshots`/presets). SPA `RenderSection` + per-block components, pure `panelRender.ts`. Refresh = existing stamp polling; mutations echo fresh `render` + re-anchor.

**Tech Stack:** established; no new deps.

## Global Constraints

- Branch `feat/panel-render` off main. Baselines: pytest 730, vitest 72. Trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Native Render tab / all engines UNTOUCHED except: if `scene_tools._force_render_settings`/`_apply_preset` bundle a `QuestionDialog` or UI coupling, extract a dialog-free core reusable by BOTH the op and the native caller (minimal refactor, byte-equivalent behavior, native still shows its dialog). Never duplicate engine logic.
- `panel/render` read op: per-block isolated (one block failing → that block null, rest render) — mirror `panel_ops.build_panel_overview`/`_guarded_block`. Field sources copied from named engine call sites, never invented; unavailable → null.
- Destructive ops (`reset_all`, `force_vertical`, `aov_tier`) use the confirm contract: without `confirm:true` → `{ok:False, error:"confirm_required", confirm_label}` (pattern: palette `_op_palette_run` / gate). Every mutation returns `{ok, error?, stamp, render}` (fresh embedded render payload; render = the `panel/render` shape).
- Redshift-unavailable → aovs block `{error:"redshift_unavailable"}` (or null with a reason), never a crash; ops never raise past drain.
- Validate = `runPaletteAction("open_reports_render_validation")` (existing palette id — verify it exists; else the reports deep-link op used elsewhere).
- Design tokens only; accent never state; toasts for action results; no popups.
- `panel/render` must NOT run heavy work on every stamp poll — reads are `GetActiveRenderData`/settings/aov-scan (cheap) but if the AOV scan is expensive, cache by a cheap render-data signature like the overview assets cache. Verify cost live.

## File Structure (locked)

```
plugin/sentinel/ui/panel_render_ops.py     # NEW: panel/render + mutation/action ops (PANEL_RENDER_OPS)
plugin/sentinel/ui/reports_dialog.py       # merge **PANEL_RENDER_OPS
plugin/sentinel/ui/scene_tools.py          # ONLY IF extracting a dialog-free preset/reset core
tests/test_panel_render_ops.py             # NEW
web/src/lib/panelRender.ts (+ .test.ts)    # pure status/action-per-block logic
web/src/components/panel/RenderSection.tsx # NEW (+ per-block sub-components or a RenderBlock)
web/src/pages/PanelPage.tsx                # wire Render section (replace placeholder)
web/src/types.ts / web/src/lib/api.ts      # PanelRender types + fetchers
web/src/mock/panel-render.json             # NEW
```

---

### Task 1: Ops — read `panel/render` + preset/frame block mutations

**Interfaces:**
- `_op_panel_render(payload)` (read-only, per-block isolated via a `_guarded_block`-style helper): payload per the spec (`preset/frame/aovs/snapshots/postrender`). Sources (grep + copy from these): preset = `doc.GetActiveRenderData()` name + `RDATA_XRES`/`YRES` (see `panel_ops._panel_render_block` — REUSE it, extend to add `preset_names` list from iterating render datas) + doc fps; frame = detect a Sentinel Frame tag (grep `frame_tag`/`SENTINEL_FRAME_TAG_PLUGIN_ID`/`_add_sentinel_frame_tag` for the detector; camera name = tag's host object); aovs = `aovs.get_rs_aovs(doc)` count + `aovs.get_aov_multipart(doc)` + target/light-groups from `aovs.check_rs_aovs`; snapshots = `flows.get_effective_snapshot_dir()` (returns dir+origin — check its return shape) + watch flag from settings; postrender = latest `<base>_render_history.json` age (grep how Reports render_validation finds it).
- `panel/render/set_preset {preset}`: apply the named preset. Find the preset-apply engine (`panel._apply_preset` at panel.py:1042 — if UI-coupled, extract the core to scene_tools/a helper; the op calls the dialog-free core). Return `{ok, stamp, render}`.
- `panel/render/reset_all` (⚠ confirm): reuse `scene_tools._force_render_settings` (panel.py/scene_tools.py:342, has a QuestionDialog at :352 — extract the reset core WITHOUT the dialog, native keeps its dialog, op runs core on `confirm:true`). Confirm-gate.
- `panel/render/force_vertical` (⚠ confirm): reuse the Force 9:16 engine (grep `BTN_FORCE_VERTICAL` handler in panel.py). Confirm-gate.
- `panel/render/add_frame_tag`: `scene_tools._add_sentinel_frame_tag(doc)`. `panel/render/select_frame_tag`: SetActiveTag the existing frame tag (`no_tag` error if none).
- Pure `_validate_render_confirm(op, payload)` or reuse a shared confirm helper.

**Steps:**
- [ ] **1. Failing tests** (`tests/test_panel_render_ops.py`, fake harness): ops registered; `panel/render` no_document; each mutation no_document; the three ⚠ ops without `confirm:true` → `{ok:False, error:"confirm_required"}` (test the pure confirm gate directly); select_frame_tag no_tag; per-block isolation via a pure builder + monkeypatched block raising → that block null.
- [ ] **2.** RED → **3.** implement (extract dialog-free cores where needed; run full pytest to prove native paths unbroken) → **4.** `pytest tests/test_panel_render_ops.py -q` + full (730+new).
- [ ] **5.** Commit `feat(panel): ops render — read panel/render (bloques aislados) + preset/frame mutations`.

---

### Task 2: Ops — AOVs + snapshots + postrender

**Interfaces:**
- `panel/render/aov_tier {tier}` (⚠ confirm): `tier ∈ {"essentials","production","light_groups"}` → build tier list (`aovs.AOV_TIER_ESSENTIALS`/`AOV_TIER_PRODUCTION`/`_build_tier_list`) → `aovs.force_aov_tier(doc, tier_list)`. Confirm-gate. Invalid tier → error.
- `panel/render/toggle_multipart`: `aovs.set_scene_multipart(doc, not aovs.get_aov_multipart(doc))`.
- `panel/render/aov_list` (read-only, for the inline Show AOVs expand): `aovs.check_rs_aovs(doc, AOV_TIER_PRODUCTION)` reshaped → `{aovs:[{name,type}], target, light_groups, tier_coverage}` (mirror what the native "Show AOVs" MessageDialog assembles at panel.py ~2156-2185). Redshift-unavailable → `{error:"redshift_unavailable"}`.
- `panel/render/toggle_watchfolder`: flip the watch flag in `GlobalSettings` (same key the native panel uses — grep `CHK_SNAPSHOT_WATCH`/watch setting key).
- `panel/render/save_still`: `scene_tools._take_renderview_snapshot(artist_name)` — artist from settings; returns a message (no popup, toast in SPA). Guard: if no snapshot dir / no EXR, `{ok:False, error:...}` with a clear message.
- `panel/render/open_folder`: open the effective snapshot dir via the existing cross-platform opener.
- Register everything into `PANEL_RENDER_OPS`; merge `**PANEL_RENDER_OPS` into `reports_dialog._OPS` (Task 1 may have already added the dict — ensure the merge happens once, here or T1).

**Steps:**
- [ ] TDD (registration, no_document, confirm gate on aov_tier, invalid tier, redshift-unavailable degradation for aov_list, watch toggle round-trip via a pure settings helper) → RED → implement → `pytest tests/test_panel_render_ops.py -q` + full → commit `feat(panel): ops render — AOV tiers/multipart/list + snapshots (still/folder/watch)`.

---

### Task 3: SPA — types, api, pure logic, mock

**Interfaces:**
- types mirror T1/T2 payloads field-for-field: `PanelRender` (`{preset,frame,aovs,snapshots,postrender}` each nullable), block types, `PanelRenderAovList`, mutation responses `{ok,error?,stamp?,render?, confirm_label?}`.
- api: `fetchPanelRender()`, `postPanelRenderSetPreset`, `postPanelRenderResetAll(confirm?)`, `postPanelRenderForceVertical(confirm?)`, `postPanelRenderAddFrameTag`, `postPanelRenderSelectFrameTag`, `postPanelRenderAovTier(tier, confirm?)`, `postPanelRenderToggleMultipart`, `fetchPanelRenderAovList`, `postPanelRenderToggleWatch`, `postPanelRenderSaveStill`, `postPanelRenderOpenFolder`; `?mock=1` → `panel-render.json`.
- `panelRender.ts` (pure, vitest): `presetStatusLine(preset)`, `frameStatusLine(frame)`, `aovStatusLine(aovs)`, `snapshotStatusLine(snapshots)` (dir + origin), `postrenderStatusLine(postrender)`; `blockAction confirm needs` (which ops are destructive → confirm). Tests for null blocks, each status format, destructive flags.
- Mock `panel-render.json`: realistic all-5-blocks (preset Render 1920×1080 25fps + 4 preset names, no frame tag, 11 AOVs multipart on, snapshots auto dir, postrender last report age). No real client names.
- [ ] TDD panelRender.ts → implement types/api/mock → `npx vitest run` + `npm run build` clean (restore plugin/web) → commit `feat(web): panel render types + api + pure status logic + mock`.

---

### Task 4: SPA — RenderSection + wiring

**Interfaces:**
- `RenderSection.tsx`: stacked blocks, each an eyebrow label + status line + actions. Blocks: Preset (`<select>` preset + Reset All⚠ + Force 9:16⚠), Frame (Add to camera + Select tag[disabled if no tag]), AOVs (Show AOVs inline expand via `fetchPanelRenderAovList` + Essentials/Production/Light Groups⚠ + Multi-Part toggle), Snapshots (Save Still + Open Folder + Watch toggle), Post-Render (Validate deep-link). Confirm inline for ⚠ (copy QC/Overview confirm bar). Null block → "no disponible" note; aovs redshift_unavailable → its own note.
- `PanelPage.tsx`: mount `<RenderSection>` in the Render section (replace placeholder); fetch `panel/render` on entering + on stamp change; mutations toast + apply echoed `render` + re-anchor stamp + `load(true)` for the header/rail sync consistency (same lesson as QC accept).
- Design tokens; the Show AOVs expand renders the list gracefully (scroll if many).
- [ ] Implement → `npx vitest run` + `npm run build` clean; dev eyeball `?page=panel&mock=1` Render section → commit `feat(web): panel Render section — bloques Preset/Frame/AOVs/Snapshots/PostRender`.

---

### Task 5: Build + docs + live

- [ ] `npm ci && vitest && build` — COMMIT plugin/web; full pytest (record).
- [ ] Docs: `**v1.21.0**` CLAUDE.md entry (Fase 6.2, live pendiente); PLUGIN_VERSION bump; ROADMAP 6.2 done + 6.3/6.4 pending; spec deviations if any.
- [ ] Commit `feat(panel): fase 6.2 — sección Render (build + docs)`.
- [ ] Live (controller MCP + user) on SHOT_18: 5 blocks' status correct; switch preset → resolution changes; apply Production AOVs (confirm) → AOV count rises; toggle Multi-Part + Watch; Add frame tag → status → "en <camera>"; Save Still; Open Folder; Validate opens Reports; no popups; single Cmd+Z reverts a preset/AOV mutation. Fix waves as needed; then final increment review + merge/push v1.21.0 on go-ahead.

## Self-Review (plan time)

- Spec coverage: layout stacked+status ✅T4, all 5 blocks ✅T1/T2/T4, per-block isolation ✅T1, confirm on 3 destructives ✅T1/T2, Show AOVs inline ✅T2/T4, Validate deep-link ✅T4, engine reuse (extract dialog-free core if coupled) ✅T1, Frame minimal ✅T1. Fuera de alcance respetado (no frame config, no reimplementar validate, native intact).
- Consistency: `panel/render` fields ↔ TS types ↔ status helpers; confirm contract identical to QC/gate; mutations return `{ok,stamp,render}` uniformly.
