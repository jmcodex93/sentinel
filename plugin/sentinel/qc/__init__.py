# -*- coding: utf-8 -*-
"""Quality-control public API.

Keep this package initializer c4d-free so pure modules such as
``sentinel.qc.registry`` can be imported by rules validation tests and tools.
"""

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


_REGISTRY_EXPORTS = {"CHECK_REGISTRY", "CheckEntry", "validate_registry"}
_RESULT_EXPORTS = {
    "CheckResult",
    "Violation",
    "cached_result",
    "legacy_items",
    "object_identity",
    "param_identity",
    "store_result",
    "structured_cache_key",
}
_SCORE_EXPORTS = {"compute_score", "run_all_checks"}


def __getattr__(name):
    if name in _REGISTRY_EXPORTS:
        from . import registry

        return getattr(registry, name)
    if name in _RESULT_EXPORTS:
        from . import results

        return getattr(results, name)
    if name in _SCORE_EXPORTS:
        from . import score

        return getattr(score, name)
    raise AttributeError(name)
