# Collect Confiable (I4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El Scene Collector deja de «copiar y confiar»: tras el `SaveProject()`, reabre el paquete colectado, re-escanea sus dependencias, clasifica cada asset (collected / missing / external), lo sella en el `sentinel_manifest.json` existente, y permite al receptor ver el resumen de entrega y re-verificar el paquete en destino.

**Architecture:** Motor puro `plugin/sentinel/manifest.py` (stdlib, sin `import c4d`, pytest-able con árboles dummy) + adaptador fino en `ui/flows.py` (re-scan post-copia dentro de `collect_scene`) + recepción ligera en `ui/panel.py` (botón en la pestaña Versions). Extiende el `sentinel_manifest.json` que `collect_scene` ya escribe — no crea sidecar nuevo.

**Tech Stack:** Python 3 (runtime C4D 2026), pytest (suite existente 171+), `c4d.documents.LoadDocument/KillDocument`, `scan_all_texture_paths` (v1.5.7).

## Global Constraints

- `plugin/sentinel/manifest.py` es stdlib-only: **prohibido `import c4d`** (patrón `postrender.py`, KTD1).
- Escritura de JSON siempre atómica: tmp + `os.replace` (patrón `baseline.py:228-237`).
- Claves del manifiesto en inglés (convención del manifiesto existente: `missing_list`, `total_size_mb`).
- **Nunca un manifiesto silenciosamente vacío**: si el re-scan falla, `"scan_status": "failed"` visible en manifiesto y diálogo.
- Con assets faltantes el Collect **no se bloquea ni se borra**: se marca en rojo en el diálogo.
- Recarga de plugin = reiniciar C4D (nunca purgar `sys.modules`).
- Tests puros con el patrón `importlib.util.spec_from_file_location` de `tests/test_postrender.py:11-21`.
- Peldaño final innegociable: colectar una entrega real de producción y verificar el manifiesto contra contenido conocido **antes de merge** (lección I1).

## File Structure

- `plugin/sentinel/manifest.py` — **nuevo**. Motor puro: clasificación de assets, resumen, verificación en destino, merge en dict de manifiesto.
- `plugin/sentinel/ui/flows.py` — modificar `collect_scene` (Phase 3, ~línea 650): re-scan post-copia + merge + diálogo ampliado.
- `plugin/sentinel/ui/panel.py` — añadir botón «Delivery Summary...» en la pestaña Versions + diálogo de recepción.
- `tests/test_manifest.py` — **nuevo**. Tests puros del motor.

---

### Task 1: Motor puro — clasificación de assets y construcción de entradas

**Files:**
- Create: `plugin/sentinel/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: nada (motor puro; los TextureRecords llegan ya convertidos a dicts planos por el adaptador de Task 3).
- Produces (Task 2, 3 y 4 dependen de esto):
  - `ASSET_COLLECTED = "collected"`, `ASSET_MISSING = "missing"`, `ASSET_EXTERNAL = "external"` (constantes str)
  - `classify_asset(status: str, resolved: str|None, package_root: str) -> str` — mapea el status del escáner (`ok|absolute|missing|asset_uri|empty`) + ruta resuelta a un estado de asset, o `""` si no es un asset de filesystem (asset_uri/empty se excluyen).
  - `build_asset_entries(scan_records: list[dict], package_root: str) -> list[dict]` — cada scan_record es `{"current_path": str, "resolved": str|None, "status": str, "source_type": str, "channel": str, "host_name": str}`; devuelve entradas `{"path": str (relativa al paquete si collected, si no la original), "original_path": str, "source_type": str, "channel": str, "host": str, "state": str, "hash": None}`.
  - `summarize_assets(entries: list[dict]) -> dict` — `{"total": int, "collected": int, "missing": int, "external": int}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manifest.py
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

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
        assert e["path"] == os.path.join("tex", "wood.jpg")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: FAIL en el `exec_module` — `FileNotFoundError` (manifest.py no existe).

