# -*- coding: utf-8 -*-
import os
import sys

import c4d
from c4d import plugins

_ROOT = os.path.dirname(__file__)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import sentinel
from sentinel import PLUGIN_NAME
from sentinel.common.constants import PLUGIN_ID
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.ui import panel as _panel
from sentinel.ui import dialogs as _dialogs
from sentinel.ui import ids as _ids
from sentinel.ui import user_areas as _user_areas
from sentinel.ui.panel import YSPanelCmd

try:
    from sentinel.ui.frame_tag import (
        SENTINEL_FRAME_TAG_PLUGIN_ID,
        SentinelFrameTag,
        _SENTINEL_FRAME_TAG_AVAILABLE,
    )
    _FRAME_TAG_IMPORT_ERROR = None
except Exception as _exc:
    SENTINEL_FRAME_TAG_PLUGIN_ID = 2099073
    SentinelFrameTag = None
    _SENTINEL_FRAME_TAG_AVAILABLE = False
    _FRAME_TAG_IMPORT_ERROR = _exc

# Compatibility surface for tests, fixture runner, and C4D scripts that import
# sentinel_panel.pyp directly. Keep private helpers too.
for _module in (_panel, _dialogs, _ids, _user_areas):
    globals().update({
        _name: _value
        for _name, _value in vars(_module).items()
        if not _name.startswith("__")
    })


def Register():
    # Load plugin icon (PNG format for best Cinema 4D compatibility).
    # Tries the new Sentinel icon first; falls back to legacy YS Guardian icon
    # if the new file is missing (defensive — should never happen in practice).
    icon = c4d.bitmaps.BaseBitmap()
    icons_dir = os.path.join(_ROOT, "icons")
    candidates = [
        os.path.join(icons_dir, "Sentinel_IC_v02.png"),
        os.path.join(icons_dir, "Sentinel_IC_v01.png"),  # previous Sentinel icon
        os.path.join(icons_dir, "ys-logo-alpha-32.png"),  # legacy YS Guardian fallback
    ]

    icon_path = None
    for candidate in candidates:
        if os.path.exists(candidate):
            icon_path = candidate
            break

    if icon_path:
        result = icon.InitWith(icon_path)
        if result[0] == c4d.IMAGERESULT_OK:
            width = icon.GetBw()
            height = icon.GetBh()
            depth = icon.GetBt()
            safe_print(f"Plugin icon loaded: {os.path.basename(icon_path)} ({width}x{height}, {depth}-bit)")
        else:
            safe_print(f"Warning: Failed to load icon from {icon_path}")
            icon = None
    else:
        safe_print(f"Warning: No icon found in {icons_dir}")
        icon = None

    ok = plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        icon=icon,
        help="Open Sentinel Panel",
        dat=YSPanelCmd()
    )
    if ok:
        safe_print(f"{PLUGIN_NAME} registered successfully")
    else:
        safe_print("Failed to register Guardian panel")

    # (The v1.5.6 Safe-Area Overlay ObjectData was retired in v1.8.0 — the
    # Sentinel Frame per-camera tag draws the viewport guides directly.)

    # Sentinel Frame camera tag (TagData) for the per-camera multi-format
    # workflow. Failure is non-fatal — the core panel and legacy flows still
    # work without the tag.
    if _SENTINEL_FRAME_TAG_AVAILABLE and SentinelFrameTag is not None:
        try:
            tag_info = (
                c4d.TAG_VISIBLE
                | c4d.TAG_EXPRESSION
                | c4d.TAG_IMPLEMENTS_DRAW_FUNCTION
            )
            frame_icon = c4d.bitmaps.BaseBitmap()
            frame_icon_path = os.path.join(_ROOT, "icons", "SentinelFrame_IC.png")
            if not (os.path.exists(frame_icon_path)
                    and frame_icon.InitWith(frame_icon_path)[0] == c4d.IMAGERESULT_OK):
                frame_icon = None
            frame_tag_ok = plugins.RegisterTagPlugin(
                id=SENTINEL_FRAME_TAG_PLUGIN_ID,
                str="Sentinel Frame",
                info=tag_info,
                g=SentinelFrameTag,
                description="Tsentinelframe",
                icon=frame_icon,
            )
            if frame_tag_ok:
                safe_print("Sentinel Frame (TagData) registered")
            else:
                safe_print("Failed to register Sentinel Frame TagData — "
                           "tag workflow disabled, panel still works")
        except Exception as e:
            safe_print(f"Sentinel Frame registration crashed: {e} — "
                       "tag workflow disabled, panel still works")
    else:
        reason = f" ({_FRAME_TAG_IMPORT_ERROR})" if _FRAME_TAG_IMPORT_ERROR else ""
        safe_print(f"TagData API unavailable{reason} — Sentinel Frame tag disabled")

    return ok


if __name__ == "__main__":
    # Print setup info using safe_print to avoid None returns in console
    safe_print("\n" + "="*50)
    safe_print(f"{PLUGIN_NAME}")
    safe_print(f"  Snapshot dir: {GlobalSettings.get_snapshot_dir()}")
    safe_print("  9 Quality Checks | ACES tone mapping")
    safe_print("="*50 + "\n")

    Register()
