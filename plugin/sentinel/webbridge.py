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
import hashlib
import http.server
import itertools
import json
import os
import queue
import threading
import traceback
import urllib.parse

# Pure, c4d-free — safe to import at module scope (see qc/registry.py's own
# docstring: stdlib only, no top-level `import c4d`). notes.py/versioning.py
# are equally c4d-free (verified: neither imports c4d, directly or via their
# own imports — see the Phase 4 Task 2 grounding pass).
from sentinel.notes import add_todo, toggle_todo
from sentinel.qc.registry import CHECK_REGISTRY
from sentinel.versioning import STATUS_OPTIONS, _sanitize_status
from . import assets as _assets  # pure stdlib module — safe here

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
_THUMB_PATH = "/thumb"


# ---------------------------------------------------------------------------
# MainThreadQueue
# ---------------------------------------------------------------------------

class _QueuedRequest:
    __slots__ = ("payload", "event", "result", "cancelled", "lock")

    def __init__(self, payload):
        self.payload = payload
        self.event = threading.Event()
        self.result = None
        self.cancelled = False
        # Guards the cancelled-check + dispatch-commit in `drain` against a
        # concurrent cancel attempt in `submit` — see both docstrings.
        self.lock = threading.Lock()


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
        main thread never drains it in time AND the cancel below succeeds;
        never raises for dispatch errors.

        Invariant (mutation-safe): on timeout, this atomically marks the
        request cancelled *before* raising ``TimeoutError`` — a
        client-abandoned request never executes late. The mark-vs-dispatch
        race against a concurrent ``drain`` is closed by ``request.lock``:
        ``drain`` holds that same lock for the cancelled-check AND the
        dispatch call as one unit, so exactly one of two outcomes happens,
        never a third "half-dispatched" one:

        - We acquire the lock first (drain hasn't reached this request
          yet): we set ``cancelled`` and raise ``TimeoutError``; ``drain``
          later sees ``cancelled`` and skips the request — it never runs.
        - ``drain`` acquired the lock first (dispatch already committed or
          in flight): our lock acquisition blocks until dispatch finishes,
          then we see ``event`` is set and return the real result instead
          of raising — it ran before/around the timeout, not after.

        Every ``dispatch`` handler (and everything ``api_handler`` calls
        through it) must still tolerate a client retry (the client may
        resubmit the same mutation after a timeout it never blocks late).
        """
        request = _QueuedRequest(payload)
        self._queue.put(request)
        if request.event.wait(timeout):
            return request.result

        with request.lock:
            if request.event.is_set():
                # drain() had already committed to dispatching this request
                # (or just finished) by the time we got the lock — it ran,
                # return its real result instead of a stale TimeoutError.
                return request.result
            request.cancelled = True
        raise TimeoutError("keep the Reports window open")

    def drain(self, dispatch):
        """Called from the main thread (the Timer). Processes EVERY item
        currently queued, in order, EXCEPT requests cancelled by a timed-out
        ``submit`` (see its docstring) — those are skipped: ``dispatch`` is
        never called for them and there is no result to discard (the queue
        no longer holds anything for a cancelled request beyond the flag).

        Mutations are safe to dispatch here now: a client that gave up
        waiting can never have its request execute later. Handlers still
        must tolerate the client retrying the same mutation after its own
        timeout (a fresh ``submit`` call is a brand new, undispatched
        request — cancellation does not deduplicate retries).

        ``dispatch(payload) -> dict`` runs once per non-cancelled item; an
        exception from ``dispatch`` becomes the result
        ``{"error": str(exc), "traceback": <format_exc>}`` instead of
        propagating. This method itself never raises.
        """
        while True:
            try:
                request = self._queue.get_nowait()
            except queue.Empty:
                return

            with request.lock:
                if request.cancelled:
                    continue

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
# JobRegistry
# ---------------------------------------------------------------------------

class JobRegistry:
    """Single-slot background-job registry for the Hub collect.

    Pure stdlib, thread-safe. ``status()`` is answered on the HTTP server
    thread (bypassing MainThreadQueue) so progress polling stays live while
    the job itself blocks C4D's main thread. One job at a time: the Hub
    collect is exclusive by design.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._job = None  # {"job_id", "spec", "state", "phase", "detail", "pct", "result", "error"}

    def start(self, spec):
        with self._lock:
            if self._job is not None and self._job["state"] in ("pending", "running"):
                raise RuntimeError("job_running")
            job_id = "job-%d" % next(self._counter)
            self._job = {"job_id": job_id, "spec": spec, "state": "pending",
                         "phase": "", "detail": "", "pct": 0,
                         "result": None, "error": None}
            return job_id

    def take_pending(self):
        with self._lock:
            job = self._job
            if job is None or job["state"] != "pending":
                return None
            job["state"] = "running"
            return job["job_id"], job["spec"]

    def _if_current(self, job_id):
        job = self._job
        return job if (job is not None and job["job_id"] == job_id) else None

    def update(self, job_id, phase, detail="", pct=None):
        with self._lock:
            job = self._if_current(job_id)
            if job is None:
                return
            job["phase"] = phase
            job["detail"] = detail
            if pct is not None:
                job["pct"] = pct

    def finish(self, job_id, result):
        with self._lock:
            job = self._if_current(job_id)
            if job is not None:
                job["state"] = "done"
                job["result"] = result
                job["pct"] = 100

    def fail(self, job_id, error):
        with self._lock:
            job = self._if_current(job_id)
            if job is not None:
                job["state"] = "error"
                job["error"] = str(error)

    def status(self, job_id):
        with self._lock:
            job = self._if_current(job_id)
            if job is None:
                return {"error": "unknown_job"}
            snap = dict(job)
            snap.pop("spec", None)
            return snap


