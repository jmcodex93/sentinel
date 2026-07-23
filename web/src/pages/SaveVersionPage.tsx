import { CheckCircle2 } from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/form/Button";
import { FieldRow } from "../components/form/FieldRow";
import { FormPageShell } from "../components/form/FormPageShell";
import { SegmentedControl } from "../components/form/SegmentedControl";
import { SubmitBar } from "../components/form/SubmitBar";
import { TextArea } from "../components/form/TextArea";
import { TextInput } from "../components/form/TextInput";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { fetchSaveVersionState, submitSaveVersion } from "../lib/api";
import { useToast } from "../lib/toast";
import type { SaveVersionState, SaveVersionStateResult, SaveVersionSubmitResponse } from "../types";

type PageState = { kind: "loading" } | SaveVersionStateResult;

// Segment value standing in for "the artist typed a custom status instead
// of picking WIP/TR/CR/FINAL" — distinct from any real suffix those four
// options ever use (WIP's own suffix is "", not this).
const CUSTOM = "__custom__";

/** Save Version — mirrors `ui/dialogs.py` `SaveVersionDialog` exactly (see
 * web_ops.py `_op_form_save_version_state/_submit`'s docstrings): required
 * comment, WIP/TR/CR/FINAL/Custom status, a non-blocking inline "final in
 * comment" hint, and a last-version + QC score header strip replacing the
 * native panel's "Last version" pillbox.
 *
 * `onBack`/`onDone` are optional — absent when hosted one-per-window by
 * `FormDialog` (unchanged behavior), present when absorbed as an in-panel
 * sub-view by the Deliver section (Fase 6.3 Task 5): `onBack` renders a
 * "← Deliver" control, `onDone` fires after a successful save so the panel
 * can navigate back without the artist ever seeing this page's own
 * "Version Saved" success screen. */
export function SaveVersionPage({
  onBack,
  onDone,
}: { onBack?: () => void; onDone?: () => void } = {}) {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [comment, setComment] = useState("");
  // Segment value: "WIP" | "TR" | "CR" | "FINAL" | CUSTOM — WIP's real
  // filename suffix is "" (see status_options), remapped to the literal
  // "WIP" here purely as a segment id distinct from an unset string.
  const [status, setStatus] = useState<string>("WIP");
  const [customStatus, setCustomStatus] = useState("");
  const [pending, setPending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Kept separate from `submitError` (the SubmitBar's generic banner): an
  // empty comment is a field-level problem, so it renders under the Comment
  // field itself via FieldRow's own error slot (and drives TextArea's red
  // border) rather than as a submit-level banner.
  const [commentError, setCommentError] = useState<string | null>(null);
  const [result, setResult] = useState<SaveVersionSubmitResponse | null>(null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchSaveVersionState().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") {
    return <ErrorState title="Couldn't load Save Version" message={state.message} onRetry={load} />;
  }
  if (state.kind === "empty") {
    return <EmptyState title="No document open" reason={state.reason} />;
  }

  const data: SaveVersionState = state.data;

  if (result?.ok) {
    return (
      <FormPageShell title="Version Saved">
        <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
          <CheckCircle2 size={32} style={{ color: "var(--color-status-pass)" }} aria-hidden="true" />
          <p className="text-body-lg" style={{ color: "var(--color-ink)" }}>
            {result.message || `Saved ${result.version ?? "version"}`}
          </p>
          {result.path && (
            <p className="text-caption font-mono" style={{ color: "var(--color-ink-secondary)" }}>
              {result.path}
            </p>
          )}
          {/* TODO(Phase 4 Task 4): the FormDialog host can auto-close this window
             on success once it exists — a web page cannot close a native C4D
             dialog from JS, so for now the artist closes it manually. */}
          <p className="text-caption mt-2" style={{ color: "var(--color-ink-secondary)" }}>
            You can close this window.
          </p>
        </div>
      </FormPageShell>
    );
  }

  const statusOptions = [
    ...data.status_options.map((option) => ({ value: option.suffix || "WIP", label: option.suffix || "WIP" })),
    { value: CUSTOM, label: "Custom" },
  ];
  const isCustom = status === CUSTOM;
  const activePreview = !isCustom
    ? data.status_options.find((option) => (option.suffix || "WIP") === status)?.preview_filename
    : undefined;
  const finalHintVisible = /final/i.test(comment);
  const trimmedComment = comment.trim();

  async function handleSubmit(event?: FormEvent) {
    event?.preventDefault();
    setSubmitError(null);
    setCommentError(null);
    if (!trimmedComment) {
      setCommentError("Please enter a comment describing this version.");
      return;
    }
    setPending(true);
    const response = await submitSaveVersion({
      comment: trimmedComment,
      status: isCustom ? "" : status === "WIP" ? "" : status,
      custom_status: isCustom ? customStatus : "",
    });
    setPending(false);

    if (!response.ok) {
      setSubmitError(response.error || "Save failed.");
      return;
    }
    setResult(response);
    toast({ message: response.message || `Saved ${response.version ?? "version"}`, variant: "success" });
    if (response.warning) {
      toast({ message: response.warning, variant: "warn" });
    }
    onDone?.();
  }

  return (
    <FormPageShell
      embedded={Boolean(onBack)}
      title="Save Version"
      meta={
        <div className="mt-1.5 flex flex-wrap items-center gap-3">
          <span className="text-caption truncate" style={{ color: "var(--color-ink-secondary)" }}>
            {data.scene}
          </span>
          {data.last_version && (
            <span
              className="text-caption shrink-0 rounded-sm px-1.5 py-0.5"
              style={{ backgroundColor: "var(--color-surface-2)", color: "var(--color-ink-secondary)" }}
            >
              Last: {data.last_version.version_label} {data.last_version.status_label}
              {data.last_version.time_label ? ` · ${data.last_version.time_label}` : ""}
            </span>
          )}
          <span
            className="text-caption shrink-0"
            style={{ color: data.qc.pass ? "var(--color-status-pass)" : "var(--color-status-warn)" }}
          >
            QC {data.qc.score || "—"}
          </span>
        </div>
      }
      footer={
        <SubmitBar
          submitLabel="Save Version"
          pending={pending}
          disabled={!trimmedComment}
          onSubmit={handleSubmit}
          error={submitError}
        />
      }
    >
      {onBack && (
        <Button variant="secondary" className="mb-3" onClick={onBack}>
          ← Deliver
        </Button>
      )}
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <FieldRow label="Comment" htmlFor="save-version-comment" error={commentError}>
          <TextArea
            id="save-version-comment"
            rows={4}
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
              if (commentError) setCommentError(null);
            }}
            placeholder="What changed in this version?"
            invalid={Boolean(commentError)}
          />
          {finalHintVisible && (
            <p className="text-caption mt-1.5" style={{ color: "var(--color-status-warn)" }}>
              Tip: instead of writing "final" in the comment, use the "Final Delivery" status below — it bakes
              the marker into the filename and the history log.
            </p>
          )}
        </FieldRow>

        <FieldRow label="Status" hint={activePreview ? `Will save as: ${activePreview}` : undefined}>
          <SegmentedControl options={statusOptions} value={status} onChange={setStatus} />
          {isCustom && (
            <TextInput
              className="mt-2"
              value={customStatus}
              onChange={(e) => setCustomStatus(e.target.value)}
              placeholder="Custom status (letters/numbers only)"
            />
          )}
        </FieldRow>
      </form>
    </FormPageShell>
  );
}
