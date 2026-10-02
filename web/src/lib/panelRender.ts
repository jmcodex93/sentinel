import type {
  PanelRenderPresetOption,
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

/** Dropdown label for one render preset: the real scene name, with a
 * trailing `· custom` on the ones outside the ruleset's approved set.
 *
 * Tail, not prefix, and a word rather than a `⚠`: the name is the primary
 * information and a narrow dropdown truncates from the right, so the marker
 * is what gets cut — never the identity. A warning glyph would read as an
 * error, and a preset the artist built on purpose is not one; it is just
 * what a Reset All would delete. */
export function presetOptionLabel(option: PanelRenderPresetOption): string {
  return option.standard ? option.name : `${option.name} · custom`;
}

/** Frame card status line: `"No Sentinel Frame tag."` / `"On <camera>."`,
 * with a `"· N formats"` tail when the server populates `format_count`
 * (from the Sentinel Frame tag's enabled-format ids; `null` if the tag has
 * none or the read failed). */
export function frameStatusLine(frame: PanelRenderFrame | null): string {
  if (frame === null) return "Frame status unavailable.";
  if (!frame.has_tag || !frame.camera_name) return "No Sentinel Frame tag.";
  const formats = frame.format_count;
  if (typeof formats === "number") {
    return `On ${frame.camera_name} · ${formats} format${formats === 1 ? "" : "s"}.`;
  }
  return `On ${frame.camera_name}.`;
}

/** AOVs card status line: `"<count> AOVs"` — a count only; the Output
 * switch (Multi-Part EXR / Direct output) owns the mode, so the status line
 * doesn't repeat it. Distinct note when Redshift itself isn't available
 * (`{error: "redshift_unavailable"}` — a scene-independent condition, not a
 * block failure). */
export function aovStatusLine(aovs: PanelRenderAovs | null): string {
  if (aovs === null) return "AOV status unavailable.";
  if ("error" in aovs) return "Redshift unavailable.";
  return `${aovs.count} AOVs`;
}

/** Snapshots card status line: the effective directory plus its resolution
 * origin chip (`"auto-detected"` for the RenderView-parsed dir, `"manual"`
 * for the Settings fallback — see `flows.get_effective_snapshot_dir`). */
export function snapshotStatusLine(snapshots: PanelRenderSnapshots | null): string {
  if (snapshots === null) return "Snapshots status unavailable.";
  if (!snapshots.stills_dir) return "Stills folder unavailable.";
  if (snapshots.stills_rel) return `→ ${snapshots.stills_rel}`;
  return `→ ${snapshots.stills_dir} · unsaved scene`;
}

/** Last two segments of a path for display (the full path goes in a title). */
export function tailPath(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 2 ? `…/${parts.slice(-2).join("/")}` : path;
}

/** The SOURCE caption: RenderView's snapshot folder; "manual" only when it is
 * the Settings fallback (auto-detected is the normal case and says nothing). */
export function snapshotSourceLine(snapshots: PanelRenderSnapshots): string {
  if (!snapshots.dir) return "Source: no RenderView snapshot folder found — set one in Settings.";
  return `Source: ${tailPath(snapshots.dir)}${snapshots.origin === "manual" ? " · manual" : ""}`;
}

/** Warning about RenderView's session-only "Save snapshots as EXR" box, or a
 * quiet note for an empty folder; null when the newest snapshot is an EXR. */
export function snapshotSourceAlert(
  snapshots: PanelRenderSnapshots,
): { text: string; tone: "warn" | "secondary" } | null {
  const source = snapshots.source;
  if (!source || !snapshots.dir) return null;
  if (source.alert === "non_exr") {
    return {
      tone: "warn",
      text: `Newest snapshot is ${source.newest_ext}, not an EXR — tick "Save snapshots as EXR" in RenderView (it resets every Cinema 4D session).`,
    };
  }
  if (source.alert === "empty") return { tone: "secondary", text: "No snapshots yet — take one in RenderView." };
  return null;
}

/** Caption under the Watch folder switch. Status colour only for problems:
 * watching and converted are a mode and a routine result, not a verdict. */
export function watchCaption(snapshots: PanelRenderSnapshots): { text: string; tone: "secondary" | "warn" | "fail" } {
  if (!snapshots.watch_enabled) {
    return { tone: "secondary", text: "Off — Save Still converts the newest snapshot on demand." };
  }
  const status = snapshots.watch_status;
  const message = status?.message ?? "";
  switch (status?.state) {
    case "running":
      return { tone: "secondary", text: message ? `${message}…` : "Converting…" };
    case "ready":
      return { tone: message.includes("not reproduced") ? "warn" : "secondary", text: message || "Watching" };
    case "error":
      return { tone: "fail", text: `Failed: ${status.last_error || message}` };
    default:
      return { tone: "secondary", text: message ? `Watching · ${message}` : "Watching" };
  }
}

const SLATE_SOURCE_LABEL: Record<string, string> = {
  project: "project ruleset",
  machine: "machine setting",
  defaults: "default",
};

/** "on · project ruleset" — the slate state and who decided it. */
export function slateSummary(slate: PanelRenderSnapshots["slate"]): string {
  if (!slate) return "unavailable";
  return `${slate.enabled ? "on" : "off"} · ${SLATE_SOURCE_LABEL[slate.source] ?? slate.source}`;
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

/** The `panel/render/*` ops the server confirm-gates (`_needs_confirm` in
 * panel_render_ops.py: `reset_all`) — every other
 * mutation, including the additive `aov_tier` coverage actions and the
 * `set_light_groups`/`set_multipart` toggles, is reversible/idempotent and
 * runs without an inline confirm step, mirroring the native panel's own
 * lack of a confirmation dialog for those actions. */
const DESTRUCTIVE_RENDER_OPS = new Set(["reset_all"]);

export function isDestructiveRenderOp(op: string): boolean {
  return DESTRUCTIVE_RENDER_OPS.has(op);
}

/** Toast after Save Still. A RenderView-post notice turns it into a warning
 * when something the artist saw in RenderView is not in the PNG. */
export function stillSavedToast(notice: string | undefined): { message: string; variant: "success" | "warn" } {
  if (!notice) return { message: "Still saved.", variant: "success" };
  return {
    message: `Still saved. ${notice}.`,
    variant: notice.includes("not reproduced") ? "warn" : "success",
  };
}
