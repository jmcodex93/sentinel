#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sentinel multi-version installer (feature I6).

Runs OUTSIDE Cinema 4D with the system Python 3 (stdlib only). Discovers every
Cinema 4D install on the machine, lets you pick one/several/all, and mirror-copies
the CONTENTS of ``plugin/`` into ``<plugins>/Sentinel/`` — the same payload and
delete-orphans semantics as ``sync.sh``, but not hardcoded to a single path.

Usage:
    python3 install.py                 # interactive picker
    python3 install.py --list          # just print discovered installs
    python3 install.py --all           # install into every discovered install
    python3 install.py --target PATH   # install into one explicit plugins dir

The discovery / label-parsing / payload-verification helpers are pure functions
(they take a root path, never touch the real machine implicitly) so they can be
unit-tested without running the CLI — see tests/test_install.py.
"""

import argparse
import os
import re
import shutil
import sys

# ── Payload description ──────────────────────────────────────────────────────
# The plugin folder whose CONTENTS get copied. The destination folder name.
PLUGIN_SRC_DIRNAME = "plugin"
DEST_FOLDER_NAME = "Sentinel"
LEGACY_DEST_FOLDER_NAME = "YS_Guardian"

# Critical paths (relative to the destination Sentinel/ root) that MUST exist
# after a copy for the payload to be considered landed. Mirrors CLAUDE.md's
# "install the full folder together" contract.
CRITICAL_PAYLOAD_PATHS = [
    "sentinel_panel.pyp",
    "sentinel",                       # the package directory
    os.path.join("sentinel", "__init__.py"),
    os.path.join("sentinel", "aovs.py"),
    os.path.join("sentinel", "postrender.py"),
    os.path.join("sentinel", "ui", "panel.py"),
    os.path.join("res", "c4d_symbols.h"),
    "exr_converter_external.py",
    "abc_retime",
]

# Case-insensitive substring that flags a Cinema 4D preferences directory.
_C4D_DIR_RE = re.compile(r"Cinema 4D\s+(\S+)", re.IGNORECASE)


# ── Pure helpers (unit-tested) ───────────────────────────────────────────────
def default_prefs_roots():
    """Return the platform's standard Cinema 4D preferences root(s).

    macOS:   ~/Library/Preferences/Maxon
    Windows: %APPDATA%/Maxon
    Linux/other: ~/.config/Maxon (best-effort; C4D on Linux is rare)
    """
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return [os.path.join(home, "Library", "Preferences", "Maxon")]
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        return [os.path.join(appdata, "Maxon")]
    return [os.path.join(home, ".config", "Maxon")]


def parse_version_label(dir_name):
    """Extract a human version label from a C4D pref-dir name.

    "Maxon Cinema 4D 2026_9D810372" -> "2026"
    "Cinema 4D 2024B_E35286C3"      -> "2024B"
    "Maxon Cinema 4D 2024_ABC123_x" -> "2024"
    Returns None when the name isn't a Cinema 4D directory.
    """
    match = _C4D_DIR_RE.search(dir_name or "")
    if not match:
        return None
    token = match.group(1)
    # Strip the machine-unique hash suffix that follows the first underscore.
    return token.split("_", 1)[0]


def discover_c4d_installs(prefs_root):
    """Discover Cinema 4D installs under a single preferences root.

    Pure: takes an explicit root so tests can pass a fake tree. Returns a list of
    dicts sorted by version label (descending), each:
        {"label": "2026", "dir_name": ..., "prefs_dir": ..., "plugins_dir": ...,
         "plugins_exists": bool}
    A directory qualifies if its name matches the C4D pattern; the plugins/ child
    need not exist yet (the installer creates it).
    """
    results = []
    try:
        entries = sorted(os.listdir(prefs_root))
    except (OSError, TypeError):
        return results

    for name in entries:
        full = os.path.join(prefs_root, name)
        if not os.path.isdir(full):
            continue
        label = parse_version_label(name)
        if label is None:
            continue
        plugins_dir = os.path.join(full, "plugins")
        results.append({
            "label": label,
            "dir_name": name,
            "prefs_dir": full,
            "plugins_dir": plugins_dir,
            "plugins_exists": os.path.isdir(plugins_dir),
        })

    # Newest label first; ties broken by dir name for determinism.
    results.sort(key=lambda r: (r["label"], r["dir_name"]), reverse=True)
    return results


def discover_all_installs(prefs_roots=None):
    """Discover installs across every configured prefs root (dedup by prefs_dir)."""
    if prefs_roots is None:
        prefs_roots = default_prefs_roots()
    seen = set()
    combined = []
    for root in prefs_roots:
        for install in discover_c4d_installs(root):
            key = install["prefs_dir"]
            if key in seen:
                continue
            seen.add(key)
            combined.append(install)
    combined.sort(key=lambda r: (r["label"], r["dir_name"]), reverse=True)
    return combined


def verify_payload(dest_dir, critical_paths=None):
    """Check the critical payload landed at dest_dir.

    Returns (ok: bool, missing: list[str]). Pure — operates on whatever tree the
    caller points it at, so tests can build a complete or incomplete fake tree.
    """
    if critical_paths is None:
        critical_paths = CRITICAL_PAYLOAD_PATHS
    missing = [rel for rel in critical_paths
               if not os.path.exists(os.path.join(dest_dir, rel))]
    return (not missing, missing)


def legacy_folder_warning(plugins_dir):
    """Return a warning string if an old YS_Guardian/ sits next to the target."""
    legacy = os.path.join(plugins_dir, LEGACY_DEST_FOLDER_NAME)
    if os.path.isdir(legacy):
        return ("WARNING: an old '%s' folder exists at %s — remove it manually to "
                "avoid duplicate plugin loading." % (LEGACY_DEST_FOLDER_NAME, legacy))
    return None


# ── Copy engine (mirror with delete-orphans) ────────────────────────────────
def mirror_copy(src_dir, dest_dir):
    """Mirror src_dir INTO dest_dir, pruning orphan files/dirs (rsync --delete).

    Approach: shutil.copytree(dirs_exist_ok=True) copies/overwrites every source
    entry, then a second walk deletes any destination entry with no source
    counterpart. __pycache__ and .pyc are skipped on copy AND ignored when
    deciding orphans, so we never churn on compiled artifacts.
    """
    src_dir = os.path.abspath(src_dir)
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True, ignore=ignore)

    _prune_orphans(src_dir, dest_dir)


def _is_ignored(name):
    return name in ("__pycache__", ".DS_Store") or name.endswith(".pyc")


def _prune_orphans(src_dir, dest_dir):
    """Delete destination entries that have no counterpart in source."""
    for dest_root, dir_names, file_names in os.walk(dest_dir, topdown=True):
        rel = os.path.relpath(dest_root, dest_dir)
        src_root = src_dir if rel == "." else os.path.join(src_dir, rel)

        # Prune orphan directories (and stop descending into them).
        kept_dirs = []
        for d in dir_names:
            if _is_ignored(d):
                # Remove stray caches from the destination too.
                shutil.rmtree(os.path.join(dest_root, d), ignore_errors=True)
                continue
            if os.path.isdir(os.path.join(src_root, d)):
                kept_dirs.append(d)
            else:
                shutil.rmtree(os.path.join(dest_root, d), ignore_errors=True)
        dir_names[:] = kept_dirs

        # Prune orphan files.
        for f in file_names:
            if _is_ignored(f):
                try:
                    os.remove(os.path.join(dest_root, f))
                except OSError:
                    pass
                continue
            if not os.path.exists(os.path.join(src_root, f)):
                try:
                    os.remove(os.path.join(dest_root, f))
                except OSError:
                    pass


def install_to(plugins_dir, src_plugin_dir):
    """Install the payload into one plugins_dir. Returns a result dict."""
    dest = os.path.join(plugins_dir, DEST_FOLDER_NAME)
    result = {"plugins_dir": plugins_dir, "dest": dest, "ok": False,
              "missing": [], "warning": None, "error": None}
    result["warning"] = legacy_folder_warning(plugins_dir)
    try:
        mirror_copy(src_plugin_dir, dest)
    except Exception as exc:  # pragma: no cover - filesystem failure path
        result["error"] = str(exc)
        return result
    ok, missing = verify_payload(dest)
    result["ok"] = ok
    result["missing"] = missing
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────
def _repo_plugin_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), PLUGIN_SRC_DIRNAME)


def _format_install_line(idx, install):
    flag = "" if install["plugins_exists"] else "  (plugins/ will be created)"
    return "  [%d] C4D %-8s  %s%s" % (idx, install["label"], install["plugins_dir"], flag)


def _print_list(installs):
    if not installs:
        print("No Cinema 4D installations found in the standard preferences paths.")
        print("Roots searched: %s" % ", ".join(default_prefs_roots()))
        return
    print("Discovered Cinema 4D installations:")
    for i, install in enumerate(installs, 1):
        print(_format_install_line(i, install))


def _prompt_selection(installs):
    """Interactive picker. Returns the chosen install dicts (possibly empty)."""
    _print_list(installs)
    if not installs:
        return []
    print("")
    print("Choose target(s): number(s) comma-separated (e.g. 1,3), 'all', or 'q' to quit.")
    try:
        raw = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("")
        return []
    if raw in ("q", "quit", ""):
        return []
    if raw == "all":
        return list(installs)
    chosen = []
    for tok in raw.replace(" ", "").split(","):
        if not tok.isdigit():
            print("Ignoring invalid selection: %r" % tok)
            continue
        i = int(tok)
        if 1 <= i <= len(installs):
            chosen.append(installs[i - 1])
        else:
            print("Ignoring out-of-range selection: %d" % i)
    return chosen


def _run_installs(targets, src_plugin_dir):
    if not src_plugin_dir or not os.path.isdir(src_plugin_dir):
        print("ERROR: plugin source not found at %s" % src_plugin_dir)
        return 1
    if not targets:
        print("Nothing to install.")
        return 0

    any_fail = False
    for plugins_dir in targets:
        print("")
        print("Installing to: %s" % plugins_dir)
        res = install_to(plugins_dir, src_plugin_dir)
        if res["warning"]:
            print("  " + res["warning"])
        if res["error"]:
            print("  FAIL: %s" % res["error"])
            any_fail = True
            continue
        if res["ok"]:
            print("  OK: payload verified at %s" % res["dest"])
        else:
            any_fail = True
            print("  FAIL: payload incomplete — missing:")
            for rel in res["missing"]:
                print("      - %s" % rel)
    print("")
    print("Restart Cinema 4D to load Sentinel." if not any_fail
          else "Completed with errors — see FAIL lines above.")
    return 1 if any_fail else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Install the Sentinel plugin into Cinema 4D plugin folders.")
    parser.add_argument("--list", action="store_true",
                        help="List discovered Cinema 4D installs and exit.")
    parser.add_argument("--all", action="store_true",
                        help="Install into every discovered install (non-interactive).")
    parser.add_argument("--target", metavar="PATH",
                        help="Install into this explicit <...>/plugins directory.")
    args = parser.parse_args(argv)

    src_plugin_dir = _repo_plugin_dir()

    if args.target:
        return _run_installs([os.path.abspath(args.target)], src_plugin_dir)

    installs = discover_all_installs()

    if args.list:
        _print_list(installs)
        return 0

    if args.all:
        return _run_installs([i["plugins_dir"] for i in installs], src_plugin_dir)

    targets = [i["plugins_dir"] for i in _prompt_selection(installs)]
    return _run_installs(targets, src_plugin_dir)


if __name__ == "__main__":
    sys.exit(main())
