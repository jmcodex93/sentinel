# -*- coding: utf-8 -*-
"""Snapshot EXR -> display PNG inside Cinema 4D (no external Python).

Measured on C4D 2026.304 (docs/research/2026-10-02-snapshot-in-c4d.md):
- ``BaseBitmap.InitWith`` loads RenderView EXR snapshots as 32-bit float RGB.
- ``doc.GetColorConverter().TransformColors(..., OCIO_RENDERING_TO_VIEW)`` gives
  the document's OCIO view transform (C4D ships Redshift's own config), equal to
  PyOpenColorIO within 1 level — ~1.35 s per 1080p image, row by row.
- GeClipMap draws the slate text (every call between BeginDraw/EndDraw), and
  all of it works off the main thread when the converter and the font
  description are captured on the main thread first.
- A font is found only by its PostScript name, and an unknown name silently
  returns another font, so the result is checked by name.
- ``GetPixelCnt`` returns a falsy value even when it succeeds: never test it.
The OCIO converter API exists from C4D 2025.2; older hosts use the external
converter (``snapshots._convert_exr_to_png``).
"""
import array
import os
import sys

import c4d
from c4d import bitmaps

from sentinel import rvpost
from sentinel import slate as slate_layout
from sentinel.common.helpers import safe_print

# Bundled Inter first (registered for this process only), then Arial, which
# ships with macOS and Windows; C4D's UI font is the last resort.
FONT_POSTSCRIPT_NAMES = ("Inter-Regular", "ArialMT")
BUNDLED_FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "fonts", "Inter-Regular.ttf")
_font_registration = None


def ocio_available():
    """True when this C4D has the document OCIO converter (2025.2+)."""
    return (hasattr(c4d.documents.BaseDocument, "GetColorConverter")
            and hasattr(c4d, "COLORSPACETRANSFORMATION_OCIO_RENDERING_TO_VIEW"))


def color_converter(doc):
    """The document's OCIO converter; capture it on the main thread."""
    return doc.GetColorConverter()


def _register_bundled_font(path=BUNDLED_FONT):
    """Make the bundled font usable by this process only (no system install)."""
    import ctypes
    if not os.path.isfile(path):
        return False
    if sys.platform == "darwin":
        import ctypes.util
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        ct = ctypes.CDLL(ctypes.util.find_library("CoreText"))
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
        cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                     ctypes.c_long, ctypes.c_bool]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                        ctypes.POINTER(ctypes.c_void_p)]
        string = cf.CFStringCreateWithCString(None, path.encode("utf-8"), 0x08000100)
        url = cf.CFURLCreateWithFileSystemPath(None, string, 0, False)
        try:
            # 1 = kCTFontManagerScopeProcess. False also when the font is already
            # registered or installed; the lookup below is what decides.
            return bool(ct.CTFontManagerRegisterFontsForURL(url, 1, ctypes.byref(ctypes.c_void_p())))
        finally:
            cf.CFRelease(url)
            cf.CFRelease(string)
    if sys.platform == "win32":
        FR_PRIVATE = 0x10
        return ctypes.windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0) > 0
    return False


def resolve_slate_font():
    """``(font description, name)`` for the slate; call on the main thread.

    ``name`` is the PostScript name that was found, or ``"system"`` when
    neither Inter nor Arial is available and C4D's UI font is used.
    """
    global _font_registration
    if _font_registration is None:
        try:
            _font_registration = _register_bundled_font()
        except Exception as exc:
            _font_registration = False
            safe_print("Slate font: could not register bundled Inter (%s)" % exc)
    clip = bitmaps.GeClipMap
    for name in FONT_POSTSCRIPT_NAMES:
        desc = clip.GetFontDescription(name, c4d.GE_FONT_NAME_POSTSCRIPT)
        if desc is not None and clip.GetFontName(desc, c4d.GE_FONT_NAME_POSTSCRIPT) == name:
            return c4d.BaseContainer(desc), name
    return c4d.BaseContainer(clip.GetDefaultFont(c4d.GE_FONT_DEFAULT_SYSTEM)), "system"


