# Fase 5.3 — Conmutador de variantes de resolución — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch textures between on-disk resolution variants (commercial `_4k_`/`_8k_` families + our Shrink `_2K` proxies) from the Hub: detect siblings, per-selection "Switch res..." dialog, pure-relink batch in one undo.

**Architecture:** Pure detection in `assets.py` (`split_res_token`, `find_res_variants` with injectable `list_dir`); two ops (`hub/variants` batched read-only, `hub/switch_res` synchronous mutation reusing `replace_basename_preserving_form` + `_settle_relink_results`); SPA variants fetch chained after the meta sweep, `⇄` row indicator, `HubSwitchResDialog` with pure `switchTargets` computation. Spec: `docs/superpowers/specs/2026-07-21-hub-variants-design.md`.

**Tech Stack:** Python stdlib (+thin c4d ops), React/TS, vitest.

## Global Constraints

- Branch: continue on `feat/hub-optimize` (5.3 ships with 5.2 in v1.18.0). Baselines: pytest 636, vitest 43. Suites green per commit; commit trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Token map exactly `{1k:1024, 2k:2048, 4k:4096, 8k:8192, 16k:16384}`, case-insensitive, delimiters `_`/`-`/`.`/name-start/name-end (extension boundary counts); token-in-word → no match; multiple tokens → LAST one switches.
- Variant grouping: same directory + identical `(prefix, suffix)` case-insensitive; ≥2 variants required (self included); ordered px desc.
- `hub/switch_res`: relink-only (NO file writes); per-key skip reasons `already_there`/`no_variant`; stored-path form preserved via `replace_basename_preserving_form`; single finally-protected undo + EventAdd; `_settle_relink_results` for writer failures; response `{ok, switched, skipped, errors, stamp}`.
- Batched ops cap 64 keys (pattern `hub/meta`); doc guard first.
- Design tokens only; accent never state; dialog pattern = HubShrinkDialog.

## File Structure (locked)

```
plugin/sentinel/assets.py           # + split_res_token, find_res_variants
plugin/sentinel/ui/hub_ops.py       # + hub/variants, hub/switch_res
tests/test_assets.py                # + detection tests
tests/test_hub_ops.py               # + op contract tests
web/src/lib/hubTable.ts             # + switchTargets (pure)
web/src/lib/hubTable.test.ts        # + tests
web/src/types.ts / web/src/lib/api.ts  # + HubVariant types, fetchHubVariants, postHubSwitchRes (+mocks)
web/src/components/hub/HubSwitchResDialog.tsx  # NEW
web/src/components/hub/HubAssetsTable.tsx      # ⇄ indicator
web/src/components/hub/HubToolbar.tsx          # Switch res... button
web/src/pages/HubPage.tsx           # variants state + sweep chaining + dialog + flow
```

---

### Task 1: Pure detection in `assets.py`

**Interfaces:**
- `split_res_token(basename) -> tuple | None` — `(prefix, px, suffix)` where `prefix + <token> + suffix == basename` (token as found, suffix includes the extension). Regex over the stem+ext with delimiter lookarounds; LAST match wins. `_2K` (our shrink suffix) is just the generic token uppercase.
- `find_res_variants(records, list_dir=os.listdir) -> {key: [{"path","px"}]}` — per record with `resolved_path`: split its basename; no token → skip; list its dir once (cache dict per call; `list_dir` failures → skip dir), collect siblings whose split yields same case-folded `(prefix, suffix)`; include self; keep only groups ≥2; sort px desc; paths joined with the record's dir (preserve the resolved dir's real form).

**Steps:**
- [ ] **1. Failing tests** (`tests/test_assets.py`): token cases — `plaster_4k_1.jpg` → ("plaster_", 4096, "_1.jpg"); `foo_2K.png` → ("foo_", 2048, ".png"); `wood-8k.exr`; `tex.4k.tif`; `4k_start.png` (start boundary); `back4k.png` → None (in-word); `scan_4k_detail_2k.png` → last token (2k); case-insensitive. Variant cases — family `plaster_{4k,8k}_1.jpg` groups; `bar_2k.png` alone → excluded (<2); different suffix (`plaster_4k_1.jpg` vs `plaster_8k_2.jpg`) → NOT grouped; injectable fake `list_dir` + call-count assertion (dir listed once for N records in same dir).
- [ ] **2.** RED → **3.** implement → **4.** green + full suite (636+).
- [ ] **5.** Commit `feat(hub): detección pura de variantes de resolución (split_res_token, find_res_variants)`.

---

### Task 2: Ops

