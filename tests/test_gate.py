import importlib.util
import json
import sys
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "plugin" / "sentinel" / "gate.py"

spec = importlib.util.spec_from_file_location("sentinel_gate_under_test", GATE_PATH)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


def registry_entry(check_id):
    from sentinel.qc.registry import CHECK_REGISTRY

    for entry in CHECK_REGISTRY:
        if entry.check_id == check_id:
            return entry
    raise AssertionError(f"Unknown check id: {check_id}")


def violation(check_id, name="Cube", index=0):
    return {
        "check_id": check_id,
        "identity": {
            "type": "object",
            "path": f"/Root/{name}[{index}]",
            "sibling_index": index,
            "guid": f"guid-{index}",
        },
        "message": name,
    }


def test_classify_gate_uses_fixability_then_severity():
    assert gate.classify_gate(registry_entry("lights")) == ("CORREGIBLE", True)
    assert gate.classify_gate(registry_entry("textures")) == ("BLOQUEANTE", True)
    assert gate.classify_gate(registry_entry("unused_mats")) == ("CORREGIBLE", False)
    assert gate.classify_gate(registry_entry("names")) == ("AVISO", False)


def test_classify_gate_respects_check_severity_override():
    context = SimpleNamespace(params={"check_severity": {"names": "FAIL"}})

    assert gate.classify_gate(registry_entry("names"), context) == ("BLOQUEANTE", True)


def test_evaluate_gate_groups_mixed_buckets():
    score_summary = {
        "new_counts": OrderedDict(
            [
                ("textures", 2),
                ("lights", 1),
                ("unused_mats", 1),
                ("names", 3),
            ]
        ),
        "baseline_matches": {
            "textures": {"new": [violation("textures", "missing", 0), violation("textures", "absolute", 1)]},
            "lights": {"new": [violation("lights", "Light", 0)]},
            "unused_mats": {"new": [violation("unused_mats", "Mat", 0)]},
            "names": {
                "new": [
                    violation("names", "Cube", 0),
                    violation("names", "Null", 1),
                    violation("names", "Sphere", 2),
                ]
            },
        },
    }

    result = gate.evaluate_gate(score_summary)

    assert result["passed"] is False
    assert [(item["check_id"], item["nivel"], item["blocks"], item["new_count"]) for item in result["blocking"]] == [
        ("textures", "BLOQUEANTE", True, 2)
    ]
    assert [(item["check_id"], item["nivel"], item["blocks"], item["new_count"]) for item in result["fixable"]] == [
        ("lights", "CORREGIBLE", True, 1),
        ("unused_mats", "CORREGIBLE", False, 1),
    ]
    assert [(item["check_id"], item["nivel"], item["blocks"], item["new_count"]) for item in result["advisory"]] == [
        ("names", "AVISO", False, 3)
    ]
    assert result["blocking"][0]["violations"] == score_summary["baseline_matches"]["textures"]["new"]


def test_evaluate_gate_ignores_checks_absent_from_new_counts():
    score_summary = {
        "new_counts": OrderedDict([("lights", 1)]),
        "baseline_matches": {
            "lights": {"new": [violation("lights", "Light")]},
            "names": {"new": [violation("names", "Cube")]},
        },
    }

    result = gate.evaluate_gate(score_summary)

    assert [item["check_id"] for item in result["fixable"]] == ["lights"]
    assert result["blocking"] == []
    assert result["advisory"] == []


def test_evaluate_gate_passes_with_zero_new_violations():
    score_summary = {
        "new_counts": OrderedDict([("lights", 0), ("textures", 0), ("names", 0)]),
        "baseline_matches": {},
    }

    result = gate.evaluate_gate(score_summary)

    assert result == {"blocking": [], "fixable": [], "advisory": [], "passed": True}


def test_identity_key_is_stable_hashable_and_usable_in_set():
    first = {"type": "object", "path": "/Root/Cube", "sibling_index": 0, "guid": "abc"}
    second = {"guid": "abc", "sibling_index": 0, "path": "/Root/Cube", "type": "object"}

    key = gate.identity_key(first)

    assert key == gate.identity_key(second)
    assert isinstance(key, str)
    assert key in {gate.identity_key(second)}
    assert json.loads(key)["path"] == "/Root/Cube"


def test_filter_to_new_keeps_only_objects_matching_new_identity_keys():
    live_objects = ["keep", "drop"]

    def identity_for(obj):
        return {
            "type": "object",
            "path": f"/Root/{obj}",
            "sibling_index": 0,
            "guid": obj,
        }

    new_keys = {gate.identity_key(identity_for("keep"))}

    assert gate.filter_to_new(live_objects, new_keys, identity_for, gate.identity_key) == ["keep"]


def test_build_override_records_matches_baseline_shape_without_writing(tmp_path):
    records = gate.build_override_records(
        [violation("textures", "MissingTexture")],
        author="Javier",
        reason="client-provided placeholder",
    )

    assert len(records) == 1
    record = records[0]
    assert record["check_id"] == "textures"
    assert record["identity"] == {
        "path": "/Root/MissingTexture[0]",
        "sibling_index": 0,
        "guid": "guid-0",
        "kind": "object",
    }
    assert record["author"] == "Javier"
    assert record["reason"] == "client-provided placeholder"
    assert record["date"]
    assert not list(tmp_path.glob("*_baseline.json"))


def test_gate_dialog_can_proceed_requires_reason_for_blocking_override(sentinel_module):
    from sentinel.ui.dialogs import gate_dialog_can_proceed

    blocking = [{"check_id": "textures", "blocks": True}]

    assert gate_dialog_can_proceed(blocking, [], {"textures": "override"}, "") is False
    assert gate_dialog_can_proceed(blocking, [], {"textures": "override"}, "approved for review") is True
    assert gate_dialog_can_proceed(blocking, [], {"textures": "baseline"}, "") is True


def test_gate_dialog_can_proceed_handles_fixable_fail_decisions(sentinel_module):
    from sentinel.ui.dialogs import gate_dialog_can_proceed

    fixable = [{"check_id": "lights", "blocks": True}]

    assert gate_dialog_can_proceed([], fixable, {}, "") is False
    assert gate_dialog_can_proceed([], fixable, {"lights": "fix"}, "") is True
    assert gate_dialog_can_proceed([], fixable, {"lights": "override"}, "") is False
    assert gate_dialog_can_proceed([], fixable, {"lights": "override"}, "one-off delivery") is True
    assert gate_dialog_can_proceed([], fixable, {"lights": "baseline"}, "") is True


def test_gate_dialog_can_proceed_allows_warn_fixable_without_decision(sentinel_module):
    from sentinel.ui.dialogs import gate_dialog_can_proceed

    warn_fixable = [{"check_id": "unused_mats", "blocks": False}]

    assert gate_dialog_can_proceed([], warn_fixable, {}, "") is True
