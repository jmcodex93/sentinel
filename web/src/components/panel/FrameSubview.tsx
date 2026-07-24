import { Button } from "../form/Button";
import { frameHint, frameStatusLine as frameSubviewStatusLine, qc12StatusLine } from "../../lib/panelFrame";
import type { PanelFrameState } from "../../types";

/** Frame sub-view (Fase 6.6) — consolidates the cross-aspect workflow that
 * used to be scattered across Render (Sentinel Frame), Tools (Mark
 * subjects) and QC (#12) into one place. Read-only state from `panel/frame`;
 * every action reuses an EXISTING op (`add_frame_tag`/`select_frame_tag`/
 * `mark_safe_area`/`qc/select`) — this sub-view introduces no new mutation.
 * The tag's heavy actions (Create/Update Takes, Set Output, Remove Stale)
 * and its fine per-format config stay in its Attribute Manager, reached via
 * "Select tag" — not brought into the SPA. */
export function FrameSubview({
  frame,
  busy,
  onBack,
  onAddTag,
  onSelectTag,
  onMarkSubjects,
  onSelectViolations,
  onOpenQc,
}: {
  frame: PanelFrameState;
  /** Non-null while any Frame/Render mutation is in flight — same single
   * busy-lock idiom as the rest of the Render section. */
  busy: string | null;
  onBack: () => void;
  onAddTag: () => void;
  onSelectTag: () => void;
  onMarkSubjects: () => void;
  onSelectViolations: () => void;
  onOpenQc: () => void;
}) {
  const isBusy = busy !== null;
  const hint = frameHint(frame);
  const warnHint = hint.startsWith("⚠") || hint.toLowerCase().includes("out of date");
  const hasTag = !!frame.frame?.has_tag;
  const violations = frame.qc12?.violations ?? 0;

  return (
    <div className="flex flex-col gap-3 p-3">
      <Button variant="secondary" onClick={onBack}>
        ← Render
      </Button>

      <p
        className="text-body rounded-lg border p-3"
        style={{
          borderColor: "var(--color-hairline)",
          backgroundColor: warnHint ? "var(--color-status-warn-tint-10)" : "var(--color-surface-1)",
          color: warnHint ? "var(--color-status-warn)" : "var(--color-ink)",
        }}
      >
        {hint}
      </p>

      {/* Sentinel Frame */}
      <section
        className="flex flex-col gap-2 rounded-lg border p-3"
        style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
      >
        <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
          SENTINEL FRAME
        </p>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {frameSubviewStatusLine(frame.frame)}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={isBusy} onClick={onAddTag}>
            Add to camera
          </Button>
          <Button variant="secondary" disabled={isBusy || !hasTag} onClick={onSelectTag}>
            Select tag
          </Button>
        </div>
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Formats, output & Take generation live on the tag — Select to edit.
        </p>
      </section>

      {/* Subjects */}
      <section
        className="flex flex-col gap-2 rounded-lg border p-3"
        style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
      >
        <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
          SUBJECTS
        </p>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {frame.subjects
            ? `${frame.subjects.marked_count} subject${frame.subjects.marked_count === 1 ? "" : "s"} marked`
            : "Subjects unavailable."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={isBusy} onClick={onMarkSubjects}>
            Mark / Unmark selected
          </Button>
        </div>
      </section>

      {/* QC #12 */}
      <section
        className="flex flex-col gap-2 rounded-lg border p-3"
        style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
      >
        <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
          QC #12 · CROSS-ASPECT SAFE AREA
        </p>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {qc12StatusLine(frame.qc12)}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" disabled={isBusy || violations === 0} onClick={onSelectViolations}>
            Select violating
          </Button>
          <button type="button" onClick={onOpenQc} className="text-caption" style={{ color: "var(--color-primary)" }}>
            Details in QC →
          </button>
        </div>
      </section>
    </div>
  );
}
