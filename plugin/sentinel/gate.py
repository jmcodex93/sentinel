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


def _registry_entry(check_id: str) -> Any:
    for entry in CHECK_REGISTRY:
        if entry.check_id == check_id:
            return entry
    return None
