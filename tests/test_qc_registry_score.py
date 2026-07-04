from collections import OrderedDict
from types import SimpleNamespace

import pytest


def _entry(CheckEntry, check_id):
    return CheckEntry(
        check_id=check_id,
        row_label="Fake",
        label_ok="Fake OK",
        label_fail_template="{n} fake issue(s)",
        names_key=None,
        severity="WARN",
        has_fix=False,
        structured_fn="scene.check_lights",
        legacy_fn="scene.check_lights",
        preflight_template="  {n} fake issues",
    )


def _empty_results(entries):
    return OrderedDict(
        (
            entry.check_id,
            {"legacy_result": 0 if entry.check_id == "rdc" else []},
        )
        for entry in entries
    )


def test_registry_extensibility_updates_legacy_views_and_score(sentinel_module):
    from sentinel.qc.registry import CHECK_REGISTRY, CheckEntry
    from sentinel.qc.score import compute_score

    fake = _entry(CheckEntry, "fake_registry_check")
    CHECK_REGISTRY.append(fake)
    try:
        assert sentinel_module._CHECK_DISPLAY["fake_registry_check"] == (
            "WARN",
            "Fake OK",
            "{n} fake issue(s)",
            None,
        )
        assert list(sentinel_module.StatusArea.ROW_KEYS)[-1] == "fake_registry_check"

        summary = compute_score(_empty_results(CHECK_REGISTRY))
        assert summary["total"] == 13
        assert summary["score"] == "13/13"
    finally:
        CHECK_REGISTRY.remove(fake)

    assert "fake_registry_check" not in list(sentinel_module.StatusArea.ROW_KEYS)
    assert sentinel_module._CHECK_DISPLAY.get("fake_registry_check") is None


def test_duplicate_check_id_validation_raises(sentinel_module):
    from sentinel.qc.registry import CheckEntry, validate_registry

    duplicate_a = _entry(CheckEntry, "duplicate")
    duplicate_b = _entry(CheckEntry, "duplicate")

    with pytest.raises(ValueError, match="Duplicate QC check_id: duplicate"):
        validate_registry([duplicate_a, duplicate_b])


def test_compute_score_matches_legacy_emptiness_semantics(sentinel_module):
    from sentinel.qc.registry import CHECK_REGISTRY
    from sentinel.qc.score import compute_score

    empty = OrderedDict()
    for index, entry in enumerate(CHECK_REGISTRY):
        if entry.check_id == "rdc":
            legacy_result = 0
        else:
            legacy_result = {} if index % 2 else []
        empty[entry.check_id] = {"legacy_result": legacy_result}

    empty_summary = compute_score(empty)
    assert empty_summary["passed"] == len(CHECK_REGISTRY)
    assert empty_summary["total"] == len(CHECK_REGISTRY)
    assert all(count == 0 for count in empty_summary["counts"].values())

    mixed = _empty_results(CHECK_REGISTRY)
    mixed["rdc"] = {"legacy_result": 2}
    mixed["vis"] = {"legacy_result": ["visibility_object"]}
    mixed["output"] = {"legacy_result": {"preset": "missing token"}}

    mixed_summary = compute_score(mixed)
    assert mixed_summary["counts"]["rdc"] == 2
    assert mixed_summary["counts"]["vis"] == 1
    assert mixed_summary["counts"]["output"] == 1
    assert mixed_summary["passed"] == len(CHECK_REGISTRY) - 3
    assert mixed_summary["score"] == f"{len(CHECK_REGISTRY) - 3}/{len(CHECK_REGISTRY)}"


def test_severity_override_changes_display_view_not_score(sentinel_module):
    from sentinel.qc.registry import CHECK_REGISTRY, build_check_display
    from sentinel.qc.score import compute_score

    results = _empty_results(CHECK_REGISTRY)
    results["names"] = {"legacy_result": ["Cube"]}
    default_summary = compute_score(results)

    context = SimpleNamespace(params={"check_severity": {"names": "FAIL"}})
    overridden_display = build_check_display(rules_context=context)
    overridden_summary = compute_score(results, context)

    assert overridden_display["names"][0] == "FAIL"
    assert sentinel_module._CHECK_DISPLAY["names"][0] == "WARN"
    assert overridden_summary["score"] == default_summary["score"]
    assert overridden_summary["counts"] == default_summary["counts"]


