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

/**
 * QC Report payload contract — mirrors `qc_report_payload` in
 * plugin/sentinel/webbridge.py exactly (see its docstring for the field-by-
 * field mapping from qc/score.py `compute_score`). Produced by
 * `GET /api/report/qc`.
 */

export type QcCheckStatus = "ok" | "fail" | "disabled";
export type QcSeverity = "FAIL" | "WARN";

export interface QcCheckDetail {
  label: string;
  message: string;
  extras: Record<string, unknown> | null;
}

export interface QcCheck {
  id: string;
  label: string;
  severity: QcSeverity;
  has_fix: boolean;
  status: QcCheckStatus;
  count: number | null;
  new: number | null;
  accepted: number | null;
  details: QcCheckDetail[];
}

export interface QcRuleset {
  name: string;
  path: string | null;
  shadowed: string[];
}

export interface QcScore {
  score: string;
  passed: number;
  total: number;
  disabled_count: number;
  baseline_status: string | null;
}

export interface QcReport {
  scene: string;
  ruleset: QcRuleset;
  score: QcScore;
  checks: QcCheck[];
  disabled: string[];
}

export type QcReportResult =
  | { kind: "ok"; data: QcReport }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/**
 * Doctor Report payload contract — mirrors `doctor_report_payload` in
 * plugin/sentinel/webbridge.py (flat item list, no natural grouping in the
 * real doctor.py engine — see its docstring). Produced by
 * `GET /api/report/doctor`.
 */

export type DoctorItemStatus = "ok" | "warn" | "fail" | "info";

export interface DoctorItem {
  id: string;
  label: string;
  status: DoctorItemStatus;
  detail: string;
  hint: string;
}

export interface DoctorMeta {
  sentinel_version: string;
  c4d_version: string;
  os: string;
  renderers: string;
  settings_path: string;
}

export interface DoctorReport {
  meta: DoctorMeta;
  items: DoctorItem[];
}

export type DoctorReportResult =
  | { kind: "ok"; data: DoctorReport }
  | { kind: "error"; message: string };

/**
 * Supervisor Report payload contract — mirrors `supervisor_report_payload`
 * in plugin/sentinel/webbridge.py. Produced by `GET /api/report/supervisor`
 * (folder resolved from `?folder=` or the last-scanned folder in settings —
 * see reports_dialog.py `_op_report_supervisor`).
 */

export interface SupervisorTrajectoryStep {
  from_version: string;
  to_version: string;
  broke: string[];
  recovered: string[];
  no_data: boolean;
}

export interface SupervisorShot {
  base: string;
  folder: string;
  version_count: number;
  last_version: string;
  status: string;
  score: string;
  qc_label: string;
  todos_total: number;
  todos_pending: number;
  days_idle: number | null;
  last_timestamp: string;
  artist: string;
  flags: string[];
  trajectory: SupervisorTrajectoryStep[];
}

export interface SupervisorReport {
  folder: string;
  generated_at: string;
  shot_count: number;
  warnings: string[];
  shots: SupervisorShot[];
}

export type SupervisorReportResult =
  | { kind: "ok"; data: SupervisorReport }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/**
 * Render Validation Report payload contract — mirrors
 * `render_validation_payload` in plugin/sentinel/webbridge.py. Produced by
 * `GET /api/report/render_validation`.
 */

export type RenderCheckStatus = "OK" | "FAIL" | "WARN";

export interface RenderValidationCheck {
  id: string;
  label: string;
  status: RenderCheckStatus;
  count: number;
  items: Record<string, unknown>[];
}

export interface RenderValidationContext {
  take_name: string;
  version: string;
  frame_start: number | null;
  frame_end: number | null;
  frame_mode: string;
}

export interface RenderValidationSummary {
  failures: number;
  warnings: number;
  streams: number;
}

export interface RenderValidationReport {
  report_path: string;
  generated_at: string;
  passed: boolean;
  context: RenderValidationContext;
  summary: RenderValidationSummary;
  checks: RenderValidationCheck[];
}

export type RenderValidationReportResult =
  | { kind: "ok"; data: RenderValidationReport }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/**
 * Save Version form contract — mirrors `_op_form_save_version_state` /
 * `_op_form_save_version_submit` in plugin/sentinel/ui/web_ops.py and
 * `validate_save_version_submit` / `save_version_status_options` /
 * `SAVE_VERSION_FINAL_HINT` in plugin/sentinel/webbridge.py. Produced by
 * `GET /api/form/save_version/state`, submitted via
 * `POST /api/form/save_version/submit`.
 */

export interface SaveVersionStatusOption {
  label: string;
  /** "" (WIP) | "TR" | "CR" | "FINAL" — versioning.py STATUS_OPTIONS. */
  suffix: string;
  /** What the next save will be named with this status selected —
   * precomputed server-side via `preview_next_filename` so the SPA never
   * round-trips just to update this label. */
  preview_filename: string;
}

/** `versioning.format_version_row()` output, or null when the scene has no
 * saved version yet. */