- [ ] **Step 3: Write minimal implementation**

```python
# plugin/sentinel/manifest.py
"""Delivery manifest engine — pure, stdlib-only (NO ``import c4d``).

Classifies delivery-package assets from pre-flattened texture-scanner
records, verifies a package on the receiving side, and merges the asset
section into the collector's existing ``sentinel_manifest.json`` dict.

C4D reads live in the thin adapter inside ``ui/flows.py`` — this module
must stay importable (and testable) without Cinema 4D. Same contract as
``postrender.py`` (KTD1).
"""

import json
import os

ASSET_COLLECTED = "collected"
ASSET_MISSING = "missing"
ASSET_EXTERNAL = "external"

ASSETS_SCHEMA_VERSION = 1

# Scanner statuses that are not filesystem assets — excluded from the
# manifest (RS Asset Manager URIs, empty path slots).
_SKIP_STATUSES = ("asset_uri", "empty")


def _inside(path, root):
    """True if ``path`` is inside ``root`` (both made real/absolute)."""
    try:
        real_path = os.path.realpath(path)
        real_root = os.path.realpath(root)
        return os.path.commonpath([real_path, real_root]) == real_root
    except (ValueError, OSError):
        # Different drives on Windows, malformed paths.
        return False


def classify_asset(status, resolved, package_root):
    """Map a scanner (status, resolved) pair to an asset state.

    Returns "" for records that are not filesystem assets.
    """
    if status in _SKIP_STATUSES:
        return ""
    if status == "missing":
        return ASSET_MISSING
    if not resolved:
        # "ok"/"absolute" without a resolved path cannot be trusted.
        return ASSET_MISSING
    if not os.path.exists(resolved):
        return ASSET_MISSING
    if _inside(resolved, package_root):
        return ASSET_COLLECTED
    return ASSET_EXTERNAL


def build_asset_entries(scan_records, package_root):
    """Flatten scanner records into manifest asset entries.

    ``scan_records`` are plain dicts (no live C4D refs):
    ``{"current_path", "resolved", "status", "source_type", "channel",
    "host_name"}``. Dedupes by classified path.
    """
    entries = []
    seen = set()
    for rec in scan_records or []:
        state = classify_asset(
            rec.get("status", ""), rec.get("resolved"), package_root)
        if not state:
            continue
        if state == ASSET_COLLECTED:
            path = os.path.relpath(
                os.path.realpath(rec["resolved"]),
                os.path.realpath(package_root))
        else:
            path = rec.get("current_path", "")
        key = (path, state)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "path": path,
            "original_path": rec.get("current_path", ""),
            "source_type": rec.get("source_type", ""),
            "channel": rec.get("channel", ""),
            "host": rec.get("host_name", ""),
            "state": state,
            "hash": None,  # reservado (schema v1: siempre None)
        })
    return entries


def summarize_assets(entries):
    counts = {"total": len(entries), "collected": 0, "missing": 0,
              "external": 0}
    for e in entries:
        state = e.get("state")
        if state in counts:
            counts[state] += 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/manifest.py tests/test_manifest.py
git commit -m "feat(manifest): pure asset-classification engine for Collect Confiable (I4)"
```

---

### Task 2: Motor puro — verificación en destino y merge en el manifiesto

**Files:**
- Modify: `plugin/sentinel/manifest.py` (añadir al final)
- Test: `tests/test_manifest.py` (añadir clases)

