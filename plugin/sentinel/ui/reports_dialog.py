# -*- coding: utf-8 -*-
"""C4D adapter for the Sentinel Reports SPA (Task 4 of the UI Foundation plan).

Hosts the built ``plugin/web/`` app in a ``CUSTOMGUI_HTMLVIEWER`` gadget
pointed at a localhost-only server (``plugin/sentinel/webbridge.py``, pure
stdlib, no c4d). This module is the seam where c4d actually gets touched:
starting the server thread, wiring the dialog's Timer to
``MainThreadQueue.drain``, and answering the one API op the SPA currently
calls (``report/delivery``) by reading the active document and the
``sentinel_manifest.json`` next to it.

Architecture note (server/queue lifecycle): both are module-level
singletons, created lazily on the first ``open_reports`` call and shared
across every reopen of the dialog within the same C4D session — the point
being one server/one port for the whole session, not one per dialog open.
They are deliberately NOT stopped from ``ReportsDialog.DestroyWindow``:
closing the window should not kill the server the SPA is still pointed at
if a browser tab (fallback path) is still open. There is also no
``PluginMessage(c4d.C4DPL_ENDACTIVITY)`` hook anywhere in
``sentinel_panel.pyp`` to stop it at plugin shutdown — grepped for one and
found none — so the daemon thread simply dies with the C4D process. That is
an accepted tradeoff (one thread, one localhost socket) rather than a
tracked gap.
"""
import c4d
from c4d import documents, gui
import os
import sys
import webbrowser

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import manifest as manifest_engine
from sentinel.common.helpers import safe_print
from sentinel.webbridge import (
    MainThreadQueue,
    create_server,
    delivery_report_payload,
    start_server_thread,
)

# Web root for the built SPA — ../../web relative to this file
# (plugin/sentinel/ui/reports_dialog.py -> plugin/web), same
# three-``dirname`` pattern panel.py/scene_tools.py use to locate the
# plugin root from __file__.
_WEB_ROOT = os.path.join(_ROOT, "web")

# Lazy module-level singletons — see the lifecycle note in the module
# docstring. None until the first successful ensure_server() call.
_server = None
_queue = None
_port = None

# MessageDialog for a missing web build is shown at most once per session
# (ensure_server can be called on every button click) — the popup would
# otherwise nag on every retry with no new information.
_web_root_warned = False


def ensure_server():
    """Start the Reports server on first call; no-op (returns the existing
    port) on every call after that. Raises on failure — callers (open_reports,
    and transitively the panel button handler) decide how to surface it."""
    global _server, _queue, _port, _web_root_warned

    if _server is not None:
        return _port

    if not os.path.isdir(_WEB_ROOT):
        if not _web_root_warned:
            _web_root_warned = True
            gui.MessageDialog(
                "Sentinel Reports: no build found at\n\n"
                f"{_WEB_ROOT}\n\n"
                "The SPA (plugin/web/) is missing from this install. "
                "Falling back to the legacy Delivery Summary dialog."
            )
        raise RuntimeError(f"Reports web build not found at {_WEB_ROOT}")

    _queue = MainThreadQueue()
    # api_handler is the queue's own submit(): every HTTP request blocks the
    # server thread until the dialog's Timer drains it on the main thread —
    # the cross-thread hand-off webbridge.py documents. No wrapper needed.
    _server, _port = create_server(_WEB_ROOT, _queue.submit)
    start_server_thread(_server)
    safe_print(f"Sentinel Reports server listening on 127.0.0.1:{_port}")
    return _port