export interface SaveVersionLast {
  version_label: string;
  version_int: number;
  status_label: string;
  time_label: string;
  comment: string;
  qc_label: string;
  qc_pass: boolean | null;
  filename: string;
  path: string;
  artist: string;
}

export interface SaveVersionState {
  scene: string;
  last_version: SaveVersionLast | null;
  qc: { score: string; pass: boolean };
  status_options: SaveVersionStatusOption[];
}

export type SaveVersionStateResult =
  | { kind: "ok"; data: SaveVersionState }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

export interface SaveVersionSubmitPayload {
  comment: string;
  /** Suffix from `status_options` ("", "TR", "CR", "FINAL"). Ignored
   * server-side when `custom_status` is non-empty. */
  status: string;
  custom_status?: string;
}

export interface SaveVersionSubmitResponse {
  ok: boolean;
  error?: string;
  message?: string;
  version?: string;
  status?: string;
  path?: string;
  /** Non-blocking "final in comment" soft warning — rides along on a
   * *successful* response, never gates the save (SAVE_VERSION_FINAL_HINT). */
  warning?: string | null;
}

/**
 * Notes form contract — mirrors `_op_form_notes_state` /
 * `_op_form_notes_submit` + `merge_notes_submission` in
 * plugin/sentinel/webbridge.py. Produced by `GET /api/form/notes/state`,
 * submitted via `POST /api/form/notes/submit`.
 */

export interface NotesTodo {
  /** null for a not-yet-saved TODO the SPA just created — `add_todo`
   * assigns the real id server-side on submit. */
  id: number | null;
  text: string;
  done: boolean;
}

export interface NotesState {
  notes_text: string;
  todos: NotesTodo[];
  scene_base: string;
}

export type NotesStateResult =
  | { kind: "ok"; data: NotesState }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

export interface NotesSubmitPayload {
  notes_text: string;
  todos: NotesTodo[];
}

export interface NotesSubmitResponse {
  ok: boolean;
  error?: string;
}

/**
 * Settings form contract — mirrors `_op_form_settings_state` /
 * `_op_form_settings_submit` + `validate_settings_submit` /
 * `SETTINGS_*_OPTIONS` in plugin/sentinel/webbridge.py. Produced by
 * `GET /api/form/settings/state`, submitted via
 * `POST /api/form/settings/submit`.
 */

export interface SettingsState {
  fps: { value: number; options: number[]; locked: boolean; locked_reason: string | null };
  /** `value` is an index into `options` (0 = Nuke, 1 = After Effects). */
  compositor: { value: number; options: string[] };
  multipart_default: boolean;
  slate: { value: boolean };
  mv_max_motion: number;
  snapshot_dir: { value: string; detected: boolean; locked: boolean };
  history_max: { value: number; options: number[] };
}

export type SettingsStateResult =
  | { kind: "ok"; data: SettingsState }
  | { kind: "error"; message: string };

export interface SettingsSubmitPayload {
  fps: number;
  compositor: number;
  multipart_default: boolean;
  slate: boolean;
  mv_max_motion: number;
  snapshot_dir: string;
  history_max: number;
}

export interface SettingsSubmitResponse {
  ok: boolean;
  error?: string;
}

/**
 * Quality Gate form contract — mirrors `_op_form_gate_state` /
 * `_op_form_gate_submit` + `gate_state_payload` / `gate_can_proceed` in
 * plugin/sentinel/webbridge.py. Produced by `GET /api/form/gate/state`,
 * submitted via `POST /api/form/gate/submit`.
 */

export type GateBucket = "fixable" | "blocking" | "advisory";

export interface GateViolationDetail {
  label: string;
  message: string;
  extras: Record<string, unknown> | null;
}

export interface GateCheck {
  check_id: string;
  label: string;
  severity: QcSeverity | "";
  bucket: GateBucket;
  /** Whether this check's *current* new-violation count blocks proceeding
   * (a WARN-severity fixable check, e.g. unused materials, never blocks). */
  blocks: boolean;
  has_fix: boolean;
  new_count: number;
  violations: GateViolationDetail[];
}

export interface GateState {
  passed: boolean;
  /** True when the baseline sidecar exists but failed to parse — surfaced
   * so "Accept" isn't offered as if it will silently work. */
  sidecar_invalid: boolean;
  checks: GateCheck[];
}

export type GateStateResult =
  | { kind: "ok"; data: GateState }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

export type GateSubmitAction =
  | { action: "fix_all" }
  | { action: "accept"; ids: string[]; author: string; reason: string }
  | { action: "proceed" }
  | { action: "cancel" };

export interface GateSubmitResponse {
  ok: boolean;
  error?: string;
  /** Present for `proceed` — whether every blocking violation is resolved. */
  proceed?: boolean;
  /** Present for `fix_all` — check_ids that were fixed. */
  fixed?: string[];
  /** Present for `accept` — whether any new acceptance was actually added. */
  accepted?: boolean;
  /** Fresh gate state after a mutating action, echoed back so the page
   * never needs a second round trip. */
  state?: GateState;
}
