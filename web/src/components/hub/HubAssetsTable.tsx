import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import * as Tooltip from "@radix-ui/react-tooltip";
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
import type { HubAsset, HubAssetStatus, HubMeta, HubResTier } from "../../types";

const ROW_H = 44; // --space-table-row (2-line rows: name+chip+badge / path+dims+owner)
const GRID_COLUMNS = "40px minmax(160px, 1fr) 90px 90px 80px 90px 160px";

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

/** channels: 1|2→"Grey", 3→"RGB", 4→"RGBA" (Task 4 spec). */
function channelsLabel(channels: number): string {
  if (channels <= 2) return "Grey";
  if (channels === 3) return "RGB";
  return "RGBA";
}

function metaLine(meta: HubMeta | undefined): string {
  if (!meta) return "—";
  const parts = [`${meta.width}×${meta.height}`, `${channelsLabel(meta.channels)} ${meta.bit_depth}b`];
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

export function HubAssetsTable({
  assets,
  pending,
  selectedKey,
  onSelect,
  onOwnerClick,
  metas,
  sort: _sort,
  onSortChange: _onSortChange,
  colWidths: _colWidths,
  onColWidthsChange: _onColWidthsChange,
}: {
  assets: HubAsset[];
  pending: Map<string, string>;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onOwnerClick: (key: string) => void;
  metas: Record<string, HubMeta>;
  /** Sort/resize props are accepted here and rendered inert (fixed header
   * labels, fixed GRID_COLUMNS widths) — Task 5 wires the interactive click
   * handlers/resizers without touching the surrounding row markup. */
  sort?: { col: string; dir: "asc" | "desc" } | null;
  onSortChange?: (col: string) => void;
  colWidths?: Record<string, number>;
  onColWidthsChange?: (widths: Record<string, number>) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: assets.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });

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
            gridTemplateColumns: GRID_COLUMNS,
            background: "var(--color-surface-1)",
            borderBottom: "1px solid var(--color-hairline-strong)",
          }}
        >
          {["", "Name", "Type", "Status", "Size", "VRAM", "Used by"].map((h) => (
            <div key={h} className="px-2 py-2" style={{ color: "var(--color-ink-secondary)" }}>
              {h}
            </div>
          ))}
        </div>
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((row) => {
            const a = assets[row.index];
            const meta = metas[a.key];
            const pendingPath = pending.get(a.key);
            const displayPath = pendingPath ?? a.path;
            const basename = displayPath.split(/[\\/]/).pop() || displayPath;
            const extraOwners = a.owners.length - 1;
            const pathColor = pendingPath ? "var(--color-status-pass)" : "var(--color-ink-secondary)";
            return (
              <div
                key={a.key}
                role="button"
                tabIndex={0}
                aria-selected={selectedKey === a.key}
                onClick={() => onSelect(a.key)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(a.key);
                  }
                }}
                className="grid cursor-pointer items-center text-body hover:bg-[var(--color-surface-2)]"
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  right: 0,
                  transform: `translateY(${row.start}px)`,
                  height: ROW_H,
                  gridTemplateColumns: GRID_COLUMNS,
                  background: selectedKey === a.key ? "var(--color-surface-2)" : undefined,
                  borderBottom: "1px solid var(--color-hairline)",
                }}
              >
                <div className="px-2">
                  <ThumbCell asset={a} />
                </div>

                <Tooltip.Root>
                  <Tooltip.Trigger asChild>
                    <div className="flex min-w-0 flex-col justify-center gap-0.5 px-2">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate" style={{ color: "var(--color-ink)" }}>
                          {basename}
                        </span>
                        <HubResChip meta={meta} />
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

                <div className="px-2">
                  <HubStatusBadge status={a.status} />
                </div>

                <span className="truncate px-2" style={{ color: "var(--color-ink-secondary)" }}>
                  {a.size_label}
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
