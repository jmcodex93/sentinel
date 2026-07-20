# Fase 5.1 — Pulido Asset Hub (metadatos, columnas, facetas) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Hub table into a texture inspector: filename-first 2-line rows, per-row image metadata (resolution/channels/bit depth/colorspace/VRAM), disk+VRAM totals, resizable persisted columns, clickable sort, and metadata facets.

**Architecture:** New pure-stdlib `imagemeta.py` (header-only parsers, never decodes pixels, never raises) + two new ops (`hub/meta` batched+cached lazy enrichment on the thumbs-memo pattern; `hub/ui_state` persisted widths/sort) + SPA table rework keeping the virtualizer (fixed 44px rows). Single server-side source for resolution bucket label+tier. Overseer's mechanisms studied, its weaknesses avoided (blocking scan, no cache, dual bucket sources, Pillow) — spec `docs/superpowers/specs/2026-07-20-hub-polish-design.md`.

**Tech Stack:** Python stdlib (struct/os), existing fake-c4d pytest harness, React 19 + TS, vitest.

## Global Constraints

- `imagemeta.py` NEVER imports c4d and NEVER raises (corrupt/unknown → `None`); no Pillow or any new dependency.
- Bucket single source: `res_bucket(max_px)` thresholds 7168/3584/1536 → labels `8K/4K/2K/<2K`, tiers `8k/4k/2k/sm`; the SPA never re-derives label or tier.
- `vram_bytes(w,h,ch,depth)` = `w*h*ch*(depth/8) * 4/3`, defensive defaults ch→4 (if not 1-4), depth→8 (if not 8/16/32); used for BOTH rows and totals.
- Ops: existing conventions (inline `GetActiveDocument()` guard, error dicts, never raise past drain; read-only ops never mutate).
- Design tokens only; accent never marks state; res-chip chroma derived from existing DESIGN.md tokens (tints/inks), no invented hex.
- Row height stays FIXED (44px) — virtualization intact; meta arrives async, cells render "—" until filled, no layout jumps.
- Settings key `hub_spa_ui` via `GlobalSettings` (pattern: `texture_repath_presets`).
- Build committed only in the final task; suites green at every commit (baseline: pytest 556, vitest 5).
- Commits: `feat:`/`fix:` + trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure (locked)

```
plugin/sentinel/imagemeta.py        # NEW pure engine: read_image_meta, vram_bytes, res_bucket
plugin/sentinel/ui/hub_ops.py       # + hub/meta (+cache), hub/meta_totals, hub/ui_state get/save;
                                    #   hub/inventory adds totals.vram_* from cache
tests/test_imagemeta.py             # NEW
tests/test_hub_ops.py               # + meta/ui_state op tests
web/src/types.ts                    # + HubMeta, HubUiState blocks
web/src/lib/api.ts                  # + fetchHubMeta, fetchHubMetaTotals, fetchHubUiState, saveHubUiState
web/src/lib/hubTable.ts             # NEW pure sort + facet logic
web/src/lib/hubTable.test.ts        # NEW vitest
web/src/mock/hub-meta.json          # NEW fixture
web/src/components/hub/HubAssetsTable.tsx  # 2-line rows, new columns, resizers, sort headers
web/src/components/hub/HubFacets.tsx       # NEW facet chips row (or folded into HubToolbar)
web/src/pages/HubPage.tsx           # meta sweep, ui_state load/save, facet state
```

---

### Task 1: `imagemeta.py` — pure header parsers + bucket + vram

**Files:** Create `plugin/sentinel/imagemeta.py`, `tests/test_imagemeta.py`.

**Interfaces (produces):**
- `read_image_meta(path) -> dict | None` — `{"width": int, "height": int, "channels": int, "bit_depth": int, "colorspace": str}` (`colorspace` ∈ `"sRGB"|"linear"|"YCbCr"|""`). Unknown format, unreadable file, or corrupt header → `None`. Never raises.
- `vram_bytes(width, height, channels, bit_depth) -> int` and `MIP_FACTOR = 4.0/3.0`.
- `res_bucket(max_px) -> {"label": str, "tier": str}` — `>=7168→("8K","8k")`, `>=3584→("4K","4k")`, `>=1536→("2K","2k")`, else `("<2K","sm")`.

