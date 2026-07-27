# -*- coding: utf-8 -*-
"""Custom Sentinel user areas and row-format helpers."""

import os

import c4d
from c4d import gui

from sentinel.assets import fit_column_widths, format_size
from sentinel.common.helpers import safe_print
from sentinel.common.settings import ASSET_HUB_COL_WIDTH_MIN, GlobalSettings

def _violation_label(violation):
    if not isinstance(violation, dict):
        return str(violation)
    message = violation.get("message")
    if message:
        return str(message)
    identity = violation.get("identity") or {}
    if isinstance(identity, dict):
        for key in ("path", "name", "param", "preset", "take", "field"):
            if identity.get(key) is not None:
                return str(identity.get(key))
    return str(violation)


def _entry_label(entry):
    if not isinstance(entry, dict):
        return str(entry)
    identity = entry.get("identity") or {}
    if isinstance(identity, dict):
        parts = []
        for key in ("path", "name", "param", "preset", "take", "field"):
            if identity.get(key) is not None:
                parts.append(str(identity.get(key)))
        if parts:
            return " / ".join(parts)
    return str(entry.get("check_id", "acceptance"))


def _accepted_entry_payload(entry, violation=None):
    return {
        "item": _violation_label(violation) if violation is not None else _entry_label(entry),
        "author": entry.get("author", "") if isinstance(entry, dict) else "",
        "reason": entry.get("reason", "") if isinstance(entry, dict) else "",
        "date": entry.get("date", "") if isinstance(entry, dict) else "",
    }


def _stale_suffix(stale_count):
    """Single source for the ' · N stale' fragment (empty when count is 0)."""
    n = int(stale_count or 0)
    return f" · {n} stale" if n else ""


def format_baseline_row_message(new_count, accepted_count, stale_count=0):
    message = f"{int(new_count or 0)} new ({int(accepted_count or 0)} accepted)"
    message += _stale_suffix(stale_count)
    return message

# ---------------- TodoArea (GeUserArea for the TODO list) ----------------
# Renders TODOs with checkbox + text + delete affordance. Two click zones per
# row: left (CHECKBOX_W px) toggles done; right (DELETE_W px) deletes.

_COL_TODO_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_TODO_ROW = c4d.Vector(0.14, 0.14, 0.14)
_COL_TODO_ROW_ALT = c4d.Vector(0.16, 0.16, 0.16)
_COL_TODO_TEXT = c4d.Vector(0.85, 0.85, 0.85)
_COL_TODO_TEXT_DONE = c4d.Vector(0.40, 0.40, 0.40)
_COL_TODO_CHECK = c4d.Vector(0.60, 0.60, 0.60)
_COL_TODO_CHECK_ON = c4d.Vector(0.30, 0.75, 0.35)
_COL_TODO_DELETE = c4d.Vector(0.55, 0.30, 0.30)


class TodoArea(gui.GeUserArea):
    """Custom-drawn TODO list with click zones for toggle and delete."""

    ROW_HEIGHT = 22
    ROW_PAD = 2
    CHECKBOX_W = 26          # left click zone width
    DELETE_W = 26            # right click zone width
    EMPTY_HEIGHT = 30

    def __init__(self):
        super().__init__()
        self.todos = []
        self.toggle_callback = None  # callable(todo_id)
        self.delete_callback = None  # callable(todo_id)
        self.font = c4d.FONT_DEFAULT

    def GetMinSize(self):
        n = len(self.todos)
        if n == 0:
            return 400, self.EMPTY_HEIGHT
        h = n * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 2
        return 400, h

    def set_todos(self, todos):
        self.todos = list(todos) if todos else []
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    def _y_to_index(self, y):
        try:
            y = int(y) - self.ROW_PAD
            if y < 0:
                return -1
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            idx = y // row_pixel
            if 0 <= idx < len(self.todos):
                return idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            idx = self._y_to_index(int(local_y))
            if idx < 0:
                return False
            todo = self.todos[idx]
            todo_id = todo.get("id")
            w = self.GetWidth()
            # Left zone → toggle
            if int(local_x) <= self.CHECKBOX_W and self.toggle_callback is not None:
                self.toggle_callback(todo_id)
                return True
            # Right zone → delete
            if int(local_x) >= w - self.DELETE_W and self.delete_callback is not None:
                self.delete_callback(todo_id)
                return True
            # Middle: also toggle (forgiving UX)
            if self.toggle_callback is not None:
                self.toggle_callback(todo_id)
                return True
        except Exception as e:
            safe_print(f"TodoArea.InputEvent error: {e}")
        return False

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_TODO_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self.todos:
                self.DrawSetTextCol(_COL_TODO_TEXT_DONE, _COL_TODO_BG)
                self.DrawText("No TODOs yet — add one below", 8, (h - 12) // 2)
                return

            x = self.ROW_PAD
            y = self.ROW_PAD
            for i, todo in enumerate(self.todos):
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                bg = _COL_TODO_ROW_ALT if (i % 2) else _COL_TODO_ROW
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top), int(w - self.ROW_PAD), int(row_bot))

                done = bool(todo.get("done"))
                text = todo.get("text", "") or ""
                text_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)

                # Checkbox
                cb_x = int(x + 6)
                cb_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)
                cb_size = 12
                # Outer box (frame)
                self.DrawSetPen(_COL_TODO_CHECK)
                self.DrawRectangle(cb_x, cb_y, cb_x + cb_size, cb_y + cb_size)
                # Inner fill (bg or checked)
                if done:
                    self.DrawSetPen(_COL_TODO_CHECK_ON)
                else:
                    self.DrawSetPen(bg)
                self.DrawRectangle(cb_x + 1, cb_y + 1, cb_x + cb_size - 1, cb_y + cb_size - 1)

                # Text
                text_x = int(x + self.CHECKBOX_W + 4)
                avail_w = w - self.CHECKBOX_W - self.DELETE_W - 12
                truncated = text
                try:
                    if int(self.DrawGetTextWidth(truncated)) > avail_w:
                        while truncated and int(self.DrawGetTextWidth(truncated + "...")) > avail_w:
                            truncated = truncated[:-1]
                        truncated = truncated + "..." if truncated != text else truncated
                except Exception:
                    if len(truncated) > 50:
                        truncated = truncated[:47] + "..."
                text_color = _COL_TODO_TEXT_DONE if done else _COL_TODO_TEXT
                self.DrawSetTextCol(text_color, bg)
                self.DrawText(truncated, text_x, text_y)

                # Delete affordance: × on the right
                del_x = int(w - self.DELETE_W + 8)
                self.DrawSetTextCol(_COL_TODO_DELETE, bg)
                self.DrawText("×", del_x, text_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"TodoArea.DrawMsg error: {e}")


