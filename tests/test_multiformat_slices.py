import pytest


@pytest.fixture
def multiformat(sentinel_module):
    import importlib
    return importlib.import_module("sentinel.multiformat")


def test_output_path_subfolder_gains_slice_folder(multiformat):
    assert multiformat.compute_format_output_path(
        "output/$prj_$frame", "custom", "subfolder", "s01"
    ) == "output/custom/s01/$prj_$frame"


def test_output_path_suffix_gains_slice_suffix(multiformat):
    assert multiformat.compute_format_output_path(
        "output/$prj_$frame", "9x16", "suffix", "s03"
    ) == "output/$prj_$frame_9x16_s03"


def test_output_path_slice_idempotent(multiformat):
    once = multiformat.compute_format_output_path(
        "output/$prj_$frame", "16x9", "subfolder", "s02")
    again = multiformat.compute_format_output_path(once, "16x9", "subfolder", "s02")
    assert once == again == "output/16x9/s02/$prj_$frame"
    once_sfx = multiformat.compute_format_output_path(
        "output/$prj_$frame", "16x9", "suffix", "s02")
    assert multiformat.compute_format_output_path(
        once_sfx, "16x9", "suffix", "s02") == once_sfx


def test_output_path_without_slice_unchanged(multiformat):
    # Byte-identical no-slice behavior (v1.28 regression guard).
    assert multiformat.compute_format_output_path(
        "output/$prj_$frame", "16x9", "subfolder"
    ) == "output/16x9/$prj_$frame"
    assert multiformat.compute_format_output_path("", "1x1", "subfolder") == "1x1/$prj_$frame"


def test_take_name_gains_slice_suffix(multiformat):
    fmt = {"id": "custom", "width": 9000, "height": 500}
    assert multiformat._take_name_for_options(fmt, "", "Hero") == "Hero_custom"
    assert multiformat._take_name_for_options(fmt, "", "Hero", "s02") == "Hero_custom_s02"


def test_existing_prefixed_ids_matches_slice_takes(multiformat, sentinel_module):
    class T:
        def __init__(self, name):
            self._n = name
        def GetName(self):
            return self._n
        def GetDown(self):
            return None
        def GetNext(self):
            return getattr(self, "_next", None)

    class Main:
        def __init__(self, first):
            self._first = first
        def GetDown(self):
            return self._first
        def GetName(self):
            return "Main"
        def GetNext(self):
            return None

    class TD:
        def __init__(self, main):
            self._main = main
        def GetMainTake(self):
            return self._main

    a = T("Hero_custom_s01")
    b = T("Hero_9x16")
    a._next = b
    td = TD(Main(a))
    defs = [{"id": "9x16"}, {"id": "custom"}]
    assert multiformat._existing_prefixed_format_ids(td, "Hero", defs) == {"custom", "9x16"}


# ---------------------------------------------------------------------------
# Task 3: engine — format_defs option + slice variant generation.
# Fakes are reused BY IMPORT from the U4 harness (module-level classes that
# deliberately model the stored-DescID rigidity — do not redefine them).
# ---------------------------------------------------------------------------

from sentinel import framing  # noqa: E402  (pure module, no c4d import)
from test_multiformat_engine_u4 import FakeCamera, FakeDocument  # noqa: E402


