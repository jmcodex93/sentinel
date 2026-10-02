import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { SegmentedControl } from "../form/SegmentedControl";
import { Select } from "../form/Select";
import { TextInput } from "../form/TextInput";
import { ConfirmBar } from "../ConfirmBar";
import { SectionGroup } from "../SectionGroup";
import { fetchSlatePreview, fetchSlateState, postHubPickPath, postSlateSave } from "../../lib/api";
import { restoreFocus } from "../../lib/focus";
import {
  DEFAULT_SLATE_STYLE,
  SLATE_ERROR_COPY,
  SLATE_FIELDS,
  SLATE_SLOTS,
  addItem,
  itemLabel,
  moveItem,
  removeItem,
  sameSlate,
} from "../../lib/panelSlate";
import { useToast } from "../../lib/toast";
import type { SlatePreviewResponse, SlateSaveResponse, SlateSlotName, SlateState, SlateStyle } from "../../types";

const PREVIEW_DEBOUNCE_MS = 350;

/** Slate editor (Render → Snapshots → Slate…). Edits the project's
 * `slate` + `slate_style` with a live preview drawn by C4D itself
 * (`panel/slate/preview`, the real layout and font, scaled down). Saving
 * goes through the server's confirm: it names the ruleset file and every
 * change, because the slate is shared by the whole project. */
