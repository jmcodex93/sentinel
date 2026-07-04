import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "plugin" / "sentinel" / "baseline.py"

spec = importlib.util.spec_from_file_location("sentinel_baseline_under_test", BASELINE_PATH)
baseline = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = baseline
spec.loader.exec_module(baseline)


DATE = "2026-07-04T12:00:00+00:00"


def object_violation(check_id, path, sibling_index=0, guid="guid-a", fmt_id=None, frame=None):
    identity = {
        "type": "object",
        "path": path,
        "sibling_index": sibling_index,
        "guid": guid,
    }
    if fmt_id is not None:
        identity["fmt_id"] = fmt_id
    if frame is not None:
        identity["frame"] = frame
    return {"check_id": check_id, "identity": identity, "message": path}


def param_violation(check_id, param, value, preset=None, take=None, field=None):
    identity = {
        "type": "parameter",
        "param": param,
        "value": value,
    }
    if preset is not None:
        identity["preset"] = preset
    if take is not None:
        identity["take"] = take
    if field is not None:
        identity["field"] = field
    return {"check_id": check_id, "identity": identity, "message": str(param)}


def entry_from_violation(violation, snapshot=None, author="artist", reason="accepted"):
    identity = dict(violation["identity"])
    identity_type = identity.pop("type", identity.get("kind"))
    identity["kind"] = "param" if identity_type == "parameter" else identity_type
    return {
        "check_id": violation["check_id"],
        "identity": identity,
        "param_snapshot": snapshot,
        "author": author,
        "reason": reason,
        "date": DATE,
    }


def read_payload(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_payload(path, entries):
    path.write_text(
        json.dumps({"schema": 1, "entries": entries}, indent=2),
        encoding="utf-8",
    )


def test_get_baseline_path_strips_version_and_status():
    path = baseline.get_baseline_path("/shots/robot_010_v014_TR.c4d")

    assert path == "/shots/robot_010_baseline.json"


def test_accept_five_then_match_same_five_reports_all_accepted(tmp_path):
    path = tmp_path / "shot_baseline.json"
    violations = [
        object_violation("default_names", f"/Root/Cube[{index}]", index, f"guid-{index}")
        for index in range(5)
    ]
    for violation in violations:
        assert baseline.add_acceptance(str(path), entry_from_violation(violation))

    entries, status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, violations)

    assert status == "ok"
    assert matched["new"] == []
    assert matched["accepted"] == violations
    assert matched["stale_entries"] == []
    assert read_payload(path)["schema"] == 1


def test_unaccepted_sixth_violation_is_new(tmp_path):
    path = tmp_path / "shot_baseline.json"
    accepted = [
        object_violation("default_names", f"/Root/Cube[{index}]", index, f"guid-{index}")
        for index in range(5)
    ]
    for violation in accepted:
        baseline.add_acceptance(str(path), entry_from_violation(violation))
    new_violation = object_violation("default_names", "/Root/Sphere", 0, "guid-new")

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, accepted + [new_violation])

    assert matched["new"] == [new_violation]
    assert matched["accepted"] == accepted
    assert matched["stale_entries"] == []


def test_renamed_object_rearms_and_marks_old_entry_stale(tmp_path):
    path = tmp_path / "shot_baseline.json"
    original = object_violation("default_names", "/Root/Cube", 0, "guid-a")
    renamed = object_violation("default_names", "/Root/HeroBox", 0, "guid-a")
    baseline.add_acceptance(str(path), entry_from_violation(original))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [renamed])

    assert matched["new"] == [renamed]
    assert matched["accepted"] == []
    assert matched["stale_entries"] == [entry_from_violation(original)]


def test_guid_mismatch_delete_shift_rearms_and_marks_stale(tmp_path):
    path = tmp_path / "shot_baseline.json"
    original = object_violation("default_names", "/Root/Cube[0]", 0, "guid-old")
    shifted = object_violation("default_names", "/Root/Cube[0]", 0, "guid-new")
    baseline.add_acceptance(str(path), entry_from_violation(original))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [shifted])

    assert matched["new"] == [shifted]
    assert matched["accepted"] == []
    assert matched["stale_entries"] == [entry_from_violation(original)]


def test_param_snapshot_mismatch_rearms_and_marks_stale(tmp_path):
    path = tmp_path / "shot_baseline.json"
    violation = param_violation("fps_range", "standard_fps", 25)
    baseline.add_acceptance(str(path), entry_from_violation(violation, snapshot=25))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [violation], current_params={"standard_fps": 24})

    assert matched["new"] == [violation]
    assert matched["accepted"] == []
    assert matched["stale_entries"] == [entry_from_violation(violation, snapshot=25)]


