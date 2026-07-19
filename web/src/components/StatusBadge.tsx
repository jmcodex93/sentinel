import { CheckCircle2, XCircle, ExternalLink } from "lucide-react";
import type { AssetStatus } from "../types";

/** `collected` → pass, `missing` → fail, `external` → warn — the mapping
 * called out explicitly in the Task 3 brief. */
const STATUS_META: Record<
  AssetStatus,
  { label: string; color: string; background: string; Icon: typeof CheckCircle2 }
> = {
  collected: {
    label: "collected",
    color: "var(--color-status-pass)",
    background: "var(--color-status-pass-tint-10)",
    Icon: CheckCircle2,
  },
  missing: {
    label: "missing",
    color: "var(--color-status-fail)",
    background: "var(--color-status-fail-tint-10)",
    Icon: XCircle,
  },
  external: {
    label: "external",
    color: "var(--color-status-warn)",
    background: "var(--color-status-warn-tint-10)",
    Icon: ExternalLink,
  },
};

export function StatusBadge({ status }: { status: AssetStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.Icon;
  return (
    <span
      className="text-label inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5"
      style={{ color: meta.color, backgroundColor: meta.background }}
    >
      <Icon size={12} strokeWidth={2.25} aria-hidden="true" />
      {meta.label}
    </span>
  );
}
