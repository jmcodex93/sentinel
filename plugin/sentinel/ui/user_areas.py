# -*- coding: utf-8 -*-
"""Custom Sentinel user areas and row-format helpers."""

import os
import time

import c4d
from c4d import gui

from sentinel.assets import fit_column_widths, format_size
from sentinel.common.helpers import safe_print
from sentinel.common.settings import ASSET_HUB_COL_WIDTH_MIN, GlobalSettings
from sentinel.qc.registry import CHECK_REGISTRY, CheckDisplayView, RowKeysView

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

_COL_GREEN = c4d.Vector(0.3, 1, 0.3)
_COL_RED = c4d.Vector(1, 0.3, 0.3)
_COL_YELLOW = c4d.Vector(1, 1, 0.3)
_COL_GRAY = c4d.Vector(0.5, 0.5, 0.5)
_COL_BG = c4d.Vector(0.08, 0.08, 0.08)
_COL_BLACK = c4d.Vector(0, 0, 0)
_COL_BG_OK = c4d.Vector(0.15, 0.15, 0.15)
_COL_BG_WARN = c4d.Vector(0.25, 0.20, 0.10)
_COL_BG_FAIL = c4d.Vector(0.25, 0.10, 0.10)


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

# Score header colors (lighter palette for the badge area)
_COL_SCORE_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_SCORE_GREEN = c4d.Vector(0.30, 0.80, 0.40)
_COL_SCORE_YELLOW = c4d.Vector(0.95, 0.75, 0.25)
_COL_SCORE_RED = c4d.Vector(0.90, 0.35, 0.35)
_COL_SCORE_TRACK = c4d.Vector(0.20, 0.20, 0.20)
_COL_SCORE_TEXT = c4d.Vector(0.95, 0.95, 0.95)
_COL_SCORE_TEXT_DIM = c4d.Vector(0.60, 0.60, 0.60)


class ScoreHeader(gui.GeUserArea):
    """Visual summary header: progress bar + pass count + scene stats — single line."""

    HEIGHT = 26

    def __init__(self):
        super().__init__()
        self.passed = 0
        self.total = 0
        self.stats_text = ""

    def GetMinSize(self):
        return 400, self.HEIGHT

    def set_state(self, passed, total, stats_text):
        self.passed = max(0, int(passed))
        self.total = max(1, int(total))
        self.stats_text = stats_text or ""
        self.Redraw()

    def _measure(self, text):
        try:
            return int(self.DrawGetTextWidth(text))
        except Exception:
            return len(text) * 6

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            # Background
            self.DrawSetPen(_COL_SCORE_BG)
            self.DrawRectangle(0, 0, w, h)

            # Status color/label
            ratio = self.passed / self.total if self.total > 0 else 0.0
            if ratio >= 0.999:
                bar_color = _COL_SCORE_GREEN
                status_label = "PASS"
            elif ratio >= 0.7:
                bar_color = _COL_SCORE_YELLOW
                status_label = "WARN"
            else:
                bar_color = _COL_SCORE_RED
                status_label = "FAIL"

            # Single-line vertical centering
            text_h = 12
            text_y = (h - text_h) // 2
            bar_h = 6
            bar_y = (h - bar_h) // 2

            margin = 8
            try:
                self.DrawSetFont(c4d.FONT_BOLD)
            except Exception:
                pass

            # 1. "QC X/Y" label (left)
            qc_label = f"QC {self.passed}/{self.total}"
            self.DrawSetTextCol(_COL_SCORE_TEXT, _COL_SCORE_BG)
            self.DrawText(qc_label, margin, text_y)
            qc_w = self._measure(qc_label)

            # 2. Status word right after
            status_x = margin + qc_w + 10
            self.DrawSetTextCol(bar_color, _COL_SCORE_BG)
            self.DrawText(status_label, status_x, text_y)
            status_w = self._measure(status_label)

            try:
                self.DrawSetFont(c4d.FONT_DEFAULT)
            except Exception:
                pass

            # 3. Stats text (right-aligned, dim grey) — measure FIRST to reserve space
            stats_x_start = w - margin
            if self.stats_text:
                tx_w = self._measure(self.stats_text)
                stats_x_start = w - margin - tx_w
                self.DrawSetTextCol(_COL_SCORE_TEXT_DIM, _COL_SCORE_BG)
                self.DrawText(self.stats_text, stats_x_start, text_y)

            # 4. Progress bar fills the middle space between status and stats
            bar_x_start = status_x + status_w + 12
            bar_x_end = stats_x_start - 12

            if bar_x_end > bar_x_start + 20:
                self.DrawSetPen(_COL_SCORE_TRACK)
                self.DrawRectangle(bar_x_start, bar_y, bar_x_end, bar_y + bar_h)
                if ratio > 0:
                    fill_w = max(2, int((bar_x_end - bar_x_start) * ratio))
                    self.DrawSetPen(bar_color)
                    self.DrawRectangle(bar_x_start, bar_y, bar_x_start + fill_w, bar_y + bar_h)

        except Exception as e:
            safe_print(f"Error in ScoreHeader.DrawMsg: {e}")


# Legacy alias: (severity, ok_message, fail_template, name_key_for_first).
# Backed by CHECK_REGISTRY so consumers do not maintain a second check list.
_CHECK_DISPLAY = CheckDisplayView()

