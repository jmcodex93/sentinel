import { useCallback, useEffect, useState } from "react";
import { CheckRow } from "../components/CheckRow";
import { KeyValueList } from "../components/KeyValueList";
import { KpiCard } from "../components/KpiCard";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Section } from "../components/Section";
import type { StatusTone } from "../components/StatusDot";
import { fetchRenderValidationReport } from "../lib/api";
import type { RenderCheckStatus, RenderValidationCheck, RenderValidationReportResult } from "../types";

type PageState = { kind: "loading" } | RenderValidationReportResult;

const TONE_FOR_STATUS: Record<RenderCheckStatus, StatusTone> = {
  OK: "pass",
  FAIL: "fail",
  WARN: "warn",
};

/** A check's `items` are opaque per-frame dicts (`{"frame": 1050, "stream":
 * "Beauty"}`, or with a `bytes` field for size outliers — see
 * postrender.py) — rendered generically as `key value · key value` rather
 * than hardcoding a frame/stream shape the engine doesn't guarantee. */
function formatItem(item: Record<string, unknown>): string {
  return Object.entries(item)
    .map(([key, value]) => `${key} ${String(value)}`)
    .join(" · ");
}

function CheckItems({ check }: { check: RenderValidationCheck }) {
  const cap = 50;
  const shown = check.items.slice(0, cap);
  if (shown.length === 0) {
    return (
      <p className="text-caption py-1" style={{ color: "var(--color-ink-secondary)" }}>
        No items to show for this check.
      </p>
    );
  }
  return (
    <ul>
      {shown.map((item, index) => (
        <li key={index} className="text-caption py-1" style={{ color: "var(--color-ink-secondary)" }}>
          {formatItem(item)}
        </li>
      ))}
      {check.items.length > cap && (
        <li className="text-caption py-1" style={{ color: "var(--color-muted)" }}>
          +{check.items.length - cap} more
        </li>
      )}
    </ul>
  );
}

export function RenderValidationPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchRenderValidationReport().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error")
    return <ErrorState title="Couldn't load the Render Validation report" message={state.message} onRetry={load} />;
  if (state.kind === "empty")
    return <EmptyState title="No render validation report yet" reason={state.reason} />;

  const { data } = state;
  const contextItems = [
    { label: "Take", value: data.context.take_name },
    { label: "Version", value: data.context.version },
    {
      label: "Frame range",
      value:
        data.context.frame_start !== null && data.context.frame_end !== null
          ? `${data.context.frame_start}–${data.context.frame_end}`
          : "",
    },
    { label: "Frame mode", value: data.context.frame_mode },
  ];

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <header
        className="px-[18px] py-[18px]"
        style={{ backgroundColor: "var(--color-surface-1)", borderBottom: "1px solid var(--color-hairline-strong)" }}
      >
        <h1 className="text-title" style={{ color: "var(--color-ink)" }}>
          Render Validation
        </h1>
        <p className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
          {data.generated_at || "—"}
        </p>
      </header>

      <div
        className="text-label px-[18px] py-1"
        style={{
          height: "22px",
          display: "flex",
          alignItems: "center",
          backgroundColor: data.passed ? "var(--color-status-pass-tint-15)" : "var(--color-status-fail-tint-15)",
          color: "var(--color-ink)",
        }}
      >
        {data.passed ? "All checks passed" : "Validation failed — see checks below"}
      </div>

      <div className="flex-1 overflow-auto p-4">
        <Section title="Context">
          <div className="rounded-lg border p-4" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
            <KeyValueList items={contextItems} />
          </div>
        </Section>

        <Section title="Summary">
          <div className="grid grid-cols-3 gap-4">
            <KpiCard label="Failures" value={data.summary.failures} tone={data.summary.failures > 0 ? "fail" : "neutral"} />
            <KpiCard label="Warnings" value={data.summary.warnings} tone={data.summary.warnings > 0 ? "warn" : "neutral"} />
            <KpiCard label="Streams" value={data.summary.streams} />
          </div>
        </Section>

        <Section title="Checks">
          <div className="rounded-lg border" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
            {data.checks.map((check) => (
              <CheckRow
                key={check.id}
                tone={TONE_FOR_STATUS[check.status]}
                label={check.label}
                meta={check.count > 0 ? String(check.count) : "OK"}
                expandedContent={check.count > 0 ? <CheckItems check={check} /> : undefined}
              />
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}
