# tests/test_manifest.py
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "plugin" / "sentinel" / "manifest.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_manifest_under_test", MANIFEST_PATH
)
manifest = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manifest
spec.loader.exec_module(manifest)


def _record(path, resolved, status, source_type="rs_node",
            channel="Diffuse", host_name="MAT_wood"):
    return {
        "current_path": path,
        "resolved": resolved,
        "status": status,
        "source_type": source_type,
        "channel": channel,
        "host_name": host_name,
    }


class TestClassifyAsset:
    def test_resolved_inside_package_is_collected(self, tmp_path):
        tex = tmp_path / "tex" / "wood.jpg"
        tex.parent.mkdir()
        tex.write_bytes(b"x")
        state = manifest.classify_asset("ok", str(tex), str(tmp_path))
        assert state == manifest.ASSET_COLLECTED

    def test_resolved_outside_package_is_external(self, tmp_path):
        outside = tmp_path.parent / f"{tmp_path.name}_outside.jpg"
        outside.write_bytes(b"x")
        state = manifest.classify_asset("absolute", str(outside), str(tmp_path))
        assert state == manifest.ASSET_EXTERNAL

    def test_scanner_missing_is_missing(self, tmp_path):
        state = manifest.classify_asset(
            "missing", str(tmp_path / "tex" / "gone.jpg"), str(tmp_path))
        assert state == manifest.ASSET_MISSING

    def test_absolute_resolving_inside_package_is_collected(self, tmp_path):
        # SaveProject deja rutas re-linkadas; una absoluta que apunta DENTRO
        # del paquete cuenta como collected, no external.
        tex = tmp_path / "tex" / "hdr.exr"
        tex.parent.mkdir()
        tex.write_bytes(b"x")
        state = manifest.classify_asset("absolute", str(tex), str(tmp_path))
        assert state == manifest.ASSET_COLLECTED

    def test_asset_uri_and_empty_are_skipped(self, tmp_path):
        assert manifest.classify_asset("asset_uri", None, str(tmp_path)) == ""
        assert manifest.classify_asset("empty", None, str(tmp_path)) == ""

    def test_resolved_none_with_ok_status_is_missing(self, tmp_path):
        # Defensa: status "ok" pero sin ruta resuelta no puede afirmarse.
        assert (manifest.classify_asset("ok", None, str(tmp_path))
                == manifest.ASSET_MISSING)


class TestBuildAssetEntries:
    def test_collected_entry_stores_package_relative_path(self, tmp_path):
        tex = tmp_path / "tex" / "wood.jpg"
        tex.parent.mkdir()
        tex.write_bytes(b"x")
        entries = manifest.build_asset_entries(
            [_record("tex/wood.jpg", str(tex), "ok")], str(tmp_path))
        assert len(entries) == 1
        e = entries[0]
        assert e["state"] == manifest.ASSET_COLLECTED
        assert e["path"] == "tex/wood.jpg"
        assert e["original_path"] == "tex/wood.jpg"
        assert e["hash"] is None
        assert e["host"] == "MAT_wood"

    def test_missing_entry_keeps_original_path(self, tmp_path):
        entries = manifest.build_asset_entries(
            [_record("tex/gone.jpg", str(tmp_path / "tex" / "gone.jpg"),
                     "missing")], str(tmp_path))
        assert entries[0]["state"] == manifest.ASSET_MISSING
        assert entries[0]["path"] == "tex/gone.jpg"

    def test_skipped_statuses_produce_no_entries(self, tmp_path):
        entries = manifest.build_asset_entries(
            [_record("asset:foo", None, "asset_uri"),
             _record("", None, "empty")], str(tmp_path))
        assert entries == []

    def test_duplicate_paths_deduped(self, tmp_path):
        tex = tmp_path / "tex" / "wood.jpg"
        tex.parent.mkdir()
        tex.write_bytes(b"x")
        entries = manifest.build_asset_entries(
            [_record("tex/wood.jpg", str(tex), "ok", channel="Diffuse"),
             _record("tex/wood.jpg", str(tex), "ok", channel="Bump")],
            str(tmp_path))
        assert len(entries) == 1


