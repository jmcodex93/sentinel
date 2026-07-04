# -*- coding: utf-8 -*-
"""Structured QC result values."""

import c4d

from sentinel.common.cache import check_cache


def _safe_json(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, set):
        return sorted(_safe_json(item) for item in value)
    return str(value)


def _safe_name(item):
    try:
        return item.GetName() or "unnamed"
    except Exception:
        return "unknown"


def _safe_guid(item):
    try:
        guid = item.GetGUID()
    except Exception:
        return None
    return _safe_json(guid)


def _siblings_for(obj):
    siblings = []
    try:
        parent = obj.GetUp()
    except Exception:
        parent = None

    if parent:
        try:
            current = parent.GetDown()
        except Exception:
            current = None
    else:
        current = obj
        depth = 0
        while current is not None and depth < 1000:
            try:
                previous = current.GetPred()
            except Exception:
                previous = None
            if previous is None:
                break
            current = previous
            depth += 1

    depth = 0
    while current is not None and depth < 1000:
        siblings.append(current)
        try:
            current = current.GetNext()
        except Exception:
            current = None
        depth += 1

    return siblings or [obj]


def _sibling_position(obj):
    name = _safe_name(obj)
    same_name = []
    for sibling in _siblings_for(obj):
        if _safe_name(sibling) == name:
            same_name.append(sibling)

    index = 0
    for i, sibling in enumerate(same_name):
        if sibling is obj:
            index = i
            break

    return index, len(same_name)


def _path_component(obj):
    name = _safe_name(obj)
    sibling_index, sibling_count = _sibling_position(obj)
    if sibling_count > 1:
        return f"{name}[{sibling_index}]", sibling_index
    return name, sibling_index


def object_identity(obj):
    """Return a JSON-safe identity for a C4D object."""
    hierarchy = []
    current = obj
    depth = 0
    while current is not None and depth < 100:
        hierarchy.append(current)
        try:
            current = current.GetUp()
        except Exception:
            current = None
        depth += 1

    hierarchy.reverse()
    components = []
    sibling_index = 0
    for item in hierarchy:
        component, sibling_index = _path_component(item)
        components.append(component)

    path = "/" + "/".join(components) if components else "/unknown"
    return {
        "type": "object",
        "path": path,
        "sibling_index": sibling_index,
        "guid": _safe_guid(obj),
    }


def material_identity(material):
    """Return a JSON-safe identity for a material-like BaseList2D."""
    return {
        "type": "material",
        "name": _safe_name(material),
        "guid": _safe_guid(material),
    }


def legacy_items(result):
    return result.to_legacy()


def structured_cache_key(legacy_key):
    return f"{legacy_key}_structured"


def cached_result(doc, legacy_key, builder):
    cached_structured = check_cache.get(doc, structured_cache_key(legacy_key))
    if cached_structured is not None:
        return cached_structured

    cached = check_cache.get(doc, legacy_key)
    if cached is not None:
        return builder(cached)

    return None


def store_result(doc, legacy_key, legacy_value, result):
    check_cache.set(doc, legacy_key, legacy_value)
    check_cache.set(doc, structured_cache_key(legacy_key), result)
    return result


def param_identity(param_name, offending_value, preset=None, take=None, field=None):
    """Return a JSON-safe identity for a parametric violation."""
    data = {
        "type": "parameter",
        "param": str(param_name),
        "value": _safe_json(offending_value),
    }
    if preset is not None:
        data["preset"] = str(preset)
    if take is not None:
        data["take"] = str(take)
    if field is not None:
        data["field"] = str(field)
    return data


class Violation(dict):
    def __init__(self, check_id, identity, message, extras=None):
        self.check_id = check_id
        self.identity = identity
        self.message = message
        self.extras = extras or {}
        super().__init__(self.to_dict())

    def to_dict(self):
        data = {
            "check_id": self.check_id,
            "identity": _safe_json(self.identity),
            "message": str(self.message),
        }
        if self.extras:
            data["extras"] = _safe_json(self.extras)
        return data


class CheckResult(dict):
    def __init__(self, check_id, violations=None, metadata=None, legacy_items=None):
        self.check_id = check_id
        self.violations = violations if violations is not None else []
        self.metadata = metadata if metadata is not None else {}
        self.legacy_items = legacy_items if legacy_items is not None else []
        super().__init__(self.to_dict())

    def add_violation(self, identity, message, extras=None):
        violation = Violation(
            check_id=self.check_id,
            identity=identity,
            message=message,
            extras=extras or {},
        )
        self.violations.append(violation)
        self["violations"] = self.violations

    def to_dict(self):
        return {
            "check_id": self.check_id,
            "violations": [violation.to_dict() for violation in self.violations],
            "metadata": _safe_json(self.metadata),
        }

    def to_legacy(self):
        return self.legacy_items
