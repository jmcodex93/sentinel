import type { ReactNode } from "react";

/** A borderless section group (panel polish / de-slop): replaces the
 * repeated `rounded-lg border p-3 surface-1` card shell in the stacked-config
 * sections. Consecutive groups separate with a hairline top border (skipped
 * for `first`); the title is a normal-weight-600 ink heading, NOT an
 * uppercase gray eyebrow. `meta` (muted, right of title) and `action` (a
 * right-aligned node) are optional. Cards are kept only where a block is a
 * real card (Overview KPIs, QC FAIL/WARN) — not here. */
export function SectionGroup({
  title,
  meta,
  action,
  children,
  first = false,
}: {
  title?: string;
  meta?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  first?: boolean;
}) {
  return (
    <section
      className={first ? "pb-4" : "border-t pt-4 pb-4"}
      style={{ borderColor: "var(--color-hairline)" }}
    >
      {(title || action) && (
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <div className="flex items-baseline gap-2">
            {title && (
              <h3 className="text-body font-semibold" style={{ color: "var(--color-ink)" }}>
                {title}
              </h3>
            )}
            {meta && (
              <span className="text-caption" style={{ color: "var(--color-muted)" }}>
                {meta}
              </span>
            )}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
