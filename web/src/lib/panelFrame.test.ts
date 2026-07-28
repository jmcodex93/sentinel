import { describe, expect, it } from "vitest";
import { frameHint, frameStatusLine, qc12StatusLine } from "./panelFrame";
import type { PanelFrameBlock, PanelFrameState } from "../types";

// Frame v2: `stale` is a constant false (auto-sync made staleness a
// transient) and blocks carry the Viewing mirror.
const block = (over: Partial<PanelFrameBlock>): PanelFrameBlock => ({
  has_tag: true,
  camera_name: "cam",
  format_count: 5,
  stale: false,
  viewing: "master",
  viewing_options: ["master", "16x9", "9x16"],
  ...over,
});

const state = (over: Partial<PanelFrameState>): PanelFrameState => ({
  frame: block({}),
  subjects: { marked_count: 2 },
  qc12: { pass: true, violations: 0, has_takes: true },
  ...over,
});

describe("frameHint", () => {
  it("no tag → add-a-frame", () => {
    expect(
      frameHint(
        state({ frame: block({ has_tag: false, camera_name: null, format_count: null }) }),
      ).toLowerCase(),
    ).toContain("add a sentinel frame");
  });
  it("tag but no delivery Takes → enable a format (above the false all-clear)", () => {
    // Even with subjects marked and QC #12 trivially passing (no Takes → the
    // check never ran), the hint must NOT read "all inside" — it must tell
    // the artist to enable a format (auto-sync generates its Takes) so QC #12
    // can actually evaluate.
    const h = frameHint(state({ subjects: { marked_count: 2 }, qc12: { pass: true, violations: 0, has_takes: false } }));
    expect(h.toLowerCase()).toContain("enable a delivery format");
    expect(h.toLowerCase()).toContain("automatically");
    expect(h).not.toContain("stay inside");
  });
  it("tag but no subjects → mark-your-subjects", () => {
    expect(frameHint(state({ subjects: { marked_count: 0 } })).toLowerCase()).toContain("mark your key subjects");
  });
  it("subjects + pass (with Takes) → all-inside", () => {
    expect(frameHint(state({}))).toContain("stay inside");
  });
  it("violations → warns with counts", () => {
    const h = frameHint(state({ qc12: { pass: false, violations: 3, has_takes: true } }));
    expect(h).toContain("3");
    expect(h).toContain("safe area");
  });
  it("no stale branch: violations win even with legacy stale=true payloads", () => {
    // Frame v2 removed the "Takes out of date" hint (auto-sync makes
    // staleness sub-second); a stray stale=true from an older server must
    // not resurrect it.
    const h = frameHint(
      state({ frame: block({ stale: true }), qc12: { pass: false, violations: 3, has_takes: true } }),
    );
    expect(h.toLowerCase()).not.toContain("out of date");
    expect(h).toContain("3");
  });
});

describe("frameStatusLine", () => {
  it("null → unavailable", () => {
    expect(frameStatusLine(null)).toContain("unavailable");
  });
  it("no tag", () => {
    expect(frameStatusLine(block({ has_tag: false, camera_name: null, format_count: null }))).toContain(
      "No Sentinel Frame",
    );
  });
  it("tag with camera + formats", () => {
    const s = frameStatusLine(block({ camera_name: "heroCam" }));
    expect(s).toContain("heroCam");
    expect(s).toContain("5");
  });
  it("frameStatusLine shows slice count", () => {
    expect(
      frameStatusLine({ has_tag: true, camera_name: "Hero", format_count: 2,
                        slice_count: 3 } as PanelFrameBlock)
    ).toBe("On Hero · 2 formats (3 slices).");
  });
  it("frameStatusLine omits zero slices", () => {
    expect(
      frameStatusLine({ has_tag: true, camera_name: "Hero", format_count: 1,
                        slice_count: 0 } as PanelFrameBlock)
    ).toBe("On Hero · 1 format.");
  });
});

describe("qc12StatusLine", () => {
  it("null → unavailable", () => {
    expect(qc12StatusLine(null)).toContain("unavailable");
  });
  it("no Takes → not evaluated (not a pass)", () => {
    const s = qc12StatusLine({ pass: true, violations: 0, has_takes: false });
    expect(s.toLowerCase()).toContain("not evaluated");
    expect(s.toLowerCase()).not.toContain("no violations");
  });
  it("pass (with Takes)", () => {
    expect(qc12StatusLine({ pass: true, violations: 0, has_takes: true }).toLowerCase()).toContain("no violations");
  });
  it("violations", () => {
    expect(qc12StatusLine({ pass: false, violations: 2, has_takes: true })).toContain("2");
  });
});
