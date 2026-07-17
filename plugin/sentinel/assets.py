"""Asset Hub pure engine — unified asset inventory, matching, totals, zip.

Stdlib only. NEVER import c4d here: C4D reads live in the thin adapter in
ui/flows.py (same pattern as manifest.py / postrender.py).
"""
import os
import zipfile

# Extension → asset_type. Lowercase, no dot.
_TYPE_BY_EXT = {
    "png": "texture", "jpg": "texture", "jpeg": "texture", "tif": "texture",
    "tiff": "texture", "psd": "texture", "tga": "texture", "bmp": "texture",
    "webp": "texture", "tx": "texture", "gif": "texture",
    "hdr": "hdri",
    "abc": "alembic",
    "vdb": "vdb",
    "ies": "ies",
    "cube": "lut_ocio", "ocio": "lut_ocio", "3dl": "lut_ocio", "lut": "lut_ocio",
    "wav": "sound", "aif": "sound", "aiff": "sound", "mp3": "sound",
    "c4d": "xref",
    "rs": "proxy", "rsproxy": "proxy", "ass": "proxy",
}

_HDRI_HINTS = ("dome", "env", "sky", "hdri")


def normalize_path_key(path):
    """Case-folded, forward-slash key used to dedupe assets across scanners."""
    if not path:
        return ""
    return str(path).strip().replace("\\", "/").lower()


def infer_type(path, owner_kind="", channel=""):
    """Best-effort asset type from extension + owner context."""
    ext = os.path.splitext(str(path or ""))[1].lstrip(".").lower()
    if ext == "exr":
        blob = f"{owner_kind} {channel}".lower()
        if owner_kind == "light" or any(h in blob for h in _HDRI_HINTS):
            return "hdri"
        return "texture"
    return _TYPE_BY_EXT.get(ext, "other")


def classify_generic(path, exists):
    """Status for GetAllAssetsNew items. C4D hands back *resolved* filenames,
    so the stored-form distinction (absolute vs relative) is not recoverable
    here — generic records are only ok/missing/empty/asset_uri."""
    s = str(path).strip() if path else ""
    if not s:
        return "empty"
    if s.startswith("asset:") or s.startswith("preset:"):
        return "asset_uri"
    return "ok" if exists else "missing"


# TextureRecord.source_type → owner_kind shown in the "Used by" column.
_OWNER_KIND_BY_SOURCE = {
    "classic_shader": "material", "octane_shader": "material",
    "rs_node": "material", "arnold_node": "material", "bc_param": "material",
    "object_bc": "object", "alembic": "object",
    "rs_object_fileref": "light",
}

_STATUS_ORDER = {"missing": 0, "absolute": 1, "empty": 2, "asset_uri": 3, "ok": 4}


def merge_inventories(texture_records, generic_records):
    """Fuse the structured texture scan (repathable, rich owners) with the
    generic GetAllAssetsNew sweep (exhaustive, read-only). Dedupe by
    normalized path; on collision the texture record wins and only the
    generic owner is appended. Empty-path records are kept with synthetic keys.

    Multiple texture records can collapse into one row when they share a
    path (e.g. 3 materials referencing the same file) — "tex_idx" keeps the
    first index for owner_ref/browse compatibility, while "tex_idxs" collects
    every colliding tex_idx so repathing can update all of them."""
    by_key = {}
    order = []

    for rec in texture_records or []:
        key = normalize_path_key(rec.get("resolved") or rec.get("path"))
        # Use synthetic key for empty paths so they remain visible as QC signals.
        if not key:
            key = f"__empty__tex__{rec.get('tex_idx')}"
        kind = _OWNER_KIND_BY_SOURCE.get(rec.get("source_type", ""), "material")
        owner = (rec.get("host_name", ""), kind, rec.get("channel", ""))
        tex_idx = rec.get("tex_idx")
        if key in by_key:
            r = by_key[key]
            if owner not in r["owners"]:
                r["owners"].append(owner)
            if tex_idx is not None and tex_idx not in r["tex_idxs"]:
                r["tex_idxs"].append(tex_idx)
            continue
        by_key[key] = {
            "key": key,
            "path": rec.get("path", ""),
            "resolved_path": rec.get("resolved"),
            "status": rec.get("status", "ok"),
            "asset_type": infer_type(rec.get("path", ""), kind,
                                     rec.get("channel", "")),
            "size_bytes": None,
            "owners": [owner],
            "repathable": True,
            "tex_idx": tex_idx,
            "tex_idxs": [tex_idx] if tex_idx is not None else [],
        }
        order.append(key)

    for i, rec in enumerate(generic_records or []):
        key = normalize_path_key(rec.get("path"))
        # Use synthetic key for empty paths so they remain visible as QC signals.
        if not key:
            key = f"__empty__gen__{i}"
        owner = (rec.get("owner_name", ""), rec.get("owner_kind", "object"), "")
        if key in by_key:
            r = by_key[key]
            if owner not in r["owners"]:
                r["owners"].append(owner)
            continue
        by_key[key] = {
            "key": key,
            "path": rec.get("path", ""),
            "resolved_path": rec.get("path") if rec.get("exists") else None,
            "status": classify_generic(rec.get("path"), rec.get("exists")),
            "asset_type": infer_type(rec.get("path", ""), owner[1], ""),
            "size_bytes": None,
            "owners": [owner],
            "repathable": False,
            "tex_idx": None,
            "tex_idxs": [],
        }
        order.append(key)

    records = [by_key[k] for k in order]
    records.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 9),
                                os.path.basename(r["path"]).lower()))
    return records


