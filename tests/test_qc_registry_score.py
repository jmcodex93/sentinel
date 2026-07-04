from collections import OrderedDict

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
