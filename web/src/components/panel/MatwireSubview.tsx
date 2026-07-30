import { useCallback, useRef, useState } from "react";
import { Button } from "../form/Button";
import { Checkbox } from "../form/Checkbox";
import { SegmentedControl } from "../form/SegmentedControl";
import { TextInput } from "../form/TextInput";
import { SectionGroup } from "../SectionGroup";
import { fetchMatwirePreview, postHubPickPath, postMatwireCreate } from "../../lib/api";
import { restoreFocus } from "../../lib/focus";
import {
  MATERIAL_OPTIONS,
  MATWIRE_IMPORT_LEFTOVERS_LABEL,
  MATWIRE_MULTIPLY_AO_LABEL,
  PROJECTION_OPTIONS,
  aoDestination,
  aoDestinationLabel,
  channelLabel,
  createMaterialCount,
  effectiveMaterial,
  glossDestinationLabel,
  ignoredReasonLabel,
  leftoverDestinationLabel,
  matwireToast,
  openpbrUnavailableNote,
  packedOrmNote,
  projectionUnavailableNote,
  effectiveProjection,
  suffixWarningsNote,
} from "../../lib/panelMatwire";
import { useToast } from "../../lib/toast";
import type { MatwireLeftoverRow, MatwirePreviewResult } from "../../types";

/** Inline (muted, non-toast) copy for a preview that can't be computed —
 * normal states of pointing at the wrong folder, not failures, so they
 * render as quiet text instead of interrupting with a toast (the
 * RenameSubview PREVIEW_EMPTY_COPY pattern). */
const PREVIEW_EMPTY_COPY: Record<string, string> = {
  no_sets: "No texture sets recognized in that folder.",
  bad_folder: "That folder doesn't exist.",
  redshift_unavailable: "Redshift is not available.",
};

const COLORSPACE_LABEL: Record<string, string> = { srgb: "sRGB", raw: "Raw" };

/** Small neutral chip for the channel's colorspace — informational, not
 * state, so it stays on the ink scale (the accent-never-marks-state rule). */
function ColorspaceChip({ colorspace }: { colorspace: string }) {
  return (
    <span
      className="text-caption shrink-0 rounded-full border px-1.5"
      style={{ borderColor: "var(--color-hairline)", color: "var(--color-ink-secondary)" }}
    >
      {COLORSPACE_LABEL[colorspace] ?? colorspace}
    </span>
  );
}

/** Folded `▸ N file(s) ignored` list with reason labels — shared by the
 * per-set fold and the global (unrecognized/non-image) fold. */
