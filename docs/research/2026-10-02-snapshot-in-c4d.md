---
module: snapshots
tags: [snapshot, exr, ocio, slate, geclipmap, fonts]
problem_type: spike
---

# Snapshot EXR → PNG and slate inside Cinema 4D (no external Python)

Measured on C4D 2026.304, macOS 26.7 (arm64), 2026-10-01/02, with throwaway
script commands (registered from `library/scripts`, results written to JSON) and
an independent oracle: PyOpenColorIO 2.6 in a scratch venv, loading
`Redshift/res/core/Data/OCIO/config.ocio`, transform ACEScg → sRGB / ACES 1.0
SDR-video. Inputs: a synthetic 1920×1080 HDR EXR (max 16, saturated patches) and
six real RenderView snapshots (1231×692 and 1374×807, RGBA half, single part).

## Why

The snapshot converter ran in an external system Python (OpenEXR + numpy +
Pillow). Installing that is the main friction for artists, OpenEXR has no wheel
for Python 3.14, and the converter approximates the ACES curve.

## Colour conversion

| Route | Result |
|---|---|
| `doc.GetColorConverter().TransformColors(list[Vector], COLORSPACETRANSFORMATION_OCIO_RENDERING_TO_VIEW)`, row by row | **Exact.** 99.8–99.93 % of pixels identical to the oracle, max 1 level, on synthetic and real snapshots. 1080p: 1.35 s (read 0.004, Vector build 0.24, transform 0.48, pack + `SetPixelCnt` 0.63). Real 1231×692: 0.6 s. |
| Today's external converter (Narkowicz fit) | Mean 12 levels off on real snapshots (max 38); 53 on the synthetic one. |
| `ColorProfileConvert` render→view through `GetPixelCnt(conversion=...)` | Converts, but wrong — worse than a plain clamp. Dead. |
| `BakeOcioViewToBitmap(bmp, rd.GetDataInstance(), SAVEBIT_NONE)` | Returns `None` for a disk-loaded bitmap, with or without OCIO profiles set and with or without `RDATA_BAKE_OCIO_VIEW_TRANSFORM`. Takes a BaseContainer, not the RenderData the stub says. Dead. |
| Pure-Python matrix + LUT | ~0.45 µs/px, approximation only. Not needed. |

C4D's default OCIO config (`resource/modules/c4d_base/ocio/config.ocio`) is
Redshift's own, so the document view is RenderView's default view. The API
exists from **2025.2** (`GetColorConverter`, `GetOcioProfiles`).

Facts: `BaseBitmap.InitWith` loads the EXR as `COLORMODE_RGBf` (36), values
above 1 kept. `GetPixelCnt` returns a falsy value even when it succeeds — never
test it. RenderView snapshots are beauty only, even with an AOV selected in the
RV dropdown.

## Slate

- `GeClipMap`: **every** call, including `SetFont`, `TextWidth` and
  `GetPixelRGBA`, must sit between `BeginDraw()` and `EndDraw()`
  ("Expected BeginDraw() call before drawing operation").
- `GetBitmap()` returns a bitmap owned by the clip map; `GetClone()` it before
  the clip map goes away ("object is not alive").
- `BaseContainer.GetClone()` needs a flags argument; copy font descriptions with
  `c4d.BaseContainer(desc)`.
- Fonts are found only by **PostScript name** (`GetFontDescription(name,
  GE_FONT_NAME_POSTSCRIPT)`): by display or family name the lookup returns an
  empty container and `SetFont` silently uses C4D's UI font. An unknown
  PostScript name silently returns another font (Helvetica here), so check
  `GetFontName(desc, GE_FONT_NAME_POSTSCRIPT) == name`.
- `EnumerateFonts` takes 1–3.5 s (4710 entries); avoid it.
- Text is antialiased (28 grey levels), accents, `·` and `—` render with Arial.
- Strip compose: 3 ms at 1080p, 13 ms at 4K; PNG save 65 / 235 ms.
- A bundled TTF registered for the process only — `CTFontManagerRegisterFontsForURL(url,
  kCTFontManagerScopeProcess)` via ctypes, 8 ms — is visible to C4D right away.
  Proven with a renamed copy of Inter ("SentinelSlate") that was not installed.
  Windows (`AddFontResourceExW(path, FR_PRIVATE, 0)`) is **not measured**;
  Arial is the fallback there.

