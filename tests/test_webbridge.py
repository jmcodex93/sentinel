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


class TestMainThreadQueueCancellation:
    """T1 of UI Phase 4: a timed-out submit() must mark its request
    cancelled BEFORE raising, and a later drain() must skip it — a
    client-abandoned request never executes late, which is what makes
    mutation ops (not just reads) safe to route through this queue.
    """

    def test_timeout_then_late_drain_never_dispatches(self):
        # (1) submit with a tiny timeout, no drain in between -> TimeoutError.
        q = webbridge.MainThreadQueue()
        with pytest.raises(TimeoutError):
            q.submit({"op": "abandoned"}, timeout=0.05)

        # Then drain with a spy dispatch -> spy is NOT called, and nothing
        # is left waiting on a stale result.
        calls = []
        q.drain(lambda payload: calls.append(payload))
        assert calls == []

    def test_happy_path_unchanged_after_cancellation_support(self):
        # (2) happy path: a request that IS drained before its timeout
        # still gets dispatched and returns the real result normally.
        q = webbridge.MainThreadQueue()
        results = {}

        def worker():
            results["value"] = q.submit({"op": "ping"}, timeout=5.0)

        t = threading.Thread(target=worker)
        t.start()
        deadline = time.time() + 2.0
        while q._queue.empty() and time.time() < deadline:
            time.sleep(0.01)

        calls = []

        def dispatch(payload):
            calls.append(payload)
            return {"pong": True}

        q.drain(dispatch)
        t.join(timeout=5.0)
        assert not t.is_alive()
        assert results["value"] == {"pong": True}
        assert calls == [{"op": "ping"}]

    def test_manually_cancelled_request_is_skipped_by_drain(self):
        # (3a) race guard, deterministic form: mark cancelled directly
        # between enqueue and drain (no live timing needed) -> drain must
        # skip it exactly like the real submit-timeout path does.
        q = webbridge.MainThreadQueue()
        request = webbridge._QueuedRequest({"op": "x"})
        request.cancelled = True
        q._queue.put(request)

        calls = []
        q.drain(lambda payload: calls.append(payload))

        assert calls == []
        assert request.result is None
        assert not request.event.is_set()

    def test_cancel_race_loses_to_in_flight_dispatch_no_half_dispatch(self):
        # (3b) drain-mid-flight semantics: if dispatch has already started
        # (committed under request.lock) by the time submit's timeout
        # fires and tries to cancel, the cancel must NOT win and must NOT
        # observe a half-dispatched state — submit blocks on the lock and
        # then returns the real dispatched result instead of raising
        # TimeoutError.
        q = webbridge.MainThreadQueue()
        dispatch_started = threading.Event()
        release_dispatch = threading.Event()

        def slow_dispatch(payload):
            dispatch_started.set()
            assert release_dispatch.wait(2.0), "test setup: dispatch never released"
            return {"ran": True}

        results = {}

        def submitter():
            try:
                results["value"] = q.submit({"op": "slow"}, timeout=0.05)
            except TimeoutError as exc:
                results["error"] = exc

        submit_thread = threading.Thread(target=submitter)
        submit_thread.start()

        deadline = time.time() + 2.0
        while q._queue.empty() and time.time() < deadline:
            time.sleep(0.01)

        drain_thread = threading.Thread(target=q.drain, args=(slow_dispatch,))
        drain_thread.start()

        assert dispatch_started.wait(2.0), "dispatch never started"
        # Dispatch is now in flight, holding request.lock. Give submit's
        # 0.05s timeout time to fire and attempt its cancel -- it must
        # block on the lock rather than racing ahead of the dispatch.
        time.sleep(0.2)
        release_dispatch.set()

        drain_thread.join(timeout=2.0)
        submit_thread.join(timeout=2.0)

        assert "error" not in results
        assert results["value"] == {"ran": True}


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


# ---------------------------------------------------------------------------
# qc_report_payload — qc.score.compute_score() -> SPA contract
# ---------------------------------------------------------------------------

def _violation(check_id, path, message, sibling_index=0, guid=None, extras=None):
    """One qc/results.py Violation.to_dict()-shaped dict."""
    v = {
        "check_id": check_id,
        "identity": {"type": "object", "path": path, "sibling_index": sibling_index,
                     "guid": guid},
        "message": message,
    }
    if extras is not None:
        v["extras"] = extras
    return v


