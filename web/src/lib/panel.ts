import type { ComponentType } from "react";
import { ClipboardCheck, Clapperboard, House, Package, Wrench } from "lucide-react";
import type { PanelOverview } from "../types";

/** Rail adaptive breakpoint (approved IA mockup,
 * `.superpowers/brainstorm/75863-1784649095/content/hybrid-rail.html`):
 * below 560px the rail collapses to 44px icons-only, at/above it becomes a
 * ~132px labeled sidebar. Kept as its own pure function (rather than inlined
 * in the ResizeObserver callback) so the breakpoint number lives in exactly
 * one place and is unit-testable without mounting a component. */
export type RailMode = "icon" | "sidebar";

const RAIL_BREAKPOINT_PX = 560;

export function railMode(width: number): RailMode {
  return width >= RAIL_BREAKPOINT_PX ? "sidebar" : "icon";
}

/** One rail/sidebar entry. Only "overview" has a real page in Fase 6.0 —
 * the rest render the "próximamente" placeholder (Task 3 brief) until
 * 6.1-6.4 fill them in. */
export interface PanelSection {
  id: "overview" | "qc" | "render" | "deliver" | "tools";
  label: string;
  Icon: ComponentType<{ size?: number; strokeWidth?: number }>;
}

export const PANEL_SECTIONS: PanelSection[] = [
  { id: "overview", label: "Overview", Icon: House },
  { id: "qc", label: "QC", Icon: ClipboardCheck },
  { id: "render", label: "Render", Icon: Clapperboard },
  { id: "deliver", label: "Deliver", Icon: Package },
  { id: "tools", label: "Tools", Icon: Wrench },
];

/** Rail badge counts — `null` means "no badge" (either the block failed to
 * load, or there's nothing to flag). Mirrors the mockup's QC-fails-count and
 * assets-missing-count badges exactly; both use status chroma at the render
 * site (they ARE state, per the plan's Global Constraints), not here. */
export interface PanelRailBadges {
  qc: number | null;
  assets: number | null;
}

export function railBadges(overview: PanelOverview): PanelRailBadges {
  const qc = overview.qc;
  let qcBadge: number | null = null;
  if (qc) {
    // `qc.total` is already net of disabled checks (see qc/score.py), so
    // it's the denominator directly — no further subtraction.
    const denominator = qc.total;
    const fails = denominator - qc.passed;
    if (fails > 0) qcBadge = fails;
  }

  const assets = overview.assets;
  const assetsBadge = assets && assets.missing > 0 ? assets.missing : null;

  return { qc: qcBadge, assets: assetsBadge };
}
