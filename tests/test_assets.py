"""Pure-engine tests for the Asset Hub inventory (plugin/sentinel/assets.py)."""
import pytest
from sentinel import assets


class TestNormalizePathKey:
    def test_backslashes_and_case_fold(self):
        assert assets.normalize_path_key("D:\\Proj\\TEX\\A.PNG") == "d:/proj/tex/a.png"

    def test_strips_whitespace(self):
        assert assets.normalize_path_key("  /a/b.png ") == "/a/b.png"

    def test_none_and_empty(self):
        assert assets.normalize_path_key(None) == ""
        assert assets.normalize_path_key("") == ""


class TestInferType:
    @pytest.mark.parametrize("path,expected", [
        ("tex/wood_diffuse.png", "texture"),
        ("tex/rough.TIF", "texture"),
        ("hdri/studio.hdr", "hdri"),
        ("caches/char.abc", "alembic"),
        ("vol/smoke.vdb", "vdb"),
        ("lights/spot.ies", "ies"),
        ("luts/show.cube", "lut_ocio"),
        ("config.ocio", "lut_ocio"),
        ("audio/track.wav", "sound"),
        ("refs/city.c4d", "xref"),
        ("proxies/tree.rs", "proxy"),
        ("misc/readme.txt", "other"),
    ])
    def test_by_extension(self, path, expected):
        assert assets.infer_type(path) == expected

    def test_exr_default_is_texture(self):
        assert assets.infer_type("tex/floor_rough.exr") == "texture"

    def test_exr_on_light_owner_is_hdri(self):
        assert assets.infer_type("tex/env.exr", owner_kind="light") == "hdri"

    def test_exr_dome_channel_is_hdri(self):
        assert assets.infer_type("a.exr", channel="Dome Texture") == "hdri"


class TestClassifyGeneric:
    def test_empty(self):
        assert assets.classify_generic("", True) == "empty"
        assert assets.classify_generic("   ", False) == "empty"
        assert assets.classify_generic(None, False) == "empty"

    def test_asset_uri(self):
        assert assets.classify_generic("asset:///abc123", True) == "asset_uri"
        assert assets.classify_generic("preset://x.lib4d/y.png", True) == "asset_uri"

    def test_exists_is_ok(self):
        assert assets.classify_generic("/proj/tex/a.png", True) == "ok"

    def test_not_exists_is_missing(self):
        assert assets.classify_generic("/proj/tex/a.png", False) == "missing"


def _tex(path, status="ok", resolved=None, host="RS_Mat", src="rs_node",
         channel="Base Color", idx=0):
    return {"path": path, "resolved": resolved or path, "status": status,
            "host_name": host, "source_type": src, "channel": channel,
            "tex_idx": idx}


def _gen(path, exists=True, owner_name="obj", owner_kind="object"):
    return {"path": path, "exists": exists,
            "owner_name": owner_name, "owner_kind": owner_kind}


class TestMergeInventories:
    def test_texture_only_is_repathable(self):
        out = assets.merge_inventories([_tex("/p/tex/a.png")], [])
        assert len(out) == 1
        r = out[0]
        assert r["repathable"] is True
        assert r["tex_idx"] == 0
        assert r["owners"] == [("RS_Mat", "material", "Base Color")]
        assert r["asset_type"] == "texture"

    def test_generic_only_is_readonly(self):
        out = assets.merge_inventories([], [_gen("/p/luts/show.cube")])
        r = out[0]
        assert r["repathable"] is False
        assert r["tex_idx"] is None
        assert r["asset_type"] == "lut_ocio"
        assert r["status"] == "ok"

    def test_same_path_merges_texture_wins(self):
        out = assets.merge_inventories(
            [_tex("/p/tex/a.png", status="absolute")],
            [_gen("/P/TEX/A.PNG", owner_name="dome", owner_kind="light")])
        assert len(out) == 1
        r = out[0]
        assert r["status"] == "absolute"          # texture record wins
        assert r["repathable"] is True
        assert ("dome", "light", "") in r["owners"]   # generic owner added

    def test_n_uses_one_row_n_owners(self):
        out = assets.merge_inventories(
            [_tex("/p/a.png", host="M1", idx=0), _tex("/p/a.png", host="M2", idx=1)],
            [])
        assert len(out) == 1
        names = [o[0] for o in out[0]["owners"]]
        assert names == ["M1", "M2"]

    def test_sort_missing_first(self):
        out = assets.merge_inventories(
            [_tex("/p/z_ok.png"), _tex("/p/a_missing.png", status="missing")],
            [])
        assert [r["status"] for r in out] == ["missing", "ok"]

    def test_source_type_maps_owner_kind(self):
        out = assets.merge_inventories(
            [_tex("/p/h.exr", src="rs_object_fileref", host="RS Dome")], [])
        assert out[0]["owners"][0][1] == "light"
        assert out[0]["asset_type"] == "hdri"
