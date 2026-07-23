import { useState } from "react";
import { Button } from "../form/Button";
import { NotesPage } from "../../pages/NotesPage";
import { SaveVersionPage } from "../../pages/SaveVersionPage";
import {
  FILTER_ALL,
  RECENT_FILTERS,
  filterRecent,
  notesStatusLine,
  statusBadgeTone,
  versionStatusLine,
} from "../../lib/panelDeliver";
import type { PanelDeliverState, PanelVersionEntry } from "../../types";

/** Reuses the same 4-block "eyebrow + status + actions" shell as
 * RenderSection's `RenderBlock` — Deliver is a sibling section, so it must
 * read as the same system, not a bespoke card design. */
function DeliverBlock({
  eyebrow,
  status,
  children,
}: {
  eyebrow: string;
  status: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border p-3"
      style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
    >
      <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
        {eyebrow.toUpperCase()}
      </p>
      <p className="text-body" style={{ color: "var(--color-ink)" }}>
        {status}
      </p>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/** Status tone → CSS var pair. Only 4 semantic status tokens exist
 * (fail/warn/pass/neutral) and none of them mean "this is an error" for a
 * review-status badge, so WIP maps to neutral (in progress), TR/CR both map
 * to warn (pending review — the row's own "TR"/"CR" text still disambiguates
 * them), and FINAL maps to pass (done). Never the accent — accent marks
 * "selected", not status. */
const BADGE_TONE_VARS: Record<ReturnType<typeof statusBadgeTone>, { color: string; background: string }> = {
  wip: { color: "var(--color-status-neutral)", background: "var(--color-status-neutral-tint-10)" },
  tr: { color: "var(--color-status-warn)", background: "var(--color-status-warn-tint-10)" },
  cr: { color: "var(--color-status-warn)", background: "var(--color-status-warn-tint-10)" },
  final: { color: "var(--color-status-pass)", background: "var(--color-status-pass-tint-10)" },
};

function VersionBadge({ status }: { status: string }) {
  const tone = BADGE_TONE_VARS[statusBadgeTone(status)];
  return (
    <span
      className="text-label shrink-0 rounded-sm px-1.5 py-0.5"
      style={{ color: tone.color, backgroundColor: tone.background }}
    >
      {status || "WIP"}
    </span>
  );
}

/** What the open-version confirm bar is about to run — either the plain
 * open, or (after an `unsaved_changes` response) the forced re-open with the
 * unsaved-changes warning copy. */
type OpenConfirm = { entry: PanelVersionEntry; forced: boolean };

type DeliverView = "main" | "save_version" | "notes";

/** The panel's Deliver section (Fase 6.3 Task 5) — Version / Notes /
 * delivery-access blocks reusing the exact `panel/deliver` read + the
 * existing Save Version / Notes form pages as in-panel sub-views (their
 * `onBack`/`onDone` props exist for exactly this). Null blocks render the
 * shared "unavailable" status line rather than hiding — same null-safety
 * convention as QcSection/RenderSection. */
export function DeliverSection({
  deliver,
  busy,
  onOpenVersion,
  onCollect,
  onOpenSupervisor,
  onOpenDeliverySummary,
  onDone,
}: {
  deliver: PanelDeliverState;
  /** Non-null while `open_version`/`open_collect` is in flight — same single
   * busy-lock idiom as the other sections. */
  busy: string | null;
  /** Runs `panel/deliver/open_version` (toast + stamp re-anchor + refetch
   * live in PanelPage, same as every other mutation) and reports back
   * whether the SPA needs to re-confirm with `force: true` — mirrors
   * QcSection's `onAccept` Promise-returning contract, since the confirm
   * bar's copy/state depends on the result, not just success/failure. */
  onOpenVersion: (path: string, force: boolean) => Promise<{ ok: boolean; error?: string }>;
  onCollect: () => void;
  onOpenSupervisor: () => void;
  onOpenDeliverySummary: () => void;
  /** Fires after Save Version / Notes submits successfully, so the section
   * can navigate back to `main` and the caller can refresh `panel/deliver`. */
  onDone: () => void;
}) {
  const [view, setView] = useState<DeliverView>("main");
  const [filter, setFilter] = useState<string>(FILTER_ALL);
  const [openConfirm, setOpenConfirm] = useState<OpenConfirm | null>(null);
  const isBusy = busy !== null;

  function backToMain() {
    setView("main");
    onDone();
  }

  if (view === "save_version") {
    return <SaveVersionPage onBack={() => setView("main")} onDone={backToMain} />;
  }
  if (view === "notes") {
    return <NotesPage onBack={() => setView("main")} onDone={backToMain} />;
  }

  const version = deliver.version;
  const notes = deliver.notes;
  const deliverAccess = deliver.deliver;
  const recent = version && !version.unsaved ? filterRecent(version.recent, filter) : [];

  function handleRowClick(entry: PanelVersionEntry) {
    setOpenConfirm({ entry, forced: false });
  }

  async function handleConfirmOpen() {
    if (!openConfirm) return;
    const result = await onOpenVersion(openConfirm.entry.path, openConfirm.forced);
    // `unsaved_changes` on the FIRST attempt re-prompts with the forced
    // warning copy instead of clearing — every other outcome (ok, or any
    // other error — already_active/file_not_found/load_failed/bad_path,
    // toasted by the caller) closes the bar.
    if (!result.ok && result.error === "unsaved_changes" && !openConfirm.forced) {
      setOpenConfirm({ entry: openConfirm.entry, forced: true });
      return;
    }
    setOpenConfirm(null);
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      {openConfirm && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border p-3"
          style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
        >
          <span className="text-body" style={{ color: "var(--color-ink)" }}>
            {openConfirm.forced
              ? "You have unsaved changes — opening this version will discard them. Continue?"
              : `Open ${openConfirm.entry.filename}?`}
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="secondary" disabled={isBusy} onClick={() => setOpenConfirm(null)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={isBusy} onClick={handleConfirmOpen}>
              Confirm
            </Button>
          </div>
        </div>
      )}

      {/* Version */}
      <DeliverBlock eyebrow="Version" status={versionStatusLine(version)}>
        <Button variant="secondary" disabled={isBusy} onClick={() => setView("save_version")}>
          Save Version
        </Button>
      </DeliverBlock>

      {version && !version.unsaved && (
        <div
          className="flex flex-col gap-2 rounded-lg border p-3"
          style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
        >
          <p className="text-label" style={{ color: "var(--color-ink-secondary)" }}>
            RECENT VERSIONS
          </p>
          <div className="flex flex-wrap gap-1">
            {RECENT_FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setFilter(f.value)}
                className="text-caption rounded-sm px-2 py-1 transition-colors duration-100 ease-out"
                style={{
                  backgroundColor: f.value === filter ? "var(--color-surface-2)" : "transparent",
                  color: f.value === filter ? "var(--color-ink)" : "var(--color-ink-secondary)",
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-1">
            {recent.length === 0 && (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                No versions match this filter.
              </p>
            )}
            {recent.map((entry) => (
              <button
                key={entry.path}
                type="button"
                disabled={isBusy}
                onClick={() => handleRowClick(entry)}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ease-out hover:bg-[var(--color-surface-2)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <VersionBadge status={entry.status} />
                <span className="text-body" style={{ color: "var(--color-ink)" }}>
                  v{String(entry.version).padStart(3, "0")}
                </span>
                {entry.age && (
                  <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                    {entry.age}
                  </span>
                )}
                {entry.qc_label && (
                  <span className="text-caption ml-auto" style={{ color: "var(--color-ink-secondary)" }}>
                    QC {entry.qc_label}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Notes */}
      <DeliverBlock eyebrow="Notes" status={notesStatusLine(notes)}>
        <Button variant="secondary" disabled={isBusy} onClick={() => setView("notes")}>
          Edit Notes
        </Button>
      </DeliverBlock>

      {/* Deliver access */}
      <DeliverBlock eyebrow="Deliver" status="Collect, supervise, and review the delivery package.">
        <Button variant="secondary" disabled={isBusy} onClick={onCollect}>
          Collect Scene
        </Button>
        <Button variant="secondary" disabled={isBusy} onClick={onOpenSupervisor}>
          Supervisor
        </Button>
        {deliverAccess?.has_manifest && (
          <Button variant="secondary" disabled={isBusy} onClick={onOpenDeliverySummary}>
            Delivery Summary
          </Button>
        )}
      </DeliverBlock>
    </div>
  );
}
