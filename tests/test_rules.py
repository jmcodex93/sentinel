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


def test_slate_true_in_project_rules(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"slate": True})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["slate"] is True
    assert context.field_sources["slate"] == "project"


def test_slate_defaults_to_false_when_absent(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["slate"] is False
    assert context.field_sources["slate"] == "defaults"


def test_invalid_slate_is_rejected_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"slate": "yes", "start_frame": 1000})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["slate"] is False
    assert context.params["start_frame"] == 1000
    assert any("slate" in warning and "expected a bool" in warning for warning in context.warnings)


def test_project_slate_false_wins_over_machine_true(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"slate": False})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {"slate": True})

    assert context.params["slate"] is False
    assert context.field_sources["slate"] == "project"


def test_integral_float_standard_fps_is_normalized(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"standard_fps": 24.0})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert isinstance(context.params["standard_fps"], int)


def test_default_rules_are_sourced_from_registry_and_constants(sentinel_module):
    from sentinel.common.constants import DEFAULT_OBJECT_NAMES, PRESETS, STILLS_PRESET_TOKENS
    from sentinel.qc.registry import CHECK_REGISTRY

    assert rules.DEFAULTS["approved_presets"] == list(PRESETS)
    assert rules.DEFAULTS["default_names"] == list(DEFAULT_OBJECT_NAMES)
    assert rules.DEFAULTS["stills_presets"] == list(STILLS_PRESET_TOKENS)
    assert rules.CHECK_DEFAULT_SEVERITY == {
        entry.check_id: entry.severity for entry in CHECK_REGISTRY
    }


def test_required_presets_defaults_to_the_embedded_four(sentinel_module):
    from sentinel.common.constants import PRESETS

    assert rules.DEFAULTS["required_presets"] == list(PRESETS)


def test_required_presets_ruleset_override_accepted(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"required_presets": ["previz", "beauty"]})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["required_presets"] == ["previz", "beauty"]
    assert context.field_sources["required_presets"] == "project"
    # It is its own key: the whitelist keeps its embedded value.
    assert context.params["approved_presets"] == rules.DEFAULTS["approved_presets"]


def test_malformed_required_presets_rejected_by_name_without_dropping_the_rest(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"required_presets": "previz", "standard_fps": 24})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["required_presets"] == rules.DEFAULTS["required_presets"]
    assert any("required_presets" in warning for warning in context.warnings)
    assert context.params["standard_fps"] == 24


def test_stills_presets_ruleset_override_accepted(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"stills_presets": ["stills", "hero"]})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["stills_presets"] == ["stills", "hero"]
    assert context.field_sources["stills_presets"] == "project"


def test_stills_presets_non_list_is_rejected_by_name(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"stills_presets": "stills"})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["stills_presets"] == rules.DEFAULTS["stills_presets"]
    assert any("stills_presets" in warning for warning in context.warnings)


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


def test_matwire_suffixes_default_is_empty_dict():
    assert rules.DEFAULTS["matwire_suffixes"] == {}


def test_valid_matwire_suffixes_accepted_and_normalized(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {"matwire_suffixes": {"basecolor": [" Diff ", "DIFFUSE"]}},
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["matwire_suffixes"] == {"basecolor": ["diff", "diffuse"]}
    assert context.field_sources["matwire_suffixes"] == "project"
    assert context.warnings == []


def test_matwire_suffixes_bad_channel_rejects_entire_key_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {
            "standard_fps": 24,
            "matwire_suffixes": {"not_a_channel": ["diff"]},
        },
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert context.params["matwire_suffixes"] == rules.DEFAULTS["matwire_suffixes"]
    assert any(
        "matwire_suffixes" in warning and "not_a_channel" in warning
        for warning in context.warnings
    )


def test_matwire_suffixes_non_dict_is_rejected_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {
            "standard_fps": 24,
            "matwire_suffixes": ["diff", "albedo"],
        },
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert context.params["matwire_suffixes"] == rules.DEFAULTS["matwire_suffixes"]
    assert any(
        "matwire_suffixes" in warning and "expected a dict" in warning
        for warning in context.warnings
    )


# --- template_scene: the studio template scene, pointed at by the ruleset ---
#
# The distinction these tests exist to pin: a ruleset that says NOTHING is
# the normal, silent case (no path, caller uses the bundled template); a
# ruleset that names a path is authoritative, whether or not that path is
# on disk (existence is the caller's refusal, not this resolver's).


def test_template_scene_absent_from_ruleset_resolves_to_none(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"standard_fps": 24})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["template_scene"] == ""
    assert rules.resolve_template_scene(context) is None


