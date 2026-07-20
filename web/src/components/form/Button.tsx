import type { ButtonHTMLAttributes } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary";
}

/** DESIGN.md `button-primary` / `button-secondary` — the only two button
 * surfaces in the system. Primary is the single accent CTA per surface
 * (reserved by callers, not enforced here); secondary is everything else. */
export function Button({ variant = "secondary", type = "button", className, style, children, disabled, ...rest }: ButtonProps) {
  const isPrimary = variant === "primary";
  return (
    <button
      {...rest}
      type={type}
      disabled={disabled}
      className={`text-label inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 transition-colors duration-100 ease-out disabled:cursor-not-allowed disabled:opacity-50 ${className ?? ""}`}
      style={{
        backgroundColor: isPrimary ? "var(--color-primary)" : "var(--color-surface-2)",
        color: isPrimary ? "var(--color-on-primary)" : "var(--color-ink)",
        border: isPrimary ? "1px solid transparent" : "1px solid var(--color-hairline)",
        ...style,
      }}
      onMouseEnter={(e) => {
        if (disabled) return;
        e.currentTarget.style.backgroundColor = isPrimary ? "var(--color-primary-hover)" : "var(--color-surface-1)";
      }}
      onMouseLeave={(e) => {
        if (disabled) return;
        e.currentTarget.style.backgroundColor = isPrimary ? "var(--color-primary)" : "var(--color-surface-2)";
      }}
    >
      {children}
    </button>
  );
}
