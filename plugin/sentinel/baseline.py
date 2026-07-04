# -*- coding: utf-8 -*-
"""Pure Python baseline sidecar engine for accepted QC violations."""

import getpass
import json
import os
import re


SCHEMA_VERSION = 1
STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_INVALID = "invalid"

_VERSION_RE = re.compile(r"_v(\d+)(?:_([A-Za-z][A-Za-z0-9]*))?$", re.IGNORECASE)
_MISSING = object()


def _parse_version_filename(name_no_ext):
    # duplicated from .pyp parse_version_filename; consolidate in U10
    if not name_no_ext:
        return "", None, None
    match = _VERSION_RE.search(name_no_ext)
    if match:
        base = name_no_ext[: match.start()]
        try:
            version = int(match.group(1))
        except ValueError:
            return name_no_ext, None, None
        status = match.group(2)
        status = status.upper() if status else None
        if base:
            return base, version, status
    return name_no_ext, None, None


def get_baseline_path(doc_path):
    """Return the per-scene baseline sidecar path for a saved scene path."""
    if not doc_path:
        return None
    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _version, _status = _parse_version_filename(name_no_ext)
    if not base:
        base = name_no_ext or "scene"
    return os.path.join(folder, f"{base}_baseline.json")


def load_baseline(path):
    """Load baseline entries and return (entries, status)."""
    if not path or not os.path.exists(path):
        return [], STATUS_MISSING
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return [], STATUS_INVALID

    if not isinstance(data, dict):
        return [], STATUS_INVALID
    if data.get("schema") != SCHEMA_VERSION:
        return [], STATUS_INVALID
    entries = data.get("entries")
    if not isinstance(entries, list):
        return [], STATUS_INVALID
    if not all(isinstance(entry, dict) for entry in entries):
        return [], STATUS_INVALID
    return entries, STATUS_OK


def add_acceptance(path, entry):
    """Merge one accepted entry into the on-disk baseline."""
    if not isinstance(entry, dict):
        return False
    entries, status = load_baseline(path)
    if status == STATUS_INVALID:
        return False

    merged = {}
    for existing in entries:
        merged[_entry_key(existing)] = existing
    merged[_entry_key(entry)] = entry
    return _write_entries(path, list(merged.values()))


def remove_acceptance(path, key):
    """Remove one accepted entry by identity key or entry-like dict."""
    entries, status = load_baseline(path)
    if status == STATUS_INVALID:
        return False

    remove_key = _entry_key(key)
    kept = [entry for entry in entries if _entry_key(entry) != remove_key]
    return _write_entries(path, kept)


def find_conflict_copies(path):
    """Return cloud-sync conflict-copy siblings for a baseline path."""
    if not path:
        return []
    folder = os.path.dirname(path) or "."
    if not os.path.isdir(folder):
        return []

    target_name = os.path.basename(path)
    stem, ext = os.path.splitext(target_name)
    stem_lower = stem.lower()
    ext_lower = ext.lower()
    conflict_paths = []
    for name in os.listdir(folder):
        if name == target_name:
            continue
        candidate_stem, candidate_ext = os.path.splitext(name)
        lower_name = name.lower()
        if ext_lower and candidate_ext.lower() != ext_lower:
            continue
        if stem_lower not in candidate_stem.lower():
            continue
        if (
            "conflicted copy" in lower_name
            or "conflict copy" in lower_name
            or "synologydrive-conflict" in lower_name
            or "synology drive conflict" in lower_name
            or "sync-conflict" in lower_name
            or "sync conflict" in lower_name
        ):
            conflict_paths.append(os.path.join(folder, name))
    return sorted(conflict_paths)


def merge_conflict_copies(path):
    """Union valid conflict-copy entries into the main baseline without deleting copies."""
    copy_paths = find_conflict_copies(path)
    entries, status = load_baseline(path)
    if status == STATUS_INVALID:
        return 0, copy_paths

    merged = {}
    for entry in entries:
        merged[_entry_key(entry)] = entry

    merged_count = 0
    for copy_path in copy_paths:
        copy_entries, copy_status = load_baseline(copy_path)
        if copy_status == STATUS_INVALID:
            continue
        for entry in copy_entries:
            key = _entry_key(entry)
            if key not in merged:
                merged_count += 1
            merged[key] = entry

    if copy_paths:
        if not _write_entries(path, list(merged.values())):
            return 0, copy_paths
    return merged_count, copy_paths


def match_violations(entries, violations, current_params=None):
    """Split current violations into new, accepted, and stale baseline entries."""
    current_params = current_params or {}
    result = {"new": [], "accepted": [], "stale_entries": []}
    stale_keys = set()

    baseline_entries = [entry for entry in entries if isinstance(entry, dict)]

    for violation in violations or []:
        if not isinstance(violation, dict):
            result["new"].append(violation)
            continue

        match = _find_matching_entry(baseline_entries, violation, current_params, result, stale_keys)
        if match is not None:
            result["accepted"].append(violation)
        else:
            result["new"].append(violation)

    return result


