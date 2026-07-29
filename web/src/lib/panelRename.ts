import type { RenameApplyResult } from "../types";

/** Batch Rename ops payload — mirrors `renaming.DEFAULT_OPS` in
 * plugin/sentinel/renaming.py FIELD-FOR-FIELD (mock-shape law: this is the
 * exact dict `normalize_ops` merges over its defaults; a drifted key would
 * be silently dropped server-side). Pinned by panelRename.test.ts. */
export interface RenameOps {
  pattern: string;
  find: string;
  replace: string;
  match_case: boolean;
  prefix: string;
  suffix: string;
  num_start: number;
  num_padding: number;
}

export const DEFAULT_RENAME_OPS: RenameOps = {
  pattern: "",
  find: "",
  replace: "",
  match_case: false,
  prefix: "",
  suffix: "",
  num_start: 1,
  num_padding: 3,
};

export type RenameSource = "objects" | "materials";

/** Apply result → toast. Collisions still succeed server-side (C4D allows
 * duplicate names — Sentinel warns, the artist decides), but the toast goes
 * WARN so the duplicate outcome is noticed, not skimmed past. */
export function renameToast(
  source: RenameSource,
  r: RenameApplyResult,
): { message: string; variant: "success" | "warn" } {
  if (!r.ok) {
    if (r.error === "no_selection") {
      return { message: "Select something to rename first.", variant: "warn" };
    }
    if (r.error === "nothing_to_do") {
      return { message: "Fill in at least one rename field.", variant: "warn" };
    }
    return { message: "Couldn't rename.", variant: "warn" };
  }
  const noun = source === "materials" ? "material" : "object";
  const collisions = r.collisions ?? 0;
  let message = `Renamed ${r.renamed ?? 0} ${noun}(s).`;
  if (collisions > 0) {
    message += ` (${collisions} duplicate result(s))`;
    return { message, variant: "warn" };
  }
  return { message, variant: "success" };
}
