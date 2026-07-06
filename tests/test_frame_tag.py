import importlib

import pytest


def test_frame_tag_imports_under_fake_c4d(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.SentinelFrameTag is not None
    assert frame_tag._DRAW_CALLS == 0


def test_is_valid_camera_host_accepts_standard_and_redshift_cameras(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.is_valid_camera_host(5103) is True
    assert frame_tag.is_valid_camera_host(1057516) is True


def test_is_valid_camera_host_rejects_non_cameras(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    assert frame_tag.is_valid_camera_host(5159) is False
    assert frame_tag.is_valid_camera_host(5140) is False


def test_frame_tag_ndc_to_pixel_mapping_flips_y(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    rect = {"left": -0.5, "right": 0.5, "bottom": -0.25, "top": 0.75}

    assert frame_tag._ndc_rect_to_pixels(rect, (100, 20, 500, 220)) == (
        200.0,
        45.0,
        400.0,
        145.0,
    )


def test_frame_tag_intersection_uses_all_guides(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    rect = frame_tag._intersect_ndc_rects(
        [
            {"left": -1.0, "right": 1.0, "bottom": -0.5, "top": 0.5},
            {"left": -0.25, "right": 0.25, "bottom": -1.0, "top": 1.0},
        ]
    )

    assert rect == {"left": -0.25, "right": 0.25, "bottom": -0.5, "top": 0.5}


def test_frame_tag_inline_rects_compute_from_tag_params_without_rect_cache(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")

    tag = {}
    for index, _fmt in enumerate(frame_tag._format_defs()):
        tag[frame_tag._format_ids(index)["enabled"]] = False

    vertical_index = 1
    ids = frame_tag._format_ids(vertical_index)
    tag[ids["enabled"]] = True
    tag[ids["nudge_x"]] = 0.25
    tag[ids["nudge_y"]] = -0.5

    custom_insets = {
        "9x16": {"top": 0.10, "bottom": 0.20, "left": 0.03, "right": 0.12},
    }
    frame_tag._write_platform_insets_to_node(tag, custom_insets)

    rects = frame_tag._compute_inline_rects(tag, 16.0 / 9.0)

    assert not hasattr(frame_tag, "_RECT_CACHE_BY_NODE")
    assert len(rects) == 1
    entry = rects[0]
    assert entry["id"] == "9x16"
    assert entry["width"] == 1080
    assert entry["height"] == 1920

    expected_guide = frame_tag.framing.crop_rect_in_master_ndc(
        1080,
        1920,
        16.0 / 9.0,
        (0.25, -0.5),
    )
    assert entry["guide"] == {
        "left": pytest.approx(expected_guide[0]),
        "bottom": pytest.approx(expected_guide[1]),
        "right": pytest.approx(expected_guide[2]),
        "top": pytest.approx(expected_guide[3]),
    }

    expected_platform = frame_tag.format_safe_area_in_master_ndc(
        "9x16",
        16.0 / 9.0,
        frame_tag._InlineRulesContext(custom_insets),
        offset=(0.25, -0.5),
    )
    assert entry["platform"] == {
        "left": pytest.approx(expected_platform["left"]),
        "right": pytest.approx(expected_platform["right"]),
        "bottom": pytest.approx(expected_platform["bottom"]),
        "top": pytest.approx(expected_platform["top"]),
    }


def test_legacy_overlay_suppression_detects_active_frame_tag(sentinel_module):
    frame_tag = importlib.import_module("sentinel.ui.frame_tag")
    overlay = importlib.import_module("sentinel.ui.overlay")

    class FakeTag(dict):
        def GetType(self):
            return frame_tag.SENTINEL_FRAME_TAG_PLUGIN_ID

        def GetNext(self):
            return None

    class FakeObject:
        def __init__(self, tag):
            self._tag = tag

        def GetFirstTag(self):
            return self._tag

        def GetDown(self):
            return None

        def GetNext(self):
            return None

    class FakeDoc:
        def __init__(self, first):
            self._first = first

        def GetFirstObject(self):
            return self._first

    tag = FakeTag(
        {
            frame_tag.ID_ENABLED: True,
            frame_tag.ID_SHOW_GUIDES: True,
            frame_tag._format_ids(0)["enabled"]: True,
        }
    )

    assert overlay.document_has_active_frame_tag(FakeDoc(FakeObject(tag))) is True

    tag[frame_tag.ID_SHOW_GUIDES] = False
    assert overlay.document_has_active_frame_tag(FakeDoc(FakeObject(tag))) is False
