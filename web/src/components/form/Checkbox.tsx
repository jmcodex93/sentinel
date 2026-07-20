interface CheckboxProps {
  id?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

/** A labeled checkbox — native input (cross-platform-reliable inside a C4D
 * webview) with the primary accent color, per DESIGN.md's "accent reserved
 * for interaction" rule (a checked box is a selection, not a status). */
export function Checkbox({ id, checked, onChange, label, disabled = false }: CheckboxProps) {
  return (
    <label
      htmlFor={id}
      className="text-body flex w-fit cursor-pointer items-center gap-2"
      style={{ color: disabled ? "var(--color-muted)" : "var(--color-ink)" }}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded-sm"
        style={{ accentColor: "var(--color-primary)" }}
      />
      {label}
    </label>
  );
}