**Interfaces:**
- Consumes: `build_asset_entries`, `summarize_assets`, `ASSET_*` (Task 1).
- Produces (Tasks 3 y 4 dependen de esto):
  - `merge_into_manifest(manifest_dict: dict, entries: list[dict], scan_status: str, required_plugins: list[dict]) -> dict` — muta y devuelve el dict: añade `assets_schema`, `scan_status`, `assets`, `asset_summary`, `required_plugins`.
  - `verify_package(manifest_dict: dict, package_root: str) -> dict` — re-comprueba en destino: `{"checked": int, "ok": int, "lost": [paths collected que ya no existen], "still_missing": [paths], "scan_status": str}`.
  - `write_manifest_json(manifest_dict: dict, path: str) -> bool` — escritura atómica tmp + `os.replace`.
  - `load_manifest_json(path: str) -> dict | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manifest.py — añadir al final

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
        assert result["still_missing"] == [os.path.join("tex", "gone.jpg")
                                           .replace(os.sep, "/")] or \
               result["still_missing"] == ["tex/gone.jpg"]

    def test_lost_in_transfer_detected(self, tmp_path):
        m = self._manifest_with(tmp_path)
        (tmp_path / "tex" / "a.jpg").unlink()   # se perdió al transferir
        result = manifest.verify_package(m, str(tmp_path))
        assert result["ok"] == 0
        assert result["lost"] == [os.path.join("tex", "a.jpg")]

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'merge_into_manifest'`.

- [ ] **Step 3: Write minimal implementation**

```python
# plugin/sentinel/manifest.py — añadir al final

def merge_into_manifest(manifest_dict, entries, scan_status,
                        required_plugins):
    """Merge the asset section into the collector's manifest dict.

    Never produces a silently-empty section: ``scan_status`` travels with
    the data so a failed re-scan is visible in the JSON itself.
    """
    manifest_dict["assets_schema"] = ASSETS_SCHEMA_VERSION
    manifest_dict["scan_status"] = scan_status
    manifest_dict["assets"] = list(entries or [])
    manifest_dict["asset_summary"] = summarize_assets(entries or [])
    manifest_dict["required_plugins"] = list(required_plugins or [])
    return manifest_dict


def verify_package(manifest_dict, package_root):
    """Receiver-side re-check of a collected package against its manifest."""
    result = {
        "checked": 0, "ok": 0, "lost": [], "still_missing": [],
        "scan_status": manifest_dict.get("scan_status", "unknown"),
    }
    for entry in manifest_dict.get("assets", []):
        state = entry.get("state")
        path = entry.get("path", "")
        if state == ASSET_COLLECTED:
            result["checked"] += 1
            if os.path.exists(os.path.join(package_root, path)):
                result["ok"] += 1
            else:
                result["lost"].append(path)
        elif state == ASSET_MISSING:
            result["still_missing"].append(path)
    return result


def write_manifest_json(manifest_dict, path):
    """Atomic write: tmp + os.replace (same pattern as baseline.py)."""
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(manifest_dict, handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except OSError:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def load_manifest_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_manifest.py -v`
Expected: PASS (19 tests). Ajusta la aserción de `still_missing` de
`test_intact_package_verifies_clean` al separador real que devuelva tu
plataforma si difiere (el motor guarda el path original del escáner para
missing — no lo normaliza).

- [ ] **Step 5: Run the full suite (regression)**

