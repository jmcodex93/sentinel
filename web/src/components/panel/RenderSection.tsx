import { useState } from "react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { SegmentedControl } from "../form/SegmentedControl";
import { Select } from "../form/Select";
import { fetchPanelRenderAovList } from "../../lib/api";
import { frameHint } from "../../lib/panelFrame";
import {
  aovStatusLine,
  frameStatusLine,
  postrenderStatusLine,
  presetOptionLabel,
  presetStatusLine,
  snapshotStatusLine,
} from "../../lib/panelRender";
import type {
  PanelFrameState,
  PanelRenderAovListOk,
  PanelRenderSection as PanelRenderSectionData,
} from "../../types";
import { ConfirmBar } from "../ConfirmBar";
import { FrameSubview } from "./FrameSubview";
import { SectionGroup } from "../SectionGroup";

/** A single stacked block — title + status line + actions row, per the
 * approved "A + status header per block" layout (mockup
 * .superpowers/brainstorm/51945-1784736330/content/render-layout.html
 * option A). Shared shell (a `SectionGroup`) so every block (Preset/Frame/
 * AOVs/Snapshots/Post-Render) reads as one system rather than five different
 * card designs — refactored here once, all 5 call sites benefit. */
function RenderBlock({
  title,
  first,
  status,
  headerRight,
  children,
}: {
  title: string;
  first?: boolean;
  status: string;
  /** Right-aligned header content, next to the title — e.g. the AOVs
   * block's "Show AOVs" link, kept separate from the action rows below it
   * rather than mixed in as a peer button. */
  headerRight?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <SectionGroup title={title} first={first} action={headerRight}>
      <div className="flex flex-col gap-2">
        <p className="text-body" style={{ color: "var(--color-ink)" }}>
          {status}
        </p>
        {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
      </div>
    </SectionGroup>
  );
}

/** A single labeled action row inside a block — short inline label + its
 * control(s), tokens only, coherent with the rest of the panel. Used for
 * the AOVs block's Coverage / Light Groups / Output rows so each reads as
 * its own concept rather than a flat row of peer buttons. */
function ActionRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex w-full flex-wrap items-center gap-2">
      <span className="text-caption w-28 shrink-0" style={{ color: "var(--color-ink-secondary)" }}>
        {label}
      </span>
      {children}
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
 * actions (Reset All) surface an inline confirm bar
 * driven by the server's `confirm_label` — the SPA never invents its own
 * copy for what a mutation is about to do. Null blocks render a distinct
 * "not available" note rather than hiding, mirroring the QC section's
 * null-safety convention. */
export function RenderSection({
  render,
  frameData,
  busy,
  confirmLabel,
  onSetPreset,
  onDestructive,
  onAddFrameTag,
  onSelectFrameTag,
  onAovTier,
  onSetLightGroups,
  onSetMultipart,
  onToggleWatch,
  onSaveStill,
  onOpenFolder,
  onValidate,
  onConfirm,
  onCancelConfirm,
  onMarkSubjects,
  onSelectViolations,
  onOpenQc,
  onSetViewing,
}: {
  render: PanelRenderSectionData;
  /** `panel/frame` state for the Frame sub-view (Fase 6.6) — a separate read
   * from `render` (its own op, its own fetch/poll in PanelPage), passed down
   * so the Frame block's hint and the sub-view itself share one source. */
  frameData: PanelFrameState;
  /** Non-null while any render mutation is in flight — single lock across
   * every block's buttons, same idiom as the QC section's `busy`. */
  busy: string | null;
  /** Set once a destructive op comes back with `confirm_required` — the
   * inline confirm bar's copy, verbatim from the server. */
  confirmLabel: string | null;
  /** Receives the chosen preset's chain INDEX (the option value) — the page
   * resolves it back to a name+index pair for `set_preset`. */
  onSetPreset: (index: number) => void;
  /** Reset All — the only render op left that is genuinely destructive and
   * confirm-gated (Force 9:16 was retired in v1.36.4: vertical delivery is
   * Sentinel Frame's job, a block below). */
  onDestructive: (op: "reset_all") => void;
  onAddFrameTag: () => void;
  onSelectFrameTag: () => void;
  /** Coverage action — Essentials/Production ADD any missing AOVs up to
   * that tier. Additive/Cmd+Z-able, no confirm bar. */
  onAovTier: (tier: "essentials" | "production") => void;
  /** Light Groups on Beauty — an independent on/off toggle (state), not a
   * tier. Sends the EXPLICIT value of the option clicked. */
  onSetLightGroups: (enabled: boolean) => void;
  /** Sends the EXPLICIT value of the option clicked (Multi-Part → true,
   * Direct output → false) — never a flip of the current state, so two
   * quick clicks can't race a read-then-flip. */
  onSetMultipart: (enabled: boolean) => void;
  onToggleWatch: () => void;
  onSaveStill: () => void;
  onOpenFolder: () => void;
  onValidate: () => void;
  onConfirm: () => void;
  onCancelConfirm: () => void;
  /** Frame sub-view actions (Fase 6.6) — all reuse existing ops
   * (`panel/tools/mark_safe_area`, `panel/qc/select`); the sub-view adds no
   * new mutation. */
  onMarkSubjects: () => void;
  onSelectViolations: () => void;
  onOpenQc: () => void;
  onSetViewing: (target: string) => void;
}) {
  const [aovListState, setAovListState] = useState<AovListState>({ kind: "idle" });
  const [renderView, setRenderView] = useState<"main" | "frame">("main");
  const isBusy = busy !== null;

  if (renderView === "frame") {
    return (
      <FrameSubview
        frame={frameData}
        busy={busy}
        onBack={() => setRenderView("main")}
        onAddTag={onAddFrameTag}
        onSelectTag={onSelectFrameTag}
        onMarkSubjects={onMarkSubjects}
        onSelectViolations={onSelectViolations}
        onOpenQc={onOpenQc}
        onSetViewing={onSetViewing}
      />
    );
  }

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
  const frameHintText = frameHint(frameData);
  const frameHintWarn = frameHintText.startsWith("⚠") || frameHintText.toLowerCase().includes("out of date");
  const aovs = render.aovs;
  const snapshots = render.snapshots;
  const postrender = render.postrender;

  return (
    // During a mutation we lock interaction at the container (`pointerEvents`)
    // instead of setting `disabled` on every control. `disabled` dims via
    // `opacity-50`, and with ~15 controls all gated on the single `isBusy`,
    // every press dimmed the whole section to 50% and back — a full-section
    // flicker on each click, worst here because Render has the most controls.
    // The lock blocks re-entry without any opacity change; real per-control
    // guards (no preset / no tag / no dir) stay.
    <div className="flex flex-col p-3" style={{ pointerEvents: isBusy ? "none" : undefined }}>
      {confirmLabel && (
        <ConfirmBar label={confirmLabel} busy={isBusy} onConfirm={onConfirm} onCancel={onCancelConfirm} className="mb-4" />
      )}

      {/* Preset */}
      <RenderBlock title="Preset" first status={presetStatusLine(preset)}>
        {preset === null ? null : (
          <>
            {/* The option VALUE is the preset's chain index, not its name:
                two presets whose names normalize alike (QC #5's "duplicate
                render preset") are distinct entries that must each activate
                themselves. The label carries the real name — see
                `presetOptionLabel`. */}
            <Select
              value={preset.preset_index === null ? "" : String(preset.preset_index)}
              options={preset.presets.map((option) => ({
                value: String(option.index),
                label: presetOptionLabel(option),
              }))}
              disabled={preset.presets.length === 0}
              onChange={(value) => onSetPreset(Number(value))}
            />
            <Button variant="secondary" disabled={false} onClick={() => onDestructive("reset_all")}>
              Reset All⚠
            </Button>
          </>
        )}
      </RenderBlock>

      {/* Frame — the Sentinel Frame status line stays render-scoped
          (`frame`, from `panel/render`); the next-step hint + "Manage
          frame →" read the consolidated `panel/frame` state (Fase 6.6). */}
      <RenderBlock title="Sentinel Frame" status={frameStatusLine(frame)}>
        {frame === null ? null : (
          <div className="flex w-full flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="secondary" disabled={false} onClick={onAddFrameTag}>
                Add to camera
              </Button>
              <Button variant="secondary" disabled={!frame.has_tag} onClick={onSelectFrameTag}>
                Select tag
              </Button>
              <button
                type="button"
                onClick={() => setRenderView("frame")}
                className="text-caption ml-auto"
                style={{ color: "var(--color-primary)" }}
              >
                Manage frame →
              </button>
            </div>
            <p
              className="text-caption"
              style={{ color: frameHintWarn ? "var(--color-status-warn)" : "var(--color-ink-secondary)" }}
            >
              {frameHintText}
            </p>
          </div>
        )}
      </RenderBlock>

      {/* AOVs — three distinct concepts, not three peer buttons: Coverage
          (additive tier actions), Light Groups (an independent toggle),
          Output (the existing persistent-mode switch). */}
      <RenderBlock
        title="AOVs"
        status={aovStatusLine(aovs)}
        headerRight={
          aovs !== null &&
          !("error" in aovs) && (
            <button
              type="button"
              onClick={toggleAovList}
              className="text-caption"
              style={{ color: "var(--color-primary)" }}
            >
              {aovListState.kind === "ok" || aovListState.kind === "unavailable" ? "▾" : "▸"} Show AOVs
            </button>
          )
        }
      >
        {aovs === null || "error" in aovs ? null : (
          <div className="flex w-full flex-col gap-2">
            <ActionRow label="Coverage">
              <Button variant="secondary" disabled={false} onClick={() => onAovTier("essentials")}>
                Essentials
              </Button>
              <Button variant="secondary" disabled={false} onClick={() => onAovTier("production")}>
                Production
              </Button>
            </ActionRow>
            <ActionRow label="Light Groups">
              <SegmentedControl
                options={[
                  { value: "off", label: "off" },
                  { value: "on", label: "on" },
                ]}
                value={aovs.light_groups ? "on" : "off"}
                disabled={false}
                onChange={(value) => onSetLightGroups(value === "on")}
              />
            </ActionRow>
            <ActionRow label="Output">
              <SegmentedControl
                options={[
                  { value: "multipart", label: "Multi-Part EXR" },
                  { value: "direct", label: "Direct output" },
                ]}
                value={aovs.multipart ? "multipart" : "direct"}
                disabled={false}
                onChange={(value) => onSetMultipart(value === "multipart")}
              />
            </ActionRow>
            {aovListState.kind === "loading" && (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                Loading AOVs…
              </p>
            )}
            {aovListState.kind === "unavailable" && (
              <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
                {aovListState.message}
              </p>
            )}
            {aovListState.kind === "ok" && (
              <div
                className="flex max-h-56 flex-col gap-1 overflow-y-auto rounded-lg border p-3"
                style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-2)" }}
              >
                <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  Target: {aovListState.data.target} · Light Groups: {aovListState.data.light_groups ? "on" : "off"}
                </p>
                <ul className="mt-1 list-inside list-disc">
                  {aovListState.data.aovs.map((entry) => (
                    <li key={`${entry.name}-${entry.type}`} className="text-caption" style={{ color: "var(--color-ink)" }}>
                      {entry.name}
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
          </div>
        )}
      </RenderBlock>

      {/* Snapshots */}
      <RenderBlock title="Snapshots" status={snapshotStatusLine(snapshots)}>
        {snapshots === null ? null : (
          <>
            <Button variant="secondary" disabled={false} onClick={onSaveStill}>
              Save Still
            </Button>
            <Button variant="secondary" disabled={!snapshots.dir} onClick={onOpenFolder}>
              Open Folder
            </Button>
            <Checkbox checked={snapshots.watch_enabled} disabled={false} onChange={onToggleWatch} label="Watch folder" />
          </>
        )}
      </RenderBlock>

      {/* Post-Render */}
      <RenderBlock title="Post-Render" status={postrenderStatusLine(postrender)}>
        <Button variant="secondary" disabled={false} onClick={onValidate}>
          Validate →
        </Button>
      </RenderBlock>
    </div>
  );
}
