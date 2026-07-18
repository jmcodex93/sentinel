import type { ReactNode } from "react";

export type KpiTone = "pass" | "fail" | "warn" | "neutral";

const TONE_COLOR: Record<KpiTone, string> = {
  pass: "var(--color-status-pass)",
  fail: "var(--color-status-fail)",
  warn: "var(--color-status-warn)",
  neutral: "var(--color-ink)",
};

interface KpiCardProps {
  label: string;
  value: ReactNode;
  /** Status color only when the value represents a count of that status
   * (DESIGN.md `kpi-card`: "never accent-colored"). Defaults to plain ink. */
  tone?: KpiTone;
}

export function KpiCard({ label, value, tone = "neutral" }: KpiCardProps) {
  return (
    <div className="rounded-lg border p-4" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
      <div className="text-body-lg" style={{ color: TONE_COLOR[tone] }}>
        {value}
      </div>
      <div className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
        {label}
      </div>
    </div>
  );
}
