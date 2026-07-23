import mockDeliveryReport from "../mock/delivery-summary.json";
import mockDoctorReport from "../mock/doctor-report.json";
import mockGate from "../mock/form-gate.json";
import mockNotes from "../mock/form-notes.json";
import mockPanelOverview from "../mock/panel-overview.json";
import mockPanelQc from "../mock/panel-qc.json";
import mockPanelRender from "../mock/panel-render.json";
import mockPanelRenderAovList from "../mock/panel-render-aov-list.json";
import mockSaveVersion from "../mock/form-save-version.json";
import mockSettings from "../mock/form-settings.json";
import mockHubInventory from "../mock/hub-inventory.json";
import mockHubMeta from "../mock/hub-meta.json";
import mockHubVariants from "../mock/hub-variants.json";
import mockPaletteActions from "../mock/palette-actions.json";
import mockQcReport from "../mock/qc-report.json";
import mockRenderValidationReport from "../mock/render-validation.json";
import mockSupervisorReport from "../mock/supervisor-report.json";
import type {
  DeliveryReport,
  DeliveryReportResult,
  DoctorReport,
  DoctorReportResult,
  GateState,
  GateStateResult,
  GateSubmitAction,
  GateSubmitResponse,
  HubApplyChange,
  HubApplyResponse,
  HubCollectStartResponse,
  HubCopyResponse,
  HubInventory,
  HubInventoryResult,
  HubJobStatus,
  HubMeta,
  HubMetaTotals,
  HubMakeRelativeResponse,
  HubMatchFolderResponse,
  HubPickPathResponse,
  HubPreset,
  HubPresetsResult,
  HubPresetsSaveResponse,
  HubSelectOwnerResponse,
  HubShrinkStartResponse,
  HubSwitchResponse,
  HubUiState,
  HubVariant,
  NotesState,
  NotesStateResult,
  NotesSubmitPayload,
  NotesSubmitResponse,
  PanelDeliverState,
  PanelOpenFormResponse,
  PanelOpenVersionResponse,
  PanelOverview,
  PanelOverviewResult,
  PanelQcAcceptResponse,
  PanelQcFixAllResponse,
  PanelQcResult,
  PanelQcSection,
  PanelQcSelectResponse,
  PanelRenderAovListOk,
  PanelRenderAovListResult,
  PanelRenderMutationResponse,
  PanelRenderResult,
  PanelRenderSection,
  PaletteAction,
  PaletteActionsResult,
  PaletteRunResponse,
  QcReport,
  QcReportResult,
  RenderValidationReport,
  RenderValidationReportResult,
  SaveVersionState,
  SaveVersionStateResult,
  SaveVersionSubmitPayload,
  SaveVersionSubmitResponse,
  SettingsState,
  SettingsStateResult,
  SettingsSubmitPayload,
  SettingsSubmitResponse,
  SupervisorReport,
  SupervisorReportResult,
} from "../types";

/** dispatch() in plugin/sentinel/ui/reports_dialog.py (Task 4) returns
 * `{"error": "no_manifest"}` when no sentinel_manifest.json sits next to
 * the open scene, or `{"error": str, "traceback": str}` for any other
 * dispatch failure (see webbridge.py `MainThreadQueue.drain`). */
interface ApiErrorPayload {
  error: string;
  traceback?: string;
}

function isApiErrorPayload(value: unknown): value is ApiErrorPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as { error: unknown }).error === "string"
  );
}

/** Shared GET + error-envelope handling for every `/api/report/<op>`
 * endpoint. `emptyReasons` maps a known `{"error": <code>}` sentinel to the
 * human-readable "empty" reason shown by that page's EmptyState — any other
 * error string (including a network/JSON failure) becomes an ErrorState. */
async function fetchReport<T>(
  path: string,
  emptyReasons: Record<string, string>,
): Promise<{ kind: "ok"; data: T } | { kind: "empty"; reason: string } | { kind: "error"; message: string }> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch {
    return {
      kind: "error",
      message:
        "Could not reach the Sentinel Reports server. Is the plugin's Reports window still open in Cinema 4D?",
    };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "error", message: "Server returned invalid JSON." };
  }

  if (!response.ok) {
    const message = isApiErrorPayload(payload) ? payload.error : `Server responded ${response.status}.`;
    return { kind: "error", message };
  }

  if (isApiErrorPayload(payload)) {
    const reason = emptyReasons[payload.error];
    if (reason) return { kind: "empty", reason };
    return { kind: "error", message: payload.error };
  }

  return { kind: "ok", data: payload as T };
}

/** Fetches the Delivery Summary payload. `?mock=1` in the page URL serves
 * the bundled fixture instead — used for local dev (`npm run dev`) before
 * the C4D-hosted server exists, and for a screenshot-able build with no
 * live Cinema 4D behind it. */
export async function fetchDeliveryReport(): Promise<DeliveryReportResult> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mock") === "1") {
    return { kind: "ok", data: mockDeliveryReport as DeliveryReport };
  }

  return fetchReport<DeliveryReport>("/api/report/delivery" + window.location.search, {
    no_manifest:
      "No sentinel_manifest.json found next to the open scene. Open a collected package in Cinema 4D, or pass ?manifest=<path>.",
  });
}

/** Fetches the QC Report payload — runs the 12 checks on the active
 * document (`GET /api/report/qc`, see reports_dialog.py `_op_report_qc`). */
export async function fetchQcReport(): Promise<QcReportResult> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mock") === "1") {
    return { kind: "ok", data: mockQcReport as QcReport };
  }

  return fetchReport<QcReport>("/api/report/qc", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen Sentinel Reports.",
  });
}

