import type { ReactNode } from "react";
import { useCallback, useRef, useState } from "react";
import type { ToastItem, ToastOptions } from "../lib/toast";
import { ToastContext } from "../lib/toast";
import { ToastStack } from "./Toast";

// DESIGN.md `toast.duration` — 4000ms auto-dismiss.
const AUTO_DISMISS_MS = 4000;
// DESIGN.md `motion.base` — the enter/exit transition itself (see Toast.tsx).
const EXIT_MS = 150;

let nextToastId = 0;

/** Wraps the app (or a single FormDialog page) so any descendant can call
 * `useToast().toast(...)` (lib/toast.ts) — renders the fixed bottom-right
 * stack itself, so callers never need to mount anything beyond this
 * provider once, near the root (see App.tsx). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, number>>(new Map());

  const clearTimer = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const remove = useCallback(
    (id: number) => {
      clearTimer(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
    },
    [clearTimer],
  );

  // Two-phase dismiss: flip `leaving` so Toast.tsx can animate out over
  // `{motion.base}` (150ms), then actually drop the item from the list.
  const dismiss = useCallback(
    (id: number) => {
      clearTimer(id);
      setItems((prev) => prev.map((item) => (item.id === id ? { ...item, leaving: true } : item)));
      window.setTimeout(() => remove(id), EXIT_MS);
    },
    [clearTimer, remove],
  );

  const toast = useCallback(
    ({ message, variant = "info" }: ToastOptions) => {
      const id = ++nextToastId;
      setItems((prev) => [...prev, { id, variant, message, leaving: false }]);
      const timer = window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
      timers.current.set(id, timer);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <ToastStack items={items} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}
