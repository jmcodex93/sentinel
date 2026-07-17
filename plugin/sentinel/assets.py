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
