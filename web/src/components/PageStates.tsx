import { AlertTriangle, FolderOpen, Loader2, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

/** Full-bleed centered card, shared by the error/empty states below. */
function StateCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div
        className="max-w-md rounded-lg border p-6 text-center"
        style={{ backgroundColor: "var(--color-surface-1)", borderColor: "var(--color-hairline)" }}
      >
        {children}
      </div>
    </div>
  );
}

export function LoadingState() {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <Loader2
        className="animate-spin"
        size={28}
        strokeWidth={2}
        style={{ color: "var(--color-ink-secondary)" }}
        aria-label="Loading"
      />
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <StateCard>
      <AlertTriangle size={28} style={{ color: "var(--color-status-fail)" }} className="mx-auto" />
      <p className="text-body-lg mt-3" style={{ color: "var(--color-ink)" }}>
        Couldn't load the Delivery Summary
      </p>
      <p className="text-body mt-2" style={{ color: "var(--color-ink-secondary)" }}>
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="text-label mt-4 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors duration-100 ease-out"
        style={{ backgroundColor: "var(--color-primary)", color: "var(--color-on-primary)" }}
        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--color-primary-hover)")}
        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "var(--color-primary)")}
      >
        <RefreshCw size={14} strokeWidth={2.25} aria-hidden="true" />
        Retry
      </button>
    </StateCard>
  );
}

export function EmptyState({ reason }: { reason: string }) {
  return (
    <StateCard>
      <FolderOpen size={28} style={{ color: "var(--color-status-neutral)" }} className="mx-auto" />
      <p className="text-body-lg mt-3" style={{ color: "var(--color-ink)" }}>
        No delivery package open
      </p>
      <p className="text-body mt-2" style={{ color: "var(--color-ink-secondary)" }}>
        {reason}
      </p>
    </StateCard>
  );
}
