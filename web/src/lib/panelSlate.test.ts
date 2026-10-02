import { describe, expect, it } from "vitest";
import {
  DEFAULT_SLATE_STYLE, addItem, fieldsToAdd, isFieldItem, itemLabel, moveItem, postPlaced, removeItem,
  sameSlate, shortPath, sizeReadout,
} from "./panelSlate";

describe("slate editor helpers", () => {
  it("labels fields and literal text", () => {
    expect(itemLabel("{shot}")).toBe("Shot");
    expect(itemLabel("{post}")).toBe("RenderView post");
    expect(itemLabel("f{frame}")).toBe("f{Frame}");
    expect(itemLabel("{date} {time}")).toBe("{Date} {Time}");
    expect(itemLabel("ACME")).toBe("ACME");
    expect(isFieldItem("{date}")).toBe(true);
    expect(isFieldItem("ACME {date}")).toBe(false);
  });

  it("adds, removes and moves items without touching other slots", () => {
    let style = addItem(DEFAULT_SLATE_STYLE, "center", "  ACME ");
    expect(style.slots.center).toEqual(["ACME"]);
    expect(addItem(style, "center", "   ")).toBe(style);
    style = moveItem(style, "left", 1, -1);
    expect(style.slots.left).toEqual(["{version}", "{shot}"]);
    expect(moveItem(style, "left", 0, -1)).toBe(style);
    style = removeItem(style, "right", 2);
    expect(style.slots.right).toEqual(["{artist}", "{date}"]);
    expect(DEFAULT_SLATE_STYLE.slots.left).toEqual(["{shot}", "{version}"]);
  });

  it("compares saved and edited slates", () => {
    const saved = { enabled: true, style: DEFAULT_SLATE_STYLE };
    expect(sameSlate(saved, { enabled: true, style: { ...DEFAULT_SLATE_STYLE } })).toBe(true);
    expect(sameSlate(saved, { enabled: false, style: DEFAULT_SLATE_STYLE })).toBe(false);
    expect(sameSlate(saved, { enabled: true, style: { ...DEFAULT_SLATE_STYLE, size: 1.5 } })).toBe(false);
  });
});

describe("slate editor display", () => {
  it("offers only the fields not already in the slot", () => {
    const tokens = fieldsToAdd(["{shot}", "ACME {date}"]).map((f) => f.token);
    expect(tokens).not.toContain("shot");
    expect(tokens).toContain("date");          // only a lone {date} counts as placed
  });

  it("knows when {post} is placed anywhere", () => {
    expect(postPlaced(DEFAULT_SLATE_STYLE)).toBe(false);
    expect(postPlaced(addItem(DEFAULT_SLATE_STYLE, "right", "Look: {post}"))).toBe(true);
  });

  it("shortens paths and reads out the real strip size", () => {
    expect(shortPath("/projects/ACME/sentinel_rules.json")).toBe("…/ACME/sentinel_rules.json");
    expect(shortPath("C:\\work\\ACME\\sentinel_rules.json")).toBe("…/ACME/sentinel_rules.json");
    expect(sizeReadout(0.8, 39, false)).toBe("×0.8 · 39 px");
    expect(sizeReadout(0.5, 16, true)).toBe("×0.5 · 16 px · min");
    expect(sizeReadout(1)).toBe("×1.0");
  });
});