def _structured(check_id, violations):
    """A CheckResult-shaped plain dict (CheckResult IS a dict subclass)."""
    return {"check_id": check_id, "violations": violations, "metadata": {}}


def _legacy_score_fixture(counts=None, disabled=None):
    """Shaped like qc.score._legacy_score()'s return (no baseline sidecar)."""
    counts = counts or {}
    disabled = disabled or []
    total = 12 - len(disabled)
    passed = total - sum(1 for v in counts.values() if v)
    return {
        "score": f"{passed}/{total}",
        "pass": passed == total,
        "passed": passed,
        "total": total,
        "counts": counts,
        "disabled": disabled,
        "disabled_count": len(disabled),
    }


class TestQcReportPayload:
    def test_all_checks_mapped_from_registry_order(self):
        score = _legacy_score_fixture()
        payload = webbridge.qc_report_payload("robot_010.c4d", {}, score, {})
        assert payload["scene"] == "robot_010.c4d"
        assert [c["id"] for c in payload["checks"]] == [
            "lights", "vis", "keys", "cam", "rdc", "textures", "unused_mats",
            "names", "output", "takes", "fps_range", "cross_aspect",
        ]
        assert payload["score"] == {
            "score": "12/12", "passed": 12, "total": 12,
            "disabled_count": 0, "baseline_status": None,
        }
        assert payload["disabled"] == []

    def test_failing_check_status_and_severity_from_registry(self):
        score = _legacy_score_fixture(counts={"lights": 3})
        structured = {"lights": _structured("lights", [
            _violation("lights", "/Rig/Key Light", "Light outside lights group"),
        ])}
        payload = webbridge.qc_report_payload("scene.c4d", {}, score, structured)
        lights_row = next(c for c in payload["checks"] if c["id"] == "lights")
        assert lights_row["status"] == "fail"
        assert lights_row["severity"] == "FAIL"  # registry default for "lights"
        assert lights_row["has_fix"] is True
        assert lights_row["count"] == 3
        assert lights_row["new"] is None  # no baseline in this fixture
        assert lights_row["accepted"] is None
        assert lights_row["details"] == [
            {"label": "/Rig/Key Light", "message": "Light outside lights group",
             "extras": None},
        ]

    def test_passing_check_status_ok_and_no_details(self):
        score = _legacy_score_fixture(counts={"lights": 0})
        payload = webbridge.qc_report_payload("scene.c4d", {}, score, {})
        lights_row = next(c for c in payload["checks"] if c["id"] == "lights")
        assert lights_row["status"] == "ok"
        assert lights_row["details"] == []

    def test_disabled_check_status_and_null_counts(self):
        score = _legacy_score_fixture(disabled=["takes"])
        payload = webbridge.qc_report_payload("scene.c4d", {}, score, {})
        assert payload["disabled"] == ["takes"]
        takes_row = next(c for c in payload["checks"] if c["id"] == "takes")
        assert takes_row["status"] == "disabled"
        assert takes_row["count"] is None
        assert takes_row["new"] is None
        assert takes_row["accepted"] is None
        assert takes_row["details"] == []

    def test_baseline_present_uses_new_counts_and_baseline_matches(self):
        score = {
            "score": "11/12", "pass": False, "passed": 11, "total": 12,
            "counts": {"lights": 1}, "new_counts": {"lights": 1},
            "accepted_counts": {"lights": 2}, "stale_counts": {"lights": 0},
            "baseline_matches": {
                "lights": {
                    "new": [_violation("lights", "/Rig/New Light", "New violation")],
                    "accepted": [
                        _violation("lights", "/Rig/Old A", "accepted 1"),
                        _violation("lights", "/Rig/Old B", "accepted 2"),
                    ],
                },
            },
            "baseline_status": "ok", "baseline_path": "/scene_baseline.json",
            "disabled": [], "disabled_count": 0, "schema": 2,
            "new": 1, "accepted": 2, "stale": 0,
        }
        structured = {"lights": _structured("lights", [
            _violation("lights", "/Rig/New Light", "New violation"),
            _violation("lights", "/Rig/Old A", "accepted 1"),
            _violation("lights", "/Rig/Old B", "accepted 2"),
        ])}
        payload = webbridge.qc_report_payload("scene.c4d", {}, score, structured)
        assert payload["score"]["baseline_status"] == "ok"
        lights_row = next(c for c in payload["checks"] if c["id"] == "lights")
        assert lights_row["count"] == 1
        assert lights_row["new"] == 1
        assert lights_row["accepted"] == 2
        # Only the "new" baseline diff surfaces in details, not the accepted ones.
        assert len(lights_row["details"]) == 1
        assert lights_row["details"][0]["label"] == "/Rig/New Light"

    def test_ruleset_mapped_with_severity_override(self):
        score = _legacy_score_fixture(counts={"vis": 1})
        ruleset = {
            "name": "sentinel_rules.json", "path": "/project/sentinel_rules.json",
            "shadowed": ["/parent/sentinel_rules.json"],
            "severity_overrides": {"vis": "FAIL"},
        }
        payload = webbridge.qc_report_payload("scene.c4d", ruleset, score, {})
        assert payload["ruleset"] == {
            "name": "sentinel_rules.json", "path": "/project/sentinel_rules.json",
            "shadowed": ["/parent/sentinel_rules.json"],
        }
        vis_row = next(c for c in payload["checks"] if c["id"] == "vis")
        assert vis_row["severity"] == "FAIL"  # overridden from registry default WARN

    def test_no_ruleset_defaults_to_defaults_name(self):
        score = _legacy_score_fixture()
        payload = webbridge.qc_report_payload("scene.c4d", None, score, None)
        assert payload["ruleset"] == {"name": "defaults", "path": None, "shadowed": []}

    def test_details_capped_at_fifty(self):
        violations = [
            _violation("names", f"/Cube.{i}", "Default name") for i in range(75)
        ]
        score = _legacy_score_fixture(counts={"names": 75})
        structured = {"names": _structured("names", violations)}
        payload = webbridge.qc_report_payload("scene.c4d", {}, score, structured)
        names_row = next(c for c in payload["checks"] if c["id"] == "names")
        assert names_row["count"] == 75
        assert len(names_row["details"]) == 50

    def test_non_dict_violation_never_raises(self):
        score = _legacy_score_fixture(counts={"lights": 1})
        structured = {"lights": _structured("lights", ["not-a-dict"])}
        payload = webbridge.qc_report_payload("scene.c4d", {}, score, structured)
        lights_row = next(c for c in payload["checks"] if c["id"] == "lights")
        assert lights_row["details"] == [
            {"label": "", "message": "not-a-dict", "extras": None}]

    def test_empty_score_never_raises(self):
        payload = webbridge.qc_report_payload("", None, {}, None)
        assert payload["scene"] == ""
        assert len(payload["checks"]) == 12
        assert payload["disabled"] == []


