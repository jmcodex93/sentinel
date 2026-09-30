import { useCallback, useRef, useState } from "react";
import { Button } from "../form/Button";
import { TextInput } from "../form/TextInput";
import { SectionGroup } from "../SectionGroup";
import { fetchNewShotPreview, postHubPickPath, postNewShotCreate } from "../../lib/api";
import { restoreFocus } from "../../lib/focus";
import { NEWSHOT_ERROR_COPY } from "../../lib/panelStandard";
import { useToast } from "../../lib/toast";
import type { NewShotPreviewResponse } from "../../types";

/** New shot sub-view (v1.37) — the artist's daily gesture: start a shot from
 * the project standard. Self-contained like MatwireSubview/StandardSubview:
 * owns its preview fetch and its create. Preview errors are normal editing
 * states (wrong folder, no standard here) and render as quiet inline text,
 * not toasts — the Batch Rename lesson; only the mutation result toasts. */
export function NewShotSubview({ onBack }: { onBack: () => void }) {
  const { toast } = useToast();
  const [folder, setFolder] = useState("");
  const [preview, setPreview] = useState<NewShotPreviewResponse | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  // Monotonic sequence: only the LATEST in-flight preview may land (a slow
  // stale response must never overwrite a newer scan).
  const seqRef = useRef(0);

  const loadPreview = useCallback(async (dir: string) => {
    if (!dir) {
      setPreview(null);
      return;
    }
    const seq = ++seqRef.current;
    const result = await fetchNewShotPreview(dir);
    if (seq !== seqRef.current) return;
    setPreview(result);
  }, []);

  const handleBrowse = async () => {
    const picked = await postHubPickPath(true, "Choose a folder inside the project");
    if (picked.ok && picked.path) {
      setFolder(picked.path);
      await loadPreview(picked.path);
    }
    // The native pick dialog stole the webview focus; without a live focused
    // element the next Cmd+Z is swallowed (v1.18 lesson, lib/focus.ts).
    restoreFocus();
  };

  const emptyReason = preview && !preview.ok
    ? (NEWSHOT_ERROR_COPY[preview.error ?? ""]
        ?? (preview.error === "no_standard" && preview.searched
          ? `No project standard found here (searched from ${preview.searched}).`
          : "Preview unavailable."))
    : null;

  const templateMissing = preview?.ok && preview.template_exists === false;
  const canCreate = !creating && !!preview?.ok && !templateMissing && name.trim().length > 0;

  const handleCreate = async () => {
    if (!canCreate) return;
    setCreating(true);
    try {
      const result = await postNewShotCreate(folder, name.trim());
      if (result.ok) {
        const basename = (result.path ?? name).split(/[/\\]/).pop() ?? name;
        toast({ message: `Shot created — ${basename}`, variant: "success" });
        onBack();
        return;
      }
      toast({
        message: NEWSHOT_ERROR_COPY[result.error ?? ""] ?? "Could not create the shot.",
        variant: "warn",
      });
    } finally {
      setCreating(false);
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

      <SectionGroup title="Folder" first>
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <TextInput
              placeholder="Path to a folder inside the project"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && folder) void loadPreview(folder);
              }}
            />
          </div>
          <Button variant="secondary" disabled={creating} onClick={handleBrowse}>
            Browse…
          </Button>
          <Button
            variant="secondary"
            disabled={creating || !folder}
            onClick={() => void loadPreview(folder)}
          >
            Refresh
          </Button>
        </div>
      </SectionGroup>

      <SectionGroup title="Standard">
        {!preview ? (
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            Pick a folder to check for a project standard.
          </p>
        ) : emptyReason ? (
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            {emptyReason}
          </p>
        ) : preview.ok && templateMissing ? (
          <p className="text-body" style={{ color: "var(--color-status-warn)" }}>
            {NEWSHOT_ERROR_COPY.template_missing}
          </p>
        ) : preview.ok ? (
          <div className="flex flex-col gap-0.5">
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
              Project: {preview.project_dir}
            </p>
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
              Pattern: {preview.pattern ?? "none"}
            </p>
            {preview.published && (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                Published by {preview.published.by} · {preview.published.at}
              </p>
            )}
          </div>
        ) : null}
      </SectionGroup>

      <SectionGroup title="Shot">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <TextInput
              placeholder="Shot name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button variant="primary" disabled={!canCreate} onClick={handleCreate}>
            Create shot
          </Button>
        </div>
      </SectionGroup>
    </div>
  );
}
