import type { CSSProperties } from "react";
import type { SupervisorShot } from "../types";

const headerCellStyle: CSSProperties = {
  backgroundColor: "var(--color-surface-1)",
  borderBottom: "1px solid var(--color-hairline-strong)",
  color: "var(--color-ink-secondary)",
};

const rowCellStyle: CSSProperties = {
  borderBottom: "1px solid var(--color-hairline)",
};

/** Version status chip (WIP/TR/CR/FINAL/custom) — a workflow-stage label,
 * not a pass/fail verdict, so it stays a plain neutral chip rather than one
 * of DESIGN.md's four exclusive status colors (Rule 2). */
function StatusChip({ status }: { status: string }) {
  return (
    <span
      className="text-label inline-block rounded-sm px-1.5 py-0.5"
      style={{ backgroundColor: "var(--color-surface-2)", color: "var(--color-ink-secondary)" }}
    >
      {status || "WIP"}
    </span>
  );
}

/** `regression` (a real QC check that used to pass) reads as a failure;
 * anything else (`stale` today) reads as a warning — mirrors the severity
 * split in supervisor.py's own `_flag_badges` (legacy HTML report). */
function FlagBadge({ flag }: { flag: string }) {
  const isFail = flag === "regression";
  return (
    <span
      className="text-label inline-block rounded-sm px-1.5 py-0.5"
      style={{
        backgroundColor: isFail ? "var(--color-status-fail-tint-10)" : "var(--color-status-warn-tint-10)",
        color: isFail ? "var(--color-status-fail)" : "var(--color-status-warn)",
      }}
    >
      {flag}
    </span>
  );
}

export function SupervisorShotsTable({ shots }: { shots: SupervisorShot[] }) {
  if (shots.length === 0) {
    return (
      <p className="text-body p-4" style={{ color: "var(--color-muted)" }}>
        No shots found in this folder.
      </p>
    );
  }

  return (
    <div className="overflow-auto rounded-lg border" style={{ borderColor: "var(--color-hairline)", maxHeight: "65vh" }}>
      <table className="w-full table-fixed border-collapse">
        <colgroup>
          <col className="w-[22%]" />
          <col className="w-[12%]" />
          <col className="w-[10%]" />
          <col className="w-[10%]" />
          <col className="w-[14%]" />
          <col className="w-[10%]" />
          <col className="w-[22%]" />
        </colgroup>
        <thead>
          <tr>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>Shot</th>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>Last version</th>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>Status</th>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>Score</th>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>TODOs</th>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>Idle</th>
            <th className="text-label sticky top-0 z-10 px-4 py-2 text-left" style={headerCellStyle}>Flags</th>
          </tr>
        </thead>
        <tbody>
          {shots.map((shot) => (
            <tr
              key={shot.base}
              className="h-8 transition-colors duration-100 ease-out hover:bg-[var(--color-surface-2)]"
            >
              <td className="text-body truncate px-4" style={{ ...rowCellStyle, color: "var(--color-ink)" }}>
                {shot.base}
              </td>
              <td className="text-body truncate px-4" style={rowCellStyle}>
                {shot.last_version || "—"}
              </td>
              <td className="px-4" style={rowCellStyle}>
                <StatusChip status={shot.status} />
              </td>
              <td className="text-body px-4" style={rowCellStyle}>
                {shot.qc_label || "—"}
              </td>
              <td className="text-body px-4" style={{ ...rowCellStyle, color: "var(--color-ink-secondary)" }}>
                {shot.todos_pending}/{shot.todos_total}
              </td>
              <td className="text-body px-4" style={{ ...rowCellStyle, color: "var(--color-ink-secondary)" }}>
                {shot.days_idle === null ? "—" : `${shot.days_idle}d`}
              </td>
              <td className="px-4" style={rowCellStyle}>
                {shot.flags.length === 0 ? (
                  <span style={{ color: "var(--color-muted)" }}>—</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {shot.flags.map((flag) => (
                      <FlagBadge key={flag} flag={flag} />
                    ))}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
