# -*- coding: utf-8 -*-
"""Safe-area viewport overlay ObjectData and shared draw state."""

import os

import c4d
from c4d import plugins

from sentinel.common.constants import SAFE_AREA_OVERLAY_PLUGIN_ID
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.rules import get_active_rules
from sentinel.safe_areas import (
    find_active_multiformat_takes,
    format_safe_area_in_master_ndc,
    resolve_take_projection_params,
)


def _doc_path_for_rules(doc):
    if doc is None:
        return ""
    try:
        return doc.GetDocumentPath() or ""
    except Exception:
        return ""


def _machine_rule_settings():
    try:
        return {"standard_fps": GlobalSettings.get_standard_fps()}
    except Exception:
        return {}


def _active_rules_for_doc(doc):
    return get_active_rules(_doc_path_for_rules(doc), _machine_rule_settings())

# Implementation: one ObjectData marker object per document, auto-
# created at scene root when the panel toggle is enabled. The marker
# draws each active multi-format Take's safe-area rectangle in the
# active camera viewport using screen-space lines positioned via
# `bd.GetSafeFrame()`.
#
# Two-piece architecture:
#   - `_SafeAreaOverlayState` singleton — module-level state shared
#     between the Sentinel panel (CommandData) and the marker object's
#     Draw method. The panel mutates it, the marker reads it.
#   - `SafeAreaOverlayObject(plugins.ObjectData)` — registered with a
#     unique plugin ID. Auto-created in the scene by Sentinel when the
#     overlay toggle is enabled.
#
# Why not TagData on the active camera (originally proposed):
#   TagData.Draw is NOT routed by C4D 2026's Python viewport pipeline —
#   Init and Execute fire as expected, but Draw is never invoked.
#   Verified empirically with the v1.5.6 probe round. ObjectData.Draw
#   on the other hand fires reliably in DRAWPASS_OBJECT regardless of
#   selection, which matches our use case (always-on overlay).
#
# Why a marker object and not a scene-level draw hook:
#   `SceneHookData` was removed in C4D 2026 (the original v1.5.5
#   intent). The ObjectData marker is the closest "always-on" Draw
#   API available in 2026 Python.


# Per-format outline colors. Matched to the cross-platform delivery
# convention (warm/orange for vertical social, cool for square/feed,
# white for the broadcast master, yellow for cinema).
_SAFE_AREA_COLORS = {
    "16x9": c4d.Vector(0.95, 0.95, 0.95),  # white — master/broadcast
    "9x16": c4d.Vector(0.95, 0.55, 0.15),  # orange — IG Reels / TikTok
    "1x1":  c4d.Vector(0.50, 0.85, 0.95),  # cyan — IG Square
    "4x5":  c4d.Vector(0.85, 0.35, 0.85),  # magenta — IG Feed portrait
    "21x9": c4d.Vector(0.95, 0.85, 0.20),  # yellow — cinema
}


class _SafeAreaOverlayState:
    """Module-level singleton for sharing viewport-overlay state between
    the Sentinel panel and the `SafeAreaOverlayObject` marker.

    The panel calls `update_from_doc(doc)` whenever scene topology
    likely changed (overlay toggle, Multi-Format regeneration). The
    marker's Draw reads `enabled` + `format_rects` on every redraw.

    Threading note: C4D runs Draw on the viewport thread. Plain bool
    + list-of-tuples reads are safe; we never mutate from the draw
    side, only read.
    """

    def __init__(self):
        self.enabled = False
        self.master_aspect = 16.0 / 9.0
        # list of (fmt_id, c4d.Vector color, dict safe_box_in_master_ndc)
        self.format_rects = []

    def update_from_doc(self, doc):
        """Recompute cached per-format master-NDC rectangles from the
        current document state."""
        self.format_rects = []
        if doc is None:
            return
        try:
            td = doc.GetTakeData()
            if td is None:
                return
            main_take = td.GetMainTake()
            if main_take is None:
                return
            params = resolve_take_projection_params(main_take, td, doc)
            aspect = params.get("aspect") if params else None
            if aspect is None or aspect <= 0:
                # Fallback: doc's active render data
                rd = doc.GetActiveRenderData()
                if rd:
                    try:
                        w = int(rd[c4d.RDATA_XRES])
                        h = int(rd[c4d.RDATA_YRES])
                        aspect = float(w) / float(h) if h > 0 else (16.0 / 9.0)
                    except Exception:
                        aspect = 16.0 / 9.0
                else:
                    aspect = 16.0 / 9.0
            self.master_aspect = float(aspect)
            rules_context = _active_rules_for_doc(doc)

            mf_takes = find_active_multiformat_takes(doc)
            rects = []
            for fmt_id, _take in mf_takes:
                safe_box = format_safe_area_in_master_ndc(fmt_id,
                                                          self.master_aspect,
                                                          rules_context)
                color = _SAFE_AREA_COLORS.get(fmt_id,
                                              c4d.Vector(0.6, 0.6, 0.6))
                rects.append((fmt_id, color, safe_box))
            self.format_rects = rects
        except Exception as e:
            safe_print(f"SafeAreaOverlay state update error: {e}")


# Module-level singleton instance. Both the panel and the ObjectData
# marker reference it through this name.
_overlay_state = _SafeAreaOverlayState()


