import { describe, expect, it } from "vitest";
import {
  NEWSHOT_ERROR_COPY,
  STANDARD_ERROR_COPY,
  publishDisabledReason,
  qcGateLine,
  toggleExclude,
} from "./panelStandard";

describe("qcGateLine", () => {
  it("passing QC reads as the green light", () => {
    expect(qcGateLine({ passed: 12, total: 12, pass: true, failing: [] }))
      .toBe("QC 12/12 — ready to publish");
  });
  it("failing QC names the blockers", () => {
    expect(qcGateLine({ passed: 10, total: 12, pass: false, failing: ["Default Names", "Output Paths"] }))
      .toBe("QC 10/12 — fix before publishing: Default Names, Output Paths");
  });
});

describe("toggleExclude", () => {
  it("adds when absent, removes when present, never mutates", () => {
    const a = toggleExclude([], "petals", 1);
    expect(a).toEqual([["petals", 1]]);
    const b = toggleExclude(a, "petals", 1);
    expect(b).toEqual([]);
    expect(a).toEqual([["petals", 1]]);
  });
  it("same name different index are distinct entries", () => {
    const a = toggleExclude([["null", 0]], "null", 2);
    expect(a).toEqual([["null", 0], ["null", 2]]);
  });
});

describe("publishDisabledReason", () => {
  it("needs a folder first", () => {
    expect(publishDisabledReason({ folder: "", qcPass: true })).toBe("Choose the project folder first.");
  });
  it("refuses on failing QC", () => {
    expect(publishDisabledReason({ folder: "/prj", qcPass: false }))
      .toBe("The scene must pass the QC before publishing.");
  });
  it("null when publishable", () => {
    expect(publishDisabledReason({ folder: "/prj", qcPass: true })).toBeNull();
  });
});

describe("error copy", () => {
  it("every server code the ops can return has copy", () => {
    for (const code of ["no_document", "unsaved", "bad_folder", "qc_failing",
      "scene_changed", "rules_unreadable", "save_failed", "write_failed"]) {
      expect(STANDARD_ERROR_COPY[code]).toBeTruthy();
    }
    for (const code of ["bad_folder", "no_standard", "no_template",
      "template_missing", "bad_name", "exists", "copy_failed"]) {
      expect(NEWSHOT_ERROR_COPY[code]).toBeTruthy();
    }
  });
});
