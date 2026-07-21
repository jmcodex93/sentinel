import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import * as Tooltip from "@radix-ui/react-tooltip";
import { ArrowDown, ArrowUp } from "lucide-react";
import {
  Image as ImageIcon,
  Sun,
  Box,
  Cloud,
  Lightbulb,
  SlidersHorizontal,
  Music,
  Package,
  File as FileIcon,
  type LucideIcon,
} from "lucide-react";
import type { HubAsset, HubAssetStatus, HubMeta, HubResTier, HubVariant } from "../../types";
import {
  channelsLabel as sharedChannelsLabel,
  clampColWidth,
  DEFAULT_COL_WIDTHS,
  gridColumnsFor,
  type ResizableColumn,
  type SortCol,
  type SortSpec,
} from "../../lib/hubTable";

const ROW_H = 44; // --space-table-row (2-line rows: name+chip+badge / path+dims+owner)

/** Res-chip chroma → existing DESIGN.md tokens only (Task 4 mapping,
 * `docs/superpowers/plans/2026-07-20-hub-polish.md`). No `--color-status-warn-tint-15`
 * token exists yet, so 4k reuses the warn 10% badge tint (closest existing token). */
const RES_CHIP_META: Record<HubResTier, { color: string; background: string }> = {
  "8k": { color: "var(--color-status-fail)", background: "var(--color-status-fail-tint-15)" },
  "4k": { color: "var(--color-status-warn)", background: "var(--color-status-warn-tint-10)" },
  "2k": { color: "var(--color-ink-secondary)", background: "var(--color-surface-2)" },
  sm: { color: "var(--color-muted)", background: "var(--color-surface-2)" },
};

function HubResChip({ meta }: { meta: HubMeta | undefined }) {
  if (!meta) return null;
  const chip = RES_CHIP_META[meta.res_tier];
  return (
    <span
      className="text-label inline-block shrink-0 rounded-sm px-1.5 py-0.5"
      style={{ color: chip.color, backgroundColor: chip.background }}
    >
      {meta.res_label}
    </span>
  );
}

function metaLine(meta: HubMeta | undefined): string {
  if (!meta) return "—";
  const parts = [`${meta.width}×${meta.height}`, `${sharedChannelsLabel(meta.channels)} ${meta.bit_depth}b`];
  if (meta.colorspace) parts.push(meta.colorspace);
  return parts.join(" · ");
}

/** asset_type (see assets.py `_TYPE_BY_EXT`) → fallback icon shown when
 * `has_thumb` is false or the thumbnail request fails. */
const TYPE_ICONS: Record<string, LucideIcon> = {
  texture: ImageIcon,
  hdri: Sun,
  alembic: Box,
  vdb: Cloud,
  ies: Lightbulb,
  lut_ocio: SlidersHorizontal,
  sound: Music,
  xref: FileIcon,
  proxy: Package,
};

function TypeIcon({ assetType }: { assetType: string }) {
  const Icon = TYPE_ICONS[assetType] ?? FileIcon;
  return <Icon size={14} strokeWidth={2} aria-hidden="true" style={{ color: "var(--color-ink-secondary)" }} />;
}

/** missing→fail, absolute/empty→warn, asset_uri→neutral, ok→pass — semantic
 * chroma only (Rule 2 in DESIGN.md: the accent never marks state). */
const STATUS_META: Record<HubAssetStatus, { label: string; color: string; background: string }> = {
  missing: { label: "missing", color: "var(--color-status-fail)", background: "var(--color-status-fail-tint-10)" },
  absolute: { label: "absolute", color: "var(--color-status-warn)", background: "var(--color-status-warn-tint-10)" },
  empty: { label: "empty", color: "var(--color-status-warn)", background: "var(--color-status-warn-tint-10)" },
  asset_uri: { label: "asset uri", color: "var(--color-status-neutral)", background: "var(--color-status-neutral-tint-10)" },
  ok: { label: "ok", color: "var(--color-status-pass)", background: "var(--color-status-pass-tint-10)" },
};

function HubStatusBadge({ status }: { status: HubAssetStatus }) {
  const meta = STATUS_META[status];
  return (
    <span
      className="text-label inline-block rounded-sm px-1.5 py-0.5"
      style={{ color: meta.color, backgroundColor: meta.background }}
    >
      {meta.label}
    </span>
  );
}

