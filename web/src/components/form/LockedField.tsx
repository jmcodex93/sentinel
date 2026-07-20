import { Lock } from "lucide-react";

interface LockedFieldProps {
  value: string;
  /** Why this field is machine-controlled, e.g. "defined by project
   * ruleset" (Standard FPS) or "Auto-detected from Redshift RenderView"
   * (snapshot dir) — see `form/settings/state`'s `fps.locked_reason` /
   * `snapshot_dir.detected` in web_ops.py. */
  reason: string;
}

/** A disabled-looking field showing a value the artist cannot edit here,
 * plus a muted note explaining why — the Settings page's `fps`/`snapshot_dir`
 * locks (mirrors `SentinelSettingsDialog`'s `Enable(..., False)` fields). */
export function LockedField({ value, reason }: LockedFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="flex items-center gap-2 rounded-md border px-3 py-1.5"
        style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
      >
        <Lock size={12} strokeWidth={2.25} style={{ color: "var(--color-muted)" }} aria-hidden="true" />
        <span className="text-body flex-1 truncate" style={{ color: "var(--color-muted)" }}>
          {value}
        </span>
      </div>
      <p className="text-caption" style={{ color: "var(--color-muted)" }}>
        {reason}
      </p>
    </div>
  );
}