JOBS = JobRegistry()


# ---------------------------------------------------------------------------
# Static + /api server
# ---------------------------------------------------------------------------

class _RequestHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):
        # Silence the default stderr access log.
        pass

    def do_GET(self):
        parsed_path = urllib.parse.urlsplit(self.path).path
        if self._is_api_path():
            self._handle_api()
        elif parsed_path == _THUMB_PATH:
            self._handle_thumb()
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

    def _send_bytes(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(data)

    # -- thumb -------------------------------------------------------

    def _handle_thumb(self):
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            key = (query.get("key") or [""])[-1]
            if not key:
                self._send_plain(404, b"missing key")
                return
            result = self.server.api_handler({"op": "hub/thumb", "key": key})
            png_path = (result or {}).get("png_path")
            if not png_path or not os.path.isfile(png_path):
                self._send_plain(404, b"no thumbnail")
                return
            with open(png_path, "rb") as handle:
                data = handle.read()
            self._send_bytes(200, data, "image/png")
        except Exception as exc:
            self._send_plain(404, ("thumb error: %s" % exc).encode("utf-8"))


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


# ---------------------------------------------------------------------------
# Save Version form — mirrors ui/dialogs.py SaveVersionDialog exactly
# ---------------------------------------------------------------------------

# Non-blocking hint shown in ui/dialogs.py SaveVersionDialog.Command when
# "final" appears in the comment (verbatim MessageDialog text there). Here
# it becomes a ``warning`` string on a *successful* submit response instead
# of a popup that must be dismissed before the save can proceed — the save
# itself is never blocked by it, matching the native dialog's own comment
# ("continuing — your comment will be saved as-is").
SAVE_VERSION_FINAL_HINT = (
    "Tip: instead of writing 'final' in the comment, use the 'Final Delivery' "
    "status tag — it bakes the marker into the filename (e.g. scene_v007_FINAL.c4d) "
    "and the history log."
)


def resolve_save_version_status(status, custom_status):
    """Pure port of ``SaveVersionDialog._current_status``: a non-empty
    custom status always wins over the combo selection, sanitized the same
    way (``versioning._sanitize_status`` — strip non-alphanumerics,
    uppercase). Returns ``""`` (WIP) if both are empty."""
    custom = (custom_status or "").strip()
    if custom:
        return _sanitize_status(custom)
    return _sanitize_status(status or "")


def validate_save_version_submit(payload):
    """Pure validation for ``POST /api/form/save_version/submit``, mirroring
    ``ui/dialogs.py`` ``SaveVersionDialog.Command``'s ``BTN_SAVE`` branch:

    - an empty (or whitespace-only) comment is rejected — the native dialog
      shows a blocking ``MessageDialog``; here it is
      ``{"ok": False, "error": str}`` for the SPA to render inline (no
      popup, per the Phase 4 popup-triage direction).
    - "final" anywhere in the comment (case-insensitive) is a *non-blocking*
      soft warning — the native dialog still lets the save proceed after
      showing it; here it rides along on a successful response as
      ``warning`` for the caller to toast, never gating the save.
    - ``status``/``custom_status`` resolve via ``resolve_save_version_status``.

    Returns ``{"ok": True, "comment", "status", "run_qc", "warning"}`` or
    ``{"ok": False, "error": str}``. Never raises.
    """
    comment = (payload.get("comment") or "").strip()
    if not comment:
        return {
            "ok": False,
            "error": "Please enter a comment describing this version.",
        }

    status = resolve_save_version_status(
        payload.get("status"), payload.get("custom_status"))
    warning = SAVE_VERSION_FINAL_HINT if "final" in comment.lower() else None

    return {
        "ok": True,
        "comment": comment,
        "status": status,
        "run_qc": bool(payload.get("run_qc", True)),
        "warning": warning,
    }


def save_version_status_options():
    """The ``status_options`` list for ``form/save_version/state`` —
    ``versioning.STATUS_OPTIONS`` reshaped to ``{"label", "suffix"}`` dicts
    (the SPA contract; the per-status filename preview is attached by the
    caller, which alone can call ``preview_next_filename`` — it needs the
    live document)."""
    return [{"label": label, "suffix": suffix} for label, suffix in STATUS_OPTIONS]


# ---------------------------------------------------------------------------
# Notes form — mirrors ui/dialogs.py NotesDialog + notes.py primitives
# ---------------------------------------------------------------------------

def merge_notes_submission(original_notes, notes_text, submitted_todos):
    """Pure reconciliation for ``POST /api/form/notes/submit``.

    ``original_notes`` must be freshly loaded from disk by the caller (never
    trust a client-supplied full copy as the source of truth — a concurrent
    external edit would otherwise be silently clobbered wholesale). Drives
    the exact same primitives ``NotesDialog``'s ``TodoArea`` callbacks use
    (``notes.add_todo`` / ``notes.toggle_todo`` — see ``ui/dialogs.py``
    ``NotesDialog._on_toggle_todo``/``_on_delete_todo``) so timestamp
    bookkeeping (``added``/``completed``) stays correct instead of being
    reinvented here.

    ``submitted_todos`` is the SPA's desired end-state todo list:
    ``[{"id": int|None, "text": str, "done": bool}, ...]``. The native
    dialog never supported editing an existing TODO's text (only
    add/toggle/delete via the ``TodoArea`` click targets), so this mirrors
    that scope exactly: an existing id's text is left untouched, only its
    done state may flip via ``toggle_todo``. A new item (no id, or an id
    that no longer matches an existing TODO) is created via ``add_todo``,
    then toggled on immediately if submitted with ``done: true``. Any
    existing id NOT present in ``submitted_todos`` is dropped — deletion is
    implicit (the whole list is a replace), not a separate ``delete_todo``
    call, since the final list is built from scratch as ``ordered``.

    Returns a deep-copied notes dict ready for ``notes.save_notes`` — never
    mutates ``original_notes``. Never raises on malformed items (a
    non-dict entry, or one with an empty/whitespace-only text, is skipped).
    """
    import copy

    working = copy.deepcopy(original_notes) if original_notes else {
        "scene": "", "updated": "", "notes": "", "todos": []}
    working.setdefault("todos", [])
    working["notes"] = (notes_text or "").strip()

    def _norm_id(raw):
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    existing_by_id = {_norm_id(t.get("id")): t for t in working["todos"]}

    ordered = []
    for item in submitted_todos or []:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        done = bool(item.get("done"))
        todo = existing_by_id.get(_norm_id(item.get("id")))

        if todo is not None:
            if bool(todo.get("done")) != done:
                toggle_todo(working, todo.get("id"))
            ordered.append(todo)
        else:
            add_todo(working, text)
            new_todo = working["todos"][-1]
            if done:
                toggle_todo(working, new_todo.get("id"))
            ordered.append(new_todo)

    working["todos"] = ordered
    return working


# ---------------------------------------------------------------------------
# Settings form — mirrors ui/dialogs.py SentinelSettingsDialog exactly
# ---------------------------------------------------------------------------

SETTINGS_FPS_OPTIONS = (24, 25, 30, 60)
SETTINGS_COMPOSITOR_OPTIONS = ("Nuke", "After Effects")
SETTINGS_HISTORY_OPTIONS = (5, 10, 20)


def validate_settings_submit(payload, fps_locked=False, snapshot_dir_locked=False):
    """Pure mapper: raw form payload -> the exact fields
    ``SentinelSettingsDialog``'s ``BTN_SAVE`` branch would persist to
    ``GlobalSettings`` (see ``ui/dialogs.py`` ``SentinelSettingsDialog.Command``).

    Honors the same two machine-controlled locks the native dialog disables
    via ``Enable(..., False)``: Standard FPS overridden by project rules
    (``fps_locked``) and the RS snapshot dir auto-detected from RenderView's
    config (``snapshot_dir_locked``) — a locked field is never written here
    even if the payload includes one, exactly like the native dialog's
    ``if not self._standard_fps_overridden: ...`` / ``if not
    self._snap_dir_overridden: ...`` guards.

    Note: unlike FPS/snapshot dir, the native dialog's "Review slate
    burn-in" checkbox is NEVER disabled even though a project ruleset can
    also override it at usage time (``CHK_SLATE`` has no
    ``_slate_overridden`` guard in ``InitValues``/``Command`` — only a
    always-shown static hint line). So ``slate`` here has no lock parameter;
    grounded in the native dialog's actual behavior, not the plan sketch's
    ``slate(+locked)`` shorthand.

    A malformed/out-of-range value is silently skipped (field omitted from
    the returned dict, left unchanged) — mirrors the native dialog's own
    robustness guards (``if 0 <= idx < len(...)``), which never surface an
    error dialog for a bad combo index either. Never raises.

    Returns a dict of only the ``GlobalSettings`` keys to write, e.g.
    ``{"standard_fps": 25, "comp_target": 0, "aov_multipart": 1,
    "snapshot_slate": True, "mv_max_motion": 0, "snapshot_dir": "...",
    "history_max_rows": 10}`` — any subset, never all keys are guaranteed
    present.
    """
    updates = {}

    if not fps_locked:
        fps = _coerce_int(payload.get("fps"))
        if fps in SETTINGS_FPS_OPTIONS:
            updates["standard_fps"] = fps

    compositor = _coerce_int(payload.get("compositor"))
    if compositor in (0, 1):
        updates["comp_target"] = compositor

    if "multipart_default" in payload:
        updates["aov_multipart"] = 1 if payload.get("multipart_default") else 0

    if "slate" in payload:
        updates["snapshot_slate"] = bool(payload.get("slate"))

    mv_max = _coerce_int(payload.get("mv_max_motion"))
    if mv_max is not None:
        updates["mv_max_motion"] = max(mv_max, 0)

    if not snapshot_dir_locked:
        snap_dir = (payload.get("snapshot_dir") or "").strip()
        if snap_dir:
            updates["snapshot_dir"] = snap_dir

    history_max = _coerce_int(payload.get("history_max"))
    if history_max in SETTINGS_HISTORY_OPTIONS:
        updates["history_max_rows"] = history_max

    return updates


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gate form — mirrors gate.py evaluate_gate() + ui/dialogs.py GateTriageDialog
# ---------------------------------------------------------------------------

_CHECK_ENTRY_BY_ID = {entry.check_id: entry for entry in CHECK_REGISTRY}


def _gate_item_payload(bucket, item):
    entry = _CHECK_ENTRY_BY_ID.get(item.get("check_id"))
    return {
        "check_id": item.get("check_id") or "",
        "label": entry.row_label if entry else (item.get("check_id") or ""),
        "severity": entry.severity if entry else "",
        "bucket": bucket,
        "blocks": bool(item.get("blocks")),
        "has_fix": bool(entry.has_fix) if entry else False,
        "new_count": int(item.get("new_count") or 0),
        "violations": [
            _qc_violation_detail(v) for v in (item.get("violations") or [])
        ],
    }


def gate_state_payload(gate_result, sidecar_invalid=False):
    """Map one ``gate.evaluate_gate()`` result to the SPA's GateState
    contract (``GET/POST /api/form/gate/state``, and echoed back inside
    every ``form/gate/submit`` response so the page never needs a second
    round trip to refresh).

    Pure: no c4d. The caller (see ``ui/web_ops.py``) computes
    ``gate_result`` on the C4D main thread exactly the way
    ``ui/flows.py`` ``_run_quality_gate`` does (``_compute_gate_snapshot``),
    and passes ``sidecar_invalid`` from that same snapshot's
    ``baseline_status``.

    ``bucket`` ("fixable"/"blocking"/"advisory") is ``evaluate_gate``'s own
    English grouping — used directly instead of re-deriving from
    ``gate.classify_gate``'s Spanish level constants
    (``CORREGIBLE``/``BLOQUEANTE``/``AVISO``), which stay internal to
    ``gate.py``/the native dialog.

    Output (TS-ready — Task 3 mirrors this as ``GateState``)::

        {
          "passed": bool,
          "sidecar_invalid": bool,
          "checks": [
            {"check_id": str, "label": str, "severity": "FAIL"|"WARN",
             "bucket": "fixable"|"blocking"|"advisory", "blocks": bool,
             "has_fix": bool, "new_count": int,
             "violations": [{"label", "message", "extras"}, ...]}
          ],
        }

    Never raises on missing/partial input.
    """
    gate_result = gate_result or {}
    checks = []
    for bucket in ("fixable", "blocking", "advisory"):
        for item in gate_result.get(bucket) or []:
            checks.append(_gate_item_payload(bucket, item))

    return {
        "passed": bool(gate_result.get("passed", True)),
        "sidecar_invalid": bool(sidecar_invalid),
        "checks": checks,
    }


def gate_can_proceed(gate_result):
    """Whether the gate may be considered resolved right now — pure re-check
    run fresh after each mutating action (``fix_all``/``accept``), so it
    needs no per-row ``decisions``/``reason`` state like the native
    ``ui/dialogs.py`` ``gate_dialog_can_proceed`` (built for one long-lived
    modal session): a check_id that was successfully fixed or accepted
    simply no longer appears in ``blocking``/``fixable`` once its new-count
    drops to 0 (``evaluate_gate`` only emits checks with ``new_count > 0``).

    Equivalent condition: no ``blocking``-bucket item, AND no
    ``fixable``-bucket item with ``blocks`` True (a WARN-severity fixable
    check, e.g. unused materials, never blocks — same as native). Advisory
    items never block either, in both implementations.
    """
    gate_result = gate_result or {}
    if gate_result.get("blocking"):
        return False
    for item in gate_result.get("fixable") or []:
        if item.get("blocks"):
            return False
    return True


# ---------------------------------------------------------------------------
# Command palette — action registry + gating
# ---------------------------------------------------------------------------

# Static action descriptors. "kind": "run" executes server-side work through
# `palette/run`; "kind": "navigate" is pure SPA client-side routing (the
# server only validates whether the target page makes sense right now — see
# `requires_doc`/`requires_saved` below — the FormDialog host that actually
# opens the page is Phase 4 Task 4, not built yet). `check_id` on a "Quick
# Fix" run action ties it to the QC check whose current violation count
# gates `enabled` (see `palette_actions_payload`) — same check_ids the
# panel's own `_qc_fix_*` handlers key off of (`self._lights_bad` etc.).
#
# `requires_confirm` + `confirm_label` mark the two Quick Fix actions whose
# native handlers gate on a real ``QuestionDialog`` decision, per
# docs/superpowers/specs/2026-07-19-popup-triage.md (DECISIÓN, "must stay"):
# panel.py:1891 "Delete N unused material(s)?" (destructive) and panel.py:1918
# the FPS/range fix preview + confirm (destructive — rewrites every render
# preset). ``fix_lights``/``fix_cameras`` never had a native confirm (they
# are reversible, low-impact fixes reported via status bar only — see
# panel.py `_qc_fix_lights`/`_qc_fix_cam`), so they stay unconfirmed. A
# native modal can't be opened mid-``palette/run`` (it would block the
# ``MainThreadQueue`` drain loop and hang the HTTP request under the
# cancellation contract — see webbridge.MainThreadQueue.drain), so the gate
# is a contract-level round trip instead: `palette/run` rejects a
# `requires_confirm` action with ``{"error": "confirm_required"}`` unless
# the payload carries ``confirm: true`` — the SPA must render
# `confirm_label` as an explicit yes/no step before resubmitting with that
# flag (see `palette_actions_payload` / `ui/web_ops.py` `_op_palette_run`).
PALETTE_ACTIONS = (
    {"id": "open_hub", "label": "Open Asset Hub", "group": "Navigate",
     "kind": "run", "requires_doc": True},
    {"id": "open_reports_qc", "label": "Open Reports · QC", "group": "Navigate",
     "kind": "run", "requires_doc": False},
    {"id": "open_reports_doctor", "label": "Open Reports · Doctor", "group": "Navigate",
     "kind": "run", "requires_doc": False},
    {"id": "open_reports_supervisor", "label": "Open Reports · Supervisor",
     "group": "Navigate", "kind": "run", "requires_doc": False},
    {"id": "open_reports_render_validation", "label": "Open Reports · Render Validation",
     "group": "Navigate", "kind": "run", "requires_doc": False},
    {"id": "open_reports_delivery", "label": "Open Reports · Delivery Summary",
     "group": "Navigate", "kind": "run", "requires_doc": False},
    {"id": "save_version", "label": "Save Version…", "group": "Scene",
     "kind": "navigate", "page": "form/save_version", "requires_doc": True},
    {"id": "edit_notes", "label": "Edit Notes…", "group": "Scene",
     "kind": "navigate", "page": "form/notes", "requires_doc": True,
     "requires_saved": True},
    {"id": "settings", "label": "Settings…", "group": "Scene",
     "kind": "navigate", "page": "form/settings", "requires_doc": False},
    {"id": "gate_triage", "label": "Quality Gate Triage…", "group": "Scene",
     "kind": "navigate", "page": "form/gate", "requires_doc": True},
    {"id": "fix_lights", "label": "Fix: Group stray lights", "group": "Quick Fix",
     "kind": "run", "requires_doc": True, "check_id": "lights"},
    {"id": "fix_cameras", "label": "Fix: Reset camera shift", "group": "Quick Fix",
     "kind": "run", "requires_doc": True, "check_id": "cam"},
    {"id": "fix_materials", "label": "Fix: Delete unused materials",
     "group": "Quick Fix", "kind": "run", "requires_doc": True,
     "check_id": "unused_mats", "requires_confirm": True,
     "confirm_label": "Delete {count} unused material(s) — single undo"},
    {"id": "fix_fps", "label": "Fix: FPS / frame range", "group": "Quick Fix",
     "kind": "run", "requires_doc": True, "check_id": "fps_range",
     "requires_confirm": True,
     "confirm_label": "Rewrite FPS + frame range on {count} issue(s) "
                       "across ALL render presets — single undo"},
    {"id": "rescan_qc", "label": "Rescan QC", "group": "Quick Fix",
     "kind": "run", "requires_doc": True},
)

PALETTE_ACTION_BY_ID = {action["id"]: action for action in PALETTE_ACTIONS}


def palette_actions_payload(doc_present, doc_saved=False, qc_counts=None):
    """Pure: build the ``palette/actions`` response — ``PALETTE_ACTIONS``'s
    static descriptors plus per-call ``enabled``/``reason`` gating.

    ``qc_counts`` maps check_id -> current legacy violation count (see
    ``qc.score.count_violations``); a Quick Fix action is disabled with
    reason "Nothing to fix" when its check's count is 0 — mirrors the
    panel's own ``_qc_fix_*`` handlers, which are no-ops printing "No ...
    issues to fix" when their bad-list is empty (Phase 4 Task 2 gives that
    same no-op a disabled, not just a silent-no-op, palette entry).

    Every action carries ``requires_confirm``/``confirm_label`` (False/None
    for most). For the two DECISIÓN-classified destructive fixes
    (``fix_materials``, ``fix_fps`` — see the ``PALETTE_ACTIONS`` comment
    above), ``confirm_label`` is formatted with the live ``qc_counts`` value
    for that action's ``check_id`` so the SPA can show "Delete 3 unused
    material(s) — single undo" instead of static wording; a missing count
    falls back to 0 rather than raising.

    Never raises: an action with a ``check_id`` not present in
    ``qc_counts`` is treated as 0 (nothing to fix), never a KeyError.
    """
    qc_counts = qc_counts or {}
    actions = []
    for action in PALETTE_ACTIONS:
        enabled = True
        reason = None
        if action.get("requires_doc") and not doc_present:
            enabled = False
            reason = "No active document"
        elif action.get("requires_saved") and not doc_saved:
            enabled = False
            reason = "Save the scene to a folder first"
        elif action.get("check_id") and qc_counts.get(action["check_id"], 0) == 0:
            enabled = False
            reason = "Nothing to fix"

        requires_confirm = bool(action.get("requires_confirm"))
        confirm_label = None
        if requires_confirm:
            count = qc_counts.get(action.get("check_id"), 0)
            confirm_label = action["confirm_label"].format(count=count)

        actions.append({
            "id": action["id"],
            "label": action["label"],
            "group": action["group"],
            "enabled": enabled,
            "reason": reason,
            "requires_confirm": requires_confirm,
            "confirm_label": confirm_label,
        })
    return actions


# ---------------------------------------------------------------------------
# Hub payload helpers
# ---------------------------------------------------------------------------

_THUMB_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr",
               ".tga", ".bmp", ".psd", ".webp"}


