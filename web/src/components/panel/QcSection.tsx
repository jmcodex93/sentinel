import { useState } from "react";
import { Button } from "../form/Button";
import { orderedSections } from "../../lib/panelQc";
import type { PaletteAction, PanelQcCheck, PanelQcSection as PanelQcSectionData } from "../../types";
import { QcCard } from "./QcCard";

/** The panel's QC section — "option C refinada" (approved mockup at
 * .superpowers/brainstorm/40035-1784707797/content/qc-list.html): FAIL
 * cards, then WARN cards, then a folded "N OK · M disabled" line. Header
 * carries the score + a single "Fix all fixables" batch action.
 *
 * `qc.ok_count`/`qc.disabled_count` are the ONLY data `panel/qc` returns for
 * passing/disabled checks (see `webbridge.group_qc_by_severity` — it never
 * builds per-check rows for "ok"/"disabled" status, on purpose, so the
 * section never runs a second check pass). The folded line's expand toggle
 * therefore can't list individual passing checks — it just restates the
 * counts on a second line rather than fabricating names that don't exist
 * in the payload. */
export function QcSection({
  qc,
  actions,
  artistName,
  busy,
  onSelect,
  onFix,
  onAccept,
  onFixAll,
}: {
  qc: PanelQcSectionData;
  actions: PaletteAction[];
  artistName: string;
  /** Non-null while any qc mutation is in flight — single lock across every
   * card and the Fix-all button, same idiom as OverviewCards' `busyFix`. */
  busy: string | null;
  onSelect: (checkId: string) => void;
  onFix: (check: PanelQcCheck) => void;
  onAccept: (checkId: string, author: string, reason: string) => Promise<{ ok: boolean; error?: string }>;
  onFixAll: () => void;
}) {
  const [okOpen, setOkOpen] = useState(false);
  const { fail, warn, okCount, disabledCount } = orderedSections(qc);
  const denominator = qc.score.total;
  const fixableCount = [...fail, ...warn].filter((c) => c.can_fix).length;
  const isBusy = busy !== null;

  function fixActionFor(check: PanelQcCheck): PaletteAction | null {
    if (!check.fix_action_id) return null;
    return actions.find((a) => a.id === check.fix_action_id) || null;
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-label" style={{ color: "var(--color-ink)" }}>
          QC{" "}
          <span style={{ color: fail.length > 0 ? "var(--color-status-fail)" : "var(--color-status-pass)" }}>
            {qc.score.passed}/{denominator}
          </span>
        </p>
        <Button variant="secondary" disabled={isBusy || fixableCount === 0} onClick={onFixAll}>
          Fix all fixables
        </Button>
      </div>

      {fail.length === 0 && warn.length === 0 ? (
        <p className="text-caption" style={{ color: "var(--color-status-pass)" }}>
          No failing or warning checks.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {fail.map((check) => (
            <QcCard
              key={check.id}
              check={check}
              fixAction={fixActionFor(check)}
              artistName={artistName}
              busy={isBusy}
              onSelect={() => onSelect(check.id)}
              onFix={() => onFix(check)}
              onAccept={(author, reason) => onAccept(check.id, author, reason)}
            />
          ))}
          {warn.map((check) => (
            <QcCard
              key={check.id}
              check={check}
              fixAction={fixActionFor(check)}
              artistName={artistName}
              busy={isBusy}
              onSelect={() => onSelect(check.id)}
              onFix={() => onFix(check)}
              onAccept={(author, reason) => onAccept(check.id, author, reason)}
            />
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={() => setOkOpen((v) => !v)}
        className="text-caption self-start"
        style={{ color: "var(--color-ink-secondary)" }}
      >
        {okOpen ? "▾" : "▸"} {okCount} OK · {disabledCount} disabled
      </button>
      {okOpen && (
        <p className="text-caption -mt-2" style={{ color: "var(--color-ink-secondary)" }}>
          {okCount} check(s) passing, {disabledCount} disabled by the project ruleset. Individual passing checks
          aren't broken out in this view — see the QC Report for the full per-check list.
        </p>
      )}
    </div>
  );
}
