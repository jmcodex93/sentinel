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
