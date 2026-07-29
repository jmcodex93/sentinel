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
            _notify_macos("Render finished — %s" % format_duration(duration))
    except Exception:
        pass
