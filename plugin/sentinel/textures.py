# -*- coding: utf-8 -*-
"""Texture scanning and repathing engine."""

import os

import c4d

from sentinel.common.constants import MAX_OBJECTS_PER_CHECK
from sentinel.common.helpers import _iter_objs, safe_print

try:
    import maxon
    MAXON_AVAILABLE = True
except ImportError:
    MAXON_AVAILABLE = False

def _is_absolute_path(filepath):
    """Check if a file path is absolute (not relative)"""
    if not filepath:
        return False
    if len(filepath) > 2:
        if filepath[1] == ':' or filepath.startswith('\\\\'):
            return True
    if filepath.startswith('/'):
        return True
    return False


# ============================================================
# Texture scan + repathing helpers (QC #6 + v1.5.7 Repathing Tool)
# ============================================================
# Redshift-specific compound DescID file references. RS stores file
# paths on certain objects (dome HDR, IES profile, VDB volume, RS proxy)
# as a TWO-LEVEL DescID — root parameter id + REDSHIFT_FILE_PATH
# sub-field. These don't surface as filename params in the standard
# BaseContainer iterator; you have to query `obj[ROOT_ID, FILE_PATH_ID]`
# explicitly to read them.
#
# Constants discovered via renderEngine (DunHouGo) reference clone:
#   light[REDSHIFT_LIGHT_DOME_TEX0, REDSHIFT_FILE_PATH]      = hdr_path
#   light[REDSHIFT_LIGHT_PHYSICAL_TEXTURE, REDSHIFT_FILE_PATH]
#   light[REDSHIFT_LIGHT_IES_PROFILE, REDSHIFT_FILE_PATH]    = ies_path
#   volume[REDSHIFT_VOLUME_FILE, REDSHIFT_FILE_PATH]         = vdb_path
#   proxy[REDSHIFT_PROXY_FILE, REDSHIFT_FILE_PATH]           = proxy_path
RS_OBJECT_FILE_REFS = [
    ("REDSHIFT_LIGHT_DOME_TEX0",      "Dome HDR"),
    ("REDSHIFT_LIGHT_PHYSICAL_TEXTURE", "Light texture"),
    ("REDSHIFT_LIGHT_IES_PROFILE",    "IES profile"),
    ("REDSHIFT_VOLUME_FILE",          "Volume (VDB)"),
    ("REDSHIFT_PROXY_FILE",           "RS Proxy"),
]

# Known node-space identifiers for material node graphs. Sentinel's
# scan walks each registered space looking for file-bearing ports.
# Adding a new renderer means adding the space id here.
#
# IDs verified against the DunHouGo renderEngine constants/common_id.py.
# Note: **Octane is NOT here** — Octane materials in C4D 2026 use the
# legacy classic-shader chain API, not maxon node graphs. They're
# scanned separately as `octane_shader` records (see Octane image
# texture detection in the shader-chain walker below).
#
# V-Ray support is deliberately omitted — not part of Sentinel's
# target workflow. The walker IS generic enough to support it if the
# id is added to the tuple below.
RS_NODESPACE = "com.redshift3d.redshift4c4d.class.nodespace"
ARNOLD_NODESPACE = "com.autodesk.arnold.nodespace"
TEXTURE_NODE_SPACES = (
    ("redshift", RS_NODESPACE),
    ("arnold",   ARNOLD_NODESPACE),
)

# Octane uses the LEGACY classic shader chain on materials, with image
# textures as `c4d.BaseList2D(ID_OCTANE_IMAGE_TEXTURE)` nodes that store
# their path at `node[c4d.IMAGETEXTURE_FILE]`. The renderEngine
# README explicitly warns: "Due to Octane use his Custom UserArea UI
# base on old layer system, and didn't support python, we can only
# modify Octane materials in material level, but can not interactive
# with selections in octane node editor."
#
# Plugin type ID for Octane image texture nodes (from
# renderEngine/constants/octane_id.py):
ID_OCTANE_IMAGE_TEXTURE = 1029508


