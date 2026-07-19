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


# ---------------------------------------------------------------------------
# delivery_report_payload — sentinel_manifest.json -> SPA contract
# ---------------------------------------------------------------------------

def _manifest_fixture(**overrides):
    """A manifest dict shaped like a real v1.10+ sentinel_manifest.json
    (anonymized: real field names/shapes, fictional shot/artist names) —
    mirrors plugin/sentinel/ui/flows.py's ``manifest`` dict after
    ``manifest_engine.merge_into_manifest``."""
    base = {
        "sentinel_manifest": True,
        "version": "Sentinel v1.13.0",
        "timestamp": "2026-07-16 18:42:07",
        "scene": "robot_010.c4d",
        "original_filename": "robot_010_v022_FINAL.c4d",
        "original_version": 22,
        "original_status": "FINAL",
        "artist": "Motioneer",
        "shot_id": "Main",
        "collected_to": "/Users/artist/Desktop/Sentinel/CollectedHUB",
        "assets_collected": 11,
        "assets_missing": 2,
        "missing_list": [],
        "pre_flight_issues": [],
        "qc": {"score": "9/12", "passed": 9, "total": 12, "new": 3,
               "accepted": 0, "stale": 0, "schema": 2,
               "disabled_checks": [], "disabled_count": 0, "checks": []},
        "notes": {"summary": "Notes: 2 TODOs", "text": "", "todos": [],
                   "pending_count": 2, "updated": ""},
        "total_size_mb": 12.4,
        "assets_schema": 1,
        "scan_status": "ok",
        "assets": [
            {"path": "tex/body_basecolor.jpg", "original_path": "relative:///body_basecolor.jpg",
             "source_type": "rs_node", "channel": "path", "host": "Body Shell",
             "state": "collected", "hash": None},
            {"path": "file:///X:/assets/robot_gen2/tex/grip_detail.png",
             "original_path": "file:///X:/assets/robot_gen2/tex/grip_detail.png",
             "source_type": "rs_node", "channel": "path", "host": "Hand Grip",
             "state": "missing", "hash": None},
            {"path": "D:/library/hdri/studio_soft_4k.hdr",
             "original_path": "D:/library/hdri/studio_soft_4k.hdr",
             "source_type": "rs_object_fileref", "channel": "Dome HDR",
             "host": "HDR Key", "state": "missing", "hash": None},
            {"path": "/Volumes/Shared/refs/robot_010_turntable.abc",
             "original_path": "/Volumes/Shared/refs/robot_010_turntable.abc",
             "source_type": "alembic", "channel": "cache",
             "host": "Turntable Rig", "state": "external", "hash": None},
        ],
        "asset_summary": {"total": 4, "collected": 1, "missing": 2, "external": 1},
        "required_plugins": [{"plugin_id": 1036222, "name": "RS Object"}],
        "plugin_inventory_scope": "objects+tags+materials",
    }
    base.update(overrides)
    return base


class TestDeliveryReportPayload:
    def test_full_manifest_maps_every_field(self):
        manifest_dict = _manifest_fixture()
        payload = webbridge.delivery_report_payload(
            manifest_dict, "/Users/artist/Desktop/Sentinel/CollectedHUB/sentinel_manifest.json")

        assert payload["scene"] == "robot_010.c4d"
        assert payload["collected_at"] == "2026-07-16 18:42:07"
        assert payload["artist"] == "Motioneer"
        assert payload["version"] == "v022"
        assert payload["qc"] == {"score": "9/12", "passed": 9, "total": 12}
        assert payload["summary"] == {"total": 4, "collected": 1, "missing": 2, "external": 1}
        assert payload["zip"] is None
        assert payload["pending_todos"] == 2
        assert payload["manifest_path"] == (
            "/Users/artist/Desktop/Sentinel/CollectedHUB/sentinel_manifest.json")

    def test_assets_mapped_with_status_and_provenance(self):
        payload = webbridge.delivery_report_payload(_manifest_fixture(), "path")
        assets = payload["assets"]
        assert len(assets) == 4

        assert assets[0] == {
            "path": "tex/body_basecolor.jpg",
            "status": "collected",
            "provenance": "material · Body Shell",
        }
        assert assets[1]["status"] == "missing"
        assert assets[1]["provenance"] == "material · Hand Grip"
        # rs_object_fileref: channel ("Dome HDR") stands in for the category.
        assert assets[2]["provenance"] == "Dome HDR · HDR Key"
        assert assets[3]["provenance"] == "alembic cache · Turntable Rig"

    def test_missing_qc_section_maps_to_none_not_keyerror(self):
        manifest_dict = _manifest_fixture()
        del manifest_dict["qc"]
        payload = webbridge.delivery_report_payload(manifest_dict, "path")
        assert payload["qc"] is None

    def test_missing_original_version_maps_to_none(self):
        payload = webbridge.delivery_report_payload(
            _manifest_fixture(original_version=None), "path")
        assert payload["version"] is None

    def test_empty_manifest_dict_never_raises_and_fills_defaults(self):
        payload = webbridge.delivery_report_payload({}, "/some/path.json")
        assert payload == {
            "scene": "",
            "collected_at": "",
            "artist": "",
            "version": None,
            "qc": None,
            "summary": {"total": 0, "collected": 0, "missing": 0, "external": 0},
            "zip": None,
            "assets": [],
            "pending_todos": 0,
            "manifest_path": "/some/path.json",
        }

    def test_none_manifest_dict_never_raises(self):
        payload = webbridge.delivery_report_payload(None, "/some/path.json")
        assert payload["scene"] == ""
        assert payload["assets"] == []

    def test_zip_section_mapped_when_present(self):
        manifest_dict = _manifest_fixture(
            zip={"zip_path": "/deliveries/robot_010.zip", "files": 4, "bytes": 123456})
        payload = webbridge.delivery_report_payload(manifest_dict, "path")
        assert payload["zip"] == {"path": "/deliveries/robot_010.zip", "bytes": 123456}

    def test_notes_missing_defaults_pending_todos_to_zero(self):
        manifest_dict = _manifest_fixture()
        del manifest_dict["notes"]
        payload = webbridge.delivery_report_payload(manifest_dict, "path")
        assert payload["pending_todos"] == 0


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
