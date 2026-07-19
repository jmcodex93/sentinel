import { Loader2 } from "lucide-react";
import { Button } from "./Button";

interface SubmitBarProps {
  onSubmit: () => void;
  onCancel?: () => void;
  pending?: boolean;
  disabled?: boolean;
  submitLabel?: string;
  cancelLabel?: string;
  /** Submit-level error (as opposed to a per-field `FieldRow` error), e.g. a
   * server rejection that isn't tied to one specific input. */
  error?: string | null;
}

/** Footer action bar for a form page — primary submit + optional cancel.
 * Pending disables both buttons and shows a spinner on submit; every form
 * page (Save Version, Notes, Settings) ends its layout with one of these. */
export function SubmitBar({
  onSubmit,
  onCancel,
  pending = false,
  disabled = false,
  submitLabel = "Save",
  cancelLabel = "Cancel",
  error,
}: SubmitBarProps) {
  return (
    <div
      className="flex flex-col gap-2 border-t px-4 py-3"
      style={{ borderColor: "var(--color-hairline-strong)", backgroundColor: "var(--color-surface-1)" }}
    >
      {error && (
        <p className="text-caption" style={{ color: "var(--color-status-fail)" }}>
          {error}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </Button>
        )}
        <Button variant="primary" onClick={onSubmit} disabled={pending || disabled}>
          {pending && <Loader2 className="animate-spin" size={14} strokeWidth={2.25} aria-hidden="true" />}
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}
