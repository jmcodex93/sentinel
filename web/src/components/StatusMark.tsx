import { CheckCircle2, XCircle, AlertTriangle, Minus } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** The single health-status vocabulary across the SPA. Distinct from the
 * version-workflow badge (WIP/TR/CR/FINAL) in panelDeliver.statusMarker —
 * that is a different axis and is NOT this. */
export type StatusTone = "pass" | "fail" | "warn" | "neutral";

const TONE_COLOR: Record<StatusTone, string> = {
  pass: "var(--color-status-pass)",
  fail: "var(--color-status-fail)",
  warn: "var(--color-status-warn)",
  neutral: "var(--color-status-neutral)",
};

const TONE_ICON: Record<StatusTone, LucideIcon> = {
  pass: CheckCircle2,
  fail: XCircle,
  warn: AlertTriangle,
  neutral: Minus,
};

/** A colored status icon (shape = color-blind-safe) plus an optional colored
 * label. Replaces the bare status dot and StatusBadge/HubStatusBadge (filled
 * tint pill). `label` present → icon + text (status IS the data: asset
 * collected/missing/external, hub ok/absolute/…); absent → icon only (the row
 * already names itself: QC checks, Doctor items). */
export function StatusMark({ tone, label }: { tone: StatusTone; label?: string }) {
  const Icon = TONE_ICON[tone];
  return (
    <span className="text-label inline-flex items-center gap-1.5" style={{ color: TONE_COLOR[tone] }}>
      <Icon size={13} strokeWidth={2.25} aria-hidden={label ? true : undefined} aria-label={label ? undefined : tone} />
      {label}
    </span>
  );
}
