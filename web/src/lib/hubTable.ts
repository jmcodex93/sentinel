import type { HubAsset, HubMeta, HubVariant } from "../types";

/**
 * Pure sort/facet/resize helpers for the Asset Hub table (Task 5,
 * `docs/superpowers/plans/2026-07-20-hub-polish.md`). No `import c4d`,
 * no DOM — vitest-covered in `hubTable.test.ts`, wired into
 * `HubAssetsTable.tsx` / `HubFacets.tsx` / `HubPage.tsx`.
 */

export type SortCol = "name" | "status" | "res" | "size" | "vram";

export const SORT_COLS: readonly SortCol[] = ["name", "status", "res", "size", "vram"];

export interface SortSpec {
  col: SortCol;
  dir: "asc" | "desc";
}

/** Categorical ordering for `HubMeta.res_tier` so "res" sorts smallest→largest. */
const RES_ORDER: Record<string, number> = { sm: 0, "1k": 1, "2k": 2, "4k": 3, "8k": 4, "16k": 5 };

function basename(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/** channels: 1|2→"Grey", 3→"RGB", 4→"RGBA" (Task 4 spec). Shared by the
 * table's meta line (`HubAssetsTable.tsx`) and the Channels facet group
 * so the label never drifts between the two surfaces. */
export function channelsLabel(channels: number): string {
  if (channels <= 2) return "Grey";
  if (channels === 3) return "RGB";
  return "RGBA";
}

function sortKey(col: SortCol, asset: HubAsset, metas: Record<string, HubMeta>): number | string | null {
  switch (col) {
    case "name":
      return basename(asset.path).toLowerCase();
    case "status":
      return asset.status;
    case "size":
      return asset.size_bytes;
    case "res": {
      const meta = metas[asset.key];
      return meta ? RES_ORDER[meta.res_tier] : null;
    }
    case "vram": {
      const meta = metas[asset.key];
      return meta ? meta.vram_bytes : null;
    }
    default:
      return null;
  }
}

/** Overseer-style default order: missing assets first, then each group
 * (missing / everything else) ordered by size_bytes descending, with
 * assets that have no known size pushed to the end of their group. */
function defaultSort(assets: HubAsset[]): HubAsset[] {
  const bySizeDesc = (list: HubAsset[]): HubAsset[] => {
    const sized = list.filter((a) => a.size_bytes != null);
    const unsized = list.filter((a) => a.size_bytes == null);
    sized.sort((a, b) => (b.size_bytes as number) - (a.size_bytes as number));
    return [...sized, ...unsized];
  };
  const missing = assets.filter((a) => a.status === "missing");
  const rest = assets.filter((a) => a.status !== "missing");
  return [...bySizeDesc(missing), ...bySizeDesc(rest)];
}

/** Sorts assets for the Hub table. `sort === null` restores the default
 * order (see `defaultSort`). A `SortSpec` sorts by the given column in the
 * given direction; assets missing the sort key entirely (no meta yet for
 * `res`/`vram`) always sort to the very end, independent of `dir` — a
 * missing value is not "small", it's unknown. */
export function sortAssets(
  assets: HubAsset[],
  metas: Record<string, HubMeta>,
  sort: SortSpec | null,
): HubAsset[] {
  if (!sort) return defaultSort(assets);
  const { col, dir } = sort;
  const withKey = assets.map((asset) => ({ asset, key: sortKey(col, asset, metas) }));
  const present = withKey.filter((x): x is { asset: HubAsset; key: number | string } => x.key !== null && x.key !== undefined);
  const absent = withKey.filter((x) => x.key === null || x.key === undefined).map((x) => x.asset);
  present.sort((x, y) => {
    const cmp = typeof x.key === "string" ? x.key.localeCompare(y.key as string) : (x.key as number) - (y.key as number);
    return dir === "asc" ? cmp : -cmp;
  });
  return [...present.map((x) => x.asset), ...absent];
}

export type SelectMode = "single" | "toggle" | "range";

/** Pure selection reducer for the Hub table's multi-select (Task 3,
 * `docs/superpowers/plans/2026-07-21-hub-optimize.md`). Always returns a
 * NEW Set — callers rely on this for React state updates and must never
 * mutate `current` in place. `visibleKeys` is the caller's CURRENT
 * sorted+filtered+faceted key ordering, so "range" walks what's actually
 * on screen, not insertion/fetch order. `range` falls back to `single`
 * (clicked key only) whenever the anchor is missing or no longer present
 * in `visibleKeys` (e.g. it scrolled out from under a facet change) — a
 * stale anchor must never silently expand to the wrong range; if the
 * clicked key itself isn't in `visibleKeys` either, the result is just
 * that key (matches "single" semantics as the safest fallback). */
export function applySelection(
  current: Set<string>,
  visibleKeys: string[],
  anchorKey: string | null,
  key: string,
  mode: SelectMode,
): Set<string> {
  if (mode === "single") {
    return new Set([key]);
  }
  if (mode === "toggle") {
    const next = new Set(current);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  }
  // range
  if (anchorKey === null) return new Set([key]);
  const anchorIdx = visibleKeys.indexOf(anchorKey);
  const keyIdx = visibleKeys.indexOf(key);
  if (anchorIdx === -1 || keyIdx === -1) return new Set([key]);
  const [start, end] = anchorIdx <= keyIdx ? [anchorIdx, keyIdx] : [keyIdx, anchorIdx];
  return new Set(visibleKeys.slice(start, end + 1));
}

/** Same VRAM formula as `imagemeta.vram_bytes` in plugin/sentinel/imagemeta.py
 * (mip-chain overhead factor 4/3), so the client Shrink-dialog preview and
 * the server's authoritative `shrink_plan` never disagree on a number shown
 * to the artist before they confirm. */
const MIP_FACTOR = 4 / 3;

function vramBytes(width: number, height: number, channels: number, bitDepth: number): number {
  const ch = Number.isInteger(channels) && channels >= 1 && channels <= 4 ? channels : 4;
  const depth = bitDepth === 8 || bitDepth === 16 || bitDepth === 32 ? bitDepth : 8;
  const raw = width * height * ch * (depth / 8);
  return Math.floor(raw * MIP_FACTOR);
}

export type ShrinkSkipReason = "not_ok" | "not_image" | "no_meta" | "already_small";

export interface ShrinkPreviewItem {
  key: string;
  width: number;
  height: number;
  newWidth: number;
  newHeight: number;
}

export interface ShrinkPreviewSkip {
  key: string;
  reason: ShrinkSkipReason;
}

export interface ShrinkPreview {
  eligible: ShrinkPreviewItem[];
  skipped: ShrinkPreviewSkip[];
  vramBefore: number;
  vramAfter: number;
}

/** Client-side mirror of `assets.shrink_plan` (Task 1,
 * `docs/superpowers/plans/2026-07-21-hub-optimize.md`), scoped to
 * `selectedKeys` only — the Shrink dialog preview so the artist sees "N to
 * shrink / N skipped / VRAM before→after" before confirming. The server
 * recomputes the authoritative plan on `hub/shrink_start` regardless (a
 * fresh scan could reveal a resolved path/meta this client snapshot didn't
 * have), so this is informative, never load-bearing. Same eligibility order
 * as the Python: status "ok" -> asset_type texture/hdri -> meta present with
 * usable dims -> not already <= target. */
export function shrinkPreview(
  assets: HubAsset[],
  metas: Record<string, HubMeta>,
  selectedKeys: Set<string>,
  targetPx: number,
): ShrinkPreview {
  const eligible: ShrinkPreviewItem[] = [];
  const skipped: ShrinkPreviewSkip[] = [];
  let vramBefore = 0;
  let vramAfter = 0;

  for (const asset of assets) {
    if (!selectedKeys.has(asset.key)) continue;
    if (asset.status !== "ok") {
      skipped.push({ key: asset.key, reason: "not_ok" });
      continue;
    }
    if (asset.asset_type !== "texture" && asset.asset_type !== "hdri") {
      skipped.push({ key: asset.key, reason: "not_image" });
      continue;
    }
    const meta = metas[asset.key];
    if (!meta || !meta.width || !meta.height) {
      skipped.push({ key: asset.key, reason: "no_meta" });
      continue;
    }
    if (Math.max(meta.width, meta.height) <= targetPx) {
      skipped.push({ key: asset.key, reason: "already_small" });
      continue;
    }
    const scale = targetPx / Math.max(meta.width, meta.height);
    const newWidth = Math.max(1, Math.round(meta.width * scale));
    const newHeight = Math.max(1, Math.round(meta.height * scale));
    eligible.push({ key: asset.key, width: meta.width, height: meta.height, newWidth, newHeight });
    vramBefore += vramBytes(meta.width, meta.height, meta.channels, meta.bit_depth);
    vramAfter += vramBytes(newWidth, newHeight, meta.channels, meta.bit_depth);
  }

  return { eligible, skipped, vramBefore, vramAfter };
}

/** Longest-edge px -> the studio's own resolution-token labels (the same
 * map `split_res_token`/`find_res_variants` recognize server-side, see
 * assets.py). Falls back to a plain `<px>px` label for any px this map
 * doesn't know about (defensive only — the server only ever emits the five
 * mapped values). */
const PX_LABELS: Record<number, string> = {
  1024: "1K",
  2048: "2K",
  4096: "4K",
  8192: "8K",
  16384: "16K",
};

function pxLabel(px: number): string {
  const known = PX_LABELS[px];
  return known ? `${known} (${px}px)` : `${px}px`;
}

export interface SwitchTarget {
  px: number | "highest";
  label: string;
  available: number;
}

export interface SwitchTargetsResult {
  targets: SwitchTarget[];
  total: number;
}

/** Pure "Switch res..." dialog computation (Task 3, fase 5.3 —
 * `docs/superpowers/plans/2026-07-21-hub-variants.md`). `variants` is the
 * `hub/variants` response keyed by asset key (absent key = no detected
 * sibling group, same "absence means nothing to report" convention as
 * `hub/meta`/`metas`). Builds the union of every px present across the
 * SELECTED keys' variant groups (desc), with a synthetic `"highest"` target
 * always first — `available` for `"highest"` counts every selected key that
 * has ANY detected group (picking "Highest" always resolves to `group[0]`
 * server-side, whatever that key's own top px is), while a concrete px
 * target counts only the selected keys whose group actually contains that
 * exact px. `total` is the selection size, so the dialog can render each
 * target's "X/N available" against the same denominator. Selected keys with
 * no `variants` entry at all contribute to `total` but to no target's
 * `available` — they simply have nothing to switch. A `null`-px entry (a
 * "bare base" sibling the server couldn't enrich with a real pixel size)
 * still counts toward `highestAvailable` — the family exists, and picking
 * "Highest" resolves server-side by real pixel size, never by this label —
 * but it never contributes an exact-px target, since there is no concrete
 * value a null entry could ever match. */
export function switchTargets(
  selectedKeys: Set<string>,
  variants: Record<string, HubVariant[]>,
): SwitchTargetsResult {
  const total = selectedKeys.size;
  let highestAvailable = 0;
  const pxCounts = new Map<number, number>();

  for (const key of selectedKeys) {
    const group = variants[key];
    if (!group || group.length === 0) continue;
    highestAvailable += 1;
    const pxSet = new Set(group.map((v) => v.px).filter((px): px is number => px !== null));
    for (const px of pxSet) {
      pxCounts.set(px, (pxCounts.get(px) ?? 0) + 1);
    }
  }

  if (highestAvailable === 0) {
    return { targets: [], total };
  }

  const pxDesc = Array.from(pxCounts.keys()).sort((a, b) => b - a);
  const targets: SwitchTarget[] = [
    { px: "highest", label: "Highest", available: highestAvailable },
    ...pxDesc.map((px) => ({ px, label: pxLabel(px), available: pxCounts.get(px) as number })),
  ];
  return { targets, total };
}

export interface FacetState {
  res: Set<string>;
  channels: Set<string>;
  depth: Set<number>;
}

export function emptyFacetState(): FacetState {
  return { res: new Set(), channels: new Set(), depth: new Set() };
}

/** Filters assets by the active facet selections. Within a group, active
 * chips OR together (e.g. Res=8K or 4K); across groups they AND (Res AND
 * Channels AND Depth all must pass). An asset without cached meta is
 * excluded whenever any facet in a given group is active — there is
 * nothing to match it against — but a group with zero active chips never
 * filters anything out (metaless assets stay visible until a facet
 * actually needs meta to decide). */
export function applyFacets(
  assets: HubAsset[],
  metas: Record<string, HubMeta>,
  facets: FacetState,
): HubAsset[] {
  const anyActive = facets.res.size > 0 || facets.channels.size > 0 || facets.depth.size > 0;
  if (!anyActive) return assets;
  return assets.filter((asset) => {
    const meta = metas[asset.key];
    if (facets.res.size > 0 && (!meta || !facets.res.has(meta.res_tier))) return false;
    if (facets.channels.size > 0 && (!meta || !facets.channels.has(channelsLabel(meta.channels)))) return false;
    if (facets.depth.size > 0 && (!meta || !facets.depth.has(meta.bit_depth))) return false;
    return true;
  });
}

export interface FacetCounts {
  res: Record<string, number>;
  channels: Record<string, number>;
  depth: Record<number, number>;
}

/** Counts assets per facet value, over whatever list is passed in. `HubPage`
 * passes the status+search-filtered set (facets compose AFTER status and
 * search, per Task 5), so the counts shown next to each chip reflect what's
 * on screen before facets narrow it further — they do not recompute per
 * other active facet selections. Assets without cached meta are excluded
 * from every count bucket (nothing to attribute them to), but this
 * function never removes anything from the caller's list — see
 * `applyFacets` for the actual filtering. */
export function facetCounts(assets: HubAsset[], metas: Record<string, HubMeta>): FacetCounts {
  const res: Record<string, number> = {};
  const channels: Record<string, number> = {};
  const depth: Record<number, number> = {};
  for (const asset of assets) {
    const meta = metas[asset.key];
    if (!meta) continue;
    res[meta.res_tier] = (res[meta.res_tier] ?? 0) + 1;
    const label = channelsLabel(meta.channels);
    channels[label] = (channels[label] ?? 0) + 1;
    depth[meta.bit_depth] = (depth[meta.bit_depth] ?? 0) + 1;
  }
  return { res, channels, depth };
}

/** Columns that carry a resizable, stored pixel width. The `name` column is
 * deliberately excluded — it always renders as `minmax(160px, 1fr)` in the
 * grid template so it absorbs whatever space the others don't claim, and
 * the thumb column is a fixed 40px icon well, not user-resizable. `res` has
 * its own column (round 2 of polish, 2026-07-20) — it used to live as a
 * secondary sort control glued to the Name header; see HubAssetsTable.tsx. */
export const RESIZABLE_COLUMNS = ["type", "res", "status", "size", "vram", "usedby"] as const;
export type ResizableColumn = (typeof RESIZABLE_COLUMNS)[number];

export const DEFAULT_COL_WIDTHS: Record<ResizableColumn, number> = {
  type: 90,
  res: 70,
  status: 90,
  size: 80,
  vram: 90,
  usedby: 160,
};

export const MIN_COL_WIDTH = 60;

/** Clamps a candidate column width to the shared 60px minimum (Task 5
 * spec). The name column's 160px minimum lives in the grid template
 * itself (`minmax(160px, 1fr)`) and never goes through this path. */
export function clampColWidth(width: number): number {
  return Math.max(MIN_COL_WIDTH, Math.round(width));
}

/** Validates a `SortSpec` loaded from `sentinel_settings.json` (persisted
 * ui_state — an external, editable-by-hand file). Anything that isn't
 * exactly `{col: <a known SortCol>, dir: "asc"|"desc"}` is rejected back to
 * `null` (the default order) rather than trusted as-is. */
export function sanitizeSortSpec(value: unknown): SortSpec | null {
  if (!value || typeof value !== "object") return null;
  const col = (value as { col?: unknown }).col;
  const dir = (value as { dir?: unknown }).dir;
  if (typeof col !== "string" || !SORT_COLS.includes(col as SortCol)) return null;
  if (dir !== "asc" && dir !== "desc") return null;
  return { col: col as SortCol, dir };
}

/** Validates `col_widths` loaded from `sentinel_settings.json`. Keeps only
 * known resizable column ids with a finite numeric value, clamped to the
 * same 60px floor the live resizer enforces — corrupted or hand-edited
 * settings (a stringified number, `0`, a negative width, an unknown key)
 * must never produce a 0px/negative column, and must never smuggle in a
 * `name` width (that column is never stored — see `RESIZABLE_COLUMNS`). */
export function sanitizeColWidths(value: unknown): Partial<Record<ResizableColumn, number>> {
  const out: Partial<Record<ResizableColumn, number>> = {};
  if (!value || typeof value !== "object") return out;
  for (const id of RESIZABLE_COLUMNS) {
    const raw = (value as Record<string, unknown>)[id];
    if (typeof raw === "number" && Number.isFinite(raw)) {
      out[id] = clampColWidth(raw);
    }
  }
  return out;
}

/** Builds the table's `gridTemplateColumns` value from stored widths,
 * falling back to `DEFAULT_COL_WIDTHS` per-column when a width hasn't been
 * customized yet. Column order/count must stay in sync with the header
 * row rendered by `HubAssetsTable`. */
export function gridColumnsFor(colWidths: Partial<Record<ResizableColumn, number>>): string {
  const w = (id: ResizableColumn) => `${colWidths[id] ?? DEFAULT_COL_WIDTHS[id]}px`;
  return `40px minmax(160px, 1fr) ${w("type")} ${w("res")} ${w("status")} ${w("size")} ${w("vram")} ${w("usedby")}`;
}
