import { Wrench } from "lucide-react";
import { CheckRow } from "./CheckRow";
import type { StatusTone } from "./StatusDot";
import type { GateCheck } from "../types";

function toneForSeverity(severity: string): StatusTone {
  return severity === "WARN" ? "warn" : "fail";
}

/** Violation detail list shown inside an expanded `GateCheckRow` — extracted
 * from GateTriagePage.tsx (Phase 5 Task 11) so the Hub's inline gate panel
 * can reuse the exact same check-list UI as the standalone Quality Gate
 * form, no duplicated markup. */
export function GateDetails({ check }: { check: GateCheck }) {
  if (check.violations.length === 0) {
    return (
      <p className="text-caption py-1" style={{ color: "var(--color-ink-secondary)" }}>
        No violation details to show for this check.
      </p>
    );
  }
  return (
    <ul>
      {check.violations.map((violation, index) => (
        <li key={`${violation.label}:${index}`} className="text-caption py-1">
          {violation.label && <span style={{ color: "var(--color-ink)" }}>{violation.label}</span>}
          {violation.label && violation.message && " — "}
          <span style={{ color: "var(--color-ink-secondary)" }}>{violation.message}</span>
        </li>
      ))}
    </ul>
  );
}

/** One gate check row (dot + label + new-count + fix wrench + expandable
 * violation details), optionally with a selection checkbox for the Accept…
 * flow — see GateTriagePage.tsx (the standalone form) and
 * HubDeliverSection.tsx (the Hub's inline gate panel). */
export function GateCheckRow({
  check,
  selectable,
  selected,
  onToggleSelect,
}: {
  check: GateCheck;
  selectable: boolean;
  selected: boolean;
  onToggleSelect: (id: string) => void;
}) {
  return (
    <div className="flex items-center">
      {selectable && (
        <span className="flex items-center pl-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(check.check_id)}
            style={{ accentColor: "var(--color-primary)" }}
            aria-label={`Select "${check.label}" for acceptance`}
          />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <CheckRow
          tone={toneForSeverity(check.severity)}
          label={check.label}
          meta={`${check.new_count} new`}
          extra={
            check.has_fix ? (
              <Wrench size={12} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-hidden="true" />
            ) : undefined
          }
          expandedContent={<GateDetails check={check} />}
        />
      </div>
    </div>
  );
}
