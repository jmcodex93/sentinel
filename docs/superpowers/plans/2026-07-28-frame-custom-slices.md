# Sentinel Frame v2.1 — Custom Ratio + Slices (v1.29) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-tag Custom format row (W×H) and per-format render slices (Sx×Sy tiled Takes with pixel-exact windows) to Sentinel Frame v2, per the approved spec `docs/superpowers/specs/2026-07-28-frame-custom-slices-design.md`.

**Architecture:** Pure math first (`framing.slice_windows` + `framing.window_crop_values` generalize the existing crop-writer math to arbitrary windows), then the engine (`multiformat.generate_multiformat_takes` learns resolved per-tag defs + slice variants), then the tag (`frame_tag.py`: custom row params, 6-column grid, slice-aware signature/links/prune/viewing/draw), then panel/SPA reflection. Non-sliced formats stay byte-identical to v1.28 (Sx=Sy=1 takes the existing code path; only the signature gains fields → one benign adoption re-sync).

**Tech Stack:** Python 3 (C4D 2026 plugin, pure modules importable without c4d, pytest + fake-c4d harness in `tests/conftest.py`), Vite+React+TS SPA in `web/` (vitest), built bundle committed to `plugin/web/`.

**Branch:** `feat/frame-slices` (create from `main` before Task 1).

## Global Constraints

- **Takes/viewport API lessons are LAW** (`docs/solutions/logic-errors/2026-07-28-take-override-descid-and-viewport.md`): (1) never match an EXISTING override with a hand-built DescID — always resolve the stored DescID via `GetAllOverrideDescID()`; (2) `UpdateSceneNode` ONLY when `takeData.GetCurrentTake() == take`; (3) after activating a take, `_force_viewport_refresh()`. All camera writes go through the existing `multiformat._set_camera_override` / `_reset_camera_dimensions_to_native`, which already encode all three — do NOT write override-touching code outside them.
- **Never mutate the master camera's base params** — everything is per-Take overrides (v1.28 invariant).
- **No dialogs in op/sync paths** — `run_full_sync` and everything reachable from the MessageData tick or panel ops is dialog-free (`_forbid_dialog` test pattern).
- **Slice boundaries are floor-exact**: pixel boundary i = `(i·W)//Sx`; widths differ ±1 px when not divisible; sum is exact. No overlap, no padding (spec decision).
- **Slice take naming**: `<prefix>_<fmt>_sNN` (row-major, 1-based, `s%02d`). When a format has Sx·Sy > 1, its whole-format take is NOT generated (and is pruned if present).
- **Slices apply in Crop composition mode only** — in "None" the camera is uncropped so a slice window is meaningless; the engine treats slices as 1×1 there and appends a report note.
- **Sx/Sy range 1–16** (AM clamp), default 1. Custom row default: disabled, 1920×1080.
- **Existing param IDs keep their meaning forever**; new IDs only (v1.28 scenes load losslessly).
- **Do not touch `plugin/web/` by hand** — it's the committed Vite build output (`cd web && npm run build`).
- Run pytest as `python3 -m pytest tests/ -q` from the repo root; vitest as `cd web && npx vitest run`.

## File Structure

