# -*- coding: utf-8 -*-
"""Batch Rename engine (v1.31) — PURE, no ``import c4d``.

``rename_plan`` drives BOTH the SPA preview and the apply op — WYSIWYG by
construction, not by discipline. Pipeline order is fixed: (1) pattern (when
non-empty it replaces the whole name; tokens ``$name``/``$parent``/``$type``
are expanded BEFORE ``$n`` so the counter substitution can't corrupt them),
(2) literal find/replace (case-insensitive unless ``match_case``; the
replacement goes through a lambda so backslashes stay literal — the v1.5.7
repathing lesson), (3) prefix/suffix. Collisions (duplicate FINAL names
within the batch) are flagged, never blocking — C4D allows duplicate names;
Sentinel warns, the artist decides.
"""

import re

DEFAULT_OPS = {
    "pattern": "",
    "find": "",
    "replace": "",
    "match_case": False,
    "prefix": "",
    "suffix": "",
    "num_start": 1,
    "num_padding": 3,
}

MAX_PADDING = 8


def _as_str(value, default=""):
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _as_int(value, default, low, high):
    try:
        value = int(value)
    except Exception:
        return default
    return max(low, min(high, value))


def normalize_ops(raw):
    """Merge a possibly-partial/malformed payload over DEFAULT_OPS."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "pattern": _as_str(raw.get("pattern", "")),
        "find": _as_str(raw.get("find", "")),
        "replace": _as_str(raw.get("replace", "")),
        "match_case": bool(raw.get("match_case", False)),
        "prefix": _as_str(raw.get("prefix", "")),
        "suffix": _as_str(raw.get("suffix", "")),
        "num_start": _as_int(raw.get("num_start", 1), 1, 0, 10 ** 9),
        "num_padding": _as_int(raw.get("num_padding", 3), 3, 0, MAX_PADDING),
    }


def ops_is_noop(ops):
    return not (ops["pattern"] or ops["find"] or ops["prefix"] or ops["suffix"])


def _expand_pattern(pattern, item, counter, padding):
    out = pattern
    out = out.replace("$name", item.get("name") or "")
    out = out.replace("$parent", item.get("parent") or "")
    out = out.replace("$type", item.get("type_name") or "")
    out = out.replace("$n", str(counter).zfill(padding))
    return out


def rename_plan(items, ops):
    """[{"old", "new", "collision"}] for ``items`` in their given order."""
    rows = []
    for index, item in enumerate(items or []):
        name = item.get("name") or ""
        new = name
        if ops["pattern"]:
            new = _expand_pattern(
                ops["pattern"], item, ops["num_start"] + index, ops["num_padding"])
        if ops["find"]:
            flags = 0 if ops["match_case"] else re.IGNORECASE
            new = re.sub(
                re.escape(ops["find"]), lambda _m: ops["replace"], new, flags=flags)
        new = ops["prefix"] + new + ops["suffix"]
        rows.append({"old": name, "new": new, "collision": False})

    counts = {}
    for row in rows:
        counts[row["new"]] = counts.get(row["new"], 0) + 1
    for row in rows:
        row["collision"] = counts[row["new"]] > 1
    return rows
