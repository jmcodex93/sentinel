import type {
  PanelNotesBlock,
  PanelVersionBlock,
  PanelVersionEntry,
} from "../types";

// Filter tokens mirror versioning.py: FILTER_ALL = "__ALL__", and "" is the
// real WIP status token (an unlabeled save), NOT "no filter".
export const FILTER_ALL = "__ALL__";
export const RECENT_FILTERS: { value: string; label: string }[] = [
  { value: FILTER_ALL, label: "All" },
  { value: "", label: "WIP" },
  { value: "TR", label: "TR" },
  { value: "CR", label: "CR" },
  { value: "FINAL", label: "FINAL" },
];

/** Version card status line. `null` block → distinct "unavailable" note
 * (the read failed in isolation) vs. an unsaved doc or a saved doc with no
 * versions yet. A blank status renders as WIP (its real filename suffix is
 * "" — see versioning.parse_version_filename). */
export function versionStatusLine(block: PanelVersionBlock | null): string {
  if (block === null) return "Version status unavailable.";
  if (block.last === null) {
    if (block.unsaved) return "Scene not saved yet.";
    return "No versions yet — click Save Version.";
  }
  const v = `v${String(block.last.version).padStart(3, "0")}`;
  const status = block.last.status || "WIP";
  const parts = [`${v} ${status}`];
  if (block.last.age) parts.push(block.last.age);
  if (block.last.qc_label) parts.push(`QC ${block.last.qc_label}`);
  return parts.join(" · ");
}

/** Notes card status line — the engine's summary, with a ⚠ prefix when
 * there are pending TODOs (matches the native panel caption). */
export function notesStatusLine(block: PanelNotesBlock | null): string {
  if (block === null) return "Notes status unavailable.";
  return block.todos_pending > 0 ? `⚠ ${block.summary}` : block.summary;
}

/** Filter Recent Versions by status token, client-side (no round-trip),
 * mirroring versioning.filter_versions_by_status: FILTER_ALL passes all,
 * "" matches only the WIP (blank) status, anything else matches exactly. */
export function filterRecent(
  recent: PanelVersionEntry[],
  filter: string,
): PanelVersionEntry[] {
  if (filter === FILTER_ALL) return recent;
  return recent.filter((r) => (r.status || "") === filter);
}

/** Status → badge tone token. Known review statuses map 1:1; any custom
 * status (e.g. "REV02") falls back to the neutral WIP tone. Tones are
 * status tokens, never the accent. */
export function statusBadgeTone(status: string): "wip" | "tr" | "cr" | "final" {
  switch ((status || "").toUpperCase()) {
    case "TR":
      return "tr";
    case "CR":
      return "cr";
    case "FINAL":
      return "final";
    default:
      return "wip";
  }
}
