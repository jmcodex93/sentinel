import { useState } from "react";
import { Button } from "../form/Button";
import { NotesPage } from "../../pages/NotesPage";
import { SaveVersionPage } from "../../pages/SaveVersionPage";
import {
  FILTER_ALL,
  RECENT_FILTERS,
  filterRecent,
  notesStatusLine,
  statusMarker,
  versionStatusLine,
} from "../../lib/panelDeliver";
import type { PanelDeliverState } from "../../types";
import { SectionGroup } from "../SectionGroup";

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
   * live in PanelPage). Opening a version is non-destructive — an already
   * open one is re-activated, an unopened one loads as a new document — so
   * a single click opens/switches, no confirm step. */
  onOpenVersion: (path: string, filename: string) => void;
  onCollect: () => void;
  onOpenSupervisor: () => void;
  onOpenDeliverySummary: () => void;
  /** Fires after Save Version / Notes submits successfully, so the section
   * can navigate back to `main` and the caller can refresh `panel/deliver`. */
  onDone: () => void;
}) {
  const [view, setView] = useState<DeliverView>("main");
  const [filter, setFilter] = useState<string>(FILTER_ALL);
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

  return (
    <div className="flex flex-col p-3">
      {/* Version */}
      <SectionGroup title="Version" first>
        <div className="flex flex-col gap-2">
          <p className="text-body" style={{ color: "var(--color-ink)" }}>
            {versionStatusLine(version)}
          </p>
          <Button variant="primary" disabled={isBusy} onClick={() => setView("save_version")}>
            Save Version
          </Button>
        </div>
      </SectionGroup>

      {version && !version.unsaved && (
        <SectionGroup title="Recent versions">
          <div className="flex flex-col gap-2">
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
              {recent.map((entry) => {
                const m = statusMarker(entry.status);
                return (
                  <button
                    key={entry.path}
                    type="button"
                    disabled={isBusy}
                    onClick={() => onOpenVersion(entry.path, entry.filename)}
                    title={`Open ${entry.filename}`}
                    className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-100 ease-out hover:bg-[var(--color-surface-2)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ backgroundColor: m.color }} />
                      <span className="text-caption font-semibold" style={{ color: m.color }}>
                        {m.label}
                      </span>
                    </span>
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
                );
              })}
            </div>
          </div>
        </SectionGroup>
      )}

      {/* Notes */}
      <SectionGroup
        title="Notes"
        action={
          <Button variant="secondary" disabled={isBusy} onClick={() => setView("notes")}>
            Edit Notes
          </Button>
        }
      >
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {notesStatusLine(notes)}
        </p>
      </SectionGroup>

      {/* Deliver access */}
      <SectionGroup title="Deliver">
        <div className="flex flex-col gap-2">
          <p className="text-body" style={{ color: "var(--color-ink)" }}>
            Collect, supervise, and review the delivery package.
          </p>
          <div className="flex flex-wrap items-center gap-2">
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
          </div>
        </div>
      </SectionGroup>
    </div>
  );
}
