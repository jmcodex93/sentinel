"""Asset Hub pure engine — unified asset inventory, matching, totals, zip.

Stdlib only. NEVER import c4d here: C4D reads live in the thin adapter in
ui/flows.py (same pattern as manifest.py / postrender.py).
"""
import os
import re
import zipfile

from . import imagemeta

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


def canonical_asset_key(path, base_dir=None):
    """Dedupe key that collapses different SCANNER STRING FORMS of the
    SAME on-disk asset — normalize_path_key alone is not enough: the
    structured texture scan and the generic GetAllAssetsNew sweep can
    report the identical file as different literal strings (URL-scheme
    prefixes, a doc-relative "./" C4D prepends to an absolute Windows
    path it can't resolve on this platform, a still-relative bare
    filename vs. the texture scanner's absolute "expected location" for
    a missing relative path, etc). normalize_path_key itself is left
    UNCHANGED — other callers rely on its exact output; this only
    changes the key merge_inventories dedupes on.

    Real production pairs this fixes (same scene, two scanners):
      - texture (absolute) `D:/.../file.jpg` vs
        generic (missing) `./D:/.../file.jpg`.
      - texture `file:///X:/.../file.png` vs generic `/X:/.../file.png`.
      - texture `relative:///file.jpg` (resolved to the doc-joined
        absolute "expected location" when missing) vs generic bare
        `file.jpg` — fixed by the base_dir anchor below.
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

    # (e) Anchor a still-relative key to the document directory. For a
    # MISSING relative texture, textures.py's classify_texture_path
    # returns the "expected location" — the ABSOLUTE doc_dir-joined
    # path — as `resolved`, which merge_inventories keys texture
    # records on; GetAllAssetsNew instead reports the bare relative
    # string for the same file. Without anchoring, those two forms
    # (absolute vs bare-relative) never converge to the same key.
    # Skipped when the key is already absolute (leading "/") or a
    # Windows drive path (checked at the very start via .match, not
    # .search — an embedded drive letter deeper in the string was
    # already promoted to the front by step (d) above).
    if (base_dir and key and not key.startswith("/")
            and not _WIN_DRIVE_RE.match(key)):
        base_key = normalize_path_key(base_dir)
        if base_key:
            joined = base_key.rstrip("/") + "/" + key
            # Collapse any "./" segment left over at the join point or
            # already embedded in either half.
            key = "/".join(p for p in joined.split("/") if p != ".")

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


def merge_inventories(texture_records, generic_records, base_dir=""):
    """Fuse the structured texture scan (repathable, rich owners) with the
    generic GetAllAssetsNew sweep (exhaustive, read-only). Dedupe by
    canonical_asset_key (not the plainer normalize_path_key — the two
    scanners can report the identical on-disk file as different literal
    strings, e.g. a URL-scheme prefix, a doc-relative "./" C4D glues onto
    an unresolvable absolute path, or a still-relative bare filename vs.
    the texture scanner's absolute "expected location" for a missing
    relative path); on collision the texture record wins and only the
    generic owner is appended. `base_dir` (typically doc.GetDocumentPath())
    anchors any still-relative key so it converges with its absolute
    counterpart — pass "" (default) to keep the old, unanchored behavior.
    Empty-path records are kept with synthetic keys.

    Multiple texture records can collapse into one row when they share a
    path (e.g. 3 materials referencing the same file) — "tex_idx" keeps the
    first index for owner_ref/browse compatibility, while "tex_idxs" collects
    every colliding tex_idx so repathing can update all of them."""
    by_key = {}
    order = []

    for rec in texture_records or []:
        key = canonical_asset_key(rec.get("resolved") or rec.get("path"), base_dir)
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
        key = canonical_asset_key(rec.get("path"), base_dir)
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


# ---------------------------------------------------------------------------
# Hub Shrink + Copy into project (Fase 5.2) — pure planners
# ---------------------------------------------------------------------------

_SHRINK_SUFFIX = {4096: "_4K", 2048: "_2K", 1024: "_1K"}


def shrink_target_name(path, target_px):
    """Sibling filename for a shrunk copy — `<stem>_<K><ext>` for the known
    targets (4096->_4K, 2048->_2K, 1024->_1K), `<stem>_{target_px}px<ext>`
    for anything else. Idempotent: if the stem already ends with the target
    suffix, the name is returned unchanged (a re-run on an already-shrunk
    sibling never doubles the suffix)."""
    suffix = _SHRINK_SUFFIX.get(target_px, f"_{target_px}px")
    root, ext = os.path.splitext(str(path))
    if root.endswith(suffix):
        return path
    return f"{root}{suffix}{ext}"


def shrink_plan(records, metas, target_px):
    """Plan a batch shrink to `target_px` on the larger dimension.

    `records` are AssetRecord dicts (key/path/resolved_path/status/
    asset_type); `metas` is {key: {"width","height","channels","bit_depth",
    ...}} — the hub image-meta shape (imagemeta.read_image_meta output).

    Eligible: status "ok" AND a meta entry present AND
    max(width, height) > target_px AND asset_type in ("texture", "hdri").
    Skip reasons (checked in this order): "not_ok", "not_image", "no_meta",
    "already_small".

    New dimensions scale by `target_px / max(w, h)`, rounded, floored at 1,
    aspect preserved. `vram_before`/`vram_after` sum
    `imagemeta.vram_bytes(...)` over the shrink list only — before at the
    original dims, after at the new dims (same channels/bit_depth).
    """
    shrink = []
    skipped = []
    vram_before = 0
    vram_after = 0

    for rec in records or []:
        key = rec.get("key")
        if rec.get("status") != "ok":
            skipped.append({"key": key, "reason": "not_ok"})
            continue
        if rec.get("asset_type") not in ("texture", "hdri"):
            skipped.append({"key": key, "reason": "not_image"})
            continue
        meta = (metas or {}).get(key)
        if not meta:
            skipped.append({"key": key, "reason": "no_meta"})
            continue
        width = meta.get("width")
        height = meta.get("height")
        if not width or not height:
            skipped.append({"key": key, "reason": "no_meta"})
            continue
        if max(width, height) <= target_px:
            skipped.append({"key": key, "reason": "already_small"})
            continue

        scale = target_px / max(width, height)
        new_width = max(1, round(width * scale))
        new_height = max(1, round(height * scale))
        channels = meta.get("channels")
        bit_depth = meta.get("bit_depth")

        shrink.append({
            "key": key,
            "path": rec.get("path"),
            "resolved_path": rec.get("resolved_path"),
            "width": width,
            "height": height,
            "new_width": new_width,
            "new_height": new_height,
        })
        vram_before += imagemeta.vram_bytes(width, height, channels, bit_depth)
        vram_after += imagemeta.vram_bytes(new_width, new_height, channels, bit_depth)

    return {
        "shrink": shrink,
        "skipped": skipped,
        "vram_before": vram_before,
        "vram_after": vram_after,
    }


def replace_basename_preserving_form(stored_path, new_basename):
    """Swap ONLY the basename of `stored_path`, preserving its original form
    exactly — scheme prefix (`relative:///`, `file:///`), separator style
    (forward or back — split on whichever appears LAST), and case. The
    sibling copy from a shrink/copy op always lands in the same directory as
    the resolved original, so relinking only ever needs a basename swap, not
    a full new path — reusing the stored form (instead of the absolute
    resolved target) is what keeps a `relative:///`-stored texture relative
    after a shrink.

    Examples: `relative:///tex/a.png` + `a_2K.png` ->
    `relative:///tex/a_2K.png`; `tex/a.png` -> `tex/a_2K.png`;
    `D:\\proj\\tex\\a.png` -> `D:\\proj\\tex\\a_2K.png`; bare `a.png` ->
    `a_2K.png`; empty stored path -> `new_basename` unchanged.
    """
    stored = stored_path or ""
    if not stored:
        return new_basename
    last_fwd = stored.rfind("/")
    last_back = stored.rfind("\\")
    cut = max(last_fwd, last_back)
    if cut < 0:
        return new_basename
    return stored[:cut + 1] + new_basename


def copy_plan(records, doc_dir):
    """Plan copying out-of-project assets into `<doc_dir>/tex/`.

    Eligible: `resolved_path` set AND its normalized-lowercased form does
    NOT already start with the normalized `doc_dir` + separator (a
    case-insensitive "already inside the project" check — intentionally
    case-insensitive since it's just a containment test). Target path is
    `os.path.join(doc_dir, "tex", basename(resolved_path))`, with the
    basename derived from the resolved path with separators normalized to
    "/" but CASE PRESERVED — a Windows-authored path (`D:\\old\\tex\\wood.png`)
    opened on macOS has no separators `os.path.basename` recognizes there,
    so it would return the whole string instead of `wood.png` (same fix as
    `match_missing_in_folder`), but using the lowercased dedupe key here
    would silently case-fold the filename (`Metal_Rough.PNG` →
    `metal_rough.png`), which breaks relinking on case-sensitive render
    farms.

    Skip reasons: "in_project" (already under doc_dir), "unresolved"
    (no resolved_path).
    """
    copy = []
    skip = []
    doc_key = normalize_path_key(doc_dir).rstrip("/") + "/"

    for rec in records or []:
        key = rec.get("key")
        resolved = rec.get("resolved_path")
        if not resolved:
            skip.append({"key": key, "reason": "unresolved"})
            continue
        resolved_key = normalize_path_key(resolved)
        if resolved_key.startswith(doc_key):
            skip.append({"key": key, "reason": "in_project"})
            continue
        basename = os.path.basename(str(resolved).replace("\\", "/"))
        target_path = os.path.join(doc_dir, "tex", basename)
        copy.append({
            "key": key,
            "resolved_path": resolved,
            "target_path": target_path,
        })

    return {"copy": copy, "skip": skip}


# ---------------------------------------------------------------------------
# Resolution variant detection (Fase 5.3) — pure, no file writes
# ---------------------------------------------------------------------------

_RES_TOKEN_MAP = {"1k": 1024, "2k": 2048, "4k": 4096, "8k": 8192, "16k": 16384}

# Alternatives ordered longest-first (documentational — none of these tokens
# is actually a prefix substring of another, so match order doesn't change
# behavior today, but it's the defensive convention if the map ever grows).
# Boundaries are zero-width lookaround assertions (never consumed) so the
# delimiter itself lands in whichever side it borders when the basename is
# sliced around the match.
_RES_TOKEN_RE = re.compile(
    r"(?:(?<=[_\-.])|^)(16k|8k|4k|2k|1k)(?:(?=[_\-.])|$)",
    re.IGNORECASE,
)


def split_res_token(basename):
    """Split `basename` around its LAST resolution token (`_4k_`, `-8k.`,
    `.4k.`, leading `4k_`, our `_2K` shrink suffix, etc.), case-insensitive.

    Returns `(prefix, px, suffix)` where `prefix + <token-as-found> + suffix
    == basename` (the delimiter on each side stays put in prefix/suffix, the
    token itself is consumed) — or `None` when no token is found. A token
    embedded in a word (`back4k.png`) never matches: both boundaries require
    a delimiter (`_`/`-`/`.`) or the start/end of the name. When multiple
    tokens are present, the LAST one wins (`scan_4k_detail_2k.png` splits on
    `2k`).
    """
    name = str(basename)
    matches = list(_RES_TOKEN_RE.finditer(name))
    if not matches:
        return None
    match = matches[-1]
    px = _RES_TOKEN_MAP[match.group(1).lower()]
    return name[:match.start()], px, name[match.end():]


def find_res_variants(records, list_dir=os.listdir):
    """Detect on-disk resolution siblings for each record — including the
    "bare base" file a tokened variant was shrunk/derived from, which
    carries no resolution token of its own (the Shrink tool creates
    exactly this pair: `NAME.png` -> `NAME_2K.png`).

    Each directory is listed at most once per call (cached by directory
    path — a `list_dir` failure skips every record in that directory
    rather than raising). Two cases:

    - Record's basename HAS a token (`split_res_token` succeeds): siblings
      are dir entries whose own split yields the same case-folded
      `(prefix, suffix)` (unchanged from before) PLUS, if present, the
      bare base file — basename == `prefix.rstrip("_-.") + suffix` — added
      with `"px": None` (unknown from the name alone).
    - Record's basename has NO token: look for dir entries whose split
      gives a prefix in `{stem + "_", stem + "-", stem + "."}`
      (case-folded) and suffix == the record's own extension (case-folded)
      — `stem` = the record's basename without extension. If any such
      tokened siblings exist, the family is those siblings plus the bare
      record itself (`"px": None`); otherwise the record has no family.

    Groups with fewer than 2 members (self included) are dropped.
    Returns `{key: [{"path", "px"}, ...]}` sorted by `px` descending with
    `None` entries LAST, paths joined with the record's directory after
    separators are normalized to `/` — same fix as `copy_plan`'s
    `match_missing_in_folder`: a Windows-authored `resolved_path`
    (`D:\\proj\\tex\\a.png`) opened on macOS has no separators
    `os.path.dirname`/`os.path.basename` recognize there, so without the
    normalization `dirname` would return `''`, `list_dir('')` would list
    the cwd, and the record would silently drop out of every group.
    """
    dir_listings = {}
    result = {}

    for rec in records or []:
        key = rec.get("key")
        resolved = rec.get("resolved_path")
        if not resolved:
            continue
        resolved = str(resolved).replace("\\", "/")
        dir_path = os.path.dirname(resolved)
        basename = os.path.basename(resolved)

        if dir_path not in dir_listings:
            try:
                dir_listings[dir_path] = list_dir(dir_path)
            except OSError:
                dir_listings[dir_path] = None
        entries = dir_listings[dir_path]
        if entries is None:
            continue

        split = split_res_token(basename)
        group = []

        if split is not None:
            prefix, _px, suffix = split
            prefix_key = prefix.lower()
            suffix_key = suffix.lower()

            for entry in entries:
                entry_split = split_res_token(entry)
                if entry_split is None:
                    continue
                e_prefix, e_px, e_suffix = entry_split
                if e_prefix.lower() == prefix_key and e_suffix.lower() == suffix_key:
                    group.append({"path": os.path.join(dir_path, entry), "px": e_px})

            bare_name = prefix.rstrip("_-.") + suffix
            if bare_name.lower() != basename.lower():
                entries_lower = {e.lower(): e for e in entries}
                found = entries_lower.get(bare_name.lower())
                if found:
                    group.append({"path": os.path.join(dir_path, found), "px": None})
        else:
            stem, ext = os.path.splitext(basename)
            candidate_prefixes = {(stem + d).lower() for d in ("_", "-", ".")}
            ext_key = ext.lower()

            for entry in entries:
                entry_split = split_res_token(entry)
                if entry_split is None:
                    continue
                e_prefix, e_px, e_suffix = entry_split
                if e_prefix.lower() in candidate_prefixes and e_suffix.lower() == ext_key:
                    group.append({"path": os.path.join(dir_path, entry), "px": e_px})

            if group:
                group.append({"path": os.path.join(dir_path, basename), "px": None})

        if len(group) < 2:
            continue
        group.sort(key=lambda g: (g["px"] is None, -(g["px"] or 0)))
        result[key] = group

    return result
