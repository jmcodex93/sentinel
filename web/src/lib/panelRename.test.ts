import { describe, expect, it } from "vitest";
import { DEFAULT_RENAME_OPS, renameToast } from "./panelRename";

describe("DEFAULT_RENAME_OPS", () => {
  it("matches the server's renaming.DEFAULT_OPS field-for-field (keys AND values)", () => {
    // Pinned against plugin/sentinel/renaming.py DEFAULT_OPS — if either side
    // drifts, this test is the tripwire (mock-shape law: the SPA must send
    // the exact ops shape normalize_ops expects).
    expect(DEFAULT_RENAME_OPS).toEqual({
      pattern: "",
      find: "",
      replace: "",
      match_case: false,
      prefix: "",
      suffix: "",
      num_start: 1,
      num_padding: 3,
    });
  });
});

describe("renameToast", () => {
  it("success on objects reads 'Renamed 12 object(s).'", () => {
    const t = renameToast("objects", { ok: true, renamed: 12, collisions: 0, source: "objects" });
    expect(t.message).toBe("Renamed 12 object(s).");
    expect(t.variant).toBe("success");
  });

  it("success on materials reads 'Renamed 3 material(s).'", () => {
    const t = renameToast("materials", { ok: true, renamed: 3, collisions: 0, source: "materials" });
    expect(t.message).toBe("Renamed 3 material(s).");
    expect(t.variant).toBe("success");
  });

  it("collisions > 0 appends the duplicate suffix and goes warn (the artist should notice)", () => {
    const t = renameToast("objects", { ok: true, renamed: 5, collisions: 2, source: "objects" });
    expect(t.message).toBe("Renamed 5 object(s). (2 duplicate result(s))");
    expect(t.variant).toBe("warn");
  });

  it("no_selection → actionable copy", () => {
    const t = renameToast("objects", { ok: false, error: "no_selection" });
    expect(t.message).toBe("Select something to rename first.");
    expect(t.variant).toBe("warn");
  });

  it("nothing_to_do → actionable copy", () => {
    const t = renameToast("materials", { ok: false, error: "nothing_to_do" });
    expect(t.message).toBe("Fill in at least one rename field.");
    expect(t.variant).toBe("warn");
  });

  it("unknown error (bad_source / network) → generic warn", () => {
    const t = renameToast("objects", { ok: false, error: "bad_source" });
    expect(t.message).toBe("Couldn't rename.");
    expect(t.variant).toBe("warn");
  });
});
