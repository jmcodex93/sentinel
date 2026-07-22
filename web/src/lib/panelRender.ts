import type {
  PanelRenderAovs,
  PanelRenderFrame,
  PanelRenderPostrender,
  PanelRenderPreset,
  PanelRenderSnapshots,
} from "../types";

/** Preset card status line: `"<name> · <resolution> · <fps>fps"`. A `null`
 * block (the read op failed in isolation, see `_guarded_block`) renders a
 * distinct unavailable note from "no active preset" (the block resolved
 * fine, the scene just has none) — the two are different failure classes
 * and the SPA should not conflate them. */
export function presetStatusLine(preset: PanelRenderPreset | null): string {
  if (preset === null) return "Render preset unavailable.";
  if (!preset.preset_name || !preset.resolution || preset.fps === null) {
    return "No active preset.";
  }
  return `${preset.preset_name} · ${preset.resolution} · ${preset.fps}fps`;
}

/** Frame card status line: `"No Sentinel Frame tag."` / `"On <camera>."`,
 * with an optional `"· N formats"` tail once an engine helper populates
 * `format_count` (currently always `null`/`undefined` — see the type's own
 * doc comment). */
export function frameStatusLine(frame: PanelRenderFrame | null): string {
  if (frame === null) return "Frame status unavailable.";
  if (!frame.has_tag || !frame.camera_name) return "No Sentinel Frame tag.";
  const formats = frame.format_count;
  if (typeof formats === "number") {
    return `On ${frame.camera_name} · ${formats} format${formats === 1 ? "" : "s"}.`;
  }
  return `On ${frame.camera_name}.`;
}

/** AOVs card status line: `"<count> AOVs · Multi-Part ON/OFF"`, or a
 * distinct note when Redshift itself isn't available (`{error:
 * "redshift_unavailable"}` — a scene-independent condition, not a block
 * failure). */
export function aovStatusLine(aovs: PanelRenderAovs | null): string {
  if (aovs === null) return "AOV status unavailable.";
  if ("error" in aovs) return "Redshift unavailable.";
  return `${aovs.count} AOVs · Multi-Part ${aovs.multipart ? "ON" : "OFF"}`;
}

/** Snapshots card status line: the effective directory plus its resolution
 * origin chip (`"auto-detected"` for the RenderView-parsed dir, `"manual"`
 * for the Settings fallback — see `flows.get_effective_snapshot_dir`). */
export function snapshotStatusLine(snapshots: PanelRenderSnapshots | null): string {
  if (snapshots === null) return "Snapshots status unavailable.";
  if (!snapshots.dir) return "No snapshot directory set.";
  const originChip = snapshots.origin === "auto" ? "auto-detected" : "manual";
  return `${snapshots.dir} · ${originChip}`;
}

/** Post-Render card status line: pass/fail + the report's generation
 * timestamp, or a "never validated" note when no report exists yet for
 * this scene (`available: false` — an unsaved doc or one that never ran
 * "Validate Render Output..."). */
export function postrenderStatusLine(postrender: PanelRenderPostrender | null): string {
  if (postrender === null) return "Post-render status unavailable.";
  if (!postrender.available) return "No render validation yet.";
  const verdict = postrender.passed ? "Passed" : "Issues found";
  return `${verdict} · ${postrender.generated_at}`;
}

/** The three `panel/render/*` ops the server confirm-gates
 * (`_needs_confirm` in panel_render_ops.py: `reset_all`, `force_vertical`,
 * `aov_tier`) — every other mutation is additive/reversible and runs
 * without an inline confirm step, mirroring the native panel's own lack of
 * a confirmation dialog for those actions. */
const DESTRUCTIVE_RENDER_OPS = new Set(["reset_all", "force_vertical", "aov_tier"]);

export function isDestructiveRenderOp(op: string): boolean {
  return DESTRUCTIVE_RENDER_OPS.has(op);
}
