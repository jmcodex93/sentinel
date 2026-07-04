from pathlib import Path


def test_looks_like_texture_path_recognizes_supported_forms(sentinel_module):
    looks = sentinel_module._looks_like_texture_path

    assert looks("relative:///tex/diffuse.exr")
    assert looks("file:///Users/me/tex/diffuse.jpg")
    assert looks(r"C:\show\shot\tex\diffuse.png")
    assert looks(r"tex\diffuse.tif")
    assert looks("asset:abc123def")
    assert looks("preset:rs/builtin/noise")


def test_looks_like_texture_path_rejects_non_textures(sentinel_module):
    looks = sentinel_module._looks_like_texture_path

    assert not looks("")
    assert not looks("None")
    assert not looks("<empty>")
    assert not looks("diffuse")
    assert not looks("notes/readme.txt")
    assert not looks("just_a_string.exr")


def test_classify_texture_path_handles_empty_asset_and_absolute(sentinel_module):
    classify = sentinel_module._classify_texture_path

    assert classify("", "/project") == ("empty", None)
    assert classify("   ", "/project") == ("empty", None)
    assert classify("asset:abc123", "/project") == ("asset_uri", None)
    assert classify("preset:rs/builtin/texture", "/project") == ("asset_uri", None)
    assert classify("/mnt/assets/tex/diffuse.exr", "/project") == (
        "absolute",
        "/mnt/assets/tex/diffuse.exr",
    )
    assert classify(r"C:\show\shot\tex\diffuse.png", "/project") == (
        "absolute",
        r"C:\show\shot\tex\diffuse.png",
    )
    assert classify("file:///C:/show/shot/tex/diffuse.png", "/project") == (
        "absolute",
        "C:/show/shot/tex/diffuse.png",
    )


def test_classify_texture_path_resolves_relative_search_dirs(sentinel_module, tmp_path):
    doc_path = tmp_path / "shot"
    tex_dir = doc_path / "tex"
    tex_dir.mkdir(parents=True)
    texture = tex_dir / "hero_albedo.exr"
    texture.write_text("placeholder", encoding="utf-8")

    assert sentinel_module._classify_texture_path(
        "relative:///hero_albedo.exr", str(doc_path)
    ) == ("ok", str(texture))
    assert sentinel_module._classify_texture_path(
        "hero_albedo.exr", str(doc_path)
    ) == ("ok", str(texture))
    assert sentinel_module._classify_texture_path(
        "tex/hero_albedo.exr", str(doc_path)
    ) == ("ok", str(texture))


def test_classify_texture_path_reports_missing_expected_location(
    sentinel_module, tmp_path
):
    doc_path = tmp_path / "shot"
    doc_path.mkdir()

    status, resolved = sentinel_module._classify_texture_path(
        "relative:///missing/diffuse.exr", str(doc_path)
    )

    assert status == "missing"
    assert Path(resolved) == doc_path / "missing" / "diffuse.exr"


def test_compute_relative_texture_path_uses_forward_slashes(sentinel_module, tmp_path):
    doc_path = tmp_path / "shot" / "c4d"
    texture_path = tmp_path / "shot" / "tex" / "diffuse.exr"
    doc_path.mkdir(parents=True)
    texture_path.parent.mkdir(parents=True)
    texture_path.write_text("placeholder", encoding="utf-8")

    assert sentinel_module.compute_relative_texture_path(
        str(texture_path), str(doc_path)
    ) == "../tex/diffuse.exr"
    assert sentinel_module.compute_relative_texture_path(str(texture_path), "") is None
