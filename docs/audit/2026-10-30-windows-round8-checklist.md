# Windows round 8 — v1.43.3 checklist

Short round for the fixes made after [round 7](2026-09-24-windows-acceptance.md#round-7--2026-10-30-candidate-5128c00-v1432-c4d-202640--udim): W8 (Redo), W5 (UDIM without tile 1001), "Ctrl+Z" and the `scene_changed` toasts. It also covers the item round 7 couldn't settle (Shift/Ctrl selection) and a quick regression of round 7's OK checks. The macOS reference values below are from 2026-10-30, C4D 2026.304.

## Setup

- **Candidate:** `sentinel-beta-0211ffe495a4.zip` (tag `v1.43.3`), SHA256 `e497f804978e89d42c1f516ae82f28a05a149eeddc12ec99c0798e0c9f1217e9`, 132 files.
  - Check the hash against the `.sha256`, then install with `install.py --target`.
- **Host:** Windows 11 + **C4D 2026.4.0**, Redshift.
  - Use a clean profile with **Sentinel only** if you can. If the MCP bridge is needed, say so in the report, and don't drive Win32 windows from C4D's main thread: round 7 hung C4D that way.
- **Fixture:** a fresh copy of the LOK-003 fixture (`EXPORT_PAINTER\`, 100 PNG, plus the FBX) in `D:\Sentinel QA\LOK\`, without round 7's `_1K` files.
  - Scene `D:\Sentinel QA\LOK\c4d\lok_v001.c4d`, with the FBX merged.
- **Doctor:** must show Sentinel **1.43.3**, "Windows 11", and no known-issue item.

## Checks

| # | Steps | Expected (macOS reference) |
|---|---|---|
| R1 | Tools → Material from Folder → the `EXPORT_PAINTER` path. | **LOK_grip_02**, under its rows, shows in amber: "No tile 1001: Redshift won't load basecolor, … (its 9 maps) and they render untextured. Add a 1001 tile (any image) or move the UVs to 1001."<br>**LOK_cuerpo_02** shows no such warning. Everything else as round 7 W1. |
| R2 | Create 2 materials. Repoint the 10 Texture tags to `LOK_cuerpo_02` / `LOK_grip_02`. Open the QC tab. | "⚠ UDIM Tiles · 4": the 4 grip meshes (Empunadura, Cinta, Goma, Tapa).<br>First row: `…Empunadura_UV: LOK_grip_02: 9 maps without tile 1001, which Redshift needs to resolve <UDIM> — renders untextured (+3 more)`.<br>No cuerpo mesh is listed. |
| R3 | **W8.** Hub: select all → Copy into project. Then Ctrl+Z, then Ctrl+Y, then Ctrl+Z again. | **Copy:** "Copied 18 (90 UDIM tiles)".<br>**Ctrl+Z:** all 18 rows go back to the absolute `EXPORT_PAINTER` paths.<br>**Ctrl+Y:** **all 18** come back as `relative:///tex/…` with status ok (round 7: only 1).<br>**Ctrl+Z again:** all 18 absolute. Finish with one more Ctrl+Y, so the samplers point to `c4d\tex\` for R7. |
| R4 | **Toasts.** Straight after one of R3's Ctrl+Z / Ctrl+Y, click several rows quickly. Then wait ~5 s and click a row again. | **During the clicks:** no toast with the raw code `scene_changed`. At most an info toast, "The scene is still updating — click the row again in a moment.", and not one per click.<br>**After waiting:** a single click selects the row's material in the Material Manager, with no toast. |
| R5 | **Selection** (round 7 open item), in the same state right after an Undo/Redo: Shift+click a row a few rows down, then Ctrl+click another row. | **Shift+click** selects the range from the anchor row; **Ctrl+click** toggles one row. If it fails, note whether it recovers after waiting ~5 s. |
| R6 | **"Ctrl+Z".** Select one cuerpo row → Shrink (cancel). Switch res (cancel). Render tab → Reset All (cancel at the confirmation). | **Shrink:** "…A single **Ctrl+Z** reverts the relink."<br>**Switch res:** "…A single **Ctrl+Z** reverts the batch."<br>**Reset All:** the confirmation ends "**Ctrl+Z** restores them." if the scene has non-standard presets, or doesn't mention undo if it has none. |
| R7 | **W5 fix.** In PowerShell, give each grip map a tile 1001 in the folder the samplers point to now (`c4d\tex\` after R3), using the command below. Rename any object so QC refreshes, then render. | **QC:** the 4 "UDIM Tiles" grip rows disappear.<br>**Render:** the grip is textured; the 1001 copy only needs to exist.<br>**Redshift console:** no `…LOK_grip_…<UDIM>.png' Not Found` line (round 7 had 9). |
| R8 | **"1001" in the path.** Copy `EXPORT_PAINTER` to `D:\Sentinel QA\shot_1001\EXPORT_PAINTER` and preview it in Material from Folder (don't create). | **Both sets** show in amber: '"1001" appears in the path outside <UDIM>: Redshift won't load … and they render untextured. Rename the folder.' |
| R9 | **Regression**, as in round 7: W9 Shrink 1K on the cuerpo base colour (+ Ctrl+Z / Ctrl+Y), W10 Switch res, W11 Collect. | Same results as round 7. W9 now works on a project-relative row: the row is `ok` after R3. |
| R10 | Python console after the round. | No traceback, no `http.handler_failed` and no `CRITICAL: Stop` from Sentinel. |

R7 command (copies each grip `_1005.png` to the same name ending `_1001.png`):

```powershell
Get-ChildItem "D:\Sentinel QA\LOK\c4d\tex\LOK_grip_*_1005.png" | ForEach-Object { Copy-Item $_.FullName ($_.FullName -replace '_1005\.png$', '_1001.png') }
```

## Known, not findings

- The Hub doesn't warn about W5 yet; QC #14 and Matwire do.
- Material Graph fixes may still lose changes on Redo (same `UNDO_MODE.ADD` pattern, not measured).
- Still open from round 7:
  - Collect's manifest: `original_path`, `hash` and counts;
  - Switch res lists an incomplete family the row is linked to;
  - Collect doesn't restore a minimized Hub.

## Report

- One OK / FAIL per check, with screenshots of R1, R2, R4 (any toast), R6 and the R7 render.
- The Doctor block at the top.
- Results go into [`2026-09-24-windows-acceptance.md`](2026-09-24-windows-acceptance.md) as round 8.
