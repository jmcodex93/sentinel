import { useState } from "react";
import { Button } from "../form/Button";
import { FieldRow } from "../form/FieldRow";
import { TextArea } from "../form/TextArea";
import { TextInput } from "../form/TextInput";
import { cardActions } from "../../lib/panelQc";
import type { PaletteAction, PanelQcCheck } from "../../types";

/** `check.new`/`check.accepted` are baseline-aware and `null` with no active
 * baseline (see PanelQcCheck) — render the legacy `count` alone rather than
 * a misleading "null new". */
function countLabel(check: PanelQcCheck): string {
  if (check.new === null) {
    return `${check.count}`;
  }
  if (check.accepted && check.accepted > 0) {
    return `${check.new} new (${check.accepted} accepted)`;
  }
  return `${check.new} new`;
}

/** One FAIL/WARN card — "option C refinada" from the approved mockup
 * (.superpowers/brainstorm/40035-1784707797/content/qc-list.html): severity
 * tint, label + count, a 1-2 line detail, and per-card actions (Select /
 * Fix / Info / Accept…) driven by `cardActions` (can_select/can_fix from
 * `CHECK_REGISTRY`, Info/Accept always available). No popups — Info toggles
 * the full `detail` list inline, Accept opens an inline author+reason form. */
export function QcCard({
  check,
  fixAction,
  artistName,
  busy,
  onSelect,
  onFix,
  onAccept,
}: {
  check: PanelQcCheck;
  /** The `PALETTE_ACTIONS` entry matching `check.fix_action_id`, or `null`
   * if this check has no Quick Fix action or the palette snapshot hasn't
   * loaded it (yet) — either way Fix renders disabled rather than crashing. */
  fixAction: PaletteAction | null;
  artistName: string;
  /** True while ANY qc mutation is in flight (single lock across the whole
   * section, same idiom as OverviewCards' `busyFix`) — disables every
   * button on every card so a second click can't race the first. */
  busy: boolean;
  onSelect: () => void;
  onFix: () => void;
  onAccept: (author: string, reason: string) => Promise<{ ok: boolean; error?: string }>;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [author, setAuthor] = useState(artistName);
  const [reason, setReason] = useState("");
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const actions = cardActions(check);
  const tintColor = check.severity === "FAIL" ? "var(--color-status-fail)" : "var(--color-status-warn)";
  const borderColor =
    check.severity === "FAIL"
      ? "color-mix(in srgb, var(--color-status-fail) 45%, var(--color-hairline))"
      : "color-mix(in srgb, var(--color-status-warn) 30%, var(--color-hairline))";
  const backgroundColor =
    check.severity === "FAIL"
      ? "color-mix(in srgb, var(--color-status-fail) 8%, var(--color-surface-1))"
      : "color-mix(in srgb, var(--color-status-warn) 5%, var(--color-surface-1))";

  function openAccept() {
    setAcceptError(null);
    setAuthor(artistName);
    setReason("");
    setAcceptOpen(true);
  }

  async function confirmAccept() {
    setAcceptError(null);
    if (!author.trim()) {
      setAcceptError("Author is required.");
      return;
    }
    if (!reason.trim()) {
      setAcceptError("Reason is required.");
      return;
    }
    setSubmitting(true);
    const response = await onAccept(author.trim(), reason.trim());
    setSubmitting(false);
    if (!response.ok) {
      setAcceptError(response.error || "Accept failed.");
      return;
    }
    setAcceptOpen(false);
  }

  return (
    <div className="rounded-lg border p-3" style={{ borderColor, backgroundColor }}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-label" style={{ color: tintColor }}>
          {check.severity === "FAIL" ? "✗" : "⚠"} {check.label} · {countLabel(check)}
        </p>
        <button
          type="button"
          onClick={() => setInfoOpen((v) => !v)}
          className="text-caption shrink-0"
          style={{ color: "var(--color-ink-secondary)" }}
        >
          {infoOpen ? "▾" : "▸"} Info
        </button>
      </div>

      {check.detail.length > 0 && (
        <p className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
          {check.detail[0]}
        </p>
      )}
      {infoOpen && check.detail.length > 1 && (
        <ul className="mt-1 list-inside list-disc">
          {check.detail.slice(1).map((line, index) => (
            <li key={index} className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
              {line}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {actions.select && (
          <button
            type="button"
            onClick={onSelect}
            disabled={busy}
            className="text-caption disabled:cursor-not-allowed disabled:opacity-50"
            style={{ color: "var(--color-primary)" }}
          >
            Select
          </button>
        )}
        {actions.fix && (
          <button
            type="button"
            onClick={onFix}
            disabled={busy || !fixAction || !fixAction.enabled}
            title={fixAction && !fixAction.enabled ? fixAction.reason || undefined : undefined}
            className="text-caption disabled:cursor-not-allowed disabled:opacity-50"
            style={{ color: "var(--color-primary)" }}
          >
            Fix
          </button>
        )}
        <button
          type="button"
          onClick={acceptOpen ? () => setAcceptOpen(false) : openAccept}
          disabled={busy}
          className="text-caption disabled:cursor-not-allowed disabled:opacity-50"
          style={{ color: "var(--color-primary)" }}
        >
          Accept…
        </button>
      </div>

      {acceptOpen && (
        <div
          className="mt-2 flex flex-col gap-2 rounded-md border p-2"
          style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-2)" }}
        >
          <FieldRow label="Author" htmlFor={`qc-accept-author-${check.id}`}>
            <TextInput
              id={`qc-accept-author-${check.id}`}
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="Your name"
            />
          </FieldRow>
          <FieldRow label="Reason" htmlFor={`qc-accept-reason-${check.id}`} error={acceptError}>
            <TextArea
              id={`qc-accept-reason-${check.id}`}
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this acceptable?"
            />
          </FieldRow>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={submitting} onClick={() => setAcceptOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={submitting || busy} onClick={confirmAccept}>
              Confirm Accept
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
