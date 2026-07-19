import { createContext, useContext } from "react";

/** Sentinel toast variants — DESIGN.md's `toast` component is the default
 * surface for *results* (the anti-popup rule): success/info/warn map to the
 * three status colors that make sense for a completed action (there is no
 * "fail" toast variant — a hard failure keeps its inline `{error}` under the
 * offending field, per the Phase 4 plan's "errors inline, not popups"). */
export type ToastVariant = "success" | "info" | "warn";

export interface ToastOptions {
  message: string;
  variant?: ToastVariant;
}

export interface ToastItem {
  id: number;
  variant: ToastVariant;
  message: string;
  leaving: boolean;
}

export interface ToastContextValue {
  toast: (options: ToastOptions) => void;
}

// Split from the `ToastProvider` component (components/ToastProvider.tsx)
// so this file only exports non-component values — keeps react-refresh's
// only-export-components rule happy without a `type ToastVariant` -> JSX
// file mixing components and hooks/context.
export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}