def test_param_snapshot_match_accepts_violation(tmp_path):
    path = tmp_path / "shot_baseline.json"
    violation = param_violation("fps_range", "standard_fps", 25)
    baseline.add_acceptance(str(path), entry_from_violation(violation, snapshot=25))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [violation], current_params={"standard_fps": 25})

    assert matched["new"] == []
    assert matched["accepted"] == [violation]
    assert matched["stale_entries"] == []


def test_cross_aspect_uses_format_not_frame_for_identity(tmp_path):
    path = tmp_path / "shot_baseline.json"
    accepted = object_violation("cross_aspect", "/Root/Logo", 0, "guid-logo", fmt_id="9x16", frame=1001)
    later_frame = object_violation("cross_aspect", "/Root/Logo", 0, "guid-logo", fmt_id="9x16", frame=1040)
    other_format = object_violation("cross_aspect", "/Root/Logo", 0, "guid-logo", fmt_id="1x1", frame=1040)
    baseline.add_acceptance(str(path), entry_from_violation(accepted))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [later_frame, other_format])

    assert matched["accepted"] == [later_frame]
    assert matched["new"] == [other_format]


def test_add_acceptance_rereads_existing_file_so_both_entries_survive(tmp_path):
    path = tmp_path / "shot_baseline.json"
    first = object_violation("default_names", "/Root/Cube", 0, "guid-a")
    second = object_violation("visibility", "/Root/Sphere", 0, "guid-b")

    assert baseline.add_acceptance(str(path), entry_from_violation(first))
    assert baseline.add_acceptance(str(path), entry_from_violation(second))

    entries, status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [first, second])

    assert status == "ok"
    assert matched["new"] == []
    assert matched["accepted"] == [first, second]
    assert read_payload(path)["schema"] == 1


def test_corrupt_json_blocks_writes_and_preserves_bytes(tmp_path):
    path = tmp_path / "shot_baseline.json"
    path.write_bytes(b'{"schema": 1, "entries": [')
    before = path.read_bytes()
    violation = object_violation("default_names", "/Root/Cube", 0, "guid-a")

    entries, status = baseline.load_baseline(str(path))
    result = baseline.add_acceptance(str(path), entry_from_violation(violation))

    assert entries == []
    assert status == "invalid"
    assert result is False
    assert path.read_bytes() == before


def test_conflict_copy_merge_unions_entries_and_keeps_copies(tmp_path):
    path = tmp_path / "shot_baseline.json"
    main_violation = object_violation("default_names", "/Root/Cube", 0, "guid-a")
    first_copy_violation = object_violation("visibility", "/Root/Sphere", 0, "guid-b")
    second_copy_violation = param_violation("fps_range", "standard_fps", 25)
    first_copy = tmp_path / "shot_baseline (Javier conflicted copy 2026-07-04).json"
    second_copy = tmp_path / "shot_baseline SynologyDrive-conflict copy.json"
    write_payload(path, [entry_from_violation(main_violation)])
    write_payload(first_copy, [entry_from_violation(first_copy_violation)])
    write_payload(second_copy, [entry_from_violation(second_copy_violation, snapshot=25)])

    merged_count, copy_paths = baseline.merge_conflict_copies(str(path))

    entries, status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(
        entries,
        [main_violation, first_copy_violation, second_copy_violation],
        current_params={"standard_fps": 25},
    )
    assert status == "ok"
    assert merged_count == 2
    assert set(copy_paths) == {str(first_copy), str(second_copy)}
    assert matched["new"] == []
    assert matched["accepted"] == [main_violation, first_copy_violation, second_copy_violation]
    assert first_copy.exists()
    assert second_copy.exists()
    assert read_payload(path)["schema"] == 1


def test_remove_acceptance_writes_schema_and_rearms_violation(tmp_path):
    path = tmp_path / "shot_baseline.json"
    violation = object_violation("default_names", "/Root/Cube", 0, "guid-a")
    entry = entry_from_violation(violation)
    baseline.add_acceptance(str(path), entry)

    assert baseline.remove_acceptance(str(path), entry)

    entries, status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [violation])
    assert status == "ok"
    assert read_payload(path)["schema"] == 1
    assert entries == []
    assert matched["new"] == [violation]
    assert matched["accepted"] == []
