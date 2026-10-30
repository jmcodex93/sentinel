# Windows round 7 — UDIM checklist (v1.43.2)

What a Windows round has to cover for the UDIM work: v1.42.0 (Matwire UDIM and the Painter OpenPBR export), v1.43.0 (Hub actions per tile, QC #14), v1.43.1 (UDIM in the Hub dialogs) and v1.43.2 (Matwire preview layout). So far these releases have only run in Windows CI (pytest); every live check was on macOS. The macOS reference values below come from the GUI pass of 2026-10-30 ([macOS acceptance](2026-10-24-macos-acceptance.md#matwire-udim-in-the-panel--2026-10-30)) and the `c4dpy` runner `tests/c4d_runner/run_udim_checks.py`.

The risks are specific to Windows:
- `<UDIM>` inside an absolute Windows path with spaces and parentheses. Painter writes `…_sRGB Encoded Rec.709 (sRGB)_1001.png`.
- Tile discovery and relinking with `\` separators.
- Shrink, Copy into project and Collect writing tile files on NTFS.
- Whether Redshift on Windows resolves the pattern at all. A tile Redshift can't find renders black, silently.

## Setup

- **Candidate:** `sentinel-beta-5128c00d6727.zip` (tag `v1.43.2`), SHA256 `1408874b3d3e8f7a87ffe6e545dfabb934830d84f3e5cd1c60ea3bfee8a19f79`, 132 files.
  - Check the hash against the `.sha256`, then install with `install.py`.
- **Host:** Windows 11 + **C4D 2026.4.0**, Redshift, a clean profile with Sentinel only (as in round 6). 2026.3 counts the same, but don't expand the Frame tag on 2026.3.4.
- **Fixture:** the LOK-003 Painter export.
  - `EXPORT_PAINTER\`: 100 PNG, 25 MB. Two texture sets, `LOK_cuerpo` on tiles 1001–1004 and 1006–1010, `LOK_grip` on 1005.
  - The mesh `LOK003_GEN3_v4_painter.fbx`, 21 MB, with two FBX materials of the same names.
  - Copy both into a folder whose path has a space, e.g. `D:\Sentinel QA\LOK\`.
  - Copy the folder's contents, not a link: steps 5 and 9 move and delete tiles.
- **Scene:** a new scene saved as `D:\Sentinel QA\LOK\c4d\lok_v001.c4d`, with the FBX merged (File → Merge).
- **Doctor:** must show Sentinel 1.43.2, the C4D build and "Windows 11", with no known-issue item.

## Checks

| # | Steps | Expected (macOS reference) |
|---|---|---|
| W1 | Tools → Material from Folder → paste the `EXPORT_PAINTER` path → Enter. | **Sets:** `LOK_cuerpo_02` and `LOK_grip_02` (`_02` because the FBX materials exist).<br>**Rows:** 9 per set: basecolor, coat_color, coat_normal, coat_roughness, coat_weight, height, metalness, normal, roughness.<br>**Tiles:** cuerpo rows say "UDIM · 9 tiles (1001–1004, 1006–1010)", grip rows "UDIM · 1 tile (1005)".<br>**Colorspace:** sRGB on basecolor and coat_color, Raw on the rest. Height says "→ mid-grey = flat (−0.5…0.5)".<br>**Skipped:** "1 file(s) skipped" per set: `…_Normal_Raw_<UDIM>.png`, "GL normal preferred".<br>No "Tiles differ" warning and no "coat weight → 1.0" note. Material OpenPBR, Projection UV Channel, button "Create 2 materials". |
| W2 | Create 2 materials. | Toast "Created 2 RS material(s)". QC drops by the materials being unassigned. |
| W3 | Ctrl+Z once, then Redo. | One undo removes **both** materials and leaves the FBX ones; Redo brings both back. |
| W4 | Open each material in the Node Editor. | **Samplers:** 9 per material. Each path is the absolute Windows path ending in `…_<UDIM>.png`.<br>**Colorspace:** sRGB on base and coat colour, Raw on the rest.<br>**Wiring:** coat weight, colour, roughness and normal wired; height → Displacement; normal → Bump. |
| W5 | Repoint the 10 Texture tags from `LOK_cuerpo`/`LOK_grip` to `LOK_cuerpo_02`/`LOK_grip_02`. Add a camera and a Redshift dome light. Render (Picture Viewer or RenderView). | Face, rim and neck textured from the cuerpo tiles. **Known (round 7, both OSes):** the grip renders untextured, because its set has no tile 1001, which Redshift needs to resolve a `<UDIM>` pattern. Check the Redshift log for `Not Found`, not the image by eye. |
| W6 | QC tab. Then move `LOK_cuerpo_Base_color_sRGB Encoded Rec.709 (sRGB)_1003.png` out of the folder. Make any small scene change (rename an object) so QC refreshes. Open QC. Afterwards put the file back. | **Clean scene:** UDIM Tiles isn't in the failure list.<br>**Without the tile:** "⚠ UDIM Tiles · 4". The first row reads `…Insertos_produccion_UV: tile 1003 has no texture (LOK_cuerpo_02: 1 map) — renders black (+3 more)`.<br>**After restoring:** it disappears. |
| W7 | Overview → Hub. | **Header:** 18 assets · 24.4 MB · 3.54 GB VRAM.<br>**Rows:** "UDIM · 9" / "UDIM · 1", Res 4K. A cuerpo map shows 576 MB VRAM, a grip map 64 MB (normal) or 21.3 MB (greyscale roughness).<br>**Status:** "absolute" (Matwire writes absolute paths). |
| W8 | Hub: select all → Copy into project. Then Ctrl+Z, then Redo. | **Files:** `c4d\tex\` (next to the scene) gets the 90 referenced PNG (the 10 skipped `Normal_Raw` tiles aren't copied).<br>**Hub:** samplers become `relative:///tex/…_<UDIM>.png`, status ok.<br>The render (W5) is still textured. One Ctrl+Z restores the absolute paths. |
| W9 | Hub: select the cuerpo base colour row → Shrink → 1K. Then Ctrl+Z, then Redo. | **Dialog:** the row is eligible with a VRAM estimate, not "no meta".<br>**Files:** 9 files `…(sRGB)_1K_1001.png` … `_1010.png` at 1024 px next to the originals; the sampler points to `…_1K_<UDIM>.png`.<br>Render still textured. One Ctrl+Z goes back to the 4K pattern. |
| W10 | Hub → Switch res on that row. Then delete one `_1K_` tile and open Switch res again. | **With the full 1K family:** 1K and Highest are offered; switching to 1K and back to Highest relinks both ways.<br>**After deleting a tile:** 1K is no longer offered, because the family is incomplete; Highest is still offered. Put the tile back afterwards. |
| W11 | Deliver → Collect into a new folder. | **Package:** `tex\` holds every referenced tile (90 PNG, plus the `_1K` family if W9 was kept), and the sealed manifest lists the tiles per map with `/` separators.<br>Known behaviour: after Collect the open document is the delivered copy. |
| W12 | Python console after the round. | No traceback, no `http.handler_failed` and no `CRITICAL: Stop` lines from Sentinel. If any appear, copy the full text. |

**Optional, host level.** If the repository is checked out on the Windows machine, run this and keep the output:

```
c4dpy -g_console=true <absolute path>\tests\c4d_runner\run_udim_checks.py
```

It should print one PASS line per section:
- material rules;
- QC14;
- shrink;
- copy into project;
- switch;
- collect.

Judge it by those lines: `c4dpy` exits 1 even on success.

## Known, not Windows findings

- QC Assets reports a texture with an absolute path as "absolute" even when the file doesn't exist. A UDIM pattern with no tile on disk therefore shows as "absolute" in QC, and QC #14 leaves it to Assets. The Hub does check existence.

## Report

- **Per check:** OK or FAIL, with a screenshot of each toast and dialog, and the W5 and W9 renders.
- **Header:** the Doctor block (OS, C4D build, Sentinel version) at the top of the report.
- **Recording:** results go into [`2026-09-24-windows-acceptance.md`](2026-09-24-windows-acceptance.md) as round 7.
