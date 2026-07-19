/** Generic status tone shared by every report page's status indicators —
 * QC check rows, Doctor items, Render Validation checks. Distinct from
 * `AssetStatus`/`StatusBadge` (Delivery Summary's collected/missing/external
 * badge with icon + tint background): this is a plain colored dot for dense
 * list rows, per DESIGN.md's four exclusive state colors. */
export type StatusTone = "pass" | "fail" | "warn" | "neutral";

const TONE_COLOR: Record<StatusTone, string> = {
  pass: "var(--color-status-pass)",
  fail: "var(--color-status-fail)",
  warn: "var(--color-status-warn)",
  neutral: "var(--color-status-neutral)",
};

export function StatusDot({ tone }: { tone: StatusTone }) {
  return (
    <span
      className="h-2 w-2 shrink-0 rounded-full"
      style={{ backgroundColor: TONE_COLOR[tone] }}
      aria-hidden="true"
    />
  );
}