## PNG metadata without Pillow

C4D's PNG saver writes `IHDR, iCCP ("sRGB IEC61966-2.1"), pHYs, IDAT…, IEND`.
Inserting `tEXt` (Latin-1) / `iTXt` (UTF-8) chunks right after `IHDR` with
`zlib.crc32` round-trips; Pillow reads them through `img.text` and C4D reloads
the file pixel-identical.

## Threading

Load, `TransformColors`, GeClipMap slate and `Save` all ran in a
`threading.Thread` (`GeIsMainThread()` false) with the converter and font
description captured on the main thread; output identical to the oracle. Not
measured: the same with the C4D UI busy at the same time (the main thread was
waiting in `join`).

## End to end (plugin code, 2026-10-02)

`flows.snapshot_save_still_core` and the watch path (`prepare_snapshot_task` →
`run_snapshot_task` in a worker) on a demo scene with `slate: true`: 0.96 s and
0.86 s, font `Inter-Regular`, `sentinel:*` metadata correct, image area equal
to the oracle (max 1 level).

## What the snapshot EXR header records (2026-10-02)

Redshift writes ~400 attributes into each RenderView snapshot's EXR header
(read with `snapshots.read_exr_attributes`, stdlib only). The ones the slate
uses: `FrameID` (int, the frame the snapshot was taken on — the document's
current frame at conversion time can differ), `capDate` (`2026:10:02 11:02:49`)
and `ocioView` (`ACES 1.0 SDR-video`); also present: `ocioDisplay`,
`ocioRenderingColorSpace`, `ocioConfig`, `FPS`, `notes` (render time, frame,
date, resolution), `name` (`Snapshot_3`).

**RenderView post — answered (2026-10-02).** Two snapshots of the same frame,
one with LUT + colour controls and one with post off, are **pixel-identical**:
the EXR holds the clean render and the post only as header attributes. Against
PNGs exported from RenderView (1100×618, exact size): the plain OCIO conversion
matches the post-off export at 0.05 levels mean (99.7 % within ±1); with post,
"LUT `Cinema Look 11.cube` at `Lut Strength` 0.492, blended after the OCIO view,
trilinear, then the master RGB curve (`curve_RGB0..3` = (0.0609, 0.0348),
(0.3261, 0.3087), (0.7478, 0.7783), (1, 1)) as a natural cubic spline clamped
outside its points" matches the LUT export at **0.75 levels mean** (80 % within
±1, max 11). Ruled out on the way: LUT only (5.6), LUT before the view (6.8),
curve before the LUT (0.89), linear / Catmull-Rom / monotone curves (2.1 / 1.5 /
0.92), tetrahedral LUT interpolation (no gain). Residual suspect: `Highlights
0.2` with colour controls on — needs an export with colour controls on, flat
curve, LUT off. Pure-Python cost: 1.55 µs/px (+2.8 s at 1080p); live in C4D,
1100×618 took 1.56 s with post vs 0.65 s without, same numbers as offline.

**Original question — RenderView post.** The header also records RV post settings,
and on the 2026-10-02 snapshots `Lut Enabled 1`, `LUT File "Cinema Look 11"`,
`Lut Strength 0.492` and `Color Controls Enabled 1` were set. Not measured:
whether the snapshot pixels already include that post, or RenderView applies
it only on display. If it is display-only, the converted PNG does not show the
LUT the artist was looking at.

## Slate style options (live, 2026-10-02)

`slate_style` through `flows.snapshot_save_still_core` on a real snapshot:
`overlay` keeps the image size (1374×772) with the bar over the bottom edge;
`below` with `badge: false` and the new tokens drew
`ACME · robot_010 · v007` / `Camera · 1374x772 · ACES 1.0 SDR-video ·
2026-10-02 11:04 · f7`, the frame taken from the EXR (7) while the document sat
on frame 0. The panel's "Preview Slate" button opened the preview in the
system viewer with the "latest snapshot" toast.

