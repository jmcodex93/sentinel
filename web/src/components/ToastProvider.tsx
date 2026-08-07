import type { ReactNode } from "react";
import { useCallback, useRef, useState } from "react";
import type { ToastItem, ToastOptions, ToastVariant } from "../lib/toast";
import { ToastContext } from "../lib/toast";
import { ToastStack } from "./Toast";

// How long a toast stays before dismissing itself, BY VARIANT. A success is
// a receipt — you glance at it and move on. A warn is the surface for "what
// you asked for did not fully happen, here is what to do instead" (the
// dialog-free Tools/QC copy: "Select one or more objects first"), so it has
// to survive being read by someone whose eyes are on the viewport, not on
// the panel. Hard failures are not here at all: they stay inline under the
// offending field (see lib/toast.ts — there is deliberately no error
// variant), which is the surface-follows-urgency rule already in the design.
const AUTO_DISMISS_MS: Record<ToastVariant, number> = {
  success: 4000,
  info: 4000,
  warn: 7000,
};
// Must match `--motion-exit`: this timer removes the item from the DOM and
// the CSS transition fades it out, so if the two disagree the toast either
// pops out mid-fade (timer shorter) or leaves a dead invisible node in the
// stack (timer longer). It used to be a hardcoded 150 against the 180ms the
// toast actually animated with — the first of those two failure modes.
const EXIT_MS = 160;

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
  // `--motion-exit`, then actually drop the item from the list.
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
      const timer = window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS[variant]);
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
