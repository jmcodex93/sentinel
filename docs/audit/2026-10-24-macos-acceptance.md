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

## Matwire UDIM in the panel — 2026-10-30

v1.43.1 code (`main` at `70db0e6`, synced with `sync.sh`, C4D restarted), C4D 2026.304, the regular profile.

**Fixture.** The real LOK-003 Painter export (100 PNG, 4K) and its FBX were copied into the session scratchpad; the originals were not touched. The FBX was merged into a throwaway scene, `lok_v001.c4d`. Its two materials, `LOK_cuerpo` and `LOK_grip`, are standard materials with no textures. The panel was driven through the real web view.

| Item | Result |
|---|---|
| Preview (Tools → Material from Folder, path pasted) | **OK.**<br>**Sets:** `LOK_cuerpo_02` and `LOK_grip_02`, deduped against the FBX materials.<br>**Rows:** 9 per set, Coat included. "UDIM · 9 tiles (1001–1004, 1006–1010)" and "UDIM · 1 tile (1005)". sRGB on base and coat colour, Raw on the rest.<br>**Skipped:** `Normal_Raw` with "GL normal preferred".<br>No tile-mismatch warning and no coat-weight note (the weight map exists). |
| Create 2 materials | **OK.** Toast "Created 2 RS material(s)". 9 samplers each, every path absolute and ending in `_<UDIM>.png`. Base and coat colour are sRGB, the rest Raw. Coat colour, weight, roughness and normal are wired, height feeds Displacement and normal feeds Bump. |
| Undo / Redo | **OK.** One Cmd+Z (12105) removed both materials and kept the FBX ones; Redo (12297) restored both. |
| Render | **OK.** Texture tags repointed to the new materials, RS dome light, 640×900. Face, rim and grip (1005) all textured; no black area. |
| QC #14 | **OK.** Clean scene: no violation. Without `LOK_cuerpo_Base_color…_1003.png`: "UDIM Tiles · 4", the four meshes on tile 1003, in the panel and from the check itself. File restored afterwards. |
| Hub | **OK.** 18 assets · 24.4 MB · 3.54 GB VRAM. Rows read "UDIM · 9" / "UDIM · 1", 4K. A cuerpo map shows 576 MB (9 × 64 MB). Status "absolute". |

**Observations:**
1. **Preview overflows sideways.** In the 420 px floating panel, the shrink-0 "UDIM · N tiles (…)" note plus the colorspace chip push past the right edge, and the file name column truncates to one letter. A horizontal scrollbar appears. Long Painter names make it worse. **Fixed** in v1.43.2 (PR #44): the notes moved to their own line under the file (in the folds too); re-checked in the same panel with the same export, no horizontal scrollbar.
2. **Missing absolute textures aren't reported as missing.** `_classify_texture_path` labels any absolute path "absolute" without checking that the file exists. Base case: with every `LOK_grip` tile moved away, QC #14 skipped the pattern ("QC Assets reports it missing"), but QC Assets still said "absolute", so QC showed nothing about the missing files. This predates UDIM and applies to plain files too.
3. **Mixed language in the Hub.** The header read "… MB disco" (`HubPage.tsx`), a Spanish word in the English UI. **Fixed** in v1.43.2: "… MB on disk", re-checked in the Hub.
4. **Two QC counts.** The header's "QC 9/14" counts warnings as passing, while the QC tab title "QC 8/14" counts only OK checks.
