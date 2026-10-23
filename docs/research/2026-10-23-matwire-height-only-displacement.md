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
really moves. Matwire adds no height → Bump Map.**

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
