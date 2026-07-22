import { describe, expect, it } from "vitest";
import { PANEL_SECTIONS, railBadges, railMode } from "./panel";
import type { PanelOverview } from "../types";

describe("railMode", () => {
  it("is icon rail below the 560px breakpoint", () => {
    expect(railMode(0)).toBe("icon");
    expect(railMode(380)).toBe("icon");
    expect(railMode(559)).toBe("icon");
  });

  it("is labeled sidebar at/above the 560px breakpoint", () => {
    expect(railMode(560)).toBe("sidebar");
    expect(railMode(900)).toBe("sidebar");
  });
});

function overview(overrides: Partial<PanelOverview> = {}): PanelOverview {
  return {
    scene: null,
    qc: null,
    assets: null,
    render: null,
    deliver: null,
    ...overrides,
  };
}

describe("railBadges", () => {
  it("has no badges when qc/assets blocks are null (failed subsystem)", () => {
    const badges = railBadges(overview());
    expect(badges.qc).toBeNull();
    expect(badges.assets).toBeNull();
  });

  it("has no QC badge when there are zero new failures", () => {
    const badges = railBadges(overview({ qc: { passed: 12, total: 12, disabled: 0, top: [], fixable: [] } }));
    expect(badges.qc).toBeNull();
  });

  it("surfaces the QC fail count as passed/total delta", () => {
    const badges = railBadges(overview({ qc: { passed: 6, total: 12, disabled: 0, top: [], fixable: [] } }));
    expect(badges.qc).toBe(6);
  });

  it("does not subtract disabled checks again — qc.total is already net of them", () => {
    // qc.total from the score engine already excludes disabled checks
    // (qc/score.py: disabled checks `continue` before entering `counts`).
    // 8 passed, 11 total (already net) -> 11 - 8 = 3 new failures, not 2.
    const badges = railBadges(overview({ qc: { passed: 8, total: 11, disabled: 1, top: [], fixable: [] } }));
    expect(badges.qc).toBe(3);
  });

  it("has no assets badge when nothing is missing", () => {
    const badges = railBadges(overview({ assets: { count: 39, missing: 0, disk_label: "604 MB", vram_label: "3.3 GB" } }));
    expect(badges.assets).toBeNull();
  });

  it("surfaces the assets missing count", () => {
    const badges = railBadges(overview({ assets: { count: 39, missing: 1, disk_label: "604 MB", vram_label: "3.3 GB" } }));
    expect(badges.assets).toBe(1);
  });
});

describe("PANEL_SECTIONS", () => {
  it("lists exactly the 5 rail entries in mockup order", () => {
    expect(PANEL_SECTIONS.map((s) => s.id)).toEqual(["overview", "qc", "render", "deliver", "tools"]);
  });
});
