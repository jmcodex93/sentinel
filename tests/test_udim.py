"""Pure tests for sentinel.udim (v1.42) — tile naming shared by Matwire,
the texture resolver, the Asset Hub and the colourspace check. Facts:
docs/research/2026-10-29-redshift-udim.md."""

from sentinel import udim


def test_split_tile_udim_painter_and_mari():
    assert udim.split_tile("LOK_cuerpo_Height_Raw_1001") == {
        "base": "LOK_cuerpo_Height_Raw", "tile": 1001, "scheme": "udim", "sep": "_"}
    assert udim.split_tile("rock_diffuse.1012") == {
        "base": "rock_diffuse", "tile": 1012, "scheme": "udim", "sep": "."}


def test_split_tile_uvtile_is_converted_to_udim_numbers():
    assert udim.split_tile("rock_Albedo_u1_v1") == {
        "base": "rock_Albedo", "tile": 1001, "scheme": "uvtile", "sep": ""}
    assert udim.split_tile("rock_Albedo_U2_V1")["tile"] == 1002
    assert udim.split_tile("rock_Albedo_u1_v2")["tile"] == 1011


def test_split_tile_rejects_non_tiles():
    for stem in ("rock_BaseColor", "rock_1000", "rock_0999", "1001",
                 "rock_10001", "rock_BaseColor_4k", "rock_u11_v1", "rock_u0_v1"):
        assert udim.split_tile(stem) is None, stem


def test_pattern_name_keeps_separator_and_uvtile_absorbs_underscore():
    assert udim.pattern_name("rock_diffuse", "udim", ".", ".exr") == "rock_diffuse.<UDIM>.exr"
    assert udim.pattern_name("LOK_Height_Raw", "udim", "_", ".png") == "LOK_Height_Raw_<UDIM>.png"
    # measured: rock<UVTILE>.png loads rock_u1_v1.png; rock_<UVTILE> renders black
    assert udim.pattern_name("rock", "uvtile", "", ".png") == "rock<UVTILE>.png"


def test_has_token_and_strip_token_are_case_insensitive():
    assert udim.has_token("/tex/rock.<UDIM>.png")
    assert udim.has_token("relative:///tex/rock<uvtile>.png")
    assert not udim.has_token("/tex/rock.1001.png")
    assert not udim.has_token(None)
    assert udim.strip_token("rock_BaseColor.<UDIM>") == "rock_BaseColor"
    assert udim.strip_token("LOK_Height_Raw_<udim>") == "LOK_Height_Raw"
    assert udim.strip_token("rock<UVTILE>") == "rock"


def test_tile_regex_and_tile_number():
    rx = udim.tile_regex("/tex/rock_BaseColor.<UDIM>.png")
    assert udim.tile_number(rx.fullmatch("/tex/rock_BaseColor.1002.png")) == 1002
    assert rx.fullmatch("/TEX/ROCK_basecolor.1002.PNG") is not None
    assert rx.fullmatch("/tex/rock_BaseColor.png") is None
    assert rx.fullmatch("/tex/rock_Roughness.1002.png") is None
    rx = udim.tile_regex("rock<UVTILE>.png")
    assert udim.tile_number(rx.fullmatch("rock_u2_v3.png")) == 1022
    assert udim.tile_regex("/tex/rock.png") is None


def test_tile_path_inverts_the_pattern():
    assert udim.tile_path("4K/rock_Height.<UDIM>.exr", 1005) == "4K/rock_Height.1005.exr"
    assert udim.tile_path("rock<UVTILE>.png", 1012) == "rock_u2_v2.png"
    assert udim.tile_path("rock.png", 1001) == "rock.png"


