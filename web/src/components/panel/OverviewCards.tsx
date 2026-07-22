import type { ReactNode } from "react";
import type { PaletteAction, PanelAssets, PanelDeliver, PanelOverview, PanelRender } from "../../types";

/** Human label for a `qc.fixable` palette action id — the same four ids
 * `_PANEL_FIX_CHECK_ID` in panel_ops.py knows about. */
const FIX_LABELS: Record<string, string> = {
  fix_lights: "Fix lights",
  fix_cameras: "Fix cameras",
  fix_materials: "Fix materials",
  fix_fps: "Fix FPS",
};

function Card({ tone, title, children }: { tone: "fail" | "warn" | "pass" | "neutral"; title: string; children: ReactNode }) {
  const toneColor = {
    fail: "var(--color-status-fail)",
    warn: "var(--color-status-warn)",
    pass: "var(--color-status-pass)",
    neutral: "var(--color-ink)",
  }[tone];
  return (
    <div
      className="flex flex-col gap-1.5 rounded-lg border p-3"
      style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
    >
      <p className="text-label" style={{ color: toneColor }}>
        {title}
      </p>
      {children}
    </div>
  );
}

function CardActions({ children }: { children: ReactNode }) {
  return <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">{children}</div>;
}

function CardAction({
  label,
  onClick,
  disabled,
  title,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="text-caption disabled:cursor-not-allowed disabled:opacity-50"
      style={{ color: "var(--color-primary)" }}
    >
      {label}
    </button>
  );
}

function UnavailableCard({ title }: { title: string }) {
  return (
    <Card tone="neutral" title={title}>
      <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
        Unavailable this refresh.
      </p>
    </Card>
  );
}

function QcCard({
  qc,
  actions,
  onFix,
  onOpenQc,
  busyFix,
}: {
  qc: PanelOverview["qc"];
  actions: PaletteAction[];
  onFix: (id: string) => void;
  onOpenQc: () => void;
  busyFix: string | null;
}) {
  if (!qc) return <UnavailableCard title="QC" />;
  const denominator = qc.total - qc.disabled;
  const passing = denominator > 0 && qc.passed === denominator;
  const topLine = qc.top.map((c) => `${c.label} ${c.count}`).join(" · ");

  return (
    <Card tone={passing ? "pass" : "fail"} title={`QC ${qc.passed}/${denominator}`}>
      <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
        {topLine || "No violations."}
      </p>
      <CardActions>
        {qc.fixable.map((id) => {
          // qc.fixable (panel/overview) and `actions` (palette/actions) are
          // independently-timed snapshots — bind each button's disabled/title
          // to the freshest known action, same as HubPreflightStrip's Fix
          // buttons, rather than trusting the fixable id alone.
          const action = actions.find((a) => a.id === id);
          return (
            <CardAction
              key={id}
              label={FIX_LABELS[id] || id}
              onClick={() => onFix(id)}
              disabled={busyFix !== null || (action ? !action.enabled : false)}
              title={action && !action.enabled ? action.reason || undefined : undefined}
            />
          );
        })}
        <CardAction label="Ver todo →" onClick={onOpenQc} />
      </CardActions>
    </Card>
  );
}

function AssetsCard({ assets, onOpenHub }: { assets: PanelAssets | null; onOpenHub: () => void }) {
  if (!assets) return <UnavailableCard title="Assets" />;
  return (
    <Card tone={assets.missing > 0 ? "warn" : "pass"} title={`Assets ${assets.count}`}>
      <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
        {assets.missing > 0 ? `${assets.missing} missing · ` : ""}
        {assets.disk_label} · {assets.vram_label ?? "—"} VRAM
      </p>
      <CardActions>
        <CardAction label="Hub →" onClick={onOpenHub} />
      </CardActions>
    </Card>
  );
}

function RenderCard({ render, onValidate }: { render: PanelRender | null; onValidate: () => void }) {
  if (!render) return <UnavailableCard title="Render" />;
  const parts = [render.preset_name, render.fps ? `${render.fps}fps` : null, render.resolution].filter(Boolean);
  return (
    <Card tone="neutral" title="Render">
      <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
        {parts.join(" · ") || "No active render data."}
      </p>
      <CardActions>
        <CardAction label="Validar último render" onClick={onValidate} />
      </CardActions>
    </Card>
  );
}

function DeliverCard({
  scene,
  deliver,
  onSaveVersion,
  onEditNotes,
  onOpenDeliver,
}: {
  scene: PanelOverview["scene"];
  deliver: PanelDeliver | null;
  onSaveVersion: () => void;
  onEditNotes: () => void;
  onOpenDeliver: () => void;
}) {
  const versionLabel = scene?.version_label || "No version saved";
  return (
    <Card tone={deliver && deliver.todos_pending > 0 ? "warn" : "neutral"} title={versionLabel}>
      {deliver ? (
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          {deliver.todos_pending > 0 ? `⚠ ${deliver.todos_pending} TODOs pendientes` : "No pending TODOs."}
        </p>
      ) : (
        <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
          Notes unavailable this refresh.
        </p>
      )}
      <CardActions>
        <CardAction label="Save Version" onClick={onSaveVersion} />
        <CardAction label="Edit Notes" onClick={onEditNotes} />
        <CardAction label="Deliver →" onClick={onOpenDeliver} />
      </CardActions>
    </Card>
  );
}

/** The 4-card "shot health" dashboard — the approved mockup's grid (QC,
 * Assets, Render, Deliver). Every card independently tolerates its
 * `PanelOverview` block being `null` (one subsystem failing must never
 * blank the others, see `panel_ops.py`'s `_guarded_block`). Quick-fix and
 * navigation buttons are thin callbacks — `PanelPage` owns the actual
 * `runPaletteAction`/`postPanelOpenForm` wiring and the confirm contract. */
export function OverviewCards({
  overview,
  actions,
  onFix,
  busyFix,
  onOpenQc,
  onOpenHub,
  onValidateRender,
  onSaveVersion,
  onEditNotes,
  onOpenDeliver,
}: {
  overview: PanelOverview;
  actions: PaletteAction[];
  onFix: (id: string) => void;
  busyFix: string | null;
  onOpenQc: () => void;
  onOpenHub: () => void;
  onValidateRender: () => void;
  onSaveVersion: () => void;
  onEditNotes: () => void;
  onOpenDeliver: () => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
      <QcCard qc={overview.qc} actions={actions} onFix={onFix} onOpenQc={onOpenQc} busyFix={busyFix} />
      <AssetsCard assets={overview.assets} onOpenHub={onOpenHub} />
      <RenderCard render={overview.render} onValidate={onValidateRender} />
      <DeliverCard
        scene={overview.scene}
        deliver={overview.deliver}
        onSaveVersion={onSaveVersion}
        onEditNotes={onEditNotes}
        onOpenDeliver={onOpenDeliver}
      />
    </div>
  );
}
