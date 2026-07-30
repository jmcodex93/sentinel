import type { MatwireCreateResult } from "../types";

/** Human labels for the engine's ignored-file reasons — pinned COMPLETE
 * against every reason plugin/sentinel/matwire.py can emit (the
 * panelMatwire.test.ts completeness pin is the tripwire when the engine
 * grows one). Labels are short fragments rendered after the filename:
 * `file.png — lower resolution`. */
export const IGNORED_REASON_LABELS: Record<string, string> = {
  lower_resolution: "lower resolution",
  duplicate_channel: "duplicate channel",
  packed_orm: "packed ORM/ARM (v2)",
  pbr_wins: "PBR maps take precedence",
  dx_superseded: "GL normal preferred",
  no_channel: "unrecognized",
  bad_extension: "not an image",
};

export function ignoredReasonLabel(reason: string): string {
  return IGNORED_REASON_LABELS[reason] ?? reason;
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
