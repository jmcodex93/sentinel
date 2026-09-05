"""Authenticated loopback HTTP server behind Sentinel's web UI."""

import http.server
import json
import os
import secrets
import threading
import urllib.parse

from sentinel.bridge.hub import _THUMB_EXTS
from sentinel.common.logging import exception as log_exception
from sentinel.common.logging import info as log_info

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

# ── Local-API hardening (Block 1) ────────────────────────────────────────────
# The bridge serves a localhost-only HTTP server whose ops can mutate the
# open document and the filesystem. Any web page open in any browser can
# fire blind cross-origin requests at 127.0.0.1 (CORS stops them READING
# responses, not SENDING requests), so the API must authenticate every
# call with a per-instance capability token and enforce method semantics.
MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB — generous for JSON payloads

# Ops reachable via GET. Everything else requires POST (mutations + ops
# that carry a body). GET is reserved for pure reads so a link prefetch,
# image src, or other browser-initiated GET can never trigger an action.
_GET_OPS = frozenset({
    # report/* — read-only payload mappers.
    "report/delivery", "report/qc", "report/doctor",
    "report/supervisor", "report/render_validation",
    # form state reads.
    "form/save_version/state", "form/notes/state", "form/settings/state",
    "form/gate/state",
    # hub reads.
    "hub/inventory", "hub/meta", "hub/meta_totals", "hub/variants",
    "hub/ui_state", "hub/job_status", "hub/preflight", "hub/presets",
    "hub/state_stamp",
    # panel reads.
    "panel/overview", "panel/qc", "panel/render", "panel/aov_list",
    "panel/render/aov_list", "panel/deliver", "panel/frame",
    "panel/state_stamp",
    # tools previews are read-only derivations.
    "panel/tools/rename_preview", "panel/tools/matwire_preview",
    "panel/tools/standard_preview", "panel/tools/newshot_preview",
    "palette/actions",
})


class _RequestHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):
        # Silence the default stderr access log.
        pass

    def do_GET(self):
        if not self._check_access():
            return
        parsed_path = urllib.parse.urlsplit(self.path).path
        if self._is_api_path():
            self._handle_api()
        elif parsed_path == _THUMB_PATH:
            self._handle_thumb()
        else:
            self._handle_static()

    def do_POST(self):
        if not self._check_access():
            return
        if self._is_api_path():
            self._handle_api()
        else:
            self._send_json({"error": "not found"}, 404)

    def _check_access(self):
        """Reject requests that did not come from the trusted SPA instance.

        Three gates, cheapest first:
        1. Host must be the loopback address the server bound (blocks DNS
           rebinding, where an attacker page resolves a hostname they own
           to 127.0.0.1 and the browser sends a Host header of that name).
        2. Origin, when present, must match our own loopback origin or be
           absent (absent = non-browser client / older HtmlViewer). The
           SPA always sends Origin on POST; browsers omit it on same-origin
           GET navigations but include it on cross-origin ones.
        3. API paths additionally require the capability token. Static
           files and /thumb stay token-free so the SPA shell can boot from
           the URL bar before JS runs (the token rides ?token= and is
           echoed by fetch wrappers from then on).
        """
        host = self.headers.get("Host") or ""
        allowed_host = f"127.0.0.1:{self.server.server_port}"
        if host != allowed_host:
            self._send_json({"error": "bad_host"}, 403)
            return False

        origin = self.headers.get("Origin") or ""
        if origin:
            expected_origin = f"http://127.0.0.1:{self.server.server_port}"
            if origin != expected_origin:
                self._send_json({"error": "bad_origin"}, 403)
                return False

        if self._is_api_path():
            token = self._extract_token()
            if not token or not secrets.compare_digest(token, self.server.api_token):
                self._send_json({"error": "unauthorized"}, 401)
                return False
        return True

    def _extract_token(self):
        # Header first (POST bodies), then query param (GET links).
        header_token = self.headers.get("X-Sentinel-Token") or ""
        if header_token:
            return header_token
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
        values = query.get("token") or [""]
        return values[-1]

    # -- api ---------------------------------------------------------

    def _is_api_path(self):
        return urllib.parse.urlsplit(self.path).path.startswith(_API_PREFIX)

    def _handle_api(self):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            op = parsed.path[len(_API_PREFIX):]

            # Method semantics: GET only for declared read-only ops.
            if self.command == "GET" and op not in _GET_OPS:
                self._send_json({"error": "method_not_allowed", "op": op}, 405)
                return

            payload = {}

            if self.command == "POST":
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length > MAX_BODY_BYTES:
                    self._send_json({"error": "payload_too_large"}, 413)
                    return
                content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if length and content_type not in ("application/json", ""):
                    self._send_json({"error": "unsupported_media_type"}, 415)
                    return
                if length:
                    raw = self.rfile.read(length)
                    if raw:
                        body = json.loads(raw)
                        if isinstance(body, dict):
                            payload.update(body)

            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            for key, values in query.items():
                payload[key] = values[-1] if values else ""

            payload["op"] = op

            result = self.server.api_handler(payload)
            # Queue failures are diagnostic dictionaries for native callers.
            # Only a generic failure may cross the HTTP boundary.
            if isinstance(result, dict) and "traceback" in result:
                self._send_json({"error": "internal_error"}, 500)
            else:
                self._send_json(result, 200)
        except Exception as exc:
            # Log the full traceback server-side but never leak local paths
            # or stack frames to the HTTP client (localhost-only is not a
            # license to hand any co-resident process an information dump).
            log_exception(
                "http.handler_failed",
                "webbridge.http",
                exc,
                method=self.command,
                path=urllib.parse.urlsplit(self.path).path,
            )
            self._send_json({"error": "internal_error"}, 500)

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
            log_exception(
                "http.handler_failed",
                "webbridge.http",
                exc,
                method=self.command,
                path=urllib.parse.urlsplit(self.path).path,
            )
            self._send_plain(404, b"thumb error")


def create_server(web_root, api_handler, host="127.0.0.1", ports=range(8347, 8357)):
    """Bind a ThreadingHTTPServer on the first free port in ``ports``.

    Returns ``(server, port, token)``. The capability ``token`` is a fresh
    random secret per server instance; it must be embedded in the SPA URL
    (``?token=<hex>``) and echoed by every API request (header or query).
    Raises ``OSError`` if every port in ``ports`` is already in use.
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
        server.api_token = secrets.token_hex(32)
        return server, port, server.api_token

    raise OSError(
        f"No free port available in {ports!r} on {host}") from last_error


def start_server_thread(server):
    """Start ``server.serve_forever()`` on a daemon thread and return it."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    server._sentinel_started = True
    thread.start()
    host, port = server.server_address[:2]
    log_info(
        "http.server_started",
        "webbridge.http",
        host=host,
        port=port,
    )
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
        except Exception as exc:
            log_exception(
                "http.server_stop_failed",
                "webbridge.http",
                exc,
                phase="shutdown",
            )
    try:
        server.server_close()
    except Exception as exc:
        log_exception(
            "http.server_stop_failed",
            "webbridge.http",
            exc,
            phase="server_close",
        )

