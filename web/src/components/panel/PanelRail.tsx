import { Bug, Command, ExternalLink, HelpCircle, Settings, Stethoscope } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { PanelRailBadges, PanelSection, RailMode } from "../../lib/panel";
import { PANEL_SECTIONS } from "../../lib/panel";

/** Badge for a rail entry — status-fail chroma for QC (a failure count IS
 * state, per the plan's Global Constraints), status-warn for assets missing
 * (mirrors the mockup's orange "1" pill). Same tint-10-background/full-color-
 * text convention used by the shared status-tone components elsewhere in the
 * panel (no `--color-on-status-*` token exists in tokens.css, so a solid fill
 * + white/black text would be an invented value). `null` renders nothing. */
function RailBadge({ count, tone }: { count: number | null; tone: "fail" | "warn" }) {
  if (count === null) return null;
  const color = tone === "fail" ? "var(--color-status-fail)" : "var(--color-status-warn)";
  const background = tone === "fail" ? "var(--color-status-fail-tint-10)" : "var(--color-status-warn-tint-10)";
  return (
    <span
      className="text-label inline-flex min-w-[16px] items-center justify-center rounded-full px-1"
      style={{ backgroundColor: background, color, fontSize: "10px", lineHeight: "14px" }}
    >
      {count}
    </span>
  );
}

function badgeForSection(id: PanelSection["id"], badges: PanelRailBadges): { count: number | null; tone: "fail" | "warn" } | null {
  if (id === "qc") return { count: badges.qc, tone: "fail" };
  if (id === "deliver") return { count: badges.assets, tone: "warn" };
  return null;
}

/** Adaptive rail — the approved IA mockup's left column
 * (`.superpowers/brainstorm/75863-1784649095/content/hybrid-rail.html`):
 * a 44px icon-only rail below the 560px breakpoint, a ~132px labeled
 * sidebar at/above it (see `railMode` in lib/panel.ts). Only "Overview" is
 * a real page in Fase 6.0 — the rest navigate to PanelPage's placeholder,
 * wired up section-by-section in 6.1-6.4. The `⌘K` hint at the bottom is
 * static (the Command Palette is its own native window opened via the C4D
 * Help menu/shortcut, not something this embedded page can open itself). */
/** One footer action button — icon-only (with a tooltip) below the 560px
 * breakpoint, icon+label at/above it, same adaptive rule as the section
 * buttons above. */
function FooterButton({
  isSidebar,
  label,
  icon,
  onClick,
}: {
  isSidebar: boolean;
  label: string;
  icon: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      onClick={onClick}
      className="text-label flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ease-out"
      style={{
        justifyContent: isSidebar ? "flex-start" : "center",
        color: "var(--color-ink-secondary)",
      }}
    >
      <span className="inline-flex shrink-0 items-center justify-center">{icon}</span>
      {isSidebar && <span className="truncate">{label}</span>}
    </button>
  );
}

