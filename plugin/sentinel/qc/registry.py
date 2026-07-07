# -*- coding: utf-8 -*-
"""Declarative QC check registry."""

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module


ALLOWED_ACTIONS = ("select", "info", "fix")


@dataclass(frozen=True)
class CheckEntry:
    check_id: str
    row_label: str
    label_ok: str
    label_fail_template: str
    names_key: str | None
    severity: str
    has_fix: bool
    structured_fn: str
    legacy_fn: str
    preflight_template: str
    report_key: str
    actions: tuple
    fix_fn: str | None = None
    # Row-click action; defaults to actions[0] (the first/primary button).
    row_click_action: str | None = None
    # "objects": fix_fn(doc, objects); "document": fix_fn(doc) — no object list.
    fix_scope: str = "objects"
    structured_kwargs: dict = field(default_factory=dict)
    legacy_kwargs: dict = field(default_factory=dict)
    legacy_from_structured: bool = True
    preflight_order: int | None = None


CHECK_REGISTRY = [
    CheckEntry(
        check_id="lights",
        row_label="Lights",
        label_ok="All lights properly organized",
        label_fail_template="{n} lights outside lights group",
        names_key=None,
        severity="FAIL",
        has_fix=True,
        structured_fn="scene.check_lights",
        legacy_fn="scene.check_lights",
        preflight_template="  {n} lights outside group",
        report_key="lights",
        actions=("select", "fix"),
        fix_fn="panel.fix_lights",
    ),
    CheckEntry(
        check_id="vis",
        row_label="Visibility",
        label_ok="Visibility settings consistent",
        label_fail_template="Visibility mismatch on '{first}'",
        names_key="vis_names",
        severity="WARN",
        has_fix=False,
        structured_fn="scene.check_visibility_traps",
        legacy_fn="scene.check_visibility_traps",
        preflight_template="  {n} visibility mismatches",
        report_key="visibility",
        actions=("select",),
    ),
    CheckEntry(
        check_id="keys",
        row_label="Keyframes",
        label_ok="Keyframes properly configured",
        label_fail_template="Multi-axis keys on '{first}'",
        names_key="keys_names",
        severity="WARN",
        has_fix=False,
        structured_fn="scene.check_keys",
        legacy_fn="scene.check_keys",
        preflight_template="  {n} multi-axis keyframes",
        report_key="keyframes",
        actions=("select",),
    ),
    CheckEntry(
        check_id="cam",
        row_label="Cameras",
        label_ok="Camera shifts at 0%",
        label_fail_template="{n} camera(s) with non-zero shift",
        names_key=None,
        severity="FAIL",
        has_fix=True,
        structured_fn="scene.check_camera_shift",
        legacy_fn="scene.check_camera_shift",
        preflight_template="  {n} camera shift issues",
        report_key="camera_shift",
        actions=("select", "fix"),
        fix_fn="panel.fix_camera_shift",
    ),
    CheckEntry(
        check_id="rdc",
        row_label="Presets",
        label_ok="Render presets compliant",
        label_fail_template="{n} non-standard render preset(s)",
        names_key=None,
        severity="FAIL",
        has_fix=False,
        structured_fn="render.check_render_conflicts",
        legacy_fn="render.check_render_conflicts",
        preflight_template="  {n} render preset issues",
        report_key="render_presets",
        actions=("info",),
    ),
    CheckEntry(
        check_id="textures",
        row_label="Assets",
        label_ok="All assets OK",
        label_fail_template="{n} asset issue(s)",
        names_key=None,
        severity="FAIL",
        has_fix=False,
        structured_fn="assets.check_textures_unified_structured",
        legacy_fn="assets.check_textures_unified",
        preflight_template="  {n} asset path issues",
        report_key="textures",
        actions=("info",),
    ),
    CheckEntry(
        check_id="unused_mats",
        row_label="Materials",
        label_ok="All materials assigned",
        label_fail_template="{n} unused material(s)",
        names_key=None,
        severity="WARN",
        has_fix=True,
        structured_fn="scene.check_unused_materials",
        legacy_fn="scene.check_unused_materials",
        preflight_template="  {n} unused materials",
        report_key="unused_materials",
        actions=("select", "fix"),
        fix_fn="panel.fix_unused_materials",
    ),
    CheckEntry(
        check_id="names",
        row_label="Naming",
        label_ok="All objects named",
        label_fail_template="Default name '{first}'",
        names_key="names_list",
        severity="WARN",
        has_fix=False,
        structured_fn="scene.check_default_names",
        legacy_fn="scene.check_default_names",
        preflight_template="  {n} objects with default names",
        report_key="default_names",
        actions=("select",),
    ),
    CheckEntry(
        check_id="output",
        row_label="Output",
        label_ok="Output paths configured",
        label_fail_template="{n} output path issue(s)",
        names_key=None,
        severity="FAIL",
        has_fix=False,
        structured_fn="render.check_output_paths",
        legacy_fn="render.check_output_paths",
        preflight_template="  {n} output path issues",
        report_key="output_paths",
        actions=("info",),
        preflight_order=9,
    ),
    CheckEntry(
        check_id="takes",
        row_label="Takes",
        label_ok="Takes configured",
        label_fail_template="{n} take issue(s)",
        names_key=None,
        severity="FAIL",
        has_fix=False,
        structured_fn="render.check_takes",
        legacy_fn="render.check_takes",
        preflight_template="  {n} take issues",
        report_key="takes",
        actions=("info",),
        preflight_order=8,
    ),
    CheckEntry(
        check_id="fps_range",
        row_label="FPS/Range",
        label_ok="FPS & frame range OK",
        label_fail_template="{n} FPS/range issue(s)",
        names_key=None,
        severity="FAIL",
        has_fix=True,
        structured_fn="render.check_fps_range",
        legacy_fn="render.check_fps_range",
        preflight_template="  {n} FPS/range issues",
        report_key="fps_range",
        actions=("info", "fix"),
        fix_fn="panel.fix_fps_range",
        fix_scope="document",
    ),
    CheckEntry(
        check_id="cross_aspect",
        row_label="Safe Area",
        label_ok="Subjects fit safe areas",
        label_fail_template="{n} cross-aspect violation(s)",
        names_key=None,
        severity="WARN",
        has_fix=False,
        structured_fn="safe_areas.check_cross_aspect_safe_area_structured",
        legacy_fn="safe_areas.check_cross_aspect_safe_area",
        preflight_template="  {n} cross-aspect violations",
        report_key="cross_aspect",
        actions=("select", "info"),
        # Row click runs the full keyframe sweep, not the cheap current-frame select.
        row_click_action="info",
        structured_kwargs={"sample_strategy": "current_frame"},
        legacy_kwargs={"sample_strategy": "current_frame"},
    ),
]


