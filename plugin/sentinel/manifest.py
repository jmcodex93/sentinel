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

from sentinel import udim

ASSET_COLLECTED = "collected"
ASSET_MISSING = "missing"
ASSET_EXTERNAL = "external"

ASSETS_SCHEMA_VERSION = 1

# Scanner statuses that are not filesystem assets — excluded from the
# manifest (RS Asset Manager URIs, empty path slots).
_SKIP_STATUSES = ("asset_uri", "empty")

# Built-in Maxon object/tag/material types that live in the plugin-ID
# range (>= 1,000,000) and would otherwise pollute the "requires plugins"
# inventory — every C4D install ships them, so they carry no signal for
# the receiver. Curated from live production runs; extend as new native
# types show up (never add renderer IDs here: a receiver missing Redshift
# or Octane is exactly what the inventory exists to flag).
NATIVE_PLUGIN_IDS = frozenset({
    1001149,    # XPresso tag
    1007455,    # Subdivision Surface
    1018544,    # Cloner (MoGraph)
    1018625,    # Data Tag (MoGraph)
    431000028,  # Bevel deformer
})


def filter_native_plugins(plugins):
    """Drop built-in Maxon entries from a required-plugins inventory."""
    return [p for p in plugins or []
            if p.get("plugin_id") not in NATIVE_PLUGIN_IDS]


def _inside(path, root):
    """True if ``path`` is inside ``root`` (both made real/absolute)."""
    try:
        real_path = os.path.realpath(path)
        real_root = os.path.realpath(root)
        return os.path.commonpath([real_path, real_root]) == real_root
    except (ValueError, OSError):
        # Different drives on Windows, malformed paths.
        return False


def _exists(path):
    """A UDIM/UVTILE pattern (v1.43) exists when at least one tile does —
    the same rule as the texture resolver."""
    if udim.has_token(path):
        return bool(udim.list_tiles(path))
    return os.path.exists(path)


def _pattern_key(path):
    return os.path.basename(str(path or "").replace("\\", "/")).lower()


def source_tiles_of(scan_records):
    """``{pattern basename (lowercase): [tiles]}`` for the UDIM paths of the
    scene BEFORE it is collected — what ``build_asset_entries`` compares the
    package against. Keyed by basename: Collect rewrites the folders
    (``relative:///…``), never the file names (measured 2026-10-29)."""
    tiles = {}
    for rec in scan_records or []:
        resolved = rec.get("resolved")
        if resolved and udim.has_token(resolved):
            tiles[_pattern_key(resolved)] = udim.list_tiles(resolved)
    return tiles


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
    if not _exists(resolved):
        return ASSET_MISSING
    if _inside(resolved, package_root):
        return ASSET_COLLECTED
    return ASSET_EXTERNAL


def build_asset_entries(scan_records, package_root):
    """Flatten scanner records into manifest asset entries.

    ``scan_records`` are plain dicts (no live C4D refs):
    ``{"current_path", "resolved", "status", "source_type", "channel",
    "host_name"}``. Dedupes by classified path.

    A UDIM pattern (v1.43) records the tiles found in the package as
    ``udim: {"tiles": [...]}`` (``mark_lost_tiles`` then compares them with
    the scene before collecting).
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
                os.path.realpath(package_root)).replace(os.sep, "/")
        else:
            path = rec.get("current_path", "")
        tiles = None
        if state != ASSET_MISSING and udim.has_token(rec.get("resolved")):
            tiles = udim.list_tiles(rec["resolved"])
        key = (path, state)
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "path": path,
            "original_path": rec.get("current_path", ""),
            "source_type": rec.get("source_type", ""),
            "channel": rec.get("channel", ""),
            "host": rec.get("host_name", ""),
            "state": state,
            "hash": None,  # reservado (schema v1: siempre None)
        }
        if tiles is not None:
            entry["udim"] = {"tiles": tiles}
        entries.append(entry)
    return entries


def mark_lost_tiles(entries, source_tiles):
    """A UDIM entry missing a tile the scene had before collecting
    (``source_tiles``, from ``source_tiles_of``) turns ``missing`` with
    ``missing_tiles`` (v1.43): that area would render black on the
    receiving side, so the package must not be sealed as complete."""
    for entry in entries or []:
        tiles = (entry.get("udim") or {}).get("tiles")
        if tiles is None or entry.get("state") != ASSET_COLLECTED:
            continue
        expected = (source_tiles or {}).get(_pattern_key(entry.get("path"))) or []
        lost = sorted(set(expected) - set(tiles))
        if lost:
            entry["state"] = ASSET_MISSING
            entry["missing_tiles"] = lost
    return entries


def summarize_assets(entries):
    counts = {"total": len(entries), "collected": 0, "missing": 0,
              "external": 0}
    for e in entries:
        state = e.get("state")
        if state in counts:
            counts[state] += 1
    return counts


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
    manifest_dict["plugin_inventory_scope"] = "objects+tags+materials"
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
            candidate = os.path.join(
                package_root, *path.replace("\\", "/").split("/"))
            tiles = (entry.get("udim") or {}).get("tiles")
            if tiles is not None:
                # v1.43: every recorded tile must still be there; a lost
                # tile is reported as its own file.
                lost = [udim.tile_path(path, t) for t in tiles
                        if not os.path.exists(udim.tile_path(candidate, t))]
                if lost:
                    result["lost"].extend(lost)
                else:
                    result["ok"] += 1
            elif os.path.exists(candidate):
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
    except Exception:
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
