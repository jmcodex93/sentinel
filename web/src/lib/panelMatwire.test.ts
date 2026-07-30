import { describe, expect, it } from "vitest";
import {
  IGNORED_REASON_LABELS,
  MATWIRE_IMPORT_LEFTOVERS_LABEL,
  MATWIRE_MULTIPLY_AO_LABEL,
  MATWIRE_PROJECTION_UNAVAILABLE_COPY,
  PROJECTION_OPTIONS,
  aoDestination,
  aoDestinationLabel,
  channelLabel,
  createMaterialCount,
  ignoredReasonLabel,
  leftoverDestination,
  leftoverDestinationLabel,
  matwireToast,
  packedOrmNote,
  projectionUnavailableNote,
  suffixWarningsNote,
} from "./panelMatwire";

/** AUTHORITATIVE ignored-reason list, pinned against the engine
 * (plugin/sentinel/matwire.py — every literal appended to `ignored` /
 * `set_ignored`). If the engine grows a reason, this test is the tripwire
 * forcing a label before the SPA ships an unlabeled raw slug.
 * v1.32.1: `packed_orm` left the list — ORM/ARM is a real channel now,
 * not an ignore reason. */
const ENGINE_REASONS = [
  "bad_extension",
  "no_channel",
  "duplicate_channel",
  "lower_resolution",
  "dx_superseded",
  "pbr_wins",
];

describe("IGNORED_REASON_LABELS", () => {
  it("covers every reason the engine can emit (completeness pin)", () => {
    for (const reason of ENGINE_REASONS) {
      expect(IGNORED_REASON_LABELS[reason], `missing label for "${reason}"`).toBeTruthy();
    }
  });

  it("has no stale labels for reasons the engine no longer emits", () => {
    expect(Object.keys(IGNORED_REASON_LABELS).sort()).toEqual([...ENGINE_REASONS].sort());
  });

  it("uses the brief's exact copy for the spelled-out reasons", () => {
    expect(IGNORED_REASON_LABELS.lower_resolution).toBe("lower resolution");
    expect(IGNORED_REASON_LABELS.pbr_wins).toBe("PBR maps take precedence");
    expect(IGNORED_REASON_LABELS.dx_superseded).toBe("GL normal preferred");
    expect(IGNORED_REASON_LABELS.no_channel).toBe("unrecognized");
    expect(IGNORED_REASON_LABELS.bad_extension).toBe("not an image");
  });

  it("ignoredReasonLabel falls back to the raw slug for an unknown reason", () => {
    expect(ignoredReasonLabel("lower_resolution")).toBe("lower resolution");
    expect(ignoredReasonLabel("future_reason")).toBe("future_reason");
  });
});

describe("matwireToast", () => {
  it("success reads 'Created 3 RS material(s).'", () => {
    const t = matwireToast({ ok: true, created: 3, materials: ["a", "b", "c"], errors: [] });
    expect(t.message).toBe("Created 3 RS material(s).");
    expect(t.variant).toBe("success");
  });

  it("failed sets append the warn suffix and go warn", () => {
    const t = matwireToast({
      ok: true,
      created: 2,
      materials: ["a", "b"],
      errors: [["broken_set", "wire_failed"]],
    });
    expect(t.message).toBe("Created 2 RS material(s). (1 set(s) failed)");
    expect(t.variant).toBe("warn");
  });

  it("no_sets → actionable copy", () => {
    const t = matwireToast({ ok: false, error: "no_sets" });
    expect(t.message).toBe("No texture sets recognized in that folder.");
    expect(t.variant).toBe("warn");
  });

  it("bad_folder → actionable copy", () => {
    const t = matwireToast({ ok: false, error: "bad_folder" });
    expect(t.message).toBe("That folder doesn't exist.");
    expect(t.variant).toBe("warn");
  });

  it("redshift_unavailable → actionable copy", () => {
    const t = matwireToast({ ok: false, error: "redshift_unavailable" });
    expect(t.message).toBe("Redshift is not available.");
    expect(t.variant).toBe("warn");
  });

  it("nothing_selected → actionable copy", () => {
    const t = matwireToast({ ok: false, error: "nothing_selected" });
    expect(t.message).toBe("All sets are excluded.");
    expect(t.variant).toBe("warn");
  });

  it("unknown error (no_document / network) → generic warn", () => {
    const t = matwireToast({ ok: false, error: "no_document" });
    expect(t.message).toBe("Couldn't create materials.");
    expect(t.variant).toBe("warn");
  });
});

