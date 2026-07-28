# -*- coding: utf-8 -*-
"""Frame v2 auto-sync: the tag is the source of truth; Takes always mirror it.

``SyncScheduler`` is PURE (injectable clock — it never reads time itself; the
caller passes ``now``). ``FrameSyncMessageData`` is the c4d host: it receives
the ``SpecialEventAdd`` ping / its own 250 ms timer tick, polls the scheduler,
and runs the take regeneration ON MAIN THREAD outside any parameter message.
NEVER a MessageDialog here — a dialog inside a message handler freezes C4D
(same rule as the panel ops' ``_forbid_dialog`` contract); failures go to
``safe_print`` plus a per-tag failure flag the AM status line can read.

Threading contract (spec §2): the tag's ``MSG_DESCRIPTION_POSTSETPARAMETER``
only calls :func:`request_sync` (cheap: signature + timestamp); the actual
regeneration runs from the MessageData tick after the debounce window closes,
never inside the parameter message, never from Draw/Execute.
"""

DEBOUNCE_SECONDS = 0.5
PLUGIN_ID = 2099077
EVENT_ID = 2099077


class SyncScheduler(object):
    """Pure per-tag debounce: the LAST signature marked within the window wins.

    Keys are opaque tag identities (GUID strings in production). ``begin_sync``
    / ``end_sync`` guard re-entry: parameter writes made BY the running sync
    (take links, saved signature) must not re-trigger it.
    """

    def __init__(self, debounce=DEBOUNCE_SECONDS):
        self._debounce = float(debounce)
        self._pending = {}          # key (tag id) -> (sig, deadline)
        self._in_sync = False

    def mark_dirty(self, key, sig, now):
        if self._in_sync:
            return
        self._pending[key] = (sig, float(now) + self._debounce)

    def begin_sync(self):
        self._in_sync = True

    def end_sync(self):
        self._in_sync = False

    def has_pending(self, key):
        # Forward interface for the AM's sync-status line (Task 4 reads it to
        # show "⟳ syncing…" while a debounce window is open) — no production
        # caller in Task 3 yet.
        return key in self._pending

    def due(self, now):
        out = []
        for key, (sig, deadline) in list(self._pending.items()):
            if float(now) >= deadline:
                out.append((key, sig))
                del self._pending[key]
        return out


# --- c4d host ---------------------------------------------------------------
# Guarded so the pure scheduler above stays importable under pytest without a
# Cinema 4D runtime (same pattern as the other sentinel modules).
try:  # pragma: no cover - exercised only inside C4D
    import c4d
    from c4d import plugins as _c4d_plugins
except ImportError:  # pragma: no cover
    c4d = None
    _c4d_plugins = None

try:
    from sentinel.common.helpers import safe_print
except ImportError:  # pragma: no cover
    def safe_print(msg):
        print(msg)


#: Module-level singleton the tag's Message hook and the MessageData share.
scheduler = SyncScheduler()

#: key (GUID string) -> last sync outcome, for the AM status line
#: ("ok" | "failed"). Session-only; absence means "never synced this session".
last_sync_result = {}


def _tag_key(tag):
    """Stable per-tag identity. BaseTag has NO GetGUID() (that's BaseObject
    API — live-caught bug: the old str(tag.GetGUID()) raised, returned None
    and silently disabled the whole auto-sync). FindUniqueID(MAXON_CREATOR_ID)
    is the BaseList2D-level unique id, present on tags."""
    try:
        uid = tag.FindUniqueID(c4d.MAXON_CREATOR_ID)
        if uid:
            return bytes(uid).hex()
    except Exception:
        pass
    return None


def request_sync(tag):
    """Mark ``tag`` dirty (debounced) and ping the MessageData host.

    Called from the tag's ``MSG_DESCRIPTION_POSTSETPARAMETER`` — must stay
    cheap and free of document mutation.
    """
    if c4d is None:
        return
    key = _tag_key(tag)
    if not key:
        return
    import time
    try:
        from sentinel.ui.frame_tag import _params_signature_for_takes
        sig = _params_signature_for_takes(tag)
    except Exception:
        sig = ""
    scheduler.mark_dirty(key, sig, now=time.monotonic())
    try:
        c4d.SpecialEventAdd(EVENT_ID)
    except Exception:
        pass


def _find_tag_by_guid(doc, key):
    """Resolve a pending tag GUID against the live document (deleted → None)."""
    from sentinel.ui.frame_tag import SENTINEL_FRAME_TAG_PLUGIN_ID

    def _walk(obj):
        while obj:
            tag = obj.GetFirstTag()
            while tag:
                if tag.GetType() == SENTINEL_FRAME_TAG_PLUGIN_ID and _tag_key(tag) == key:
                    return tag
                tag = tag.GetNext()
            child = obj.GetDown()
            if child:
                found = _walk(child)
                if found is not None:
                    return found
            obj = obj.GetNext()
        return None

    try:
        return _walk(doc.GetFirstObject())
    except Exception:
        return None


def _drain(now):
    """Run every due sync. Called from the MessageData on main thread only."""
    entries = scheduler.due(now)
    if not entries:
        return
    doc = c4d.documents.GetActiveDocument()
    if doc is None:
        return
    from sentinel.ui.frame_tag import run_full_sync, _force_viewport_refresh

    ran_any = False
    for key, _sig in entries:
        tag = _find_tag_by_guid(doc, key)
        if tag is None:
            last_sync_result.pop(key, None)  # deleted mid-window: drop silently
            continue
        scheduler.begin_sync()
        try:
            result = run_full_sync(doc, tag)
            ran_any = True
            last_sync_result[key] = "ok" if result.get("ok") else "failed"
            if not result.get("ok"):
                safe_print("Sentinel Frame auto-sync failed: %s" % result.get("error"))
        except Exception as exc:
            last_sync_result[key] = "failed"
            safe_print("Sentinel Frame auto-sync crashed: %s" % exc)
        finally:
            scheduler.end_sync()
    if ran_any:
        # A sync can rewrite the CURRENTLY-VIEWED take's overrides (nudging a
        # format while viewing it) — the editor won't re-derive the camera
        # projection on its own (same lazy-viewport gap as _activate_viewing).
        _force_viewport_refresh()


if _c4d_plugins is not None:

    class FrameSyncMessageData(_c4d_plugins.MessageData):
        """Main-thread pump for the debounced Frame auto-sync."""

        def GetTimer(self):
            # Coarse tick; the real cadence is the scheduler's debounce window.
            return 250

        def CoreMessage(self, mid, bc):
            timer_id = getattr(c4d, "MSG_TIMER", None)
            if mid == EVENT_ID or (timer_id is not None and mid == timer_id):
                import time
                try:
                    _drain(time.monotonic())
                except Exception as exc:  # never let the pump die
                    safe_print("Sentinel Frame sync pump error: %s" % exc)
            return True

else:  # pragma: no cover
    FrameSyncMessageData = None