def _scan_shader_chain(host, host_name, owner_source_type, add_fn):
    """Walk `host`'s shader chain via GetFirstShader / GetNext.

    Detects:
      - `Xbitmap` (classic C4D Bitmap shader, type 5833) → reads
        `c4d.BITMAPSHADER_FILENAME`. This is also where Arnold stores
        the HDR for its Sky object — Arnold's `ArnoldShaderLinkCustomData`
        builds an Xbitmap and attaches it as a child shader of the
        sky/light object, so it shows up here.
      - `ID_OCTANE_IMAGE_TEXTURE` (1029508) → reads
        `c4d.IMAGETEXTURE_FILE`. Used by Octane image-texture nodes
        on materials AND on environment tags.

    `host` can be a BaseMaterial, a BaseObject, or a BaseTag — anything
    that responds to GetFirstShader / GetNext. The source_type recorded
    for each finding combines the owner kind with the shader kind:
      - "classic_shader"  — Xbitmap on a material
      - "octane_shader"   — Octane image on a material
      - "object_shader"   — Xbitmap on an object (e.g. Arnold Sky HDR)
      - "object_oct_shader" — Octane image on an object
      - "tag_shader"      — Xbitmap on a tag
      - "tag_oct_shader"  — Octane image on a tag (e.g. Octane Env Tag)
    """
    try:
        shader = host.GetFirstShader()
    except Exception:
        return
    while shader is not None:
        try:
            stype = shader.GetType()
        except Exception:
            stype = 0

        if stype == c4d.Xbitmap:
            try:
                fp = shader[c4d.BITMAPSHADER_FILENAME]
                if fp:
                    if owner_source_type == "material":
                        src = "classic_shader"
                    elif owner_source_type == "object":
                        src = "object_shader"
                    elif owner_source_type == "tag":
                        src = "tag_shader"
                    else:
                        src = "classic_shader"
                    add_fn(src, host, host_name, "Bitmap shader",
                           {"shader": shader}, str(fp))
            except Exception:
                pass
        elif stype == ID_OCTANE_IMAGE_TEXTURE:
            try:
                fp = shader[c4d.IMAGETEXTURE_FILE]
                if fp:
                    if owner_source_type == "material":
                        src = "octane_shader"
                    elif owner_source_type == "object":
                        src = "object_oct_shader"
                    elif owner_source_type == "tag":
                        src = "tag_oct_shader"
                    else:
                        src = "octane_shader"
                    add_fn(src, host, host_name, "Octane image",
                           {"shader": shader}, str(fp))
            except Exception:
                pass

        try:
            shader = shader.GetNext()
        except Exception:
            break

# Common subfolders to search when auto-finding a missing texture by
# filename only (Step 2's "Auto-Find Missing" smart action). Conservative
# strategy — exact filename match only, common mograph asset layouts.
_TEXTURE_SEARCH_SUBDIRS = ("", "tex", "textures", "Textures", "maps",
                          "Maps", "assets", "Assets", "img", "images",
                          "HDR", "hdr", "hdris", "HDRIs")

# Image / HDR extensions we recognize as textures. Used to filter out
# false positives when walking node port values that happen to be strings.
_TEXTURE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr", ".tx",
    ".tex", ".psd", ".bmp", ".gif", ".tga", ".dds", ".webp", ".iff",
    ".pic", ".picon", ".rla", ".rpf", ".sgi", ".rgb", ".rgba", ".jp2",
    ".cr2", ".dng", ".raw",
}


