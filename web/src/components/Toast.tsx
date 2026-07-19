import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { ToastItem, ToastVariant } from "../lib/toast";

const VARIANT_ICON = {
  success: CheckCircle2,
  info: Info,
  warn: AlertTriangle,
} as const;

const VARIANT_COLOR: Record<ToastVariant, string> = {
  success: "var(--color-status-pass)",
  info: "var(--color-status-neutral)",
  warn: "var(--color-status-warn)",
};

/** One toast — DESIGN.md `toast` component: surface-2 background,
 * hairline-strong border, rounded-lg, body typography. Enter/exit animates
 * opacity + a small vertical offset over `{motion.base}` (150ms): `entered`
 * flips true one frame after mount (enter), `leaving` is set by the
 * provider before the item is actually removed (exit) — see lib/toast.tsx. */
function ToastRow({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const Icon = VARIANT_ICON[item.variant];
  const visible = entered && !item.leaving;

  return (
    <div
      role="status"
      className="flex w-80 items-start gap-2 rounded-lg border px-4 py-3 transition-[opacity,transform] ease-[var(--motion-easing)]"
      style={{
        backgroundColor: "var(--color-surface-2)",
        borderColor: "var(--color-hairline-strong)",
        transitionDuration: "var(--motion-base)",
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(8px)",
      }}
    >
      <Icon
        size={16}
        strokeWidth={2.25}
        style={{ color: VARIANT_COLOR[item.variant] }}
        aria-hidden="true"
        className="mt-0.5 shrink-0"
      />
      <p className="text-body flex-1" style={{ color: "var(--color-ink)" }}>
        {item.message}
      </p>
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss"
        className="shrink-0 rounded-sm p-0.5 transition-colors duration-100 ease-out hover:bg-[var(--color-surface-1)]"
      >
        <X size={14} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-hidden="true" />
      </button>
    </div>
  );
}

/** Fixed bottom-right stack, newest at the bottom — DESIGN.md "stacking
 * bottom-right". Mounted once by `ToastProvider`. */
export function ToastStack({ items, onDismiss }: { items: ToastItem[]; onDismiss: (id: number) => void }) {
  if (items.length === 0) return null;
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex flex-col gap-2">
      {items.map((item) => (
        <div key={item.id} className="pointer-events-auto">
          <ToastRow item={item} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  );
}
