# -*- coding: utf-8 -*-
"""Pure review-slate layout + PNG text-chunk helpers (sentinel.slate).

The in-C4D converter draws with GeClipMap; everything it decides (strip size,
font size, where each text goes, which colour, which metadata) lives here so
it is testable without C4D. ``measure`` is injected: a fake monospace width.
"""
import struct
import zlib

import pytest

from sentinel import slate


def mono(text):
    return 10 * len(text)


SLATE = {"shot": "robot_010", "version": "v007", "status": "TR", "score": "9/12",
         "artist": "Javièr", "date": "2026-10-02", "frame": 1024}


def test_strip_height_scales_with_image_and_has_a_floor():
    assert slate.strip_height(1080) == 49
    assert slate.strip_height(2160) == 97
    assert slate.strip_height(100) == 24


def test_font_size_is_half_the_strip():
    assert slate.font_size(49) == 24.5
    assert slate.font_size(24) == 12.0


def test_layout_left_block_badge_then_right_aligned_dim_text():
    ops = slate.slate_ops(1920, 49, 29, SLATE, mono)
    texts = [op[2] for op in ops]
    assert texts == ["robot_010 · v007   ", "TR · 9/12", "Javièr  ·  2026-10-02  ·  1024"]
    (x0, y0, _, c0), (x1, y1, _, c1), (x2, y2, t2, c2) = ops
    pad = 12  # max(6, 49 // 4)
    assert x0 == pad
    assert x1 == pad + mono("robot_010 · v007   ")
    assert x2 == 1920 - pad - mono(t2)
    assert y0 == y1 == y2 == (49 - 29) // 2
    assert c0 == slate.SLATE_TEXT_LIGHT
    assert c1 == slate.pick_badge_color("TR")
    assert c2 == slate.SLATE_TEXT_DIM


def test_layout_skips_empty_right_block():
    ops = slate.slate_ops(1920, 49, 29, {"shot": "a", "status": "WIP"}, mono)
    assert [op[2] for op in ops] == ["a   ", "WIP"]


def test_metadata_mirrors_the_slate_fields():
    meta = slate.slate_metadata(SLATE)
    assert meta == [("sentinel:shot", "robot_010"), ("sentinel:version", "v007"),
                    ("sentinel:status", "TR"), ("sentinel:score", "9/12"),
                    ("sentinel:artist", "Javièr"), ("sentinel:date", "2026-10-02"),
                    ("sentinel:frame", "1024")]
    assert ("sentinel:frame", "") not in slate.slate_metadata({"frame": ""})


def _png(chunks):
    out = b"\x89PNG\r\n\x1a\n"
    for ctype, data in chunks:
        out += struct.pack(">I", len(data)) + ctype + data + struct.pack(
            ">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    return out


def _tiny_png():
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    return _png([(b"IHDR", ihdr), (b"iCCP", b"sRGB\x00\x00x"), (b"IDAT", idat), (b"IEND", b"")])


def _chunks(data):
    pos, found = 8, []
    while pos < len(data):
        length, = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        crc, = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(ctype + body) & 0xFFFFFFFF
        found.append(ctype.decode("ascii"))
        pos += 12 + length
    return found


def test_png_text_round_trips_and_lands_right_after_ihdr():
    items = slate.slate_metadata(SLATE) + [("sentinel:note", "em dash — here")]
    data = slate.insert_png_text(_tiny_png(), items)
    assert _chunks(data) == ["IHDR"] + ["tEXt"] * 7 + ["iTXt", "iCCP", "IDAT", "IEND"]
    assert slate.read_png_text(data) == dict(items)


def test_latin1_text_uses_text_and_others_use_itxt():
    data = slate.insert_png_text(_tiny_png(), [("k1", "Mélgar ·"), ("k2", "Łukasz")])
    assert _chunks(data)[1:3] == ["tEXt", "iTXt"]
    assert slate.read_png_text(data) == {"k1": "Mélgar ·", "k2": "Łukasz"}


def test_insert_png_text_rejects_non_png():
    with pytest.raises(ValueError):
        slate.insert_png_text(b"not a png", [("k", "v")])


def test_pillow_reads_the_inserted_text():
    Image = pytest.importorskip("PIL.Image")
    import io
    data = slate.insert_png_text(_tiny_png(), slate.slate_metadata(SLATE))
    img = Image.open(io.BytesIO(data))
    img.load()
    assert img.text["sentinel:artist"] == "Javièr"
    assert img.text["sentinel:status"] == "TR"


def test_badge_colours_labels_and_lines_match_the_legacy_slate():
    assert slate.pick_badge_color("tr") == (255, 178, 36)
    assert slate.pick_badge_color("FINAL") == (69, 209, 131)
    assert slate.pick_badge_color("REV02") == slate.SLATE_DEFAULT_BADGE
    assert slate.pick_badge_color(None) == (150, 150, 150)
    assert slate.format_badge_label({"status": "TR", "score": "9/12"}) == "TR · 9/12"
    assert slate.format_badge_label({}) == "WIP"
    assert slate.build_slate_lines({}) == ("—", "")
    assert slate.build_slate_lines(SLATE) == ("robot_010 · v007", "Javièr  ·  2026-10-02  ·  1024")
