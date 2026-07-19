import type { ReactNode } from "react";

interface FieldRowProps {
  label: string;
  htmlFor?: string;
  /** Field-level validation error — shown in `{colors.status-fail}` under
   * the control, replacing `hint` when present. This is the "errors inline
   * under the field, never a popup" surface the Phase 4 plan calls for. */
  error?: string | null;
  /** Static caption shown under the control when there is no error. */
  hint?: string;
  children: ReactNode;
}

/** One labeled form field — label, control, and an inline error/hint line.
 * The one primitive every form page's fields are built from (Save Version's
 * comment, Notes' TODO list wrapper, Settings' every field, Gate's
 * author/reason). */
export function FieldRow({ label, htmlFor, error, hint, children }: FieldRowProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-caption" style={{ color: "var(--color-status-fail)" }}>
          {error}
        </p>
      ) : hint ? (
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
