/**
 * Confirm-bar button policy — the whole decision behind the panel's three
 * confirm gates (Overview's `confirmAction`, QC's `qcConfirm`, Render's
 * `confirmLabel`), kept pure so it is testable without a DOM: `ConfirmBar`
 * only maps the descriptors this returns onto `<Button>`s.
 *
 * Two rules from the destructive-action audit (tfmstyle UX Handbook,
 * *Design Destructive Actions to Prevent Mistakes*):
 *
 * 1. The confirm button says the ACTION, not "yes". The verb comes from the
 *    server (`confirm_verb`, next to `confirm_label`) because the server is
 *    what knows the consequence; a missing verb falls back to "Confirm" so
 *    no button is ever left mute.
 * 2. A destructive confirm does NOT sit in the primary slot. The order is
 *    swapped (destructive first, safe last) so the rightmost button — the
 *    one a hand reaches for out of position habit, since that is where the
 *    panel accepts every innocuous thing — is the one that changes nothing.
 *    The destructive button stays perfectly reachable; it just stops being
 *    the one you hit by muscle memory.
 *
 * `destructive` is likewise server-owned (never inferred client-side), so
 * the shared bar can't turn an innocuous gate red by accident.
 */

export interface ConfirmBarButtonSpec {
  /** Which callback the button fires — `ConfirmBar` maps this, never the
   * position, so a re-order can't silently swap the handlers. */
  role: "confirm" | "cancel";
  label: string;
  variant: "primary" | "secondary" | "destructive";
}

export const CONFIRM_FALLBACK_VERB = "Confirm";

/** Left-to-right button list for a confirm bar. */
export function confirmBarButtons(options: {
  confirmVerb?: string | null;
  destructive?: boolean;
}): ConfirmBarButtonSpec[] {
  const verb = options.confirmVerb?.trim() ? options.confirmVerb.trim() : CONFIRM_FALLBACK_VERB;
  const cancel: ConfirmBarButtonSpec = { role: "cancel", label: "Cancel", variant: "secondary" };

  if (options.destructive) {
    // Destructive out of the primary (rightmost) slot — see rule 2 above.
    return [{ role: "confirm", label: verb, variant: "destructive" }, cancel];
  }
  return [cancel, { role: "confirm", label: verb, variant: "primary" }];
}
