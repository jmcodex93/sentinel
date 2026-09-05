# Sentinel embedded GUI acceptance — 2026-09-05

Follow-up to [beta acceptance](2026-09-05-beta-acceptance.md). The user explicitly authorized closing C4D, installing the candidate and reopening the saved scene copy. This record covers the installed macOS/C4D GUI, not Windows certification.

## Installation and preserved work

The original GUI was already closed when this session resumed. The saved `Untitled-1-before-beta.c4d` copy was reopened successfully after installing candidate `5f4d978dfe62`. The installed deployable file manifest matched the archive exactly. Previous Sentinel was retained under the C4D preference folder's `Sentinel Backups/backup-20260905T142208428701Z-809f8229` record. All mutations for acceptance were made in separate `Beta_A.c4d` and `Beta_B.c4d` documents under the ignored acceptance scratch folder.

Doctor in the actual embedded HTML viewer passed payload, Redshift, external Python, preference folder and scene folder checks. The initially absent Sentinel settings file was reported neutrally.

## Embedded interface evidence

- Notes opened for A retained a Unicode draft after switching to B. Save displayed the scene-changed error and did not create a notes sidecar in B. Returning to A allowed save; the UTF-8 sidecar contained the exact accented text.
- Editing A's notes sidecar externally caused the still-open form to reject its stale save and preserve the draft. The external text remained on disk.
- Hub read B's texture and updated its metadata after replacing the file at the same path: 1,754→902 bytes and the new sRGB profile appeared after Refresh.
- Five rapid A/B transitions settled the inventory on A with zero assets. This exposed a separate defect: the delivery preflight retained B's QC score and Materials fix until manual Refresh. The inventory was current; the preflight component fetched only on mount. Commit `fe091b7` now refreshes the preflight and fix availability with each accepted inventory revision and ignores older responses. After reinstall/restart, the same rapid transitions showed A's own QC 9/13 (A now contained the render fixture), removed B's Materials fix and retained the delivery target and ZIP checkbox. Independent review found no actionable issues.

## RenderView evidence

Redshift rendered a disposable cube scene at 320×180. RenderView's own Take Snapshot produced a 68,552-byte EXR in the temporary acceptance folder. Closing only RenderView did not persist its new snapshot directory. A full C4D quit wrote the new `snapshotDir` to `prefs/redshift_rv.cfg`; Sentinel's automatic discovery reads that persisted configuration. No real-time observation of unsaved RenderView preferences is claimed.

The installed panel reported the persisted path as **auto-detected**. Watch ignored the existing EXR backlog. A new RenderView snapshot passed through the actual system-Python converter to exactly one readable `Beta_A_snap_001.png` at 320×180, with non-flat rendered pixel values (0–173). The panel reported `converted Beta_A_snap_001.png`; the host status was `ready` with no error.

This uncovered another fresh-install blocker: Watch correctly requires an artist name, but Settings no longer exposed that existing setting. The earlier native panel's artist control had been retired. A temporary `Sentinel QA` value was used to isolate and verify the converter; restoring the user-facing Settings field and exercising its save/read behavior is the final correction below.

## Final verification

Installed and tested source: `19b8ad57cb428f412be763b871df4d2fffac73d4`. The installed file manifest matches that candidate exactly.

The restored Artist Name control passed the real embedded GUI lifecycle: initially blank, save `  Aceptación Ñ  `, confirm trimmed UTF-8 value on disk, close/reopen Settings and read the same value, then explicitly clear and save. The native fallback also exposes the field; its new control was source-reviewed, not separately exercised in this GUI run. Older/malformed submit values preserve the existing artist in backend regression tests. Both scoped fixes received independent review with no actionable findings.

| Check | Result |
|---|---|
| Full `python3 -m pytest -q` | **1,781 passed** in 23.50 s |
| Full Vitest | **249 passed**, 17 files |
| `npm run lint` | Passed |
| TypeScript/Vite build | Passed |
| Post-commit build → `git diff --exit-code -- ../plugin/web` | Passed; bundled output unchanged |
| Actual installed candidate file manifest | Matches |
| Embedded Notes / Hub / Settings checks above | Passed |
| Actual RenderView EXR → watched PNG / off-on without duplicates | Passed |

Cleanup: both disposable scenes closed without unsaved changes. RenderView's pre-test configuration was restored byte-for-byte. Watch is off, the test artist has been cleared, and the original scene copy is the only open document. Its Camera, Main take, My Render Setting, 30 fps and 0–90 frame range are unchanged. The panel was reopened after cleanup and no longer displays the test artist.

## Remaining usability follow-ups

- An already-open floating Settings window can stay behind Panel when Settings is requested again. `reports_dialog.open_form` safely reuses the instance but does not raise it. Closing Panel exposed the existing form with its state intact. Any focus correction must preserve the existing protection against closing/recreating a live HTML viewer in the same tick.
- With Watch off, Overview's artist label did not immediately refresh after changing Settings; reopening Panel displayed the persisted value. The setting itself saved and reopened correctly. Global-settings-driven panel refresh is a separate follow-up.

These limits are recorded rather than claiming every possible embedded-window interaction passed.

Windows/C4D, SMB/NAS behavior and the commercial launch prerequisites remain outside this macOS result.
