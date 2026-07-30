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

    def test_ao_row_carries_destination_from_single_source(self, matwire):
        """v1.33: the AO row says where the AO ACTUALLY lands, straight from
        ``ao_destination`` — the same function the writer decides from (the
        ``contributes`` discipline)."""
        scan = matwire.scan_texture_sets(
            ["rock_AO.png", "rock_BaseColor.png"])
        off = matwire.preview_payload(scan, [])
        rows = {r["channel"]: r for r in off["sets"][0]["channels"]}
        assert rows["ao"]["destination"] == "unconnected"
        assert "destination" not in rows["basecolor"]  # AO row only
        on = matwire.preview_payload(scan, [], multiply_ao=True)
        rows_on = {r["channel"]: r for r in on["sets"][0]["channels"]}
        assert rows_on["ao"]["destination"] == "base_color_multiply"

    def test_ao_row_destination_without_basecolor_stays_unconnected(self, matwire):
        """AO-only set: nothing to multiply INTO, so the row must not
        promise a wiring the writer won't make."""
        scan = matwire.scan_texture_sets(["rock_AO.png", "rock_Roughness.png"])
        payload = matwire.preview_payload(scan, [], multiply_ao=True)
        rows = {r["channel"]: r for r in payload["sets"][0]["channels"]}
        assert rows["ao"]["destination"] == "unconnected"


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

        # base_color: srgb, per channel_colorspace("basecolor") == "srgb".
        # v1.33 CONTRACT CHANGE: an identity Color Correct is ALWAYS
        # interposed (spec 2026-07-30), so the sampler now hangs off
        # rscolorcorrection.input instead of standardmaterial.base_color.
        correction = material[sm + "base_color"]
        assert correction["$type"] == "#" + RS + "rscolorcorrection"
        base = correction["#<" + RS + "rscolorcorrection.input"]
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

    def test_both_dedicated_emits_unconnected_orm_sampler(self, matwire, matwire_c4d):
        # Review M1 (v1.32.1): with roughness AND metalness dedicated, the
        # splitter would contribute nothing (outr/AO never wires) — but the
        # recognized ORM FILE must stay VISIBLE in the graph (AO/leftover
        # philosophy: files never vanish silently). The plan degrades to a
        # bare unconnected RAW sampler with zero connects.
        plan = self._plan(matwire, matwire_c4d, "x_BaseColor.png", "x_ORM.png",
                          "x_Roughness.png", "x_Metalness.png")
        RS = matwire_c4d._RS_CORE
        assert plan is not None
        assert plan["connects"] == []
        desc = plan["splitter_desc"]
        assert desc["$type"] == "#" + RS + "texturesampler"  # sampler, no splitter
        assert desc["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("packed_orm")]

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


class TestDirectoryResolutionRanking:
    """Review I1: the recursive lister (v1.32.1) delivers multi-res packs as
    `1K/albedo.png` / `4K/albedo.png` — IDENTICAL filenames, so ranking from
    the name alone collapsed them into one arbitrary winner. Directory
    segments now supply the rank when the filename carries no token."""

    def test_subfolder_pack_ranks_by_directory(self, matwire):
        out = _scan(
            matwire,
            "1K/albedo.png", "1K/roughness.png",
            "4K/albedo.png", "4K/roughness.png")
        assert len(out["sets"]) == 1
        s = out["sets"][0]
        assert s["channels"]["basecolor"] == "4K/albedo.png"
        assert s["channels"]["roughness"] == "4K/roughness.png"
        ignored = dict(s["ignored"])
        # The losers are LOWER RESOLUTION, not indistinguishable duplicates.
        assert ignored["1K/albedo.png"] == "lower_resolution"
        assert ignored["1K/roughness.png"] == "lower_resolution"

    def test_deepest_directory_token_wins(self, matwire):
        out = _scan(matwire, "8K/rock/2K/albedo.png", "8K/rock/4K/albedo.png")
        s = out["sets"][0]
        assert s["channels"]["basecolor"] == "8K/rock/4K/albedo.png"

    def test_filename_token_beats_contradicting_directory_token(self, matwire):
        # `1K/x_BaseColor_8k.png` really is the 8K map: the name wins.
        out = _scan(matwire,
                    "1K/x_BaseColor_8k.png", "8K/x_BaseColor_2k.png")
        s = out["sets"][0]
        assert s["channels"]["basecolor"] == "1K/x_BaseColor_8k.png"
        assert ("8K/x_BaseColor_2k.png", "lower_resolution") in s["ignored"]

    def test_untokened_directory_leaves_rank_untouched(self, matwire):
        # A bare (no-token) file still outranks every explicit px — Shrink
        # lesson, unchanged by the directory fallback.
        out = _scan(matwire, "tex/x_BaseColor.png", "4K/x_BaseColor.png")
        s = out["sets"][0]
        assert s["channels"]["basecolor"] == "tex/x_BaseColor.png"
        assert ("4K/x_BaseColor.png", "lower_resolution") in s["ignored"]

    def test_flat_pack_is_byte_identical(self, matwire):
        # No directory part anywhere: exactly the v1.32 behavior.
        flat = _scan(matwire, "x_BaseColor.png", "x_Roughness.png",
                     "x_BaseColor_2k.png")
        s = flat["sets"][0]
        assert s["channels"]["basecolor"] == "x_BaseColor.png"
        assert ("x_BaseColor_2k.png", "lower_resolution") in s["ignored"]
        assert matwire._dir_px("x_BaseColor.png") is None

    def test_dir_px_helper_edges(self, matwire):
        assert matwire._dir_px("4K/a.png") == 4096
        assert matwire._dir_px("back4k/a.png") is None  # embedded, no boundary
        assert matwire._dir_px("a.png") is None
        assert matwire._dir_px("") is None


class TestOrmContributions:
    """Review I2: ONE source for what the packed ORM actually feeds — the
    preview note and the writer's connect pairs read the same function."""

    def test_no_dedicated_maps_feeds_both(self, matwire):
        assert matwire.orm_contributions(
            {"packed_orm": "x_ORM.png", "basecolor": "x_col.png"}) == \
            ["roughness", "metalness"]

    def test_dedicated_roughness_leaves_metalness_only(self, matwire):
        assert matwire.orm_contributions(
            {"packed_orm": "x.png", "roughness": "r.png"}) == ["metalness"]

    def test_glossiness_also_occupies_refl_roughness(self, matwire):
        assert matwire.orm_contributions(
            {"packed_orm": "x.png", "glossiness": "g.png"}) == ["metalness"]

    def test_dedicated_metalness_leaves_roughness_only(self, matwire):
        assert matwire.orm_contributions(
            {"packed_orm": "x.png", "metalness": "m.png"}) == ["roughness"]

    def test_both_dedicated_contributes_nothing(self, matwire):
        assert matwire.orm_contributions(
            {"packed_orm": "x.png", "roughness": "r.png",
             "metalness": "m.png"}) == []

    def test_no_orm_or_empty(self, matwire):
        assert matwire.orm_contributions({"basecolor": "c.png"}) == []
        assert matwire.orm_contributions(None) == []

    def test_writer_connects_follow_the_same_source(self, sentinel_module, matwire):
        matwire_c4d = importlib.import_module("sentinel.matwire_c4d")
        channels = {"packed_orm": "x_ORM.png", "roughness": "x_r.png"}
        plan = matwire_c4d.build_orm_plan("/tex", {"channels": channels})
        assert matwire.orm_contributions(channels) == ["metalness"]
        assert [out for out, _in in plan["connects"]] == \
            [matwire_c4d._RS_CORE + "rscolorsplitter.outb"]

    def test_preview_row_carries_contributes(self, matwire):
        scan = matwire.scan_texture_sets(
            ["rock_ORM.png", "rock_BaseColor.png", "rock_Metalness.png"])
        payload = matwire.preview_payload(scan, [])
        rows = {r["channel"]: r for r in payload["sets"][0]["channels"]}
        assert rows["packed_orm"]["contributes"] == ["roughness"]
        # Only the ORM row carries the field — other channels stay clean.
        assert "contributes" not in rows["basecolor"]

    def test_preview_row_contributes_empty_when_both_dedicated(self, matwire):
        scan = matwire.scan_texture_sets(
            ["rock_ORM.png", "rock_Roughness.png", "rock_Metalness.png"])
        payload = matwire.preview_payload(scan, [])
        rows = {r["channel"]: r for r in payload["sets"][0]["channels"]}
        assert rows["packed_orm"]["contributes"] == []


class TestKindFromAssetid:
    """Review M4: the assetid parse that shipped broken since v1.32 (every
    material stacked in column 0.0) finally has a pin — BOTH read shapes."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def test_maxon_pair_str_form(self, matwire_c4d):
        # What node.GetValue(assetid) really returns, str()'d.
        value = "(com.redshift3d.redshift4c4d.nodes.core.texturesampler,)"
        assert matwire_c4d._kind_from_assetid(value) == "texturesampler"

    def test_plain_id_string_form(self, matwire_c4d):
        value = matwire_c4d._RS_CORE + "standardmaterial"
        assert matwire_c4d._kind_from_assetid(value) == "standardmaterial"

    def test_parsed_kinds_hit_the_layout_columns(self, matwire_c4d):
        for kind in matwire_c4d._LAYOUT_COLS:
            pair = "(" + matwire_c4d._RS_CORE + kind + ",)"
            assert matwire_c4d._kind_from_assetid(pair) == kind

    def test_empty_and_none(self, matwire_c4d):
        assert matwire_c4d._kind_from_assetid(None) == ""
        assert matwire_c4d._kind_from_assetid("") == ""


class _OrderRecordingDoc:
    """Doc fake recording the interleaving of insertion vs graph work."""

    def __init__(self, log):
        self._log = log
        self.undo_operations = []

    def InsertMaterial(self, mat):
        self._log.append("InsertMaterial")

    def AddUndo(self, undo_type, target):
        self._log.append(("AddUndo", undo_type))
        self.undo_operations.append((undo_type, target))


class TestCreateMaterialOrdering:
    """v1.32.1 live-caught: graph transactions on an ALREADY-INSERTED
    material each become their own document undo step, so a batch of >1
    material needed 4+ Cmd+Z. Root fix = build the WHOLE graph on the
    off-document material and insert LAST. These pin that ordering (and its
    consequence for the failure path) without a real C4D."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def _install_fakes(self, matwire_c4d, monkeypatch, log, fail_on=None):
        class _FakeMat:
            def SetName(self, name):
                log.append("SetName")

        class _FakeGraphDescription:
            @staticmethod
            def GetGraph(mat, nodeSpaceId=None):
                log.append("GetGraph")
                return "graph"

            @staticmethod
            def ApplyDescription(graph, desc):
                log.append("ApplyDescription")
                if fail_on == "apply":
                    raise RuntimeError("apply boom")

        fake_maxon = type("_M", (), {
            "GraphDescription": _FakeGraphDescription,
            "NodeSpaceIdentifiers": type("_N", (), {"RedshiftMaterial": 1}),
        })
        monkeypatch.setattr(matwire_c4d, "maxon", fake_maxon)
        monkeypatch.setattr(matwire_c4d.c4d, "BaseMaterial",
                            lambda _type: _FakeMat())
        monkeypatch.setattr(
            matwire_c4d, "_layout_and_title_nodes",
            lambda graph, titles=None: log.append("_layout_and_title_nodes"))

    def test_graph_is_complete_before_insertion(self, matwire_c4d, monkeypatch):
        log = []
        self._install_fakes(matwire_c4d, monkeypatch, log)
        doc = _OrderRecordingDoc(log)
        tex_set = {"name": "plaster", "channels": {"basecolor": "c.png"},
                   "normal_flipy": False}
        out = matwire_c4d.create_material_for_set(doc, "/tex", tex_set, "plaster")
        assert out["ok"] is True
        insert_at = log.index("InsertMaterial")
        # EVERY graph call happens before the document ever sees the material.
        assert log.index("GetGraph") < insert_at
        assert log.index("ApplyDescription") < insert_at
        assert log.index("_layout_and_title_nodes") < insert_at
        # ...and the only document record is the insertion's NEWOBJ.
        assert doc.undo_operations == [
            (matwire_c4d.c4d.UNDOTYPE_NEWOBJ, doc.undo_operations[0][1])]
        assert log[insert_at + 1] == ("AddUndo", matwire_c4d.c4d.UNDOTYPE_NEWOBJ)

    def test_failure_never_touches_the_document(self, matwire_c4d, monkeypatch):
        log = []
        self._install_fakes(matwire_c4d, monkeypatch, log, fail_on="apply")
        doc = _OrderRecordingDoc(log)
        tex_set = {"name": "plaster", "channels": {"basecolor": "c.png"},
                   "normal_flipy": False}
        out = matwire_c4d.create_material_for_set(doc, "/tex", tex_set, "plaster")
        assert out["ok"] is False and "apply boom" in out["error"]
        # No insertion, hence no NEWOBJ and no balancing DELETE to take.
        assert "InsertMaterial" not in log
        assert doc.undo_operations == []


class TestAoDestination:
    """matwire.ao_destination — the SINGLE source for "where does the AO
    go" (same discipline as orm_contributions): the writer builds the graph
    from it and the preview annotates the AO row from it, so the row the
    artist reads can never promise a wiring the writer won't make."""

    def test_ao_destination_single_source(self, matwire):
        ch_ao = {"basecolor": "b.png", "ao": "a.png"}
        assert matwire.ao_destination(ch_ao, True) == "base_color_multiply"
        assert matwire.ao_destination(ch_ao, False) == "unconnected"
        assert matwire.ao_destination({"basecolor": "b.png"}, True) is None

    def test_ao_without_basecolor_has_nothing_to_multiply_into(self, matwire):
        assert matwire.ao_destination({"ao": "a.png"}, True) == "unconnected"
        assert matwire.ao_destination({"ao": "a.png"}, False) == "unconnected"

    def test_empty_channels(self, matwire):
        assert matwire.ao_destination({}, True) is None
        assert matwire.ao_destination(None, True) is None

    def test_writer_follows_the_same_source(self, sentinel_module, matwire):
        # The writer's loose-AO decision IS ao_destination — not a parallel
        # rule that could drift (review I2 pattern).
        matwire_c4d = importlib.import_module("sentinel.matwire_c4d")
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"basecolor": "b.png", "ao": "a.png"}}
        _desc, ao = matwire_c4d.build_description("/tex", tex_set,
                                                  multiply_ao=True)
        assert matwire.ao_destination(tex_set["channels"], True) == \
            "base_color_multiply"
        assert ao is None


