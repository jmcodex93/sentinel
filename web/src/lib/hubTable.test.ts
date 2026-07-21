import { describe, expect, it } from "vitest";
import {
  applyFacets,
  applySelection,
  channelsLabel,
  facetCounts,
  MIN_COL_WIDTH,
  sanitizeColWidths,
  sanitizeSortSpec,
  sortAssets,
  type FacetState,
} from "./hubTable";
import type { HubAsset, HubMeta } from "../types";

function asset(overrides: Partial<HubAsset> & { key: string }): HubAsset {
  return {
    key: overrides.key,
    path: overrides.path ?? `${overrides.key}.png`,
    resolved_path: null,
    status: overrides.status ?? "ok",
    asset_type: overrides.asset_type ?? "texture",
    size_bytes: overrides.size_bytes ?? null,
    size_label: "",
    owners: [],
    repathable: true,
    has_thumb: false,
  };
}

function meta(overrides: Partial<HubMeta>): HubMeta {
  return {
    width: 1024,
    height: 1024,
    channels: 3,
    bit_depth: 8,
    colorspace: "sRGB",
    vram_bytes: 0,
    vram_label: "0 B",
    res_label: "1K",
    res_tier: "2k",
    ...overrides,
  };
}

const emptyFacets = (): FacetState => ({ res: new Set(), channels: new Set(), depth: new Set() });

describe("channelsLabel", () => {
  it("maps 1|2 channels to Grey, 3 to RGB, 4 to RGBA", () => {
    expect(channelsLabel(1)).toBe("Grey");
    expect(channelsLabel(2)).toBe("Grey");
    expect(channelsLabel(3)).toBe("RGB");
    expect(channelsLabel(4)).toBe("RGBA");
  });
});

describe("sortAssets — default (sort: null)", () => {
  it("puts missing assets first, then orders each group by size_bytes desc with nulls last", () => {
    const assets = [
      asset({ key: "a", status: "ok", size_bytes: 100 }),
      asset({ key: "b", status: "missing", size_bytes: 50 }),
      asset({ key: "c", status: "ok", size_bytes: null }),
      asset({ key: "d", status: "missing", size_bytes: 500 }),
      asset({ key: "e", status: "ok", size_bytes: 900 }),
    ];
    const sorted = sortAssets(assets, {}, null);
    expect(sorted.map((a) => a.key)).toEqual(["d", "b", "e", "a", "c"]);
  });
});

describe("sortAssets — SortCol", () => {
  const assets = [
    asset({ key: "banana", path: "x/banana.png", status: "ok", size_bytes: 200 }),
    asset({ key: "apple", path: "x/apple.png", status: "missing", size_bytes: 800 }),
    asset({ key: "cherry", path: "x/cherry.png", status: "absolute", size_bytes: 50 }),
  ];
  const metas: Record<string, HubMeta> = {
    banana: meta({ res_tier: "4k", vram_bytes: 300 }),
    apple: meta({ res_tier: "8k", vram_bytes: 900 }),
    // cherry has no meta on purpose (must sort to the end regardless of direction)
  };

  it("sorts by name asc/desc", () => {
    expect(sortAssets(assets, metas, { col: "name", dir: "asc" }).map((a) => a.key)).toEqual([
      "apple",
      "banana",
      "cherry",
    ]);
    expect(sortAssets(assets, metas, { col: "name", dir: "desc" }).map((a) => a.key)).toEqual([
      "cherry",
      "banana",
      "apple",
    ]);
  });

  it("sorts by status asc/desc", () => {
    expect(sortAssets(assets, metas, { col: "status", dir: "asc" }).map((a) => a.key)).toEqual([
      "cherry",
      "apple",
      "banana",
    ]);
    expect(sortAssets(assets, metas, { col: "status", dir: "desc" }).map((a) => a.key)).toEqual([
      "banana",
      "apple",
      "cherry",
    ]);
  });

  it("sorts by size asc/desc", () => {
    expect(sortAssets(assets, metas, { col: "size", dir: "asc" }).map((a) => a.key)).toEqual([
      "cherry",
      "banana",
      "apple",
    ]);
    expect(sortAssets(assets, metas, { col: "size", dir: "desc" }).map((a) => a.key)).toEqual([
      "apple",
      "banana",
      "cherry",
    ]);
  });

  it("sorts by res asc/desc, assets without meta always last", () => {
    expect(sortAssets(assets, metas, { col: "res", dir: "asc" }).map((a) => a.key)).toEqual([
      "banana",
      "apple",
      "cherry",
    ]);
    expect(sortAssets(assets, metas, { col: "res", dir: "desc" }).map((a) => a.key)).toEqual([
      "apple",
      "banana",
      "cherry",
    ]);
  });

  it("sorts by vram asc/desc, assets without meta always last", () => {
    expect(sortAssets(assets, metas, { col: "vram", dir: "asc" }).map((a) => a.key)).toEqual([
      "banana",
      "apple",
      "cherry",
    ]);
    expect(sortAssets(assets, metas, { col: "vram", dir: "desc" }).map((a) => a.key)).toEqual([
      "apple",
      "banana",
      "cherry",
    ]);
  });
});

