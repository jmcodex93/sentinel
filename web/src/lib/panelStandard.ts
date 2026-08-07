/** Pure client logic for the Project standard sub-views (v1.37). */

export interface StandardQc {
  passed: number;
  total: number;
  pass: boolean;
  failing: string[];
}

export type ExcludeEntry = [string, number];

export function qcGateLine(qc: StandardQc): string {
  if (qc.pass) return `QC ${qc.passed}/${qc.total} — ready to publish`;
  return `QC ${qc.passed}/${qc.total} — fix before publishing: ${qc.failing.join(", ")}`;
}

export function toggleExclude(list: ExcludeEntry[], name: string, index: number): ExcludeEntry[] {
  const has = list.some(([n, i]) => n === name && i === index);
  if (has) return list.filter(([n, i]) => !(n === name && i === index));
  return [...list, [name, index]];
}

export function publishDisabledReason(state: { folder: string; qcPass: boolean }): string | null {
  if (!state.folder) return "Choose the project folder first.";
  if (!state.qcPass) return "The scene must pass the QC before publishing.";
  return null;
}

export const STANDARD_ERROR_COPY: Record<string, string> = {
  no_document: "No active document.",
  unsaved: "Save the scene first — the standard is published from a saved shot.",
  bad_folder: "That folder does not exist.",
  qc_failing: "The scene must pass the QC before publishing.",
  scene_changed: "The scene changed since the preview — review and publish again.",
  rules_unreadable: "The existing sentinel_rules.json cannot be read. Fix or remove it first.",
  save_failed: "Could not write the standard scene file.",
  write_failed: "Could not write sentinel_rules.json.",
};

export const NEWSHOT_ERROR_COPY: Record<string, string> = {
  bad_folder: "That folder does not exist.",
  no_standard: "No project standard found here (no sentinel_rules.json in this folder or its parents).",
  no_template: "This project's ruleset does not declare a standard scene.",
  template_missing: "The standard scene file is missing — ask the supervisor to republish.",
  bad_name: "Shot names cannot be empty or contain slashes.",
  exists: "A shot with that name already exists. Nothing was overwritten.",
  copy_failed: "Could not copy the standard scene to the destination.",
};
