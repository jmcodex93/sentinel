# -*- coding: utf-8 -*-
"""Pure Python quality gate helpers."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from sentinel import baseline
from sentinel.qc.registry import CHECK_REGISTRY, entry_severity

LEVEL_FIXABLE = "CORREGIBLE"
LEVEL_BLOCKING = "BLOQUEANTE"
LEVEL_ADVISORY = "AVISO"


def classify_gate(entry: Any, rules_context: Any = None) -> tuple[str, bool]:
    """Return the gate level and whether the check blocks delivery."""
    severity = entry_severity(entry, rules_context)
    blocks = severity == "FAIL"
    if entry.has_fix:
        return LEVEL_FIXABLE, blocks
    if blocks:
        return LEVEL_BLOCKING, True
    return LEVEL_ADVISORY, False


def identity_key(identity: Any) -> str:
    """Return a stable hashable key for a structured violation identity."""
    try:
        return json.dumps(identity, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return json.dumps(_json_safe(identity), sort_keys=True, separators=(",", ":"))


def evaluate_gate(score_summary: dict[str, Any], rules_context: Any = None) -> dict[str, Any]:
    """Bucket checks with new violations into blocking, fixable, and advisory groups."""
    result = {
        "blocking": [],
        "fixable": [],
        "advisory": [],
        "passed": True,
    }
    new_counts = score_summary.get("new_counts") or {}
    baseline_matches = score_summary.get("baseline_matches") or {}

    for check_id in new_counts:
        new_count = new_counts.get(check_id, 0)
        if new_count <= 0:
            continue

        entry = _registry_entry(check_id)
        if entry is None:
            continue

        level, blocks = classify_gate(entry, rules_context)
        violations = list((baseline_matches.get(check_id) or {}).get("new") or [])
        item = {
            "check_id": check_id,
            "nivel": level,
            "blocks": blocks,
            "new_count": new_count,
            "violations": violations,
        }
        if level == LEVEL_FIXABLE:
            result["fixable"].append(item)
        elif level == LEVEL_BLOCKING:
            result["blocking"].append(item)
        else:
            result["advisory"].append(item)

    result["passed"] = not (result["blocking"] or result["fixable"] or result["advisory"])
    return result


def build_override_records(
    new_violations: Iterable[dict[str, Any]],
    author: str,
    reason: str,
) -> list[dict[str, Any]]:
    """Build per-delivery override records without writing the baseline sidecar."""
    records = []
    for violation in new_violations or []:
        record = baseline.entry_from_violation(violation, author, reason)
        if record is not None:
            records.append(record)
    return records


def filter_to_new(
    live_objects: Iterable[Any],
    new_keys: set[Any],
    identity_fn: Callable[[Any], Any],
    key_fn: Callable[[Any], Any],
) -> list[Any]:
    """Keep live objects whose computed identity key is present in ``new_keys``."""
    return [
        obj
        for obj in live_objects or []
        if key_fn(identity_fn(obj)) in new_keys
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def build_preflight_issues(score: dict[str, Any]) -> list[str]:
    """Ordered human-readable preflight issue strings from a QC score.

    One line per check with new violations (``score["counts"]``), honoring
    each registry entry's ``preflight_order`` (falling back to declaration
    order when unset) and formatting via ``preflight_template``. This is
    the exact loop the native Asset Hub dialog's
    ``AssetHubDialog._build_collect_preflight_payload`` used to duplicate
    inline (and the retired ``collect_scene`` before it) — extracted here
    so the Hub SPA's ``hub/collect_start`` op shares one implementation
    instead of re-deriving it.
    """
    counts = score.get("counts") or {}
    preflight_entries = sorted(
        enumerate(CHECK_REGISTRY),
        key=lambda item: (
            item[1].preflight_order
            if item[1].preflight_order is not None
            else item[0]
        ),
    )
    issues = []
    for _idx, entry in preflight_entries:
        count = counts.get(entry.check_id, 0)
        if count:
            issues.append(entry.preflight_template.format(n=count))
    return issues


def count_new_fails(score: dict[str, Any], rules_context: Any = None) -> int:
    """Total new-violation count across FAIL-severity checks.

    Uses the same ``entry_severity(entry, rules_context)`` accessor as
    ``classify_gate``/``evaluate_gate`` above, and the same
    ``score["counts"]`` accessor ``build_preflight_issues`` (and the
    native dialog's own preflight loop) use — so this always agrees with
    what the preflight issue list and the modal gate would report as
    FAIL-severity violations.
    """
    counts = score.get("counts") or {}
    total = 0
    for entry in CHECK_REGISTRY:
        if entry_severity(entry, rules_context) != "FAIL":
            continue
        total += counts.get(entry.check_id, 0)
    return total


def _registry_entry(check_id: str) -> Any:
    for entry in CHECK_REGISTRY:
        if entry.check_id == check_id:
            return entry
    return None