function IgnoredFold({ rows, title }: { rows: [string, string][]; title: string }) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;
  return (
    <div>
      <button
        type="button"
        className="text-caption cursor-pointer"
        style={{ color: "var(--color-ink-secondary)" }}
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? "▾" : "▸"} {rows.length} {title}
      </button>
      {open && (
        <div className="mt-1 flex flex-col gap-0.5 pl-4">
          {rows.map(([file, reason], index) => (
            <div key={index} className="text-caption flex items-baseline gap-2">
              <span className="min-w-0 truncate" style={{ color: "var(--color-ink-secondary)" }}>
                {file}
              </span>
              <span className="shrink-0" style={{ color: "var(--color-muted)" }}>
                {ignoredReasonLabel(reason)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Folded `▸ N unrecognized file(s)` list with each leftover's destination
 * (its prefix-matched set, or the catch-all leftovers material) — the
 * IgnoredFold pattern, but with a destination instead of a reason. The
 * destination is derived against the LIVE `excluded` selection (not the
 * preview's stale assignment): a leftover whose set has since been
 * excluded from Create is dropped by the server, and the label must say
 * so rather than showing an arrow to a set that won't exist. */
function LeftoversFold({
  rows,
  excluded,
}: {
  rows: MatwireLeftoverRow[];
  excluded: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  if (rows.length === 0) return null;
  return (
    <div>
      <button
        type="button"
        className="text-caption cursor-pointer"
        style={{ color: "var(--color-ink-secondary)" }}
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? "▾" : "▸"} {rows.length} unrecognized file(s)
      </button>
      {open && (
        <div className="mt-1 flex flex-col gap-0.5 pl-4">
          {rows.map((row, index) => (
            <div key={index} className="text-caption flex items-baseline gap-2">
              <span className="min-w-0 truncate" style={{ color: "var(--color-ink-secondary)" }}>
                {row.file}
              </span>
              <span className="shrink-0" style={{ color: "var(--color-muted)" }}>
                {leftoverDestinationLabel(row, excluded)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Material from Folder sub-view (v1.32) — self-contained like the
 * RenameSubview: owns its preview fetch and its create. The preview is
 * ALWAYS the server's scan (`matwire_preview` — no client-side recognition
 * anywhere); the SPA only edits inclusion + names on top of it. NO 2s poll
 * here: the input is a disk folder, not scene state, so refresh is
 * explicit — Browse re-pick, the Refresh button, or the refetch after a
 * create (which re-dedupes default names against the new materials). */
export function MatwireSubview({ onBack }: { onBack: () => void }) {
  const { toast } = useToast();
  const [folder, setFolder] = useState("");
  const [preview, setPreview] = useState<MatwirePreviewResult | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [names, setNames] = useState<Record<string, string>>({});
  const [importLeftovers, setImportLeftovers] = useState(false);
  // v1.33 wiring options — both default to the v1.32.1-equivalent material.
  const [projection, setProjection] = useState("uv");
  const [multiplyAo, setMultiplyAo] = useState(false);
  // v1.34: material type, OpenPBR default.
  const [material, setMaterial] = useState("openpbr");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  // Monotonic sequence: only the LATEST in-flight preview may land (a slow
  // stale response must never overwrite a newer scan).
  const seqRef = useRef(0);

  const loadPreview = useCallback(async (dir: string) => {
    const seq = ++seqRef.current;
    setLoading(true);
    try {
      // multiplyAo rides along so the server's AO rows agree with the
      // checkbox; toggling it does NOT re-fetch (a re-scan re-seeds names
      // and inclusion — the AO label stays live via the aoDestination
      // mirror instead).
      const result = await fetchMatwirePreview(dir, multiplyAo);
      if (seq !== seqRef.current) return;
      setPreview(result);
      // Re-seed the editable state from the server's scan: default names are
      // the op's deduped `names` (position-aligned with `sets`), inclusion
      // resets to all-in. A re-scan is a new scan — stale edits for sets
      // that may no longer exist must not linger.
      if (result.ok) {
        const sets = result.sets ?? [];
        const defaults = result.names ?? [];
        const seeded: Record<string, string> = {};
        sets.forEach((s, i) => {
          seeded[s.name] = defaults[i] ?? s.name;
        });
        setNames(seeded);
        setExcluded(new Set());
      }
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [multiplyAo]);

  const handleBrowse = async () => {
    const picked = await postHubPickPath(true, "Choose texture folder");
    if (picked.ok && picked.path) {
      setFolder(picked.path);
      await loadPreview(picked.path);
    }
    // The native pick dialog stole the webview focus; without a live focused
    // element the next Cmd+Z is swallowed (v1.18 lesson, lib/focus.ts).
    restoreFocus();
  };

  const sets = preview?.ok ? (preview.sets ?? []) : [];
  const included = sets.filter((s) => !excluded.has(s.name));
  const leftovers = preview?.ok ? (preview.leftovers ?? []) : [];
  const warningsNote = preview?.ok ? suffixWarningsNote(preview.suffix_warnings) : null;
  // Non-null => this RS build has no shared UV context node: the Projection
  // selector is disabled and says why (the writer degrades to v1.32.1).
  const projectionNote = preview?.ok
    ? projectionUnavailableNote(preview.uvcontext_available)
    : null;
  // What the material is ACTUALLY wired with: with the note up, the pick
  // degrades to UV for BOTH the payload and the shown value, so the
  // disabled control can never say Tri-Planar while the writer does UV.
  const wiredProjection = effectiveProjection(projection, projectionNote);
  // Non-null => this RS build has no OpenPBR node: the Material selector is
  // disabled and says why (the writer degrades to Standard Surface).
  const openpbrNote = preview?.ok
    ? openpbrUnavailableNote(preview.openpbr_available)
    : null;
  // What the material ACTUALLY gets built as — same degradation contract as
  // wiredProjection: the disabled control can never say OpenPBR while the
  // writer builds Standard.
  const wiredMaterial = effectiveMaterial(material, openpbrNote);
  const emptyReason = preview && !preview.ok
    ? (PREVIEW_EMPTY_COPY[preview.error ?? ""] ?? "Preview unavailable.")
    : null;
  const canCreate = !applying && included.length > 0;
  // The button counts the catch-all `<root>_leftovers` material too when the
  // server would create it (review M1) — the promise must match the outcome.
  const createCount = createMaterialCount(included.length, importLeftovers, leftovers);

  const handleCreate = async () => {
    // Belt + braces: the button is disabled at zero included sets, so the
    // op is never called with everything excluded (client-side
    // `nothing_selected` — see matwireToast).
    if (included.length === 0) return;
    setApplying(true);
    try {
      const result = await postMatwireCreate(
        folder, [...excluded], names, importLeftovers, wiredProjection, multiplyAo,
        wiredMaterial);
      toast(matwireToast(result));
      // Refetch: the new materials change the dedupe of default names.
      if (result.ok) await loadPreview(folder);
    } finally {
      setApplying(false);
      restoreFocus();
    }
  };

  const toggleSet = (name: string, include: boolean) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (include) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <div className="flex flex-col p-3">
      <div className="flex items-center justify-between">
        <Button variant="secondary" onClick={onBack}>
          ← Tools
        </Button>
      </div>

      <SectionGroup title="Texture folder" first>
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <TextInput
              placeholder="Path to a texture folder"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && folder) void loadPreview(folder);
              }}
            />
          </div>
          <Button variant="secondary" disabled={applying} onClick={handleBrowse}>
            Browse…
          </Button>
          <Button
            variant="secondary"
            disabled={applying || !folder}
            onClick={() => void loadPreview(folder)}
          >
            Refresh
          </Button>
        </div>
      </SectionGroup>

      <SectionGroup title="Texture sets">
        {!preview && !loading ? (
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            Pick a folder to scan.
          </p>
        ) : emptyReason ? (
          <p className="text-body" style={{ color: "var(--color-muted)" }}>
            {emptyReason}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {warningsNote && (
              <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
                {warningsNote}
              </p>
            )}
            {sets.map((texSet) => {
              const isIncluded = !excluded.has(texSet.name);
              return (
                <div
                  key={texSet.name}
                  className="rounded-lg border p-2"
                  style={{
                    borderColor: "var(--color-hairline)",
                    opacity: isIncluded ? 1 : 0.55,
                  }}
                >
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={isIncluded}
                      onChange={(checked) => toggleSet(texSet.name, checked)}
                      label=""
                    />
                    <div className="min-w-0 flex-1">
                      <TextInput
                        value={names[texSet.name] ?? texSet.name}
                        disabled={!isIncluded}
                        onChange={(e) =>
                          setNames((prev) => ({ ...prev, [texSet.name]: e.target.value }))
                        }
                      />
                    </div>
                  </div>
                  <div className="mt-1.5 flex flex-col gap-0.5 pl-6">
                    {texSet.channels.map((row) => {
                      // The AO row says where the AO ACTUALLY lands (loose
                      // sampler vs. multiplied into base color) — mirrored
                      // from the engine's ao_destination so it relabels the
                      // instant the checkbox flips, without a re-scan.
                      const aoNote =
                        row.channel === "ao"
                          ? aoDestinationLabel(
                              aoDestination(
                                texSet.channels.map((c) => c.channel),
                                multiplyAo,
                              ),
                            )
                          : null;
                      // ORM/ARM rows say what they actually feed HERE — a
                      // packed map whose outputs are both taken by dedicated
                      // maps ends up unconnected, and the preview must not
                      // read like a normal wired channel (review I2).
                      const ormNote = packedOrmNote(row.contributes);
                      // The glossiness row says what it actually gets wired
                      // as — mirrored from the engine's gloss_destination so
                      // it relabels the instant the Material selector flips,
                      // without a re-scan.
                      const glossNote =
                        row.channel === "glossiness"
                          ? glossDestinationLabel(
                              texSet.channels.map((c) => c.channel),
                              wiredMaterial,
                            )
                          : null;
                      return (
                        <div key={row.channel} className="text-caption flex items-baseline gap-2">
                          <span className="w-32 shrink-0" style={{ color: "var(--color-ink)" }}>
                            {channelLabel(row.channel)}
                          </span>
                          <span
                            className="min-w-0 flex-1 truncate"
                            style={{ color: "var(--color-ink-secondary)" }}
                          >
                            {row.file}
                          </span>
                          {(ormNote || aoNote || glossNote) && (
                            <span className="shrink-0" style={{ color: "var(--color-muted)" }}>
                              {ormNote ?? aoNote ?? glossNote}
                            </span>
                          )}
                          <ColorspaceChip colorspace={row.colorspace} />
                        </div>
                      );
                    })}
                    <IgnoredFold rows={texSet.ignored} title="file(s) skipped" />
                  </div>
                </div>
              );
            })}
            <IgnoredFold rows={preview?.ignored ?? []} title="file(s) not recognized" />
            <div className="mt-1 flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  Material
                </span>
                <SegmentedControl
                  options={MATERIAL_OPTIONS}
                  value={wiredMaterial}
                  onChange={setMaterial}
                  disabled={openpbrNote !== null}
                />
              </div>
              {/* Honest degradation: a disabled control with no reason reads
                  as a bug — the server tells us the node is missing. */}
              {openpbrNote && (
                <p className="text-caption" style={{ color: "var(--color-muted)" }}>
                  {openpbrNote}
                </p>
              )}
              <div className="flex items-center gap-2">
                <span className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                  Projection
                </span>
                <SegmentedControl
                  options={PROJECTION_OPTIONS}
                  value={wiredProjection}
                  onChange={setProjection}
                  disabled={projectionNote !== null}
                />
              </div>
              {/* Honest degradation: a disabled control with no reason reads
                  as a bug — the server tells us the node is missing. */}
              {projectionNote && (
                <p className="text-caption" style={{ color: "var(--color-muted)" }}>
                  {projectionNote}
                </p>
              )}
              <Checkbox
                checked={multiplyAo}
                onChange={setMultiplyAo}
                label={MATWIRE_MULTIPLY_AO_LABEL}
              />
            </div>
            {leftovers.length > 0 && (
              <div className="mt-1 flex flex-col gap-1">
                <Checkbox
                  checked={importLeftovers}
                  onChange={setImportLeftovers}
                  label={MATWIRE_IMPORT_LEFTOVERS_LABEL}
                />
                <LeftoversFold rows={leftovers} excluded={excluded} />
              </div>
            )}
          </div>
        )}
        <div className="mt-3">
          <Button variant="primary" disabled={!canCreate} onClick={handleCreate}>
            Create {createCount} material{createCount === 1 ? "" : "s"}
          </Button>
        </div>
      </SectionGroup>
    </div>
  );
}