def hub_inventory_payload(records, totals, scene_name="", skipped=0):
    """Pure: shape merged AssetRecords (assets.merge_inventories) for the SPA.

    Strips live-scene fields (tex_idx/tex_idxs stay server-side; the apply
    op re-resolves keys against a fresh scan — HTTP is stateless).
    """
    assets_out = []
    for rec in records:
        resolved = rec.get("resolved_path")
        ext = os.path.splitext(resolved or "")[1].lower()
        assets_out.append({
            "key": rec.get("key", ""),
            "path": rec.get("path", ""),
            "resolved_path": resolved,
            "status": rec.get("status", ""),
            "asset_type": rec.get("asset_type", ""),
            "size_bytes": rec.get("size_bytes"),
            "size_label": _assets.format_size(rec.get("size_bytes")),
            "owners": [{"name": n, "kind": k, "channel": c}
                       for (n, k, c) in rec.get("owners", [])],
            "repathable": bool(rec.get("repathable")),
            "has_thumb": bool(resolved) and ext in _THUMB_EXTS,
        })
    totals_out = dict(totals)
    totals_out["total_label"] = _assets.format_size(totals.get("total_bytes"))
    return {"scene_name": scene_name, "skipped": skipped,
            "assets": assets_out, "totals": totals_out}