def test_disabled_check_is_removed_from_score_denominator(sentinel_module):
    from sentinel.qc.registry import CHECK_REGISTRY
    from sentinel.qc.score import compute_score

    results = _empty_results(CHECK_REGISTRY)
    results["names"] = {"legacy_result": ["Cube"]}
    context = SimpleNamespace(params={"checks_enabled": {"names": False}})

    summary = compute_score(results, context)

    assert "names" not in summary["counts"]
    assert summary["disabled"] == ["names"]
    assert summary["disabled_count"] == 1
    assert summary["total"] == len(CHECK_REGISTRY) - 1
    assert summary["passed"] == len(CHECK_REGISTRY) - 1
    assert summary["score"] == f"{len(CHECK_REGISTRY) - 1}/{len(CHECK_REGISTRY) - 1}"


def _object_violation(check_id, index):
    return {
        "check_id": check_id,
        "identity": {
            "type": "object",
            "path": f"/Root/Cube[{index}]",
            "sibling_index": index,
            "guid": f"guid-{index}",
        },
        "message": f"Cube[{index}] uses a default name",
    }


def test_compute_score_with_baseline_counts_only_new_violations(sentinel_module):
    from sentinel import baseline
    from sentinel.qc.registry import CHECK_REGISTRY
    from sentinel.qc.score import compute_score

    violations = [_object_violation("names", index) for index in range(5)]
    entries = [
        baseline.entry_from_violation(violation, "Javier", "legacy shot")
        for violation in violations
    ]
    results = _empty_results(CHECK_REGISTRY)
    results["names"] = {
        "legacy_result": ["Cube"] * 5,
        "structured_result": {"violations": violations},
    }

    summary = compute_score(results, baseline_entries=entries, current_params={})

    assert summary["counts"]["names"] == 0
    assert summary["accepted_counts"]["names"] == 5
    assert summary["new"] == 0
    assert summary["accepted"] == 5
    assert summary["passed"] == len(CHECK_REGISTRY)
    assert summary["score"] == f"{len(CHECK_REGISTRY)}/{len(CHECK_REGISTRY)}"


def test_mixed_baseline_score_and_row_rendering_semantics(sentinel_module):
    from sentinel import baseline
    from sentinel.qc.registry import CHECK_REGISTRY
    from sentinel.qc.score import compute_score

    violations = [_object_violation("names", index) for index in range(3)]
    entries = [
        baseline.entry_from_violation(violation, "Javier", "known client scene")
        for violation in violations[:2]
    ]
    results = _empty_results(CHECK_REGISTRY)
    results["names"] = {
        "legacy_result": ["Cube"] * 3,
        "structured_result": {"violations": violations},
    }

    summary = compute_score(results, baseline_entries=entries, current_params={})

    assert summary["counts"]["names"] == 1
    assert summary["accepted_counts"]["names"] == 2
    assert sentinel_module.format_baseline_row_message(1, 2) == "1 nuevas (2 aceptadas)"


def test_invalid_baseline_sidecar_uses_legacy_score_with_visible_status(sentinel_module, tmp_path):
    from sentinel.qc.registry import CHECK_REGISTRY
    from sentinel.qc.score import compute_score

    baseline_path = tmp_path / "shot_baseline.json"
    baseline_path.write_text("{not valid json", encoding="utf-8")
    results = _empty_results(CHECK_REGISTRY)
    results["names"] = {"legacy_result": ["Cube"]}

    summary = compute_score(results, baseline_path=str(baseline_path), current_params={})

    assert summary["counts"]["names"] == 1
    assert summary["baseline_status"] == "invalid"
    assert summary["baseline_path"] == str(baseline_path)
    assert "baseline ilegible" in summary["baseline_warning"]