function ThumbCell({ asset }: { asset: HubAsset }) {
  const [failed, setFailed] = useState(false);
  if (!asset.has_thumb || failed) {
    return (
      <div className="flex h-full items-center justify-center">
        <TypeIcon assetType={asset.asset_type} />
      </div>
    );
  }
  return (
    <div className="flex h-full items-center justify-center">
      <img
        loading="lazy"
        src={`/thumb?key=${encodeURIComponent(asset.key)}`}
        alt=""
        className="h-6 w-6 rounded-sm object-cover"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

/** One entry per grid column, in `gridColumnsFor`'s fixed order. `sortCol`
 * is `null` for columns with no corresponding `SortCol` (thumb icon well,
 * Type, Used by — Type is a free-text category and Used by is an array,
 * neither reduces to a single sortable scalar). `resizeId` is set only for
 * the columns tracked in `RESIZABLE_COLUMNS`. `res` got its own column in
 * round 2 of polish (2026-07-20) — it used to be a secondary `text-caption`
 * sort control glued to the Name header (see the deviation note in
 * `docs/superpowers/specs/2026-07-20-hub-polish-design.md`); now it's a
 * normal sortable/resizable column like the rest, no special-casing below. */
const HEADER_COLUMNS: { id: string; label: string; sortCol: SortCol | null; resizeId: ResizableColumn | null }[] = [
  { id: "thumb", label: "", sortCol: null, resizeId: null },
  { id: "name", label: "Name", sortCol: "name", resizeId: null },
  { id: "type", label: "Type", sortCol: null, resizeId: "type" },
  { id: "res", label: "Res", sortCol: "res", resizeId: "res" },
  { id: "status", label: "Status", sortCol: "status", resizeId: "status" },
  { id: "size", label: "Size", sortCol: "size", resizeId: "size" },
  { id: "vram", label: "VRAM", sortCol: "vram", resizeId: "vram" },
  { id: "usedby", label: "Used by", sortCol: null, resizeId: "usedby" },
];

/** asc → desc → default(null); mirrors the SortSpec cycle in hubTable.ts. */
function nextSort(current: SortSpec | null | undefined, col: SortCol): SortSpec | null {
  if (!current || current.col !== col) return { col, dir: "asc" };
  if (current.dir === "asc") return { col, dir: "desc" };
  return null;
}

function SortIndicator({ dir }: { dir: "asc" | "desc" }) {
  const Icon = dir === "asc" ? ArrowUp : ArrowDown;
  return <Icon size={11} strokeWidth={2.5} aria-hidden="true" style={{ display: "inline", verticalAlign: "-1px" }} />;
}

/** Divider + 8px hit-area on the LEFT edge of a resizable header cell — i.e.
 * on the boundary with the PREVIOUS column. This geometry is forced by the
 * grid layout: every resizable column sits to the right of the single
 * flexible `Name` track (`minmax(160px, 1fr)`), which absorbs whatever
 * space the fixed columns don't claim. That means a fixed column's LEFT
 * edge = (container width) − (sum of every fixed column at/after it), which
 * moves when its own width changes — its RIGHT edge is anchored by
 * whatever sits after it and does NOT track a resize of this column. A
 * divider placed on the right edge of a column (round 2 polish) therefore
 * never visibly follows the pointer for anything but the very last column:
 * the boundary the user is dragging stays put while `Name`, off to the
 * left, silently absorbs the delta — which reads as the drag doing nothing,
 * or moving backwards. Anchoring the divider on the LEFT edge instead makes
 * it track correctly, but flips the sign: this column's left edge moves
 * LEFT as it grows (eating into `Name`'s space) and RIGHT as it shrinks, so
 * `handlePointerMove` computes `startWidth - delta` — pointer left (negative
 * delta) grows the column and moves its left edge (the divider) left with
 * the pointer; pointer right shrinks it and moves the edge right with the
 * pointer. Double-click deletes the stored width entirely (falls back to
 * `DEFAULT_COL_WIDTHS` at render, rather than freezing in today's default
 * value — future default tuning then still reaches a user who's reset).
 * Pointer cancel (e.g. the OS interrupts the gesture) is treated like
 * pointerup: commit + persist whatever width the drag reached, never leave
 * it uncommitted. Lives as an absolutely-positioned sibling of the header
 * label, so a drag gesture never lands on — and can never trigger — the
 * sort button. */
function ColumnResizer({
  colId,
  width,
  onResize,
  onResizeEnd,
  onReset,
}: {
  colId: ResizableColumn;
  width: number;
  onResize: (colId: ResizableColumn, width: number) => void;
  onResizeEnd: () => void;
  onReset: (colId: ResizableColumn) => void;
}) {
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [hovering, setHovering] = useState(false);

  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragRef.current = { startX: event.clientX, startWidth: width };
      setDragging(true);
      (event.target as HTMLElement).setPointerCapture(event.pointerId);
    },
    [width],
  );

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      const delta = event.clientX - dragRef.current.startX;
      // Inverted vs. a naive right-edge resizer: this divider sits on the
      // column's LEFT edge, which moves left as the column grows (see the
      // comment above ColumnResizer) — so growing the column requires
      // SUBTRACTING the pointer's rightward delta, not adding it.
      onResize(colId, clampColWidth(dragRef.current.startWidth - delta));
    },
    [colId, onResize],
  );

  const endDrag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setDragging(false);
      try {
        (event.target as HTMLElement).releasePointerCapture(event.pointerId);
      } catch {
        // pointercancel may have already released capture — commit regardless
      }
      onResizeEnd();
    },
    [onResizeEnd],
  );

  const highlighted = dragging || hovering;

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onPointerEnter={() => setHovering(true)}
      onPointerLeave={() => setHovering(false)}
      onDoubleClick={(event) => {
        event.stopPropagation();
        onReset(colId);
      }}
      className="absolute top-0 h-full w-2 cursor-col-resize touch-none select-none"
      style={{ left: -4, zIndex: 2 }}
    >
      <div
        aria-hidden="true"
        className="absolute top-0 h-full"
        style={{
          left: "50%",
          width: 1,
          transform: "translateX(-50%)",
          backgroundColor: highlighted ? "var(--color-hairline-strong)" : "var(--color-hairline)",
        }}
      />
    </div>
  );
}

