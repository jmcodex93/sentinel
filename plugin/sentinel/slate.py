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
import copy
import re
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


# ── Style (project ruleset key ``slate_style``) ────────────────────────────
#
# Defaults reproduce the original fixed slate. ``slots`` hold lists of items;
# each item is literal text with ``{token}`` placeholders, and an item whose
# tokens all resolve empty disappears together with its separator.

TOKENS = ("shot", "version", "status", "score", "artist", "date", "time", "frame",
          "scene", "take", "project", "camera", "resolution", "view", "post")
POSITIONS = ("below", "overlay")
SLOT_NAMES = ("left", "center", "right")
SLOT_SEPARATORS = {"left": " · ", "center": " · ", "right": "  ·  "}
OVERLAY_ALPHA = 0.65          # bar opacity when drawn over the image
MAX_ITEM_CHARS = 80
SIZE_RANGE = (0.5, 2.0)
DEFAULT_STYLE = {
    "position": "below",
    "slots": {"left": ["{shot}", "{version}"], "center": [],
              "right": ["{artist}", "{date}", "{frame}"]},
    "badge": True,
    "size": 1.0,
    # When the snapshot carries RenderView post that Sentinel re-applied, show
    # it ({post}) in the centre, unless the project already placed {post}.
    "show_post": True,
}
_TOKEN = re.compile(r"\{([a-z_]+)\}")


def default_style():
    return copy.deepcopy(DEFAULT_STYLE)


def validate_style(value):
    """``(ok, complete style, reason)`` for the ``slate_style`` ruleset key.

    Missing subkeys and missing slots take their defaults, so a project can
    declare only what it changes. Any bad subkey rejects the whole key, named.
    """
    if not isinstance(value, dict):
        return False, None, "expected an object"
    style = default_style()
    for key, item in value.items():
        if key == "position":
            if item not in POSITIONS:
                return False, None, "position must be one of %s" % ", ".join(POSITIONS)
            style["position"] = item
        elif key in ("badge", "show_post"):
            if not isinstance(item, bool):
                return False, None, "%s must be true or false" % key
            style[key] = item
        elif key == "size":
            if isinstance(item, bool) or not isinstance(item, (int, float)) \
                    or not SIZE_RANGE[0] <= item <= SIZE_RANGE[1]:
                return False, None, "size must be a number from %s to %s" % SIZE_RANGE
            style["size"] = float(item)
        elif key == "slots":
            if not isinstance(item, dict):
                return False, None, "slots must be an object with left/center/right"
            for slot, entries in item.items():
                if slot not in SLOT_NAMES:
                    return False, None, "unknown slot '%s' (use left, center, right)" % slot
                if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
                    return False, None, "slot '%s' must be a list of strings" % slot
                for entry in entries:
                    if len(entry) > MAX_ITEM_CHARS:
                        return False, None, "slot '%s' item longer than %d characters" % (
                            slot, MAX_ITEM_CHARS)
                    for token in _TOKEN.findall(entry):
                        if token not in TOKENS:
                            return False, None, "unknown token {%s} in slot '%s'" % (token, slot)
                style["slots"][slot] = list(entries)
        else:
            return False, None, "unknown option '%s'" % key
    return True, style, None


def compact_style(style):
    """Only what differs from the defaults, for writing to the ruleset —
    defaults written out would freeze them in the project file (the same rule
    as Publish standard). ``{}`` means "the default slate"."""
    out = {}
    for key, default in DEFAULT_STYLE.items():
        if key == "slots":
            slots = {name: list(style["slots"][name]) for name in SLOT_NAMES
                     if style["slots"].get(name, []) != default[name]}
            if slots:
                out["slots"] = slots
        elif style.get(key, default) != default:
            out[key] = style[key]
    return out


def _slot_text(entries):
    return " · ".join(entries) if entries else "(empty)"


def style_diff(old, new):
    """Human lines for what saving ``new`` over ``old`` changes (both complete
    styles, as ``validate_style`` returns them). Empty when nothing changes."""
    lines = []
    for key, label in (("position", "position"), ("size", "size"),
                       ("badge", "status badge"), ("show_post", "RenderView post")):
        if old.get(key) != new.get(key):
            fmt = (lambda v: "on" if v else "off") if isinstance(new.get(key), bool) else str
            lines.append("%s: %s → %s" % (label, fmt(old.get(key)), fmt(new.get(key))))
    for name in SLOT_NAMES:
        if old["slots"].get(name) != new["slots"].get(name):
            lines.append("%s: %s → %s" % (name, _slot_text(old["slots"].get(name)),
                                          _slot_text(new["slots"].get(name))))
    return lines


def render_item(item, fields):
    """Fill an item's tokens; '' when it has tokens and all of them are empty."""
    tokens = _TOKEN.findall(item)
    values = {t: str(fields.get(t) if fields.get(t) is not None else "").strip() for t in tokens}
    if tokens and not any(values.values()):
        return ""
    return _TOKEN.sub(lambda m: values.get(m.group(1), ""), item).strip()


def strip_height(image_height, size=1.0):
    """Height of the slate strip: 4.5% of the image × size, never under 24 px."""
    return max(24, int(round(image_height * 0.045 * size)))


