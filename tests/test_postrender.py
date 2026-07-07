import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTRENDER_PATH = ROOT / "plugin" / "sentinel" / "postrender.py"
VERSIONING_PATH = ROOT / "plugin" / "sentinel" / "versioning.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_postrender_under_test", POSTRENDER_PATH
)
postrender = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = postrender
spec.loader.exec_module(postrender)

versioning_spec = importlib.util.spec_from_file_location(
    "sentinel_versioning_under_test", VERSIONING_PATH
)
versioning = importlib.util.module_from_spec(versioning_spec)
sys.modules[versioning_spec.name] = versioning
versioning_spec.loader.exec_module(versioning)


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
            return 200_000 + (frame % 5) * 1000
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
    assert 1020 not in contaminated_result


def _state(**overrides):
    data = {
        "take_name": "Main",
        "is_main": True,
        "is_checked": True,
        "raw_path": "",
        "resolved_beauty_path": "",
        "multipass_save": False,
        "multipass_path": "",
        "xres": 1920,
        "yres": 1080,
        "format_id": 1016606,
        "multipass_format_id": 1016606,
        "frame_mode": 0,
        "frame_from": 1001,
        "frame_to": 1002,
        "timeline_min": 1001,
        "timeline_max": 1100,
        "current_frame": 1050,
        "fps": 25,
        "frame_step": 1,
        "redshift_available": False,
        "aov_multipart": False,
        "aov_global_path": "",
        "aovs": [],
        "light_groups": [],
        "doc_path": "",
        "version": "v007",
    }
    data.update(overrides)
    return data


def _touch_frame(folder, stem, frame, ext="exr", size=2048):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{frame:04d}.{ext}"
    path.write_bytes(b"x" * size)
    return path


def test_render_history_path_strips_version_status():
    assert versioning.render_history_path("/show/robot_010_v022_FINAL.c4d") == (
        "/show/robot_010_render_history.json"
    )
    assert versioning.render_history_path("/show/robot_010_v001.c4d") == (
        "/show/robot_010_render_history.json"
    )


def test_audit_manifest_missing_direct_aov_warns_but_multipart_does_not(tmp_path):
    folder = tmp_path / "missing_aov"
    for frame in (1001, 1002):
        _touch_frame(folder, "Beauty_", frame)
        _touch_frame(folder, "BeautyMultipart_", frame)

    direct_manifest = [{
        "take_name": "Main",
        "folder": str(folder),
        "beauty_prefix": "Beauty_",
        "ext": "exr",
        "frame_set": [1001, 1002],
        "aov_mode": "direct",
        "aov_files": [{"name": "Denoised", "prefix": "Beauty_Denoised_", "ext": "exr", "folder": str(folder)}],
        "multipart": None,
    }]
    direct_report = postrender.build_report(postrender.audit_manifest(direct_manifest, str(folder)))
    assert direct_report["checks"]["aov_missing"]["status"] == "WARN"
    assert direct_report["checks"]["aov_missing"]["count"] == 2

    multipart_manifest = [dict(direct_manifest[0], aov_mode="multipart", aov_files=[], multipart={
        "prefix": "BeautyMultipart_",
        "ext": "exr",
        "folder": str(folder),
    })]
    multipart_report = postrender.build_report(postrender.audit_manifest(multipart_manifest, str(folder)))
    assert multipart_report["checks"]["aov_missing"]["status"] == "OK"
    assert multipart_report["checks"]["aov_missing"]["count"] == 0


def test_direct_aov_partial_gap_warns_without_failing_beauty_missing(tmp_path):
    folder = tmp_path / "aov_partial_gap"
    for frame in (1001, 1002):
        _touch_frame(folder, "Beauty_", frame)
    _touch_frame(folder, "Beauty_Denoised_", 1001)
    manifest = [{
        "take_name": "Main",
        "folder": str(folder),
        "beauty_prefix": "Beauty_",
        "ext": "exr",
        "frame_set": [1001, 1002],
        "aov_mode": "direct",
        "aov_files": [{"name": "Denoised", "prefix": "Beauty_Denoised_", "ext": "exr", "folder": str(folder)}],
        "multipart": None,
    }]

    report = postrender.build_report(postrender.audit_manifest(manifest, str(folder)))

    assert report["passed"] is True
    assert report["checks"]["missing"]["count"] == 0
    assert report["checks"]["aov_missing"]["count"] >= 1


def test_audit_manifest_marks_missing_multitake_format_coverage(tmp_path):
    root = tmp_path / "multi_take"
    manifest = []
    for fmt in ("16x9", "9x16", "1x1", "4x5", "21x9"):
        folder = root / fmt
        if fmt != "9x16":
            _touch_frame(folder, "beauty_", 1001)
        manifest.append({
            "take_name": fmt,
            "folder": str(folder),
            "beauty_prefix": "beauty_",
            "ext": "exr",
            "frame_set": [1001],
            "xres": 1920,
            "yres": 1080,
            "aov_mode": "none",
            "aov_files": [],
            "multipart": None,
        })

    report = postrender.build_report(postrender.audit_manifest(manifest, str(root)))

    assert report["checks"]["coverage_missing"]["status"] == "WARN"
    assert any(
        item["take_name"] == "9x16"
        for item in report["checks"]["coverage_missing"]["items"]
    )


