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


# ── slate_style: validation and defaults ─────────────────────────────────────
def test_validate_style_fills_defaults_for_what_is_not_declared():
    ok, style, _ = slate.validate_style({"size": 1.5, "slots": {"center": ["ACME"]}})
    assert ok
    assert style["size"] == 1.5 and style["position"] == "below" and style["badge"] is True
    assert style["slots"] == {"left": ["{shot}", "{version}"], "center": ["ACME"],
                              "right": ["{artist}", "{date}", "{frame}"]}


@pytest.mark.parametrize("value, fragment", [
    ({"position": "above"}, "position"),
    ({"size": 3}, "size"),
    ({"size": True}, "size"),
    ({"badge": "yes"}, "badge"),
    ({"slots": {"top": []}}, "unknown slot 'top'"),
    ({"slots": {"left": "{shot}"}}, "list of strings"),
    ({"slots": {"left": ["{shoot}"]}}, "unknown token {shoot}"),
    ({"slots": {"left": ["x" * 81]}}, "longer than"),
    ({"colour": "red"}, "unknown option 'colour'"),
    ("below", "expected an object"),
])
def test_validate_style_rejects_bad_values_by_name(value, fragment):
    ok, style, reason = slate.validate_style(value)
    assert not ok and style is None
    assert fragment in reason


def test_default_style_reproduces_the_original_slate():
    assert slate.slate_ops(1920, 49, 29, SLATE, mono) == \
        slate.slate_ops(1920, 49, 29, SLATE, mono, slate.default_style())


# ── tokens and slots ─────────────────────────────────────────────────────────
def test_item_with_only_empty_tokens_disappears_with_its_separator():
    style = slate.default_style()
    ops = slate.slate_ops(1920, 49, 29, dict(SLATE, version=""), mono, style)
    assert ops[0][2] == "robot_010   "
    style["slots"]["left"] = ["ACME", "{project}", "{shot}"]
    ops = slate.slate_ops(1920, 49, 29, SLATE, mono, style)
    assert ops[0][2] == "ACME · robot_010   "


def test_render_item_fills_tokens_and_keeps_literal_text():
    fields = {"take": "cam_A", "resolution": "1920x1080"}
    assert slate.render_item("Take {take} @ {resolution}", fields) == "Take cam_A @ 1920x1080"
    assert slate.render_item("Client review", fields) == "Client review"
    assert slate.render_item("{camera}", fields) == ""


def test_center_slot_is_centred_and_badge_can_be_switched_off():
    style = slate.default_style()
    style["slots"]["center"] = ["ACME"]
    style["badge"] = False
    ops = slate.slate_ops(1000, 40, 20, SLATE, mono, style)
    assert [op[2] for op in ops] == ["robot_010 · v007   ", "ACME", "Javièr  ·  2026-10-02  ·  1024"]
    assert ops[1][0] == (1000 - mono("ACME")) // 2


def test_overflow_drops_right_items_first_and_never_the_badge():
    # room 460 px: left+badge 280, full right 300 → frame, then date, dropped
    texts = [op[2] for op in slate.slate_ops(480, 40, 20, SLATE, mono)]
    assert texts == ["robot_010 · v007   ", "TR · 9/12", "Javièr"]
    # room 580 px: only the frame has to go
    texts = [op[2] for op in slate.slate_ops(600, 40, 20, SLATE, mono)]
    assert texts[2] == "Javièr  ·  2026-10-02"


def test_a_single_item_too_long_is_ellipsized():
    style = slate.default_style()
    style["slots"]["right"] = ["{artist}"]
    ops = slate.slate_ops(400, 40, 20, dict(SLATE, artist="A" * 60), mono, style)
    right = ops[-1][2]
    assert right.endswith("…") and mono(right) <= 400


def test_size_scales_the_strip():
    assert slate.strip_height(1080, 2.0) == 97
    assert slate.strip_height(1080, 0.5) == 24


def test_overlay_row_blends_the_bar_and_keeps_text_opaque():
    image = bytearray([200, 200, 200] * 2)
    strip = bytes(list(slate.SLATE_STRIP_BG) + [233, 237, 242])
    out = slate.overlay_row(image, strip)
    a = slate.OVERLAY_ALPHA
    assert list(out[:3]) == [int(200 * (1 - a) + c * a + 0.5) for c in slate.SLATE_STRIP_BG]
    assert list(out[3:]) == [233, 237, 242]


def test_metadata_includes_extra_fields_when_present():
    meta = dict(slate.slate_metadata(dict(SLATE, take="cam_A", view="ACES 1.0 SDR-video", camera="")))
    assert meta["sentinel:take"] == "cam_A"
    assert meta["sentinel:view"] == "ACES 1.0 SDR-video"
    assert "sentinel:camera" not in meta


def test_item_with_literal_text_but_empty_tokens_disappears_whole():
    """'f{frame}' without a frame must not leave a stray 'f' in the slate."""
    assert slate.render_item("f{frame}", {"frame": ""}) == ""
    assert slate.render_item("Take {take}", {}) == ""
    assert slate.render_item("{date} {time}", {"date": "2026-10-02"}) == "2026-10-02"
