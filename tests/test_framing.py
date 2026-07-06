import importlib.util
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FRAMING_PATH = ROOT / "plugin" / "sentinel" / "framing.py"

spec = importlib.util.spec_from_file_location("sentinel_framing_under_test", FRAMING_PATH)
framing = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = framing
spec.loader.exec_module(framing)


def assert_rect_close(actual, expected, abs_tol=1e-9):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        assert got == pytest.approx(want, abs=abs_tol)


def assert_box_close(actual, expected, abs_tol=1e-9):
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        assert actual[key] == pytest.approx(value, abs=abs_tol)


def test_framing_module_is_pure_python():
    assert "c4d" not in sys.modules or getattr(sys.modules["c4d"], "__name__", "") == "c4d"
    assert not any(name == "c4d" for name in framing.__dict__)


def test_inscribed_rect_vertical_format_in_landscape_frame():
    frame = (0.0, 0.0, 16.0 / 9.0, 1.0)
    rect = framing.inscribed_rect(frame, 9.0 / 16.0)

    assert rect[3] - rect[1] == pytest.approx(1.0)
    assert rect[2] - rect[0] == pytest.approx(9.0 / 16.0)
    assert framing.rect_center(rect) == pytest.approx((8.0 / 9.0, 0.5))


def test_inscribed_rect_same_aspect_returns_full_frame():
    frame = (0.0, 0.0, 16.0 / 9.0, 1.0)
    rect = framing.inscribed_rect(frame, 16.0 / 9.0)

    assert_rect_close(rect, frame)


def test_offset_rect_fractional_nudge_and_clamp():
    frame = (0.0, 0.0, 16.0 / 9.0, 1.0)
    centered = framing.inscribed_rect(frame, 9.0 / 16.0)
    offset = framing.offset_rect(centered, frame, 0.10, 0.0)
    clamped = framing.offset_rect(centered, frame, 10.0, 0.0)

    available_right = frame[2] - centered[2]
    expected_dx = available_right * 0.10
    assert_rect_close(
        offset,
        (centered[0] + expected_dx, centered[1], centered[2] + expected_dx, centered[3]),
    )
    assert framing.offset_rect(centered, frame, 0.0, 0.0) == pytest.approx(centered)
    assert clamped[2] == pytest.approx(frame[2])


def test_format_crop_rect_and_scaled_rect():
    crop = framing.format_crop_rect(1920, 1080, 1080, 1920, nudge=(0.0, 0.0))
    scaled = framing.scaled_rect(crop, 0.90)

    assert crop[2] - crop[0] == pytest.approx(9.0 / 16.0)
    assert crop[3] - crop[1] == pytest.approx(1.0)
    assert framing.rect_center(scaled) == pytest.approx(framing.rect_center(crop))
    assert scaled[2] - scaled[0] == pytest.approx((crop[2] - crop[0]) * 0.90)


def test_compensated_focus_modes():
    source_focal = 36.0

    assert framing.compensated_focus(
        source_focal, 1920, 1080, 1080, 1920, "preserve_vertical"
    ) == pytest.approx(36.0 * (16.0 / 9.0) / (9.0 / 16.0))
    assert framing.compensated_focus(
        source_focal, 1920, 1080, 1080, 1920, "off"
    ) == pytest.approx(source_focal)
    assert framing.compensated_focus(
        source_focal, 1920, 1080, 1080, 1920, "preserve_horizontal"
    ) == pytest.approx(source_focal)
    assert framing.compensated_focus(
        source_focal, 1080, 1920, 1920, 1080, "crop"
    ) == pytest.approx(36.0 * (16.0 / 9.0) / (9.0 / 16.0))


def test_format_camera_framing_values_nudge_to_film_offset():
    focus, film_x, film_y = framing.format_camera_framing_values(
        36.0,
        1920,
        1080,
        1080,
        1920,
        "preserve_vertical",
        nudge=(0.05, -0.03),
        source_film_x=0.01,
        source_film_y=-0.02,
    )

    source_aspect = 16.0 / 9.0
    target_aspect = 9.0 / 16.0
    max_film_x = (1.0 - (target_aspect / source_aspect)) * 0.5
    assert focus == pytest.approx(36.0 * source_aspect / target_aspect)
    assert film_x == pytest.approx(0.01 + max_film_x * 0.05)
    assert film_y == pytest.approx(-0.02)


def test_format_camera_framing_values_off_does_not_override_focus():
    focus, film_x, film_y = framing.format_camera_framing_values(
        36.0, 1920, 1080, 1920, 1080, "off", nudge=(0.05, -0.03)
    )

    assert focus is None
    assert film_x == pytest.approx(0.0)
    assert film_y == pytest.approx(0.0)