- `plugin/sentinel/framing.py` — pure: add `slice_windows`, `window_crop_values`.
- `plugin/sentinel/multiformat.py` — output-path slice suffix, slice-aware take naming, engine `format_defs` option + slice variant loop.
- `plugin/sentinel/ui/frame_tag.py` — per-tag defs (custom row), new param ids, AM grid, signature, slice links, prune, viewing, draw.
- `plugin/sentinel/safe_areas.py` — `find_active_multiformat_takes` recognizes slice families (QC #12 must keep evaluating a sliced format's FULL window).
- `plugin/sentinel/ui/panel_render_ops.py` + `panel_frame_ops.py` — `slice_count`, viewing options with slices.
- `web/src/lib/panelFrame.ts`, `web/src/types.ts`, `web/src/components/panel/FrameSubview.tsx` — SPA reflection.
- Tests: `tests/test_framing_v2.py`, `tests/test_multiformat_slices.py` (new), `tests/test_frame_tag.py`, `tests/test_panel_frame_ops.py`, `web/src/lib/panelFrame.test.ts`.

## New ID map (frame_tag.py) — locked here, all tasks use these exact values

```python
# Per-format rows: ID_FORMAT_BASE=1100, ID_FORMAT_STRIDE=20 (existing).
# Row indexes: 0..4 = MULTIFORMAT_DEFS order, 5 = Custom (CUSTOM_FORMAT_INDEX).
# _format_ids(index) gains:
#   "slice_x": base+5, "slice_y": base+6, "width": base+7, "height": base+8
#   (width/height meaningful only on the custom row, index 5 → 1207/1208)
FORMAT_ROW_COUNT = 6
CUSTOM_FORMAT_INDEX = 5
CUSTOM_FORMAT_ID = "custom"
ID_GROUP_CUSTOM = 904            # 8-column sub-grid under the formats grid
ID_PRIVATE_SLICE_LINK_BASE = 2600  # slice take BaseLinks:
MAX_SLICE_ORDINALS = 256           # id = 2600 + row_index*256 + (ordinal-1)
VIEWING_SLICE_STRIDE = 1000        # ID_VIEWING encoding for slices (see Task 5)
```

Existing id neighborhoods for reference (do not collide): 900–903 groups, 1000–1013 core, 1100–1204 format rows, 2000–2059 insets, 2400–2405 format take links, 2500–2502 private, 3000–3004 actions. New slice links occupy 2600–4135.

**Viewing/`set_viewing` target strings:** `"master"`, `"<fmt_id>"` (non-sliced), `"<fmt_id>:sNN"` (slice), e.g. `"custom:s02"`. SPA displays `custom · s02`.

---

### Task 1: Pure framing math — `slice_windows` + `window_crop_values`

**Files:**
- Modify: `plugin/sentinel/framing.py` (append after `inscribed_crop_factor`)
- Test: `tests/test_framing_v2.py` (append)

**Interfaces:**
- Produces: `framing.slice_windows(rect: Rect, sx: int, sy: int, px_w: int, px_h: int) -> list[tuple[Rect, int, int, str]]` — row-major `(sub_rect, w_px, h_px, suffix)`; suffix `""` for 1×1, else `"s01"`… Works for any linear rect convention (top-left abstract frame AND NDC-with-y-up, because it interpolates `t→b` linearly).
- Produces: `framing.window_crop_values(window: Rect, src_aspect: float, src_film: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float, float]` — `(factor, film_x, film_y)` for an ARBITRARY window in the abstract master frame `(0, 0, src_aspect, 1)`; feeds `crop_writes` unchanged. For the centered+nudged window it must equal `inscribed_crop_factor` + `nudge_to_film` exactly (parity test below).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_framing_v2.py`):

```python
# ---------------------------------------------------------------- v1.29 slices

def test_slice_windows_1x1_passthrough():
    rect = (0.0, 0.0, 16.0 / 9.0, 1.0)
    assert framing.slice_windows(rect, 1, 1, 9000, 500) == [(rect, 9000, 500, "")]


def test_slice_windows_3x1_divisible_event_screen():
    # The spec's motor case: 9000x500 in 3x1 -> three 3000x500 windows.
    rect = (0.0, 0.0, 18.0, 1.0)
    out = framing.slice_windows(rect, 3, 1, 9000, 500)
    assert [(w, h, s) for _r, w, h, s in out] == [
        (3000, 500, "s01"), (3000, 500, "s02"), (3000, 500, "s03")]
    r0, r1, r2 = out[0][0], out[1][0], out[2][0]
    assert r0 == (0.0, 0.0, 6.0, 1.0)
    assert r1 == (6.0, 0.0, 12.0, 1.0)
    assert r2 == (12.0, 0.0, 18.0, 1.0)


def test_slice_windows_non_divisible_floor_exact():
    # 100 px in 3 -> 33/33/34, boundaries floor((i)*100/3) = 0,33,66,100.
    out = framing.slice_windows((0.0, 0.0, 1.0, 1.0), 3, 1, 100, 10)
    widths = [w for _r, w, _h, _s in out]
    assert widths == [33, 33, 34]
    assert sum(widths) == 100
    # Windows are contiguous (no overlap, no gap).
    assert out[0][0][2] == out[1][0][0]
    assert out[1][0][2] == out[2][0][0]


def test_slice_windows_row_major_order_2x2():
    out = framing.slice_windows((0.0, 0.0, 2.0, 2.0), 2, 2, 200, 200)
    assert [s for _r, _w, _h, s in out] == ["s01", "s02", "s03", "s04"]
    # s01 = top-left, s02 = top-right, s03 = bottom-left (top-left convention).
    assert out[0][0] == (0.0, 0.0, 1.0, 1.0)
    assert out[1][0] == (1.0, 0.0, 2.0, 1.0)
    assert out[2][0] == (0.0, 1.0, 1.0, 2.0)


def test_slice_windows_clamps_grid_to_pixels():
    # More slices than pixels would emit 0-px windows; the grid clamps.
    out = framing.slice_windows((0.0, 0.0, 1.0, 1.0), 5, 1, 3, 10)
    assert len(out) == 3
    assert all(w >= 1 for _r, w, _h, _s in out)


def test_window_crop_values_parity_with_centered_nudge_path():
    # For the format's own (centered + nudged) window, the generalized window
    # math must reproduce inscribed_crop_factor + nudge_to_film EXACTLY —
    # this is the no-regression anchor for non-sliced formats.
    src_w, src_h, tw, th = 1920, 1080, 1080, 1920
    nudge = (0.3, -0.4)
    src_film = (0.01, -0.02)
    sa = src_w / src_h
    window = framing.format_crop_rect(src_w, src_h, tw, th, nudge)
    factor, fx, fy = framing.window_crop_values(window, sa, src_film)
    assert factor == pytest.approx(framing.inscribed_crop_factor(src_w, src_h, tw, th))
    exp_fx, exp_fy = framing.nudge_to_film(nudge, src_film[0], src_film[1],
                                           src_w, src_h, tw, th)
    assert fx == pytest.approx(exp_fx)
    assert fy == pytest.approx(exp_fy)


def test_window_crop_values_wider_target_factor_is_one():
    src_w, src_h = 1920, 1080
    window = framing.format_crop_rect(src_w, src_h, 2560, 1080, (0.0, 1.0))
    factor, _fx, fy = framing.window_crop_values(window, src_w / src_h)
    assert factor == pytest.approx(1.0)
    # Full-down nudge on 21:9 -> known travel (ta/sa - 1)/2.
    ta, sa = 2560 / 1080, 1920 / 1080
    assert fy == pytest.approx((ta / sa - 1.0) * 0.5)


def test_window_crop_values_slice_of_custom_9000x500():
    # Custom 9000x500 inside a 16:9 master, sliced 3x1: each slice window's
    # values must place the render exactly on its third of the guide.
    src_w, src_h = 1920, 1080
    sa = src_w / src_h
    fmt_window = framing.format_crop_rect(src_w, src_h, 9000, 500, None)
    slices = framing.slice_windows(fmt_window, 3, 1, 9000, 500)
    factors = []
    films_x = []
    for sub, w_px, h_px, _s in slices:
        factor, fx, fy = framing.window_crop_values(sub, sa)
        factors.append(factor)
        films_x.append(fx)
        assert fy == pytest.approx((( (sub[1] + sub[3]) * 0.5) - 0.5) / (sub[3] - sub[1]))
    # All three slices share the same crop factor (equal widths here)...
    assert factors[0] == pytest.approx(factors[1]) == pytest.approx(factors[2])
    # ...and pan left / center / right: center slice centered, edges symmetric.
    assert films_x[1] == pytest.approx(0.0)
    assert films_x[0] == pytest.approx(-films_x[2])
    assert films_x[0] < 0.0 < films_x[2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_framing_v2.py -q`
Expected: FAIL with `AttributeError: module 'sentinel.framing' has no attribute 'slice_windows'`

- [ ] **Step 3: Implement** (append to `plugin/sentinel/framing.py` after `inscribed_crop_factor`):

```python
def slice_windows(rect, sx, sy, px_w, px_h):
    """Split ``rect`` into an ``sx``×``sy`` grid of render-slice windows.

    Pixel boundaries are FLOOR-EXACT (spec v1.29 decision 4): boundary ``i``
    on the X axis is ``(i*px_w)//sx``, so slice widths differ by at most 1 px
    when ``px_w`` isn't divisible and the sum is exactly ``px_w`` — no
    overlap, no gap (physical LED panels). Returns row-major (reading order,
    top-left first) ``(sub_rect, w_px, h_px, suffix)`` tuples with 1-based
    zero-padded suffixes ``"s01"``…; a 1×1 grid returns ``[(rect, px_w,
    px_h, "")]`` so non-sliced callers stay byte-identical.

    Works in any linear rect convention — the sub-rects interpolate from
    ``(left, top)`` to ``(right, bottom)`` proportionally to the pixel
    boundaries, so both the abstract top-left frame (crop writer) and an
    NDC y-up rect passed as ``(left, top_ndc, right, bottom_ndc)`` (viewport
    cut lines) slice correctly.
    """
    sx = max(1, int(sx))
    sy = max(1, int(sy))
    px_w = max(1, int(px_w))
    px_h = max(1, int(px_h))
    sx = min(sx, px_w)  # never emit 0-px slices
    sy = min(sy, px_h)
    if sx == 1 and sy == 1:
        return [(rect, px_w, px_h, "")]

    left, top, right, bottom = rect
    xs = [(i * px_w) // sx for i in range(sx + 1)]
    ys = [(j * px_h) // sy for j in range(sy + 1)]
    out = []
    ordinal = 0
    for j in range(sy):
        for i in range(sx):
            ordinal += 1
            sub = (
                left + (right - left) * (xs[i] / float(px_w)),
                top + (bottom - top) * (ys[j] / float(px_h)),
                left + (right - left) * (xs[i + 1] / float(px_w)),
                top + (bottom - top) * (ys[j + 1] / float(px_h)),
            )
            out.append((sub, xs[i + 1] - xs[i], ys[j + 1] - ys[j],
                        "s%02d" % ordinal))
    return out


def window_crop_values(window, src_aspect, src_film=(0.0, 0.0)):
    """Return ``(factor, film_x, film_y)`` for an ARBITRARY window rect in
    the abstract master frame ``(0, 0, src_aspect, 1)`` (top-left, y down).

    Generalizes the centered+nudge pair ``inscribed_crop_factor`` +
    ``nudge_to_film`` to any anchor — same math, different anchor (spec
    v1.29): ``factor`` is the window width as a fraction of the master
    width (the sensor/aperture scale ``crop_writes`` consumes), and the
    film offsets are the window center's displacement from the master
    center in fractions of the CURRENT (cropped) gate — X relative to the
    gate width, Y relative to the gate height, exactly C4D's film-offset /
    RS sensor-shift semantics that v1.28 live-verified. Feed the result to
    ``crop_writes`` unchanged (its ``factor >= 1`` branch keeps working:
    a full-width window yields factor 1.0 → resolution-only crop + pan).
    """
    sa = max(0.0001, float(src_aspect))
    left, top, right, bottom = window
    ww = float(right) - float(left)
    wh = float(bottom) - float(top)
    if ww <= 0.0 or wh <= 0.0:
        return (1.0, float(src_film[0]), float(src_film[1]))
    factor = ww / sa
    film_x = float(src_film[0]) + (((left + right) * 0.5) - sa * 0.5) / ww
    film_y = float(src_film[1]) + (((top + bottom) * 0.5) - 0.5) / wh
    return (factor, film_x, film_y)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_framing_v2.py tests/test_framing.py -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/framing.py tests/test_framing_v2.py
git commit -m "feat(framing): slice_windows (floor-exact tiling) + window_crop_values (arbitrary-window crop)"
```

---

### Task 2: multiformat — slice-aware output paths + take naming

**Files:**
- Modify: `plugin/sentinel/multiformat.py` (`compute_format_output_path`, `_take_name_for_options`, `_existing_prefixed_format_ids`)
- Test: `tests/test_multiformat_slices.py` (create)

**Interfaces:**
- Produces: `compute_format_output_path(source_path, fmt_id, mode="subfolder", slice_suffix=None)` — subfolder: `.../<fmt>/s01/<file>`; suffix: `<file>_<fmt>_s01`. Existing 3-arg calls unchanged.
- Produces: `_take_name_for_options(fmt_def, source_take_name="", name_prefix=None, slice_suffix=None)` — appends `_s01` when given.
- Produces: `_existing_prefixed_format_ids(takeData, name_prefix, defs=None)` — accepts resolved defs (falls back to `MULTIFORMAT_DEFS`) and also matches slice-named takes (`<prefix>_<fmt>_sNN` reports fmt id).

- [ ] **Step 1: Write the failing tests** — create `tests/test_multiformat_slices.py`:

```python
import pytest


@pytest.fixture
def multiformat(sentinel_module):
    import importlib
    return importlib.import_module("sentinel.multiformat")


def test_output_path_subfolder_gains_slice_folder(multiformat):
    assert multiformat.compute_format_output_path(
        "output/$prj_$frame", "custom", "subfolder", "s01"
    ) == "output/custom/s01/$prj_$frame"


def test_output_path_suffix_gains_slice_suffix(multiformat):
    assert multiformat.compute_format_output_path(
        "output/$prj_$frame", "9x16", "suffix", "s03"
    ) == "output/$prj_$frame_9x16_s03"


def test_output_path_slice_idempotent(multiformat):
    once = multiformat.compute_format_output_path(
        "output/$prj_$frame", "16x9", "subfolder", "s02")
    again = multiformat.compute_format_output_path(once, "16x9", "subfolder", "s02")
    assert once == again == "output/16x9/s02/$prj_$frame"
    once_sfx = multiformat.compute_format_output_path(
        "output/$prj_$frame", "16x9", "suffix", "s02")
    assert multiformat.compute_format_output_path(
        once_sfx, "16x9", "suffix", "s02") == once_sfx


def test_output_path_without_slice_unchanged(multiformat):
    # Byte-identical no-slice behavior (v1.28 regression guard).
    assert multiformat.compute_format_output_path(
        "output/$prj_$frame", "16x9", "subfolder"
    ) == "output/16x9/$prj_$frame"
    assert multiformat.compute_format_output_path("", "1x1", "subfolder") == "1x1/$prj_$frame"


def test_take_name_gains_slice_suffix(multiformat):
    fmt = {"id": "custom", "width": 9000, "height": 500}
    assert multiformat._take_name_for_options(fmt, "", "Hero") == "Hero_custom"
    assert multiformat._take_name_for_options(fmt, "", "Hero", "s02") == "Hero_custom_s02"


def test_existing_prefixed_ids_matches_slice_takes(multiformat, sentinel_module):
    class T:
        def __init__(self, name):
            self._n = name
        def GetName(self):
            return self._n
        def GetDown(self):
            return None
        def GetNext(self):
            return getattr(self, "_next", None)

    class Main:
        def __init__(self, first):
            self._first = first
        def GetDown(self):
            return self._first
        def GetName(self):
            return "Main"
        def GetNext(self):
            return None

    class TD:
        def __init__(self, main):
            self._main = main
        def GetMainTake(self):
            return self._main

    a = T("Hero_custom_s01")
    b = T("Hero_9x16")
    a._next = b
    td = TD(Main(a))
    defs = [{"id": "9x16"}, {"id": "custom"}]
    assert multiformat._existing_prefixed_format_ids(td, "Hero", defs) == {"custom", "9x16"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_multiformat_slices.py -q`
Expected: FAIL (`TypeError: compute_format_output_path() takes from 2 to 3 positional arguments`).

- [ ] **Step 3: Implement.** In `compute_format_output_path`, add the `slice_suffix=None` parameter and this logic — keep the existing body for the `slice_suffix is None` path untouched; when a suffix is given, compose on top of the format result:

```python
def compute_format_output_path(source_path, fmt_id, mode="subfolder", slice_suffix=None):
    ...existing docstring (add: slice_suffix: optional "s01"-style render-slice
    suffix (v1.29). Subfolder mode nests .../<fmt>/<sNN>/...; suffix mode
    appends _<fmt>_<sNN>. Idempotent like the fmt guards.)...
    base = _compute_format_output_path_no_slice(source_path, fmt_id, mode)
    if not slice_suffix or not fmt_id:
        return base
    norm = base.replace("\\", "/")
    if "/" in norm:
        head, tail = norm.rsplit("/", 1)
    else:
        head, tail = "", norm
    if mode == "suffix":
        if tail.endswith(f"_{slice_suffix}"):
            return norm
        new_tail = f"{tail}_{slice_suffix}" if tail else f"_{slice_suffix}"
        return f"{head}/{new_tail}" if head else new_tail
    head_parts = head.split("/") if head else []
    if head_parts and head_parts[-1] == slice_suffix:
        return norm
    if head and tail:
        return f"{head}/{slice_suffix}/{tail}"
    if head:
        return f"{head}/{slice_suffix}"
    if tail:
        return f"{slice_suffix}/{tail}"
    return slice_suffix
```

Mechanically: rename the current function body to `_compute_format_output_path_no_slice(source_path, fmt_id, mode)` (private, unchanged logic) and make `compute_format_output_path` the wrapper above.

`_take_name_for_options` — add the parameter:

```python
def _take_name_for_options(fmt_def, source_take_name="", name_prefix=None, slice_suffix=None):
    """Compose the Take name, optionally scoped to a camera/tag prefix and a
    render-slice suffix (v1.29: '<prefix>_<fmt>_s01')."""
    if not fmt_def:
        return ""
    prefix = (name_prefix or "").strip()
    if prefix:
        base = f"{prefix}_{fmt_def.get('id', '')}"
    else:
        base = take_name_for_format(fmt_def, source_take_name)
    if slice_suffix:
        return f"{base}_{slice_suffix}"
    return base
```

`_existing_prefixed_format_ids` — accept defs and match slice names:

```python
def _existing_prefixed_format_ids(takeData, name_prefix, defs=None):
    """Return fmt ids for existing takes named '<prefix>_<fmt_id>' or a
    slice thereof ('<prefix>_<fmt_id>_sNN', v1.29)."""
    prefix = (name_prefix or "").strip()
    if not prefix:
        return set()
    source_defs = defs if defs is not None else MULTIFORMAT_DEFS
    name_to_id = {
        f"{prefix}_{fmt_def['id']}": fmt_def["id"] for fmt_def in source_defs
    }
    found = set()
    for take in _walk_child_takes(takeData):
        try:
            name = take.GetName() or ""
        except Exception:
            continue
        fmt_id = name_to_id.get(name)
        if fmt_id is None and "_s" in name:
            stem, _sep, tail = name.rpartition("_s")
            if tail.isdigit():
                fmt_id = name_to_id.get(stem)
        if fmt_id:
            found.add(fmt_id)
    return found
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_multiformat_slices.py tests/test_multiformat_engine_u4.py -q`
Expected: PASS (new + all existing engine tests — regression guard).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/multiformat.py tests/test_multiformat_slices.py
git commit -m "feat(multiformat): slice-aware output paths, take naming and prefixed-id detection"
```

---

### Task 3: multiformat engine — `format_defs` option + slice variant generation

**Files:**
- Modify: `plugin/sentinel/multiformat.py` (`generate_multiformat_takes`)
- Test: `tests/test_multiformat_slices.py` (append)

**Interfaces:**
- Consumes: Task 1's `framing.slice_windows`, `framing.window_crop_values`, existing `framing.crop_writes`, `framing.format_crop_rect`.
- Produces: `generate_multiformat_takes(doc, options)` learns:
  - `options["format_defs"]`: optional list of RESOLVED def dicts `{"id", "label", "width", "height", "slices": (sx, sy)}` (slices optional, default (1,1)). When present it is the def source (`formats` ids are looked up in it); when absent, behavior is exactly v1.28 (`get_multiformat_def`).
  - Callback keys: `tag_link_writer(key, take)` / `existing_take_resolver(key)` are called with `key = fmt_id` for whole-format takes (unchanged) and `key = f"{fmt_id}:{suffix}"` (e.g. `"custom:s01"`) for slice takes.
  - Report: slice take names appear in `created`/`updated`; slices in non-crop modes add a note `"slices ignored for <fmt> (composition mode is not crop)"`.
  - Slice RenderData clones are named `f"{source_rd.GetName()}_{fmt_id}_{suffix}"`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_multiformat_slices.py`). Reuse the fake harness from `tests/test_multiformat_engine_u4.py` — import its fakes rather than redefining if they are module-level classes; otherwise copy the minimal set (`FakeRenderData`, `FakeOverride`, `FakeCamera`, `FakeTake`, `FakeTakeData`, `FakeDoc`, and the fake-c4d fixture idiom). Follow that file's existing test style exactly. The test:

```python
def _run_sliced(multiformat, sentinel_module, formats, format_defs, film_offsets=None):
    # Build doc/takeData/camera fakes exactly like test_multiformat_engine_u4
    # (copy the helper construction from its generate tests).
    links = {}
    report = multiformat.generate_multiformat_takes(doc, {
        "formats": formats,
        "format_defs": format_defs,
        "composition_mode": "crop",
        "name_prefix": "Hero",
        "source_cam": cam,
        "film_offsets": film_offsets or {},
        "tag_link_writer": lambda key, take: links.__setitem__(key, take),
    })
    return report, links, doc


def test_engine_generates_slice_takes_for_custom_3x1(multiformat, sentinel_module):
    custom = {"id": "custom", "label": "Custom", "width": 9000, "height": 500,
              "slices": (3, 1)}
    report, links, doc = _run_sliced(multiformat, sentinel_module,
                                     ["custom"], [custom])
    assert report["success"] is True
    assert report["created"] == ["Hero_custom_s01", "Hero_custom_s02", "Hero_custom_s03"]
    assert set(links) == {"custom:s01", "custom:s02", "custom:s03"}
    # Each slice's RenderData: 3000x500, slice output subfolder.
    for n, key in enumerate(["custom:s01", "custom:s02", "custom:s03"], start=1):
        take = links[key]
        rd = take.GetRenderData(doc.GetTakeData())
        assert int(rd[sentinel_module.c4d.RDATA_XRES]) == 3000
        assert int(rd[sentinel_module.c4d.RDATA_YRES]) == 500
        assert f"/custom/s%02d/" % n in "/" + rd[sentinel_module.c4d.RDATA_PATH]


def test_engine_slice_camera_overrides_match_window_math(multiformat, sentinel_module):
    from sentinel import framing
    custom = {"id": "custom", "label": "Custom", "width": 9000, "height": 500,
              "slices": (3, 1)}
    report, links, doc = _run_sliced(multiformat, sentinel_module,
                                     ["custom"], [custom])
    sa = 1920.0 / 1080.0
    fmt_window = framing.format_crop_rect(1920, 1080, 9000, 500, None)
    expected = framing.slice_windows(fmt_window, 3, 1, 9000, 500)
    # Ocamera fake (aperture 36): check the s01 take's stored override params.
    take = links["custom:s01"]
    ovr = take.overrides[-1]  # harness exposes written overrides; adapt to U4 fake
    sub, _w, _h, _sfx = expected[0]
    factor, fx, fy = framing.window_crop_values(sub, sa, (0.0, 0.0))
    assert ovr.params[framing.CAMERAOBJECT_APERTURE] == pytest.approx(36.0 * factor)
    assert ovr.params[framing.CAMERAOBJECT_FILM_OFFSET_X] == pytest.approx(fx)
    assert ovr.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] == pytest.approx(fy)


def test_engine_1x1_format_defs_path_matches_legacy(multiformat, sentinel_module):
    # Passing format_defs WITHOUT slices must produce the same take names,
    # resolutions and paths as the legacy id-lookup path (v1.28 parity).
    ...build two identical docs; run once with formats=["9x16"] only, once with
    format_defs=[dict(get_multiformat_def("9x16"))]; compare report["created"],
    RD resolution and RDATA_PATH equality...


def test_engine_slices_ignored_outside_crop_mode(multiformat, sentinel_module):
    custom = {"id": "custom", "label": "Custom", "width": 9000, "height": 500,
              "slices": (3, 1)}
    ...run with composition_mode="none"...
    assert report["created"] == ["Hero_custom"]
    assert any("slices ignored" in n for n in report["notes"])
```

(Adapt fake-object access to the concrete U4 harness shapes — read `tests/test_multiformat_engine_u4.py` first and mirror how its existing tests assert on overrides and render data. Do not invent new fake shapes; the harness deliberately models the stored-DescID rigidity.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_multiformat_slices.py -q`
Expected: new tests FAIL (unknown format "custom" / missing slice takes).

- [ ] **Step 3: Implement in `generate_multiformat_takes`.** Changes, keeping the existing loop structure:

1. After reading options, resolve the def source:

```python
format_defs_opt = options.get("format_defs")
def _resolve_def(fmt_id):
    if format_defs_opt:
        for d in format_defs_opt:
            if d.get("id") == fmt_id:
                return d
        return None
    return get_multiformat_def(fmt_id)
```

Use `_resolve_def(fmt_id)` where the loop currently calls `get_multiformat_def(fmt_id)`, and pass the defs to orphan reporting: `report["orphaned"] = sorted(_existing_prefixed_format_ids(td, name_prefix, format_defs_opt) - requested_formats)`.

2. Inside the per-format loop, compute the slice variants and wrap the ENTIRE existing take-creation body (name lookup → create/adopt → render data → SetCamera → resolution/path → camera overrides → report/created → tag_link_writer) in an inner `for` over variants:

```python
sx, sy = 1, 1
raw_slices = fmt_def.get("slices") or (1, 1)
try:
    sx, sy = max(1, int(raw_slices[0])), max(1, int(raw_slices[1]))
except Exception:
    sx, sy = 1, 1
tw, th = int(fmt_def["width"]), int(fmt_def["height"])
if (sx * sy) > 1 and composition_mode != COMPOSITION_MODE_CROP:
    report["notes"].append(
        f"slices ignored for {fmt_id} (composition mode is not crop)")
    sx, sy = 1, 1
if sx * sy > 1:
    fmt_window = framing.format_crop_rect(
        src_w, src_h, tw, th, film_offsets.get(fmt_id))
    variants = [
        {"suffix": sfx, "window": sub, "width": w_px, "height": h_px,
         "key": f"{fmt_id}:{sfx}"}
        for sub, w_px, h_px, sfx in framing.slice_windows(
            fmt_window, sx, sy, tw, th)
    ]
else:
    variants = [{"suffix": None, "window": None, "width": tw, "height": th,
                 "key": fmt_id}]

for variant in variants:
    take_name = _take_name_for_options(
        fmt_def, report["source_take_name"], name_prefix, variant["suffix"])
    ...existing body, with these substitutions...
```

Substitutions inside the body (each is a small, mechanical edit of the existing code):
- `existing_take_resolver(fmt_id)` → `existing_take_resolver(variant["key"])`.
- `expected_rd_name = f"{source_rd.GetName()}_{fmt_id}"` → append `_{variant['suffix']}` when suffix is set:
  `expected_rd_name = f"{source_rd.GetName()}_{fmt_id}" + (f"_{variant['suffix']}" if variant["suffix"] else "")` (and the same name at `SetName`).
- Resolution writes use `variant["width"]` / `variant["height"]` instead of `fmt_def[...]`.
- Output path: `compute_format_output_path(src_path, fmt_id, output_mode, variant["suffix"])`.
- Camera overrides: in the `COMPOSITION_MODE_CROP` branch, when `variant["window"] is not None`, replace the factor/nudge computation with the window math (everything else — kind detection, sensor/src-film reads, `_reset_camera_dimensions_to_native`, `_set_camera_override` loop — identical):

```python
if variant["window"] is not None:
    factor, film_x, film_y = framing.window_crop_values(
        variant["window"], src_w / float(src_h),
        (crop_src_film[0], crop_src_film[1]))
    nudge_film = (film_x, film_y)
else:
    factor = framing.inscribed_crop_factor(src_w, src_h, tw, th)
    nudge_film = framing.nudge_to_film(
        nudge, crop_src_film[0], crop_src_film[1], src_w, src_h, tw, th)
for pid, val in framing.crop_writes(
        kind, src_aperture, sensor, factor, nudge_film, crop_src_film):
    _set_camera_override(take, td, source_cam, pid, val)
```

- `tag_link_writer(fmt_id, take)` → `tag_link_writer(variant["key"], take)`.

The no-slice path must remain BYTE-IDENTICAL in behavior: single variant, `suffix=None`, `key=fmt_id`, window `None` → all substitutions degrade to the previous expressions.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_multiformat_slices.py tests/test_multiformat_engine_u4.py -q`
Expected: PASS — the U4 suite green is the v1.28 no-regression proof.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/multiformat.py tests/test_multiformat_slices.py
git commit -m "feat(multiformat): engine slice variants via format_defs option (window-anchored crop writes)"
```

---

### Task 4: frame_tag — custom row + slice params (defs, Init, AM description, signature)

**Files:**
- Modify: `plugin/sentinel/ui/frame_tag.py`
- Test: `tests/test_frame_tag.py` (append)

**Interfaces:**
- Consumes: nothing new from other tasks (this is param/description layer only).
- Produces (used by Tasks 5–8):
  - Constants from the ID map at the top of this plan (`FORMAT_ROW_COUNT`, `CUSTOM_FORMAT_INDEX`, `CUSTOM_FORMAT_ID`, `ID_GROUP_CUSTOM`, `ID_PRIVATE_SLICE_LINK_BASE`, `MAX_SLICE_ORDINALS`, `VIEWING_SLICE_STRIDE`).
  - `_format_ids(index)` gains keys `"slice_x"`, `"slice_y"`, `"width"`, `"height"` (base+5..base+8).
  - `_format_defs(node=None)` — 5 standard defs (canonical dicts, NEVER mutated) + a FRESH custom def dict `{"id": "custom", "label": "Custom", "width": W, "height": H}` appended when `node` is given and the custom row is enabled.
  - `_as_int(value, default)` module helper.
  - `_slices_for_index(node, index) -> (sx, sy)` (clamped 1–16, default (1,1)).
  - `_engine_format_defs(node) -> list[dict]` — resolved defs for the engine: shallow COPIES of `_format_defs(node)` entries with `"slices": (sx, sy)` injected.
  - `_total_slice_count(node) -> int` — `sum(sx*sy for enabled formats where sx*sy > 1)`.
  - Signature payload per enabled format gains `"slices": [sx, sy]`; the custom entry additionally gains `"size": [W, H]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_frame_tag.py`; tag fakes are plain dicts as in the existing tests):

```python
def _base_tag(frame_tag, enabled_indexes=(0,)):
    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_CROP}
    for index in range(frame_tag.FORMAT_ROW_COUNT):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = index in enabled_indexes
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0
        tag[ids["slice_x"]] = 1
        tag[ids["slice_y"]] = 1
    return tag


def test_format_defs_without_node_are_the_five_standard(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    assert [d["id"] for d in frame_tag._format_defs()] == [
        "16x9", "9x16", "1x1", "4x5", "21x9"]


def test_format_defs_include_custom_when_enabled(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0, frame_tag.CUSTOM_FORMAT_INDEX))
    ids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[ids["width"]] = 9000
    tag[ids["height"]] = 500
    defs = frame_tag._format_defs(tag)
    assert defs[-1] == {"id": "custom", "label": "Custom", "width": 9000, "height": 500}
    # Disabled custom -> absent.
    tag[ids["enabled"]] = False
    assert [d["id"] for d in frame_tag._format_defs(tag)] == [
        "16x9", "9x16", "1x1", "4x5", "21x9"]
    # Canonical standard defs are never mutated by per-tag resolution.
    from sentinel.multiformat import MULTIFORMAT_DEFS
    assert "slices" not in MULTIFORMAT_DEFS[0]


def test_engine_format_defs_inject_slices(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(1, frame_tag.CUSTOM_FORMAT_INDEX))
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    tag[cids["slice_x"]] = 3
    defs = frame_tag._engine_format_defs(tag)
    by_id = {d["id"]: d for d in defs}
    assert by_id["custom"]["slices"] == (3, 1)
    assert by_id["9x16"]["slices"] == (1, 1)
    assert frame_tag._total_slice_count(tag) == 3


def test_signature_changes_with_slices_and_custom_size(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0, frame_tag.CUSTOM_FORMAT_INDEX))
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    base_sig = frame_tag._params_signature_for_takes(dict(tag))
    tag[frame_tag._format_ids(0)["slice_x"]] = 2
    assert frame_tag._params_signature_for_takes(dict(tag)) != base_sig
    tag[frame_tag._format_ids(0)["slice_x"]] = 1
    tag[cids["width"]] = 9001
    assert frame_tag._params_signature_for_takes(dict(tag)) != base_sig


def test_slices_default_to_1x1_for_v128_tags(sentinel_module):
    # A v1.28 scene has NO slice/custom params stored: defaults must resolve
    # to slices (1,1) and custom disabled, i.e. the same defs as before.
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = {frame_tag.ID_COMPOSITION: frame_tag.COMPOSITION_CROP}
    for index in range(5):
        ids = frame_tag._format_ids(index)
        tag[ids["enabled"]] = True
        tag[ids["nudge_x"]] = 0.0
        tag[ids["nudge_y"]] = 0.0
    assert [d["id"] for d in frame_tag._format_defs(tag)] == [
        "16x9", "9x16", "1x1", "4x5", "21x9"]
    assert all(d["slices"] == (1, 1) for d in frame_tag._engine_format_defs(tag))
    assert frame_tag._slices_for_index(tag, 0) == (1, 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_frame_tag.py -q`
Expected: new tests FAIL (`AttributeError: FORMAT_ROW_COUNT`).

- [ ] **Step 3: Implement in `plugin/sentinel/ui/frame_tag.py`:**

1. Add the constants from the plan's ID map (after `ID_FORMAT_STRIDE`), and `_FORMAT_COLORS["custom"] = (0.35, 0.95, 0.55)`.

2. `_format_ids` — add the four keys:

```python
def _format_ids(index):
    base = ID_FORMAT_BASE + (index * ID_FORMAT_STRIDE)
    return {
        "group": base,
        "enabled": base + 1,
        "color": base + 2,
        "nudge_x": base + 3,
        "nudge_y": base + 4,
        "slice_x": base + 5,
        "slice_y": base + 6,
        "width": base + 7,   # custom row only
        "height": base + 8,  # custom row only
    }
```

3. Add `_as_int` next to `_as_float`:

```python
def _as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)
```

4. `_format_defs(node=None)`:

```python
def _format_defs(node=None):
    """Canonical defs — the 5 standard entries plus, when ``node`` is given
    and its Custom row is enabled, a FRESH custom def dict (v1.29). The
    standard entries are the shared MULTIFORMAT_DEFS dicts and must never be
    mutated; the custom def is rebuilt per call from the tag params."""
    defs = []
    for fmt in MULTIFORMAT_DEFS:
        canonical = get_multiformat_def(fmt.get("id"))
        if canonical:
            defs.append(canonical)
    if node is not None:
        custom = _custom_def_from_params(node)
        if custom is not None:
            defs.append(custom)
    return defs


def _custom_def_from_params(node):
    ids = _format_ids(CUSTOM_FORMAT_INDEX)
    if not _as_bool(_get_node_value(node, ids["enabled"], False), False):
        return None
    width = max(16, _as_int(_get_node_value(node, ids["width"], 1920), 1920))
    height = max(16, _as_int(_get_node_value(node, ids["height"], 1080), 1080))
    return {"id": CUSTOM_FORMAT_ID, "label": "Custom",
            "width": width, "height": height}
```

**CRITICAL default:** the custom row's `enabled` default is `False` everywhere (`_as_bool(..., False)`), unlike the standard rows' `True` — a v1.28 tag with no stored custom params must NOT sprout a custom format. Audit EVERY `_as_bool(_get_node_value(node, ids["enabled"], True), True)` call site: they iterate `_format_defs(node)` whose last entry only exists when custom is enabled, so the `True` default stays correct for the standard rows — but any loop that iterates `range(FORMAT_ROW_COUNT)` (new code) must use `True` for indexes 0–4 and `False` for index 5. Add a helper and use it in all new code:

```python
def _row_enabled(node, index):
    default = index != CUSTOM_FORMAT_INDEX
    return _as_bool(_get_node_value(node, _format_ids(index)["enabled"], default), default)
```

5. Thread `node` through the def-iterating helpers. Change these signatures/bodies to call `_format_defs(node)` (mechanical; each already receives the node): `_enabled_format_entries`, `_format_index_for_id(fmt_id, node=None)`, `_enabled_format_ids_from_params`, `_film_offsets_from_params`, `_params_payload_for_takes`, `_viewing_cycle_entries`, `_viewing_value_from_takes`, `_activate_viewing`, `set_viewing`, `_find_orphaned_takes_for_tag`, `_current_take_is_own_format`, `_current_own_format_id`, and the Draw label loop (`label_defs = _format_defs(tag)`). `_write_platform_insets_to_node` / `_standard_platform_insets_by_format` / `_resolved_platform_insets_by_format` keep iterating the 5 standard defs plus custom: change them to iterate `range(FORMAT_ROW_COUNT)` with id resolution `MULTIFORMAT_DEFS[index]["id"] if index < 5 else CUSTOM_FORMAT_ID` (custom insets default to zeros via `SAFE_AREA_INSETS.get("custom") → None`).

6. Slice/engine helpers:

```python
def _slices_for_index(node, index):
    ids = _format_ids(index)
    sx = max(1, min(16, _as_int(_get_node_value(node, ids["slice_x"], 1), 1)))
    sy = max(1, min(16, _as_int(_get_node_value(node, ids["slice_y"], 1), 1)))
    return (sx, sy)


def _engine_format_defs(node):
    """Resolved defs for the multiformat engine: enabled formats only is NOT
    the contract here — the engine filters by options['formats']; this returns
    ALL per-tag defs (5 standard + custom-if-enabled) as shallow copies with
    the per-row slice grid injected."""
    out = []
    for index, fmt in enumerate(_format_defs(node)):
        d = dict(fmt)
        d["slices"] = _slices_for_index(node, index)
        out.append(d)
    return out


def _total_slice_count(node):
    total = 0
    for index, fmt in enumerate(_format_defs(node)):
        if not _row_enabled(node, index):
            continue
        sx, sy = _slices_for_index(node, index)
        if sx * sy > 1:
            total += sx * sy
    return total
```

7. `_params_payload_for_takes` — per enabled format append slices, and size for custom:

```python
entry = {
    "id": fmt.get("id"),
    "nudge": [...existing...],
    "slices": list(_slices_for_index(node, index)),
}
if fmt.get("id") == CUSTOM_FORMAT_ID:
    entry["size"] = [int(fmt.get("width", 0)), int(fmt.get("height", 0))]
formats.append(entry)
```

8. `_format_param_map()` / `_FORMAT_PARAM_TO_ENABLE` — must cover all 6 rows and the new per-row params regardless of custom state (it gates AM enabling). Rebuild from row count, not defs:

```python
def _format_param_map():
    mapping = {}
    for index in range(FORMAT_ROW_COUNT):
        ids = _format_ids(index)
        for key in ("color", "nudge_x", "nudge_y", "slice_x", "slice_y",
                    "width", "height"):
            mapping[ids[key]] = ids["enabled"]
    return mapping
```

9. `Init` — extend the per-format loop to `range(FORMAT_ROW_COUNT)` (resolve color id per row: `MULTIFORMAT_DEFS[index]["id"]` for 0–4, `"custom"` for 5) and initialize: `slice_x`/`slice_y` = 1 (int attrs), and on the custom row `enabled=False`, `width=1920`, `height=1080` (int attrs), color `_FORMAT_COLORS["custom"]`, nudges 0.

10. `GetDDescription` — formats grid goes to 6 columns and each standard row appends Sx/Sy; custom row lives in its own 8-column sub-grid:

```python
if not self._set_description_group(
    node, description, ID_GROUP_FORMATS, "Formats", main_group,
    columns=6, titlebar=False
):
    return False
...per standard row (indexes 0..4), after nudge_y add:
    if not self._set_description_parameter(
        node, description, ids["slice_x"], c4d.DTYPE_LONG, "Sx", formats_group, 1, 16, 1
    ):
        return False
    if not self._set_description_parameter(
        node, description, ids["slice_y"], c4d.DTYPE_LONG, "Sy", formats_group, 1, 16, 1
    ):
        return False

# Custom row (spec: own 8-column sub-grid under the main grid; W/H need two
# extra cells so the shared 6-column widths can't apply — accepted deviation).
custom_group = _description_parent(ID_GROUP_CUSTOM, c4d.DTYPE_GROUP, node)
if not self._set_description_group(
    node, description, ID_GROUP_CUSTOM, "Custom", main_group,
    columns=8, titlebar=False
):
    return False
cids = _format_ids(CUSTOM_FORMAT_INDEX)
for pid, dtype, name, lo, hi, st in (
    (cids["enabled"], c4d.DTYPE_BOOL, "Custom", None, None, None),
    (cids["color"], color_dtype, "", None, None, None),
    (cids["width"], c4d.DTYPE_LONG, "W", 16, 16384, 1),
    (cids["height"], c4d.DTYPE_LONG, "H", 16, 16384, 1),
    (cids["nudge_x"], c4d.DTYPE_REAL, "X", -1.0, 1.0, 0.01),
    (cids["nudge_y"], c4d.DTYPE_REAL, "Y", -1.0, 1.0, 0.01),
    (cids["slice_x"], c4d.DTYPE_LONG, "Sx", 1, 16, 1),
    (cids["slice_y"], c4d.DTYPE_LONG, "Sy", 1, 16, 1),
):
    if not self._set_description_parameter(
        node, description, pid, dtype, name, custom_group, lo, hi, st
    ):
        return False
```

**Percent-unit guard:** `_set_description_parameter` currently stamps `DESC_UNIT_PERCENT` on every `DTYPE_REAL` except `ID_LINE_WIDTH` — the new LONG params are unaffected, but verify no REAL is added here (W/H/Sx/Sy are LONG).

11. `Message` focus-format span: replace `span = len(_format_defs()) * ID_FORMAT_STRIDE` with `span = FORMAT_ROW_COUNT * ID_FORMAT_STRIDE` (so touching custom W/H/Sx/Sy focuses the custom row).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_frame_tag.py tests/test_panel_frame_ops.py tests/test_panel_render_ops.py -q`
Expected: PASS (existing suites exercise the threaded-node signatures; fix any call site the type change surfaces — the default `node=None` keeps old 0-arg calls valid).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/frame_tag.py tests/test_frame_tag.py
git commit -m "feat(frame-tag): custom format row + per-format slice params (defs, Init, AM grid, signature)"
```

---

### Task 5: frame_tag — slice-aware sync, links, prune, viewing, own-take detection

**Files:**
- Modify: `plugin/sentinel/ui/frame_tag.py`
- Test: `tests/test_frame_tag.py` (append)

**Interfaces:**
- Consumes: Task 3's engine (`format_defs` option, `key`-based callbacks), Task 4's helpers.
- Produces:
  - `_slice_link_id(index, ordinal) -> int` (`2600 + index*256 + (ordinal-1)`; ordinal 1-based).
  - `_write_link_for_key(node, key, take)` / `_read_link_for_key(node, key, doc)` — `key` = `fmt_id` or `"fmt:sNN"`; dispatch to the existing per-format link (2400+index, unchanged) or the slice link.
  - `_parse_own_format_suffix(suffix, defs) -> tuple[str, str | None] | None` — pure: `"custom"` → `("custom", None)`, `"custom_s02"` → `("custom", "s02")`, unknown → `None`.
  - `_current_own_take_info(tag, doc) -> tuple[str, str | None] | None` (replaces the internals of `_current_own_format_id`, which becomes `info[0] if info else None`).
  - `viewing_targets(node) -> list[str]` — `["master", "16x9", "custom:s01", ...]` in cycle order (Task 8's panel source).
  - `set_viewing(doc, tag, target)` accepts `"fmt:sNN"` targets.
  - `_run_takes_generation` passes `format_defs=_engine_format_defs(node)` and key-based callbacks; `_find_orphaned_takes_for_tag` returns `(key, take)` pairs covering: disabled formats (whole + slices), whole-format take of a now-sliced format, slice takes not in the current grid, disabled custom.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_frame_tag.py`):

```python
def test_parse_own_format_suffix(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    defs = [{"id": "9x16"}, {"id": "custom"}]
    assert frame_tag._parse_own_format_suffix("9x16", defs) == ("9x16", None)
    assert frame_tag._parse_own_format_suffix("custom_s02", defs) == ("custom", "s02")
    assert frame_tag._parse_own_format_suffix("custom", defs) == ("custom", None)
    assert frame_tag._parse_own_format_suffix("foo", defs) is None
    assert frame_tag._parse_own_format_suffix("9x16_s2x", defs) is None


def test_slice_link_ids_disjoint_per_format(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    ids = {frame_tag._slice_link_id(i, o)
           for i in range(frame_tag.FORMAT_ROW_COUNT)
           for o in range(1, 257)}
    assert len(ids) == frame_tag.FORMAT_ROW_COUNT * 256
    assert min(ids) == frame_tag.ID_PRIVATE_SLICE_LINK_BASE
    # Never collides with the existing private id neighborhoods.
    assert all(i not in (2400, 2401, 2402, 2403, 2404, 2405, 2500, 2501, 2502)
               for i in ids)


def test_link_for_key_roundtrip(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0,))
    frame_tag._write_link_for_key(tag, "16x9", "TAKE_WHOLE")
    frame_tag._write_link_for_key(tag, "16x9:s03", "TAKE_S3")
    assert frame_tag._read_link_for_key(tag, "16x9", None) == "TAKE_WHOLE"
    assert frame_tag._read_link_for_key(tag, "16x9:s03", None) == "TAKE_S3"
    assert frame_tag._read_link_for_key(tag, "16x9:s04", None) is None


def test_viewing_targets_list_slices(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    tag = _base_tag(frame_tag, enabled_indexes=(0, frame_tag.CUSTOM_FORMAT_INDEX))
    cids = frame_tag._format_ids(frame_tag.CUSTOM_FORMAT_INDEX)
    tag[cids["width"]] = 9000
    tag[cids["height"]] = 500
    tag[cids["slice_x"]] = 3
    assert frame_tag.viewing_targets(tag) == [
        "master", "16x9", "custom:s01", "custom:s02", "custom:s03"]
```

Also extend `test_current_take_is_own_format_gates_guides_in_format_takes` with a slice take: `FakeTake("Hero_16x9_s02")` must be detected as own-format (guides suppressed) and `_current_own_take_info` must return `("16x9", "s02")`.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_frame_tag.py -q`
Expected: new tests FAIL.

- [ ] **Step 3: Implement:**

1. Link plumbing:

```python
def _slice_link_id(index, ordinal):
    return ID_PRIVATE_SLICE_LINK_BASE + index * MAX_SLICE_ORDINALS + (int(ordinal) - 1)


def _split_key(key):
    """'custom:s02' -> ('custom', 's02'); 'custom' -> ('custom', None)."""
    if ":" in (key or ""):
        fmt_id, _sep, sfx = key.partition(":")
        return fmt_id, sfx
    return key, None


def _ordinal_from_suffix(suffix):
    try:
        return int(str(suffix)[1:])
    except Exception:
        return None
```

`_write_link_for_key` / `_read_link_for_key`: split the key; suffix `None` → delegate to the existing `_write_take_link` / `_read_take_link` (with `_format_index_for_id(fmt_id, node)`); suffix set → same BaseLink store/read idiom as `_write_take_link`/`_read_take_link` but at `_slice_link_id(index, ordinal)`. Factor the BaseLink wrap/unwrap into tiny shared helpers `_store_link(bc, key_id, take)` / `_load_link(bc, key_id, doc)` extracted from the existing pair rather than duplicating.

2. `_run_takes_generation` — options gain `"format_defs": _engine_format_defs(node)`, and the callbacks become key-based:

```python
"tag_link_writer": lambda key, take: _tag_link_writer(key, take),  # writer body calls _write_link_for_key(node, key, take)
"existing_take_resolver": lambda key: _read_link_for_key(node, key, doc),
```

(The undo-anchor bookkeeping inside `_tag_link_writer` stays exactly as is.)

3. `_parse_own_format_suffix` (pure):

```python
def _parse_own_format_suffix(suffix, defs):
    ids = {d.get("id") for d in defs}
    if suffix in ids:
        return (suffix, None)
    stem, sep, tail = suffix.rpartition("_s")
    if sep and stem in ids and tail.isdigit():
        return (stem, "s" + tail)
    return None
```

`_current_own_take_info(tag, doc)`: refactor `_current_own_format_id`'s body to call `_parse_own_format_suffix(suffix, _format_defs(tag))` and return the tuple; `_current_own_format_id` returns `info[0] if info else None`; `_current_take_is_own_format` returns `info is not None`. (One resolution path, three thin views — delete the duplicated body.)

4. Viewing:

```python
def _viewing_entry_pairs(node):
    """[(value, target_str, label)] for the cycle/panel — one source.
    value: index+1 for whole formats; (index+1)*VIEWING_SLICE_STRIDE + ordinal
    for slices (stable against enable churn)."""
    pairs = []
    for index, fmt in enumerate(_format_defs(node)):
        if not _row_enabled(node, index):
            continue
        fmt_id = fmt.get("id")
        sx, sy = _slices_for_index(node, index)
        if sx * sy > 1:
            for ordinal in range(1, sx * sy + 1):
                sfx = "s%02d" % ordinal
                pairs.append(((index + 1) * VIEWING_SLICE_STRIDE + ordinal,
                              f"{fmt_id}:{sfx}",
                              f"{fmt.get('label') or fmt_id} · {sfx}"))
        else:
            pairs.append((index + 1, fmt_id, fmt.get("label") or fmt_id))
    return pairs


def viewing_targets(node):
    return ["master"] + [target for _v, target, _l in _viewing_entry_pairs(node)]
```

`_viewing_cycle_entries` = `[(0, "Master")] + [(value, label) ...]` from the pairs. `_activate_viewing`: values `>= VIEWING_SLICE_STRIDE` decode `index = value // VIEWING_SLICE_STRIDE - 1`, `ordinal = value % VIEWING_SLICE_STRIDE`, resolve via `_read_link_for_key(node, f"{defs[index]['id']}:s%02d" % ordinal, doc)`; keep the `SetCurrentTake` + `_event_add` + `_force_viewport_refresh` tail identical (viewport lesson #3). `_viewing_value_from_takes`: after the existing per-format link check, check slice links for sliced formats. `set_viewing`: accept slice targets by matching against `viewing_targets(tag)`; map target → value via `_viewing_entry_pairs`.

5. Prune — rewrite `_find_orphaned_takes_for_tag(node, doc)` around an EXPECTED-set:

```python
def _expected_take_names(node):
    host = _tag_host(node)
    prefix = _safe_node_name(host, "")
    expected = {}
    if not prefix:
        return expected
    for index, fmt in enumerate(_format_defs(node)):
        if not _row_enabled(node, index):
            continue
        fmt_id = fmt.get("id")
        sx, sy = _slices_for_index(node, index)
        if sx * sy > 1:
            for ordinal in range(1, sx * sy + 1):
                sfx = "s%02d" % ordinal
                expected[f"{prefix}_{fmt_id}_{sfx}"] = f"{fmt_id}:{sfx}"
        else:
            expected[f"{prefix}_{fmt_id}"] = fmt_id
    return expected
```

Orphans = takes owned by this tag that are NOT expected: (a) name-walk every child take whose name parses as `<prefix>_<suffix>` with `_parse_own_format_suffix(suffix, all_defs)` where `all_defs` = the 5 standard + `{"id": "custom"}` UNCONDITIONALLY (a disabled custom's takes must still be found); (b) link-walk: the 6 per-format links plus every slice link (`for index in range(FORMAT_ROW_COUNT): for ordinal in range(1, MAX_SLICE_ORDINALS + 1)` — BC misses are cheap dict lookups; break early per format after 16×16=256 anyway). Keep the existing dedupe-by-name and return `(key, take)` pairs; `_prune_orphaned_takes` clears links via `_write_link_for_key(node, key, None)` and keeps its Viewing guard (never delete the ACTIVE take without falling back to Main first) byte-identical.

Add a prune test with dict-tag + fake doc/takes: enable 16x9 with slices 2×1 → `_expected_take_names` lists `Hero_16x9_s01/s02`; a `FakeTake("Hero_16x9")` (the old whole take) and a `FakeTake("Hero_16x9_s03")` in the walk must both come back as orphans; `Hero_16x9_s02` must not.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_frame_tag.py tests/test_frame_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/frame_tag.py tests/test_frame_tag.py
git commit -m "feat(frame-tag): slice-aware sync wiring, take links, prune, viewing and own-take detection"
```

---

### Task 6: Viewport draw — cut lines, slice numbering, slice-take HUD

**Files:**
- Modify: `plugin/sentinel/ui/frame_tag.py` (`_compute_inline_rects`, `Draw`)
- Test: `tests/test_frame_tag.py` (append — pure parts only; the draw itself is live-verified)

**Interfaces:**
- Consumes: `framing.slice_windows` (Task 1), `_slices_for_index` / `_current_own_take_info` (Tasks 4–5).
- Produces: `_compute_inline_rects` entries gain `"slices": (sx, sy)`; new pure helper `_slice_cut_segments(guide: dict, sx, sy, px_w, px_h) -> list[tuple[p1, p2]]` returning INTERNAL boundary segments in NDC dict-space endpoints `((x1, y1), (x2, y2))`.

- [ ] **Step 1: Write the failing test:**

```python
def test_slice_cut_segments_internal_boundaries_only(sentinel_module):
    import importlib
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    guide = {"left": -0.9, "right": 0.9, "bottom": -0.1, "top": 0.1}
    segs = frame_tag._slice_cut_segments(guide, 3, 1, 9000, 500)
    # 3x1 -> exactly 2 internal vertical cuts, spanning top..bottom.
    assert len(segs) == 2
    xs = sorted(p1[0] for p1, _p2 in segs)
    assert xs[0] == pytest.approx(-0.3)
    assert xs[1] == pytest.approx(0.3)
    for (x1, y1), (x2, y2) in segs:
        assert x1 == x2
        assert {y1, y2} == {pytest.approx(0.1), pytest.approx(-0.1)}
    assert frame_tag._slice_cut_segments(guide, 1, 1, 100, 100) == []
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_frame_tag.py -q` → FAIL.

- [ ] **Step 3: Implement:**

```python
def _slice_cut_segments(guide, sx, sy, px_w, px_h):
    """Internal slice boundaries of a guide rect (NDC dict) as endpoint
    pairs. Reuses framing.slice_windows' floor-exact boundaries by passing
    the rect as (left, top, right, bottom) — linear interpolation makes the
    y-up NDC convention transparent."""
    windows = framing.slice_windows(
        (guide["left"], guide["top"], guide["right"], guide["bottom"]),
        sx, sy, px_w, px_h)
    if len(windows) <= 1:
        return []
    xs = sorted({round(w[0][0], 9) for w in windows} | {round(w[0][2], 9) for w in windows})
    ys = sorted({round(w[0][1], 9) for w in windows} | {round(w[0][3], 9) for w in windows})
    segs = []
    for x in xs[1:-1]:
        segs.append(((x, guide["top"]), (x, guide["bottom"])))
    for y in ys[1:-1]:
        segs.append(((guide["left"], y), (guide["right"], y)))
    return segs
```

In `_compute_inline_rects`, add to each entry: `"slices": _slices_for_index(node, index)` (node is already in scope).

In `Draw`:

1. **Cut lines** (inside the `show_guides` block, after `_draw_rect` of each guide): when `entry["slices"][0] * entry["slices"][1] > 1`, draw each segment of `_slice_cut_segments(entry["guide"], sx, sy, entry["width"], entry["height"])` converted to pixels (reuse `_ndc_rect_to_pixels`' linear mapping — add a tiny point mapper `_ndc_point_to_pixels((x, y), safe_frame)` factored from it) via `_draw_dashed_line(bd, p1, p2, 1)` with the same (possibly dimmed) color the guide used.

2. **Slice numbering** (inside the `show_hud` block): ONLY when the format is focused (`entry["id"] == label_focus_fmt`) or exactly one format is enabled (`len(pixel_guides) == 1`) — spec's noise rule. For each slice window from `framing.slice_windows((g["left"], g["top"], g["right"], g["bottom"]), sx, sy, w, h)`, draw `_draw_hud_text(bd, px + 4, py + 4, "s%d" % ordinal)` at the window's top-left pixel corner (ordinal from the returned suffix, rendered short: `s1`…`sN` per spec).

3. **Slice-take HUD**: replace the `own_fmt = _current_own_format_id(tag, doc)` block with `info = _current_own_take_info(tag, doc)`; when `info` is `(fmt_id, sfx)` with `sfx`, the HUD line reads `"Viewing: %s %s  %dx%d  %s" % (fmt_id, sfx, w_px, h_px, _sync_status_text(tag))` where the slice dims come from re-running `framing.slice_windows((0,0,1,1), sx, sy, tw, th)` for the tag's def (helper `_slice_dims(node, fmt_id, suffix)` → `(w_px, h_px)` or the format dims when suffix is None). The `get_multiformat_def(own_fmt)` call must go through the per-tag defs (`next((d for d in _format_defs(tag) if d["id"] == fmt_id), {})`) so `custom` resolves.

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_frame_tag.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/frame_tag.py tests/test_frame_tag.py
git commit -m "feat(frame-tag): slice cut guides, slice numbering and slice-take HUD in viewport draw"
```

---

### Task 7: QC #12 — slice families still count as delivery Takes

**Files:**
- Modify: `plugin/sentinel/safe_areas.py` (`find_active_multiformat_takes`)
- Test: `tests/test_safe_area_math_helpers.py` (append; check the fixture idiom used there first)

**Interfaces:**
- Produces: `find_active_multiformat_takes(doc)` also matches `..._<fmt>_sNN` take names and returns ONE entry per (fmt_id, family): the first slice take found represents the family. Downstream QC #12 evaluates the format's FULL window from `fmt_id` + master projection (spec: slicing is render packaging, not framing), so the representative take only feeds naming/reporting — verify with `grep -n "mf_takes" plugin/sentinel/safe_areas.py` that the take object is not used to derive the format window (it is not; the window comes from `format_safe_area_in_master_ndc(fmt_id, master_aspect, ...)`).
- **Scope note (document, do not implement):** the CUSTOM format is NOT added to QC #12 in v1.29 — `known_ids` stays `MULTIFORMAT_DEFS`; custom gets guide/take/output/auto-sync but no safe-area check yet (its per-format insets don't exist in `SAFE_AREA_INSETS`). Recorded as deuda in CLAUDE.md (Task 9).

- [ ] **Step 1: Write the failing test** — fake take tree containing `Hero_9x16_s01`, `Hero_9x16_s02`, `Hero_16x9` (mirror the fake take/doc shapes already used in `tests/test_safe_area_math_helpers.py`; if that file has no take-walk fakes, model them on `test_multiformat_slices.py`'s):

```python
def test_find_active_multiformat_takes_dedupes_slice_families(...):
    result = safe_areas.find_active_multiformat_takes(doc)
    ids = [fmt_id for fmt_id, _take in result]
    assert sorted(ids) == ["16x9", "9x16"]  # s01/s02 collapse to one 9x16 entry
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement** — in `_walk`'s matcher, after the existing `endswith("_" + kid)` check, add a slice-name check and a per-family dedupe set:

```python
seen_families = set()
...
    if matched_id is None:
        stem, sep, tail = name.rpartition("_s")
        if sep and tail.isdigit():
            base = stem
            if base in known_ids:
                matched_id = base
            else:
                for kid in known_ids:
                    if base.endswith("_" + kid):
                        matched_id = kid
                        break
            if matched_id:
                family = (matched_id, base)
                if family in seen_families:
                    matched_id = None
                else:
                    seen_families.add(family)
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_safe_area_math_helpers.py tests/test_panel_frame_ops.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/safe_areas.py tests/test_safe_area_math_helpers.py
git commit -m "fix(qc12): sliced formats still register as active delivery Takes (family dedupe)"
```

---

### Task 8: Panel + SPA — slice count and slice viewing options

**Files:**
- Modify: `plugin/sentinel/ui/panel_render_ops.py` (`_panel_frame_block`), `plugin/sentinel/ui/panel_frame_ops.py` (`_frame_block`)
- Modify: `web/src/types.ts`, `web/src/lib/panelFrame.ts`, `web/src/components/panel/FrameSubview.tsx`
- Test: `tests/test_panel_frame_ops.py`, `tests/test_panel_render_ops.py`, `web/src/lib/panelFrame.test.ts`

**Interfaces:**
- Consumes: `frame_tag._total_slice_count(tag)`, `frame_tag.viewing_targets(tag)` (Tasks 4–5).
- Produces: `_panel_frame_block` payload gains `"slice_count": int | None` (None on failure, 0 when no sliced formats). `panel/frame`'s `frame.viewing_options` = `viewing_targets(tag)` (slice ids `"fmt:sNN"`); `viewing` reports `"fmt:sNN"` when a slice take is active (from `_current_own_take_info`). SPA `frameStatusLine` renders `On Hero · 2 formats (3 slices).`; the Viewing selector labels map `:` → ` · `.

- [ ] **Step 1: Failing pytest** (append to `tests/test_panel_frame_ops.py`, mirroring its existing fake-doc/tag idiom): assert `slice_count` present in the frame block and `viewing_options` containing `"custom:s01"` when the fake tag has custom 3×1 enabled; and failing vitest (append to `web/src/lib/panelFrame.test.ts`):

```ts
it("frameStatusLine shows slice count", () => {
  expect(
    frameStatusLine({ has_tag: true, camera_name: "Hero", format_count: 2,
                      slice_count: 3 } as PanelFrameBlock)
  ).toBe("On Hero · 2 formats (3 slices).");
});
it("frameStatusLine omits zero slices", () => {
  expect(
    frameStatusLine({ has_tag: true, camera_name: "Hero", format_count: 1,
                      slice_count: 0 } as PanelFrameBlock)
  ).toBe("On Hero · 1 format.");
});
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_panel_frame_ops.py -q` and `cd web && npx vitest run` → both FAIL on the new cases.

- [ ] **Step 3: Implement:**

`panel_render_ops._panel_frame_block` — add inside the has-tag branch:

```python
slice_count = None
try:
    from sentinel.ui.frame_tag import _total_slice_count
    slice_count = int(_total_slice_count(tag))
except Exception:
    pass
return {"has_tag": True, "camera_name": host.GetName() or "",
        "format_count": format_count, "slice_count": slice_count}
```

(and `"slice_count": None` in the no-tag return).

`panel_frame_ops._frame_block` — replace the viewing/viewing_options block:

```python
from sentinel.ui.frame_tag import _current_own_take_info, viewing_targets
info = _current_own_take_info(found[0], doc)
if info:
    fmt, sfx = info
    base["viewing"] = f"{fmt}:{sfx}" if sfx else fmt
base["viewing_options"] = viewing_targets(found[0])
```

(keep the try/except isolation exactly as it is today).

`web/src/types.ts` — add `slice_count?: number | null;` to `PanelFrameBlock`.

`web/src/lib/panelFrame.ts`:

```ts
export function frameStatusLine(frame: PanelFrameBlock | null): string {
  if (frame === null) return "Frame status unavailable.";
  if (!frame.has_tag || !frame.camera_name) return "No Sentinel Frame tag.";
  const n = frame.format_count;
  const formats = typeof n === "number" ? ` · ${n} format${n === 1 ? "" : "s"}` : "";
  const s = frame.slice_count;
  const slices = typeof s === "number" && s > 0 ? ` (${s} slice${s === 1 ? "" : "s"})` : "";
  return `On ${frame.camera_name}${formats}${slices}.`;
}
```

`FrameSubview.tsx` — the Viewing options mapping becomes `label: id === "master" ? "Master" : id.replace(":", " · ")` (adjust to the component's existing option shape).

- [ ] **Step 4: Run + build**

Run: `python3 -m pytest tests/test_panel_frame_ops.py tests/test_panel_render_ops.py -q` → PASS.
Run: `cd web && npx vitest run` → PASS.
Run: `cd web && npm run build` → succeeds; the bundle updates `plugin/web/`.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/panel_render_ops.py plugin/sentinel/ui/panel_frame_ops.py \
        web/src plugin/web tests/test_panel_frame_ops.py tests/test_panel_render_ops.py
git commit -m "feat(panel): slice count in frame block + slice viewing options (SPA + ops)"
```

---

### Task 9: Version bump, docs, full-suite verification

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION = "1.29.0"`)
- Modify: `CLAUDE.md` (project overview header version, new "What Works" entry + Version History entry for v1.29.0)
- Modify: `docs/superpowers/specs/2026-07-28-frame-custom-slices-design.md` (Estado → implementado, pendiente live-verify)

**Steps:**

- [ ] **Step 1:** Bump `PLUGIN_VERSION` to `"1.29.0"`.
- [ ] **Step 2:** CLAUDE.md — update the header line (`Sentinel (v1.29.0)`), add the v1.29.0 Version History entry summarizing: custom ratio row (per-tag defs), slices for all formats (floor-exact `slice_windows`, `window_crop_values` window-anchored crop writes, `_sNN` takes/outputs/links/prune/viewing, cut guides + slice HUD, panel slice count), no-regression contract (1×1 byte-identical, one adoption re-sync from the signature fields), and the recorded deuda: QC #12 does not evaluate the custom format yet; slices are ignored outside Crop composition mode.
- [ ] **Step 3:** Full verification:

Run: `python3 -m pytest tests/ -q` → ALL PASS (expect ~890+, zero failures).
Run: `cd web && npx vitest run` → ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add plugin/sentinel/__init__.py CLAUDE.md docs/superpowers/specs/2026-07-28-frame-custom-slices-design.md
git commit -m "docs: v1.29.0 — Frame v2.1 custom ratio + slices (pending live verification)"
```

---

## After the plan (session-level, not subagent tasks)

1. **Final adversarial review** of the whole branch (superpowers:requesting-code-review) — fix anything Critical/Important.
2. **Live verification with the user via MCP cinema4d** (C4D restart required to load Python changes; `sync.sh` to the active prefs folder `9D810372` first). Oracle matrix from the spec:
   - Custom 9000×500 with 3×1 slices → 3 takes at 3000×500; each slice's REAL render == its guide window (numeric comparison, like the v1.28 spike); horizontal assembly of the 3 == the whole-frame render.
   - 2×2 slices on a standard format.
   - Viewing per slice (WYSIWYG), auto-sync on Sx change, cut guides legible, AM grid aligned.
3. **Merge** `feat/frame-slices` into `main` with `--no-ff` ONLY after the user confirms live verification; then update memory `project_overview.md` and remind the user of the two pending roadmap threads (Tools expansion research + cross-DCC opportunities).
