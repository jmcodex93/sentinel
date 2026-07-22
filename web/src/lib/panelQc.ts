import type { PanelQcCheck, PanelQcSection, QcCheckDetail } from "../types";

/** One line for the collapsed card: the first violation's "label — message"
 * (or bare message when there's no label), plus a "(+N more)" tail when the
 * check has more violations than shown. `check.detail` is the same
 * `{label, message, extras}` shape as `QcCheck.details` (Reports QC) — never
 * a plain string, see `webbridge.group_qc_by_severity`. */
export function detailPreview(detail: QcCheckDetail[]): string {
  if (detail.length === 0) return "";
  const [first, ...rest] = detail;
  const line = first.label ? `${first.label} — ${first.message}` : first.message;
  return rest.length > 0 ? `${line} (+${rest.length} more)` : line;
}

/** Per-card action availability, derived straight from the check's own
 * `can_select`/`can_fix` flags (sourced server-side from `CHECK_REGISTRY` —
 * see `_op_panel_qc` in panel_ops.py). Info and Accept are always available
 * for any FAIL/WARN card — every check has a detail to expand, and any
 * violation can be accepted into the baseline regardless of fix/select
 * capability. */
export interface QcCardActions {
  select: boolean;
  fix: boolean;
  info: true;
  accept: true;
}

export function cardActions(check: PanelQcCheck): QcCardActions {
  return {
    select: check.can_select,
    fix: check.can_fix,
    info: true,
    accept: true,
  };
}

/** The panel QC section's card layout: FAIL cards, then WARN cards, then a
 * folded OK/disabled line. The server (`webbridge.group_qc_by_severity`)
 * already orders and partitions the checks — this just renames the fields
 * to the camelCase the SPA components expect, it does not re-derive
 * anything. */
export interface OrderedQcSections {
  fail: PanelQcCheck[];
  warn: PanelQcCheck[];
  okCount: number;
  disabledCount: number;
}

export function orderedSections(qc: PanelQcSection): OrderedQcSections {
  return {
    fail: qc.fail,
    warn: qc.warn,
    okCount: qc.ok_count,
    disabledCount: qc.disabled_count,
  };
}

/** `check.new`/`check.accepted` are baseline-aware and `null` with no active
 * baseline (see PanelQcCheck) — render the legacy `count` alone rather than
 * a misleading "null new". */
export function countLabel(check: PanelQcCheck): string {
  if (check.new === null) {
    return `${check.count}`;
  }
  if (check.accepted && check.accepted > 0) {
    return `${check.new} new (${check.accepted} accepted)`;
  }
  return `${check.new} new`;
}