def _looks_like_texture_path(s):
    """Heuristic: does this string look like a texture file path?

    Recognized forms (verified empirically in C4D 2026):
      - `relative:///foo.jpg` — maxon Url with relative scheme, the
        most common form for RS node texture ports
      - `file:///abs/path.jpg` — maxon Url with absolute file scheme
      - `asset:abc123def` — RS Asset Manager managed reference
        (may not contain slashes — check BEFORE the slash gate)
      - `preset:rs/builtin/...` — RS preset reference
      - `/abs/path.jpg`, `C:/path/x.jpg`, `rel/path.jpg` — plain paths
        with a recognized extension
    """
    if not s or len(s) < 4:
        return False
    s = str(s).strip()
    if s in ("None", "<empty>", ""):
        return False
    # RS Asset Manager / preset URIs — may not contain slashes
    if s.startswith("asset:") or s.startswith("preset:"):
        return True
    lower = s.lower()
    # Maxon Url schemes (relative://, file://) + plain paths must
    # have a recognized image extension
    has_path_indicator = (
        s.startswith("relative://") or s.startswith("file://") or
        "/" in s or "\\" in s
    )
    if not has_path_indicator:
        return False
    return any(lower.endswith(ext) for ext in _TEXTURE_EXTENSIONS)


def compute_relative_texture_path(abs_path, doc_path):
    """Convert an absolute texture path to one relative to `doc_path`.

    Returns the relative path string on success, or None when:
      - `doc_path` is empty (doc never saved)
      - The two paths live on different drives / volumes (Windows
        cross-drive case)
      - The relative result climbs more than 4 levels up (`../../../../`
        which usually means the texture isn't in a sensible sibling
        location and a relative path would be fragile)

    Note: returns POSIX-style separators on all platforms (C4D accepts
    forward slashes uniformly).
    """
    if not abs_path or not doc_path:
        return None
    try:
        rel = os.path.relpath(abs_path, doc_path)
    except (ValueError, OSError):
        # Different drive on Windows raises ValueError
        return None
    # Reject overly-deep climbs
    if rel.count("..") > 4:
        return None
    # Reject if relpath bottomed out at the absolute path (no common root)
    if os.path.isabs(rel):
        return None
    return rel.replace("\\", "/")


def find_missing_texture_candidates(filename, doc_path,
                                    extra_search_dirs=None):
    """Conservative auto-find for a missing texture by filename match.

    Returns a list of absolute paths where a file with that EXACT
    filename exists. Empty list = not found.

    Searches `_TEXTURE_SEARCH_SUBDIRS` under `doc_path` (and any extra
    paths provided). Exact filename match only — no fuzzy / partial
    matching to avoid wrong-but-similar files.
    """
    if not filename or not doc_path:
        return []
    name = os.path.basename(filename)
    if not name:
        return []
    candidates = []
    search_dirs = list(_TEXTURE_SEARCH_SUBDIRS)
    if extra_search_dirs:
        search_dirs.extend(extra_search_dirs)
    for sub in search_dirs:
        candidate = os.path.join(doc_path, sub, name) if sub else os.path.join(doc_path, name)
        try:
            if os.path.isfile(candidate):
                candidates.append(candidate)
        except Exception:
            continue
    return candidates


def _c4d_texture_search_dirs():
    """C4D's own implicit texture search locations, beyond the doc folder.

    C4D resolves relative texture paths not just under the document's
    own tex/ subfolders but also via the user's startup "tex" folder and
    any enabled global texture path (Preferences > Files > Texture Paths).
    That's why GetAllAssetsNew can report a texture as "ok" while our
    doc-folder-only scan reports it "missing" for the same file. Best
    effort — must never raise, a scan should never break because this
    lookup failed.
    """
    dirs = []
    try:
        startup = c4d.storage.GeGetStartupWritePath()
        if startup:
            dirs.append(os.path.join(startup, "tex"))
    except Exception:
        pass
    try:
        for entry in (c4d.GetGlobalTexturePaths() or []):
            try:
                path, enabled = entry
            except Exception:
                continue
            if enabled and path:
                dirs.append(path)
    except Exception:
        pass
    return dirs


