import { describe, expect, it } from "vitest";
import { undoShortcut } from "./platform";

describe("undoShortcut", () => {
  it("says Cmd+Z only on a Mac", () => {
    expect(undoShortcut("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15")).toBe("Cmd+Z");
  });

  it("says Ctrl+Z on Windows and when the platform is unknown", () => {
    expect(undoShortcut("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0")).toBe("Ctrl+Z");
    expect(undoShortcut("")).toBe("Ctrl+Z");
  });
});
