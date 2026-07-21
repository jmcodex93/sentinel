"""Pure image-header parsers for the Asset Hub — width/height/channels/
bit_depth/colorspace from a handful of bytes, no external imaging library.

Stdlib only. NEVER import c4d here (same pattern as assets.py / manifest.py).
Never raises: any exception anywhere in a parser is swallowed and the
public entry point returns None. Reads are bounded (~64KB per file) —
this only looks at file headers, never full pixel data.
"""
import os
import re
import struct

_MAX_READ = 65536

MIP_FACTOR = 4.0 / 3.0

_PNG_COLOR_TYPE_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_EXR_PIXEL_TYPE_BITS = {0: 32, 1: 16, 2: 32}  # uint, half, float


def read_image_meta(path):
    """Return {"width","height","channels","bit_depth","colorspace"} or None.

    Never raises. Dispatches by magic bytes; TGA has no magic and is
    dispatched by ".tga" extension as a last resort.
    """
    try:
        with open(path, "rb") as f:
            data = f.read(_MAX_READ)
    except Exception:
        return None
    if not data:
        return None

    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return _parse_png(data)
        if data[:2] == b"\xff\xd8":
            return _parse_jpeg(data)
        if data[:4] in (b"II*\x00", b"MM\x00*"):
            return _parse_tiff(data)
        if data[:4] == b"\x76\x2f\x31\x01":
            return _parse_exr(data)
        if data[:10] == b"#?RADIANCE" or data[:6] == b"#?RGBE":
            return _parse_hdr(data)
        if data[:2] == b"BM":
            return _parse_bmp(data)
        ext = os.path.splitext(str(path))[1].lower()
        if ext == ".tga":
            return _parse_tga(data)
    except Exception:
        return None
    return None


def vram_bytes(width, height, channels, bit_depth):
    """Rough GPU VRAM footprint estimate including mip chain overhead."""
    if not isinstance(channels, int) or channels < 1 or channels > 4:
        channels = 4
    if bit_depth not in (8, 16, 32):
        bit_depth = 8
    raw = width * height * channels * (bit_depth / 8.0)
    return int(raw * MIP_FACTOR)


def res_bucket(max_px):
    """Bucket the larger image dimension into a display tier."""
    if max_px >= 14336:
        return {"label": "16K", "tier": "16k"}
    if max_px >= 7168:
        return {"label": "8K", "tier": "8k"}
    if max_px >= 3584:
        return {"label": "4K", "tier": "4k"}
    if max_px >= 1536:
        return {"label": "2K", "tier": "2k"}
    if max_px >= 768:
        return {"label": "1K", "tier": "1k"}
    return {"label": "<1K", "tier": "sm"}


# ---------------------------------------------------------------------------
# Format parsers (each returns a meta dict or None; caller catches exceptions)
# ---------------------------------------------------------------------------

def _parse_png(data):
    if len(data) < 26 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    bit_depth = data[24]
    color_type = data[25]
    channels = _PNG_COLOR_TYPE_CHANNELS.get(color_type)
    if channels is None:
        return None

    colorspace = ""
    pos = 8
    n = len(data)
    guard = 0
    while pos + 8 <= n and guard < 2000:
        guard += 1
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        if ctype in (b"IDAT", b"IEND"):
            break
        if ctype == b"sRGB":
            colorspace = "sRGB"
            break
        pos += 8 + length + 4

    return {
        "width": width, "height": height, "channels": channels,
        "bit_depth": bit_depth, "colorspace": colorspace,
    }


def _parse_jpeg(data):
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    pos = 2
    n = len(data)
    guard = 0
    while pos + 2 <= n and guard < 2000:
        guard += 1
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0x00 or (0xD0 <= marker <= 0xD9) or marker == 0x01:
            pos += 2
            continue
        if pos + 4 > n:
            break
        seg_len = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            seg = data[pos + 4:pos + 4 + seg_len - 2]
            if len(seg) < 6:
                return None
            bit_depth = seg[0]
            height, width = struct.unpack(">HH", seg[1:5])
            channels = seg[5]
            colorspace = "YCbCr" if channels == 3 else ""
            return {
                "width": width, "height": height, "channels": channels,
                "bit_depth": bit_depth, "colorspace": colorspace,
            }
        if marker == 0xDA:  # SOS — entropy data follows, no more header markers
            return None
        pos += 2 + seg_len
    return None


