import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../form/Button";
import { fetchHubPreflight, fetchPaletteActions, runPaletteAction } from "../../lib/api";
import { confirmBarButtons } from "../../lib/confirmBar";
import { SnapshotChannel } from "../../lib/snapshot";
import { useToast } from "../../lib/toast";
import type {
  PaletteAction,
  PaletteActionsResult,
  QcCheck,
  QcReportResult,
} from "../../types";

type PageState = { kind: "loading" } | QcReportResult;

export interface HubPreflightSnapshot {
  state: QcReportResult;
  actions: PaletteAction[];
}

/** Read QC and its matching fix availability as one latest-wins unit. */
// Exported so the race regression exercises the exact loader used below.
// oxlint-disable-next-line react/only-export-components
export async function loadHubPreflightSnapshot(
  channel: SnapshotChannel,
  commit: (snapshot: HubPreflightSnapshot) => void,
  readPreflight: () => Promise<QcReportResult> = fetchHubPreflight,
  readActions: () => Promise<PaletteActionsResult> = fetchPaletteActions,
): Promise<void> {
  await channel.load(
    async () => {
      const [state, actionResult] = await Promise.all([readPreflight(), readActions()]);
      return {
        stamp: null,
        result: {
          kind: "ok" as const,
          data: {
            state,
            actions: actionResult.kind === "ok" ? actionResult.data : [],
          },
        },
      };
    },
    ({ result }) => {
      if (result.kind === "ok") commit(result.data);
    },
  );
}

/** Maps a preflight-fixable QC check id (`qc/registry.py`) to the palette
 * Quick Fix action id that fixes it (`PALETTE_ACTIONS` in webbridge.py) —
 * the same four fixes the Command Palette exposes. */
const FIX_ACTION_BY_CHECK: Record<string, string> = {
  lights: "fix_lights",
  cam: "fix_cameras",
  unused_mats: "fix_materials",
  fps_range: "fix_fps",
};

/** Compact QC preflight strip for the Hub's Deliver section — score line +
 * fail/warn chips, inline Fix buttons for the four batchable checks (reusing
 * `runPaletteAction`, including its confirm-required round trip — see
 * PalettePage.tsx's `confirmAction` handling, copied here), and a
 * "Details…" button that opens the native Reports window on QC
 * (`open_reports_qc`). Purely advisory: it never blocks Deliver — the
 * inline Quality Gate (`HubDeliverSection`) is what actually gates a
 * `gates_enabled` collect. */
export function HubPreflightStrip({
  inventoryRevision,
  onFixed,
}: {
  inventoryRevision: number;
  onFixed?: () => void;
}) {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [actions, setActions] = useState<PaletteAction[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<PaletteAction | null>(null);
  const preflightChannel = useRef(new SnapshotChannel());

  const load = useCallback(() => {
    setState({ kind: "loading" });
    setConfirmAction(null);
    void loadHubPreflightSnapshot(preflightChannel.current, (snapshot) => {
      setState(snapshot.state);
      setActions(snapshot.actions);
    });
  }, []);

  useEffect(() => {
    const channel = preflightChannel.current;
    load();
    return () => channel.invalidate();
  }, [inventoryRevision, load]);

  async function runFix(action: PaletteAction, confirm?: boolean) {
    if (action.requires_confirm && !confirm) {
      setConfirmAction(action);
      return;
    }
    setBusyId(action.id);
    const response = await runPaletteAction(action.id, confirm);
    setBusyId(null);
    setConfirmAction(null);

    if (!response.ok) {
      toast({ message: response.error || "Fix failed.", variant: "warn" });
      return;
    }
    toast({ message: response.message || "Fixed.", variant: "success" });
    load();
    onFixed?.();
  }

  function openDetails() {
    runPaletteAction("open_reports_qc").then((response) => {
      if (!response.ok) toast({ message: response.error || "Couldn't open Reports.", variant: "warn" });
    });
  }

  const strip = (
    className: string,
    children: ReactNode,
  ) => (
    <div
      className={`flex flex-wrap items-center gap-2 rounded-lg border p-3 ${className}`}
      style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
    >
      {children}
    </div>
  );

  if (state.kind === "loading") {
    return strip(
      "",
      <>
        <Loader2 className="animate-spin" size={16} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-label="Loading" />
        <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Checking QC status…
        </span>
      </>,
    );
  }

  if (state.kind === "error" || state.kind === "empty") {
    const message = state.kind === "error" ? state.message : state.reason;
    return strip(
      "",
      <>
        <AlertTriangle size={16} style={{ color: "var(--color-status-warn)" }} aria-hidden="true" />
        <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          {message}
        </span>
      </>,
    );
  }

  const data = state.data;
  const failing = data.checks.filter((check: QcCheck) => check.status === "fail");
  const scoreTone = failing.length === 0 ? "var(--color-status-pass)" : "var(--color-status-fail)";

  if (confirmAction) {
    // Same verb/destructive/order policy as the panel's ConfirmBar
    // (`lib/confirmBar.ts`) — this strip just keeps its own inline layout
    // (buttons pushed right with `ml-auto`) instead of the floating bar.
    return strip(
      "",
      <>
        <span className="text-body" style={{ color: "var(--color-ink)" }}>
          {confirmAction.confirm_label}
        </span>
        <div className="ml-auto flex gap-2">
          {confirmBarButtons({
            confirmVerb: confirmAction.confirm_verb,
            destructive: confirmAction.destructive,
          }).map((button) => (
            <Button
              key={button.role}
              variant={button.variant}
              disabled={busyId !== null}
              onClick={button.role === "cancel" ? () => setConfirmAction(null) : () => runFix(confirmAction, true)}
            >
              {button.label}
            </Button>
          ))}
        </div>
      </>,
    );
  }

  return strip(
    "",
    <>
      <span className="text-body-lg shrink-0" style={{ color: scoreTone }}>
        QC {data.score.score}
      </span>
      {failing.length === 0 && (
        <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          No failing checks.
        </span>
      )}
      {failing.map((check) => {
        const fixId = check.has_fix ? FIX_ACTION_BY_CHECK[check.id] : undefined;
        const action = fixId ? actions.find((a) => a.id === fixId) : undefined;
        const tint = check.severity === "WARN" ? "var(--color-status-warn-tint-10)" : "var(--color-status-fail-tint-10)";
        const color = check.severity === "WARN" ? "var(--color-status-warn)" : "var(--color-status-fail)";
        return (
          <span
            key={check.id}
            className="text-label inline-flex items-center gap-1.5 rounded-sm px-1.5 py-0.5"
            style={{ backgroundColor: tint, color }}
          >
            {check.label} · {check.new ?? check.count ?? 0} new
            {action && (
              <button
                type="button"
                disabled={busyId !== null || !action.enabled}
                onClick={() => runFix(action)}
                className="text-label ml-1 rounded-sm px-1 underline disabled:cursor-not-allowed disabled:opacity-50"
                style={{ color }}
                title={action.enabled ? undefined : action.reason || undefined}
              >
                Fix
              </button>
            )}
          </span>
        );
      })}
      <Button variant="secondary" className="ml-auto" onClick={openDetails}>
        Details…
      </Button>
    </>,
  );
}
