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

/**
 * Command Palette contract — mirrors `palette_actions_payload` in
 * plugin/sentinel/webbridge.py (`PALETTE_ACTIONS`) and `_op_palette_run` in
 * plugin/sentinel/ui/web_ops.py. Produced by `GET /api/palette/actions`,
 * actions run via `POST /api/palette/run`.
 */

export interface PaletteAction {
  id: string;
  label: string;
  group: string;
  enabled: boolean;
  reason: string | null;
  /** True for the two DECISIÓN-classified destructive Quick Fix actions
   * (delete unused materials, rewrite FPS/frame range) — see the
   * `PALETTE_ACTIONS` comment in webbridge.py. The palette must show
   * `confirm_label` as an explicit yes/no step and resubmit
   * `palette/run` with `confirm: true` before the action actually runs. */
  requires_confirm: boolean;
  confirm_label: string | null;
}

export type PaletteActionsResult =
  | { kind: "ok"; data: PaletteAction[] }
  | { kind: "error"; message: string };

export interface PaletteRunResponse {
  ok: boolean;
  error?: string;
  /** Toast-able result message for a `kind: "run"` action. */
  message?: string;
  /** Present for a `kind: "navigate"` action — the SPA page (a `FormPage`,
   * e.g. "form/save_version") to switch to client-side. */
  navigate?: string;
}

/**
 * Asset Hub contract (Phase 5) — mirrors `hub_inventory_payload` in
 * plugin/sentinel/webbridge.py and the ops in
 * plugin/sentinel/ui/hub_ops.py (`HUB_OPS`), routed through the same
 * `/api/<op>` dispatch as every other op (see `reports_dialog.py`'s
 * `HUB_OPS` merge + the `hub/job_status` special-case answered outside the
 * `MainThreadQueue`). Produced by `GET /api/hub/inventory`.
 */

export type HubAssetStatus = "missing" | "absolute" | "empty" | "asset_uri" | "ok";

export interface HubOwner {
  name: string;
  kind: string;
  channel: string;
}

export interface HubAsset {
  key: string;
  path: string;
  resolved_path: string | null;
  status: HubAssetStatus;
  asset_type: string;
  size_bytes: number | null;
  size_label: string;
  owners: HubOwner[];
  repathable: boolean;
  has_thumb: boolean;
}

export interface HubTotals {
  count: number;
  missing: number;
  absolute: number;
  total_bytes: number;
  unsized: number;
  total_label: string;
  by_type: Record<string, number>;
}

export interface HubInventory {
  scene_name: string;
  skipped: number;
  assets: HubAsset[];
  totals: HubTotals;
}

export type HubInventoryResult =
  | { kind: "ok"; data: HubInventory }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/** `GET /api/hub/state_stamp` — see `_op_hub_state_stamp` in hub_ops.py.
 * Consumed by `fetchHubStateStamp`, which collapses this to `string | null`
 * (the SPA never needs to distinguish "no document" from a network error —
 * either way there's nothing to compare against). */
export interface HubStateStamp {
  stamp: string;
}

/** `GET /api/hub/presets` — see `_op_hub_presets` in hub_ops.py, reshaping
 * `ui.dialogs.load_repath_presets` (persisted Texture Repathing Find/Replace
 * history, capped at 5, de-duped). */
export interface HubPreset {
  find: string;
  replace: string;
}

export type HubPresetsResult =
  | { kind: "ok"; data: HubPreset[] }
  | { kind: "error"; message: string };

/** `POST /api/hub/presets/save` — see `_op_hub_presets_save` in hub_ops.py. */
export interface HubPresetsSaveResponse {
  ok: boolean;
  error?: string;
}

/** One pending Find/Replace or relink edit, as sent to `hub/apply_repath`
 * (`payload.get("changes")` in `_op_hub_apply_repath`) — `key` is the
 * `HubAsset.key` this row was fetched with, re-resolved server-side against
 * a fresh scan (HTTP is stateless, see the op's own docstring). */
export interface HubApplyChange {
  key: string;
  new_path: string;
}

/** `POST /api/hub/apply_repath` — see `_op_hub_apply_repath` in
 * hub_ops.py. `stamp` (added after the Task 3/4/6 payload block was
 * written) is a fresh `hub/state_stamp`-equivalent fingerprint the mutation
 * computes *after* its own `c4d.EventAdd()`, so the SPA can re-anchor its
 * polling baseline from it and never mistake its own edit for an external
 * scene change. */
