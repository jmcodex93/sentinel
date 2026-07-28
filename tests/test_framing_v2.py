# -*- coding: utf-8 -*-
"""Camera-type-aware crop writer (Frame v2, Task 2).

Ocamera ids (aperture/film offset) are inert on ORSCAMERA (confirmed
production bug — the nudge silently didn't render). ORSCAMERA has its own
parameter namespace (7002 sensor size / 7012 sensor shift). See
docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md.
"""

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


def test_nudge_to_film_matches_format_crop_values_pan_math():
    # Parity: nudge_to_film must reproduce the exact film pan that the
    # existing focal-based format_crop_values computes (same optics, same
    # gate-relative math — only the lever driving the crop factor changes).
    nudge = (0.0, 1.0)
    src_w, src_h, tgt_w, tgt_h = 1920, 1080, 1080, 1920
    _, old_film_x, old_film_y = framing.format_crop_values(
        36.0, src_w, src_h, tgt_w, tgt_h, nudge, 0.0, 0.0)
    new_film_x, new_film_y = framing.nudge_to_film(
        nudge, 0.0, 0.0, src_w, src_h, tgt_w, tgt_h)
    assert new_film_x == old_film_x
    assert new_film_y == old_film_y
