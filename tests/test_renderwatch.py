import importlib

import pytest


@pytest.fixture
def renderwatch(sentinel_module):
    return importlib.import_module("sentinel.renderwatch")


def test_watch_notifies_once_over_threshold(renderwatch):
    w = renderwatch.RenderWatch(threshold=30.0)
    assert w.observe(False, 0.0) is None      # idle
    assert w.observe(True, 10.0) is None      # render starts
    assert w.observe(True, 30.0) is None      # still rendering
    d = w.observe(False, 55.0)                # finished after 45s
    assert d == pytest.approx(45.0)
    assert w.observe(False, 56.0) is None     # no repeat


def test_watch_short_render_is_silent(renderwatch):
    w = renderwatch.RenderWatch(threshold=30.0)
    w.observe(True, 0.0)
    assert w.observe(False, 5.0) is None      # 5s < 30s threshold


def test_watch_rendering_at_first_observation_counts_from_there(renderwatch):
    # C4D may already be rendering when the plugin loads: the first True
    # observation anchors the start; no crash, duration measured from it.
    w = renderwatch.RenderWatch(threshold=30.0)
    assert w.observe(True, 100.0) is None
    assert w.observe(False, 200.0) == pytest.approx(100.0)


def test_format_duration(renderwatch):
    assert renderwatch.format_duration(45.2) == "45s"
    assert renderwatch.format_duration(754.0) == "12m 34s"
    assert renderwatch.format_duration(3601.0) == "1h 0m 1s"
