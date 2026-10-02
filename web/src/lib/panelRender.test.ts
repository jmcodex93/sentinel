import { describe, expect, it } from "vitest";
import {
  aovStatusLine,
  frameStatusLine,
  isDestructiveRenderOp,
  postrenderStatusLine,
  presetOptionLabel,
  presetStatusLine,
  stillSavedToast,
  slateSummary,
  snapshotSourceAlert,
  snapshotSourceLine,
  snapshotStatusLine,
  watchCaption,
} from "./panelRender";
import type {
  PanelRenderAovs,
  PanelRenderFrame,
  PanelRenderPostrender,
  PanelRenderPreset,
  PanelRenderPresetOption,
  PanelRenderSnapshots,
} from "../types";

describe("presetStatusLine", () => {
  it("formats name, resolution and fps", () => {
    const preset: PanelRenderPreset = {
      preset_name: "Render",
      preset_index: 2,
      presets: [],
      fps: 25,
      resolution: "1920x1080",
    };
    expect(presetStatusLine(preset)).toBe("Render · 1920x1080 · 25fps");
  });

  it("renders an unavailable note for a null block", () => {
    expect(presetStatusLine(null)).toBe("Render preset unavailable.");
  });

  it("falls back gracefully when fields are missing", () => {
    const preset: PanelRenderPreset = {
      preset_name: null,
      preset_index: null,
      presets: [],
      fps: null,
      resolution: null,
    };
    expect(presetStatusLine(preset)).toBe("No active preset.");
  });
});

describe("presetOptionLabel", () => {
  const option = (over: Partial<PanelRenderPresetOption> = {}): PanelRenderPresetOption => ({
    index: 0,
    name: "RS-LookDev 2026",
    standard: false,
    ...over,
  });

  it("shows the real scene name, never a normalized one", () => {
    expect(presetOptionLabel(option({ standard: true }))).toBe("RS-LookDev 2026");
  });

  it("marks a preset outside the standard set without inventing an error", () => {
    const label = presetOptionLabel(option());
    expect(label.startsWith("RS-LookDev 2026")).toBe(true);
    expect(label).toBe("RS-LookDev 2026 \u00b7 custom");
    expect(label).not.toContain("\u26a0");
  });

  it("leaves a standard preset unmarked", () => {
    expect(presetOptionLabel(option({ name: "Render", standard: true }))).toBe("Render");
  });
});

describe("frameStatusLine", () => {
  it("reports no frame tag", () => {
    const frame: PanelRenderFrame = { has_tag: false, camera_name: null };
    expect(frameStatusLine(frame)).toBe("No Sentinel Frame tag.");
  });

  it("reports the host camera when a tag exists", () => {
    const frame: PanelRenderFrame = { has_tag: true, camera_name: "Camera" };
    expect(frameStatusLine(frame)).toBe("On Camera.");
  });

  it("appends the format count when known", () => {
    const frame: PanelRenderFrame = { has_tag: true, camera_name: "Camera", format_count: 5 };
    expect(frameStatusLine(frame)).toBe("On Camera · 5 formats.");
  });

  it("renders an unavailable note for a null block", () => {
    expect(frameStatusLine(null)).toBe("Frame status unavailable.");
  });
});

describe("aovStatusLine", () => {
  it("formats the AOV count only — the Output switch owns the mode", () => {
    const aovs: PanelRenderAovs = {
      count: 11,
      multipart: true,
      target: "Nuke",
      light_groups: true,
      light_group_names: ["fg", "bg"],
    };
    expect(aovStatusLine(aovs)).toBe("11 AOVs");
  });

  it("formats the count regardless of multipart state", () => {
    const aovs: PanelRenderAovs = {
      count: 3,
      multipart: false,
      target: "After Effects",
      light_groups: false,
      light_group_names: [],
    };
    expect(aovStatusLine(aovs)).toBe("3 AOVs");
  });

  it("reports Redshift unavailable", () => {
    expect(aovStatusLine({ error: "redshift_unavailable" })).toBe("Redshift unavailable.");
  });

  it("renders an unavailable note for a null block", () => {
    expect(aovStatusLine(null)).toBe("AOV status unavailable.");
  });
});

