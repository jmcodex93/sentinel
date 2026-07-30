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
