# Redshift resolves a `<UDIM>` pattern only through tile 1001 (2026-10-30)

Found in the Windows acceptance round 7 (W5: the LOK-003 grip, whose texture set only has tile 1005, rendered untextured). Re-measured on macOS, C4D 2026.304 + Redshift, in the GUI session.

## Method

`tests/c4d_runner/run_udim_checks.py` helpers, loaded with `runpy`:
- one 2000-unit quad whose UVs cover a single tile;
- an emission material built by Matwire's `create_material_for_set`;
- 16 px pure-colour tiles (1001 red, 1002 green, 1005 yellow);
- `rendered_colour` (64×64 `RenderDocument`, centre pixel; `None` = the grey of a missing texture).

Each case runs in its own throwaway document, saved next to its `tex/` folder. Paths were tested both absolute (as Matwire writes them) and relative (`tex/…`).

## Tile 1001

| Tiles on disk | UVs on | Absolute | Relative |
|---|---|---|---|
| 1001, 1002 | 1001 | red | red |
| 1001, 1002 | 1002 | green | green |
| 1002 | 1002 | **missing** | **missing** |
| 1005 | 1005 | **missing** | **missing** |
| 1001, 1005 | 1005 | yellow | yellow |
| none (base case) | 1001 | missing | missing |

- Control: an explicit path to `probe.1005.png` renders yellow.
- The Redshift log (`~/redshift/log/log.latest.0/log.html`) says `Param tex0: Texture '…/probe.<UDIM>.png' Not Found` for the cases without 1001. That is the same line the Windows console showed for the 9 grip samplers.
- When tile 1001 is missing, the **whole pattern** is treated as missing; every tile renders black, not only the absent one.

## "1001" elsewhere in the path

UVs on 1002, tiles 1001 and 1002 present, absolute path. Only the folder name changes:

| Folder | Render |
|---|---|
| `shot_2001` | green |
| `shot_1002` | green |
| `shot_1001` | **missing** |
| `sh1001x` | **missing** |

The log shows why: Redshift turns the path back into a pattern by replacing **every** `1001` in it. `…/udim1001c/a/tex/probe.<UDIM>.png` is logged as `UVTILE texture resource creation failed for '…/udim<UDIM>c/a/tex/probe.<UDIM>.png'! No files found`. A folder or file name containing `1001` (a frame number, a shot code) therefore breaks every UDIM texture under it.

## Consequences for Sentinel

- **QC #14** checked used tiles against the tiles on disk. It was satisfied by the LOK grip (UVs on 1005, file 1005 present), yet the grip renders untextured.
- **Matwire, the Hub and Collect** also treated these patterns as complete.
- **Now:** `udim.redshift_unresolved` encodes both rules. QC #14 adds them to its message ("N maps without tile 1001, which Redshift needs to resolve <UDIM> — renders untextured"), and the Matwire preview warns per set. `run_udim_checks.qc14_redshift_resolution` ties each verdict to a real render. The Hub doesn't use the rule yet.
- What renders correctly: a UDIM pattern with tile 1001 on disk and no other `1001` in its path.
- Not covered here: `<UVTILE>` (whether `_u1_v1` plays the same role) and other renderers.
