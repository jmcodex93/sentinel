import { useEffect, useState } from "react";
import { formatBytes } from "../../lib/format";
import { shrinkPreview } from "../../lib/hubTable";
import { Button } from "../form/Button";
import type { HubAsset, HubMeta } from "../../types";

const TARGETS: { value: number; label: string }[] = [
  { value: 4096, label: "4K (4096px)" },
  { value: 2048, label: "2K (2048px)" },
  { value: 1024, label: "1K (1024px)" },
];

/** Confirmation dialog for the Hub's "Shrink…" toolbar action (Task 4,
 * `docs/superpowers/plans/2026-07-21-hub-optimize.md`). The preview shown
 * here (eligible count, skipped count, VRAM before→after) is computed
 * client-side via `shrinkPreview` — a pure mirror of the server's
 * `assets.shrink_plan` — purely informative: `hub/shrink_start` recomputes
 * the authoritative plan against a fresh scan regardless, so a stale/partial
 * client snapshot never causes a wrong write, only a possibly-stale count
 * shown before the artist confirms. Shrink NEVER overwrites originals — it
 * writes sibling `_4K`/`_2K`/`_1K` copies and relinks to those — so this
 * dialog's confirm gesture is the whole safety story; there is no further
 * server-side confirm step. Escape closes without side effects. */
export function HubShrinkDialog({
  assets,
  metas,
  selectedKeys,
  busy,
  onConfirm,
  onClose,
}: {
  assets: HubAsset[];
  metas: Record<string, HubMeta>;
  selectedKeys: Set<string>;
  busy: boolean;
  onConfirm: (targetPx: number) => void;
  onClose: () => void;
}) {
  const [targetPx, setTargetPx] = useState(2048);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const preview = shrinkPreview(assets, metas, selectedKeys, targetPx);
  const vramSaved = preview.vramBefore - preview.vramAfter;

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
        aria-labelledby="hub-shrink-dialog-title"
        className="flex w-full max-w-md flex-col gap-4 rounded-lg border p-5"
        style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline-strong)" }}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="hub-shrink-dialog-title" className="text-title" style={{ color: "var(--color-ink)" }}>
          Shrink textures
        </h2>

        <fieldset className="flex flex-col gap-2">
          <legend className="text-label mb-1" style={{ color: "var(--color-ink-secondary)" }}>
            Target size
          </legend>
          {TARGETS.map((target) => (
            <label key={target.value} className="flex items-center gap-2 text-body" style={{ color: "var(--color-ink)" }}>
              <input
                type="radio"
                name="hub-shrink-target"
                value={target.value}
                checked={targetPx === target.value}
                onChange={() => setTargetPx(target.value)}
              />
              {target.label}
            </label>
          ))}
        </fieldset>

        <div
          className="flex flex-col gap-1 rounded-md px-3 py-2"
          style={{ backgroundColor: "var(--color-surface-2)" }}
        >
          <p className="text-body" style={{ color: "var(--color-ink)" }}>
            {preview.eligible.length} to shrink
            {preview.skipped.length > 0 ? ` · ${preview.skipped.length} skipped` : ""}
          </p>
          {preview.eligible.length > 0 && (
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
              VRAM {formatBytes(preview.vramBefore)} → {formatBytes(preview.vramAfter)}
              {vramSaved > 0 ? ` (−${formatBytes(vramSaved)})` : ""}
            </p>
          )}
        </div>

        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Writes new sibling files next to the originals and relinks to them — originals are never overwritten. A
          single Cmd+Z reverts the relink.
        </p>

        <div className="flex justify-end gap-2">
          <Button variant="secondary" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={busy || preview.eligible.length === 0} onClick={() => onConfirm(targetPx)}>
            Shrink {preview.eligible.length > 0 ? `(${preview.eligible.length})` : ""}
          </Button>
        </div>
      </div>
    </div>
  );
}