def _resolve_relative_texture(rel_path, doc_path, global_dirs=None):
    """Find a relative texture by searching standard texture subfolders.

    Replicates Redshift's automatic texture search behavior: a path like
    `xfgpebk_8K_Albedo.jpg` is found whether it sits at `<doc>/`,
    `<doc>/tex/`, `<doc>/textures/`, etc. Without this, every
    `relative:///foo.jpg` URL that points to a tex/ subfolder reads as
    MISSING even when RS Asset Manager shows it healthy.

    `global_dirs`, when given, extends the search to C4D's own implicit
    texture locations (user startup tex/ folder, enabled global texture
    paths) — the same places `GetAllAssetsNew` resolves against. Each
    global dir is tried both with the relative subpath joined on (mirrors
    the doc_path search) and with just the bare filename (C4D also
    matches global texture paths by filename alone).

    Returns the resolved absolute path or None if not found anywhere.
    """
    if not rel_path:
        return None
    rel = rel_path.lstrip("/")

    if doc_path:
        # Direct resolution first (covers paths that already include subdir)
        direct = os.path.normpath(os.path.join(doc_path, rel))
        if os.path.isfile(direct):
            return direct
        # Search common subdirs (matches RS texture search semantics)
        for subdir in _TEXTURE_SEARCH_SUBDIRS:
            if not subdir:
                continue
            cand = os.path.normpath(os.path.join(doc_path, subdir, rel))
            if os.path.isfile(cand):
                return cand

    if global_dirs:
        basename = os.path.basename(rel)
        for gdir in global_dirs:
            if not gdir:
                continue
            cand = os.path.normpath(os.path.join(gdir, rel))
            if os.path.isfile(cand):
                return cand
            if basename:
                cand = os.path.normpath(os.path.join(gdir, basename))
                if os.path.isfile(cand):
                    return cand

    return None


def _classify_texture_path(filepath, doc_path, global_dirs=None):
    """Classify a texture path into a status string.

    Status values:
      - "asset_uri" — internal asset:/preset: URI, RS Asset Manager
        managed (not user-repathable in the traditional sense).
      - "empty"   — empty / whitespace string.
      - "absolute" — absolute path on disk (raw or file:// URL).
      - "missing"  — relative path that doesn't resolve to an existing
                     file in `doc_path` or any standard texture subfolder.
      - "ok"       — relative path (raw or relative:// URL) that
                     resolves to a file on disk (anywhere RS would find it).

    Maxon URL schemes are recognized:
      - `relative:///foo.jpg` → relative to doc_path, searched
        across standard texture subfolders (tex/, textures/, etc.)
      - `file:///abs/path.jpg` → absolute

    Returns (status, resolved_abs_path_or_None).
    """
    if not filepath:
        return "empty", None
    s = str(filepath).strip()
    if not s:
        return "empty", None

    # RS Asset Manager / preset URIs
    if s.startswith("asset:") or s.startswith("preset:"):
        return "asset_uri", None

    # Maxon Url: relative://
    if s.startswith("relative://"):
        rel = s[len("relative://"):].lstrip("/")
        resolved = _resolve_relative_texture(rel, doc_path, global_dirs)
        if resolved is not None:
            return "ok", resolved
        # Fall back to the direct path for the "expected location" report
        direct = os.path.normpath(os.path.join(doc_path or ".", rel))
        return "missing", direct

    # Maxon Url: file://
    if s.startswith("file://"):
        abs_part = s[len("file://"):]
        # On Windows file:// URLs sometimes have a leading slash before drive
        if abs_part.startswith("/") and len(abs_part) > 3 and abs_part[2] == ":":
            abs_part = abs_part.lstrip("/")
        return "absolute", abs_part

    # Plain absolute path
    if _is_absolute_path(s):
        return "absolute", s

    # Plain relative path — same search-subdir fallback as relative://
    resolved = _resolve_relative_texture(s, doc_path, global_dirs)
    if resolved is not None:
        return "ok", resolved
    direct = os.path.normpath(os.path.join(doc_path or ".", s))
    return "missing", direct


