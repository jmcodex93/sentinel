"""Pure Asset Hub payload, repath, thumbnail, and progress helpers."""

import hashlib
import os

from sentinel import assets as _assets

_THUMB_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr",
               ".tga", ".bmp", ".psd", ".webp"}


def hub_inventory_payload(records, totals, scene_name="", skipped=0):
    """Pure: shape merged AssetRecords (assets.merge_inventories) for the SPA.

    Strips live-scene fields (tex_idx/tex_idxs stay server-side; the apply
    op re-resolves keys against a fresh scan — HTTP is stateless).
    """
    assets_out = []
    for rec in records:
        resolved = rec.get("resolved_path")
        ext = os.path.splitext(resolved or "")[1].lower()
        assets_out.append({
            "key": rec.get("key", ""),
            "path": rec.get("path", ""),
            "resolved_path": resolved,
            "status": rec.get("status", ""),
            "asset_type": rec.get("asset_type", ""),
            "size_bytes": rec.get("size_bytes"),
            "size_label": _assets.format_size(rec.get("size_bytes")),
            "owners": [{"name": n, "kind": k, "channel": c}
                       for (n, k, c) in rec.get("owners", [])],
            "repathable": bool(rec.get("repathable")),
            "has_thumb": bool(resolved) and ext in _THUMB_EXTS
            and rec.get("status") != "missing",
        })
    totals_out = dict(totals)
    totals_out["total_label"] = _assets.format_size(totals.get("total_bytes"))
    return {"scene_name": scene_name, "skipped": skipped,
            "assets": assets_out, "totals": totals_out}


def resolve_repath_targets(records, changes):
    """Pure: map client pending changes [{key,new_path}] onto tex_idxs."""
    by_key = {rec.get("key"): rec for rec in records}
    targets, errors = [], []
    for change in changes or []:
        key = change.get("key", "")
        new_path = (change.get("new_path") or "").strip()
        rec = by_key.get(key)
        if rec is None:
            errors.append({"key": key, "error": "unknown key (rescan?)"})
            continue
        if not new_path:
            errors.append({"key": key, "error": "empty new path"})
            continue
        if not rec.get("repathable"):
            errors.append({"key": key, "error": "not repathable"})
            continue
        idxs = rec.get("tex_idxs") or (
            [rec["tex_idx"]] if rec.get("tex_idx") is not None else [])
        if not idxs:
            errors.append({"key": key, "error": "no writable shader"})
            continue
        targets.append({"key": key, "new_path": new_path, "tex_idxs": list(idxs)})
    return targets, errors


def thumb_cache_name(resolved_path, mtime):
    """Pure: stable cache filename from path and mtime."""
    digest = hashlib.sha1(
        ("%s|%s" % (resolved_path, mtime)).encode("utf-8")).hexdigest()
    return digest + ".png"


_COLLECT_PHASES = (("Saving", "save", 15), ("Re-scanning", "rescan", 60),
                   ("Writing manifest", "manifest", 80), ("Zipping", "zip", 90))


def collect_phase_pct(message):
    """Pure: map run_collect_pipeline status strings to (phase, pct) tuples."""
    for prefix, phase, pct in _COLLECT_PHASES:
        if (message or "").startswith(prefix):
            return phase, pct
    return "run", None
