# -*- coding: utf-8 -*-
"""Render-complete notification (v1.30 Tools quick-wins).

Pure state machine (:class:`RenderWatch`) ticked from the existing
``FrameSyncMessageData`` 250 ms pump (a second MessageData would burn a
plugin id for nothing). Detects the Picture Viewer render finishing via
``c4d.CheckIsRunning(CHECKISRUNNING_EXTERNALRENDERING)`` and posts a macOS
notification when the render lasted longer than the threshold (30 s — test
renders stay silent) and the ``render_notify`` setting is on (default ON).
The tick must NEVER raise into the pump.
"""

import subprocess
import sys
import time

try:
    import c4d
except ImportError:  # pragma: no cover
    c4d = None

THRESHOLD_SECONDS = 30.0


class RenderWatch(object):
    """idle -> rendering -> done, injectable clock, duration-once semantics."""

    def __init__(self, threshold=THRESHOLD_SECONDS):
        self._threshold = float(threshold)
        self._started = None

    def observe(self, is_rendering, now):
        if is_rendering:
            if self._started is None:
                self._started = float(now)
            return None
        if self._started is None:
            return None
        duration = float(now) - self._started
        self._started = None
        if duration > self._threshold:
            return duration
        return None


def format_duration(seconds):
    seconds = int(round(float(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%dh %dm %ds" % (hours, minutes, secs)
    if minutes:
        return "%dm %ds" % (minutes, secs)
    return "%ds" % secs


def _notify_macos(message, title="Sentinel"):
    if sys.platform != "darwin":
        return
    try:
        script = 'display notification "%s" with title "%s"' % (
            str(message).replace('"', "'"), str(title).replace('"', "'"))
        subprocess.Popen(["osascript", "-e", script])
    except Exception:
        pass


#: Latest render-finished notice for the IN-C4D delivery paths (panel toast +
#: status bar). macOS banners are best-effort only — live-caught: Focus modes
#: / per-responsible-process permissions silently swallow osascript
#: notifications (exit 0, nothing shown), so the plugin's own surfaces are
#: the primary channel. Peek-don't-pop: every ``panel/state_stamp`` reader
#: sees the same notice and the CLIENT dedupes by ``id`` — popping here would
#: let any concurrent stamp fetch (mutation refetches) swallow the toast.
NOTICE_MAX_AGE_SECONDS = 180.0
_notice_seq = 0
_latest_notice = None  # {"id": int, "text": str, "ts": float}


def _record_notice(text, now):
    global _notice_seq, _latest_notice
    _notice_seq += 1
    _latest_notice = {"id": _notice_seq, "text": str(text), "ts": float(now)}


def latest_notice(now=None, max_age=NOTICE_MAX_AGE_SECONDS):
    """Return the latest notice as ``{"id", "text"}`` while it is younger
    than ``max_age`` seconds, else ``None``. Read-only (peek)."""
    if _latest_notice is None:
        return None
    now = time.monotonic() if now is None else float(now)
    if now - _latest_notice["ts"] > float(max_age):
        return None
    return {"id": _latest_notice["id"], "text": _latest_notice["text"]}


def _status_bar(message):
    if c4d is None:
        return
    try:
        c4d.gui.StatusSetText(str(message))
    except Exception:
        pass


_watch = RenderWatch()


def tick_active_document(now=None):
    """Poll the external-render state; notify on a qualifying finish."""
    if c4d is None:
        return
    try:
        rendering = bool(c4d.CheckIsRunning(c4d.CHECKISRUNNING_EXTERNALRENDERING))
        duration = _watch.observe(rendering, time.monotonic() if now is None else now)
        if duration is None:
            return
        from sentinel.common.settings import GlobalSettings
        try:
            enabled = bool(int(GlobalSettings.get("render_notify", 1)))
        except Exception:
            enabled = True
        if enabled:
            message = "Render finished — %s" % format_duration(duration)
            # Primary: the plugin's own surfaces (panel toast via the notice,
            # C4D status bar). Secondary: macOS banner, best-effort only.
            _record_notice(message, time.monotonic() if now is None else now)
            _status_bar("Sentinel: %s" % message)
            _notify_macos(message)
    except Exception:
        pass