describe("applyFacets", () => {
  const assets = [
    asset({ key: "a" }),
    asset({ key: "b" }),
    asset({ key: "c" }),
    asset({ key: "d" }), // no meta
  ];
  const metas: Record<string, HubMeta> = {
    a: meta({ res_tier: "8k", channels: 4, bit_depth: 16 }),
    b: meta({ res_tier: "8k", channels: 3, bit_depth: 8 }),
    c: meta({ res_tier: "2k", channels: 3, bit_depth: 8 }),
  };

  it("is a no-op with no active facets", () => {
    expect(applyFacets(assets, metas, emptyFacets()).map((a) => a.key)).toEqual(["a", "b", "c", "d"]);
  });

  it("filters by a single group (OR within group)", () => {
    const facets = emptyFacets();
    facets.res.add("8k");
    expect(applyFacets(assets, metas, facets).map((a) => a.key)).toEqual(["a", "b"]);
  });

  it("composes res AND channels (intersection across groups)", () => {
    const facets = emptyFacets();
    facets.res.add("8k");
    facets.channels.add("RGBA");
    expect(applyFacets(assets, metas, facets).map((a) => a.key)).toEqual(["a"]);
  });

  it("excludes metaless assets once any facet in a group is active", () => {
    const facets = emptyFacets();
    facets.depth.add(8);
    const result = applyFacets(assets, metas, facets).map((a) => a.key);
    expect(result).not.toContain("d");
  });

  it("a facet combination with zero matches filters to empty", () => {
    const facets = emptyFacets();
    facets.res.add("2k");
    facets.channels.add("RGBA");
    expect(applyFacets(assets, metas, facets)).toEqual([]);
  });
});

describe("facetCounts", () => {
  const assets = [
    asset({ key: "a" }),
    asset({ key: "b" }),
    asset({ key: "c" }),
    asset({ key: "d" }), // no meta — excluded from all counts
  ];
  const metas: Record<string, HubMeta> = {
    a: meta({ res_tier: "8k", channels: 4, bit_depth: 16 }),
    b: meta({ res_tier: "8k", channels: 3, bit_depth: 8 }),
    c: meta({ res_tier: "2k", channels: 3, bit_depth: 8 }),
  };

  it("counts assets per facet value, excluding metaless assets", () => {
    const counts = facetCounts(assets, metas);
    expect(counts.res).toEqual({ "8k": 2, "2k": 1 });
    expect(counts.channels).toEqual({ RGBA: 1, RGB: 2 });
    expect(counts.depth).toEqual({ 16: 1, 8: 2 });
  });

  it("returns empty count maps when nothing has meta", () => {
    expect(facetCounts(assets, {})).toEqual({ res: {}, channels: {}, depth: {} });
  });
});

