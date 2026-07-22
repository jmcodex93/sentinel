import { useCallback, useEffect, useRef, useState } from "react";
import { OverviewCards } from "../components/panel/OverviewCards";
import { PanelHeader } from "../components/panel/PanelHeader";
import { PanelRail } from "../components/panel/PanelRail";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Button } from "../components/form/Button";
import {
  fetchPaletteActions,
  fetchPanelOverview,
  fetchPanelStamp,
  isMock,
  postPanelOpenForm,
  runPaletteAction,
} from "../lib/api";
import { railBadges, railMode, type PanelSection } from "../lib/panel";
import { useToast } from "../lib/toast";
import type { PaletteAction, PanelOverviewResult } from "../types";

type PageState = { kind: "loading" } | PanelOverviewResult;

const POLL_INTERVAL_MS = 2000;

/** Deep-link palette action id + label for each not-yet-built section's
 * "próximamente" placeholder — the closest native equivalent already
 * reachable via `palette/run`'s navigate/run actions (see webbridge.py
 * `PALETTE_ACTIONS`). Tools has no report page of its own; Asset Hub is
 * where the native panel's Tools tab sends "Asset Management" today, so
 * it's the closest stand-in until 6.4. */
const PLACEHOLDER_DEEP_LINKS: Partial<Record<PanelSection["id"], { id: string; label: string }>> = {
  qc: { id: "open_reports_qc", label: "Open QC Report" },
  render: { id: "open_reports_render_validation", label: "Open Render Validation" },
  deliver: { id: "open_reports_delivery", label: "Open Delivery Summary" },
  tools: { id: "open_hub", label: "Open Asset Hub" },
};

