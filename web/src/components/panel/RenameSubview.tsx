import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { SegmentedControl } from "../form/SegmentedControl";
import { TextInput } from "../form/TextInput";
import { SectionGroup } from "../SectionGroup";
import { fetchPanelStamp, fetchRenamePreview, postRenameApply } from "../../lib/api";
import { DEFAULT_RENAME_OPS, renameToast } from "../../lib/panelRename";
import type { RenameOps, RenameSource } from "../../lib/panelRename";
import { useToast } from "../../lib/toast";
import type { RenamePreviewResult } from "../../types";

/** Inline (muted, non-toast) copy for a preview that can't be computed —
 * these are normal editing states, not failures, so they render as quiet
 * text under the fields instead of interrupting with a toast. */
const PREVIEW_EMPTY_COPY: Record<string, string> = {
  no_selection: "Select something to rename",
  nothing_to_do: "Fill in a field",
};

/** Batch Rename sub-view (v1.31) — self-contained like the absorbed form
 * pages: owns its preview fetches, its stamp poll and its apply. The preview
 * is ALWAYS the server's `rename_plan` (no client-side name computation
 * anywhere — WYSIWYG with apply by construction). Refetch triggers: 300ms
 * debounce on any field/source edit, plus a 2s `fetchPanelStamp` poll so a
 * selection change in C4D flows into the preview without touching the SPA. */
export function RenameSubview({ onBack }: { onBack: () => void }) {
  const { toast } = useToast();
  const [source, setSource] = useState<RenameSource>("objects");
  const [ops, setOps] = useState<RenameOps>(DEFAULT_RENAME_OPS);
  const [preview, setPreview] = useState<RenamePreviewResult | null>(null);
  const [applying, setApplying] = useState(false);

  // Monotonic sequence: only the LATEST in-flight preview may land (a slow
  // stale response must never overwrite a newer plan).
  const seqRef = useRef(0);
  const stampRef = useRef<string | null>(null);
  // Latest source/ops for the stamp poll, without re-arming the interval.
  const paramsRef = useRef({ source, ops });
  paramsRef.current = { source, ops };

  const loadPreview = useCallback(async (src: RenameSource, o: RenameOps) => {
    const seq = ++seqRef.current;
    const result = await fetchRenamePreview(src, o);
    if (seq === seqRef.current) setPreview(result);
  }, []);

  // 300ms debounce on any field/source change.
  useEffect(() => {
    const timer = setTimeout(() => void loadPreview(source, ops), 300);
    return () => clearTimeout(timer);
  }, [source, ops, loadPreview]);

  // 2s stamp poll — the selection in C4D is part of the preview's input, but
  // selection changes never reach the SPA on their own; the shared panel
  // stamp does move, so refetch when it changes.
  useEffect(() => {
    const interval = setInterval(async () => {
      // Same guard as PanelPage's poll: a hidden webview shouldn't keep
      // hitting the server (review Minor).
      if (document.visibilityState !== "visible") return;
      const stamp = await fetchPanelStamp();
      if (stamp !== null && stamp !== stampRef.current) {
        stampRef.current = stamp;
        const { source: src, ops: o } = paramsRef.current;
        void loadPreview(src, o);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [loadPreview]);

  const setOp = <K extends keyof RenameOps>(key: K, value: RenameOps[K]) =>
    setOps((prev) => ({ ...prev, [key]: value }));

  const handleApply = async () => {
    setApplying(true);
    try {
      const result = await postRenameApply(source, ops);
      toast(renameToast(source, result));
      await loadPreview(source, ops);
    } finally {
      setApplying(false);
    }
  };

  const rows = preview?.ok ? (preview.rows ?? []) : [];
  const emptyReason = preview && !preview.ok
    ? (PREVIEW_EMPTY_COPY[preview.error ?? ""] ?? "Preview unavailable.")
    : null;
  const canApply = !applying && !!preview?.ok && rows.length > 0;

  const numberField = (label: string, key: "num_start" | "num_padding") => (
    <div className="flex items-center gap-2">
      <label className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
        {label}
      </label>
      <div className="w-16">
        <TextInput
          type="number"
          value={ops[key]}
          onChange={(e) => setOp(key, parseInt(e.target.value || "0", 10))}
        />
      </div>
    </div>
  );

  return (
    <div className="flex flex-col p-3">
      <div className="flex items-center justify-between">
        <Button variant="secondary" onClick={onBack}>
          ← Tools
        </Button>
        <SegmentedControl
          options={[
            { value: "objects", label: "Objects" },
            { value: "materials", label: "Materials" },
          ]}
          value={source}
          disabled={applying}
          onChange={(value) => setSource(value as RenameSource)}
        />
      </div>

      <SectionGroup title="Rename" first>
        <div className="flex flex-col gap-2">
          <div>
            <TextInput
              placeholder="Pattern (replaces the whole name)"
              value={ops.pattern}
              onChange={(e) => setOp("pattern", e.target.value)}
            />
            <p className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
              Tokens: $n · $name · $parent · $type
            </p>
          </div>
          <div className="flex gap-2">
            <TextInput
              placeholder="Find"
              value={ops.find}
              onChange={(e) => setOp("find", e.target.value)}
            />
            <TextInput
              placeholder="Replace"
              value={ops.replace}
              onChange={(e) => setOp("replace", e.target.value)}
            />
          </div>
          <Checkbox
            checked={ops.match_case}
            onChange={(checked) => setOp("match_case", checked)}
            label="Match case"
          />
          <div className="flex gap-2">
            <TextInput
              placeholder="Prefix"
              value={ops.prefix}
              onChange={(e) => setOp("prefix", e.target.value)}
            />
            <TextInput
              placeholder="Suffix"
              value={ops.suffix}
              onChange={(e) => setOp("suffix", e.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-4">
            {numberField("Start #", "num_start")}
            {numberField("Padding", "num_padding")}
          </div>
        </div>
      </SectionGroup>

      <SectionGroup title="Preview">
        {emptyReason ? (
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            {emptyReason}
          </p>
        ) : rows.length === 0 ? (
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            Nothing selected.
          </p>
        ) : (
          <div className="flex flex-col">
            {rows.map((row, index) => (
              <div
                key={index}
                className="text-body flex items-baseline gap-2 border-b py-1"
                style={{
                  borderColor: "var(--color-hairline)",
                  color: row.collision ? "var(--color-status-warn)" : "var(--color-ink)",
                }}
              >
                <span className="min-w-0 flex-1 truncate" style={{ color: "var(--color-ink-secondary)" }}>
                  {row.old}
                </span>
                <span aria-hidden style={{ color: "var(--color-muted)" }}>
                  →
                </span>
                <span className="min-w-0 flex-1 truncate">{row.new}</span>
                {row.collision && (
                  <span className="text-caption shrink-0" style={{ color: "var(--color-status-warn)" }}>
                    duplicate result
                  </span>
                )}
              </div>
            ))}
            {preview?.truncated && (
              <p className="text-caption mt-1" style={{ color: "var(--color-ink-secondary)" }}>
                Showing {rows.length} of {preview.total ?? rows.length}
              </p>
            )}
          </div>
        )}
        <div className="mt-3">
          <Button variant="primary" disabled={!canApply} onClick={handleApply}>
            Apply
          </Button>
        </div>
      </SectionGroup>
    </div>
  );
}