# ---------------------------------------------------------------------------
# doctor_report_payload — doctor.run_all_diagnostics() -> SPA contract
# ---------------------------------------------------------------------------

def _doctor_items_fixture():
    """Shaped like doctor.py's item builders (_item()) — anonymized values."""
    return [
        {"id": "c4d_version", "label": "Cinema 4D version", "status": "ok",
         "detail": "Cinema 4D 2026 (raw 2026301)", "hint": "Tested and supported."},
        {"id": "payload", "label": "Plugin payload integrity", "status": "fail",
         "detail": "Missing at /opt/sentinel: res/description", "hint": "Reinstall."},
        {"id": "renderers", "label": "Renderers detected", "status": "info",
         "detail": "No supported renderer detected.", "hint": ""},
    ]


def _doctor_meta_fixture():
    """Shaped like doctor.run_all_diagnostics()'s meta dict."""
    return {
        "sentinel_version": "1.13.0",
        "c4d_version": "2026",
        "os": "macOS 15.1 (arm64)",
        "renderers": "",
        "settings_path": "/Users/artist/Library/Preferences/Sentinel/sentinel_settings.json",
    }


class TestDoctorReportPayload:
    def test_items_and_meta_mapped(self):
        payload = webbridge.doctor_report_payload(_doctor_items_fixture(), _doctor_meta_fixture())
        assert payload["meta"]["sentinel_version"] == "1.13.0"
        assert payload["meta"]["os"] == "macOS 15.1 (arm64)"
        assert len(payload["items"]) == 3
        assert payload["items"][1] == {
            "id": "payload", "label": "Plugin payload integrity", "status": "fail",
            "detail": "Missing at /opt/sentinel: res/description", "hint": "Reinstall.",
        }

    def test_empty_items_and_meta_never_raises(self):
        payload = webbridge.doctor_report_payload([], {})
        assert payload["items"] == []
        assert payload["meta"] == {
            "sentinel_version": "", "c4d_version": "", "os": "",
            "renderers": "", "settings_path": "",
        }

    def test_none_inputs_never_raise(self):
        payload = webbridge.doctor_report_payload(None, None)
        assert payload["items"] == []
        assert payload["meta"]["sentinel_version"] == ""


