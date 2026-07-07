# -*- coding: utf-8 -*-
"""Version filename and history sidecar helpers."""

import json
import os
import re as _re

try:
    from sentinel.common.helpers import safe_print
except ModuleNotFoundError:
    def safe_print(*args, **kwargs):
        print(*args, **kwargs)

# ---------------- Smart Incremental Save (versioning + history) ----------------
# Pure helpers — no UI, no document mutation. Tested via reasoning + step-by-step verification.
import re as _re

# Version + optional status tag suffix (e.g. _v003, _v003_TR, _v003_CR, _v003_PITCH).
# Status must be alphanumeric (letters first); we sanitize on write.
_VERSION_RE = _re.compile(r'_v(\d+)(?:_([A-Za-z][A-Za-z0-9]*))?$', _re.IGNORECASE)

# Mograph-native review status tags. Convention from Matthew Creed / community.
STATUS_NONE = ""        # WIP — no suffix
STATUS_TR = "TR"        # Team Review
STATUS_CR = "CR"        # Client Review
STATUS_FINAL = "FINAL"  # Final Delivery

# (combo_label, suffix). Order = combobox order.
STATUS_OPTIONS = [
    ("Work in Progress (WIP)",   STATUS_NONE),
    ("Team Review (TR)",         STATUS_TR),
    ("Client Review (CR)",       STATUS_CR),
    ("Final Delivery",           STATUS_FINAL),
]


def _sanitize_status(status):
    """Strip non-alphanumeric chars; uppercase. Returns "" if nothing left."""
    if not status:
        return ""
    cleaned = _re.sub(r'[^A-Za-z0-9]', '', status).upper()
    return cleaned


def parse_version_filename(name_no_ext):
    """Parse a basename (no extension) into (base, version_int, status_or_None).

    Examples:
      'scene_v003'        -> ('scene', 3, None)
      'scene_v003_TR'     -> ('scene', 3, 'TR')
      'robot_010_v014_CR' -> ('robot_010', 14, 'CR')
      'scene'             -> ('scene', None, None)
      'scene_v'           -> ('scene_v', None, None)
    """
    if not name_no_ext:
        return "", None, None
    m = _VERSION_RE.search(name_no_ext)
    if m:
        base = name_no_ext[:m.start()]
        try:
            ver = int(m.group(1))
        except ValueError:
            return name_no_ext, None, None
        status = m.group(2)
        status = status.upper() if status else None
        if base:
            return base, ver, status
    return name_no_ext, None, None


def build_versioned_filename(base, version, status=None, extension="c4d"):
    """('scene', 3) -> 'scene_v003.c4d'
       ('scene', 3, 'TR') -> 'scene_v003_TR.c4d'
    """
    if not base:
        base = "scene"
    suffix = ""
    cleaned = _sanitize_status(status)
    if cleaned:
        suffix = f"_{cleaned}"
    return f"{base}_v{int(version):03d}{suffix}.{extension}"


def get_history_path(doc_path):
    """Return the sidecar history JSON path for a given .c4d file path.

    Strips any '_v###[_status]' suffix so all versions of the same scene share one history.
    Returns None if doc_path is empty.
    """
    if not doc_path:
        return None
    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _ver, _status = parse_version_filename(name_no_ext)
    return os.path.join(folder, f"{base}_history.json")


def render_history_path(doc_path):
    """Return the version-stripped render validation sidecar path."""
    if not doc_path:
        return None
    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _ver, _status = parse_version_filename(name_no_ext)
    return os.path.join(folder, f"{base}_render_history.json")


def load_history(history_path):
    """Load history JSON. Always returns a dict with 'versions' list (empty if missing/invalid)."""
    default = {"scene": None, "versions": []}
    if not history_path or not os.path.exists(history_path):
        return default
    try:
        with open(history_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict) or "versions" not in data or not isinstance(data["versions"], list):
            safe_print(f"History file malformed, ignoring: {history_path}")
            return default
        return data
    except Exception as e:
        safe_print(f"Could not load history: {e}")
        return default