class TestColorCorrectAndAoMultiply:
    """v1.33: identity Color Correct always on basecolor (cost ≈0, measured
    identity — spike 2026-07-30 §B.2 T_CC) and the opt-in AO multiply via
    rscolorlayer with layer1_blend_mode = 4 (Multiply — enum measured, 2 is
    NOT). Child-port ids introspected live in C4D 2026.303 before use:
    rscolorcorrection.input / rscolorlayer.base_color / .layer1_color /
    .layer1_enable / .layer1_blend_mode."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def test_color_correct_always_interposed(self, matwire, matwire_c4d):
        scan = matwire.scan_texture_sets(["p_BaseColor.png", "p_Roughness.png"])
        desc, _ao = matwire_c4d.build_description("/tex", scan["sets"][0])
        RS = matwire_c4d._RS_CORE
        material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        cc = material["#<" + RS + "standardmaterial.base_color"]
        assert cc["$type"] == "#" + RS + "rscolorcorrection"
        inner = cc["#<" + RS + "rscolorcorrection.input"]
        assert inner["$type"] == "#" + RS + "texturesampler"
        assert inner["#<" + RS + "texturesampler.tex0/path"].endswith(
            "p_BaseColor.png")
        # colorspace stays explicit and comes from the single source
        assert inner["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("basecolor")]
        # roughness untouched by the correction
        assert material["#<" + RS + "standardmaterial.refl_roughness"]["$type"] == \
            "#" + RS + "texturesampler"

    def test_no_basecolor_no_correction_node(self, matwire, matwire_c4d):
        scan = matwire.scan_texture_sets(["p_Roughness.png"])
        desc, _ao = matwire_c4d.build_description("/tex", scan["sets"][0])
        assert "rscolorcorrection" not in repr(desc)

    def test_ao_multiply_wires_layer_and_drops_loose_sampler(
            self, matwire, matwire_c4d):
        scan = matwire.scan_texture_sets(["p_BaseColor.png", "p_AO.png"])
        tex_set = scan["sets"][0]
        RS = matwire_c4d._RS_CORE
        # OFF: AO stays a loose sampler (v1.32 behavior)
        desc_off, ao_off = matwire_c4d.build_description(
            "/tex", tex_set, multiply_ao=False)
        assert ao_off is not None
        assert desc_off["#<" + matwire_c4d._RS_OUTPUT + ".surface"][
            "#<" + RS + "standardmaterial.base_color"]["$type"] == \
            "#" + RS + "rscolorcorrection"
        # ON: color layer between the corrected color and base_color; no loose AO
        desc_on, ao_on = matwire_c4d.build_description(
            "/tex", tex_set, multiply_ao=True)
        assert ao_on is None
        layer = desc_on["#<" + matwire_c4d._RS_OUTPUT + ".surface"][
            "#<" + RS + "standardmaterial.base_color"]
        assert layer["$type"] == "#" + RS + "rscolorlayer"
        assert layer["#<" + RS + "rscolorlayer.layer1_blend_mode"] == 4  # Multiply
        # never depend on node defaults (colorspace/flipy principle)
        assert layer["#<" + RS + "rscolorlayer.layer1_enable"] is True
        base = layer["#<" + RS + "rscolorlayer.base_color"]
        assert base["$type"] == "#" + RS + "rscolorcorrection"  # correction first
        assert base["#<" + RS + "rscolorcorrection.input"][
            "#<" + RS + "texturesampler.tex0/path"].endswith("p_BaseColor.png")
        lay1 = layer["#<" + RS + "rscolorlayer.layer1_color"]
        assert lay1["#<" + RS + "texturesampler.tex0/path"].endswith("p_AO.png")
        assert lay1["#<" + RS + "texturesampler.tex0/colorspace"] == \
            matwire_c4d._RS_COLORSPACE[matwire.channel_colorspace("ao")]

    def test_ao_multiply_without_basecolor_is_noop(self, matwire, matwire_c4d):
        # An AO-only set has nothing to multiply INTO: the layer must not
        # appear and the AO stays loose (never a dangling color layer).
        scan = matwire.scan_texture_sets(["p_AO.png", "p_Roughness.png"])
        desc, ao = matwire_c4d.build_description(
            "/tex", scan["sets"][0], multiply_ao=True)
        RS = matwire_c4d._RS_CORE
        material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        assert "#<" + RS + "standardmaterial.base_color" not in material
        assert "rscolorlayer" not in repr(desc)
        assert ao is not None

    def test_default_keeps_existing_callers_off(self, matwire, matwire_c4d):
        # multiply_ao defaults to False: same graph as an explicit False.
        scan = matwire.scan_texture_sets(["p_BaseColor.png", "p_AO.png"])
        tex_set = scan["sets"][0]
        assert matwire_c4d.build_description("/tex", tex_set) == \
            matwire_c4d.build_description("/tex", tex_set, multiply_ao=False)

    def test_intermediary_layout_columns(self, matwire_c4d):
        # Both new nodes sit between the samplers (-600) and the material
        # (0); rows are keyed by COLUMN, so sharing one never stacks.
        cols = matwire_c4d._LAYOUT_COLS
        assert cols["texturesampler"] < cols["rscolorcorrection"] < \
            cols["rscolorlayer"] <= cols["bumpmap"] < cols["standardmaterial"]


class TestNodeTitles:
    """v1.33 semantic titles. Samplers are titled by CHANNEL, not filename;
    leftovers (which have no channel) fall back to their basename.

    LIVE-CAUGHT (user, v1.33 matrix): the Node Editor renders
    ``net.maxon.node.base.name``, NOT ``…attribute.title`` — the titles were
    written and read back fine while the editor still showed each sampler's
    filename and each utility node's native type name. The writer now sets
    BOTH attributes; `name` is the one the artist actually sees."""

    def test_writer_sets_the_visible_name_attribute(self, matwire_c4d):
        # Regression for the live catch: writing only the title attribute
        # left the editor showing filenames.
        assert matwire_c4d._NAME_ATTR == "net.maxon.node.base.name"
        import inspect
        body = inspect.getsource(matwire_c4d._layout_and_title_nodes)
        assert "_NAME_ATTR" in body, "the visible name attribute must be written"

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def test_kind_titles_cover_the_utility_nodes(self, matwire_c4d):
        titles = matwire_c4d.NODE_TITLES
        assert titles["rscolorcorrection"] == "Color Correct"
        assert titles["rscolorlayer"] == "AO Multiply"
        assert titles["bumpmap"] == "Bump"
        assert titles["displacement"] == "Displacement"
        # the material/output keep their native identity
        assert "standardmaterial" not in titles
        assert "output" not in titles

    def test_sampler_titles_by_channel(self, matwire, matwire_c4d):
        scan = matwire.scan_texture_sets([
            "p_BaseColor.png", "p_Roughness.png", "p_NormalDX.png",
            "p_Height.exr", "p_AO.png", "p_ORM.png", "p_Opacity.png",
            "p_Emission.png"])
        titles = matwire_c4d.build_node_titles("/tex", scan["sets"][0])
        assert titles[os.path.join("/tex", "p_BaseColor.png")] == "Base Color"
        assert titles[os.path.join("/tex", "p_Roughness.png")] == "Roughness"
        assert titles[os.path.join("/tex", "p_NormalDX.png")] == "Normal"
        assert titles[os.path.join("/tex", "p_Height.exr")] == "Height"
        assert titles[os.path.join("/tex", "p_AO.png")] == "AO"
        assert titles[os.path.join("/tex", "p_ORM.png")] == "ORM"
        assert titles[os.path.join("/tex", "p_Opacity.png")] == "Opacity"
        assert titles[os.path.join("/tex", "p_Emission.png")] == "Emission"

    def test_leftovers_titled_by_basename(self, matwire, matwire_c4d):
        scan = matwire.scan_texture_sets(["p_BaseColor.png"])
        titles = matwire_c4d.build_node_titles(
            "/tex", scan["sets"][0], ["sub/readme_preview.png"])
        assert titles[os.path.join("/tex", "sub", "readme_preview.png")] == \
            "readme_preview.png"

    def test_title_lookup_prefers_the_channel_map(self, matwire_c4d):
        # _node_title is the single decision point the layout pass uses.
        titles = {"/tex/a.png": "Base Color"}
        assert matwire_c4d._node_title("texturesampler", "/tex/a.png", titles) == \
            "Base Color"
        # unknown sampler path (never happens for our own graph) -> basename
        assert matwire_c4d._node_title("texturesampler", "/tex/z.png", titles) == \
            "z.png"
        assert matwire_c4d._node_title("rscolorcorrection", "", titles) == \
            "Color Correct"
        assert matwire_c4d._node_title("standardmaterial", "", titles) is None


class TestUvContextPlan:
    """v1.33 shared UV context — one ``uvcontextprojection`` per material
    feeding the ``uv_context`` of EVERY sampler. Ids/enums/traps pinned here
    come from the live introspection of 2026-07-30 (spike doc,
    "Confirmación de puertos v1.33"), never from documentation."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    @pytest.fixture
    def available(self, matwire_c4d, monkeypatch):
        monkeypatch.setattr(matwire_c4d, "uvcontext_available", lambda: True)
        return matwire_c4d

    def test_plan_pins_proj_type_and_rectangular_tiling(self, available):
        matwire_c4d = available
        UC = matwire_c4d._RS_UVCTX
        for proj_type in (1, 2):
            plan = matwire_c4d.build_uvcontext_plan(proj_type)
            desc = plan["desc"]
            assert desc["$type"] == "#" + UC
            assert desc["#<" + UC + ".proj_type"] == proj_type
            # 1 would be HEXAGONAL tiling (measured live) — a writer that
            # "turns tiling on" with 1 ships hexagons.
            assert desc["#<" + UC + ".uv_tiling"] == 0
            assert plan["connect_to"] == \
                matwire_c4d._RS_CORE + "texturesampler.uv_context"

    def test_projection_string_map(self, matwire_c4d):
        assert matwire_c4d.PROJECTION_TYPES == {"uv": 1, "triplanar": 2}

    def test_plan_is_none_when_node_unavailable(self, matwire_c4d, monkeypatch):
        monkeypatch.setattr(matwire_c4d, "uvcontext_available", lambda: False)
        assert matwire_c4d.build_uvcontext_plan(1) is None

    def test_context_has_its_own_layout_column_upstream(self, matwire_c4d):
        cols = matwire_c4d._LAYOUT_COLS
        assert cols["uvcontextprojection"] < cols["texturesampler"]

    def test_sampler_transform_ports_are_never_written(self, matwire, matwire_c4d,
                                                       monkeypatch):
        """The sampler's own scale/offset/rotate MULTIPLY with the context
        (measured: 4 x 2 = 8 tiles), so writing them would give the artist
        two chained transforms. Every desc this writer builds is swept."""
        monkeypatch.setattr(matwire_c4d, "uvcontext_available", lambda: True)
        scan = matwire.scan_texture_sets([
            "p_BaseColor.png", "p_Roughness.png", "p_Normal.png",
            "p_AO.png", "p_ORM.png", "p_Height.exr", "p_Opacity.png",
            "p_Emission.png"])
        tex_set = scan["sets"][0]
        descs = []
        for multiply_ao in (False, True):
            main, ao = matwire_c4d.build_description(
                "/tex", tex_set, multiply_ao=multiply_ao)
            descs.append(main)
            if ao is not None:
                descs.append(ao)
        orm = matwire_c4d.build_orm_plan("/tex", tex_set)
        if orm is not None:
            descs.append(orm["splitter_desc"])
        descs.extend(matwire_c4d.build_leftover_descriptions(
            "/tex", ["stray.png"]))
        descs.append(matwire_c4d.build_uvcontext_plan(1)["desc"])

        forbidden = tuple(
            matwire_c4d._RS_CORE + "texturesampler." + p
            for p in ("scale", "offset", "rotate"))
        seen_keys = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    seen_keys.append(key)
                    walk(value)
            elif isinstance(node, (list, tuple)):
                for item in node:
                    walk(item)

        for desc in descs:
            walk(desc)
        assert seen_keys, "sweep found no keys — the fixture went stale"
        for key in seen_keys:
            assert not any(f in key for f in forbidden), \
                "sampler transform port written: " + key

    def test_create_material_threads_projection_to_the_plan(self, matwire_c4d,
                                                            monkeypatch):
        seen = []

        def _fake_plan(proj_type):
            seen.append(proj_type)
            return None  # None => v1.32.1 graph, keeps this test c4d-free

        monkeypatch.setattr(matwire_c4d, "build_uvcontext_plan", _fake_plan)
        log = []
        TestCreateMaterialOrdering._install_fakes(
            TestCreateMaterialOrdering(), matwire_c4d, monkeypatch, log)
        doc = _OrderRecordingDoc(log)
        tex_set = {"name": "p", "channels": {"basecolor": "c.png"},
                   "normal_flipy": False}
        for projection, expected in (("uv", 1), ("triplanar", 2),
                                     ("nonsense", 1)):
            out = matwire_c4d.create_material_for_set(
                doc, "/tex", tex_set, "p", projection=projection)
            assert out["ok"] is True
        assert seen == [1, 2, 1]

    def test_context_applies_after_samplers_and_before_layout(self, matwire_c4d,
                                                              monkeypatch):
        """ORDER IS THE CONTRACT: the context walks the live graph to find
        samplers, so every sampler-creating apply must already have run; the
        layout pass must run last so the context gets positioned."""
        log = []
        TestCreateMaterialOrdering._install_fakes(
            TestCreateMaterialOrdering(), matwire_c4d, monkeypatch, log)
        monkeypatch.setattr(matwire_c4d, "build_uvcontext_plan",
                            lambda proj_type: {"desc": {}, "connect_to": "x"})
        monkeypatch.setattr(matwire_c4d, "_apply_uvcontext_plan",
                            lambda graph, plan: log.append("_apply_uvcontext"))
        # the ORM branch needs a live graph to walk; here only its position
        # in the sequence matters, and it creates a sampler.
        monkeypatch.setattr(
            matwire_c4d, "_apply_orm_plan",
            lambda graph, plan: log.append("ApplyDescription"))
        doc = _OrderRecordingDoc(log)
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"basecolor": "c.png", "packed_orm": "o.png"}}
        out = matwire_c4d.create_material_for_set(
            doc, "/tex", tex_set, "p", leftover_files=["stray.png"])
        assert out["ok"] is True
        at = log.index("_apply_uvcontext")
        # every ApplyDescription (main + ORM + leftovers) comes first...
        assert max(i for i, e in enumerate(log)
                   if e == "ApplyDescription") < at
        # ...and the layout/title pass comes after.
        assert at < log.index("_layout_and_title_nodes") < log.index("InsertMaterial")


