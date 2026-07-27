import { describe, it, expect } from "vitest";
import { assetStatusTone, hubAssetStatusTone } from "./status";

describe("assetStatusTone", () => {
  it("maps Delivery asset statuses to health tones", () => {
    expect(assetStatusTone("collected")).toBe("pass");
    expect(assetStatusTone("missing")).toBe("fail");
    expect(assetStatusTone("external")).toBe("warn");
  });
});

describe("hubAssetStatusTone", () => {
  it("maps Hub asset statuses to health tones (mirrors HubAssetsTable STATUS_META chroma)", () => {
    expect(hubAssetStatusTone("ok")).toBe("pass");
    expect(hubAssetStatusTone("missing")).toBe("fail");
    expect(hubAssetStatusTone("absolute")).toBe("warn");
    expect(hubAssetStatusTone("empty")).toBe("warn");
    expect(hubAssetStatusTone("asset_uri")).toBe("neutral");
  });
});