## RenderView post — refined (2026-10-02, controlled pairs)

Each pair = snapshot + RenderView *Save image* PNG taken back to back, 925×520:

| Pair | Result |
|---|---|
| colour controls on, flat curve, LUT 0 % | 0.21 mean vs plain OCIO — the RV post pipeline's own floor; `Highlights 0.2` is a Tonemapping setting, not active; a 0 % LUT is a no-op |
| curve only (LUT 0 %) | 0.21 with the natural spline — the curve model is exact |
| LUT 50 % only | 0.75 with lattice coordinate `v·(N−1)`; **0.30** with `v·N − 0.5` (GPU 3D-texture sampling, clamped) |
| LUT 50 % + curve | **0.30** (99.1 % within ±1) |
| the earlier 1100×618 LUT 49 % + curve pair | **0.30** (99.2 %) — it was never out of sync |

Ruled out for the LUT: tetrahedral interpolation, 8-bit quantised input or
output, blending the strength in linear light or gamma 2.2, other strengths.
The tell was that the shadow error (+2.7 levels) did not change with the
strength — the lookup itself, not the blend, was off.

## LUT without colour management first (Windows round 4, 2026-10-05)

Windows 11, C4D 2026.3.4, Redshift 2026.7.0. The RenderView header carried
`Apply color management before LUT = 0` (on the macOS host it was 1), so the
plan refused the LUT as "unsupported order". Pair: snapshot
`17912002770_image.exr` (LUT `acceptance_warm.cube`, size 2, 50 %, master RGB
curve, ACES 1.0 SDR-video) and the RenderView *Save image* PNG, 1026×577,
compared on the opaque pixels (alpha 255):

| Order | Mean R / G / B (levels) | Max |
|---|---|---|
| OCIO view → LUT → curve (the "on" order) | 21.1 / 18.0 / 11.0 | 41 |
| OCIO view → curve → LUT | 23.4 / 23.6 / 18.7 | 47 |
| LUT on linear → sRGB encode → curve (no view) | 25.4 / 30.6 / 30.6 | 42 |
| **LUT on scene-linear (clamped lookup, unclamped blend) → OCIO view → curve** | **0.38 / 0.23 / 0.21** | **3** |

Texel-centre sampling holds here too (corner sampling: 15.7 levels). The
background (alpha 0) matches as well: the LUT's black entry, 0.04 red at 50 %,
comes out 12 vs RenderView's 11. `rvpost.apply_lut_linear` + `apply_row` run
end to end on that EXR reproduce the same 0.38 / 0.23 / 0.21. The snapshot's
`A` channel equals the export's alpha pixel for pixel (Sentinel's PNG is RGB).

`Saturation` read 1.0 with colour controls on and the export matched with no
saturation applied: 1.0 is neutral there. The macOS header read 0.0; both are
treated as neutral until RenderView's default on macOS is confirmed. Per-channel
curves (a green curve was used) remain named, not reproduced: no export pair
isolates their order against the master curve yet.

## Alpha in the converted PNG (live, macOS C4D 2026.304, 2026-10-22)

RenderView's PNG export is RGBA and its alpha equals the snapshot EXR's `A`
pixel for pixel (Windows round 4). Measured on a synthetic EXR (alpha 1 / ramp
0.49 / 0):

| Call | Result |
|---|---|
| `GetAlphaPixel(GetInternalChannel(), x, y)` | 255 / 125 / 0 — correct, per pixel |
| channel `GetPixelCnt(…, 1, COLORMODE_GRAY)` | 255 / 125 / 0 — correct, per row |
| `GetPixelCnt(…, 16, COLORMODE_ARGBf)` on the image | A = 1.0 everywhere |
| `GetPixelCnt(…, COLORMODE_ALPHA)` | 0 everywhere |
| `Init(w, h, 32)` | no alpha channel; PNG RGB |
| `SetPixelCnt(…, COLORMODE_ARGB)` | alpha dropped |
| `AddChannel(True, False)` + channel `SetPixelCnt(…, COLORMODE_GRAY)` + `Save(…, SAVEBIT_ALPHA)` | RGBA PNG, exact; 5 ms for 1920×1080 (212 ms with `SetAlphaPixel`) |
| `Save` without `SAVEBIT_ALPHA` | RGB even with the channel |