/** Fetches the Doctor Report payload — Sentinel's non-network diagnostics
 * (`GET /api/report/doctor`). `_op_report_doctor` never returns a
 * `{"error": <code>}` sentinel (doctor.py's `run_all_diagnostics()` always
 * has something to report), so there is no "empty" reason to map — any
 * error dict here is an unexpected dispatch failure. */
export async function fetchDoctorReport(): Promise<DoctorReportResult> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mock") === "1") {
    return { kind: "ok", data: mockDoctorReport as DoctorReport };
  }

  const result = await fetchReport<DoctorReport>("/api/report/doctor", {});
  return result.kind === "empty" ? { kind: "error", message: result.reason } : result;
}

/** Fetches the Supervisor Report payload for `folder` (`GET
 * /api/report/supervisor?folder=<folder>`). Omitting `folder` falls back to
 * the last-scanned folder in settings (see reports_dialog.py
 * `_op_report_supervisor`) — used for the page's initial load. */
export async function fetchSupervisorReport(folder?: string): Promise<SupervisorReportResult> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mock") === "1") {
    return { kind: "ok", data: mockSupervisorReport as SupervisorReport };
  }

  const query = folder ? `?folder=${encodeURIComponent(folder)}` : "";
  return fetchReport<SupervisorReport>("/api/report/supervisor" + query, {
    no_folder: "Enter a project folder above and click Scan.",
  });
}

/** Fetches the last saved Render Validation report for the active document
 * (`GET /api/report/render_validation`, see reports_dialog.py
 * `_op_report_render_validation`). */
export async function fetchRenderValidationReport(): Promise<RenderValidationReportResult> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mock") === "1") {
    return { kind: "ok", data: mockRenderValidationReport as RenderValidationReport };
  }

  return fetchReport<RenderValidationReport>("/api/report/render_validation", {
    no_report: 'Run "Validate Render Output..." in the Render tab first.',
  });
}

// ---------------------------------------------------------------------------
// Form ops (Phase 4 Task 3) — save version, notes, settings, gate triage.
//
// State ops (`GET /api/form/<name>/state`) reuse `fetchReport` above, same
// error-envelope handling as the report pages. Submit ops
// (`POST /api/form/<name>/submit`) go through `postForm` below: unlike a
// report GET, a submit response's own `{ok: false, error}` is NOT an
// exceptional case to redirect into an ErrorState/EmptyState — it is normal
// validation feedback the calling page renders inline under the offending
// field (DESIGN.md's anti-popup rule), so `postForm` never throws and always
// resolves to the typed response shape, synthesizing `{ok: false, error}`
// only for a genuine network/JSON failure.
// ---------------------------------------------------------------------------

export function isMock(): boolean {
  return new URLSearchParams(window.location.search).get("mock") === "1";
}

async function postForm<T extends { ok: boolean; error?: string }>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return {
      ok: false,
      error: "Could not reach the Sentinel server. Is this form's window still open in Cinema 4D?",
    } as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    return { ok: false, error: "Server returned invalid JSON." } as T;
  }
}

/** `GET /api/form/save_version/state` — see web_ops.py `_op_form_save_version_state`. */
export async function fetchSaveVersionState(): Promise<SaveVersionStateResult> {
  if (isMock()) {
    return { kind: "ok", data: mockSaveVersion as SaveVersionState };
  }
  return fetchReport<SaveVersionState>("/api/form/save_version/state", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen Save Version.",
  });
}

/** Client-only mirror of `validate_save_version_submit`'s two visible rules
 * (empty comment rejected, "final" is a non-blocking warning) — used ONLY
 * in `?mock=1` mode, where there is no real server to validate against. In
 * live mode the actual server response is always the source of truth (see
 * `submitSaveVersion` below); this never runs then. */