# ---------------------------------------------------------------------------
# supervisor_report_payload — supervisor.scan_folder() -> SPA contract
# ---------------------------------------------------------------------------

def _supervisor_shots_fixture():
    """Shaped like supervisor.build_shot_summary()'s return — anonymized."""
    return [
        {
            "base": "robot_010", "folder": "/projects/demo/robot_010",
            "history_path": "/projects/demo/robot_010/robot_010_history.json",
            "version_count": 5, "last_version": "v005", "status": "TR",
            "score": "10/12", "qc_label": "10/12", "todos_total": 3,
            "todos_pending": 1, "notes_text": "waiting on client notes",
            "days_idle": 1, "last_timestamp": "2026-07-15 10:00:00",
            "artist": "Motioneer", "flags": ["regression"],
            "version_rows": [{"version": "v005", "status": "TR", "score": "10/12",
                              "qc_label": "10/12"}],
            "trajectory": [{"from_version": "v004", "to_version": "v005",
                            "broke": ["Lights"], "recovered": [], "no_data": False}],
        },
        {
            "base": "robot_020", "folder": "/projects/demo/robot_020",
            "history_path": "/projects/demo/robot_020/robot_020_history.json",
            "version_count": 1, "last_version": "v001", "status": "",
            "score": "12/12", "qc_label": "12/12", "todos_total": 0,
            "todos_pending": 0, "notes_text": "", "days_idle": 9,
            "last_timestamp": "2026-07-07 09:00:00", "artist": "Motioneer",
            "flags": ["stale"], "version_rows": [], "trajectory": [],
        },
    ]


def _supervisor_meta_fixture():
    return {"folder": "/projects/demo", "generated": "2026-07-16 18:00:00",
            "shot_count": 2, "warnings": []}


class TestSupervisorReportPayload:
    def test_folder_and_shots_mapped(self):
        payload = webbridge.supervisor_report_payload(
            _supervisor_shots_fixture(), _supervisor_meta_fixture())
        assert payload["folder"] == "/projects/demo"
        assert payload["generated_at"] == "2026-07-16 18:00:00"
        assert payload["shot_count"] == 2
        assert payload["warnings"] == []
        assert len(payload["shots"]) == 2
        first = payload["shots"][0]
        assert first["base"] == "robot_010"
        assert first["last_version"] == "v005"
        assert first["status"] == "TR"
        assert first["flags"] == ["regression"]
        assert first["trajectory"] == [
            {"from_version": "v004", "to_version": "v005",
             "broke": ["Lights"], "recovered": [], "no_data": False}]
        # Dropped on purpose (see docstring): not part of the mapped shot.
        assert "history_path" not in first
        assert "notes_text" not in first

    def test_warnings_and_empty_scan_mapped(self):
        payload = webbridge.supervisor_report_payload(
            [], {"folder": "/projects/empty", "generated": "2026-07-16 18:00:00",
                 "shot_count": 0, "warnings": ["Corrupted: /projects/empty/x_history.json"]})
        assert payload["shots"] == []
        assert payload["warnings"] == ["Corrupted: /projects/empty/x_history.json"]

    def test_none_inputs_never_raise(self):
        payload = webbridge.supervisor_report_payload(None, None)
        assert payload["shots"] == []
        assert payload["folder"] == ""


# ---------------------------------------------------------------------------
# render_validation_payload — postrender.build_report() -> SPA contract
# ---------------------------------------------------------------------------

