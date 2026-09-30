# Sentinel beta acceptance — 2026-09-05

Baseline: stabilization commit `dc52ed4`. Branch: `codex/product-readiness`.
This is a local candidate and acceptance record, not a published release or cross-platform certification. The subsequent [installed GUI acceptance](2026-09-05-gui-acceptance.md) records the completed macOS flows, two further corrections and remaining usability follow-ups.

## Candidate and recovery

`build_candidate.py` packages committed source, not dirty working-tree files. The archive contains `install.py`, `INSTALLATION_README.md`, `plugin/`, and `SENTINEL_CANDIDATE.json` recording commit/build identity and each content file's SHA256 and size. Archive paths, hashes, extracted files and the shared payload verifier are checked before the output is activated. Outputs live under ignored `dist/`.

Installation now stages a complete, integrity-checked payload before replacing Sentinel. Successful updates retain the previous installation in a timestamped record under `Sentinel Backups/`, beside the preference folder's `plugins/` directory. Rollback validates the original record, so old versions lacking today's license/notice files remain restorable. Both update and rollback preserve a recoverable payload on activation failure and report its exact location. The installer requires the target C4D to be closed; it does not attempt unreliable process detection across platforms. Backup retention is explicit; no old backup is automatically deleted.

Verified update→rollback with a temporary copy of the actual installed plugin. Its original deployable file manifest matched after restoration; the running GUI installation was not modified. Failure-injection tests cover staging, corruption, activation, restoration, and tampered backups. Independent review caught a CLI recovery-path omission; its regression failed before correction and passed afterward.

## Bugs found during actual host acceptance

- **AOVs:** the Essentials action added 11 AOVs, but one Undo did not restore the previous list. `force_aov_tier` now captures the VideoPost before changing globals/AOVs and closes its undo transaction on error. A real-host prototype proved the correction before implementation.
- **Frame:** after generating Takes, one Undo removed the preexisting Frame tag from the camera. This also reproduced through the normal add-tag core. Capturing the owning camera before the Take operations preserves the tag and its settings through Undo. The acceptance checks also retain another camera tag and successfully regenerate afterward. Several alternative explanations were experimentally rejected; they were not patched into production.
- **Acceptance harness:** Variants can insert a parked container ahead of the anchor. The new runner originally assumed the first root was the anchor; it now reacquires the named anchor. The switch/Undo and save/load assertions remain intact.

## Verification evidence

Integrated source tested: `8df459eb7d013daae180ec49a85f54869a78c6bb`.

| Verification | Result |
|---|---|
| `python3 -m pytest -q` | **1,775 passed** in 24.57 s |
| `npm test` in `web/` | **247 passed**, 15 test files |
| `npm run lint` | Passed |
| `npm run build` | Passed; `git diff --exit-code -- ../plugin/web` confirms bundled output is unchanged |
| Fresh C4D 2026.304 `run_beta_checks.py` | Exit 0; all six check groups passed |
| Actual installed-payload copy → update → rollback | Original file manifest restored exactly |

The host loaded the built ZIP through a fresh isolated installation, not the working-tree Python sources. Frame retained both its own tag and an existing Protection tag after one Undo, kept its formats/style and regenerated Takes. Redshift Essentials added 11 AOVs and restored the original collection with one Undo. Variants reloaded both options with resolved links and zero orphans. EXR conversion produced a 128×64 PNG with increasing sampled levels of 0, 214 and 247.

Independent final review found no actionable bugs in the installer/candidate changes, Frame and AOV corrections, host runner or integration. The reviewer inspected the actual host JSON and retained the GUI/Windows limitations below.

The final ZIP and adjacent `.sha256`/acceptance JSON are local artifacts under `dist/`. The final build checks that all shipped content hashes match this tested candidate; later acceptance-documentation commits do not change its payload. The ZIP manifest records its exact source commit. A digest is kept beside the archive rather than inside the source commit it identifies.

`tests/c4d_runner/run_beta_checks.py` uses a candidate loaded normally by C4D's plugin loader. It does not reload or purge a running Sentinel package. Run it only in a fresh `c4dpy` process with `-g_console=true`, `-g_additionalModulePath=<isolated plugins folder>`, and the script's absolute path. `SENTINEL_ACCEPTANCE_OUTPUT` optionally names a JSON evidence file. The runner refuses execution in the GUI Script Manager and cleans up its disposable documents and files.

