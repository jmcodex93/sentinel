# -*- coding: utf-8 -*-
"""Quality-control result models."""

from .results import (
    CheckResult,
    Violation,
    cached_result,
    legacy_items,
    object_identity,
    param_identity,
    store_result,
    structured_cache_key,
)
from .registry import CHECK_REGISTRY, CheckEntry, validate_registry
from .score import compute_score, run_all_checks

__all__ = [
    "CHECK_REGISTRY",
    "CheckResult",
    "CheckEntry",
    "Violation",
    "cached_result",
    "compute_score",
    "legacy_items",
    "object_identity",
    "param_identity",
    "run_all_checks",
    "store_result",
    "structured_cache_key",
    "validate_registry",
]
