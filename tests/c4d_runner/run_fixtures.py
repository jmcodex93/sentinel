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


def _script_path() -> Path:
    try:
        return Path(__file__).resolve()
    except NameError:
        return Path(os.getcwd()).resolve() / "tests" / "c4d_runner" / "run_fixtures.py"


ROOT = _script_path().parents[2]
PLUGIN_PATH = ROOT / "plugin" / "sentinel_panel.pyp"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


def _load_sentinel():
    loader = importlib.machinery.SourceFileLoader(
        "sentinel_panel_fixture_runner", str(PLUGIN_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    # Pin machine-dependent settings for deterministic fixture output.
    module.GlobalSettings.get_standard_fps = staticmethod(lambda: 25)
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


def _load_document(path: Path):
    if not path.exists():
        return None, f"missing fixture scene: {path}"
    try:
        doc = documents.LoadDocument(
            str(path),
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_MERGESCENE
            | c4d.SCENEFILTER_TAKES
            | c4d.SCENEFILTER_RENDERDATA,
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


def _compare_fixture(name, actual, expected):
    failures = []
    for check_id, _func_name in CHECKS:
        exp = expected.get(check_id)
        act = actual.get(check_id)
        if exp == act:
            continue
        failures.append((check_id, _diff(exp, act)))
    extra = sorted(set(actual) - {check_id for check_id, _ in CHECKS})
    missing = sorted({check_id for check_id, _ in CHECKS} - set(actual))
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

            doc, load_error = _load_document(scene_path)
            if load_error:
                all_failures.append((name, "load", load_error))
                continue
            loaded_docs.append(doc)

            try:
                actual = _run_checks(module, doc)
            except Exception:
                all_failures.append((name, "run", traceback.format_exc()))
                continue

            if freeze:
                expected_path.write_text(_json_dump(actual) + "\n", encoding="utf-8")
                continue

            expected, expected_error = _read_expected(expected_path)
            if expected_error:
                all_failures.append((name, "expected", expected_error))
                continue

            for check_id, diff_text in _compare_fixture(name, actual, expected):
                all_failures.append((name, check_id, diff_text))
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
        for fixture_name, check_id, detail in all_failures:
            print(f"\n[{fixture_name}] {check_id}")
            print(detail)
        return 1

    if freeze:
        print(
            "PASS Sentinel fixture runner: froze expected JSON for "
            + ", ".join(FIXTURE_NAMES)
        )
    else:
        print(
            "PASS Sentinel fixture runner: "
            f"{len(FIXTURE_NAMES)} fixture(s) matched expected JSON"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