def save_history(history_path, history_data):
    """Write history JSON. Returns True/False."""
    if not history_path:
        return False
    try:
        with open(history_path, 'w') as f:
            json.dump(history_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        safe_print(f"Could not save history: {e}")
        return False


def compute_next_version(doc_path):
    """Determine the next version number to use, given the current document path.

    Looks at:
      - The current filename's version (if it follows _v### pattern)
      - All sibling files in the folder matching <base>_v###*.c4d (status tag ignored)
    Returns (base_name, next_version_int).

    If no current path, returns (None, 1) — caller must prompt for base name.
    """
    if not doc_path:
        return None, 1

    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _current_v, _current_s = parse_version_filename(name_no_ext)

    # Scan folder for max existing version with this base — status tag ignored
    max_ver = 0
    if os.path.isdir(folder):
        try:
            for f in os.listdir(folder):
                if not f.lower().endswith('.c4d'):
                    continue
                f_name = os.path.splitext(f)[0]
                f_base, f_ver, _f_status = parse_version_filename(f_name)
                if f_base == base and f_ver is not None:
                    if f_ver > max_ver:
                        max_ver = f_ver
        except Exception as e:
            safe_print(f"Error scanning folder for versions: {e}")

    return base, max_ver + 1


def append_history_entry(history_path, entry):
    """Add a new version entry to the history JSON. Creates file if missing."""
    history = load_history(history_path)
    if "versions" not in history:
        history["versions"] = []
    # Newest first
    history["versions"].insert(0, entry)
    # Keep "scene" name updated for clarity
    if entry.get("scene"):
        history["scene"] = entry["scene"]
    return save_history(history_path, history)


def get_latest_version_info(doc):
    """Read the latest version entry from the doc's history sidecar.

    Returns the dict for the most recent version, or None if no history exists.
    """
    if not doc:
        return None
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path or not doc_name:
        return None
    full_path = os.path.join(doc_path, doc_name)
    history_path = get_history_path(full_path)
    if not history_path or not os.path.exists(history_path):
        return None
    history = load_history(history_path)
    versions = history.get("versions") or []
    return versions[0] if versions else None


def load_versions_for_doc(doc):
    """Read the full versions list (newest first) from the doc's sidecar history.

    Returns [] if no doc, no path, or no history file. Always returns a list.
    """
    if not doc:
        return []
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path or not doc_name:
        return []
    full_path = os.path.join(doc_path, doc_name)
    history_path = get_history_path(full_path)
    if not history_path or not os.path.exists(history_path):
        return []
    history = load_history(history_path)
    versions = history.get("versions") or []
    return versions if isinstance(versions, list) else []


# Filter token for "show all versions" — distinct from STATUS_NONE ("") so the UI
# can have an "All" choice that's different from "WIP only".
FILTER_ALL = "__ALL__"


def filter_versions_by_status(versions, status_filter):
    """Filter a versions list by status tag.

    status_filter:
      FILTER_ALL  -> return all
      ""          -> only WIP entries (status "" or missing)
      "TR"|"CR"|"FINAL"|<custom>  -> only entries whose status matches (case-insensitive)
    """
    if not versions:
        return []
    if status_filter == FILTER_ALL:
        return list(versions)
    target = (status_filter or "").upper()
    out = []
    for entry in versions:
        s = (entry.get("status") or "").upper()
        if s == target:
            out.append(entry)
    return out


def format_history_qc_label(entry):
    """Return the QC label for a history entry, marking old score schema."""
    if not isinstance(entry, dict):
        return ""
    score = entry.get("qc_score", "") or ""
    if not score:
        return ""
    if entry.get("schema") != 2:
        return f"{score} (legacy)"

    new_count = int(entry.get("new", 0) or 0)
    accepted_count = int(entry.get("accepted", 0) or 0)
    parts = [score, f"{new_count} new"]
    if accepted_count:
        parts.append(f"{accepted_count} accepted")
    return " · ".join(parts)


def format_version_row(entry):
    """Build display strings for one version entry. Returns a dict of pre-formatted parts.

    Keys:
      version_label  : 'v007'
      status_label   : 'TR' | 'CR' | 'FINAL' | 'WIP' | <custom>
      time_label     : '2h ago' | '2026-04-01' (or '')
      comment        : raw comment string (caller may truncate)
      qc_label       : '9/11' | '' if no QC was run for this entry
      qc_pass        : True | False | None
      filename       : the .c4d filename
      path           : the full saved path
    """
    if entry is None:
        return None
    try:
        ver_int = int(entry.get("version", 0))
    except Exception:
        ver_int = 0
    status = (entry.get("status") or "").upper()
    return {
        "version_label": f"v{ver_int:03d}",
        "version_int":   ver_int,
        "status_label":  status if status else "WIP",
        "time_label":    _humanize_time_diff(entry.get("timestamp", "")),
        "comment":       entry.get("comment", "") or "",
        "qc_label":      format_history_qc_label(entry),
        "qc_pass":       entry.get("qc_pass"),
        "filename":      entry.get("filename", "") or "",
        "path":          entry.get("path", "") or "",
        "artist":        entry.get("artist", "") or "",
    }


def _humanize_time_diff(timestamp_str):
    """Convert '2026-05-05 13:02:29' to a friendly relative string."""
    from datetime import datetime
    try:
        ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""
    delta = datetime.now() - ts
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days < 30:
        return f"{days}d ago"
    return ts.strftime("%Y-%m-%d")


def preview_next_filename(doc, status=None):
    """Compute what the next version filename will be, without saving."""
    if not doc:
        return None
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path:
        suggested_base = os.path.splitext(doc_name)[0] if doc_name else "scene"
        suggested_base, _v, _s = parse_version_filename(suggested_base)
        if not suggested_base or suggested_base.lower().startswith("untitled"):
            suggested_base = "scene"
        return build_versioned_filename(suggested_base, 1, status=status)
    full_doc_path = os.path.join(doc_path, doc_name) if doc_name else doc_path
    base, next_version = compute_next_version(full_doc_path)
    if not base:
        base = os.path.splitext(doc_name or "scene")[0] or "scene"
        base, _v, _s = parse_version_filename(base)
        if not base:
            base = "scene"
    return build_versioned_filename(base, next_version, status=status)
