# -*- coding: utf-8 -*-
"""Pure project rules discovery, validation, and resolution."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

RULES_FILENAME = "sentinel_rules.json"
SEVERITIES = {"FAIL", "WARN"}
MAP_MERGE_KEYS = {"safe_area_insets", "check_severity", "checks_enabled"}

# Mirrored from sentinel.common.constants.PRESETS. Duplicated here so this
# module remains importable without importing c4d-dependent package modules.
APPROVED_PRESETS_DEFAULT = ["previz", "pre_render", "render", "stills"]

# Mirrored from sentinel.qc.registry.CHECK_REGISTRY for the same import-purity
# reason. U7 can replace this duplication once the package bootstrap is pure.
CHECK_DEFAULT_SEVERITY = {
    "lights": "FAIL",
    "vis": "WARN",
    "keys": "WARN",
    "cam": "FAIL",
    "rdc": "FAIL",
    "textures": "FAIL",
    "unused_mats": "WARN",
    "names": "WARN",
    "output": "FAIL",
    "takes": "FAIL",
    "fps_range": "FAIL",
    "cross_aspect": "WARN",
}
CHECK_IDS = set(CHECK_DEFAULT_SEVERITY)

DEFAULTS = {
    "standard_fps": 25,
    "start_frame": 1001,
    "approved_presets": list(APPROVED_PRESETS_DEFAULT),
    "default_names": [
        "null",
        "cube",
        "sphere",
        "cylinder",
        "cone",
        "plane",
        "disc",
        "torus",
        "capsule",
        "oil tank",
        "platonic",
        "pyramid",
        "gem",
        "tube",
        "landscape",
        "figure",
        "spline",
        "circle",
        "rectangle",
        "n-side",
        "arc",
        "helix",
        "sweep",
        "extrude",
        "lathe",
        "loft",
        "boole",
        "symmetry",
        "instance",
        "cloner",
        "fracture",
        "voronoi fracture",
        "matrix",
        "mograph",
        "camera",
        "light",
        "floor",
        "sky",
        "environment",
        "physical sky",
    ],
    "safe_area_insets": {
        "16x9": {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05},
        "9x16": {"top": 0.08, "bottom": 0.15, "left": 0.05, "right": 0.10},
        "1x1": {"top": 0.05, "bottom": 0.08, "left": 0.05, "right": 0.05},
        "4x5": {"top": 0.05, "bottom": 0.10, "left": 0.05, "right": 0.05},
        "21x9": {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05},
    },
    "check_severity": dict(CHECK_DEFAULT_SEVERITY),
    "checks_enabled": {check_id: True for check_id in CHECK_DEFAULT_SEVERITY},
}

_RULES_CACHE: dict[str, dict[str, Any]] = {}
_ACTIVE_RULE_IDENTITIES: dict[str, tuple[str | None, float | None]] = {}


@dataclass(frozen=True)
class RulesContext:
    """Resolved rule parameters and their provenance.

    ``source`` is the primary source represented in the effective params:
    project if any field came from the rules file, then machine, then defaults.
    ``field_sources`` records the winning origin for each top-level field.
    ``reason`` carries special resolution context such as ``"unsaved"``.
    """

    params: dict[str, Any]
    source: str
    field_sources: dict[str, str]
    rules_path: str | None
    shadowed_paths: list[str]
    warnings: list[str]
    identity: tuple[str | None, float | None]
    reason: str | None = None


def invalidate() -> None:
    """Clear the module-level rules cache."""
    _RULES_CACHE.clear()
    _ACTIVE_RULE_IDENTITIES.clear()


def get_active_rules(
    doc_path: str | os.PathLike[str] | None,
    machine_settings: dict[str, Any] | None = None,
) -> RulesContext:
    """Resolve active rules for runtime checks and invalidate QC cache on file changes."""
    if machine_settings is None:
        machine_settings = _load_machine_settings()

    context = resolve_rules(doc_path, machine_settings or {})
    cache_key = _active_identity_key(doc_path)
    previous_identity = _ACTIVE_RULE_IDENTITIES.get(cache_key)
    if previous_identity is not None and previous_identity != context.identity:
        try:
            from sentinel.common.cache import check_cache

            check_cache.clear()
        except Exception:
            pass
    _ACTIVE_RULE_IDENTITIES[cache_key] = context.identity
    return context


def discover_rules_file(scene_dir: str | os.PathLike[str] | None) -> tuple[str | None, list[str]]:
    """Find the nearest sentinel_rules.json at scene_dir or up to 3 ancestors."""
    if not scene_dir:
        return None, []

    current = Path(scene_dir).expanduser()
    found: list[str] = []
    for _level in range(4):
        candidate = current / RULES_FILENAME
        if candidate.is_file():
            found.append(str(candidate))

        parent = current.parent
        if parent == current:
            break
        current = parent

    if not found:
        return None, []
    return found[0], found[1:]


def load_rules(path: str | os.PathLike[str] | None) -> tuple[dict[str, Any], list[str]]:
    """Load and validate a rules file. Returns ({}, warnings) on any problem."""
    if not path:
        return {}, []

    warnings: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        return {}, [f"Could not read rules file {path}: {exc}"]

    if not isinstance(raw, dict):
        return {}, [f"Rules file {path} must contain a JSON object"]

    rules: dict[str, Any] = {}
    for key, value in raw.items():
        valid, normalized, reason = _validate_key(key, value)
        if valid:
            rules[key] = normalized
        else:
            warnings.append(f"Rejected rules key '{key}': {reason}")
    return rules, warnings


def resolve_rules(
    scene_path: str | os.PathLike[str] | None,
    machine_settings: dict[str, Any] | None,
) -> RulesContext:
    """Resolve effective rules with precedence project > machine > defaults."""
    if not scene_path:
        params, field_sources, machine_warnings = _merge_params({}, machine_settings or {})
        return RulesContext(
            params=params,
            source=_primary_source(field_sources),
            field_sources=field_sources,
            rules_path=None,
            shadowed_paths=[],
            warnings=machine_warnings,
            identity=(None, None),
            reason="unsaved",
        )

    scene_dir = _scene_dir(scene_path)
    rules_path, shadowed_paths = discover_rules_file(scene_dir)
    identity = (rules_path, _mtime(rules_path) if rules_path else None)
    project_rules, project_warnings = _cached_project_rules(str(scene_dir), identity)

    params, field_sources, machine_warnings = _merge_params(project_rules, machine_settings or {})
    return RulesContext(
        params=params,
        source=_primary_source(field_sources),
        field_sources=field_sources,
        rules_path=rules_path,
        shadowed_paths=shadowed_paths,
        warnings=project_warnings + machine_warnings,
        identity=identity,
        reason=None,
    )


def _scene_dir(scene_path: str | os.PathLike[str]) -> Path:
    path = Path(scene_path).expanduser()
    if path.is_dir():
        return path
    return path.parent


def _active_identity_key(doc_path: str | os.PathLike[str] | None) -> str:
    if not doc_path:
        return "<unsaved>"
    try:
        return str(_scene_dir(doc_path))
    except Exception:
        return str(doc_path)


def _load_machine_settings() -> dict[str, Any]:
    settings: dict[str, Any] = {}
    try:
        from sentinel.common.settings import GlobalSettings

        settings["standard_fps"] = GlobalSettings.get_standard_fps()
    except Exception:
        pass
    return settings


def _mtime(path: str | None) -> float | None:
    if not path:
        return None
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _cached_project_rules(
    cache_key: str,
    identity: tuple[str | None, float | None],
) -> tuple[dict[str, Any], list[str]]:
    cached = _RULES_CACHE.get(cache_key)
    if cached and cached.get("identity") == identity:
        return copy.deepcopy(cached["rules"]), list(cached["warnings"])

    if identity[0] is None:
        rules, warnings = {}, []
    else:
        rules, warnings = load_rules(identity[0])

    _RULES_CACHE[cache_key] = {
        "identity": identity,
        "rules": copy.deepcopy(rules),
        "warnings": list(warnings),
    }
    return rules, warnings


def _merge_params(
    project_rules: dict[str, Any],
    machine_settings: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    params = copy.deepcopy(DEFAULTS)
    field_sources = {key: "defaults" for key in DEFAULTS}
    warnings: list[str] = []

    valid_machine: dict[str, Any] = {}
    for key, value in (machine_settings or {}).items():
        valid, normalized, reason = _validate_key(key, value)
        if valid:
            valid_machine[key] = normalized
        else:
            warnings.append(f"Rejected machine setting '{key}': {reason}")

    _apply_source(params, field_sources, valid_machine, "machine")
    _apply_source(params, field_sources, project_rules, "project")
    return params, field_sources, warnings


def _apply_source(
    params: dict[str, Any],
    field_sources: dict[str, str],
    values: dict[str, Any],
    source: str,
) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        if key in MAP_MERGE_KEYS:
            merged = copy.deepcopy(params[key])
            for child_key, child_value in value.items():
                if key == "safe_area_insets" and isinstance(child_value, dict):
                    existing = merged.get(child_key, {})
                    if isinstance(existing, dict):
                        nested = copy.deepcopy(existing)
                        nested.update(copy.deepcopy(child_value))
                        merged[child_key] = nested
                    else:
                        merged[child_key] = copy.deepcopy(child_value)
                else:
                    merged[child_key] = copy.deepcopy(child_value)
            params[key] = merged
        else:
            params[key] = copy.deepcopy(value)
        field_sources[key] = source


def _primary_source(field_sources: dict[str, str]) -> str:
    sources = set(field_sources.values())
    if "project" in sources:
        return "project"
    if "machine" in sources:
        return "machine"
    return "defaults"


def _validate_key(key: str, value: Any) -> tuple[bool, Any, str | None]:
    if key == "standard_fps":
        if _is_number(value):
            return True, value, None
        return False, None, "expected a number"

    if key == "start_frame":
        if isinstance(value, int) and not isinstance(value, bool):
            return True, value, None
        return False, None, "expected an int"

    if key in {"approved_presets", "default_names"}:
        if _is_str_list(value):
            return True, list(value), None
        return False, None, "expected a list of strings"

    if key == "safe_area_insets":
        return _validate_safe_area_insets(value)

    if key == "check_severity":
        return _validate_check_severity(value)

    if key == "checks_enabled":
        return _validate_checks_enabled(value)

    return False, None, "unknown key"


def _validate_safe_area_insets(value: Any) -> tuple[bool, Any, str | None]:
    if not isinstance(value, dict):
        return False, None, "expected a per-format dict"

    normalized: dict[str, dict[str, float | int]] = {}
    for fmt_id, insets in value.items():
        if not isinstance(fmt_id, str):
            return False, None, "format ids must be strings"
        if not isinstance(insets, dict):
            return False, None, f"format '{fmt_id}' must map to an inset dict"
        for side in ("top", "bottom", "left", "right"):
            if side not in insets:
                return False, None, f"format '{fmt_id}' missing '{side}'"
            if not _is_number(insets[side]):
                return False, None, f"format '{fmt_id}' side '{side}' expected a number"
        normalized[fmt_id] = {
            "top": insets["top"],
            "bottom": insets["bottom"],
            "left": insets["left"],
            "right": insets["right"],
        }
    return True, normalized, None


def _validate_check_severity(value: Any) -> tuple[bool, Any, str | None]:
    if not isinstance(value, dict):
        return False, None, "expected a dict of check_id to severity"
    unknown = sorted(str(check_id) for check_id in value if check_id not in CHECK_IDS)
    if unknown:
        return False, None, f"unknown check id(s): {', '.join(unknown)}"
    bad = sorted(str(check_id) for check_id, severity in value.items() if severity not in SEVERITIES)
    if bad:
        return False, None, f"invalid severity for check id(s): {', '.join(bad)}"
    return True, dict(value), None


def _validate_checks_enabled(value: Any) -> tuple[bool, Any, str | None]:
    if not isinstance(value, dict):
        return False, None, "expected a dict of check_id to bool"
    unknown = sorted(str(check_id) for check_id in value if check_id not in CHECK_IDS)
    if unknown:
        return False, None, f"unknown check id(s): {', '.join(unknown)}"
    bad = sorted(str(check_id) for check_id, enabled in value.items() if not isinstance(enabled, bool))
    if bad:
        return False, None, f"enabled value must be bool for check id(s): {', '.join(bad)}"
    return True, dict(value), None


def _is_number(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
