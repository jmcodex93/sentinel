# -*- coding: utf-8 -*-
"""Dockable host for the Fase 6.0 Panel SPA (``PanelSPADialog`` +
``SentinelPanelSPACmd``) — Task 2 of ``docs/superpowers/plans/
2026-07-21-panel-60-host.md``.

This is a NEW, separate command living alongside the untouched native panel
(``ui/panel.py`` ``YSPanel``/``YSPanelCmd``) — the parallel-panel strategy
the plan's Global Constraints call for. Nothing in ``panel.py`` is touched
here.

Two things had to be copied EXACTLY from existing, proven code rather than
reinvented:

- Dockable + layout-persistent registration: ``SentinelPanelSPACmd`` mirrors
  ``ui/panel.py`` ``YSPanelCmd`` (panel.py:2877-2893) field-for-field —
  ``Execute`` opens via ``dlg.Open(dlgtype=c4d.DLG_TYPE_ASYNC,
  pluginid=..., defaultw, defaulth)``, ``RestoreLayout`` calls
  ``dlg.Restore(pluginid=..., secret=sec_ref)``. This pairing is what makes
  a C4D command dockable and have its layout position/state persisted
  across restarts — a command that only implements ``Execute`` opens fine
  but forgets where it was docked.
- Dialog body: ``PanelSPADialog`` mirrors ``ui/reports_dialog.py``
  ``FormDialog``/``ReportsDialog`` — full-bleed ``CUSTOMGUI_HTMLVIEWER``,
  the same webbrowser fallback notice when the gadget isn't available on
  this platform/build, ``SetTimer(25)`` with ``Timer`` draining the SAME
  module-level ``MainThreadQueue`` those dialogs drain
  (``reports_dialog._queue`` via ``reports_dialog._dispatch``) plus the
  guarded ``pump_jobs()`` call — one queue, one server, for however many
  dialogs (native panel forms, Reports, Hub, and now this panel) are open
  at once; see ``reports_dialog``'s module docstring for why that is safe.
  Server startup goes through ``reports_dialog.ensure_server()`` — same
  lazy singleton, same missing-web-build error contract every other host in
  this codebase relies on.

Unlike ``FormDialog``, this dialog takes no ``page`` parameter: it always
points at the fixed ``?page=panel`` SPA route (the ``PanelPage`` Task 3
builds), so there is exactly one Panel SPA window, not one per page.

The command's own ``self.dlg`` reference IS the GC retention for this
dialog instance (identical to how ``YSPanelCmd`` already works) — no
separate registry is needed the way ``ui/reports_dialog.py``'s
``_open_form_dialogs``/``_open_reports_dialog`` module-level slots are
needed for THOSE call sites (a ``CommandData`` is itself a long-lived
singleton C4D holds onto for the life of the plugin, so its ``dlg``
attribute survives exactly as long as the command does).
"""
import c4d
from c4d import gui, plugins
import webbrowser

from sentinel.common.constants import SENTINEL_PANEL_SPA_PLUGIN_ID
from sentinel.common.helpers import safe_print
from sentinel.ui import reports_dialog

_PANEL_PAGE = "panel"

# Strong reference for open_panel_spa() below — see its docstring and the
# REGRESSION NOTE in ui/reports_dialog.py (module docstring, around
# _open_form_dialogs): a DLG_TYPE_ASYNC dialog whose only Python reference is
# discarded gets garbage-collected out from under its own CreateLayout/Timer
# machinery, producing a blank window. Not used by SentinelPanelSPACmd, which
# already has its own equivalent retention via self.dlg.
_open_panel_spa_dialog = None


