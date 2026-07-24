import type { PanelToolResult } from "../types";

export interface ToolDef {
  id: string;
  label: string;
}

/** The Tools section's scene-authoring groups. The Asset Hub deliberately
 * lives elsewhere (Overview / QC #6 / Deliver→Collect) — a fourth door here
 * was redundant, so Tools stays scoped to real authoring utilities. */
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
    title: "Animation",
    tools: [
      { id: "panel/tools/vibrate_null", label: "Vibrate Null" },
      { id: "panel/tools/abc_retime", label: "ABC Retime" },
      { id: "panel/tools/cam_simple", label: "Cam Simple" },
      { id: "panel/tools/cam_shakel", label: "Cam Shakel" },
    ],
  },
  {
    title: "QC Marking",
    tools: [{ id: "panel/tools/mark_safe_area", label: "Mark / Unmark Safe Area Subject" }],
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
  return { message: "Done.", variant: "success" };
}
