# -*- coding: utf-8 -*-
"""Declarative QC check registry."""

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module


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
    ),
    CheckEntry(
        check_id="textures",
        row_label="Assets",
        label_ok="All assets OK",
        label_fail_template="{n} asset issue(s)",
        names_key=None,
        severity="FAIL",
        has_fix=False,
        structured_fn="panel.check_textures_unified_structured",
        legacy_fn="panel.check_textures_unified",
        preflight_template="  {n} asset path issues",
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
    ),
    CheckEntry(
        check_id="cross_aspect",
        row_label="Safe Area",
        label_ok="Subjects fit safe areas",
        label_fail_template="{n} cross-aspect violation(s)",
        names_key=None,
        severity="WARN",
        has_fix=False,
        structured_fn="panel.check_cross_aspect_safe_area_structured",
        legacy_fn="panel.check_cross_aspect_safe_area",
        preflight_template="  {n} cross-aspect violations",
        structured_kwargs={"sample_strategy": "current_frame"},
        legacy_kwargs={"sample_strategy": "current_frame"},
    ),
]


def _check_id(entry):
    if isinstance(entry, Mapping):
        return entry.get("check_id")
    return getattr(entry, "check_id", None)


def validate_registry(entries):
    """Raise ValueError immediately for duplicate check ids."""
    seen = set()
    for entry in entries:
        check_id = _check_id(entry)
        if not check_id:
            raise ValueError("QC registry entry is missing check_id")
        if check_id in seen:
            raise ValueError(f"Duplicate QC check_id: {check_id}")
        seen.add(check_id)
    return True


def resolve_function(fn_ref, panel_module=None):
    """Resolve a registry function reference lazily."""
    source, func_name = fn_ref.split(".", 1)
    if source == "scene":
        module = import_module("sentinel.checks.scene")
    elif source == "render":
        module = import_module("sentinel.checks.render")
    elif source == "panel":
        if panel_module is None:
            raise ValueError(f"Panel module is required to resolve {fn_ref}")
        module = panel_module
    else:
        raise ValueError(f"Unknown QC function source: {source}")
    return getattr(module, func_name)


def display_tuple(entry):
    return (
        entry.severity,
        entry.label_ok,
        entry.label_fail_template,
        entry.names_key,
    )


def build_check_display(entries=None):
    entries = CHECK_REGISTRY if entries is None else entries
    return OrderedDict((entry.check_id, display_tuple(entry)) for entry in entries)


def build_row_keys(entries=None):
    entries = CHECK_REGISTRY if entries is None else entries
    return [entry.check_id for entry in entries]


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
