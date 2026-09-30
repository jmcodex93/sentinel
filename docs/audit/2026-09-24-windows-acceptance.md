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

## Remaining for a Windows retest

Repeat on a new candidate built from `main` (it now includes `fix/windows-acceptance` and the separator fixes above): Collect into an occupied folder, thumbnail after same-path replacement, clean install and `--list` from a normal user session, a UNC/SMB path with spaces and accents, the Frame tag inspection keeping the `_bugreports` text if C4D exits, and rollback when a genuine previous backup exists. The three production paths changed by the separator fix have only been exercised by unit tests, so check them inside C4D too: the report path shown by Validate Render Output after a validation (native `\` form, no mixed separators), the output folder in a Sentinel Variants tag's report row after rendering all options with a render path such as `$prj/images`, and Hub Switch res between two resolution variants of a texture (the shader is relinked to the right file and the scene still resolves it). The external Python with OpenEXR/numpy/Pillow must be discoverable at C4D startup; the run only proved it by prepending a venv to the process `PATH`.
