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


def cross_aspect_violation(path, sibling_index=0, guid="guid-a", fmt_id="9x16"):
    return {
        "check_id": "cross_aspect",
        "identity": {
            "type": "cross_aspect_safe_area",
            "object": {
                "type": "object",
                "path": path,
                "sibling_index": sibling_index,
                "guid": guid,
            },
            "fmt_id": fmt_id,
        },
        "message": f"{path} violates {fmt_id}",
    }


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


def test_guid_mismatch_at_same_location_still_accepts(tmp_path):
    """WAS: ``test_guid_mismatch_delete_shift_rearms_and_marks_stale``, which
    asserted that a differing guid at the same location re-armed — the guard
    against a deleted ``Cube[0]`` handing its acceptance to the sibling that
    shifted into its place.

    That guard could not work and did far more harm than good. C4D
    regenerates an object's guid every time the document is loaded (measured
    live 2026-07-31, and again end-to-end: accept, save, reopen, and the
    acceptance was gone). Since a stored guid NEVER matches after a reopen,
    this branch fired on every acceptance in every scene — accepting a
    violation lasted only until the artist closed the file.

    It also modelled the wrong thing. Accepting says "an object named this,
    HERE, is on purpose" — a statement about a place, with an author and a
    reason. If a different object occupies that place, the reason almost
    certainly still holds. Renaming still re-arms (see the test above), which
    is the case where the artist's statement genuinely stops applying."""
    path = tmp_path / "shot_baseline.json"
    original = object_violation("default_names", "/Root/Cube[0]", 0, "guid-old")
    shifted = object_violation("default_names", "/Root/Cube[0]", 0, "guid-new")
    baseline.add_acceptance(str(path), entry_from_violation(original))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [shifted])

    assert matched["accepted"] == [shifted]
    assert matched["new"] == []
    assert matched["stale_entries"] == []


def test_missing_current_guid_at_same_location_still_accepts(tmp_path):
    """Same correction as above for the case where the CURRENT violation
    carries no guid at all: the location is what identifies the acceptance,
    so a missing guid cannot invalidate it either."""
    path = tmp_path / "shot_baseline.json"
    original = object_violation("default_names", "/Root/Cube[0]", 0, "guid-old")
    no_guid = object_violation("default_names", "/Root/Cube[0]", 0, None)
    baseline.add_acceptance(str(path), entry_from_violation(original))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [no_guid])

    assert matched["accepted"] == [no_guid]
    assert matched["new"] == []
    assert matched["stale_entries"] == []


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
    accepted = cross_aspect_violation("/Root/Logo", 0, "guid-logo", fmt_id="9x16")
    later_frame = cross_aspect_violation("/Root/Logo", 0, "guid-logo", fmt_id="9x16")
    other_format = cross_aspect_violation("/Root/Logo", 0, "guid-logo", fmt_id="1x1")
    baseline.add_acceptance(str(path), entry_from_violation(accepted))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [later_frame, other_format])

    assert matched["accepted"] == [later_frame]
    assert matched["new"] == [other_format]


def test_cross_aspect_rename_rearms_and_marks_old_entry_stale(tmp_path):
    path = tmp_path / "shot_baseline.json"
    original = cross_aspect_violation("/Root/Logo", 0, "guid-logo", fmt_id="9x16")
    renamed = cross_aspect_violation("/Root/LogoRenamed", 0, "guid-logo", fmt_id="9x16")
    baseline.add_acceptance(str(path), entry_from_violation(original))

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [renamed])

    assert matched["new"] == [renamed]
    assert matched["accepted"] == []
    assert matched["stale_entries"] == [entry_from_violation(original)]


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


def test_conflict_copy_merge_can_repair_invalid_main_baseline(tmp_path):
    path = tmp_path / "shot_baseline.json"
    path.write_text("{not valid json", encoding="utf-8")
    copy_violation = object_violation("visibility", "/Root/Sphere", 0, "guid-b")
    conflict_copy = tmp_path / "shot_baseline SynologyDrive-conflict copy.json"
    write_payload(conflict_copy, [entry_from_violation(copy_violation)])

    merged_count, copy_paths = baseline.merge_conflict_copies(str(path))

    entries, status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [copy_violation])
    assert status == "ok"
    assert merged_count == 1
    assert copy_paths == [str(conflict_copy)]
    assert matched["accepted"] == [copy_violation]
    assert conflict_copy.exists()


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


def test_acceptance_survives_reopening_the_scene(tmp_path):
    """C4D REGENERATES an object's GUID on every save (measured live
    2026-07-31: two saved generations of the same file give different
    GetGUID() AND different FindUniqueID(MAXON_CREATOR_ID)). So an entry read
    back from a sidecar can never carry a guid that matches the object it
    describes, and treating that mismatch as "different object" re-armed
    EVERY acceptance the moment the artist reopened the scene.

    The location is all there is to match on, and it is what the artist means
    by "this violation, here". (An earlier attempt kept the guid's veto for
    the session that wrote the entry; an end-to-end run in C4D killed it —
    the guid dies when the DOCUMENT reloads, which happens constantly inside
    one session, so the veto still fired.)"""
    path = tmp_path / "shot_baseline.json"
    original = object_violation("default_names", "/Root/Cube[0]", 0, "guid-session-1")
    baseline.add_acceptance(str(path), entry_from_violation(original))

    # The artist saves and reopens the scene: C4D has handed the very same
    # object a brand new guid.
    reopened = object_violation("default_names", "/Root/Cube[0]", 0, "guid-session-2")

    entries, _status = baseline.load_baseline(str(path))
    matched = baseline.match_violations(entries, [reopened])

    assert matched["accepted"] == [reopened], "acceptance forgotten on reopen"
    assert matched["new"] == []
    assert matched["stale_entries"] == []


