# -*- coding: utf-8 -*-
"""Sentinel Doctor — environment self-diagnostic (feature I6).

Follows the postrender.py pattern: the core is stdlib-only and PURE (item
builders take faked inputs so pytest can cover them without Cinema 4D), while
every real read of the live C4D environment happens in a thin adapter where
``import c4d`` is function-local and guarded. Nothing here mutates the scene.

Produces a list of diagnostic items, each a dict:
    {"id", "label", "status" (ok|warn|fail|info), "detail", "hint"}
plus a copyable plain-text report suitable for pasting into a GitHub issue.

The optional update check (`check_for_update`) touches the network; it is a
separate function invoked only on explicit user action, times out fast, and
degrades to an INFO item when offline — never an error.
"""

import json
import os
import platform
import sys

OK = "ok"
WARN = "warn"
FAIL = "fail"
INFO = "info"

# Cinema 4D major versions Sentinel is actively tested against.
TESTED_C4D_MAJORS = (2024, 2026)

GITHUB_OWNER_REPO = "jmcodex93/sentinel"
_RELEASES_LATEST_URL = "https://api.github.com/repos/%s/releases/latest" % GITHUB_OWNER_REPO
_TAGS_URL = "https://api.github.com/repos/%s/tags" % GITHUB_OWNER_REPO

# Critical payload paths relative to the running plugin root (the folder that
# holds sentinel_panel.pyp). Kept in sync with install.CRITICAL_PAYLOAD_PATHS.
_RES_TRIPLET = [
    os.path.join("res", "c4d_symbols.h"),
    os.path.join("res", "description"),
    os.path.join("res", "strings_us"),
]


def _item(item_id, label, status, detail="", hint=""):
    return {"id": item_id, "label": label, "status": status,
            "detail": detail, "hint": hint}


# ── Pure builders (unit-tested with faked inputs) ────────────────────────────
def parse_c4d_major(version_int):
    """Extract the major (year) from c4d.GetC4DVersion()'s int.

    Modern C4D encodes version as year*1000 + build (2026.301 -> 2026301), so
    ``// 1000`` yields the year. Legacy R-series (21000 -> 21) also survives.
    Returns None for unusable input.
    """
    try:
        v = int(version_int)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v // 1000


def build_c4d_version_item(version_int, tested=TESTED_C4D_MAJORS):
    major = parse_c4d_major(version_int)
    if major is None:
        return _item("c4d_version", "Cinema 4D version", WARN,
                     "Could not read the running Cinema 4D version.",
                     "Run Sentinel Doctor from inside Cinema 4D.")
    detail = "Cinema 4D %s (raw %s)" % (major, version_int)
    if major in tested:
        return _item("c4d_version", "Cinema 4D version", OK, detail,
                     "This version is tested and supported.")
    return _item(
        "c4d_version", "Cinema 4D version", WARN, detail,
        "Sentinel is tested on Cinema 4D %s. It may still work here, but if you "
        "hit trouble this untested version is the first thing to mention in a "
        "bug report." % " / ".join(str(t) for t in tested))


def build_payload_item(root_dir):
    """Check the running install's payload integrity (res triplet, package,
    abc_retime). ``root_dir`` is the folder containing sentinel_panel.pyp."""
    if not root_dir or not os.path.isdir(root_dir):
        return _item("payload", "Plugin payload integrity", FAIL,
                     "Plugin root not found: %s" % root_dir,
                     "Reinstall with install.py so the full folder lands together.")
    missing = []
    for rel in _RES_TRIPLET:
        if not os.path.exists(os.path.join(root_dir, rel)):
            missing.append(rel)
    if not os.path.isfile(os.path.join(root_dir, "sentinel", "__init__.py")):
        missing.append(os.path.join("sentinel", "__init__.py"))
    if not os.path.isdir(os.path.join(root_dir, "abc_retime")):
        missing.append("abc_retime")

    if not missing:
        return _item("payload", "Plugin payload integrity", OK,
                     "res/ triplet, sentinel package and abc_retime all present.",
                     "")
    return _item(
        "payload", "Plugin payload integrity", FAIL,
        "Missing at %s: %s" % (root_dir, ", ".join(missing)),
        "The install is incomplete — re-run install.py to copy the whole plugin "
        "folder (the .pyp alone is not enough).")


