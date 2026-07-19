import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import type { StatusTone } from "./StatusDot";
import { StatusDot } from "./StatusDot";

interface CheckRowProps {
  tone: StatusTone;
  label: string;
  /** Trailing caption text, e.g. "OK", "3", "1 new (2 accepted)". */
  meta: string;
  /** Small icon(s) between the label and meta, e.g. a fix-available wrench. */
  extra?: ReactNode;
  /** Muted styling for a disabled/inactive row (still shows its dot/label). */
  muted?: boolean;
  /** Content shown when the row is expanded. Omitted/null -> row is not
   * expandable (no chevron, click does nothing). */
  expandedContent?: ReactNode;
}

/** One row in a Sentinel Reports check/diagnostic list — reused by
 * QcReportPage (QC checks) and RenderValidationPage (post-render checks).
 * `{status-dot}{label}{extra}{meta}{chevron}`, `table-row` height, optional
 * click-to-expand detail list underneath. */
export function CheckRow({ tone, label, meta, extra, muted = false, expandedContent }: CheckRowProps) {
  const [expanded, setExpanded] = useState(false);
  const expandable = Boolean(expandedContent);

  return (
    <div style={{ borderBottom: "1px solid var(--color-hairline)" }}>
      <button
        type="button"
        disabled={!expandable}
        onClick={() => setExpanded((value) => !value)}
        className="flex h-8 w-full items-center gap-2 px-4 text-left transition-colors duration-100 ease-out enabled:hover:bg-[var(--color-surface-2)] disabled:cursor-default"
      >
        <StatusDot tone={tone} />
        <span
          className="text-body flex-1 truncate"
          style={{ color: muted ? "var(--color-muted)" : "var(--color-ink)" }}
        >
          {label}
        </span>
        {extra}
        <span className="text-caption shrink-0" style={{ color: "var(--color-ink-secondary)" }}>
          {meta}
        </span>
        {expandable &&
          (expanded ? (
            <ChevronUp size={14} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-hidden="true" />
          ) : (
            <ChevronDown
              size={14}
              strokeWidth={2.25}
              style={{ color: "var(--color-ink-secondary)" }}
              aria-hidden="true"
            />
          ))}
      </button>
      {expanded && expandedContent && <div className="pb-2 pl-9 pr-4">{expandedContent}</div>}
    </div>
  );
}