def test_coverage_missing_only_when_beauty_stream_produces_nothing(tmp_path):
    partial = tmp_path / "partial_gap"
    empty = tmp_path / "empty_take"
    frame_set = list(range(1001, 1101))
    for frame in frame_set:
        if frame != 1050:
            _touch_frame(partial, "beauty_", frame)
    empty.mkdir()
    manifest = [
        {
            "take_name": "Partial",
            "folder": str(partial),
            "beauty_prefix": "beauty_",
            "ext": "exr",
            "frame_set": frame_set,
            "xres": 1920,
            "yres": 1080,
            "aov_mode": "none",
            "aov_files": [],
            "multipart": None,
        },
        {
            "take_name": "Empty",
            "folder": str(empty),
            "beauty_prefix": "beauty_",
            "ext": "exr",
            "frame_set": frame_set,
            "xres": 1920,
            "yres": 1080,
            "aov_mode": "none",
            "aov_files": [],
            "multipart": None,
        },
    ]

    report = postrender.build_report(postrender.audit_manifest(manifest, str(tmp_path)))
    coverage_takes = {
        item["take_name"]
        for item in report["checks"]["coverage_missing"]["items"]
    }

    assert "Partial" not in coverage_takes
    assert "Empty" in coverage_takes


def test_build_manifest_dedups_inherited_child_render_state(tmp_path):
    path = str(tmp_path / "beauty_1001")
    states = [
        _state(take_name="Main", is_main=True, is_checked=True, resolved_beauty_path=path),
        _state(take_name="Child", is_main=False, is_checked=True, resolved_beauty_path=path),
    ]

    manifest = postrender.build_manifest_from_state(states, str(tmp_path))

    assert len(manifest) == 1
    assert manifest[0]["beauty_prefix"] == "beauty_"


def test_build_manifest_frame_modes_use_literal_values(tmp_path):
    manual = postrender.build_manifest_from_state([
        _state(frame_mode=0, frame_from=1001, frame_to=1005, frame_step=2, resolved_beauty_path=str(tmp_path / "manual_1001"))
    ])
    current = postrender.build_manifest_from_state([
        _state(frame_mode=1, current_frame=1042, resolved_beauty_path=str(tmp_path / "current_1042"))
    ])
    allframes = postrender.build_manifest_from_state([
        _state(frame_mode=2, timeline_min=1010, timeline_max=1012, resolved_beauty_path=str(tmp_path / "all_1010"))
    ])

    assert manual[0]["frame_set"] == postrender.expected_frames(1001, 1005, 2)
    assert current[0]["frame_set"] == [1042]
    assert allframes[0]["frame_set"] == postrender.expected_frames(1010, 1012, 1)


def test_build_manifest_single_render_includes_main(tmp_path):
    manifest = postrender.build_manifest_from_state([
        _state(is_main=True, is_checked=False, resolved_beauty_path=str(tmp_path / "beauty_1001"))
    ])

    assert len(manifest) == 1
    assert manifest[0]["take_name"] == "Main"


def test_build_manifest_excludes_unchecked_main_when_children_exist(tmp_path):
    manifest = postrender.build_manifest_from_state([
        _state(take_name="Main", is_main=True, is_checked=False, resolved_beauty_path=str(tmp_path / "main_1001")),
        _state(take_name="9x16", is_main=False, is_checked=True, resolved_beauty_path=str(tmp_path / "9x16_1001")),
    ])

    assert [entry["take_name"] for entry in manifest] == ["9x16"]


def test_separator_qualified_prefix_avoids_common_collision(tmp_path):
    folder = tmp_path / "collision"
    _touch_frame(folder, "beauty_", 1001, size=2048)
    _touch_frame(folder, "beautyMask_", 1001, size=100)
    manifest = postrender.build_manifest_from_state([
        _state(resolved_beauty_path=str(folder / "beauty_1001"), frame_from=1001, frame_to=1001)
    ])

    assert manifest[0]["beauty_prefix"] == "beauty_"
    scan = postrender.audit_manifest(manifest, str(folder))["streams"][0]["scan"]
    assert scan["truncated"] == []
    assert scan["found"] == [1001]


def test_zfill_fallback_path_without_frame_uses_stem_prefix(tmp_path):
    folder = tmp_path / "fallback"
    _touch_frame(folder, "beauty_", 1001)
    _touch_frame(folder, "beauty_", 1002)

    manifest = postrender.build_manifest_from_state([
        _state(resolved_beauty_path=str(folder / "beauty"))
    ])

    assert manifest[0]["beauty_prefix"] == "beauty"
    assert postrender.audit_manifest(manifest, str(folder))["streams"][0]["scan"]["found"] == [1001, 1002]


