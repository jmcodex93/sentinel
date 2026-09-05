import { expect, it, vi } from "vitest";
import { SnapshotChannel } from "../../lib/snapshot";
import type {
  PaletteAction,
  PaletteActionsResult,
  QcReportResult,
} from "../../types";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function preflight(score: string): QcReportResult {
  return {
    kind: "ok",
    data: {
      // Deliberately identical: document names are display labels and cannot
      // distinguish two open Cinema 4D documents.
      scene: "Same.c4d",
      ruleset: { name: "Built-in defaults", path: null, shadowed: [] },
      score: {
        score,
        passed: Number(score.split("/")[0]),
        total: 13,
        disabled_count: 0,
        baseline_status: null,
      },
      checks: [],
      disabled: [],
    },
  };
}

function fixAction(enabled: boolean): PaletteAction {
  return {
    id: "fix_materials",
    label: "Fix Materials",
    group: "QC",
    enabled,
    reason: enabled ? null : "No unused materials",
    requires_confirm: true,
    confirm_label: "Delete unused materials?",
    confirm_verb: "Delete materials",
    destructive: true,
  };
}

it("keeps preflight and fix availability on the latest accepted inventory snapshot", async () => {
  const module = await import("./HubPreflightStrip");
  expect(module.loadHubPreflightSnapshot).toBeTypeOf("function");
  if (!("loadHubPreflightSnapshot" in module)) return;

  const load = module.loadHubPreflightSnapshot as (
    channel: SnapshotChannel,
    commit: (snapshot: { state: QcReportResult; actions: PaletteAction[] }) => void,
    readPreflight: () => Promise<QcReportResult>,
    readActions: () => Promise<PaletteActionsResult>,
  ) => Promise<void>;
  const channel = new SnapshotChannel();
  const commits = vi.fn();

  const betaBPreflight = deferred<QcReportResult>();
  const betaBActions = deferred<PaletteActionsResult>();
  const betaBLoad = load(
    channel,
    commits,
    () => betaBPreflight.promise,
    () => betaBActions.promise,
  );

  const betaAPreflight = deferred<QcReportResult>();
  const betaAActions = deferred<PaletteActionsResult>();
  const betaALoad = load(
    channel,
    commits,
    () => betaAPreflight.promise,
    () => betaAActions.promise,
  );

  betaAPreflight.resolve(preflight("10/13"));
  betaAActions.resolve({ kind: "ok", data: [fixAction(false)] });
  await betaALoad;

  betaBPreflight.resolve(preflight("8/13"));
  betaBActions.resolve({ kind: "ok", data: [fixAction(true)] });
  await betaBLoad;

  expect(commits).toHaveBeenCalledTimes(1);
  expect(commits.mock.calls[0][0]).toEqual({
    state: preflight("10/13"),
    actions: [fixAction(false)],
  });
});
