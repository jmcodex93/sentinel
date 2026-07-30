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
    out = _scan(matwire, "x_ORM_2k.png")
    reasons = {f: r for f, r in out["ignored"]}
    assert reasons["x_ORM_2k.png"] == "packed_orm"


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
    out = _scan(matwire, "x_ORM.png", "x_BaseColor.png", "readme.txt", "x_thumb.png")
    reasons = {f: r for f, r in out["ignored"]}
    assert reasons["x_ORM.png"] == "packed_orm"
    assert reasons["readme.txt"] == "bad_extension"
    assert reasons["x_thumb.png"] == "no_channel"
    assert set(out["sets"][0]["channels"]) == {"basecolor"}


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

        # normal: bump chain, raw, inputtype 1 (tangent-space), flipy set
        # only for DX-only sets (this set is Normal_DX-only -> flipy True)
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
