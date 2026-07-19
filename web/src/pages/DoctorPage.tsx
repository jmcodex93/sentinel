import { useCallback, useEffect, useState } from "react";
import { ErrorState, LoadingState } from "../components/PageStates";
import { KeyValueList } from "../components/KeyValueList";
import { Section } from "../components/Section";
import { StatusDot } from "../components/StatusDot";
import type { StatusTone } from "../components/StatusDot";
import { fetchDoctorReport } from "../lib/api";
import type { DoctorItem, DoctorItemStatus, DoctorReportResult } from "../types";

type PageState = { kind: "loading" } | DoctorReportResult;

const TONE_FOR_STATUS: Record<DoctorItemStatus, StatusTone> = {
  ok: "pass",
  warn: "warn",
  fail: "fail",
  info: "neutral",
};

function DoctorItemRow({ item }: { item: DoctorItem }) {
  return (
    <div className="flex items-start gap-3 px-4 py-2" style={{ borderBottom: "1px solid var(--color-hairline)" }}>
      <span className="mt-1.5 shrink-0">
        <StatusDot tone={TONE_FOR_STATUS[item.status]} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {item.label}
        </p>
        {item.detail && (
          <p className="text-caption mt-0.5" style={{ color: "var(--color-ink-secondary)" }}>
            {item.detail}
          </p>
        )}
        {item.hint && (
          <p className="text-caption mt-0.5" style={{ color: "var(--color-muted)" }}>
            {item.hint}
          </p>
        )}
      </div>
    </div>
  );
}

export function DoctorPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchDoctorReport().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") return <ErrorState title="Couldn't load the Doctor Report" message={state.message} onRetry={load} />;

  const { data } = state;
  const metaItems = [
    { label: "Sentinel", value: data.meta.sentinel_version },
    { label: "Cinema 4D", value: data.meta.c4d_version },
    { label: "OS", value: data.meta.os },
    { label: "Renderers", value: data.meta.renderers },
    { label: "Settings", value: data.meta.settings_path },
  ];

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <header
        className="px-[18px] py-[18px]"
        style={{ backgroundColor: "var(--color-surface-1)", borderBottom: "1px solid var(--color-hairline-strong)" }}
      >
        <h1 className="text-title" style={{ color: "var(--color-ink)" }}>
          Sentinel Doctor
        </h1>
        <p className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
          Environment diagnostics — {data.items.length} check{data.items.length === 1 ? "" : "s"}
        </p>
      </header>

      <div className="flex-1 overflow-auto p-4">
        <Section title="Environment">
          <div className="rounded-lg border p-4" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
            <KeyValueList items={metaItems} />
          </div>
        </Section>

        <Section title="Diagnostics">
          {data.items.length === 0 ? (
            <p className="text-body p-4" style={{ color: "var(--color-muted)" }}>
              No diagnostics reported.
            </p>
          ) : (
            <div className="rounded-lg border" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
              {data.items.map((item) => (
                <DoctorItemRow key={item.id} item={item} />
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