**Format specs (header-only, `struct` + bounded reads — max ~64KB per file; each parser dispatched by magic bytes):**
- **PNG** (`\x89PNG\r\n\x1a\n`): IHDR at offset 16: `>II` width/height, byte 24 bit depth, byte 25 color type → channels {0:1, 2:3, 3:1, 4:2, 6:4}; walk chunks (length `>I` + 4-byte type) until `IDAT`/`IEND`, `sRGB` chunk present → colorspace "sRGB" else "".
- **JPEG** (`\xff\xd8`): walk markers; on SOF0/1/2 (`\xff\xc0/c1/c2`): precision byte = bit depth, then `>HH` height/width, then components byte = channels. colorspace "YCbCr" when channels==3 else "".
- **TIFF** (`II*\x00` / `MM\x00*`): first IFD; tags 256 (ImageWidth), 257 (ImageLength), 258 (BitsPerSample — first value), 277 (SamplesPerPixel). colorspace "".
- **EXR** (`\x76\x2f\x31\x01`): parse header attributes (name\0 type\0 size(le int32) data) until empty name: `dataWindow` (box2i, 4×int32 → w=xmax-xmin+1, h=ymax-ymin+1), `channels` (chlist — count channels by iterating null-terminated names until empty; pixel type int32 after each name: 1=half→16, 2=float→32, 0=uint→32). colorspace "linear".
- **Radiance HDR** (`#?RADIANCE` or `#?RGBE`): scan header lines for the resolution line `-Y <h> +X <w>`; channels 3, bit_depth 32, colorspace "linear".
- **TGA** (no magic — dispatch by `.tga` extension as last resort): bytes 12-15 `<HH` width/height, byte 16 pixel depth → channels = depth//8, bit_depth 8.
- **BMP** (`BM`): `<II` at offset 18 width/height (height abs), offset 28 `<H` bpp → channels = bpp//8 (min 1), bit_depth 8.

**Steps:**
- [ ] **1. Failing tests** — build minimal synthetic headers in-test (bytes literals per format written to `tmp_path` files) asserting exact meta dicts; corrupt-header cases (truncated PNG IHDR, JPEG without SOF, empty file, unknown extension) → `None`; `res_bucket` edge tests at 7168/7167, 3584/3583, 1536/1535; `vram_bytes` defaults (ch=0→4, depth=12→8) and exact value `vram_bytes(4096,4096,3,8) == int(4096*4096*3*(4/3))`.
- [ ] **2.** `python3 -m pytest tests/test_imagemeta.py -v` → FAIL (module missing).
- [ ] **3.** Implement per the specs above. Every parser wrapped so ANY exception → `None`.
- [ ] **4.** Focused green, then `python3 -m pytest -q` (556 + new).
- [ ] **5.** Commit `feat(hub): imagemeta — pure header parsers, vram estimate, res buckets`.

---

### Task 2: Ops — `hub/meta`, `hub/meta_totals`, `hub/ui_state`, inventory VRAM totals

**Files:** Modify `plugin/sentinel/ui/hub_ops.py`; test `tests/test_hub_ops.py`.

**Interfaces:**
- Module cache `_META_CACHE = {}` keyed `(path, mtime, size_bytes)`; helper `_meta_for(path) -> dict | None` (stat + cache + `imagemeta.read_image_meta`; adds `vram_bytes`, `vram_label` (via `assets.format_size`), `res_label`, `res_tier` from `res_bucket(max(w,h))`).
- `"hub/meta"`: `{keys: [...]} → {"metas": {key: meta}}` — key→path via `_THUMB_PATHS` (fallback: one `scan_scene_assets` + `_remember_thumb_paths` when a key is unknown, same policy as `hub/thumb`); keys without path/meta simply absent. Read-only. Cap batch at 64 keys per request (`{"error": "too_many_keys"}` beyond — the SPA batches visible rows, never the world).
- `"hub/meta_totals"`: read-only; sums `vram_bytes` and disk bytes over UNIQUE resolved paths currently in `_THUMB_PATHS` that have a cache entry → `{"vram_bytes", "vram_label", "disk_bytes", "disk_label", "covered", "total"}` (`covered`/`total` = how many unique files have meta vs exist — the SPA shows "est." while partial).
- `_op_hub_inventory`: after the scan, add `totals["vram_bytes"]`/`totals["vram_label"]` from cached entries only (no parsing in the inventory path — it must stay fast).
- `"hub/ui_state"` (GET-style, read-only) → `{"state": {...}}` from `GlobalSettings.get("hub_spa_ui", {})`; `"hub/ui_state/save"` (mutation) `{state: {col_widths: {...}, sort: {col, dir}}}` → validates it is a dict, stores verbatim under `hub_spa_ui`, `{"ok": True}`.

