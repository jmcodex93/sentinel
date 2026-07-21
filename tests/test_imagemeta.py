"""Tests for plugin/sentinel/imagemeta.py — pure image header parsers.

Synthetic minimal headers are built in-test (no real image files / no
Pillow dependency). Helper builders are module-level so later tasks can
import them (see docs/superpowers/plans/2026-07-20-hub-polish.md Task 2).
"""
import struct

from sentinel import imagemeta


# ---------------------------------------------------------------------------
# Synthetic header builders (reusable by later tasks' tests)
# ---------------------------------------------------------------------------

def make_png(width, height, bit_depth, color_type, srgb=False):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    out = sig + ihdr_chunk
    if srgb:
        srgb_data = b"\x00"
        out += struct.pack(">I", len(srgb_data)) + b"sRGB" + srgb_data + b"\x00\x00\x00\x00"
    out += struct.pack(">I", 0) + b"IDAT" + b"\x00\x00\x00\x00"
    return out


def make_jpeg(width, height, bit_depth=8, channels=3, include_sof=True):
    soi = b"\xff\xd8"
    app0_data = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    app0 = b"\xff\xe0" + struct.pack(">H", len(app0_data) + 2) + app0_data
    out = soi + app0
    if include_sof:
        sof_body = (
            struct.pack(">B", bit_depth)
            + struct.pack(">HH", height, width)
            + struct.pack(">B", channels)
            + b"\x01\x11\x00"  # one minimal component descriptor
        )
        out += b"\xff\xc0" + struct.pack(">H", len(sof_body) + 2) + sof_body
    return out


def make_tiff(width, height, bit_depth, channels, big_endian=False):
    endian = ">" if big_endian else "<"
    magic = b"MM\x00*" if big_endian else b"II*\x00"
    entries = [
        (256, 4, 1, width),
        (257, 4, 1, height),
        (258, 3, 1, bit_depth),
        (277, 3, 1, channels),
    ]
    ifd = struct.pack(endian + "H", len(entries))
    for tag, typ, cnt, val in entries:
        if typ == 3:
            value_field = struct.pack(endian + "H", val) + b"\x00\x00"
        else:
            value_field = struct.pack(endian + "I", val)
        ifd += struct.pack(endian + "HHI", tag, typ, cnt) + value_field
    ifd += struct.pack(endian + "I", 0)  # next IFD offset
    header = magic + struct.pack(endian + "I", 8)
    return header + ifd


def make_exr(width, height, pixel_types=(1,)):
    magic = b"\x76\x2f\x31\x01"
    version = struct.pack("<I", 2)
    header = b""
    dw_data = struct.pack("<4i", 0, 0, width - 1, height - 1)
    header += b"dataWindow\x00" + b"box2i\x00" + struct.pack("<i", len(dw_data)) + dw_data
    ch_data = b""
    for i, pt in enumerate(pixel_types):
        name = ("ch%d" % i).encode("ascii") + b"\x00"
        ch_data += name + struct.pack("<i", pt) + b"\x00\x00\x00\x00" + struct.pack("<ii", 1, 1)
    ch_data += b"\x00"
    header += b"channels\x00" + b"chlist\x00" + struct.pack("<i", len(ch_data)) + ch_data
    header += b"\x00"
    return magic + version + header


def make_hdr(width, height, rgbe=False):
    magic = "#?RGBE" if rgbe else "#?RADIANCE"
    text = "%s\nFORMAT=32-bit_rle_rgbe\n\n-Y %d +X %d\n" % (magic, height, width)
    return text.encode("ascii")


def make_tga(width, height, depth=32):
    header = bytearray(18)
    struct.pack_into("<HH", header, 12, width, height)
    header[16] = depth
    return bytes(header)


def make_bmp(width, height, bpp=24):
    header = bytearray(30)
    header[0:2] = b"BM"
    struct.pack_into("<ii", header, 18, width, height)
    struct.pack_into("<H", header, 28, bpp)
    return bytes(header)


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------

def test_png_rgba_srgb(tmp_path):
    path = _write(tmp_path, "a.png", make_png(100, 50, 8, 6, srgb=True))
    assert imagemeta.read_image_meta(path) == {
        "width": 100, "height": 50, "channels": 4, "bit_depth": 8, "colorspace": "sRGB",
    }


