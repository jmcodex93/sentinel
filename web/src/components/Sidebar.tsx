import { Clapperboard, ClipboardCheck, Package, ShieldCheck, Stethoscope, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Page } from "../App";

interface NavItem {
  page: Page;
  label: string;
  Icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { page: "delivery", label: "Delivery Summary", Icon: Package },
  { page: "qc", label: "QC Report", Icon: ClipboardCheck },
  { page: "doctor", label: "Doctor", Icon: Stethoscope },
  { page: "supervisor", label: "Supervisor", Icon: Users },
  { page: "render", label: "Render Validation", Icon: Clapperboard },
];

/** State-lift router nav — five report pages, no URL routing needed (the
 * SPA is hosted inside a single C4D HtmlViewer gadget/browser tab; a page
 * refresh always re-lands on the default page, which is acceptable here).
 * See App.tsx's `Page` union for the sibling switch statement. */
export function Sidebar({ active, onNavigate }: { active: Page; onNavigate: (page: Page) => void }) {
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
        {NAV_ITEMS.map(({ page, label, Icon }) => {
          const isActive = page === active;
          return (
            <button
              key={page}
              type="button"
              aria-current={isActive ? "page" : undefined}
              onClick={() => onNavigate(page)}
              className="text-label flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ease-out"
              style={{
                backgroundColor: isActive ? "var(--color-surface-2)" : "transparent",
                color: isActive ? "var(--color-ink)" : "var(--color-ink-secondary)",
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = "var(--color-surface-1)";
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <Icon size={14} strokeWidth={2.25} aria-hidden="true" />
              {label}
              {isActive && (
                <span
                  className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: "var(--color-primary)" }}
                  aria-hidden="true"
                />
              )}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
