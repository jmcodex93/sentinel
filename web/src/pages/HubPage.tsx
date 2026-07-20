import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { HubAssetsTable } from "../components/hub/HubAssetsTable";
import { HubDeliverSection } from "../components/hub/HubDeliverSection";
import { HubPreflightStrip } from "../components/hub/HubPreflightStrip";
import { HubToolbar, type HubFilter } from "../components/hub/HubToolbar";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { Section } from "../components/Section";
import {
  fetchHubInventory,
  fetchHubMeta,
  fetchHubMetaTotals,
  fetchHubPresets,
  fetchHubStateStamp,
  isMock,
  postHubApply,
  postHubMakeRelative,
  postHubMatchFolder,
  postHubPickPath,
  postHubSelectOwner,
  saveHubPreset,
} from "../lib/api";
import { computeBulkChanges } from "../lib/repath";
import { useToast } from "../lib/toast";
import type { HubInventory, HubInventoryResult, HubMeta, HubMetaTotals, HubPreset } from "../types";

type PageState = { kind: "loading" } | HubInventoryResult;

const POLL_INTERVAL_MS = 2000;
const META_CHUNK_SIZE = 64;

function mergePending(prev: Map<string, string>, additions: Map<string, string>): Map<string, string> {
  if (additions.size === 0) return prev;
  const next = new Map(prev);
  for (const [key, path] of additions) next.set(key, path);
  return next;
}

/** Asset Hub SPA page — inventory table, filters/search, Find/Replace
 * bulk repathing, and the polling loop that keeps the table honest against
 * out-of-band scene edits (native Attribute Manager, undo, another dialog).
 * See docs/superpowers/plans/2026-07-20-hub-spa.md Task 10 for the full
 * behavior contract this implements. The Deliver section (preflight strip +
 * inline gate + job progress + delivery summary, `?focus=deliver` scrolls
 * it into view) is Task 11 — see HubPreflightStrip.tsx / HubDeliverSection.tsx.
 */