class TestSummarize:
    def test_counts(self, tmp_path):
        tex = tmp_path / "tex" / "a.jpg"
        tex.parent.mkdir()
        tex.write_bytes(b"x")
        outside = tmp_path.parent / f"{tmp_path.name}_b.jpg"
        outside.write_bytes(b"x")
        entries = manifest.build_asset_entries(
            [_record("tex/a.jpg", str(tex), "ok"),
             _record(str(outside), str(outside), "absolute",
                     host_name="MAT_metal"),
             _record("tex/c.jpg", str(tmp_path / "tex" / "c.jpg"),
                     "missing", host_name="MAT_glass")],
            str(tmp_path))
        s = manifest.summarize_assets(entries)
        assert s == {"total": 3, "collected": 1, "missing": 1, "external": 1}


class TestMergeIntoManifest:
    def test_merge_adds_asset_section(self):
        base = {"sentinel_manifest": True, "qc": {"passed": 11}}
        entries = [{"path": "tex/a.jpg", "original_path": "tex/a.jpg",
                    "source_type": "rs_node", "channel": "Diffuse",
                    "host": "MAT", "state": manifest.ASSET_COLLECTED,
                    "hash": None}]
        out = manifest.merge_into_manifest(
            base, entries, "ok",
            [{"plugin_id": 1028083, "name": "Alembic"}])
        assert out is base
        assert out["assets_schema"] == manifest.ASSETS_SCHEMA_VERSION
        assert out["scan_status"] == "ok"
        assert out["asset_summary"]["collected"] == 1
        assert out["required_plugins"][0]["name"] == "Alembic"
        assert out["plugin_inventory_scope"] == "objects+tags+materials"
        assert out["qc"] == {"passed": 11}  # lo existente no se toca

    def test_failed_scan_records_empty_assets_with_status(self):
        out = manifest.merge_into_manifest({}, [], "failed", [])
        assert out["scan_status"] == "failed"
        assert out["assets"] == []
        assert out["asset_summary"]["total"] == 0


class TestVerifyPackage:
    def _manifest_with(self, tmp_path):
        tex = tmp_path / "tex" / "a.jpg"
        tex.parent.mkdir()
        tex.write_bytes(b"x")
        entries = manifest.build_asset_entries(
            [_record("tex/a.jpg", str(tex), "ok"),
             _record("tex/gone.jpg", str(tmp_path / "tex" / "gone.jpg"),
                     "missing", host_name="MAT_b")],
            str(tmp_path))
        return manifest.merge_into_manifest({}, entries, "ok", [])

    def test_intact_package_verifies_clean(self, tmp_path):
        m = self._manifest_with(tmp_path)
        result = manifest.verify_package(m, str(tmp_path))
        assert result["checked"] == 1          # solo collected se re-chequea
        assert result["ok"] == 1
        assert result["lost"] == []
        assert result["still_missing"] == ["tex/gone.jpg"]

    def test_lost_in_transfer_detected(self, tmp_path):
        m = self._manifest_with(tmp_path)
        (tmp_path / "tex" / "a.jpg").unlink()   # se perdió al transferir
        result = manifest.verify_package(m, str(tmp_path))
        assert result["ok"] == 0
        assert result["lost"] == ["tex/a.jpg"]

    def test_failed_scan_manifest_reports_status(self, tmp_path):
        m = manifest.merge_into_manifest({}, [], "failed", [])
        result = manifest.verify_package(m, str(tmp_path))
        assert result["scan_status"] == "failed"
        assert result["checked"] == 0


class TestManifestIO:
    def test_atomic_write_and_load_roundtrip(self, tmp_path):
        target = tmp_path / "sentinel_manifest.json"
        data = manifest.merge_into_manifest(
            {"sentinel_manifest": True}, [], "ok", [])
        assert manifest.write_manifest_json(data, str(target)) is True
        loaded = manifest.load_manifest_json(str(target))
        assert loaded["scan_status"] == "ok"
        assert not list(tmp_path.glob("*.tmp.*"))   # tmp limpiado

    def test_load_missing_or_corrupt_returns_none(self, tmp_path):
        assert manifest.load_manifest_json(str(tmp_path / "no.json")) is None
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert manifest.load_manifest_json(str(bad)) is None

    def test_write_failure_returns_false_and_cleans_tmp(self, tmp_path):
        target = tmp_path / "sentinel_manifest.json"
        bad = {"assets": {1, 2, 3}}  # a set is not JSON-serializable
        assert manifest.write_manifest_json(bad, str(target)) is False
        assert not target.exists()
        assert not list(tmp_path.glob("*.tmp.*"))


