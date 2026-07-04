def test_baseline_artifact_details_include_accepted_reasons(sentinel_module):
    accepted_violation = {
        "check_id": "names",
        "identity": {
            "type": "object",
            "path": "/Root/Cube",
            "sibling_index": 0,
            "guid": "guid-cube",
        },
        "message": "Cube uses a default name",
    }
    accepted_entry = {
        "check_id": "names",
        "identity": {
            "kind": "object",
            "path": "/Root/Cube",
            "sibling_index": 0,
            "guid": "guid-cube",
        },
        "author": "Javier",
        "reason": "legacy client-approved scene",
        "date": "2026-07-04 12:00:00",
    }
    stale_entry = {
        "check_id": "names",
        "identity": {
            "kind": "object",
            "path": "/Root/OldCube",
            "sibling_index": 0,
            "guid": "guid-old",
        },
        "author": "Ana",
        "reason": "old acceptance",
        "date": "2026-07-03 09:00:00",
    }
    qc_summary = {
        "schema": 2,
        "baseline_matches": {
            "names": {
                "new": [],
                "accepted": [accepted_violation],
                "accepted_entries": [accepted_entry],
                "stale_entries": [stale_entry],
            }
        },
    }

    details = sentinel_module.build_baseline_artifact_details(qc_summary)

    assert details["names"]["accepted_count"] == 1
    assert details["names"]["accepted"] == [
        {
            "item": "Cube uses a default name",
            "author": "Javier",
            "reason": "legacy client-approved scene",
            "date": "2026-07-04 12:00:00",
        }
    ]
    assert details["names"]["stale"] == [
        {
            "item": "/Root/OldCube",
            "author": "Ana",
            "reason": "old acceptance",
            "date": "2026-07-03 09:00:00",
        }
    ]
