"""Observable contract for Sentinel's best-effort console logger."""

import json


def _payload(line):
    assert line.startswith("[Sentinel] ")
    return json.loads(line[len("[Sentinel] "):])


def test_info_emits_one_deterministic_json_line(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    lines = []
    monkeypatch.setattr("builtins.print", lines.append)
    sentinel_logging.info(
        "server.started", "webbridge.http", port=8347, host="127.0.0.1"
    )

    assert len(lines) == 1
    payload = _payload(lines[0])
    assert list(payload) == ["component", "event", "fields", "level", "ts"]
    assert payload["level"] == "INFO"
    assert payload["event"] == "server.started"
    assert payload["component"] == "webbridge.http"
    assert payload["fields"] == {"host": "127.0.0.1", "port": 8347}
    assert payload["ts"].endswith("Z")
    assert "\n" not in lines[0]


def test_nested_unknown_values_and_broken_repr_never_escape(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    class Broken:
        def __repr__(self):
            raise RuntimeError("repr failed")

    lines = []
    monkeypatch.setattr("builtins.print", lines.append)
    sentinel_logging.warning(
        "value.bad", "tests", target={"items": [Broken()]}
    )

    assert _payload(lines[0])["fields"]["target"] == {
        "items": ["<unrepresentable>"]
    }


def test_console_failure_is_swallowed(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    def broken_print(_line):
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "broken")

    monkeypatch.setattr("builtins.print", broken_print)
    assert sentinel_logging.error("console.failed", "tests", value=1) is None


def test_exception_keeps_traceback_local_and_structured(monkeypatch):
    from sentinel.common import logging as sentinel_logging

    lines = []
    monkeypatch.setattr("builtins.print", lines.append)
    try:
        raise ValueError("bad payload")
    except ValueError as exc:
        sentinel_logging.exception(
            "queue.dispatch_failed", "webbridge.runtime", exc, op="panel/qc"
        )

    assert len(lines) == 1
    fields = _payload(lines[0])["fields"]
    assert fields["exception_type"] == "ValueError"
    assert fields["exception_message"] == "bad payload"
    assert "ValueError: bad payload" in fields["traceback"]
    assert fields["op"] == "panel/qc"


def test_safe_print_uses_the_legacy_structured_event(monkeypatch):
    from sentinel.common import helpers

    calls = []
    monkeypatch.setattr(
        helpers,
        "_log_info",
        lambda event, component, **fields: calls.append(
            (event, component, fields)
        ),
        raising=False,
    )
    helpers.safe_print("hello")
    assert calls == [("legacy.message", "legacy", {"message": "hello"})]


def test_safe_print_none_remains_silent(monkeypatch):
    from sentinel.common import helpers

    calls = []
    monkeypatch.setattr(
        helpers,
        "_log_info",
        lambda *args, **kwargs: calls.append((args, kwargs)),
        raising=False,
    )
    helpers.safe_print(None)
    assert calls == []
