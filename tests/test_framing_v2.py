# -*- coding: utf-8 -*-
"""Camera-type-aware crop writer (Frame v2, Task 2).

Ocamera ids (aperture/film offset) are inert on ORSCAMERA (confirmed
production bug — the nudge silently didn't render). ORSCAMERA has its own
parameter namespace (7002 sensor size / 7012 sensor shift). See
docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md.
"""

import pytest

from sentinel import framing


def test_detect_camera_kind():
    assert framing.detect_camera_kind(5103) == "ocamera"          # Ocamera clásico
    assert framing.detect_camera_kind(framing.ORSCAMERA_TYPE) == "orscamera"
    assert framing.detect_camera_kind(999999) == "ocamera"        # desconocido → trata como estándar


def test_crop_writes_ocamera_narrower():
    # 16:9 → 9:16: factor = (9/16)/(16/9); aperture escala, focal NO aparece
    writes = framing.crop_writes(
        "ocamera", aperture=36.0, sensor=None, factor=0.3164,
        nudge_film=(0.0, 0.05), src_film=(0.0, 0.0))
    ids = [w[0] for w in writes]
    assert framing.CAMERAOBJECT_APERTURE in ids
    assert framing.CAMERA_FOCUS not in ids
    assert framing.CAMERAOBJECT_FILM_OFFSET_Y in ids  # nudge presente


def test_crop_writes_ocamera_no_nudge_no_offset_writes():
    writes = framing.crop_writes(
        "ocamera", aperture=36.0, sensor=None, factor=0.5,
        nudge_film=(0.0, 0.0), src_film=(0.0, 0.0))
    ids = [w[0] for w in writes]
    assert framing.CAMERAOBJECT_FILM_OFFSET_X not in ids  # sin override espurio


def test_crop_writes_orscamera_uses_rs_namespace():
    writes = framing.crop_writes(
        "orscamera", aperture=None, sensor=(36.0, 24.0), factor=0.5,
        nudge_film=(0.02, 0.0), src_film=(0.0, 0.0))
    ids = [w[0] for w in writes]
    assert framing.RS_SENSOR_SIZE in ids
    assert framing.CAMERAOBJECT_APERTURE not in ids


def test_crop_writes_orscamera_scales_both_axes_and_writes_shift_vector():
    writes = framing.crop_writes(
        "orscamera", aperture=None, sensor=(36.0, 24.0), factor=0.5,
        nudge_film=(0.02, 0.0), src_film=(0.0, 0.0))
    by_id = dict(writes)
    assert by_id[framing.RS_SENSOR_SIZE] == (18.0, 12.0, 0.0)
    assert framing.RS_SENSOR_SHIFT in by_id
    assert by_id[framing.RS_SENSOR_SHIFT] == (0.02, 0.0, 0.0)


def test_crop_writes_orscamera_no_nudge_no_shift_write():
    writes = framing.crop_writes(
        "orscamera", aperture=None, sensor=(36.0, 24.0), factor=0.5,
        nudge_film=(0.0, 0.0), src_film=(0.0, 0.0))
    ids = [w[0] for w in writes]
    assert framing.RS_SENSOR_SHIFT not in ids


def test_crop_writes_factor_one_is_empty():
    assert framing.crop_writes("ocamera", aperture=36.0, sensor=None,
                               factor=1.0, nudge_film=(0.0, 0.0), src_film=(0.0, 0.0)) == []
    assert framing.crop_writes("orscamera", aperture=None, sensor=(36.0, 24.0),
                               factor=1.0, nudge_film=(0.0, 0.0), src_film=(0.0, 0.0)) == []


def test_inscribed_crop_factor_narrower_and_wider():
    # 16:9 -> 9:16 (narrower): factor < 1
    factor = framing.inscribed_crop_factor(1920, 1080, 1080, 1920)
    assert 0.31 < factor < 0.32
    # 16:9 -> 21:9 (wider-or-equal): no crop, resolution alone handles it
    assert framing.inscribed_crop_factor(1920, 1080, 2560, 1080) == 1.0