describe("channelLabel", () => {
  it("labels packed_orm as 'ORM/ARM (packed)'", () => {
    expect(channelLabel("packed_orm")).toBe("ORM/ARM (packed)");
  });

  it("passes every other channel through untouched", () => {
    expect(channelLabel("basecolor")).toBe("basecolor");
    expect(channelLabel("roughness")).toBe("roughness");
  });
});

describe("leftoverDestination", () => {
  it("names the assigned set", () => {
    expect(leftoverDestination("plaster")).toBe("→ plaster");
  });

  it("unassigned goes to the leftovers material", () => {
    expect(leftoverDestination(null)).toBe("→ leftovers material");
  });
});

describe("leftoverDestinationLabel", () => {
  it("assigned + set still included shows the arrow destination", () => {
    const label = leftoverDestinationLabel(
      { file: "plaster_extra.png", set: "plaster" },
      new Set(),
    );
    expect(label).toBe("→ plaster");
  });

  it("assigned + set excluded shows the dropped label, not a stale arrow", () => {
    const label = leftoverDestinationLabel(
      { file: "plaster_extra.png", set: "plaster" },
      new Set(["plaster"]),
    );
    expect(label).toBe("dropped (set excluded)");
  });

  it("unassigned always goes to the leftovers material, regardless of exclusions", () => {
    const label = leftoverDestinationLabel(
      { file: "unknown.png", set: null },
      new Set(["plaster"]),
    );
    expect(label).toBe("→ leftovers material");
  });
});

describe("suffixWarningsNote", () => {
  it("is null when there are no warnings", () => {
    expect(suffixWarningsNote([])).toBeNull();
    expect(suffixWarningsNote(undefined)).toBeNull();
  });

  it("names the rejected ruleset keys", () => {
    expect(suffixWarningsNote(["bogus", "nope"])).toBe(
      "Ruleset matwire_suffixes: invalid key(s) ignored — bogus, nope",
    );
  });
});

describe("leftover import checkbox copy", () => {
  it("is pinned to the brief's exact label", () => {
    expect(MATWIRE_IMPORT_LEFTOVERS_LABEL).toBe("Import unrecognized files");
  });
});

describe("packedOrmNote", () => {
  it("lists both fed inputs when no dedicated map competes", () => {
    expect(packedOrmNote(["roughness", "metalness"])).toBe("→ roughness + metalness");
  });

  it("lists the single surviving input when one dedicated map wins", () => {
    expect(packedOrmNote(["metalness"])).toBe("→ metalness");
    expect(packedOrmNote(["roughness"])).toBe("→ roughness");
  });

  it("says the ORM ends up unconnected when dedicated maps win both", () => {
    // The writer degrades the splitter to a bare sampler here — the preview
    // must not read like a normal wired channel (review I2).
    expect(packedOrmNote([])).toBe("→ unconnected (dedicated maps win)");
  });

  it("renders nothing for rows without the field (every non-ORM channel)", () => {
    expect(packedOrmNote(undefined)).toBeNull();
  });
});

