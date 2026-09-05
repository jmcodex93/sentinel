# -*- coding: utf-8 -*-
"""QC registry runner and score semantics."""

import copy
import inspect
import os
from collections import OrderedDict

from sentinel import baseline
from sentinel.common.helpers import safe_print
from sentinel.qc.registry import CHECK_REGISTRY, is_check_enabled, resolve_function


_BASELINE_LOAD_CACHE = {}


def _call(fn, doc, kwargs, rules_context=None):
    if rules_context is not None:
        # Decide by signature, not by catching TypeError and grepping its
        # text: an internal bug raising TypeError mentioning the parameter
        # name would have been silently retried without rules_context,
        # masking the real error.
        try:
            accepts_rc = "rules_context" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            accepts_rc = False
        if accepts_rc:
            return fn(doc, rules_context=rules_context, **kwargs)
    if kwargs:
        return fn(doc, **kwargs)
    return fn(doc)


def _legacy_from_structured(structured_result):
    to_legacy = getattr(structured_result, "to_legacy", None)
    if callable(to_legacy):
        return to_legacy()
    return structured_result


def run_all_checks(doc, module, rules_context=None):
    """Run registry checks in order and return legacy + structured results."""
    results = OrderedDict()
    for entry in CHECK_REGISTRY:
        if not is_check_enabled(entry, rules_context):
            results[entry.check_id] = {
                "legacy_result": 0 if entry.check_id == "rdc" else [],
                "structured_result": None,
                "disabled": True,
            }
            continue
        structured_fn = resolve_function(entry.structured_fn, module)
        structured_result = _call(structured_fn, doc, entry.structured_kwargs, rules_context)

        if entry.legacy_from_structured:
            legacy_result = _legacy_from_structured(structured_result)
        else:
            legacy_fn = resolve_function(entry.legacy_fn, module)
            legacy_result = _call(legacy_fn, doc, entry.legacy_kwargs, rules_context)

        results[entry.check_id] = {
            "legacy_result": legacy_result,
            "structured_result": structured_result,
            "disabled": False,
        }
    return results


def count_violations(check_id, legacy_result):
    """Return the current legacy violation count for a check."""
    if check_id == "rdc":
        return int(legacy_result or 0)
    return len(legacy_result or [])


def _legacy_score(results, rules_context=None):
    counts = OrderedDict()
    disabled = []
    for entry in CHECK_REGISTRY:
        result_pair = results.get(entry.check_id, {}) if results else {}
        if result_pair.get("disabled") or not is_check_enabled(entry, rules_context):
            disabled.append(entry.check_id)
            continue
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
        "disabled": disabled,
        "disabled_count": len(disabled),
    }


def _structured_violations_for(entry, result_pair):
    structured = result_pair.get("structured_result") if result_pair else None
    if not structured:
        return []
    raw = []
    if isinstance(structured, dict):
        raw = structured.get("violations") or []
    else:
        raw = getattr(structured, "violations", []) or []

    normalized = []
    for violation in raw:
        if isinstance(violation, dict):
            item = dict(violation)
            item["check_id"] = entry.check_id
            normalized.append(item)
    return normalized


def _load_baseline_entries(baseline_path, baseline_entries):
    if baseline_entries is not None:
        return list(baseline_entries), baseline.STATUS_OK
    if not baseline_path:
        return [], baseline.STATUS_MISSING

    entries, status = _cached_load_baseline(baseline_path)
    if status == baseline.STATUS_INVALID:
        conflict_paths = baseline.find_conflict_copies(baseline_path)
        if conflict_paths:
            merged_count, _copy_paths = baseline.merge_conflict_copies(baseline_path)
            _BASELINE_LOAD_CACHE.pop(baseline_path, None)
            entries, status = _cached_load_baseline(baseline_path)
            if status == baseline.STATUS_OK:
                safe_print(
                    f"Recovered baseline sidecar from {len(conflict_paths)} conflict copy/copies "
                    f"({merged_count} entries merged): {baseline_path}"
                )
        if status == baseline.STATUS_INVALID:
            safe_print(
                "Baseline sidecar is invalid; using legacy QC totals only "
                f"until it is repaired: {baseline_path}"
            )
    return entries, status


