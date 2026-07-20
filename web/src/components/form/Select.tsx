interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  id?: string;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
}

/** Native `<select>` styled to DESIGN.md tokens. Values are always strings
 * (native select semantics) — callers with a numeric field (fps, history
 * row count, ...) convert at the edge (`Number(value)`), same pattern as
 * `TextInput`'s `type="number"` fields. */
export function Select({ id, value, options, onChange, disabled = false }: SelectProps) {
  return (
    <select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="text-body w-full rounded-md border px-3 py-1.5 outline-none transition-colors duration-100 ease-out focus:border-[var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50"
      style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)", color: "var(--color-ink)" }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
