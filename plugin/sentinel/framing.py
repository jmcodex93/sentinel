# -*- coding: utf-8 -*-
"""Pure framing math for Sentinel Frame.

Rectangles use the C4DMultiFrame convention: ``(left, top, right, bottom)``
inside a frame whose origin is top-left and whose Y axis grows downward.  For
aspect math we use an abstract source frame ``(0, 0, source_aspect, 1)``.

Nudges are fractions of the available travel in each axis: ``0.10`` means
10 percent toward the positive side, ``-1.0`` means all the way to the
negative side.  This adapts C4DMultiFrame's percentage UI values to a pure
Python API.
"""

from __future__ import annotations

from typing import Optional, Tuple


Rect = Tuple[float, float, float, float]


COMPENSATE_OFF = "off"
COMPENSATE_PRESERVE_VERTICAL = "preserve_vertical"
COMPENSATE_PRESERVE_HORIZONTAL = "preserve_horizontal"
COMPENSATE_CROP = "crop"

# Camera parameter ids kept here so C4D-bound engines can import one table
# without making this module depend on c4d.  Standard and Redshift camera
# stubs in C4D 2026 expose the same film offset values; verify Orscamera live
# in U4 before writing overrides.
CAMERA_FOCUS = 500
CAMERAOBJECT_APERTURE = 1006
CAMERAOBJECT_FILM_OFFSET_X = 1118
CAMERAOBJECT_FILM_OFFSET_Y = 1119

# --- Camera-type-aware crop writes (Frame v2) -------------------------------
# ORSCAMERA (native Redshift camera, C4D 2023.1+) has its OWN parameter
# namespace — Ocamera ids (APERTURE=1006, FILM_OFFSET_X/Y=1118/1119) are
# inert on it. That's the confirmed production bug: the crop factor (driven
# by focal, id 500, which DOES exist on both node types) rendered fine, but
# the WYSIWYG nudge/pan silently didn't — 1118/1119 have no effect on
# ORSCAMERA. Live spike results + the writer decision are in
# docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md.
ORSCAMERA_TYPE = 1057516          # confirmed live, C4D 2026.303
RS_SENSOR_SIZE = 7002             # RSCAMERAOBJECT_SENSOR_SIZE (Vector, mm)
RS_SENSOR_SHIFT = 7012            # RSCAMERAOBJECT_SENSOR_SHIFT (Vector, fraction-of-frame — gate-relative, same semantics as Ocamera film offset)


def _aspect(width: float, height: float, fallback: float = 1.0) -> float:
    width = float(width)
    height = float(height)
    if width <= 0.0 or height <= 0.0:
        return float(fallback)
    return width / height


def _abstract_frame(source_aspect: float) -> Rect:
    return (0.0, 0.0, max(0.0001, float(source_aspect)), 1.0)