export function HubAssetsTable({
  assets,
  pending,
  selectedKeys,
  onRowClick,
  onOwnerClick,
  metas,
  variants,
  sort,
  onSortChange,
  colWidths,
  onColWidthsChange,
}: {
  assets: HubAsset[];
  pending: Map<string, string>;
  selectedKeys: Set<string>;
  onRowClick: (key: string, modifiers: { meta: boolean; shift: boolean }) => void;
  onOwnerClick: (key: string) => void;
  metas: Record<string, HubMeta>;
  /** Fase 5.3 — `hub/variants` sweep result, keyed by asset key. Optional so
   * existing callers/tests that don't exercise the variants sweep don't
   * need to pass an empty object explicitly. */
  variants?: Record<string, HubVariant[]>;
  sort?: SortSpec | null;
  onSortChange?: (sort: SortSpec | null) => void;
  colWidths?: Partial<Record<ResizableColumn, number>>;
  onColWidthsChange?: (widths: Partial<Record<ResizableColumn, number>>, commit: boolean) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: assets.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });

  const widths = colWidths ?? {};
  const gridColumns = gridColumnsFor(widths);

  const handleResize = useCallback(
    (colId: ResizableColumn, width: number) => {
      onColWidthsChange?.({ ...widths, [colId]: width }, false);
    },
    [onColWidthsChange, widths],
  );
  const handleResizeEnd = useCallback(() => {
    onColWidthsChange?.(widths, true);
  }, [onColWidthsChange, widths]);
  const handleResetWidth = useCallback(
    (colId: ResizableColumn) => {
      const next = { ...widths };
      delete next[colId];
      onColWidthsChange?.(next, true);
    },
    [onColWidthsChange, widths],
  );

  if (assets.length === 0) {
    return (
      <p className="text-body p-4" style={{ color: "var(--color-muted)" }}>
        No assets recorded for this scene.
      </p>
    );
  }

  return (
    <Tooltip.Provider delayDuration={300}>
      <div
        ref={scrollRef}
        className="overflow-auto rounded-lg border"
        style={{ maxHeight: "52vh", borderColor: "var(--color-hairline)" }}
      >
        {/* header: sticky flex row (not <table> — the virtualizer positions rows
            absolutely; grid-template columns keep header/rows aligned) */}
        <div
          className="sticky top-0 z-10 grid text-label"
          style={{
            gridTemplateColumns: gridColumns,
            background: "var(--color-surface-1)",
            borderBottom: "1px solid var(--color-hairline-strong)",
          }}
        >
          {HEADER_COLUMNS.map((col) => {
            const isSorted = sort?.col === col.sortCol;
            // aria-sort belongs on the header cell (role="columnheader"), not
            // the button inside it — assistive tech ignores aria-sort on
            // non-columnheader elements.
            const cellAriaSort = isSorted ? (sort!.dir === "asc" ? "ascending" : "descending") : "none";
            return (
              <div
                key={col.id}
                role="columnheader"
                aria-sort={cellAriaSort}
                className="relative flex items-center gap-1 px-2 py-2"
                style={{ color: "var(--color-ink-secondary)" }}
              >
                {col.sortCol ? (
                  <button
                    type="button"
                    onClick={() => onSortChange?.(nextSort(sort, col.sortCol as SortCol))}
                    className="flex items-center gap-1 hover:text-[var(--color-ink)]"
                    style={{ color: isSorted ? "var(--color-ink)" : "inherit" }}
                  >
                    {col.label}
                    {isSorted && <SortIndicator dir={sort!.dir} />}
                  </button>
                ) : (
                  col.label
                )}
                {col.resizeId && (
                  <ColumnResizer
                    colId={col.resizeId}
                    width={widths[col.resizeId] ?? DEFAULT_COL_WIDTHS[col.resizeId]}
                    onResize={handleResize}
                    onResizeEnd={handleResizeEnd}
                    onReset={handleResetWidth}
                  />
                )}
              </div>
            );
          })}
        </div>
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((row) => {
            const a = assets[row.index];
            const meta = metas[a.key];
            const variantGroup = variants?.[a.key];
            const pendingPath = pending.get(a.key);
            const displayPath = pendingPath ?? a.path;
            const basename = displayPath.split(/[\\/]/).pop() || displayPath;
            const extraOwners = a.owners.length - 1;
            const pathColor = pendingPath ? "var(--color-status-pass)" : "var(--color-ink-secondary)";
            const isSelected = selectedKeys.has(a.key);
            return (
              <div
                key={a.key}
                role="button"
                tabIndex={0}
                aria-selected={isSelected}
                onPointerDown={(event) => {
                  // A shift-click otherwise fires the browser's native text
                  // selection drag on the row's text nodes — preventDefault
                  // here (not on click, which fires too late) suppresses it.
                  if (event.shiftKey) event.preventDefault();
                }}
                onClick={(event) => onRowClick(a.key, { meta: event.metaKey || event.ctrlKey, shift: event.shiftKey })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    // Keyboard activation is always treated as a plain click,
                    // regardless of live modifier keys — range/toggle are
                    // pointer gestures over the visible list.
                    onRowClick(a.key, { meta: false, shift: false });
                  }
                }}
                className="grid cursor-pointer items-center text-body hover:bg-[var(--color-surface-2)] select-none"
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  right: 0,
                  transform: `translateY(${row.start}px)`,
                  height: ROW_H,
                  gridTemplateColumns: gridColumns,
                  background: isSelected ? "var(--color-surface-2)" : undefined,
                  borderBottom: "1px solid var(--color-hairline)",
                }}
              >
                <div className="px-2">
                  <ThumbCell asset={a} />
                </div>

                <Tooltip.Root>
                  <Tooltip.Trigger asChild>
                    <div className="flex min-w-0 flex-col justify-center gap-0.5 px-2">
                      <span className="truncate" style={{ color: "var(--color-ink)" }}>
                        {basename}
                      </span>
                      <span className="text-caption truncate" style={{ color: pathColor }}>
                        {displayPath} · {metaLine(meta)}
                        {a.owners.length > 0 ? ` · ${a.owners[0].name}` : ""}
                      </span>
                    </div>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content
                      side="top"
                      align="start"
                      sideOffset={4}
                      className="text-caption max-w-md rounded-md px-2 py-1 shadow-lg"
                      style={{
                        backgroundColor: "var(--color-surface-2)",
                        color: "var(--color-ink)",
                        border: "1px solid var(--color-hairline-strong)",
                      }}
                    >
                      {a.path}
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>

                <span className="truncate px-2" style={{ color: "var(--color-ink-secondary)" }}>
                  {a.asset_type}
                </span>

                <div className="flex items-center gap-1 px-2">
                  {meta ? <HubResChip meta={meta} /> : <span style={{ color: "var(--color-muted)" }}>—</span>}
                  {variantGroup && (
                    <span
                      className="text-label"
                      style={{ color: "var(--color-ink-secondary)" }}
                      title={`${variantGroup.length} resolutions on disk`}
                    >
                      ⇄
                    </span>
                  )}
                </div>

                <div className="px-2">
                  <HubStatusBadge status={a.status} />
                </div>

                <span className="truncate px-2" style={{ color: "var(--color-ink-secondary)" }}>
                  {a.size_bytes != null && a.size_bytes < 0 ? "—" : a.size_label}
                </span>

                <span className="truncate px-2" style={{ color: "var(--color-ink-secondary)" }}>
                  {meta?.vram_label ?? "—"}
                </span>

                <div className="px-2">
                  {a.owners.length === 0 ? (
                    <span style={{ color: "var(--color-muted)" }}>—</span>
                  ) : (
                    <button
                      type="button"
                      className="truncate underline-offset-2 hover:underline"
                      style={{ color: "var(--color-ink-secondary)" }}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOwnerClick(a.key);
                      }}
                    >
                      {a.owners[0].name}
                      {extraOwners > 0 ? ` (+${extraOwners})` : ""}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Tooltip.Provider>
  );
}
