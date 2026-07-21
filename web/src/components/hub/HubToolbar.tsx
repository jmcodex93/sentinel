import { FolderInput, FolderSearch, Link2, Minimize2, RotateCcw, Search, Wand2 } from "lucide-react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { Select } from "../form/Select";
import { TextInput } from "../form/TextInput";
import type { HubAssetStatus, HubPreset } from "../../types";

export type HubFilter = "all" | HubAssetStatus;

const FILTER_OPTIONS: { value: HubFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "missing", label: "Missing" },
  { value: "absolute", label: "Absolute" },
  { value: "ok", label: "OK" },
  { value: "asset_uri", label: "Asset URI" },
];

interface HubToolbarProps {
  filter: HubFilter;
  onFilter: (filter: HubFilter) => void;
  search: string;
  onSearch: (search: string) => void;
  find: string;
  onFindChange: (find: string) => void;
  replace: string;
  onReplaceChange: (replace: string) => void;
  matchCase: boolean;
  onMatchCaseChange: (matchCase: boolean) => void;
  presets: HubPreset[];
  onPreview: () => void;
  onMakeRelative: () => void;
  onSearchFolder: () => void;
  onRelinkSelected: () => void;
  onClear: () => void;
  onApply: () => void;
  pendingCount: number;
  selectedCount: number;
  busy: boolean;
  /** Task 4 (Fase 5.2) — Shrink/Copy into project. `onShrink` opens the
   * confirm dialog (HubPage owns the dialog + job flow); `shrinkEnabled`/
   * `copyEnabled` are coarse "any selected row is plausibly eligible" gates
   * computed by HubPage from status/asset_type alone — the exact per-target
   * eligibility (dims vs. target_px) is the dialog's own `shrinkPreview`
   * call, since the K target isn't chosen yet at the toolbar. `jobRunning`
   * disables both while a shrink job (or the Deliver collect job, sharing
   * the same single job slot server-side) is in flight. */
  onShrink: () => void;
  onCopyIntoProject: () => void;
  shrinkEnabled: boolean;
  copyEnabled: boolean;
  jobRunning: boolean;
}

/** Toolbar for the Asset Hub table -- search/filter row plus the bulk
 * repathing actions (mirrors `AssetHubDialog`'s Find/Replace strip + Smart
 * Actions row, dialogs.py ~2100-2260). All the mutating actions only ever
 * stage into `pending` (owned by `HubPage`) except Apply All, which is the
 * single write. `find`/`replace`/`matchCase` are controlled by `HubPage` so
 * `onPreview` can read the exact values that produced the staged rows (the
 * task brief's prop list named these three by value only; the paired
 * `onXChange` setters are the obviously-required wiring for controlled
 * inputs -- same shape as every other `TextInput`/`Checkbox` usage in this
 * codebase). */
export function HubToolbar({
  filter,
  onFilter,
  search,
  onSearch,
  find,
  onFindChange,
  replace,
  onReplaceChange,
  matchCase,
  onMatchCaseChange,
  presets,
  onPreview,
  onMakeRelative,
  onSearchFolder,
  onRelinkSelected,
  onClear,
  onApply,
  pendingCount,
  selectedCount,
  busy,
  onShrink,
  onCopyIntoProject,
  shrinkEnabled,
  copyEnabled,
  jobRunning,
}: HubToolbarProps) {
  return (
    <div
      className="flex flex-col gap-3 border-b px-4 py-3"
      style={{ borderColor: "var(--color-hairline-strong)", backgroundColor: "var(--color-surface-1)" }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search
            size={14}
            strokeWidth={2.25}
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2"
            style={{ color: "var(--color-ink-secondary)" }}
            aria-hidden="true"
          />
          <TextInput
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder="Search path or type..."
            className="pl-8"
            aria-label="Search assets"
          />
        </div>
        <div className="w-40">
          <Select
            id="hub-filter"
            value={filter}
            onChange={(value) => onFilter(value as HubFilter)}
            options={FILTER_OPTIONS}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[160px] flex-1">
          <TextInput
            value={find}
            onChange={(e) => onFindChange(e.target.value)}
            placeholder="Find"
            aria-label="Find"
          />
        </div>
        <div className="min-w-[160px] flex-1">
          <TextInput
            value={replace}
            onChange={(e) => onReplaceChange(e.target.value)}
            placeholder="Replace"
            aria-label="Replace"
          />
        </div>
        <Checkbox
          id="hub-match-case"
          checked={matchCase}
          onChange={onMatchCaseChange}
          label="Match case"
        />
        {presets.length > 0 && (
          <div className="w-44">
            {/* Index-based select: value is the preset's index into `presets`
                (as a plain decimal string), looked up by Number(value) on
                change. Avoids building any composite string key out of
                find/replace -- there is no separator character to pick or
                get wrong. */}
            <Select
              id="hub-recent-presets"
              value=""
              onChange={(value) => {
                if (value === "") return;
                const preset = presets[Number(value)];
                if (preset) {
                  onFindChange(preset.find);
                  onReplaceChange(preset.replace);
                }
              }}
              options={[
                { value: "", label: "Recent..." },
                ...presets.map((p, index) => ({
                  value: String(index),
                  label: `${p.find} -> ${p.replace}`,
                })),
              ]}
            />
          </div>
        )}
        <Button variant="secondary" disabled={busy || !find} onClick={onPreview}>
          Preview
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" disabled={busy} onClick={onMakeRelative}>
            <Wand2 size={14} strokeWidth={2.25} aria-hidden="true" />
            Make All Relative
          </Button>
          <Button variant="secondary" disabled={busy} onClick={onSearchFolder}>
            <FolderSearch size={14} strokeWidth={2.25} aria-hidden="true" />
            Search Folder...
          </Button>
          <Button
            variant="secondary"
            disabled={busy || selectedCount !== 1}
            title={selectedCount > 1 ? "Select exactly one row to relink." : undefined}
            onClick={onRelinkSelected}
          >
            <Link2 size={14} strokeWidth={2.25} aria-hidden="true" />
            Relink Selected...
          </Button>
          <Button variant="secondary" disabled={busy || pendingCount === 0} onClick={onClear}>
            <RotateCcw size={14} strokeWidth={2.25} aria-hidden="true" />
            Clear
          </Button>
          <Button
            variant="secondary"
            disabled={busy || jobRunning || !shrinkEnabled}
            title={selectedCount > 0 && !shrinkEnabled ? "No selected texture/HDRI rows are shrinkable." : undefined}
            onClick={onShrink}
          >
            <Minimize2 size={14} strokeWidth={2.25} aria-hidden="true" />
            Shrink...
          </Button>
          <Button
            variant="secondary"
            disabled={busy || jobRunning || !copyEnabled}
            title={selectedCount > 0 && !copyEnabled ? "Select at least one absolute-path row to copy in." : undefined}
            onClick={onCopyIntoProject}
          >
            <FolderInput size={14} strokeWidth={2.25} aria-hidden="true" />
            Copy into project
          </Button>
          {selectedCount > 0 && (
            <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
              {selectedCount} selected
            </span>
          )}
        </div>
        <Button variant="primary" disabled={busy || pendingCount === 0} onClick={onApply}>
          Apply All {pendingCount > 0 ? `(${pendingCount})` : ""}
        </Button>
      </div>
    </div>
  );
}