def test_reaccepting_after_reopen_does_not_duplicate_the_entry(tmp_path):
    """Second manifestation of the same root cause: the entry KEY carried the
    object guid, so the same acceptance sealed in two sessions produced two
    entries — a sidecar that grows every time the artist re-accepts, and (via
    the same key) an entry no caller could address, since the only key one can
    build carries today's guid. (``remove_acceptance`` has no production
    callers today, so the live symptom was the growth, not a broken retire.)

    Identity is the LOCATION, and the guid adds nothing to it: at any one
    instant only one object occupies a given path and sibling index."""
    path = tmp_path / "shot_baseline.json"
    first = object_violation("default_names", "/Root/Cube", 0, "guid-session-1")
    baseline.add_acceptance(str(path), entry_from_violation(first))

    again = object_violation("default_names", "/Root/Cube", 0, "guid-session-2")
    baseline.add_acceptance(str(path), entry_from_violation(again))

    entries, _status = baseline.load_baseline(str(path))
    assert len(entries) == 1, "the sidecar grew a duplicate on re-accept"

    # ...and the surviving entry is addressable with a key built from today's
    # violation, which is the only key any caller can produce.
    assert baseline.remove_acceptance(str(path), baseline._entry_key(again))
    assert baseline.load_baseline(str(path))[0] == []


def test_conflict_copy_never_overwrites_another_artists_acceptance(tmp_path):
    """Two artists accepting the SAME location is the whole point of this
    function, and since identity stopped carrying the object guid their two
    records share a key. Letting the copy win would destroy an audit record —
    author and reason are mandatory fields — and report `merged_count == 0`
    while doing it, so the loss would not even appear in the log."""
    path = tmp_path / "shot_baseline.json"
    violation = object_violation("default_names", "/Root/Cube", 0, "guid-a")
    write_payload(path, [entry_from_violation(violation, author="Ana",
                                              reason="legacy prop, keep")])
    copy_path = tmp_path / "shot_baseline (Javier's conflicted copy).json"
    write_payload(copy_path, [entry_from_violation(violation, author="Beto",
                                                   reason="")])

    merged_count, copies = baseline.merge_conflict_copies(str(path))

    entries, _status = baseline.load_baseline(str(path))
    assert len(entries) == 1
    assert entries[0]["author"] == "Ana", "the copy erased an audit record"
    assert entries[0]["reason"] == "legacy prop, keep"
    assert merged_count == 0 and copies == [str(copy_path)]


def test_same_object_accepted_in_two_formats_keeps_both(tmp_path):
    """`fmt_id` is part of the entry key: QC #12 accepts a subject per
    delivery format, so the same object at the same location legitimately
    carries one acceptance per format. Collapsing them would silently drop
    the first one the artist made."""
    path = tmp_path / "shot_baseline.json"
    vertical = cross_aspect_violation("/Root/Logo", 0, "guid-logo", fmt_id="9x16")
    square = cross_aspect_violation("/Root/Logo", 0, "guid-logo", fmt_id="1x1")
    baseline.add_acceptance(str(path), entry_from_violation(vertical))
    baseline.add_acceptance(str(path), entry_from_violation(square))

    entries, _status = baseline.load_baseline(str(path))
    assert len(entries) == 2, "one format's acceptance was overwritten"
    matched = baseline.match_violations(entries, [vertical, square])
    assert matched["accepted"] == [vertical, square]


def test_sibling_index_separates_acceptances_at_the_same_path(tmp_path):
    """Location means path AND sibling index. Accepting `Cube[0]` must not
    accept `Cube[1]`, which is a different violation the artist never saw."""
    path = tmp_path / "shot_baseline.json"
    first = object_violation("default_names", "/Root/Cube", 0, "guid-0")
    second = object_violation("default_names", "/Root/Cube", 1, "guid-1")
    baseline.add_acceptance(str(path), entry_from_violation(first))

    entries, _status = baseline.load_baseline(str(path))
    assert len(entries) == 1
    matched = baseline.match_violations(entries, [first, second])

    assert matched["accepted"] == [first]
    assert matched["new"] == [second], "an unaccepted sibling was masked"

    # ...and the index has to be part of the STORED key too, or accepting the
    # sibling afterwards would overwrite the first acceptance instead of
    # standing beside it.
    baseline.add_acceptance(str(path), entry_from_violation(second))
    entries, _status = baseline.load_baseline(str(path))
    assert len(entries) == 2, "the sibling's acceptance replaced the first"
    assert baseline.match_violations(entries, [first, second])["accepted"] == [
        first, second]