describe("createMaterialCount", () => {
  const unassigned = [{ file: "notes.png", set: null }];
  const assigned = [{ file: "plaster_thumb.png", set: "plaster" }];

  it("is just the included sets when leftover import is off", () => {
    expect(createMaterialCount(3, false, unassigned)).toBe(3);
  });

  it("adds the catch-all material when an unassigned leftover would be imported", () => {
    expect(createMaterialCount(3, true, unassigned)).toBe(4);
  });

  it("adds nothing when every leftover already has a home set", () => {
    expect(createMaterialCount(3, true, assigned)).toBe(3);
    expect(createMaterialCount(3, true, [])).toBe(3);
  });

  it("counts the catch-all once regardless of how many leftovers are unassigned", () => {
    expect(
      createMaterialCount(1, true, [
        { file: "a.png", set: null },
        { file: "b.png", set: null },
      ]),
    ).toBe(2);
  });

  it("stays at zero with no included sets (the op returns no_sets first)", () => {
    expect(createMaterialCount(0, true, unassigned)).toBe(0);
  });
});

// --- v1.33: Projection + AO multiply ---------------------------------------

/** The server's `matwire.ao_destination` outcomes, verbatim. `aoDestination`
 * is a CLIENT MIRROR (the sub-view must relabel the AO row the instant the
 * checkbox flips, without a folder re-scan that would clobber the artist's
 * name edits) — this list is the pin that keeps the mirror and the single
 * source from drifting. */
const SERVER_AO_DESTINATIONS = ["base_color_multiply", "unconnected"];

describe("aoDestination (mirror of matwire.ao_destination)", () => {
  it("returns the server's exact outcome strings", () => {
    expect(aoDestination(["ao", "basecolor"], true)).toBe(SERVER_AO_DESTINATIONS[0]);
    expect(aoDestination(["ao", "basecolor"], false)).toBe(SERVER_AO_DESTINATIONS[1]);
  });

  it("is null for a set with no AO at all", () => {
    expect(aoDestination(["basecolor", "roughness"], true)).toBeNull();
  });

  it("never promises the multiply without a base color to multiply into", () => {
    // AO-only set: the writer leaves the AO loose (a color layer would
    // dangle), so the row must say unconnected even with the box ticked.
    expect(aoDestination(["ao", "roughness"], true)).toBe("unconnected");
  });
});

describe("aoDestinationLabel", () => {
  it("names the multiply target when the AO is wired", () => {
    expect(aoDestinationLabel("base_color_multiply")).toBe("→ base color (multiply)");
  });

  it("says unconnected when the AO stays a loose sampler", () => {
    expect(aoDestinationLabel("unconnected")).toBe("→ unconnected");
  });

  it("renders nothing when there is no AO row", () => {
    expect(aoDestinationLabel(null)).toBeNull();
  });
});

describe("AO multiply checkbox copy", () => {
  it("says DEDICATED — a packed ORM's AO is never wired by this toggle", () => {
    // Honesty fix (Task 1 review Minor): a set with `packed_orm` but no
    // dedicated `ao` file has its AO inside the ORM's red channel, which
    // the writer never wires — an unscoped "Multiply AO into base color"
    // would promise an effect that silently does nothing.
    expect(MATWIRE_MULTIPLY_AO_LABEL).toBe("Multiply dedicated AO map into base color");
  });
});

describe("PROJECTION_OPTIONS", () => {
  it("carries exactly the values the op accepts (matwire_c4d.PROJECTION_TYPES)", () => {
    expect(PROJECTION_OPTIONS.map((o) => o.value)).toEqual(["uv", "triplanar"]);
  });

  it("labels them as the artist reads them in the RS node", () => {
    expect(PROJECTION_OPTIONS.map((o) => o.label)).toEqual(["UV Channel", "Tri-Planar"]);
  });
});

describe("projectionUnavailableNote", () => {
  it("explains the disabled selector instead of leaving a dead control", () => {
    expect(projectionUnavailableNote(false)).toBe(MATWIRE_PROJECTION_UNAVAILABLE_COPY);
    expect(MATWIRE_PROJECTION_UNAVAILABLE_COPY).toContain("Redshift");
  });

  it("renders nothing when the shared UV context node is available", () => {
    expect(projectionUnavailableNote(true)).toBeNull();
    // Preview shapes older than v1.33 (no field) must not scare the artist
    // with a warning about a node that is probably there — treat missing as
    // available, the same shape-tolerant default the other rows use.
    expect(projectionUnavailableNote(undefined)).toBeNull();
  });
});