def test_format_crop_values_narrower_target_crops_aperture_and_pans_gate_relative():
    # 1:1 from 16:9 (1280x720 master): aperture scales by target/source aspect,
    # and a full nudge pans by the GATE-relative travel (source/target - 1)/2.
    src_ap = 36.0
    src_w, src_h = 1280.0, 720.0
    tw, th = 1080.0, 1080.0
    sa = src_w / src_h
    ta = tw / th

    ap, fx, fy = framing.format_crop_values(src_ap, src_w, src_h, tw, th, nudge=(1.0, 0.0))
    assert ap == pytest.approx(src_ap * (ta / sa))          # 36 * (1/1.777) = 20.25
    assert ap == pytest.approx(20.25)
    assert fx == pytest.approx((sa / ta - 1.0) * 0.5)       # 0.389 (full right)
    assert fy == pytest.approx(0.0)                          # 1:1 has no vertical travel

    # Centered (no nudge) leaves film offset at the source value.
    ap0, fx0, fy0 = framing.format_crop_values(src_ap, src_w, src_h, tw, th, nudge=(0.0, 0.0),
                                               source_film_x=0.02, source_film_y=-0.01)
    assert ap0 == pytest.approx(20.25)
    assert fx0 == pytest.approx(0.02)
    assert fy0 == pytest.approx(-0.01)


def test_format_crop_values_wider_target_keeps_aperture_and_pans_vertically():
    # 21:9 from 16:9: wider than source -> aperture unchanged, aspect crops
    # top/bottom, and the nudge pans VERTICALLY.
    src_ap = 36.0
    src_w, src_h = 1920.0, 1080.0
    tw, th = 2560.0, 1080.0
    sa = src_w / src_h
    ta = tw / th

    ap, fx, fy = framing.format_crop_values(src_ap, src_w, src_h, tw, th, nudge=(1.0, 1.0))
    assert ap == pytest.approx(src_ap)                       # min(1, ta/sa)=1 -> unchanged
    assert fx == pytest.approx(0.0)                          # no horizontal travel
    assert fy == pytest.approx((ta / sa - 1.0) * 0.5)        # vertical travel


def test_crop_rect_in_master_ndc_uses_camera_ndc_convention():
    rect = framing.crop_rect_in_master_ndc(1080, 1920, 16.0 / 9.0)
    crop_x = (9.0 / 16.0) / (16.0 / 9.0)

    assert_rect_close(rect, (-crop_x, -1.0, crop_x, 1.0))


def test_format_safe_area_default_offset_matches_previous_math(sentinel_module):
    expected = {
        "16x9": {
            "left": -0.9,
            "right": 0.9,
            "bottom": -0.9,
            "top": 0.9,
        },
        "9x16": {
            "left": -0.31640625 + (2.0 * 0.31640625) * 0.05,
            "right": 0.31640625 - (2.0 * 0.31640625) * 0.10,
            "bottom": -1.0 + 2.0 * 0.15,
            "top": 1.0 - 2.0 * 0.08,
        },
        "1x1": {
            "left": -0.5625 + (2.0 * 0.5625) * 0.05,
            "right": 0.5625 - (2.0 * 0.5625) * 0.05,
            "bottom": -1.0 + 2.0 * 0.08,
            "top": 1.0 - 2.0 * 0.05,
        },
        "4x5": {
            "left": -0.45 + (2.0 * 0.45) * 0.05,
            "right": 0.45 - (2.0 * 0.45) * 0.05,
            "bottom": -1.0 + 2.0 * 0.10,
            "top": 1.0 - 2.0 * 0.05,
        },
        "21x9": {
            "left": -0.9,
            "right": 0.9,
            "bottom": -0.75 + (2.0 * 0.75) * 0.05,
            "top": 0.75 - (2.0 * 0.75) * 0.05,
        },
    }

    for fmt_id, box in expected.items():
        actual_default = sentinel_module.format_safe_area_in_master_ndc(fmt_id, 16.0 / 9.0)
        actual_zero = sentinel_module.format_safe_area_in_master_ndc(
            fmt_id, 16.0 / 9.0, offset=(0.0, 0.0)
        )
        assert_box_close(actual_default, box)
        assert_box_close(actual_zero, box)


def test_format_safe_area_offset_shifts_and_clamps_to_crop_travel(sentinel_module):
    centered = sentinel_module.format_safe_area_in_master_ndc("9x16", 16.0 / 9.0)
    shifted = sentinel_module.format_safe_area_in_master_ndc(
        "9x16", 16.0 / 9.0, offset=(1.0, 0.0)
    )
    over_shifted = sentinel_module.format_safe_area_in_master_ndc(
        "9x16", 16.0 / 9.0, offset=(10.0, 0.0)
    )

    crop_x = (9.0 / 16.0) / (16.0 / 9.0)
    expected_shift = 1.0 - crop_x
    assert shifted["left"] == pytest.approx(centered["left"] + expected_shift)
    assert shifted["right"] == pytest.approx(centered["right"] + expected_shift)
    assert shifted == pytest.approx(over_shifted)