class TestRealisticPackageTree:
    """Simula el árbol que SaveProject produce: tex/ + subcarpetas +
    una referencia externa y una perdida — el caso de la entrega real."""

    def test_mixed_package(self, tmp_path):
        pkg = tmp_path / "delivery"
        (pkg / "tex").mkdir(parents=True)
        (pkg / "tex" / "wood.jpg").write_bytes(b"x" * 100)
        (pkg / "tex" / "hdr.exr").write_bytes(b"x" * 100)
        external = tmp_path / "shared_lib" / "metal.jpg"
        external.parent.mkdir()
        external.write_bytes(b"x")

        records = [
            _record("tex/wood.jpg", str(pkg / "tex" / "wood.jpg"), "ok"),
            _record("tex/hdr.exr", str(pkg / "tex" / "hdr.exr"), "ok",
                    source_type="rs_object_fileref", channel="Dome HDR"),
            _record(str(external), str(external), "absolute",
                    host_name="MAT_metal"),
            _record("caches/sim.abc", str(pkg / "caches" / "sim.abc"),
                    "missing", source_type="alembic"),
        ]
        entries = manifest.build_asset_entries(records, str(pkg))
        m = manifest.merge_into_manifest(
            {"sentinel_manifest": True}, entries, "ok",
            [{"plugin_id": 1028083, "name": "Alembic"}])
        s = m["asset_summary"]
        assert (s["collected"], s["missing"], s["external"]) == (2, 1, 1)

        # Recepción: el receptor pierde el HDR al transferir.
        (pkg / "tex" / "hdr.exr").unlink()
        v = manifest.verify_package(m, str(pkg))
        assert v["lost"] == ["tex/hdr.exr"]


class TestCrossPlatformPaths:
    """A package collected on Windows stores forward-slash paths so a
    macOS/Linux receiver's verify_package doesn't report every asset LOST
    just because os.sep differs from the sender's."""

    def test_serialized_manifest_never_contains_backslashes(self, tmp_path):
        pkg = tmp_path / "delivery"
        (pkg / "tex" / "sub").mkdir(parents=True)
        (pkg / "tex" / "sub" / "wood.jpg").write_bytes(b"x")
        entries = manifest.build_asset_entries(
            [_record("tex/sub/wood.jpg",
                     str(pkg / "tex" / "sub" / "wood.jpg"), "ok")],
            str(pkg))
        m = manifest.merge_into_manifest({}, entries, "ok", [])
        serialized = json.dumps(m["assets"])
        assert "\\" not in serialized

    def test_verify_accepts_forward_slash_path_on_any_platform(self, tmp_path):
        pkg = tmp_path / "delivery"
        (pkg / "tex").mkdir(parents=True)
        (pkg / "tex" / "wood.jpg").write_bytes(b"x")
        # Simulates a manifest written by a Windows sender: path uses "/"
        # explicitly (as build_asset_entries now normalizes to).
        m = {"assets": [{"path": "tex/wood.jpg",
                          "state": manifest.ASSET_COLLECTED}]}
        result = manifest.verify_package(m, str(pkg))
        assert result["ok"] == 1
        assert result["lost"] == []


class TestFilterNativePlugins:
    """IDs nativos de Maxon viven en rango de plugin (>=1M) y contaminan
    el inventario de 'requires plugins' — verificado en producción
    (SHOT_18: XPresso/SDS/Cloner/Data Tag/Bevel listados junto a RS)."""

    def test_native_ids_filtered_renderer_kept(self):
        plugins = [
            {"plugin_id": 1001149, "name": "XPresso"},
            {"plugin_id": 1007455, "name": "Subdivision Surface"},
            {"plugin_id": 1018544, "name": "Cloner"},
            {"plugin_id": 1018625, "name": "Data Tag"},
            {"plugin_id": 431000028, "name": "Bevel"},
            {"plugin_id": 1036222, "name": "RS Object"},
            {"plugin_id": 1036751, "name": "RS Light"},
        ]
        kept = manifest.filter_native_plugins(plugins)
        assert [p["name"] for p in kept] == ["RS Object", "RS Light"]

    def test_empty_and_unknown_pass_through(self):
        assert manifest.filter_native_plugins([]) == []
        unknown = [{"plugin_id": 1029508, "name": "Octane ImageTexture"}]
        assert manifest.filter_native_plugins(unknown) == unknown