Run: `python3 -m pytest tests/ -v --ignore=tests/c4d_runner`
Expected: todo verde (171+ existentes + 19 nuevos).

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/manifest.py tests/test_manifest.py
git commit -m "feat(manifest): receiver-side verify + manifest merge + atomic IO"
```

---

### Task 3: Adaptador en Collect — re-scan post-copia dentro de `collect_scene`

**Files:**
- Modify: `plugin/sentinel/ui/flows.py` (Phase 3 de `collect_scene`, insertar antes de la escritura del manifiesto en `manifest_path`, ~línea 650 y ~785)

**Interfaces:**
- Consumes: `manifest.build_asset_entries`, `merge_into_manifest`, `write_manifest_json`, `summarize_assets` (Tasks 1-2); `scan_all_texture_paths` (`sentinel/textures.py:355`).
- Produces: función módulo-nivel `_rescan_collected_package(delivery_c4d_path, target_dir) -> tuple[list[dict], str, list[dict]]` (entries, scan_status, required_plugins) que Task 5 reutiliza en fixtures.

- [ ] **Step 1: Write the adapter function**

En `flows.py`, junto a las demás helpers del collector (tras `collect_scene` o antes, nivel módulo):

```python
def _rescan_collected_package(delivery_c4d_path, target_dir):
    """Reopen the collected .c4d and re-scan its dependencies.

    This is the step SaveProject skips: verifying the *result*. Loads the
    delivered scene into a temp document (never added to the GUI), scans
    every texture/cache reference on that copy, classifies against the
    package root, and inventories third-party plugin object/tag types.

    Returns (asset_entries, scan_status, required_plugins). On any load
    failure returns ([], "failed", []) — never a silently-empty result.
    """
    from sentinel import manifest as manifest_engine
    from sentinel.textures import scan_all_texture_paths

    tmp_doc = None
    try:
        tmp_doc = c4d.documents.LoadDocument(
            delivery_c4d_path,
            c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS,
            None,
        )
        if tmp_doc is None:
            safe_print("Scene Collector: re-scan LoadDocument failed")
            return [], "failed", []

        records = scan_all_texture_paths(tmp_doc) or []
        # Flatten: drop live C4D refs before handing to the pure engine.
        flat = [{
            "current_path": r.get("current_path", ""),
            "resolved": r.get("resolved"),
            "status": r.get("status", ""),
            "source_type": r.get("source_type", ""),
            "channel": r.get("channel", ""),
            "host_name": r.get("host_name", ""),
        } for r in records]
        entries = manifest_engine.build_asset_entries(flat, target_dir)

        # Plugin inventory: object/tag types in the plugin-ID range
        # (>= 1,000,000 — C4D built-ins live below; Redshift/Alembic/
        # third-party all show up here, which is exactly the point:
        # "this scene needs X to open correctly").
        required = {}
        first = tmp_doc.GetFirstObject()
        if first:
            stack = [first]
            while stack:
                obj = stack.pop()
                while obj:
                    type_id = obj.GetType()
                    if type_id >= 1_000_000 and type_id not in required:
                        required[type_id] = obj.GetTypeName() or "<plugin>"
                    tag = obj.GetFirstTag()
                    while tag:
                        tag_id = tag.GetType()
                        if tag_id >= 1_000_000 and tag_id not in required:
                            required[tag_id] = tag.GetTypeName() or "<plugin>"
                        tag = tag.GetNext()
                    child = obj.GetDown()
                    if child:
                        stack.append(child)
                    obj = obj.GetNext()
        required_plugins = [
            {"plugin_id": pid, "name": name}
            for pid, name in sorted(required.items())
        ]
        return entries, "ok", required_plugins
    except Exception as e:
        safe_print(f"Scene Collector: re-scan error: {e}")
        return [], "failed", []
    finally:
        if tmp_doc is not None:
            try:
                c4d.documents.KillDocument(tmp_doc)
            except Exception:
                pass
```

- [ ] **Step 2: Wire it into Phase 3 of `collect_scene`**

Justo después del bloque «Phase 2.5: Rename» (tras la línea que loguea
`expected file ... not found after SaveProject`) y **antes** de construir
el dict `manifest` en Phase 3, añadir:

```python
    # ── Phase 2.6: Re-scan the collected package (Collect Confiable, I4) ──
    safe_print("Scene Collector: Re-scanning collected package...")
    delivered_c4d = desired_at if os.path.exists(desired_at) else saved_at
    asset_entries, scan_status, required_plugins = \
        _rescan_collected_package(delivered_c4d, target_dir)
