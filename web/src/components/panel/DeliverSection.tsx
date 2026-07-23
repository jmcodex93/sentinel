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
import type { PanelDeliverState } from "../../types";

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

/** Status tone → CSS var pair, matching the native panel's badge palette so
 * the artist's mental model carries over: WIP = neutral grey (in progress),
 * TR = amber (team review), CR = blue (client review), FINAL = green (done).
 * Each review stage gets its own hue. Never the accent — accent marks
 * "selected", not status; the CR blue is deliberately distinct from it. */
const BADGE_TONE_VARS: Record<ReturnType<typeof statusBadgeTone>, { color: string; background: string }> = {
  wip: { color: "var(--color-status-neutral)", background: "var(--color-status-neutral-tint-10)" },
  tr: { color: "var(--color-status-warn)", background: "var(--color-status-warn-tint-10)" },
  cr: { color: "var(--color-status-info)", background: "var(--color-status-info-tint-10)" },
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
    <div className="flex flex-col gap-3 p-3">
      {/* Version */}
      <DeliverBlock eyebrow="Version" status={versionStatusLine(version)}>
        <Button variant="primary" disabled={isBusy} onClick={() => setView("save_version")}>
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
                onClick={() => onOpenVersion(entry.path, entry.filename)}
                title={`Open ${entry.filename}`}
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