class StatusArea(gui.GeUserArea):
    # Row order matches CHECK_REGISTRY; index here = clickable row index.
    ROW_KEYS = RowKeysView()

    def __init__(self):
        super().__init__()
        self.data = {}
        self.show = {k: True for k in _CHECK_DISPLAY}
        self.pad = 3
        self.rowh = 20
        self.font = c4d.FONT_MONOSPACED
        self.last_draw_time = 0
        self.min_draw_interval = 0.05
        # Click interaction (hover not supported: C4D 2026 Python does not route
        # BFM_GETCURSORINFO to embedded GeUserAreas)
        self.click_callback = None  # set by parent dialog: callable(row_key)

    def GetMinSize(self):
        rows = sum(1 for _, v in self.show.items() if v)
        return 400, max(1, rows) * (self.rowh + self.pad) + self.pad + 4

    def set_state(self, data, show):
        self.data = data or {}
        self.show = show or self.show

        # Throttle redraws
        now = time.time()
        if now - self.last_draw_time > self.min_draw_interval:
            self.Redraw()
            self.last_draw_time = now

    # ---- mouse interaction ----
    def _y_to_row(self, y):
        """Map y coordinate (local) to a visible row index, or -1 if outside."""
        try:
            y = int(y) - self.pad
            if y < 0:
                return -1
            row_pixel = self.rowh + self.pad
            visible_idx = y // row_pixel
            visible_keys = [k for k in self.ROW_KEYS if self.show.get(k, False)]
            if 0 <= visible_idx < len(visible_keys):
                return visible_idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        """Handle clicks. Called by C4D on mouse interaction over the GeUserArea."""
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            row = self._y_to_row(int(local_y))
            if row >= 0 and self.click_callback is not None:
                visible_keys = [k for k in self.ROW_KEYS if self.show.get(k, False)]
                if row < len(visible_keys):
                    self.click_callback(visible_keys[row])
                    return True
        except Exception as e:
            safe_print(f"StatusArea.InputEvent error: {e}")
        return False

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            x = self.pad
            y = self.pad

            for entry in CHECK_REGISTRY:
                label = entry.row_label
                key = entry.check_id
                if not self.show.get(key, False):
                    continue

                val = int(self.data.get(key, 0))
                cfg = _CHECK_DISPLAY.get(key)
                if not cfg:
                    continue

                severity, ok_msg, fail_tpl, name_key = cfg
                severity = self.data.get("_severity_by_id", {}).get(key, severity)
                disabled = key in set(self.data.get("_disabled_checks", []))
                baseline_counts = {}
                if self.data.get("_baseline_active"):
                    baseline_counts = self.data.get("_baseline_counts", {}).get(key, {}) or {}
                accepted_count = int(baseline_counts.get("accepted", 0) or 0)
                stale_count = int(baseline_counts.get("stale", 0) or 0)

                if disabled:
                    status = "[OFF ]"
                    message = "Disabled by project rules"
                    text_col = _COL_GRAY
                    bg = _COL_BG
                elif val > 0:
                    status = f"[{severity}]"
                    first = ""
                    if name_key:
                        names = self.data.get(name_key, [])
                        first = names[0] if names else "object"
                    if accepted_count:
                        message = format_baseline_row_message(val, accepted_count, stale_count)
                    else:
                        message = fail_tpl.format(n=val, first=first)
                    if name_key and val > 1 and not accepted_count:
                        message += f" (+{val-1} more)"
                    if not accepted_count:
                        message += _stale_suffix(stale_count)
                    text_col = _COL_RED if severity == "FAIL" else _COL_YELLOW
                    bg = _COL_BG_FAIL if severity == "FAIL" else _COL_BG_WARN
                else:
                    status = "[OK*]" if accepted_count else "[ OK ]"
                    message = format_baseline_row_message(0, accepted_count, stale_count) if accepted_count else ok_msg
                    if not accepted_count:
                        message += _stale_suffix(stale_count)
                    text_col = _COL_GREEN
                    bg = _COL_BG_OK

                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(y), int(w - self.pad), int(y + self.rowh))

                text_y = int(y + (self.rowh - 12) // 2)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(status, int(x + 5), text_y)

                self.DrawSetTextCol(_COL_GRAY, _COL_BLACK)
                self.DrawText(f"{label.ljust(13)}:", int(x + 55), text_y)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(message, int(x + 175), text_y)

                y += self.rowh + self.pad

        except Exception as e:
            safe_print(f"Error in DrawMsg: {e}")


# ---------------- Browse Versions UserArea ----------------
# Color palette for status badges (subtle backgrounds, ~70% saturation)
_COL_BADGE_WIP = c4d.Vector(0.35, 0.35, 0.35)        # neutral grey
_COL_BADGE_TR = c4d.Vector(0.55, 0.42, 0.18)         # amber
_COL_BADGE_CR = c4d.Vector(0.20, 0.40, 0.65)         # blue
_COL_BADGE_FINAL = c4d.Vector(0.25, 0.55, 0.30)      # green
_COL_BADGE_CUSTOM = c4d.Vector(0.45, 0.30, 0.55)     # purple

_COL_HISTORY_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_HISTORY_ROW_BG = c4d.Vector(0.14, 0.14, 0.14)
_COL_HISTORY_ROW_ALT = c4d.Vector(0.16, 0.16, 0.16)
_COL_HISTORY_TEXT = c4d.Vector(0.85, 0.85, 0.85)
_COL_HISTORY_DIM = c4d.Vector(0.55, 0.55, 0.55)


def _badge_color_for_status(status):
    """Pick the badge background color for a status string."""
    s = (status or "").upper()
    if s == "" or s == "WIP":
        return _COL_BADGE_WIP
    if s == "TR":
        return _COL_BADGE_TR
    if s == "CR":
        return _COL_BADGE_CR
    if s == "FINAL":
        return _COL_BADGE_FINAL
    return _COL_BADGE_CUSTOM


class HistoryArea(gui.GeUserArea):
    """Custom-drawn list of recent versions. One row per entry, status-coded badges.

    set_entries(entries) updates the list. click_callback(entry_dict) fires on row click.
    """

    ROW_HEIGHT = 22
    ROW_PAD = 2
    EMPTY_HEIGHT = 28

    def __init__(self):
        super().__init__()
        self.entries = []                # list of formatted dicts (output of format_version_row)
        self.click_callback = None       # callable(entry_dict)
        self.empty_msg = "No versions yet"
        self.font = c4d.FONT_DEFAULT

    def GetMinSize(self):
        rows = max(1, len(self.entries))
        h = rows * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 2
        if not self.entries:
            h = self.EMPTY_HEIGHT
        return 400, h

    def set_entries(self, entries):
        self.entries = list(entries) if entries else []
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    # ── click detection ─────────────────────────────
    def _y_to_index(self, y):
        try:
            y = int(y) - self.ROW_PAD
            if y < 0:
                return -1
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            idx = y // row_pixel
            if 0 <= idx < len(self.entries):
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
            if idx >= 0 and self.click_callback is not None:
                self.click_callback(self.entries[idx])
                return True
        except Exception as e:
            safe_print(f"HistoryArea.InputEvent error: {e}")
        return False

    # ── drawing ─────────────────────────────────────
    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_HISTORY_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self.entries:
                # Empty state
                self.DrawSetTextCol(_COL_HISTORY_DIM, _COL_HISTORY_BG)
                self.DrawText(self.empty_msg, 8, (h - 12) // 2)
                return

            # Layout: [v###] [BADGE] [comment............] [QC] [time]
            COL_VER_W = 50
            COL_BADGE_W = 50
            COL_QC_W = 50
            COL_TIME_W = 70
            margin = 6

            x = self.ROW_PAD
            y = self.ROW_PAD

            for i, entry in enumerate(self.entries):
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                # Alternating row background
                bg = _COL_HISTORY_ROW_ALT if (i % 2) else _COL_HISTORY_ROW_BG
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top), int(w - self.ROW_PAD), int(row_bot))

                text_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)
                cx = int(x + margin)

                # Version label
                self.DrawSetTextCol(_COL_HISTORY_TEXT, bg)
                self.DrawText(entry.get("version_label", "v???"), cx, text_y)
                cx += COL_VER_W

                # Status badge — colored rect with status text inside
                status = entry.get("status_label", "WIP")
                badge_col = _badge_color_for_status(status)
                badge_x0 = cx
                badge_x1 = cx + COL_BADGE_W - 6
                badge_y0 = row_top + 4
                badge_y1 = row_bot - 4
                self.DrawSetPen(badge_col)
                self.DrawRectangle(int(badge_x0), int(badge_y0), int(badge_x1), int(badge_y1))
                # Center the text inside the badge
                try:
                    txt_w = int(self.DrawGetTextWidth(status))
                except Exception:
                    txt_w = len(status) * 6
                badge_text_x = int(badge_x0 + ((badge_x1 - badge_x0) - txt_w) // 2)
                self.DrawSetTextCol(c4d.Vector(1, 1, 1), badge_col)
                self.DrawText(status, badge_text_x, text_y)
                cx += COL_BADGE_W

                # Time (right-aligned)
                tx_right = w - margin
                time_label = entry.get("time_label", "")
                if time_label:
                    try:
                        tw = int(self.DrawGetTextWidth(time_label))
                    except Exception:
                        tw = len(time_label) * 6
                    self.DrawSetTextCol(_COL_HISTORY_DIM, bg)
                    self.DrawText(time_label, int(tx_right - tw), text_y)
                    tx_right -= (tw + margin * 2)

                # QC label (just left of time, if present)
                qc_label = entry.get("qc_label", "")
                if qc_label:
                    try:
                        qw = int(self.DrawGetTextWidth(qc_label))
                    except Exception:
                        qw = len(qc_label) * 6
                    qc_color = _COL_HISTORY_DIM
                    qc_pass = entry.get("qc_pass")
                    if qc_pass is True:
                        qc_color = _COL_GREEN
                    elif qc_pass is False:
                        qc_color = _COL_YELLOW
                    self.DrawSetTextCol(qc_color, bg)
                    self.DrawText(qc_label, int(tx_right - qw), text_y)
                    tx_right -= (qw + margin * 2)

                # Comment (fills remaining space — may need truncation)
                comment = entry.get("comment", "")
                if comment:
                    avail_w = max(20, tx_right - cx - margin)
                    # Crude truncation: clip if too long
                    truncated = comment
                    try:
                        full_w = int(self.DrawGetTextWidth(truncated))
                        if full_w > avail_w:
                            # binary chop
                            while truncated and int(self.DrawGetTextWidth(truncated + "...")) > avail_w:
                                truncated = truncated[:-1]
                            truncated = truncated + "..." if truncated != comment else truncated
                    except Exception:
                        if len(truncated) > 60:
                            truncated = truncated[:57] + "..."
                    self.DrawSetTextCol(_COL_HISTORY_TEXT, bg)
                    self.DrawText(f'"{truncated}"', cx, text_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"Error in HistoryArea.DrawMsg: {e}")


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


class TextureListArea(gui.GeUserArea):
    """Scrollable custom-drawn list of texture records for the
    Repathing dialog.

    State is set via `set_state(records, filter_status, pending_changes)`.
    Clicks are routed through `click_callback(record_idx, region)` where
    `region` is one of:
      - "row"    — click on the row body (open file picker)
      - "browse" — click on the `[...]` browse button
      - None     — click in unfilled area
    Asset URI rows are not clickable (they call back with region=None).
    """

    ROW_HEIGHT = 38      # 2 lines per row: path + optional pending preview
    ROW_PAD = 2
    EMPTY_HEIGHT = 36
    BROWSE_BTN_W = 26
    MARGIN = 6

    # Filter values
    FILTER_ALL = "all"
    FILTER_MISSING = "missing"
    FILTER_ABSOLUTE = "absolute"
    FILTER_OK = "ok"
    FILTER_ASSET_URI = "asset_uri"

    def __init__(self):
        super().__init__()
        self.records = []                 # full list from scan
        self.filter_status = self.FILTER_ALL
        self.pending_changes = {}         # {record_idx: new_path_str}
        self.click_callback = None        # callable(record_idx, region)
        self.empty_msg = "No textures in scene"
        self.font = c4d.FONT_DEFAULT
        # Computed during draw — used by hit-testing
        self._visible_indices = []        # filtered indices in display order

    # ── state ───────────────────────────────────────
    def set_state(self, records, filter_status=None, pending_changes=None):
        self.records = list(records) if records else []
        if filter_status is not None:
            self.filter_status = filter_status
        if pending_changes is not None:
            self.pending_changes = dict(pending_changes)
        self._recompute_visible()
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    def _recompute_visible(self):
        f = self.filter_status
        if f == self.FILTER_ALL:
            self._visible_indices = list(range(len(self.records)))
        else:
            self._visible_indices = [
                i for i, r in enumerate(self.records)
                if r.get("status") == f
            ]

    def GetMinSize(self):
        # Report the FULL content height — the enclosing ScrollGroup is
        # the viewport and supplies the scrollbar. Returning the real
        # height is what tells the scroll group the content overflows.
        if not self._visible_indices:
            return 400, self.EMPTY_HEIGHT
        n = len(self._visible_indices)
        h = n * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 4
        return 400, h

    # ── click detection ─────────────────────────────
    def _hit_test(self, local_x, local_y):
        """Return (record_idx, region) for a click at local coords.
        record_idx is the absolute index into self.records (not the
        filtered display index). region: "row" | "browse" | None.
        """
        try:
            y = int(local_y) - self.ROW_PAD
            if y < 0:
                return -1, None
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            display_idx = y // row_pixel
            if not (0 <= display_idx < len(self._visible_indices)):
                return -1, None
            rec_idx = self._visible_indices[display_idx]
            rec = self.records[rec_idx]
            status = rec.get("status")
            if status in ("asset_uri", "empty"):
                return rec_idx, None  # not interactive

            # Browse button is the rightmost BROWSE_BTN_W pixels
            w = self.GetWidth()
            x = int(local_x)
            if x >= w - self.BROWSE_BTN_W - self.MARGIN:
                return rec_idx, "browse"
            return rec_idx, "row"
        except Exception:
            return -1, None

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            lx, ly = _ua_local_coords(self, mx, my)
            rec_idx, region = self._hit_test(lx, ly)
            if rec_idx >= 0 and region is not None and self.click_callback:
                self.click_callback(rec_idx, region)
                return True
        except Exception as e:
            safe_print(f"TextureListArea.InputEvent error: {e}")
        return False

    # ── drawing ─────────────────────────────────────
    def _status_glyph_color(self, status):
        return {
            "missing":   ("✗", _COL_TEXLIST_RED),
            "absolute":  ("⚠", _COL_TEXLIST_AMBER),
            "asset_uri": ("≈", _COL_TEXLIST_BLUE),
            "ok":        ("✓", _COL_TEXLIST_GREEN),
            "empty":     ("·", _COL_TEXLIST_DIM),
        }.get(status, ("?", _COL_TEXLIST_DIM))

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()
            self.DrawSetPen(_COL_TEXLIST_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self._visible_indices:
                msg_txt = (self.empty_msg if not self.records
                           else f"No textures match filter "
                                f"'{self.filter_status}'")
                self.DrawSetTextCol(_COL_TEXLIST_DIM, _COL_TEXLIST_BG)
                self.DrawText(msg_txt, 8, (h - 12) // 2)
                return

            # Column layout (approximate widths within available width)
            #   [status 22] [host 180] [channel 100] [path expand] [btn 26]
            COL_STATUS = 22
            COL_HOST = 180
            COL_CHAN = 100
            BTN_W = self.BROWSE_BTN_W
            margin = self.MARGIN

            x = self.ROW_PAD
            y = self.ROW_PAD

            for display_idx, rec_idx in enumerate(self._visible_indices):
                rec = self.records[rec_idx]
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                # Skip rows fully outside the redraw clip region — keeps
                # drawing cheap when the scrolled list is long.
                if row_bot < y1 or row_top > y2:
                    y += self.ROW_HEIGHT + self.ROW_PAD
                    continue
                bg = (_COL_TEXLIST_ROW_ALT if (display_idx % 2)
                      else _COL_TEXLIST_ROW)
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top),
                                   int(w - self.ROW_PAD), int(row_bot))

                # Two-line layout: first line = main info, second = pending
                # change (or current path if no pending). 14px line height.
                line1_y = int(row_top + 4)
                line2_y = int(row_top + 4 + 16)
                status = rec.get("status", "")
                glyph, glyph_col = self._status_glyph_color(status)

                # Status glyph
                self.DrawSetTextCol(glyph_col, bg)
                self.DrawText(glyph, int(x + margin), line1_y)

                cx = int(x + margin + COL_STATUS)

                # Host name (truncated if too long)
                host = str(rec.get("host_name", "<?>"))
                if len(host) > 28:
                    host = host[:25] + "..."
                self.DrawSetTextCol(_COL_TEXLIST_TEXT, bg)
                self.DrawText(host, cx, line1_y)
                cx += COL_HOST

                # Channel name
                channel = str(rec.get("channel", ""))[:16]
                self.DrawSetTextCol(_COL_TEXLIST_DIM, bg)
                self.DrawText(channel, cx, line1_y)
                cx += COL_CHAN

                # Source type tag (small, right of channel) — useful at a
                # glance to know which renderer this is from.
                stype = rec.get("source_type", "")
                stype_short = stype.replace("_shader", "").replace(
                    "_node", "/node").replace("_oct_", "/oct ").replace(
                    "_fileref", "/ref")
                self.DrawSetTextCol(_COL_TEXLIST_DIM, bg)
                self.DrawText(f"[{stype_short}]", cx, line1_y)

                # Browse button — rightmost. Hidden for non-interactive
                # rows (asset_uri / empty).
                interactive = status not in ("asset_uri", "empty")
                if interactive:
                    btn_x0 = int(w - BTN_W - margin)
                    btn_y0 = int(row_top + 4)
                    btn_y1 = int(row_top + self.ROW_HEIGHT - 4)
                    self.DrawSetPen(_COL_TEXLIST_BTN_BG)
                    self.DrawRectangle(btn_x0, btn_y0,
                                       int(w - margin), btn_y1)
                    self.DrawSetTextCol(_COL_TEXLIST_TEXT,
                                        _COL_TEXLIST_BTN_BG)
                    self.DrawText("...",
                                  btn_x0 + 6, btn_y0 + 4)

                # Second line: pending change OR current path
                pending = self.pending_changes.get(rec_idx)
                if pending:
                    # Show "→ new_path" in green
                    self.DrawSetTextCol(_COL_TEXLIST_PENDING, bg)
                    pending_short = _format_path_compact(pending, 80)
                    self.DrawText(f"→ {pending_short}",
                                  int(x + margin + COL_STATUS), line2_y)
                else:
                    # Show current path muted
                    cur = _format_path_compact(rec.get("current_path", ""), 80)
                    text_col = (_COL_TEXLIST_DIM if status == "asset_uri"
                                else _COL_TEXLIST_TEXT)
                    self.DrawSetTextCol(text_col, bg)
                    self.DrawText(cur,
                                  int(x + margin + COL_STATUS), line2_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"Error in TextureListArea.DrawMsg: {e}")


# ---------------- AssetListArea (Sentinel Asset Hub) ----------------

_ASSET_STATUS_COLORS = {
    "ok":        c4d.Vector(0.30, 0.69, 0.31),
    "missing":   c4d.Vector(0.90, 0.22, 0.21),
    "absolute":  c4d.Vector(1.00, 0.60, 0.00),
    "asset_uri": c4d.Vector(0.47, 0.47, 0.47),
    "empty":     c4d.Vector(0.47, 0.47, 0.47),
}

# Dim gray (#777777) for the "read-only" badge drawn after non-repathable
# records' type text — item 4 of the Asset Hub UI polish pass.
_COL_ASSET_READONLY = c4d.Vector(0.47, 0.47, 0.47)

# Asset Hub header (item 2) and pre-flight strip (item 3) colors.
_COL_HUB_HEADER_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_HUB_HEADER_TEXT = c4d.Vector(0.95, 0.95, 0.95)
_COL_HUB_HEADER_DIM = c4d.Vector(0.60, 0.60, 0.60)
_COL_HUB_HEADER_RED = c4d.Vector(0.898, 0.451, 0.451)     # #e57373
_COL_HUB_HEADER_ORANGE = c4d.Vector(1.00, 0.718, 0.302)   # #ffb74d

_COL_PREFLIGHT_OK_BG = c4d.Vector(0.14, 0.18, 0.14)
_COL_PREFLIGHT_WARN_BG = c4d.Vector(0.20, 0.17, 0.12)
_COL_PREFLIGHT_TEXT = c4d.Vector(0.90, 0.90, 0.90)

_ASSET_SORT_KEYS = {
    "status": lambda r: {"missing": 0, "absolute": 1, "empty": 2,
                          "asset_uri": 3, "ok": 4}.get(r["status"], 9),
    "name":   lambda r: os.path.basename(r["path"]).lower(),
    "type":   lambda r: r["asset_type"],
    "size":   lambda r: -(r["size_bytes"] or 0),
}


class AssetListArea(gui.GeUserArea):
    """Flat, sortable asset table for the Asset Hub. Regions per row: 'row'
    (highlight), 'used_by' (select owner in scene), 'browse' (file picker,
    repathable only). Header clicks sort the table instead of calling back.
    Thumbnails come from self.thumb_cache, filled by the dialog's Timer —
    a None value is a permanent placeholder (nothing is drawn) so a failed
    load is not retried every frame.
    """

    ROW_H = 26
    HEADER_H = 20

    # User-resizable columns (item 3) — status/thumb are small fixed icon
    # columns and path always takes the remainder, so neither is draggable.
    RESIZABLE_COLS = ("name", "type", "size", "used")
    # Shared with settings.py's per-key validation floor — one constant,
    # not two independently-maintained "40"s.
    MIN_COL_WIDTH = ASSET_HUB_COL_WIDTH_MIN
    DRAG_HIT_TOLERANCE = 5   # px on either side of a divider that counts as a hit

    # Browse is a fixed-width slot pinned to the right edge, always — it
    # never shrinks or gets pushed off-screen by widened columns. Path
    # fills the gap between the last resizable column and the browse
    # slot, with a hard floor of PATH_MIN_WIDTH.
    BROWSE_COL_WIDTH = 26
    PATH_MIN_WIDTH = 60
    # Live-measured: the enclosing ScrollGroup draws its vertical
    # scrollbar over the rightmost ~15-18px of this UserArea whenever the
    # content scrolls (confirmed on screen — GetWidth() reported 1346 with
    # browse drawn at x=1320, mathematically inside but visually under the
    # scrollbar track). Reserve that strip so browse never sits under it.
    SCROLLBAR_PAD = 18
    # Leading fixed layout before the 4 resizable columns: 6 (left margin)
    # + status(24)+6 + thumb(26)+6 = 68, derived once here so _columns and
    # _max_col_width (the drag clamp) can never drift apart.
    _LEADING_FIXED_WIDTH = 6 + 24 + 6 + 26 + 6

    def __init__(self):
        super().__init__()
        self.records = []
        self.visible = []            # indices into records after filter/search
        self.filter_status = None
        self.search_text = ""
        self.pending_changes = {}    # {record_key: new_path}
        self.sort_column = "status"
        self.selected_key = None
        self.click_callback = None   # callable(record_key, region)
        self.thumb_cache = {}        # {resolved_path: c4d.bitmaps.BaseBitmap}
        self.font = c4d.FONT_DEFAULT
        # Persisted per-column widths (item 3) — loaded here with a
        # per-key validation fallback to defaults, so a malformed/legacy
        # sentinel_settings.json value never crashes layout.
        self.col_widths = GlobalSettings.get_asset_hub_col_widths()

    # ── state ───────────────────────────────────────
    def set_state(self, records, filter_status=None, search_text="",
                  pending_changes=None):
        self.records = records or []
        self.filter_status = filter_status
        self.search_text = (search_text or "").lower()
        self.pending_changes = pending_changes or {}
        self._recompute_visible()
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    def sort_by(self, column):
        if column in _ASSET_SORT_KEYS:
            self.sort_column = column
            self._recompute_visible()
            self.Redraw()

    def _recompute_visible(self):
        idxs = range(len(self.records))
        if self.filter_status:
            idxs = [i for i in idxs
                    if self.records[i]["status"] == self.filter_status]
        else:
            idxs = list(idxs)
        if self.search_text:
            idxs = [i for i in idxs
                    if self.search_text in self.records[i]["path"].lower()
                    or self.search_text in os.path.basename(
                        self.records[i]["path"]).lower()]
        key = _ASSET_SORT_KEYS[self.sort_column]
        idxs.sort(key=lambda i: key(self.records[i]))
        self.visible = idxs

    def get_visible_range(self):
        """All filtered rows (the ScrollGroup clips drawing; thumbnail work
        is bounded by batching in the dialog Timer, not by this range)."""
        return (0, len(self.visible))

    def GetMinSize(self):
        # Report the FULL content height — the enclosing ScrollGroup is the
        # viewport (same convention as TextureListArea.GetMinSize).
        h = self.HEADER_H + max(1, len(self.visible)) * self.ROW_H
        return 700, h

    def _col_budget(self, w):
        """Max total width the 4 resizable columns may occupy at widget
        width `w`, leaving room for the leading fixed columns + gutters,
        PATH_MIN_WIDTH, the pinned BROWSE_COL_WIDTH slot, and
        SCROLLBAR_PAD (the ScrollGroup's vertical scrollbar draws over the
        rightmost strip of this UserArea). Single source of truth for
        both `_columns`' fit-to-viewport shrink and the drag clamp in
        `_max_col_width` — derived directly from the layout `_columns()`
        produces: at the limit, _LEADING_FIXED_WIDTH + sum(4 resizable
        widths) + 4 gutters (6px each) + 1 gutter before browse (6px) +
        PATH_MIN_WIDTH + BROWSE_COL_WIDTH + SCROLLBAR_PAD == w.
        """
        fixed = (self._LEADING_FIXED_WIDTH + 4 * 6 + 6
                 + self.BROWSE_COL_WIDTH + self.SCROLLBAR_PAD)
        return w - fixed - self.PATH_MIN_WIDTH

    # ── column layout (computed once per hit-test / draw from current width)
    def _columns(self, w):
        xs = {}
        x = 6
        # Fit-to-viewport invariant: self.col_widths may hold values
        # persisted from an EARLIER, wider window (sentinel_settings.json
        # survives across sessions/window sizes). Honoring them verbatim
        # here would push path/browse off the visible edge on a narrower
        # window — fit_column_widths (pure, sentinel.assets) shrinks them
        # proportionally to fit, display-only: the return value is never
        # written back to self.col_widths, so widening the window again
        # restores the user's actual stored widths.
        fitted = fit_column_widths(self.col_widths, self.RESIZABLE_COLS,
                                    self._col_budget(w), self.MIN_COL_WIDTH)
        # status/thumb stay fixed icon columns; both the hit test and the
        # draw pass read this same table, so they stay in sync. "type" is
        # widened 64 -> 110 by default to make room for the item-4
        # "read-only" badge.
        for name, cw in (("status", 24), ("thumb", 26),
                          ("name", fitted["name"]), ("type", fitted["type"]),
                          ("size", fitted["size"]), ("used", fitted["used"])):
            xs[name] = (x, cw)
            x += cw + 6
        # Browse is a fixed slot pinned SCROLLBAR_PAD px inboard of the
        # right edge — live measurement showed the ScrollGroup's vertical
        # scrollbar draws over the rightmost ~15-18px of this UserArea
        # when content scrolls, so a browse slot anchored at the bare
        # edge (mathematically inside GetWidth()) sat under the
        # scrollbar track and read as invisible/clipped. Path fills
        # exactly the gap between the last resizable column and the
        # browse slot (floor PATH_MIN_WIDTH). Between the fit-to-viewport
        # shrink above and the drag clamp in _max_col_width, this floor
        # should never be force-violated in practice; the max() here is
        # the last-resort guard for windows narrower than GetMinSize.
        browse_x = w - self.BROWSE_COL_WIDTH - self.SCROLLBAR_PAD
        xs["browse"] = (browse_x, self.BROWSE_COL_WIDTH)
        xs["path"] = (x, max(self.PATH_MIN_WIDTH, browse_x - 6 - x))
        return xs

    def _column_edges(self, xs):
        """Right-edge x for each resizable column, from an already-computed
        `_columns()` table. Single source of truth for both the drag hit
        test and the drawn divider lines — what the user sees is exactly
        where they grab (item 2 of the follow-up UI polish pass)."""
        return {col: xs[col][0] + xs[col][1] for col in self.RESIZABLE_COLS}

    def _divider_hit(self, lx, ly):
        """Return the resizable column whose right-edge divider is within
        DRAG_HIT_TOLERANCE px of lx, or None. Header row only — dividers
        are not draggable over the data rows."""
        if ly >= self.HEADER_H:
            return None
        xs = self._columns(self.GetWidth())
        for col, edge in self._column_edges(xs).items():
            if abs(lx - edge) <= self.DRAG_HIT_TOLERANCE:
                return col
        return None

    def _max_col_width(self, col, w):
        """Widest `col` can become while still leaving PATH_MIN_WIDTH free
        for the path column before the fixed BROWSE_COL_WIDTH slot.

        Belt-and-braces on top of `_columns`' fit-to-viewport shrink:
        "others" is read from the FITTED layout (not the raw, possibly
        oversized stored widths), so the budget for the dragged column
        reflects what the other three columns actually occupy on screen
        right now — widening one column can never push path/browse off
        the right edge or into each other.
        """
        budget = self._col_budget(w)
        fitted = fit_column_widths(self.col_widths, self.RESIZABLE_COLS,
                                    budget, self.MIN_COL_WIDTH)
        others = sum(fitted[c] for c in self.RESIZABLE_COLS if c != col)
        return max(self.MIN_COL_WIDTH, budget - others)

    def _drag_column(self, col, mx, my):
        """Blocking column-resize drag loop.

        Grounded in the local SDK example `geuserarea_drag_r13.py`
        (MouseDragStart / MouseDrag / MouseDragEnd):
        - C4D's per-tick deltaX from MouseDrag() is signed opposite to the
          actual mouse movement, so the example accumulates the true
          current mouse X via `mouseX -= deltaX` each tick — mirrored here
          as `mx`.
        - The FIRST MouseDrag() tick reports a synthetic dx/dy of 4.0 from
          the click itself (example lines 283-298), so it is skipped via
          the same `is_first_tick` guard — without it every drag starts
          4px off, and a plain click near a divider (no real movement)
          would still shrink the column.
        - MouseDragEnd() is called from `finally` (not just after a clean
          break), matching the example's unconditional call — any
          exception mid-drag still releases the mouse capture.
        Width is clamped to [MIN_COL_WIDTH, _max_col_width(col, GetWidth())]
        — the upper bound is recomputed every tick from the CURRENT widget
        width, so it tracks a live window resize during the drag and, more
        importantly, guarantees path always keeps its PATH_MIN_WIDTH floor
        before the fixed browse slot (item 1 of the follow-up UI polish
        pass — a plain MIN_COL_WIDTH=40 floor alone let name/type/size/used
        grow large enough to push path under/past browse). The clamped
        width is pushed to col_widths (and therefore _columns/
        LayoutChanged) on every tick that changes it, so the table visibly
        resizes live. Persistence only fires if the final width differs
        from drag start — a no-movement click writes nothing to settings.
        No cursor feedback: BFM_GETCURSORINFO is not routed to embedded
        GeUserAreas in C4D 2026 (documented limitation, see CLAUDE.md
        Known Limitations).
        """
        start_x = mx
        start_width = self.col_widths[col]
        try:
            # DONTHIDEMOUSE keeps the pointer visible (no OS-level cursor
            # feedback anyway, per the limitation above); NOMOVE keeps the
            # OS cursor pinned at the click position during the drag,
            # matching the SDK example exactly.
            self.MouseDragStart(
                c4d.KEY_MLEFT, mx, my,
                c4d.MOUSEDRAGFLAGS_DONTHIDEMOUSE | c4d.MOUSEDRAGFLAGS_NOMOVE)
            is_first_tick = True
            while True:
                result, dx, dy, channels = self.MouseDrag()
                if result != c4d.MOUSEDRAGRESULT_CONTINUE:
                    break
                if is_first_tick:
                    is_first_tick = False
                    continue
                mx -= dx
                max_w = self._max_col_width(col, self.GetWidth())
                new_width = max(self.MIN_COL_WIDTH,
                                min(max_w, int(start_width + (mx - start_x))))
                if new_width != self.col_widths[col]:
                    self.col_widths[col] = new_width
                    self.LayoutChanged()
                    self.Redraw()
        except Exception as e:
            safe_print(f"AssetListArea._drag_column error: {e}")
        finally:
            self.MouseDragEnd()
        # Persist only if the width actually moved off drag start.
        if self.col_widths[col] != start_width:
            GlobalSettings.set_asset_hub_col_widths(self.col_widths)

    # ── click detection ─────────────────────────────
    def _hit_test(self, lx, ly):
        if ly < self.HEADER_H:
            xs = self._columns(self.GetWidth())
            for col in ("status", "name", "type", "size"):
                cx, cw = xs[col]
                if cx <= lx <= cx + cw:
                    return None, ("header", col)
            return None, None
        row = int((ly - self.HEADER_H) // self.ROW_H)
        if row < 0 or row >= len(self.visible):
            return None, None
        rec = self.records[self.visible[row]]
        xs = self._columns(self.GetWidth())
        ux, uw = xs["used"]
        bx, bw = xs["browse"]
        if ux <= lx <= ux + uw:
            return rec["key"], "used_by"
        if rec["repathable"] and bx <= lx <= bx + bw:
            return rec["key"], "browse"
        return rec["key"], "row"

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            lx, ly = _ua_local_coords(self, mx, my)

            # A divider hit takes priority over a header sort click (item 3)
            # — clicking exactly on a boundary resizes, it never sorts.
            divider_col = self._divider_hit(lx, ly)
            if divider_col is not None:
                self._drag_column(divider_col, mx, my)
                return True

            key, region = self._hit_test(lx, ly)
            if region and isinstance(region, tuple) and region[0] == "header":
                self.sort_by(region[1])
                return True
            if key is not None:
                self.selected_key = key
                self.Redraw()
                if self.click_callback and region:
                    self.click_callback(key, region)
                return True
        except Exception as e:
            safe_print(f"AssetListArea.InputEvent error: {e}")
        return False

    # ── drawing ─────────────────────────────────────
    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            self.DrawSetPen(c4d.Vector(0.13, 0.13, 0.13))
            self.DrawRectangle(x1, y1, x2, y2)
            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass
            xs = self._columns(w)

            # header
            self.DrawSetTextCol(c4d.Vector(0.55, 0.55, 0.55),
                                c4d.Vector(0.13, 0.13, 0.13))
            labels = (("status", ""), ("name", "Asset"), ("type", "Type"),
                      ("size", "Size"), ("used", "Used by"), ("path", "Path"))
            for col, label in labels:
                cx, _cw = xs[col]
                mark = " ▾" if col == self.sort_column else ""
                self.DrawText(label + mark, cx, 3)

            y = self.HEADER_H
            for row, idx in enumerate(self.visible):
                rec = self.records[idx]
                if rec["key"] == self.selected_key:
                    self.DrawSetPen(c4d.Vector(0.20, 0.25, 0.32))
                    self.DrawRectangle(0, y, w, y + self.ROW_H - 1)
                # status dot
                cx, _ = xs["status"]
                self.DrawSetPen(_ASSET_STATUS_COLORS.get(
                    rec["status"], c4d.Vector(0.5, 0.5, 0.5)))
                self.DrawRectangle(cx + 4, y + 8, cx + 13, y + 17)
                # thumbnail (None entry in the cache = permanent placeholder,
                # draw nothing rather than retry every frame)
                tx, _ = xs["thumb"]
                bmp = self.thumb_cache.get(rec.get("resolved_path"))
                if bmp is not None:
                    self.DrawBitmap(bmp, tx, y + 2, 22, 22, 0, 0,
                                    bmp.GetBw(), bmp.GetBh(), c4d.BMP_NORMAL)
                # texts
                pending = rec["key"] in self.pending_changes
                bg = (c4d.Vector(0.20, 0.25, 0.32) if
                      rec["key"] == self.selected_key
                      else c4d.Vector(0.13, 0.13, 0.13))
                if pending:
                    name_col = c4d.Vector(0.51, 0.78, 0.52)
                elif rec["status"] in ("missing", "absolute"):
                    name_col = _ASSET_STATUS_COLORS.get(
                        rec["status"], c4d.Vector(0.8, 0.8, 0.8))
                else:
                    name_col = c4d.Vector(0.83, 0.83, 0.83)
                self.DrawSetTextCol(name_col, bg)
                nx, nw = xs["name"]
                name_text = os.path.basename(rec["path"]) or rec["path"]
                self.DrawText(_format_path_compact(name_text,
                                                   max_chars=max(10, nw // 7)),
                              nx, y + 5)
                self.DrawSetTextCol(c4d.Vector(0.6, 0.6, 0.6), bg)
                self.DrawText(rec["asset_type"], xs["type"][0], y + 5)
                if not rec["repathable"]:
                    # Dim "read-only" tag after the type text, budgeted
                    # inside the widened type column so it never collides
                    # with Size (item 4).
                    try:
                        type_w = int(self.DrawGetTextWidth(rec["asset_type"]))
                    except Exception:
                        type_w = len(rec["asset_type"]) * 6
                    badge_x = xs["type"][0] + type_w + 6
                    type_end = xs["type"][0] + xs["type"][1]
                    if badge_x < type_end - 10:
                        self.DrawSetTextCol(_COL_ASSET_READONLY, bg)
                        self.DrawText("read-only", badge_x, y + 5)
                    self.DrawSetTextCol(c4d.Vector(0.6, 0.6, 0.6), bg)
                self.DrawText(format_size(rec["size_bytes"]), xs["size"][0], y + 5)
                owners = rec["owners"] or [("", "", "")]
                used = (f"{owners[0][0]} / {owners[0][2]}" if owners[0][2]
                        else owners[0][0])
                if len(owners) > 1:
                    used += f" (+{len(owners) - 1})"
                self.DrawSetTextCol(c4d.Vector(0.55, 0.65, 0.75), bg)
                ux, uw = xs["used"]
                self.DrawText(_format_path_compact(used,
                                                   max_chars=max(10, uw // 7)),
                              ux, y + 5)
                shown_path = self.pending_changes.get(rec["key"], rec["path"])
                self.DrawSetTextCol(
                    c4d.Vector(0.51, 0.78, 0.52) if pending
                    else c4d.Vector(0.45, 0.45, 0.45), bg)
                px, pw = xs["path"]
                self.DrawText(_format_path_compact(shown_path,
                                                   max_chars=max(20, pw // 7)),
                              px, y + 5)
                if rec["repathable"]:
                    self.DrawSetTextCol(c4d.Vector(0.7, 0.7, 0.7), bg)
                    self.DrawText("...", xs["browse"][0], y + 5)
                y += self.ROW_H

            # Column dividers (item 2, follow-up UI polish pass) — drawn at
            # the exact same x as _divider_hit's boundary (both derive from
            # `xs` via _column_edges), so what the user sees is exactly
            # where they grab. Visible 1px line across the header; a
            # fainter line continues down the body rows for column
            # separation.
            for col, edge in self._column_edges(xs).items():
                self.DrawSetPen(c4d.Vector(0.32, 0.32, 0.32))
                self.DrawRectangle(edge, 0, edge + 1, self.HEADER_H)
                if y > self.HEADER_H:
                    self.DrawSetPen(c4d.Vector(0.18, 0.18, 0.18))
                    self.DrawRectangle(edge, self.HEADER_H, edge + 1, y)

            # Faint divider before the fixed browse slot (item 1 of the
            # follow-up UI polish pass) — body rows only, so the "…" reads
            # as its own column instead of running into path's text.
            if y > self.HEADER_H:
                browse_edge = xs["browse"][0]
                self.DrawSetPen(c4d.Vector(0.18, 0.18, 0.18))
                self.DrawRectangle(browse_edge, self.HEADER_H,
                                   browse_edge + 1, y)

        except Exception as e:
            safe_print(f"Error in AssetListArea.DrawMsg: {e}")


class AssetHubHeaderArea(gui.GeUserArea):
    """Colored header for the Asset Hub: "Scene: <name>" left-anchored,
    asset totals right-anchored — replacing a plain StaticText (item 2 of
    the UI polish pass). Pattern mirrored from ScoreHeader — measure a
    segment with DrawGetTextWidth, then DrawSetTextCol + DrawText it; the
    right-hand block measures its total width first (same _measure per
    segment) so it can start at GetWidth() - total - margin.
    """

    HEIGHT = 20

    def __init__(self):
        super().__init__()
        self.doc_name = ""
        self.count = 0
        self.missing = 0
        self.absolute = 0
        self.size_text = ""
        self.suffix = ""

    def GetMinSize(self):
        return 400, self.HEIGHT

    def set_header_state(self, doc_name, count, missing, absolute,
                          size_text, suffix=""):
        self.doc_name = doc_name or ""
        self.count = max(0, int(count or 0))
        self.missing = max(0, int(missing or 0))
        self.absolute = max(0, int(absolute or 0))
        self.size_text = size_text or ""
        self.suffix = suffix or ""
        self.Redraw()

    def _measure(self, text):
        try:
            return int(self.DrawGetTextWidth(text))
        except Exception:
            return len(text) * 6

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_HUB_HEADER_BG)
            self.DrawRectangle(0, 0, w, h)

            text_y = max(2, (h - 12) // 2)
            sep = " · "
            sep_w = self._measure(sep)
            margin = 8

            # Right: summary segments, measured first so the left side
            # knows how much room it has before it would overlap them.
            segments = [
                (f"{self.count} assets", _COL_HUB_HEADER_TEXT),
                (f"{self.missing} missing",
                 _COL_HUB_HEADER_RED if self.missing else _COL_HUB_HEADER_DIM),
                (f"{self.absolute} absolute",
                 _COL_HUB_HEADER_ORANGE if self.absolute else _COL_HUB_HEADER_DIM),
                (self.size_text, _COL_HUB_HEADER_DIM),
            ]
            if self.suffix:
                segments.append((self.suffix, _COL_HUB_HEADER_DIM))
            segments = [(text, col) for text, col in segments if text]

            total_w = sum(self._measure(text) for text, _ in segments)
            total_w += sep_w * max(0, len(segments) - 1)
            right_start = max(margin, w - total_w - margin)

            # Left: scene identity, clipped so a long scene name can never
            # overlap the right-anchored summary — same truncate-to-width
            # loop TodoArea/PreflightStripArea use (shrink + ellipsis until
            # it fits the room between the left margin and right_start).
            left_text = f"Scene: {self.doc_name}" if self.doc_name else "Scene:"
            avail_w = max(0, right_start - margin)
            truncated = left_text
            try:
                if self._measure(truncated) > avail_w:
                    while truncated and self._measure(truncated + "...") > avail_w:
                        truncated = truncated[:-1]
                    truncated = (truncated + "..."
                                 if truncated != left_text else truncated)
            except Exception:
                if len(truncated) > 40:
                    truncated = truncated[:37] + "..."
            self.DrawSetTextCol(_COL_HUB_HEADER_DIM, _COL_HUB_HEADER_BG)
            self.DrawText(truncated, margin, text_y)

            x = right_start
            first = True
            for text, col in segments:
                if not first:
                    self.DrawSetTextCol(_COL_HUB_HEADER_DIM, _COL_HUB_HEADER_BG)
                    self.DrawText(sep, x, text_y)
                    x += sep_w
                self.DrawSetTextCol(col, _COL_HUB_HEADER_BG)
                self.DrawText(text, x, text_y)
                x += self._measure(text)
                first = False

        except Exception as e:
            safe_print(f"Error in AssetHubHeaderArea.DrawMsg: {e}")


class PreflightStripArea(gui.GeUserArea):
    """Full-width colored strip for the Asset Hub pre-flight QC summary
    (item 3 of the UI polish pass) — dark green when all checks are clear,
    dark amber when there are failing checks, with the score/summary text
    drawn on top and truncated to width (same truncate-to-width technique
    TodoArea.DrawMsg uses for its row text).
    """

    HEIGHT = 22

    def __init__(self):
        super().__init__()
        self.ok = True
        self.text = ""

    def GetMinSize(self):
        return 300, self.HEIGHT

    def set_state(self, ok, text):
        self.ok = bool(ok)
        self.text = text or ""
        self.Redraw()

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            bg = _COL_PREFLIGHT_OK_BG if self.ok else _COL_PREFLIGHT_WARN_BG
            self.DrawSetPen(bg)
            self.DrawRectangle(0, 0, w, h)

            text_y = max(2, (h - 12) // 2)
            margin = 6
            avail_w = w - margin * 2
            truncated = self.text
            try:
                if int(self.DrawGetTextWidth(truncated)) > avail_w:
                    while truncated and int(
                            self.DrawGetTextWidth(truncated + "...")) > avail_w:
                        truncated = truncated[:-1]
                    truncated = (truncated + "..."
                                 if truncated != self.text else truncated)
            except Exception:
                if len(truncated) > 80:
                    truncated = truncated[:77] + "..."

            self.DrawSetTextCol(_COL_PREFLIGHT_TEXT, bg)
            self.DrawText(truncated, margin, text_y)

        except Exception as e:
            safe_print(f"Error in PreflightStripArea.DrawMsg: {e}")
