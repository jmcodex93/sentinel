import { useEffect, useState } from "react";
import { switchTargets } from "../../lib/hubTable";
import { Button } from "../form/Button";
import type { HubVariant } from "../../types";

/** Confirmation dialog for the Hub's "Switch res..." toolbar action (Task 3,
 * fase 5.3 — `docs/superpowers/plans/2026-07-21-hub-variants.md`). Same
 * pattern as `HubShrinkDialog`: the target list + "X/N available" counters
 * are computed client-side via the pure `switchTargets`, purely informative
 * — `hub/switch_res` recomputes the authoritative sibling groups against a
 * fresh scan regardless, so a stale/partial client snapshot never causes a
 * wrong write, only a possibly-stale count shown before the artist
 * confirms. Switch is relink-only (no file writes) — that, plus a single
 * Cmd+Z reverting the whole batch, is the entire safety story; there is no
 * further server-side confirm step. Escape closes without side effects. */
export function HubSwitchResDialog({
  selectedKeys,
  variants,
  busy,
  onConfirm,
  onClose,
}: {
  selectedKeys: Set<string>;
  variants: Record<string, HubVariant[]>;
  busy: boolean;
  onConfirm: (target: number | "highest") => void;
  onClose: () => void;
}) {
  const { targets, total } = switchTargets(selectedKeys, variants);
  const [target, setTarget] = useState<number | "highest">(targets[0]?.px ?? "highest");

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const selectedTarget = targets.find((t) => t.px === target);

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.5)" }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="hub-switch-res-dialog-title"
        className="flex w-full max-w-md flex-col gap-4 rounded-lg border p-5"
        style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline-strong)" }}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="hub-switch-res-dialog-title" className="text-title" style={{ color: "var(--color-ink)" }}>
          Switch resolution
        </h2>

        {targets.length === 0 ? (
          <p className="text-body" style={{ color: "var(--color-ink-secondary)" }}>
            None of the selected rows have another resolution on disk.
          </p>
        ) : (
          <fieldset className="flex flex-col gap-2">
            <legend className="text-label mb-1" style={{ color: "var(--color-ink-secondary)" }}>
              Target
            </legend>
            {targets.map((t) => (
              <label
                key={String(t.px)}
                className="flex items-center gap-2 text-body"
                style={{ color: "var(--color-ink)" }}
              >
                <input
                  type="radio"
                  name="hub-switch-res-target"
                  value={String(t.px)}
                  checked={target === t.px}
                  onChange={() => setTarget(t.px)}
                />
                {t.label}
                <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  {t.available}/{total} available
                </span>
              </label>
            ))}
          </fieldset>
        )}

        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Relinks each texture to an existing sibling file next to it — never writes or generates new files. A
          single Cmd+Z reverts the batch.
        </p>

        <div className="flex justify-end gap-2">
          <Button variant="secondary" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={busy || !selectedTarget || selectedTarget.available === 0}
            onClick={() => onConfirm(target)}
          >
            Switch {selectedTarget && selectedTarget.available > 0 ? `(${selectedTarget.available})` : ""}
          </Button>
        </div>
      </div>
    </div>
  );
}
