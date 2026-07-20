import mockDeliveryReport from "../mock/delivery-summary.json";
import mockDoctorReport from "../mock/doctor-report.json";
import mockGate from "../mock/form-gate.json";
import mockNotes from "../mock/form-notes.json";
import mockSaveVersion from "../mock/form-save-version.json";
import mockSettings from "../mock/form-settings.json";
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
  NotesState,
  NotesStateResult,
  NotesSubmitPayload,
  NotesSubmitResponse,
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

function isMock(): boolean {
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