function mockSaveVersionSubmit(payload: SaveVersionSubmitPayload): SaveVersionSubmitResponse {
  const comment = (payload.comment || "").trim();
  if (!comment) {
    return { ok: false, error: "Please enter a comment describing this version." };
  }
  const status = (payload.custom_status || "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "") || payload.status || "";
  const version = "v008";
  const suffix = status ? `_${status}` : "";
  return {
    ok: true,
    message: `Saved as robot_010_${version}${suffix}.c4d`,
    version,
    status,
    path: `/mock/robot_010/robot_010_${version}${suffix}.c4d`,
    warning: comment.toLowerCase().includes("final")
      ? "Tip: instead of writing 'final' in the comment, use the 'Final Delivery' status tag — it bakes the marker into the filename and the history log."
      : null,
  };
}

/** `POST /api/form/save_version/submit` — see web_ops.py `_op_form_save_version_submit`. */
export async function submitSaveVersion(payload: SaveVersionSubmitPayload): Promise<SaveVersionSubmitResponse> {
  if (isMock()) {
    return mockSaveVersionSubmit(payload);
  }
  return postForm<SaveVersionSubmitResponse>("/api/form/save_version/submit", payload);
}

/** `GET /api/form/notes/state` — see web_ops.py `_op_form_notes_state`. */
export async function fetchNotesState(): Promise<NotesStateResult> {
  if (isMock()) {
    return { kind: "ok", data: mockNotes as NotesState };
  }
  return fetchReport<NotesState>("/api/form/notes/state", {
    no_scene_path: "Save the scene to a folder first, then reopen Edit Notes.",
  });
}

/** `POST /api/form/notes/submit` — see web_ops.py `_op_form_notes_submit`. */
export async function submitNotes(payload: NotesSubmitPayload): Promise<NotesSubmitResponse> {
  if (isMock()) {
    return { ok: true };
  }
  return postForm<NotesSubmitResponse>("/api/form/notes/submit", payload);
}

/** `GET /api/form/settings/state` — see web_ops.py `_op_form_settings_state`.
 * Never returns an `{"error": "no_document"}` sentinel (settings are
 * machine/global, not scene-scoped) — an `"empty"` result here would be
 * unreachable, same reasoning as Doctor's report op. */
export async function fetchSettingsState(): Promise<SettingsStateResult> {
  if (isMock()) {
    return { kind: "ok", data: mockSettings as SettingsState };
  }
  const result = await fetchReport<SettingsState>("/api/form/settings/state", {});
  return result.kind === "empty" ? { kind: "error", message: result.reason } : result;
}

/** `POST /api/form/settings/submit` — see web_ops.py `_op_form_settings_submit`. */
export async function submitSettings(payload: SettingsSubmitPayload): Promise<SettingsSubmitResponse> {
  if (isMock()) {
    return { ok: true };
  }
  return postForm<SettingsSubmitResponse>("/api/form/settings/submit", payload);
}

// `?mock=1` gate state is stateful across fix_all/accept actions within one
// page session (unlike the other three forms' fire-and-forget mocks) so the
// mock flow can actually demonstrate "fixed checks disappear from the list"
// end to end for screenshots/dev — reset on page reload.
let mockGateState: GateState | null = null;

function getMockGateState(): GateState {
  if (!mockGateState) {
    mockGateState = JSON.parse(JSON.stringify(mockGate)) as GateState;
  }
  return mockGateState;
}

function mockGateSubmit(action: GateSubmitAction): GateSubmitResponse {
  const state = getMockGateState();

  if (action.action === "cancel") {
    return { ok: true, proceed: false, state };
  }

  if (action.action === "proceed") {
    const proceed = !state.checks.some((c) => c.bucket === "blocking" || (c.bucket === "fixable" && c.blocks));
    return { ok: true, proceed, state };
  }

  if (action.action === "fix_all") {
    const fixed = state.checks.filter((c) => c.bucket === "fixable").map((c) => c.check_id);
    mockGateState = { ...state, checks: state.checks.filter((c) => c.bucket !== "fixable") };
    mockGateState.passed = !mockGateState.checks.some((c) => c.bucket === "blocking");
    return { ok: true, fixed, state: mockGateState };
  }

  // action.action === "accept"
  const author = action.author.trim();
  const reason = action.reason.trim();
  if (!author || !reason) {
    return { ok: false, error: "Author and reason are required to accept violations." };
  }
  if (action.ids.length === 0) {
    return { ok: false, error: "Select at least one check to accept." };
  }
  mockGateState = { ...state, checks: state.checks.filter((c) => !action.ids.includes(c.check_id)) };
  mockGateState.passed = !mockGateState.checks.some((c) => c.bucket === "blocking");
  return { ok: true, accepted: true, state: mockGateState };
}

/** `GET /api/form/gate/state` — see web_ops.py `_op_form_gate_state`. */
export async function fetchGateState(): Promise<GateStateResult> {
  if (isMock()) {
    return { kind: "ok", data: getMockGateState() };
  }
  return fetchReport<GateState>("/api/form/gate/state", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen the Quality Gate.",
  });
}

/** `POST /api/form/gate/submit` — see web_ops.py `_op_form_gate_submit`. */
export async function submitGate(action: GateSubmitAction): Promise<GateSubmitResponse> {
  if (isMock()) {
    return mockGateSubmit(action);
  }
  return postForm<GateSubmitResponse>("/api/form/gate/submit", action);
}

// ---------------------------------------------------------------------------
// Command palette (Phase 4 Task 4) — see web_ops.py `_op_palette_actions` /
// `_op_palette_run` and the `PALETTE_ACTIONS` registry in webbridge.py.
// ---------------------------------------------------------------------------

/** `GET /api/palette/actions` — never returns a `{"error": <code>}` empty
 * sentinel (the registry always has entries; per-action `enabled` carries
 * the "nothing to do right now" state instead), so an error dict here is
 * always an unexpected dispatch failure, same reasoning as Doctor/Settings.
 *
 * The op's real payload is `{"actions": [...]}` (see `_op_palette_actions`
 * in web_ops.py — it returns a dict, like every other op, NOT a bare
 * array), so `fetchReport` is typed against that wrapper shape and this
 * unwraps `.actions` for the page. A malformed/missing `actions` field
 * (should never happen from a well-formed server, but a live bug once
 * already proved "should never happen" isn't "never") degrades to an
 * ErrorState here rather than handing the page a non-array to `.filter()`
 * — see PalettePage.tsx's own `Array.isArray` guard for the second layer
 * of the same defense. */
export async function fetchPaletteActions(): Promise<PaletteActionsResult> {
  if (isMock()) {
    return { kind: "ok", data: mockPaletteActions as PaletteAction[] };
  }
  const result = await fetchReport<{ actions: PaletteAction[] }>("/api/palette/actions", {});
  if (result.kind === "empty") {
    return { kind: "error", message: result.reason };
  }
  if (result.kind === "error") {
    return result;
  }
  if (!Array.isArray(result.data.actions)) {
    return { kind: "error", message: "Server returned a malformed palette/actions payload." };
  }
  return { kind: "ok", data: result.data.actions };
}

/** Client-only mock for `palette/run` — used ONLY in `?mock=1` mode (see
 * `mockSaveVersionSubmit` above for the same reasoning). Mirrors the real
 * op's shape closely enough to exercise the confirm step and navigate
 * flow in a mock/screenshot session: a `requires_confirm` action without
 * `confirm: true` is rejected, a `navigate`-kind id echoes back its page
 * from `PALETTE_ACTIONS`' `kind`/`page` (hardcoded here since the mock
 * action list itself doesn't carry `kind`/`page`, only what the SPA reads),
 * everything else returns a canned toast message. */
const MOCK_NAVIGATE_PAGES: Record<string, string> = {
  save_version: "form/save_version",
  edit_notes: "form/notes",
  settings: "form/settings",
  gate_triage: "form/gate",
};

