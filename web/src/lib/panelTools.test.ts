import { describe, expect, it } from "vitest";
import { TOOL_GROUPS, toolToast } from "./panelTools";

describe("TOOL_GROUPS", () => {
  it("has the four native groups", () => {
    expect(TOOL_GROUPS.map((g) => g.title)).toEqual([
      "Layout & Hierarchy", "Animation", "QC Marking", "Asset",
    ]);
  });
  it("Layout group has the four hierarchy tools", () => {
    const ids = TOOL_GROUPS[0].tools.map((t) => t.id);
    expect(ids).toEqual([
      "panel/tools/hierarchy", "panel/tools/h_to_layers",
      "panel/tools/solo", "panel/tools/drop_to_floor",
    ]);
  });
});

describe("toolToast", () => {
  it("success with a count reads naturally", () => {
    const t = toolToast("panel/tools/drop_to_floor", { ok: true, dropped: 3 });
    expect(t.variant).toBe("success");
    expect(t.message).toContain("3");
  });
  it("no_selection → warn with actionable copy", () => {
    const t = toolToast("panel/tools/abc_retime", { ok: false, error: "no_selection" });
    expect(t.variant).toBe("warn");
    expect(t.message.toLowerCase()).toContain("select");
  });
  it("file_not_found → warn", () => {
    const t = toolToast("panel/tools/cam_simple", { ok: false, error: "file_not_found" });
    expect(t.variant).toBe("warn");
  });
  it("mark toggle reports marked count (real payload: lowercase verb)", () => {
    const t = toolToast("panel/tools/mark_safe_area", { ok: true, verb: "mark", marked: 2, unmarked: 0, failed: 0 });
    expect(t.message).toContain("Marked 2");
  });
  it("mark toggle reports unmarked count (real payload: lowercase verb)", () => {
    const t = toolToast("panel/tools/mark_safe_area", { ok: true, verb: "unmark", marked: 0, unmarked: 3, failed: 0 });
    expect(t.message).toContain("Unmarked 3");
  });
});
