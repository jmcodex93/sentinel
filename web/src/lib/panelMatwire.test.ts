import { describe, expect, it } from "vitest";
import {
  IGNORED_REASON_LABELS,
  MATWIRE_IMPORT_LEFTOVERS_LABEL,
  channelLabel,
  ignoredReasonLabel,
  leftoverDestination,
  leftoverDestinationLabel,
  matwireToast,
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
