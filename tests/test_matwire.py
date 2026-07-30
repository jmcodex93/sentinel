import importlib
import os

import pytest


@pytest.fixture
def matwire(sentinel_module):
    return importlib.import_module("sentinel.matwire")


def _scan(matwire, *names):
    return matwire.scan_texture_sets(list(names))


def test_single_set_full_pbr(matwire):
    out = _scan(
        matwire,
        "plaster_BaseColor.jpg", "plaster_Roughness.jpg", "plaster_Metalness.jpg",
        "plaster_Normal.png", "plaster_Height.exr", "plaster_AO.jpg",
        "plaster_Opacity.png", "plaster_Emission.jpg",
    )
    assert out["ignored"] == []
    assert len(out["sets"]) == 1
    s = out["sets"][0]
    assert s["name"] == "plaster"
    assert set(s["channels"]) == {
        "basecolor", "roughness", "metalness", "normal", "height",
        "ao", "opacity", "emission"}
    assert s["normal_flipy"] is False


def test_suffix_synonyms_and_map_tolerance(matwire):
    out = _scan(
        matwire,
        "wood_albedo.png",          # basecolor
        "wood_rgh.png",             # roughness
        "wood_mtl.png",             # metalness
        "wood_nmap.png",            # normal
        "wood_depth.png",           # height
        "wood_occ.png",             # ao
        "wood_cutout.png",          # opacity
        "wood_emit.png",            # emission
        "brick_RoughnessMap.png",   # glued Map suffix
        "brick_Base_Color Map.png", # space separator + split words
    )
    sets = {s["name"]: s for s in out["sets"]}
    assert set(sets["wood"]["channels"]) == {
        "basecolor", "roughness", "metalness", "normal", "height",
        "ao", "opacity", "emission"}
    assert set(sets["brick"]["channels"]) == {"roughness", "basecolor"}


def test_normal_gl_dx_precedence(matwire):
    # GL wins over DX and over generic; DX-only sets flipy.
    both = _scan(matwire, "a_Normal_GL.png", "a_Normal_DX.png", "a_BaseColor.png")
    s = both["sets"][0]
    assert s["channels"]["normal"] == "a_Normal_GL.png"
    assert s["normal_flipy"] is False
    assert ("a_Normal_DX.png", "dx_superseded") in s["ignored"]

    dx_only = _scan(matwire, "b_NormalDX.png", "b_BaseColor.png")
    s2 = dx_only["sets"][0]
    assert s2["channels"]["normal"] == "b_NormalDX.png"
    assert s2["normal_flipy"] is True


def test_multi_set_grouping_and_res_variants(matwire):
    out = _scan(
        matwire,
        "plaster_A_4k_BaseColor.jpg", "plaster_A_8k_BaseColor.jpg",
        "plaster_A_Roughness.jpg",
        "plaster_B_BaseColor.jpg", "plaster_B_Roughness.jpg",
    )
    sets = {s["name"]: s for s in out["sets"]}
    assert set(sets) == {"plaster_A", "plaster_B"}
    a = sets["plaster_A"]
    assert a["channels"]["basecolor"] == "plaster_A_8k_BaseColor.jpg"  # highest wins
    assert ("plaster_A_4k_BaseColor.jpg", "lower_resolution") in a["ignored"]


def test_no_token_variant_outranks_tokened(matwire):
    # v1.18 Shrink lesson: the original carries NO res token and outranks proxies.
    out = _scan(matwire, "wall_BaseColor.jpg", "wall_2k_BaseColor.jpg",
                "wall_Roughness.jpg")
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "wall_BaseColor.jpg"
    assert ("wall_2k_BaseColor.jpg", "lower_resolution") in s["ignored"]