```

Y donde se construye/escribe el manifiesto (antes del `json.dump` actual en
`manifest_path`, ~línea 786), sustituir la escritura directa por:

```python
    from sentinel import manifest as manifest_engine
    manifest_engine.merge_into_manifest(
        manifest, asset_entries, scan_status, required_plugins)
    if not manifest_engine.write_manifest_json(manifest, manifest_path):
        safe_print(f"Scene Collector: Could not save manifest atomically")
    else:
        safe_print(f"Scene Collector: Manifest saved to {manifest_path}")
```

(eliminando el `try/except` con `json.dump` que había — la atomicidad
vive ahora en el motor).

- [ ] **Step 3: Extend the success dialog**

En el bloque del mensaje de éxito (donde hoy se compone `msg` con
`Missing: ...` y `Size: ...`), añadir tras la línea del tamaño:

```python
    summary = manifest.get("asset_summary", {})
    if manifest.get("scan_status") == "failed":
        msg += "\n\n⚠ RE-SCAN FAILED — manifest has no asset verification!"
    else:
        msg += (f"\n\nPackage re-scan: {summary.get('total', 0)} assets — "
                f"{summary.get('collected', 0)} in package, "
                f"{summary.get('missing', 0)} missing, "
                f"{summary.get('external', 0)} external")
        if summary.get("missing", 0) or summary.get("external", 0):
            problem = [e["path"] for e in manifest.get("assets", [])
                       if e["state"] != "collected"][:10]
            msg += "\n  " + "\n  ".join(problem)
```

- [ ] **Step 4: Live C4D verification (no pytest possible — GUI flow)**

1. Reinicia C4D (política de recarga).
2. Abre `tests/fixtures/violating.c4d`, ejecuta Collect Scene a una carpeta nueva.
3. Verifica: `sentinel_manifest.json` contiene `assets_schema: 1`, `scan_status: "ok"`, `assets[]` no vacío, y el diálogo muestra la línea «Package re-scan: ...».
4. Mueve una textura del paquete fuera (simula pérdida) y re-colecta a otra carpeta desde una escena con esa textura absoluta → aparece como `external` o `missing` según el caso.
5. Consola sin trazas de error; `KillDocument` no deja el doc temporal en la lista de documentos abiertos (Window ▸ ... no muestra documento extra).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/flows.py
git commit -m "feat(collect): post-copy re-scan + asset section in sentinel_manifest.json (I4)"
```

---

### Task 4: Recepción — «Delivery Summary...» + «Verify Delivery» en la pestaña Versions

**Files:**
- Modify: `plugin/sentinel/ui/panel.py` (pestaña Versions: añadir botón; + handler en `Command`)
- Modify: `plugin/sentinel/ui/ids.py` (nuevo ID de widget)

**Interfaces:**
- Consumes: `manifest.load_manifest_json`, `verify_package` (Task 2).
- Produces: nada aguas abajo.

- [ ] **Step 1: Add the widget ID**

En `ui/ids.py`, siguiendo la numeración existente de la sección Versions
(usa el siguiente entero libre del bloque — inspecciona el rango de la
pestaña Versions y toma el siguiente; ejemplo con hueco libre):

```python
BTN_DELIVERY_SUMMARY = 11360  # Versions tab: Delivery Summary (I4)
```

(Si `11360` está ocupado en tu `ids.py`, usa el siguiente libre del bloque
Versions y mantén el nombre `BTN_DELIVERY_SUMMARY` — Tasks posteriores
referencian el nombre, no el número.)

- [ ] **Step 2: Add the button to the Versions tab build**

En `panel.py`, en el método que construye la pestaña Versions (búscalo con
`grep -n "Recent Versions\|_build_versions" plugin/sentinel/ui/panel.py`),
añadir al final de la sección, junto a los botones existentes:

```python
        # Delivery reception (I4): only when a collected manifest with an
        # asset section sits next to the open scene.
        if self._delivery_manifest_available():
            self.AddButton(ids.BTN_DELIVERY_SUMMARY, c4d.BFH_SCALEFIT, 0, 12,
                           "Delivery Summary...")
```

Y como método del diálogo:

