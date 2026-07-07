# -*- coding: utf-8 -*-
"""Custom Sentinel user areas and row-format helpers."""

import time

import c4d
from c4d import gui

from sentinel.common.helpers import safe_print
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
