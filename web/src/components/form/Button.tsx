import type { ButtonHTMLAttributes } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "destructive";
}

/** DESIGN.md `button-primary` / `button-secondary` — plus `destructive`,
 * the button that accepts an irreversible action. Primary is the single
 * accent CTA per surface (reserved by callers, not enforced here);
 * secondary is everything else.
 *
 * Destructive is filled with `--color-status-fail`, NOT the accent: the
 * accent means "interaction" and never state (DESIGN.md), and the fail hue
 * is the one already reading as "this is the bad one" everywhere else in
 * the panel. It is deliberately the only red button in the system — the
 * server decides which actions get it (`destructive` in the confirm
 * contract), so it keeps meaning something. Hover is a brightness step
 * rather than a second red token: no new color enters the system. */
export function Button({ variant = "secondary", type = "button", className, style, children, disabled, ...rest }: ButtonProps) {
  const isPrimary = variant === "primary";
  const isDestructive = variant === "destructive";
  return (
    <button
      {...rest}
      type={type}
      disabled={disabled}
      className={`text-label inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 transition-[background-color,transform] duration-[var(--motion-fast)] ease-[var(--ease-glide)] active:scale-[0.97] active:duration-[var(--motion-press)] active:ease-[var(--ease-spring)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-canvas)] disabled:cursor-not-allowed disabled:opacity-50 ${
        isPrimary
          ? "bg-[var(--color-primary)] enabled:hover:bg-[var(--color-primary-hover)] text-[var(--color-on-primary)]"
          : isDestructive
            ? "bg-[var(--color-status-fail)] enabled:hover:brightness-110 text-[var(--color-on-primary)]"
            : "bg-[var(--color-surface-2)] enabled:hover:bg-[var(--color-surface-1)] text-[var(--color-ink)]"
      } ${className ?? ""}`}
      style={{
        border: isPrimary || isDestructive ? "1px solid transparent" : "1px solid var(--color-hairline)",
        boxShadow: isPrimary || isDestructive ? "inset 0 1px 0 rgba(255,255,255,.08)" : undefined,
        ...style,
      }}
    >
      {children}
    </button>
  );
}