def test_png_gray_no_srgb(tmp_path):
    path = _write(tmp_path, "a.png", make_png(64, 64, 8, 0, srgb=False))
    assert imagemeta.read_image_meta(path) == {
        "width": 64, "height": 64, "channels": 1, "bit_depth": 8, "colorspace": "",
    }


def test_png_rgb_16bit(tmp_path):
    path = _write(tmp_path, "a.png", make_png(4096, 4096, 16, 2))
    assert imagemeta.read_image_meta(path) == {
        "width": 4096, "height": 4096, "channels": 3, "bit_depth": 16, "colorspace": "",
    }


def test_png_truncated_ihdr_returns_none(tmp_path):
    full = make_png(100, 50, 8, 6)
    path = _write(tmp_path, "a.png", full[:20])  # cut mid-IHDR
    assert imagemeta.read_image_meta(path) is None


# ---------------------------------------------------------------------------
# JPEG
# ---------------------------------------------------------------------------

def test_jpeg_rgb(tmp_path):
    path = _write(tmp_path, "a.jpg", make_jpeg(1920, 1080, 8, 3))
    assert imagemeta.read_image_meta(path) == {
        "width": 1920, "height": 1080, "channels": 3, "bit_depth": 8, "colorspace": "YCbCr",
    }


def test_jpeg_grayscale_no_colorspace(tmp_path):
    path = _write(tmp_path, "a.jpg", make_jpeg(200, 100, 8, 1))
    assert imagemeta.read_image_meta(path) == {
        "width": 200, "height": 100, "channels": 1, "bit_depth": 8, "colorspace": "",
    }


def test_jpeg_without_sof_returns_none(tmp_path):
    path = _write(tmp_path, "a.jpg", make_jpeg(200, 100, include_sof=False))
    assert imagemeta.read_image_meta(path) is None


# ---------------------------------------------------------------------------
# TIFF
# ---------------------------------------------------------------------------

def test_tiff_little_endian(tmp_path):
    path = _write(tmp_path, "a.tif", make_tiff(800, 600, 16, 4))
    assert imagemeta.read_image_meta(path) == {
        "width": 800, "height": 600, "channels": 4, "bit_depth": 16, "colorspace": "",
    }


def test_tiff_big_endian(tmp_path):
    path = _write(tmp_path, "a.tif", make_tiff(320, 240, 8, 3, big_endian=True))
    assert imagemeta.read_image_meta(path) == {
        "width": 320, "height": 240, "channels": 3, "bit_depth": 8, "colorspace": "",
    }


# ---------------------------------------------------------------------------
# EXR
# ---------------------------------------------------------------------------

def test_exr_half_rgba(tmp_path):
    path = _write(tmp_path, "a.exr", make_exr(2048, 1024, pixel_types=(1, 1, 1, 1)))
    assert imagemeta.read_image_meta(path) == {
        "width": 2048, "height": 1024, "channels": 4, "bit_depth": 16, "colorspace": "linear",
    }


def test_exr_float_single_channel(tmp_path):
    path = _write(tmp_path, "a.exr", make_exr(512, 512, pixel_types=(2,)))
    assert imagemeta.read_image_meta(path) == {
        "width": 512, "height": 512, "channels": 1, "bit_depth": 32, "colorspace": "linear",
    }


def test_exr_uint_channel(tmp_path):
    path = _write(tmp_path, "a.exr", make_exr(100, 100, pixel_types=(0,)))
    meta = imagemeta.read_image_meta(path)
    assert meta["bit_depth"] == 32
    assert meta["colorspace"] == "linear"


def test_exr_corrupt_returns_none(tmp_path):
    full = make_exr(100, 100)
    path = _write(tmp_path, "a.exr", full[:10])
    assert imagemeta.read_image_meta(path) is None


# ---------------------------------------------------------------------------
# Radiance HDR
# ---------------------------------------------------------------------------

def test_hdr_radiance(tmp_path):
    path = _write(tmp_path, "a.hdr", make_hdr(1024, 512))
    assert imagemeta.read_image_meta(path) == {
        "width": 1024, "height": 512, "channels": 3, "bit_depth": 32, "colorspace": "linear",
    }