def test_unsaved_doc_manifest_uses_audit_folder(tmp_path):
    manifest = postrender.build_manifest_from_state([
        _state(raw_path="beauty", resolved_beauty_path="", doc_path="")
    ], str(tmp_path))

    assert manifest[0]["folder"] == str(tmp_path)


def test_low_variance_flat_plane_documents_mad_escape_and_warn_severity():
    flat_sizes = {frame: 5_000_000 for frame in range(1001, 1101)}
    flat_sizes[1050] = 200_000

    assert postrender.size_outliers(flat_sizes) == []

    report = postrender.build_report({"categories": {"size_outliers": [{"frame": 1050}]}, "manifest": [], "streams": []})
    assert report["checks"]["size_outliers"]["status"] == "WARN"


def test_u6_complete_report_and_render_history_do_not_touch_versions_history(tmp_path):
    folder = _fixture_single_complete(tmp_path)
    manifest = [{
        "take_name": "Main",
        "folder": str(folder),
        "beauty_prefix": "beauty",
        "ext": "exr",
        "frame_set": list(FRAMES),
        "aov_mode": "none",
        "aov_files": [],
        "multipart": None,
        "version": "v007",
    }]
    report = postrender.build_report(postrender.audit_manifest(manifest, str(folder)))
    doc_path = tmp_path / "robot_010_v007_TR.c4d"
    versions_history = tmp_path / "robot_010_history.json"
    versions_history.write_text('{"versions":[{"version":7}]}\n')
    before_hash = hashlib.sha256(versions_history.read_bytes()).hexdigest()

    assert report["passed"] is True
    assert all(check["status"] == "OK" for check in report["checks"].values())
    assert postrender.append_render_history(str(doc_path), report) is True

    assert hashlib.sha256(versions_history.read_bytes()).hexdigest() == before_hash
    render_history = json.loads((tmp_path / "robot_010_render_history.json").read_text())
    assert render_history["render_validations"][0]["type"] == "render_validation"


def test_render_history_shared_across_versions(tmp_path):
    first = {"passed": True, "checks": {}, "context": {"version": "v007_TR"}}
    second = {"passed": False, "checks": {"missing": {"count": 1}}, "context": {"version": "v008"}}

    assert postrender.append_render_history(str(tmp_path / "robot_010_v007_TR.c4d"), first)
    assert postrender.append_render_history(str(tmp_path / "robot_010_v008.c4d"), second)

    history_path = tmp_path / "robot_010_render_history.json"
    history = json.loads(history_path.read_text())
    assert len(history["render_validations"]) == 2
    assert not (tmp_path / "robot_010_v007_TR_render_history.json").exists()


def test_write_report_atomic_failure_leaves_prior_intact(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text('{"ok": true}\n')

    def boom(*_args, **_kwargs):
        raise RuntimeError("dump failed")

    monkeypatch.setattr(postrender.json, "dump", boom)

    assert postrender.write_report_atomic(str(path), {"ok": False}) is False
    assert path.read_text() == '{"ok": true}\n'
    assert not list(tmp_path.glob("report.json.tmp.*"))


def test_report_single_category_dedup_for_zero_byte(tmp_path):
    folder = tmp_path / "zero"
    _touch_frame(folder, "beauty_", 1001, size=0)
    manifest = [{
        "take_name": "Main",
        "folder": str(folder),
        "beauty_prefix": "beauty_",
        "ext": "exr",
        "frame_set": [1001],
        "aov_mode": "none",
        "aov_files": [],
        "multipart": None,
    }]

    report = postrender.build_report(postrender.audit_manifest(manifest, str(folder)))

    assert report["checks"]["zero_byte"]["count"] == 1
    assert report["checks"]["truncated"]["count"] == 0
    assert report["checks"]["size_outliers"]["count"] == 0


def test_report_cap_preserves_total_count():
    findings = {
        "categories": {"missing": [{"frame": frame} for frame in range(500)]},
        "manifest": [],
        "streams": [],
    }

    report = postrender.build_report(findings)

    assert report["checks"]["missing"]["count"] == 500
    assert len(report["checks"]["missing"]["items"]) == 50


def test_doc_without_path_report_and_history_use_audited_folder(tmp_path):
    report = {"passed": True, "checks": {}, "context": {}}
    report_path = postrender.report_path_for_doc("", str(tmp_path))

    assert report_path == str(tmp_path / "sentinel_render_report.json")
    assert postrender.write_report_atomic(report_path, report)
    assert postrender.append_render_history(str(tmp_path), report)
    assert (tmp_path / "sentinel_render_report.json").exists()
    assert (tmp_path / "sentinel_render_history.json").exists()


def test_malformed_render_sidecar_is_replaced_without_crash(tmp_path):
    history_path = tmp_path / "robot_010_render_history.json"
    history_path.write_text("{not json")

    assert postrender.append_render_history(str(tmp_path / "robot_010_v001.c4d"), {
        "passed": True,
        "checks": {},
        "context": {"version": "v001"},
    })
    history = json.loads(history_path.read_text())
    assert len(history["render_validations"]) == 1