def test_nudge_to_film_narrower_target_hand_computed():
    # Hardcoded ground truth (computed BY HAND from the pre-refactor
    # max_film_x/max_film_y formula, independent of nudge_to_film itself —
    # format_crop_values now calls nudge_to_film internally, so comparing
    # the two would be circular and couldn't catch a shared regression).
    #
    #   source 1920x1080 -> target 1080x1080 (narrower, square)
    #   sa = 1920/1080 = 16/9;  ta = 1080/1080 = 1.0
    #   max_film_x = max(0, sa/ta - 1) * 0.5 = (16/9 - 1) * 0.5 = (7/9) * 0.5 = 7/18
    #   max_film_y = max(0, ta/sa - 1) * 0.5 = 0 (ta < sa, no vertical room)
    #   nudge = (0.5, 0.0) -> film_x = 0.0 + (7/18)*0.5 = 7/36; film_y = 0.0
    film_x, film_y = framing.nudge_to_film(
        (0.5, 0.0), 0.0, 0.0, 1920, 1080, 1080, 1080)
    assert film_x == pytest.approx(7.0 / 36.0)
    assert film_y == pytest.approx(0.0)


def test_nudge_to_film_wider_target_with_source_offsets_hand_computed():
    # Second hardcoded ground-truth case: a WIDER target (vertical travel
    # room instead of horizontal) plus non-zero source film offsets, so the
    # additive term is also exercised.
    #
    #   source 1920x1080 -> target 2560x1080 (21:9, wider)
    #   sa = 1920/1080 = 16/9;  ta = 2560/1080 = 64/27
    #   max_film_x = max(0, sa/ta - 1) * 0.5 = max(0, 0.75 - 1) * 0.5 = 0
    #   max_film_y = max(0, ta/sa - 1) * 0.5 = ((64/27)/(16/9) - 1) * 0.5
    #              = (4/3 - 1) * 0.5 = (1/3) * 0.5 = 1/6
    #   source_film = (0.1, -0.05); nudge = (0.0, 1.0)
    #   film_x = 0.1 + 0 * 0.0 = 0.1
    #   film_y = -0.05 + (1/6) * 1.0 = -0.05 + 1/6 = 7/60
    film_x, film_y = framing.nudge_to_film(
        (0.0, 1.0), 0.1, -0.05, 1920, 1080, 2560, 1080)
    assert film_x == pytest.approx(0.1)
    assert film_y == pytest.approx(7.0 / 60.0)


def test_crop_writes_wider_emits_pan_only():
    # 21:9-style WIDER target: the crop is resolution-only, but a vertical
    # nudge must still pan inside the top/bottom crop (live-caught: the old
    # early-return [] swallowed 21:9's vertical nudge entirely). Hand math
    # (1920x1080 -> 2560x1080, full nudge): film_y = (ta/sa - 1)/2 = 1/6.
    writes = framing.crop_writes(
        "orscamera", aperture=None, sensor=(36.0, 24.0), factor=4.0 / 3.0,
        nudge_film=(0.0, 1.0 / 6.0), src_film=(0.0, 0.0))
    assert writes == [(framing.RS_SENSOR_SHIFT, (0.0, 1.0 / 6.0, 0.0))]

    writes_o = framing.crop_writes(
        "ocamera", aperture=36.0, sensor=None, factor=4.0 / 3.0,
        nudge_film=(0.0, 1.0 / 6.0), src_film=(0.0, 0.0))
    assert writes_o == [
        (framing.CAMERAOBJECT_FILM_OFFSET_X, 0.0),
        (framing.CAMERAOBJECT_FILM_OFFSET_Y, 1.0 / 6.0),
    ]


def test_crop_writes_wider_without_nudge_stays_empty():
    assert framing.crop_writes(
        "ocamera", aperture=36.0, sensor=None, factor=4.0 / 3.0,
        nudge_film=(0.0, 0.0), src_film=(0.0, 0.0)) == []


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
