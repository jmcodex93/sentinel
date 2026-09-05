import os


def test_save_history_dump_failure_preserves_existing_bytes_and_cleans_temp(
        sentinel_module, tmp_path, monkeypatch):
    from sentinel import versioning

    path = tmp_path / "shot_history.json"
    original = b'{"versions":[{"version":1}]}\n'
    path.write_bytes(original)

    def fail_after_partial_write(data, handle, **kwargs):
        handle.write('{"versions":[')
        raise RuntimeError("disk full")

    monkeypatch.setattr(versioning.json, "dump", fail_after_partial_write)

    assert versioning.save_history(str(path), {"versions": []}) is False
    assert path.read_bytes() == original
    assert list(tmp_path.glob("shot_history.json.tmp.*")) == []


def test_save_history_replace_failure_preserves_existing_bytes_and_cleans_temp(
        sentinel_module, tmp_path, monkeypatch):
    from sentinel import versioning

    path = tmp_path / "shot_history.json"
    original = b'{"versions":[{"version":1}]}\n'
    path.write_bytes(original)
    monkeypatch.setattr(versioning.os, "replace",
                        lambda source, target: (_ for _ in ()).throw(OSError("locked")))

    assert versioning.save_history(str(path), {"versions": []}) is False
    assert path.read_bytes() == original
    assert list(tmp_path.glob("shot_history.json.tmp.*")) == []


def test_save_notes_replace_failure_preserves_existing_bytes_and_cleans_temp(
        sentinel_module, tmp_path, monkeypatch):
    from sentinel import notes

    path = tmp_path / "shot_notes.json"
    original = b'{"notes":"keep me","todos":[]}\n'
    path.write_bytes(original)
    monkeypatch.setattr(notes.os, "replace",
                        lambda source, target: (_ for _ in ()).throw(OSError("locked")))

    assert notes.save_notes(str(path), {"notes": "new", "todos": []}) is False
    assert path.read_bytes() == original
    assert list(tmp_path.glob("shot_notes.json.tmp.*")) == []


def test_save_notes_dump_failure_preserves_existing_bytes_and_cleans_temp(
        sentinel_module, tmp_path, monkeypatch):
    from sentinel import notes

    path = tmp_path / "shot_notes.json"
    original = b'{"notes":"keep me","todos":[]}\n'
    path.write_bytes(original)

    def fail_after_partial_write(data, handle, **kwargs):
        handle.write('{"notes":"partial')
        raise RuntimeError("disk full")

    monkeypatch.setattr(notes.json, "dump", fail_after_partial_write)

    assert notes.save_notes(str(path), {"notes": "new", "todos": []}) is False
    assert path.read_bytes() == original
    assert list(tmp_path.glob("shot_notes.json.tmp.*")) == []


def test_parse_version_filename_with_statuses(sentinel_module):
    parse = sentinel_module.parse_version_filename

    assert parse("robot_010_v014_CR") == ("robot_010", 14, "CR")
    assert parse("shot_A_v007_TR") == ("shot_A", 7, "TR")
    assert parse("scene_v003") == ("scene", 3, None)
    assert parse("scene") == ("scene", None, None)
    assert parse("scene_v") == ("scene_v", None, None)
    assert parse("") == ("", None, None)


def test_build_versioned_filename_sanitizes_status(sentinel_module):
    build = sentinel_module.build_versioned_filename

    assert build("scene", 3) == "scene_v003.c4d"
    assert build("scene", 3, "TR") == "scene_v003_TR.c4d"
    assert build("scene", 12, "rev-02") == "scene_v012_REV02.c4d"
    assert build("", 1, " client review ") == "scene_v001_CLIENTREVIEW.c4d"
    assert build("scene", 5, extension="bak") == "scene_v005.bak"


