import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DeliverySummaryView } from "../DeliverySummaryView";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { FieldRow } from "../form/FieldRow";
import { TextArea } from "../form/TextArea";
import { TextInput } from "../form/TextInput";
import { GateCheckRow } from "../GateChecks";
import {
  fetchGateState,
  fetchHubJobStatus,
  postHubPickPath,
  startHubCollect,
  submitGate,
} from "../../lib/api";
import { useToast } from "../../lib/toast";
import type { GateBucket, GateCheck, GateState, HubCollectResult, HubJobStatus } from "../../types";

type Phase = "idle" | "gate" | "running" | "done" | "error";

const BUCKET_TITLE: Record<GateBucket, string> = {
  blocking: "Blocking",
  fixable: "Fixable",
  advisory: "Advisory",
};
const BUCKET_ORDER: GateBucket[] = ["blocking", "fixable", "advisory"];

const JOB_POLL_MS = 500;

/** Hub Deliver section — the SPA equivalent of the panel's Collect Scene
 * button, with the Quality Gate and job progress inline instead of a chain
 * of native dialogs. State machine: idle → gate (inline, only on
 * `gate_blocked`) → running (polling the collect job) → done | error.
 * See docs/superpowers/plans/2026-07-20-hub-spa.md Task 11 for the full
 * contract. */
