import { useCallback, useEffect, useState } from "react";
import { Checkbox } from "../components/form/Checkbox";
import { FieldRow } from "../components/form/FieldRow";
import { FormPageShell } from "../components/form/FormPageShell";
import { LockedField } from "../components/form/LockedField";
import { Select } from "../components/form/Select";
import { SubmitBar } from "../components/form/SubmitBar";
import { TextInput } from "../components/form/TextInput";
import { ErrorState, LoadingState } from "../components/PageStates";
import { fetchSettingsState, submitSettings } from "../lib/api";
import { useToast } from "../lib/toast";
import type { SettingsState, SettingsStateResult } from "../types";

type PageState = { kind: "loading" } | SettingsStateResult;

/** Settings — mirrors `ui/dialogs.py` `SentinelSettingsDialog` (see
 * web_ops.py `_op_form_settings_state/_submit`'s docstrings). Two fields
 * can be machine-locked: Standard FPS (a project ruleset overrides it) and
 * the RS Snapshot Directory (auto-detected from Redshift RenderView) — both
 * render as `LockedField` instead of an editable control when locked. */
export function SettingsPage() {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [fps, setFps] = useState(25);
  const [compositor, setCompositor] = useState(0);
  const [multipart, setMultipart] = useState(true);
  const [slate, setSlate] = useState(false);
  const [mvMax, setMvMax] = useState(0);
  const [snapshotDir, setSnapshotDir] = useState("");
  const [historyMax, setHistoryMax] = useState(5);
  const [pending, setPending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchSettingsState().then((result) => {
      setState(result);
      if (result.kind === "ok") {
        const d = result.data;
        setFps(d.fps.value);
        setCompositor(d.compositor.value);
        setMultipart(d.multipart_default);
        setSlate(d.slate.value);
        setMvMax(d.mv_max_motion);
        setSnapshotDir(d.snapshot_dir.value);
        setHistoryMax(d.history_max.value);
      }
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") {
    return <ErrorState title="Couldn't load Settings" message={state.message} onRetry={load} />;
  }

  const data: SettingsState = state.data;

  async function handleSubmit() {
    setSubmitError(null);
    setPending(true);
    const response = await submitSettings({
      fps,
      compositor,
      multipart_default: multipart,
      slate,
      mv_max_motion: mvMax,
      snapshot_dir: snapshotDir,
      history_max: historyMax,
    });
    setPending(false);

    if (!response.ok) {
      setSubmitError(response.error || "Settings failed to save.");
      return;
    }
    toast({ message: "Settings saved.", variant: "success" });
  }

  return (
    <FormPageShell
      title="Settings"
      footer={<SubmitBar submitLabel="Save Settings" pending={pending} onSubmit={handleSubmit} error={submitError} />}
    >
      <div className="flex flex-col gap-4">
        <FieldRow label="Standard FPS" htmlFor="settings-fps">
          {data.fps.locked ? (
            <LockedField value={`${data.fps.value} fps`} reason={data.fps.locked_reason || "Locked"} />
          ) : (
            <Select
              id="settings-fps"
              value={String(fps)}
              options={data.fps.options.map((value) => ({ value: String(value), label: `${value} fps` }))}
              onChange={(v) => setFps(Number(v))}
            />
          )}
        </FieldRow>

        <FieldRow label="Compositor Target" htmlFor="settings-compositor">
          <Select
            id="settings-compositor"
            value={String(compositor)}
            options={data.compositor.options.map((label, index) => ({ value: String(index), label }))}
            onChange={(v) => setCompositor(Number(v))}
          />
        </FieldRow>

        <FieldRow label="Multi-Part EXR">
          <Checkbox
            id="settings-multipart"
            checked={multipart}
            onChange={setMultipart}
            label="Enabled by default for new AOV setups"
          />
        </FieldRow>

        <FieldRow label="Snapshot Slate">
          <Checkbox id="settings-slate" checked={slate} onChange={setSlate} label="Burn in review slate on snapshots" />
        </FieldRow>

        <FieldRow label="Max Motion Vector Length" htmlFor="settings-mv-max" hint="0 = no clamp.">
          <TextInput
            id="settings-mv-max"
            type="number"
            min={0}
            value={mvMax}
            onChange={(e) => setMvMax(Math.max(0, Number(e.target.value) || 0))}
          />
        </FieldRow>

        <FieldRow label="RS Snapshot Directory" htmlFor="settings-snapshot-dir">
          {data.snapshot_dir.locked ? (
            <LockedField value={snapshotDir} reason="Auto-detected from Redshift RenderView" />
          ) : (
            <TextInput
              id="settings-snapshot-dir"
              value={snapshotDir}
              onChange={(e) => setSnapshotDir(e.target.value)}
              placeholder="/path/to/snapshots"
            />
          )}
        </FieldRow>

        <FieldRow label="Recent Versions Shown" htmlFor="settings-history-max">
          <Select
            id="settings-history-max"
            value={String(historyMax)}
            options={data.history_max.options.map((value) => ({ value: String(value), label: String(value) }))}
            onChange={(v) => setHistoryMax(Number(v))}
          />
        </FieldRow>
      </div>
    </FormPageShell>
  );
}