def resolve_repath_targets(records, changes):
    """Pure: map client pending changes [{key,new_path}] onto tex_idxs."""
    by_key = {rec.get("key"): rec for rec in records}
    targets, errors = [], []
    for change in changes or []:
        key = change.get("key", "")
        new_path = (change.get("new_path") or "").strip()
        rec = by_key.get(key)
        if rec is None:
            errors.append({"key": key, "error": "unknown key (rescan?)"})
            continue
        if not new_path:
            errors.append({"key": key, "error": "empty new path"})
            continue
        if not rec.get("repathable"):
            errors.append({"key": key, "error": "not repathable"})
            continue
        idxs = rec.get("tex_idxs") or (
            [rec["tex_idx"]] if rec.get("tex_idx") is not None else [])
        if not idxs:
            errors.append({"key": key, "error": "no writable shader"})
            continue
        targets.append({"key": key, "new_path": new_path, "tex_idxs": list(idxs)})
    return targets, errors


def thumb_cache_name(resolved_path, mtime):
    """Pure: stable cache filename from path and mtime."""
    digest = hashlib.sha1(
        ("%s|%s" % (resolved_path, mtime)).encode("utf-8")).hexdigest()
    return digest + ".png"


_COLLECT_PHASES = (("Saving", "save", 15), ("Re-scanning", "rescan", 60),
                   ("Writing manifest", "manifest", 80), ("Zipping", "zip", 90))


def collect_phase_pct(message):
    """Pure: map run_collect_pipeline status strings to (phase, pct) tuples."""
    for prefix, phase, pct in _COLLECT_PHASES:
        if (message or "").startswith(prefix):
            return phase, pct
    return "run", None
