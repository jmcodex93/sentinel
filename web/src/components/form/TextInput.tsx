import type { InputHTMLAttributes } from "react";

interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

/** DESIGN.md-toned single-line input — surface-1 fill, hairline border
 * (status-fail when `invalid`), primary focus ring. */
export function TextInput({ invalid = false, className, style, ...rest }: TextInputProps) {
  return (
    <input
      {...rest}
      className={`text-body w-full rounded-md border px-3 py-1.5 outline-none transition-colors duration-100 ease-out focus:border-[var(--color-primary)] ${className ?? ""}`}
      style={{
        backgroundColor: "var(--color-surface-1)",
        borderColor: invalid ? "var(--color-status-fail)" : "var(--color-hairline)",
        color: "var(--color-ink)",
        ...style,
      }}
    />
  );
}