def _op_report_delivery(payload):
    """``report/delivery`` — locate sentinel_manifest.json and map it to
    the SPA's DeliveryReport contract. Runs on the C4D main thread (via
    Timer -> MainThreadQueue.drain), so it may safely touch ``c4d``, but
    per the queue's read-only/idempotent invariant it must never open a
    dialog or mutate the document — a timed-out request still gets
    dispatched later with nobody listening for the result.

    Explicit path wins over the active-document lookup: an explicit
    ``?manifest=<path>`` (or ``?path=<path>``, the brief's alternate name)
    query param lets the SPA point at any collected package, not just the
    one next to the currently open scene.
    """
    manifest_path = payload.get("manifest") or payload.get("path")

    if not manifest_path:
        doc = documents.GetActiveDocument()
        doc_path = doc.GetDocumentPath() if doc else ""
        if not doc_path:
            return {"error": "no_manifest"}
        manifest_path = os.path.join(doc_path, "sentinel_manifest.json")

    if not os.path.isfile(manifest_path):
        return {"error": "no_manifest"}

    manifest_dict = manifest_engine.load_manifest_json(manifest_path)
    if manifest_dict is None:
        return {"error": "no_manifest"}

    return delivery_report_payload(manifest_dict, manifest_path)


# op name (as the SPA requests it, "report/delivery") -> handler(payload).
_OPS = {
    "report/delivery": _op_report_delivery,
}


def _dispatch(payload):
    """The queue's dispatch callable — see MainThreadQueue.drain for the
    error-dict-not-raise contract this must honor (satisfied automatically:
    an unhandled exception here is caught by drain() itself)."""
    op = payload.get("op", "")
    handler = _OPS.get(op)
    if handler is None:
        return {"error": f"unknown op: {op!r}"}
    return handler(payload)


class ReportsDialog(gui.GeDialog):
    """Dockable async dialog: an HtmlViewer body pointed at the local
    Reports server. Rewritten from scratch for Sentinel's own contract —
    architecturally informed by (not copied from, license) Overseer's
    dialog host pattern: Timer-driven queue drain, webbrowser fallback when
    the HtmlViewer gadget isn't available on this platform/build.
    """

    ID_HTML = 3001
    ID_NOTICE = 3002

    def __init__(self, port):
        super().__init__()
        self._port = port
        self._html = None

    def CreateLayout(self):
        self.SetTitle("Sentinel Reports")
        self._html = self.AddCustomGui(
            self.ID_HTML, c4d.CUSTOMGUI_HTMLVIEWER, "reports",
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0, c4d.BaseContainer())

        if self._html is None:
            # No HtmlViewer gadget on this platform/build — open the report
            # in the system browser instead and explain the empty window.
            url = f"http://127.0.0.1:{self._port}/"
            webbrowser.open(url)
            self.AddStaticText(
                self.ID_NOTICE, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0,
                "HTML viewer is not available in this Cinema 4D build.\n"
                f"Opened in your default browser instead: {url}", 0)

        # Draining the queue on a Timer (not per-request) is what lets the
        # HTTP server thread's blocking submit() calls actually get
        # answered — see MainThreadQueue in webbridge.py.
        self.SetTimer(25)
        return True

    def InitValues(self):
        if self._html is not None:
            self._html.SetUrl(f"http://127.0.0.1:{self._port}/",
                               c4d.URL_ENCODING_UTF16)
        return True

    def Timer(self, msg):
        if _queue is not None:
            _queue.drain(_dispatch)
        return True

    def DestroyWindow(self):
        # Server/queue are module-level and outlive this dialog instance —
        # see the lifecycle note in the module docstring. Nothing to clean
        # up here.
        pass


def open_reports(doc):
    """Ensure the Reports server is running and open the dialog.

    ``doc`` is accepted (not read here) for call-site symmetry with the
    panel's other dialog openers (``_open_asset_hub(doc)``) and so a future
    op that needs doc-open-time context has somewhere to plug in; the
    ``report/delivery`` op itself re-reads ``GetActiveDocument()`` at
    dispatch time instead of capturing ``doc`` now, since dispatch runs
    later (on a Timer tick, possibly after the user switched documents) and
    should reflect whichever document is active *then*.

    Raises on failure (missing web build, or a server bind failure such as
    every port in range being busy) — the panel's button handler catches
    this and falls back to the legacy text-dialog Delivery Summary.
    """
    port = ensure_server()
    dlg = ReportsDialog(port)
    dlg.Open(c4d.DLG_TYPE_ASYNC, defaultw=1080, defaulth=760)
    return dlg
