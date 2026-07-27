import { useEffect, useState } from "react";
import { Button } from "../form/Button";

/** Inline confirm bar — the shared shell behind the panel's three confirm
 * gates (Overview's `confirmAction`, QC's `qcConfirm`, Render's
 * `confirmLabel`): identical Cancel/Confirm layout, only the label and
 * callbacks differ. Extracted here (Task 5, panel polish) so the mount
 * glide + floating shadow are authored once instead of three times.
 * Mounts with a fade + small `translateY` glide (same `entered`-one-frame-
 * after-mount idiom as `Toast.tsx`) since the bar floats in over existing
 * content rather than always being there — `boxShadow: var(--shadow-float)`
 * matches that "floats over" reading. Behavior (Cancel/Confirm wiring,
 * disabled state) is unchanged from the three inline blocks this replaces. */
export function ConfirmBar({
  label,
  busy,
  onConfirm,
  onCancel,
  className,
}: {
  label: string;
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
        <Button variant="secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="primary" disabled={busy} onClick={onConfirm}>
          Confirm
        </Button>
      </div>
    </div>
  );
}
