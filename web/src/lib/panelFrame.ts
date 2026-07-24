import type { PanelFrameBlock, PanelFrameQc12, PanelFrameState } from "../types";

/** The single next-step hint for the Frame sub-view — derived from state,
 * NOT a forced wizard. Priority: stale takes-out-of-date first (blocks a
 * correct QC read), then QC #12 violations, then "no subjects yet", then
 * the all-clear, then "no tag yet". */
export function frameHint(state: PanelFrameState): string {
  const { frame, subjects, qc12 } = state;
  if (!frame || !frame.has_tag) {
    return "Add a Sentinel Frame to your camera to start.";
  }
  if (frame.stale) {
    return "Takes out of date — update them from the tag.";
  }
  if (qc12 && !qc12.pass && qc12.violations > 0) {
    return `⚠ ${qc12.violations} subject/format violation${qc12.violations === 1 ? "" : "s"} — subjects leave the safe area.`;
  }
  if (!subjects || subjects.marked_count === 0) {
    return "Mark your key subjects (logo, title, character) so QC #12 can verify them.";
  }
  return "✓ All marked subjects stay inside every format's safe area.";
}

/** Frame block status: `"On <camera> · N formats"` / `"No Sentinel Frame tag."` */
export function frameStatusLine(frame: PanelFrameBlock | null): string {
  if (frame === null) return "Frame status unavailable.";
  if (!frame.has_tag || !frame.camera_name) return "No Sentinel Frame tag.";
  const n = frame.format_count;
  const formats = typeof n === "number" ? ` · ${n} format${n === 1 ? "" : "s"}` : "";
  return `On ${frame.camera_name}${formats}.`;
}

/** QC #12 block status. */
export function qc12StatusLine(qc12: PanelFrameQc12 | null): string {
  if (qc12 === null) return "QC #12 status unavailable.";
  if (qc12.pass || qc12.violations === 0) return "No violations.";
  return `${qc12.violations} subject/format violation${qc12.violations === 1 ? "" : "s"}.`;
}