export interface HubApplyResponse {
  ok: boolean;
  error?: string;
  applied?: number;
  errors?: { key: string; error: string }[];
  stamp?: string;
}

/** `POST /api/hub/select_owner` — see `_op_hub_select_owner` in
 * hub_ops.py. Same trailing `stamp` reasoning as `HubApplyResponse`. */
export interface HubSelectOwnerResponse {
  ok: boolean;
  error?: string;
  stamp?: string;
}

/** `POST /api/hub/pick_path` — see `_op_hub_pick_path` in hub_ops.py (a
 * blocking native `LoadDialog`, safe under the fase-4 per-request
 * `MainThreadQueue` lock). */
export interface HubPickPathResponse {
  ok: boolean;
  error?: string;
  path?: string;
}

/** `POST /api/hub/match_folder` — see `_op_hub_match_folder` in hub_ops.py
 * (Search Folder for Missing). `matches` are only the unambiguous
 * single-candidate hits — ambiguous (2+ candidates) is just a count, the
 * SPA never auto-picks. */
export interface HubMatchFolderResponse {
  ok: boolean;
  error?: string;
  matches?: { key: string; match: string }[];
  ambiguous?: number;
  truncated?: boolean;
}

/** `POST /api/hub/make_relative` — see `_op_hub_make_relative` in
 * hub_ops.py (Make All Relative). Read-only: stages `changes` for the SPA
 * to merge into `pending`, does not write anything itself. */
export interface HubMakeRelativeResponse {
  ok: boolean;
  error?: string;
  changes?: { key: string; new_path: string }[];
  skipped_cross_drive?: number;
}

export interface HubCollectStartResponse {
  ok: boolean;
  error?: string;
  job_id?: string;
}

export interface HubCollectResult {
  target_dir: string;
  delivery_filename: string;
  assets_collected: number;
  assets_missing: number;
  zip: { zip_path: string; files: number; bytes: number } | null;
  zip_error: string | null;
  pending_todos: number;
  report: DeliveryReport; // reuses the existing DeliveryReport type
}

/**
 * Hub Shrink contract (Phase 5.2) — mirrors `_op_hub_shrink_start` /
 * `_run_shrink_for_job` in plugin/sentinel/ui/hub_ops.py and `shrink_plan`
 * in plugin/sentinel/assets.py. Produced by `POST /api/hub/shrink_start`
 * `{keys, target_px}`; the job result (fetched via the shared
 * `fetchHubJobStatus`) is this shape, not `HubCollectResult` — see
 * `HubJobStatus.result` below.
 */
export interface HubShrinkStartResponse {
  ok: boolean;
  /** "no_document" | "invalid_target" | "nothing_to_shrink" | "job_running". */
  error?: string;
  job_id?: string;
}

export interface HubShrinkResultItem {
  key: string;
  target_path: string;
  resolved_path: string;
}

export interface HubShrinkSkip {
  key: string;
  reason: string;
}

export interface HubShrinkError {
  key: string;
  error: string;
}

export interface HubShrinkResult {
  shrunk: HubShrinkResultItem[];
  skipped: HubShrinkSkip[];
  errors: HubShrinkError[];
  bytes_saved: number;
}

/** `POST /api/hub/copy_into_project` — see `_op_hub_copy_into_project` in
 * hub_ops.py. Synchronous (no job) — a handful of `shutil.copy2` calls plus
 * one relink undo step. Same trailing `stamp` reasoning as `HubApplyResponse`. */
export interface HubCopyResponse {
  ok: boolean;
  /** "no_document" | "unsaved_document". */
  error?: string;
  copied?: number;
  reused?: number;
  errors?: { key: string; error: string }[];
  stamp?: string;
}