def scan_all_texture_paths(doc):
    """Comprehensive scan of every texture path in the document.

    Returns a flat list of TextureRecord dicts — one per (texture-bearing
    location, current_path) pair. Includes everything: OK paths, absolute,
    missing, asset_uri.

    Each TextureRecord:
        {
          "source_type": str — "classic_shader" | "octane_shader" |
                                "bc_param" | "rs_node" | "arnold_node" |
                                "alembic" | "object_bc" |
                                "rs_object_fileref",
          "host":        BaseObject | BaseMaterial — live ref (for write-back)
          "host_name":   str — human-readable identifier
          "channel":     str — shader/channel name (e.g. "Diffuse")
          "context":     dict — source-specific extras (shader ref, port
                                ref, etc.) the writer uses to apply changes
          "current_path": str
          "status":      "ok" | "absolute" | "missing" | "asset_uri" | "empty"
          "resolved":    str | None — abs path on disk if it exists
        }

    Performance: caps at ~500 records (safety net for huge scenes). Most
    real scenes have 20–200 textures.
    """
    records = []
    if not doc:
        return records

    doc_path = doc.GetDocumentPath() or ""
    global_dirs = _c4d_texture_search_dirs()
    seen = set()  # dedupe by (host_id, channel, path) to avoid noise

    def _add(source_type, host, host_name, channel, context, path):
        if not path:
            return
        # Dedupe key — same shader-channel-path combo shouldn't be added twice
        try:
            host_id = id(host)
        except Exception:
            host_id = 0
        key = (source_type, host_id, channel, str(path))
        if key in seen:
            return
        seen.add(key)
        status, resolved = _classify_texture_path(str(path), doc_path, global_dirs)
        records.append({
            "source_type": source_type,
            "host":        host,
            "host_name":   host_name,
            "channel":     channel,
            "context":     context or {},
            "current_path": str(path),
            "status":      status,
            "resolved":    resolved,
        })

    try:
        materials = doc.GetMaterials() or []

        for mat in materials:
            if not mat:
                continue
            mat_name = mat.GetName() or "<unnamed>"

            # ── Classic + Octane shader chain on material ──
            _scan_shader_chain(mat, mat_name, "material", _add)

            # ── Material BaseContainer params (HDR/IBL, area light tex, etc.) ──
            try:
                bc = mat.GetDataInstance()
                if bc:
                    for desc_id, _ in bc:
                        try:
                            fp = bc.GetFilename(desc_id)
                            if fp and str(fp).strip():
                                _add("bc_param", mat, mat_name,
                                     "Material param",
                                     {"desc_id": desc_id}, str(fp))
                        except Exception:
                            pass
            except Exception:
                pass

            # ── Node graphs (RS / Octane / Arnold) ──
            if MAXON_AVAILABLE:
                try:
                    nodeMat = mat.GetNodeMaterialReference()
                except Exception:
                    nodeMat = None
                if nodeMat is not None:
                    for space_label, space_id in TEXTURE_NODE_SPACES:
                        try:
                            if not nodeMat.HasSpace(space_id):
                                continue
                            graph = nodeMat.GetGraph(space_id)
                            if graph is None:
                                continue
                            root = graph.GetViewRoot()
                            source_type = {
                                "redshift": "rs_node",
                                "arnold":   "arnold_node",
                            }.get(space_label, f"{space_label}_node")
                            # Pass the graph ref to the walker so it can
                            # store it in each record's context — required
                            # at write time for the maxon transaction.
                            _scan_node_graph(root, mat, mat_name,
                                             source_type, _add,
                                             graph_ref=graph)
                        except Exception:
                            continue

            if len(records) > 500:
                break

        # ── Object-level texture references ──
        # Covers: Alembic objects (ALEMBIC_PATH), RS Dome Light / Area
        # Light HDR textures (live in the object's BaseContainer), volume
        # cache files, etc. Anything stored as a BC filename param on a
        # scene object is captured here.
        if len(records) < 500:
            try:
                first = doc.GetFirstObject()
                if first:
                    for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                        if not obj:
                            continue
                        obj_name = obj.GetName() or "<obj>"

                        # Alembic objects use a specific param ID
                        # (type 1028083). Keep this as a distinct
                        # source_type for clearer reporting.
                        if obj.GetType() == 1028083:
                            try:
                                fp = obj[c4d.ALEMBIC_PATH]
                                if fp:
                                    _add("alembic", obj, obj_name,
                                         "Alembic cache", {}, str(fp))
                            except Exception:
                                pass

                        # Generic BC scan — catches simple filename params
                        # (anything that responds to bc.GetFilename(desc_id)).
                        try:
                            bc = obj.GetDataInstance()
                            if bc:
                                for desc_id, _ in bc:
                                    try:
                                        fp = bc.GetFilename(desc_id)
                                        if fp and str(fp).strip():
                                            _add("object_bc", obj, obj_name,
                                                 "Object param",
                                                 {"desc_id": desc_id}, str(fp))
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                        # Shader chain on the OBJECT itself — Arnold Sky /
                        # SkyDome stores its HDR as an Xbitmap shader
                        # attached to the light object (via
                        # ArnoldShaderLinkCustomData → Xbitmap shader
                        # under the object). Same path for any other
                        # renderer that follows the same pattern.
                        _scan_shader_chain(obj, obj_name, "object", _add)

                        # Tag shader chains — Octane's Environment Tag
                        # (type 1029643) holds its HDR as an Octane Image
                        # shader inside the tag's own shader chain. Other
                        # tags (texture tag, etc.) might do the same.
                        try:
                            tag = obj.GetFirstTag()
                            while tag is not None:
                                try:
                                    tag_name = tag.GetName() or "<tag>"
                                except Exception:
                                    tag_name = "<tag>"
                                _scan_shader_chain(
                                    tag,
                                    f"{obj_name} / {tag_name}",
                                    "tag", _add)
                                try:
                                    tag = tag.GetNext()
                                except Exception:
                                    break
                        except Exception:
                            pass

                        # Redshift compound-DescID file refs: HDR on dome
                        # lights, IES profiles, VDB volumes, RS proxies.
                        # These don't show up in the BC iterator — they
                        # use a `obj[ROOT_ID, REDSHIFT_FILE_PATH]` two-level
                        # access pattern (per renderEngine reference).
                        file_path_id = getattr(c4d, "REDSHIFT_FILE_PATH", None)
                        if file_path_id is not None:
                            for const_name, channel in RS_OBJECT_FILE_REFS:
                                root_id = getattr(c4d, const_name, None)
                                if root_id is None:
                                    continue
                                try:
                                    value = obj[root_id, file_path_id]
                                except Exception:
                                    continue
                                if value and str(value).strip():
                                    _add("rs_object_fileref", obj, obj_name,
                                         channel,
                                         {"root_id": root_id,
                                          "field_id": file_path_id},
                                         str(value))

                        if len(records) > 500:
                            break
            except Exception:
                pass
    except Exception as e:
        safe_print(f"scan_all_texture_paths error: {e}")

    return records