Host coverage:

- C4D 2026.304 on macOS, with the actual Frame/Pin/Variants registrations loaded.
- EXR Watch: a real HDR EXR gradient generated by OpenEXR passes through the detected system Python and external ACES converter into a valid PNG. Settle, exactly-once processing and output pixel progression are checked. This is a generated acceptance asset, not a RenderView capture from a production scene.
- Pin: capture/restore, safety tag coexistence and one-step Undo.
- Variants: two objects retain world positions; duplicate/switch/Undo and saved-scene reload retain both options and their links.
- Frame: generate Takes, Undo without losing the Frame or another camera tag, preserve enabled formats/style and regenerate.
- AOV Essentials: add and undo the actual Redshift AOV collection.
- Existing product operations reused without the fixture loader: Standard/OpenPBR material QC/fix/Undo, real SaveProject/rescan/manifest including negative paths, and Notes scene/revision/UTF-8 guards.

## Remaining acceptance gates

| Gate | Current evidence / next action |
|---|---|
| Embedded C4D webview | Completed scoped installed-GUI acceptance after user-approved restart; see the follow-up record for Notes, Hub, Settings results and the remaining focus/settings-refresh limitations. |
| RenderView snapshot capture | Completed in the subsequent GUI run: actual Redshift RenderView capture, persisted-directory auto-detection, exactly-once PNG conversion and off/on backlog protection. |
| Windows/C4D | Run on 2026-09-24 against this candidate: no global acceptance (Collect replaced an existing delivery), plus a stale Hub thumbnail and a misleading installer listing. All three corrected on `fix/windows-acceptance` and live-verified on macOS; a Windows retest is pending. See the [Windows acceptance record](2026-09-24-windows-acceptance.md). |
| Network paths and interruption | Failure injection is covered locally; SMB/NAS permission/locking and interruption under real Windows remain unverified. |
| Commercial launch | Ownership/third-party redistribution, registered IDs and the support matrix remain as recorded in the preceding product-readiness audit. No permission or commercial compatibility is inferred. |

## Windows / GUI checklist

Use disposable scenes and keep a copy of the previous install. Record Windows/macOS, C4D and Redshift versions, candidate commit and ZIP digest with every result.

1. Close C4D. Install the extracted candidate using `python install.py --target "<preferences>/plugins"`. Record the printed backup path. Reopen C4D; confirm panel and all three tags load.
2. Open scene A and B. Edit Notes in A, switch to B and submit: B must remain untouched and the draft recoverable. Verify accented notes, shared version bases and rejection after an external sidecar edit.
3. Change documents repeatedly with Panel and Hub open. Confirm scene identity, metadata and resolution alternatives refresh, including an asset replaced at the same path.
4. Run material QC on a generic-name sRGB normal feeding Bump→Standard/OpenPBR. Fix to RAW and undo once. Unreadable material coverage must remain unverified.
5. Collect a saved scene into an empty delivery folder. Reopen the result and inspect matching manifest identity. An occupied output must not overwrite the existing scene; a failed manifest write must not report completion.
6. Enable Snapshot Watch, then capture a new RenderView EXR. Existing backlog stays ignored; the new stable file converts once and the UI remains responsive. Test off/on and a changed source folder.
7. Create Frame, Pin and Variants states, change them and Undo/Redo. Check camera tags, option links and saved-scene reload. Add AOV Essentials and undo once.
8. Close C4D. Run `python install.py --target "<preferences>/plugins" --rollback latest`. Reopen and confirm the previous plugin loads and the scene remains intact. Preserve any failure logs and the exact recovery path; do not delete backup records as a recovery step.

The isolated-preference exploration used Maxon's documented `g_prefspath`/`g_additionalModulePath` options ([Maxon configuration reference](https://help.maxon.net/c4d/en-us/Content/html/11083.html)). A fresh preference profile required license selection; testing instead used the already licensed c4dpy profile with an isolated plugin path. No account or license configuration was changed.