# Helper: convert msg[BFM_INPUT_X/Y] (window-global in C4D 2026 Python) to
# user-area-local coordinates. GeUserArea.Local2Global() with NO args returns
# the user area's window origin as {'x': ..., 'y': ...}. Subtracting that from
# the raw msg coords gives correct local coords. Verified empirically — the
# documented Global2Local(x, y) does NOT return area-local in C4D 2026.
def _ua_local_coords(user_area, mx, my):
    """Return (local_x, local_y) for a window-global click on the given GeUserArea."""
    try:
        origin = user_area.Local2Global()
    except Exception:
        return mx, my
    try:
        if isinstance(origin, dict):
            ox = origin.get("x", 0)
            oy = origin.get("y", 0)
        else:
            ox, oy = origin[0], origin[1]
        return int(mx) - int(ox), int(my) - int(oy)
    except Exception:
        return mx, my

# ============================================================
# Texture Repathing — TextureListArea (v1.5.7)
# ============================================================
# Custom-drawn list of texture records produced by
# `scan_all_texture_paths(doc)`. One row per record:
#
#   [status] host_name (channel)  current_path...  [...]
#   → new_path (only if pending change)
#
# Status glyphs (BMP-compatible):
#   ✗  missing  — red
#   ⚠  absolute — amber
#   ≈  asset_uri — light blue (READ-ONLY, no `[...]` button)
#   ✓  ok        — green
#
# Asset URIs are dimmed and not interactive — they're managed by the
# renderer's internal asset manager (RS Asset Manager, Octane Asset DB,
# Arnold Asset DB) and shouldn't be edited from Sentinel.

_COL_TEXLIST_BG       = c4d.Vector(0.10, 0.10, 0.10)
_COL_TEXLIST_ROW      = c4d.Vector(0.14, 0.14, 0.14)
_COL_TEXLIST_ROW_ALT  = c4d.Vector(0.16, 0.16, 0.16)
_COL_TEXLIST_TEXT     = c4d.Vector(0.85, 0.85, 0.85)
_COL_TEXLIST_DIM      = c4d.Vector(0.55, 0.55, 0.55)
_COL_TEXLIST_GREEN    = c4d.Vector(0.30, 0.80, 0.40)
_COL_TEXLIST_RED      = c4d.Vector(0.95, 0.40, 0.40)
_COL_TEXLIST_AMBER    = c4d.Vector(0.95, 0.75, 0.30)
_COL_TEXLIST_BLUE     = c4d.Vector(0.45, 0.75, 0.95)
_COL_TEXLIST_PENDING  = c4d.Vector(0.40, 0.85, 0.45)
_COL_TEXLIST_BTN_BG   = c4d.Vector(0.22, 0.22, 0.22)


def _format_path_compact(path, max_chars=60):
    """Smart middle-truncate of a path string for display.

    Keeps the start (so the artist sees the prefix that's usually the
    interesting part — `relative://`, `/Users/foo/`, etc.) AND the
    filename at the end. Drops the middle when too long.
    """
    if not path:
        return ""
    s = str(path)
    if len(s) <= max_chars:
        return s
    keep_end = max(20, max_chars // 2)
    keep_start = max(10, max_chars - keep_end - 3)
    return s[:keep_start] + "..." + s[-keep_end:]
