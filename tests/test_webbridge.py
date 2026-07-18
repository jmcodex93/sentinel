# -*- coding: utf-8 -*-
"""Tests for the pure-stdlib web bridge (plugin/sentinel/webbridge.py):
MainThreadQueue (cross-thread submit/drain hand-off used by the C4D Timer)
and create_server/start_server_thread/stop_server (static + /api server for
the Reports SPA). No c4d import anywhere here or in webbridge.py — this is
exercised with real sockets/threads, no mocks of http.
"""
import http.client
import json
import socket
import threading
import time

import pytest

from sentinel import webbridge


# ---------------------------------------------------------------------------
# MainThreadQueue
# ---------------------------------------------------------------------------

class TestMainThreadQueueRoundTrip:
    def test_submit_from_thread_drain_on_main_thread(self):
        q = webbridge.MainThreadQueue()
        results = {}

        def worker():
            results["value"] = q.submit({"op": "ping"}, timeout=5.0)

        t = threading.Thread(target=worker)
        t.start()

        # Give the worker a moment to enqueue before draining, so this
        # exercises the real wait-then-wake path, not a lucky race.
        deadline = time.time() + 2.0
        while q._queue.empty() and time.time() < deadline:
            time.sleep(0.01)

        def dispatch(payload):
            assert payload == {"op": "ping"}
            return {"pong": True}

        q.drain(dispatch)
        t.join(timeout=5.0)
        assert not t.is_alive()
        assert results["value"] == {"pong": True}

    def test_drain_processes_everything_queued(self):
        q = webbridge.MainThreadQueue()
        results = [None, None, None]

        def worker(i):
            results[i] = q.submit({"n": i}, timeout=5.0)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()

        deadline = time.time() + 2.0
        while q._queue.qsize() < 3 and time.time() < deadline:
            time.sleep(0.01)

        seen = []

        def dispatch(payload):
            seen.append(payload["n"])
            return {"n": payload["n"]}

        q.drain(dispatch)
        for t in threads:
            t.join(timeout=5.0)

        assert sorted(seen) == [0, 1, 2]
        assert results == [{"n": 0}, {"n": 1}, {"n": 2}]

    def test_submit_timeout_raises(self):
        q = webbridge.MainThreadQueue()
        with pytest.raises(TimeoutError) as exc_info:
            q.submit({"op": "never-drained"}, timeout=0.05)
        assert "keep the Reports window open" in str(exc_info.value)

    def test_drain_dispatch_exception_returns_error_dict_not_raised(self):
        q = webbridge.MainThreadQueue()
        results = {}

        def worker():
            results["value"] = q.submit({"op": "boom"}, timeout=5.0)

        t = threading.Thread(target=worker)
        t.start()

        deadline = time.time() + 2.0
        while q._queue.empty() and time.time() < deadline:
            time.sleep(0.01)

        def dispatch(payload):
            raise ValueError("kaboom")

        q.drain(dispatch)  # must not raise
        t.join(timeout=5.0)

        assert "error" in results["value"]
        assert "kaboom" in results["value"]["error"]
        assert "traceback" in results["value"]
        assert "ValueError" in results["value"]["traceback"]

    def test_drain_empty_queue_is_noop(self):
        q = webbridge.MainThreadQueue()
        calls = []
        q.drain(lambda payload: calls.append(payload))
        assert calls == []

    def test_drain_never_raises_even_if_dispatch_always_fails(self):
        q = webbridge.MainThreadQueue()
        q._queue.put(webbridge._QueuedRequest({"op": "x"}))

        def dispatch(payload):
            raise RuntimeError("nope")

        # Should complete without raising.
        q.drain(dispatch)


# ---------------------------------------------------------------------------
# HTTP server: static + /api
# ---------------------------------------------------------------------------

def _echo_handler(payload):
    return {"echo": payload}


def _raising_handler(payload):
    raise RuntimeError("handler exploded")


