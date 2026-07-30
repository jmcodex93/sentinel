import type { MatwireCreateResult, MatwireLeftoverRow } from "../types";

/** Human labels for the engine's ignored-file reasons — pinned COMPLETE
 * against every reason plugin/sentinel/matwire.py can emit (the
 * panelMatwire.test.ts completeness pin is the tripwire when the engine
 * grows one). Labels are short fragments rendered after the filename:
 * `file.png — lower resolution`. */
export const IGNORED_REASON_LABELS: Record<string, string> = {
  lower_resolution: "lower resolution",
  duplicate_channel: "duplicate channel",
  pbr_wins: "PBR maps take precedence",
  dx_superseded: "GL normal preferred",
  no_channel: "unrecognized",
  bad_extension: "not an image",
};

export function ignoredReasonLabel(reason: string): string {
  return IGNORED_REASON_LABELS[reason] ?? reason;
}

/** Display label for a channel row — engine keys pass through except the
 * packed map, which reads as what it is (v1.32.1). */
export function channelLabel(channel: string): string {
  return channel === "packed_orm" ? "ORM/ARM (packed)" : channel;
}

/** Suffix note for the packed ORM/ARM channel row — what the splitter
 * ACTUALLY feeds in this set. The list is server-derived
 * (`matwire.orm_contributions`, the same source as the writer's connect
 * pairs), so the note can't promise wiring the writer won't make: with
 * dedicated roughness AND metalness maps present the ORM degrades to a
 * bare unconnected sampler, and the row must say so (review I2). Returns
 * null for rows that carry no `contributes` (every non-ORM channel). */
export function packedOrmNote(contributes: string[] | undefined): string | null {
  if (!contributes) return null;
  if (contributes.length === 0) return "→ unconnected (dedicated maps win)";
  return `→ ${contributes.join(" + ")}`;
}

/** Truthful Create-button count (review M1): the server also creates the
 * catch-all `<root>_leftovers` material when leftover import is ON and at
 * least one unrecognized file matched no set — the button used to promise
 * only `included.length`. Zero included sets stays zero: the op returns
 * `no_sets` before creating anything, leftovers included. */
export function createMaterialCount(
  includedCount: number,
  importLeftovers: boolean,
  leftovers: MatwireLeftoverRow[],
): number {
  if (includedCount === 0) return 0;
  const hasUnassigned = importLeftovers && leftovers.some((row) => row.set === null);
  return includedCount + (hasUnassigned ? 1 : 0);
}

/** Checkbox copy for the opt-in leftover import — pinned in the vitest so
 * the guard and the message can't drift apart. */
export const MATWIRE_IMPORT_LEFTOVERS_LABEL = "Import unrecognized files";

/** Checkbox copy for the opt-in AO multiply. "DEDICATED" is load-bearing
 * (Task 1 review Minor): a set whose AO only exists inside a packed
 * ORM/ARM red channel is NOT touched by this toggle — the writer wires the
 * splitter's green/blue outputs and never the AO — so an unscoped
 * "Multiply AO into base color" would promise an effect that silently does
 * nothing on exactly the packs where it's easiest to assume otherwise. */
export const MATWIRE_MULTIPLY_AO_LABEL = "Multiply dedicated AO map into base color";

/** Where a set's AO map actually lands — a MIRROR of the engine's
 * `matwire.ao_destination` (three outcomes, same strings; the vitest pins
 * them). The mirror exists because the AO row must relabel the instant the
 * checkbox flips: the alternative, re-fetching the preview on every toggle,
 * re-seeds names/exclusions from the server scan and would throw away the
 * artist's edits. The server still stamps `destination` on the row from the
 * single source (the op takes `multiply_ao`) — this only keeps the on-screen
 * label live between fetches. */
export type AoDestination = "base_color_multiply" | "unconnected" | null;

export function aoDestination(channels: string[], multiplyAo: boolean): AoDestination {
  if (!channels.includes("ao")) return null;
  // An AO-only set has nothing to multiply INTO (a dangling color layer),
  // so the writer leaves the sampler loose — and so must the label.
  if (multiplyAo && channels.includes("basecolor")) return "base_color_multiply";
  return "unconnected";
}

/** Destination fragment rendered after the AO filename — the packedOrmNote
 * idiom, so a wired and an unwired AO never read the same. */
export function aoDestinationLabel(destination: AoDestination): string | null {
  if (destination === "base_color_multiply") return "→ base color (multiply)";
  if (destination === "unconnected") return "→ unconnected";
  return null;
}

/** Projection selector options. The VALUES are the op's accepted strings
 * (`matwire_c4d.PROJECTION_TYPES` — the op normalizes anything else to
 * "uv", so a drift here degrades quietly and the vitest pins them); the
 * labels are the RS node's own wording. */
export const PROJECTION_OPTIONS: { value: string; label: string }[] = [
  { value: "uv", label: "UV Channel" },
  { value: "triplanar", label: "Tri-Planar" },
];

export const MATWIRE_PROJECTION_UNAVAILABLE_COPY =
  "This Redshift build has no shared UV context node. Tiling still gets one control — a UniversalXform group — but Tri-Planar needs the context.";

/** Inline reason for the disabled Projection selector, or null when the
 * shared context node is available. A preview without the field (pre-v1.33
 * shape) counts as available: the honest degradation is server-reported,
 * never guessed from a missing key. */
export function projectionUnavailableNote(available: boolean | undefined): string | null {
  return available === false ? MATWIRE_PROJECTION_UNAVAILABLE_COPY : null;
}