export function HubDeliverSection({
  missingCount,
  onInventoryRefresh,
}: {
  missingCount: number;
  onInventoryRefresh: () => void;
}) {
  const { toast } = useToast();
  const [phase, setPhase] = useState<Phase>("idle");
  const [target, setTarget] = useState("");
  const [zip, setZip] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<HubJobStatus | null>(null);

  // Inline Quality Gate triage — mirrors GateTriagePage.tsx's own state,
  // scoped to this section (no navigation to a second window).
  const [gateState, setGateState] = useState<GateState | null>(null);
  const [gateBusy, setGateBusy] = useState(false);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [author, setAuthor] = useState("");
  const [reason, setReason] = useState("");
  const [acceptError, setAcceptError] = useState<string | null>(null);

  // Latest-value refs for the poll effect below — it must stay scoped to
  // [phase, jobId] only (a new `toast`/`onInventoryRefresh` identity on
  // every parent re-render must not tear down and restart the 500ms
  // interval), same reasoning as HubPage.tsx's stampRef/pendingRef.
  const toastRef = useRef(toast);
  useEffect(() => {
    toastRef.current = toast;
  }, [toast]);
  const onInventoryRefreshRef = useRef(onInventoryRefresh);
  useEffect(() => {
    onInventoryRefreshRef.current = onInventoryRefresh;
  }, [onInventoryRefresh]);

  async function startCollect(gateAck: boolean) {
    setBusy(true);
    setError(null);
    const res = await startHubCollect(target.trim(), zip, gateAck);
    setBusy(false);

    if (!res.ok) {
      if (res.error === "gate_blocked") {
        const gateResult = await fetchGateState();
        if (gateResult.kind === "ok") {
          setGateState(gateResult.data);
          setSelected(new Set());
          setPhase("gate");
        } else {
          setError(gateResult.kind === "error" ? gateResult.message : gateResult.reason);
          setPhase("error");
        }
        return;
      }
      setError(res.error || "Couldn't start delivery.");
      setPhase("error");
      return;
    }

    if (!res.job_id) {
      setError("Server did not return a job id.");
      setPhase("error");
      return;
    }
    setJobId(res.job_id);
    setJobStatus(null);
    setPhase("running");
  }

  function handleDeliverClick() {
    if (!target.trim()) {
      toast({ message: "Choose a target folder first.", variant: "warn" });
      return;
    }
    startCollect(false);
  }

  async function handleChoose() {
    const picked = await postHubPickPath(true, "Choose delivery folder");
    if (picked.ok && picked.path) setTarget(picked.path);
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runGateAction(action: "fix_all" | "proceed" | "cancel") {
    setGateBusy(true);
    const response = await submitGate({ action });
    setGateBusy(false);

    if (!response.ok) {
      toast({ message: response.error || "Gate action failed.", variant: "warn" });
      return;
    }
    if (action === "fix_all") {
      toast({
        message: response.fixed?.length ? `Fixed ${response.fixed.length} check(s).` : "Nothing to fix.",
        variant: "success",
      });
      if (response.state) {
        setGateState(response.state);
        setSelected(new Set());
        if (response.state.passed) {
          startCollect(true);
        }
      }
      return;
    }
    if (action === "proceed") {
      if (response.proceed) {
        startCollect(true);
      } else {
        toast({ message: "Blocking checks remain — fix or accept them first.", variant: "warn" });
        if (response.state) setGateState(response.state);
      }
      return;
    }
    // cancel
    toast({ message: "Delivery cancelled.", variant: "info" });
    setPhase("idle");
  }

  async function confirmAccept() {
    setAcceptError(null);
    if (!author.trim() || !reason.trim()) {
      setAcceptError("Author and reason are required to accept violations.");
      return;
    }
    if (selected.size === 0) {
      setAcceptError("Select at least one check to accept.");
      return;
    }
    setGateBusy(true);
    const response = await submitGate({
      action: "accept",
      ids: Array.from(selected),
      author: author.trim(),
      reason: reason.trim(),
    });
    setGateBusy(false);

    if (!response.ok) {
      setAcceptError(response.error || "Accept failed.");
      return;
    }
    toast({ message: "Accepted into the baseline.", variant: "success" });
    setAcceptOpen(false);
    setAuthor("");
    setReason("");
    setSelected(new Set());
    if (response.state) {
      setGateState(response.state);
      if (response.state.passed) {
        startCollect(true);
      }
    }
  }

  // Job progress polling — 500ms while `phase === "running"`; the effect's
  // own cleanup (fired when `phase` changes away from "running") is what
  // stops polling, so a terminal `done`/`error` state never needs its own
  // clearInterval bookkeeping.
  useEffect(() => {
    if (phase !== "running" || !jobId) return;
    let cancelled = false;

    async function poll() {
      const status = await fetchHubJobStatus(jobId!);
      if (cancelled) return;
      setJobStatus(status);

      if (status.error) {
        setError(status.error);
        setPhase("error");
        return;
      }
      if (status.state === "done") {
        setPhase("done");
        if (status.result) {
          toastRef.current({ message: "Delivery complete.", variant: "success" });
        } else {
          toastRef.current({ message: "Delivery complete (mock — no report data).", variant: "info" });
        }
        onInventoryRefreshRef.current();
        return;
      }
      if (status.state === "error") {
        setError(status.detail || "Delivery failed.");
        setPhase("error");
      }
    }

    poll();
    const id = window.setInterval(poll, JOB_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // Intentionally scoped to [phase, jobId] only — `toast`/`onInventoryRefresh`
    // are read inside but must not restart the interval on every parent
    // re-render (same reasoning as HubPage.tsx's stampRef/pendingRef refs).
  }, [phase, jobId]);

  function handleRetry() {
    setError(null);
    if (phase === "error" && jobStatus) {
      // A job that reached the server and then failed — restart clean.
      setJobId(null);
      setJobStatus(null);
    }
    startCollect(false);
  }

  function handleDeliverAgain() {
    setPhase("idle");
    setJobId(null);
    setJobStatus(null);
    setError(null);
    setGateState(null);
  }

  const cardStyle = {
    backgroundColor: "var(--color-surface-1)",
    borderColor: "var(--color-hairline)",
  };

  if (phase === "idle") {
    return (
      <div className="flex flex-col gap-3 rounded-lg border p-4" style={cardStyle}>
        {missingCount > 0 && (
          <div
            className="flex items-center gap-2 rounded-md px-3 py-2"
            style={{ backgroundColor: "var(--color-status-warn-tint-10)" }}
          >
            <AlertTriangle size={14} style={{ color: "var(--color-status-warn)" }} aria-hidden="true" />
            <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
              {missingCount} asset{missingCount === 1 ? "" : "s"} missing — delivery will proceed, the manifest
              seals them as missing.
            </p>
          </div>
        )}
        <FieldRow label="Deliver to" htmlFor="hub-deliver-target">
          <div className="flex gap-2">
            <TextInput
              id="hub-deliver-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="Choose a delivery folder…"
            />
            <Button variant="secondary" onClick={handleChoose}>
              Choose…
            </Button>
          </div>
        </FieldRow>
        <Checkbox id="hub-deliver-zip" checked={zip} onChange={setZip} label="Also create a .zip" />
        <div className="flex justify-end">
          <Button variant="primary" disabled={busy} onClick={handleDeliverClick}>
            Deliver
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "gate" && gateState) {
    const byBucket: Record<GateBucket, GateCheck[]> = { blocking: [], fixable: [], advisory: [] };
    for (const check of gateState.checks) byBucket[check.bucket].push(check);
    const hasFixable = byBucket.fixable.length > 0;

    return (
      <div className="flex flex-col gap-3 rounded-lg border p-4" style={cardStyle}>
        <p className="text-body-lg" style={{ color: "var(--color-status-fail)" }}>
          Quality Gate — {gateState.checks.length} check(s) need attention
        </p>
        {gateState.sidecar_invalid && (
          <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
            Baseline sidecar unreadable.
          </p>
        )}

        {BUCKET_ORDER.map((bucket) =>
          byBucket[bucket].length > 0 ? (
            <div key={bucket}>
              <h3 className="text-subhead mb-2" style={{ color: "var(--color-ink)" }}>
                {BUCKET_TITLE[bucket]}
              </h3>
              <div className="rounded-lg border" style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}>
                {byBucket[bucket].map((check) => (
                  <GateCheckRow
                    key={check.check_id}
                    check={check}
                    selectable={acceptOpen}
                    selected={selected.has(check.check_id)}
                    onToggleSelect={toggleSelect}
                  />
                ))}
              </div>
            </div>
          ) : null,
        )}

        {acceptOpen && (
          <div className="flex flex-col gap-3 rounded-lg border p-3" style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-2)" }}>
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
              {selected.size > 0 ? `${selected.size} check(s) selected above` : "Select checks above to accept"}
            </p>
            <FieldRow label="Author" htmlFor="hub-gate-author">
              <TextInput id="hub-gate-author" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Your name" />
            </FieldRow>
            <FieldRow label="Reason" htmlFor="hub-gate-reason" error={acceptError}>
              <TextArea
                id="hub-gate-reason"
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why is this acceptable?"
              />
            </FieldRow>
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={gateBusy}
                onClick={() => {
                  setAcceptOpen(false);
                  setAcceptError(null);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={gateBusy || !author.trim() || !reason.trim() || selected.size === 0}
                onClick={confirmAccept}
              >
                Confirm Accept
              </Button>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="secondary" disabled={gateBusy} onClick={() => runGateAction("cancel")}>
            Cancel
          </Button>
          <Button variant="secondary" disabled={gateBusy || !hasFixable} onClick={() => runGateAction("fix_all")}>
            Fix auto-fixables
          </Button>
          <Button variant="secondary" disabled={gateBusy} onClick={() => setAcceptOpen((v) => !v)}>
            Accept…
          </Button>
          <Button variant="primary" disabled={gateBusy} onClick={() => runGateAction("proceed")}>
            Proceed anyway
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "running") {
    const pct = jobStatus?.pct ?? 0;
    return (
      <div className="flex flex-col gap-3 rounded-lg border p-4" style={cardStyle}>
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {jobStatus?.phase || "Delivering…"}
        </p>
        {jobStatus?.detail && (
          <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
            {jobStatus.detail}
          </p>
        )}
        <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ backgroundColor: "var(--color-surface-2)" }}>
          <div
            className="h-full rounded-full transition-all duration-150 ease-out"
            style={{ width: `${Math.min(100, Math.max(0, pct))}%`, backgroundColor: "var(--color-status-pass)" }}
          />
        </div>
      </div>
    );
  }

  if (phase === "done") {
    // This section only ever starts a "collect" job (`startHubCollect`
    // above) — the `result` union only widened (Fase 5.2) because
    // `HubJobStatus` is now shared with the Hub's shrink job too, whose
    // `HubShrinkResult` never reaches this code path.
    const result = (jobStatus?.result as HubCollectResult | null) ?? null;
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 rounded-lg border p-4" style={cardStyle}>
          <CheckCircle2 size={16} style={{ color: "var(--color-status-pass)" }} aria-hidden="true" />
          <p className="text-body" style={{ color: "var(--color-ink)" }}>
            {result ? "Delivery complete." : "Delivery complete (mock — no report data)."}
          </p>
          <Button variant="secondary" className="ml-auto" onClick={handleDeliverAgain}>
            Deliver Again
          </Button>
        </div>
        {result && (
          <div className="overflow-hidden rounded-lg border" style={cardStyle}>
            <DeliverySummaryView data={result.report} />
            <div className="flex flex-col gap-1 border-t px-4 py-3" style={{ borderColor: "var(--color-hairline)" }}>
              {result.zip && (
                <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  Zip: {result.zip.zip_path} · {result.zip.files} file(s)
                </p>
              )}
              {result.zip_error && (
                <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
                  Zip failed: {result.zip_error}
                </p>
              )}
              {result.pending_todos > 0 && (
                <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
                  {result.pending_todos} pending TODO{result.pending_todos === 1 ? "" : "s"}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // error
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4" style={cardStyle}>
      <div className="flex items-center gap-2">
        <AlertTriangle size={16} style={{ color: "var(--color-status-fail)" }} aria-hidden="true" />
        <p className="text-body" style={{ color: "var(--color-status-fail)" }}>
          {error || "Delivery failed."}
        </p>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={handleDeliverAgain}>
          Back
        </Button>
        <Button variant="primary" disabled={busy} onClick={handleRetry}>
          Retry
        </Button>
      </div>
    </div>
  );
}
