import { useEffect, useState } from "react";
import { Button } from "./form/Button";
import { confirmBarButtons } from "../lib/confirmBar";

/** Inline confirm bar — the shared shell behind the panel's three confirm
 * gates (Overview's `confirmAction`, QC's `qcConfirm`, Render's
 * `confirmLabel`): one layout, only the copy, the destructive flag and the
 * callbacks differ. Which buttons exist, what they say and in what order
 * is `lib/confirmBar.ts` (pure, tested); this file is the shell.
 * Extracted here (Task 5, panel polish) so the mount
 * glide + floating shadow are authored once instead of three times.
 * Mounts with a fade + small `translateY` glide (same `entered`-one-frame-
 * after-mount idiom as `Toast.tsx`) since the bar floats in over existing
 * content rather than always being there — `boxShadow: var(--shadow-float)`
 * matches that "floats over" reading. Behavior (Cancel/Confirm wiring,
 * disabled state) is unchanged from the three inline blocks this replaces. */
export function ConfirmBar({
  label,
  confirmVerb,
  destructive,
  busy,
  onConfirm,
  onCancel,
  className,
}: {
  label: string;
  /** What the confirm button says — the server's `confirm_verb`. Absent
   * (an older action, or a route that never learned to send one) falls
   * back to "Confirm": never a mute button, never SPA-invented copy. */
  confirmVerb?: string | null;
  /** Server-owned (`destructive` in the confirm contract). Drives the red
   * variant AND the button order — see `lib/confirmBar.ts`. */
  destructive?: boolean;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  className?: string;
}) {
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      className={`flex flex-wrap items-center gap-2 rounded-lg border p-3 transition-[opacity,transform] ease-[var(--ease-glide)] ${className ?? ""}`}
      style={{
        backgroundColor: "var(--color-surface-1)",
        borderColor: "var(--color-hairline)",
        boxShadow: "var(--shadow-float)",
        transitionDuration: "var(--motion-glide)",
        opacity: entered ? 1 : 0,
        transform: entered ? "translateY(0)" : "translateY(-4px)",
      }}
    >
      <span className="text-body" style={{ color: "var(--color-ink)" }}>
        {label}
      </span>
      <div className="ml-auto flex gap-2">
        {confirmBarButtons({ confirmVerb, destructive }).map((button) => (
          <Button
            key={button.role}
            variant={button.variant}
            disabled={busy}
            onClick={button.role === "confirm" ? onConfirm : onCancel}
          >
            {button.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