_RS_OUTPUT_FOR_TEST = "com.redshift3d.redshift4c4d.node.output"


# --- fake graph for the UV-context fan-out (mirrors the live shapes) -------
# GetValue(assetid) returns a maxon Pair whose str() is "(com...kind,)" —
# the exact shape that broke _kind_from_assetid live, so the fake speaks it.

class _FakeGraphPort:
    def __init__(self, node, port_id):
        self.node = node
        self.port_id = port_id
        self.incoming = []

    def Connect(self, other):
        other.incoming.append(self)


class _FakeGraphPortList:
    def __init__(self, node):
        self._node = node

    def FindChild(self, port_id):
        return self._node.port(port_id)


class _FakeGraphNode:
    def __init__(self, asset_id):
        self.asset_id = asset_id
        self._ports = {}

    def port(self, port_id):
        return self._ports.setdefault(port_id, _FakeGraphPort(self, port_id))

    def GetValue(self, attr):
        return "(%s,)" % self.asset_id

    def GetInputs(self):
        return _FakeGraphPortList(self)

    def GetOutputs(self):
        return _FakeGraphPortList(self)


class _FakeTransaction:
    def __init__(self, graph):
        self._graph = graph

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def Commit(self):
        self._graph.commits += 1


class _FakeGraph:
    def __init__(self, asset_ids):
        self.nodes = [_FakeGraphNode(a) for a in asset_ids]
        self.applied = []
        self.commits = 0

    def GetViewRoot(self):
        return self

    def GetInnerNodes(self, mask=None, includeThis=False):
        return list(self.nodes)

    def BeginTransaction(self):
        return _FakeTransaction(self)


