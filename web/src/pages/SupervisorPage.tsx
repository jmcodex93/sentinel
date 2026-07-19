import { AlertTriangle, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Section } from "../components/Section";
import { SupervisorShotsTable } from "../components/SupervisorShotsTable";
import { fetchSupervisorReport } from "../lib/api";
import type { SupervisorReportResult } from "../types";

type PageState = { kind: "loading" } | SupervisorReportResult;

const EMPTY_REASON =
  "Enter a project folder above and click Scan. Sentinel reads each shot's " +
  "*_history.json / *_notes.json sidecars next to its .c4d files — no scene " +
  "is ever opened.";

export function SupervisorPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [folderInput, setFolderInput] = useState("");

  const scan = useCallback((folder?: string) => {
    setState({ kind: "loading" });
    fetchSupervisorReport(folder).then((result) => {
      setState(result);
      if (result.kind === "ok") setFolderInput(result.data.folder);
    });
  }, []);

  useEffect(() => {
    scan();
  }, [scan]);

  const handleScan = () => {
    const folder = folderInput.trim();
    if (folder) scan(folder);
  };

  const header = (
    <header
      className="px-[18px] py-[18px]"
      style={{ backgroundColor: "var(--color-surface-1)", borderBottom: "1px solid var(--color-hairline-strong)" }}
    >
      <h1 className="text-title" style={{ color: "var(--color-ink)" }}>
        Supervisor
      </h1>
      <div className="mt-3 flex gap-2">
        <input
          type="text"
          value={folderInput}
          onChange={(event) => setFolderInput(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && handleScan()}
          placeholder="/path/to/project"
          className="text-body flex-1 rounded-md px-3 py-1.5 outline-none"
          style={{
            backgroundColor: "var(--color-surface-2)",
            color: "var(--color-ink)",
            border: "1px solid var(--color-hairline)",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          }}
        />
        <button
          type="button"
          onClick={handleScan}
          disabled={!folderInput.trim()}
          className="text-label inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors duration-100 ease-out disabled:opacity-50"
          style={{ backgroundColor: "var(--color-primary)", color: "var(--color-on-primary)" }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-primary-hover)")}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "var(--color-primary)")}
        >
          <Search size={14} strokeWidth={2.25} aria-hidden="true" />
          Scan
        </button>
      </div>
    </header>
  );

  if (state.kind === "loading") {
    return (
      <div className="flex h-full flex-1 flex-col overflow-hidden">
        {header}
        <LoadingState />
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex h-full flex-1 flex-col overflow-hidden">
        {header}
        <ErrorState title="Couldn't scan the project folder" message={state.message} onRetry={() => scan(folderInput || undefined)} />
      </div>
    );
  }

  if (state.kind === "empty") {
    return (
      <div className="flex h-full flex-1 flex-col overflow-hidden">
        {header}
        <EmptyState title="No folder scanned yet" reason={EMPTY_REASON} />
      </div>
    );
  }

  const { data } = state;

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      {header}
      <div className="flex-1 overflow-auto p-4">
        {data.warnings.length > 0 && (
          <Section title="Warnings">
            <div
              className="rounded-lg border p-3"
              style={{
                backgroundColor: "var(--color-status-warn-tint-10)",
                borderColor: "var(--color-hairline)",
              }}
            >
              {data.warnings.map((warning, index) => (
                <p
                  key={index}
                  className="text-caption flex items-start gap-2 py-0.5"
                  style={{ color: "var(--color-status-warn)" }}
                >
                  <AlertTriangle size={12} strokeWidth={2.25} className="mt-0.5 shrink-0" aria-hidden="true" />
                  {warning}
                </p>
              ))}
            </div>
          </Section>
        )}

        <Section title={`Shots (${data.shot_count})`}>
          <SupervisorShotsTable shots={data.shots} />
        </Section>
      </div>
    </div>
  );
}
