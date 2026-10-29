---
module: matwire
tags: [matwire, redshift, udim, uvtile, texturesampler, getallassetsnew, renderdocument]
problem_type: spike
---

# UDIM / UVTILE in the Redshift Texture Sampler (C4D 2026.304)

Measured on C4D 2026.304, macOS, 2026-10-29, through the C4D MCP on throwaway
documents (`KillDocument` in `finally`). Tiles were 32×32 solid-colour PNGs
written with `BaseBitmap.Save`: 1001 red, 1002 green, 1011 blue (and the same
colours as `rock_u1_v1` / `rock_u2_v1` / `rock_u1_v2`). The mesh is one
polygon object with five quads whose UVs sit in different tiles, rendered with
`RenderDocument` (Redshift, 500×100) through an emission-only Standard
material (base colour 0, reflection weight 0, emission weight 1), and sampled
at each quad's centre.

## Render results

Quads: A = u 0–1, B = u 1–2, C = u 2–3 (no tile on disk), D = C4D v 1–2,
E = C4D v −1–0 (all with u 0–1).

| Sampler `tex0/path` | A | B | C | D | E |
|---|---|---|---|---|---|
| `rock_BaseColor.1001.png` (base case) | red | red | red | red | red |
| `rock_BaseColor.<UDIM>.png` | red | green | **black** | black | blue |
| `rock_BaseColor.<udim>.png` | red | green | black | black | blue |
| `rock<UVTILE>.png` | red | green | black | black | blue |
| `rock<uvtile>.png` | red | green | black | black | blue |
| `rock_<UVTILE>.png` | black | black | black | black | black |

What this establishes:

- The base case discriminates: a plain path repeats the one texture across
  every tile (wrap), so the coloured tiles in the token rows come from tile
  resolution, not from the UVs alone.
- `<UDIM>` and `<UVTILE>` both work, case-insensitively.
- **`<UVTILE>` absorbs the leading underscore**: `rock<UVTILE>.png` loads
  `rock_u1_v1.png`; `rock_<UVTILE>.png` looks for `rock__u1_v1.png` and
  renders black everywhere.
- **A tile missing on disk renders black, silently** (quad C). No error,
  no log line.
- Tile row: Redshift's UDIM row 1 (1011) is C4D's UV **v in [−1, 0]**
  (quad E), not v in [1, 2] (quad D). C4D stores v flipped relative to the
  UDIM convention. Meshes imported from Painter/Maya keep this consistent
  (C4D flips on import), so it only matters when building UVs by hand, as
  this probe did.
- The texture tag created by `MakeTag(Ttexture)` defaults to projection 0
  (spherical). The first run, with that default, rendered every quad red;
  `TEXTURETAG_PROJECTION_UVW` is required for a UV probe.

## Through Matwire's own writer