def _render_report_fixture(**overrides):
    """Shaped exactly like postrender.build_report()'s return."""
    base = {
        "schema": 1,
        "type": "sentinel_render_report",
        "generated_at": "2026-07-16T18:42:07Z",
        "passed": False,
        "summary": {"failures": 2, "warnings": 1, "streams": 3, "manifest_entries": 3},
        "context": {"take_name": "16x9", "version": "v022", "frame_start": 1001,
                     "frame_end": 1100, "frame_mode": "Manual", "manifest_entries": 3},
        "checks": {
            "missing": {"status": "FAIL", "count": 2, "label": "Missing frames",
                        "items": [{"frame": 1050, "stream": "Beauty"},
                                  {"frame": 1051, "stream": "Beauty"}]},
            "stale": {"status": "WARN", "count": 1, "label": "Stale frames",
                      "items": [{"frame": 1002, "stream": "Beauty"}]},
            "zero_byte": {"status": "OK", "count": 0, "label": "Zero-byte frames",
                          "items": []},
        },
    }
    base.update(overrides)
    return base


class TestRenderValidationPayload:
    def test_full_report_mapped(self):
        payload = webbridge.render_validation_payload(
            _render_report_fixture(), "/projects/demo/robot_010_sentinel_render_report.json")
        assert payload["report_path"] == (
            "/projects/demo/robot_010_sentinel_render_report.json")
        assert payload["generated_at"] == "2026-07-16T18:42:07Z"
        assert payload["passed"] is False
        assert payload["context"] == {
            "take_name": "16x9", "version": "v022", "frame_start": 1001,
            "frame_end": 1100, "frame_mode": "Manual",
        }
        assert payload["summary"] == {"failures": 2, "warnings": 1, "streams": 3}
        checks_by_id = {c["id"]: c for c in payload["checks"]}
        assert checks_by_id["missing"]["status"] == "FAIL"
        assert checks_by_id["missing"]["count"] == 2
        assert len(checks_by_id["missing"]["items"]) == 2
        assert checks_by_id["zero_byte"]["status"] == "OK"

    def test_passed_report_mapped(self):
        payload = webbridge.render_validation_payload(
            _render_report_fixture(passed=True, summary={"failures": 0, "warnings": 0,
                                                          "streams": 1, "manifest_entries": 1}),
            "path")
        assert payload["passed"] is True
        assert payload["summary"]["failures"] == 0

    def test_empty_report_never_raises(self):
        payload = webbridge.render_validation_payload({}, "/some/path.json")
        assert payload == {
            "report_path": "/some/path.json",
            "generated_at": "",
            "passed": False,
            "context": {"take_name": "", "version": "", "frame_start": None,
                        "frame_end": None, "frame_mode": ""},
            "summary": {"failures": 0, "warnings": 0, "streams": 0},
            "checks": [],
        }

    def test_none_report_never_raises(self):
        payload = webbridge.render_validation_payload(None, "/some/path.json")
        assert payload["passed"] is False
        assert payload["checks"] == []


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


# ---------------------------------------------------------------------------
# Save Version form — validate_save_version_submit / resolve_save_version_status
# ---------------------------------------------------------------------------

class TestResolveSaveVersionStatus:
    def test_custom_status_wins_over_combo_status(self):
        assert webbridge.resolve_save_version_status("TR", "pitch v2") == "PITCHV2"

    def test_falls_back_to_combo_status_when_custom_empty(self):
        assert webbridge.resolve_save_version_status("CR", "   ") == "CR"

    def test_both_empty_is_wip(self):
        assert webbridge.resolve_save_version_status("", "") == ""
        assert webbridge.resolve_save_version_status(None, None) == ""


class TestValidateSaveVersionSubmit:
    def test_empty_comment_is_rejected(self):
        result = webbridge.validate_save_version_submit({"comment": "   "})
        assert result == {
            "ok": False,
            "error": "Please enter a comment describing this version.",
        }

    def test_missing_comment_key_is_rejected(self):
        result = webbridge.validate_save_version_submit({})
        assert result["ok"] is False

    def test_valid_comment_normalizes_fields(self):
        result = webbridge.validate_save_version_submit({
            "comment": "  rim lights pass  ",
            "status": "TR",
            "custom_status": "",
            "run_qc": False,
        })
        assert result == {
            "ok": True,
            "comment": "rim lights pass",
            "status": "TR",
            "run_qc": False,
            "warning": None,
        }

    def test_run_qc_defaults_true_when_absent(self):
        result = webbridge.validate_save_version_submit({"comment": "ok"})
        assert result["run_qc"] is True

    def test_final_in_comment_is_a_non_blocking_warning(self):
        result = webbridge.validate_save_version_submit({
            "comment": "This is the FINAL pass",
        })
        assert result["ok"] is True
        assert result["warning"] == webbridge.SAVE_VERSION_FINAL_HINT

    def test_final_substring_case_insensitive(self):
        result = webbridge.validate_save_version_submit({"comment": "final."})
        assert result["warning"] is not None

    def test_no_final_no_warning(self):
        result = webbridge.validate_save_version_submit({"comment": "lookdev pass"})
        assert result["warning"] is None

    def test_custom_status_takes_priority_in_full_submit(self):
        result = webbridge.validate_save_version_submit({
            "comment": "ok", "status": "TR", "custom_status": "PITCH",
        })
        assert result["status"] == "PITCH"