class TestUvContextFanOut:
    """The central v1.33 claim — ONE context feeds EVERY texturesampler —
    pinned without a live C4D. The fake speaks the real shapes: assetid
    reads as a Pair-str, ports are found by full id, Connect records the
    edge."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def _fake_maxon(self, matwire_c4d, monkeypatch, ctx_id):
        class _GD:
            @staticmethod
            def ApplyDescription(graph, desc):
                graph.applied.append(desc)
                graph.nodes.append(_FakeGraphNode(ctx_id))

        fake = type("_M", (), {
            "GraphDescription": _GD,
            "NODE_KIND": type("_K", (), {"NODE": 1}),
        })
        monkeypatch.setattr(matwire_c4d, "maxon", fake)

    def test_every_sampler_is_connected_and_only_samplers(self, matwire_c4d,
                                                          monkeypatch):
        core = matwire_c4d._RS_CORE
        ctx_id = matwire_c4d._RS_UVCTX
        self._fake_maxon(matwire_c4d, monkeypatch, ctx_id)
        graph = _FakeGraph([
            core + "texturesampler",          # basecolor
            core + "texturesampler",          # roughness
            core + "texturesampler",          # ORM (splitter-fed)
            core + "texturesampler",          # loose leftover
            core + "rscolorsplitter",         # must NOT be connected
            core + "standardmaterial",
            _RS_OUTPUT_FOR_TEST,
        ])
        plan = {"desc": {"$type": "#" + ctx_id},
                "connect_to": core + "texturesampler.uv_context"}
        matwire_c4d._apply_uvcontext_plan(graph, plan)

        assert graph.applied == [plan["desc"]], "context desc applied once"
        assert graph.commits == 1, "the fan-out is ONE transaction"
        ctx_nodes = [n for n in graph.nodes if n.asset_id == ctx_id]
        assert len(ctx_nodes) == 1
        ctx = ctx_nodes[0]
        out_port = ctx.port(ctx_id + ".outcontext")

        samplers = [n for n in graph.nodes
                    if n.asset_id == core + "texturesampler"]
        assert len(samplers) == 4
        # (a) EVERY sampler got the context on its uv_context port
        for sampler in samplers:
            incoming = sampler.port(plan["connect_to"]).incoming
            assert incoming == [out_port], \
                "sampler missed the shared context"
        # (b) the context node itself is excluded (never wired into itself)
        for port in ctx._ports.values():
            assert port.incoming == []
        # (c) the splitter (and every non-sampler) is excluded
        for node in graph.nodes:
            if node.asset_id == core + "texturesampler":
                continue
            for port in node._ports.values():
                assert port.incoming == [], \
                    "non-sampler node wired to the context: " + node.asset_id

    def test_fallback_only_runs_without_the_context(self, matwire_c4d,
                                                    monkeypatch):
        """The UniTransform is the FALLBACK: with a context available it must
        never be built (two shared controls chained on the same samplers
        would multiply, which is the one thing the spike measured)."""
        log = []
        TestCreateMaterialOrdering._install_fakes(
            TestCreateMaterialOrdering(), matwire_c4d, monkeypatch, log)
        monkeypatch.setattr(matwire_c4d, "build_unitransform_plan",
                            lambda: {"knobs": []})
        monkeypatch.setattr(matwire_c4d, "_apply_unitransform_plan",
                            lambda graph, plan: log.append("_apply_unitransform"))
        monkeypatch.setattr(matwire_c4d, "_apply_uvcontext_plan",
                            lambda graph, plan: log.append("_apply_uvcontext"))
        tex_set = {"name": "p", "channels": {"basecolor": "c.png"},
                   "normal_flipy": False}

        monkeypatch.setattr(matwire_c4d, "build_uvcontext_plan",
                            lambda proj_type: {"desc": {}, "connect_to": "x"})
        assert matwire_c4d.create_material_for_set(
            _OrderRecordingDoc(log), "/tex", tex_set, "p")["ok"] is True
        assert "_apply_uvcontext" in log
        assert "_apply_unitransform" not in log, \
            "UniTransform built alongside the context"

        log[:] = []
        monkeypatch.setattr(matwire_c4d, "build_uvcontext_plan",
                            lambda proj_type: None)
        assert matwire_c4d.create_material_for_set(
            _OrderRecordingDoc(log), "/tex", tex_set, "p")["ok"] is True
        assert "_apply_unitransform" in log
        # AFTER the layout pass (an assetid-less group node would otherwise
        # be positioned in column 0, on top of the material).
        assert (log.index("_layout_and_title_nodes")
                < log.index("_apply_unitransform")
                < log.index("InsertMaterial"))

    def test_fallback_failure_never_kills_the_material(self, matwire_c4d,
                                                       monkeypatch):
        """This branch only ever runs on Redshift builds we cannot test
        against, so it degrades to the v1.32.1 graph instead of losing a
        material that is otherwise complete."""
        log = []
        TestCreateMaterialOrdering._install_fakes(
            TestCreateMaterialOrdering(), matwire_c4d, monkeypatch, log)
        monkeypatch.setattr(matwire_c4d, "build_uvcontext_plan",
                            lambda proj_type: None)
        monkeypatch.setattr(matwire_c4d, "build_unitransform_plan",
                            lambda: {"knobs": []})

        def _boom(graph, plan):
            raise RuntimeError("no group API on this build")

        monkeypatch.setattr(matwire_c4d, "_apply_unitransform_plan", _boom)
        out = matwire_c4d.create_material_for_set(
            _OrderRecordingDoc(log), "/tex",
            {"name": "p", "channels": {"basecolor": "c.png"},
             "normal_flipy": False}, "p")
        assert out["ok"] is True and out["error"] is None
        assert "InsertMaterial" in log, "material lost to a cosmetic failure"

    def test_no_samplers_leaves_no_orphan_context(self, matwire_c4d,
                                                  monkeypatch):
        """Unreachable today (every scanned set has files), but applying
        first and returning later would leave a dangling context node."""
        core = matwire_c4d._RS_CORE
        ctx_id = matwire_c4d._RS_UVCTX
        self._fake_maxon(matwire_c4d, monkeypatch, ctx_id)
        graph = _FakeGraph([core + "standardmaterial", _RS_OUTPUT_FOR_TEST])
        plan = {"desc": {"$type": "#" + ctx_id},
                "connect_to": core + "texturesampler.uv_context"}
        matwire_c4d._apply_uvcontext_plan(graph, plan)
        assert graph.applied == [], "context desc must not be applied"
        assert graph.commits == 0
        assert all(n.asset_id != ctx_id for n in graph.nodes), \
            "orphan context node left in the graph"


# --- fake graph WITH group support, for the UniTransform fallback ---------
# It speaks the two live shapes that decide this code: MoveToGroup RETURNS a
# group and INVALIDATES every moved handle (touching one raises, exactly as
# C4D does — the spike hit this), and a group's inner nodes are reachable
# only through GetInnerNodes on the group itself.

class _DeadNodeError(RuntimeError):
    pass


class _FakeUtPort:
    """Speaks maxon's shape for a MISSING port: ``FindChild`` answers with a
    NULL port object, not None, and every operation on it quietly no-ops.
    That distinction is the whole reason ``_ut_port`` exists — a fake that
    returned None would raise AttributeError and make an unguarded call site
    look safe while in production it silently leaves a node at zero."""

    def __init__(self, owner, port_id, null=False):
        self.owner = owner
        self.port_id = port_id
        self.incoming = []
        self.value = None
        self.null = null

    def Connect(self, other):
        if self.null or other.null:
            return                       # maxon: silently does nothing
        other.incoming.append(self)

    def SetPortValue(self, value):
        if self.null:
            return
        self.value = value

    def GetPortValue(self):
        return None if self.null else self.value

    def IsNullValue(self):
        return self.null


class _FakeUtPortList:
    def __init__(self, node):
        self._node = node

    def FindChild(self, port_id):
        return self._node.port(port_id)


_MUL_ID = "com.redshift3d.redshift4c4d.nodes.core.rsmathmulvector"

#: Ports each faked node type really has. A node with a whitelist returns
#: None from FindChild for anything else — exactly like maxon — so a wrong
#: port id in the writer fails the test instead of conjuring a port. Nodes
#: absent from this table (samplers, the group root) stay permissive: their
#: ids ARE what the writer is asserting, and the group's ports are created
#: through the helper.
_FAKE_NODE_PORTS = {
    "net.maxon.node.type": {"in", "datatype", "out"},
    _MUL_ID: {_MUL_ID + ".input1", _MUL_ID + ".input2", _MUL_ID + ".out"},
}


class _FakeUtNode:
    def __init__(self, asset_id):
        self.asset_id = asset_id
        self.alive = True
        self.attrs = {}
        self.inner = []
        self._ports = {}
        self._allowed = _FAKE_NODE_PORTS.get(asset_id)

    def _check(self):
        if not self.alive:
            raise _DeadNodeError(
                "Node with path %s doesn't exist any longer." % self.asset_id)

    def port(self, port_id):
        self._check()
        if self._allowed is not None and port_id not in self._allowed:
            return _FakeUtPort(self, port_id, null=True)
        return self._ports.setdefault(port_id, _FakeUtPort(self, port_id))

    def GetInputs(self):
        self._check()
        return _FakeUtPortList(self)

    def GetOutputs(self):
        self._check()
        return _FakeUtPortList(self)

    def SetValue(self, attr, value):
        self._check()
        self.attrs[attr] = value

    def GetValue(self, attr):
        if attr == "net.maxon.node.attribute.assetid":
            return "(%s,)" % self.asset_id
        return self.attrs.get(attr)

    def GetInnerNodes(self, mask, includeThis, out):
        out.extend(self.inner)

    def Remove(self):
        self._check()
        self.graph.nodes.remove(self)
        if self in self.graph.groups:
            self.graph.groups.remove(self)


class _FakeUtGraph:
    def __init__(self, asset_ids):
        self.nodes = []
        self.applied = []
        self.commits = 0
        self.groups = []
        for asset_id in asset_ids:
            self._own(_FakeUtNode(asset_id))

    def _own(self, node):
        node.graph = self
        self.nodes.append(node)
        return node

    def GetViewRoot(self):
        return self

    def GetInnerNodes(self, mask=None, includeThis=False):
        return list(self.nodes)

    def BeginTransaction(self):
        return _FakeTransaction(self)

    def MoveToGroup(self, _root, group_id, members):
        """Real semantics: the members are re-parented, their old handles go
        dead, and the group gets LIVE inner nodes carrying their state."""
        group = _FakeUtNode("group:" + str(group_id))
        for member in members:
            member._check()
            moved = _FakeUtNode(member.asset_id)
            moved.graph = self
            moved.attrs = dict(member.attrs)
            moved._ports = {k: v for k, v in member._ports.items()}
            group.inner.append(moved)
            member.alive = False
            self.nodes.remove(member)
        self._own(group)
        self.groups.append(group)
        return group


class TestUniTransformFallback:
    """The pre-2026.2 Redshift fallback: one UniTransform group whose three
    knobs drive the transform of EVERY sampler."""

    @pytest.fixture
    def matwire_c4d(self, sentinel_module):
        return importlib.import_module("sentinel.matwire_c4d")

    def _fake_maxon(self, matwire_c4d, monkeypatch):
        class _Vec:
            def __init__(self, x, y, z=0.0):
                self.x, self.y, self.z = x, y, z

            def __eq__(self, other):
                return (self.x, self.y, self.z) == (other.x, other.y, other.z)

            def __repr__(self):
                return "Vec(%s,%s,%s)" % (self.x, self.y, self.z)

        class _GD:
            @staticmethod
            def ApplyDescription(graph, desc):
                graph.applied.append(desc)
                graph._own(_FakeUtNode(str(desc["$type"]).lstrip("#")))

        class _Helper:
            @staticmethod
            def CreateOutputPort(group, port_id, label):
                return group.port("out:" + port_id)

            @staticmethod
            def CreateInputPort(group, port_id, label):
                return group.port("in:" + port_id)

        fake = type("_M", (), {
            "GraphDescription": _GD,
            "GraphModelHelper": _Helper,
            "NODE_KIND": type("_K", (), {"NODE": 1}),
            "GraphNode": lambda: None,
            "Id": staticmethod(lambda v: v),
            "String": staticmethod(lambda v: v),
            "Float": staticmethod(lambda v: v),
            "Vector": _Vec,
        })
        monkeypatch.setattr(matwire_c4d, "maxon", fake)
        monkeypatch.setattr(matwire_c4d, "MAXON_AVAILABLE", True)
        return _Vec

    def test_plan_shape_is_identity_and_upstream(self, matwire_c4d,
                                                 monkeypatch):
        self._fake_maxon(matwire_c4d, monkeypatch)
        plan = matwire_c4d.build_unitransform_plan()
        core = matwire_c4d._RS_CORE
        knobs = {k["node"]: k for k in plan["inputs"]}
        assert set(knobs) == {"Scale2D", "UniScale", "Offset", "Rotation"}
        # Identity — a Value node is born at ZERO, so an unwritten Scale
        # would drive every sampler to a 0x0 tiling, and an unwritten
        # UniScale would multiply the whole thing back to zero.
        assert knobs["Scale2D"]["value"] == (1.0, 1.0)
        assert knobs["UniScale"]["value"] == 1.0
        assert knobs["Offset"]["value"] == (0.0, 0.0)
        assert knobs["Rotation"]["value"] == 0.0
        # Only the vec2 knobs retype the node; UniScale and rotate want the
        # node's native float.
        assert knobs["Rotation"]["datatype"] is None
        assert knobs["UniScale"]["datatype"] is None
        assert knobs["Scale2D"]["datatype"] == knobs["Offset"]["datatype"] \
            == matwire_c4d._VEC2_TYPE
        # The knob the artist reads is "Scale"; "Scale2D" is the node behind it.
        assert knobs["Scale2D"]["label"] == "Scale"
        outs = {o["label"]: o for o in plan["outputs"]}
        assert set(outs) == {"Scale", "Offset", "Rotation"}
        # Scale is emitted by the MULTIPLY (UniScale x Scale2D), not the value.
        assert outs["Scale"]["source"] == plan["mul_name"]
        assert outs["Scale"]["connect_to"] == core + "texturesampler.scale"
        assert outs["Offset"]["connect_to"] == core + "texturesampler.offset"
        assert outs["Rotation"]["connect_to"] == core + "texturesampler.rotate"
        assert plan["column"] < matwire_c4d._LAYOUT_COLS["texturesampler"]

    def test_group_drives_every_sampler_with_identity_values(self, matwire_c4d,
                                                             monkeypatch):
        vec = self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([
            core + "texturesampler",
            core + "texturesampler",
            core + "texturesampler",      # ORM / leftover — included too
            core + "rscolorsplitter",     # must NOT be driven
            core + "standardmaterial",
            _RS_OUTPUT_FOR_TEST,
        ])
        plan = matwire_c4d.build_unitransform_plan()
        matwire_c4d._apply_unitransform_plan(graph, plan)

        assert len(graph.groups) == 1, "exactly one UniversalXform group"
        group = graph.groups[0]
        assert str(group.GetValue("net.maxon.node.base.name")) \
            == "UniversalXform"
        assert group.GetValue("net.maxon.node.base.xpos") == plan["column"]
        inner = []
        group.GetInnerNodes(1, False, inner)
        by_name = {str(n.GetValue("net.maxon.node.base.name")): n
                   for n in inner}
        assert sorted(by_name) == ["Offset", "Rotation", "Scale", "Scale2D",
                                   "UniScale"], "the multiply must move too"

        # The multiply is fed by BOTH scale knobs, and it is what feeds the
        # samplers' scale — an unfed input1 would zero the whole tiling.
        mul = by_name[plan["mul_name"]]
        ports = plan["mul_ports"]
        assert mul.port(ports["uniscale"]).incoming == [
            by_name["UniScale"].port("out")]
        assert mul.port(ports["scale"]).incoming == [
            by_name["Scale2D"].port("out")]

        samplers = [n for n in graph.nodes
                    if n.asset_id == core + "texturesampler"]
        assert len(samplers) == 3
        expected = {"Scale2D": vec(1.0, 1.0, 0.0), "UniScale": 1.0,
                    "Offset": vec(0.0, 0.0, 0.0), "Rotation": 0.0}
        for knob in plan["inputs"]:
            in_port = group.port("in:ut_in_" + knob["node"].lower())
            # the LIVE value lives on the group's input port (it drives the
            # inner Value node, and is born at zero)
            assert in_port.GetPortValue() == expected[knob["node"]], \
                "group knob %s left at its zero birth value" % knob["node"]
            assert in_port.incoming == [] and \
                by_name[knob["node"]].port("in").incoming == [in_port], \
                "group knob %s does not drive its value node" % knob["node"]
        for spec in plan["outputs"]:
            out_port = group.port("out:ut_out_" + spec["label"].lower())
            # The group port must be FED — driving samplers from an unfed
            # port is the 0-scale material, and it renders identically to a
            # correct one at identity, so only this assertion catches it.
            src = by_name[spec["source"]]
            src_port = (src.port(plan["mul_ports"]["out"])
                        if spec["source"] == plan["mul_name"]
                        else src.port("out"))
            assert out_port.incoming == [src_port], \
                "group output %s is not fed by %s" % (spec["label"],
                                                      spec["source"])
            for sampler in samplers:
                assert sampler.port(spec["connect_to"]).incoming == [out_port], \
                    "sampler missed the shared %s" % spec["label"]
        # nothing but samplers is driven from outside the group
        for node in graph.nodes:
            if node.asset_id == core + "texturesampler" or node is group:
                continue
            for port in node._ports.values():
                assert port.incoming == [], "non-sampler wired: " + node.asset_id

    def test_moved_handles_are_never_reused(self, matwire_c4d, monkeypatch):
        """The spike's live failure, pinned: MoveToGroup invalidates the
        handles, so the wiring MUST go through the group's inner nodes. The
        fake raises on a dead handle exactly as C4D does."""
        self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([core + "texturesampler",
                              core + "standardmaterial"])
        matwire_c4d._apply_unitransform_plan(
            graph, matwire_c4d.build_unitransform_plan())
        assert len(graph.groups) == 1  # no _DeadNodeError escaped

    def test_knob_values_survive_a_shuffled_enumeration(self, matwire_c4d,
                                                        monkeypatch):
        """Graph enumeration order is NOT creation order — measured live:
        three runs enumerated the same group's ports three different ways.
        Any scheme that zips freshly-applied nodes against the plan BY
        POSITION would write Scale's identity into Rotation on the run where
        the order flips. Here the fake enumerates in reverse; the values must
        still land on the right knobs."""
        vec = self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([core + "texturesampler"])
        inner_nodes = _FakeUtGraph.GetInnerNodes

        def _reversed(self, mask=None, includeThis=False):
            return list(reversed(inner_nodes(self, mask, includeThis)))

        monkeypatch.setattr(_FakeUtGraph, "GetInnerNodes", _reversed)
        plan = matwire_c4d.build_unitransform_plan()
        matwire_c4d._apply_unitransform_plan(graph, plan)

        group = graph.groups[0]
        expected = {"Scale2D": vec(1.0, 1.0, 0.0), "UniScale": 1.0,
                    "Offset": vec(0.0, 0.0, 0.0), "Rotation": 0.0}
        for knob in plan["inputs"]:
            assert group.port(
                "in:ut_in_" + knob["node"].lower()).GetPortValue() \
                == expected[knob["node"]], \
                "%s got another knob's identity value" % knob["node"]

    def test_a_port_that_drops_the_identity_aborts_before_wiring(
            self, matwire_c4d, monkeypatch):
        """The failure mode this branch cannot survive: a build where the
        created group port silently refuses the vec2. Wiring the samplers to
        it anyway ships Scale=(0,0) — one stretched texel across every
        material — and renders IDENTICALLY to a correct material at
        identity, so no pixel check would ever catch it. Abort instead, and
        leave nothing behind."""
        self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([core + "texturesampler",
                              core + "standardmaterial"])

        def _deaf(self, value):
            self.value = None          # the write silently no-ops

        monkeypatch.setattr(_FakeUtPort, "SetPortValue", _deaf)
        with pytest.raises(RuntimeError, match="identity value"):
            matwire_c4d._apply_unitransform_plan(
                graph, matwire_c4d.build_unitransform_plan())
        sampler = [n for n in graph.nodes
                   if n.asset_id == core + "texturesampler"][0]
        assert all(p.incoming == [] for p in sampler._ports.values()), \
            "samplers wired to a port that dropped its value"
        assert graph.groups == []
        assert [n.asset_id for n in graph.nodes] == [
            core + "texturesampler", core + "standardmaterial"], \
            "half-built UniversalXform left in the graph"

    def test_missing_group_api_creates_nothing_and_is_not_silent(
            self, matwire_c4d, monkeypatch):
        """An older build without the group calls must create NOTHING —
        checked before the first apply, so no orphan Value node is left
        sitting on top of the material — and must still RAISE, because the
        caller's log is the only trace the artist gets on a build where the
        disabled-selector copy has just promised them this control."""
        self._fake_maxon(matwire_c4d, monkeypatch)
        monkeypatch.delattr(matwire_c4d.maxon.GraphModelHelper,
                            "CreateInputPort")
        graph = _FakeUtGraph([matwire_c4d._RS_CORE + "texturesampler"])
        with pytest.raises(RuntimeError, match="node-group API"):
            matwire_c4d._apply_unitransform_plan(
                graph, matwire_c4d.build_unitransform_plan())
        assert graph.applied == [] and graph.groups == []

    def test_a_failure_between_apply_and_naming_leaves_no_orphan(
            self, matwire_c4d, monkeypatch):
        """ApplyDescription COMMITS the node before the writes that can
        fail. If tracking happened after those writes, a build whose Value
        node lacks a `datatype` port would strand a nameless node at (0,0)
        on top of the material — after the layout pass, so nothing would
        ever move it."""
        self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([core + "texturesampler",
                              core + "standardmaterial"])
        monkeypatch.setitem(_FAKE_NODE_PORTS, "net.maxon.node.type",
                            {"in", "out"})       # no `datatype` port
        with pytest.raises(Exception):
            matwire_c4d._apply_unitransform_plan(
                graph, matwire_c4d.build_unitransform_plan())
        assert [n.asset_id for n in graph.nodes] == [
            core + "texturesampler", core + "standardmaterial"], \
            "nameless Value node stranded in the root graph"

    def test_a_missing_port_aborts_instead_of_wiring_nothing(
            self, matwire_c4d, monkeypatch):
        """maxon answers a missing port with a NULL port, not None, and
        every call on it no-ops — so an unguarded `FindChild(...).Connect()`
        completes happily while the knob drives nothing and the samplers get
        the inner Values' birth zeros. The group port would still read back
        its identity, so the read-back guard cannot see this: only refusing
        the null port can. (The fake models the null-port shape; a fake
        returning None would raise AttributeError and hide the whole class.)
        """
        self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([core + "texturesampler",
                              core + "standardmaterial"])
        monkeypatch.setitem(_FAKE_NODE_PORTS, "net.maxon.node.type",
                            {"datatype", "out"})        # no `in` port
        with pytest.raises(RuntimeError, match="has no port"):
            matwire_c4d._apply_unitransform_plan(
                graph, matwire_c4d.build_unitransform_plan())
        assert graph.groups == []
        assert [n.asset_id for n in graph.nodes] == [
            core + "texturesampler", core + "standardmaterial"]

    def test_a_late_failure_removes_the_whole_group(self, matwire_c4d,
                                                    monkeypatch):
        """A failure in the OUTPUT loop happens after the group exists and
        after earlier outputs were already fanned out. Only the group handle
        is still alive at that point (the members died in the move), so the
        cleanup must remove the group — otherwise samplers stay wired to the
        ports of a node nobody can find."""
        self._fake_maxon(matwire_c4d, monkeypatch)
        core = matwire_c4d._RS_CORE
        graph = _FakeUtGraph([core + "texturesampler",
                              core + "standardmaterial"])
        plan = matwire_c4d.build_unitransform_plan()
        plan["outputs"][-1]["source"] = "NoSuchNode"   # fails mid-loop
        with pytest.raises(RuntimeError):
            matwire_c4d._apply_unitransform_plan(graph, plan)
        assert graph.groups == []
        assert [n.asset_id for n in graph.nodes] == [
            core + "texturesampler", core + "standardmaterial"], \
            "group left behind after a late failure"

    def test_no_samplers_creates_nothing(self, matwire_c4d, monkeypatch):
        self._fake_maxon(matwire_c4d, monkeypatch)
        graph = _FakeUtGraph([matwire_c4d._RS_CORE + "standardmaterial",
                              _RS_OUTPUT_FOR_TEST])
        matwire_c4d._apply_unitransform_plan(
            graph, matwire_c4d.build_unitransform_plan())
        assert graph.applied == [] and graph.groups == [], \
            "orphan UniTransform left driving nothing"
