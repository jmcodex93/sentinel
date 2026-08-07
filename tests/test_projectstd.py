"""Pure-engine tests for the project standard (v1.37). No c4d import."""
import os

from sentinel import projectstd


class TestDeriveShotPattern:
    def test_shot_in_named_folder(self):
        pat = projectstd.derive_shot_pattern(
            "/prj/shots/SH010/SH010_v012.c4d", "/prj")
        assert pat == "shots/{shot}/{shot}_v001.c4d"

    def test_shot_at_project_root(self):
        pat = projectstd.derive_shot_pattern("/prj/SH010_v012_TR.c4d", "/prj")
        assert pat == "{shot}_v001.c4d"

    def test_folder_not_named_after_shot_is_kept_verbatim(self):
        pat = projectstd.derive_shot_pattern(
            "/prj/escenas/SH010_v012.c4d", "/prj")
        assert pat == "escenas/{shot}_v001.c4d"

    def test_scene_outside_project_returns_none(self):
        assert projectstd.derive_shot_pattern("/otro/SH010_v001.c4d", "/prj") is None

    def test_unversioned_filename_still_derives(self):
        pat = projectstd.derive_shot_pattern("/prj/shots/master/master.c4d", "/prj")
        assert pat == "shots/{shot}/{shot}_v001.c4d"


class TestShotDestination:
    def test_pattern_expansion(self):
        dest = projectstd.shot_destination(
            "shots/{shot}/{shot}_v001.c4d", "/prj", "SH020")
        assert dest == os.path.join("/prj", "shots", "SH020", "SH020_v001.c4d")

    def test_empty_pattern_places_at_project_root(self):
        """An absent shot_pattern places the shot at the project root — no
        invented folder structure (spec: out of scope), no refusal either
        (a missing pattern is missing placement info, not a wrong standard)."""
        dest = projectstd.shot_destination("", "/prj", "SH020")
        assert dest == os.path.join("/prj", "SH020_v001.c4d")


class TestValidShotName:
    def test_plain_name_ok(self):
        assert projectstd.valid_shot_name("SH020")

    def test_empty_and_separators_rejected(self):
        assert not projectstd.valid_shot_name("")
        assert not projectstd.valid_shot_name("a/b")
        assert not projectstd.valid_shot_name("a\\b")
        assert not projectstd.valid_shot_name("  ")

    def test_windows_hostile_names_rejected(self):
        """Same hygiene as shot_pattern segments (rules.valid_path_segment):
        a shot named AUX or 'SH01?' would create an impossible folder on a
        Windows station."""
        assert not projectstd.valid_shot_name("AUX")
        assert not projectstd.valid_shot_name("SH01?")
        assert not projectstd.valid_shot_name("SH01.")
        assert not projectstd.valid_shot_name("..")


class TestDeriveRulesPayload:
    def test_payload_shape(self):
        payload = projectstd.derive_rules_payload(
            fps=25, start_frame=1001,
            preset_names=["previz", "render"],
            pattern="shots/{shot}/{shot}_v001.c4d",
            author="Javier", published_at="2026-08-07 12:00:00")
        assert payload == {
            "standard_fps": 25,
            "start_frame": 1001,
            "approved_presets": ["previz", "render"],
            "required_presets": ["previz", "render"],
            "template_scene": "sentinel_standard.c4d",
            "shot_pattern": "shots/{shot}/{shot}_v001.c4d",
            "published": {"by": "Javier", "at": "2026-08-07 12:00:00"},
        }

    def test_no_pattern_key_when_underivable(self):
        payload = projectstd.derive_rules_payload(
            fps=25, start_frame=1001, preset_names=[],
            pattern=None, author="", published_at="t")
        assert "shot_pattern" not in payload


class TestMergeRules:
    def test_derived_wins_manual_keys_survive(self):
        existing = {"standard_fps": 24, "gates_enabled": True,
                    "safe_area_insets": {"9x16": [1, 2, 3, 4]}}
        derived = {"standard_fps": 25, "template_scene": "sentinel_standard.c4d"}
        merged = projectstd.merge_rules(existing, derived)
        assert merged["standard_fps"] == 25
        assert merged["gates_enabled"] is True
        assert merged["safe_area_insets"] == {"9x16": [1, 2, 3, 4]}

    def test_none_existing_is_just_derived(self):
        derived = {"standard_fps": 25}
        assert projectstd.merge_rules(None, derived) == derived


class TestRepublishDiff:
    def test_first_publish_has_no_diff(self):
        assert projectstd.republish_diff(None, {"standard_fps": 25}) == []

    def test_scalar_change_is_named(self):
        lines = projectstd.republish_diff(
            {"standard_fps": 25}, {"standard_fps": 24})
        assert lines == ["fps: 25 → 24"]

    def test_preset_add_remove_named(self):
        lines = projectstd.republish_diff(
            {"required_presets": ["previz", "stills"]},
            {"required_presets": ["previz", "cliente_9x16"],
             "approved_presets": ["previz", "cliente_9x16"]})
        assert any("+cliente_9x16" in l for l in lines)
        assert any("-stills" in l for l in lines)

    def test_unchanged_keys_produce_no_lines(self):
        same = {"standard_fps": 25, "required_presets": ["a"]}
        assert projectstd.republish_diff(dict(same), dict(same)) == []

    def test_template_replacement_always_flagged_when_existing_declares_one(self):
        """Republish overwrites sentinel_standard.c4d on disk even when the
        key text does not change — the supervisor must hear it."""
        lines = projectstd.republish_diff(
            {"template_scene": "sentinel_standard.c4d"},
            {"template_scene": "sentinel_standard.c4d"})
        assert lines == ["the standard scene file will be replaced"]
