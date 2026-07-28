import { Button } from "../form/Button";
import { SegmentedControl } from "../form/SegmentedControl";
import { frameHint, frameStatusLine as frameSubviewStatusLine, qc12StatusLine } from "../../lib/panelFrame";
import type { PanelFrameState } from "../../types";
import { SectionGroup } from "../SectionGroup";

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
  onSetViewing,
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
  /** Frame v2: activate the take behind a Viewing selection ("master" or a
   * format id) — two-way mirror of the tag's AM cycle. */
  onSetViewing: (target: string) => void;
}) {
  const isBusy = busy !== null;
  const hint = frameHint(frame);
  const warnHint = hint.startsWith("⚠") || hint.toLowerCase().includes("out of date");
  const hasTag = !!frame.frame?.has_tag;
  const violations = frame.qc12?.violations ?? 0;

  return (
    <div className="flex flex-col p-3">
      <Button variant="secondary" onClick={onBack}>
        ← Render
      </Button>

      <p
        className="text-body mt-3 rounded-lg border p-3"
        style={{
          borderColor: "var(--color-hairline)",
          backgroundColor: warnHint ? "var(--color-status-warn-tint-10)" : "var(--color-surface-1)",
          color: warnHint ? "var(--color-status-warn)" : "var(--color-ink)",
        }}
      >
        {hint}
      </p>

      {/* Sentinel Frame */}
      <SectionGroup title="Sentinel Frame" first>
        <div className="flex flex-col gap-2">
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
          {hasTag && (frame.frame?.viewing_options?.length ?? 0) > 1 && (
            <div className="flex items-center gap-2">
              <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                Viewing
              </span>
              <SegmentedControl
                options={(frame.frame?.viewing_options ?? ["master"]).map((id) => ({
                  value: id,
                  label: id === "master" ? "Master" : id,
                }))}
                value={frame.frame?.viewing ?? "master"}
                disabled={isBusy}
                onChange={onSetViewing}
              />
            </div>
          )}
          <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
            Formats & framing live on the tag — Select to edit. Takes stay in sync automatically.
          </p>
        </div>
      </SectionGroup>

      {/* Subjects */}
      <SectionGroup title="Subjects">
        <div className="flex flex-col gap-2">
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
        </div>
      </SectionGroup>

      {/* QC #12 */}
      <SectionGroup title="QC #12 · Cross-Aspect Safe Area">
        <div className="flex flex-col gap-2">
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
        </div>
      </SectionGroup>
    </div>
  );
}
