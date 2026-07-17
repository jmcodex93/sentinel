"""Pure-engine tests for the Asset Hub inventory (plugin/sentinel/assets.py)."""
import os
import zipfile

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
        assert r["tex_idxs"] == [0]
        assert r["owners"] == [("RS_Mat", "material", "Base Color")]
        assert r["asset_type"] == "texture"

    def test_generic_only_is_readonly(self):
        out = assets.merge_inventories([], [_gen("/p/luts/show.cube")])
        r = out[0]
        assert r["repathable"] is False
        assert r["tex_idx"] is None
        assert r["tex_idxs"] == []
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
        # Every colliding tex_idx is kept so repathing updates all shaders,
        # not just the first record that claimed the shared path.
        assert out[0]["tex_idxs"] == [0, 1]
        assert out[0]["tex_idx"] == 0

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

    def test_empty_texture_path_keeps_status(self):
        out = assets.merge_inventories([_tex(" ", status="empty", resolved=None, idx=0)], [])
        assert len(out) == 1
        r = out[0]
        assert r["status"] == "empty"
        assert r["repathable"] is True
        assert r["tex_idx"] == 0
        assert r["key"].startswith("__empty__tex__")

    def test_empty_generic_path_keeps_status(self):
        out = assets.merge_inventories([], [_gen("", exists=False)])
        assert len(out) == 1
        r = out[0]
        assert r["status"] == "empty"
        assert r["repathable"] is False
        assert r["key"].startswith("__empty__gen__")


class TestTotalsAndSizes:
    def test_format_size(self):
        assert assets.format_size(None) == "—"
        assert assets.format_size(-1) == "?"
        assert assets.format_size(512) == "512 B"
        assert assets.format_size(48 * 1024 * 1024) == "48.0 MB"
        assert assets.format_size(int(1.94 * 1024**3)) == "1.94 GB"

    def test_compute_totals(self):
        recs = assets.merge_inventories(
            [_tex("/p/a.png", status="missing"),
             _tex("/p/b.png", status="absolute"),
             _tex("/p/c.abc")], [])
        recs[1]["size_bytes"] = 100
        recs[2]["size_bytes"] = 50
        t = assets.compute_totals(recs)
        assert t["count"] == 3 and t["missing"] == 1 and t["absolute"] == 1
        assert t["total_bytes"] == 150
        assert t["unsized"] == 1          # the missing one has size None
        assert t["by_type"]["texture"] == 2 and t["by_type"]["alembic"] == 1

    def test_stat_sizes_batch(self, tmp_path):
        f = tmp_path / "a.png"; f.write_bytes(b"x" * 10)
        recs = [
            {"resolved_path": str(f), "size_bytes": None},
            {"resolved_path": None, "size_bytes": None},        # missing: skip
            {"resolved_path": str(tmp_path / "gone.png"), "size_bytes": None},
        ]
        nxt = assets.stat_sizes_batch(recs, 0, 2)
        assert nxt == 2
        assert recs[0]["size_bytes"] == 10
        assert recs[1]["size_bytes"] is None
        nxt = assets.stat_sizes_batch(recs, nxt, 5)
        assert nxt == 3                                          # clamped to len
        assert recs[2]["size_bytes"] == -1                       # stat failed