export function PanelRail({
  mode,
  active,
  onSelect,
  badges,
  onPalette,
  onSettings,
  onDoctor,
  onGithub,
  onBug,
}: {
  mode: RailMode;
  active: PanelSection["id"];
  onSelect: (id: PanelSection["id"]) => void;
  badges: PanelRailBadges;
  onPalette: () => void;
  onSettings: () => void;
  onDoctor: () => void;
  onGithub: () => void;
  onBug: () => void;
}) {
  const isSidebar = mode === "sidebar";
  const [helpOpen, setHelpOpen] = useState(false);

  return (
    <nav
      className="flex shrink-0 flex-col gap-1.5 py-2"
      style={{
        width: isSidebar ? 132 : 44,
        borderRight: "1px solid var(--color-hairline-strong)",
        backgroundColor: "var(--color-surface-1)",
      }}
    >
      <div className="flex flex-1 flex-col gap-1 px-1.5">
        {PANEL_SECTIONS.map((section) => {
          const isActive = section.id === active;
          const badge = badgeForSection(section.id, badges);
          return (
            <button
              key={section.id}
              type="button"
              title={section.label}
              onClick={() => onSelect(section.id)}
              className="text-label flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ease-out"
              style={{
                justifyContent: isSidebar ? "flex-start" : "center",
                backgroundColor: isActive ? "var(--color-surface-2)" : "transparent",
                color: isActive ? "var(--color-ink)" : "var(--color-ink-secondary)",
              }}
            >
              <span className="relative inline-flex shrink-0 items-center justify-center">
                <section.Icon size={16} strokeWidth={2.25} />
                {!isSidebar && badge && badge.count !== null && (
                  <span
                    className="absolute -right-1.5 -top-1.5 rounded-full px-1"
                    style={{
                      backgroundColor:
                        badge.tone === "fail" ? "var(--color-status-fail-tint-10)" : "var(--color-status-warn-tint-10)",
                      color: badge.tone === "fail" ? "var(--color-status-fail)" : "var(--color-status-warn)",
                      fontSize: "8px",
                      lineHeight: "12px",
                    }}
                  >
                    {badge.count}
                  </span>
                )}
              </span>
              {isSidebar && <span className="truncate">{section.label}</span>}
              {isSidebar && badge && <RailBadge count={badge.count} tone={badge.tone} />}
            </button>
          );
        })}
      </div>
      <div
        className="flex flex-col gap-1 border-t px-1.5 pt-1.5"
        style={{ borderColor: "var(--color-hairline)" }}
      >
        {/* Command Palette — the rail's power tool, lifted to the top of the
            footer and given ink (not ink-secondary) emphasis so it reads as
            the primary utility, not a low-priority link. */}
        <button
          type="button"
          title="Command Palette — search & run any action"
          onClick={onPalette}
          className="text-label flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ease-out"
          style={{
            justifyContent: isSidebar ? "flex-start" : "center",
            color: "var(--color-ink)",
            backgroundColor: "var(--color-surface-2)",
          }}
        >
          <Command size={16} strokeWidth={2.25} className="shrink-0" />
          {isSidebar && <span className="truncate">Commands</span>}
        </button>
        <FooterButton isSidebar={isSidebar} label="Settings" icon={<Settings size={16} strokeWidth={2.25} />} onClick={onSettings} />
        <FooterButton isSidebar={isSidebar} label="Doctor" icon={<Stethoscope size={16} strokeWidth={2.25} />} onClick={onDoctor} />
        {/* Help — folds the two "once in a lifetime" links (GitHub, Report
            Bug) into one entry with a small popover, reclaiming a footer row. */}
        <div className="relative">
          <FooterButton
            isSidebar={isSidebar}
            label="Help"
            icon={<HelpCircle size={16} strokeWidth={2.25} />}
            onClick={() => setHelpOpen((v) => !v)}
          />
          {helpOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setHelpOpen(false)} />
              <div
                className="absolute bottom-full left-0 z-20 mb-1 flex min-w-[140px] flex-col rounded-md border py-1 shadow-lg"
                style={{ borderColor: "var(--color-hairline-strong)", backgroundColor: "var(--color-surface-2)" }}
              >
                <button
                  type="button"
                  onClick={() => { setHelpOpen(false); onGithub(); }}
                  className="text-label flex items-center gap-2 px-3 py-1.5 text-left transition-colors duration-100 ease-out hover:bg-[var(--color-surface-1)]"
                  style={{ color: "var(--color-ink)" }}
                >
                  <ExternalLink size={14} strokeWidth={2.25} className="shrink-0" />
                  GitHub
                </button>
                <button
                  type="button"
                  onClick={() => { setHelpOpen(false); onBug(); }}
                  className="text-label flex items-center gap-2 px-3 py-1.5 text-left transition-colors duration-100 ease-out hover:bg-[var(--color-surface-1)]"
                  style={{ color: "var(--color-ink)" }}
                >
                  <Bug size={14} strokeWidth={2.25} className="shrink-0" />
                  Report Bug
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
