# -*- coding: utf-8 -*-
"""Pure-stdlib web bridge for the Sentinel Reports SPA.

Two independent pieces:

- ``MainThreadQueue``: lets HTTP-server threads hand work to the C4D main
  thread (the only thread allowed to touch the document), which drains the
  queue from a dialog ``Timer``. This is the same generic
  request-queue-drained-by-a-timer shape used by other embedded-webview C4D
  tools, reimplemented here from scratch for Sentinel's own contract.
- ``create_server`` / ``start_server_thread`` / ``stop_server``: a
  ``ThreadingHTTPServer`` that serves the built SPA as static files and
  proxies ``/api/<op>`` requests to a synchronous ``api_handler`` callable.

Stdlib only. NEVER import c4d here: the C4D adapter (dialog host, Timer
wiring, manifest lookups) lives in ``ui/`` — same split as assets.py /
manifest.py / postrender.py.
"""
import http.server
import json
import os
import queue
import threading
import traceback
import urllib.parse

# Pure, c4d-free — safe to import at module scope (see qc/registry.py's own
# docstring: stdlib only, no top-level `import c4d`).
from sentinel.qc.registry import CHECK_REGISTRY

# Content-types for the file kinds the built SPA ships (index.html, JS/CSS
# bundles, source maps, the manifest/report JSON, icons, and the locally
# bundled Inter woff2). Anything else falls back to application/octet-stream.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
}

_API_PREFIX = "/api/"


# ---------------------------------------------------------------------------
# MainThreadQueue
# ---------------------------------------------------------------------------

class _QueuedRequest:
    __slots__ = ("payload", "event", "result")

    def __init__(self, payload):
        self.payload = payload
        self.event = threading.Event()
        self.result = None


