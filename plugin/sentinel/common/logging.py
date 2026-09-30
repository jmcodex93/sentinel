# -*- coding: utf-8 -*-
"""Failure-proof structured logging for the Cinema 4D console."""

import datetime
import json
import math
import traceback as _traceback


_PREFIX = "[Sentinel] "
_UNREPRESENTABLE = "<unrepresentable>"
_MAX_DEPTH = 12


def _safe_text(value):
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return _UNREPRESENTABLE


def _safe_value(value, seen=None, depth=0):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _safe_text(value)
    if depth >= _MAX_DEPTH:
        return "<max-depth>"

    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return "<recursive>"

    if isinstance(value, dict):
        seen.add(value_id)
        try:
            converted = {}
            for key, item in value.items():
                converted[_safe_text(key)] = _safe_value(
                    item, seen, depth + 1
                )
            return converted
        except Exception:
            return _safe_text(value)
        finally:
            seen.discard(value_id)

    if isinstance(value, (list, tuple)):
        seen.add(value_id)
        try:
            return [_safe_value(item, seen, depth + 1) for item in value]
        except Exception:
            return _safe_text(value)
        finally:
            seen.discard(value_id)

    return _safe_text(value)


def _timestamp():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def emit(level, event, component, **fields):
    """Emit one deterministic JSON line; logging failures never escape."""
    try:
        payload = {
            "ts": _timestamp(),
            "level": _safe_text(level).upper(),
            "event": _safe_text(event),
            "component": _safe_text(component),
            "fields": _safe_value(fields),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        try:
            print(_PREFIX + encoded)
        except Exception:
            pass
    except Exception:
        pass


def debug(event, component, **fields):
    return emit("DEBUG", event, component, **fields)


def info(event, component, **fields):
    return emit("INFO", event, component, **fields)


def warning(event, component, **fields):
    return emit("WARNING", event, component, **fields)


def error(event, component, **fields):
    return emit("ERROR", event, component, **fields)


def exception(event, component, exc, **fields):
    """Emit a caught exception with its traceback kept in local console data."""
    try:
        exception_type = type(exc).__name__
    except Exception:
        exception_type = _UNREPRESENTABLE
    exception_message = _safe_text(exc)
    try:
        formatted = "".join(
            _traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    except Exception:
        formatted = _UNREPRESENTABLE
    fields.update({
        "exception_type": exception_type,
        "exception_message": exception_message,
        "traceback": formatted,
    })
    return emit("ERROR", event, component, **fields)
