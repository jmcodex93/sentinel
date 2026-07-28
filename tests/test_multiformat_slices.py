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