def font_size(strip_h):
    """Text size in pixels for a strip of ``strip_h``."""
    return strip_h * 0.5


def _ellipsize(text, width, measure):
    if measure(text) <= width:
        return text
    while text and measure(text + "…") > width:
        text = text[:-1]
    return text + "…" if text else ""


def slate_ops(width, strip_h, text_h, fields, measure, style=None):
    """Draw operations ``[(x, y, text, rgb)]`` relative to the strip's top-left.

    ``measure(text) -> width in px`` and ``text_h`` come from the rasteriser
    with the font already set, so the layout matches what is actually drawn.
    When the text does not fit, items are dropped from the end of the right
    slot, then the centre, then the left; the badge is never dropped, and a
    last item that still does not fit is shortened with an ellipsis.
    """
    style = style or DEFAULT_STYLE
    fields = fields or {}
    pad = max(6, strip_h // 4)
    ty = max(0, (strip_h - text_h) // 2)
    items = {slot: [t for t in (render_item(i, fields) for i in style["slots"].get(slot, [])) if t]
             for slot in SLOT_NAMES}
    placed = any("{post}" in entry for entries in style["slots"].values() for entry in entries)
    auto_post = bool(style.get("show_post", True) and fields.get("post") and not placed)
    if auto_post:
        items["center"].append(str(fields["post"]))
    badge = format_badge_label(fields) if style.get("badge", True) else ""

    def texts():
        out = {slot: SLOT_SEPARATORS[slot].join(items[slot]) for slot in SLOT_NAMES}
        return out

    def widths(t):
        left_w = measure(t["left"] + "   ") if t["left"] else 0
        badge_w = measure(badge) if badge else 0
        return left_w + badge_w, measure(t["center"]) if t["center"] else 0, \
            measure(t["right"]) if t["right"] else 0

    def fits(t):
        lw, cw, rw = widths(t)
        room = width - 2 * pad
        if cw:
            half = (room - cw) / 2.0
            return lw + pad <= half and rw + pad <= half
        return lw + rw + (pad if lw and rw else 0) <= room

    t = texts()
    for slot in ("right", "center", "left"):
        while not fits(t) and len(items[slot]) > 1:
            items[slot].pop()
            t = texts()
        if slot == "right" and auto_post and not fits(t):
            # The automatic post is extra information: it goes whole, before
            # anything the project asked for in the centre or the left.
            items["center"].pop()
            auto_post = False
            t = texts()
    if not fits(t):
        lw, cw, rw = widths(t)
        room = width - 2 * pad
        if t["right"]:
            t["right"] = _ellipsize(t["right"], max(0, room - lw - (cw and cw + 2 * pad) - pad), measure)
        if not fits(t) and t["center"]:
            lw, cw, rw = widths(t)
            t["center"] = _ellipsize(t["center"], max(0, room - 2 * max(lw, rw) - 2 * pad), measure)
        if not fits(t) and t["left"]:
            lw, cw, rw = widths(t)
            avail = room - (measure(badge) if badge else 0) - rw - pad - measure("   ")
            t["left"] = _ellipsize(t["left"], max(0, avail), measure)

    ops = []
    x = pad
    if t["left"]:
        ops.append((x, ty, t["left"] + "   ", SLATE_TEXT_LIGHT))
        x += measure(t["left"] + "   ")
    if badge:
        ops.append((x, ty, badge, pick_badge_color(fields.get("status"))))
    if t["center"]:
        ops.append(((width - measure(t["center"])) // 2, ty, t["center"], SLATE_TEXT_LIGHT))
    if t["right"]:
        ops.append((width - pad - measure(t["right"]), ty, t["right"], SLATE_TEXT_DIM))
    return ops


def overlay_row(image_row, strip_row, bg=SLATE_STRIP_BG, alpha=OVERLAY_ALPHA):
    """Blend one RGB row of the drawn strip over one RGB row of the image.

    Bar pixels (exactly the strip background) are mixed at ``alpha``; text
    pixels are drawn opaque so the text stays legible on bright images.
    """
    out = bytearray(image_row)
    inv = 1.0 - alpha
    b0, b1, b2 = bg
    for i in range(0, len(out) - 2, 3):
        r, g, b = strip_row[i], strip_row[i + 1], strip_row[i + 2]
        if r == b0 and g == b1 and b == b2:
            out[i] = int(out[i] * inv + r * alpha + 0.5)
            out[i + 1] = int(out[i + 1] * inv + g * alpha + 0.5)
            out[i + 2] = int(out[i + 2] * inv + b * alpha + 0.5)
        else:
            out[i], out[i + 1], out[i + 2] = r, g, b
    return out


def slate_metadata(slate):
    """``[(key, value)]`` for the PNG text chunks, mirroring the slate fields."""
    slate = slate or {}
    items = [("sentinel:%s" % key, "" if slate.get(key) is None else str(slate.get(key)))
             for key in SLATE_METADATA_KEYS]
    if slate.get("frame") not in (None, ""):
        items.append(("sentinel:frame", str(slate.get("frame"))))
    for key in TOKENS:
        if key not in SLATE_METADATA_KEYS and key != "frame" and slate.get(key) not in (None, ""):
            items.append(("sentinel:%s" % key, str(slate.get(key))))
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
