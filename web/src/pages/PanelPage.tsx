import { useCallback, useEffect, useRef, useState } from "react";
import { OverviewCards } from "../components/panel/OverviewCards";
import { PanelHeader } from "../components/panel/PanelHeader";
import { PanelRail } from "../components/panel/PanelRail";
import { QcSection } from "../components/panel/QcSection";
import { RenderSection } from "../components/panel/RenderSection";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Button } from "../components/form/Button";
import {
  fetchPaletteActions,
  fetchPanelOverview,
  fetchPanelQc,
  fetchPanelRender,
  fetchPanelStamp,
  isMock,
  postPanelOpenForm,
  postPanelQcAccept,
  postPanelQcFixAll,
  postPanelQcSelect,
  postPanelRenderAddFrameTag,
  postPanelRenderAovTier,
  postPanelRenderForceVertical,
  postPanelRenderOpenFolder,
  postPanelRenderResetAll,
  postPanelRenderSaveStill,
  postPanelRenderSelectFrameTag,
  postPanelRenderSetMultipart,
  postPanelRenderSetPreset,
  postPanelRenderToggleWatchfolder,
  runPaletteAction,
} from "../lib/api";
import { railBadges, railMode, type PanelSection } from "../lib/panel";
import { useToast } from "../lib/toast";
import type {
  PaletteAction,
  PanelOverviewResult,
  PanelQcCheck,
  PanelQcResult,
  PanelRenderMutationResponse,
  PanelRenderResult,
} from "../types";

type PageState = { kind: "loading" } | PanelOverviewResult;
type QcPageState = { kind: "loading" } | PanelQcResult;
type RenderPageState = { kind: "loading" } | PanelRenderResult;

/** What the Render section's inline confirm bar is about to run — set once
 * a destructive op (`reset_all`/`force_vertical`/`aov_tier`) comes back
 * `confirm_required`, so Confirm can re-issue the exact same op with
 * `confirm: true` (the server, not the SPA, owns the copy in `label`). */
type AovTier = "essentials" | "production" | "light_groups";
type RenderConfirm = { op: "reset_all" | "force_vertical" | "aov_tier"; tier?: AovTier; label: string };

/** What the inline confirm bar is about to run, for the QC section's Fix
 * (per-card, via the shared palette action) and Fix-all (via
 * `panel/qc/fix_all`) mutations — same "gate on the freshest known
 * enabled/reason/requires_confirm before hitting the server" contract as
 * Overview's `confirmAction`, just able to represent either mutation kind. */
type QcConfirm = { kind: "card_fix"; action: PaletteAction } | { kind: "fix_all"; action: PaletteAction };

const POLL_INTERVAL_MS = 2000;

/** Deep-link palette action id + label for each not-yet-built section's
 * "próximamente" placeholder — the closest native equivalent already
 * reachable via `palette/run`'s navigate/run actions (see webbridge.py
 * `PALETTE_ACTIONS`). Tools has no report page of its own; Asset Hub is
 * where the native panel's Tools tab sends "Asset Management" today, so
 * it's the closest stand-in until 6.4. */
