import os


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