def test_mixed_casing_groups_into_one_set(matwire):
    # Set identity is case-insensitive; display name keeps first-seen casing.
    out = _scan(matwire, "Rock_Cliff_BaseColor.jpg", "rock_cliff_AO.jpg")
    assert len(out["sets"]) == 1
    s = out["sets"][0]
    assert s["name"] == "Rock_Cliff"
    assert set(s["channels"]) == {"basecolor", "ao"}


def test_trailing_resolution_token_poliigon_pattern(matwire):
    # Poliigon pattern: resolution token AFTER the channel suffix.
    out = _scan(matwire, "plaster_BaseColor_8k.jpg")
    assert out["ignored"] == []
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "plaster_BaseColor_8k.jpg"


def test_trailing_and_pre_token_resolution_compete(matwire):
    # No-token wins regardless of whether the loser's token sits before
    # or after the channel suffix.
    out = _scan(
        matwire,
        "wall_BaseColor.jpg",       # no token -> wins
        "wall_BaseColor_2k.jpg",    # trailing token
        "wall_2k_BaseColor.jpg",    # pre-token
    )
    assert len(out["sets"]) == 1
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "wall_BaseColor.jpg"
    reasons = {f: r for f, r in s["ignored"]}
    assert reasons["wall_BaseColor_2k.jpg"] == "lower_resolution"
    assert reasons["wall_2k_BaseColor.jpg"] == "lower_resolution"


def test_orm_with_trailing_resolution_token(matwire):
    # v1.32.1: packed_orm is a REAL channel — res-token ranking applies.
    out = _scan(matwire, "x_ORM_2k.png")
    assert out["ignored"] == []
    s = out["sets"][0]
    assert s["name"] == "x"
    assert s["channels"]["packed_orm"] == "x_ORM_2k.png"


def test_spec_gloss_precedence(matwire):
    # PBR present -> spec/gloss suppressed per-set.
    pbr = _scan(matwire, "m_BaseColor.jpg", "m_Roughness.jpg",
                "m_Specular.jpg", "m_Glossiness.jpg")
    s = pbr["sets"][0]
    assert "specular" not in s["channels"] and "glossiness" not in s["channels"]
    reasons = {f: r for f, r in s["ignored"]}
    assert reasons["m_Specular.jpg"] == "pbr_wins"
    assert reasons["m_Glossiness.jpg"] == "pbr_wins"
    # Legacy-only set keeps them.
    legacy = _scan(matwire, "n_Diffuse.jpg", "n_Specular.jpg", "n_Glossiness.jpg")
    assert set(legacy["sets"][0]["channels"]) == {"basecolor", "specular", "glossiness"}


def test_orm_and_unknown_and_extension(matwire):
    # v1.32.1: the ORM file joins its set's channels (grouped by root)
    # instead of landing in global ignored.
    out = _scan(matwire, "x_ORM.png", "x_BaseColor.png", "readme.txt", "x_thumb.png")
    reasons = {f: r for f, r in out["ignored"]}
    assert reasons["readme.txt"] == "bad_extension"
    assert reasons["x_thumb.png"] == "no_channel"
    assert set(out["sets"][0]["channels"]) == {"basecolor", "packed_orm"}
    assert out["sets"][0]["channels"]["packed_orm"] == "x_ORM.png"


def test_duplicate_channel_first_wins(matwire):
    out = _scan(matwire, "y_col.png", "y_diffuse.png", "y_rough.png")
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "y_col.png"
    assert ("y_diffuse.png", "duplicate_channel") in s["ignored"]


def test_glued_stem_never_false_positives(matwire):
    # Separator required: "protocol" must NOT end-match "col" -> basecolor.
    out = _scan(matwire, "protocol.png", "gunmetal.png")
    reasons = {f: r for f, r in out["ignored"]}
    assert reasons["protocol.png"] == "no_channel"
    assert reasons["gunmetal.png"] == "no_channel"


