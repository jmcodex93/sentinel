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

import os
import re

UDIM = "udim"
UVTILE = "uvtile"

_UDIM_TAIL = re.compile(r"^(?P<base>.+?)(?P<sep>[._])(?P<tile>1\d{3})$")
_UVTILE_TAIL = re.compile(r"^(?P<base>.+?)_u(?P<u>\d+)_v(?P<v>\d+)$", re.IGNORECASE)
_TOKEN = re.compile(r"<(?:udim|uvtile)>", re.IGNORECASE)
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


def tile_regex(pattern):
    """Case-insensitive regex that FULL-matches the tile files of
    ``pattern`` (a name or a whole path holding one token); ``None`` when
    there is no token. Groups: ``tile`` for UDIM, ``u``/``v`` for UVTILE —
    read them with ``tile_number``."""
    text = str(pattern or "")
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
        tile = tile_number(rx.fullmatch(str(entry)))
        if tile is not None:
            tiles.add(tile)
    return sorted(tiles)


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
