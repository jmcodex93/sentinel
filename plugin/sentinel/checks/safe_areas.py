# -*- coding: utf-8 -*-
"""Cross-aspect safe-area QC wrappers."""

from sentinel.qc.results import CheckResult, object_identity
from sentinel.safe_areas import _scan_cross_aspect_safe_area

def _cross_aspect_safe_area_result(violations):
    result = CheckResult(
        "cross_aspect_safe_area",
        metadata={"legacy_count": len(violations)},
        legacy_items=violations,
    )
    for item in violations:
        obj = item.get("object")
        fmt_id = item.get("fmt_id")
        result.add_violation(
            {
                "type": "cross_aspect_safe_area",
                "object": object_identity(obj),
                "fmt_id": fmt_id,
            },
            f"Safe-area subject violates {fmt_id} format",
            {
                "object_name": item.get("object_name"),
                "fmt_id": fmt_id,
                "sides": item.get("sides"),
                "frames": item.get("frames"),
            },
        )
    return result


def check_cross_aspect_safe_area_structured(doc, sample_strategy="keyframes", rules_context=None):
    """QC #12 structured wrapper.

    Frames are deliberately stored only in violation extras, never in the
    identity. The legacy check did not use check_cache, and this helper keeps
    the same no-cache runtime behavior for sample_strategy-sensitive results.
    """
    return _cross_aspect_safe_area_result(
        _scan_cross_aspect_safe_area(
            doc, sample_strategy=sample_strategy, rules_context=rules_context)
    )


def check_cross_aspect_safe_area(doc, sample_strategy="keyframes", rules_context=None):
    return check_cross_aspect_safe_area_structured(
        doc, sample_strategy=sample_strategy, rules_context=rules_context
    ).to_legacy()

