import type { StatusTone } from "../components/StatusMark";
import type { AssetStatus, HubAssetStatus } from "../types";

/** Delivery Summary asset status → health tone. */
export function assetStatusTone(status: AssetStatus): StatusTone {
  switch (status) {
    case "collected": return "pass";
    case "missing": return "fail";
    case "external": return "warn";
  }
}

/** Hub asset status → health tone. Mirrors the chroma HubAssetsTable's
 * STATUS_META already used (missing→fail, absolute/empty→warn,
 * asset_uri→neutral, ok→pass). */
export function hubAssetStatusTone(status: HubAssetStatus): StatusTone {
  switch (status) {
    case "ok": return "pass";
    case "missing": return "fail";
    case "absolute": return "warn";
    case "empty": return "warn";
    case "asset_uri": return "neutral";
  }
}