def _scan_node_graph(root_node, host_mat, mat_name, source_type, add_fn,
                    graph_ref=None):
    """Walk every GraphNode under `root_node` recursively, checking each
    node's `GetPortValue()` for texture-like paths.

    `graph_ref` is the maxon GraphModelRef that owns this node tree.
    Stored in each record's context so `apply_texture_path_change` can
    open a transaction at write time.

    Architecture note: in C4D 2026's maxon node graph API, `node.GetInputs()`
    does NOT return what we need for texture-bearing ports. Instead, inputs
    live as the `<` pseudo-child of each node (GraphNode kind=2), with
    individual port nodes nested below — and texture ports specifically
    have sub-port leaves like `path`, `colorspace`, `framerate`, etc.

    Empirically (verified with the v1.5.7 probe round), the leaf
    `path` GraphNode carries a maxon Url value like:
        `relative:///1679705615_celes-club-...jpg`
        `file:///Users/x/y.jpg`
        `asset:abc123` (RS Asset Manager)

    Walking by `GetChildren()` only (no `GetInputs()` reliance) and
    calling `GetPortValue()` on every descendant catches all of these
    forms uniformly. Depth cap = 20 to absorb deep texture sub-port
    hierarchies plus generous safety margin.
    """

    def read_port_value(node):
        """Return the port's value as a string if it looks like a
        texture path, otherwise None. We prefer `str(val)` over
        `GetSystemPath()` here so the URL scheme (`relative://`,
        `file://`) is preserved for the classifier — otherwise
        relative paths get resolved to absolute and we lose the
        "is this OK as relative or should it be flagged absolute?"
        distinction."""
        try:
            val = node.GetPortValue()
        except Exception:
            return None
        if val is None:
            return None
        try:
            s = str(val)
        except Exception:
            return None
        return s if _looks_like_texture_path(s) else None

    def walk(node, depth=0):
        if not node or depth > 20:
            return
        # Try reading a value from this node — most GraphNodes will
        # return None (they're container nodes or non-port-bearing
        # kinds), but leaf ports return their actual value.
        fp = read_port_value(node)
        if fp:
            # Human-friendly channel: last segment of dotted node id
            # (e.g. "com.redshift...filename.path" → "path")
            try:
                node_id = str(node.GetId())
            except Exception:
                node_id = "port"
            channel = node_id.split(".")[-1] if "." in node_id else node_id
            add_fn(source_type, host_mat, mat_name, channel,
                   {"port": node, "graph": graph_ref}, fp)
        try:
            for child in node.GetChildren():
                walk(child, depth + 1)
        except Exception:
            pass

    walk(root_node)