function SectionPlaceholder({ section, onDeepLink }: { section: PanelSection["id"]; onDeepLink: (id: string) => void }) {
  const link = PLACEHOLDER_DEEP_LINKS[section];
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div
        className="max-w-md rounded-lg border p-6 text-center"
        style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
      >
        <p className="text-body-lg" style={{ color: "var(--color-ink)" }}>
          Próximamente
        </p>
        <p className="text-body mt-2" style={{ color: "var(--color-ink-secondary)" }}>
          Esta sección aún vive en el panel nativo.
        </p>
        {link && (
          <div className="mt-4">
            <Button variant="secondary" onClick={() => onDeepLink(link.id)}>
              {link.label} →
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Fase 6.0 dockable Panel SPA — adaptive rail + always-visible header +
 * Overview "shot health" dashboard. See
 * docs/superpowers/plans/2026-07-21-panel-60-host.md Task 3, and the
 * approved IA mockup at
 * .superpowers/brainstorm/75863-1784649095/content/hybrid-rail.html.
 *
 * Only "Overview" has real content; the other 4 rail sections render a
 * placeholder linking their closest native equivalent until 6.1-6.4 build
 * them out (per the plan's Global Constraints — quick actions/navigation
 * reuse the existing `palette/run` ids, no new ops beyond `panel/open_form`
 * for the two absorbed-later native windows).
 */
export function PanelPage() {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [section, setSection] = useState<PanelSection["id"]>("overview");
  const [mode, setMode] = useState<"icon" | "sidebar">("icon");
  const [actions, setActions] = useState<PaletteAction[]>([]);
  const [busyFixId, setBusyFixId] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<PaletteAction | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const stampRef = useRef<string | null>(null);

  const load = useCallback((silent: boolean) => {
    if (!silent) setState({ kind: "loading" });
    fetchPanelOverview().then(async (result) => {
      setState(result);
      stampRef.current = result.kind === "ok" ? await fetchPanelStamp() : null;
    });
    fetchPaletteActions().then((result) => {
      if (result.kind === "ok") setActions(result.data);
    });
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  // Adaptive rail breakpoint — ResizeObserver on the page root rather than
  // `window.resize`, since this page is hosted inside a native docked panel
  // whose own window can be any size independent of the OS window.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? el.clientWidth;
      setMode(railMode(width));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Stamp polling — same "compare, then refetch only on change" idiom as
  // HubPage's own polling effect. No live interval under `?mock=1` (no real
  // document to drift from).
  useEffect(() => {
    if (isMock()) return;
    const id = window.setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      const newStamp = await fetchPanelStamp();
      if (newStamp === null || stampRef.current === null || newStamp === stampRef.current) return;
      load(true);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  async function runFix(action: PaletteAction, confirm?: boolean) {
    // qc.fixable (panel/overview) and this actions list (palette/actions) are
    // independently-timed snapshots — a fixable id can be stale by the time
    // the artist clicks it. Gate on the freshest known enabled/reason before
    // honoring requires_confirm or hitting the server, same as
    // PalettePage.runAction / HubPreflightStrip.runFix.
    if (!action.enabled) {
      if (action.reason) toast({ message: action.reason, variant: "warn" });
      return;
    }
    if (action.requires_confirm && !confirm) {
      setConfirmAction(action);
      return;
    }
    setBusyFixId(action.id);
    const response = await runPaletteAction(action.id, confirm);
    setBusyFixId(null);
    setConfirmAction(null);

    if (!response.ok) {
      toast({ message: response.error || "Fix failed.", variant: "warn" });
      return;
    }
    toast({ message: response.message || "Fixed.", variant: "success" });
    load(true);
  }

  function handleFix(id: string) {
    const action = actions.find((a) => a.id === id);
    if (!action) {
      toast({ message: "Fix action unavailable.", variant: "warn" });
      return;
    }
    runFix(action);
  }

  async function handleDeepLink(id: string) {
    const response = await runPaletteAction(id);
    if (!response.ok) toast({ message: response.error || "Couldn't open.", variant: "warn" });
  }

  async function handleOpenForm(page: "form/save_version" | "form/notes") {
    const response = await postPanelOpenForm(page);
    if (!response.ok) toast({ message: response.error || "Couldn't open.", variant: "warn" });
  }

  const badges = state.kind === "ok" ? railBadges(state.data) : { qc: null, assets: null };

  return (
    <div ref={rootRef} className="flex h-screen" style={{ backgroundColor: "var(--color-canvas)" }}>
      <PanelRail mode={mode} active={section} onSelect={setSection} badges={badges} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <PanelHeader scene={state.kind === "ok" ? state.data.scene : null} qc={state.kind === "ok" ? state.data.qc : null} />

        <div className="flex-1 overflow-auto">
          {state.kind === "loading" && <LoadingState />}
          {state.kind === "error" && (
            <ErrorState title="Couldn't load the panel" message={state.message} onRetry={() => load(false)} />
          )}
          {state.kind === "empty" && <EmptyState title="No document open" reason={state.reason} />}

          {state.kind === "ok" && section === "overview" && (
            <>
              {confirmAction && (
                <div
                  className="mx-3 mt-3 flex flex-wrap items-center gap-2 rounded-lg border p-3"
                  style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
                >
                  <span className="text-body" style={{ color: "var(--color-ink)" }}>
                    {confirmAction.confirm_label}
                  </span>
                  <div className="ml-auto flex gap-2">
                    <Button variant="secondary" disabled={busyFixId !== null} onClick={() => setConfirmAction(null)}>
                      Cancel
                    </Button>
                    <Button variant="primary" disabled={busyFixId !== null} onClick={() => runFix(confirmAction, true)}>
                      Confirm
                    </Button>
                  </div>
                </div>
              )}
              <OverviewCards
                overview={state.data}
                actions={actions}
                busyFix={busyFixId}
                onFix={handleFix}
                onOpenQc={() => handleDeepLink("open_reports_qc")}
                onOpenHub={() => handleDeepLink("open_hub")}
                onValidateRender={() => handleDeepLink("open_reports_render_validation")}
                onSaveVersion={() => handleOpenForm("form/save_version")}
                onEditNotes={() => handleOpenForm("form/notes")}
                onOpenDeliver={() => handleDeepLink("open_reports_delivery")}
              />
            </>
          )}

          {state.kind === "ok" && section !== "overview" && (
            <SectionPlaceholder section={section} onDeepLink={handleDeepLink} />
          )}
        </div>
      </div>
    </div>
  );
}
