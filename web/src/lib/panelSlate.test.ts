import { describe, expect, it } from "vitest";
import { DEFAULT_SLATE_STYLE, addItem, isFieldItem, itemLabel, moveItem, removeItem, sameSlate } from "./panelSlate";

describe("slate editor helpers", () => {
  it("labels fields and literal text", () => {
    expect(itemLabel("{shot}")).toBe("Shot");
    expect(itemLabel("{post}")).toBe("RenderView post");
    expect(itemLabel("f{frame}")).toBe("f‹Frame›");
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
