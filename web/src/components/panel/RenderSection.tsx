import { useState } from "react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { Select } from "../form/Select";
import { fetchPanelRenderAovList } from "../../lib/api";
import {
  aovStatusLine,
  frameStatusLine,
  postrenderStatusLine,
  presetStatusLine,
  snapshotStatusLine,
} from "../../lib/panelRender";
import type { PanelRenderAovListOk, PanelRenderSection as PanelRenderSectionData } from "../../types";

/** A single stacked block — eyebrow label + status line + actions row, per
 * the approved "A + status header per block" layout (mockup
 * .superpowers/brainstorm/51945-1784736330/content/render-layout.html
 * option A). Shared shell so every block (Preset/Frame/AOVs/Snapshots/
 * Post-Render) reads as one system rather than five different card designs. */
function RenderBlock({
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

type AovListState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; data: PanelRenderAovListOk }
  | { kind: "unavailable"; message: string };

/** The panel's Render section (Fase 6.2) — 5 stacked status blocks reusing
 * the existing engines via thin ops (`panel_render_ops.py`). Destructive
 * actions (Reset All, Force 9:16, an AOV tier) surface an inline confirm bar
 * driven by the server's `confirm_label` — the SPA never invents its own
 * copy for what a mutation is about to do. Null blocks render a distinct
 * "not available" note rather than hiding, mirroring the QC section's
 * null-safety convention. */
export function RenderSection({
  render,
  busy,
  confirmLabel,
  onSetPreset,
  onDestructive,
  onAddFrameTag,
  onSelectFrameTag,
  onToggleMultipart,
  onToggleWatch,
  onSaveStill,
  onOpenFolder,
  onValidate,
  onConfirm,
  onCancelConfirm,
}: {
  render: PanelRenderSectionData;
  /** Non-null while any render mutation is in flight — single lock across
   * every block's buttons, same idiom as the QC section's `busy`. */
  busy: string | null;
  /** Set once a destructive op comes back with `confirm_required` — the
   * inline confirm bar's copy, verbatim from the server. */
  confirmLabel: string | null;
  onSetPreset: (preset: string) => void;
  onDestructive: (
    op: "reset_all" | "force_vertical" | "aov_tier",
    tier?: "essentials" | "production" | "light_groups",
  ) => void;
  onAddFrameTag: () => void;
  onSelectFrameTag: () => void;
  onToggleMultipart: () => void;
  onToggleWatch: () => void;
  onSaveStill: () => void;
  onOpenFolder: () => void;
  onValidate: () => void;
  onConfirm: () => void;
  onCancelConfirm: () => void;
}) {
  const [aovListState, setAovListState] = useState<AovListState>({ kind: "idle" });
  const isBusy = busy !== null;

  async function toggleAovList() {
    if (aovListState.kind !== "idle" && aovListState.kind !== "unavailable") {
      setAovListState({ kind: "idle" });
      return;
    }
    setAovListState({ kind: "loading" });
    const result = await fetchPanelRenderAovList();
    if (result.kind === "ok") {
      setAovListState({ kind: "ok", data: result.data });
      return;
    }
    // "empty" carries the friendly reason (e.g. Redshift unavailable, no
    // active document); a hard "error" (network/JSON failure) gets a
    // generic message — neither is a crash.
    setAovListState({
      kind: "unavailable",
      message: result.kind === "empty" ? result.reason : "Couldn't load the AOV list.",
    });
  }

  const preset = render.preset;
  const frame = render.frame;
  const aovs = render.aovs;
  const snapshots = render.snapshots;
  const postrender = render.postrender;

  return (
    <div className="flex flex-col gap-3 p-3">
      {confirmLabel && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border p-3"
          style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
        >
          <span className="text-body" style={{ color: "var(--color-ink)" }}>
            {confirmLabel}
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="secondary" disabled={isBusy} onClick={onCancelConfirm}>
              Cancel
            </Button>
            <Button variant="primary" disabled={isBusy} onClick={onConfirm}>
              Confirm
            </Button>
          </div>
        </div>
      )}

      {/* Preset */}
      <RenderBlock eyebrow="Preset" status={presetStatusLine(preset)}>
        {preset === null ? null : (
          <>
            <Select
              value={preset.preset_name ?? ""}
              options={preset.preset_names.map((name) => ({ value: name, label: name }))}
              disabled={isBusy || preset.preset_names.length === 0}
              onChange={onSetPreset}
            />
            <Button variant="secondary" disabled={isBusy} onClick={() => onDestructive("reset_all")}>
              Reset All⚠
            </Button>
            <Button variant="secondary" disabled={isBusy} onClick={() => onDestructive("force_vertical")}>
              Force 9:16⚠
            </Button>
          </>
        )}
      </RenderBlock>

      {/* Frame */}
      <RenderBlock eyebrow="Sentinel Frame" status={frameStatusLine(frame)}>
        {frame === null ? null : (
          <>
            <Button variant="secondary" disabled={isBusy} onClick={onAddFrameTag}>
              Add to camera
            </Button>
            <Button variant="secondary" disabled={isBusy || !frame.has_tag} onClick={onSelectFrameTag}>
              Select tag
            </Button>
          </>
        )}
      </RenderBlock>

      {/* AOVs */}
      <RenderBlock eyebrow="AOVs" status={aovStatusLine(aovs)}>
        {aovs === null ? null : (
          <>
            <button
              type="button"
              onClick={toggleAovList}
              className="text-caption"
              style={{ color: "var(--color-primary)" }}
            >
              {aovListState.kind === "ok" || aovListState.kind === "unavailable" ? "▾" : "▸"} Show AOVs
            </button>
            {!("error" in aovs) && (
              <>
                <Button variant="secondary" disabled={isBusy} onClick={() => onDestructive("aov_tier", "essentials")}>
                  Essentials⚠
                </Button>
                <Button variant="secondary" disabled={isBusy} onClick={() => onDestructive("aov_tier", "production")}>
                  Production⚠
                </Button>
                <Button variant="secondary" disabled={isBusy} onClick={() => onDestructive("aov_tier", "light_groups")}>
                  Light Groups⚠
                </Button>
                <Checkbox
                  checked={aovs.multipart}
                  disabled={isBusy}
                  onChange={onToggleMultipart}
                  label="Multi-Part EXR"
                />
              </>
            )}
          </>
        )}
      </RenderBlock>
      {aovListState.kind === "loading" && (
        <p className="text-caption -mt-2" style={{ color: "var(--color-ink-secondary)" }}>
          Loading AOVs…
        </p>
      )}
      {aovListState.kind === "unavailable" && (
        <p className="text-caption -mt-2" style={{ color: "var(--color-status-warn)" }}>
          {aovListState.message}
        </p>
      )}
      {aovListState.kind === "ok" && (
        <div
          className="-mt-2 flex max-h-56 flex-col gap-1 overflow-y-auto rounded-lg border p-3"
          style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-2)" }}
        >
          <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
            Target: {aovListState.data.target} · Light Groups: {aovListState.data.light_groups ? "on" : "off"}
          </p>
          <ul className="mt-1 list-inside list-disc">
            {aovListState.data.aovs.map((entry) => (
              <li key={entry.name} className="text-caption" style={{ color: "var(--color-ink)" }}>
                {entry.name} <span style={{ color: "var(--color-ink-secondary)" }}>({entry.type})</span>
              </li>
            ))}
          </ul>
          {aovListState.data.tier_coverage.production_missing.length > 0 && (
            <p className="text-caption mt-1" style={{ color: "var(--color-status-warn)" }}>
              Missing from Production: {aovListState.data.tier_coverage.production_missing.join(", ")}
            </p>
          )}
        </div>
      )}

      {/* Snapshots */}
      <RenderBlock eyebrow="Snapshots" status={snapshotStatusLine(snapshots)}>
        {snapshots === null ? null : (
          <>
            <Button variant="secondary" disabled={isBusy} onClick={onSaveStill}>
              Save Still
            </Button>
            <Button variant="secondary" disabled={isBusy || !snapshots.dir} onClick={onOpenFolder}>
              Open Folder
            </Button>
            <Checkbox checked={snapshots.watch_enabled} disabled={isBusy} onChange={onToggleWatch} label="Watch folder" />
          </>
        )}
      </RenderBlock>

      {/* Post-Render */}
      <RenderBlock eyebrow="Post-Render" status={postrenderStatusLine(postrender)}>
        <Button variant="secondary" disabled={isBusy} onClick={onValidate}>
          Validate →
        </Button>
      </RenderBlock>
    </div>
  );
}