def format_size(nbytes):
    """Human-readable file size. None → '—', negative → '?'."""
    if nbytes is None:
        return "—"
    if nbytes < 0:
        return "?"
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit, div in (("KB", 1024.0), ("MB", 1024.0**2), ("GB", 1024.0**3),
                      ("TB", 1024.0**4)):
        val = nbytes / div
        if val < 1024 or unit == "TB":
            # Special rule: GB/TB with value < 10 get 2 decimals.
            if unit in ("GB", "TB") and val < 10:
                return f"{val:.2f} {unit}"
            return f"{val:.1f} {unit}" if val < 100 else f"{val:.0f} {unit}"
    return f"{nbytes} B"


def compute_totals(records):
    """Aggregate stats: count, missing, absolute, total_bytes, unsized, by_type."""
    totals = {"count": len(records), "missing": 0, "absolute": 0,
              "total_bytes": 0, "unsized": 0, "by_type": {}}
    for r in records:
        st = r.get("status")
        if st == "missing":
            totals["missing"] += 1
        elif st == "absolute":
            totals["absolute"] += 1
        t = r.get("asset_type", "other")
        totals["by_type"][t] = totals["by_type"].get(t, 0) + 1
        size = r.get("size_bytes")
        if size is None or size < 0:
            totals["unsized"] += 1
        else:
            totals["total_bytes"] += size
    return totals


def stat_sizes_batch(records, start, count, getsize=os.path.getsize):
    """Fill size_bytes for records[start:start+count]. Meant to be called
    from the dialog Timer in small batches so slow network mounts never
    block the UI. Returns the next start index (== len when done)."""
    end = min(len(records), start + count)
    for i in range(start, end):
        rec = records[i]
        if rec.get("size_bytes") is not None:
            continue
        path = rec.get("resolved_path")
        if not path:
            continue
        try:
            rec["size_bytes"] = int(getsize(path))
        except Exception:
            rec["size_bytes"] = -1
    return end


def build_file_index(root, walk=os.walk, cap=50000):
    """Index a folder tree by lowercase basename. Caps at `cap` files so a
    mis-picked root (e.g. '/') can't hang the UI; truncated=True tells the
    dialog to warn."""
    index = {}
    n = 0
    truncated = False
    for dirpath, _dirs, files in walk(root):
        for name in files:
            if n >= cap:
                truncated = True
                return index, truncated
            index.setdefault(name.lower(), []).append(
                os.path.join(dirpath, name))
            n += 1
    return index, truncated


def match_missing_in_folder(records, index):
    """Match missing records against a folder index by basename
    (case-insensitive). 2+ candidates → ambiguous: the user picks, we never
    auto-choose."""
    out = {}
    for rec in records:
        if rec.get("status") != "missing":
            continue
        base = os.path.basename(str(rec.get("path", ""))).lower()
        candidates = index.get(base)
        if not candidates:
            continue
        if len(candidates) == 1:
            out[rec["key"]] = {"match": candidates[0]}
        else:
            out[rec["key"]] = {"ambiguous": list(candidates)}
    return out


def create_zip_archive(delivery_dir, zip_path=None, on_progress=None):
    """Zip the delivery folder (folder name as the archive root). The source
    folder is always kept — the zip is an additional artifact."""
    delivery_dir = os.path.abspath(delivery_dir)
    root_name = os.path.basename(delivery_dir.rstrip(os.sep))
    if zip_path is None:
        zip_path = delivery_dir.rstrip(os.sep) + ".zip"

    file_list = []
    for dirpath, _dirs, files in os.walk(delivery_dir):
        for name in files:
            file_list.append(os.path.join(dirpath, name))

    total = len(file_list)
    written_bytes = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, fpath in enumerate(file_list, 1):
            arcname = os.path.join(
                root_name, os.path.relpath(fpath, delivery_dir))
            zf.write(fpath, arcname.replace(os.sep, "/"))
            written_bytes += os.path.getsize(fpath)
            if on_progress:
                on_progress(i, total)
    return {"zip_path": zip_path, "files": total, "bytes": written_bytes}