describe("snapshotStatusLine", () => {
  const base: PanelRenderSnapshots = {
    dir: "/Users/artist/Desktop/rv_snaps", origin: "auto", watch_enabled: false,
    stills_dir: "/projects/ACME/output/stills/Javier/261002", stills_rel: "output/stills/Javier/261002",
  };

  it("leads with where the PNGs land, relative to the project", () => {
    expect(snapshotStatusLine(base)).toBe("→ output/stills/Javier/261002");
  });

  it("names the absolute fallback for an unsaved scene", () => {
    expect(snapshotStatusLine({ ...base, stills_rel: null })).toBe(
      "→ /projects/ACME/output/stills/Javier/261002 · unsaved scene");
  });

  it("renders unavailable notes", () => {
    expect(snapshotStatusLine({ ...base, stills_dir: null })).toBe("Stills folder unavailable.");
    expect(snapshotStatusLine(null)).toBe("Snapshots status unavailable.");
  });

  it("shows the source tail and 'manual' only for the fallback", () => {
    expect(snapshotSourceLine(base)).toBe("Source: …/Desktop/rv_snaps");
    expect(snapshotSourceLine({ ...base, origin: "manual" })).toBe("Source: …/Desktop/rv_snaps · manual");
    expect(snapshotSourceLine({ ...base, dir: null })).toContain("no RenderView snapshot folder");
  });

  it("warns when RenderView stopped writing EXR", () => {
    const alert = snapshotSourceAlert({ ...base, source: { newest_ext: ".rssnap2", alert: "non_exr" } });
    expect(alert?.tone).toBe("warn");
    expect(alert?.text).toContain(".rssnap2");
    expect(snapshotSourceAlert({ ...base, source: { newest_ext: ".exr", alert: null } })).toBeNull();
    expect(snapshotSourceAlert({ ...base, source: { newest_ext: null, alert: "empty" } })?.tone).toBe("secondary");
  });

  it("describes the watch state, colouring only problems", () => {
    expect(watchCaption(base).text).toContain("Off");
    const on = { ...base, watch_enabled: true };
    expect(watchCaption({ ...on, watch_status: { state: "watching", message: "" } })).toEqual({ tone: "secondary", text: "Watching" });
    expect(watchCaption({ ...on, watch_status: { state: "ready", message: "converted a.png · RenderView post applied: LUT X 49%" } }).tone).toBe("secondary");
    expect(watchCaption({ ...on, watch_status: { state: "ready", message: "converted a.png · not reproduced: bloom" } }).tone).toBe("warn");
    expect(watchCaption({ ...on, watch_status: { state: "error", message: "x", last_error: "decoder failed" } })).toEqual({ tone: "fail", text: "Failed: decoder failed" });
  });

  it("summarises the slate and who decided it", () => {
    expect(slateSummary({ enabled: true, source: "project" })).toBe("on · project ruleset");
    expect(slateSummary({ enabled: false, source: "defaults" })).toBe("off · default");
  });
});

describe("postrenderStatusLine", () => {
  it("reports a passed report", () => {
    const postrender: PanelRenderPostrender = {
      available: true,
      generated_at: "2026-07-20T10:00:00",
      passed: true,
    };
    expect(postrenderStatusLine(postrender)).toBe("Passed · 2026-07-20T10:00:00");
  });

  it("reports a failed report", () => {
    const postrender: PanelRenderPostrender = {
      available: true,
      generated_at: "2026-07-20T10:00:00",
      passed: false,
    };
    expect(postrenderStatusLine(postrender)).toBe("Issues found · 2026-07-20T10:00:00");
  });

  it("reports no report yet", () => {
    expect(postrenderStatusLine({ available: false })).toBe("No render validation yet.");
  });

  it("renders an unavailable note for a null block", () => {
    expect(postrenderStatusLine(null)).toBe("Post-render status unavailable.");
  });
});

describe("isDestructiveRenderOp", () => {
  it("flags reset_all as destructive", () => {
    expect(isDestructiveRenderOp("reset_all")).toBe(true);
  });

  it("does not flag the additive/reversible ops, including aov_tier and set_light_groups", () => {
    expect(isDestructiveRenderOp("aov_tier")).toBe(false);
    expect(isDestructiveRenderOp("set_light_groups")).toBe(false);
    expect(isDestructiveRenderOp("set_preset")).toBe(false);
    expect(isDestructiveRenderOp("add_frame_tag")).toBe(false);
    expect(isDestructiveRenderOp("select_frame_tag")).toBe(false);
    expect(isDestructiveRenderOp("set_multipart")).toBe(false);
    expect(isDestructiveRenderOp("toggle_watchfolder")).toBe(false);
    expect(isDestructiveRenderOp("save_still")).toBe(false);
    expect(isDestructiveRenderOp("open_folder")).toBe(false);
  });
});

describe("save still toast", () => {
  it("is a plain success without a notice", () => {
    expect(stillSavedToast(undefined)).toEqual({ message: "Still saved.", variant: "success" });
  });
  it("reports re-applied post as success and missing post as a warning", () => {
    expect(stillSavedToast("RenderView post applied: LUT Look 49%").variant).toBe("success");
    const warn = stillSavedToast("RenderView post applied: LUT Look 49% · not reproduced: bloom");
    expect(warn.variant).toBe("warn");
    expect(warn.message).toBe("Still saved. RenderView post applied: LUT Look 49% · not reproduced: bloom.");
  });
});