def _make_cam(sentinel_module):
    cam = FakeCamera()
    cam[framing.CAMERA_FOCUS] = 36.0
    cam[framing.CAMERAOBJECT_APERTURE] = 36.0
    cam[framing.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
    cam[framing.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
    return cam


def _run_sliced(multiformat, sentinel_module, formats, format_defs,
                film_offsets=None, composition_mode="crop"):
    doc = FakeDocument(sentinel_module.c4d)
    cam = _make_cam(sentinel_module)
    links = {}
    report = multiformat.generate_multiformat_takes(doc, {
        "formats": formats,
        "format_defs": format_defs,
        "composition_mode": composition_mode,
        "name_prefix": "Hero",
        "source_cam": cam,
        "film_offsets": film_offsets or {},
        "tag_link_writer": lambda key, take: links.__setitem__(key, take),
    })
    return report, links, doc, cam


def test_engine_generates_slice_takes_for_custom_3x1(multiformat, sentinel_module):
    custom = {"id": "custom", "label": "Custom", "width": 9000, "height": 500,
              "slices": (3, 1)}
    report, links, doc, _cam = _run_sliced(
        multiformat, sentinel_module, ["custom"], [custom])
    assert report["success"] is True
    assert report["created"] == ["Hero_custom_s01", "Hero_custom_s02", "Hero_custom_s03"]
    assert set(links) == {"custom:s01", "custom:s02", "custom:s03"}
    # Each slice's RenderData: 3000x500, slice output subfolder.
    for n, key in enumerate(["custom:s01", "custom:s02", "custom:s03"], start=1):
        take = links[key]
        rd = take.GetRenderData(doc.GetTakeData())
        assert int(rd[sentinel_module.c4d.RDATA_XRES]) == 3000
        assert int(rd[sentinel_module.c4d.RDATA_YRES]) == 500
        assert "/custom/s%02d/" % n in "/" + rd[sentinel_module.c4d.RDATA_PATH]


def test_engine_slice_camera_overrides_match_window_math(multiformat, sentinel_module):
    custom = {"id": "custom", "label": "Custom", "width": 9000, "height": 500,
              "slices": (3, 1)}
    report, links, doc, cam = _run_sliced(
        multiformat, sentinel_module, ["custom"], [custom])
    assert report["errors"] == []
    sa = 1920.0 / 1080.0
    fmt_window = framing.format_crop_rect(1920, 1080, 9000, 500, None)
    expected = framing.slice_windows(fmt_window, 3, 1, 9000, 500)
    # Ocamera fake (aperture 36): check the s01 take's stored override params.
    take = links["custom:s01"]
    ovr = take.FindOverride(doc.take_data, cam)
    sub, _w, _h, _sfx = expected[0]
    factor, fx, fy = framing.window_crop_values(sub, sa, (0.0, 0.0))
    assert ovr.params[framing.CAMERAOBJECT_APERTURE] == pytest.approx(36.0 * factor)
    assert ovr.params[framing.CAMERAOBJECT_FILM_OFFSET_X] == pytest.approx(fx)
    assert ovr.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] == pytest.approx(fy)


def test_engine_1x1_format_defs_path_matches_legacy(multiformat, sentinel_module):
    # Passing format_defs WITHOUT slices must produce the same take names,
    # resolutions and paths as the legacy id-lookup path (v1.28 parity).
    def run(options_extra):
        doc = FakeDocument(sentinel_module.c4d)
        cam = _make_cam(sentinel_module)
        opts = {
            "formats": ["9x16"],
            "composition_mode": "crop",
            "name_prefix": "Hero",
            "source_cam": cam,
        }
        opts.update(options_extra)
        report = multiformat.generate_multiformat_takes(doc, opts)
        take = doc.take_data.main.children[0]
        rd = take.GetRenderData(doc.GetTakeData())
        return report, take, rd

    legacy_report, legacy_take, legacy_rd = run({})
    defs_report, defs_take, defs_rd = run(
        {"format_defs": [dict(multiformat.get_multiformat_def("9x16"))]})

    assert defs_report["created"] == legacy_report["created"] == ["Hero_9x16"]
    assert defs_report["notes"] == legacy_report["notes"] == []
    assert defs_take.GetName() == legacy_take.GetName()
    assert defs_rd.GetName() == legacy_rd.GetName()
    c4d = sentinel_module.c4d
    assert defs_rd[c4d.RDATA_XRES] == legacy_rd[c4d.RDATA_XRES]
    assert defs_rd[c4d.RDATA_YRES] == legacy_rd[c4d.RDATA_YRES]
    assert defs_rd[c4d.RDATA_PATH] == legacy_rd[c4d.RDATA_PATH]


def test_engine_slices_ignored_outside_crop_mode(multiformat, sentinel_module):
    custom = {"id": "custom", "label": "Custom", "width": 9000, "height": 500,
              "slices": (3, 1)}
    report, links, doc, _cam = _run_sliced(
        multiformat, sentinel_module, ["custom"], [custom],
        composition_mode="none")
    assert report["created"] == ["Hero_custom"]
    assert set(links) == {"custom"}
    assert any("slices ignored" in n for n in report["notes"])
