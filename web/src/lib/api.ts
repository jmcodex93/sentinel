import mockDeliveryReport from "../mock/delivery-summary.json";
import mockDoctorReport from "../mock/doctor-report.json";
import mockQcReport from "../mock/qc-report.json";
import mockRenderValidationReport from "../mock/render-validation.json";
import mockSupervisorReport from "../mock/supervisor-report.json";
import type {
  DeliveryReport,
  DeliveryReportResult,
  DoctorReport,
  DoctorReportResult,
  QcReport,
  QcReportResult,
  RenderValidationReport,
  RenderValidationReportResult,
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
