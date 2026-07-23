import type { ReactNode } from "react";

interface FormPageShellProps {
  title: string;
  /** Meta content under the title — scene name, last version pillbox, QC
   * score, whatever the page needs (see `report-page-header`). */
  meta?: ReactNode;
  children: ReactNode;
  /** Pinned footer, typically a `SubmitBar` — kept outside the scroll area
   * so the primary action is always reachable. */
  footer?: ReactNode;
  /** Embedded as an in-panel sub-view (Deliver section, Fase 6.3) rather
   * than hosted one-per-window. The window host wants a full-height shell
   * with a bottom-pinned footer; the panel host is a tall docked frame the
   * form doesn't fill, so `h-screen` + a pinned footer would strand the
   * submit button far below the (short) fields. Embedded mode drops the
   * full-height/scroll shell and lets the footer flow right after the
   * content. */
  embedded?: boolean;
}

/** Full-bleed page shell for a Sentinel form (Save Version, Notes, Settings,
 * Gate Triage) — each is hosted one-per-window by a native `FormDialog`
 * (Phase 4 Task 4), so there is no Sidebar here, just
 * `report-page-header`-styled header + scrollable body + pinned footer. */
export function FormPageShell({ title, meta, children, footer, embedded = false }: FormPageShellProps) {
  return (
    <div
      className={embedded ? "flex flex-col" : "flex h-screen flex-col overflow-hidden"}
      style={{ backgroundColor: "var(--color-canvas)" }}
    >
      <header
        className="px-[18px] py-[18px]"
        style={{ backgroundColor: "var(--color-surface-1)", borderBottom: "1px solid var(--color-hairline-strong)" }}
      >
        <h1 className="text-title truncate" style={{ color: "var(--color-ink)" }}>
          {title}
        </h1>
        {meta}
      </header>
      <div className={embedded ? "p-4" : "flex-1 overflow-auto p-4"}>{children}</div>
      {footer}
    </div>
  );
}