class TestSearchFolderForMissing:
    def test_build_index_and_cap(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.png").write_bytes(b"x")
        (tmp_path / "sub" / "B.PNG").write_bytes(b"x")
        idx, truncated = assets.build_file_index(str(tmp_path))
        assert truncated is False
        assert len(idx["a.png"]) == 1
        assert len(idx["b.png"]) == 1          # case-insensitive key

    def test_cap_marks_truncated(self, tmp_path):
        for i in range(5):
            (tmp_path / f"f{i}.png").write_bytes(b"x")
        idx, truncated = assets.build_file_index(str(tmp_path), cap=3)
        assert truncated is True
        assert sum(len(v) for v in idx.values()) == 3

    def test_match_unique_and_ambiguous_and_none(self):
        recs = [
            {"key": "k1", "status": "missing", "path": "old/tex/wood.png"},
            {"key": "k2", "status": "missing", "path": "old/rock.png"},
            {"key": "k3", "status": "missing", "path": "old/gone.png"},
            {"key": "k4", "status": "ok", "path": "tex/fine.png"},
        ]
        idx = {"wood.png": ["/new/tex/wood.png"],
               "rock.png": ["/a/rock.png", "/b/rock.png"],
               "fine.png": ["/x/fine.png"]}
        m = assets.match_missing_in_folder(recs, idx)
        assert m["k1"] == {"match": "/new/tex/wood.png"}
        assert m["k2"] == {"ambiguous": ["/a/rock.png", "/b/rock.png"]}
        assert "k3" not in m
        assert "k4" not in m                    # never touches non-missing

    def test_match_windows_style_path_on_any_platform(self):
        # A missing record whose stored path uses Windows-style backslash
        # separators (e.g. authored on Windows, opened on macOS) must still
        # resolve to its basename via the normalized path key, not
        # os.path.basename (which is a no-op for backslash paths on POSIX).
        recs = [
            {"key": "k1", "status": "missing", "path": "D:\\old\\tex\\wood.png"},
        ]
        idx = {"wood.png": ["/new/tex/wood.png"]}
        m = assets.match_missing_in_folder(recs, idx)
        assert m["k1"] == {"match": "/new/tex/wood.png"}


class TestCreateZip:
    def test_zips_tree_and_reports(self, tmp_path):
        d = tmp_path / "delivery"; (d / "tex").mkdir(parents=True)
        (d / "scene.c4d").write_bytes(b"c4d")
        (d / "tex" / "a.png").write_bytes(b"png")
        seen = []
        result = assets.create_zip_archive(
            str(d), on_progress=lambda i, n: seen.append((i, n)))
        assert result["files"] == 2
        assert result["zip_path"] == str(tmp_path / "delivery.zip")
        assert seen[-1] == (2, 2)
        with zipfile.ZipFile(result["zip_path"]) as zf:
            names = sorted(zf.namelist())
        assert names == ["delivery/scene.c4d", "delivery/tex/a.png"]
        assert d.exists()                       # source folder kept

    def test_explicit_zip_path(self, tmp_path):
        d = tmp_path / "delivery"; d.mkdir()
        (d / "scene.c4d").write_bytes(b"x")
        out = str(tmp_path / "custom.zip")
        result = assets.create_zip_archive(str(d), zip_path=out)
        assert result["zip_path"] == out and os.path.exists(out)


class TestFitColumnWidths:
    """AssetListArea's fit-to-viewport invariant (Asset Hub UI polish):
    stored column widths may come from an earlier, wider window and must
    never be honored verbatim past the current viewport budget."""

    ORDER = ("name", "type", "size", "used")

    def test_under_budget_passes_through_unchanged(self):
        stored = {"name": 210, "type": 110, "size": 64, "used": 180}  # sum=564
        out = assets.fit_column_widths(stored, self.ORDER, budget=700, min_width=40)
        assert out == stored
        # Must be a copy, not the same object — caller mutates it freely
        # without corrupting the source dict.
        assert out is not stored

    def test_exact_budget_passes_through_unchanged(self):
        stored = {"name": 100, "type": 100, "size": 100, "used": 100}  # sum=400
        out = assets.fit_column_widths(stored, self.ORDER, budget=400, min_width=40)
        assert out == stored

    def test_over_budget_shrinks_proportionally_and_fits(self):
        # sum=564, must fit into budget=400 -> shrink each proportionally,
        # no column needs the min-width floor, so it fits on the first try.
        stored = {"name": 210, "type": 110, "size": 64, "used": 180}
        out = assets.fit_column_widths(stored, self.ORDER, budget=400, min_width=40)
        assert out == {"name": 148, "type": 78, "size": 45, "used": 127}
        assert sum(out.values()) <= 400
        # Proportional: relative order of the stored widths is preserved
        # (name > used > type > size, same as the input).
        assert out["name"] > out["used"] > out["type"] > out["size"]

    def test_over_budget_result_never_exceeds_budget_when_it_fits(self):
        # A budget comfortably above 4 * min_width always yields a result
        # that fits, whether or not the min-width floor engages.
        stored = {"name": 500, "type": 400, "size": 300, "used": 300}  # sum=1500
        for budget in (1200, 800, 400):
            out = assets.fit_column_widths(stored, self.ORDER, budget, min_width=40)
            assert sum(out.values()) <= budget
            assert all(out[c] >= 40 for c in self.ORDER)

    def test_does_not_mutate_stored_dict(self):
        stored = {"name": 500, "type": 400, "size": 300, "used": 300}
        original = dict(stored)
        assets.fit_column_widths(stored, self.ORDER, budget=200, min_width=40)
        assert stored == original

    def test_degenerate_budget_floors_everything_at_min(self):
        # Even 4 * min_width doesn't fit -> every column floors at min,
        # accepting the residual overlap (no valid layout exists).
        stored = {"name": 500, "type": 400, "size": 300, "used": 300}
        out = assets.fit_column_widths(stored, self.ORDER, budget=50, min_width=40)
        assert out == {c: 40 for c in self.ORDER}

    def test_zero_or_negative_budget_floors_everything_at_min(self):
        stored = {"name": 210, "type": 110, "size": 64, "used": 180}
        for budget in (0, -50):
            out = assets.fit_column_widths(stored, self.ORDER, budget, min_width=40)
            assert out == {c: 40 for c in self.ORDER}

    def test_missing_keys_in_stored_default_to_min_width(self):
        out = assets.fit_column_widths({"name": 100}, self.ORDER,
                                       budget=700, min_width=40)
        assert out["name"] == 100
        assert out["type"] == out["size"] == out["used"] == 40
