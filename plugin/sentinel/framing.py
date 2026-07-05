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
