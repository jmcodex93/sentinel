import { useEffect, useRef, useState } from "react";
import type { PanelQc, PanelScene } from "../../types";

/** QC score bar — same tone rule as `QcReportPage` (`scoreTone`): full pass
 * is `status-pass`, anything short of it is `status-fail`. `qc.total` is
 * already net of disabled checks (see `qc/score.py` — disabled checks never
 * enter `counts`), so the denominator is `total` directly, no further
 * subtraction. Width is the passed/total fraction; `total === 0` (every
 * check turned off) draws an empty, neutral bar rather than dividing by
 * zero.
 *
 * Score pop (Task 5, panel polish): `.animate-pop` fires on the score text
 * only when `passed`/`total`/`disabled` actually change value between
 * renders — tracked via a ref, not on every 2s poll (which hands down a
 * fresh `qc` object with the *same* numbers most ticks). No pop on first
 * mount — the ref starts `null` and the first render just seeds it. */
function QcBar({ qc }: { qc: PanelQc }) {
  const denominator = qc.total;
  const fraction = denominator > 0 ? qc.passed / denominator : 0;
  const tone = denominator > 0 && qc.passed === denominator ? "pass" : "fail";
  const color = denominator > 0 ? (tone === "pass" ? "var(--color-status-pass)" : "var(--color-status-fail)") : "var(--color-status-neutral)";

  const scoreKey = `${qc.passed}/${denominator}/${qc.disabled}`;
  const prevKeyRef = useRef<string | null>(null);
  const [pop, setPop] = useState(false);

  useEffect(() => {
    const changed = prevKeyRef.current !== null && prevKeyRef.current !== scoreKey;
    prevKeyRef.current = scoreKey;
    if (!changed) return;
    setPop(true);
    const timer = setTimeout(() => setPop(false), 300);
    return () => clearTimeout(timer);
  }, [scoreKey]);

  return (
    <div className="flex items-center gap-2">
      <span className={`text-caption shrink-0 ${pop ? "animate-pop" : ""}`} style={{ color }}>
        QC {qc.passed}/{denominator}
        {qc.disabled > 0 ? ` · ${qc.disabled} disabled` : ""}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ backgroundColor: "var(--color-surface-2)" }}>
        <div
          className="h-full rounded-full transition-all duration-150 ease-out"
          style={{ width: `${Math.round(fraction * 100)}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

/** Scene identity strip always visible above the active section — filename,
 * version pill + age, shot/artist, and the QC score bar (shared visual
 * language with the approved mockup's header line). Either block being
 * `null` (a `panel/overview` block failure) degrades to an inline note
 * instead of hiding the whole header. */
export function PanelHeader({ scene, qc }: { scene: PanelScene | null; qc: PanelQc | null }) {
  return (
    <header
      className="flex flex-col gap-1.5 px-3 py-2.5"
      style={{ borderBottom: "1px solid var(--color-hairline-strong)", backgroundColor: "var(--color-surface-1)" }}
    >
      {scene ? (
        <>
          <div className="flex min-w-0 items-baseline gap-2">
            <h1 className="text-body-lg truncate" style={{ color: "var(--color-ink)" }}>
              {scene.name || "Untitled"}
            </h1>
            <span className="text-caption shrink-0" style={{ color: "var(--color-ink-secondary)" }}>
              {[scene.version_label, scene.version_age].filter(Boolean).join(" · ")}
            </span>
          </div>
          <p className="text-caption truncate" style={{ color: "var(--color-ink-secondary)" }}>
            {[scene.shot_id, scene.artist, scene.polys_label].filter(Boolean).join(" · ")}
          </p>
        </>
      ) : (
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Scene info unavailable.
        </p>
      )}

      {qc ? (
        <QcBar qc={qc} />
      ) : (
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          QC status unavailable.
        </p>
      )}
    </header>
  );
}
