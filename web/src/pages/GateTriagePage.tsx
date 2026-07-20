import { CheckCircle2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/form/Button";
import { FieldRow } from "../components/form/FieldRow";
import { FormPageShell } from "../components/form/FormPageShell";
import { TextArea } from "../components/form/TextArea";
import { TextInput } from "../components/form/TextInput";
import { GateCheckRow } from "../components/GateChecks";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Section } from "../components/Section";
import { fetchGateState, submitGate } from "../lib/api";
import { useToast } from "../lib/toast";
import type { GateBucket, GateCheck, GateState, GateStateResult } from "../types";

type PageState = { kind: "loading" } | GateStateResult;
type ViewState = "form" | "resolved" | "cancelled";

const BUCKET_TITLE: Record<GateBucket, string> = {
  blocking: "Blocking",
  fixable: "Fixable",
  advisory: "Advisory",
};
const BUCKET_ORDER: GateBucket[] = ["blocking", "fixable", "advisory"];

/** Quality Gate triage — mirrors `gate.py` + `ui/dialogs.py`
 * `GateTriageDialog` (see web_ops.py `_op_form_gate_state/_submit`'s
 * docstrings). Checks group into Blocking/Fixable/Advisory buckets; three
 * mutating actions (Fix auto-fixables / Accept… / Proceed anyway) plus
 * Cancel — no per-row Override in v1, matching the op contract exactly. */
export function GateTriagePage() {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [view, setView] = useState<ViewState>("form");
  const [busy, setBusy] = useState(false);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [author, setAuthor] = useState("");
  const [reason, setReason] = useState("");
  const [acceptError, setAcceptError] = useState<string | null>(null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchGateState().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") {
    return <ErrorState title="Couldn't load the Quality Gate" message={state.message} onRetry={load} />;
  }
  if (state.kind === "empty") {
    return <EmptyState title="No document open" reason={state.reason} />;
  }

  const data: GateState = state.data;

  function applyState(next: GateState) {
    setState({ kind: "ok", data: next });
    setSelected(new Set());
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runAction(action: "fix_all" | "proceed" | "cancel") {
    setBusy(true);
    const response = await submitGate({ action });
    setBusy(false);

    if (!response.ok) {
      toast({ message: response.error || "Action failed.", variant: "warn" });
      return;
    }
    if (action === "fix_all") {
      toast({
        message: response.fixed?.length ? `Fixed ${response.fixed.length} check(s).` : "Nothing to fix.",
        variant: "success",
      });
      if (response.state) applyState(response.state);
      return;
    }
    if (action === "proceed") {
      if (response.proceed) {
        toast({ message: "Gate passed — you may continue.", variant: "success" });
        setView("resolved");
      } else {
        toast({ message: "Blocking checks remain — fix or accept them first.", variant: "warn" });
        if (response.state) applyState(response.state);
      }
      return;
    }
    // cancel
    toast({ message: "Gate cancelled.", variant: "info" });
    setView("cancelled");
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
    setBusy(true);
    const response = await submitGate({
      action: "accept",
      ids: Array.from(selected),
      author: author.trim(),
      reason: reason.trim(),
    });
    setBusy(false);

    if (!response.ok) {
      setAcceptError(response.error || "Accept failed.");
      return;
    }
    toast({ message: "Accepted into the baseline.", variant: "success" });
    if (response.state) applyState(response.state);
    setAcceptOpen(false);
    setAuthor("");
    setReason("");
  }

  if (view !== "form") {
    return (
      <FormPageShell title={view === "resolved" ? "Gate Passed" : "Gate Cancelled"}>
        <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
          <CheckCircle2 size={32} style={{ color: "var(--color-status-pass)" }} aria-hidden="true" />
          <p className="text-body-lg" style={{ color: "var(--color-ink)" }}>
            {view === "resolved"
              ? "The quality gate is resolved."
              : "The gate was cancelled — no further action was taken."}
          </p>
          {/* TODO(Phase 4 Task 4): the FormDialog host can auto-close this window
             and resume the guarded save/collect flow once it exists — a web page
             cannot close a native C4D dialog or trigger that flow from JS. */}
          <p className="text-caption mt-2" style={{ color: "var(--color-ink-secondary)" }}>
            You can close this window.
          </p>
        </div>
      </FormPageShell>
    );
  }

  if (data.checks.length === 0) {
    return (
      <FormPageShell title="Quality Gate">
        <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
          <CheckCircle2 size={32} style={{ color: "var(--color-status-pass)" }} aria-hidden="true" />
          <p className="text-body-lg" style={{ color: "var(--color-ink)" }}>
            No blocking or advisory checks — the gate is clear.
          </p>
        </div>
      </FormPageShell>
    );
  }

  const byBucket: Record<GateBucket, GateCheck[]> = { blocking: [], fixable: [], advisory: [] };
  for (const check of data.checks) byBucket[check.bucket].push(check);
  const hasFixable = byBucket.fixable.length > 0;

  return (
    <FormPageShell
      title="Quality Gate"
      meta={
        <p
          className="text-caption mt-1.5"
          style={{ color: data.passed ? "var(--color-status-pass)" : "var(--color-status-fail)" }}
        >
          {data.passed ? "Passed" : `${data.checks.length} check(s) need attention`}
          {data.sidecar_invalid && <span style={{ color: "var(--color-status-warn)" }}> · baseline sidecar unreadable</span>}
        </p>
      }
      footer={
        <div
          className="flex flex-col gap-3 border-t px-4 py-3"
          style={{ borderColor: "var(--color-hairline-strong)", backgroundColor: "var(--color-surface-1)" }}
        >
          {acceptOpen && (
            <div
              className="flex flex-col gap-3 rounded-lg border p-3"
              style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-2)" }}
            >
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                {selected.size > 0 ? `${selected.size} check(s) selected above` : "Select checks above to accept"}
              </p>
              <FieldRow label="Author" htmlFor="gate-author">
                <TextInput id="gate-author" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Your name" />
              </FieldRow>
              <FieldRow label="Reason" htmlFor="gate-reason" error={acceptError}>
                <TextArea
                  id="gate-reason"
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why is this acceptable?"
                />
              </FieldRow>
              <div className="flex justify-end gap-2">
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => {
                    setAcceptOpen(false);
                    setAcceptError(null);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  disabled={busy || !author.trim() || !reason.trim() || selected.size === 0}
                  onClick={confirmAccept}
                >
                  Confirm Accept
                </Button>
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => runAction("cancel")}>
              Cancel
            </Button>
            <Button variant="secondary" disabled={busy || !hasFixable} onClick={() => runAction("fix_all")}>
              Fix auto-fixables
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setAcceptOpen((v) => !v)}>
              Accept…
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => runAction("proceed")}>
              Proceed anyway
            </Button>
          </div>
        </div>
      }
    >
      {BUCKET_ORDER.map((bucket) =>
        byBucket[bucket].length > 0 ? (
          <Section key={bucket} title={BUCKET_TITLE[bucket]}>
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
          </Section>
        ) : null,
      )}
    </FormPageShell>
  );
}
