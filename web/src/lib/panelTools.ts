import type { PanelToolResult } from "../types";

export interface ToolDef {
  id: string;
  label: string;
}

/** The Tools section's scene-authoring groups. The Asset Hub deliberately
 * lives elsewhere (Overview / QC #6 / Deliver→Collect) — a fourth door here
 * was redundant, so Tools stays scoped to real authoring utilities. Mark /
 * Unmark Safe Area Subject moved to the Render → Frame sub-view (Fase 6.6) —
 * the `panel/tools/mark_safe_area` op stays, it's just called from there now. */
export const TOOL_GROUPS: { title: string; tools: ToolDef[] }[] = [
  {
    title: "Layout & Hierarchy",
    tools: [
      { id: "panel/tools/hierarchy", label: "Hierarchy" },
      { id: "panel/tools/h_to_layers", label: "H → Layers" },
      { id: "panel/tools/solo", label: "Solo Layers" },
      { id: "panel/tools/drop_to_floor", label: "Drop to Floor" },
    ],
  },
  {
    title: "Cleanup",
    tools: [
      { id: "panel/tools/delete_empty_nulls", label: "Delete Empty Nulls" },
      { id: "panel/tools/clean_material_tags", label: "Clean Material Tags" },
    ],
  },
  {
    title: "Animation",
    tools: [
      { id: "panel/tools/vibrate_null", label: "Vibrate Null" },
      { id: "panel/tools/abc_retime", label: "ABC Retime" },
      { id: "panel/tools/cam_simple", label: "Cam Simple" },
      { id: "panel/tools/cam_shakel", label: "Cam Shakel" },
    ],
  },
];

const ERROR_COPY: Record<string, string> = {
  no_document: "No active document.",
  no_selection: "Select one or more objects first.",
  no_layers: "No layers found — create them with H → Layers first.",
  no_groups: "No null groups found in the scene.",
  orphans: "Some objects sit outside null groups — organize them first.",
  file_not_found: "Template file not found in the plugin's c4d folder.",
  merge_failed: "Couldn't merge the template.",
  merge_error: "Error loading the template.",
  apply_failed: "ABC Retime tag couldn't be applied (plugin installed? valid object?).",
  bad_target: "Unknown link.",
  none_found: "Nothing to clean — scene is already tidy.",
  no_keys: "Selection has no keyframes.",
  bad_frames: "Frames must be a non-zero integer (±10000).",
  need_two: "Select two or more objects to stagger.",
};

/** Tool result → toast. Success uses a count when the op returns one; errors
 * map to actionable copy (mirroring the native MessageDialog intent). */
export function toolToast(id: string, r: PanelToolResult): { message: string; variant: "success" | "warn" } {
  if (!r.ok) {
    return { message: ERROR_COPY[r.error ?? ""] ?? "Couldn't run that tool.", variant: "warn" };
  }
  if (id === "panel/tools/drop_to_floor" && typeof r.dropped === "number") {
    return { message: `Dropped ${r.dropped} object${r.dropped === 1 ? "" : "s"} to floor.`, variant: "success" };
  }
  if (id === "panel/tools/solo") {
    return { message: r.unsolo ? "Restored all layers." : `Soloed ${r.soloed ?? 0} layer(s).`, variant: "success" };
  }
  if (id === "panel/tools/mark_safe_area") {
    const unmarking = r.verb === "unmark";
    const n = unmarking ? r.unmarked : r.marked;
    return { message: `${unmarking ? "Unmarked" : "Marked"} ${n ?? 0} object(s) as Safe Area Subject(s).`, variant: "success" };
  }
  if (id === "panel/tools/h_to_layers") {
    return { message: `Synced layers: ${r.created ?? 0} new, ${r.updated ?? 0} updated.`, variant: "success" };
  }
  if ((id === "panel/tools/cam_simple" || id === "panel/tools/cam_shakel" || id === "panel/tools/hierarchy" || id === "panel/tools/vibrate_null") && r.camera_name) {
    return { message: `Merged ${r.camera_name}.`, variant: "success" };
  }
  if (id === "panel/tools/abc_retime") {
    return { message: `ABC Retime: ${r.applied ?? 0} applied, ${r.skipped ?? 0} skipped.`, variant: "success" };
  }
  if (id === "panel/tools/delete_empty_nulls" && typeof r.removed === "number") {
    return { message: `Removed ${r.removed} empty null${r.removed === 1 ? "" : "s"}.`, variant: "success" };
  }
  if (id === "panel/tools/clean_material_tags") {
    const broken = r.removed_broken ?? 0;
    const dupes = r.removed_dupes ?? 0;
    const total = broken + dupes;
    return {
      message: `Removed ${broken} broken + ${dupes} duplicate tag${total === 1 ? "" : "s"}.`,
      variant: "success",
    };
  }
  if (id === "panel/tools/keyframe_offset") {
    const keys = r.keys ?? 0;
    const objects = r.objects ?? 0;
    return {
      message: `Shifted ${keys} key${keys === 1 ? "" : "s"} across ${objects} object${objects === 1 ? "" : "s"} by ${r.frames ?? 0}f.`,
      variant: "success",
    };
  }
  if (id === "panel/tools/keyframe_stagger") {
    const objects = r.objects ?? 0;
    const keys = r.keys ?? 0;
    return {
      message: `Staggered ${objects} object${objects === 1 ? "" : "s"} (${r.frames ?? 0}f step, ${keys} key${keys === 1 ? "" : "s"}).`,
      variant: "success",
    };
  }
  return { message: "Done.", variant: "success" };
}
