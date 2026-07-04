import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "plugin" / "sentinel" / "rules.py"

spec = importlib.util.spec_from_file_location("sentinel_rules_under_test", RULES_PATH)
rules = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rules
spec.loader.exec_module(rules)


def write_rules(directory, payload):
    path = directory / rules.RULES_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_discover_rules_nearest_wins_and_reports_shadowed(tmp_path):
    project = tmp_path / "project"
    scene_dir = project / "shots" / "shot010"
    scene_dir.mkdir(parents=True)
    project_rules = write_rules(project, {"standard_fps": 24})
    scene_rules = write_rules(scene_dir, {"standard_fps": 30})

    found, shadowed = rules.discover_rules_file(scene_dir)

    assert found == str(scene_rules)
    assert shadowed == [str(project_rules)]


def test_discover_rules_ignores_files_beyond_three_ancestors(tmp_path):
    scene_dir = tmp_path / "a" / "b" / "c" / "d"
    scene_dir.mkdir(parents=True)
    write_rules(tmp_path, {"standard_fps": 24})

    found, shadowed = rules.discover_rules_file(scene_dir)

    assert found is None
    assert shadowed == []


def test_corrupt_json_falls_back_to_defaults_with_warning(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    scene_path = scene_dir / "shot.c4d"
    rules_path = scene_dir / rules.RULES_FILENAME
    rules_path.write_text("{not valid json", encoding="utf-8")

    rules.invalidate()
    context = rules.resolve_rules(scene_path, {})

    assert context.params == rules.DEFAULTS
    assert context.source == "defaults"
    assert context.rules_path == str(rules_path)
    assert context.warnings
    assert "Could not read rules file" in context.warnings[0]


def test_bad_key_type_is_rejected_but_other_file_keys_apply(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {
            "standard_fps": "twenty",
            "start_frame": 1000,
            "approved_presets": ["render", "custom"],
        },
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == rules.DEFAULTS["standard_fps"]
    assert context.params["start_frame"] == 1000
    assert context.params["approved_presets"] == ["render", "custom"]
    assert any("standard_fps" in warning and "expected a number" in warning for warning in context.warnings)


def test_standard_fps_and_start_frame_validate_ranges(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {
            "standard_fps": 23.976,
            "start_frame": -1,
        },
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == rules.DEFAULTS["standard_fps"]
    assert context.params["start_frame"] == rules.DEFAULTS["start_frame"]
    assert any("standard_fps" in warning and "integer in range 1..240" in warning for warning in context.warnings)
    assert any("start_frame" in warning and "int >= 0" in warning for warning in context.warnings)


def test_gates_enabled_true_in_project_rules(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"gates_enabled": True})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["gates_enabled"] is True
    assert context.field_sources["gates_enabled"] == "project"


def test_gates_enabled_defaults_to_false_when_absent(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["gates_enabled"] is False
    assert context.field_sources["gates_enabled"] == "defaults"


def test_invalid_gates_enabled_is_rejected_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"gates_enabled": "yes", "start_frame": 1000})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["gates_enabled"] is False
    assert context.params["start_frame"] == 1000
    assert any("gates_enabled" in warning and "expected a bool" in warning for warning in context.warnings)


def test_project_gates_enabled_false_wins_over_machine_true(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"gates_enabled": False})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {"gates_enabled": True})

    assert context.params["gates_enabled"] is False
    assert context.field_sources["gates_enabled"] == "project"


def test_integral_float_standard_fps_is_normalized(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"standard_fps": 24.0})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert isinstance(context.params["standard_fps"], int)


def test_default_rules_are_sourced_from_registry_and_constants(sentinel_module):
    from sentinel.common.constants import DEFAULT_OBJECT_NAMES, PRESETS
    from sentinel.qc.registry import CHECK_REGISTRY

    assert rules.DEFAULTS["approved_presets"] == list(PRESETS)
    assert rules.DEFAULTS["default_names"] == list(DEFAULT_OBJECT_NAMES)
    assert rules.CHECK_DEFAULT_SEVERITY == {
        entry.check_id: entry.severity for entry in CHECK_REGISTRY
    }