export function SlateSubview({ onBack, onOpenFullSize }: { onBack: () => void; onOpenFullSize: () => void }) {
  const { toast } = useToast();
  const [saved, setSaved] = useState<SlateState | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [style, setStyle] = useState<SlateStyle>(DEFAULT_SLATE_STYLE);
  const [preview, setPreview] = useState<SlatePreviewResponse | null>(null);
  const [confirm, setConfirm] = useState<{ response: SlateSaveResponse; folder?: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [newText, setNewText] = useState<Record<SlateSlotName, string>>({ left: "", center: "", right: "" });
  // Only the latest preview request may land (a slow one must not overwrite a newer edit).
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const state = await fetchSlateState();
    setSaved(state);
    if (state.ok) {
      setEnabled(state.enabled);
      setStyle(state.style);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const seq = ++seqRef.current;
    const timer = window.setTimeout(async () => {
      const result = await fetchSlatePreview(style);
      if (seq === seqRef.current) setPreview(result);
    }, PREVIEW_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [style]);

  const dirty = !!saved?.ok && !sameSlate({ enabled: saved.enabled, style: saved.style }, { enabled, style });

  const save = async (options: { folder?: string; confirm?: boolean } = {}) => {
    setSaving(true);
    try {
      const result = await postSlateSave(style, enabled, options);
      if (result.error === "confirm_required") {
        setConfirm({ response: result, folder: options.folder });
        return;
      }
      setConfirm(null);
      if (result.error === "need_folder") {
        const picked = await postHubPickPath(true, "Where should the project's slate be saved?");
        restoreFocus();
        if (picked.ok && picked.path) await save({ folder: picked.path });
        return;
      }
      if (result.ok) {
        toast({
          message: result.unchanged ? "Nothing to save." : `Slate saved for the team in ${result.path}.`,
          variant: result.unchanged ? "info" : "success",
        });
        await load();
        return;
      }
      const copy = SLATE_ERROR_COPY[result.error ?? ""] ?? "Could not save the slate.";
      toast({ message: result.detail ? `${copy} ${result.detail}` : copy, variant: "warn" });
    } finally {
      setSaving(false);
      restoreFocus();
    }
  };

  const edit = (next: SlateStyle) => {
    setConfirm(null);
    setStyle(next);
  };

  if (saved && !saved.ok) {
    return (
      <div className="flex flex-col gap-3 p-3">
        <div>
          <Button variant="secondary" onClick={onBack}>← Render</Button>
        </div>
        <p className="text-body" style={{ color: "var(--color-ink-secondary)" }}>
          {SLATE_ERROR_COPY[saved.error ?? ""] ?? "The slate settings are unavailable."}
        </p>
      </div>
    );
  }

  const previewCaption = preview?.ok
    ? [
        preview.source === "snapshot" ? "Latest snapshot" : "Grey frame (no snapshot yet)",
        preview.font === "Inter-Regular" ? null : preview.font === "ArialMT" ? "Arial" : "system font",
        preview.notice || null,
      ].filter(Boolean).join(" · ")
    : null;

  return (
    <div className="flex flex-col p-3">
      <div className="mb-3 flex items-center justify-between">
        <Button variant="secondary" onClick={onBack}>← Render</Button>
        <Button variant="secondary" disabled={saving} onClick={onOpenFullSize}>Open saved slate full size</Button>
      </div>

      <SectionGroup title="Preview" first>
        {preview?.ok && preview.image ? (
          <div className="flex flex-col gap-1">
            <img src={preview.image} alt="Slate preview" className="w-full rounded-md" style={{ border: "1px solid var(--color-hairline)" }} />
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>{previewCaption}</p>
          </div>
        ) : (
          <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
            {preview ? (SLATE_ERROR_COPY[preview.error ?? ""] ?? "Preview unavailable.") + (preview.detail ? ` ${preview.detail}` : "") : "Drawing the preview…"}
          </p>
        )}
      </SectionGroup>

      <SectionGroup title="Slate">
        <div className="flex flex-col gap-3">
          <Checkbox checked={enabled} onChange={(value) => { setConfirm(null); setEnabled(value); }} label="Burn the slate into snapshots" />
          <SegmentedControl
            options={[{ value: "below", label: "Strip below the image" }, { value: "overlay", label: "Bar over the image" }]}
            value={style.position}
            onChange={(value) => edit({ ...style, position: value as SlateStyle["position"] })}
          />
          <label className="text-body flex items-center gap-3" style={{ color: "var(--color-ink)" }}>
            Size
            <input
              type="range" min={0.5} max={2} step={0.1} value={style.size}
              onChange={(e) => edit({ ...style, size: Math.round(Number(e.target.value) * 10) / 10 })}
              className="flex-1" style={{ accentColor: "var(--color-primary)" }}
            />
            <span className="text-caption w-10 text-right" style={{ color: "var(--color-ink-secondary)" }}>×{style.size.toFixed(1)}</span>
          </label>
          <Checkbox checked={style.badge} onChange={(value) => edit({ ...style, badge: value })} label="Status badge (TR · 9/12)" />
          <Checkbox checked={style.show_post} onChange={(value) => edit({ ...style, show_post: value })} label="Show the RenderView post (LUT, curve) when a snapshot has it" />
        </div>
      </SectionGroup>

      {SLATE_SLOTS.map(({ slot, label }) => (
        <SectionGroup key={slot} title={label}>
          <div className="flex flex-col gap-2">
            {style.slots[slot].length === 0 ? (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>Empty</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {style.slots[slot].map((item, index) => (
                  <span
                    key={`${item}-${index}`}
                    className="text-caption inline-flex items-center gap-1 rounded-md px-2 py-1"
                    style={{ backgroundColor: "var(--color-surface-1)", border: "1px solid var(--color-hairline)", color: "var(--color-ink)" }}
                  >
                    <button type="button" aria-label="Move left" onClick={() => edit(moveItem(style, slot, index, -1))} style={{ color: "var(--color-ink-secondary)" }}>‹</button>
                    {itemLabel(item)}
                    <button type="button" aria-label="Move right" onClick={() => edit(moveItem(style, slot, index, 1))} style={{ color: "var(--color-ink-secondary)" }}>›</button>
                    <button type="button" aria-label="Remove" onClick={() => edit(removeItem(style, slot, index))} style={{ color: "var(--color-ink-secondary)" }}>×</button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2">
              <div className="w-40 shrink-0">
                <Select
                  value=""
                  options={[{ value: "", label: "Add field…" }, ...SLATE_FIELDS.map((f) => ({ value: f.token, label: f.label }))]}
                  onChange={(token) => { if (token) edit(addItem(style, slot, `{${token}}`)); }}
                />
              </div>
              <div className="min-w-0 flex-1">
                <TextInput
                  placeholder="Add text (e.g. client name)"
                  value={newText[slot]}
                  onChange={(e) => setNewText({ ...newText, [slot]: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newText[slot].trim()) {
                      edit(addItem(style, slot, newText[slot]));
                      setNewText({ ...newText, [slot]: "" });
                    }
                  }}
                />
              </div>
              <Button
                variant="secondary"
                disabled={!newText[slot].trim()}
                onClick={() => { edit(addItem(style, slot, newText[slot])); setNewText({ ...newText, [slot]: "" }); }}
              >
                Add
              </Button>
            </div>
          </div>
        </SectionGroup>
      ))}

      <SectionGroup>
        <div className="flex flex-col gap-2">
          <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
            {saved?.rules_path
              ? `Saved in ${saved.rules_path} — shared by everyone in this project.`
              : "This scene has no project rules yet — Save asks where to create them."}
          </p>
          {saved?.warnings?.map((warning) => (
            <p key={warning} className="text-caption" style={{ color: "var(--color-status-warn)" }}>{warning}</p>
          ))}
          {confirm?.response.confirm_label ? (
            <ConfirmBar
              label={confirm.response.confirm_label}
              confirmVerb={confirm.response.confirm_verb}
              destructive={confirm.response.destructive}
              busy={saving}
              onConfirm={() => void save({ folder: confirm.folder, confirm: true })}
              onCancel={() => { setConfirm(null); restoreFocus(); }}
            />
          ) : (
            <div className="flex items-center gap-2">
              <Button variant="primary" disabled={!dirty || saving || !saved?.scene_saved} onClick={() => void save()}>
                Save for the project
              </Button>
              <Button variant="secondary" disabled={saving} onClick={() => edit({ ...DEFAULT_SLATE_STYLE, slots: { ...DEFAULT_SLATE_STYLE.slots } })}>
                Reset to default
              </Button>
              {dirty && <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>Unsaved changes</span>}
            </div>
          )}
        </div>
      </SectionGroup>
    </div>
  );
}