/** `GET /api/hub/job_status?job_id=<id>` — see `webbridge.JobRegistry.status`
 * and the `hub/job_status` special-case in `reports_dialog.py` (answered
 * directly on the HTTP server thread, bypassing `MainThreadQueue`, so
 * polling stays live while a collect job blocks the main thread). Returned
 * raw (not wrapped in a `{kind: ...}` result) — the shape itself already
 * carries every state the SPA needs to render, including an unknown/expired
 * `job_id` via `error`. `result` widens to a union (Fase 5.2): a
 * `"kind": "shrink"` job spec resolves to `HubShrinkResult`, everything else
 * (the pre-5.2 default, `"collect"`) resolves to `HubCollectResult` — the
 * page reading it knows which one to expect from which action it started. */
export interface HubJobStatus {
  job_id?: string;
  state?: "pending" | "running" | "done" | "error";
  phase?: string;
  detail?: string;
  pct?: number;
  result?: HubCollectResult | HubShrinkResult | null;
  error?: string;
}

/**
 * Hub Metadata contract — mirrors `_meta_for` in plugin/sentinel/ui/hub_ops.py
 * (Task 2). Produced by `POST /api/hub/meta` with `{keys: [...]}` payload
 * (see `_op_hub_meta`). Per-asset image metadata extracted from file headers
 * (width, height, channels, bit_depth, colorspace) plus derived fields
 * (vram_bytes, vram_label, res_label, res_tier).
 */
export type HubResTier = "16k" | "8k" | "4k" | "2k" | "1k" | "sm";

export interface HubMeta {
  width: number;
  height: number;
  channels: number;
  bit_depth: number;
  colorspace: string;
  vram_bytes: number;
  vram_label: string;
  res_label: string;
  res_tier: HubResTier;
}

/**
 * Hub Metadata Totals contract — mirrors the response from
 * `GET /api/hub/meta_totals` (see `_op_hub_meta_totals` in hub_ops.py).
 * Aggregated metrics over all unique assets in the inventory that have
 * cached metadata. `covered`/`total` indicates partial vs complete scan
 * state (the SPA shows "~" prefix while `covered < total`).
 */
export interface HubMetaTotals {
  vram_bytes: number;
  vram_label: string;
  disk_bytes: number;
  disk_label: string;
  covered: number;
  total: number;
}

/**
 * Hub resolution-variant contract (Fase 5.3) — mirrors `_op_hub_variants` in
 * plugin/sentinel/ui/hub_ops.py. `basename` is the sibling file's name only
 * (never a full path — the client only needs it to build the relink via
 * `postHubSwitchRes`); `px` is the longest-edge pixel size the shared
 * `split_res_token` token maps to. A key only appears in the response's
 * record when its detected group has >=2 members (itself included) — see
 * `find_res_variants` in assets.py. `px` is `null` for a "bare base"
 * sibling — the un-tokened original a Shrink copy was derived from — when
 * the server couldn't enrich it with a real pixel size (`_meta_for` failed
 * to parse the file); such an entry is never a valid exact-px switch
 * target, but it does still count toward the family for "Highest".
 */
export interface HubVariant {
  basename: string;
  px: number | null;
}

/** `POST /api/hub/switch_res` — see `_op_hub_switch_res` in hub_ops.py.
 * Relink-only (no file writes), same trailing `stamp` reasoning as
 * `HubApplyResponse`. `skipped` reasons are `"no_variant"` (no sibling at
 * the requested target) or `"already_there"` (the current file already IS
 * that target — covers "Highest" when nothing is higher). */
export interface HubSwitchResponse {
  ok: boolean;
  /** "no_document" | "invalid_target" | "too_many_keys". */
  error?: string;
  switched?: string[];
  skipped?: { key: string; reason: string }[];
  errors?: { key: string; error: string }[];
  stamp?: string;
}

/**
 * Hub UI State contract — mirrors the response from `GET /api/hub/ui_state`
 * and the payload for `POST /api/hub/ui_state/save` (see `_op_hub_ui_state`
 * and `_op_hub_ui_state_save` in hub_ops.py). Persisted in `sentinel_settings.json`
 * under the key `hub_spa_ui`. Carries resizable column widths and sort spec
 * across sessions.
 */
export interface HubUiState {
  col_widths?: Record<string, number>;
  sort?: { col: string; dir: "asc" | "desc" };
}

/**
 * Panel SPA "shot health" dashboard contract (Fase 6.0) — mirrors
 * ``build_panel_overview`` / ``PANEL_OPS`` in
 * plugin/sentinel/ui/panel_ops.py. Produced by ``GET /api/panel/overview``.
 * Each block is independently nullable: a failure isolated to one subsystem
 * (see that module's ``_guarded_block``) degrades only that card, never the
 * whole dashboard — every consumer of this type MUST render a null block as
 * an unavailable/empty card, not crash.
 */

