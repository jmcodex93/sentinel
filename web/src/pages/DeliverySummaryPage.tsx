import { useCallback, useEffect, useState } from "react";
import { DeliverySummaryView } from "../components/DeliverySummaryView";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { fetchDeliveryReport } from "../lib/api";
import type { DeliveryReportResult } from "../types";

type PageState = { kind: "loading" } | DeliveryReportResult;

export function DeliverySummaryPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchDeliveryReport().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") return <ErrorState message={state.message} onRetry={load} />;
  if (state.kind === "empty") return <EmptyState reason={state.reason} />;

  return <DeliverySummaryView data={state.data} />;
}