def test_rootless_pack_groups_under_default_root(matwire):
    out = matwire.scan_texture_sets(
        ["albedo.png", "roughness.png", "normal.png"], default_root="plaster")
    assert len(out["sets"]) == 1
    s = out["sets"][0]
    assert s["name"] == "plaster"
    assert set(s["channels"]) == {"basecolor", "roughness", "normal"}


def test_channel_colorspace_single_source(matwire):
    assert matwire.channel_colorspace("basecolor") == "srgb"
    assert matwire.channel_colorspace("emission") == "srgb"
    for ch in ("roughness", "metalness", "normal", "height", "ao",
               "opacity", "specular", "glossiness"):
        assert matwire.channel_colorspace(ch) == "raw"


def test_dedupe_names(matwire):
    assert matwire.dedupe_names(["wood", "wood", "Plaster"], ["plaster"]) == [
        "wood", "wood_02", "Plaster_02"]


class TestCanonicalChannels:
    def test_contains_every_table_channel(self, matwire):
        assert {"packed_orm", "normal_gl", "normal_dx", "normal", "basecolor",
                "roughness", "metalness", "height", "ao", "opacity",
                "emission", "specular", "glossiness"} == set(
            matwire.CANONICAL_CHANNELS)

    def test_packed_orm_colorspace_is_raw(self, matwire):
        assert matwire.channel_colorspace("packed_orm") == "raw"


class TestValidateExtraSuffixes:
    def test_valid_and_rejected_mix_per_key(self, matwire):
        valid, rejected = matwire.validate_extra_suffixes({
            "basecolor": [" Col_Especial ", "ALB"],
            "nope_channel": ["x"],          # unknown channel key
            "roughness": "rugosidad",       # not a list
            "metalness": ["met2", 7],       # non-str item
            "ao": ["", "  "],               # empty entries dropped -> key dropped
            "height": ["alto"],
        })
        assert valid == {"basecolor": ["col_especial", "alb"],
                         "height": ["alto"]}
        assert sorted(rejected) == ["ao", "metalness", "nope_channel",
                                    "roughness"]

    def test_non_dict_yields_nothing(self, matwire):
        valid, rejected = matwire.validate_extra_suffixes(None)
        assert valid == {} and rejected == []


class TestExtraSuffixes:
    def test_extras_extend_embedded_tables(self, matwire):
        out = matwire.scan_texture_sets(
            ["muro_col_especial.png", "muro_Roughness.png"],
            extra_suffixes={"basecolor": ["col_especial"]})
        s = out["sets"][0]
        assert s["name"] == "muro"
        assert s["channels"]["basecolor"] == "muro_col_especial.png"
        assert s["channels"]["roughness"] == "muro_Roughness.png"

    def test_embedded_synonyms_still_work_with_extras(self, matwire):
        out = matwire.scan_texture_sets(
            ["wood_albedo.png"], extra_suffixes={"basecolor": ["col_especial"]})
        assert out["sets"][0]["channels"]["basecolor"] == "wood_albedo.png"

    def test_without_extras_custom_suffix_stays_unknown(self, matwire):
        out = matwire.scan_texture_sets(["muro_col_especial.png"])
        assert out["sets"] == []
        assert ("muro_col_especial.png", "no_channel") in out["ignored"]