export interface PanelQcTopCheck {
  check_id: string;
  label: string;
  count: number;
}

export interface PanelQc {
  passed: number;
  total: number;
  disabled: number;
  top: PanelQcTopCheck[];
  /** Palette action ids (fix_lights/fix_cameras/fix_materials/fix_fps)
   * currently enabled — see `_PANEL_FIX_CHECK_ID` in panel_ops.py. */
  fixable: string[];
}

export interface PanelScene {
  name: string;
  path_set: boolean;
  shot_id: string;
  artist: string;
  version_label: string | null;
  version_age: string | null;
  polys_label: string;
}

export interface PanelAssets {
  count: number;
  missing: number;
  disk_label: string;
  /** Null while the Hub's image-metadata cache is cold this session (never
   * opened yet) — the overview shows "—" rather than a misleading "0 B". */
  vram_label: string | null;
}

export interface PanelRender {
  preset_name: string | null;
  fps: number;
  resolution: string | null;
  /** Always null in v1 — no engine helper answers "does this scene have a
   * multiformat Take" without a from-scratch scene walk (see panel_ops.py
   * module docstring). */
  multiformat: boolean | null;
}

export interface PanelDeliver {
  todos_pending: number;
  notes_present: boolean;
  /** Always null in v1 — no "last collected" accessor exists yet. */
  last_delivery_age: string | null;
}

export interface PanelOverview {
  scene: PanelScene | null;
  qc: PanelQc | null;
  assets: PanelAssets | null;
  render: PanelRender | null;
  deliver: PanelDeliver | null;
}

export type PanelOverviewResult =
  | { kind: "ok"; data: PanelOverview }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/** `POST /api/panel/open_form` — see `_op_panel_open_form` in panel_ops.py. */
export interface PanelOpenFormResponse {
  ok: boolean;
  error?: string;
}

/**
 * Panel QC section contract (Fase 6.1) — mirrors `_op_panel_qc`'s full
 * per-check FAIL/WARN/OK/disabled breakdown and its three mutations
 * (`panel/qc/select`, `panel/qc/accept`, `panel/qc/fix_all`) in
 * plugin/sentinel/ui/panel_ops.py, reshaped via the pure
 * `webbridge.group_qc_by_severity`. Named `PanelQcSection`, not `PanelQc`,
 * to avoid colliding with the existing top-3 `PanelQc` overview-card type
 * above — the two are different shapes for the same underlying data.
 */
export interface PanelQcCheck {
  id: string;
  label: string;
  severity: "FAIL" | "WARN";
  count: number;
  /** Baseline-aware "new" violation count; `null` with no active baseline. */
  new: number | null;
  /** Baseline-aware accepted count; `null` with no active baseline. */
  accepted: number | null;
  /** Same shape as `QcCheck.details` above (`{label, message, extras}`) —
   * `group_qc_by_severity` passes `row["details"]` straight through, never a
   * flattened string list. */
  detail: QcCheckDetail[];
  can_select: boolean;
  can_fix: boolean;
  /** Matching `PALETTE_ACTIONS` quick-fix id, or `null` if this check has
   * no Quick Fix action. */
  fix_action_id: string | null;
  /** True when every current violation is already baselined (`new === 0`
   * and `accepted > 0`) — the row still renders as a FAIL/WARN card. */
  accepted_all: boolean;
}

export interface PanelQcSection {
  score: { passed: number; total: number; disabled: number };
  fail: PanelQcCheck[];
  warn: PanelQcCheck[];
  ok_count: number;
  disabled_count: number;
}

export type PanelQcResult =
  | { kind: "ok"; data: PanelQcSection }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/** `POST /api/panel/qc/select` — see `_op_panel_qc_select` in panel_ops.py.
 * Cycles ONE flagged object/material per call (module-side cursor keyed by
 * check_id, mirrors the native per-instance idx); `cursor_pos`/`total` let
 * the SPA show progress like "Select 3/8". */
export interface PanelQcSelectResponse {
  ok: boolean;
  error?: string;
  stamp?: string;
  cursor_pos?: number;
  total?: number;
}

