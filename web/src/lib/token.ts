/** Capability token for the Sentinel local API (Block-1 hardening).
 *
 * The C4D dialog embeds `?token=<hex>` in the SPA URL. We read it once at
 * module load and echo it on every /api request via the
 * `X-Sentinel-Token` header (POST) or `?token=` query param (GET links).
 * Absent token = mock/dev mode (`?mock=1`) or a stale bookmark; the
 * server answers 401 and the SPA shows its normal error state.
 */
const TOKEN_PARAM = "token";

function readToken(): string {
  try {
    return new URLSearchParams(window.location.search).get(TOKEN_PARAM) ?? "";
  } catch {
    return "";
  }
}

export const apiToken: string = readToken();

/** Append the token as a query parameter for GET fetch URLs. */
export function withToken(path: string): string {
  if (!apiToken) return path;
  const joiner = path.includes("?") ? "&" : "?";
  return `${path}${joiner}${TOKEN_PARAM}=${encodeURIComponent(apiToken)}`;
}

/** Headers object carrying the token for POST fetch calls. */
export function tokenHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...extra,
  };
  if (apiToken) headers["X-Sentinel-Token"] = apiToken;
  return headers;
}