class TestSaveVersionStatusOptions:
    def test_matches_versioning_status_options(self):
        options = webbridge.save_version_status_options()
        assert options[0] == {"label": "Work in Progress (WIP)", "suffix": ""}
        assert {"label": "Final Delivery", "suffix": "FINAL"} in options
        assert len(options) == 4


# ---------------------------------------------------------------------------
# Notes form — merge_notes_submission
# ---------------------------------------------------------------------------

def _notes_fixture():
    return {
        "scene": "robot_010",
        "updated": "2026-07-01 10:00:00",
        "notes": "old text",
        "todos": [
            {"id": 1, "text": "rig fix", "done": False, "added": "2026-07-01 10:00:00"},
            {"id": 2, "text": "already done", "done": True,
             "added": "2026-07-01 09:00:00", "completed": "2026-07-01 09:30:00"},
        ],
    }


class TestMergeNotesSubmission:
    def test_notes_text_replaced_and_stripped(self):
        merged = webbridge.merge_notes_submission(_notes_fixture(), "  new text  ", [])
        assert merged["notes"] == "new text"

    def test_none_original_falls_back_to_empty_notes(self):
        merged = webbridge.merge_notes_submission(None, "hello", [])
        assert merged["notes"] == "hello"
        assert merged["todos"] == []

    def test_does_not_mutate_original(self):
        original = _notes_fixture()
        webbridge.merge_notes_submission(original, "changed", [])
        assert original["notes"] == "old text"

    def test_existing_todo_text_is_never_edited(self):
        submitted = [{"id": 1, "text": "renamed text", "done": False}]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        assert merged["todos"][0]["text"] == "rig fix"

    def test_toggling_done_stamps_completed(self):
        submitted = [
            {"id": 1, "text": "rig fix", "done": True},
            {"id": 2, "text": "already done", "done": True},
        ]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        todo1 = next(t for t in merged["todos"] if t["id"] == 1)
        assert todo1["done"] is True
        assert "completed" in todo1
        # id 2 was already done and submitted done=True -> untouched.
        todo2 = next(t for t in merged["todos"] if t["id"] == 2)
        assert todo2["completed"] == "2026-07-01 09:30:00"

    def test_toggling_done_to_false_removes_completed(self):
        submitted = [
            {"id": 1, "text": "rig fix", "done": False},
            {"id": 2, "text": "already done", "done": False},
        ]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        todo2 = next(t for t in merged["todos"] if t["id"] == 2)
        assert "completed" not in todo2

    def test_id_missing_from_submission_is_deleted(self):
        submitted = [{"id": 1, "text": "rig fix", "done": False}]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        assert [t["id"] for t in merged["todos"]] == [1]

    def test_new_todo_without_id_is_added(self):
        submitted = [
            {"id": 1, "text": "rig fix", "done": False},
            {"id": 2, "text": "already done", "done": True},
            {"text": "brand new todo", "done": False},
        ]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        assert len(merged["todos"]) == 3
        new_todo = merged["todos"][-1]
        assert new_todo["text"] == "brand new todo"
        assert new_todo["id"] == 3
        assert new_todo["done"] is False

    def test_new_todo_submitted_already_done_is_toggled_on(self):
        submitted = [{"text": "born done", "done": True}]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        # existing ids 1+2 dropped (not in submission), only the new one remains
        assert len(merged["todos"]) == 1
        new_todo = merged["todos"][0]
        assert new_todo["done"] is True
        assert "completed" in new_todo

    def test_blank_text_items_are_skipped(self):
        submitted = [{"text": "   ", "done": False}]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        assert merged["todos"] == []

    def test_non_dict_item_is_skipped_never_raises(self):
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", ["not-a-dict", None])
        assert merged["todos"] == []

    def test_string_id_from_json_is_normalized(self):
        # A JS client could round-trip an id as a string; must still match.
        submitted = [{"id": "1", "text": "rig fix", "done": False}]
        merged = webbridge.merge_notes_submission(_notes_fixture(), "x", submitted)
        assert len(merged["todos"]) == 1
        assert merged["todos"][0]["id"] == 1

    def test_empty_original_and_empty_submission_returns_empty_todos(self):
        merged = webbridge.merge_notes_submission(_notes_fixture(), "", [])
        assert merged["todos"] == []
        assert merged["notes"] == ""


