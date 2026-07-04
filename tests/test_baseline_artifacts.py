import json


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


class _ReportDoc:
    def GetDocumentName(self):
        return "shot.c4d"

    def GetDocumentPath(self):
        return ""

    def GetTakeData(self):
        return None


def test_qc_report_marks_disabled_checks_and_uses_summary_denominator(sentinel_module, tmp_path):
    save_path = tmp_path / "qc_report.json"
    sentinel_module.c4d.storage.SaveDialog = lambda *args, **kwargs: str(save_path)
    results = {
        "names_bad": ["Cube"],
        "scene_stats": {"polygons": 10, "materials": 1, "lights": 0},
    }
    qc_summary = {
        "score": "11/11",
        "pass": True,
        "passed": 11,
        "total": 11,
        "counts": {},
        "disabled": ["names"],
        "disabled_count": 1,
    }

    written = sentinel_module.export_qc_report(_ReportDoc(), results, "Javier", qc_summary)

    payload = json.loads(save_path.read_text(encoding="utf-8"))
    assert written == str(save_path)
    assert payload["disabled_checks"] == ["names"]
    assert payload["checks"]["default_names"]["status"] == "DISABLED"
    assert payload["checks"]["default_names"]["count"] == 0
    assert payload["summary"]["score"] == "11/11"
    assert payload["summary"]["total_checks"] == 11
    assert payload["summary"]["disabled_count"] == 1
