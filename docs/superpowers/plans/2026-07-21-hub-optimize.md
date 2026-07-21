# Fase 5.2 — Hub Shrink + Copy into project — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch texture optimization from the Hub: multi-select rows, Shrink to a K target as a live-progress job (sibling copies + single-undo relink, originals kept), and Copy into project (copy to `<docdir>/tex/` + relink, collision-safe).

**Architecture:** Pure planners in `assets.py` (`shrink_plan`, `shrink_target_name`, `copy_plan`); job-kind dispatch added to the existing `pump_jobs` (spec gains `"kind"`, collect stays the default); shrink saves copies first (per-file progress via `JOBS`), then relinks the whole batch in ONE undo; `hub/copy_into_project` is a synchronous mutation. SPA: selection model as pure `applySelection` in `hubTable.ts`, toolbar Shrink dialog + Copy button, job progress reusing the Deliver progress pattern. Spec: `docs/superpowers/specs/2026-07-21-hub-optimize-design.md`.

**Tech Stack:** Python stdlib + c4d BaseBitmap (thin ops), React/TS, vitest.

## Global Constraints

- Branch: `feat/hub-optimize` off main. Suites green at every commit (baseline pytest 603, vitest 28). Commits with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Pure planners never import c4d and never raise. Ops follow hub_ops conventions (doc guard first, error dicts, mutation responses carry `"stamp": _stamp_for(doc)`).
- Shrink NEVER overwrites originals; sibling name `<stem>_<K><ext>` (4096→`_4K`, 2048→`_2K`, 1024→`_1K`; existing target overwritten — idempotent re-run; stem already ending in the target suffix isn't doubled).
- Saver allowlist by extension: `.png→FILTER_PNG, .jpg/.jpeg→FILTER_JPG, .tif/.tiff→FILTER_TIF, .bmp→FILTER_BMP, .tga→FILTER_TGA`; anything else (exr/hdr/psd/webp) → per-row error `unsupported format` — never silent degradation.
- Relink phase: ONE `StartUndo`/`EndUndo` (finally-protected) via `resolve_repath_targets` + `apply_texture_path_change`; only files whose save succeeded are relinked.
- Single job slot shared with collect (`JOBS.start` raising → `{"ok": False, "error": "job_running"}`).
- Copy collisions: same byte size → reuse (relink only, counted `reused`); different size → per-row error, never overwrite. Unsaved doc → `unsaved_document`.
- Design tokens only; accent never state; toasts success/info/warn; per-row errors → warn toast with count, details to console.

## File Structure (locked)

```
plugin/sentinel/assets.py           # + shrink_plan, shrink_target_name, copy_plan (pure)
plugin/sentinel/ui/hub_ops.py       # + hub/shrink_start, _run_shrink_for_job, hub/copy_into_project;
                                    #   pump_jobs kind-dispatch
tests/test_assets.py                # + planner tests
tests/test_hub_ops.py               # + op/contract tests
web/src/lib/hubTable.ts             # + applySelection (pure)
web/src/lib/hubTable.test.ts        # + selection tests
web/src/types.ts / web/src/lib/api.ts  # + shrink/copy types + fetchers (+ mock no-ops)
web/src/components/hub/HubShrinkDialog.tsx  # NEW
web/src/components/hub/HubAssetsTable.tsx   # multi-select wiring
web/src/components/hub/HubToolbar.tsx       # Shrink/Copy buttons + N selected
web/src/pages/HubPage.tsx           # selection state, dialog, job polling, copy flow
```

---

### Task 1: Pure planners in `assets.py`

**Interfaces (produces):**
- `shrink_target_name(path, target_px) -> str` — `_SHRINK_SUFFIX = {4096: "_4K", 2048: "_2K", 1024: "_1K"}`; unknown target → `_{target_px}px`. If the stem already endswith the suffix, return the same name unchanged (idempotent).
- `shrink_plan(records, metas, target_px) -> dict` — `records` = AssetRecord dicts, `metas` = `{key: meta}` (the hub/meta shapes: width/height/vram_bytes...). Output: `{"shrink": [{"key","path","resolved_path","width","height","new_width","new_height"}], "skipped": [{"key","reason"}], "vram_before": int, "vram_after": int}`. Eligible: status `ok` AND meta present AND `max(w,h) > target_px` AND `asset_type in ("texture","hdri")`. Skip reasons: `already_small`, `no_meta`, `not_image`, `not_ok`. New dims: scale factor `target_px / max(w,h)`, `round()`, min 1, aspect preserved. `vram_before/after` sum `imagemeta.vram_bytes` over the shrink list only (after uses new dims, same channels/depth).
- `copy_plan(records, doc_dir) -> dict` — `{"copy": [{"key","resolved_path","target_path"}], "skip": [{"key","reason"}]}`. Eligible: `resolved_path` set AND normalized-lowercased path does NOT start with normalized `doc_dir` + separator. Target: `os.path.join(doc_dir, "tex", basename)`. Skip reasons: `in_project`, `unresolved`.

**Steps:**
- [ ] **1. Failing tests** in `tests/test_assets.py`: suffix table + no-doubling + unknown target; plan with a mixed batch (8K shrink→2K dims exact, 2K skipped `already_small`, missing skipped `not_ok`, no-meta skipped, alembic skipped `not_image`); vram_before>vram_after and both exact via `imagemeta.vram_bytes`; non-square aspect (4000×717 @2048 → 2048×367); copy_plan in/out of project incl. case-insensitive prefix and `unresolved`.
- [ ] **2.** RED (`python3 -m pytest tests/test_assets.py -q`) → **3.** implement (import `from . import imagemeta` inside assets.py — pure↔pure is fine) → **4.** green + full suite (603+new).
- [ ] **5.** Commit `feat(hub): pure planners — shrink_plan, shrink_target_name, copy_plan`.

---

### Task 2: Ops — `hub/shrink_start` job + `hub/copy_into_project`

**Interfaces:**
- `pump_jobs` kind-dispatch: spec dict gains `"kind"` (`"collect"` default when absent — backward compatible); `kind == "shrink"` → `_run_shrink_for_job(job_id, spec)`; keep `_run_collect_for_job` boundary intact (tests monkeypatch it).
- `_op_hub_shrink_start(payload)` — `{keys, target_px}`: doc guard → validate `target_px in (4096, 2048, 1024)` (`invalid_target`) → fresh `scan_scene_assets` + `_remember_thumb_paths` → build metas via `_meta_for` for the requested keys → `assets_engine.shrink_plan` → empty shrink list → `{"ok": False, "error": "nothing_to_shrink"}` → `JOBS.start({"kind": "shrink", "plan": plan})` (catch `RuntimeError` → `job_running`) → `{"ok": True, "job_id"}`.
- `_run_shrink_for_job(job_id, spec)` — phase 1 per file: `JOBS.update(job_id, "shrink", "<basename> i/n", pct)`; `_save_shrunk_copy(item)` helper: BaseBitmap `InitWith(resolved)` → `Init(new_w, new_h)` + `ScaleIt(dst, 256, True, False)` → `Save(target, _SAVER_BY_EXT[ext])`; ext not in allowlist or any failure → collect `{"key","error"}`. Phase 2: relink saved ones — fresh scan (records may have shifted), `resolve_repath_targets(records, [{"key", "new_path": target}])`, single `doc.StartUndo()`/`finally EndUndo()` + `apply_texture_path_change` loop + `EventAdd`. `JOBS.finish(job_id, {"shrunk", "skipped": plan["skipped"], "errors", "bytes_saved"})` (`bytes_saved` = sum original size − new size via `os.path.getsize`, best-effort).
- `_op_hub_copy_into_project(payload)` — `{keys}`: doc guard → `doc.GetDocumentPath()` empty → `unsaved_document` → fresh scan → `copy_plan` filtered to requested keys → per item: target exists? same `getsize` → reused; different → error; else `os.makedirs(tex, exist_ok=True)` + `shutil.copy2` → relink batch in one undo → `{"ok": True, "copied", "reused", "errors", "stamp": _stamp_for(doc)}`.
- Register `"hub/shrink_start"`, `"hub/copy_into_project"` in `HUB_OPS`.

**Steps:**
- [ ] **1. Failing tests** (`tests/test_hub_ops.py`, fake harness): both ops registered; shrink_start no_document; shrink_start invalid target `{"ok": False, "error": "invalid_target"}` ordering AFTER doc guard (harness → no_document wins; test the validator via a small pure split if unreachable — prefer extracting `_validate_shrink_payload(payload) -> error|None` and testing it directly); copy no_document; pump_jobs kind-dispatch: seed a `{"kind": "shrink", ...}` pending job with `_run_shrink_for_job` monkeypatched → called; a kind-less spec still routes to `_run_collect_for_job` (monkeypatched) — backward compat pinned.
- [ ] **2.** RED → **3.** implement → **4.** `python3 -m pytest tests/test_hub_ops.py tests/test_assets.py -q` + full suite green.
- [ ] **5.** Commit `feat(hub): shrink job (sibling copies + single-undo relink) + copy into project op`.

---

### Task 3: SPA selection model

**Interfaces:**
- `hubTable.ts`: `export type SelectMode = "single" | "toggle" | "range";` `export function applySelection(current: Set<string>, visibleKeys: string[], anchorKey: string | null, key: string, mode: SelectMode): Set<string>` — single → `{key}`; toggle → symmetric toggle; range → keys between anchor and key inclusive in `visibleKeys` order (anchor missing/not visible → falls back to single). Always returns a NEW Set.
- `HubAssetsTable`: props `selectedKeys: Set<string>`, `onRowClick(key, {meta, shift}) `(replaces `selectedKey`/`onSelect`; derive mode: shift→range, meta/ctrl→toggle, else single); `aria-selected` per row from the Set; row still fires the owner-select only on plain single click (page decides).
- `HubPage`: `selectedKeys` state + `anchorRef`; plain click → applySelection single + `postHubSelectOwner`; Escape (keydown listener on the table container) → clear; Relink Selected enabled only when `selectedKeys.size === 1`, hint otherwise; toolbar shows `N selected`.

**Steps:**
- [ ] **1.** TDD `applySelection` in `hubTable.test.ts` (single replaces, toggle on/off, range forward/backward over a filtered ordering, anchor-not-visible fallback, immutability) → RED → implement → GREEN.
- [ ] **2.** Wire table/page/toolbar; `npx vitest run` + `npm run build` clean (restore `plugin/web/`).
- [ ] **3.** Commit `feat(web): hub multi-selection (single/toggle/range), relink gating, N selected`.

---

### Task 4: SPA — Shrink dialog + job flow + Copy button

**Interfaces:**
- types/api: `HubShrinkStartResponse {ok, error?, job_id?}`, `startHubShrink(keys, targetPx)`; `HubCopyResponse {ok, error?, copied?, reused?, errors?, stamp?}`, `postHubCopyIntoProject(keys)`. Job status reuses `fetchHubJobStatus`/`HubJobStatus` (its `result` widens: shrink jobs carry `{shrunk, skipped, errors, bytes_saved}` — type as a union or optional fields). Mock branches: shrink/copy return an informative `{ok: false, error: "mock"}` (no stateful job mock — same policy as deliver).
- `HubShrinkDialog.tsx`: props `{plan: client-side preview, targets, onConfirm(targetPx), onClose}` — the PREVIEW is computed client-side from `selectedKeys`+`metas` (mirror the eligibility rules: ok + meta + image + max>target; show n to shrink / n skipped / VRAM before→after using `vram_bytes` from metas scaled by (target/max)² approximation? NO — compute exactly like the server: new dims by factor, vram scales by (new_w*new_h)/(w*h)). Server recomputes authoritative plan anyway (client preview is informative).
- HubPage: Shrink button (enabled when any selected row is plausibly eligible) → dialog → `startHubShrink` → poll `fetchHubJobStatus` 500ms (reuse/extract the Deliver polling helper if trivially shareable — do NOT rewrite HubDeliverSection) → progress bar near the toolbar (pass-fill on neutral track) → done: toast (`Shrunk N — saved X` using bytes_saved via a small client formatter or server label; keep simple: show count + errors count), re-fetch inventory + meta sweep re-run (key set changed → new signature triggers it) + re-anchor stamp. Copy button (enabled when any selected is `absolute`) → `postHubCopyIntoProject` → toast `{copied, reused, errors}` → re-fetch + re-anchor from `stamp`.

**Steps:**
- [ ] **1.** Implement types/api/dialog/wiring. If preview math lands in `hubTable.ts` as a pure helper (`shrinkPreview(assets, metas, selected, targetPx)`), vitest it (mirror-of-server test with the Task 1 numbers: 8K→2K dims, VRAM before/after).
- [ ] **2.** `npx vitest run` + `npm run build` clean (restore `plugin/web/`).
- [ ] **3.** Commit `feat(web): shrink dialog + job progress, copy-into-project flow`.

---

### Task 5: Build, docs, live

- [ ] `cd web && npm ci && npx vitest run && npm run build` — COMMIT `plugin/web/` assets. Full `python3 -m pytest -q` (record count).
- [ ] Docs: CLAUDE.md — new `**v1.18.0**` entry (Fase 5.2, live pendiente hasta el bloque live); bump `PLUGIN_VERSION` to 1.18.0; ROADMAP: 5.2 done, backlog remainder intact.
- [ ] Commit `feat(hub): fase 5.2 — shrink + copy into project (build + docs)`.
- [ ] Live (controller + user): real scene — filter 4K → select batch → Shrink to 2K (progress visible live; `_2K` siblings on disk; single Cmd+Z restores original links; sizes/VRAM refresh alone); copy the absolute rows into `tex/` + provoke a collision (same name different size → per-row error, file untouched); `job_running` when overlapping with a collect; selection UX (toggle/range/Escape). Fix waves as needed; docs live-note updated; then merge/push per user go-ahead.

## Self-Review (plan time)

- Spec coverage: selección ✅T3, shrink job+diálogo+K targets ✅T1/T2/T4, copy síncrona+colisiones ✅T1/T2/T4, undo único ✅T2, slot único ✅T2, motor puro+tests ✅T1, live ✅T5. Fuera de alcance respetado (sin recompresión, sin hover icons).
- Type consistency: `shrink_plan` output keys ↔ `_run_shrink_for_job` consumption ↔ TS preview mirror; job spec `kind` ↔ pump dispatch ↔ backward-compat test; `applySelection` signature ↔ table `onRowClick` modes.
- No placeholders: saver allowlist, suffix table, eligibility rules, collision semantics all explicit.
