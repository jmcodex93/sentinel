# -*- coding: utf-8 -*-
"""Review slate burned into snapshot PNGs — pure layout and PNG metadata.

No c4d import: the in-C4D adapter (``snapshot_c4d``) rasterises the text with
GeClipMap and only asks this module what to draw, where and in which colour.
The strip is appended BELOW the image (the original pixels are never touched):
left ``shot · vNNN`` + a colourised status badge, right a dimmed
``artist · date · frame``. The same fields travel as ``sentinel:*`` PNG text
chunks, written here with the standard library (tEXt for Latin-1 values, iTXt
for anything else) so no Pillow is needed.
"""
import struct
import zlib

# Status badge colours (RGB). Semantics always paired with the text label.
SLATE_STATUS_COLORS = {
    "WIP": (150, 150, 150),    # grey — not for review
    "TR": (255, 178, 36),      # amber — in review
    "CR": (255, 178, 36),      # amber — in review
    "FINAL": (69, 209, 131),   # green — approved
}
SLATE_DEFAULT_BADGE = (150, 150, 150)
SLATE_STRIP_BG = (11, 20, 26)       # dark instrument bar
SLATE_TEXT_LIGHT = (233, 237, 242)
SLATE_TEXT_DIM = (166, 176, 188)
SLATE_METADATA_KEYS = ("shot", "version", "status", "score", "artist", "date")

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def pick_badge_color(status):
    """Return the RGB badge colour for a review status (case-insensitive)."""
    if not status:
        return SLATE_STATUS_COLORS["WIP"]
    return SLATE_STATUS_COLORS.get(str(status).strip().upper(), SLATE_DEFAULT_BADGE)


def format_badge_label(slate):
    """The colourised badge text, e.g. 'TR · 9/12', 'FINAL · 12/12', 'WIP'."""
    status = (slate.get("status") or "WIP") if slate else "WIP"
    status = str(status).strip() or "WIP"
    score = str((slate.get("score") if slate else "") or "").strip()
    return f"{status} · {score}" if score else status


def build_slate_lines(slate):
    """The (left, right) text blocks: 'shot · vNNN' and 'artist · date · frame'."""
    slate = slate or {}
    shot = str(slate.get("shot") or "").strip() or "—"
    version = str(slate.get("version") or "").strip()
    left = f"{shot} · {version}".rstrip(" ·") if version else shot
    right = "  ·  ".join(str(slate.get(key)) for key in ("artist", "date", "frame")
                         if slate.get(key) not in (None, ""))
    return left, right


def strip_height(image_height):
    """Height of the slate strip: 4.5% of the image, never under 24 px."""
    return max(24, int(round(image_height * 0.045)))


def font_size(strip_h):
    """Text size in pixels for a strip of ``strip_h``."""
    return strip_h * 0.5


def slate_ops(width, strip_h, text_h, slate, measure):
    """Draw operations ``[(x, y, text, rgb)]`` relative to the strip's top-left.

    ``measure(text) -> width in px`` and ``text_h`` come from the rasteriser
    with the font already set, so the layout matches what is actually drawn.
    """
    pad = max(6, strip_h // 4)
    ty = max(0, (strip_h - text_h) // 2)
    left, right = build_slate_lines(slate)
    left_block = left + "   "
    ops = [(pad, ty, left_block, SLATE_TEXT_LIGHT),
           (pad + measure(left_block), ty, format_badge_label(slate),
            pick_badge_color((slate or {}).get("status")))]
    if right:
        ops.append((width - pad - measure(right), ty, right, SLATE_TEXT_DIM))
    return ops


def slate_metadata(slate):
    """``[(key, value)]`` for the PNG text chunks, mirroring the slate fields."""
    slate = slate or {}
    items = [("sentinel:%s" % key, "" if slate.get(key) is None else str(slate.get(key)))
             for key in SLATE_METADATA_KEYS]
    if slate.get("frame") not in (None, ""):
        items.append(("sentinel:frame", str(slate.get("frame"))))
    return items


def _chunk(ctype, data):
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def _text_chunk(key, value):
    keyword = key.encode("latin-1")
    try:
        return _chunk(b"tEXt", keyword + b"\x00" + value.encode("latin-1"))
    except UnicodeEncodeError:
        # iTXt: keyword, no compression, empty language tag and translated keyword.
        return _chunk(b"iTXt", keyword + b"\x00\x00\x00\x00\x00" + value.encode("utf-8"))


def insert_png_text(data, items):
    """Return ``data`` (a PNG file) with text chunks inserted right after IHDR."""
    if not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    ihdr_end = 8 + 12 + struct.unpack(">I", data[8:12])[0]
    text = b"".join(_text_chunk(key, value) for key, value in items)
    return data[:ihdr_end] + text + data[ihdr_end:]


def read_png_text(data):
    """``{key: value}`` from the tEXt/iTXt chunks of a PNG file."""
    out = {}
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"tEXt":
            key, _, value = body.partition(b"\x00")
            out[key.decode("latin-1")] = value.decode("latin-1")
        elif ctype == b"iTXt":
            key, _, rest = body.partition(b"\x00")
            # compression flag, method, language\0, translated keyword\0, text
            rest = rest[2:]
            _, _, rest = rest.partition(b"\x00")
            _, _, value = rest.partition(b"\x00")
            out[key.decode("latin-1")] = value.decode("utf-8")
        elif ctype == b"IEND":
            break
        pos += 12 + length
    return out