class _LiveServer:
    """Test helper: starts a real create_server() instance and tears it down."""

    def __init__(self, web_root, api_handler=_echo_handler, ports=None):
        kwargs = {}
        if ports is not None:
            kwargs["ports"] = ports
        self.server, self.port = webbridge.create_server(
            str(web_root), api_handler, **kwargs)
        self.thread = webbridge.start_server_thread(self.server)

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp, body
        finally:
            conn.close()

    def post(self, path, body_obj=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            data = json.dumps(body_obj or {}).encode("utf-8")
            conn.request("POST", path, body=data,
                          headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            body = resp.read()
            return resp, body
        finally:
            conn.close()

    def close(self):
        webbridge.stop_server(self.server)


@pytest.fixture
def web_root(tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    (root / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    assets = root / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('hi');", encoding="utf-8")
    (assets / "font.woff2").write_bytes(b"\x00\x01\x02fontdata")
    return root


class TestStaticServing:
    def test_index_served_at_root(self, web_root):
        live = _LiveServer(web_root)
        try:
            resp, body = live.get("/")
            assert resp.status == 200
            assert body == b"<html>INDEX</html>"
            assert "text/html" in resp.getheader("Content-Type")
        finally:
            live.close()

    def test_nested_asset_served_with_content_type(self, web_root):
        live = _LiveServer(web_root)
        try:
            resp, body = live.get("/assets/app.js")
            assert resp.status == 200
            assert body == b"console.log('hi');"
            assert "javascript" in resp.getheader("Content-Type")

            resp2, body2 = live.get("/assets/font.woff2")
            assert resp2.status == 200
            assert body2 == b"\x00\x01\x02fontdata"
            assert resp2.getheader("Content-Type") == "font/woff2"
        finally:
            live.close()

    def test_unknown_spa_route_falls_back_to_index(self, web_root):
        live = _LiveServer(web_root)
        try:
            resp, body = live.get("/reports/delivery/some/deep/route")
            assert resp.status == 200
            assert body == b"<html>INDEX</html>"
        finally:
            live.close()

    def test_path_traversal_blocked(self, tmp_path, web_root):
        # A "secret" file lives OUTSIDE web_root, one level up.
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET", encoding="utf-8")

        live = _LiveServer(web_root)
        try:
            resp, body = live.get("/../secret.txt")
            assert b"TOP SECRET" not in body
            # Either SPA-falls-back to index (200) or 404 — never the file.
            assert resp.status in (200, 404)
        finally:
            live.close()

    def test_symlink_inside_root_pointing_outside_is_blocked(self, tmp_path, web_root):
        # A symlink physically inside web_root but resolving OUTSIDE it
        # (e.g. web_root/leak -> ../secret.txt) must not be served — the
        # containment check has to follow the symlink (realpath), not just
        # normalize the literal request path.
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET VIA SYMLINK", encoding="utf-8")
        leak = web_root / "leak.txt"
        try:
            leak.symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this filesystem")

        live = _LiveServer(web_root)
        try:
            resp, body = live.get("/leak.txt")
            assert b"TOP SECRET VIA SYMLINK" not in body
            assert resp.status in (200, 404)
        finally:
            live.close()

    def test_missing_web_root_or_index_returns_plain_404(self, tmp_path):
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        live = _LiveServer(empty_root)
        try:
            resp, body = live.get("/")
            assert resp.status == 404
        finally:
            live.close()


class TestApiRouting:
    def test_get_round_trip_with_query_params(self, web_root):
        live = _LiveServer(web_root, api_handler=_echo_handler)
        try:
            resp, body = live.get("/api/report/delivery?path=foo&name=bar")
            assert resp.status == 200
            data = json.loads(body)
            payload = data["echo"]
            assert payload["op"] == "report/delivery"
            assert payload["path"] == "foo"
            assert payload["name"] == "bar"
        finally:
            live.close()

    def test_post_round_trip_merges_body_and_query(self, web_root):
        live = _LiveServer(web_root, api_handler=_echo_handler)
        try:
            resp, body = live.post("/api/echo?extra=1", {"a": 1, "b": "two"})
            assert resp.status == 200
            data = json.loads(body)
            payload = data["echo"]
            assert payload["op"] == "echo"
            assert payload["a"] == 1
            assert payload["b"] == "two"
            assert payload["extra"] == "1"
        finally:
            live.close()

    def test_handler_exception_returns_500_with_error(self, web_root):
        live = _LiveServer(web_root, api_handler=_raising_handler)
        try:
            resp, body = live.get("/api/whatever")
            assert resp.status == 500
            data = json.loads(body)
            assert "error" in data
            assert "handler exploded" in data["error"]
        finally:
            live.close()

    def test_no_cors_header_present(self, web_root):
        live = _LiveServer(web_root, api_handler=_echo_handler)
        try:
            resp, _ = live.get("/api/echo")
            assert resp.getheader("Access-Control-Allow-Origin") is None
        finally:
            live.close()


class TestPortSelection:
    def test_port_in_use_skips_to_next(self, web_root):
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        busy_port = occupied.getsockname()[1]
        try:
            server, port = webbridge.create_server(
                str(web_root), _echo_handler,
                ports=range(busy_port, busy_port + 3))
            webbridge.start_server_thread(server)
            try:
                assert port != busy_port
                assert port in (busy_port + 1, busy_port + 2)
            finally:
                webbridge.stop_server(server)
        finally:
            occupied.close()

    def test_all_ports_busy_raises_oserror(self, web_root):
        s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s1.bind(("127.0.0.1", 0))
        s1.listen(1)
        p1 = s1.getsockname()[1]

        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.bind(("127.0.0.1", p1 + 1))
        s2.listen(1)
        try:
            with pytest.raises(OSError):
                webbridge.create_server(
                    str(web_root), _echo_handler, ports=range(p1, p1 + 2))
        finally:
            s1.close()
            s2.close()


class TestServerLifecycle:
    def test_start_server_thread_returns_daemon_thread(self, web_root):
        live = _LiveServer(web_root)
        try:
            assert isinstance(live.thread, threading.Thread)
            assert live.thread.daemon is True
            assert live.thread.is_alive()
        finally:
            live.close()

    def test_stop_server_is_idempotent(self, web_root):
        live = _LiveServer(web_root)
        webbridge.stop_server(live.server)
        # Calling it again must not raise.
        webbridge.stop_server(live.server)

    def test_stop_server_before_start_does_not_hang(self, web_root):
        # create_server() without start_server_thread() means serve_forever
        # never ran; stop_server must still return instead of blocking
        # forever on shutdown()'s wait for a loop that will never notice it.
        server, _port = webbridge.create_server(str(web_root), _echo_handler)
        webbridge.stop_server(server)