**Steps:**
- [ ] **1. Failing tests** (fake-c4d harness; lazy imports): ops registered (`hub/meta`, `hub/meta_totals`, `hub/ui_state`, `hub/ui_state/save`); `hub/meta` no_document contract; `hub/meta` with >64 keys → `{"error": "too_many_keys"}` BEFORE the doc guard is irrelevant — pick doc-guard-first like siblings and test with harness accordingly (no doc → `{"error": "no_document"}`); pure `_meta_for` tested directly with a real tmp PNG built from the Task 1 test helper (import the synthetic-header builder or inline bytes) — cache hit asserted by monkeypatching `imagemeta.read_image_meta` to fail on second call.
- [ ] **2.** RED → **3.** implement → **4.** `python3 -m pytest tests/test_hub_ops.py tests/test_imagemeta.py -q` green, full suite green.
- [ ] **5.** Commit `feat(hub): meta ops — batched header metadata with (path,mtime,size) cache, vram totals, ui_state`.

---

### Task 3: SPA foundation — types, api, mock

**Files:** Modify `web/src/types.ts`, `web/src/lib/api.ts`; create `web/src/mock/hub-meta.json`.

**Interfaces (mirror Task 2 field-for-field):**
```ts
export interface HubMeta {
  width: number; height: number; channels: number; bit_depth: number;
  colorspace: string; vram_bytes: number; vram_label: string;
  res_label: string; res_tier: "8k" | "4k" | "2k" | "sm";
}
export interface HubMetaTotals {
  vram_bytes: number; vram_label: string; disk_bytes: number;
  disk_label: string; covered: number; total: number;
}
export interface HubUiState {
  col_widths?: Record<string, number>;
  sort?: { col: string; dir: "asc" | "desc" };
}
```
- api: `fetchHubMeta(keys: string[]): Promise<Record<string, HubMeta>>` (POST `hub/meta`, returns `{}` on any error; mock branch returns `hub-meta.json` filtered by keys), `fetchHubMetaTotals()`, `fetchHubUiState(): Promise<HubUiState>`, `saveHubUiState(state: HubUiState)` (fire-and-forget postForm). Mock `hub-meta.json`: metas for ~10 of the `hub-inventory.json` keys covering all four tiers + a greyscale + a 32b linear EXR.

**Steps:** implement → `npx vitest run` + `npm run build` clean (restore `plugin/web/` if dirtied) → commit `feat(web): hub meta/ui-state types + api + mock`.

---

### Task 4: Table rework — 2-line rows, new columns, async meta fill

**Files:** Modify `web/src/components/hub/HubAssetsTable.tsx`, `web/src/pages/HubPage.tsx`.