def build_settings_item(settings_path, legacy_path):
    """Settings file existence / readability / writability + migration state."""
    prefs_dir = os.path.dirname(settings_path) if settings_path else ""
    legacy_present = bool(legacy_path) and os.path.exists(legacy_path)

    if settings_path and os.path.exists(settings_path):
        # Readable?
        try:
            with open(settings_path, "r") as fh:
                json.load(fh)
        except Exception as exc:
            return _item(
                "settings", "Settings file", FAIL,
                "%s exists but is not readable JSON: %s" % (settings_path, exc),
                "Delete the file — Sentinel will recreate it from defaults.")
        writable = os.access(settings_path, os.W_OK)
        detail = "%s (readable%s)" % (settings_path,
                                      ", writable" if writable else ", READ-ONLY")
        if legacy_present:
            detail += " · legacy ys_guardian_settings.json still present"
        if not writable:
            return _item("settings", "Settings file", WARN, detail,
                         "Fix the file permissions so preferences can be saved.")
        return _item("settings", "Settings file", OK, detail,
                     "Legacy settings already migrated." if legacy_present else "")

    # No new settings file yet.
    if legacy_present:
        return _item(
            "settings", "Settings file", INFO,
            "No sentinel_settings.json yet; legacy %s found." % legacy_path,
            "It will be migrated automatically the first time you use Sentinel.")
    # Can we write to the prefs dir?
    if prefs_dir and os.path.isdir(prefs_dir) and os.access(prefs_dir, os.W_OK):
        return _item("settings", "Settings file", INFO,
                     "No settings file yet (will be created in %s)." % prefs_dir,
                     "")
    return _item(
        "settings", "Settings file", WARN,
        "Preferences folder not writable: %s" % prefs_dir,
        "Sentinel cannot save preferences here — check folder permissions.")


def build_renderers_item(renderers):
    """``renderers`` is a list of detected renderer name strings."""
    if renderers:
        return _item("renderers", "Renderers detected", OK,
                     "Found: %s" % ", ".join(renderers),
                     "")
    return _item(
        "renderers", "Renderers detected", INFO,
        "No supported renderer detected (Redshift is the one Sentinel probes "
        "directly; Arnold/Octane are only surfaced when their video-post "
        "plugin is loaded).",
        "If you use Redshift, make sure the Redshift plugin is installed and "
        "enabled in Cinema 4D.")


def build_python_item(python_path):
    """External Python (for the EXR->PNG converter)."""
    if python_path and os.path.exists(python_path):
        return _item("ext_python", "External Python (EXR converter)", OK,
                     "Found: %s" % python_path,
                     "")
    return _item(
        "ext_python", "External Python (EXR converter)", WARN,
        "No system Python 3 with OpenEXR + numpy + Pillow was found.",
        "Snapshot EXR->PNG conversion needs it. Install with: "
        "pip3 install OpenEXR numpy Pillow")


def build_write_permission_item(item_id, label, path):
    """Generic writability probe for a directory (prefs dir, scene dir)."""
    if not path:
        return _item(item_id, label, INFO, "Not applicable (no path).", "")
    if os.path.isdir(path) and os.access(path, os.W_OK):
        return _item(item_id, label, OK, "Writable: %s" % path, "")
    if not os.path.isdir(path):
        return _item(item_id, label, WARN, "Folder does not exist: %s" % path,
                     "Save the scene, or check the path exists.")
    return _item(item_id, label, WARN, "Not writable: %s" % path,
                 "Check folder permissions — Sentinel cannot write here.")


def compare_versions(current, latest):
    """Compare two dotted version strings (v-prefix tolerated).

    Returns "current" (up to date / ahead) or "outdated" (latest > current) or
    "unknown" when either can't be parsed.
    """
    cur = _version_tuple(current)
    lat = _version_tuple(latest)
    if cur is None or lat is None:
        return "unknown"
    if lat > cur:
        return "outdated"
    return "current"


