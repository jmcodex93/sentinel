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
