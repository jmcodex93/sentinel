import { describe, expect, it } from "vitest";
import { computeBulkChanges } from "./repath";

const asset = (key: string, path: string, status = "ok", repathable = true) =>
  ({ key, path, status: status as never, repathable });

describe("computeBulkChanges — parity with dialogs.py _preview_bulk", () => {
  it("is case-insensitive by default", () => {
    const out = computeBulkChanges([asset("k", "D:/Tex/FOO.png")], "d:/tex", "E:/tex", false);
    expect(out.get("k")).toBe("E:/tex/FOO.png");
  });
  it("match case restricts", () => {
    const out = computeBulkChanges([asset("k", "D:/Tex/FOO.png")], "d:/tex", "E:/tex", true);
    expect(out.size).toBe(0);
  });
  it("windows backslashes survive find AND replace (no regex/$ expansion)", () => {
    const out = computeBulkChanges(
      [asset("k", "D:\\proj\\tex\\a.png")], "D:\\proj", "\\\\server\\share$&", false);
    expect(out.get("k")).toBe("\\\\server\\share$&\\tex\\a.png");
  });
  it("skips asset_uri, empty and non-repathable rows", () => {
    const out = computeBulkChanges([
      asset("a", "x/t.png", "asset_uri"), asset("b", "x/t.png", "empty"),
      asset("c", "x/t.png", "ok", false)], "x", "y", false);
    expect(out.size).toBe(0);
  });
  it("no-op replacement produces no pending entry", () => {
    expect(computeBulkChanges([asset("k", "a/b.png")], "zzz", "q", false).size).toBe(0);
  });
});
