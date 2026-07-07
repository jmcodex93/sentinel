import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTRENDER_PATH = ROOT / "plugin" / "sentinel" / "postrender.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_postrender_under_test", POSTRENDER_PATH
)
postrender = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = postrender
spec.loader.exec_module(postrender)


BASE = 2_000_000_000.0
FRAMES = range(1001, 1101)


def _nominal_size(frame):
    return 5_000_000 + (frame % 7) * 1000


def _make_seq(
    folder,
    start,
    end,
    size_fn,
    mtime_fn,
    ext,
    prefix="beauty",
    sep="_",
    skip=(),
):
    """Create a dummy frame sequence on disk.

    folder   : pathlib.Path (created if missing)
    start,end : inclusive frame range (both endpoints written)
    size_fn  : callable(frame:int) -> int  bytes to write for that frame (0 => 0-byte)
    mtime_fn : callable(frame:int) -> float  epoch seconds; set via os.utime
    ext      : extension WITHOUT dot, e.g. "exr"
    prefix   : filename stem before the frame number, e.g. "beauty"
    sep      : separator between prefix and 4-digit frame: "_" (beauty_1001) or "." (beauty.1001)
    skip     : frames NOT to write (to punch a gap)
    Returns the list of written file paths.
    """
    folder.mkdir(parents=True, exist_ok=True)
    skipped = set(skip)
    paths = []
    for frame in range(start, end + 1):
        if frame in skipped:
            continue
        path = folder / f"{prefix}{sep}{frame:04d}.{ext}"
        path.write_bytes(b"\0" * size_fn(frame))
        mtime = mtime_fn(frame)
        os.utime(path, (mtime, mtime))
        paths.append(path)
    return paths


def _fixture_single_complete(tmp_path):
    folder = tmp_path / "single_complete"
    _make_seq(
        folder,
        1001,
        1100,
        _nominal_size,
        lambda frame: BASE + (frame - 1001) * 60,
        "exr",
    )
    return folder


def _fixture_gap_truncated(tmp_path):
    folder = tmp_path / "gap_truncated"

    def size(frame):
        if frame == 1050:
            return 0
        if frame == 1075:
            return 512
        return _nominal_size(frame)

    _make_seq(
        folder,
        1001,
        1100,
        size,
        lambda frame: BASE + (frame - 1001) * 60,
        "exr",
        sep=".",
        skip=(1043,),
    )
    (folder / "notes.txt").write_text("ignore me")
    return folder


def _fixture_black_frame(tmp_path):
    folder = tmp_path / "black_frame"
    _make_seq(
        folder,
        1001,
        1100,
        lambda frame: 200_000 if frame == 1057 else _nominal_size(frame),
        lambda frame: BASE + (frame - 1001) * 60,
        "exr",
    )
    return folder


def _fixture_stale_overwrite(tmp_path):
    folder = tmp_path / "stale_overwrite"
    _make_seq(
        folder,
        1001,
        1100,
        _nominal_size,
        lambda frame: (
            BASE + (frame - 1001) * 60
            if frame < 1050
            else BASE - 100_000 + (frame - 1050) * 60
        ),
        "exr",
    )
    return folder


def _fixture_long_render_spread(tmp_path):
    folder = tmp_path / "long_render_spread"
    _make_seq(
        folder,
        1001,
        1100,
        _nominal_size,
        lambda frame: BASE + (frame - 1001) * 300,
        "exr",
    )
    return folder


def _fixture_stale_plus_black(tmp_path):
    folder = tmp_path / "stale_plus_black"

    def size(frame):
        if frame == 1020:
            return 200_000
        if frame >= 1050:
            return 3_000_000 + (frame % 5) * 1000
        return _nominal_size(frame)

    _make_seq(
        folder,
        1001,
        1100,
        size,
        lambda frame: (
            BASE + (frame - 1001) * 60
            if frame < 1050
            else BASE - 100_000 + (frame - 1050) * 60
        ),
        "exr",
    )
    return folder


def _scan(folder):
    return postrender.scan_sequence(
        folder, "beauty", postrender.expected_frames(1001, 1100, 1), "exr"
    )


def _sizes(folder, frames):
    return {
        frame: os.path.getsize(folder / f"beauty_{frame:04d}.exr")
        for frame in frames
    }


def test_postrender_module_is_pure_python():
    assert "c4d" not in sys.modules or getattr(sys.modules["c4d"], "__name__", "") == "c4d"
    assert not any(name == "c4d" for name in postrender.__dict__)


def test_expected_frames_arithmetic():
    assert len(postrender.expected_frames(1001, 1100, 1)) == 100
    assert len(postrender.expected_frames(1001, 1100, 2)) == 50
    assert postrender.expected_frames(1057, 1057, 1) == [1057]


def test_scan_single_complete_sequence(tmp_path):
    result = _scan(_fixture_single_complete(tmp_path))

    assert result["missing"] == []
    assert result["zero_byte"] == []
    assert result["truncated"] == []
    assert result["stale"] == []
    assert result["found"] == list(FRAMES)


