import { describe, expect, it } from "vitest";
import { cardActions, countLabel, detailPreview, orderedSections } from "./panelQc";
import type { PanelQcCheck, PanelQcSection } from "../types";

function check(overrides: Partial<PanelQcCheck> = {}): PanelQcCheck {
  return {
    id: "lights",
    label: "Lights Organization",
    severity: "FAIL",
    count: 8,
    new: 8,
    accepted: 0,
    detail: [{ label: "/ Sun Light", message: "Light is not inside the group.", extras: null }],
    can_select: true,
    can_fix: true,
    fix_action_id: "fix_lights",
    accepted_all: false,
    ...overrides,
  };
}

describe("cardActions", () => {
  it("enables select and fix for a fixable + selectable check", () => {
    const actions = cardActions(check());
    expect(actions).toEqual({ select: true, fix: true, info: true, accept: true });
  });

  it("disables select and fix for an info-only check", () => {
    const actions = cardActions(
      check({ id: "textures", can_select: false, can_fix: false, fix_action_id: null }),
    );
    expect(actions).toEqual({ select: false, fix: false, info: true, accept: true });
  });

  it("still exposes info/accept for a WARN check with no quick fix", () => {
    const actions = cardActions(
      check({
        id: "default_names",
        severity: "WARN",
        can_select: true,
        can_fix: false,
        fix_action_id: null,
      }),
    );
    expect(actions).toEqual({ select: true, fix: false, info: true, accept: true });
  });
});

function qc(overrides: Partial<PanelQcSection> = {}): PanelQcSection {
  return {
    score: { passed: 6, total: 10, disabled: 0 },
    fail: [check()],
    warn: [check({ id: "default_names", severity: "WARN" })],
    ok_count: 6,
    disabled_count: 0,
    ...overrides,
  };
}

describe("countLabel", () => {
  it("renders bare count when there is no active baseline (new === null)", () => {
    expect(countLabel(check({ count: 4, new: null, accepted: null }))).toBe("4");
  });

  it("renders '<new> new' with no accepted violations", () => {
    expect(countLabel(check({ new: 8, accepted: 0 }))).toBe("8 new");
  });

  it("renders '<new> new (<accepted> accepted)' when some are baselined", () => {
    expect(countLabel(check({ new: 3, accepted: 2 }))).toBe("3 new (2 accepted)");
  });
});

describe("detailPreview", () => {
  it("returns empty string for no violations", () => {
    expect(detailPreview([])).toBe("");
  });

  it("renders 'label — message' for a single violation", () => {
    expect(
      detailPreview([{ label: "/ Sun Light", message: "Light is not inside the group.", extras: null }]),
    ).toBe("/ Sun Light — Light is not inside the group.");
  });

  it("renders bare message when the violation has no label", () => {
    expect(detailPreview([{ label: "", message: "9 texture paths are missing.", extras: null }])).toBe(
      "9 texture paths are missing.",
    );
  });

  it("appends a '(+N more)' tail when there are additional violations", () => {
    expect(
      detailPreview([
        { label: "/ Sun Light", message: "Light is not inside the group.", extras: null },
        { label: "/ Rim Light.1", message: "Light is not inside the group.", extras: null },
        { label: "/ Fill Light", message: "Light is not inside the group.", extras: null },
      ]),
    ).toBe("/ Sun Light — Light is not inside the group. (+2 more)");
  });
});

describe("orderedSections", () => {
  it("surfaces fail/warn lists and the folded ok/disabled counts", () => {
    const sections = orderedSections(qc());
    expect(sections.fail).toEqual(qc().fail);
    expect(sections.warn).toEqual(qc().warn);
    expect(sections.okCount).toBe(6);
    expect(sections.disabledCount).toBe(0);
  });

  it("handles empty fail/warn groups (all checks passing)", () => {
    const sections = orderedSections(qc({ fail: [], warn: [], ok_count: 12, disabled_count: 1 }));
    expect(sections.fail).toEqual([]);
    expect(sections.warn).toEqual([]);
    expect(sections.okCount).toBe(12);
    expect(sections.disabledCount).toBe(1);
  });
});
