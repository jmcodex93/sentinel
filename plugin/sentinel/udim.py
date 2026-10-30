# -*- coding: utf-8 -*-
"""UDIM / UVTILE tile naming (v1.42) — PURE, no ``import c4d``.

The single source of what a tiled texture looks like on disk and in a
Redshift sampler path, shared by the Matwire engine, the texture resolver,
the Asset Hub and the colourspace check. Measured
(docs/research/2026-10-29-redshift-udim.md): Redshift resolves ``<UDIM>``
(1001 + v·10 + u) and ``<UVTILE>`` in ``tex0/path``, case-insensitively;
``<UVTILE>`` absorbs the underscore before ``u1_v1``; a tile missing on disk
renders black, silently.

Tiles are recognized only at the END of a filename stem (Painter
``…_1001``, Mari ``….1001``, Mudbox ``…_u1_v1``). UVTILE numbers are kept
as their UDIM equivalent (``u1_v1`` = 1001) so labels read the same.
"""

import math
import os
import re
import unicodedata

UDIM = "udim"
UVTILE = "uvtile"

_UDIM_TAIL = re.compile(r"^(?P<base>.+?)(?P<sep>[._])(?P<tile>1\d{3})$")
_UVTILE_TAIL = re.compile(r"^(?P<base>.+?)_u(?P<u>\d+)_v(?P<v>\d+)$", re.IGNORECASE)
TOKEN_RE = _TOKEN = re.compile(r"<(?:udim|uvtile)>", re.IGNORECASE)
_STRIP_TOKEN = re.compile(r"[._]?<udim>|<uvtile>", re.IGNORECASE)
#: UDIM has ten columns (u 0..9); UVTILE columns past that have no UDIM number.
_MAX_U = 10


def _uvtile_number(u, v):
    if 1 <= u <= _MAX_U and v >= 1:
        return 1000 + u + (v - 1) * 10
    return None


def split_tile(stem):
    """``{"base", "tile", "scheme", "sep"}`` when ``stem`` ends in a tile,
    else ``None``. ``sep`` is the separator found before a UDIM number
    (``.`` or ``_``) and is empty for UVTILE, whose token absorbs it."""
    stem = str(stem or "")
    m = _UDIM_TAIL.match(stem)
    if m and int(m.group("tile")) >= 1001:
        return {"base": m.group("base"), "tile": int(m.group("tile")),
                "scheme": UDIM, "sep": m.group("sep")}
    m = _UVTILE_TAIL.match(stem)
    if m:
        tile = _uvtile_number(int(m.group("u")), int(m.group("v")))
        if tile is not None:
            return {"base": m.group("base"), "tile": tile,
                    "scheme": UVTILE, "sep": ""}
    return None


def pattern_name(base, scheme, sep, ext):
    """The Redshift path for a tile family: ``base.<UDIM>.ext`` keeps the
    separator found on disk; ``base<UVTILE>.ext`` drops it (measured: the
    token stands for ``_u1_v1``)."""
    if scheme == UVTILE:
        return "%s<UVTILE>%s" % (base, ext)
    return "%s%s<UDIM>%s" % (base, sep, ext)


def has_token(path):
    return bool(_TOKEN.search(str(path or "")))


def strip_token(stem):
    """``stem`` without its tile token (and the separator before a UDIM
    token) — so a sampler path's name can be matched to a channel."""
    return _STRIP_TOKEN.sub("", str(stem or ""))


def _nfc(text):
    """NFC form: APFS/SMB can return decomposed names (``n`` + U+0303) for
    what the pattern spells composed, which would read as a missing tile."""
    return unicodedata.normalize("NFC", str(text or ""))


def tile_regex(pattern):
    """Case-insensitive regex that FULL-matches the tile files of
    ``pattern`` (a name or a whole path holding one token); ``None`` when
    there is no token. Groups: ``tile`` for UDIM, ``u``/``v`` for UVTILE —
    read them with ``tile_number``."""
    text = _nfc(pattern)
    m = _TOKEN.search(text)
    if not m:
        return None
    if m.group(0).lower() == "<udim>":
        body = r"(?P<tile>1\d{3})"
    else:
        body = r"_u(?P<u>\d+)_v(?P<v>\d+)"
    return re.compile(re.escape(text[:m.start()]) + body
                      + re.escape(text[m.end():]), re.IGNORECASE)


def tile_number(match):
    """UDIM number of a ``tile_regex`` match, or ``None`` when the numbers
    are outside what UDIM can address."""
    if match is None:
        return None
    groups = match.groupdict()
    if groups.get("tile"):
        tile = int(groups["tile"])
        return tile if tile >= 1001 else None
    return _uvtile_number(int(groups["u"]), int(groups["v"]))


