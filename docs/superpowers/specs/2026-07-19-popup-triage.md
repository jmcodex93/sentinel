---
module: ui
tags: [popup-triage, reports, dialogs]
problem_type: ui-migration
---

# Popup triage — batch 1 (Phase 2 Task 3) + batch 2 (Task 4)

Full inventory of every `c4d.gui.MessageDialog(...)` / `c4d.gui.QuestionDialog(...)`
call site across `plugin/sentinel/ui/flows.py`, `plugin/sentinel/ui/panel.py`, and
`plugin/sentinel/ui/dialogs.py`, as required by the Phase 2 plan
(`docs/superpowers/plans/2026-07-19-ui-phase2-reports.md`, Tasks 3 and 4). Line
numbers are post-batch-1 (i.e. after the Task 3 conversions landed); the batch-2
section below re-verifies and converts the remaining panel.py INFORMATIVO sites
Task 3 flagged as "Task 4 candidate".

## Classification key

- **DECISIÓN** — a real yes/no gate (`QuestionDialog` driving a branch), a
  validation/prerequisite guard ("select something first", "save the scene
  first"), or a failure the user must notice before retrying / before data
  loss. Stays a native popup, this batch and future ones.
- **INFORMATIVO** — a pure result announcement after an action completed,
  where an inline surface already exists nearby (a caption/label/status area
  in the same dialog, or Cinema 4D's own status bar via `StatusSetText`).
  Candidate for conversion.
- **INFORMATIVO-DIFERIDO** — a pure result announcement with no existing
  inline surface nearby; would need a toast/notification affordance that
  doesn't exist yet (Phase 4 per the plan). Default when genuinely unsure
  between INFORMATIVO and DIFERIDO.

Converted-this-batch rows are marked **CONVERTED** in the classification
column with a short note on what replaced the popup.

---

## `plugin/sentinel/ui/flows.py` (14 sites)

`collect_scene()` (lines 458–616) is retired/dead code — superseded by
`AssetHubDialog` + `run_collect_pipeline` in v1.11 (confirmed via grep: no
live callers; `panel.py` has an explicit comment "`collect_scene` is no
longer called"). Its five popups are listed for completeness but not
classified for conversion — converting dead code has no user-facing effect
and the function is slated for removal, not investment.

| file:line | gist | classification | rationale |
|---|---|---|---|
| flows.py:459 | "No active document!" | LEGACY (dead code) | `collect_scene` has zero live callers |
| flows.py:464 | "Please save the scene first before collecting." | LEGACY (dead code) | same |
| flows.py:524 | 3-way pre-flight `MessageDialog(GEMB_YESNOCANCEL)` | LEGACY (dead code) | same |
| flows.py:543 | QuestionDialog "Pre-flight passed — proceed?" | LEGACY (dead code) | same |
| flows.py:616 | Collect summary dialog | LEGACY (dead code) | same |
| flows.py:694 | "Save Project failed!" (`run_collect_pipeline`, live — called from `AssetHubDialog`) | DECISIÓN | error before data loss (SaveProject failed); user must notice |
| flows.py:699 | "Save Project error:\n{e}" | DECISIÓN | same — exception during SaveProject |
| flows.py:1030 | "Please set your artist name first!" (`snapshot_save_still`) | DECISIÓN | defense-in-depth guard; the only live caller (`scene_tools._take_renderview_snapshot`) already validates artist_name before calling in, so this is currently unreachable, but kept as a guard since `snapshot_save_still` is a shared function |
| flows.py:1036 | `MessageDialog(error)` — no EXR snapshot found | DECISIÓN | real, reachable error explaining why the flow can't continue |
| flows.py:1059 | "Conversion failed:\n{error}" | DECISIÓN | real error, ACES conversion failure |
| flows.py:1067–1069 | "Still saved!" (filename/resolution/folder, or fallback path-only) | **CONVERTED** — `c4d.gui.StatusSetText(...)` | Picture Viewer already shows the result image (`c4d.bitmaps.ShowBitmap`) — the popup was purely redundant with what the artist is already looking at |
| flows.py:1143 | "Please set your artist name first!" (`snapshot_open_folder`) | DECISIÓN | reachable guard — `scene_tools._open_artist_folder` does NOT pre-check artist_name before calling in (unlike the save-still caller) |
| flows.py:1149 | "Folder not found:\n{output_dir}" | DECISIÓN | real error — stills folder doesn't exist yet |

**Converted this batch: 2** (lines 1067, 1069 — same call site's two branches).

---

## `plugin/sentinel/ui/panel.py` (44 sites remaining + 3 converted this batch + 2 new)

Baseline before this batch: 45 `MessageDialog`/`QuestionDialog` sites. This
batch converts 3 to `StatusSetText`/caption and adds 2 new ones (fallback
dialogs for the new Reports entry points) — net 44 remaining native popups.

### Converted this batch

| file:line (pre-batch) | gist | replaced with |
|---|---|---|
| `_qc_fix_fps_range` (fix-applied branch) | "Applied N fix(es):" + itemized list | `safe_print` (itemized detail to console) + `c4d.gui.StatusSetText("FPS/range: applied N fix(es) — see console for details")` — matches the sibling fixes (`_qc_fix_lights`, `_qc_fix_cam`, `_qc_fix_unused_mats`), which already used console+status-bar instead of a popup |
| `_qc_fix_fps_range` (no-fix branch) | "No fixes were applied." | `c4d.gui.StatusSetText("FPS/range: no fixes were applied")` |
| `_handle_save_version` (plain WIP save, non-review status) | Save summary (version/status/QC/history path) | `safe_print` (QC line) + `c4d.gui.StatusSetText(base_msg...)` — the "Last version" pillbox above the Save Version button (`LABEL_LAST_VERSION`) already reflects the new save on the next refresh tick (`self._dirty = True` is set right before this branch; verified `_update_last_version_label` is called whenever `self._dirty` is serviced, panel.py ~line 1255), so the modal was repeating facts already visible in the header. The review-status branch (TR/CR/FINAL) is untouched — its `QuestionDialog` ("continue in a new WIP version?") is a real decision, not a pure announcement. |

### New popups added this batch (Reports fallback paths)

| file:line | gist | classification | rationale |
|---|---|---|---|
| panel.py:2239 | "Sentinel Reports could not open. Use each check row's Info button…" | DECISIÓN | fallback shown only if the Reports server fails to start (missing SPA build / port exhaustion) for the new "Open QC Report" button — error the user must notice, no legacy QC-report dialog exists to fall back to |
| panel.py:2635 | Legacy Validate Render Output result text (`result["message"]`) | DECISIÓN (kept, repurposed as fallback) | fallback for the render-validation Reports entry — same content the old always-shown dialog had; now only shown if Reports can't open |

### Remaining native popups (DECISIÓN / INFORMATIVO-DIFERIDO — not converted)

| file:line | gist | classification | rationale |
|---|---|---|---|
| panel.py:1464 | "Could not update the baseline sidecar." | DECISIÓN | write failure, must notice |
| panel.py:1499 | "File not found: {filename}" (Browse Versions row click) | DECISIÓN | error — file moved/deleted since history was recorded |
| panel.py:1538 | QuestionDialog "Open {filename}?" (+ unsaved-changes warning) | DECISIÓN | real yes/no gate before loading another file |
| panel.py:1548 | "Cinema 4D could not open: {filename}" | DECISIÓN | error, LoadFile returned False |
| panel.py:1553 | "Error opening file:\n\n{e}" | DECISIÓN | error, exception during LoadFile |
| panel.py:1728 | RENDER PRESETS info report (Info button, multi-paragraph) | INFORMATIVO-DIFERIDO | on-demand detailed report, explicit "Info" click, too much content for a caption; family shared with 1799/1814/1865/2042/2158 below |
| panel.py:1748 | QuestionDialog "Open Asset Hub to fix these?" (texture issues) | DECISIÓN | real yes/no gate, branches to `_open_asset_hub` |
| panel.py:1799 | OUTPUT PATH ISSUES info report | INFORMATIVO-DIFERIDO | same family as 1728 |
| panel.py:1814 | TAKE ISSUES info report | INFORMATIVO-DIFERIDO | same family |
| panel.py:1865 | FPS & FRAME RANGE info report | INFORMATIVO-DIFERIDO | same family |
| panel.py:1891 | QuestionDialog "Delete N unused material(s)?" | DECISIÓN | destructive confirm |
| panel.py:1918 | QuestionDialog FPS/range fix preview + confirm | DECISIÓN | destructive confirm, lists every change up front |
| panel.py:1956 | "No cross-aspect safe-area violations." (Select, explanatory) | INFORMATIVO-DIFERIDO | multi-paragraph explanation of why nothing was selected; no compact surface |
| panel.py:1981 | "No objects marked as Safe Area subjects." (Info) | INFORMATIVO-DIFERIDO | same family |
| panel.py:1989 | "No Multi-Format delivery Takes detected." (Info) | INFORMATIVO-DIFERIDO | same family |
| panel.py:2042 | Cross-Aspect full keyframe-sweep report | INFORMATIVO-DIFERIDO | same family as 1728, largest of the group |
| panel.py:2122 | "Redshift module not available." | DECISIÓN | guard/error |
| panel.py:2158 | Full AOV report (active/missing per tier) | INFORMATIVO-DIFERIDO | multi-paragraph, too much for `LABEL_AOV_INFO`; family with 1728 |
| panel.py:2399, 2437, 2443, 2447, 2451 | `_show_delivery_summary` legacy text-dialog family (manifest read error, scan-failed summary, verify confirm, VERIFY LOST, VERIFY OK) | DECISIÓN | intentional fallback path for when the Reports SPA fails to load — kept native **by design** (see CLAUDE.md: "Los diálogos nativos viejos (Doctor/Supervisor) quedan como fallback igual que `_show_delivery_summary`"); not a conversion target, ever |
| panel.py:2462 | "No active document." (Edit Notes guard) | DECISIÓN | guard |
| panel.py:2466 | "Save the scene first before adding notes." | DECISIÓN | prerequisite guard |
| panel.py:2488 | "Failed to save notes file." | DECISIÓN | write failure |
| panel.py:2496 | "No active document." (Save Version guard) | DECISIÓN | guard |
| panel.py:2549 | QuestionDialog "Continue editing in a new WIP version?" | DECISIÓN | real yes/no gate after a TR/CR/FINAL save |
| panel.py:2561 | "Could not create continuation version:\n\n{msg}" | DECISIÓN | error |
| panel.py:2577 | "Save Version failed:\n\n{msg}" | DECISIÓN | error, must notice before retrying |
| panel.py:2595 | "No Redshift render data in this scene." | DECISIÓN | guard |
| panel.py:2612 | QuestionDialog "Switch to Multi-Part EXR / Direct Output?" | DECISIÓN | real yes/no gate, explains compression consequences |
| panel.py:2616 | "Could not change Multi-Part EXR:\n\n{error}" | DECISIÓN | error |
| panel.py:2665 | "No active document." (Open Asset Hub guard) | DECISIÓN | guard |
| panel.py:2680 | "Asset Hub failed to open:\n{e}" | DECISIÓN | error |

### Converted this batch (Task 4)

Every panel.py site Task 3 tagged INFORMATIVO / "Task 4 candidate" — 7 sites,
not 8 (Task 3's totals table undercounted DECISIÓN by one and overcounted
INFORMATIVO by one; corrected below). Re-verified each against the live code
before converting (see rationale column) — no reclassifications, all 7 held up
under review.

| file:line (pre-batch-2) | gist | replaced with |
|---|---|---|
| panel.py:1452 | "Accepted N violation(s) for {row}." (baseline accept) | `safe_print` + `c4d.gui.StatusSetText` — `self._refresh()` runs immediately above and already re-executes all checks, updating the QC row/StatusArea before the message would have shown |
| panel.py:1462 | "Acceptances retired for {row}." | same pattern as 1452, same `self._refresh()` call above it |
| panel.py:1512 | "Already viewing {filename}." (Browse Versions row click on the active doc) | `c4d.gui.StatusSetText` — quick observational notice, matches the pattern already used for `_qc_select_unused_mats` etc. |
| panel.py:1751 | "All assets OK. No absolute paths or missing files." (Assets Info, no issues branch) | `c4d.gui.StatusSetText` — the QC row already shows `[ OK ]` for this check |
| panel.py:2124 | "No AOVs configured.\n\nUse 'Essentials' or 'Production' to add passes." (AOV Info, Redshift available but empty) | `c4d.gui.StatusSetText` — note: Task 3's rationale ("`LABEL_AOV_INFO` could carry this") didn't hold up on re-verification; `_update_aov_info_label` only shows Compositor + Multi-Part status, never an AOV count, so `LABEL_AOV_INFO` isn't actually the right surface — used `StatusSetText` instead |
| panel.py:2284 | "QC Report saved!\n\n{save_path}" | `safe_print` (unchanged, already printed the same path one line above) + `c4d.gui.StatusSetText` — the popup was a verbatim duplicate of what was already printed to console |
| panel.py:2623 | "Multi-Part EXR: ON/OFF — applied to scene." | `safe_print` + `c4d.gui.StatusSetText` — `self._set_active_tab(...)` runs immediately above and already rebuilds `LABEL_AOV_INFO` synchronously with the new state |

**Converted this batch: 7.**

---

## `plugin/sentinel/ui/dialogs.py` (50 sites — classification only, no conversions this batch)

Produced by reading every call site's enclosing dialog/flow (`SaveVersionDialog`,
`BaselineActionDialog`, `GateTriageDialog`, `SentinelSettingsDialog`,
`TextureRepathingDialog`, `AssetHubDialog`, `SentinelDoctorDialog`,
`SupervisorDialog`). Tally: 31 DECISIÓN, 16 INFORMATIVO, 3 INFORMATIVO-DIFERIDO
(corrected during Task 4's totals pass — the original 27/19/4 count was an
arithmetic slip in the batch-1 doc; row-by-row classification below is
unchanged, only the summary tally was off).

| file:line | gist | classification | rationale |
|---|---|---|---|
| dialogs.py:218 | "Comment required" — save blocked, empty comment field | DECISIÓN | validation gate blocking save; user must fix before retrying (`SaveVersionDialog`) |
| dialogs.py:226 | Soft tip: use a "Final Delivery" status tag instead of typing "final" in the comment; save proceeds anyway | INFORMATIVO | non-blocking tip, could append to the nearby preview caption instead of interrupting |
| dialogs.py:325 | "Reason is required" — blocks Accept in baseline triage | DECISIÓN | validation gate before accepting violations |
| dialogs.py:328 | Confirm "Accept these violations?" (+ reason text) | DECISIÓN | real yes/no gate driving the Accept branch |
| dialogs.py:335 | Confirm "Retire all acceptances for {row}?" | DECISIÓN | real yes/no gate driving the Retire branch |
| dialogs.py:600 | "Resolve every blocking FAIL row… overrides require a reason" | DECISIÓN | error the user must notice before proceeding through the QC gate; no inline caption in `GateTriageDialog` (Proceed is merely disabled) |
| dialogs.py:987 | "Could not save settings: {e}" | DECISIÓN | failure user must notice before retrying/losing edits |
| dialogs.py:1323 | "Enter a string in the 'Find' field" | DECISIÓN | validation gate |
| dialogs.py:1359 | "No paths contain '{find}'" | INFORMATIVO | `LBL_SUMMARY` status caption exists and is refreshed right after in the same flow |
| dialogs.py:1369 | "Previewing N change(s)…" | INFORMATIVO | `LBL_SUMMARY`/`LBL_PENDING_COUNT` captions already sit above the list and are refreshed by `_refresh_list`/`_refresh_pending_count` |
| dialogs.py:1378 | "Document must be saved first" (relative-path conversion) | DECISIÓN | prerequisite guard |
| dialogs.py:1408 | "{N} absolute path(s) → relative" | INFORMATIVO | `LBL_SUMMARY` refreshed immediately by `_refresh_list()` right before this call |
| dialogs.py:1414 | "Document must be saved first" (auto-find missing) | DECISIÓN | same prerequisite guard as 1378 |
| dialogs.py:1453 | "Auto-find: N resolved" | INFORMATIVO | `LBL_SUMMARY` caption refreshed just before |
| dialogs.py:1459 | Confirm "Discard N pending change(s)?" | DECISIÓN | real yes/no gate before discarding staged edits |
| dialogs.py:1501 | "No pending changes to apply" | DECISIÓN | "do something first" guard |
| dialogs.py:1505 | Confirm "Apply N change(s) to the scene?" | DECISIÓN | real yes/no gate before committing a scene-mutating batch |
| dialogs.py:1550 | "Applied X of Y change(s)" | INFORMATIVO | `LBL_SUMMARY`/`LBL_PENDING_COUNT` refreshed by the rescan that follows |
| dialogs.py:2111 | "Select an asset row first" | DECISIÓN | "select something first" guard |
| dialogs.py:2115 | Same guard, record lookup returned None | DECISIÓN | same as 2111 |
| dialogs.py:2118 | "This asset is read-only — cannot be relinked" | DECISIÓN | error, must notice before retrying with a different row |
| dialogs.py:2131 | "Enter a string in the 'Find' field" (AssetHub) | DECISIÓN | validation gate, same pattern as 1323 |
| dialogs.py:2155 | "No repathable paths contain '{find}'" | INFORMATIVO | `LBL_PENDING` refreshed via `_push_state()` just before |
| dialogs.py:2162 | "Document must be saved first" (make-all-relative) | DECISIÓN | prerequisite guard, same as 1378 |
| dialogs.py:2197 | "{N} absolute path(s) → relative" | INFORMATIVO | `LBL_PENDING` refreshed by `_push_state()` immediately prior |
| dialogs.py:2222 | "Matched N missing asset(s)" | INFORMATIVO | `LBL_PENDING` refreshed by `_push_state()` right after |
| dialogs.py:2227 | "No pending changes to apply" (AssetHub) | DECISIÓN | "do something first" guard, same as 1501 |
| dialogs.py:2230 | Confirm "Apply N change(s) to the scene?" | DECISIÓN | real yes/no gate, same as 1505 |
| dialogs.py:2277 | "Applied X of Y change(s)" | INFORMATIVO | `LBL_PENDING` exists, rescan follows via `self._rescan()` |
| dialogs.py:2338 | "No auto-fixable issues found" | INFORMATIVO | preflight strip (`preflight_ua`) sits right above, already summarizes pass/fail |
| dialogs.py:2342 | "Auto-fixed N issue(s) across M check(s)" | INFORMATIVO | `preflight_ua` refreshed immediately after via `_refresh_preflight()` |
| dialogs.py:2387 | "No failing checks to accept" | INFORMATIVO | `preflight_ua` already shows the all-clear state |
| dialogs.py:2393 | "Save the scene first" (baseline sidecar path is derived from file location) | DECISIÓN | prerequisite guard |
| dialogs.py:2432 | "Baseline updated for N check(s), M violation(s) accepted" | INFORMATIVO | `preflight_ua` refreshed right after via `_refresh_preflight()` |
| dialogs.py:2448 | "Run a pre-flight scan first" | DECISIÓN | prerequisite guard |
| dialogs.py:2468 | Full per-check violation breakdown ("Show Details") | INFORMATIVO-DIFERIDO | this dialog IS the detail view — variable-length, per-check, per-violation list too large for any caption/strip |
| dialogs.py:2548 | "Please save the scene first before collecting" | DECISIÓN | prerequisite guard |
| dialogs.py:2554 | "Choose a delivery folder first" | DECISIÓN | prerequisite guard |
| dialogs.py:2561 | Confirm "N pending repathing changes are NOT applied and won't be in the package. Continue?" | DECISIÓN | real yes/no gate protecting against silent data loss |
| dialogs.py:2575 | Confirm "N missing asset(s) will NOT be in the package… Continue?" | DECISIÓN | real yes/no gate warning of an incomplete delivery |
| dialogs.py:2595 | "Collect failed — see console" | DECISIÓN | failure, must notice before retrying |
| dialogs.py:2621 | Collect summary ending "Open delivery folder?" | DECISIÓN | `QuestionDialog` used as a genuine branch (open Finder/Explorer or not) |
| dialogs.py:2729 | "Diagnostic copied to clipboard" | INFORMATIVO-DIFERIDO | `SentinelDoctorDialog` has no status caption near the Copy button, only the read-only report field |
| dialogs.py:2732 | "Could not copy to clipboard — select the text manually" | DECISIÓN | failure with an actionable fallback instruction, must notice |
| dialogs.py:2746 | Update-check result (detail + hint) | INFORMATIVO | redundant — same detail/hint already rendered into the item-row list via `_build_item_rows()` right before |
| dialogs.py:2829 | "Could not scan the folder: {exc}" | DECISIÓN | failure, must notice before retrying |
| dialogs.py:2834 | "No scene sidecars found in this folder" | INFORMATIVO | `TXT_REPORT` field already updated via `_report_text()` immediately before, would show the same empty state |
| dialogs.py:2854 | "Scan a folder first, then export" | DECISIÓN | prerequisite guard |
| dialogs.py:2875 | "Could not write the HTML export: {exc}" | DECISIÓN | failure, must notice before retrying |
| dialogs.py:2881 | "Supervisor report exported:\n\n{written}" | INFORMATIVO-DIFERIDO | no existing caption displays export destination (`LABEL_FOLDER` is dedicated to the scanned folder, not the export path) |

---

## Totals

Updated after Task 4 (batch 2). "Sites" = call sites inventoried in that file
as of the batch that touched it (flows.py/panel.py rows reflect their own
batch's before-state; dialogs.py is untouched since batch 1). "DECISIÓN"
includes the flows.py dead-code count parenthetically since those sites still
exist as live `MessageDialog` calls in unreachable code. Corrected two
arithmetic slips from the batch-1 version of this table: panel.py's
INFORMATIVO count was 7 (not 8), and dialogs.py's DECISIÓN/INFORMATIVO/DIFERIDO
split was 31/16/3 (not 27/19/4) — see the dialogs.py section note above.

| File | Sites | DECISIÓN | INFORMATIVO (remaining) | INFORMATIVO-DIFERIDO | Converted this batch | Converted (cumulative) |
|---|---|---|---|---|---|---|
| flows.py | 14 | 12 (7 + 5 dead-code) | 0 | 0 | 0 | **2** |
| panel.py | 44 (+2 new fallbacks from batch 1) | 28 | 0 | 9 | **7** | **10** (3 batch 1 + 7 batch 2) |
| dialogs.py | 50 | 31 | 16 | 3 | 0 | 0 |
| **Total** | **108** | 71 | 16 | 12 | **7** | **12** |

Panel.py's INFORMATIVO backlog is now zero — every site Task 3 flagged as a
Task 4 candidate was re-verified and converted (see "Converted this batch
(Task 4)" table above; no reclassifications, all 7 held up). What remains in
panel.py is DECISIÓN (kept, by design) and INFORMATIVO-DIFERIDO. dialogs.py's
16 INFORMATIVO sites are still open — explicit scope for a future batch, not
touched here. INFORMATIVO-DIFERIDO items need a toast/notification surface
that doesn't exist yet (Phase 4 of the plan) and are not candidates for
caption conversion regardless of batch.