/** `POST /api/panel/qc/accept` — see `_op_panel_qc_accept` in panel_ops.py.
 * `qc` echoes a fresh `panel/qc` payload so the SPA never needs a second
 * round trip after a successful acceptance. */
export interface PanelQcAcceptResponse {
  ok: boolean;
  error?: string;
  stamp?: string;
  qc?: PanelQcSection;
}

/** `POST /api/panel/qc/fix_all` — see `_op_panel_qc_fix_all` in panel_ops.py.
 * Same `qc` echo as `PanelQcAcceptResponse`. */
export interface PanelQcFixAllResponse {
  ok: boolean;
  error?: string;
  stamp?: string;
  qc?: PanelQcSection;
}

/**
 * Panel Render section contract (Fase 6.2) — mirrors `build_panel_render`
 * and its mutation/action ops in `plugin/sentinel/ui/panel_render_ops.py`.
 * Field names copied 1:1 from that module (`_panel_preset_block`,
 * `_panel_frame_block`, `_panel_aovs_block`, `_panel_snapshots_block`,
 * `_panel_postrender_block`) — every block is independently nullable
 * (`_guarded_block`), and `PanelRenderAovs` additionally carries its own
 * `{error: "redshift_unavailable"}` shape when the RS Python module isn't
 * importable.
 */
export interface PanelRenderPreset {
  preset_name: string | null;
  preset_names: string[];
  fps: number | null;
  resolution: string | null;
}

export interface PanelRenderFrame {
  has_tag: boolean;
  camera_name: string | null;
  /** Not populated by `_panel_frame_block` in v1 (only `has_tag`/
   * `camera_name` are read there) — present for forward compat with the
   * `format_count` field the Task 3 brief describes; `null` until an
   * engine helper answers it, same convention as `PanelRender.multiformat`
   * in the overview card. */
  format_count?: number | null;
}

export interface PanelRenderAovsOk {
  count: number;
  multipart: boolean;
  target: string;
  light_groups: boolean;
  light_group_names: string[];
}

export type PanelRenderAovs = PanelRenderAovsOk | { error: "redshift_unavailable" };

export interface PanelRenderSnapshots {
  dir: string | null;
  origin: "auto" | "manual";
  watch_enabled: boolean;
}

export interface PanelRenderPostrenderAvailable {
  available: true;
  generated_at: string;
  passed: boolean;
}

export interface PanelRenderPostrenderUnavailable {
  available: false;
}

export type PanelRenderPostrender = PanelRenderPostrenderAvailable | PanelRenderPostrenderUnavailable;

export interface PanelRenderSection {
  preset: PanelRenderPreset | null;
  frame: PanelRenderFrame | null;
  aovs: PanelRenderAovs | null;
  snapshots: PanelRenderSnapshots | null;
  postrender: PanelRenderPostrender | null;
}

export type PanelRenderResult =
  | { kind: "ok"; data: PanelRenderSection }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };

/** Every `panel/render/*` mutation returns this same shape (see the
 * module docstring in `panel_render_ops.py`): `render` echoes a fresh
 * `panel/render` payload so the SPA never needs a second round trip after
 * a successful mutation, and a destructive op without `confirm: true`
 * returns `{ok: false, error: "confirm_required", confirm_label}`. */
export interface PanelRenderMutationResponse {
  ok: boolean;
  error?: string;
  stamp?: string;
  render?: PanelRenderSection;
  confirm_label?: string;
}

/** `GET /api/panel/render/aov_list` — see `_op_panel_render_aov_list` in
 * panel_render_ops.py. Read-only, for the inline "Show AOVs" expand.
 * `{error: "redshift_unavailable"}` when the RS Python module isn't
 * importable — never a crash. */
export interface PanelRenderAovListEntry {
  name: string;
  type: string;
}

export interface PanelRenderAovListOk {
  aovs: PanelRenderAovListEntry[];
  target: string;
  light_groups: boolean;
  tier_coverage: {
    essentials_missing: string[];
    production_missing: string[];
  };
}

export type PanelRenderAovListResult =
  | { kind: "ok"; data: PanelRenderAovListOk }
  | { kind: "empty"; reason: string }
  | { kind: "error"; message: string };
