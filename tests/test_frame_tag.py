import importlib


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
