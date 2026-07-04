"""Run Sentinel QC fixture scenes inside Cinema 4D or c4dpy.

Usage:
  c4dpy tests/c4d_runner/run_fixtures.py
  c4dpy tests/c4d_runner/run_fixtures.py --freeze

In Script Manager, open this file and run it. To freeze expected JSON from
Script Manager, set FREEZE_EXPECTED = True below before running.
"""

from __future__ import annotations

import difflib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

import c4d
from c4d import documents


FREEZE_EXPECTED = False
FIXTURE_NAMES = ("violating", "clean")
CHECKS = (
    ("lights", "check_lights"),
    ("visibility_traps", "check_visibility_traps"),
    ("keys", "check_keys"),
    ("camera_shift", "check_camera_shift"),
    ("render_conflicts", "check_render_conflicts"),
    ("textures", "check_textures_unified"),
    ("unused_materials", "check_unused_materials"),
    ("default_names", "check_default_names"),
    ("output_paths", "check_output_paths"),
    ("takes", "check_takes"),
    ("fps_range", "check_fps_range"),
    ("cross_aspect_safe_area", "check_cross_aspect_safe_area"),
)
STRUCTURED_CHECKS = (
    ("lights", "scene_checks", "check_lights", {}),
    ("visibility_traps", "scene_checks", "check_visibility_traps", {}),
    ("keys", "scene_checks", "check_keys", {}),
    ("camera_shift", "scene_checks", "check_camera_shift", {}),
    ("render_conflicts", "render_checks", "check_render_conflicts", {}),
    ("textures", None, "check_textures_unified_structured", {}),
    ("unused_materials", "scene_checks", "check_unused_materials", {}),
    ("default_names", "scene_checks", "check_default_names", {}),
    ("output_paths", "render_checks", "check_output_paths", {}),
    ("takes", "render_checks", "check_takes", {}),
    ("fps_range", "render_checks", "check_fps_range", {}),
    (
        "cross_aspect_safe_area",
        None,
        "check_cross_aspect_safe_area_structured",
        {"sample_strategy": "current_frame"},
    ),
)


def _script_path() -> Path:
    try:
        return Path(__file__).resolve()
    except NameError:
        return Path(os.getcwd()).resolve() / "tests" / "c4d_runner" / "run_fixtures.py"


ROOT = _script_path().parents[2]
PLUGIN_PATH = ROOT / "plugin" / "sentinel_panel.pyp"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