/** The projection the material will ACTUALLY be wired with — what both the
 * create payload and the (disabled) selector must show. Without this a
 * Tri-Planar picked before the preview reported the node missing would stay
 * in state, ride along in the payload and keep the disabled control lit,
 * contradicting the degradation note right under it. Derived, never a
 * state mutation on render: the artist's pick survives if a later preview
 * reports the node present again. */
export function effectiveProjection(
  selected: string,
  unavailableNote: string | null,
): string {
  return unavailableNote === null ? selected : "uv";
}

/** Material type options. OpenPBR is FIRST because it is the default; the
 * values are the op's accepted strings (`matwire_c4d.MATERIAL_TYPES` — the
 * op normalizes anything else to the default, never raises). */
export const MATERIAL_OPTIONS: { value: string; label: string }[] = [
  { value: "openpbr", label: "OpenPBR" },
  { value: "standard", label: "Standard" },
];

export const MATWIRE_OPENPBR_UNAVAILABLE_COPY =
  "This Redshift build has no OpenPBR node — materials are built as Standard Surface.";

/** Inline reason for the disabled Material selector, or null when OpenPBR
 * is available. A preview without the field (pre-v1.34 shape) counts as
 * available: the degradation is server-reported, never guessed. */
export function openpbrUnavailableNote(
  available: boolean | undefined,
): string | null {
  return available === false ? MATWIRE_OPENPBR_UNAVAILABLE_COPY : null;
}

/** The material the writer will ACTUALLY build — what both the payload and
 * the (disabled) selector must show. Derived, never a state mutation on
 * render, so the artist's pick survives if a later preview reports the node
 * present again.
 *
 * Deliberately asymmetric with `effectiveProjection` (which collapses ANY
 * unavailable pick to "uv"): this only degrades `"openpbr"` specifically,
 * mirroring the server's `_matwire_material` (Task 3 review finding) —
 * `value if value != "openpbr" or openpbr_available() else "standard"`. A
 * future third `MATERIAL_TYPES` entry must pass through unharmed on a build
 * lacking the OpenPBR node; only "openpbr" itself is unavailable there. */
export function effectiveMaterial(
  selected: string,
  unavailableNote: string | null,
): string {
  return selected === "openpbr" && unavailableNote !== null ? "standard" : selected;
}

/** Destination fragment after a glossiness filename — a MIRROR of the
 * engine's `matwire.gloss_destination`, for the same reason the AO mirror
 * exists: the row must relabel the instant the selector flips, and
 * re-fetching the preview would discard the artist's name edits. */
export function glossDestinationLabel(
  channels: string[],
  material: string,
): string | null {
  if (!channels.includes("glossiness")) return null;
  return material === "standard"
    ? "→ roughness (glossiness mode)"
    : "→ specular roughness (inverted)";
}

/** Destination fragment rendered after a leftover filename: its assigned
 * set's material, or the catch-all `<root>_leftovers` material when no set
 * name prefixes the file (the server names it — the client only says
 * where the file is headed). */
export function leftoverDestination(set: string | null): string {
  return set === null ? "→ leftovers material" : `→ ${set}`;
}

/** Display label for a leftover row against the LOCAL `excluded` selection
 * state — not just the preview's raw assignment. A leftover assigned to a
 * set the artist has since excluded from Create is DROPPED by the server
 * (matwire_create only imports leftovers whose set exists in the create),
 * so showing its stale "→ <set>" arrow would tell the artist one outcome
 * while they get another. Unassigned leftovers (`set === null`) always go
 * to the catch-all `<root>_leftovers` material regardless of exclusions. */
export function leftoverDestinationLabel(
  row: MatwireLeftoverRow,
  excludedSet: Set<string>,
): string {
  if (row.set !== null && excludedSet.has(row.set)) {
    return "dropped (set excluded)";
  }
  return leftoverDestination(row.set);
}

/** Inline note for ruleset `matwire_suffixes` keys the engine rejected —
 * null when the ruleset is clean (the normal case renders nothing). */
export function suffixWarningsNote(warnings: string[] | undefined): string | null {
  if (!warnings || warnings.length === 0) return null;
  return `Ruleset matwire_suffixes: invalid key(s) ignored — ${warnings.join(", ")}`;
}

/** Create result → toast. Per-set failures still succeed as a batch
 * (`ok: true` with `errors` rows), but the toast goes WARN so the partial
 * outcome is noticed, not skimmed past — the renameToast collision idiom.
 * `nothing_selected` is a CLIENT-side state (the Create button is disabled
 * at zero included sets, so the op is never called with everything
 * excluded), but the copy stays here so the guard and the message can't
 * drift apart. */
export function matwireToast(
  r: MatwireCreateResult,
): { message: string; variant: "success" | "warn" } {
  if (!r.ok) {
    if (r.error === "no_sets") {
      return { message: "No texture sets recognized in that folder.", variant: "warn" };
    }
    if (r.error === "bad_folder") {
      return { message: "That folder doesn't exist.", variant: "warn" };
    }
    if (r.error === "redshift_unavailable") {
      return { message: "Redshift is not available.", variant: "warn" };
    }
    if (r.error === "nothing_selected") {
      return { message: "All sets are excluded.", variant: "warn" };
    }
    return { message: "Couldn't create materials.", variant: "warn" };
  }
  const failed = (r.errors ?? []).length;
  let message = `Created ${r.created ?? 0} RS material(s).`;
  if (failed > 0) {
    message += ` (${failed} set(s) failed)`;
    return { message, variant: "warn" };
  }
  return { message, variant: "success" };
}
