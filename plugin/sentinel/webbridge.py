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