def _check_id(entry):
    if isinstance(entry, Mapping):
        return entry.get("check_id")
    return getattr(entry, "check_id", None)


def validate_registry(entries):
    """Raise ValueError immediately for malformed or duplicate registry entries."""
    seen = set()
    seen_report_keys = set()
    for entry in entries:
        check_id = _check_id(entry)
        if not check_id:
            raise ValueError("QC registry entry is missing check_id")
        if check_id in seen:
            raise ValueError(f"Duplicate QC check_id: {check_id}")
        seen.add(check_id)

        actions = getattr(entry, "actions", None)
        if not actions:
            raise ValueError(f"QC check {check_id} has no actions")
        for action in actions:
            if action not in ALLOWED_ACTIONS:
                raise ValueError(f"QC check {check_id} has invalid action: {action}")

        row_click_action = getattr(entry, "row_click_action", None)
        if row_click_action is not None and row_click_action not in actions:
            raise ValueError(
                f"QC check {check_id}: row_click_action ({row_click_action}) "
                f"must be one of its actions"
            )

        fix_scope = getattr(entry, "fix_scope", "objects")
        if fix_scope not in ("objects", "document"):
            raise ValueError(f"QC check {check_id} has invalid fix_scope: {fix_scope}")

        report_key = getattr(entry, "report_key", None)
        if not report_key:
            raise ValueError(f"QC check {check_id} has no report_key")
        if report_key in seen_report_keys:
            raise ValueError(f"Duplicate QC report_key: {report_key}")
        seen_report_keys.add(report_key)

        has_fix = bool(getattr(entry, "has_fix", False))
        fix_fn = getattr(entry, "fix_fn", None)
        if has_fix != bool(fix_fn):
            raise ValueError(
                f"QC check {check_id}: has_fix ({has_fix}) must match "
                f"whether fix_fn is set ({bool(fix_fn)})"
            )
    return True


def resolve_function(fn_ref, panel_module=None):
    """Resolve a registry function reference lazily."""
    source, func_name = fn_ref.split(".", 1)
    if source == "scene":
        module = import_module("sentinel.checks.scene")
    elif source == "render":
        module = import_module("sentinel.checks.render")
    elif source == "assets":
        module = import_module("sentinel.checks.assets")
    elif source == "safe_areas":
        module = import_module("sentinel.checks.safe_areas")
    elif source == "panel":
        if panel_module is None:
            raise ValueError(f"Panel module is required to resolve {fn_ref}")
        module = panel_module
    else:
        raise ValueError(f"Unknown QC function source: {source}")
    return getattr(module, func_name)


def _rules_params(rules_context):
    return getattr(rules_context, "params", {}) if rules_context is not None else {}


def is_check_enabled(entry, rules_context=None):
    checks_enabled = _rules_params(rules_context).get("checks_enabled", {})
    return bool(checks_enabled.get(entry.check_id, True))


def entry_severity(entry, rules_context=None):
    check_severity = _rules_params(rules_context).get("check_severity", {})
    return check_severity.get(entry.check_id, entry.severity)


def display_tuple(entry, rules_context=None):
    return (
        entry_severity(entry, rules_context),
        entry.label_ok,
        entry.label_fail_template,
        entry.names_key,
    )


def build_check_display(entries=None, rules_context=None):
    entries = CHECK_REGISTRY if entries is None else entries
    return OrderedDict((entry.check_id, display_tuple(entry, rules_context)) for entry in entries)


def build_row_keys(entries=None, rules_context=None, include_disabled=True):
    entries = CHECK_REGISTRY if entries is None else entries
    return [
        entry.check_id
        for entry in entries
        if include_disabled or is_check_enabled(entry, rules_context)
    ]


class CheckDisplayView(Mapping):
    """Mapping view derived from CHECK_REGISTRY for legacy callers."""

    def __iter__(self):
        return iter(build_row_keys())

    def __len__(self):
        return len(CHECK_REGISTRY)

    def __getitem__(self, key):
        for entry in CHECK_REGISTRY:
            if entry.check_id == key:
                return display_tuple(entry)
        raise KeyError(key)


class RowKeysView(Sequence):
    """Sequence view derived from CHECK_REGISTRY for legacy callers."""

    def __iter__(self):
        return iter(build_row_keys())

    def __len__(self):
        return len(CHECK_REGISTRY)

    def __getitem__(self, index):
        return build_row_keys()[index]


validate_registry(CHECK_REGISTRY)