class PanelSPADialog(gui.GeDialog):
    """Full-bleed HtmlViewer body pointed at ``?page=panel`` on the shared
    Reports/Forms/Hub localhost server. See the module docstring for why
    this duplicates (rather than reuses) ``FormDialog``'s body: it is the
    same architecture, just fixed to one page and its own class so the
    dockable ``SentinelPanelSPACmd`` above it has an unambiguous, single
    dialog type to hold onto (mirroring ``YSPanelCmd`` holding a plain
    ``YSPanel``, not a parameterized one)."""

    ID_HTML = 3001
    ID_NOTICE = 3002

    def __init__(self):
        super().__init__()
        self._html = None

    def _url(self, port):
        return f"http://127.0.0.1:{port}/?page={_PANEL_PAGE}"

    def CreateLayout(self):
        self.SetTitle("Sentinel Panel")
        self._html = self.AddCustomGui(
            self.ID_HTML, c4d.CUSTOMGUI_HTMLVIEWER, "panel",
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0, c4d.BaseContainer())

        if self._html is None:
            # No HtmlViewer gadget on this platform/build — same degraded
            # path ReportsDialog/FormDialog take: open in the system browser
            # and explain the empty window instead of failing silently.
            try:
                port = reports_dialog.ensure_server()
                url = self._url(port)
                webbrowser.open(url)
                notice = ("HTML viewer is not available in this Cinema 4D "
                           f"build.\nOpened in your default browser instead: {url}")
            except Exception as exc:
                notice = ("HTML viewer is not available in this Cinema 4D "
                           f"build, and the Sentinel server failed to start: {exc}")
            self.AddStaticText(
                self.ID_NOTICE, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0,
                notice, 0)

        # Draining the shared MainThreadQueue on a Timer (not per-request) is
        # what lets the HTTP server thread's blocking submit() calls actually
        # get answered — see reports_dialog.py / webbridge.MainThreadQueue.
        self.SetTimer(25)
        return True

    def InitValues(self):
        if self._html is not None:
            try:
                port = reports_dialog.ensure_server()
            except Exception as exc:
                safe_print(f"Sentinel Panel SPA: server failed to start: {exc}")
                return True
            self._html.SetUrl(self._url(port), c4d.URL_ENCODING_UTF16)
        return True

    def Timer(self, msg):
        if reports_dialog._queue is not None:
            reports_dialog._queue.drain(reports_dialog._dispatch)
        try:
            reports_dialog.pump_jobs()
        except Exception:
            pass  # a job failure is recorded in JOBS; the Timer never raises
        return True

    def DestroyWindow(self):
        # Server/queue are module-level (owned by reports_dialog.py) and
        # outlive this dialog instance — nothing to clean up here.
        pass


class SentinelPanelSPACmd(plugins.CommandData):
    """Registers "Sentinel Panel (SPA)" as its own dockable C4D command,
    living alongside (not replacing) ``YSPanelCmd``. Field-for-field mirror
    of that class — see the module docstring for why this exact shape
    (held ``dlg`` + ``Execute``/``RestoreLayout`` pair) is what makes a
    command dockable and layout-persistent."""

    dlg = None

    def Execute(self, doc):
        if self.dlg is None:
            self.dlg = PanelSPADialog()
            safe_print("Sentinel Panel (SPA) initialized")
        # Pass plugin ID as second argument for layout persistence.
        return self.dlg.Open(dlgtype=c4d.DLG_TYPE_ASYNC,
                              pluginid=SENTINEL_PANEL_SPA_PLUGIN_ID,
                              defaultw=420, defaulth=640)

    def RestoreLayout(self, sec_ref):
        """Required for layout persistence - called when C4D restores layouts."""
        if self.dlg is None:
            self.dlg = PanelSPADialog()
        return self.dlg.Restore(pluginid=SENTINEL_PANEL_SPA_PLUGIN_ID, secret=sec_ref)


def open_panel_spa():
    """Convenience opener mirroring ``ui/reports_dialog.open_form``'s shape
    for any future non-menu call site (e.g. a palette navigate action) —
    NOT used by ``Register()``/``SentinelPanelSPACmd`` itself, which opens
    its own held ``dlg`` directly like ``YSPanelCmd`` does. Kept as a thin,
    standalone function rather than folding into the command class so a
    future caller doesn't have to reach into ``SentinelPanelSPACmd``
    internals to open the same window. Retains a strong reference in the
    module-level ``_open_panel_spa_dialog`` slot (same reasoning as
    ``reports_dialog.open_form``'s registry) so the caller is never required
    to keep its own reference for the dialog to actually render.
    """
    global _open_panel_spa_dialog

    dlg = PanelSPADialog()
    dlg.Open(c4d.DLG_TYPE_ASYNC,
              pluginid=SENTINEL_PANEL_SPA_PLUGIN_ID,
              defaultw=420, defaulth=640)
    _open_panel_spa_dialog = dlg
    return dlg