def _version_tuple(value):
    if not value:
        return None
    text = str(value).strip().lstrip("vV")
    parts = text.split(".")
    nums = []
    for part in parts:
        # Keep only the leading integer portion of each segment.
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            return None
        nums.append(int(digits))
    return tuple(nums) if nums else None


def build_update_item(current_version, latest_version, error=None):
    if error:
        # C4D's embedded Python commonly lacks CA certificates, so HTTPS
        # verification fails even when online — give the right hint for that
        # case instead of blaming the connection (verified live, C4D 2026.301).
        if "CERTIFICATE" in error.upper() or "SSL" in error.upper():
            return _item("update", "Update check", INFO,
                         "Could not verify GitHub's certificate — Cinema 4D's "
                         "embedded Python has no CA certificates on this machine.",
                         "Check manually: github.com/%s/releases" % GITHUB_OWNER_REPO)
        return _item("update", "Update check", INFO,
                     "Could not reach GitHub: %s" % error,
                     "This is fine offline — retry when you have a connection.")
    state = compare_versions(current_version, latest_version)
    if state == "outdated":
        return _item(
            "update", "Update check", INFO,
            "A newer release is available: %s (you have %s)."
            % (latest_version, current_version),
            "Download the latest release and re-run install.py.")
    if state == "current":
        return _item("update", "Update check", OK,
                     "Sentinel %s is up to date (latest %s)."
                     % (current_version, latest_version),
                     "")
    return _item("update", "Update check", INFO,
                 "Could not compare versions (current %s, latest %s)."
                 % (current_version, latest_version),
                 "")


# ── Copyable report ──────────────────────────────────────────────────────────
_STATUS_TAG = {OK: "[OK]  ", WARN: "[WARN]", FAIL: "[FAIL]", INFO: "[INFO]"}


def build_copyable_report(items, meta):
    """Assemble a plain-text diagnostic block for a bug report.

    ``meta`` is a dict with keys: sentinel_version, c4d_version, os, renderers,
    settings_path. Any missing key degrades gracefully.
    """
    lines = ["Sentinel Doctor report", "=" * 30]
    lines.append("Sentinel version : %s" % meta.get("sentinel_version", "?"))
    lines.append("Cinema 4D        : %s" % meta.get("c4d_version", "?"))
    lines.append("OS               : %s" % meta.get("os", "?"))
    lines.append("Renderers        : %s" % (meta.get("renderers") or "none detected"))
    lines.append("Settings path    : %s" % meta.get("settings_path", "?"))
    lines.append("-" * 30)
    for it in items:
        tag = _STATUS_TAG.get(it.get("status"), "[??]  ")
        lines.append("%s %s" % (tag, it.get("label", "")))
        detail = it.get("detail")
        if detail:
            lines.append("       %s" % detail)
        hint = it.get("hint")
        if hint and it.get("status") in (WARN, FAIL):
            lines.append("       hint: %s" % hint)
    return "\n".join(lines)


# ── Thin C4D adapter (function-local, guarded imports) ───────────────────────
def get_running_root():
    """Folder containing sentinel_panel.pyp (two levels up from this module)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_c4d_version_int():
    try:
        import c4d
        return c4d.GetC4DVersion()
    except Exception:
        return None


def get_settings_paths():
    """(settings_path, legacy_path) for the running C4D prefs, or ('','')."""
    try:
        import c4d
        from sentinel.common.constants import LEGACY_SETTINGS_FILE, SETTINGS_FILE
        prefs = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
        return (os.path.join(prefs, SETTINGS_FILE),
                os.path.join(prefs, LEGACY_SETTINGS_FILE))
    except Exception:
        return ("", "")


def detect_renderers():
    """Return a list of renderer names detected in the running C4D.

    Redshift is probed by module import (the way Sentinel already talks to it).
    Arnold/Octane are surfaced only when their video-post render plugin is
    loaded — cheap and robust, no hardcoded plugin ids required.
    """
    found = []
    # Redshift: module import guard (matches the rest of the codebase).
    try:
        import redshift  # noqa: F401
        found.append("Redshift")
    except Exception:
        pass

    try:
        import c4d
        plugin_list = c4d.plugins.FilterPluginList(c4d.PLUGINFLAG_VIDEOPOST, True) or []
        names = []
        for plug in plugin_list:
            try:
                names.append(plug.GetName() or "")
            except Exception:
                continue
        joined = " ".join(names).lower()
        if "redshift" in joined and "Redshift" not in found:
            found.append("Redshift")
        if "arnold" in joined:
            found.append("Arnold")
        if "octane" in joined:
            found.append("Octane")
    except Exception:
        pass

    # Dedup, preserve order.
    seen = set()
    ordered = []
    for name in found:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def discover_external_python():
    """Reuse the snapshot converter's Python discovery. Returns path or None."""
    try:
        from sentinel import snapshots
        return snapshots._find_system_python()
    except Exception:
        return None