def _load_sentinel():
    # Test-harness-only purge: C4D caches the `sentinel` package between runner
    # executions, so a fresh .pyp load would import stale package modules.
    # Safe here because the runner owns no live plugin instances; the shipping
    # plugin's reload policy remains restart-only (no purge in the .pyp).
    for mod_name in [m for m in sys.modules if m == "sentinel" or m.startswith("sentinel.")]:
        del sys.modules[mod_name]
    loader = importlib.machinery.SourceFileLoader(
        "sentinel_panel_fixture_runner", str(PLUGIN_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    # Pin machine-dependent settings for deterministic fixture output.
    module.GlobalSettings.get_standard_fps = staticmethod(lambda: 25)
    # Rules resolution reads GlobalSettings lazily, so this pin still feeds
    # the default rules context when no sentinel_rules.json fixture is present.
    module.get_active_rules("", {"standard_fps": 25})
    module.check_cache.clear()
    return module


def _name(value):
    try:
        return value.GetName() or "<unnamed>"
    except Exception:
        return str(value)


def _normalize_path(value):
    if not isinstance(value, str):
        return value
    return value.replace("\\", "/")


def _normalize(value):
    if isinstance(value, dict):
        out = {}
        for key in sorted(value.keys(), key=str):
            if key == "object":
                continue
            normalized_key = str(key)
            item = value[key]
            if key in ("path", "resolved") and isinstance(item, str):
                item = _normalize_path(item)
            out[normalized_key] = _normalize(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if hasattr(value, "GetName"):
        return _name(value)
    return _normalize_path(value)


def _placeholder_guid_values(value):
    """Replace serialized GUID values so fixture oracles survive rebuilds."""
    if isinstance(value, dict):
        out = {}
        for key in sorted(value.keys(), key=str):
            normalized_key = str(key)
            if normalized_key == "guid":
                out[normalized_key] = "<guid>"
            else:
                out[normalized_key] = _placeholder_guid_values(value[key])
        return out
    if isinstance(value, list):
        return [_placeholder_guid_values(item) for item in value]
    return value


def _run_checks(module, doc):
    module.check_cache.clear()
    results = {}
    for check_id, func_name in CHECKS:
        func = getattr(module, func_name)
        if func_name == "check_cross_aspect_safe_area":
            raw = func(doc, sample_strategy="current_frame")
        else:
            raw = func(doc)
        results[check_id] = _normalize(raw)
    return results


def _resolve_structured_callable(module, owner_attr, func_name):
    owner = getattr(module, owner_attr) if owner_attr else module
    return getattr(owner, func_name)


def _run_structured_checks(module, doc):
    module.check_cache.clear()
    results = {}
    for check_id, owner_attr, func_name, kwargs in STRUCTURED_CHECKS:
        func = _resolve_structured_callable(module, owner_attr, func_name)
        raw = func(doc, **kwargs)
        results[check_id] = _placeholder_guid_values(_normalize(raw))
    return results


def _load_document(path: Path):
    if not path.exists():
        return None, f"missing fixture scene: {path}"
    try:
        # C4D 2026 has no SCENEFILTER_TAKES/RENDERDATA — takes and render data
        # load with the document; OBJECTS|MATERIALS is the full-load pair.
        doc = documents.LoadDocument(
            str(path),
            c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS,
        )
    except Exception as exc:
        return None, f"LoadDocument failed for {path}: {exc}"
    if doc is None:
        return None, f"LoadDocument returned None for {path}"
    return doc, None


def _read_expected(path: Path):
    if not path.exists():
        return None, f"missing expected JSON: {path} (run with --freeze after building fixtures)"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, f"could not read expected JSON {path}: {exc}"


def _json_dump(data):
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def _diff(expected, actual):
    expected_lines = _json_dump(expected).splitlines()
    actual_lines = _json_dump(actual).splitlines()
    return "\n".join(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
    )


def _compare_fixture(actual, expected, checks):
    failures = []
    check_ids = [item[0] for item in checks]
    for check_id in check_ids:
        exp = expected.get(check_id)
        act = actual.get(check_id)
        if exp == act:
            continue
        failures.append((check_id, _diff(exp, act)))
    extra = sorted(set(actual) - set(check_ids))
    missing = sorted(set(check_ids) - set(actual))
    for check_id in extra:
        failures.append((check_id, f"unexpected check key in actual: {check_id}"))
    for check_id in missing:
        failures.append((check_id, f"missing check key in actual: {check_id}"))
    return failures


def main():
    freeze = FREEZE_EXPECTED or "--freeze" in sys.argv or os.environ.get(
        "SENTINEL_FREEZE_EXPECTED"
    ) in ("1", "true", "TRUE", "yes", "YES")
    active_doc = None
    try:
        active_doc = documents.GetActiveDocument()
    except Exception:
        active_doc = None

    loaded_docs = []
    all_failures = []

    try:
        module = _load_sentinel()
        for name in FIXTURE_NAMES:
            scene_path = FIXTURES_DIR / f"{name}.c4d"
            expected_path = FIXTURES_DIR / f"expected_{name}.json"
            structured_expected_path = (
                FIXTURES_DIR / f"expected_{name}_structured.json"
            )

            doc, load_error = _load_document(scene_path)
            if load_error:
                all_failures.append((name, "runner", "load", load_error))
                continue
            loaded_docs.append(doc)

            try:
                actual = _run_checks(module, doc)
                actual_structured = _run_structured_checks(module, doc)
            except Exception:
                all_failures.append((name, "runner", "run", traceback.format_exc()))
                continue

            if freeze:
                expected_path.write_text(_json_dump(actual) + "\n", encoding="utf-8")
                structured_expected_path.write_text(
                    _json_dump(actual_structured) + "\n",
                    encoding="utf-8",
                )
                continue

            expected, expected_error = _read_expected(expected_path)
            if expected_error:
                all_failures.append((name, "text", "expected", expected_error))
            else:
                for check_id, diff_text in _compare_fixture(
                    actual, expected, CHECKS
                ):
                    all_failures.append((name, "text", check_id, diff_text))

            structured_expected, structured_expected_error = _read_expected(
                structured_expected_path
            )
            if structured_expected_error:
                all_failures.append(
                    (name, "structured", "expected", structured_expected_error)
                )
            else:
                for check_id, diff_text in _compare_fixture(
                    actual_structured, structured_expected, STRUCTURED_CHECKS
                ):
                    all_failures.append((name, "structured", check_id, diff_text))
    finally:
        for doc in loaded_docs:
            try:
                documents.KillDocument(doc)
            except Exception:
                pass
        if active_doc is not None:
            try:
                documents.SetActiveDocument(active_doc)
            except Exception:
                pass
        try:
            c4d.EventAdd()
        except Exception:
            pass

    if all_failures:
        print(f"FAIL Sentinel fixture runner: {len(all_failures)} failure(s)")
        for fixture_name, oracle, check_id, detail in all_failures:
            if oracle in ("text", "structured"):
                print(f"\n[{fixture_name}] {oracle} oracle: {check_id}")
            else:
                print(f"\n[{fixture_name}] {oracle}: {check_id}")
            print(detail)
        return 1

    if freeze:
        print(
            "PASS Sentinel fixture runner: froze text and structured expected JSON for "
            + ", ".join(FIXTURE_NAMES)
        )
    else:
        print(
            "PASS Sentinel fixture runner: "
            f"{len(FIXTURE_NAMES)} fixture(s) matched text and structured expected JSON"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
