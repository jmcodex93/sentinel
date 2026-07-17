"""Asset Hub pure engine — unified asset inventory, matching, totals, zip.

Stdlib only. NEVER import c4d here: C4D reads live in the thin adapter in
ui/flows.py (same pattern as manifest.py / postrender.py).
"""
import os
import re
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


_WIN_DRIVE_RE = re.compile(r"[a-z]:/")


def canonical_asset_key(path):
    """Dedupe key that collapses different SCANNER STRING FORMS of the
    SAME on-disk asset — normalize_path_key alone is not enough: the
    structured texture scan and the generic GetAllAssetsNew sweep can
    report the identical file as different literal strings (URL-scheme
    prefixes, a doc-relative "./" C4D prepends to an absolute Windows
    path it can't resolve on this platform, etc). normalize_path_key
    itself is left UNCHANGED — other callers rely on its exact output;
    this only changes the key merge_inventories dedupes on.

    Real production pairs this fixes (same scene, two scanners):
      - texture (absolute) `D:/.../file.jpg` vs
        generic (missing) `./D:/.../file.jpg`.
      - texture `file:///X:/.../file.png` vs generic `/X:/.../file.png`.
      - texture `relative:///file.jpg` vs generic `file.jpg`.
    """
    key = normalize_path_key(path)
    if not key:
        return key

    # (a) Maxon Url: file:// — same Windows-drive leading-slash fix as
    # textures.py's classify_texture_path (file:///x:/... -> x:/...).
    if key.startswith("file://"):
        key = key[len("file://"):]
        if key.startswith("/") and len(key) > 3 and key[2] == ":":
            key = key.lstrip("/")

    # (b) Maxon Url: relative:// — strip the scheme + any leading
    # slashes (relative:///foo.jpg -> foo.jpg).
    elif key.startswith("relative://"):
        key = key[len("relative://"):].lstrip("/")

    # (c) Collapse leading "./" segments — C4D's doc-relative prefix
    # glued onto an otherwise-absolute path it couldn't resolve
    # (e.g. "./d:/...").
    while key.startswith("./"):
        key = key[2:]

    # (d) A Windows drive letter (e.g. "d:/") appearing past the very
    # start of the key means an unrelated prefix (doc dir, or a "./"
    # not caught above once embedded deeper) was glued onto an
    # otherwise-absolute Windows path — cut it off so both scanner
    # forms key on the same drive-rooted path.
    match = _WIN_DRIVE_RE.search(key)
    if match and match.start() > 0:
        key = key[match.start():]

    return key


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
    canonical_asset_key (not the plainer normalize_path_key — the two
    scanners can report the identical on-disk file as different literal
    strings, e.g. a URL-scheme prefix or a doc-relative "./" C4D glues
    onto an unresolvable absolute path); on collision the texture record
    wins and only the generic owner is appended. Empty-path records are
    kept with synthetic keys.

    Multiple texture records can collapse into one row when they share a
    path (e.g. 3 materials referencing the same file) — "tex_idx" keeps the
    first index for owner_ref/browse compatibility, while "tex_idxs" collects
    every colliding tex_idx so repathing can update all of them."""
    by_key = {}
    order = []

    for rec in texture_records or []:
        key = canonical_asset_key(rec.get("resolved") or rec.get("path"))
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
        key = canonical_asset_key(rec.get("path"))
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


def fit_column_widths(stored, order, budget, min_width):
    """Shrink a table's resizable column widths so they always sum to at
    most `budget`, without ever mutating the caller's persisted widths.

    Used by AssetListArea._columns (the Asset Hub table, item 3/5 of the
    UI polish pass) to enforce a fit-to-viewport invariant: stored widths
    can come from an EARLIER, wider window (persisted to
    sentinel_settings.json), so honoring them verbatim on a narrower
    window pushes later columns (path, the fixed browse "…" slot) off the
    visible edge. This function is pure and display-only — callers must
    never write its return value back to storage, so re-widening the
    window restores the user's actual stored widths.

    Args:
        stored: {col: width} for every column in `order` (extra keys ignored).
        order: the fixed column order, e.g. ("name", "type", "size", "used").
        budget: max total width the columns in `order` may occupy.
        min_width: floor for every individual column.

    Returns:
        A NEW {col: width} dict. Under budget: passed through unchanged
        (still a copy). Over budget: shrunk proportionally to each
        column's share of `stored`, each clamped to >= min_width. If even
        the min-width floors don't fit inside `budget` (an absurdly
        narrow viewport), every column floors at min_width and the
        caller accepts the residual overlap — there is no narrower valid
        layout to produce.
    """
    widths = {c: int(stored.get(c, min_width)) for c in order}
    total = sum(widths.values())
    if total <= budget:
        return widths
    if budget <= 0:
        return {c: min_width for c in order}
    shrunk = {c: max(min_width, int(widths[c] * budget / total)) for c in order}
    if sum(shrunk.values()) > budget:
        # Proportional shrink still doesn't fit once the floors kicked in
        # — no valid layout exists inside this budget, floor everything.
        return {c: min_width for c in order}
    return shrunk


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
        # Derive the basename from the normalized (forward-slash) key
        # instead of os.path.basename: a Windows-authored path like
        # "D:\old\tex\wood.png" opened on macOS has no path separators
        # os.path.basename recognizes, so it returns the whole string
        # instead of "wood.png".
        base = normalize_path_key(rec.get("path", "")).rsplit("/", 1)[-1]
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
