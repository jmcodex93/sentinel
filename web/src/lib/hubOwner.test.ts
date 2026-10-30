import { describe, expect, it, vi } from "vitest";
import { noticeGate, selectOwner, type OwnerDeps } from "./hubOwner";

/** Fake Hub channel: `stamps` is what the server answers per call. */
function deps(answers: Array<{ ok: boolean; stamp?: string; error?: string }>, opts: { refreshed?: boolean } = {}) {
  let stamp: string | null = "S1";
  const calls: string[] = [];
  const d: OwnerDeps = {
    currentStamp: () => stamp,
    select: vi.fn(async (_key: string, expected: string) => {
      calls.push(expected);
      return answers.shift() ?? { ok: false, error: "scene_changed" };
    }),
    acknowledge: vi.fn((next: string) => {
      stamp = next;
    }),
    refresh: vi.fn(async () => {
      if (opts.refreshed === false) return false;
      stamp = "S2";
      return true;
    }),
  };
  return { d, calls };
}

describe("selectOwner (W8 follow-up, Windows round 7)", () => {
  it("selects with the known stamp and acknowledges the answer", async () => {
    const { d, calls } = deps([{ ok: true, stamp: "S1b" }]);
    expect(await selectOwner("k", d)).toBeNull();
    expect(calls).toEqual(["S1"]);
    expect(d.acknowledge).toHaveBeenCalledWith("S1b", "S1");
    expect(d.refresh).not.toHaveBeenCalled();
  });

  it("refreshes quietly on scene_changed and retries once with the new stamp", async () => {
    const { d, calls } = deps([{ ok: false, error: "scene_changed" }, { ok: true, stamp: "S2b" }]);
    expect(await selectOwner("k", d)).toBeNull();
    expect(calls).toEqual(["S1", "S2"]);
    expect(d.refresh).toHaveBeenCalledTimes(1);
  });

  it("says the scene is still updating when the retry also races a change", async () => {
    const { d, calls } = deps([{ ok: false, error: "scene_changed" }, { ok: false, error: "scene_changed" }]);
    expect(await selectOwner("k", d)).toEqual({
      message: "The scene is still updating — click the row again in a moment.",
      variant: "info",
    });
    expect(calls).toEqual(["S1", "S2"]);
  });

  it("retries with the row's current key when the refresh renamed it (R4, round 8)", async () => {
    const { d } = deps([{ ok: false, error: "scene_changed" }, { ok: true, stamp: "S2b" }]);
    d.currentKey = (key) => (key === "tex/a.png" ? "lib/a.png" : key);
    expect(await selectOwner("tex/a.png", d)).toBeNull();
    expect(vi.mocked(d.select).mock.calls.map(([key]) => key)).toEqual(["tex/a.png", "lib/a.png"]);
  });

  it("does not retry when the refresh was held back (staged changes)", async () => {
    const { d, calls } = deps([{ ok: false, error: "scene_changed" }], { refreshed: false });
    expect(await selectOwner("k", d)).toBeNull();
    expect(calls).toEqual(["S1"]);
  });

  it("never shows a raw error code", async () => {
    const { d } = deps([{ ok: false, error: "unknown key" }]);
    expect(await selectOwner("k", d)).toEqual({
      message: "That asset is no longer in the scene.",
      variant: "warn",
    });
    const other = deps([{ ok: false, error: "no_document" }]);
    expect(await selectOwner("k", other.d)).toEqual({ message: "Couldn't select the owner.", variant: "warn" });
  });

  it("does nothing without a loaded snapshot", async () => {
    const { d } = deps([]);
    d.currentStamp = () => null;
    expect(await selectOwner("k", d)).toBeNull();
    expect(d.select).not.toHaveBeenCalled();
  });
});

describe("noticeGate (R4, Windows round 8)", () => {
  const settling = { message: "The scene is still updating — click the row again in a moment.", variant: "info" as const };

  it("shows a repeated notice once per window, not once per click", () => {
    let now = 0;
    const gate = noticeGate(5000, () => now);
    expect(gate(settling)).toBe(settling);
    now = 300;
    expect(gate(settling)).toBeNull();
    now = 4999;
    expect(gate(settling)).toBeNull();
    now = 5000;
    expect(gate(settling)).toBe(settling);
  });

  it("lets a different notice through and passes null along", () => {
    let now = 0;
    const gate = noticeGate(5000, () => now);
    const gone = { message: "That asset is no longer in the scene.", variant: "warn" as const };
    expect(gate(settling)).toBe(settling);
    now = 100;
    expect(gate(gone)).toBe(gone);
    expect(gate(null)).toBeNull();
  });
});
