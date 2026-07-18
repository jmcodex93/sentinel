/**
 * Human-readable byte formatting — mirrors `format_size` in
 * plugin/sentinel/assets.py exactly (same thresholds, same rounding),
 * so a zip size reads identically whether it's shown by the native panel
 * or Sentinel Reports.
 */
export function formatBytes(nbytes: number | null | undefined): string {
  if (nbytes === null || nbytes === undefined) return "—";
  if (nbytes < 0) return "?";
  if (nbytes < 1024) return `${nbytes} B`;

  const units: Array<[string, number]> = [
    ["KB", 1024],
    ["MB", 1024 ** 2],
    ["GB", 1024 ** 3],
    ["TB", 1024 ** 4],
  ];

  for (const [unit, div] of units) {
    const val = nbytes / div;
    if (val < 1024 || unit === "TB") {
      // Special rule: GB/TB under 10 get 2 decimals.
      if ((unit === "GB" || unit === "TB") && val < 10) {
        return `${val.toFixed(2)} ${unit}`;
      }
      return val < 100 ? `${val.toFixed(1)} ${unit}` : `${val.toFixed(0)} ${unit}`;
    }
  }
  return `${nbytes} B`;
}

/** Manifest timestamps are plain "YYYY-MM-DD HH:MM:SS" strings, not ISO —
 * render as-is when unparseable rather than showing "Invalid Date". */
export function formatCollectedAt(raw: string): string {
  if (!raw) return "";
  const isoish = raw.includes("T") ? raw : raw.replace(" ", "T");
  const parsed = new Date(isoish);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
