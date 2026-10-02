import { ChevronLeft, ChevronRight, X } from "lucide-react";
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
  SLATE_SLOTS,
  addItem,
  fieldsToAdd,
  itemLabel,
  moveItem,
  postPlaced,
  removeItem,
  sameSlate,
  shortPath,
  sizeReadout,
} from "../../lib/panelSlate";
import { useToast } from "../../lib/toast";
import type { SlatePreviewResponse, SlateSaveResponse, SlateSlotName, SlateState, SlateStyle } from "../../types";

const PREVIEW_DEBOUNCE_MS = 350;
const CUSTOM_TEXT = "__custom__";

const iconButton = "inline-flex h-5 w-5 items-center justify-center rounded hover:bg-[var(--color-surface-2)]";

/** Slate editor (Render → Snapshots → Slate…). Edits the project's `slate`
 * + `slate_style`. The preview stays on screen while the zones are edited
 * and is the DRAFT, drawn by C4D (`panel/slate/preview`); "View at 100 %"
 * opens that same draft full size. Saving goes through the server's
 * confirm, which names the ruleset file and every change — the slate is
 * shared by the whole project. */
export function SlateSubview({ onBack }: { onBack: () => void }) {
  const { toast } = useToast();
  const [saved, setSaved] = useState<SlateState | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [style, setStyle] = useState<SlateStyle>(DEFAULT_SLATE_STYLE);
  const [preview, setPreview] = useState<SlatePreviewResponse | null>(null);
  const [confirm, setConfirm] = useState<{ response: SlateSaveResponse; folder?: string } | null>(null);
  const [saving, setSaving] = useState(false);
  // Which zone is showing its "custom text" input, and what is typed in it.
  const [customSlot, setCustomSlot] = useState<SlateSlotName | null>(null);
  const [customText, setCustomText] = useState("");
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
      const result = await fetchSlatePreview(style, { enabled });
      if (seq === seqRef.current) setPreview(result);
    }, PREVIEW_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [style, enabled]);

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
          message: result.unchanged
            ? "Nothing to save."
            : `Slate saved for the project in ${shortPath(result.path ?? "")}.`,
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

  const viewFullSize = async () => {
    const result = await fetchSlatePreview(style, { enabled, open: true });
    if (!result.ok) {
      toast({ message: SLATE_ERROR_COPY[result.error ?? ""] ?? "Could not open the preview.", variant: "warn" });
    }
    restoreFocus();
  };

  const edit = (next: SlateStyle) => {
    setConfirm(null);
    setStyle(next);
  };

  const addCustom = (slot: SlateSlotName) => {
    if (customText.trim()) edit(addItem(style, slot, customText));
    setCustomText("");
    setCustomSlot(null);
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

  const autoPost = style.show_post && !postPlaced(style);
  const postText = preview?.ok && preview.source === "snapshot" && preview.post
    ? `this snapshot: ${preview.post}`
    : "when a snapshot has one";
  const previewCaption = preview?.ok
    ? [
        preview.source === "snapshot" ? "Latest snapshot" : "Grey frame (no snapshot yet)",
        preview.font === "Inter-Regular" ? null : preview.font === "ArialMT" ? "Arial" : "system font",
        enabled ? null : "slate off",
      ].filter(Boolean).join(" · ")
    : null;

  return (
    <div className="flex flex-col">
      {/* Sticky so the preview stays in view while the zones are edited. */}
      <div
        className="sticky top-0 z-10 flex flex-col gap-2 p-3"
        style={{ backgroundColor: "var(--color-canvas)", borderBottom: "1px solid var(--color-hairline)" }}
      >
        <div className="flex items-center justify-between">
          <Button variant="secondary" onClick={onBack}>← Render</Button>
          <Button variant="secondary" disabled={!preview?.ok} onClick={() => void viewFullSize()}>
            View at 100 %
          </Button>
        </div>
        {preview?.ok && preview.image ? (
          <>
            <img
              src={preview.image}
              alt="Slate preview"
              className="w-full rounded-md object-contain"
              style={{ maxHeight: 140, border: "1px solid var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
            />
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>{previewCaption}</p>
          </>
        ) : (
          <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
            {preview ? (SLATE_ERROR_COPY[preview.error ?? ""] ?? "Preview unavailable.") + (preview.detail ? ` ${preview.detail}` : "") : "Drawing the preview…"}
          </p>
        )}
      </div>

      <div className="flex flex-col px-3 pb-3">
        <SectionGroup
          title="Slate"
          first
          action={
            <Button variant="secondary" disabled={saving} onClick={() => edit({ ...DEFAULT_SLATE_STYLE, slots: { ...DEFAULT_SLATE_STYLE.slots } })}>
              Reset to default
            </Button>
          }
        >
          <div className="flex flex-col gap-3 pt-3">
            <Checkbox checked={enabled} onChange={(value) => { setConfirm(null); setEnabled(value); }} label="Burn the slate into snapshots" />
            {!enabled && (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                Slate is off — snapshots are saved without it. The settings below are kept.
              </p>
            )}
          </div>
        </SectionGroup>

        {/* Off looks off: dimmed and inert (not `disabled`, which would also dim
            the save area and is the wrong signal for a kept configuration). */}
        <div style={enabled ? undefined : { opacity: 0.5, pointerEvents: "none" }}>
          <SectionGroup>
            <div className="flex flex-col gap-3">
              <SegmentedControl
                options={[{ value: "below", label: "Strip below the image" }, { value: "overlay", label: "Bar over the image" }]}
                value={style.position}
                onChange={(value) => edit({ ...style, position: value as SlateStyle["position"] })}
              />
              <label className="text-body flex items-center gap-3" style={{ color: "var(--color-ink)" }}>
                Text size
                <input
                  type="range" min={0.5} max={2} step={0.1} value={style.size}
                  onChange={(e) => edit({ ...style, size: Math.round(Number(e.target.value) * 10) / 10 })}
                  className="min-w-0 flex-1" style={{ accentColor: "var(--color-primary)" }}
                />
                <span className="text-caption shrink-0 text-right" style={{ color: "var(--color-ink-secondary)" }}>
                  {sizeReadout(style.size, preview?.ok ? preview.strip_px : undefined, preview?.ok ? preview.at_min : undefined)}
                </span>
              </label>
              <Checkbox checked={style.badge} onChange={(value) => edit({ ...style, badge: value })} label="Status badge (status · QC score)" />
            </div>
          </SectionGroup>

          {SLATE_SLOTS.map(({ slot, label }) => {
            const items = style.slots[slot];
            const showGhost = slot === "center" && autoPost;
            return (
              <SectionGroup key={slot} title={label}>
                <div className="flex flex-col gap-2">
                  {items.length === 0 && !showGhost && (
                    <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>Nothing placed</p>
                  )}
                  {(items.length > 0 || showGhost) && (
                    <div className="flex flex-wrap gap-1.5">
                      {items.map((item, index) => (
                        <span
                          key={`${item}-${index}`}
                          className="text-caption inline-flex items-center gap-0.5 rounded-md py-0.5 pr-0.5 pl-1"
                          style={{ backgroundColor: "var(--color-surface-1)", border: "1px solid var(--color-hairline)", color: "var(--color-ink)" }}
                        >
                          {index > 0 ? (
                            <button type="button" aria-label="Move left" className={iconButton} onClick={() => edit(moveItem(style, slot, index, -1))} style={{ color: "var(--color-ink-secondary)" }}>
                              <ChevronLeft size={14} />
                            </button>
                          ) : <span className="w-1" />}
                          <span className="px-0.5">{itemLabel(item)}</span>
                          {index < items.length - 1 && (
                            <button type="button" aria-label="Move right" className={iconButton} onClick={() => edit(moveItem(style, slot, index, 1))} style={{ color: "var(--color-ink-secondary)" }}>
                              <ChevronRight size={14} />
                            </button>
                          )}
                          <button type="button" aria-label="Remove" className={iconButton} onClick={() => edit(removeItem(style, slot, index))} style={{ color: "var(--color-ink-secondary)" }}>
                            <X size={14} />
                          </button>
                        </span>
                      ))}
                      {showGhost && (
                        <span
                          className="text-caption inline-flex items-center gap-0.5 rounded-md py-0.5 pr-0.5 pl-2"
                          style={{ border: "1px dashed var(--color-hairline-strong)", color: "var(--color-ink-secondary)" }}
                          title="Added automatically when a snapshot carries RenderView post; dropped first if the strip is full. Click to place it yourself."
                        >
                          <button type="button" onClick={() => edit(addItem(style, "center", "{post}"))}>RenderView post · auto</button>
                          <button type="button" aria-label="Hide the RenderView post" className={iconButton} onClick={() => edit({ ...style, show_post: false })}>
                            <X size={14} />
                          </button>
                        </span>
                      )}
                    </div>
                  )}
                  {showGhost && (
                    <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>{postText}</p>
                  )}
                  {slot === "center" && !style.show_post && !postPlaced(style) && (
                    <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                      RenderView post hidden ·{" "}
                      <button type="button" className="underline" onClick={() => edit({ ...style, show_post: true })}>Show</button>
                    </p>
                  )}
                  {customSlot === slot ? (
                    <div className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <TextInput
                          autoFocus
                          placeholder="Text (e.g. client name)"
                          value={customText}
                          onChange={(e) => setCustomText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") addCustom(slot);
                            if (e.key === "Escape") { setCustomSlot(null); setCustomText(""); }
                          }}
                        />
                      </div>
                      <Button variant="secondary" disabled={!customText.trim()} onClick={() => addCustom(slot)}>Add</Button>
                    </div>
                  ) : (
                    <Select
                      value=""
                      options={[
                        { value: "", label: "Add…" },
                        ...fieldsToAdd(items).map((f) => ({ value: f.token, label: f.label })),
                        { value: CUSTOM_TEXT, label: "Custom text…" },
                      ]}
                      onChange={(value) => {
                        if (value === CUSTOM_TEXT) { setCustomSlot(slot); setCustomText(""); }
                        else if (value) edit(addItem(style, slot, `{${value}}`));
                      }}
                    />
                  )}
                </div>
              </SectionGroup>
            );
          })}
        </div>

        <SectionGroup>
          <div className="flex flex-col gap-2">
            <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }} title={saved?.rules_path || undefined}>
              {saved?.rules_path
                ? `Saved in ${shortPath(saved.rules_path)} — shared by everyone in this project.`
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
                {dirty && <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>Unsaved changes</span>}
              </div>
            )}
            {saved && !saved.scene_saved && (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>{SLATE_ERROR_COPY.unsaved}</p>
            )}
          </div>
        </SectionGroup>
      </div>
    </div>
  );
}
