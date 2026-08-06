import { describe, expect, it } from "vitest";
import { TOOL_GROUPS, toolToast } from "./panelTools";

describe("TOOL_GROUPS", () => {
  // v1.36.1 adds a fourth group. It was first called "Return Points" and
  // held only Pin State; renamed to "States & Options" and given Variant Set
  // as well, because a variant is NOT a point to come back to — it is an
  // alternative that coexists — so the first title described one sibling and
  // misdescribed the other. Kept as an exact-equality assertion: the contract
  // is "these groups, in this order", and loosening it to a `contains` would
  // stop catching a group accidentally appearing or moving.
  it("has the scene-authoring groups, Cleanup between Layout and Animation", () => {
    expect(TOOL_GROUPS.map((g) => g.title)).toEqual([
      "Layout & Hierarchy", "Cleanup", "Animation", "States & Options",
    ]);
  });
  it("States & Options holds the two sibling tools (v1.36.1)", () => {
    const group = TOOL_GROUPS.find((g) => g.title === "States & Options");
    expect(group?.tools).toEqual([
      { id: "panel/tools/pin_state", label: "Pin State" },
      { id: "panel/tools/variant_set", label: "Variant Set" },
    ]);
  });
  it("Cleanup group has the two cleanup tools", () => {
    const cleanup = TOOL_GROUPS.find((g) => g.title === "Cleanup");
    expect(cleanup?.tools.map((t) => t.id)).toEqual([
      "panel/tools/delete_empty_nulls", "panel/tools/clean_material_tags",
    ]);
  });
  it("carries no keyframe tools (dedicated Frames row, not a group entry)", () => {
    const allIds = TOOL_GROUPS.flatMap((g) => g.tools.map((t) => t.id));
    expect(allIds).not.toContain("panel/tools/keyframe_offset");
    expect(allIds).not.toContain("panel/tools/keyframe_stagger");
  });
  it("carries no Asset Hub entry (removed — reachable from Overview/QC/Deliver)", () => {
    const allIds = TOOL_GROUPS.flatMap((g) => g.tools.map((t) => t.id));
    expect(allIds).not.toContain("open_hub");
  });
  it("carries no mark_safe_area entry (moved to Frame sub-view)", () => {
    const allIds = TOOL_GROUPS.flatMap((g) => g.tools.map((t) => t.id));
    expect(allIds).not.toContain("panel/tools/mark_safe_area");
  });
  // v1.36 puso aquí Variant Set; v1.36.1 lo movió a "States & Options" para
  // que viva junto a Pin State — reestructurar la escena es su efecto, no
  // aquello por lo que el artista lo busca. Este grupo vuelve a ser sólo las
  // cuatro herramientas de disposición.
  it("Layout group has the hierarchy tools only (v1.36.1)", () => {
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

  it("delete_empty_nulls ok reports removed count (singular)", () => {
    const t = toolToast("panel/tools/delete_empty_nulls", { ok: true, removed: 1 });
    expect(t.variant).toBe("success");
    expect(t.message).toBe("Removed 1 empty null.");
  });
  it("delete_empty_nulls ok reports removed count (plural)", () => {
    const t = toolToast("panel/tools/delete_empty_nulls", { ok: true, removed: 4 });
    expect(t.message).toBe("Removed 4 empty nulls.");
  });
  it("delete_empty_nulls none_found → warn", () => {
    const t = toolToast("panel/tools/delete_empty_nulls", { ok: false, error: "none_found" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Nothing to clean — scene is already tidy.");
  });
  it("clean_material_tags ok reports broken + duplicate counts", () => {
    const t = toolToast("panel/tools/clean_material_tags", { ok: true, removed_broken: 2, removed_dupes: 3 });
    expect(t.variant).toBe("success");
    expect(t.message).toBe("Removed 2 broken + 3 duplicate tags.");
  });
  it("clean_material_tags ok singular tag phrasing", () => {
    const t = toolToast("panel/tools/clean_material_tags", { ok: true, removed_broken: 1, removed_dupes: 0 });
    expect(t.message).toBe("Removed 1 broken + 0 duplicate tag.");
  });
  it("clean_material_tags none_found → warn", () => {
    const t = toolToast("panel/tools/clean_material_tags", { ok: false, error: "none_found" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Nothing to clean — scene is already tidy.");
  });
  it("variant_set ok names the option and its object count (plural)", () => {
    const t = toolToast("panel/tools/variant_set", { ok: true, objects: 3, option: "Option A" });
    expect(t.variant).toBe("success");
    expect(t.message).toBe("Variant set created — 3 objects in Option A.");
  });
  it("variant_set ok singular phrasing", () => {
    const t = toolToast("panel/tools/variant_set", { ok: true, objects: 1, option: "Option A" });
    expect(t.message).toBe("Variant set created — 1 object in Option A.");
  });
  it("variant_set no_selection → warn telling the artist what to do", () => {
    const t = toolToast("panel/tools/variant_set", { ok: false, error: "no_selection" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Select one or more objects first.");
  });
  it("variant_set no_tag → warn (not the generic fallback)", () => {
    const t = toolToast("panel/tools/variant_set", { ok: false, error: "no_tag" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Couldn't create the Variants tag on the anchor.");
  });
  it("pin_state ok reports the pinned count (plural)", () => {
    const t = toolToast("panel/tools/pin_state", { ok: true, pinned: 3, failed: 0 });
    expect(t.variant).toBe("success");
    expect(t.message).toBe("Pinned 3 objects.");
  });
  it("pin_state ok singular phrasing", () => {
    const t = toolToast("panel/tools/pin_state", { ok: true, pinned: 1, failed: 0 });
    expect(t.message).toBe("Pinned 1 object.");
  });
  it("pin_state names partial failures instead of hiding them", () => {
    const t = toolToast("panel/tools/pin_state", { ok: true, pinned: 2, failed: 1 });
    expect(t.message).toBe("Pinned 2 objects · 1 failed.");
  });
  it("pin_state no_selection → warn", () => {
    const t = toolToast("panel/tools/pin_state", { ok: false, error: "no_selection" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Select one or more objects first.");
  });
  it("pin_state no_pin → warn (not the generic fallback)", () => {
    const t = toolToast("panel/tools/pin_state", { ok: false, error: "no_pin" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Couldn't pin the selection — no state was captured.");
  });
  it("keyframe_offset ok reports keys/objects/frames from the op result", () => {
    const t = toolToast("panel/tools/keyframe_offset", { ok: true, keys: 12, objects: 3, frames: 5 });
    expect(t.variant).toBe("success");
    expect(t.message).toBe("Shifted 12 keys across 3 objects by 5f.");
  });
  it("keyframe_offset ok singular phrasing", () => {
    const t = toolToast("panel/tools/keyframe_offset", { ok: true, keys: 1, objects: 1, frames: -2 });
    expect(t.message).toBe("Shifted 1 key across 1 object by -2f.");
  });
  it("keyframe_offset no_keys → warn", () => {
    const t = toolToast("panel/tools/keyframe_offset", { ok: false, error: "no_keys" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Selection has no keyframes.");
  });
  it("keyframe_offset bad_frames → warn", () => {
    const t = toolToast("panel/tools/keyframe_offset", { ok: false, error: "bad_frames" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Frames must be a non-zero integer (±10000).");
  });
  it("keyframe_stagger ok reports objects/frames/keys from the op result", () => {
    const t = toolToast("panel/tools/keyframe_stagger", { ok: true, objects: 4, frames: 3, keys: 20 });
    expect(t.variant).toBe("success");
    expect(t.message).toBe("Staggered 4 objects (3f step, 20 keys).");
  });
  it("keyframe_stagger ok singular phrasing", () => {
    const t = toolToast("panel/tools/keyframe_stagger", { ok: true, objects: 1, frames: 1, keys: 1 });
    expect(t.message).toBe("Staggered 1 object (1f step, 1 key).");
  });
  it("keyframe_stagger need_two → warn", () => {
    const t = toolToast("panel/tools/keyframe_stagger", { ok: false, error: "need_two" });
    expect(t.variant).toBe("warn");
    expect(t.message).toBe("Select two or more objects to stagger.");
  });
});
