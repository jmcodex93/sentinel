import { describe, expect, it } from "vitest";
import { confirmBarButtons } from "./confirmBar";

/** The confirm bar's whole policy: what the buttons say, which one is red,
 * and which one sits in the position the artist reaches for by habit. */
describe("confirmBarButtons", () => {
  it("shows the server's verb on the confirm button", () => {
    const buttons = confirmBarButtons({ confirmVerb: "Delete materials", destructive: true });
    const confirm = buttons.find((b) => b.role === "confirm");
    expect(confirm?.label).toBe("Delete materials");
  });

  it("falls back to Confirm when the server sends no verb", () => {
    for (const verb of [undefined, null, "", "   "]) {
      const buttons = confirmBarButtons({ confirmVerb: verb });
      expect(buttons.find((b) => b.role === "confirm")?.label).toBe("Confirm");
    }
  });

  it("uses the destructive variant only when the server says destructive", () => {
    expect(confirmBarButtons({ confirmVerb: "Delete materials", destructive: true })
      .find((b) => b.role === "confirm")?.variant).toBe("destructive");
    // Same verb, not flagged: the bar is shared by three gates and must not
    // turn red on its own.
    expect(confirmBarButtons({ confirmVerb: "Delete materials", destructive: false })
      .find((b) => b.role === "confirm")?.variant).toBe("primary");
    expect(confirmBarButtons({ confirmVerb: "Delete materials" })
      .find((b) => b.role === "confirm")?.variant).toBe("primary");
  });

  it("keeps a destructive confirm out of the last (primary-habit) slot", () => {
    const destructive = confirmBarButtons({ confirmVerb: "Delete materials", destructive: true });
    expect(destructive.map((b) => b.role)).toEqual(["confirm", "cancel"]);
    expect(destructive[destructive.length - 1].role).toBe("cancel");

    // Innocuous gates keep the familiar Cancel · Confirm order.
    const safe = confirmBarButtons({ confirmVerb: "Apply", destructive: false });
    expect(safe.map((b) => b.role)).toEqual(["cancel", "confirm"]);
  });

  it("always offers exactly one confirm and one cancel", () => {
    for (const destructive of [true, false]) {
      const buttons = confirmBarButtons({ confirmVerb: "Do it", destructive });
      expect(buttons.filter((b) => b.role === "confirm")).toHaveLength(1);
      expect(buttons.filter((b) => b.role === "cancel")).toHaveLength(1);
      expect(buttons.find((b) => b.role === "cancel")?.label).toBe("Cancel");
      expect(buttons.find((b) => b.role === "cancel")?.variant).toBe("secondary");
    }
  });
});
