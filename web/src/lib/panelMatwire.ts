import type { MatwireCreateResult } from "../types";

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