def _tiff_value(data, endian, typ, count, value_field):
    if typ == 3:  # SHORT
        if count == 1:
            return struct.unpack(endian + "H", value_field[0:2])[0]
        offset = struct.unpack(endian + "I", value_field)[0]
        return struct.unpack(endian + "H", data[offset:offset + 2])[0]
    if typ == 4:  # LONG
        if count == 1:
            return struct.unpack(endian + "I", value_field)[0]
        offset = struct.unpack(endian + "I", value_field)[0]
        return struct.unpack(endian + "I", data[offset:offset + 4])[0]
    return None


def _parse_tiff(data):
    if len(data) < 8:
        return None
    if data[:4] == b"II*\x00":
        endian = "<"
    elif data[:4] == b"MM\x00*":
        endian = ">"
    else:
        return None

    ifd_offset = struct.unpack(endian + "I", data[4:8])[0]
    n = len(data)
    if ifd_offset + 2 > n:
        return None
    count = struct.unpack(endian + "H", data[ifd_offset:ifd_offset + 2])[0]

    tags = {}
    entry_off = ifd_offset + 2
    for _ in range(min(count, 1000)):
        entry = data[entry_off:entry_off + 12]
        if len(entry) < 12:
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", entry[0:8])
        value_field = entry[8:12]
        if tag in (256, 257, 258, 277):
            tags[tag] = _tiff_value(data, endian, typ, cnt, value_field)
        entry_off += 12

    if 256 not in tags or 257 not in tags or tags[256] is None or tags[257] is None:
        return None
    return {
        "width": tags[256], "height": tags[257],
        "channels": tags.get(277) or 1,
        "bit_depth": tags.get(258) or 8,
        "colorspace": "",
    }


def _parse_exr(data):
    n = len(data)
    if n < 8 or data[:4] != b"\x76\x2f\x31\x01":
        return None

    pos = 8
    width = height = None
    pixel_types = []
    guard = 0
    while pos < n and guard < 5000:
        guard += 1
        null_idx = data.find(b"\x00", pos)
        if null_idx == -1:
            break
        name = data[pos:null_idx]
        if name == b"":
            break
        pos = null_idx + 1

        type_null = data.find(b"\x00", pos)
        if type_null == -1:
            break
        pos = type_null + 1

        if pos + 4 > n:
            break
        size = struct.unpack("<i", data[pos:pos + 4])[0]
        pos += 4
        if size < 0 or pos + size > n:
            break
        attr_data = data[pos:pos + size]

        if name == b"dataWindow" and size >= 16:
            xmin, ymin, xmax, ymax = struct.unpack("<4i", attr_data[:16])
            width = xmax - xmin + 1
            height = ymax - ymin + 1
        elif name == b"channels":
            pixel_types = _parse_exr_chlist(attr_data)

        pos += size

    if width is None or height is None or not pixel_types:
        return None
    bit_depth = _EXR_PIXEL_TYPE_BITS.get(pixel_types[0], 32)
    return {
        "width": width, "height": height, "channels": len(pixel_types),
        "bit_depth": bit_depth, "colorspace": "linear",
    }


def _parse_exr_chlist(attr_data):
    pixel_types = []
    csize = len(attr_data)
    cpos = 0
    guard = 0
    while cpos < csize and guard < 1000:
        guard += 1
        cnull = attr_data.find(b"\x00", cpos)
        if cnull == -1:
            break
        cname = attr_data[cpos:cnull]
        if cname == b"":
            break
        cpos = cnull + 1
        if cpos + 16 > csize:
            break
        pt = struct.unpack("<i", attr_data[cpos:cpos + 4])[0]
        pixel_types.append(pt)
        cpos += 16
    return pixel_types


_HDR_RES_RE = re.compile(r"-Y\s+(\d+)\s+\+X\s+(\d+)")


def _parse_hdr(data):
    if not (data[:10] == b"#?RADIANCE" or data[:6] == b"#?RGBE"):
        return None
    text = data[:_MAX_READ].decode("latin-1", errors="ignore")
    m = _HDR_RES_RE.search(text)
    if not m:
        return None
    height = int(m.group(1))
    width = int(m.group(2))
    return {"width": width, "height": height, "channels": 3, "bit_depth": 32, "colorspace": "linear"}


def _parse_tga(data):
    if len(data) < 18:
        return None
    width, height = struct.unpack("<HH", data[12:16])
    depth = data[16]
    channels = depth // 8
    if channels <= 0:
        return None
    return {"width": width, "height": height, "channels": channels, "bit_depth": 8, "colorspace": ""}


def _parse_bmp(data):
    if len(data) < 30 or data[:2] != b"BM":
        return None
    width, height = struct.unpack("<ii", data[18:26])
    height = abs(height)
    bpp = struct.unpack("<H", data[28:30])[0]
    channels = max(1, bpp // 8)
    return {"width": width, "height": height, "channels": channels, "bit_depth": 8, "colorspace": ""}
