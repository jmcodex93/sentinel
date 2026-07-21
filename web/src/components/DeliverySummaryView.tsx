import { AssetsTable } from "./AssetsTable";
import { KpiCard } from "./KpiCard";
import { formatBytes, formatCollectedAt } from "../lib/format";
import type { DeliveryReport } from "../types";

/** Pure presentational split of DeliverySummaryPage's ok-branch JSX (header
 * meta line + KPI grid + AssetsTable + manifest-path footer) — no fetch, no
 * loading/error/empty handling, just `{ data }` in, markup out. Split out so
 * the Hub's inline "delivered" state (Task 11) can render the exact same
 * summary a collected package's dedicated Delivery Summary page shows,
 * without duplicating the JSX. DeliverySummaryPage keeps the fetch and
 * renders this for its `kind: "ok"` state — behavior unchanged. */
export function DeliverySummaryView({ data }: { data: DeliveryReport }) {
  const metaParts = [
    formatCollectedAt(data.collected_at),
    data.version ?? undefined,
    data.artist || undefined,
    data.qc ? `QC ${data.qc.score}` : undefined,
    data.pending_todos > 0 ? `${data.pending_todos} pending TODO${data.pending_todos === 1 ? "" : "s"}` : undefined,
  ].filter((part): part is string => Boolean(part));

  const allCollected = data.summary.total > 0 && data.summary.collected === data.summary.total;

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <header
        className="px-[18px] py-[18px]"
        style={{
          backgroundColor: "var(--color-surface-1)",
          borderBottom: "1px solid var(--color-hairline-strong)",
        }}
      >
        <h1 className="text-title truncate" style={{ color: "var(--color-ink)" }}>
          {data.scene}
        </h1>
        {metaParts.length > 0 && (
          <p className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
            {metaParts.join(" · ")}
          </p>
        )}
      </header>

      <div className="flex-1 overflow-auto p-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard label="Collected" value={data.summary.collected} tone={allCollected ? "pass" : "neutral"} />
          <KpiCard label="Missing" value={data.summary.missing} tone={data.summary.missing > 0 ? "fail" : "neutral"} />
          <KpiCard label="External" value={data.summary.external} tone={data.summary.external > 0 ? "warn" : "neutral"} />
          <KpiCard label="Zip size" value={data.zip ? formatBytes(data.zip.bytes) : "—"} />
        </div>

        <div className="mt-4">
          <AssetsTable assets={data.assets} />
        </div>
      </div>

      <footer className="px-4 py-2" style={{ borderTop: "1px solid var(--color-hairline)" }}>
        <p className="text-caption truncate" style={{ color: "var(--color-muted)" }}>
          {data.manifest_path}
        </p>
      </footer>
    </div>
  );
}
