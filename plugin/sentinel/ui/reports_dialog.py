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

Op inventory (Phase 2 Task 1 adds report/qc, report/doctor,
report/supervisor, report/render_validation alongside report/delivery;
Phase 4 Task 2 adds the form/* + palette/* ops, implemented in the sibling
``ui/web_ops.py`` and merged into ``_OPS`` below — split out once this
file's op count grew past the ~600 line guideline). Every op is dispatched
from ``MainThreadQueue.drain`` — see its docstring for the mutation-safe
invariant every handler below must honor: post-commit 69d7a7a a handler MAY
mutate the document (a client-abandoned/timed-out request is guaranteed
never dispatched late), but must still tolerate the client retrying the
same mutation after its own timeout.
"""
import c4d
from c4d import documents, gui
import json
import os
import sys
import urllib.parse
import webbrowser

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import doctor
from sentinel import manifest as manifest_engine
from sentinel import postrender
from sentinel import supervisor
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.qc.score import compute_score, run_all_checks
from sentinel.rules_context import active_rules_for_doc
from sentinel.ui.hub_ops import HUB_OPS, pump_jobs
from sentinel.ui.web_ops import FORM_OPS
from sentinel import webbridge
from sentinel.webbridge import (
    MainThreadQueue,
    create_server,
    delivery_report_payload,
    doctor_report_payload,
    qc_report_payload,
    render_validation_payload,
    start_server_thread,
    supervisor_report_payload,
)

# Same key ui/dialogs.py's SupervisorDialog persists the last-scanned folder
# under (GlobalSettings-backed, machine-local — see CLAUDE.md "Saved Per
# Computer/User"). Shared literal, not imported from dialogs.py, to avoid
# pulling that module's whole (2800+ line) import chain into the report
# server for one string constant.
_SUPERVISOR_LAST_FOLDER_KEY = "supervisor_last_folder"

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

# Strong references to every currently-open ReportsDialog/FormDialog
# instance, keyed by page ("palette" -> its FormDialog; a single slot for
# ReportsDialog since it is one deep-linkable window regardless of page —
# see open_reports). REGRESSION NOTE: c4d.gui.GeDialog.Open(DLG_TYPE_ASYNC)
# does NOT itself keep the Python object alive — C4D owns the native window
# shell, but the Python-side GeDialog instance is ordinary Python garbage
# once nothing references it. A caller that does `open_form(doc, "palette")`
# and discards the return (as SentinelPaletteCmd.Execute originally did)
# gets a BLANK window: the object is collected before/while CreateLayout's
# HtmlViewer + Timer machinery would otherwise keep driving it, so the
# shell never navigates or drains the queue. Same class of bug this project
# hit earlier with the Asset Hub dialog. Fixing it HERE (the single place
# every caller funnels through) means no call site — panel button, palette
# navigate action, CommandData shortcut, any future one — has to remember
# to keep its own reference; open_form/open_reports are the one owner.
_open_form_dialogs = {}
_open_reports_dialog = None

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
                "Falling back to the legacy native dialog."
            )
        raise RuntimeError(f"Reports web build not found at {_WEB_ROOT}")

    _queue = MainThreadQueue()
    # api_handler is _api_entry, not the queue's submit() directly: every op
    # except hub/job_status still blocks the server thread until the
    # dialog's Timer drains it on the main thread (the cross-thread hand-off
    # webbridge.py documents) — hub/job_status is the one op answered right
    # here on the server thread, see _api_entry's own docstring for why.
    _server, _port = create_server(_WEB_ROOT, _api_entry)
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


def _op_report_qc(payload):
    """``report/qc`` — run the 12 QC checks on the active document and map
    the result to the SPA's QcReport contract.

    Runs QC exactly the way ``ui/dialogs.py`` ``AssetHubDialog._refresh_preflight``
    does (its own docstring names this as the source of truth: "Re-run QC +
    score the same way `collect_scene` does"): ``active_rules_for_doc`` ->
    ``run_all_checks`` -> ``compute_score``, with the baseline kwargs added
    only when a baseline sidecar already exists on disk. ``_baseline_path_for_doc``
    and ``_current_module`` are private to ``ui.flows`` and imported locally
    here for the exact same reason ``ui/dialogs.py`` does it locally: avoids
    a module-load-time cycle (``ui.flows`` imports ``ui.dialogs`` at module
    scope for ``GateTriageDialog``). No dialog is opened and nothing is
    mutated — read-only, satisfies the MainThreadQueue invariant.
    """
    from sentinel.ui.flows import _baseline_path_for_doc, _current_module

    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    rules_context = active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    score_kwargs = {"baseline_path": baseline_path,
                     "current_params": rules_context.params} if baseline_path else {}
    score = compute_score(registry_results, rules_context, **score_kwargs)

    structured_by_check = {
        check_id: pair.get("structured_result")
        for check_id, pair in registry_results.items()
    }
    ruleset = {
        "name": (os.path.basename(rules_context.rules_path)
                 if rules_context.rules_path else "defaults"),
        "path": rules_context.rules_path,
        "shadowed": list(rules_context.shadowed_paths or []),
        "severity_overrides": (rules_context.params or {}).get("check_severity", {}),
    }
    scene_name = doc.GetDocumentName() or "Untitled"

    return qc_report_payload(scene_name, ruleset, score, structured_by_check)


def _op_report_doctor(payload):
    """``report/doctor`` — run Sentinel Doctor's non-network diagnostics and
    map them to the SPA's DoctorReport contract.

    Only ``run_all_diagnostics()`` — the explicit, opt-in ``check_for_update``
    (network call, see doctor.py's own docstring: "invoked only on explicit
    user action") is deliberately NOT run here, keeping this op fast and
    fully read-only/idempotent like every other MainThreadQueue dispatch.
    """
    items, meta = doctor.run_all_diagnostics()
    return doctor_report_payload(items, meta)


def _op_report_supervisor(payload):
    """``report/supervisor`` — scan a project folder's version/notes
    sidecars (no ``.c4d`` ever opened) and map the result to the SPA's
    SupervisorReport contract.

    Folder resolution: an explicit ``payload["folder"]`` wins, else the last
    folder scanned from the native Supervisor dialog (or a previous SPA
    scan) — ``GlobalSettings`` key ``supervisor_last_folder``, the same one
    ``ui/dialogs.py`` ``SupervisorDialog`` reads/writes. No folder resolved
    at all -> ``{"error": "no_folder"}``.

    Persisting the folder back to settings on every explicit scan is an
    idempotent write (same folder in -> same value stored, repeatable any
    number of times including a re-dispatch of a timed-out request) so it
    is allowed under the MainThreadQueue invariant even though it is
    technically a write — it only ever mirrors ``payload["folder"]``, never
    derives new state.

    Timing note: this walks the folder tree for every ``*_history.json``
    (depth-capped at 6, see ``supervisor.MAX_WALK_DEPTH``) and reads each
    sidecar's small JSON — cheap for a normal shot count, but on a very
    large/deep project tree this read-only I/O runs synchronously on the
    C4D main thread (via the Timer -> ``MainThreadQueue.drain`` hand-off)
    like every other op; there is no background/async scan here.
    """
    folder = payload.get("folder") or GlobalSettings.get(_SUPERVISOR_LAST_FOLDER_KEY, "")
    if not folder:
        return {"error": "no_folder"}

    if payload.get("folder"):
        GlobalSettings.set(_SUPERVISOR_LAST_FOLDER_KEY, folder)

    shots, meta = supervisor.scan_folder(folder)
    return supervisor_report_payload(shots, meta)


def _op_report_render_validation(payload):
    """``report/render_validation`` — locate and load the last saved render
    validation report for the active document and map it to the SPA's
    RenderValidationReport contract.

    The report path is deterministic from the saved document path alone
    (``postrender.report_path_for_doc``: ``<scene_folder>/<base>_sentinel_render_report.json``,
    version/status-stripped — it does NOT depend on which render-output
    folder was audited), so no dialog or folder picker is needed here. An
    unsaved document, or a saved one that has never run "Validate Render
    Output..." (``ui/scene_tools.py`` ``_handle_validate_render``), has no
    deterministic report path/file yet -> ``{"error": "no_report"}``, same
    as ``report/delivery``'s ``no_manifest``.
    """
    doc = documents.GetActiveDocument()
    doc_path = doc.GetDocumentPath() if doc else ""
    doc_name = doc.GetDocumentName() if doc else ""
    if not doc or not doc_path or not doc_name:
        return {"error": "no_report"}

    doc_full_path = os.path.join(doc_path, doc_name)
    report_path = postrender.report_path_for_doc(doc_full_path, "")
    if not report_path or not os.path.isfile(report_path):
        return {"error": "no_report"}

    try:
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except Exception:
        return {"error": "no_report"}

    return render_validation_payload(report, report_path)


# op name (as the SPA requests it, e.g. "report/delivery") -> handler(payload).
# form/* and palette/* ops are defined in the sibling ui/web_ops.py (FORM_OPS)
# and merged in here so the server still has a single op table.
_OPS = {
    "report/delivery": _op_report_delivery,
    "report/qc": _op_report_qc,
    "report/doctor": _op_report_doctor,
    "report/supervisor": _op_report_supervisor,
    "report/render_validation": _op_report_render_validation,
    **FORM_OPS,
    **HUB_OPS,
}


def _api_entry(payload):
    """Server-thread entry point passed to ``create_server`` in place of
    ``_queue.submit`` directly. ``hub/job_status`` is answered right here,
    NOT via the ``MainThreadQueue``: a Collect job (``hub/collect_start`` +
    ``hub_ops.pump_jobs``) runs synchronously on the main thread and blocks
    it for the duration, which also blocks the Timer that would otherwise
    drain the queue — a queued ``hub/job_status`` request would simply never
    get answered until the job finishes, defeating the whole point of
    polling for live progress. ``webbridge.JOBS`` is its own
    thread-safe registry (see its docstring) built exactly for this: safe to
    read from the server thread while the main thread is busy. Every other
    op still goes through the queue.
    """
    if payload.get("op") == "hub/job_status":
        return webbridge.JOBS.status(payload.get("job_id") or "")
    return _queue.submit(payload)


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

    def __init__(self, port, page=None):
        super().__init__()
        self._port = port
        # Deep-link into a specific SPA page (e.g. "doctor", "qc") via a
        # `?page=` query param the SPA reads once at mount (web/src/App.tsx
        # initialPage()) — None keeps the SPA's own default (Delivery).
        self._page = page
        self._html = None

    def _url(self):
        base = f"http://127.0.0.1:{self._port}/"
        return f"{base}?page={self._page}" if self._page else base

    def CreateLayout(self):
        self.SetTitle("Sentinel Reports")
        self._html = self.AddCustomGui(
            self.ID_HTML, c4d.CUSTOMGUI_HTMLVIEWER, "reports",
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0, c4d.BaseContainer())

        if self._html is None:
            # No HtmlViewer gadget on this platform/build — open the report
            # in the system browser instead and explain the empty window.
            url = self._url()
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
            self._html.SetUrl(self._url(), c4d.URL_ENCODING_UTF16)
        return True

    def Timer(self, msg):
        if _queue is not None:
            _queue.drain(_dispatch)
        try:
            pump_jobs()
        except Exception:
            pass  # a job failure is recorded in JOBS; the Timer never raises
        return True

    def DestroyWindow(self):
        # Server/queue are module-level and outlive this dialog instance —
        # see the lifecycle note in the module docstring. Nothing to clean
        # up here.
        pass


# Per-page default window size for FormDialog (Phase 4 Task 4) — sized to
# fit each form comfortably without scrolling on a typical desktop; the
# artist can still resize like any other C4D async dialog. "palette" isn't
# a form/* op page (no state/submit ops of its own — see web_ops.py
# palette/actions + palette/run) but shares the same host/sizing table
# since it is also opened via ``open_form``.
_FORM_SIZES = {
    "form/save_version": (520, 480),
    "form/notes": (560, 620),
    "form/settings": (560, 560),
    "form/gate": (640, 600),
    "palette": (560, 420),
    "hub": (1120, 700),
}

_FORM_TITLES = {
    "form/save_version": "Sentinel — Save Version",
    "form/notes": "Sentinel — Notes",
    "form/settings": "Sentinel — Settings",
    "form/gate": "Sentinel — Quality Gate",
    "palette": "Sentinel — Command Palette",
    "hub": "Sentinel — Asset Hub",
}


class FormDialog(gui.GeDialog):
    """Dockable async dialog hosting one SPA form/* page (or the command
    palette) in its own right-sized window — the Task 4 counterpart to
    ``ReportsDialog`` above. Same architecture, deliberately duplicated
    rather than parameterized into one class: ``ReportsDialog`` always
    lands on the Sidebar-driven Reports shell (``ReportsApp`` in
    App.tsx) with a fixed 1080x760 size, while a form page is
    full-bleed/no-sidebar (``FormApp``) and each page has its own natural
    size — the two host different SPA shells, not just different
    ``?page=`` values, so sharing one class would need a
    ``has_sidebar``-style branch for no real benefit at this size.

    Server/queue lifecycle, HtmlViewer/browser fallback, and the
    Timer-driven ``MainThreadQueue.drain`` are identical to
    ``ReportsDialog`` — see its docstring. Multiple ``FormDialog``/
    ``ReportsDialog`` instances (e.g. the panel's Save Version form open
    at the same time as a Reports QC page, or two form windows opened
    back to back) safely share the one module-level ``_queue``: each
    instance's own ``Timer`` calls ``_queue.drain(_dispatch)``, and
    ``MainThreadQueue.drain`` is a plain ``queue.Queue.get_nowait()`` loop
    that always runs on the single C4D main thread (Timer callbacks are
    never concurrent with each other) — whichever dialog's Timer fires
    first simply drains every currently-queued request, including ones
    submitted by a different dialog's HTTP request; the result is routed
    back to the right waiting HTTP thread via that request's own
    threading.Event, not by which dialog drained it. So N open dialogs
    draining one queue is equivalent to 1 dialog draining it N times as
    often — never a double-dispatch, never a starved request.
    """

    ID_HTML = 3001
    ID_NOTICE = 3002

    def __init__(self, port, page, title=None, query=None):
        super().__init__()
        self._port = port
        self._page = page
        self._title = title or _FORM_TITLES.get(page, "Sentinel")
        self._html = None
        # Extra deep-link params appended to the URL beyond `?page=` (e.g.
        # `{"focus": "deliver"}` -> `&focus=deliver`) — see _url().
        self._query = query or {}

    def _url(self):
        url = f"http://127.0.0.1:{self._port}/?page={self._page}"
        for key, value in sorted(self._query.items()):
            url += "&%s=%s" % (key, urllib.parse.quote(str(value)))
        return url

    def CreateLayout(self):
        self.SetTitle(self._title)
        self._html = self.AddCustomGui(
            self.ID_HTML, c4d.CUSTOMGUI_HTMLVIEWER, "form",
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0, c4d.BaseContainer())

        if self._html is None:
            # No HtmlViewer gadget on this platform/build — open the form
            # in the system browser instead and explain the empty window
            # (same degraded path ReportsDialog takes).
            url = self._url()
            webbrowser.open(url)
            self.AddStaticText(
                self.ID_NOTICE, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0,
                "HTML viewer is not available in this Cinema 4D build.\n"
                f"Opened in your default browser instead: {url}", 0)

        self.SetTimer(25)
        return True

    def InitValues(self):
        if self._html is not None:
            self._html.SetUrl(self._url(), c4d.URL_ENCODING_UTF16)
        return True

    def Timer(self, msg):
        if _queue is not None:
            _queue.drain(_dispatch)
        try:
            pump_jobs()
        except Exception:
            pass  # a job failure is recorded in JOBS; the Timer never raises
        return True

    def DestroyWindow(self):
        # Server/queue are module-level and outlive this dialog instance —
        # see the lifecycle note in the module docstring. Nothing to clean
        # up here.
        pass


def open_form(doc, page, defaultw=None, defaulth=None, query=None):
    """Ensure the Reports/Forms server is running and open ``page`` (one of
    ``form/save_version``, ``form/notes``, ``form/settings``, ``form/gate``,
    or ``palette``) in its own right-sized ``FormDialog`` window.

    ``doc`` is accepted for call-site symmetry with ``open_reports`` (see
    its docstring) — every op re-reads ``GetActiveDocument()`` at dispatch
    time instead of capturing ``doc`` now.

    ``defaultw``/``defaulth`` override the per-page size table
    (``_FORM_SIZES``) when given; omit them to use the table's default for
    ``page`` (falling back to 560x480 for an unrecognized page — should not
    happen with the callers in this codebase, but keeps this function total
    rather than raising a KeyError on a typo).

    Raises on failure (missing web build, or a server bind failure) exactly
    like ``open_reports`` — callers catch this and fall back to the native
    modal dialog + engine call the page replaces (``SaveVersionDialog`` +
    ``smart_save_version``, ``NotesDialog``, ``SentinelSettingsDialog``;
    there is no native equivalent for ``palette``, so its caller's fallback
    is just an error message).

    Retains a strong reference to the returned dialog in the module-level
    ``_open_form_dialogs`` registry (keyed by ``page``), closing any
    previous still-open instance of the SAME page first — see the registry
    note above ``_open_form_dialogs`` for why this is not optional
    bookkeeping: without it, a caller that doesn't keep its own reference
    (e.g. a ``CommandData.Execute`` that just calls ``open_form(doc, page)``
    for its side effect) gets a dialog that C4D shows as an empty/blank
    window because Python garbage-collects the only object actually driving
    it. Callers MAY still keep their own reference too (harmless — both just
    point at the same object), but no caller is REQUIRED to for the dialog
    to work correctly.

    ``query`` is an optional dict of extra deep-link params appended to the
    URL beyond ``?page=`` (e.g. ``{"focus": "deliver"}`` -> the SPA sees
    ``?page=hub&focus=deliver``) — passed straight through to ``FormDialog``.
    """
    port = ensure_server()
    table_w, table_h = _FORM_SIZES.get(page, (560, 480))

    existing = _open_form_dialogs.get(page)
    if existing is not None:
        try:
            if existing.IsOpen():
                existing.Close()
        except Exception:
            pass

    dlg = FormDialog(port, page, query=query)
    dlg.Open(c4d.DLG_TYPE_ASYNC,
              defaultw=defaultw or table_w, defaulth=defaulth or table_h)
    _open_form_dialogs[page] = dlg
    return dlg


def open_reports(doc, page=None):
    """Ensure the Reports server is running and open the dialog.

    ``doc`` is accepted (not read here) for call-site symmetry with the
    panel's other dialog openers (``_open_asset_hub(doc)``) and so a future
    op that needs doc-open-time context has somewhere to plug in; the
    ``report/delivery`` op itself re-reads ``GetActiveDocument()`` at
    dispatch time instead of capturing ``doc`` now, since dispatch runs
    later (on a Timer tick, possibly after the user switched documents) and
    should reflect whichever document is active *then*.

    ``page`` optionally deep-links straight to one of the SPA's pages
    ("qc", "doctor", "supervisor", "render") instead of its default
    Delivery Summary landing page — see ``ReportsDialog._url``.

    Raises on failure (missing web build, or a server bind failure such as
    every port in range being busy) — the panel's button handler catches
    this and falls back to a legacy native dialog.

    Retains a strong reference to the returned dialog in the module-level
    ``_open_reports_dialog`` slot (one slot, not keyed by ``page`` — Reports
    is a single deep-linkable window, unlike the per-page ``FormDialog``
    registry), closing any previous still-open Reports window first. Same
    reasoning as ``open_form``'s registry: ``ui/web_ops.py``
    ``_palette_open_reports`` calls this and discards the return (it only
    needs the side effect), which used to mean the palette's "Open Reports
    · ..." actions could hand back a blank window once nothing else kept
    the object alive. The panel's own ``self._reports`` bookkeeping in
    ``_open_reports`` is redundant with this now (both just reference the
    same object) but harmless, so it is left as-is rather than churned.
    """
    global _open_reports_dialog

    port = ensure_server()

    existing = _open_reports_dialog
    if existing is not None:
        try:
            if existing.IsOpen():
                existing.Close()
        except Exception:
            pass

    dlg = ReportsDialog(port, page=page)
    dlg.Open(c4d.DLG_TYPE_ASYNC, defaultw=1080, defaulth=760)
    _open_reports_dialog = dlg
    return dlg