def test_list_tiles_reads_the_folder_once_and_sorts(tmp_path):
    for name in ("a_col.1002.png", "a_col.1001.png", "a_col.1011.png",
                 "a_rough.1001.png", "a_col.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert udim.list_tiles(str(tmp_path / "a_col.<UDIM>.png")) == [1001, 1002, 1011]
    assert udim.list_tiles(str(tmp_path / "missing.<UDIM>.png")) == []
    assert udim.list_tiles(str(tmp_path / "nope" / "a.<UDIM>.png")) == []  # unreadable dir
    assert udim.list_tiles(str(tmp_path / "a_col.png")) == []  # no token


def test_list_tiles_uses_injected_listdir():
    seen = []

    def listdir(folder):
        seen.append(folder)
        return ["r_u1_v1.png", "r_u2_v1.png", "r_u1_v1.exr"]

    assert udim.list_tiles("/f/r<UVTILE>.png", listdir=listdir) == [1001, 1002]
    assert seen == ["/f"]


def test_format_tiles_compacts_runs():
    assert udim.format_tiles([1001, 1002, 1003, 1004, 1006, 1007, 1008, 1009, 1010]) \
        == "1001–1004, 1006–1010"
    assert udim.format_tiles([1005]) == "1005"
    assert udim.format_tiles([1002, 1001, 1001, 1011]) == "1001–1002, 1011"
    assert udim.format_tiles([]) == ""


def test_list_tiles_matches_nfd_entries_against_nfc_pattern():
    """macOS/SMB can hand back decomposed names; the accented basename must
    still find its tiles instead of reading as missing."""
    import unicodedata
    nfc = unicodedata.normalize("NFC", "cañón_<UDIM>.png")
    nfd = unicodedata.normalize("NFD", "cañón_1001.png")
    assert nfc != unicodedata.normalize("NFD", nfc)

    def listdir(folder):
        return [nfd, unicodedata.normalize("NFD", "cañón_1002.png")]

    assert udim.list_tiles("/f/" + nfc, listdir=listdir) == [1001, 1002]


# --- v1.43: tiles from UVs (QC #14) --------------------------------------
# Measured (docs/research/2026-10-29-redshift-udim.md): 1011 is C4D UV
# v in [-1, 0]; v in [1, 2] and u past the 10th column render black.

def test_tile_of_uv_follows_the_measured_c4d_rows():
    assert udim.tile_of_uv(0.5, 0.5) == 1001
    assert udim.tile_of_uv(1.5, 0.5) == 1002
    assert udim.tile_of_uv(9.5, 0.5) == 1010
    assert udim.tile_of_uv(0.5, -0.5) == 1011
    assert udim.tile_of_uv(2.5, -1.5) == 1023


def test_tile_of_uv_outside_the_addressable_range_is_none():
    assert udim.tile_of_uv(0.5, 1.5) is None    # row above 1001: black
    assert udim.tile_of_uv(-0.5, 0.5) is None
    assert udim.tile_of_uv(10.5, 0.5) is None


def _quad(u0, v0, u1, v1):
    """8 floats in the UVW tag's low-level order: a, b, c, d as (u, v)."""
    return [u0, v1, u0, v0, u1, v0, u1, v1]


def test_tiles_of_polygons_uses_each_polygon_centroid():
    floats = _quad(0, 0, 1, 1) + _quad(1, 0, 2, 1) + _quad(0, -1, 1, 0)
    assert udim.tiles_of_polygons(floats) == {1001, 1002, 1011}


def test_tiles_of_polygons_triangle_repeats_c_in_d():
    tri = [1.1, 0.1, 1.9, 0.1, 1.5, 0.9, 1.5, 0.9]
    assert udim.tiles_of_polygons(tri) == {1002}


def test_tiles_of_polygons_restricted_to_indices():
    floats = _quad(0, 0, 1, 1) + _quad(1, 0, 2, 1) + _quad(2, 0, 3, 1)
    assert udim.tiles_of_polygons(floats, [0, 2]) == {1001, 1003}
    assert udim.tiles_of_polygons(floats, []) == set()


def test_tiles_of_polygons_reports_out_of_range_as_none():
    floats = _quad(0, 0, 1, 1) + _quad(0, 1, 1, 2)
    assert udim.tiles_of_polygons(floats) == {1001, None}


def test_tile_gaps_names_the_tiles_and_maps_that_lack_them():
    maps = [("rock_Base.<UDIM>.png", [1001, 1002]), ("rock_Rough.<UDIM>.png", [1001])]
    assert udim.tile_gaps({1001, 1002, 1003}, maps) == {
        "missing": [1002, 1003], "maps": ["rock_Base.<UDIM>.png", "rock_Rough.<UDIM>.png"],
        "out_of_range": False}


def test_tile_gaps_none_when_every_used_tile_has_a_texture():
    assert udim.tile_gaps({1001}, [("a.<UDIM>.png", [1001, 1002])]) is None
    assert udim.tile_gaps(set(), [("a.<UDIM>.png", [1001])]) is None


def test_tile_gaps_flags_uvs_no_tile_can_address():
    assert udim.tile_gaps({1001, None}, [("a.<UDIM>.png", [1001])]) == {
        "missing": [], "maps": [], "out_of_range": True}


# ── Redshift resolution (measured 2026-10-30,
#    docs/research/2026-10-30-redshift-udim-needs-tile-1001.md) ──────────

def test_redshift_unresolved_without_tile_1001():
    # the LOK grip: its only tile is 1005 — Redshift reports Not Found
    assert udim.redshift_unresolved("/p/tex/grip_Base.<UDIM>.png", [1005]) == "no_1001"
    assert udim.redshift_unresolved("/p/tex/a.<UDIM>.png", [1002]) == "no_1001"


def test_redshift_resolves_a_pattern_with_tile_1001():
    assert udim.redshift_unresolved("/p/tex/a.<UDIM>.png", [1001, 1005]) is None
    assert udim.redshift_unresolved("/p/shot_2001/a.<UDIM>.png", [1001]) is None
    assert udim.redshift_unresolved("/p/shot_1002/a.<UDIM>.png", [1001]) is None


def test_redshift_unresolved_with_1001_elsewhere_in_the_path():
    # Redshift re-patterns EVERY 1001 of the 1001 tile's path
    assert udim.redshift_unresolved("/p/shot_1001/a.<UDIM>.png", [1001]) == "1001_in_path"
    assert udim.redshift_unresolved(r"D:\shots\sh1001x\a_<udim>.png", [1001, 1002]) == "1001_in_path"
    assert udim.redshift_unresolved("/p/tex/rock_1001_<UDIM>.png", [1001]) == "1001_in_path"
    # checked before the tile: the path breaks it whatever is on disk
    assert udim.redshift_unresolved("/p/shot_1001/a.<UDIM>.png", [1005]) == "1001_in_path"


def test_redshift_unresolved_says_nothing_it_has_not_measured():
    assert udim.redshift_unresolved("/p/tex/a<UVTILE>.png", [1005]) is None  # UVTILE: unmeasured
    assert udim.redshift_unresolved("/p/tex/plain.png", []) is None
