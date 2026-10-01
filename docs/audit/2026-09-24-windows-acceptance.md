# Sentinel Windows acceptance — 2026-09-24

Follow-up to [beta acceptance](2026-09-05-beta-acceptance.md), which left Windows as an open gate. This record summarizes an external acceptance run on Windows and the corrections made afterwards on branch `fix/windows-acceptance`. The full report and its evidence folder live outside the repository (`aceptacion-sentinel-windows.md` + `evidencias/`, on the tester's share); they are not copied here because the evidence links are relative to that folder.

## Tested candidate and environment

- Candidate `323049e81e1e` (Sentinel 1.38.0, build `323049e81e1e-20260905T144727Z`). ZIP SHA256 matched its `.sha256`; 122/122 extracted files and 120/120 installed files matched the candidate manifest, audited inside the running C4D process.
- Windows 11 Pro 25H2 (build 26200.9278), Cinema 4D 2026.3.4 (`2026304`), Redshift core 2026.8.0.0, embedded Python 3.11.4.
- Tests ran 2026-09-07 → 2026-09-24. Panel, Doctor, Settings, Notes, Hub, Collect and RenderView/Watch were driven through the real interface; Pin, Variants, AOV and the Frame autosync ran the original functions on real documents via Script Manager (engine-level, not every visual control).

## Result

No global acceptance: one confirmed plugin defect. Everything else passed or was blocked by the environment, not by Sentinel.

| Area | Result |
|---|---|
| Package integrity, startup, Panel, Doctor, Frame/Pin/Variants registration | PASS |
| Settings (empty/accented Artist Name, persistence across restart) | PASS |
| Notes (A→B→A draft guard, external concurrent edit) | PASS |
| Frame Takes + one Undo keeping tag and settings (autosync path) | PASS |
| Pin capture/restore/Undo, Variants duplicate/switch/save/reopen, AOV Essentials + one Undo | PASS |
| Snapshot Watch: folder detection, real RenderView EXR → exactly one PNG, no backlog reprocessing | PASS |
| Collect into a fresh folder + reopen | PASS |
| **Collect into an occupied folder** | **FAIL** — see P1 |
| Hub texture replaced at the same path + Refresh | Metadata PASS, thumbnail stale — see P2 |
| `install.py --list` / `--target` from the agent's restricted process | FAIL under access-denied AppData (environment); `--list` hid the cause — see P2 |
| Hub rapid A/B switching, rollback, NAS/SMB | PENDING (coverage / no resource) |

Two unexpected C4D exits were recorded without evidence against Sentinel (no Application event, `_bugreports` unreadable; the second followed a launch from the restricted shell). The user-launched session stayed stable through a real render and snapshot.

## Findings and corrections

**P1 — Collect replaced an existing delivery.** Delivering again into the same folder replaced the first delivery's `sentinel_manifest.json` and left a second scene (`Entrega á B.c4d`) next to the first. Cause: `hub/collect_start` never checked the target; the candidate's pipeline only refused the folder-named scene collision, so with the clean name occupied it still delivered on top. Not Windows-specific. Fix: `hub/collect_start` refuses a target that exists and holds anything besides OS folder junk (`.DS_Store`, `desktop.ini`, `Thumbs.db`) with `target_not_empty`, before the QC pre-flight and without writing; the SPA stays on the form with an actionable warn toast instead of an error screen whose Retry could never succeed.

**P2 — Hub thumbnail stale after Refresh.** The server's disk cache was already keyed by mtime; the webview reused its HTTP cache because `/thumb?key=` never changed and is served with `max-age=300`. Fix: `stat_sizes_batch` records `mtime`, the inventory publishes `thumb_version` (mtime-size) and the SPA puts it in the URL (`&v=`).

**P2 — installer diagnosis.** `discover_c4d_installs` swallowed every `OSError`, so access denied on `AppData\Maxon` printed "No Cinema 4D installations found". Fix: a missing root stays quiet; an unreadable one is named with its reason and the `--target` way out, `--list` exits 1, and `--all` refuses instead of installing into zero targets. Whether the installer works in a normal Windows session is still unverified.

**Frame direct-helper observation — closed, not a defect.** The tag loss came from calling `_run_takes_generation` inside a transaction opened by the tester. Its only other caller, the legacy create-takes handler, answers button id 3001, which is no longer in the tag description since v1.28, so the artist cannot reach it.

## Verification of the corrections

- Tests failed first for the expected reason; mutations (junk filter removed, guard disabled, existence check inverted, version by size only, no mtime capture, URL without version, error swallowed again, `--list`/`--all` ignoring errors, missing root treated as error) each broke at least one test.
- On the candidate base: pytest 1790 passed, vitest 253 passed, `tsc` clean, committed bundle rebuilt (single referenced asset).
- Live, 2026-09-30, macOS, C4D 2026.304, branch synced and C4D restarted, driven through the real Hub interface with the report's accented QA names:
  - Texture replaced at the same path (red 64×64 → green 96×48) + Refresh: thumbnail turned green together with the metadata (96×48, 205 B).
  - First Collect into a new `Entrega á B`: delivered. Deliver Again into the same folder: refused with the warn toast, form kept; SHA256 of `B.c4d`, `sentinel_manifest.json` and `tex/textura B.png` identical before and after, no file added.
  - Collect into a fresh folder holding only `.DS_Store`: delivered normally.

## Automated test suite on Windows — 2026-09-30

`.github/workflows/verify.yml` runs pytest on `windows-latest` alongside ubuntu and macOS (GitHub-hosted runner, Python 3.11, only `pytest` installed).

- **First run** (PR #14, run 36717060800): 16 failed, 1762 passed. The failures predated that PR and had one cause: path separators.
- **Fixed in PR #15** (merged `bff726e`). Each case was classified before touching anything:
  - *Production wrong — 10 tests, fixed in code.* Each function produced a path with mixed separators on Windows. `assets.find_res_variants` normalized to `/` (as its docstring promises) and then joined with `os.path.join`, which adds `\` on Windows; it now joins with `posixpath.join`. Shader data was never affected, because `hub/switch_res` only takes the basename from that path. `postrender.report_path_for_doc` and `_render_history_target` normalized *local* paths to `/` before joining, so the report path shown in the Validate dialog read `C:/shots\x_sentinel_render_report.json`; they now keep the native form. The deliberate `/` normalization of render paths from another OS in the manifest is unchanged. `variant_tag._render_output_folder` returned `$prj` (native) + what the artist typed (`/images`) as-is, and that folder appears in the tag's report row; it now goes through `os.path.normpath`.
  - *Test wrong — 6 tests, fixed in the tests (approved before editing).* Production was correct and the test hardcoded POSIX or expected the raw path. `get_baseline_path` and `render_history_path` join natively, like the other sidecars. `resolve_output_template` and the manifest `folder` are `/` by design. `payload.verify_payload` reports canonical `/` ids. The collect job's `document_path` is a `normcase`+`abspath` identity key on both sides.
- **Result:** run 36718693740 (PR #15) and run 36719298189 (PR #16) — all four jobs green; Windows **1778 passed, 1 skipped, 0 failed**. The one skip is `tests/test_slate.py`, which needs numpy and Pillow; CI does not install them, and it skips on macOS and Linux the same way.

This is unit-test coverage on a Windows runner, not host acceptance: no Cinema 4D runs there, so it says nothing about the plugin inside C4D on Windows. The retest below still closes this record.

## Round 2 — 2026-09-30

Second external run on the same machine (report `aceptacion-sentinel-windows-ronda2.md`; its evidence folder was not shared with this record). Candidate `5c32d9c07bf7` (build `5c32d9c07bf7-20260930T131907Z`); ZIP SHA256 matched, 122/122 package files and 120/120 installed files verified, also inside the running C4D process. Windows 11 Pro 25H2 build 26200.9457, C4D 2026.3.4, Redshift DLL 2026.9.0.0 (updated since round 1).

**Verdict: no global acceptance**, because the full UI runs of the Frame inspection and Hub Switch res ended in C4D crashes. No functional regression was found, and every round-1 finding is closed.

| Area | Result |
|---|---|
| Install from a normal session: `--list`, `--target` with a real backup of `323049e`, loaded identity | PASS |
| Rollback to `323049e` and reinstall of `5c32d9c`, both verified inside C4D | PASS |
| Collect into an occupied folder (round-1 P1): warning, form kept, hashes identical, no new file | PASS |
| Collect into folders holding only `desktop.ini` / only `Thumbs.db`; reopen of the delivery | PASS |
| Hub thumbnail after same-path replacement + Refresh | PASS |
| Validate Render Output on a real 3-frame sequence: report path only with `\` | PASS |
| Variants render-all with `$prj/images`: two PNGs, starting option kept, folder with `\` (the report goes to the status bar; the retest list wrongly said "tag row") | PASS |
| Notes and Collect on a real UNC share (`\\deepspace9.local\home`, spaces and accents) | PASS (engine/handlers inside C4D; the visual draft on UNC not covered) |
| Real RenderView EXR → exactly one PNG, no backlog reprocessing on off/on | PASS, with the external Python exposed only to the C4D process |
| Regression: Panel, Doctor, Settings with accents across restart, Notes A→B→A + external edit, Frame Takes + one Undo, Pin, Variants save/reopen, AOV one Undo | PASS (Pin/Variants/AOV/Frame through their engines, not every button) |
| Hub Switch res, full UI | FAIL — C4D crashed when selecting the 2k row, before pressing Switch res. The handler alone passed 2k→4k, `ok`, save/reopen and one Undo |
| Frame tag inspection, full UI | FAIL — C4D crashed when expanding MAIN in the Attribute Manager |
| Doctor with the external Python on PATH | FAIL — plugin defect, see below |
| EXR conversion on a normal startup | PENDING — no suitable external Python is discoverable (environment) |

**Crashes — open, not attributed.** Both are `ACCESS_VIOLATION 0xC0000005` at address `0x0` with the first stack frame in `gui.module.xdl64` (16:09:28 expanding MAIN on the Frame tag; 16:55:14 clicking a row in the Hub webview). The report classifies them as C4D/environment on the user's statement; the cause was not isolated and other plugins were loaded. Round 1 also had an unexplained exit during Frame inspection, so three exits across two rounds happened while a Sentinel UI was in use — a pattern that neither proves nor rules out Sentinel. Evidence needed: the two `_BugReport.txt` texts, and the same two actions repeated with only Sentinel installed.

*Crash report analysis (2026-10-01, from the full evidence folder):*
- Both reports have the **same faulting stack, offset for offset**: on the main thread, during window-message processing, `gui.module.xdl64` calls through a null function pointer (`rip = 0`). There is **no `python311.dll` frame** on that thread, so no Sentinel Python code was executing at the moment of the fault. Two different actions (expanding a tag in the Attribute Manager, clicking a row in the Hub webview) end at one identical native site.
- Both happened **1–3 s after the tester's automated controller captured the window and clicked**: the screenshot before the Frame crash was written at 16:09:27, the crash at 16:09:28.39; the Hub screenshot at 16:55:12, the crash at 16:55:14.77. The C4D Python process had `_ctypes.pyd` loaded, which Sentinel does not use (no `ctypes` anywhere in `plugin/`), so other code ran inside C4D's Python during the session. The sessions were heavy: 7 and 16 open documents (several duplicates), about 10.6 GB in use. Arnold (C4DtoA) and Octane 1.9.5 were also loaded.
- The Critical_Log holds thousands of `CRITICAL: Stop [ge_container.h(523)]` (plus `ge_container.h(602)` and `basecontainer.cpp(353)`) in bursts of roughly 440/920/1800 that line up with scene-scanning actions (Collect, the scripted native phases, Variants render, Hub). **Measured live on macOS (C4D 2026.304, 2026-10-01, C4D stdout captured): Sentinel produces them.** With a one-cube scene open and the panel closed: 0. Opening the panel: 928 (882 × 523, 36 × 602, 10 × 353), the same burst size as on Windows. Sources: `textures.py` and `checks/scene.py` iterated every `(id, value)` of material/object/tag/shader containers and called `GetFilename` / `GetLink` on every id whatever its type (the 523/602 stops); and the texture scan read `obj[root, REDSHIFT_FILE_PATH]` for the five RS file refs on every object, Redshift or not (the 353 stops, 5 per object per scan). Fixed on `fix/doctor-python-on-path`: the scans walk only the ids of the requested type (`GetIndexId`/`GetType`), and the RS refs are read only when the object's container has that root. After the fix: 0 stops with panel, QC and Hub, also on a scene with a Redshift dome light whose HDR is still detected (two owners, as before). The stops are assertions C4D logs and continues past; nothing links them to the null call.
- The same live run showed every Sentinel dialog `Timer` returning `True`, which C4D 2026.304 rejects with `TypeError: Timer expected None, not bool` on every 25 ms tick (1410 tracebacks within seconds). Also fixed (0 after). Neither defect explains a null function call in `gui.module`, but both added constant work and console noise to the sessions that crashed.
- Reading: the crash evidence does not point at Sentinel, and the timing points at the UI automation in a long, heavy session. To close it, repeat both actions **by hand** in a fresh C4D session with few documents, on a candidate with these fixes; if they pass, the crashes are not a Sentinel defect.

**Doctor false warning — fixed.** Windows discovery returns the bare name `python` when the interpreter comes from PATH, and the converter's subprocess resolves it, but `doctor.build_python_item` tested `os.path.exists("python")` and warned that no Python was found while conversion worked. Doctor now resolves a bare name with `shutil.which` and shows the real path; an absolute path that no longer exists still warns. Tests failed first; mutations (no PATH resolution, accepting a path without checking it exists) each broke a test; full suite 1793 passed.

## Remaining for a Windows retest

On a candidate that includes the Doctor fix:

1. Doctor with the external Python on PATH reports it as found, with its resolved path.
2. With only Sentinel as a third-party plugin: expand MAIN on a Sentinel Frame tag, and select a row in the Hub and run Switch res between two resolution variants (relinked to the right file, `ok`, one Undo). Keep `_bugreports` text for any exit. If both pass, repeat with the usual plugins loaded to see whether another plugin is involved.
3. Make a suitable external Python (OpenEXR, numpy, Pillow) discoverable at a normal C4D startup (on PATH as `python`/`python3`, or in one of the install locations Sentinel searches), then confirm Doctor and a real EXR snapshot conversion without any process-level PATH change.