def tile_path(pattern, tile):
    """The concrete file of ``tile`` in ``pattern`` (the inverse of
    ``pattern_name``); ``pattern`` unchanged when it has no token."""
    text = str(pattern or "")
    m = _TOKEN.search(text)
    if not m:
        return text
    tile = int(tile)
    if m.group(0).lower() == "<udim>":
        body = str(tile)
    else:
        body = "_u%d_v%d" % ((tile - 1001) % 10 + 1, (tile - 1001) // 10 + 1)
    return text[:m.start()] + body + text[m.end():]


def list_tiles(pattern_path, listdir=os.listdir):
    """Sorted tile numbers of ``pattern_path`` present on disk — one
    ``listdir`` of its folder. ``[]`` when there is no token or the folder
    can't be read (never raises: callers report that as missing)."""
    folder, name = os.path.split(str(pattern_path or ""))
    rx = tile_regex(name)
    if rx is None:
        return []
    try:
        entries = listdir(folder or os.curdir)
    except OSError:
        return []
    tiles = set()
    for entry in entries:
        tile = tile_number(rx.fullmatch(_nfc(entry)))
        if tile is not None:
            tiles.add(tile)
    return sorted(tiles)


def redshift_unresolved(path, tiles):
    """Why Redshift reports a ``<UDIM>`` pattern ``Not Found`` although tiles
    exist (measured 2026-10-30, docs/research/2026-10-30-redshift-udim-needs-
    tile-1001.md), or ``None`` when it resolves:

    - ``"1001_in_path"``: ``1001`` also appears outside the token (a
      ``shot_1001`` folder) — Redshift re-patterns every ``1001`` of the
      1001 tile's path, so the lookup fails whatever is on disk;
    - ``"no_1001"``: tile 1001 isn't among ``tiles`` — Redshift looks the
      pattern up through it, and the whole texture goes missing.

    ``<UVTILE>`` returns ``None``: not measured."""
    text = str(path or "")
    m = _TOKEN.search(text)
    if not m or m.group(0).lower() != "<udim>":
        return None
    if "1001" in text[:m.start()] + text[m.end():]:
        return "1001_in_path"
    if 1001 not in {int(t) for t in tiles or ()}:
        return "no_1001"
    return None


def format_tiles(tiles):
    """``"1001–1004, 1006–1010"`` — consecutive numbers collapse to a run."""
    nums = sorted({int(t) for t in tiles or ()})
    parts = []
    start = prev = None
    for n in nums:
        if start is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            parts.append(str(start) if start == prev else "%d–%d" % (start, prev))
        start = prev = n
    if start is not None:
        parts.append(str(start) if start == prev else "%d–%d" % (start, prev))
    return ", ".join(parts)


def tile_of_uv(u, v):
    """UDIM tile Redshift reads at C4D UV ``(u, v)``, or ``None`` when no
    tile can be addressed there (renders black). Measured: 1011 is C4D
    v in [−1, 0] — C4D's v runs opposite to the UDIM rows — and v in
    [1, 2] reads no tile."""
    col = math.floor(u)
    row = math.floor(1.0 - v)
    if 0 <= col < _MAX_U and row >= 0:
        return 1001 + col + 10 * row
    return None


def tiles_of_polygons(uv_floats, poly_indices=None):
    """Tiles under the polygons of a UVW tag. ``uv_floats`` is the tag's
    low-level layout (measured, 2026.304): 8 floats per polygon, corners
    a, b, c, d as (u, v); a triangle repeats c in d. Each polygon counts
    at its UV centroid. ``poly_indices`` limits the read to those polygons.
    The set holds ``None`` when some polygon sits where no tile can be
    addressed."""
    us = uv_floats[0::2]
    vs = uv_floats[1::2]
    count = len(us) // 4
    floor = math.floor
    if poly_indices is None:
        centroids = zip(
            (a + b + c + d for a, b, c, d in zip(us[0::4], us[1::4], us[2::4], us[3::4])),
            (a + b + c + d for a, b, c, d in zip(vs[0::4], vs[1::4], vs[2::4], vs[3::4])))
    else:
        centroids = ((us[4 * i] + us[4 * i + 1] + us[4 * i + 2] + us[4 * i + 3],
                      vs[4 * i] + vs[4 * i + 1] + vs[4 * i + 2] + vs[4 * i + 3])
                     for i in poly_indices if 0 <= i < count)
    cells = {(floor(su * 0.25), floor(1.0 - sv * 0.25)) for su, sv in centroids}
    return {1001 + col + 10 * row if 0 <= col < _MAX_U and row >= 0 else None
            for col, row in cells}


def tile_gaps(used, maps):
    """QC #14 verdict for one object and one material. ``used``: the tiles
    under its polygons (``tiles_of_polygons``, may hold ``None``); ``maps``:
    ``[(name, tiles on disk)]`` for the material's tiled samplers. ``None``
    when every used tile has a texture in every map; otherwise the missing
    tiles, the maps that lack one, and whether some UVs sit where no tile
    can be addressed — all of it renders black (measured)."""
    tiles = {t for t in used if t is not None}
    missing = set()
    lacking = []
    for name, on_disk in maps:
        gap = tiles - set(on_disk)
        if gap:
            missing |= gap
            lacking.append(name)
    out_of_range = None in used
    if not missing and not out_of_range:
        return None
    return {"missing": sorted(missing), "maps": lacking, "out_of_range": out_of_range}
