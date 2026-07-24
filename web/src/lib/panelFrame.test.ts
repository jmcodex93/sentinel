import { describe, expect, it } from "vitest";
import { frameHint, frameStatusLine, qc12StatusLine } from "./panelFrame";
import type { PanelFrameState } from "../types";

const state = (over: Partial<PanelFrameState>): PanelFrameState => ({
  frame: { has_tag: true, camera_name: "cam", format_count: 5, stale: false },
  subjects: { marked_count: 2 },
  qc12: { pass: true, violations: 0 },
  ...over,
});

describe("frameHint", () => {
  it("no tag → add-a-frame", () => {
    expect(frameHint(state({ frame: { has_tag: false, camera_name: null, format_count: null, stale: false } })).toLowerCase())
      .toContain("add a sentinel frame");
  });
  it("tag but no subjects → mark-your-subjects", () => {
    expect(frameHint(state({ subjects: { marked_count: 0 } })).toLowerCase()).toContain("mark your key subjects");
  });
  it("subjects + pass → all-inside", () => {
    expect(frameHint(state({}))).toContain("stay inside");
  });
  it("violations → warns with counts", () => {
    const h = frameHint(state({ qc12: { pass: false, violations: 3 } }));
    expect(h).toContain("3");
    expect(h).toContain("safe area");
  });
  it("stale takes priority over violations", () => {
    const h = frameHint(state({ frame: { has_tag: true, camera_name: "cam", format_count: 5, stale: true }, qc12: { pass: false, violations: 3 } }));
    expect(h.toLowerCase()).toContain("out of date");
  });
});

describe("frameStatusLine", () => {
  it("null → unavailable", () => {
    expect(frameStatusLine(null)).toContain("unavailable");
  });
  it("no tag", () => {
    expect(frameStatusLine({ has_tag: false, camera_name: null, format_count: null, stale: false })).toContain("No Sentinel Frame");
  });
  it("tag with camera + formats", () => {
    const s = frameStatusLine({ has_tag: true, camera_name: "heroCam", format_count: 5, stale: false });
    expect(s).toContain("heroCam");
    expect(s).toContain("5");
  });
});

describe("qc12StatusLine", () => {
  it("null → unavailable", () => {
    expect(qc12StatusLine(null)).toContain("unavailable");
  });
  it("pass", () => {
    expect(qc12StatusLine({ pass: true, violations: 0 }).toLowerCase()).toContain("no violations");
  });
  it("violations", () => {
    expect(qc12StatusLine({ pass: false, violations: 2 })).toContain("2");
  });
});