# ---------------------------------------------------------------------------
# Settings form — validate_settings_submit
# ---------------------------------------------------------------------------

class TestValidateSettingsSubmit:
    def test_full_valid_payload_maps_every_field(self):
        updates = webbridge.validate_settings_submit({
            "fps": 30,
            "compositor": 1,
            "multipart_default": True,
            "slate": True,
            "mv_max_motion": 42,
            "snapshot_dir": "/Volumes/cache/snaps",
            "history_max": 10,
        })
        assert updates == {
            "standard_fps": 30,
            "comp_target": 1,
            "aov_multipart": 1,
            "snapshot_slate": True,
            "mv_max_motion": 42,
            "snapshot_dir": "/Volumes/cache/snaps",
            "history_max_rows": 10,
        }

    def test_fps_locked_never_writes_standard_fps(self):
        updates = webbridge.validate_settings_submit({"fps": 60}, fps_locked=True)
        assert "standard_fps" not in updates

    def test_snapshot_dir_locked_never_writes_snapshot_dir(self):
        updates = webbridge.validate_settings_submit(
            {"snapshot_dir": "/tmp/x"}, snapshot_dir_locked=True)
        assert "snapshot_dir" not in updates

    def test_out_of_range_fps_is_skipped_not_errored(self):
        updates = webbridge.validate_settings_submit({"fps": 23})
        assert "standard_fps" not in updates

    def test_non_numeric_fps_is_skipped(self):
        updates = webbridge.validate_settings_submit({"fps": "not-a-number"})
        assert "standard_fps" not in updates

    def test_out_of_range_compositor_is_skipped(self):
        updates = webbridge.validate_settings_submit({"compositor": 5})
        assert "comp_target" not in updates

    def test_out_of_range_history_max_is_skipped(self):
        updates = webbridge.validate_settings_submit({"history_max": 999})
        assert "history_max_rows" not in updates

    def test_negative_mv_max_motion_is_clamped_to_zero(self):
        updates = webbridge.validate_settings_submit({"mv_max_motion": -5})
        assert updates["mv_max_motion"] == 0

    def test_blank_snapshot_dir_never_overwrites(self):
        updates = webbridge.validate_settings_submit({"snapshot_dir": "   "})
        assert "snapshot_dir" not in updates

    def test_multipart_default_false_still_written(self):
        updates = webbridge.validate_settings_submit({"multipart_default": False})
        assert updates["aov_multipart"] == 0

    def test_empty_payload_yields_no_updates(self):
        assert webbridge.validate_settings_submit({}) == {}


# ---------------------------------------------------------------------------
# Gate form — gate_state_payload / gate_can_proceed
# ---------------------------------------------------------------------------

def _gate_item(check_id, new_count=1, blocks=False, violations=None):
    return {
        "check_id": check_id,
        "nivel": "x",
        "blocks": blocks,
        "new_count": new_count,
        "violations": violations or [],
    }


class TestGateStatePayload:
    def test_maps_bucket_label_severity_and_violations(self):
        gate_result = {
            "fixable": [_gate_item("lights", new_count=2, blocks=True,
                                    violations=[_violation("lights", "Null/Cube", "stray light")])],
            "blocking": [],
            "advisory": [],
            "passed": False,
        }
        payload = webbridge.gate_state_payload(gate_result, sidecar_invalid=False)
        assert payload["passed"] is False
        assert payload["sidecar_invalid"] is False
        assert len(payload["checks"]) == 1
        check = payload["checks"][0]
        assert check["check_id"] == "lights"
        assert check["label"] == "Lights"
        assert check["severity"] == "FAIL"
        assert check["bucket"] == "fixable"
        assert check["blocks"] is True
        assert check["has_fix"] is True
        assert check["new_count"] == 2
        assert check["violations"][0]["label"] == "Null/Cube"

    def test_unknown_check_id_falls_back_to_raw_id(self):
        gate_result = {"fixable": [], "blocking": [_gate_item("not_a_real_check")],
                        "advisory": [], "passed": False}
        payload = webbridge.gate_state_payload(gate_result)
        check = payload["checks"][0]
        assert check["label"] == "not_a_real_check"
        assert check["severity"] == ""
        assert check["has_fix"] is False

    def test_empty_gate_result_never_raises(self):
        payload = webbridge.gate_state_payload({})
        assert payload == {"passed": True, "sidecar_invalid": False, "checks": []}

    def test_none_gate_result_never_raises(self):
        payload = webbridge.gate_state_payload(None)
        assert payload["checks"] == []


