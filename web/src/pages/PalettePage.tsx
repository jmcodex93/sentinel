import { Search } from "lucide-react";
import type { KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Page } from "../App";
import { Button } from "../components/form/Button";
import { ErrorState, LoadingState } from "../components/PageStates";
import { fetchPaletteActions, runPaletteAction } from "../lib/api";
import { useToast } from "../lib/toast";
import type { PaletteAction, PaletteActionsResult } from "../types";

type PageState = { kind: "loading" } | PaletteActionsResult;

// Registry order the panel's Help menu / gate wiring introduced the groups
// in (see `PALETTE_ACTIONS` in webbridge.py) — an unrecognized future group
// sorts after these three rather than disappearing.
const GROUP_ORDER = ["Navigate", "Scene", "Quick Fix"];

function groupRank(group: string): number {
  const index = GROUP_ORDER.indexOf(group);
  return index === -1 ? GROUP_ORDER.length : index;
}

/** Command Palette — ⌘K-style search over every registered Sentinel action
 * (`PALETTE_ACTIONS` in webbridge.py). Opened one-per-window by the native
 * `FormDialog` host (Phase 4 Task 4), either from the panel's Help menu or
 * the standalone "Sentinel: Command Palette" CommandData the artist can
 * bind a shortcut to. v1 filter is a plain case-insensitive substring match
 * (YAGNI — no fuzzy scoring yet); arrows move the highlight, Enter runs the
 * highlighted action. A `requires_confirm` action (the two DECISIÓN
 * destructive Quick Fixes) shows an inline confirm step instead of running
 * immediately — see `runPaletteAction`'s docstring for why this can't be a
 * native modal. A `kind: "navigate"` result switches this SAME window to
 * the target form page client-side (`onNavigate`, from App.tsx's `page`
 * state) rather than opening a second native dialog. */
export function PalettePage({ onNavigate }: { onNavigate: (page: Page) => void }) {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [confirmAction, setConfirmAction] = useState<PaletteAction | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchPaletteActions().then(setState);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Defense in depth against a shape-drift bug (a live one already shipped
  // once: the API layer briefly handed this page the raw `{actions:[...]}`
  // wrapper object instead of the unwrapped array — `.filter()` on an
  // object threw, React unmounted, the window went blank with zero visible
  // error). `fetchPaletteActions` is the primary fix; this guard is the
  // second layer so a future contract drift degrades to a message instead
  // of a silent blank window. Kept as a plain boolean here (not an early
  // return) — every hook below must still run unconditionally on every
  // render; the actual bail-out JSX lives with the other kind-based
  // returns further down, after all hooks have been called.
  const malformed = state.kind === "ok" && !Array.isArray(state.data);
  const actions = useMemo(
    () => (state.kind === "ok" && Array.isArray(state.data) ? state.data : []),
    [state],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pool = q
      ? actions.filter((a) => a.label.toLowerCase().includes(q) || a.group.toLowerCase().includes(q))
      : actions;
    // Stable sort by group rank only — keeps each group's own registry
    // order intact (Array.prototype.sort is stable per spec since ES2019).
    return [...pool].sort((a, b) => groupRank(a.group) - groupRank(b.group));
  }, [actions, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (activeIndex >= filtered.length) {
      setActiveIndex(Math.max(0, filtered.length - 1));
    }
  }, [filtered.length, activeIndex]);

  useEffect(() => {
    rowRefs.current.get(activeIndex)?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  async function runAction(action: PaletteAction, confirm?: boolean) {
    if (!action.enabled) {
      if (action.reason) toast({ message: action.reason, variant: "warn" });
      return;
    }
    if (action.requires_confirm && !confirm) {
      setConfirmAction(action);
      return;
    }
    setBusy(true);
    const response = await runPaletteAction(action.id, confirm);
    setBusy(false);
    setConfirmAction(null);

    if (!response.ok) {
      toast({ message: response.error || "Action failed.", variant: "warn" });
      return;
    }
    if (response.navigate) {
      onNavigate(response.navigate as Page);
      return;
    }
    toast({ message: response.message || "Done.", variant: "success" });
    // Refresh so enabled/reason/confirm_label reflect whatever just
    // changed (a Quick Fix that just ran should immediately read
    // "Nothing to fix" if the palette stays open).
    load();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (confirmAction) return; // the confirm card owns Enter while it's open
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const action = filtered[activeIndex];
      if (action) runAction(action);
    }
  }

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") {
    return <ErrorState title="Couldn't load the Command Palette" message={state.message} onRetry={load} />;
  }
  if (malformed) {
    return (
      <ErrorState
        title="Couldn't load the Command Palette"
        message="Server returned a malformed palette/actions payload."
        onRetry={load}
      />
    );
  }

  if (confirmAction) {
    return (
      <div className="flex h-screen flex-col" style={{ backgroundColor: "var(--color-canvas)" }}>
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
          <p className="text-body-lg" style={{ color: "var(--color-ink)" }}>
            {confirmAction.confirm_label}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => setConfirmAction(null)}
              autoFocus
            >
              Cancel
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => runAction(confirmAction, true)}>
              Confirm
            </Button>
          </div>
        </div>
      </div>
    );
  }

  let rowIndex = -1;
  const groups: [string, PaletteAction[]][] = [];
  for (const action of filtered) {
    const last = groups[groups.length - 1];
    if (last && last[0] === action.group) {
      last[1].push(action);
    } else {
      groups.push([action.group, [action]]);
    }
  }

  return (
    <div className="flex h-screen flex-col" style={{ backgroundColor: "var(--color-canvas)" }}>
      <div
        className="flex shrink-0 items-center gap-2 px-3 py-2.5"
        style={{ borderBottom: "1px solid var(--color-hairline-strong)" }}
      >
        <Search size={16} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search Sentinel actions…"
          aria-label="Search Sentinel actions"
          className="text-body-lg w-full bg-transparent outline-none"
          style={{ color: "var(--color-ink)" }}
        />
      </div>

      <div className="flex-1 overflow-auto p-2">
        {filtered.length === 0 && (
          <p className="text-body p-4 text-center" style={{ color: "var(--color-ink-secondary)" }}>
            No matching actions.
          </p>
        )}
        {groups.map(([group, groupActions]) => (
          <div key={group} className="mb-2">
            <p
              className="text-caption px-2 py-1"
              style={{ color: "var(--color-ink-secondary)" }}
            >
              {group}
            </p>
            {groupActions.map((action) => {
              rowIndex += 1;
              const isActive = rowIndex === activeIndex;
              return (
                <button
                  key={action.id}
                  ref={(el) => {
                    if (el) rowRefs.current.set(rowIndex, el);
                    else rowRefs.current.delete(rowIndex);
                  }}
                  type="button"
                  disabled={busy}
                  onMouseEnter={() => setActiveIndex(rowIndex)}
                  onClick={() => runAction(action)}
                  className="text-body flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left transition-colors duration-100 ease-out disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: isActive ? "var(--color-surface-2)" : "transparent",
                    color: action.enabled ? "var(--color-ink)" : "var(--color-ink-secondary)",
                    opacity: action.enabled ? 1 : 0.6,
                  }}
                >
                  <span className="truncate">{action.label}</span>
                  {!action.enabled && action.reason && (
                    <span className="text-caption shrink-0" style={{ color: "var(--color-ink-secondary)" }}>
                      {action.reason}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