# Defensive check: confirm ObjectData + the draw constants we rely on
# exist before defining the class. Falls back to `object` so the
# module still parses if any of these is missing (panel still works,
# just no overlay).
try:
    _ObjectDataBase = plugins.ObjectData
    _ = c4d.DRAWPASS_OBJECT
    _ = c4d.DRAWRESULT_OK
    _ = c4d.DRAWRESULT_SKIP
    _ = c4d.OBJECT_GENERATOR
    _SAFE_AREA_OBJECT_AVAILABLE = True
except Exception as _exc:
    _ObjectDataBase = object
    _SAFE_AREA_OBJECT_AVAILABLE = False
    safe_print(f"ObjectData API not available ({_exc}) — safe-area "
               "viewport overlay disabled. Panel still works.")


class SafeAreaOverlayObject(_ObjectDataBase):
    """ObjectData plugin: a marker null whose Draw renders the cross-
    aspect safe-area rectangles into the active camera viewport.

    Auto-created by the Sentinel panel when the "Show Safe-Area
    Overlay" toggle is enabled. Reads from `_overlay_state` — when
    `enabled` is False or no formats are active, the Draw body skips
    immediately (sub-millisecond overhead).
    """

    def Init(self, node, isCloneInit=False):
        return True

    def Draw(self, op, drawpass, bd, bh):
        # Only do work on DRAWPASS_OBJECT — confirmed via probe that
        # this pass fires regardless of selection. DRAWPASS_HANDLES
        # only fires when the object is selected, which isn't what we
        # want for an always-on overlay.
        if drawpass != c4d.DRAWPASS_OBJECT:
            return c4d.DRAWRESULT_OK

        try:
            if not _overlay_state.enabled:
                return c4d.DRAWRESULT_SKIP
            rects = _overlay_state.format_rects
            if not rects:
                return c4d.DRAWRESULT_SKIP

            # `bd.GetSafeFrame()` returns the safe-frame rectangle in
            # viewport pixel coordinates — i.e. where the camera's
            # actual rendered frame lands (handles letterbox/pillarbox
            # automatically). We position the format rectangles inside
            # this area.
            safe = bd.GetSafeFrame()
            if not safe:
                return c4d.DRAWRESULT_SKIP
            cl = int(safe.get("cl", 0))
            ct = int(safe.get("ct", 0))
            cr = int(safe.get("cr", 0))
            cb = int(safe.get("cb", 0))
            master_w = cr - cl
            master_h = cb - ct
            if master_w < 4 or master_h < 4:
                return c4d.DRAWRESULT_SKIP

            # Switch to 2D screen-space drawing. After this, DrawLine
            # treats Vector(x, y, 0) as pixel coordinates.
            bd.SetMatrix_Screen()

            for fmt_id, color, safe_box in rects:
                # Map master NDC ([-1, +1]) → pixel coords inside the
                # safe-frame rectangle. NDC y=+1 is top, -1 is bottom;
                # screen y increases downward → flip.
                px_left = cl + (safe_box["left"] + 1.0) * 0.5 * master_w
                px_right = cl + (safe_box["right"] + 1.0) * 0.5 * master_w
                px_top = ct + (1.0 - safe_box["top"]) * 0.5 * master_h
                px_bot = ct + (1.0 - safe_box["bottom"]) * 0.5 * master_h

                # Skip degenerate
                if px_right - px_left < 1.0 or px_bot - px_top < 1.0:
                    continue

                bd.SetPen(color)
                p_tl = c4d.Vector(px_left, px_top, 0)
                p_tr = c4d.Vector(px_right, px_top, 0)
                p_br = c4d.Vector(px_right, px_bot, 0)
                p_bl = c4d.Vector(px_left, px_bot, 0)
                bd.DrawLine(p_tl, p_tr, 0)
                bd.DrawLine(p_tr, p_br, 0)
                bd.DrawLine(p_br, p_bl, 0)
                bd.DrawLine(p_bl, p_tl, 0)

                # Format label in the top-left corner of each rect.
                try:
                    bd.DrawHUDText(int(px_left + 4),
                                   int(px_top + 4),
                                   fmt_id)
                except Exception:
                    pass

            return c4d.DRAWRESULT_OK
        except Exception as e:
            safe_print(f"SafeAreaOverlayObject.Draw error: {e}")
            return c4d.DRAWRESULT_SKIP


def find_or_create_safe_area_overlay_object(doc):
    """Locate the existing overlay marker in `doc`, or create one at
    scene root if none exists. Identified by plugin TYPE
    (`SAFE_AREA_OVERLAY_PLUGIN_ID`), so renames don't break detection.

    Returns the BaseObject, or None on failure / when the plugin isn't
    registered (e.g. ObjectData API missing in this C4D build).
    """
    if doc is None or not _SAFE_AREA_OBJECT_AVAILABLE:
        return None

    # Search existing
    def _find(start):
        op = start
        while op is not None:
            if op.GetType() == SAFE_AREA_OVERLAY_PLUGIN_ID:
                return op
            child = op.GetDown()
            if child is not None:
                found = _find(child)
                if found is not None:
                    return found
            op = op.GetNext()
        return None

    existing = _find(doc.GetFirstObject())
    if existing is not None:
        return existing

    # Create new at scene root
    try:
        obj = c4d.BaseObject(SAFE_AREA_OVERLAY_PLUGIN_ID)
        if obj is None:
            return None
        obj.SetName("Sentinel Safe-Area Overlay")
        doc.StartUndo()
        doc.InsertObject(obj)
        doc.AddUndo(c4d.UNDOTYPE_NEW, obj)
        doc.EndUndo()
        c4d.EventAdd()
        return obj
    except Exception as e:
        safe_print(f"Could not create safe-area overlay object: {e}")
        return None
