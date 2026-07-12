#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
External EXR to PNG Converter for Sentinel
Uses system Python with OpenEXR and Pillow
"""

import sys
import os
import json
import numpy as np
from PIL import Image

# ── Review slate (I7) ────────────────────────────────────────────────────────
# A bottom burn-in strip stamped onto review PNGs so a client can never mistake
# a WIP for a FINAL. Pillow-only, default bitmap font (no font files bundled).
# The strip is COMPOSITED (image grows by the strip height) — the review pixels
# above it are never overwritten. Metadata is mirrored into PNG text chunks.

# Status badge colors (RGB). Semantics always paired with the text label.
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


def pick_badge_color(status):
    """Return the RGB badge color for a review status (case-insensitive)."""
    if not status:
        return SLATE_STATUS_COLORS["WIP"]
    return SLATE_STATUS_COLORS.get(str(status).strip().upper(), SLATE_DEFAULT_BADGE)


def format_badge_label(slate):
    """The colorized badge text, e.g. 'TR · 9/12', 'FINAL · 12/12', 'WIP'."""
    status = (slate.get("status") or "WIP") if slate else "WIP"
    status = str(status).strip() or "WIP"
    score = str((slate.get("score") if slate else "") or "").strip()
    return f"{status} · {score}" if score else status


def build_slate_lines(slate):
    """Assemble the (left, right) text blocks for the slate strip.

    left  : 'shot · vNNN' (the badge is drawn separately, colorized)
    right : 'artist · date · frame' (blank parts skipped)
    """
    slate = slate or {}
    shot = str(slate.get("shot") or "").strip() or "—"
    version = str(slate.get("version") or "").strip()
    left = f"{shot} · {version}".rstrip(" ·") if version else shot

    right_parts = []
    for key in ("artist", "date", "frame"):
        val = slate.get(key)
        if val not in (None, ""):
            right_parts.append(str(val))
    right = "  ·  ".join(right_parts)
    return left, right


def load_slate_data(path):
    """Load slate JSON written by the Sentinel caller. Returns a dict or None."""
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        print(f"Warning: could not read slate data {path}: {exc}")
        return None
    return data if isinstance(data, dict) else None


def build_png_info(slate):
    """Build a PngInfo carrying sentinel:* text chunks mirroring the slate."""
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    slate = slate or {}
    for key in SLATE_METADATA_KEYS:
        val = slate.get(key)
        info.add_text("sentinel:%s" % key, "" if val is None else str(val))
    frame = slate.get("frame")
    if frame not in (None, ""):
        info.add_text("sentinel:frame", str(frame))
    return info


def _measure_text(draw, text, font):
    try:
        return int(draw.textlength(text, font=font))
    except Exception:
        try:
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0])
        except Exception:
            return len(text) * 6


def compose_slate(img, slate):
    """Return a new image with the slate strip composited beneath ``img``.

    The original pixels are preserved verbatim; the canvas grows downward by the
    strip height (max(24, ~4.5% of image height)).
    """
    from PIL import ImageDraw, ImageFont

    img = img.convert("RGB")
    w, h = img.size
    strip_h = max(24, int(round(h * 0.045)))

    out = Image.new("RGB", (w, h + strip_h), SLATE_STRIP_BG)
    out.paste(img, (0, 0))

    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default()

    try:
        text_h = font.getbbox("Ag")[3]
    except Exception:
        text_h = 11
    pad = max(6, strip_h // 4)
    ty = h + max(0, (strip_h - text_h) // 2)

    left, right = build_slate_lines(slate)
    badge = format_badge_label(slate)
    badge_color = pick_badge_color(slate.get("status") if slate else None)

    x = pad
    left_block = left + "   "
    draw.text((x, ty), left_block, fill=SLATE_TEXT_LIGHT, font=font)
    x += _measure_text(draw, left_block, font)
    draw.text((x, ty), badge, fill=badge_color, font=font)

    if right:
        rw = _measure_text(draw, right, font)
        draw.text((w - pad - rw, ty), right, fill=SLATE_TEXT_DIM, font=font)

    return out


def _save_png(img, png_path, slate_data=None):
    """Save PNG. With no slate: byte-identical to the legacy plain save."""
    if slate_data:
        composed = compose_slate(img, slate_data)
        composed.save(png_path, 'PNG', compress_level=0, optimize=False,
                      pnginfo=build_png_info(slate_data))
    else:
        img.save(png_path, 'PNG', compress_level=0, optimize=False)


# Try to import OpenEXR
try:
    import OpenEXR
    import Imath
    HAS_OPENEXR = True
except ImportError:
    HAS_OPENEXR = False
    print("Warning: OpenEXR not available, will try Pillow only")


def apply_aces_tone_mapping(linear_rgb):
    """Apply ACES RRT/ODT tone mapping approximation
    This approximates the ACES 1.0 SDR Video (REC709/sRGB) view transform
    """
    # ACES RRT/ODT approximation
    # Based on the ACES filmic tone mapping curve
    x = linear_rgb

    # Exposure adjustment (ACES uses 0.6 exposure by default)
    x = x * 0.6

    # ACES tone mapping matrix coefficients
    a = 2.51
    b = 0.03
    c = 2.43
    d = 0.59
    e = 0.14

    # Apply the ACES curve
    result = ((x*(a*x+b))/(x*(c*x+d)+e))

    return np.clip(result, 0, 1)


def acescg_to_linear_srgb(acescg):
    """Convert from ACEScg color space to linear sRGB
    Uses the proper ACEScg to sRGB primaries transformation
    """
    # ACEScg to linear sRGB matrix
    # This matrix accounts for the different primaries between ACEScg and sRGB
    matrix = np.array([
        [ 1.70505, -0.62179, -0.08326],
        [-0.13026,  1.14080, -0.01055],
        [-0.02400, -0.12897,  1.15297]
    ])

    # Reshape for matrix multiplication
    shape = acescg.shape
    pixels = acescg.reshape(-1, 3)

    # Apply the color space transformation
    linear_srgb = np.dot(pixels, matrix.T)

    # Reshape back
    return linear_srgb.reshape(shape)


def apply_redshift_display_transform(linear_rgb):
    """Apply a display transform that mimics Redshift's RenderView
    Combines ACES tone mapping with proper sRGB encoding
    """
    # Step 1: Convert from ACEScg to linear sRGB if needed
    # (Assuming input is in ACEScg space as that's Redshift's default)
    linear_srgb = acescg_to_linear_srgb(linear_rgb)

    # Step 2: Apply ACES tone mapping
    tone_mapped = apply_aces_tone_mapping(linear_srgb)

    # Step 3: Apply sRGB OETF (not simple gamma!)
    # This is the proper sRGB transfer function
    srgb = np.where(
        tone_mapped <= 0.0031308,
        tone_mapped * 12.92,
        1.055 * np.power(tone_mapped, 1.0/2.4) - 0.055
    )

    return np.clip(srgb, 0, 1)


def read_exr_openexr(filepath):
    """Read EXR using OpenEXR library"""
    exr_file = OpenEXR.InputFile(filepath)
    header = exr_file.header()

    # Get image dimensions
    dw = header['dataWindow']
    width = dw.max.x - dw.min.x + 1
    height = dw.max.y - dw.min.y + 1

    # Define channel types
    pt = Imath.PixelType(Imath.PixelType.FLOAT)

    # Read RGB channels (handle different channel names)
    channels = header['channels'].keys()

    # Try to find RGB channels
    if 'R' in channels and 'G' in channels and 'B' in channels:
        r_str = exr_file.channel('R', pt)
        g_str = exr_file.channel('G', pt)
        b_str = exr_file.channel('B', pt)
    elif 'r' in channels and 'g' in channels and 'b' in channels:
        r_str = exr_file.channel('r', pt)
        g_str = exr_file.channel('g', pt)
        b_str = exr_file.channel('b', pt)
    else:
        # Try to get any three channels
        chan_list = list(channels)
        if len(chan_list) >= 3:
            r_str = exr_file.channel(chan_list[0], pt)
            g_str = exr_file.channel(chan_list[1], pt)
            b_str = exr_file.channel(chan_list[2], pt)
        else:
            raise Exception(f"Not enough channels in EXR: {chan_list}")

    # Convert to numpy arrays
    r = np.frombuffer(r_str, dtype=np.float32).reshape((height, width))
    g = np.frombuffer(g_str, dtype=np.float32).reshape((height, width))
    b = np.frombuffer(b_str, dtype=np.float32).reshape((height, width))

    # Stack into RGB image
    rgb = np.stack([r, g, b], axis=-1)

    return rgb


def convert_exr_to_png(exr_path, png_path, color_mode='auto', slate_data=None):
    """Convert EXR to PNG with Redshift-accurate color management

    Args:
        exr_path: Path to input EXR file
        png_path: Path to output PNG file
        color_mode: Color conversion mode
                   'auto' - Detect best mode based on values
                   'aces' - Use ACES display transform (default Redshift)
                   'simple' - Simple gamma 2.2 (legacy)
                   'linear' - No tone mapping, just sRGB encoding
        slate_data: optional dict — when provided, a review-slate strip is
                    composited and sentinel:* metadata is stamped. None keeps
                    the output byte-identical to the legacy pipeline.
    """
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(png_path) or '.', exist_ok=True)

        # Try OpenEXR first if available
        if HAS_OPENEXR:
            try:
                print(f"Reading EXR with OpenEXR: {exr_path}")

                # Read the EXR file
                exr_file = OpenEXR.InputFile(exr_path)
                header = exr_file.header()

                # Check for color space metadata in header
                print(f"EXR Header channels: {list(header['channels'].keys())}")

                # Check for any color space attributes
                if 'chromaticities' in header:
                    print(f"Chromaticities found: {header['chromaticities']}")
                if 'whiteLuminance' in header:
                    print(f"White luminance: {header['whiteLuminance']}")

                # Read the image data
                linear_rgb = read_exr_openexr(exr_path)

                # Check value range to understand the data
                min_value = np.min(linear_rgb)
                max_value = np.max(linear_rgb)
                avg_value = np.mean(linear_rgb)
                print(f"EXR value range: min={min_value:.3f}, max={max_value:.3f}, avg={avg_value:.3f}")

                # Determine which color mode to use
                if color_mode == 'auto':
                    # Auto-detect based on value range
                    if max_value > 1.5:
                        actual_mode = 'aces'
                        print(f"Auto-detected HDR content (max={max_value:.2f}), using ACES mode")
                    else:
                        actual_mode = 'linear'
                        print(f"Auto-detected SDR content (max={max_value:.2f}), using linear mode")
                else:
                    actual_mode = color_mode
                    print(f"Using {actual_mode} color mode")

                # Apply the appropriate color transform
                if actual_mode == 'aces':
                    # Full ACES display transform (Redshift default)
                    print("Applying Redshift/ACES display transform...")
                    display_rgb = apply_redshift_display_transform(linear_rgb)

                elif actual_mode == 'simple':
                    # Legacy simple gamma 2.2
                    print("Applying simple gamma 2.2 correction...")
                    display_rgb = np.power(np.clip(linear_rgb, 0, 1), 1.0/2.2)

                elif actual_mode == 'linear':
                    # Just apply sRGB encoding, no tone mapping
                    print("Applying sRGB encoding (no tone mapping)...")
                    display_rgb = np.where(
                        linear_rgb <= 0.0031308,
                        linear_rgb * 12.92,
                        1.055 * np.power(np.clip(linear_rgb, 0, 1), 1.0/2.4) - 0.055
                    )
                    display_rgb = np.clip(display_rgb, 0, 1)

                else:
                    # Default to ACES
                    print(f"Unknown mode '{actual_mode}', defaulting to ACES")
                    display_rgb = apply_redshift_display_transform(linear_rgb)

                # Convert to 8-bit
                rgb_8bit = np.clip(display_rgb * 255, 0, 255).astype(np.uint8)

                # Save with PIL using maximum quality settings
                img = Image.fromarray(rgb_8bit)

                # Save with maximum PNG quality (no compression); optional slate
                _save_png(img, png_path, slate_data)

                print(f"SUCCESS: Converted with ACES display transform to {png_path}")
                return True

            except Exception as e:
                print(f"OpenEXR failed: {e}")
                print("Falling back to PIL...")

        # Fallback to PIL (basic conversion)
        print(f"Reading EXR with PIL: {exr_path}")
        img = Image.open(exr_path)

        print(f"PIL Image mode: {img.mode}, size: {img.size}")

        # Convert to RGB if needed
        if img.mode != 'RGB':
            print(f"Converting from {img.mode} to RGB")
            img = img.convert('RGB')

        # Get image as numpy array for processing
        img_array = np.array(img, dtype=np.float32) / 255.0

        # Check value range for PIL data
        min_val = np.min(img_array)
        max_val = np.max(img_array)
        print(f"PIL data range: min={min_val:.3f}, max={max_val:.3f}")

        # Apply appropriate transform for PIL fallback
        if color_mode == 'aces' or (color_mode == 'auto' and max_val > 0.9):
            print("Applying ACES display transform to PIL data...")
            display_rgb = apply_redshift_display_transform(img_array)
        elif color_mode == 'simple':
            print("Applying simple gamma 2.2 to PIL data...")
            display_rgb = np.power(np.clip(img_array, 0, 1), 1.0/2.2)
        else:
            print("Applying sRGB encoding to PIL data...")
            display_rgb = np.where(
                img_array <= 0.0031308,
                img_array * 12.92,
                1.055 * np.power(np.clip(img_array, 0, 1), 1.0/2.4) - 0.055
            )
            display_rgb = np.clip(display_rgb, 0, 1)

        # Convert back to 8-bit
        rgb_8bit = np.clip(display_rgb * 255, 0, 255).astype(np.uint8)
        img = Image.fromarray(rgb_8bit)

        # Save with maximum quality; optional slate
        _save_png(img, png_path, slate_data)

        print(f"SUCCESS: Converted with PIL (display transform applied) to {png_path}")
        return True

    except Exception as e:
        print(f"ERROR: Failed to convert: {e}")
        import traceback
        traceback.print_exc()
        return False


def parse_cli_args(argv):
    """Parse CLI args backward-compatibly.

    Positional: input.exr output.png [color_mode]. The optional ``--slate
    <path>`` flag may appear anywhere; without it, old 3-arg calls behave
    exactly as before (slate disabled).

    Returns (exr_path, png_path, color_mode, slate_path).
    """
    slate_path = None
    positionals = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--slate":
            i += 1
            if i < len(argv):
                slate_path = argv[i]
        else:
            positionals.append(token)
        i += 1

    exr_path = positionals[0] if len(positionals) > 0 else None
    png_path = positionals[1] if len(positionals) > 1 else None
    color_mode = positionals[2] if len(positionals) > 2 else 'auto'
    return exr_path, png_path, color_mode, slate_path


def main():
    """Main entry point for command line usage"""
    exr_path, png_path, color_mode, slate_path = parse_cli_args(sys.argv[1:])

    if not exr_path or not png_path:
        print("Usage: python exr_converter_external.py input.exr output.png [color_mode] [--slate slate.json]")
        print("Color modes: auto (default), aces, simple, linear")
        sys.exit(1)

    if not os.path.exists(exr_path):
        print(f"ERROR: Input file not found: {exr_path}")
        sys.exit(1)

    slate_data = load_slate_data(slate_path) if slate_path else None

    print(f"Converting with color mode: {color_mode}"
          + (" (+slate)" if slate_data else ""))
    success = convert_exr_to_png(exr_path, png_path, color_mode, slate_data=slate_data)

    # Return exit code (0 for success, 1 for failure)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()