```python
    def _delivery_manifest_available(self):
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return False
        doc_path = doc.GetDocumentPath()
        if not doc_path:
            return False
        path = os.path.join(doc_path, "sentinel_manifest.json")
        if not os.path.exists(path):
            return False
        from sentinel import manifest as manifest_engine
        data = manifest_engine.load_manifest_json(path)
        # Solo manifiestos con sección de assets (I4+); los antiguos no
        # ofrecen nada que verificar.
        return bool(data and data.get("assets_schema"))
```

- [ ] **Step 3: Handle the click in `Command`**

En el `Command` del panel (mismo patrón que los demás botones):

```python
        if wid == ids.BTN_DELIVERY_SUMMARY:
            self._show_delivery_summary()
            return True
```

Y el método:

```python
    def _show_delivery_summary(self):
        from sentinel import manifest as manifest_engine
        doc = c4d.documents.GetActiveDocument()
        doc_path = doc.GetDocumentPath() if doc else None
        if not doc_path:
            return
        data = manifest_engine.load_manifest_json(
            os.path.join(doc_path, "sentinel_manifest.json"))
        if not data:
            c4d.gui.MessageDialog("Could not read sentinel_manifest.json.")
            return

        qc = data.get("qc", {})
        summary = data.get("asset_summary", {})
        notes = data.get("notes", {})
        lines = ["DELIVERY SUMMARY", ""]
        original = data.get("original_filename") or data.get("scene", "")
        if original:
            lines.append(f"Origin: {original}")
        if qc:
            lines.append(f"QC at collect: {qc.get('passed', '?')}/"
                         f"{qc.get('total', '?')}")
        baseline_info = data.get("baseline", {})
        acceptances = baseline_info.get("acceptances") or []
        if acceptances:
            lines.append(f"Accepted violations: {len(acceptances)} "
                         f"(see baseline sidecar for author + reason)")
        pending = notes.get("pending_count", 0)
        if pending:
            lines.append(f"Pending TODOs: {pending}")
        if data.get("scan_status") == "failed":
            lines.append("")
            lines.append("⚠ Package re-scan FAILED at collect time — "
                         "asset list not verified by sender!")
        else:
            lines.append("")
            lines.append(f"Assets: {summary.get('total', 0)} — "
                         f"{summary.get('collected', 0)} in package, "
                         f"{summary.get('missing', 0)} missing at collect, "
                         f"{summary.get('external', 0)} external")
        plugins = data.get("required_plugins") or []
        if plugins:
            names = ", ".join(p.get("name", "?") for p in plugins[:8])
            lines.append(f"Requires plugins: {names}")
        lines.append("")
        lines.append("Verify package integrity on this machine now?")

        if c4d.gui.QuestionDialog("\n".join(lines)):
            result = manifest_engine.verify_package(data, doc_path)
            if result["lost"]:
                lost = "\n  ".join(result["lost"][:15])
                c4d.gui.MessageDialog(
                    f"VERIFY: {len(result['lost'])} asset(s) LOST in "
                    f"transfer (were in package at collect):\n  {lost}")
            else:
                c4d.gui.MessageDialog(
                    f"VERIFY OK: {result['ok']}/{result['checked']} "
                    f"collected assets present."
                    + (f"\n{len(result['still_missing'])} were already "
                       f"missing at collect time." if result["still_missing"]
                       else ""))
```

- [ ] **Step 4: Live C4D verification**

