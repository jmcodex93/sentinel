import type { FacetCounts, FacetState } from "../../lib/hubTable";

const RES_ORDER = ["16k", "8k", "4k", "2k", "1k", "sm"] as const;
const RES_LABEL: Record<string, string> = {
  "16k": "16K",
  "8k": "8K",
  "4k": "4K",
  "2k": "2K",
  "1k": "1K",
  sm: "<1K",
};
const CHANNELS_ORDER = ["Grey", "RGB", "RGBA"] as const;
const DEPTH_ORDER = [8, 16, 32] as const;

function Chip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      disabled={count === 0 && !active}
      className="text-label inline-flex shrink-0 items-center gap-1 rounded-sm px-2 py-1 transition-colors duration-100 ease-out disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        color: active ? "var(--color-on-primary)" : "var(--color-ink-secondary)",
        backgroundColor: active ? "var(--color-primary)" : "var(--color-surface-2)",
        border: "1px solid " + (active ? "var(--color-primary)" : "var(--color-hairline)"),
      }}
    >
      {label} <span style={{ opacity: 0.75 }}>{count}</span>
    </button>
  );
}

function FacetGroup<T extends string | number>({
  title,
  values,
  labelFor,
  counts,
  active,
  onToggle,
}: {
  title: string;
  values: readonly T[];
  labelFor: (value: T) => string;
  counts: Record<string, number>;
  active: Set<T>;
  onToggle: (value: T) => void;
}) {
  const present = values.filter((v) => (counts[String(v)] ?? 0) > 0 || active.has(v));
  if (present.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-caption shrink-0" style={{ color: "var(--color-muted)" }}>
        {title}
      </span>
      {present.map((value) => (
        <Chip
          key={String(value)}
          label={labelFor(value)}
          count={counts[String(value)] ?? 0}
          active={active.has(value)}
          onClick={() => onToggle(value)}
        />
      ))}
    </div>
  );
}

/** Metadata facet row (Res / Channels / Depth) shown under the toolbar.
 * Composes AFTER the existing status filter + search — `HubPage` passes
 * counts computed over that already-filtered set (see `facetCounts` in
 * `hubTable.ts`). A group with every count at 0 (and nothing active in it)
 * hides itself entirely rather than showing a row of dead chips. */
export function HubFacets({
  counts,
  facets,
  onChange,
}: {
  counts: FacetCounts;
  facets: FacetState;
  onChange: (facets: FacetState) => void;
}) {
  const toggle = <K extends "res" | "channels" | "depth">(group: K, value: FacetState[K] extends Set<infer V> ? V : never) => {
    const next: FacetState = { res: new Set(facets.res), channels: new Set(facets.channels), depth: new Set(facets.depth) };
    const target = next[group] as Set<typeof value>;
    if (target.has(value)) target.delete(value);
    else target.add(value);
    onChange(next);
  };

  const hasAny =
    RES_ORDER.some((v) => (counts.res[v] ?? 0) > 0) ||
    CHANNELS_ORDER.some((v) => (counts.channels[v] ?? 0) > 0) ||
    DEPTH_ORDER.some((v) => (counts.depth[v] ?? 0) > 0);
  if (!hasAny) return null;

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2"
      style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
    >
      <FacetGroup
        title="Res"
        values={RES_ORDER}
        labelFor={(v) => RES_LABEL[v]}
        counts={counts.res}
        active={facets.res}
        onToggle={(v) => toggle("res", v)}
      />
      <FacetGroup
        title="Channels"
        values={CHANNELS_ORDER}
        labelFor={(v) => v}
        counts={counts.channels}
        active={facets.channels}
        onToggle={(v) => toggle("channels", v)}
      />
      <FacetGroup
        title="Depth"
        values={DEPTH_ORDER}
        labelFor={(v) => `${v}b`}
        counts={counts.depth}
        active={facets.depth}
        onToggle={(v) => toggle("depth", v)}
      />
    </div>
  );
}
