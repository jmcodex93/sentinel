import type { HubAsset } from "../types";

/** Mirror of AssetHubDialog._preview_bulk (dialogs.py:2158): literal
 * substring find/replace, case-insensitive by default. The replacement is a
 * function so `$&` etc. in the user's replace string stay literal — parity
 * with Python's `pattern.sub(lambda _m: repl, path)`. */
const ESCAPE_RE = /[.*+?^${}()|[\]\\]/g;

export function computeBulkChanges(
  assets: Pick<HubAsset, "key" | "path" | "status" | "repathable">[],
  find: string,
  replace: string,
  matchCase: boolean,
): Map<string, string> {
  const out = new Map<string, string>();
  if (!find) return out;
  const pattern = new RegExp(find.replace(ESCAPE_RE, "\\$&"), matchCase ? "g" : "gi");
  for (const asset of assets) {
    if (!asset.repathable || asset.status === "asset_uri" || asset.status === "empty") continue;
    const next = asset.path.replace(pattern, () => replace);
    if (next !== asset.path) out.set(asset.key, next);
  }
  return out;
}
