import { ShieldCheck } from "lucide-react";

/**
 * Minimal sidebar for Phase 1 (a single Delivery Summary page). Phase 2
 * adds QC Report / Doctor / Supervisor entries — this nav grows a real
 * router at that point, not before (YAGNI for now).
 */
export function Sidebar() {
  return (
    <aside
      className="flex w-[200px] shrink-0 flex-col p-4"
      style={{ backgroundColor: "var(--color-canvas)", borderRight: "1px solid var(--color-hairline)" }}
    >
      <div className="text-label mb-6 flex items-center gap-2 px-2" style={{ color: "var(--color-ink)" }}>
        <ShieldCheck size={16} strokeWidth={2.25} aria-hidden="true" />
        Sentinel Reports
      </div>
      <nav className="flex flex-col gap-1">
        <a
          href="#delivery-summary"
          aria-current="page"
          className="text-label flex items-center gap-2 rounded-md px-2 py-1.5"
          style={{ backgroundColor: "var(--color-surface-2)", color: "var(--color-ink)" }}
        >
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: "var(--color-primary)" }}
            aria-hidden="true"
          />
          Delivery Summary
        </a>
      </nav>
    </aside>
  );
}