def test_scan_gap_zero_byte_and_truncated_sequence(tmp_path):
    result = _scan(_fixture_gap_truncated(tmp_path))

    assert result["missing"] == [1043]
    assert result["zero_byte"] == [1050]
    assert result["truncated"] == [1075]
    assert 1050 not in result["found"]
    assert 1075 not in result["found"]


def test_scan_stale_overwrite_excludes_stale_from_found(tmp_path):
    result = _scan(_fixture_stale_overwrite(tmp_path))
    stale = list(range(1050, 1101))

    assert result["stale"] == stale
    assert not any(frame in result["found"] for frame in stale)
    assert result["found"] == list(range(1001, 1050))


def test_scan_long_render_spread_is_not_stale(tmp_path):
    result = _scan(_fixture_long_render_spread(tmp_path))

    assert result["stale"] == []
    assert result["found"] == list(FRAMES)


def test_scan_parses_padding_separator_trailing_digits_and_extension(tmp_path):
    underscore = tmp_path / "underscore"
    dot = tmp_path / "dot"
    digit_prefix = tmp_path / "digit_prefix"
    _make_seq(
        underscore,
        1001,
        1001,
        _nominal_size,
        lambda frame: BASE,
        "exr",
        sep="_",
    )
    _make_seq(
        dot,
        1001,
        1001,
        _nominal_size,
        lambda frame: BASE,
        "exr",
        sep=".",
    )
    _make_seq(
        digit_prefix,
        1001,
        1001,
        _nominal_size,
        lambda frame: BASE,
        "exr",
        prefix="shot_010_beauty",
    )
    (underscore / "beauty_1002.txt").write_text("wrong extension")

    assert postrender.scan_sequence(underscore, "beauty", [1001, 1002], "exr") == {
        "found": [1001],
        "missing": [1002],
        "zero_byte": [],
        "truncated": [],
        "stale": [],
    }
    assert postrender.scan_sequence(dot, "beauty", [1001], "exr")["found"] == [1001]
    assert postrender.scan_sequence(
        digit_prefix, "shot_010_beauty", [1001], "exr"
    )["found"] == [1001]


def test_scan_empty_and_nonexistent_folders_report_missing(tmp_path):
    expected = [1001, 1002, 1003]
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = tmp_path / "does_not_exist"

    assert postrender.scan_sequence(empty, "beauty", expected, "exr") == {
        "found": [],
        "missing": expected,
        "zero_byte": [],
        "truncated": [],
        "stale": [],
    }
    assert postrender.scan_sequence(missing, "beauty", expected, "exr") == {
        "found": [],
        "missing": expected,
        "zero_byte": [],
        "truncated": [],
        "stale": [],
    }


def test_detect_stale_cluster_direct_cases():
    bimodal = {
        1001: BASE - 100_000,
        1002: BASE - 99_940,
        1003: BASE - 99_880,
        1004: BASE,
        1005: BASE + 60,
        1006: BASE + 120,
    }
    uniform = {frame: BASE + i * 300 for i, frame in enumerate(range(1001, 1007))}
    identical = {1001: BASE, 1002: BASE, 1003: BASE}

    assert postrender.detect_stale_cluster(bimodal) == [1001, 1002, 1003]
    assert postrender.detect_stale_cluster(uniform) == []
    assert postrender.detect_stale_cluster(identical) == []
    assert postrender.detect_stale_cluster({1001: BASE, 1002: BASE + 60}) == []


def test_size_outliers_flags_black_frame(tmp_path):
    folder = _fixture_black_frame(tmp_path)
    sizes = _sizes(folder, FRAMES)

    assert 1057 in postrender.size_outliers(sizes)


def test_size_outliers_uniform_sequence_is_clean(tmp_path):
    folder = _fixture_single_complete(tmp_path)
    sizes = _sizes(folder, FRAMES)

    assert postrender.size_outliers(sizes) == []


def test_size_outliers_flags_large_high_outlier():
    sizes = {frame: 5_000_000 + (frame % 7) * 1000 for frame in range(1001, 1101)}
    sizes[1088] = 5_100_000

    assert postrender.size_outliers(sizes) == [1088]


def test_size_outliers_small_samples_and_all_equal_are_clean():
    assert postrender.size_outliers({1001: 5_000_000}) == []
    assert postrender.size_outliers({1001: 5_000_000, 1002: 5_001_000}) == []
    assert postrender.size_outliers({1001: 5_000_000, 1002: 5_000_000, 1003: 5_000_000}) == []


def test_size_outliers_requires_clean_population_for_stale_plus_black(tmp_path):
    folder = _fixture_stale_plus_black(tmp_path)
    scan = _scan(folder)
    clean_frames = [frame for frame in scan["found"]]
    contaminated_frames = list(FRAMES)

    clean_result = postrender.size_outliers(_sizes(folder, clean_frames))
    contaminated_result = postrender.size_outliers(_sizes(folder, contaminated_frames))

    assert 1020 in clean_result
    assert contaminated_result != clean_result
    assert 1020 not in contaminated_result or set(contaminated_result) != set(clean_result)