def test_leading_digit_status_round_trips_and_shares_sidecars(sentinel_module, tmp_path):
    build = sentinel_module.build_versioned_filename
    parse = sentinel_module.parse_version_filename

    filename = build("shot", 7, "2d-review")
    path = tmp_path / filename
    path.write_bytes(b"")

    assert filename == "shot_v007_2DREVIEW.c4d"
    assert parse(path.stem) == ("shot", 7, "2DREVIEW")
    assert sentinel_module.get_history_path(str(path)) == str(tmp_path / "shot_history.json")
    assert sentinel_module.compute_next_version(str(path)) == ("shot", 8)


def test_get_history_path_strips_version_and_status(sentinel_module, tmp_path):
    path = tmp_path / "robot_010_v014_FINAL.c4d"

    assert sentinel_module.get_history_path(str(path)) == str(
        tmp_path / "robot_010_history.json"
    )


def test_compute_next_version_ignores_status_tags(sentinel_module, tmp_path):
    for name in [
        "shot_v001.c4d",
        "shot_v002_TR.c4d",
        "shot_v007_FINAL.c4d",
        "other_v099.c4d",
        "shot_notes.json",
    ]:
        (tmp_path / name).write_text("", encoding="utf-8")

    base, version = sentinel_module.compute_next_version(
        os.path.join(str(tmp_path), "shot_v002_TR.c4d")
    )

    assert base == "shot"
    assert version == 8


def test_history_qc_label_marks_old_schema_entries_legacy(sentinel_module):
    legacy = {"qc_score": "8/12", "qc_pass": False}
    current = {
        "schema": 2,
        "qc_score": "11/12",
        "qc_pass": False,
        "new": 1,
        "accepted": 4,
    }

    assert sentinel_module.format_history_qc_label(legacy) == "8/12 (legacy)"
    assert sentinel_module.format_version_row(legacy)["qc_label"] == "8/12 (legacy)"
    assert sentinel_module.format_history_qc_label(current) == "11/12 · 1 new · 4 accepted"


def test_history_qc_label_ignores_qc_counts_vector(sentinel_module):
    """qc_counts (the per-check trajectory vector) never changes rendering."""
    # Legacy v1 entries without the vector render exactly as before.
    legacy_v1 = {"qc_score": "8/12", "qc_pass": False}
    assert sentinel_module.format_history_qc_label(legacy_v1) == "8/12 (legacy)"

    # A schema-2 entry carrying qc_counts renders identically to one without
    # it — readers only use qc_score/schema/new/accepted.
    without = {"schema": 2, "qc_score": "11/12", "qc_pass": False, "new": 1, "accepted": 4}
    with_vector = dict(without, qc_counts={"names": 1, "cam": 0, "lights": 0})
    assert (
        sentinel_module.format_history_qc_label(with_vector)
        == sentinel_module.format_history_qc_label(without)
        == "11/12 · 1 new · 4 accepted"
    )
    # And it flows through format_version_row untouched too.
    assert (
        sentinel_module.format_version_row(with_vector)["qc_label"]
        == "11/12 · 1 new · 4 accepted"
    )
    # A legacy v2-era entry that also carried qc_counts (they always did —
    # flows.py has persisted it on every QC-bearing save) renders unchanged.
    legacy_with_counts = dict(legacy_v1, qc_counts={"names": 4})
    assert sentinel_module.format_history_qc_label(legacy_with_counts) == "8/12 (legacy)"


def test_versioning_remains_importable_by_path_without_plugin_on_sys_path():
    """Fresh isolated process prevents the C4D test harness masking imports."""
    import subprocess
    import sys
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / 'plugin' / 'sentinel' / 'versioning.py'
    result = subprocess.run(
        [sys.executable, '-I', '-c',
         'import runpy, sys; m = runpy.run_path(sys.argv[1]); '
         'assert m["parse_version_filename"]("shot_v002_TR") == ("shot", 2, "TR"); '
         'from pathlib import Path; '
         '[runpy.run_path(str(Path(sys.argv[1]).with_name(name))) '
         'for name in ("baseline.py", "postrender.py", "supervisor.py")]',
         str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
