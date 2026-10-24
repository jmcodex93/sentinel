# Sentinel macOS acceptance — round 1 (2026-10-24)

The macOS counterpart of the Windows rounds in
[`2026-09-24-windows-acceptance.md`](2026-09-24-windows-acceptance.md). The run
used candidate `cf3355b` (v1.40.0 plus PR #30 follow-ups, #31 QC #13 data
channels and #32 Matwire displacement range), run by the agent on the
developer's Mac. Evidence (EXR snapshots, RenderView exports, stills,
ruleset) was kept in the session scratchpad and is not copied here.

## Environment

- macOS (Darwin 25.6.0, arm64), Cinema 4D 2026.3 (`2026304`), Redshift for C4D 2026.
- The user ruled on 2026-10-23 that 2026.3 and 2026.4 count the same for acceptance.
- Candidate `sentinel-beta-cf3355b64a6d.zip`, SHA256
  `b9331acb988d3acb9930d90ddf6245da54d7f6ba37c65e707c255a4ad8d4fd4d`, 129 files.
- **Host checks in `c4dpy`:** the candidate was installed with `install.py` into an isolated plugins folder and loaded through `-g_additionalModulePath`.
- **GUI round:** the candidate was installed with `install.py` into the regular profile, which kept a backup of the previous payload.
  - That profile also loads the studio's usual plugins: Octane, Greyscalegorilla, Redshift SMC, KitBash Cargo, MFX, Forester and others. This round therefore also covers the "usual plugins" pass that was waived on Windows.
  - A fresh preference profile is not usable for an unattended run on this Mac, because it asks for a licence choice.

## Host checks (`c4dpy`)

| Runner | Result |
|---|---|
| `run_beta_checks.py` (candidate payload) | PASS: exr_watch, pin_restore, variant_roundtrip, frame_sync, aov_undo, core_workflow |
| `run_fixtures.py` | PASS: 2 fixtures match the frozen oracle. Exit code 1 is `c4dpy` turning `SystemExit(0)` into 1 on this host; a bare `raise SystemExit(0)` gives 1 too. |
| `run_product_checks.py` | PASS, including "generic normal, RAW fix and one-step undo" (#31) and "Matwire displacement remap via ops" (#32) |

## GUI round

| Item | Result |
|---|---|
| Doctor | OK. Sentinel 1.40.0, C4D 2026304, "Built in", "Inter (bundled)", no known-issue item. The OS row reads "Darwin 25.6.0 (arm64)", the kernel name rather than the macOS version. |
| Stills path | OK. `→ ACME/output/stills/Javier m/261024` for `ACME/c4d/_Shots/shot_v001.c4d`. |
| Real RenderView snapshot → Save Still | OK. RGBA PNG; alpha within 1 level of the EXR; colour within 1 level of the OCIO view. |
| LUT from Redshift's own library | **FAIL → fixed in PR #33.** The notice said "LUT Filmic High Contrast not found": RenderView lists `.cube` files in LUT Location's subfolders and records only the name. |
| Master curve + green curve | The notice said "order unmeasured", as designed. The pair measured the order: **channel curve first, then master** (green 0.53 levels, max 3; master-first fails 82 % of the pixels). Implemented in PR #33. |
| Saturation / exposure notes | None. The Mac header has `Saturation = 0.0` and it is no longer named. |
| Slate folder picker | OK. Opens in the scene's folder (`_Shots`). |
| Slate row after Save for the project | OK. Shows "on · project ruleset" right after going back. |
| Slate below | OK. RGBA, 32 opaque strip rows, image alpha kept, `sentinel:version = v001` without a Save Version history. |
| Bar over the image | OK. 1280×720 as the source, bar opaque. |
| Numbered stills, Open Stills | OK. `_snap_001…008`; Finder opens the stills folder. |
| Watch folder, 3 snapshots | OK. `_006–_008` in seconds; three "Snapshot watch: converted …" lines in the Python console. |
| Non-EXR alert live | OK when the panel is visible. It appeared within seconds without touching the panel once RenderView stopped covering it (see observations). |
| Sentinel Frame tag, MAIN expanded ×5 | OK. No crash; C4D answered afterwards. |
| Overview, QC, Deliver, Tools, Settings, Help, Asset Hub, QC Report, Supervisor | OK. No errors. |

## RenderView fidelity on macOS

Pairs of a snapshot EXR and a RenderView *Save image* PNG of the same snapshot, 1280×720, opaque pixels:

| Pair | Sentinel's reproduction vs export |
|---|---|
| M0: post off (base) | 0.20 / 0.03 / 0.07 mean; max 16 in R on 2.6 % of pixels |
| M1: Filmic High Contrast 50 %, CM before LUT off, master curve (with the PR #33 lookup) | 0.40 / 0.58 / 0.70 mean; max 23 |
| M3: master + green curve (channel first) | 0.40 / 0.53 / 0.85 mean; max 25 in R, 3 in G |

The maxima all come from one difference that exists **with post off too**. In very saturated colours (the blue torus), C4D's ACES 1.0 SDR-video view (the same as PyOpenColorIO with C4D's config) clamps a channel to 0, while RenderView on macOS gives 16–23 there.

- "Use Monitor Color Space" does not change the export: on and off were identical.
- The header's OCIO config is the same file as on Windows, where the same kind of scene matched (Windows round 5: max 4).
- Most likely, RenderView's GPU path on macOS evaluates the view differently. Sentinel converts with C4D's view, so this is a measured platform limitation, not a Sentinel defect.

## Observations

1. When RenderView is maximized over the panel, the panel's web view stops polling: the source line and the non-EXR alert update as soon as the panel is visible again.
2. On this host, RenderView's "Save snapshots as EXR" was already ticked when RenderView opened. The panel's alert text still says the box "resets every Cinema 4D session", which may no longer hold on macOS.
3. Doctor's OS row shows the Darwin kernel version.
