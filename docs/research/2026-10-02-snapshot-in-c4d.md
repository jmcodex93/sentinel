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

**Open question — RenderView post.** The header also records RV post settings,
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
