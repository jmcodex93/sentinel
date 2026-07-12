# -*- coding: utf-8 -*-
"""Tests for the review-slate burn-in in exr_converter_external.py (I7).

The converter is a standalone script (runs outside C4D), so we load it by path
like tests/test_install.py loads install.py. Its top-level imports numpy + PIL,
so the whole module is skipped if those are unavailable.
"""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parents[1]
CONVERTER_PATH = ROOT / "plugin" / "exr_converter_external.py"


def _load_converter():
    spec = importlib.util.spec_from_file_location(
        "sentinel_exr_converter_under_test", str(CONVERTER_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conv = _load_converter()


# ── badge color pick ─────────────────────────────────────────────────────────
def test_pick_badge_color_known_statuses():
    assert conv.pick_badge_color("WIP") == (150, 150, 150)
    assert conv.pick_badge_color("TR") == (255, 178, 36)
    assert conv.pick_badge_color("CR") == (255, 178, 36)
    assert conv.pick_badge_color("FINAL") == (69, 209, 131)


def test_pick_badge_color_case_insensitive_and_defaults():
    assert conv.pick_badge_color("final") == (69, 209, 131)
    assert conv.pick_badge_color("tr") == (255, 178, 36)
    # Unknown custom tag falls back to the neutral badge.
    assert conv.pick_badge_color("REV02") == conv.SLATE_DEFAULT_BADGE
    # Missing status reads as WIP.
    assert conv.pick_badge_color(None) == (150, 150, 150)
    assert conv.pick_badge_color("") == (150, 150, 150)


# ── badge label ──────────────────────────────────────────────────────────────
def test_format_badge_label():
    assert conv.format_badge_label({"status": "TR", "score": "9/12"}) == "TR · 9/12"
    assert conv.format_badge_label({"status": "FINAL", "score": "12/12"}) == "FINAL · 12/12"
    # No score → status only.
    assert conv.format_badge_label({"status": "WIP", "score": ""}) == "WIP"
    # Empty status defaults to WIP.
    assert conv.format_badge_label({"status": "", "score": ""}) == "WIP"
    assert conv.format_badge_label({}) == "WIP"


# ── slate text lines ─────────────────────────────────────────────────────────
def test_build_slate_lines():
    slate = {
        "shot": "robot_010", "version": "v007", "status": "TR", "score": "9/12",
        "artist": "Javier", "date": "2026-07-10", "frame": 1024,
    }
    left, right = conv.build_slate_lines(slate)
    assert left == "robot_010 · v007"
    assert "Javier" in right and "2026-07-10" in right and "1024" in right


def test_build_slate_lines_missing_fields():
    left, right = conv.build_slate_lines({})
    assert left == "—"
    assert right == ""


# ── CLI parsing (backward compatible) ────────────────────────────────────────
def test_parse_cli_args_legacy_three_positional_no_slate():
    exr, png, mode, slate = conv.parse_cli_args(["a.exr", "b.png", "aces"])
    assert (exr, png, mode) == ("a.exr", "b.png", "aces")
    assert slate is None  # old 3-arg call → slate disabled


def test_parse_cli_args_two_positional_default_mode():
    exr, png, mode, slate = conv.parse_cli_args(["a.exr", "b.png"])
    assert (exr, png, mode, slate) == ("a.exr", "b.png", "auto", None)


def test_parse_cli_args_with_slate_flag():
    exr, png, mode, slate = conv.parse_cli_args(
        ["a.exr", "b.png", "aces", "--slate", "s.json"])
    assert (exr, png, mode, slate) == ("a.exr", "b.png", "aces", "s.json")


def test_parse_cli_args_slate_flag_anywhere():
    exr, png, mode, slate = conv.parse_cli_args(
        ["--slate", "s.json", "a.exr", "b.png", "aces"])
    assert (exr, png, mode, slate) == ("a.exr", "b.png", "aces", "s.json")


# ── Pillow compositing + metadata + OFF byte-identity ────────────────────────
def _dummy_image(w=120, h=80):
    from PIL import Image
    return Image.new("RGB", (w, h), (40, 90, 160))


def _expected_strip_h(h):
    return max(24, int(round(h * 0.045)))


def test_compose_slate_grows_by_strip_height():
    img = _dummy_image(120, 80)
    slate = {"shot": "sh010", "version": "v003", "status": "TR", "score": "9/12"}
    out = conv.compose_slate(img, slate)
    assert out.size == (120, 80 + _expected_strip_h(80))
    # Original pixels above the strip are preserved verbatim.
    assert out.getpixel((0, 0)) == (40, 90, 160)


def test_save_png_with_slate_writes_metadata_and_taller(tmp_path):
    from PIL import Image

    img = _dummy_image(200, 100)
    slate = {
        "shot": "robot_010", "version": "v007", "status": "TR", "score": "9/12",
        "artist": "Javier", "date": "2026-07-10", "frame": 1024,
    }
    out_path = tmp_path / "slate.png"
    conv._save_png(img, str(out_path), slate)

    reopened = Image.open(str(out_path))
    assert reopened.size == (200, 100 + _expected_strip_h(100))
    text = reopened.text
    assert text.get("sentinel:shot") == "robot_010"
    assert text.get("sentinel:version") == "v007"
    assert text.get("sentinel:status") == "TR"
    assert text.get("sentinel:score") == "9/12"
    assert text.get("sentinel:artist") == "Javier"
    assert text.get("sentinel:date") == "2026-07-10"
    assert text.get("sentinel:frame") == "1024"


def test_save_png_slate_off_is_byte_identical(tmp_path):
    """Slate-OFF path must match the legacy plain save exactly (criterion 1)."""
    img = _dummy_image(64, 48)

    ours = tmp_path / "off.png"
    reference = tmp_path / "ref.png"
    conv._save_png(img, str(ours), None)
    img.save(str(reference), "PNG", compress_level=0, optimize=False)

    assert ours.read_bytes() == reference.read_bytes()