def apply_texture_path_change(record, new_path, doc=None):
    """Write `new_path` back to the texture record's host.

    Source-type dispatch:
      - classic_shader: shader[c4d.BITMAPSHADER_FILENAME] = new_path
      - octane_shader: shader[c4d.IMAGETEXTURE_FILE] = new_path
      - bc_param / object_bc: bc.SetFilename(desc_id, new_path)
      - alembic: obj[c4d.ALEMBIC_PATH] = new_path
      - rs_object_fileref: obj[root_id, c4d.REDSHIFT_FILE_PATH] = new_path
      - rs_node / arnold_node: maxon graph transaction with explicit
        Commit() — port.SetPortValue(maxon.Url(new_path)).

    Wraps the change in AddUndo when `doc` is provided so the entire
    Apply All operation can be reverted with a single Cmd+Z (caller is
    expected to bracket the loop with StartUndo / EndUndo).

    Returns True on success, False on failure (logs to console).
    """
    if not record or new_path is None:
        return False
    source_type = record.get("source_type")
    host = record.get("host")
    context = record.get("context") or {}

    try:
        # All Xbitmap-backed sources share one write path (material,
        # object, tag) — they're all shaders with BITMAPSHADER_FILENAME.
        if source_type in ("classic_shader", "object_shader", "tag_shader"):
            shader = context.get("shader")
            if shader is None:
                return False
            if doc is not None:
                try:
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, shader)
                except Exception:
                    pass
            shader[c4d.BITMAPSHADER_FILENAME] = new_path
            return True

        # All Octane Image-backed sources share one write path
        # (material, object, tag) — same IMAGETEXTURE_FILE param.
        elif source_type in ("octane_shader", "object_oct_shader",
                             "tag_oct_shader"):
            shader = context.get("shader")
            if shader is None:
                return False
            if doc is not None:
                try:
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, shader)
                except Exception:
                    pass
            shader[c4d.IMAGETEXTURE_FILE] = new_path
            return True

        elif source_type in ("bc_param", "object_bc"):
            # Same write path for both — bc_param lives on a material,
            # object_bc lives on an object. The mechanism is identical.
            desc_id = context.get("desc_id")
            if host is None or desc_id is None:
                return False
            bc = host.GetDataInstance()
            if bc is None:
                return False
            if doc is not None:
                try:
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, host)
                except Exception:
                    pass
            bc.SetFilename(desc_id, new_path)
            return True

        elif source_type == "alembic":
            if host is None:
                return False
            if doc is not None:
                try:
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, host)
                except Exception:
                    pass
            host[c4d.ALEMBIC_PATH] = new_path
            return True

        elif source_type == "rs_object_fileref":
            # Redshift compound DescID: host[ROOT_ID, FIELD_ID] = path
            root_id = context.get("root_id")
            field_id = context.get("field_id")
            if host is None or root_id is None or field_id is None:
                return False
            if doc is not None:
                try:
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, host)
                except Exception:
                    pass
            host[root_id, field_id] = new_path
            return True

        elif source_type in ("rs_node", "arnold_node"):
            # Node-graph port write via maxon transaction.
            # Pattern (verified in Cinema-4D-Python-API-Examples/
            # scripts/05_modules/node/modify_port_value_r26.py):
            #
            #   url = maxon.Url(new_path_str)
            #   with graph.BeginTransaction(userData) as transaction:
            #       port.SetPortValue(url)
            #       transaction.Commit()     # ← REQUIRED. The context
            #                                   manager exit does NOT
            #                                   auto-commit — it rolls
            #                                   back if Commit isn't
            #                                   called explicitly.
            #
            # We pass `UndoMode.ADD` in user_data so the transaction
            # joins the doc's outer StartUndo / EndUndo (the dialog's
            # Apply All wraps the whole batch for one-Cmd+Z reversal).
            if not MAXON_AVAILABLE:
                safe_print("apply_texture_path_change: maxon module "
                           "unavailable — skipping node-graph write.")
                return False
            port = context.get("port")
            graph = context.get("graph")
            if port is None or graph is None:
                safe_print(f"apply_texture_path_change: missing port/graph "
                           f"in context for {source_type}.")
                return False
            try:
                import maxon as _maxon
                url = _maxon.Url(str(new_path))
                # Register a classic undo on the host material BEFORE the
                # transaction. UNDOTYPE_CHANGE snapshots the whole material
                # (its embedded node graph included), so Cmd+Z reverts the
                # port edit. It ALSO gives the maxon transaction's
                # UndoMode.ADD a classic undo item inside the caller's open
                # StartUndo / EndUndo bracket to attach to — without this
                # anchor the bracket is empty and the node-graph change does
                # NOT join the document undo stack (mirrors the official
                # Maxon example create_redshift_nodematerial_2024.py, which
                # always calls doc.AddUndo before the ADD-mode transaction).
                if doc is not None and host is not None:
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_CHANGE, host)
                    except Exception:
                        pass
                user_data = _maxon.DataDictionary()
                try:
                    # Join the surrounding undo (StartUndo wrap from caller)
                    user_data.Set(_maxon.nodes.UndoMode,
                                  _maxon.nodes.UNDO_MODE.ADD)
                except Exception:
                    pass
                with graph.BeginTransaction(user_data) as transaction:
                    port.SetPortValue(url)
                    # CRITICAL: explicit commit. Without this, the
                    # transaction rolls back at `with` exit and the
                    # write silently vanishes — we'd see no exception
                    # but the value wouldn't change.
                    transaction.Commit()
                return True
            except Exception as e:
                safe_print(f"apply_texture_path_change: node-graph write "
                           f"failed for {source_type}: {e}")
                return False

        else:
            safe_print(f"apply_texture_path_change: unknown source_type "
                       f"{source_type!r}")
            return False
    except Exception as e:
        safe_print(f"apply_texture_path_change error ({source_type}): {e}")
        return False