def resolve_author(artist_name):
    """Return a non-empty artist name, falling back to the OS user."""
    if isinstance(artist_name, str) and artist_name.strip():
        return artist_name
    return getpass.getuser()


def _write_entries(path, entries):
    if not path:
        return False
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    payload = {"schema": SCHEMA_VERSION, "entries": entries}
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False
    return True


def _find_matching_entry(entries, violation, current_params, result, stale_keys):
    check_id = violation.get("check_id")
    identity = violation.get("identity") or {}
    kind = _identity_kind(identity)

    if kind == "object":
        return _find_object_match(entries, check_id, identity, result, stale_keys)
    if kind == "param":
        return _find_param_match(entries, check_id, identity, current_params, result, stale_keys)
    return None


def _find_object_match(entries, check_id, identity, result, stale_keys):
    exact_without_guid = []
    guid_mismatches = []
    moved_or_renamed = []

    for entry in entries:
        if entry.get("check_id") != check_id:
            continue
        entry_identity = entry.get("identity") or {}
        if _identity_kind(entry_identity) != "object":
            continue
        if _fmt_id(entry_identity) != _fmt_id(identity):
            continue

        same_location = (
            entry_identity.get("path") == identity.get("path")
            and entry_identity.get("sibling_index") == identity.get("sibling_index")
        )
        entry_guid = entry_identity.get("guid")
        violation_guid = identity.get("guid")

        if same_location:
            if not entry_guid or entry_guid == violation_guid:
                exact_without_guid.append(entry)
            elif violation_guid:
                guid_mismatches.append(entry)
        elif entry_guid and violation_guid and entry_guid == violation_guid:
            moved_or_renamed.append(entry)

    if exact_without_guid:
        return exact_without_guid[0]

    for stale in guid_mismatches + moved_or_renamed:
        _append_stale(result, stale_keys, stale)
    return None


def _find_param_match(entries, check_id, identity, current_params, result, stale_keys):
    matches = []
    for entry in entries:
        if entry.get("check_id") != check_id:
            continue
        entry_identity = entry.get("identity") or {}
        if _identity_kind(entry_identity) != "param":
            continue
        if _param_identity_key(entry_identity) == _param_identity_key(identity):
            matches.append(entry)

    for entry in matches:
        snapshot = entry.get("param_snapshot")
        if snapshot is None:
            return entry
        current_value = _current_param_value(entry.get("identity") or identity, current_params)
        if current_value is not _MISSING and current_value == snapshot:
            return entry

    for stale in matches:
        if stale.get("param_snapshot") is not None:
            _append_stale(result, stale_keys, stale)
    return None


def _append_stale(result, stale_keys, entry):
    key = _entry_key(entry)
    if key in stale_keys:
        return
    stale_keys.add(key)
    result["stale_entries"].append(entry)


def _entry_key(entry):
    if isinstance(entry, tuple):
        return entry
    if not isinstance(entry, dict):
        return ("raw", _stable_value(entry))

    if "identity" in entry:
        check_id = entry.get("check_id")
        identity = entry.get("identity") or {}
    else:
        check_id = entry.get("check_id")
        identity = entry

    kind = _identity_kind(identity)
    if kind == "object":
        return (
            "object",
            check_id,
            identity.get("path"),
            identity.get("sibling_index"),
            identity.get("guid"),
            _fmt_id(identity),
        )
    if kind == "param":
        return ("param", check_id) + _param_identity_key(identity)
    return ("unknown", check_id, _stable_value(identity))


def _identity_kind(identity):
    raw = identity.get("kind", identity.get("type")) if isinstance(identity, dict) else None
    if raw == "parameter":
        return "param"
    return raw


def _fmt_id(identity):
    return identity.get("fmt_id") if isinstance(identity, dict) else None


def _param_identity_key(identity):
    return (
        identity.get("param"),
        identity.get("preset"),
        identity.get("take"),
        identity.get("field"),
        _stable_value(identity.get("value", _MISSING)),
    )


def _current_param_value(identity, current_params):
    if not isinstance(current_params, dict):
        return _MISSING

    param = identity.get("param")
    preset = identity.get("preset")
    take = identity.get("take")
    field = identity.get("field")

    for key in (
        (param, preset, take, field),
        (param, preset, field),
        (param, take, field),
        (param, field),
        param,
    ):
        if key in current_params:
            return current_params[key]

    value = current_params.get(param, _MISSING)
    for child_key in (preset, take, field):
        if child_key is None:
            continue
        if not isinstance(value, dict) or child_key not in value:
            return _MISSING
        value = value[child_key]
    return value


def _stable_value(value):
    if value is _MISSING:
        return ("__missing__",)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(value)