export function HubPage() {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [pending, setPending] = useState<Map<string, string>>(new Map());
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [filter, setFilter] = useState<HubFilter>("all");
  const [search, setSearch] = useState("");
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [matchCase, setMatchCase] = useState(false);
  const [presets, setPresets] = useState<HubPreset[]>([]);
  const [busy, setBusy] = useState(false);
  const [sceneChanged, setSceneChanged] = useState(false);
  const [metas, setMetas] = useState<Record<string, HubMeta>>({});
  const [metaTotals, setMetaTotals] = useState<HubMetaTotals | null>(null);

  // Refs so the polling interval (set up once) always reads the latest
  // values without re-creating the interval on every keystroke/selection.
  const stampRef = useRef<string | null>(null);
  const deliverRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef<Map<string, string>>(pending);
  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);

  const refreshInventory = useCallback(async (silent: boolean) => {
    if (!silent) setState({ kind: "loading" });
    const result = await fetchHubInventory();
    setState(result);
    setSceneChanged(false);
    stampRef.current = result.kind === "ok" ? await fetchHubStateStamp() : null;
  }, []);

  useEffect(() => {
    refreshInventory(false);
    fetchHubPresets().then((result) => {
      if (result.kind === "ok") setPresets(result.data);
    });

    // `?focus=deliver` deep-link — the Collect Scene button (panel.py)
    // opens the Hub with this so the artist lands directly on Deliver
    // instead of scrolling past the inventory table themselves.
    try {
      const focus = new URLSearchParams(window.location.search).get("focus");
      if (focus === "deliver") {
        requestAnimationFrame(() => {
          deliverRef.current?.scrollIntoView({ block: "start" });
        });
      }
    } catch {
      // window/URLSearchParams unavailable in this host — no-op
    }
  }, [refreshInventory]);

  // Meta sweep: after each inventory load, fetch header metadata for every
  // asset key in chunks of 64 (sequential — 39-500 assets is at most ~8
  // requests, simpler than viewport-tracking, and the server-side (path,
  // mtime, size) cache makes repeat sweeps of unchanged assets free). Skipped
  // when the key set is unchanged from the last sweep (e.g. a silent poll
  // refresh with no new assets) so it doesn't re-hit the server every 2s.
  const sweptKeysRef = useRef<string>("");
  useEffect(() => {
    if (state.kind !== "ok") return;
    const keys = state.data.assets.map((a) => a.key);
    const signature = keys.slice().sort().join("|");
    if (signature === sweptKeysRef.current) return;
    sweptKeysRef.current = signature;

    let cancelled = false;
    (async () => {
      for (let i = 0; i < keys.length; i += META_CHUNK_SIZE) {
        if (cancelled) return;
        const chunk = keys.slice(i, i + META_CHUNK_SIZE);
        const result = await fetchHubMeta(chunk);
        if (cancelled) return;
        if (Object.keys(result).length > 0) {
          setMetas((prev) => ({ ...prev, ...result }));
        }
      }
      if (cancelled) return;
      const totals = await fetchHubMetaTotals();
      if (!cancelled) setMetaTotals(totals);
    })();
    return () => {
      cancelled = true;
    };
  }, [state]);

  useEffect(() => {
    // No polling under `?mock=1` — there is no live document to drift from,
    // and the mocked stamp is a constant that would never fire a change
    // anyway, but setting up a live interval in a mock/demo/screenshot
    // context is still the wrong behavior to ship.
    if (isMock()) return;
    const id = window.setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      const newStamp = await fetchHubStateStamp();
      if (newStamp === null || stampRef.current === null || newStamp === stampRef.current) return;
      if (pendingRef.current.size === 0) {
        refreshInventory(true);
      } else {
        setSceneChanged(true);
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refreshInventory]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") {
    return <ErrorState title="Couldn't load the Asset Hub" message={state.message} onRetry={() => refreshInventory(false)} />;
  }
  if (state.kind === "empty") {
    return <EmptyState title="No document open" reason={state.reason} />;
  }

  const data: HubInventory = state.data;

  async function handleOwnerClick(key: string) {
    const res = await postHubSelectOwner(key);
    if (res.stamp) stampRef.current = res.stamp;
    if (!res.ok) toast({ message: res.error || "Couldn't select the owner.", variant: "warn" });
  }

  function handleRowSelect(key: string) {
    setSelectedKey(key);
    handleOwnerClick(key);
  }

  function handlePreview() {
    if (!find) return;
    const changes = computeBulkChanges(data.assets, find, replace, matchCase);
    setPending((prev) => mergePending(prev, changes));
    saveHubPreset(find, replace).then(() => {
      fetchHubPresets().then((result) => {
        if (result.kind === "ok") setPresets(result.data);
      });
    });
    toast({
      message: changes.size > 0 ? `${changes.size} path(s) staged.` : `No repathable paths contain '${find}'.`,
      variant: changes.size > 0 ? "success" : "info",
    });
  }

  async function handleMakeRelative() {
    setBusy(true);
    const res = await postHubMakeRelative();
    setBusy(false);
    if (!res.ok) {
      toast({ message: res.error || "Couldn't compute relative paths.", variant: "warn" });
      return;
    }
    const changes = new Map((res.changes || []).map((c) => [c.key, c.new_path]));
    setPending((prev) => mergePending(prev, changes));
    let message = `${changes.size} absolute path(s) → relative.`;
    if (res.skipped_cross_drive) message += ` ${res.skipped_cross_drive} skipped (cross-drive).`;
    toast({ message, variant: "success" });
  }

  async function handleSearchFolder() {
    // `busy` is set around the picker itself (not just the match_folder
    // call after it) so a double-click can't queue a second native
    // LoadDialog while the first is still open.
    setBusy(true);
    try {
      const picked = await postHubPickPath(true, "Choose folder to search");
      if (!picked.ok || !picked.path) return;
      const res = await postHubMatchFolder(picked.path);
      if (!res.ok) {
        toast({ message: res.error || "Couldn't search that folder.", variant: "warn" });
        return;
      }
      const changes = new Map((res.matches || []).map((m) => [m.key, m.match]));
      setPending((prev) => mergePending(prev, changes));
      let message = `Matched ${changes.size} missing asset(s).`;
      if (res.ambiguous) message += ` ${res.ambiguous} ambiguous (use Relink Selected…).`;
      if (res.truncated) message += " Folder index truncated (>50k files).";
      toast({ message, variant: changes.size > 0 ? "success" : "info" });
    } finally {
      setBusy(false);
    }
  }

  async function handleRelinkSelected() {
    if (!selectedKey) {
      toast({ message: "Select a row first.", variant: "info" });
      return;
    }
    setBusy(true);
    try {
      const picked = await postHubPickPath(false, "Choose replacement file");
      if (!picked.ok || !picked.path) return;
      setPending((prev) => new Map(prev).set(selectedKey, picked.path!));
    } finally {
      setBusy(false);
    }
  }

  function handleClear() {
    setPending(new Map());
  }

  async function handleApply() {
    if (pending.size === 0) return;
    const changes = Array.from(pending, ([key, new_path]) => ({ key, new_path }));
    setBusy(true);
    const res = await postHubApply(changes);
    setBusy(false);
    if (!res.ok) {
      toast({ message: res.error || "Apply failed.", variant: "warn" });
      return;
    }
    if (res.stamp) stampRef.current = res.stamp;
    const errorKeys = new Set((res.errors || []).map((e) => e.key));
    setPending((prev) => {
      const next = new Map<string, string>();
      for (const [key, path] of prev) if (errorKeys.has(key)) next.set(key, path);
      return next;
    });
    const errorCount = res.errors?.length ?? 0;
    toast({
      message: errorCount > 0
        ? `Applied ${res.applied ?? 0}, ${errorCount} failed — see remaining pending rows.`
        : `Applied ${res.applied ?? 0} change(s).`,
      variant: errorCount > 0 ? "warn" : "success",
    });
    await refreshInventory(true);
  }

  const searchLower = search.trim().toLowerCase();
  const filteredAssets = data.assets.filter((asset) => {
    if (filter !== "all" && asset.status !== filter) return false;
    if (searchLower && !asset.path.toLowerCase().includes(searchLower) && !asset.asset_type.toLowerCase().includes(searchLower)) {
      return false;
    }
    return true;
  });

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <header
        className="flex items-center justify-between gap-3 px-4 py-3"
        style={{ backgroundColor: "var(--color-surface-1)", borderBottom: "1px solid var(--color-hairline-strong)" }}
      >
        <div className="min-w-0">
          <h1 className="text-title truncate" style={{ color: "var(--color-ink)" }}>
            Asset Hub — {data.scene_name}
          </h1>
          <p className="text-caption mt-0.5" style={{ color: "var(--color-ink-secondary)" }}>
            {data.totals.count} assets · {data.totals.total_label}
            {metaTotals && metaTotals.total > 0 && (
              <span>
                {" "}
                · {metaTotals.covered < metaTotals.total ? "~" : ""}
                {metaTotals.vram_label} VRAM
              </span>
            )}
            {data.totals.missing > 0 && (
              <span style={{ color: "var(--color-status-fail)" }}> · {data.totals.missing} missing</span>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={() => refreshInventory(false)}
          disabled={busy}
          className="text-label inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 transition-colors duration-100 ease-out disabled:cursor-not-allowed disabled:opacity-50"
          style={{ backgroundColor: "var(--color-surface-2)", color: "var(--color-ink)", border: "1px solid var(--color-hairline)" }}
        >
          <RefreshCw size={14} strokeWidth={2.25} aria-hidden="true" />
          Refresh
        </button>
      </header>

      {sceneChanged && (
        <div
          className="flex items-center justify-between gap-3 px-4 py-2"
          style={{ backgroundColor: "var(--color-status-warn-tint-10)", borderBottom: "1px solid var(--color-hairline)" }}
        >
          <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
            Scene changed — Refresh to rescan (pending changes will be kept by key).
          </p>
          <button
            type="button"
            onClick={() => refreshInventory(true)}
            className="text-label rounded-md px-2.5 py-1"
            style={{ backgroundColor: "var(--color-primary)", color: "var(--color-on-primary)" }}
          >
            Refresh
          </button>
        </div>
      )}

      <HubToolbar
        filter={filter}
        onFilter={setFilter}
        search={search}
        onSearch={setSearch}
        find={find}
        onFindChange={setFind}
        replace={replace}
        onReplaceChange={setReplace}
        matchCase={matchCase}
        onMatchCaseChange={setMatchCase}
        presets={presets}
        onPreview={handlePreview}
        onMakeRelative={handleMakeRelative}
        onSearchFolder={handleSearchFolder}
        onRelinkSelected={handleRelinkSelected}
        onClear={handleClear}
        onApply={handleApply}
        pendingCount={pending.size}
        busy={busy}
      />

      <div className="flex-1 overflow-auto p-4">
        <HubAssetsTable
          assets={filteredAssets}
          pending={pending}
          selectedKey={selectedKey}
          onSelect={handleRowSelect}
          onOwnerClick={handleOwnerClick}
          metas={metas}
        />
        <div ref={deliverRef}>
          <Section title="Deliver">
            <div className="flex flex-col gap-3">
              <HubPreflightStrip onFixed={() => refreshInventory(true)} />
              <HubDeliverSection
                missingCount={data.totals.missing}
                onInventoryRefresh={() => refreshInventory(true)}
              />
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