class TestPackedOrmChannel:
    def test_orm_joins_set_with_basecolor_sibling(self, matwire):
        out = _scan(matwire, "rock_BaseColor.jpg", "rock_ORM.png")
        s = out["sets"][0]
        assert set(s["channels"]) == {"basecolor", "packed_orm"}
        assert out["ignored"] == []

    def test_rootless_orm_groups_under_default_root(self, matwire):
        out = matwire.scan_texture_sets(["orm.png"], default_root="plaster")
        s = out["sets"][0]
        assert s["name"] == "plaster"
        assert s["channels"]["packed_orm"] == "orm.png"

    def test_second_orm_is_duplicate_channel(self, matwire):
        out = _scan(matwire, "z_ORM.png", "z_ARM.png", "z_BaseColor.png")
        s = out["sets"][0]
        assert s["channels"]["packed_orm"] == "z_ORM.png"
        assert ("z_ARM.png", "duplicate_channel") in s["ignored"]

    def test_res_token_ranking_applies_to_orm(self, matwire):
        out = _scan(matwire, "x_ORM_2k.png", "x_ORM.png")
        s = out["sets"][0]
        assert s["channels"]["packed_orm"] == "x_ORM.png"
        assert ("x_ORM_2k.png", "lower_resolution") in s["ignored"]

    def test_orm_never_suppresses_dedicated_maps(self, matwire):
        # Engine level: packed_orm coexists with dedicated roughness /
        # metalness (the WRITER applies dedicated-wins per splitter output).
        out = _scan(matwire, "m_ORM.png", "m_Roughness.png", "m_Metalness.png")
        s = out["sets"][0]
        assert set(s["channels"]) == {"packed_orm", "roughness", "metalness"}
        assert s["ignored"] == []


class TestLeftoverHints:
    def test_no_channel_files_appear_in_leftover_hints(self, matwire):
        out = _scan(matwire, "x_BaseColor.png", "x_thumb.png",
                    "Plaster A-preview.png", "readme.txt")
        assert out["leftover_hints"] == {
            "x_thumb.png": "x_thumb",
            "Plaster A-preview.png": "plaster_a_preview",
        }
        # ignored keeps the 2-tuple shape everywhere
        assert ("x_thumb.png", "no_channel") in out["ignored"]
        assert all(len(row) == 2 for row in out["ignored"])

    def test_clean_scan_has_empty_hints(self, matwire):
        out = _scan(matwire, "x_BaseColor.png")
        assert out["leftover_hints"] == {}


class TestAssignLeftovers:
    def test_prefix_match_longest_name_wins(self, matwire):
        result = matwire.assign_leftovers(
            {"plaster_a_thumb.png": "plaster_a_thumb",
             "plaster_readme.png": "plaster_readme",
             "loose.png": "loose"},
            ["plaster", "plaster_a", "wood"])
        assert result == [
            {"file": "plaster_a_thumb.png", "set": "plaster_a"},
            {"file": "plaster_readme.png", "set": "plaster"},
            {"file": "loose.png", "set": None},
        ]

    def test_exact_hint_equals_name(self, matwire):
        result = matwire.assign_leftovers({"wood.txt": "wood"}, ["Wood"])
        assert result == [{"file": "wood.txt", "set": "Wood"}]

    def test_no_partial_word_match(self, matwire):
        # "woodpecker" must not match set "wood" (separator required).
        result = matwire.assign_leftovers(
            {"woodpecker.png": "woodpecker"}, ["wood"])
        assert result == [{"file": "woodpecker.png", "set": None}]

    def test_empty_inputs(self, matwire):
        assert matwire.assign_leftovers({}, ["a"]) == []
        assert matwire.assign_leftovers(None, None) == []


class TestPreviewPayload:
    """Pure preview shaping (Task 3): scan result -> SPA payload with
    colorspace-annotated channel rows + defaults deduped vs the Material
    Manager. JSON-friendly: tuples become lists."""

    def test_shapes_channels_with_colorspace(self, matwire):
        scan = matwire.scan_texture_sets(
            ["plaster_BaseColor.jpg", "plaster_Roughness.jpg",
             "plaster_NormalDX.png", "notes.txt"])
        payload = matwire.preview_payload(scan, [])
        assert len(payload["sets"]) == 1
        s = payload["sets"][0]
        assert s["name"] == "plaster"
        assert s["normal_flipy"] is True  # DX-only set
        rows = {r["channel"]: r for r in s["channels"]}
        assert rows["basecolor"]["file"] == "plaster_BaseColor.jpg"
        assert rows["basecolor"]["colorspace"] == "srgb"
        assert rows["roughness"]["colorspace"] == "raw"
        assert rows["normal"]["colorspace"] == "raw"
        assert payload["ignored"] == [["notes.txt", "bad_extension"]]
        assert payload["names"] == ["plaster"]

    def test_names_deduped_against_existing(self, matwire):
        scan = matwire.scan_texture_sets(
            ["wood_col.png", "Plaster_col.png"])
        payload = matwire.preview_payload(scan, ["plaster", "wood"])
        assert payload["names"] == ["wood_02", "Plaster_02"]

    def test_set_ignored_rows_are_lists(self, matwire):
        scan = matwire.scan_texture_sets(
            ["y_col.png", "y_diffuse.png"])
        payload = matwire.preview_payload(scan, [])
        assert ["y_diffuse.png", "duplicate_channel"] in payload["sets"][0]["ignored"]