def test_hdr_rgbe_variant(tmp_path):
    path = _write(tmp_path, "a.hdr", make_hdr(200, 100, rgbe=True))
    assert imagemeta.read_image_meta(path) == {
        "width": 200, "height": 100, "channels": 3, "bit_depth": 32, "colorspace": "linear",
    }


# ---------------------------------------------------------------------------
# TGA (extension-only dispatch)
# ---------------------------------------------------------------------------

def test_tga_rgba(tmp_path):
    path = _write(tmp_path, "a.tga", make_tga(300, 200, depth=32))
    assert imagemeta.read_image_meta(path) == {
        "width": 300, "height": 200, "channels": 4, "bit_depth": 8, "colorspace": "",
    }


def test_tga_rgb(tmp_path):
    path = _write(tmp_path, "a.tga", make_tga(64, 64, depth=24))
    assert imagemeta.read_image_meta(path) == {
        "width": 64, "height": 64, "channels": 3, "bit_depth": 8, "colorspace": "",
    }


# ---------------------------------------------------------------------------
# BMP
# ---------------------------------------------------------------------------

def test_bmp_rgb(tmp_path):
    path = _write(tmp_path, "a.bmp", make_bmp(640, 480, bpp=24))
    assert imagemeta.read_image_meta(path) == {
        "width": 640, "height": 480, "channels": 3, "bit_depth": 8, "colorspace": "",
    }


def test_bmp_negative_height_top_down(tmp_path):
    path = _write(tmp_path, "a.bmp", make_bmp(100, -50, bpp=32))
    meta = imagemeta.read_image_meta(path)
    assert meta["width"] == 100
    assert meta["height"] == 50


# ---------------------------------------------------------------------------
# Corrupt / missing / unknown
# ---------------------------------------------------------------------------

def test_empty_file_returns_none(tmp_path):
    path = _write(tmp_path, "a.png", b"")
    assert imagemeta.read_image_meta(path) is None


def test_unknown_extension_returns_none(tmp_path):
    path = _write(tmp_path, "a.xyz", b"not an image at all")
    assert imagemeta.read_image_meta(path) is None


def test_nonexistent_file_returns_none(tmp_path):
    path = str(tmp_path / "does_not_exist.png")
    assert imagemeta.read_image_meta(path) is None


def test_garbage_bytes_with_known_extension_returns_none(tmp_path):
    path = _write(tmp_path, "a.tif", b"garbage" * 10)
    assert imagemeta.read_image_meta(path) is None


# ---------------------------------------------------------------------------
# res_bucket
# ---------------------------------------------------------------------------

def test_res_bucket_8k_boundary():
    assert imagemeta.res_bucket(7168) == {"label": "8K", "tier": "8k"}
    assert imagemeta.res_bucket(7167) == {"label": "4K", "tier": "4k"}


def test_res_bucket_4k_boundary():
    assert imagemeta.res_bucket(3584) == {"label": "4K", "tier": "4k"}
    assert imagemeta.res_bucket(3583) == {"label": "2K", "tier": "2k"}


def test_res_bucket_2k_boundary():
    assert imagemeta.res_bucket(1536) == {"label": "2K", "tier": "2k"}
    assert imagemeta.res_bucket(1535) == {"label": "<2K", "tier": "sm"}


def test_res_bucket_small():
    assert imagemeta.res_bucket(0) == {"label": "<2K", "tier": "sm"}


# ---------------------------------------------------------------------------
# vram_bytes
# ---------------------------------------------------------------------------

def test_vram_bytes_exact_value():
    assert imagemeta.vram_bytes(4096, 4096, 3, 8) == int(4096 * 4096 * 3 * (4.0 / 3.0))


def test_vram_bytes_defaults_channels():
    # channels out of 1..4 range defaults to 4
    assert imagemeta.vram_bytes(100, 100, 0, 8) == imagemeta.vram_bytes(100, 100, 4, 8)


def test_vram_bytes_defaults_bit_depth():
    # bit_depth not in {8,16,32} defaults to 8
    assert imagemeta.vram_bytes(100, 100, 3, 12) == imagemeta.vram_bytes(100, 100, 3, 8)


def test_vram_bytes_returns_int():
    assert isinstance(imagemeta.vram_bytes(101, 101, 3, 8), int)


def test_mip_factor_constant():
    assert imagemeta.MIP_FACTOR == 4.0 / 3.0