def test_no_rules_file_and_no_machine_settings_returns_embedded_defaults(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params == rules.DEFAULTS
    assert context.source == "defaults"
    assert all(source == "defaults" for source in context.field_sources.values())
    assert context.rules_path is None
    assert context.shadowed_paths == []
    assert context.warnings == []


def test_machine_settings_win_over_defaults_without_project_rules(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()

    rules.invalidate()
    context = rules.resolve_rules(
        scene_dir / "shot.c4d",
        {"standard_fps": 24, "start_frame": 1000},
    )

    assert context.params["standard_fps"] == 24
    assert context.params["start_frame"] == 1000
    assert context.source == "machine"
    assert context.field_sources["standard_fps"] == "machine"
    assert context.field_sources["approved_presets"] == "defaults"


def test_project_rules_win_over_machine_settings_for_same_key(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"standard_fps": 30})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {"standard_fps": 24})

    assert context.params["standard_fps"] == 30
    assert context.source == "project"
    assert context.field_sources["standard_fps"] == "project"


def test_rules_file_mtime_change_reloads_without_manual_invalidate(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    rules_path = write_rules(scene_dir, {"standard_fps": 24})

    rules.invalidate()
    first = rules.resolve_rules(scene_dir / "shot.c4d", {})
    assert first.params["standard_fps"] == 24

    rules_path.write_text(json.dumps({"standard_fps": 30}), encoding="utf-8")
    new_mtime = os.path.getmtime(rules_path) + 5.0
    os.utime(rules_path, (new_mtime, new_mtime))

    second = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert second.params["standard_fps"] == 30
    assert second.identity != first.identity


def test_unsaved_scene_uses_machine_and_defaults_with_unsaved_reason():
    rules.invalidate()
    context = rules.resolve_rules("", {"standard_fps": 24})

    assert context.params["standard_fps"] == 24
    assert context.params["start_frame"] == rules.DEFAULTS["start_frame"]
    assert context.source == "machine"
    assert context.reason == "unsaved"
    assert context.rules_path is None
    assert context.identity == (None, None)


def test_unknown_check_id_rejects_entire_map_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {
            "standard_fps": 24,
            "check_severity": {"not_a_check": "FAIL"},
            "checks_enabled": {"also_not_a_check": False},
        },
    )
    expected_severity = copy.deepcopy(rules.DEFAULTS["check_severity"])
    expected_enabled = copy.deepcopy(rules.DEFAULTS["checks_enabled"])

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert context.params["check_severity"] == expected_severity
    assert context.params["checks_enabled"] == expected_enabled
    assert any("check_severity" in warning and "unknown check id" in warning for warning in context.warnings)
    assert any("checks_enabled" in warning and "unknown check id" in warning for warning in context.warnings)


def test_effective_params_feed_registry_consumer_from_project_machine_defaults(tmp_path):
    scene_dir = tmp_path / "project" / "shots"
    scene_dir.mkdir(parents=True)
    write_rules(
        scene_dir,
        {
            "standard_fps": 24,
            "approved_presets": ["render", "custom"],
        },
    )

    rules.invalidate()
    context = rules.resolve_rules(
        scene_dir / "shot.c4d",
        {
            "standard_fps": 30,
            "start_frame": 1000,
            "default_names": ["locator"],
        },
    )

    def fake_registry_consumer(rules_context):
        return {
            "fps": rules_context.params["standard_fps"],
            "start": rules_context.params["start_frame"],
            "presets": rules_context.params["approved_presets"],
            "names": rules_context.params["default_names"],
            "safe_area_9x16": rules_context.params["safe_area_insets"]["9x16"],
        }

    consumed = fake_registry_consumer(context)

    assert consumed["fps"] == 24
    assert context.field_sources["standard_fps"] == "project"
    assert consumed["start"] == 1000
    assert context.field_sources["start_frame"] == "machine"
    assert consumed["presets"] == ["render", "custom"]
    assert consumed["names"] == ["locator"]
    assert consumed["safe_area_9x16"] == rules.DEFAULTS["safe_area_insets"]["9x16"]
