import math

import pytest


def assert_box_close(actual, expected, abs_tol=1e-9):
    assert actual.keys() == expected.keys()
    for key, value in expected.items():
        assert actual[key] == pytest.approx(value, abs=abs_tol)


def test_multiformat_defs_and_aspects(sentinel_module):
    square = sentinel_module.get_multiformat_def("1x1")
    vertical = sentinel_module.get_multiformat_def("9x16")

    assert square["width"] == square["height"] == 1080
    assert sentinel_module.format_aspect(square) == pytest.approx(1.0)
    assert sentinel_module.format_aspect(vertical) == pytest.approx(1080 / 1920)
    assert sentinel_module.get_multiformat_def("unknown") is None
    assert sentinel_module.format_aspect(None) == pytest.approx(1.0)


def test_fov_and_aperture_helpers(sentinel_module):
    source_h_fov = math.radians(60)
    target = sentinel_module.compute_target_horizontal_fov(
        source_h_fov, 16 / 9, 9 / 16
    )

    assert target == pytest.approx(
        2.0 * math.atan(((9 / 16) / (16 / 9)) * math.tan(source_h_fov / 2.0))
    )
    assert sentinel_module.compute_target_horizontal_fov(source_h_fov, 0, 9 / 16) == source_h_fov
    assert sentinel_module.compute_target_aperture(36.0, 1920, 1080) == pytest.approx(20.25)
    assert sentinel_module.compute_target_aperture(36.0, 0, 1080) == pytest.approx(36.0)


def test_format_output_path_modes(sentinel_module):
    compute = sentinel_module.compute_format_output_path

    assert compute("output/$prj_$frame", "16x9", "subfolder") == "output/16x9/$prj_$frame"
    assert compute("output/$prj_$frame", "16x9", "suffix") == "output/$prj_$frame_16x9"
    assert compute(r"output\$prj_$frame", "9x16", "subfolder") == "output/9x16/$prj_$frame"
    assert compute("$prj_$frame", "9x16", "subfolder") == "9x16/$prj_$frame"
    assert compute("", "1x1", "subfolder") == "1x1/$prj_$frame"
    assert compute("", "1x1", "suffix") == "$prj_1x1_$frame"
    assert compute("output/$prj", "", "subfolder") == "output/$prj"


def test_format_output_path_is_idempotent(sentinel_module):
    # Set Output reads back the active render-data path and re-applies the
    # format, so re-application must NOT stack the format segment.
    compute = sentinel_module.compute_format_output_path

    once = compute("output/$prj_$frame", "16x9", "subfolder")
    assert once == "output/16x9/$prj_$frame"
    assert compute(once, "16x9", "subfolder") == once  # no output/16x9/16x9/...
    assert compute(compute(once, "16x9", "subfolder"), "16x9", "subfolder") == once

    once_sfx = compute("output/$prj_$frame", "16x9", "suffix")
    assert once_sfx == "output/$prj_$frame_16x9"
    assert compute(once_sfx, "16x9", "suffix") == once_sfx  # no _16x9_16x9

    # A different format still nests normally after the first.
    assert compute(once, "9x16", "subfolder") == "output/16x9/9x16/$prj_$frame"


def test_take_name_for_format(sentinel_module):
    fmt = sentinel_module.get_multiformat_def("9x16")

    assert sentinel_module.take_name_for_format(fmt, "Main") == "9x16"
    assert sentinel_module.take_name_for_format(fmt, "") == "9x16"
    assert sentinel_module.take_name_for_format(fmt, "shot_010") == "shot_010_9x16"
    assert sentinel_module.take_name_for_format(None, "shot_010") == ""


def test_safe_area_ndc_box_respects_asymmetric_insets(sentinel_module):
    assert_box_close(
        sentinel_module.safe_area_ndc_box("9x16"),
        {"left": -0.9, "right": 0.8, "bottom": -0.7, "top": 0.84},
    )
    assert_box_close(
        sentinel_module.safe_area_ndc_box("unknown"),
        {"left": -1.0, "right": 1.0, "bottom": -1.0, "top": 1.0},
    )


def test_format_safe_area_in_master_ndc_for_vertical_crop(sentinel_module):
    box = sentinel_module.format_safe_area_in_master_ndc("9x16", 16 / 9)

    crop_x = (9 / 16) / (16 / 9)
    assert_box_close(
        box,
        {
            "left": -crop_x + (2 * crop_x) * 0.05,
            "right": crop_x - (2 * crop_x) * 0.10,
            "bottom": -1.0 + 2.0 * 0.15,
            "top": 1.0 - 2.0 * 0.08,
        },
    )
    assert box["left"] < box["right"]
    assert abs(box["left"]) > abs(box["right"])


def test_format_safe_area_in_master_ndc_for_wide_crop(sentinel_module):
    box = sentinel_module.format_safe_area_in_master_ndc("21x9", 16 / 9)
    crop_y = (16 / 9) / (2560 / 1080)

    assert_box_close(
        box,
        {
            "left": -0.9,
            "right": 0.9,
            "bottom": -crop_y + (2 * crop_y) * 0.05,
            "top": crop_y - (2 * crop_y) * 0.05,
        },
    )


def test_corners_violation_sides(sentinel_module):
    safe_box = {"left": -0.5, "right": 0.5, "bottom": -0.25, "top": 0.25}

    assert sentinel_module.corners_violation_sides([], safe_box) == set()
    assert sentinel_module.corners_violation_sides([(0.0, 0.0)], safe_box) == set()
    assert sentinel_module.corners_violation_sides(
        [(-0.6, 0.0), (0.6, 0.3), (0.0, -0.3)], safe_box
    ) == {"left", "right", "top", "bottom"}


def test_project_world_to_ndc_identity_matrix(sentinel_module):
    class IdentityMatrix:
        def __mul__(self, other):
            return other

    point = sentinel_module.c4d.Vector(0.5, 0.25, 2.0)
    ndc_x, ndc_y, in_front = sentinel_module.project_world_to_ndc(
        IdentityMatrix(), point, math.radians(90), 16 / 9
    )

    assert in_front is True
    assert ndc_x == pytest.approx(0.25)
    assert ndc_y == pytest.approx(0.25 * (16 / 9) / 2.0)

    behind = sentinel_module.c4d.Vector(0.0, 0.0, -1.0)
    assert sentinel_module.project_world_to_ndc(
        IdentityMatrix(), behind, math.radians(90), 16 / 9
    ) == (0.0, 0.0, False)