function mockPaletteRun(id: string, confirm?: boolean): PaletteRunResponse {
  const action = (mockPaletteActions as PaletteAction[]).find((a) => a.id === id);
  if (!action) {
    return { ok: false, error: `unknown palette action: ${id}` };
  }
  if (action.requires_confirm && !confirm) {
    return { ok: false, error: "confirm_required" };
  }
  const navigate = MOCK_NAVIGATE_PAGES[id];
  if (navigate) {
    return { ok: true, navigate };
  }
  if (id.startsWith("open_reports") || id === "open_hub") {
    return { ok: true, message: "Opened." };
  }
  if (id === "rescan_qc") {
    return { ok: true, message: "QC cache cleared" };
  }
  return { ok: true, message: `${action.label} — done` };
}

/** `POST /api/palette/run` — `{"id": <action id>}`, optionally
 * `{"confirm": true}` to pass a `requires_confirm` action's contract gate
 * (see `_op_palette_run`'s docstring for why this is a round trip instead
 * of a native modal). */
export async function runPaletteAction(id: string, confirm?: boolean): Promise<PaletteRunResponse> {
  if (isMock()) {
    return mockPaletteRun(id, confirm);
  }
  return postForm<PaletteRunResponse>("/api/palette/run", confirm ? { id, confirm: true } : { id });
}

// ---------------------------------------------------------------------------
// Asset Hub (Phase 5) — see plugin/sentinel/ui/hub_ops.py `HUB_OPS`, routed
// through the same `/api/<op>` dispatch as every op above. Pages are not
// wired to this module yet (that's a later Phase 5 task); these functions
// only need to compile and match the Python contract field-for-field.
// ---------------------------------------------------------------------------

/** `GET /api/hub/inventory` — see `_op_hub_inventory` in hub_ops.py. */
export async function fetchHubInventory(): Promise<HubInventoryResult> {
  if (isMock()) {
    return { kind: "ok", data: mockHubInventory as HubInventory };
  }
  return fetchReport<HubInventory>("/api/hub/inventory", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen the Asset Hub.",
  });
}

/** `GET /api/hub/state_stamp` — see `_op_hub_state_stamp` in hub_ops.py.
 * Collapses the `{stamp}` / `{error}` envelope to `string | null`: the SPA
 * only ever compares stamps to detect change, so "no document" and a
 * network failure are equally "nothing to compare". */
export async function fetchHubStateStamp(): Promise<string | null> {
  if (isMock()) {
    return "mock-stamp";
  }
  const result = await fetchReport<{ stamp: string }>("/api/hub/state_stamp", {});
  return result.kind === "ok" ? result.data.stamp : null;
}

/** `GET /api/hub/presets` — see `_op_hub_presets` in hub_ops.py. */
export async function fetchHubPresets(): Promise<HubPresetsResult> {
  if (isMock()) {
    return { kind: "ok", data: [] };
  }
  const result = await fetchReport<{ presets: HubPreset[] }>("/api/hub/presets", {});
  if (result.kind === "empty") {
    return { kind: "error", message: result.reason };
  }
  if (result.kind === "error") {
    return result;
  }
  return { kind: "ok", data: Array.isArray(result.data.presets) ? result.data.presets : [] };
}

/** `POST /api/hub/presets/save` — see `_op_hub_presets_save` in hub_ops.py. */
export async function saveHubPreset(find: string, replace: string): Promise<HubPresetsSaveResponse> {
  if (isMock()) {
    return { ok: true };
  }
  return postForm<HubPresetsSaveResponse>("/api/hub/presets/save", { find, replace });
}

/** `POST /api/hub/apply_repath` — see `_op_hub_apply_repath` in hub_ops.py. */
export async function postHubApply(changes: HubApplyChange[]): Promise<HubApplyResponse> {
  if (isMock()) {
    return { ok: true, applied: changes.length, errors: [], stamp: "mock-stamp" };
  }
  return postForm<HubApplyResponse>("/api/hub/apply_repath", { changes });
}

/** `POST /api/hub/select_owner` — see `_op_hub_select_owner` in hub_ops.py. */
export async function postHubSelectOwner(key: string): Promise<HubSelectOwnerResponse> {
  if (isMock()) {
    return { ok: true, stamp: "mock-stamp" };
  }
  return postForm<HubSelectOwnerResponse>("/api/hub/select_owner", { key });
}

/** `POST /api/hub/pick_path` — see `_op_hub_pick_path` in hub_ops.py
 * (`directory` picks a folder instead of a file; `title` is the dialog
 * caption). */
export async function postHubPickPath(directory: boolean, title?: string): Promise<HubPickPathResponse> {
  if (isMock()) {
    return { ok: false, error: "cancelled" };
  }
  return postForm<HubPickPathResponse>("/api/hub/pick_path", { directory, title });
}

/** `POST /api/hub/collect_start` — see `_op_hub_collect_start` in
 * hub_ops.py. `gateAck` must be exactly `true` to proceed past a blocking
 * FAIL-severity gate (mirrors the fase-4 `form/gate` `confirm_required`
 * contract — see that op's docstring). */
export async function startHubCollect(
  targetDir: string,
  zip: boolean,
  gateAck: boolean,
): Promise<HubCollectStartResponse> {
  if (isMock()) {
    return { ok: true, job_id: "mock-job-1" };
  }
  return postForm<HubCollectStartResponse>("/api/hub/collect_start", {
    target_dir: targetDir,
    zip,
    gate_ack: gateAck,
  });
}

/** `GET /api/hub/job_status?job_id=<id>` — see `webbridge.JobRegistry.status`
 * and the `hub/job_status` special-case in `reports_dialog.py` (answered
 * directly on the HTTP server thread, so it is NOT routed through
 * `fetchReport`'s `MainThreadQueue`-backed error envelope — the raw shape
 * already carries `error` for an unknown/expired job_id). */