class MainThreadQueue:
    """Cross-thread hand-off: server threads call ``submit``, the C4D main
    thread calls ``drain`` from its Timer callback.
    """

    def __init__(self):
        self._queue = queue.Queue()

    def submit(self, payload, timeout=30.0):
        """Called from a server thread. Blocks until the main thread's next
        ``drain`` call processes this payload, or ``timeout`` seconds elapse.

        Returns whatever ``dispatch`` produced — including an error dict if
        dispatch raised (see ``drain``). Raises ``TimeoutError`` only if the
        main thread never drains in time; never raises for dispatch errors.

        Invariant: a timed-out request is NOT removed from the queue — it
        stays there and ``drain`` will still dispatch it on a later Timer
        tick, whenever the main thread gets to it. Its result is computed
        but discarded (nothing is waiting on the Event anymore). This means
        every ``dispatch`` handler (and everything ``api_handler`` calls
        through it) must be safe to run even when nobody is listening
        anymore: read-only or idempotent, no reliance on the caller still
        being there to consume side effects exactly once.
        """
        request = _QueuedRequest(payload)
        self._queue.put(request)
        if not request.event.wait(timeout):
            raise TimeoutError("keep the Reports window open")
        return request.result

    def drain(self, dispatch):
        """Called from the main thread (the Timer). Processes EVERY item
        currently queued, in order — including requests whose ``submit``
        already timed out and returned (see the invariant on ``submit``);
        ``drain`` has no way to know that and dispatches them anyway. Its
        result is then discarded (nothing is waiting on that Event). Keep
        ``dispatch`` read-only/idempotent for this reason. ``dispatch(payload)
        -> dict`` runs once per item; an exception from ``dispatch`` becomes
        the result ``{"error": str(exc), "traceback": <format_exc>}`` instead
        of propagating. This method itself never raises.
        """
        while True:
            try:
                request = self._queue.get_nowait()
            except queue.Empty:
                return

            try:
                request.result = dispatch(request.payload)
            except Exception as exc:
                request.result = {
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            finally:
                request.event.set()


# ---------------------------------------------------------------------------
# Static + /api server
# ---------------------------------------------------------------------------

class _RequestHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):
        # Silence the default stderr access log.
        pass

    def do_GET(self):
        if self._is_api_path():
            self._handle_api()
        else:
            self._handle_static()

    def do_POST(self):
        if self._is_api_path():
            self._handle_api()
        else:
            self._send_json({"error": "not found"}, 404)

    # -- api ---------------------------------------------------------

    def _is_api_path(self):
        return urllib.parse.urlsplit(self.path).path.startswith(_API_PREFIX)

    def _handle_api(self):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            payload = {}

            if self.command == "POST":
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    raw = self.rfile.read(length)
                    if raw:
                        body = json.loads(raw)
                        if isinstance(body, dict):
                            payload.update(body)

            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            for key, values in query.items():
                payload[key] = values[-1] if values else ""

            payload["op"] = parsed.path[len(_API_PREFIX):]

            result = self.server.api_handler(payload)
            self._send_json(result, 200)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _send_json(self, obj, code):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- static --------------------------------------------------------

    def _handle_static(self):
        web_root = self.server.web_root
        path = urllib.parse.urlsplit(self.path).path
        if path in ("", "/"):
            path = "/index.html"

        candidate = os.path.normpath(os.path.join(web_root, path.lstrip("/")))
        if not self._is_inside_root(candidate, web_root) or not os.path.isfile(candidate):
            # Unknown path (not a real file under web_root, and not a
            # traversal hit either) — SPA fallback to index.html.
            candidate = os.path.join(web_root, "index.html")

        if not os.path.isfile(candidate):
            self._send_plain(404, b"Not Found")
            return

        ext = os.path.splitext(candidate)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(candidate, "rb") as f:
            data = f.read()

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _is_inside_root(candidate, root):
        # realpath (not just normpath) so a symlink living inside web_root
        # that points outside it (e.g. web_root/evil -> /etc/passwd) is
        # rejected too — normpath alone only collapses ".."/"." segments in
        # the literal path string, it does not follow symlinks.
        real_candidate = os.path.realpath(candidate)
        real_root = os.path.realpath(root)
        return (real_candidate == real_root
                or real_candidate.startswith(real_root + os.sep))

    def _send_plain(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(web_root, api_handler, host="127.0.0.1", ports=range(8347, 8357)):
    """Bind a ThreadingHTTPServer on the first free port in ``ports``.

    Returns ``(server, port)``. Raises ``OSError`` if every port in
    ``ports`` is already in use.
    """
    web_root = os.path.abspath(web_root)
    last_error = None

    for port in ports:
        try:
            server = http.server.ThreadingHTTPServer((host, port), _RequestHandler)
        except OSError as exc:
            last_error = exc
            continue

        server.web_root = web_root
        server.api_handler = api_handler
        return server, port

    raise OSError(
        f"No free port available in {ports!r} on {host}") from last_error


def start_server_thread(server):
    """Start ``server.serve_forever()`` on a daemon thread and return it."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    server._sentinel_started = True
    thread.start()
    return thread


def stop_server(server):
    """Shut the server down. Safe to call more than once, and safe to call
    even if ``start_server_thread`` was never called for this server (calling
    ``shutdown()`` on a server whose ``serve_forever`` never ran would block
    forever waiting for a loop that will never notice the shutdown flag).
    """
    if getattr(server, "_sentinel_stopped", False):
        return
    server._sentinel_stopped = True
    if getattr(server, "_sentinel_started", False):
        try:
            server.shutdown()
        except Exception:
            pass
    try:
        server.server_close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Delivery report payload — sentinel_manifest.json -> SPA contract
# ---------------------------------------------------------------------------

# source_type values (see manifest.py / textures.py docstrings) that come
# from a material's shader/node graph. rs_object_fileref is deliberately
# NOT here: it is an object-level file reference (dome HDR, light gobo) and
# its ``channel`` is already a human label ("Dome HDR", "Light texture").
_MATERIAL_SOURCE_TYPES = frozenset({
    "rs_node", "arnold_node", "classic_shader", "octane_shader", "bc_param",
})


def _asset_provenance(entry):
    """Human-readable origin for one manifest asset entry, e.g.
    ``"material · Body Shell"`` — built from source_type/channel/host, the
    only fields manifest.py's ``build_asset_entries`` records for this.
    Never raises: every field defaults to "" and missing pieces are simply
    omitted from the joined string.
    """
    source_type = entry.get("source_type") or ""
    channel = entry.get("channel") or ""
    host = entry.get("host") or ""

    if source_type in _MATERIAL_SOURCE_TYPES:
        category = "material"
    elif source_type == "object_bc":
        category = "object"
    elif source_type == "alembic":
        category = "alembic cache"
    elif source_type == "rs_object_fileref":
        # channel is already descriptive here ("Dome HDR", "Light texture").
        category = channel or "object"
    else:
        category = source_type or "asset"

    return f"{category} · {host}" if host else category


def _delivery_asset(entry):
    return {
        "path": entry.get("path") or "",
        "status": entry.get("state") or "",
        "provenance": _asset_provenance(entry),
    }


def _delivery_version(manifest_dict):
    """Format ``original_version`` (an int or None in the manifest, see
    ui/flows.py) as the SPA's "v022"-style string, or None if unknown."""
    raw = manifest_dict.get("original_version")
    if raw is None:
        return None
    try:
        return f"v{int(raw):03d}"
    except (TypeError, ValueError):
        return None


def _delivery_qc(manifest_dict):
    """The manifest only carries a "qc" section when project rules were
    active at collect time (see ui/flows.py) — absent otherwise, never a
    KeyError."""
    qc = manifest_dict.get("qc")
    if not isinstance(qc, dict):
        return None
    return {
        "score": qc.get("score") or "",
        "passed": qc.get("passed", 0),
        "total": qc.get("total", 0),
    }


def _delivery_summary(manifest_dict):
    summary = manifest_dict.get("asset_summary")
    if not isinstance(summary, dict):
        summary = {}
    return {
        "total": summary.get("total", 0),
        "collected": summary.get("collected", 0),
        "missing": summary.get("missing", 0),
        "external": summary.get("external", 0),
    }


def _delivery_zip(manifest_dict):
    """The manifest currently never persists a "zip" section (the zip
    archive is a return value of the collect flow, not written to the
    sidecar — see ui/flows.py run_collect_pipeline). Mapped defensively in
    case a future version adds one."""
    zip_raw = manifest_dict.get("zip")
    if not isinstance(zip_raw, dict):
        return None
    path = zip_raw.get("path") or zip_raw.get("zip_path") or ""
    if not path:
        return None
    return {"path": path, "bytes": zip_raw.get("bytes", 0)}


def delivery_report_payload(manifest_dict, manifest_path):
    """Map a loaded ``sentinel_manifest.json`` dict to the exact SPA
    contract consumed by ``GET /api/report/delivery``
    (web/src/lib/api.ts + web/src/types.ts DeliveryReport).

    Pure: no c4d, no filesystem access — ``manifest_dict`` is whatever
    ``manifest.load_manifest_json`` returned, ``manifest_path`` is the path
    it was loaded from (passed through, not read from the dict). Never
    raises on a partial/legacy manifest — every field falls back to a
    sensible null/empty default instead of a KeyError.
    """
    manifest_dict = manifest_dict or {}
    notes = manifest_dict.get("notes")
    if not isinstance(notes, dict):
        notes = {}
    assets = manifest_dict.get("assets") or []

    return {
        "scene": manifest_dict.get("scene") or "",
        "collected_at": manifest_dict.get("timestamp") or "",
        "artist": manifest_dict.get("artist") or "",
        "version": _delivery_version(manifest_dict),
        "qc": _delivery_qc(manifest_dict),
        "summary": _delivery_summary(manifest_dict),
        "zip": _delivery_zip(manifest_dict),
        "assets": [_delivery_asset(entry) for entry in assets],
        "pending_todos": notes.get("pending_count", 0),
        "manifest_path": manifest_path or "",
    }


# ---------------------------------------------------------------------------
# QC report payload — qc.score.compute_score() -> SPA contract
# ---------------------------------------------------------------------------

# Cap on violation rows per check, same rationale/value as postrender.py's
# REPORT_ITEM_CAP: a runaway check (e.g. hundreds of default-named objects)
# should not blow up the payload — the row's `count` already carries the
# true total, `details` is a preview.
_QC_DETAIL_CAP = 50


def _qc_violation_detail(violation):
    """One structured violation -> the SPA's compact detail row.

    ``violation`` is a qc/results.py ``Violation.to_dict()`` shape:
    ``{"check_id", "identity", "message", "extras"?}`` where ``identity`` is
    always a JSON-safe dict built by ``object_identity``/``material_identity``/
    ``param_identity`` (path+sibling_index+guid, or name+guid, or
    param+value+...) — never a live c4d object reference. Defensive against a
    malformed/non-dict entry (never raises, never drops the row silently).
    """
    if not isinstance(violation, dict):
        return {"label": "", "message": str(violation), "extras": None}
    identity = violation.get("identity") or {}
    label = identity.get("path") or identity.get("name") or identity.get("param") or ""
    return {
        "label": label,
        "message": violation.get("message") or "",
        "extras": violation.get("extras"),
    }


def _qc_check_details(check_id, score, structured_by_check):
    """Violations to show for one check_id, capped at ``_QC_DETAIL_CAP``.

    Mirrors ``ui/dialogs.py`` ``AssetHubDialog._new_violations_for_check``
    exactly: when a baseline sidecar is active, prefer its "new" diff
    (``score["baseline_matches"]``) so accepted violations don't reappear;
    otherwise fall back to the raw structured violations for that check.
    """
    baseline_matches = score.get("baseline_matches")
    if baseline_matches:
        match = baseline_matches.get(check_id) or {}
        violations = match.get("new") or []
    else:
        structured = structured_by_check.get(check_id)
        violations = (structured or {}).get("violations") or []
    return [_qc_violation_detail(v) for v in violations[:_QC_DETAIL_CAP]]


def _qc_check_row(entry, score, structured_by_check, severity_overrides):
    check_id = entry.check_id
    disabled = check_id in (score.get("disabled") or [])
    has_baseline = "new_counts" in score

    if disabled:
        count = new = accepted = None
        status = "disabled"
        details = []
    else:
        count = (score.get("counts") or {}).get(check_id, 0)
        new = (score.get("new_counts") or {}).get(check_id) if has_baseline else None
        accepted = (score.get("accepted_counts") or {}).get(check_id) if has_baseline else None
        status = "ok" if not count else "fail"
        details = _qc_check_details(check_id, score, structured_by_check)

    return {
        "id": check_id,
        "label": entry.row_label,
        "severity": severity_overrides.get(check_id, entry.severity),
        "has_fix": entry.has_fix,
        "status": status,
        "count": count,
        "new": new,
        "accepted": accepted,
        "details": details,
    }


def qc_report_payload(scene_name, ruleset, score, structured_by_check):
    """Map one ``run_all_checks`` + ``compute_score`` run (qc/score.py) to
    the SPA's QcReport contract (``GET/POST /api/report/qc``).

    Pure: no c4d. Callers (see ``ui/reports_dialog.py`` ``_op_report_qc``)
    must gather everything on the C4D main thread first, exactly the way
    ``ui/dialogs.py`` ``AssetHubDialog._refresh_preflight`` /
    ``ui/flows.py`` ``_build_qc_summary`` do — this function never re-derives
    scoring logic, only reshapes its output:

    - ``scene_name``: ``doc.GetDocumentName()`` (or "" for an unsaved doc).
    - ``ruleset``: ``{"name", "path", "shadowed", "severity_overrides"}`` —
      built by the caller from the ``RulesContext`` returned by
      ``rules_context.active_rules_for_doc`` (``rules_path``,
      ``shadowed_paths``, and ``params.get("check_severity", {})`` — see
      ``rules.py`` ``RulesContext`` / ``qc/registry.py`` ``entry_severity``).
      ``name`` is expected to already be a display name (e.g. the rules
      file's basename, or "defaults" when no project ruleset applies).
    - ``score``: the dict ``qc.score.compute_score`` returns, passed through
      unmodified. Already JSON-safe — every violation embedded in it
      (``baseline_matches[...]["new"/"accepted"]``) traces back to
      ``qc/results.py`` ``Violation.to_dict()``, which never stores a live
      c4d object. Legacy shape (no baseline sidecar) has
      score/pass/passed/total/counts/disabled/disabled_count; the baseline
      shape additionally has new_counts/accepted_counts/stale_counts/
      baseline_matches/baseline_status/baseline_path/schema/new/accepted/stale.
    - ``structured_by_check``: ``{check_id: CheckResult-shaped dict or None}``
      — one entry per ``CHECK_REGISTRY`` id, taken verbatim from
      ``run_all_checks``'s ``result_pair["structured_result"]`` (a
      ``CheckResult`` IS a dict — ``{"check_id", "violations", "metadata"}``
      — so this is passed through, never re-derived). ``None`` for a
      disabled check.

    Output (TS-ready — Task 2 mirrors this as ``QcReport``)::

        {
          "scene": str,
          "ruleset": {"name": str, "path": str|None, "shadowed": [str, ...]},
          "score": {"score": "9/12", "passed": int, "total": int,
                    "disabled_count": int, "baseline_status": str|None},
          "checks": [
            {"id": str, "label": str, "severity": "FAIL"|"WARN",
             "has_fix": bool, "status": "ok"|"fail"|"disabled",
             "count": int|None, "new": int|None, "accepted": int|None,
             "details": [{"label": str, "message": str, "extras": dict|None}]}
          ],
          "disabled": [str, ...],
        }

    Never raises on missing/partial input — every field defaults sensibly.
    """
    score = score or {}
    structured_by_check = structured_by_check or {}
    ruleset = ruleset or {}
    severity_overrides = ruleset.get("severity_overrides") or {}

    checks = [
        _qc_check_row(entry, score, structured_by_check, severity_overrides)
        for entry in CHECK_REGISTRY
    ]

    return {
        "scene": scene_name or "",
        "ruleset": {
            "name": ruleset.get("name") or "defaults",
            "path": ruleset.get("path"),
            "shadowed": list(ruleset.get("shadowed") or []),
        },
        "score": {
            "score": score.get("score") or "",
            "passed": score.get("passed", 0),
            "total": score.get("total", 0),
            "disabled_count": score.get("disabled_count", 0),
            "baseline_status": score.get("baseline_status"),
        },
        "checks": checks,
        "disabled": list(score.get("disabled") or []),
    }


# ---------------------------------------------------------------------------
# Doctor report payload — doctor.run_all_diagnostics() -> SPA contract
# ---------------------------------------------------------------------------

def _doctor_item(item):
    item = item or {}
    return {
        "id": item.get("id") or "",
        "label": item.get("label") or "",
        "status": item.get("status") or "info",
        "detail": item.get("detail") or "",
        "hint": item.get("hint") or "",
    }


def doctor_report_payload(items, meta):
    """Map ``doctor.run_all_diagnostics()``'s ``(items, meta)`` to the SPA's
    DoctorReport contract (``GET /api/report/doctor``).

    Pure: no c4d, no filesystem/network access — ``items``/``meta`` are
    whatever the doctor engine already computed. Deliberately NOT nested
    into "sections" (the plan's initial sketch): ``run_all_diagnostics``
    returns one flat item list with no natural grouping in the real engine
    (payload/settings/renderers/python/permissions checks are siblings, not
    categorized) and ``meta`` is a handful of environment strings — inventing
    a grouping here would not be grounded in what doctor.py actually
    produces. The optional, explicit-only ``check_for_update`` item (network
    call, never run automatically — see doctor.py's docstring) is out of
    scope for this read-only report op; ``report/doctor`` only surfaces the
    non-network diagnostics.

    Output (TS-ready — Task 2 mirrors this as ``DoctorReport``)::

        {
          "meta": {"sentinel_version": str, "c4d_version": str, "os": str,
                    "renderers": str, "settings_path": str},
          "items": [{"id": str, "label": str, "status": "ok"|"warn"|"fail"|"info",
                      "detail": str, "hint": str}, ...],
        }

    Never raises on missing/partial input.
    """
    meta = meta or {}
    return {
        "meta": {
            "sentinel_version": meta.get("sentinel_version") or "",
            "c4d_version": meta.get("c4d_version") or "",
            "os": meta.get("os") or "",
            "renderers": meta.get("renderers") or "",
            "settings_path": meta.get("settings_path") or "",
        },
        "items": [_doctor_item(item) for item in (items or [])],
    }


# ---------------------------------------------------------------------------
# Supervisor report payload — supervisor.scan_folder() -> SPA contract
# ---------------------------------------------------------------------------

def _supervisor_shot(shot):
    shot = shot or {}
    return {
        "base": shot.get("base") or "",
        "folder": shot.get("folder") or "",
        "version_count": shot.get("version_count", 0),
        "last_version": shot.get("last_version") or "",
        "status": shot.get("status") or "",
        "score": shot.get("score") or "",
        "qc_label": shot.get("qc_label") or "",
        "todos_total": shot.get("todos_total", 0),
        "todos_pending": shot.get("todos_pending", 0),
        "days_idle": shot.get("days_idle"),
        "last_timestamp": shot.get("last_timestamp") or "",
        "artist": shot.get("artist") or "",
        "flags": list(shot.get("flags") or []),
        "trajectory": list(shot.get("trajectory") or []),
    }


def supervisor_report_payload(shots, meta):
    """Map ``supervisor.scan_folder()``'s ``(shots, meta)`` to the SPA's
    SupervisorReport contract (``GET/POST /api/report/supervisor``).

    Pure: no c4d, no filesystem access — ``supervisor.py`` itself is already
    pure stdlib (it reads sidecars via ``sentinel.versioning``/``sentinel.notes``,
    never opens a ``.c4d``), so every field here is already JSON-safe and is
    reshaped/renamed, never re-derived. Dropped versus the raw shot dict:
    ``history_path`` (an on-disk detail, not report content), ``notes_text``
    and ``version_rows`` (redundant with ``qc_label``/``trajectory`` for a
    report view — Task 2 can reintroduce them from the same source if a page
    needs the detail).

    Output (TS-ready — Task 2 mirrors this as ``SupervisorReport``)::

        {
          "folder": str, "generated_at": str, "shot_count": int,
          "warnings": [str, ...],
          "shots": [
            {"base": str, "folder": str, "version_count": int,
             "last_version": str, "status": str, "score": str,
             "qc_label": str, "todos_total": int, "todos_pending": int,
             "days_idle": int|None, "last_timestamp": str, "artist": str,
             "flags": [str, ...],
             "trajectory": [{"from_version", "to_version", "broke": [str],
                              "recovered": [str], "no_data": bool}, ...]}
          ],
        }

    Never raises on missing/partial input.
    """
    meta = meta or {}
    return {
        "folder": meta.get("folder") or "",
        "generated_at": meta.get("generated") or "",
        "shot_count": meta.get("shot_count", 0),
        "warnings": list(meta.get("warnings") or []),
        "shots": [_supervisor_shot(shot) for shot in (shots or [])],
    }


# ---------------------------------------------------------------------------
# Render validation payload — postrender.build_report() -> SPA contract
# ---------------------------------------------------------------------------

def _render_validation_check(check_id, check):
    check = check or {}
    return {
        "id": check_id,
        "label": check.get("label") or "",
        "status": check.get("status") or "OK",
        "count": check.get("count", 0),
        "items": list(check.get("items") or []),
    }


def render_validation_payload(report, report_path):
    """Map a loaded ``<base>_sentinel_render_report.json`` dict (written by
    ``postrender.build_report`` + ``postrender.write_report_atomic``, see
    ``ui/scene_tools.py`` ``_handle_validate_render``) to the SPA's
    RenderValidationReport contract (``GET /api/report/render_validation``).

    Pure: no c4d, no filesystem access — ``report`` is whatever ``json.load``
    produced from that file, ``report_path`` is passed through (not read
    from the dict, same convention as ``delivery_report_payload``). Never
    raises on a partial/legacy report.

    Output (TS-ready — Task 2 mirrors this as ``RenderValidationReport``)::

        {
          "report_path": str, "generated_at": str, "passed": bool,
          "context": {"take_name": str, "version": str,
                       "frame_start": int|None, "frame_end": int|None,
                       "frame_mode": str},
          "summary": {"failures": int, "warnings": int, "streams": int},
          "checks": [
            {"id": str, "label": str, "status": "OK"|"FAIL"|"WARN",
             "count": int, "items": [dict, ...]}, ...
          ],
        }
    """
    report = report or {}
    context = report.get("context") or {}
    summary = report.get("summary") or {}
    checks = report.get("checks") or {}

    return {
        "report_path": report_path or "",
        "generated_at": report.get("generated_at") or "",
        "passed": bool(report.get("passed", False)),
        "context": {
            "take_name": context.get("take_name") or "",
            "version": context.get("version") or "",
            "frame_start": context.get("frame_start"),
            "frame_end": context.get("frame_end"),
            "frame_mode": context.get("frame_mode") or "",
        },
        "summary": {
            "failures": summary.get("failures", 0),
            "warnings": summary.get("warnings", 0),
            "streams": summary.get("streams", 0),
        },
        "checks": [
            _render_validation_check(check_id, check)
            for check_id, check in checks.items()
        ],
    }
