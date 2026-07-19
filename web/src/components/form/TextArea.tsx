import type { TextareaHTMLAttributes } from "react";

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

/** Multi-line sibling of `TextInput` — same tokens, defaults to 4 rows. */
export function TextArea({ invalid = false, className, style, rows = 4, ...rest }: TextAreaProps) {
  return (
    <textarea
      {...rest}
      rows={rows}
      className={`text-body w-full resize-y rounded-md border px-3 py-1.5 outline-none transition-colors duration-100 ease-out focus:border-[var(--color-primary)] ${className ?? ""}`}
      style={{
        backgroundColor: "var(--color-surface-1)",
        borderColor: invalid ? "var(--color-status-fail)" : "var(--color-hairline)",
        color: "var(--color-ink)",
        ...style,
      }}
    />
  );
}
