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
      className={`text-label inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 transform-gpu transition-[background-color,transform] duration-[var(--motion-fast)] ease-[var(--ease-glide)] active:scale-[0.97] active:duration-[var(--motion-press)] active:ease-[var(--ease-spring)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-canvas)] disabled:cursor-not-allowed disabled:opacity-50 ${
        isPrimary
          ? "bg-[var(--color-primary)] enabled:hover:bg-[var(--color-primary-hover)] text-[var(--color-on-primary)]"
          : "bg-[var(--color-surface-2)] enabled:hover:bg-[var(--color-surface-1)] text-[var(--color-ink)]"
      } ${className ?? ""}`}
      style={{
        border: isPrimary ? "1px solid transparent" : "1px solid var(--color-hairline)",
        boxShadow: isPrimary ? "inset 0 1px 0 rgba(255,255,255,.08)" : undefined,
        ...style,
      }}
    >
      {children}
    </button>
  );
}
