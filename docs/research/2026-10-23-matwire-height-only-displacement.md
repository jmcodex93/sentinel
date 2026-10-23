---
module: matwire
tags: [matwire, redshift, displacement, height, bump, renderdocument]
problem_type: spike
---

# Height-only Matwire sets: does Redshift show relief with no extra setup?

Measured on C4D 2026.304, macOS (Apple M2 Max), 2026-10-23, in a fresh
`c4dpy` process on throwaway documents: scenes built by Matwire's own writer
(`create_material_for_set`), saved to a scratch folder, reloaded with
`LoadDocument` (never inserted) and rendered with `RenderDocument` on the
main thread. Nothing touched an artist's scene.

**Verdict: yes. Relief is visible on a 1-segment plane, and the geometry
really moves. Matwire adds no height → Bump Map.** A float map's convention
is now read from its pixels (section below).

## Setup

- Set: `dome_BaseColor.png` (flat grey 180) + `dome_Height.png` / `.exr`
  (512², 8×8 grid of hemispheres, black background, white peaks, no normal
  map). Built with `c4d.bitmaps`, PNG 8-bit, EXR 32-bit float.
- Plane 100×100 cm at **1×1**, **20×20** and **400×400** segments, UVW tag,
  no Redshift Object tag. Camera at 35° above the plane, 480×270.
  Distant light at 30° elevation, brightness 2.5.
- Render settings: new document defaults (Redshift is the default engine in
  2026). Recorded from the video post: **Automatic Displacement (20939) = on**,
  **Auto Bump (5806) = 2**, Global Displacement (5801) = on. The Displacement
  node keeps its default `scale = 1`.
- Variants per density: `off` (Displacement node removed), `png` (Matwire
  now: -0.5..0.5), `png01` (old Matwire: 0..1), `exr` (0..1).

## Numbers

Luma difference against `off` of the same density (0–255, whole frame;
`off` mean luma 92.3 at every density). Every render returned
`RENDERRESULT_OK` in 1–4 s.

| Plane | variant | mean abs | px > 2 levels | px > 10 levels |
|---|---|---|---|---|
| 1×1 | png | 14.97 | 40.7 % | 32.6 % |
| 1×1 | png01 | 14.32 | 39.6 % | 31.7 % |
| 1×1 | exr | 14.32 | 39.7 % | 31.8 % |
| 20×20 | png | 14.90 | 41.4 % | 32.6 % |
| 20×20 | exr | 14.25 | 40.4 % | 31.8 % |
| 400×400 | png | 15.26 | 46.1 % | 32.8 % |
| 400×400 | exr | 14.63 | 45.2 % | 31.9 % |

- **The 1-segment plane looks the same as the 400-segment one.** All 64
  domes are shaded and self-shadowed on four vertices: Automatic
  Displacement tessellates without any Redshift Object tag.
- **It is geometry, not only auto-bump**: the plane's far silhouette sits on
  row 52 for `off` and `png01` (black border = 0 displacement) and drops to
  row **53** for `png` (black border = -0.5 cm) at all three densities.
  A bump can't move a silhouette.
- `exr` (0..1) and `png01` (0..1) give identical statistics, so the 8-bit
  and float maps of the same data agree, and `png` vs `png01` differ only by
  the half-unit offset (mean 7.1–7.4 levels, from the shift of the whole
  surface).

## Consequence

Height-only sets need nothing extra in this Redshift build: Matwire keeps
wiring height → Displacement only, with the range from `height_range`. A
height → Bump Map fallback would duplicate what Auto Bump and Automatic
Displacement already do.

Not measured: scenes where the artist has switched Automatic Displacement
off, or added a Redshift Object tag with displacement disabled. There,
relief would need the tag, which is the artist's documented setting, not
Matwire's.

## Float maps: the convention is read from the pixels

The dome map above has a black background, so it validates the wiring, not
which convention real EXRs use. A float height can be a zero-centred bake
(ZBrush/Mudbox: zero = flat, negatives below) or a float copy of a 16-bit
map (mid-grey 0.5 = flat). Keeping 0..1 for every .exr inflated the second
kind by half a unit, so Matwire now samples the pixels
(`matwire_c4d.height_float_stats`, `BaseBitmap`, red channel, 256×256
stride grid) and `matwire.float_height_convention` decides:

- any value < 0 → zero-centred → **0..1**;
- wholly inside [0, 1] with |mean − 0.5| ≤ **0.1** → mid-grey → **−0.5..0.5**;
- anything else, or unreadable → **0..1**, and the preview row says the
  convention is not verified.

Tolerance: flat area dominates a height map, so a mid-grey map's mean sits
near 0.5, while a black-flat map's mean is coverage × average relief. The
dome map (64 % of its area flat black) measures **mean 0.346** (min 0,
max 0.9996) → unverified, outside the window with margin.

Live, through the panel ops on a throwaway document (`run_product_checks.py`,
64² maps written with `c4d.bitmaps`):

| Map | min / max / mean read back | row | newrange written |
|---|---|---|---|
| zero-centred EXR | −0.400 / 0.400 / 0.000 | zero_based | 0 / 1 |
| mid-grey EXR | 0.100 / 0.900 / 0.500 | centered | −0.5 / 0.5 |
| black-flat EXR | 0.000 / 1.000 / 0.197 | unverified | 0 / 1 |
| mid-grey PNG (8-bit) | not sampled | centered | −0.5 / 0.5 |

Negative values survive `BaseBitmap.InitWith` on an EXR.

**Cost** (c4dpy, M2 Max, ZIP EXRs written by C4D): 4096² → **0.40 s** cold
(0.38 s of it the load), 8192² → **1.68 s** cold (1.51 s load, ~0.17 s
sampling 65 536 values). Loading dominates; the stride makes sampling
negligible. Results are cached per (path, mtime, size), so the panel's
re-fetch on every toggle costs ~0 s after the first, and create re-reads
the file only if it changed. A noisier real 8K EXR compresses worse and
loads slower than these synthetic ones.

Limit: a regular stride can alias with a strictly periodic pattern (the
synthetic 8K map, periodic every 64 rows, sampled only its flat rows and
read a constant 0.5). Real height maps aren't periodic at the stride, but
the risk exists and is why an unclear map is flagged, not guessed.

## Harness trap: two Redshift video posts deadlock the render

The first attempt hung every render (in `c4dpy` and in the GUI through the
MCP `render` tool, which then had to be force-quit). Cause, measured: a
fresh `BaseDocument` in 2026 already carries a Redshift video post (plus
Magic Bullet Looks on this machine), and the scene builder inserted a
second one. With two, `RenderDocument` never returns: the Redshift log
shows `Context: Locked:Render`, then `PreviewScheduler: Clearing Caches`,
then `Context: Busy:Render Waiting until idle` and nothing more. The main
thread waits in `redshift4c4d.xlib` at about 1 % CPU. Escape doesn't break
it. Rendering from a `C4DThread` (main thread free) deadlocks the same way.
A good render logs a single `Locked:Render` followed by `Status: Scanning
Scene`. Before inserting a Redshift video post, look for one already there.