const PLACEHOLDER_DEEP_LINKS: Partial<Record<PanelSection["id"], { id: string; label: string }>> = {
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
  const [qcState, setQcState] = useState<QcPageState>({ kind: "loading" });
  const [busyQcId, setBusyQcId] = useState<string | null>(null);
  const [qcConfirm, setQcConfirm] = useState<QcConfirm | null>(null);
  const [renderState, setRenderState] = useState<RenderPageState>({ kind: "loading" });
  const [busyRenderId, setBusyRenderId] = useState<string | null>(null);
  const [renderConfirm, setRenderConfirm] = useState<RenderConfirm | null>(null);

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

  // `panel/qc` is its own fetch (Fase 6.1) — the section's full per-check
  // FAIL/WARN/OK/disabled breakdown, not the top-3 summary `load` above
  // already carries in `state.data.qc`. Fetched on entering the QC section
  // and again on every stamp change while it's active (see the polling
  // effect below), same "compare, then refetch only on change" idiom.
  const loadQc = useCallback((silent: boolean) => {
    if (!silent) setQcState({ kind: "loading" });
    fetchPanelQc().then(async (result) => {
      setQcState(result);
      if (result.kind === "ok") stampRef.current = await fetchPanelStamp();
    });
  }, []);

  // `panel/render` (Fase 6.2) — same "own fetch on entering the section,
  // own stamp-driven refetch" idiom as `panel/qc` above.
  const loadRender = useCallback((silent: boolean) => {
    if (!silent) setRenderState({ kind: "loading" });
    fetchPanelRender().then(async (result) => {
      setRenderState(result);
      if (result.kind === "ok") stampRef.current = await fetchPanelStamp();
    });
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  useEffect(() => {
    if (section === "qc") loadQc(false);
  }, [section, loadQc]);

  useEffect(() => {
    if (section === "render") loadRender(false);
  }, [section, loadRender]);

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
      if (section === "qc") loadQc(true);
      if (section === "render") loadRender(true);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [load, loadQc, loadRender, section]);

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

  async function handleQcSelect(checkId: string) {
    setBusyQcId(`select:${checkId}`);
    const response = await postPanelQcSelect(checkId);
    setBusyQcId(null);
    if (!response.ok) {
      toast({ message: response.error || "Select failed.", variant: "warn" });
      return;
    }
    if (response.stamp) stampRef.current = response.stamp;
    const progress =
      response.total && response.total > 0 ? ` ${response.cursor_pos}/${response.total}` : "";
    toast({ message: `Selected in scene.${progress}`, variant: "success" });
  }

  async function handleQcAccept(checkId: string, author: string, reason: string) {
    setBusyQcId(`accept:${checkId}`);
    const response = await postPanelQcAccept(checkId, author, reason);
    setBusyQcId(null);
    if (!response.ok) {
      return { ok: false, error: response.error };
    }
    if (response.stamp) stampRef.current = response.stamp;
    if (response.qc) setQcState({ kind: "ok", data: response.qc });
    toast({ message: "Accepted into the baseline.", variant: "success" });
    load(true); // keeps the rail/header QC badge in sync, same as runQcCardFix/runQcFixAll
    return { ok: true };
  }

  // Per-card Fix reuses the exact same shared palette action (fix_lights/
  // fix_cameras/fix_materials/fix_fps) + enabled/reason + requires_confirm
  // gate as Overview's `runFix` above — the QC section's Fix button is not
  // a distinct mutation, just a different entry point into `palette/run`.
  async function runQcCardFix(action: PaletteAction, confirm?: boolean) {
    if (!action.enabled) {
      if (action.reason) toast({ message: action.reason, variant: "warn" });
      return;
    }
    if (action.requires_confirm && !confirm) {
      setQcConfirm({ kind: "card_fix", action });
      return;
    }
    setBusyQcId(`fix:${action.id}`);
    const response = await runPaletteAction(action.id, confirm);
    setBusyQcId(null);
    setQcConfirm(null);

    if (!response.ok) {
      toast({ message: response.error || "Fix failed.", variant: "warn" });
      return;
    }
    toast({ message: response.message || "Fixed.", variant: "success" });
    loadQc(true);
    load(true); // keeps the rail/header QC badge and the palette action list in sync
  }

  function handleQcFix(check: PanelQcCheck) {
    const action = actions.find((a) => a.id === check.fix_action_id);
    if (!action) {
      toast({ message: "Fix action unavailable.", variant: "warn" });
      return;
    }
    runQcCardFix(action);
  }

  /** Fix-all is its own op (`panel/qc/fix_all`, `fixes.apply_fixes` over
   * every currently-fixable check in one undo) — not a loop over
   * `runPaletteAction`. The confirm gate still has to reflect the palette's
   * `requires_confirm` contract for materials/fps, so this looks up whether
   * any check the batch would touch matches a destructive palette action. */
  function qcFixAllConfirmAction(): PaletteAction | null {
    if (qcState.kind !== "ok") return null;
    for (const check of [...qcState.data.fail, ...qcState.data.warn]) {
      if (!check.can_fix) continue;
      const action = actions.find((a) => a.id === check.fix_action_id);
      if (action?.requires_confirm) return action;
    }
    return null;
  }

  async function runQcFixAll(confirm?: boolean) {
    if (!confirm) {
      const needsConfirm = qcFixAllConfirmAction();
      if (needsConfirm) {
        setQcConfirm({ kind: "fix_all", action: needsConfirm });
        return;
      }
    }
    setBusyQcId("fix_all");
    const response = await postPanelQcFixAll();
    setBusyQcId(null);
    setQcConfirm(null);

    if (!response.ok) {
      toast({ message: response.error || "Fix all failed.", variant: "warn" });
      return;
    }
    if (response.stamp) stampRef.current = response.stamp;
    if (response.qc) setQcState({ kind: "ok", data: response.qc });
    toast({ message: "Fixed.", variant: "success" });
    load(true); // keeps the rail/header QC badge and the palette action list in sync
  }

  /** Shared tail for every `panel/render/*` mutation: apply the echoed
   * `render` + fresh stamp, toast, and `load(true)` so the rail/header stay
   * in sync — same lesson as the QC accept/fix handlers above. Errors never
   * apply a false-success toast (e.g. add_frame_tag's `no_camera`/
   * `already_tagged`/`import_failure` all land here as a warn toast, not a
   * "Done." success). */
  function applyRenderMutation(response: PanelRenderMutationResponse, successMsg = "Done.") {
    if (!response.ok) {
      toast({ message: response.error || "Action failed.", variant: "warn" });
      return;
    }
    if (response.stamp) stampRef.current = response.stamp;
    if (response.render) setRenderState({ kind: "ok", data: response.render });
    toast({ message: successMsg, variant: "success" });
    load(true);
  }

  async function handleSetPreset(preset: string) {
    setBusyRenderId("set_preset");
    const response = await postPanelRenderSetPreset(preset);
    setBusyRenderId(null);
    applyRenderMutation(response, `Preset set to ${preset}.`);
  }

  /** Destructive ops (Reset All, Force 9:16, an AOV tier) never confirm
   * client-side — the first call omits `confirm`, and a `confirm_required`
   * response is what opens the inline bar, with the server's own
   * `confirm_label` as the copy (never SPA-authored text). */
  async function runRenderDestructive(op: "reset_all" | "force_vertical" | "aov_tier", tier?: AovTier, confirm?: boolean) {
    const busyId = tier ? `${op}:${tier}` : op;
    setBusyRenderId(busyId);
    const response =
      op === "reset_all"
        ? await postPanelRenderResetAll(confirm)
        : op === "force_vertical"
          ? await postPanelRenderForceVertical(confirm)
          : await postPanelRenderAovTier(tier ?? "essentials", confirm);
    setBusyRenderId(null);

    if (!response.ok && response.error === "confirm_required") {
      setRenderConfirm({ op, tier, label: response.confirm_label || "Are you sure?" });
      return;
    }
    setRenderConfirm(null);
    applyRenderMutation(response);
  }

  async function handleAddFrameTag() {
    setBusyRenderId("add_frame_tag");
    const response = await postPanelRenderAddFrameTag();
    setBusyRenderId(null);
    applyRenderMutation(response, "Sentinel Frame added.");
  }

  async function handleSelectFrameTag() {
    setBusyRenderId("select_frame_tag");
    const response = await postPanelRenderSelectFrameTag();
    setBusyRenderId(null);
    applyRenderMutation(response, "Tag selected.");
  }

  async function handleSetMultipart(enabled: boolean) {
    setBusyRenderId("set_multipart");
    const response = await postPanelRenderSetMultipart(enabled);
    setBusyRenderId(null);
    applyRenderMutation(response);
  }

  async function handleToggleWatch() {
    setBusyRenderId("toggle_watchfolder");
    const response = await postPanelRenderToggleWatchfolder();
    setBusyRenderId(null);
    applyRenderMutation(response);
  }

  async function handleSaveStill() {
    setBusyRenderId("save_still");
    const response = await postPanelRenderSaveStill();
    setBusyRenderId(null);
    applyRenderMutation(response, "Still saved.");
  }

  async function handleOpenFolder() {
    setBusyRenderId("open_folder");
    const response = await postPanelRenderOpenFolder();
    setBusyRenderId(null);
    applyRenderMutation(response, "Folder opened.");
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

          {state.kind === "ok" && section === "qc" && (
            <>
              {qcConfirm && (
                <div
                  className="mx-3 mt-3 flex flex-wrap items-center gap-2 rounded-lg border p-3"
                  style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
                >
                  <span className="text-body" style={{ color: "var(--color-ink)" }}>
                    {qcConfirm.action.confirm_label}
                  </span>
                  <div className="ml-auto flex gap-2">
                    <Button variant="secondary" disabled={busyQcId !== null} onClick={() => setQcConfirm(null)}>
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      disabled={busyQcId !== null}
                      onClick={() =>
                        qcConfirm.kind === "card_fix" ? runQcCardFix(qcConfirm.action, true) : runQcFixAll(true)
                      }
                    >
                      Confirm
                    </Button>
                  </div>
                </div>
              )}
              {qcState.kind === "loading" && <LoadingState />}
              {qcState.kind === "error" && (
                <ErrorState title="Couldn't load QC" message={qcState.message} onRetry={() => loadQc(false)} />
              )}
              {qcState.kind === "empty" && <EmptyState title="No document open" reason={qcState.reason} />}
              {qcState.kind === "ok" && (
                <QcSection
                  qc={qcState.data}
                  actions={actions}
                  artistName={state.data.scene?.artist ?? ""}
                  busy={busyQcId}
                  onSelect={handleQcSelect}
                  onFix={handleQcFix}
                  onAccept={handleQcAccept}
                  onFixAll={() => runQcFixAll()}
                />
              )}
            </>
          )}

          {state.kind === "ok" && section === "render" && (
            <>
              {renderState.kind === "loading" && <LoadingState />}
              {renderState.kind === "error" && (
                <ErrorState title="Couldn't load Render" message={renderState.message} onRetry={() => loadRender(false)} />
              )}
              {renderState.kind === "empty" && <EmptyState title="No document open" reason={renderState.reason} />}
              {renderState.kind === "ok" && (
                <RenderSection
                  render={renderState.data}
                  busy={busyRenderId}
                  confirmLabel={renderConfirm?.label ?? null}
                  onSetPreset={handleSetPreset}
                  onDestructive={(op, tier) => runRenderDestructive(op, tier)}
                  onAddFrameTag={handleAddFrameTag}
                  onSelectFrameTag={handleSelectFrameTag}
                  onSetMultipart={handleSetMultipart}
                  onToggleWatch={handleToggleWatch}
                  onSaveStill={handleSaveStill}
                  onOpenFolder={handleOpenFolder}
                  onValidate={() => handleDeepLink("open_reports_render_validation")}
                  onConfirm={() => renderConfirm && runRenderDestructive(renderConfirm.op, renderConfirm.tier, true)}
                  onCancelConfirm={() => setRenderConfirm(null)}
                />
              )}
            </>
          )}

          {state.kind === "ok" && section !== "overview" && section !== "qc" && section !== "render" && (
            <SectionPlaceholder section={section} onDeepLink={handleDeepLink} />
          )}
        </div>
      </div>
    </div>
  );
}