**Interfaces:**
- `_op_hub_variants(payload)` — doc guard → keys cap 64 (`too_many_keys`) → resolve via `_THUMB_PATHS` (one fallback scan for unknowns, pattern `hub/meta`) → build minimal records `[{"key","resolved_path"}]` → `find_res_variants` → `{"variants": {key: [{"basename": os-basename-of-variant-path, "px": px}]}}` (only keys present in the result).
- `_op_hub_switch_res(payload)` — `{keys, target}`: doc guard → validate target (`"highest"` or int>0 → else `invalid_target`) → fresh scan (records + tex) + `_remember_thumb_paths` → `find_res_variants` over the requested keys → per key: variants absent → skip `no_variant`; pick = highest px if `"highest"` else exact px match (none → `no_variant`); pick == current resolved basename (case-folded) → skip `already_there`; else stage `replace_basename_preserving_form(record["path"], variant_basename)`. Apply staged via `resolve_repath_targets` + writer loop with `write_results` bookkeeping + `_settle_relink_results`, single finally undo + EventAdd → `{ok: True, switched, skipped, errors, stamp: _stamp_for(doc)}`.
- Register both in `HUB_OPS`.

**Steps:**
- [ ] **1. Failing tests**: registration; no_document both; `_validate_switch_target` pure split tested directly (highest/2048 ok; 0/"2k"/None → invalid).
- [ ] **2.** RED → **3.** implement → **4.** `pytest tests/test_hub_ops.py tests/test_assets.py -q` + full suite.
- [ ] **5.** Commit `feat(hub): ops hub/variants + hub/switch_res (relink puro, forma de ruta conservada)`.

---

### Task 3: SPA

**Interfaces:**
- types/api: `HubVariant {basename: string; px: number}`, `fetchHubVariants(keys): Promise<Record<string, HubVariant[]>>` (POST `hub/variants`, `{}` on error, mock: fixture `hub-variants.json` with 2-3 families over mock inventory keys), `HubSwitchResponse {ok, error?, switched?, skipped?, errors?, stamp?}`, `postHubSwitchRes(keys, target: number | "highest")`.
- `hubTable.ts`: `switchTargets(selectedKeys, variants) -> {targets: [{px: number | "highest", label: string, available: number}], total: number}` — union of variant px across selection (desc) + "Highest" first; `available` = selected keys having that px (highest = keys with ≥2 variants); pure, vitest (union, counters, empty selection).
- HubPage: after the meta sweep completes, chain a variants sweep (same 64-chunk sequential pattern, merged into `variants` state; re-arm semantics identical to meta — reuse the sweep helper if trivially extractable, else parallel effect with its own completion stamp). `⇄` affix on the Res chip cell when `variants[key]` exists (title "N resolutions on disk"). Toolbar "Switch res..." enabled when any selected key has variants → `HubSwitchResDialog` (pattern HubShrinkDialog: target list from `switchTargets`, confirm → post → toast `{switched, skipped, errors}` → clear selection + re-fetch + re-anchor stamp from response).
**Steps:**
- [ ] **1.** TDD `switchTargets` → RED → GREEN.
- [ ] **2.** Implement api/types/mock/dialog/wiring; `npx vitest run` (43+new) + `npm run build` clean; restore `plugin/web/`.
- [ ] **3.** Commit `feat(web): switch resolution — variants sweep, ⇄ indicator, diálogo por selección`.

---

### Task 4: Build, docs, live

- [ ] `cd web && npm ci && npx vitest run && npm run build` — COMMIT `plugin/web/`. Full pytest (record).
- [ ] Docs: fold 5.3 into the v1.18.0 CLAUDE.md entry (still unreleased; keep live-pendiente wording accurate); ROADMAP 5.3 done; spec Desviaciones if any.
- [ ] Commit `feat(hub): fase 5.3 — switch de variantes (build + docs)`.
- [ ] Live block (controller MCP + user eyeball): real scene — `_4k_1.jpg` families + Shrink `_2K` proxies detected (⇄ visible); batch down to 2K and back to Highest; Cmd+Z single; stored-path forms preserved (relative stays relative); skips correct (`already_there`); toast counts. Then final increment review + merge/push of the whole v1.18.0 branch per user go-ahead.

## Self-Review (plan time)

- Spec coverage: detección ✅T1, ops ✅T2, SPA (sweep, indicador, diálogo) ✅T3, live ✅T4. Fuera de alcance respetado (no genera archivos, sin estado global).
- Type consistency: `find_res_variants` output ↔ op payload ↔ `HubVariant` ↔ `switchTargets` input; skip reasons `already_there`/`no_variant` consistentes T2↔T3 toasts.
- No placeholders: token map, delimitadores, última-coincidencia, orden px desc, cap 64, patrón settle — todos explícitos.
