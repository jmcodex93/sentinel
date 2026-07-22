import { describe, expect, it } from "vitest";
import {
  aovStatusLine,
  frameStatusLine,
  isDestructiveRenderOp,
  postrenderStatusLine,
  presetStatusLine,
  snapshotStatusLine,
} from "./panelRender";
import type {
  PanelRenderAovs,
  PanelRenderFrame,
  PanelRenderPostrender,
  PanelRenderPreset,
  PanelRenderSnapshots,
} from "../types";

describe("presetStatusLine", () => {
  it("formats name, resolution and fps", () => {
    const preset: PanelRenderPreset = {
      preset_name: "Render",
      preset_names: ["Previz", "Pre-Render", "Render", "Stills"],
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
      preset_names: [],
      fps: null,
      resolution: null,
    };
    expect(presetStatusLine(preset)).toBe("No active preset.");
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
  it("formats the AOV count and multipart state (ON)", () => {
    const aovs: PanelRenderAovs = {
      count: 11,
      multipart: true,
      target: "Nuke",
      light_groups: true,
      light_group_names: ["fg", "bg"],
    };
    expect(aovStatusLine(aovs)).toBe("11 AOVs · Multi-Part ON");
  });

  it("formats the multipart state (OFF)", () => {
    const aovs: PanelRenderAovs = {
      count: 3,
      multipart: false,
      target: "After Effects",
      light_groups: false,
      light_group_names: [],
    };
    expect(aovStatusLine(aovs)).toBe("3 AOVs · Multi-Part OFF");
  });

  it("reports Redshift unavailable", () => {
    expect(aovStatusLine({ error: "redshift_unavailable" })).toBe("Redshift unavailable.");
  });

  it("renders an unavailable note for a null block", () => {
    expect(aovStatusLine(null)).toBe("AOV status unavailable.");
  });
});

describe("snapshotStatusLine", () => {
  it("formats the directory and an auto-detected origin chip", () => {
    const snapshots: PanelRenderSnapshots = {
      dir: "/Users/artist/renders/snapshots",
      origin: "auto",
      watch_enabled: true,
    };
    expect(snapshotStatusLine(snapshots)).toBe("/Users/artist/renders/snapshots · auto-detected");
  });

  it("formats a manual-fallback origin chip", () => {
    const snapshots: PanelRenderSnapshots = {
      dir: "/Users/artist/renders/snapshots",
      origin: "manual",
      watch_enabled: false,
    };
    expect(snapshotStatusLine(snapshots)).toBe("/Users/artist/renders/snapshots · manual");
  });

  it("reports no directory set", () => {
    const snapshots: PanelRenderSnapshots = { dir: null, origin: "manual", watch_enabled: false };
    expect(snapshotStatusLine(snapshots)).toBe("No snapshot directory set.");
  });

  it("renders an unavailable note for a null block", () => {
    expect(snapshotStatusLine(null)).toBe("Snapshots status unavailable.");
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
  it("flags reset_all, force_vertical and aov_tier as destructive", () => {
    expect(isDestructiveRenderOp("reset_all")).toBe(true);
    expect(isDestructiveRenderOp("force_vertical")).toBe(true);
    expect(isDestructiveRenderOp("aov_tier")).toBe(true);
  });

  it("does not flag the additive/reversible ops", () => {
    expect(isDestructiveRenderOp("set_preset")).toBe(false);
    expect(isDestructiveRenderOp("add_frame_tag")).toBe(false);
    expect(isDestructiveRenderOp("select_frame_tag")).toBe(false);
    expect(isDestructiveRenderOp("toggle_multipart")).toBe(false);
    expect(isDestructiveRenderOp("toggle_watchfolder")).toBe(false);
    expect(isDestructiveRenderOp("save_still")).toBe(false);
    expect(isDestructiveRenderOp("open_folder")).toBe(false);
  });
});