class TestGateCanProceed:
    def test_passes_when_no_blocking_and_no_blocking_fixable(self):
        gate_result = {
            "blocking": [],
            "fixable": [_gate_item("unused_mats", blocks=False)],
            "advisory": [_gate_item("vis", blocks=False)],
        }
        assert webbridge.gate_can_proceed(gate_result) is True

    def test_blocked_by_blocking_bucket(self):
        gate_result = {"blocking": [_gate_item("output")], "fixable": [], "advisory": []}
        assert webbridge.gate_can_proceed(gate_result) is False

    def test_blocked_by_fixable_item_that_blocks(self):
        gate_result = {
            "blocking": [],
            "fixable": [_gate_item("lights", blocks=True)],
            "advisory": [],
        }
        assert webbridge.gate_can_proceed(gate_result) is False

    def test_fixable_item_that_does_not_block_is_fine(self):
        gate_result = {
            "blocking": [],
            "fixable": [_gate_item("unused_mats", blocks=False)],
            "advisory": [],
        }
        assert webbridge.gate_can_proceed(gate_result) is True

    def test_empty_result_can_proceed(self):
        assert webbridge.gate_can_proceed({}) is True
        assert webbridge.gate_can_proceed(None) is True


# ---------------------------------------------------------------------------
# Command palette — palette_actions_payload
# ---------------------------------------------------------------------------

class TestPaletteActionsPayload:
    def _by_id(self, actions):
        return {a["id"]: a for a in actions}

    def test_every_registered_action_id_present(self):
        actions = webbridge.palette_actions_payload(doc_present=True, doc_saved=True)
        ids = {a["id"] for a in actions}
        assert ids == {a["id"] for a in webbridge.PALETTE_ACTIONS}

    def test_no_doc_disables_doc_requiring_actions(self):
        actions = self._by_id(
            webbridge.palette_actions_payload(doc_present=False))
        assert actions["open_hub"]["enabled"] is False
        assert actions["open_hub"]["reason"] == "No active document"
        assert actions["fix_lights"]["enabled"] is False
        # Doesn't require a doc -> stays enabled even with no doc.
        assert actions["open_reports_qc"]["enabled"] is True
        assert actions["settings"]["enabled"] is True

    def test_unsaved_doc_disables_edit_notes_only(self):
        actions = self._by_id(webbridge.palette_actions_payload(
            doc_present=True, doc_saved=False))
        assert actions["edit_notes"]["enabled"] is False
        assert actions["edit_notes"]["reason"] == "Save the scene to a folder first"
        # save_version only requires a doc, not a saved path.
        assert actions["save_version"]["enabled"] is True

    def test_quick_fix_disabled_when_nothing_to_fix(self):
        actions = self._by_id(webbridge.palette_actions_payload(
            doc_present=True, doc_saved=True,
            qc_counts={"lights": 0, "cam": 3, "unused_mats": 0, "fps_range": 0}))
        assert actions["fix_lights"]["enabled"] is False
        assert actions["fix_lights"]["reason"] == "Nothing to fix"
        assert actions["fix_cameras"]["enabled"] is True
        assert actions["fix_cameras"]["reason"] is None
        assert actions["fix_materials"]["enabled"] is False

    def test_missing_check_id_in_qc_counts_treated_as_zero(self):
        actions = self._by_id(webbridge.palette_actions_payload(
            doc_present=True, doc_saved=True, qc_counts={}))
        assert actions["fix_fps"]["enabled"] is False

    def test_rescan_qc_only_needs_a_document(self):
        actions = self._by_id(webbridge.palette_actions_payload(
            doc_present=True, doc_saved=False, qc_counts={}))
        assert actions["rescan_qc"]["enabled"] is True
