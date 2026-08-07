import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { TextInput } from "../form/TextInput";
import { SectionGroup } from "../SectionGroup";
import { fetchStandardPreview, postHubPickPath, postStandardPublish } from "../../lib/api";
import { restoreFocus } from "../../lib/focus";
import {
  STANDARD_ERROR_COPY,
  publishDisabledReason,
  qcGateLine,
  toggleExclude,
} from "../../lib/panelStandard";
import type { ExcludeEntry } from "../../lib/panelStandard";
import { useToast } from "../../lib/toast";
import type { StandardPreviewResponse } from "../../types";

/** Publish standard sub-view (v1.37) — the supervisor's once-per-project
 * gesture. Self-contained like MatwireSubview: owns its preview fetch and
 * its publish. The preview is ALWAYS the server's scan (`standard_preview`);
 * the SPA only edits which top-level objects travel (`exclude`) and the
 * shot-name pattern text on top of it. */
export function StandardSubview({ onBack }: { onBack: () => void }) {
  const { toast } = useToast();
  const [folder, setFolder] = useState("");
  const [preview, setPreview] = useState<StandardPreviewResponse | null>(null);
  const [exclude, setExclude] = useState<ExcludeEntry[]>([]);
  const [patternText, setPatternText] = useState("");
  const [applying, setApplying] = useState(false);

  // Monotonic sequence: only the LATEST in-flight preview may land (a slow
  // stale response must never overwrite a newer scan).
  const seqRef = useRef(0);

  const loadPreview = useCallback(async (dir: string) => {
    const seq = ++seqRef.current;
    const result = await fetchStandardPreview(dir || undefined);
    if (seq !== seqRef.current) return;
    setPreview(result);
    // Re-seed the editable state from the server's scan: a re-scan is a new
    // scan, and stale exclusions/pattern edits for a prior folder must not
    // linger silently.
    if (result.ok) {
      setExclude([]);
      setPatternText(result.pattern ?? "");
    }
  }, []);

  // Load once on mount against the active document's own folder (folder="").
  useEffect(() => {
    void loadPreview("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleBrowse = async () => {
    const picked = await postHubPickPath(true, "Choose the project folder");
    if (picked.ok && picked.path) {
      setFolder(picked.path);
      await loadPreview(picked.path);
    }
    // The native pick dialog stole the webview focus; without a live focused
    // element the next Cmd+Z is swallowed (v1.18 lesson, lib/focus.ts).
    restoreFocus();
  };

  const qc = preview?.ok ? preview.qc : undefined;
  const scene = preview?.ok ? preview.scene : undefined;
  const objects = scene?.objects ?? [];
  const wontTravel = preview?.ok ? (preview.wont_travel ?? []) : [];
  const diff = preview?.ok ? (preview.diff ?? []) : [];
  const emptyReason = preview && !preview.ok
    ? (STANDARD_ERROR_COPY[preview.error ?? ""] ?? "Preview unavailable.")
    : null;

  const disabledReason = publishDisabledReason({ folder, qcPass: qc?.pass ?? false });
  const canPublish = !applying && !!preview?.ok && !disabledReason;

  const handlePublish = async () => {
    setApplying(true);
    try {
      const result = await postStandardPublish(folder, exclude, patternText || null);
      if (result.ok) {
        const n = result.excluded ?? 0;
        toast({
          message: n === 0
            ? "Standard published — no branches excluded"
            : `Standard published — ${n} branch${n === 1 ? "" : "es"} excluded`,
          variant: "success",
        });
        await loadPreview(folder);
      } else {
        toast({
          message: STANDARD_ERROR_COPY[result.error ?? ""] ?? "Could not publish the standard.",
          variant: "warn",
        });
      }
    } finally {
      setApplying(false);
      restoreFocus();
    }
  };

  return (
    <div className="flex flex-col p-3">
      <div className="flex items-center justify-between">
        <Button variant="secondary" onClick={onBack}>
          ← Tools
        </Button>
      </div>

      <SectionGroup title="Project folder" first>
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <TextInput
              placeholder="Path to the project folder"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void loadPreview(folder);
              }}
            />
          </div>
          <Button variant="secondary" disabled={applying} onClick={handleBrowse}>
            Browse…
          </Button>
          <Button
            variant="secondary"
            disabled={applying}
            onClick={() => void loadPreview(folder)}
          >
            Refresh
          </Button>
        </div>
      </SectionGroup>

      {emptyReason ? (
        <SectionGroup title="Standard">
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            {emptyReason}
          </p>
        </SectionGroup>
      ) : (
        <>
          {qc && (
            <SectionGroup title="Quality gate">
              <p
                className="text-body"
                style={{ color: qc.pass ? "var(--color-ink)" : "var(--color-status-warn)" }}
              >
                {qcGateLine(qc)}
              </p>
            </SectionGroup>
          )}

          <SectionGroup title="Will travel">
            {scene && (
              <div className="mb-2 flex flex-col gap-0.5">
                <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  FPS {scene.fps} · start frame {scene.start_frame}
                </p>
                <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  Presets: {scene.presets.length > 0 ? scene.presets.join(", ") : "none"}
                </p>
              </div>
            )}
            <div className="mb-2">
              <label className="text-caption mb-1 block" style={{ color: "var(--color-ink-secondary)" }}>
                Shot name pattern
              </label>
              <TextInput
                placeholder="Shot name pattern"
                value={patternText}
                onChange={(e) => setPatternText(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              {objects.length === 0 ? (
                <p className="text-body" style={{ color: "var(--color-muted)" }}>
                  No top-level objects in the scene.
                </p>
              ) : (
                objects.map((obj) => {
                  const checked = !exclude.some(([n, i]) => n === obj.name && i === obj.index);
                  return (
                    <Checkbox
                      key={`${obj.name}:${obj.index}`}
                      checked={checked}
                      onChange={() => setExclude((prev) => toggleExclude(prev, obj.name, obj.index))}
                      label={obj.children ? `${obj.name} (+children)` : obj.name}
                    />
                  );
                })
              )}
            </div>
          </SectionGroup>

          {wontTravel.length > 0 && (
            <SectionGroup title="Won't travel">
              <div className="flex flex-col gap-0.5">
                {wontTravel.map((line, index) => (
                  <p key={index} className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                    {line}
                  </p>
                ))}
              </div>
            </SectionGroup>
          )}

          {preview?.existing_rules && (
            <SectionGroup title="Republish — what changes">
              {diff.length === 0 ? (
                <p className="text-body" style={{ color: "var(--color-ink-secondary)" }}>
                  Republish — replaces the existing standard
                </p>
              ) : (
                <div className="flex flex-col gap-0.5">
                  {diff.map((line, index) => (
                    <p key={index} className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                      {line}
                    </p>
                  ))}
                </div>
              )}
            </SectionGroup>
          )}

          <SectionGroup title="Publish">
            {disabledReason && (
              <p className="text-caption mb-2" style={{ color: "var(--color-status-warn)" }}>
                {disabledReason}
              </p>
            )}
            <Button variant="primary" disabled={!canPublish} onClick={handlePublish}>
              Publish standard
            </Button>
          </SectionGroup>
        </>
      )}
    </div>
  );
}