**Interfaces:**
- `HubAssetsTable` gains props: `metas: Record<string, HubMeta>`, `sort: {col, dir} | null`, `onSortChange(col)`, `colWidths: Record<string, number>`, `onColWidthsChange(widths)` (resizers live in Task 5 — this task ACCEPTS the props and renders fixed defaults so Task 5 is purely additive).
- Row layout (ROW_H = 44): line 1 = basename (derive `path.split(/[\\/]/).pop()`) + res chip (`metas[key]?.res_label`, colored by `res_tier`) + status badge; line 2 (`text-caption`, muted, truncated) = full path · `4096×4096 · RGB 8b · linear` (from meta; "—" while absent) · first owner. Columns: thumb 40 | name (flex) | type 90 | status 90 | size 80 | VRAM 90 | used-by 160.
- Res chip tiers → existing tokens only: `8k` = `--color-status-fail-tint-15` bg + fail text; `4k` = warn tint; `2k` = `--color-surface-2` + ink-secondary; `sm` = surface-2 + muted. (Semantic reading: heavier = hotter; consistent with Overseer's legend without new hex.)
- HubPage: meta sweep effect — after inventory ok, batch `fetchHubMeta` over ALL asset keys in chunks of 64 sequentially (not just visible — 39-500 assets ≈ ≤8 requests; simpler than viewport tracking and the cache makes repeats free), merging into a `metas` state map; then `fetchHubMetaTotals` once and render `vram_label` in the header totals line (with `~` prefix while `covered < total`).
- VRAM column cell: `metas[key]?.vram_label ?? "—"`.

**Steps:** implement → vitest + build clean → mock eyeball if dev server available → commit `feat(web): hub table 2-line rows + metadata columns + async meta sweep`.

---

### Task 5: Resizable columns, clickable sort, facets

**Files:** Create `web/src/lib/hubTable.ts`, `web/src/lib/hubTable.test.ts`, `web/src/components/hub/HubFacets.tsx`; modify `HubAssetsTable.tsx`, `HubPage.tsx`.

**Interfaces:**
- `hubTable.ts` (pure, vitest-covered):
```ts
export type SortCol = "name" | "status" | "res" | "size" | "vram";
export interface SortSpec { col: SortCol; dir: "asc" | "desc"; }
export function sortAssets(assets: HubAsset[], metas: Record<string, HubMeta>, sort: SortSpec | null): HubAsset[];
// null → default: missing first, then size_bytes desc (Overseer semantics; nulls last)
export interface FacetState { res: Set<string>; channels: Set<string>; depth: Set<number>; }
export function applyFacets(assets: HubAsset[], metas: ..., facets: FacetState): HubAsset[];
export function facetCounts(assets: HubAsset[], metas: ...): { res: Record<string, number>; channels: Record<string, number>; depth: Record<number, number>; }
// channels: 1|2→"Grey", 3→"RGB", 4→"RGBA"; assets without meta excluded from counts, NEVER filtered out unless a facet is active
```
- Resizers: 4px hit-area divider between header cells; pointerdown+move adjusts the left column's width (min 60px, name column min 160); state lifts to HubPage; `saveHubUiState` debounced 500ms after drag end; double-click divider → delete that width (back to default). Widths feed `gridTemplateColumns` (name stays `minmax(160px, 1fr)`; others `${px}px`).
- Sort headers: click cycles asc → desc → default(null); `aria-sort`; persisted via ui_state alongside widths; HubPage loads `fetchHubUiState` once at mount before first render of the table (non-blocking — defaults until it arrives).
- `HubFacets` row under the toolbar: three chip groups (Res / Channels / Depth) with counts from `facetCounts`, multi-select toggle, composing with existing status filter + search (facets apply after status+search).
- vitest: default sort (missing first, heaviest desc, nulls last), each SortCol both dirs, facet composition (res∩channels), counts exclude metaless assets, facet with zero matches shows 0 and filters to empty.

**Steps:** TDD hubTable.ts (RED → GREEN) → wire components → vitest + build clean → commit `feat(web): hub resizable columns, clickable sort, metadata facets`.

---

### Task 6: Build, docs, live verification

**Files:** `plugin/web/` (committed build), `CLAUDE.md`, `ROADMAP.md`, spec (deviations if any), `.superpowers/sdd/progress.md`.

- [ ] `cd web && npm ci && npx vitest run && npm run build` — commit regenerated assets.
- [ ] Full `python3 -m pytest -q` — record count.
- [ ] Docs: fold Fase 5.1 into the v1.17.0 CLAUDE.md entry (same release, still unreleased); ROADMAP: note 5.1 done + 5.2 backlog (Shrink / copy-into-project).
- [ ] Commit `feat(hub): fase 5.1 — inspector de texturas (build + docs)`.
- [ ] Live (user-assisted): sync + restart C4D; real scene: metas correct (cross-check 2-3 files against Overseer's reported values: same file → same dims/channels/depth), totals coherent (~537 MB disk / ~2.9 GB VRAM ballpark on the SHOT_18 scene), chips consistent (label matches color), column drag persists across window reopen, sort + facets with correct counts, no scroll regression, meta cells fill in without layout jumps.

## Self-Review (plan time)

- Spec coverage: motor ✅T1, meta op+cache+totals ✅T2, ui_state ✅T2/T5, types/api ✅T3, 2-line rows+chips+async fill ✅T4, resizers+sort+facets ✅T5, build/docs/live ✅T6. Fuera de alcance respetado (sin Shrink, sin native changes).
- Type consistency: `res_tier` values (`8k/4k/2k/sm`) consistent T1↔T2↔T3↔T4; `HubMeta` fields mirror `_meta_for` output; SortCol/FacetState only in T5 consumers.
- No placeholders: parser specs carry exact offsets/fields; token mapping for chips named explicitly.
