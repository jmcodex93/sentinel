"""Asset Hub pure engine — unified asset inventory, matching, totals, zip.

Stdlib only. NEVER import c4d here: C4D reads live in the thin adapter in
ui/flows.py (same pattern as manifest.py / postrender.py).
"""
import os

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
    generic owner is appended. Empty-path records are kept with synthetic keys."""
    by_key = {}
    order = []

    for rec in texture_records or []:
        key = normalize_path_key(rec.get("resolved") or rec.get("path"))
        # Use synthetic key for empty paths so they remain visible as QC signals.
        if not key:
            key = f"__empty__tex__{rec.get('tex_idx')}"
        kind = _OWNER_KIND_BY_SOURCE.get(rec.get("source_type", ""), "material")
        owner = (rec.get("host_name", ""), kind, rec.get("channel", ""))
        if key in by_key:
            r = by_key[key]
            if owner not in r["owners"]:
                r["owners"].append(owner)
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
            "tex_idx": rec.get("tex_idx"),
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
        }
        order.append(key)

    records = [by_key[k] for k in order]
    records.sort(key=lambda r: (_STATUS_ORDER.get(r["status"], 9),
                                os.path.basename(r["path"]).lower()))
    return records
