# -*- coding: utf-8 -*-
"""Common helper functions."""

import os
import subprocess
import sys

from .logging import info as _log_info


def safe_print(msg):
    """Compatibility console logger; new code should emit named events."""
    if msg is None:
        return
    try:
        message = str(msg)
    except Exception:
        message = "<unrepresentable>"
    _log_info("legacy.message", "legacy", message=message)


def open_in_explorer(path):
    """Open a file or folder in the system file manager (cross-platform)"""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        safe_print(f"Could not open path: {path} - {e}")


def _safe_name(obj):
    """Get object name safely, returns 'unknown' if object is dead"""
    try:
        return obj.GetName() or "unnamed"
    except Exception:
        return "unknown"


def _iter_objs(op, max_count=None):
    """Optimized object iterator with limit"""
    count = 0
    stack = [op]

    while stack and (max_count is None or count < max_count):
        current = stack.pop()
        if current is None:
            continue

        yield current
        count += 1

        child = current.GetDown()
        if child:
            stack.append(child)

        sibling = current.GetNext()
        if sibling:
            stack.append(sibling)


def _any_ancestor_named(o, names_lower):
    """Check if any ancestor has one of the specified names"""
    if not o:
        return False

    p = o.GetUp()
    depth = 0
    max_depth = 100

    while p and depth < max_depth:
        try:
            nm = (p.GetName() or "").strip().lower()
            if nm in names_lower:
                return True
        except Exception:
            pass
        p = p.GetUp()
        depth += 1
    return False