1. Reinicia C4D. Abre el `.c4d` de un paquete colectado en Task 3.
2. Pestaña Versions → aparece «Delivery Summary...» (y NO aparece al abrir una escena sin manifiesto al lado — cero ruido).
3. El resumen muestra QC sellado, acceptances, TODOs pendientes y conteos de assets.
4. «Verify» con paquete intacto → «VERIFY OK n/n».
5. Borra una textura del paquete → «Verify» la lista como LOST.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/panel.py plugin/sentinel/ui/ids.py
git commit -m "feat(panel): delivery summary + receiver-side verify for collected packages (I4)"
```

---

### Task 5: Escalera de verificación — fixtures dirigidos + peldaño de producción real

**Files:**
- Test: `tests/test_manifest.py` (añadir clase de integración con árbol realista)
- Verificación en vivo: `tests/fixtures/violating.c4d`, `tests/fixtures/clean.c4d` + **una entrega real**

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: evidencia de cierre del plan (criterio de "done").

- [ ] **Step 1: Add the realistic-tree integration test**

```python
# tests/test_manifest.py — añadir al final

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
        assert v["lost"] == [os.path.join("tex", "hdr.exr")]
```

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest tests/ -v --ignore=tests/c4d_runner`
Expected: todo verde.

- [ ] **Step 3: Fixture C4D dirigido (en vivo)**

1. Reinicia C4D. Colecta `clean.c4d` → manifiesto con `missing: 0, external: 0`.
2. Colecta `violating.c4d` (contiene textura ausente por diseño) → el asset ausente aparece como `missing` en manifiesto y diálogo.
3. Si la escena fixture tiene RS Proxy/VDB/XRef: confirma que aparecen en `assets[]` (vía `rs_object_fileref` / `object_bc`). Si no los tiene, añade a una copia local un RS Proxy con ruta rota y confirma que el re-scan lo lista — **este es el asset que motivó I4**.

- [ ] **Step 4: Peldaño de producción real (bloquea el merge — lección I1)**

1. Colecta una entrega real reciente del estudio a una carpeta temporal.
2. Compara `asset_summary` contra lo que sabes que contiene esa entrega (conteo de texturas ±, presencia de los cachés que conoces).
3. Cualquier falso positivo/negativo → se arregla + se añade como test en `tests/test_manifest.py` antes de continuar (loop incidente→fixture).
4. Abre el paquete desde una segunda cuenta de usuario o segunda máquina → «Delivery Summary» + «Verify» OK; borra un fichero → LOST detectado.

- [ ] **Step 5: Final commit + branch/PR**

```bash
git add tests/test_manifest.py
git commit -m "test(manifest): realistic package-tree integration + production-run findings"
```

Rama y PR según el flujo del repo (`feat/i4-collect-confiable` → PR a main).

---

## Self-Review (hecho al escribir el plan)

- **Cobertura del spec:** manifiesto+clasificación (T1-2) ✓; re-scan post-copia (T3) ✓; diálogo con conteos y sin bloqueo (T3.3) ✓; recepción + verify (T4) ✓; inventario de plugins (T3.1) ✓; secuencias/tokens — **recortado de v1**: el escáner actual no emite registros por-frame de secuencias; se difiere con el campo `hash` (anotado aquí para que el gap sea visible, no silencioso); escalera con peldaño real (T5) ✓; escáner RS Proxy/VDB/IES **ya cubierto** por `textures.py:543-563` (corrección de grounding — el spec pedía añadirlos; la tarea real es *verificarlos* en T5.3).
- **Placeholders:** ninguno — todo paso de código lleva el código; los pasos en vivo llevan procedimiento exacto y resultado esperado.
- **Consistencia de tipos:** `build_asset_entries` → entries consumidas por `merge_into_manifest`/`verify_package` con las mismas claves (`path`, `state`, `hash`); `_rescan_collected_package` devuelve la tupla exacta que T3.2 desempaqueta; `BTN_DELIVERY_SUMMARY` referenciado por nombre en T4.
- **Desviaciones del spec (con motivo):** claves en inglés (convención del manifiesto existente); sección de assets integrada en `sentinel_manifest.json` (ya existía — el spec asumía sidecar nuevo); recepción como botón en Versions en vez de detección automática por artista (menor intrusión en `panel.py` de 2.568 líneas; la detección automática queda como mejora posterior).
