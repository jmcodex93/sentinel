import { describe, expect, it } from "vitest";
import {
  filterRecent,
  notesStatusLine,
  statusBadgeTone,
  versionStatusLine,
} from "./panelDeliver";
import type { PanelVersionEntry } from "../types";

const entry = (over: Partial<PanelVersionEntry>): PanelVersionEntry => ({
  version: 1, status: "", age: null, qc_label: null, path: "/p/v001.c4d",
  filename: "v001.c4d", ...over,
});

describe("versionStatusLine", () => {
  it("null block → unavailable", () => {
    expect(versionStatusLine(null)).toBe("Version status unavailable.");
  });
  it("unsaved doc → save first note", () => {
    expect(versionStatusLine({ last: null, unsaved: true, recent: [] })).toContain("not saved");
  });
  it("no versions on a saved doc", () => {
    expect(versionStatusLine({ last: null, unsaved: false, recent: [] })).toContain("No versions");
  });
  it("last version renders version + status + age + qc", () => {
    const line = versionStatusLine({
      last: { version: 7, status: "TR", age: "2h ago", qc_label: "9/12" },
      unsaved: false, recent: [],
    });
    expect(line).toContain("v007");
    expect(line).toContain("TR");
    expect(line).toContain("2h ago");
    expect(line).toContain("9/12");
  });
  it("empty status renders as WIP", () => {
    const line = versionStatusLine({
      last: { version: 3, status: "", age: null, qc_label: null },
      unsaved: false, recent: [],
    });
    expect(line).toContain("WIP");
  });
});

describe("notesStatusLine", () => {
  it("null block → unavailable", () => {
    expect(notesStatusLine(null)).toBe("Notes status unavailable.");
  });
  it("pending todos get a warning prefix", () => {
    const line = notesStatusLine({
      summary: "Notes: text + 3 TODOs (2 pending)", todos_pending: 2,
      notes_present: true, unsaved: false,
    });
    expect(line.startsWith("⚠")).toBe(true);
  });
  it("no pending todos → no prefix", () => {
    const line = notesStatusLine({
      summary: "Notes: —", todos_pending: 0, notes_present: false, unsaved: false,
    });
    expect(line.startsWith("⚠")).toBe(false);
  });
});

describe("filterRecent", () => {
  const rows = [
    entry({ version: 1, status: "" }),
    entry({ version: 2, status: "TR" }),
    entry({ version: 3, status: "FINAL" }),
  ];
  it("__ALL__ returns everything", () => {
    expect(filterRecent(rows, "__ALL__")).toHaveLength(3);
  });
  it("empty-string filter matches WIP (status '')", () => {
    const out = filterRecent(rows, "");
    expect(out).toHaveLength(1);
    expect(out[0].version).toBe(1);
  });
  it("status filter matches exactly", () => {
    expect(filterRecent(rows, "TR").map((r) => r.version)).toEqual([2]);
  });
});

describe("statusBadgeTone", () => {
  it("maps known statuses", () => {
    expect(statusBadgeTone("")).toBe("wip");
    expect(statusBadgeTone("TR")).toBe("tr");
    expect(statusBadgeTone("CR")).toBe("cr");
    expect(statusBadgeTone("FINAL")).toBe("final");
  });
  it("unknown/custom status falls back to wip tone", () => {
    expect(statusBadgeTone("REV02")).toBe("wip");
  });
});