export async function fetchHubJobStatus(jobId: string): Promise<HubJobStatus> {
  if (isMock()) {
    return { job_id: jobId, state: "done", phase: "run", detail: "", pct: 100, result: null };
  }
  try {
    const response = await fetch("/api/hub/job_status?job_id=" + encodeURIComponent(jobId));
    return (await response.json()) as HubJobStatus;
  } catch {
    return { error: "Could not reach the Sentinel server. Is the Asset Hub still open in Cinema 4D?" };
  }
}

/** `POST /api/hub/match_folder` — see `_op_hub_match_folder` in hub_ops.py
 * (Search Folder for Missing). */
export async function postHubMatchFolder(root: string): Promise<HubMatchFolderResponse> {
  if (isMock()) {
    return { ok: true, matches: [], ambiguous: 0, truncated: false };
  }
  return postForm<HubMatchFolderResponse>("/api/hub/match_folder", { root });
}

/** `POST /api/hub/make_relative` — see `_op_hub_make_relative` in
 * hub_ops.py (Make All Relative). Server-side because the rule
 * (`compute_relative_texture_path`'s `os.path.relpath` + cross-drive/climb
 * depth rejection) is not trivially reproducible in the browser. */
export async function postHubMakeRelative(): Promise<HubMakeRelativeResponse> {
  if (isMock()) {
    return { ok: true, changes: [], skipped_cross_drive: 0 };
  }
  return postForm<HubMakeRelativeResponse>("/api/hub/make_relative", {});
}

/** `GET /api/hub/preflight` — see `_op_hub_preflight` in hub_ops.py. Same
 * `qc_report_payload` shape as `GET /api/report/qc`, so this reuses
 * `QcReport`/`QcReportResult` rather than a duplicate Hub-specific type. */
export async function fetchHubPreflight(): Promise<QcReportResult> {
  if (isMock()) {
    return { kind: "ok", data: mockQcReport as QcReport };
  }
  return fetchReport<QcReport>("/api/hub/preflight", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen the Asset Hub.",
  });
}

/** `POST /api/hub/meta` — see `_op_hub_meta` in hub_ops.py.
 * Caps each request at 64 keys — the caller (HubPage's meta sweep) chunks
 * the full asset key set into sequential 64-key calls rather than sending
 * one giant request.
 * Returns only the metas that were found; missing keys are absent.
 * Returns `{}` on any error (never throws). Mock branch filters
 * `hub-meta.json` by the requested keys. */
export async function fetchHubMeta(keys: string[]): Promise<Record<string, HubMeta>> {
  if (isMock()) {
    const mockData = mockHubMeta as Record<string, HubMeta>;
    const result: Record<string, HubMeta> = {};
    for (const key of keys) {
      if (key in mockData) {
        result[key] = mockData[key];
      }
    }
    return result;
  }

  try {
    const response = await fetch("/api/hub/meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    });
    const payload = await response.json();
    if (response.ok && payload && typeof payload === "object" && "metas" in payload) {
      return (payload as { metas: Record<string, HubMeta> }).metas;
    }
  } catch {
    // Silently fall through to empty return
  }
  return {};
}

/** `GET /api/hub/meta_totals` — see `_op_hub_meta_totals` in hub_ops.py.
 * Aggregated metrics over all assets that have cached metadata.
 * Returns a default totals object on any error (never throws). */
export async function fetchHubMetaTotals(): Promise<HubMetaTotals> {
  const defaultTotals: HubMetaTotals = {
    vram_bytes: 0,
    vram_label: "—",
    disk_bytes: 0,
    disk_label: "—",
    covered: 0,
    total: 0,
  };

  if (isMock()) {
    // Fixture totals (sum of all 10 hub-meta.json vram_bytes):
    // tex_body_diffuse(67MB) + tex_body_normal(67MB) + tex_shared_noise(256MB)
    // + tex_glass_normal(16MB) + hdri_dome_studio(32MB) + tex_label_diffuse(4MB)
    // + tex_props_ao(5.3MB) + abc_hero_anim(45MB) + hdri_dome_backup(64MB)
    // + abc_crowd_sim(5.3MB) = 582,658,730 bytes = 556 MB
    return {
      vram_bytes: 582658730,
      vram_label: "556 MB",
      disk_bytes: 536870912,
      disk_label: "512 MB",
      covered: 10,
      total: 10,
    };
  }

  try {
    const response = await fetch("/api/hub/meta_totals");
    if (!response.ok) return defaultTotals;
    return (await response.json()) as HubMetaTotals;
  } catch {
    return defaultTotals;
  }
}

/** `POST /api/hub/shrink_start` — see `_op_hub_shrink_start` in hub_ops.py.
 * Queues a background job; poll its progress with the existing
 * `fetchHubJobStatus`/`HubJobStatus` (the `result` field resolves to
 * `HubShrinkResult` for this job kind). `?mock=1` has no stateful job
 * registry to back a fake job (same policy as `startHubCollect`'s sibling
 * ops), so it returns an informative failure instead of a fake job_id. */
export async function startHubShrink(keys: string[], targetPx: number): Promise<HubShrinkStartResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<HubShrinkStartResponse>("/api/hub/shrink_start", { keys, target_px: targetPx });
}

/** `POST /api/hub/copy_into_project` — see `_op_hub_copy_into_project` in
 * hub_ops.py. Synchronous mutation, no job. Same `?mock=1` policy as
 * `startHubShrink` above — no stateful mock, an informative failure. */
export async function postHubCopyIntoProject(keys: string[]): Promise<HubCopyResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<HubCopyResponse>("/api/hub/copy_into_project", { keys });
}