`matwire_c4d.create_material_for_set` with `{"emission": "rock_BaseColor.<UDIM>.png"}`
(Standard; the shared UV Context Projection node is available in this build
and sits in front of the sampler) → `ok`. The render resolves tiles through
the context node: quad E shows the blue 1011 tile and quad C (no tile) shows
no tile colour. (Tiles A/B saturate to white in that run because the default
base colour gets lit, so A vs B isn't discriminated there; E is the proof.)

## Writer re-check (v1.42)

Same mesh, camera and render settings, material from
`create_material_for_set(…, {"emission": "rock_Emit.<UDIM>.png"}, material="standard")`
(UV Context node present). Tiles are dim: 1001 = (64, 0, 0), 1002 = (0, 64, 0),
1011 = (0, 0, 64). Pixels were sampled at each quad's centre and ±30 px. The
table shows the left edge of A, the right edge of B, and the centres of C–E.

| Sampler path | A (x 44) | B (x 192) | C | D | E |
|---|---|---|---|---|---|
| `nope_Emit.<UDIM>.png` (no tile on disk, base case) | 228,228,228 | 207,207,207 | 129,129,129 | 119,119,119 | 118,118,118 |
| `rock_Emit.<UDIM>.png` | **236**,229,228 | 212,**219**,209 | 129,129,129 | 119,119,119 | 119,118,**130** |
| `rock_Emit.1001.png` (plain path) | **236**,229,228 | **215**,208,208 | **137**,130,130 | **127**,120,120 | **126**,119,118 |

The base case explains the white in the first writer run: the quad centres
of A and B saturate to 255 **with no tile at all**. That is the default
light's highlight on the reflective Standard (`refl_weight` 1), not emission.
Against that base, the token path adds the tile colour exactly where it
should:
- A gains red, B gains green and E gains blue.
- C and D are unchanged (no tile, and D is outside the tile rows).
- The plain path adds red to every quad (wrap).

## Texture Sampler ports

Input ports of `texturesampler` filtered for tile/uv/path words: `tex0_gamma`,
`wrapu`, `wrapv`, `uv_context`, `filter_enable_type`, `filter_bicubic`,
`mip_bias`, `tex0` (`path`). **There is no tile-mode port**: UDIM is entirely
the token in the path.

## What C4D and Sentinel see

- `GetAllAssetsNew` on a document whose sampler holds `rock_BaseColor.<UDIM>.png`
  lists **each tile that exists** as its own asset (`…1001.png`, `…1002.png`,
  `…1011.png`, all `exists=True`), plus the document itself.
- `textures.scan_all_texture_paths` reports the sampler with the **pattern**
  as its path. For an absolute path the status is `absolute` (no existence
  check); for a relative path `_resolve_relative_texture` calls
  `os.path.isfile` on the pattern, so a relative `<UDIM>` path would be a
  false `missing`.
- `matwire_c4d.height_float_stats(<pattern>)` returns `None` (it can't open
  a pattern), so a float height map with UDIM tiles would read "unverified".
- `matgraph.infer_channel("LOK_body_Roughness.<UDIM>.png", "base_color")`
  returns `("basecolor", "port")`: the name signal is lost on token names and
  only the port remains.

## Coat ports (for the Painter OpenPBR export)

Read from fresh nodes in the same session:

| | OpenPBR | Standard |
|---|---|---|
| weight | `coat_weight` (born 0) | `coat_weight` (born 0) |
| colour | `coat_color` (born 1,1,1) | `coat_color` (born 1,1,1) |
| roughness | `coat_roughness` (born 0) | `coat_roughness` (born 0) |
| normal | `geometry_coat_normal` | `coat_bump_input` |

Both BRDFs are born with `coat_weight = 0`, so coat maps without a weight map
(or a written weight) are invisible, the same trap as emission.

## The LOK Painter export

`…/LOK-003 MAX HYPE (Attack)/…/texturizado/EXPORT_PAINTER`: 100 PNGs, two
texture sets. `LOK_cuerpo` uses tiles 1001–1004 and 1006–1010; `LOK_grip`
uses only 1005 (the gap in `cuerpo` is where `grip` lives, not a missing
tile). Filenames follow
`<mesh>_<set>_<channel>_<OCIO colourspace>_<tile>.png`, e.g.
`LOK_cuerpo_Base_color_sRGB Encoded Rec.709 (sRGB)_1001.png`,
`LOK_cuerpo_Specular_roughness_Raw_1001.png`. Channels: `Base_color`,
`Base_metalness`, `Specular_roughness`, `Normal`, `Normal_OpenGL`, `Height`,
`Coat_color`, `Coat_weight`, `Coat_roughness`, `Coat_normal`.

The v1.41 engine recognises **0 sets** in that folder (all 100 files
`no_channel`). Stripping the tile and the colourspace suffix by hand still
splits the sets (`LOK_cuerpo_Base` for metalness, `LOK_cuerpo_Specular` for
roughness, `LOK_cuerpo_Coat` for coat roughness/normal) and leaves
`Normal_OpenGL`, `Coat_color` and `Coat_weight` unrecognised.

## Sources

- Redshift docs, "UDIM and UVTILE":
  https://help.maxon.net/r3d/cinema/en-us/Content/html/UDIM+and+UVTILE.html
  (UDIM index = 1001 + v·10 + u, max 10 columns; UVTILE `_u1_v1`; Redshift
  can't filter across tile neighbours).
- Redshift docs, "Texture Sampler":
  https://help.maxon.net/r3d/cinema/en-us/Content/html/Texture+Sampler.html