def _clamp_nudge(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _coerce_nudge(nudge: Optional[tuple[float, float]]) -> tuple[float, float]:
    if nudge is None:
        return (0.0, 0.0)
    try:
        x, y = nudge
    except Exception:
        return (0.0, 0.0)
    return (_clamp_nudge(x), _clamp_nudge(y))


def inscribed_rect(frame: Rect, aspect: float) -> Rect:
    """Return the largest rect of ``aspect`` centered inside ``frame``."""
    left, top, right, bottom = frame
    width = max(1.0, right - left)
    height = max(1.0, bottom - top)
    frame_aspect = width / height
    aspect = max(0.0001, float(aspect))

    if aspect >= frame_aspect:
        guide_width = width
        guide_height = width / aspect
    else:
        guide_height = height
        guide_width = height * aspect

    cx = left + width * 0.5
    cy = top + height * 0.5
    return (
        cx - guide_width * 0.5,
        cy - guide_height * 0.5,
        cx + guide_width * 0.5,
        cy + guide_height * 0.5,
    )


def clamp_rect(rect: Rect, frame: Rect) -> Rect:
    """Translate ``rect`` just enough to keep it inside ``frame``."""
    left, top, right, bottom = rect
    fl, ft, fr, fb = frame
    dx = 0.0
    dy = 0.0

    if left < fl:
        dx = fl - left
    elif right > fr:
        dx = fr - right
    if top < ft:
        dy = ft - top
    elif bottom > fb:
        dy = fb - bottom

    return (left + dx, top + dy, right + dx, bottom + dy)


def offset_rect(rect: Rect, frame: Rect, offset_x: float = 0.0, offset_y: float = 0.0) -> Rect:
    """Nudge ``rect`` within ``frame`` by fractional X/Y travel and clamp it."""
    left, top, right, bottom = rect
    fl, ft, fr, fb = frame
    max_left = fl - left
    max_right = fr - right
    max_up = ft - top
    max_down = fb - bottom
    ox = _clamp_nudge(offset_x)
    oy = _clamp_nudge(offset_y)

    dx = max_right * ox if ox >= 0.0 else -max_left * ox
    dy = max_down * oy if oy >= 0.0 else -max_up * oy
    return clamp_rect((left + dx, top + dy, right + dx, bottom + dy), frame)


def rect_center(rect: Rect) -> tuple[float, float]:
    """Return the center point of ``rect`` in the same coordinate space."""
    left, top, right, bottom = rect
    return (left + (right - left) * 0.5, top + (bottom - top) * 0.5)


def format_crop_rect(
    source_width: float,
    source_height: float,
    target_width: float,
    target_height: float,
    nudge: Optional[tuple[float, float]] = None,
) -> Rect:
    """Return a nudged target-format crop rect in the abstract source frame."""
    source_aspect = _aspect(source_width, source_height)
    target_aspect = _aspect(target_width, target_height)
    frame = _abstract_frame(source_aspect)
    rect = inscribed_rect(frame, target_aspect)
    offset_x, offset_y = _coerce_nudge(nudge)
    return offset_rect(rect, frame, offset_x, offset_y)


def scaled_rect(rect: Rect, scale: float) -> Rect:
    """Return ``rect`` scaled about its center by ``scale`` clamped to [0, 1]."""
    left, top, right, bottom = rect
    cx = (left + right) * 0.5
    cy = (top + bottom) * 0.5
    clamped = max(0.0, min(1.0, float(scale)))
    half_width = (right - left) * clamped * 0.5
    half_height = (bottom - top) * clamped * 0.5
    return (cx - half_width, cy - half_height, cx + half_width, cy + half_height)


def crop_rect_in_master_ndc(
    target_width: float,
    target_height: float,
    master_aspect: float,
    nudge: Optional[tuple[float, float]] = None,
) -> Rect:
    """Return the target crop rect in master NDC as ``(left, bottom, right, top)``.

    Unlike the top-left rect convention used by the crop helpers, this returns
    NDC bounds with Y growing upward so callers can compare directly with
    projected camera points.
    """
    if master_aspect is None or float(master_aspect) <= 0.0:
        return (-1.0, -1.0, 1.0, 1.0)
    crop = format_crop_rect(master_aspect, 1.0, target_width, target_height, nudge)
    left, top, right, bottom = crop
    master_aspect = max(0.0001, float(master_aspect))
    ndc_left = (left / master_aspect) * 2.0 - 1.0
    ndc_right = (right / master_aspect) * 2.0 - 1.0
    ndc_top = 1.0 - top * 2.0
    ndc_bottom = 1.0 - bottom * 2.0
    return (ndc_left, ndc_bottom, ndc_right, ndc_top)


def compensated_focus(
    source_focal: float,
    src_w: float,
    src_h: float,
    tgt_w: float,
    tgt_h: float,
    mode: str,
) -> float:
    """Return focal length compensated for the selected aspect mode."""
    focus = float(source_focal)
    source_aspect = _aspect(src_w, src_h, fallback=0.0)
    target_aspect = _aspect(tgt_w, tgt_h, fallback=0.0)
    if source_aspect <= 0.0 or target_aspect <= 0.0:
        return focus

    if mode == COMPENSATE_PRESERVE_VERTICAL:
        return focus * source_aspect / target_aspect
    if mode == COMPENSATE_CROP:
        return focus * max(source_aspect / target_aspect, target_aspect / source_aspect)
    return focus


def nudge_to_film(
    nudge: Optional[tuple[float, float]],
    src_film_x: float,
    src_film_y: float,
    src_w: float,
    src_h: float,
    tgt_w: float,
    tgt_h: float,
) -> tuple[float, float]:
    """Return ``(film_x, film_y)`` — the gate-relative pan for a crop-mode
    override.  C4D's film offset (and its ORSCAMERA sensor-shift analogue)
    is GATE-relative (an offset of 1.0 shifts by a full frame width), so the
    per-full-nudge travel is ``(source_aspect/target_aspect - 1)/2`` on the
    axis that actually has room.  This is identical whether the crop is
    driven by focal, aperture or sensor size, because the world-space crop
    rect is the same — extracted once here so every crop-writer lever (Task
    2's ``crop_writes`` included) reuses the exact same pan math.
    """
    sa = _aspect(src_w, src_h, fallback=0.0)
    ta = _aspect(tgt_w, tgt_h, fallback=0.0)
    if sa <= 0.0 or ta <= 0.0:
        return (float(src_film_x), float(src_film_y))

    offset_x, offset_y = _coerce_nudge(nudge)
    max_film_x = max(0.0, sa / ta - 1.0) * 0.5  # horizontal travel (narrower targets)
    max_film_y = max(0.0, ta / sa - 1.0) * 0.5  # vertical travel (wider targets)
    film_x = float(src_film_x) + max_film_x * offset_x
    film_y = float(src_film_y) + max_film_y * offset_y
    return (film_x, film_y)


def inscribed_crop_factor(src_w: float, src_h: float, tgt_w: float, tgt_h: float) -> float:
    """Return the sensor/aperture scale factor for a crop-mode override.

    ``< 1.0`` for target formats NARROWER than the source (the crop kicks
    in — sensor/aperture shrinks by ``target_aspect / source_aspect``);
    ``1.0`` for wider-or-equal targets (the resolution change alone crops
    top/bottom on every camera, so the caller skips the override).
    """
    sa = _aspect(src_w, src_h, fallback=0.0)
    ta = _aspect(tgt_w, tgt_h, fallback=0.0)
    if sa <= 0.0 or ta <= 0.0 or ta >= sa:
        return 1.0
    return ta / sa


def format_crop_values(
    source_focal: float,
    src_w: float,
    src_h: float,
    tgt_w: float,
    tgt_h: float,
    nudge: Optional[tuple[float, float]] = None,
    source_film_x: float = 0.0,
    source_film_y: float = 0.0,
) -> tuple[float, float, float]:
    """Return ``(focal, film_x, film_y)`` for a TRUE inscribed crop.

    Kept as the documented focal-based fallback (e.g. for callers that
    cannot resolve a camera-type-aware writer).  The camera-type-aware
    Frame v2 path (``detect_camera_kind`` / ``crop_writes``) is now the
    default in ``multiformat.generate_multiformat_takes`` — it drives the
    crop via APERTURE (Ocamera) or SENSOR SIZE (ORSCAMERA) instead of focal,
    because ORSCAMERA's own film-offset ids (7012 sensor shift) are what the
    nudge actually needs — Ocamera's FILM_OFFSET_X/Y (1118/1119) are inert on
    it.  See docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md.

    * For a target NARROWER than the source, the FOCAL length is zoomed in by
      ``source_aspect / target_aspect`` to crop the sides down to the inscribed
      width; at the target resolution the vertical extent comes out to the full
      master height, so it matches the guide.  For a WIDER-or-equal target the
      focal is unchanged (returned == source) — the resolution change alone
      crops top/bottom — and the caller should skip the override.
    * The nudge pan math is shared with ``crop_writes`` via ``nudge_to_film``.
    """
    sa = _aspect(src_w, src_h, fallback=0.0)
    ta = _aspect(tgt_w, tgt_h, fallback=0.0)
    if sa <= 0.0 or ta <= 0.0:
        return (float(source_focal), float(source_film_x), float(source_film_y))

    # Zoom in only when the target is narrower (sa/ta > 1); unchanged otherwise.
    focal = float(source_focal) * max(1.0, sa / ta)
    film_x, film_y = nudge_to_film(
        nudge, source_film_x, source_film_y, src_w, src_h, tgt_w, tgt_h)
    return (focal, film_x, film_y)


def detect_camera_kind(type_int: int) -> str:
    """Return ``"orscamera"`` for a native Redshift camera type id, else
    ``"ocamera"`` (the default/fallback for standard C4D cameras and any
    unrecognized type)."""
    try:
        return "orscamera" if int(type_int) == ORSCAMERA_TYPE else "ocamera"
    except Exception:
        return "ocamera"


def crop_writes(
    kind: str,
    aperture: Optional[float],
    sensor: Optional[tuple[float, float]],
    factor: float,
    nudge_film: tuple[float, float],
    src_film: tuple[float, float],
) -> list:
    """Pure table of ``(param_id, value)`` camera-override writes for a TRUE
    inscribed crop of ``factor`` (``< 1`` narrower target; ``== 1`` → no
    writes, wider-or-equal formats are resolution-only).

    Same optics both camera kinds — a sensor/aperture crop keeps focal
    length (and therefore DOF + zoom keyframes) intact:

    * ``"ocamera"`` — ``CAMERAOBJECT_APERTURE`` (1006) scaled by ``factor``,
      plus ``CAMERAOBJECT_FILM_OFFSET_X/Y`` (1118/1119) when the nudge pans
      away from the source film offset.
    * ``"orscamera"`` — ``RS_SENSOR_SIZE`` (7002, Vector, mm) scaled by
      ``factor`` on both axes, plus ``RS_SENSOR_SHIFT`` (7012, Vector,
      fraction-of-frame) when the nudge pans away from the source. Values
      are returned as plain 3-tuples ``(x, y, z)`` — the C4D-bound caller
      coerces to ``c4d.Vector`` at the override call site (this module stays
      pure, no ``import c4d``).

    See docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md
    for the live spike that confirmed these ids and units.
    """
    if factor >= 1.0 - 1e-9:
        return []

    nx, ny = float(nudge_film[0]), float(nudge_film[1])
    sx, sy = float(src_film[0]), float(src_film[1])
    has_nudge = abs(nx - sx) > 1e-9 or abs(ny - sy) > 1e-9

    writes = []
    if kind == "orscamera":
        sensor = sensor or (0.0, 0.0)
        w = float(sensor[0]) * float(factor)
        h = float(sensor[1]) * float(factor)
        writes.append((RS_SENSOR_SIZE, (w, h, 0.0)))
        if has_nudge:
            writes.append((RS_SENSOR_SHIFT, (nx, ny, 0.0)))
        return writes

    writes.append((CAMERAOBJECT_APERTURE, float(aperture) * float(factor)))
    if has_nudge:
        writes.append((CAMERAOBJECT_FILM_OFFSET_X, nx))
        writes.append((CAMERAOBJECT_FILM_OFFSET_Y, ny))
    return writes


def format_camera_framing_values(
    source_focal: float,
    src_w: float,
    src_h: float,
    tgt_w: float,
    tgt_h: float,
    mode: str,
    nudge: Optional[tuple[float, float]] = None,
    source_film_x: float = 0.0,
    source_film_y: float = 0.0,
) -> tuple[float | None, float, float]:
    """Return ``(focus, film_x, film_y)`` for a target format.

    ``focus`` is ``None`` in ``off`` mode to match C4DMultiFrame's "do not
    override focal length" behavior.  Film offsets always include the source
    camera offsets plus the nudge contribution.
    """
    source_aspect = _aspect(src_w, src_h, fallback=0.0)
    target_aspect = _aspect(tgt_w, tgt_h, fallback=0.0)
    focus = None
    if mode != COMPENSATE_OFF and float(source_focal) > 0.0:
        focus = compensated_focus(source_focal, src_w, src_h, tgt_w, tgt_h, mode)

    offset_x, offset_y = _coerce_nudge(nudge)
    max_film_x = max(0.0, 1.0 - (target_aspect / source_aspect)) * 0.5 if source_aspect > 0.0 else 0.0
    max_film_y = max(0.0, 1.0 - (source_aspect / target_aspect)) * 0.5 if target_aspect > 0.0 else 0.0
    film_x = float(source_film_x) + max_film_x * offset_x
    film_y = float(source_film_y) + max_film_y * offset_y
    return (focus, film_x, film_y)