/** `POST /api/hub/variants` — see `_op_hub_variants` in hub_ops.py
 * (Fase 5.3). Same batched-read-only shape/cap/mock convention as
 * `fetchHubMeta`: the caller (HubPage's variants sweep, chained after the
 * meta sweep) chunks the full key set into sequential 64-key calls. Returns
 * only the keys with a detected sibling group (>=2 on-disk variants); a key
 * absent from the result has none. Returns `{}` on any error (never
 * throws). Mock branch filters `hub-variants.json` by the requested keys. */
export async function fetchHubVariants(keys: string[]): Promise<Record<string, HubVariant[]>> {
  if (isMock()) {
    const mockData = mockHubVariants as Record<string, HubVariant[]>;
    const result: Record<string, HubVariant[]> = {};
    for (const key of keys) {
      if (key in mockData) {
        result[key] = mockData[key];
      }
    }
    return result;
  }

  try {
    const response = await fetch("/api/hub/variants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys }),
    });
    const payload = await response.json();
    if (response.ok && payload && typeof payload === "object" && "variants" in payload) {
      return (payload as { variants: Record<string, HubVariant[]> }).variants;
    }
  } catch {
    // Silently fall through to empty return
  }
  return {};
}

/** `POST /api/hub/switch_res` — see `_op_hub_switch_res` in hub_ops.py
 * (Fase 5.3). Synchronous relink-only mutation (no job), same `?mock=1`
 * policy as `startHubShrink`/`postHubCopyIntoProject` above — no stateful
 * mock to relink against, so this returns an informative failure instead of
 * fabricating a result. `target` is either an exact px or the literal
 * `"highest"` (picks each key's own top variant). */
export async function postHubSwitchRes(keys: string[], target: number | "highest"): Promise<HubSwitchResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<HubSwitchResponse>("/api/hub/switch_res", { keys, target });
}

/** `GET /api/hub/ui_state` — see `_op_hub_ui_state` in hub_ops.py.
 * Retrieves persisted column widths and sort spec from `sentinel_settings.json`.
 * Returns an empty state on any error (never throws). */
export async function fetchHubUiState(): Promise<HubUiState> {
  if (isMock()) {
    return { col_widths: {}, sort: undefined };
  }

  try {
    const response = await fetch("/api/hub/ui_state");
    if (!response.ok) return {};
    const payload = await response.json();
    if (payload && typeof payload === "object" && "state" in payload) {
      return (payload as { state: HubUiState }).state;
    }
  } catch {
    // Silently fall through to empty return
  }
  return {};
}

/** `POST /api/hub/ui_state/save` — see `_op_hub_ui_state_save` in hub_ops.py.
 * Fire-and-forget mutation: persists column widths and sort spec.
 * Never throws; silently fails on network error. */
export async function saveHubUiState(state: HubUiState): Promise<void> {
  if (isMock()) {
    return;
  }

  try {
    await fetch("/api/hub/ui_state/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    });
  } catch {
    // Fire-and-forget; silently ignore errors
  }
}

// ---------------------------------------------------------------------------
// Panel SPA (Fase 6.0) — see plugin/sentinel/ui/panel_ops.py (PANEL_OPS),
// routed through the same `/api/<op>` dispatch as every other op above.
// ---------------------------------------------------------------------------

/** `GET /api/panel/state_stamp` — see `_op_panel_state_stamp` in
 * panel_ops.py, reusing hub's `_stamp_for` unmodified. Same collapse to
 * `string | null` as `fetchHubStateStamp`: the panel only ever compares
 * stamps to detect change, so "no document" and a network failure are
 * equally "nothing to compare". */
export async function fetchPanelStamp(): Promise<string | null> {
  if (isMock()) {
    return "mock-stamp";
  }
  const result = await fetchReport<{ stamp: string }>("/api/panel/state_stamp", {});
  return result.kind === "ok" ? result.data.stamp : null;
}

/** `GET /api/panel/overview` — see `_op_panel_overview`/`build_panel_overview`
 * in panel_ops.py. Each of the 5 blocks may independently be `null` (a
 * failure isolated to one subsystem) — the page must render those cards as
 * unavailable, never crash. */
export async function fetchPanelOverview(): Promise<PanelOverviewResult> {
  if (isMock()) {
    return { kind: "ok", data: mockPanelOverview as PanelOverview };
  }
  return fetchReport<PanelOverview>("/api/panel/overview", {
    no_document: "No active Cinema 4D document. Open a scene to see its shot health.",
  });
}

/** `POST /api/panel/open_form` — see `_op_panel_open_form` in panel_ops.py.
 * Opens one of the three absorbed-later native windows (Save Version /
 * Notes / Settings) from a dashboard card button. `?mock=1` has no native
 * window to open, so it resolves `{ok: true}` without side effects, same
 * fire-and-forget-in-mock convention as `saveHubUiState`. */
export async function postPanelOpenForm(page: string): Promise<PanelOpenFormResponse> {
  if (isMock()) {
    return { ok: true };
  }
  return postForm<PanelOpenFormResponse>("/api/panel/open_form", { page });
}

/** `GET /api/panel/qc` — see `_op_panel_qc` in panel_ops.py (Fase 6.1 Task
 * 1). Full per-check FAIL/WARN/OK/disabled breakdown for the panel's QC
 * section; same doc-guard/`{"error": "no_document"}` shape as
 * `fetchPanelOverview`, hence the same `fetchReport` handling. */
export async function fetchPanelQc(): Promise<PanelQcResult> {
  if (isMock()) {
    return { kind: "ok", data: mockPanelQc as PanelQcSection };
  }
  return fetchReport<PanelQcSection>("/api/panel/qc", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen the panel.",
  });
}

/** `POST /api/panel/qc/select` — see `_op_panel_qc_select` in panel_ops.py.
 * No stateful mock scene to select against, so `?mock=1` resolves an
 * informative failure — same convention as `postHubCopyIntoProject`/
 * `postHubSwitchRes` above. */
