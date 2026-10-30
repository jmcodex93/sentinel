# Windows round 9 — v1.43.4 checklist

Short round for the fix of [round 8](2026-09-24-windows-acceptance.md#round-8--2026-10-30-candidate-0211ffe-v1433-c4d-202640)'s two FAILs: R4 and R5, Hub clicks right after an Undo/Redo. It ends with a quick regression of the Hub actions round 8 passed. The macOS reference values below are from 2026-10-30, C4D 2026.304.

## Setup

- **Candidate:** `sentinel-beta-<sha>.zip` (tag `v1.43.4`), filled in after the tag.
  - Check the hash against the `.sha256`, then install with `install.py --target`.
- **Host:** Windows 11 + **C4D 2026.4.0**, Redshift. A clean profile with **Sentinel only**, as in round 8.
- **Fixture:** round 8's scene works: `D:\Sentinel QA\LOK\c4d\lok_v001.c4d`, with the 2 materials and the 10 repointed Texture tags.
  - Before starting, point the samplers back to `EXPORT_PAINTER\` (the absolute paths): select all rows in the Hub → Relink, or reopen a copy saved before round 8's R3.
  - Or start from a fresh LOK-003 copy and repeat round 8's R1–R2 setup.
- **Doctor:** must show Sentinel **1.43.4**, "Windows 11", and no known-issue item.

**Don't click a Hub row between a Ctrl+Z and the Ctrl+Y that follows it.** A row click selects the material in C4D, and that empties the Redo history (measured on macOS; known, not a finding). In S1–S3 the clicks come after the Ctrl+Z or the Ctrl+Y, never between the two.

## Checks

| # | Steps | Expected (macOS reference) |
|---|---|---|
| S1 | **R4, quick clicks.** Hub: select all → Copy into project. Press Ctrl+Z, and **straight away** click 4–5 rows quickly (within the first 2 s). | No toast "That asset is no longer in the scene.".<br>At most **one** "The scene is still updating — click the row again in a moment.", not one per click.<br>The last row clicked is selected in the Hub and its material in the Material Manager. |
| S2 | **R5, selection across the Undo.** Press Ctrl+Y (rows back to `relative:///tex/…`). Click a row, then press Ctrl+Z and wait ~3 s until the paths read `EXPORT_PAINTER\…`. Shift+click a row 3 rows down, then Ctrl+click another row. | **After the Ctrl+Z:** the row clicked first stays highlighted ("1 selected").<br>**Shift+click:** the range from that row, "4 selected" (round 8: 1).<br>**Ctrl+click:** adds one, "5 selected". |
| S3 | **R5 straight away.** Ctrl+Y, and **straight away** click, Shift+click 3 rows down, Ctrl+click (as round 8's R5). | "4 selected" after the Shift+click, "5 selected" after the Ctrl+click, without waiting ~5 s. |
| S4 | **The selection doesn't jump.** Select 2–3 cuerpo rows. In the Material Manager, duplicate `LOK_grip_02` (copy and paste it) and wait for the Hub to refresh. Then undo the paste. | The same rows stay selected; no other row becomes selected. (The new material shifts every texture's scan position, so the Hub doesn't carry by position: it keeps the keys that still exist.) |
| S5 | **Regression:** Copy into project + Ctrl+Z / Ctrl+Y (all 18 rows each time), Shrink 1K on a cuerpo row + Ctrl+Z, Switch res, Collect. | Same results as round 8's R3 and R9. |
| S6 | Python console after the round. | No traceback, no `http.handler_failed` and no `CRITICAL: Stop` from Sentinel. |

## Known, not findings

- A Hub row click between an Undo and a Redo empties the Redo (see Setup).
- Still open from round 8:
  - Collect's manifest: `original_path`, `hash` and counts;
  - the Deliver bar's QC count refreshes only with the inventory.
  - Switch res lists an incomplete family the row is linked to;
  - Collect doesn't restore a minimized Hub.

## Report

- One OK / FAIL per check, with a screenshot of any toast in S1 and the "N selected" count in S2 and S3.
- The Doctor block at the top.
- Results go into [`2026-09-24-windows-acceptance.md`](2026-09-24-windows-acceptance.md) as round 9.
