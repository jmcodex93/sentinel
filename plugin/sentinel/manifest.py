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