export async function postPanelQcSelect(checkId: string): Promise<PanelQcSelectResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<PanelQcSelectResponse>("/api/panel/qc/select", { check_id: checkId });
}

/** `POST /api/panel/qc/accept` — see `_op_panel_qc_accept` in panel_ops.py.
 * Author/reason validation happens server-side (`_validate_accept_payload`);
 * this call always forwards whatever the inline form collected. Same
 * no-stateful-mock convention as `postPanelQcSelect`. */
export async function postPanelQcAccept(
  checkId: string,
  author: string,
  reason: string,
): Promise<PanelQcAcceptResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<PanelQcAcceptResponse>("/api/panel/qc/accept", {
    check_id: checkId,
    author,
    reason,
  });
}

/** `POST /api/panel/qc/fix_all` — see `_op_panel_qc_fix_all` in panel_ops.py.
 * Same no-stateful-mock convention as `postPanelQcSelect`/`postPanelQcAccept`. */
export async function postPanelQcFixAll(): Promise<PanelQcFixAllResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<PanelQcFixAllResponse>("/api/panel/qc/fix_all", {});
}

// ---------------------------------------------------------------------------
// Panel Render section (Fase 6.2 Task 3, AOVs block reorganized in a later
// pass) — see `PANEL_RENDER_OPS` in plugin/sentinel/ui/panel_render_ops.py.
// Each of the 5 blocks may independently be `null` (`_guarded_block`
// isolation, same convention as `fetchPanelOverview`/`fetchPanelQc`).
// Mutation posters follow the shared `{ok, error?, stamp?, render?,
// confirm_label?}` contract; only `reset_all`/`force_vertical` stay
// destructive and take an optional `confirm` flag mirroring
// `runPaletteAction`'s own confirm param — `aov_tier` (Essentials/
// Production) is additive/Cmd+Z-able and never confirm-gates, and Light
// Groups is an independent toggle (`set_light_groups`), not a tier.
// ---------------------------------------------------------------------------

/** `GET /api/panel/render` — see `_op_panel_render`/`build_panel_render` in
 * panel_render_ops.py. */
export async function fetchPanelRender(): Promise<PanelRenderResult> {
  if (isMock()) {
    return { kind: "ok", data: mockPanelRender as PanelRenderSection };
  }
  return fetchReport<PanelRenderSection>("/api/panel/render", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen the panel.",
  });
}

/** Client-only mock for the render-section mutations — used ONLY in
 * `?mock=1` mode. Mirrors the confirm-gate contract for the three
 * destructive ops (same reasoning as `mockPaletteRun`) so a mock/screenshot
 * session can exercise the inline confirm step; every other op echoes the
 * bundled fixture back as `render` (no stateful scene to actually mutate,
 * same no-stateful convention as `postPanelQcSelect`). */
const MOCK_RENDER_CONFIRM_LABELS: Record<string, string> = {
  reset_all: "Reset ALL render presets from template? This replaces existing presets with standard settings.",
  force_vertical: "Force the active render preset's aspect ratio (9:16 / 16:9)?",
};

function mockPanelRenderMutation(op: string, confirm?: boolean): PanelRenderMutationResponse {
  const label = MOCK_RENDER_CONFIRM_LABELS[op];
  if (label && !confirm) {
    return { ok: false, error: "confirm_required", confirm_label: label };
  }
  return { ok: true, stamp: "mock-stamp", render: mockPanelRender as PanelRenderSection };
}

/** `POST /api/panel/render/set_preset` — see `_op_panel_render_set_preset`. */
export async function postPanelRenderSetPreset(preset: string): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("set_preset");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/set_preset", { preset });
}

/** `POST /api/panel/render/reset_all` — destructive, confirm-gated (see
 * `_op_panel_render_reset_all`). */
export async function postPanelRenderResetAll(confirm?: boolean): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("reset_all", confirm);
  }
  return postForm<PanelRenderMutationResponse>(
    "/api/panel/render/reset_all",
    confirm ? { confirm: true } : {},
  );
}

/** `POST /api/panel/render/force_vertical` — destructive, confirm-gated
 * (see `_op_panel_render_force_vertical`). */
export async function postPanelRenderForceVertical(confirm?: boolean): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("force_vertical", confirm);
  }
  return postForm<PanelRenderMutationResponse>(
    "/api/panel/render/force_vertical",
    confirm ? { confirm: true } : {},
  );
}

/** `POST /api/panel/render/add_frame_tag` — see
 * `_op_panel_render_add_frame_tag`. Additive/idempotent, no confirm gate. */
export async function postPanelRenderAddFrameTag(): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("add_frame_tag");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/add_frame_tag", {});
}

/** `POST /api/panel/render/select_frame_tag` — see
 * `_op_panel_render_select_frame_tag`. `{ok: false, error: "no_tag"}` when
 * the scene has no Sentinel Frame tag. */
export async function postPanelRenderSelectFrameTag(): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("select_frame_tag");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/select_frame_tag", {});
}

/** `POST /api/panel/render/aov_tier` — additive coverage-level action (see
 * `_op_panel_render_aov_tier`), NOT confirm-gated: Essentials/Production add
 * the AOVs missing up to that tier and are fully Cmd+Z-able. `tier` must be
 * one of `"essentials"`/`"production"` — `"light_groups"` was never a tier,
 * see `postPanelRenderSetLightGroups`. */
export async function postPanelRenderAovTier(
  tier: "essentials" | "production",
): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("aov_tier");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/aov_tier", { tier });
}

/** `POST /api/panel/render/set_light_groups` — see
 * `_op_panel_render_set_light_groups`. Light Groups on Beauty is an
 * independent on/off TOGGLE (state), not an AOV tier — sends the EXPLICIT
 * value of the option clicked (never a flip of the current state), same
 * convention as `postPanelRenderSetMultipart`. `{ok: false, error:
 * "no_groups_assigned"}` means there are lights but none carry a
 * light-group assignment — the SPA should toast that, not flip the UI. */
