"""SyncScheduler — the pure debounce core of the Frame v2 auto-sync.

The scheduler never imports c4d and never reads the clock itself: the caller
injects ``now`` (``time.monotonic()`` in production, literals here), which is
what makes the debounce contract directly testable.
"""

from sentinel.ui.frame_sync import SyncScheduler


def test_debounce_waits_for_quiet():
    s = SyncScheduler(debounce=0.5)
    s.mark_dirty("tag1", "sig1", now=10.0)
    assert s.due(now=10.3) == []                      # aún en ventana
    assert s.due(now=10.6) == [("tag1", "sig1")]      # ventana cumplida
    assert s.due(now=10.7) == []                      # consumido


def test_new_change_resets_window():
    s = SyncScheduler(debounce=0.5)
    s.mark_dirty("tag1", "sig1", now=10.0)
    s.mark_dirty("tag1", "sig2", now=10.4)            # el drag sigue
    assert s.due(now=10.6) == []                      # reseteado
    assert s.due(now=10.95) == [("tag1", "sig2")]     # solo el último estado


def test_two_tags_independent():
    s = SyncScheduler(debounce=0.5)
    s.mark_dirty("tag1", "a", now=0.0)
    s.mark_dirty("tag2", "b", now=0.4)
    assert s.due(now=0.6) == [("tag1", "a")]          # tag2 aún en ventana
    assert s.due(now=1.0) == [("tag2", "b")]


def test_reentry_guard():
    s = SyncScheduler(debounce=0.5)
    s.begin_sync()
    s.mark_dirty("tag1", "sig2", now=1.0)             # cambio DURANTE el sync (del propio sync)
    assert s.due(now=2.0) == []                       # suprimido por el guard
    s.end_sync()
    s.mark_dirty("tag1", "sig3", now=3.0)
    assert s.due(now=3.6) == [("tag1", "sig3")]


def test_has_pending_reports_scheduler_state():
    s = SyncScheduler(debounce=0.5)
    assert s.has_pending("tag1") is False
    s.mark_dirty("tag1", "sig", now=0.0)
    assert s.has_pending("tag1") is True
    assert s.has_pending("otro") is False
    s.due(now=1.0)
    assert s.has_pending("tag1") is False
