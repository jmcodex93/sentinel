# -*- coding: utf-8 -*-
"""QC registry runner and score semantics."""

from collections import OrderedDict

from sentinel.qc.registry import CHECK_REGISTRY, resolve_function


def _call(fn, doc, kwargs):
    if kwargs:
        return fn(doc, **kwargs)
    return fn(doc)


def _legacy_from_structured(structured_result):
    to_legacy = getattr(structured_result, "to_legacy", None)
    if callable(to_legacy):
        return to_legacy()
    return structured_result


def run_all_checks(doc, module):
    """Run registry checks in order and return legacy + structured results."""
    results = OrderedDict()
    for entry in CHECK_REGISTRY:
        structured_fn = resolve_function(entry.structured_fn, module)
        structured_result = _call(structured_fn, doc, entry.structured_kwargs)

        if entry.legacy_from_structured:
            legacy_result = _legacy_from_structured(structured_result)
        else:
            legacy_fn = resolve_function(entry.legacy_fn, module)
            legacy_result = _call(legacy_fn, doc, entry.legacy_kwargs)

        results[entry.check_id] = {
            "legacy_result": legacy_result,
            "structured_result": structured_result,
        }
    return results


def count_violations(check_id, legacy_result):
    """Return the current legacy violation count for a check."""
    if check_id == "rdc":
        return int(legacy_result or 0)
    return len(legacy_result or [])


def compute_score(results):
    """Reproduce the legacy pass/fail score semantics exactly."""
    counts = OrderedDict()
    for entry in CHECK_REGISTRY:
        result_pair = results.get(entry.check_id, {}) if results else {}
        legacy_result = result_pair.get("legacy_result")
        counts[entry.check_id] = count_violations(entry.check_id, legacy_result)

    total = len(counts)
    passed = sum(1 for value in counts.values() if value == 0)
    return {
        "score": f"{passed}/{total}",
        "pass": passed == total,
        "passed": passed,
        "total": total,
        "counts": counts,
    }
