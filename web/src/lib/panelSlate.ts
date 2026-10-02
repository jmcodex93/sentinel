import type { SlateSlotName, SlateStyle } from "../types";

/** Fields the slate can show, in menu order. Mirrors `slate.TOKENS`. */
export const SLATE_FIELDS: { token: string; label: string }[] = [
  { token: "shot", label: "Shot" },
  { token: "version", label: "Version" },
  { token: "status", label: "Status" },
  { token: "score", label: "QC score" },
  { token: "artist", label: "Artist" },
  { token: "date", label: "Date" },
  { token: "time", label: "Time" },
  { token: "frame", label: "Frame" },
  { token: "scene", label: "Scene" },
  { token: "take", label: "Take" },
  { token: "project", label: "Project" },
  { token: "camera", label: "Camera" },
  { token: "resolution", label: "Resolution" },
  { token: "view", label: "Colour view" },
  { token: "post", label: "RenderView post" },
];

export const SLATE_SLOTS: { slot: SlateSlotName; label: string }[] = [
  { slot: "left", label: "Left" },
  { slot: "center", label: "Centre" },
  { slot: "right", label: "Right" },
];

const LABELS: Record<string, string> = Object.fromEntries(SLATE_FIELDS.map((f) => [f.token, f.label]));

/** Chip text for a slot item: a lone token shows its label ("Shot"); text
 * with tokens shows them as ‹Label› inside the literal text. */
export function itemLabel(item: string): string {
  const lone = /^\{([a-z_]+)\}$/.exec(item);
  if (lone) return LABELS[lone[1]] ?? item;
  return item.replace(/\{([a-z_]+)\}/g, (_m, token: string) => `‹${LABELS[token] ?? token}›`);
}

/** True when the item is only a field (as opposed to literal text). */
export function isFieldItem(item: string): boolean {
  return /^\{[a-z_]+\}$/.test(item);
}

function withSlot(style: SlateStyle, slot: SlateSlotName, items: string[]): SlateStyle {
  return { ...style, slots: { ...style.slots, [slot]: items } };
}

export function addItem(style: SlateStyle, slot: SlateSlotName, item: string): SlateStyle {
  const text = item.trim();
  if (!text) return style;
  return withSlot(style, slot, [...style.slots[slot], text]);
}

export function removeItem(style: SlateStyle, slot: SlateSlotName, index: number): SlateStyle {
  return withSlot(style, slot, style.slots[slot].filter((_, i) => i !== index));
}

/** Move an item one place left (-1) or right (+1); out of range is a no-op. */
export function moveItem(style: SlateStyle, slot: SlateSlotName, index: number, delta: -1 | 1): SlateStyle {
  const items = [...style.slots[slot]];
  const target = index + delta;
  if (target < 0 || target >= items.length) return style;
  [items[index], items[target]] = [items[target], items[index]];
  return withSlot(style, slot, items);
}

export function sameSlate(a: { enabled: boolean; style: SlateStyle }, b: { enabled: boolean; style: SlateStyle }): boolean {
  return a.enabled === b.enabled && JSON.stringify(a.style) === JSON.stringify(b.style);
}

/** The default slate — kept in step with `slate.DEFAULT_STYLE`. */
export const DEFAULT_SLATE_STYLE: SlateStyle = {
  position: "below",
  slots: { left: ["{shot}", "{version}"], center: [], right: ["{artist}", "{date}", "{frame}"] },
  badge: true,
  size: 1.0,
  show_post: true,
};

export const SLATE_ERROR_COPY: Record<string, string> = {
  no_document: "Open a scene first.",
  unsaved: "Save the scene first: the slate is stored with the project's rules.",
  bad_style: "That slate setting is not valid.",
  needs_2025_2: "The slate preview needs Cinema 4D 2025.2 or newer.",
  preview_failed: "Could not draw the preview.",
  bad_folder: "That folder does not exist.",
  folder_out_of_reach: "Sentinel only reads rules from the scene's folder or up to three folders above it — pick one of those.",
  rules_unreadable: "The project's sentinel_rules.json can't be read, so it was not touched. Fix it first.",
  write_failed: "Could not write the project's rules.",
};