`convert_snapshot` end to end: no slate → RGBA, alpha within 1 level of the
EXR; slate below → strip rows opaque; bar over the image → same size, bar
opaque; an EXR without `A` → RGB. `sentinel:*` text chunks insert into the
RGBA PNG unchanged. The panel's slate preview stays RGB (a draft on screen).

The linear-stage LUT was also run through `convert_exr` live on that EXR: within
1 level (mean 0.001) of `apply_lut_linear` → PyOpenColorIO → `apply_row`, and
21 levels away from the no-LUT conversion (base case).

## Channel curves and Color Controls (Windows round 5, 2026-10-22)

Windows 11, C4D 2026.4.0, Redshift 2026.7.0. Snapshot + RenderView export pairs, 2108×1186, opaque pixels:

| Pair | Sentinel's reproduction vs export (mean R / G / B, max) |
|---|---|
| C6: LUT 17³ 50 %, CM before LUT off, master curve | 0.09 / 0.33 / 1.10, max 4 |
| C7: same, CM before LUT on | 0.40 / 0.68 / 1.36, max 5 |
| C8: green curve only, before the change (named, not applied) | G max 60 |
| C8: green curve as a natural spline on the display G | 0.09 / 0.27 / 0.69, max 4 / 3 / 2 |

Blue, with a LUT, sits about 1.2 levels high in the shadows (max 2). Neither tetrahedral interpolation nor a half-float LUT explains it, and it is not chased.

RenderView's Color Controls panel (RS 2026.7) has only Contrast, the curve
channel selector with its curves, and "Apply Color Controls to Alpha". The
header's `Saturation` (1.0 on Windows, 0.0 on macOS), `Exposure (EV)`,
`Gamma`, `Hue` and `Highlights` are not RenderView post and are no longer named.
The order of a channel curve against a non-flat master curve is still
unmeasured; that combination applies the master and names the channel curve.

## C4D 2027: the scene's view is not the snapshot's (2026-10-25)

C4D 2027.0 (macOS) ships the maxon-cg v1.1 OCIO config, and a new document defaults to **"ACES 2.0 SDR-video"**. C4D 2026 used ACES 1.0 SDR-video. The view list in 2027 is ACES 2.0 SDR-video, ACES 1.0 SDR-video, Un-tone-mapped, Log and Raw.

Converting a 2026 snapshot (header `ocioView = ACES 1.0 SDR-video`) with the 2027 document's converter came out 15–37 levels mean off its RenderView export:
- the EXR loads identically in both versions;
- only the view differs.

The fix sets the view on a temporary, never-inserted document: copy `DOCUMENT_COLOR_MANAGEMENT`, `DOCUMENT_OCIO_CONFIG` and `DOCUMENT_OCIO_RENDER_COLORSPACE`, call `UpdateOcioColorSpaces()`, then set `DOCUMENT_OCIO_DISPLAY_COLORSPACE` and `DOCUMENT_OCIO_VIEW_TRANSFORM` to the indices of the recorded names in `GetOcioDisplayColorSpaceNames()` and `GetOcioViewTransformNames()`. Its `GetColorConverter()` gives the ACES 1.0 values exactly (0.5772 / 0 / 0.0316 for a sample, the same as 2026).

With it, the 2026 snapshots convert in 2027 byte-identical to 2026, and the M1/M3 RenderView pairs give the same 0.4–0.85 levels mean as in 2026.

PyOpenColorIO 2.6 with the v1.1 config does not reproduce C4D 2027's own ACES 2.0 output exactly (up to 0.22 per channel at a few sample points). That has not been chased: Sentinel always uses C4D's converter.