describe("sanitizeSortSpec — untrusted sentinel_settings.json input", () => {
  it("passes through a valid spec", () => {
    expect(sanitizeSortSpec({ col: "size", dir: "desc" })).toEqual({ col: "size", dir: "desc" });
  });
  it("rejects an unknown column", () => {
    expect(sanitizeSortSpec({ col: "bogus", dir: "asc" })).toBeNull();
  });
  it("rejects an invalid direction", () => {
    expect(sanitizeSortSpec({ col: "name", dir: "sideways" })).toBeNull();
  });
  it("rejects null/undefined/non-object input", () => {
    expect(sanitizeSortSpec(null)).toBeNull();
    expect(sanitizeSortSpec(undefined)).toBeNull();
    expect(sanitizeSortSpec("name")).toBeNull();
    expect(sanitizeSortSpec(42)).toBeNull();
  });
});

describe("sanitizeColWidths — untrusted sentinel_settings.json input", () => {
  it("keeps known resizable columns with finite numbers, clamped to the min", () => {
    expect(sanitizeColWidths({ type: 120, size: 10 })).toEqual({ type: 120, size: MIN_COL_WIDTH });
  });
  it("drops unknown keys, including a smuggled-in name width", () => {
    expect(sanitizeColWidths({ name: 999, bogus: 50, type: 100 })).toEqual({ type: 100 });
  });
  it("clamps 0/negative finite values to the min instead of trusting them", () => {
    expect(sanitizeColWidths({ type: 0, status: -50 })).toEqual({ type: MIN_COL_WIDTH, status: MIN_COL_WIDTH });
  });
  it("drops non-finite / non-numeric values (NaN, Infinity, strings)", () => {
    expect(sanitizeColWidths({ size: NaN, vram: Infinity, usedby: "200" })).toEqual({});
  });
  it("returns an empty object for null/undefined/non-object input", () => {
    expect(sanitizeColWidths(null)).toEqual({});
    expect(sanitizeColWidths(undefined)).toEqual({});
    expect(sanitizeColWidths("widths")).toEqual({});
  });
});

describe("applySelection", () => {
  const visible = ["a", "b", "c", "d", "e"];

  it("single mode always replaces the whole selection with just the clicked key", () => {
    const current = new Set(["a", "b", "c"]);
    expect(applySelection(current, visible, "a", "d", "single")).toEqual(new Set(["d"]));
  });

  it("toggle mode adds an unselected key", () => {
    const current = new Set(["a"]);
    expect(applySelection(current, visible, "a", "c", "toggle")).toEqual(new Set(["a", "c"]));
  });

  it("toggle mode removes an already-selected key", () => {
    const current = new Set(["a", "c"]);
    expect(applySelection(current, visible, "a", "c", "toggle")).toEqual(new Set(["a"]));
  });

  it("range mode selects forward from anchor to key inclusive, in visible order", () => {
    const current = new Set(["b"]);
    expect(applySelection(current, visible, "b", "d", "range")).toEqual(new Set(["b", "c", "d"]));
  });

  it("range mode selects backward from anchor to key inclusive", () => {
    const current = new Set(["d"]);
    expect(applySelection(current, visible, "d", "b", "range")).toEqual(new Set(["b", "c", "d"]));
  });

  it("range mode operates over the passed-in (filtered/sorted) visible ordering, not insertion order", () => {
    const filteredVisible = ["e", "c", "a"]; // some other sort/filter order
    expect(applySelection(new Set(), filteredVisible, "e", "a", "range")).toEqual(new Set(["e", "c", "a"]));
  });

  it("range mode with a null anchor falls back to single", () => {
    const current = new Set(["a", "b"]);
    expect(applySelection(current, visible, null, "d", "range")).toEqual(new Set(["d"]));
  });

  it("range mode with an anchor no longer in the visible set falls back to single", () => {
    const current = new Set(["a", "b"]);
    expect(applySelection(current, visible, "zzz", "d", "range")).toEqual(new Set(["d"]));
  });

  it("range mode where the clicked key itself is not visible falls back to single", () => {
    const current = new Set(["a", "b"]);
    expect(applySelection(current, visible, "a", "zzz", "range")).toEqual(new Set(["zzz"]));
  });

  it("always returns a new Set instance, never mutates the input", () => {
    const current = new Set(["a"]);
    const result = applySelection(current, visible, "a", "b", "toggle");
    expect(result).not.toBe(current);
    expect(current).toEqual(new Set(["a"])); // unmutated
  });
});