def test_template_scene_absolute_path_is_used_verbatim(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    template = tmp_path / "studio" / "standard.c4d"
    write_rules(scene_dir, {"template_scene": str(template)})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.field_sources["template_scene"] == "project"
    assert rules.resolve_template_scene(context) == os.path.normpath(str(template))


def test_template_scene_relative_path_anchors_on_the_declaring_rules_folder(tmp_path):
    """Not the cwd and not the scene: the folder of the sentinel_rules.json
    that declared it, so moving a whole project folder keeps the path
    valid. The scene lives two levels below the rules file precisely so a
    scene-anchored implementation would land somewhere else."""
    project = tmp_path / "project"
    scene_dir = project / "shots" / "shot010"
    scene_dir.mkdir(parents=True)
    write_rules(project, {"template_scene": "_pipeline/studio_template.c4d"})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert rules.resolve_template_scene(context) == os.path.normpath(
        str(project / "_pipeline" / "studio_template.c4d")
    )


def test_template_scene_nearest_rules_file_anchors_its_own_relative_path(tmp_path):
    """Two rules files in the ancestry: the nearest one wins the key AND
    owns the anchor. A resolver that anchored on the outermost (or on any
    other discovered file) would silently point at a different template."""
    project = tmp_path / "project"
    scene_dir = project / "shots" / "shot010"
    scene_dir.mkdir(parents=True)
    write_rules(project, {"template_scene": "outer/template.c4d"})
    write_rules(scene_dir, {"template_scene": "inner/template.c4d"})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert rules.resolve_template_scene(context) == os.path.normpath(
        str(scene_dir / "inner" / "template.c4d")
    )


def test_template_scene_resolves_even_when_the_file_is_not_on_disk(tmp_path):
    """The resolver does not check existence — that is the caller's refusal.
    If this ever returned None for a missing file, a declared-but-missing
    template would degrade into the silent 'ruleset says nothing' case,
    which is exactly the failure the feature exists to prevent."""
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"template_scene": "nowhere/gone.c4d"})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    resolved = rules.resolve_template_scene(context)
    assert resolved == os.path.normpath(str(scene_dir / "nowhere" / "gone.c4d"))
    assert not os.path.exists(resolved)


def test_malformed_template_scene_rejected_by_name_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {"standard_fps": 24, "template_scene": 42},
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert context.params["template_scene"] == ""
    assert rules.resolve_template_scene(context) is None
    assert any(
        "template_scene" in warning and "path string" in warning
        for warning in context.warnings
    )


def test_list_template_scene_rejected_by_name_but_rest_of_file_applies(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(
        scene_dir,
        {"standard_fps": 24, "template_scene": ["a.c4d", "b.c4d"]},
    )

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert context.params["template_scene"] == ""
    assert any("template_scene" in warning for warning in context.warnings)


def test_blank_template_scene_is_rejected_rather_than_read_as_a_path(tmp_path):
    scene_dir = tmp_path / "project"
    scene_dir.mkdir()
    write_rules(scene_dir, {"standard_fps": 24, "template_scene": "   "})

    rules.invalidate()
    context = rules.resolve_rules(scene_dir / "shot.c4d", {})

    assert context.params["standard_fps"] == 24
    assert rules.resolve_template_scene(context) is None
    assert any("template_scene" in warning for warning in context.warnings)
