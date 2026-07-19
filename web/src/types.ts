/**
 * Delivery Summary payload contract — see docs/superpowers/plans/2026-07-18-ui-foundation.md
 * (Task 3 Interfaces) for the canonical shape. Produced by
 * `GET /api/report/delivery` (Task 4, `plugin/sentinel/ui/reports_dialog.py`
 * mapping `sentinel_manifest.json` — see `plugin/sentinel/manifest.py` for
 * the real per-asset fields this gets built from).
 */

export type AssetStatus = "collected" | "missing" | "external";

export interface DeliveryAsset {
  path: string;
  status: AssetStatus;
  /** Human-readable origin, e.g. "material · Grip Handle" — built from the
   * manifest's source_type/channel/host fields (see manifest.py). */
  provenance: string;
}

export interface DeliveryQc {
  /** Pre-formatted score, e.g. "9/12" (manifest stores it as a string —
   * see ui/flows.py `preflight_score.get("score", "")`). */
  score: string;
  passed?: number;
  total?: number;
}

export interface DeliverySummary {
  total: number;
  collected: number;
  missing: number;
  external: number;
}

export interface DeliveryZip {
  path: string;
  bytes: number;
}

export interface DeliveryReport {
  scene: string;
  collected_at: string;
  artist: string;
  /** Original scene version at collect time, e.g. "v022" — passthrough of
   * the manifest's original_version, not part of the strict Task 3
   * contract but useful in the header meta line; absent when unknown. */
  version?: string | null;
  qc: DeliveryQc | null;
  summary: DeliverySummary;
  zip: DeliveryZip | null;
  assets: DeliveryAsset[];
  pending_todos: number;
  manifest_path: string;
}

/** Discriminated result of a delivery-report fetch, covering every state
 * the Delivery Summary page renders (loading is the fetch-in-flight gap
 * between mount and one of these). */
export type DeliveryReportResult =
  | { kind: "ok"; data: DeliveryReport }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };
