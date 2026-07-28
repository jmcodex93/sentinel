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