def _cached_load_baseline(baseline_path):
    try:
        mtime = os.path.getmtime(baseline_path)
    except OSError:
        mtime = None
    cache_key = (baseline_path, mtime)
    cached = _BASELINE_LOAD_CACHE.get(baseline_path)
    if cached and cached.get("key") == cache_key:
        return copy.deepcopy(cached["entries"]), cached["status"]
    entries, status = baseline.load_baseline(baseline_path)
    _BASELINE_LOAD_CACHE[baseline_path] = {
        "key": cache_key,
        "entries": copy.deepcopy(entries),
        "status": status,
    }
    return entries, status


def _baseline_score(results, rules_context, baseline_path, current_params, baseline_entries):
    entries, status = _load_baseline_entries(baseline_path, baseline_entries)
    if status != baseline.STATUS_OK:
        if status == baseline.STATUS_INVALID:
            summary = _legacy_score(results, rules_context)
            summary.update(
                {
                    "baseline_status": status,
                    "baseline_path": baseline_path,
                    "baseline_warning": "baseline unreadable - showing totals only",
                }
            )
            return summary
        return None

    current_params = current_params or getattr(rules_context, "params", {}) or {}
    counts = OrderedDict()
    accepted_counts = OrderedDict()
    stale_counts = OrderedDict()
    disabled = []
    baseline_matches = OrderedDict()

    for entry in CHECK_REGISTRY:
        result_pair = results.get(entry.check_id, {}) if results else {}
        if result_pair.get("disabled") or not is_check_enabled(entry, rules_context):
            disabled.append(entry.check_id)
            continue

        violations = _structured_violations_for(entry, result_pair)
        matched = baseline.match_violations(entries, violations, current_params)
        baseline_matches[entry.check_id] = matched
        counts[entry.check_id] = len(matched.get("new") or [])
        accepted_counts[entry.check_id] = len(matched.get("accepted") or [])
        stale_counts[entry.check_id] = len(matched.get("stale_entries") or [])

    total = len(counts)
    passed = sum(1 for value in counts.values() if value == 0)
    return {
        "score": f"{passed}/{total}",
        "pass": passed == total,
        "passed": passed,
        "total": total,
        "counts": counts,
        "new_counts": counts,
        "accepted_counts": accepted_counts,
        "stale_counts": stale_counts,
        "baseline_matches": baseline_matches,
        "baseline_status": status,
        "baseline_path": baseline_path,
        "disabled": disabled,
        "disabled_count": len(disabled),
        "schema": 2,
        "new": sum(counts.values()),
        "accepted": sum(accepted_counts.values()),
        "stale": sum(stale_counts.values()),
    }


def compute_score(
    results,
    rules_context=None,
    baseline_path=None,
    current_params=None,
    baseline_entries=None,
):
    """Return QC score, using accepted baselines only when explicitly present."""
    if baseline_path or baseline_entries is not None:
        summary = _baseline_score(
            results,
            rules_context,
            baseline_path,
            current_params,
            baseline_entries,
        )
        if summary is not None:
            return _with_coverage(summary, results)

    return _with_coverage(_legacy_score(results, rules_context), results)


def _with_coverage(summary, results):
    """Missing coverage remains in the denominator, outside baseline data.

    Counts still mean observed violations. A failed read cannot manufacture
    a violation identity or be hidden by accepting existing mismatches.
    """
    unverified = {}
    for check_id in summary["counts"]:
        structured = ((results or {}).get(check_id) or {}).get("structured_result") or {}
        rows = (structured.get("metadata") or {}).get("unverified") or []
        if rows:
            unverified[check_id] = list(rows)
    if unverified:
        summary["unverified"] = unverified
        summary["unverified_counts"] = {key: len(rows) for key, rows in unverified.items()}
        passed = sum(1 for key, count in summary["counts"].items()
                     if count == 0 and key not in unverified)
        summary.update(passed=passed, score=f"{passed}/{summary['total']}")
        summary["pass"] = passed == summary["total"]
    return summary
