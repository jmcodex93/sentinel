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
      { id: "panel/tools/variant_set", label: "Variant Set" },
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
  // v1.36.1. A pin neither lays out, cleans, nor animates — none of the
  // three groups above names what it does, so it gets its own rather than
  // being filed under the least-wrong one. "Return Points" is the term this
  // project already uses for the v1.30→v1.36 arc (Pin = states to come back
  // to, Variants = options to come back to); Variant Set stays where it is
  // for now — moving it is a separate call, not this one's to make.
  {
    title: "Return Points",
    tools: [
      { id: "panel/tools/pin_state", label: "Pin State" },
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
  no_tag: "Couldn't create the Variants tag on the anchor.",
  no_pin: "Couldn't pin the selection — no state was captured.",
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
  if (id === "panel/tools/variant_set") {
    const objects = r.objects ?? 0;
    const option = r.option || "Option A";
    return {
      message: `Variant set created — ${objects} object${objects === 1 ? "" : "s"} in ${option}.`,
      variant: "success",
    };
  }
  if (id === "panel/tools/pin_state") {
    const pinned = r.pinned ?? 0;
    const failed = r.failed ?? 0;
    // Partial failures are named, never rounded away: the op only reports
    // `ok` when at least one pin landed, so silence here would tell an
    // artist that objects were covered when they were not.
    const tail = failed > 0 ? ` · ${failed} failed.` : ".";
    return {
      message: `Pinned ${pinned} object${pinned === 1 ? "" : "s"}${tail}`,
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