class TestBuildDescription:
    """matwire_c4d.build_description (pure dict assembly, no c4d calls) —
    pins the writer's GraphDescription against spike drift. Colorspaces
    must come from matwire.channel_colorspace (the single source), never
    a second per-branch literal table."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def _tex_set(self, matwire, **extra):
        scan = matwire.scan_texture_sets([
            "plaster_BaseColor.jpg", "plaster_Roughness.jpg",
            "plaster_NormalDX.png", "plaster_Height.exr",
            "plaster_Emission.jpg",
        ])
        s = scan["sets"][0]
        s.update(extra)
        return s

    def test_full_set_desc_shape(self, matwire, matwire_c4d):
        tex_set = self._tex_set(matwire)
        desc, ao_desc = matwire_c4d.build_description("/tex", tex_set)

        RS = matwire_c4d._RS_CORE
        sm = "#<" + RS + "standardmaterial."
        material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        assert material["$type"] == "#" + RS + "standardmaterial"

        # base_color: srgb, per channel_colorspace("basecolor") == "srgb"
        base = material[sm + "base_color"]
        assert base["#<" + RS + "texturesampler.tex0/path"] == os.path.join(
            "/tex", "plaster_BaseColor.jpg")
        assert base["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("basecolor")]
        assert matwire.channel_colorspace("basecolor") == "srgb"

        # roughness: raw
        rough = material[sm + "refl_roughness"]
        assert rough["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("roughness")]
        assert matwire.channel_colorspace("roughness") == "raw"

        # normal: bump chain, raw, inputtype 1 (tangent-space); flipy is
        # ALWAYS explicit (hardening: never depend on node defaults) —
        # True here (DX-only set)
        bump = material[sm + "bump_input"]
        assert bump["$type"] == "#" + RS + "bumpmap"
        assert bump["#<" + RS + "bumpmap.inputtype"] == 1
        assert bump["#<" + RS + "bumpmap.flipy"] is True
        normal_sampler = bump["#<" + RS + "bumpmap.input"]
        assert normal_sampler["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("normal")]
        assert matwire.channel_colorspace("normal") == "raw"

        # height -> output displacement, raw
        disp = desc["#<" + matwire_c4d._RS_OUTPUT + ".displacement"]
        assert disp["$type"] == "#" + RS + "displacement"
        disp_sampler = disp["#<" + RS + "displacement.texmap"]
        assert disp_sampler["#<" + RS + "texturesampler.tex0/path"] == \
            os.path.join("/tex", "plaster_Height.exr")
        assert disp_sampler["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("height")]
        assert matwire.channel_colorspace("height") == "raw"

        # emission: srgb color + literal weight 1.0
        assert material[sm + "emission_color"][
            "#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("emission")]
        assert matwire.channel_colorspace("emission") == "srgb"
        assert material[sm + "emission_weight"] == 1.0

        assert ao_desc is None

    def test_gl_normal_writes_explicit_flipy_false(self, matwire, matwire_c4d):
        # Hardening: flipy is ALWAYS written explicitly (never depend on
        # node defaults — colorspace principle). NB the real RS default is
        # false; the suspected live bug was a maxon.Bool truthiness read
        # artifact in the verification harness.
        scan = matwire.scan_texture_sets(["a_BaseColor.png", "a_Normal_GL.png"])
        desc, _ao = matwire_c4d.build_description("/f", scan["sets"][0])
        RS = matwire_c4d._RS_CORE
        material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        bump = material["#<" + RS + "standardmaterial.bump_input"]
        assert bump["#<" + RS + "bumpmap.flipy"] is False

    def test_gloss_only_set_no_roughness_key_collision(self, matwire, matwire_c4d):
        scan = matwire.scan_texture_sets(
            ["metal_BaseColor.jpg", "metal_Gloss.jpg", "metal_AO.png"])
        tex_set = scan["sets"][0]
        desc, ao_desc = matwire_c4d.build_description("/tex", tex_set)

        RS = matwire_c4d._RS_CORE
        sm = "#<" + RS + "standardmaterial."
        material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]

        gloss = material[sm + "refl_roughness"]
        assert gloss["#<" + RS + "texturesampler.tex0/path"] == \
            os.path.join("/tex", "metal_Gloss.jpg")
        assert gloss["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("glossiness")]
        assert matwire.channel_colorspace("glossiness") == "raw"
        assert material[sm + "refl_isglossiness"] is True

        # AO is a separate isolated sampler (§5), always raw.
        assert ao_desc["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("ao")]
        assert matwire.channel_colorspace("ao") == "raw"


class TestOrmPlan:
    """matwire_c4d.build_orm_plan — the packed_orm splitter branch (pure
    dict/pair assembly). Per the v1.32.1 mini-spike, ONE splitter feeding
    TWO ports is NOT expressible declaratively (dict nesting duplicates the
    node, no $ref mechanism), so the plan is a splitter desc for a second
    isolated ApplyDescription PLUS imperative connect pairs."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def _plan(self, matwire, matwire_c4d, *names):
        scan = matwire.scan_texture_sets(list(names))
        return matwire_c4d.build_orm_plan("/tex", scan["sets"][0])

    def test_orm_alone_connects_both_outputs(self, matwire, matwire_c4d):
        plan = self._plan(matwire, matwire_c4d, "x_BaseColor.png", "x_ORM.png")
        RS = matwire_c4d._RS_CORE
        desc = plan["splitter_desc"]
        assert desc["$type"] == "#" + RS + "rscolorsplitter"
        samp = desc["#<" + RS + "rscolorsplitter.input"]
        assert samp["#<" + RS + "texturesampler.tex0/path"] == os.path.join(
            "/tex", "x_ORM.png")
        # RAW via the single colorspace source (channel_colorspace)
        assert samp["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("packed_orm")]
        assert matwire.channel_colorspace("packed_orm") == "raw"
        assert plan["connects"] == [
            (RS + "rscolorsplitter.outg", RS + "standardmaterial.refl_roughness"),
            (RS + "rscolorsplitter.outb", RS + "standardmaterial.metalness"),
        ]
        # outr (AO) is NEVER wired
        assert not any("outr" in out for out, _ in plan["connects"])

    def test_dedicated_roughness_frees_outg(self, matwire, matwire_c4d):
        plan = self._plan(matwire, matwire_c4d,
                          "x_Roughness.png", "x_ORM.png")
        RS = matwire_c4d._RS_CORE
        assert plan["connects"] == [
            (RS + "rscolorsplitter.outb", RS + "standardmaterial.metalness")]

    def test_glossiness_counts_as_dedicated_roughness(self, matwire, matwire_c4d):
        # glossiness occupies refl_roughness (+ refl_isglossiness) — outg
        # must not fight it.
        plan = self._plan(matwire, matwire_c4d, "x_Gloss.png", "x_ORM.png")
        RS = matwire_c4d._RS_CORE
        assert plan["connects"] == [
            (RS + "rscolorsplitter.outb", RS + "standardmaterial.metalness")]

    def test_dedicated_metalness_frees_outb(self, matwire, matwire_c4d):
        plan = self._plan(matwire, matwire_c4d,
                          "x_Metalness.png", "x_ORM.png")
        RS = matwire_c4d._RS_CORE
        assert plan["connects"] == [
            (RS + "rscolorsplitter.outg", RS + "standardmaterial.refl_roughness")]

    def test_both_dedicated_skips_splitter_entirely(self, matwire, matwire_c4d):
        # Judged: with both dedicated maps the splitter would contribute
        # NOTHING (outr never wired) — do not create a dead node.
        plan = self._plan(matwire, matwire_c4d, "x_Roughness.png",
                          "x_Metalness.png", "x_ORM.png")
        assert plan is None

    def test_no_orm_channel_plan_is_none(self, matwire, matwire_c4d):
        plan = self._plan(matwire, matwire_c4d,
                          "x_BaseColor.png", "x_Roughness.png")
        assert plan is None

    def test_orm_does_not_leak_into_build_description(self, matwire, matwire_c4d):
        # The main description never references the ORM file or splitter —
        # they live exclusively in the plan (second apply + connects).
        scan = matwire.scan_texture_sets(["x_BaseColor.png", "x_ORM.png"])
        desc, ao = matwire_c4d.build_description("/tex", scan["sets"][0])
        assert "x_ORM.png" not in repr(desc)
        assert "rscolorsplitter" not in repr(desc)
        assert ao is None

    def test_relative_subdir_path_joined_with_os_sep(self, matwire, matwire_c4d):
        # Recursive scans deliver relative paths with "/" — the writer
        # normalizes them through os.path.join.
        scan = matwire.scan_texture_sets(["x_ORM.png"])
        s = scan["sets"][0]
        s["channels"]["packed_orm"] = "sub/dir/x_ORM.png"
        plan = matwire_c4d.build_orm_plan("/tex", s)
        RS = matwire_c4d._RS_CORE
        assert plan["splitter_desc"]["#<" + RS + "rscolorsplitter.input"][
            "#<" + RS + "texturesampler.tex0/path"] == os.path.join(
                "/tex", "sub", "dir", "x_ORM.png")

    def test_splitter_has_a_layout_column(self, matwire_c4d):
        # Intermediary node between samplers (-600) and material (0):
        # shares the bump/displacement column (rows are keyed by column,
        # so cohabitation never stacks).
        assert matwire_c4d._LAYOUT_COLS["rscolorsplitter"] == \
            matwire_c4d._LAYOUT_COLS["bumpmap"]


class TestLeftoverDescriptions:
    """matwire_c4d.build_leftover_descriptions — unconnected RAW samplers
    (AO pattern: each is an isolated second ApplyDescription scope)."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def test_samplers_raw_and_isolated_shape(self, matwire_c4d):
        descs = matwire_c4d.build_leftover_descriptions(
            "/tex", ["readme_preview.png", "sub/thumb.jpg"])
        RS = matwire_c4d._RS_CORE
        assert len(descs) == 2
        for d in descs:
            assert d["$type"] == "#" + RS + "texturesampler"
            assert d["#<" + RS + "texturesampler.tex0/colorspace"] == \
                matwire_c4d._CS_RAW
        assert descs[0]["#<" + RS + "texturesampler.tex0/path"] == \
            os.path.join("/tex", "readme_preview.png")
        assert descs[1]["#<" + RS + "texturesampler.tex0/path"] == \
            os.path.join("/tex", "sub", "thumb.jpg")

    def test_empty_and_none_inputs(self, matwire_c4d):
        assert matwire_c4d.build_leftover_descriptions("/tex", []) == []
        assert matwire_c4d.build_leftover_descriptions("/tex", None) == []
