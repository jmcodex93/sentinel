import { Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CheckRow } from "../components/CheckRow";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Section } from "../components/Section";
import type { StatusTone } from "../components/StatusDot";
import { fetchQcReport } from "../lib/api";
import type { QcCheck, QcReportResult } from "../types";

type PageState = { kind: "loading" } | QcReportResult;

/** Dot tone for a check row: pass when clean, disabled -> neutral, else the
 * check's own severity (FAIL -> fail-red, WARN -> warn-amber) — "status dot:
 * pass/fail per count>0 + severity tint" from the Task 2 brief. */
function toneForCheck(check: QcCheck): StatusTone {
  if (check.status === "disabled") return "neutral";
  if (check.status === "ok") return "pass";
  return check.severity === "FAIL" ? "fail" : "warn";
}

/** Trailing caption: "Disabled", "OK", a plain count, or the baseline
 * "N new (M accepted)" shape called out in CLAUDE.md's Baseline section. */
function metaForCheck(check: QcCheck): string {
  if (check.status === "disabled") return "Disabled";
  if (check.new !== null && check.new !== undefined) {
    if (check.new === 0 && (check.accepted ?? 0) === 0) return "OK";
    return check.accepted ? `${check.new} new (${check.accepted} accepted)` : `${check.new} new`;
  }
  return check.count ? String(check.count) : "OK";
}

function CheckDetails({ check }: { check: QcCheck }) {
  const shown = check.details.length;
  const hiddenCount = check.count !== null && check.count > shown ? check.count - shown : 0;
  if (shown === 0) {
    return (
      <p className="text-caption py-1" style={{ color: "var(--color-ink-secondary)" }}>
        No violation details to show for this check.
      </p>
    );
  }
  return (
    <ul>
      {check.details.map((detail, index) => (
        <li key={`${detail.label}:${index}`} className="text-caption py-1">
          {detail.label && (
            <span style={{ color: "var(--color-ink)" }}>{detail.label}</span>
          )}
          {detail.label && detail.message && " — "}
          <span style={{ color: "var(--color-ink-secondary)" }}>{detail.message}</span>
        </li>
      ))}
      {hiddenCount > 0 && (
        <li className="text-caption py-1" style={{ color: "var(--color-muted)" }}>
          +{hiddenCount} more
        </li>
      )}
    </ul>
  );
}

function QcCheckRow({ check }: { check: QcCheck }) {
  return (
    <CheckRow
      tone={toneForCheck(check)}
      label={check.label}
      meta={metaForCheck(check)}
      muted={check.status === "disabled"}
      extra={
        check.has_fix ? (
          <Wrench size={12} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-hidden="true" />
        ) : undefined
      }
      expandedContent={check.status === "disabled" ? undefined : <CheckDetails check={check} />}
    />
  );
}

export function QcReportPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchQcReport().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") return <ErrorState title="Couldn't load the QC Report" message={state.message} onRetry={load} />;
  if (state.kind === "empty") return <EmptyState title="No QC data" reason={state.reason} />;

  const { data } = state;
  const activeChecks = data.checks.filter((check) => check.status !== "disabled");
  const disabledChecks = data.checks.filter((check) => check.status === "disabled");
  const scoreTone: StatusTone = data.score.total > 0 && data.score.passed === data.score.total ? "pass" : "fail";

  const metaParts = [
    data.score.score ? `QC ${data.score.score}` : undefined,
    data.score.disabled_count > 0
      ? `${data.score.disabled_count} disabled`
      : undefined,
    data.score.baseline_status ? `baseline: ${data.score.baseline_status}` : undefined,
  ].filter((part): part is string => Boolean(part));

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <header
        className="px-[18px] py-[18px]"
        style={{ backgroundColor: "var(--color-surface-1)", borderBottom: "1px solid var(--color-hairline-strong)" }}
      >
        <div className="flex items-center gap-3">
          <h1 className="text-title truncate" style={{ color: "var(--color-ink)" }}>
            {data.scene || "Untitled"}
          </h1>
          <span
            className="text-label shrink-0 rounded-sm px-1.5 py-0.5"
            style={{ backgroundColor: "var(--color-surface-2)", color: "var(--color-ink-secondary)" }}
            title={data.ruleset.path ?? "No project ruleset — using embedded defaults"}
          >
            {data.ruleset.name}
          </span>
        </div>
        {(metaParts.length > 0 || data.ruleset.shadowed.length > 0) && (
          <p className="text-caption mt-1" style={{ color: scoreTone === "fail" ? "var(--color-status-fail)" : "var(--color-ink-secondary)" }}>
            {metaParts.join(" · ")}
            {data.ruleset.shadowed.length > 0 && (
              <span style={{ color: "var(--color-status-warn)" }}>
                {metaParts.length > 0 ? " · " : ""}
                {data.ruleset.shadowed.length} ruleset(s) shadowed
              </span>
            )}
          </p>
        )}
      </header>

      <div className="flex-1 overflow-auto p-4">
        <Section title="Checks">
          <div className="rounded-lg border" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
            {activeChecks.map((check) => (
              <QcCheckRow key={check.id} check={check} />
            ))}
          </div>
        </Section>

        {disabledChecks.length > 0 && (
          <Section title="Disabled">
            <div className="rounded-lg border" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
              {disabledChecks.map((check) => (
                <QcCheckRow key={check.id} check={check} />
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}
