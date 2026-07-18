import mockDeliveryReport from "../mock/delivery-summary.json";
import type { DeliveryReport, DeliveryReportResult } from "../types";

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

/** Fetches the Delivery Summary payload. `?mock=1` in the page URL serves
 * the bundled fixture instead — used for local dev (`npm run dev`) before
 * the C4D-hosted server exists, and for a screenshot-able build with no
 * live Cinema 4D behind it. */
export async function fetchDeliveryReport(): Promise<DeliveryReportResult> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mock") === "1") {
    return { kind: "ok", data: mockDeliveryReport as DeliveryReport };
  }

  let response: Response;
  try {
    response = await fetch("/api/report/delivery" + window.location.search);
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
    const message = isApiErrorPayload(payload)
      ? payload.error
      : `Server responded ${response.status}.`;
    return { kind: "error", message };
  }

  if (isApiErrorPayload(payload)) {
    if (payload.error === "no_manifest") {
      return {
        kind: "empty",
        reason:
          "No sentinel_manifest.json found next to the open scene. Open a collected package in Cinema 4D, or pass ?manifest=<path>.",
      };
    }
    return { kind: "error", message: payload.error };
  }

  return { kind: "ok", data: payload as DeliveryReport };
}