def get_scene_dir():
    """Directory of the active saved document, or '' when unsaved/unavailable."""
    try:
        import c4d
        doc = c4d.documents.GetActiveDocument()
        path = doc.GetDocumentPath() if doc else ""
        return path or ""
    except Exception:
        return ""


def get_sentinel_version():
    try:
        from sentinel import PLUGIN_VERSION
        return PLUGIN_VERSION
    except Exception:
        return "unknown"


def os_label():
    try:
        return "%s %s (%s)" % (platform.system(), platform.release(),
                               platform.machine())
    except Exception:
        return sys.platform


def run_all_diagnostics():
    """Run every non-network diagnostic against the live environment.

    Returns (items, meta). Safe to call from the UI thread; each adapter guards
    its own c4d access so a missing API degrades to WARN/INFO, never a crash.
    """
    version_int = get_c4d_version_int()
    root = get_running_root()
    settings_path, legacy_path = get_settings_paths()
    renderers = detect_renderers()
    python_path = discover_external_python()
    scene_dir = get_scene_dir()
    prefs_dir = os.path.dirname(settings_path) if settings_path else ""

    items = [
        build_c4d_version_item(version_int),
        build_payload_item(root),
        build_settings_item(settings_path, legacy_path),
        build_renderers_item(renderers),
        build_python_item(python_path),
        build_write_permission_item("perm_prefs", "Prefs folder writable", prefs_dir),
    ]
    if scene_dir:
        items.append(build_write_permission_item(
            "perm_scene", "Scene folder writable", scene_dir))
    else:
        items.append(_item("perm_scene", "Scene folder writable", INFO,
                           "No saved scene open.",
                           "Save the scene to check its folder is writable."))

    meta = {
        "sentinel_version": get_sentinel_version(),
        "c4d_version": ("%s" % parse_c4d_major(version_int)) if version_int else "?",
        "os": os_label(),
        "renderers": ", ".join(renderers) if renderers else "",
        "settings_path": settings_path or "?",
    }
    return items, meta


def check_for_update(current_version=None, timeout=3):
    """Explicit, opt-in update check against GitHub releases. NEVER automatic.

    One GET to the releases/latest endpoint (falls back to the tags list), short
    timeout, stdlib urllib only. Returns a diagnostic item; any network failure
    degrades to an INFO item so being offline is never an error.
    """
    import urllib.request

    if current_version is None:
        current_version = get_sentinel_version()

    def _fetch(url):
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Sentinel-Doctor",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    latest = None
    error = None
    try:
        data = _fetch(_RELEASES_LATEST_URL)
        latest = data.get("tag_name") or data.get("name")
        if not latest:
            raise ValueError("no tag in latest release")
    except Exception as exc:
        # Fall back to the tags list (repos with no formal "release").
        try:
            tags = _fetch(_TAGS_URL)
            if isinstance(tags, list) and tags:
                latest = tags[0].get("name")
            if not latest:
                raise ValueError("no tags")
        except Exception as exc2:
            error = str(exc2) or str(exc)

    return build_update_item(current_version, latest, error=error)