export async function postPanelRenderSetLightGroups(enabled: boolean): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/set_light_groups", { enabled });
}

/** `POST /api/panel/render/set_multipart` — see
 * `_op_panel_render_set_multipart`. Sets the Multi-Part EXR / Direct output
 * mode to an EXPLICIT value (the segmented switch always sends the option
 * clicked, never a flip of the current state). Reversible, no confirm
 * gate. `?mock=1` has no stateful scene to actually flip the mode on, so it
 * returns an informative failure like the other stateless mutations
 * (`startHubShrink`/`postHubCopyIntoProject`) rather than faking success. */
export async function postPanelRenderSetMultipart(enabled: boolean): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return { ok: false, error: "mock" };
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/set_multipart", { enabled });
}

/** `GET /api/panel/render/aov_list` — see `_op_panel_render_aov_list`.
 * Read-only, for the inline "Show AOVs" expand. `{error:
 * "redshift_unavailable"}` degrades to the `"empty"` kind, same convention
 * as every other `fetchReport`-backed report op. */
export async function fetchPanelRenderAovList(): Promise<PanelRenderAovListResult> {
  if (isMock()) {
    return { kind: "ok", data: mockPanelRenderAovList as PanelRenderAovListOk };
  }
  return fetchReport<PanelRenderAovListOk>("/api/panel/render/aov_list", {
    no_document: "No active Cinema 4D document. Open a scene, then reopen the panel.",
    redshift_unavailable: "Redshift is not available in this Cinema 4D session.",
  });
}

/** `POST /api/panel/render/toggle_watchfolder` — see
 * `_op_panel_render_toggle_watchfolder`. Reversible, no confirm gate. */
export async function postPanelRenderToggleWatchfolder(): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("toggle_watchfolder");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/toggle_watchfolder", {});
}

/** `POST /api/panel/render/save_still` — see `_op_panel_render_save_still`. */
export async function postPanelRenderSaveStill(): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("save_still");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/save_still", {});
}

/** `POST /api/panel/render/open_folder` — see `_op_panel_render_open_folder`. */
export async function postPanelRenderOpenFolder(): Promise<PanelRenderMutationResponse> {
  if (isMock()) {
    return mockPanelRenderMutation("open_folder");
  }
  return postForm<PanelRenderMutationResponse>("/api/panel/render/open_folder", {});
}

// ---------------------------------------------------------------------------
// Panel Deliver section (Fase 6.3 Task 3) — see `PANEL_DELIVER_OPS` in
// plugin/sentinel/ui/panel_deliver_ops.py. `panel/deliver` itself never
// returns an `{error}` envelope (a missing document degrades every block to
// `null` instead), so it does not go through `fetchReport`'s Result wrapper
// or `postForm`'s `{ok, error?}` bound — it's a plain typed fetch that
// degrades to the same all-null shape on a network/JSON failure.
// ---------------------------------------------------------------------------

/** Client-only mock for `panel/deliver` (only in `?mock=1`). Shape MUST
 * match the real payload (nested blocks) — a flat mock would pass tests
 * and crash on real data (the React #31 lesson). */
function mockPanelDeliver(): PanelDeliverState {
  return {
    version: {
      last: { version: 7, status: "TR", age: "2h ago", qc_label: "9/12" },
      unsaved: false,
      recent: [
        {
          version: 7, status: "TR", age: "2h ago", qc_label: "9/12",
          path: "/mock/shot_v007_TR.c4d", filename: "shot_v007_TR.c4d",
        },
        {
          version: 6, status: "", age: "5h ago", qc_label: "8/12",
          path: "/mock/shot_v006.c4d", filename: "shot_v006.c4d",
        },
      ],
    },
    notes: {
      summary: "Notes: review lighting + 3 TODOs (2 pending)",
      todos_pending: 2, notes_present: true, unsaved: false,
    },
    deliver: { has_manifest: true },
    stamp: "mock-stamp",
  };
}

const EMPTY_PANEL_DELIVER: PanelDeliverState = {
  version: null, notes: null, deliver: null, stamp: null,
};

/** `POST /api/panel/deliver` — see `_op_panel_deliver` in
 * panel_deliver_ops.py. */
export async function fetchPanelDeliver(): Promise<PanelDeliverState> {
  if (isMock()) return mockPanelDeliver();
  let response: Response;
  try {
    response = await fetch("/api/panel/deliver", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  } catch {
    return EMPTY_PANEL_DELIVER;
  }
  try {
    return (await response.json()) as PanelDeliverState;
  } catch {
    return EMPTY_PANEL_DELIVER;
  }
}

/** `POST /api/panel/deliver/open_version` — open a version .c4d via the
 * dialog-free core (`flows.open_version_core`). A first call without
 * `force` can surface `error: "unsaved_changes"` for the SPA to confirm
 * inline before re-posting with `force: true`. */
export async function postPanelOpenVersion(
  path: string,
  force?: boolean,
): Promise<PanelOpenVersionResponse> {
  if (isMock()) {
    return { ok: true, opened: true, stamp: "mock-stamp" };
  }
  return postForm<PanelOpenVersionResponse>(
    "/api/panel/deliver/open_version",
    force ? { path, force: true } : { path },
  );
}

/** `POST /api/panel/deliver/open_collect` — open the Asset Hub focused on
 * delivery (mirrors the native Collect button). */
export async function postPanelOpenCollect(): Promise<PaletteRunResponse> {
  if (isMock()) {
    return { ok: true, message: "Asset Hub opened" };
  }
  return postForm<PaletteRunResponse>("/api/panel/deliver/open_collect", {});
}