def _to_byte(value):
    return 0 if value <= 0.0 else 255 if value >= 1.0 else int(value * 255.0 + 0.5)


def convert_exr(path, converter, post=None):
    """Load an EXR and return a 24-bit BaseBitmap in the OCIO view space,
    with the RenderView post in ``post`` (an active ``rvpost`` plan) re-applied."""
    src = bitmaps.BaseBitmap()
    result, _ = src.InitWith(path)
    if result != c4d.IMAGERESULT_OK:
        raise RuntimeError("Could not read %s (result %s)" % (os.path.basename(path), result))
    width, height = src.GetSize()
    out = bitmaps.BaseBitmap()
    if out.Init(width, height, 24) != c4d.IMAGERESULT_OK:
        raise RuntimeError("Could not allocate a %dx%d image" % (width, height))
    transform = c4d.COLORSPACETRANSFORMATION_OCIO_RENDERING_TO_VIEW
    vector = c4d.Vector
    row = bytearray(width * 12)
    for y in range(height):
        src.GetPixelCnt(0, y, width, row, 12, c4d.COLORMODE_RGBf, c4d.PIXELCNT_0)
        floats = array.array("f")
        floats.frombytes(row)
        channels = iter(floats)
        colors = converter.TransformColors(
            [vector(r, g, b) for r, g, b in zip(channels, channels, channels)], transform)
        if post is not None:
            values = []
            extend = values.extend
            for color in colors:
                extend((color.x, color.y, color.z))
            line = rvpost.apply_row(values, post)
        else:
            line = bytearray(width * 3)
            i = 0
            for color in colors:
                line[i] = _to_byte(color.x)
                line[i + 1] = _to_byte(color.y)
                line[i + 2] = _to_byte(color.z)
                i += 3
        out.SetPixelCnt(0, y, width, line, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
    return out


def _draw_strip(width, strip_h, fields, font, style):
    """The slate strip as its own 24-bit bitmap (opaque background)."""
    size = slate_layout.font_size(strip_h)
    clip = bitmaps.GeClipMap()
    if not clip.Init(width, strip_h, 24):
        raise RuntimeError("Could not allocate the slate strip")
    clip.BeginDraw()
    try:
        clip.SetColor(*slate_layout.SLATE_STRIP_BG, 255)
        clip.FillRect(0, 0, width - 1, strip_h - 1)
        desc = c4d.BaseContainer(font)
        bitmaps.GeClipMap.SetFontSize(desc, c4d.GE_FONT_SIZE_INTERNAL, size)
        clip.SetFont(desc, size)
        for x, y, text, rgb in slate_layout.slate_ops(width, strip_h, clip.TextHeight(),
                                                       fields, clip.TextWidth, style):
            clip.SetColor(*rgb, 255)
            clip.TextAt(x, y, text)
    finally:
        clip.EndDraw()
    return clip.GetBitmap().GetClone()  # the clip map owns its bitmap


def compose_slate(image, fields, font, style=None):
    """Return a new bitmap with the slate: a strip below the image (default,
    the image pixels untouched) or a bar drawn over its bottom edge
    (``position: overlay``, same dimensions)."""
    style = style or slate_layout.DEFAULT_STYLE
    width, height = image.GetSize()
    strip_h = min(slate_layout.strip_height(height, style.get("size", 1.0)), height)
    strip = _draw_strip(width, strip_h, fields, font, style)
    overlay = style.get("position") == "overlay"
    out = bitmaps.BaseBitmap()
    if out.Init(width, height + (0 if overlay else strip_h), 24) != c4d.IMAGERESULT_OK:
        raise RuntimeError("Could not allocate the slated image")
    line = bytearray(width * 3)
    for y in range(height):
        image.GetPixelCnt(0, y, width, line, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
        out.SetPixelCnt(0, y, width, line, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
    strip_line = bytearray(width * 3)
    top = height - strip_h if overlay else height
    for y in range(strip_h):
        strip.GetPixelCnt(0, y, width, strip_line, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
        if overlay:
            image.GetPixelCnt(0, top + y, width, line, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
            row = slate_layout.overlay_row(line, strip_line)
        else:
            row = strip_line
        out.SetPixelCnt(0, top + y, width, row, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
    return out


def slate_fields(attrs, slate, size):
    """The slate's fields for this snapshot: what Sentinel collected on the
    main thread, overridden by what RenderView recorded in the EXR header
    ``attrs`` (frame, capture date/time, OCIO view), plus the resolution."""
    from sentinel.snapshots import snapshot_capture_fields
    fields = dict(slate or {})
    fields.update(snapshot_capture_fields(attrs))
    fields["resolution"] = "%dx%d" % size
    return fields


def convert_snapshot(exr_path, png_path, converter, slate=None, font=None, style=None):
    """EXR -> PNG at ``png_path`` (overwritten), with the slate when given.

    Re-applies the RenderView post the EXR header records and this module can
    reproduce (LUT, RGB curve — see ``rvpost``). Returns ``(ok, message)``: on
    failure the error; on success what was re-applied and what was not, or
    None. Safe in a worker thread when ``converter`` and ``font`` were
    captured on the main thread.
    """
    from sentinel.snapshots import read_exr_attributes
    try:
        attrs = read_exr_attributes(exr_path)
        plan = rvpost.post_plan(attrs)
        image = convert_exr(exr_path, converter, plan if rvpost.plan_is_active(plan) else None)
        fields = None
        post = rvpost.applied_label(plan)
        if slate:
            fields = slate_fields(attrs, slate, image.GetSize())
            fields["post"] = post
            image = compose_slate(image, fields, font if font is not None else
                                  bitmaps.GeClipMap.GetDefaultFont(c4d.GE_FONT_DEFAULT_SYSTEM),
                                  style)
        if image.Save(png_path, c4d.FILTER_PNG) != c4d.IMAGERESULT_OK:
            return False, "Could not write %s" % png_path
        # The post re-applied travels as metadata even without a slate.
        metadata = slate_layout.slate_metadata(fields) if fields else \
            ([("sentinel:post", post)] if post else [])
        if metadata:
            with open(png_path, "rb") as handle:
                data = handle.read()
            with open(png_path, "wb") as handle:
                handle.write(slate_layout.insert_png_text(data, metadata))
        notice = rvpost.describe(plan)
        if notice:
            safe_print("Snapshot %s: %s" % (os.path.basename(exr_path), notice))
        return True, notice or None
    except Exception as exc:
        return False, "Conversion failed: %s" % exc


def preview_slate(png_path, slate, font, style, exr_path=None, converter=None):
    """Write a slate preview to ``png_path``: the given snapshot converted for
    real, or a neutral grey 1920×1080 frame when there is none.
    Returns ``(ok, error, source)`` with source ``"snapshot"``/``"placeholder"``."""
    if exr_path and converter is not None:
        ok, error = convert_snapshot(exr_path, png_path, converter, slate=slate,
                                     font=font, style=style)
        return ok, error, "snapshot"
    try:
        width, height = 1920, 1080
        image = bitmaps.BaseBitmap()
        if image.Init(width, height, 24) != c4d.IMAGERESULT_OK:
            return False, "Could not allocate the preview", "placeholder"
        grey = bytearray([92, 92, 92] * width)
        for y in range(height):
            image.SetPixelCnt(0, y, width, grey, 3, c4d.COLORMODE_RGB, c4d.PIXELCNT_0)
        fields = dict(slate or {}, resolution="%dx%d" % (width, height))
        out = compose_slate(image, fields, font, style)
        if out.Save(png_path, c4d.FILTER_PNG) != c4d.IMAGERESULT_OK:
            return False, "Could not write %s" % png_path, "placeholder"
        return True, None, "placeholder"
    except Exception as exc:
        return False, "Preview failed: %s" % exc, "placeholder"
