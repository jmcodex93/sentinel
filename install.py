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
    python3 install.py --target PATH --rollback latest
    python3 install.py --target PATH --rollback BACKUP_ID

The discovery / label-parsing / payload-verification helpers are pure functions
(they take a root path, never touch the real machine implicitly) so they can be
unit-tested without running the CLI — see tests/test_install.py.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import uuid

# ── Payload description ──────────────────────────────────────────────────────
# The plugin folder whose CONTENTS get copied. The destination folder name.
PLUGIN_SRC_DIRNAME = "plugin"
DEST_FOLDER_NAME = "Sentinel"
LEGACY_DEST_FOLDER_NAME = "YS_Guardian"
BACKUP_DIR_NAME = "Sentinel Backups"
BACKUP_MANIFEST_NAME = "backup.json"

# Load the same stdlib-only verifier used by Doctor without importing C4D.
import importlib.util
_payload_spec = importlib.util.spec_from_file_location(
    "sentinel_payload", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "plugin", "sentinel", "payload.py"))
_payload = importlib.util.module_from_spec(_payload_spec)
_payload_spec.loader.exec_module(_payload)
CRITICAL_PAYLOAD_PATHS = _payload.CRITICAL_PAYLOAD_PATHS

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


def discover_c4d_installs(prefs_root, errors=None):
    """Discover Cinema 4D installs under a single preferences root.

    Pure: takes an explicit root so tests can pass a fake tree. Returns a list of
    dicts sorted by version label (descending), each:
        {"label": "2026", "dir_name": ..., "prefs_dir": ..., "plugins_dir": ...,
         "plugins_exists": bool}
    A directory qualifies if its name matches the C4D pattern; the plugins/ child
    need not exist yet (the installer creates it).

    A missing root is normal (no C4D on this machine) and stays quiet. A root
    that exists but cannot be read is NOT "no installs": when ``errors`` is a
    list, ``{"root", "reason"}`` is appended so the caller can say so
    (Windows acceptance 2026-09-24 — access denied was reported as "No
    Cinema 4D installations found").
    """
    results = []
    try:
        entries = sorted(os.listdir(prefs_root))
    except FileNotFoundError:
        return results
    except (OSError, TypeError) as exc:
        if errors is not None and isinstance(exc, OSError):
            errors.append({"root": str(prefs_root),
                           "reason": exc.strerror or str(exc)})
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


def discover_all_installs(prefs_roots=None, errors=None):
    """Discover installs across every configured prefs root (dedup by prefs_dir).
    Unreadable roots are appended to ``errors`` (see discover_c4d_installs)."""
    if prefs_roots is None:
        prefs_roots = default_prefs_roots()
    seen = set()
    combined = []
    for root in prefs_roots:
        for install in discover_c4d_installs(root, errors=errors):
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
    return _payload.verify_payload(dest_dir, critical_paths)


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

    ignore = lambda directory, names: [name for name in names if _is_ignored(name)]
    shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True, ignore=ignore)

    _prune_orphans(src_dir, dest_dir)


def _is_ignored(name):
    return name in ("__pycache__", ".DS_Store", "node_modules", ".pytest_cache", ".git", "backup") or name.endswith((".pyc", ".bak", ".backup", "~"))


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


def _iter_payload_files(root):
    """Return deployable files in deterministic relative-path order."""
    root = os.path.abspath(root)
    paths = []
    for current, dir_names, file_names in os.walk(root, topdown=True):
        dir_names[:] = sorted(name for name in dir_names if not _is_ignored(name))
        for name in sorted(file_names):
            if _is_ignored(name):
                continue
            path = os.path.join(current, name)
            if os.path.isfile(path):
                paths.append((os.path.relpath(path, root).replace(os.sep, "/"), path))
    return paths


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_tree_manifest(root):
    """Describe every deployable file so copies and legacy backups can verify."""
    files = {}
    for relative, path in _iter_payload_files(root):
        files[relative] = {
            "sha256": _sha256_file(path),
            "size": os.path.getsize(path),
        }
    return {"schema": 1, "files": files}


def verify_tree_manifest(root, manifest):
    """Return ``(ok, issues)`` for an exact per-file snapshot manifest."""
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        return False, ["invalid manifest schema"]
    expected = manifest.get("files")
    if not isinstance(expected, dict):
        return False, ["invalid manifest file table"]
    actual_paths = {relative: path for relative, path in _iter_payload_files(root)}
    issues = []
    for relative in sorted(set(expected) - set(actual_paths)):
        issues.append("missing: %s" % relative)
    for relative in sorted(set(actual_paths) - set(expected)):
        issues.append("unexpected: %s" % relative)
    for relative in sorted(set(expected) & set(actual_paths)):
        record = expected[relative]
        if not isinstance(record, dict):
            issues.append("invalid record: %s" % relative)
            continue
        path = actual_paths[relative]
        if os.path.getsize(path) != record.get("size"):
            issues.append("size mismatch: %s" % relative)
        elif _sha256_file(path) != record.get("sha256"):
            issues.append("sha256 mismatch: %s" % relative)
    return not issues, issues


def backup_root_for(plugins_dir):
    """Return the backup root beside, never inside, C4D's scanned plugins dir."""
    plugins_dir = os.path.abspath(plugins_dir)
    return os.path.join(os.path.dirname(plugins_dir), BACKUP_DIR_NAME)


def _record_name(prefix):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return "%s%s-%s" % (prefix, stamp, uuid.uuid4().hex[:8])


def _write_manifest(path, manifest):
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _stage_payload(plugins_dir, source, manifest, require_current_payload):
    root = backup_root_for(plugins_dir)
    os.makedirs(root, exist_ok=True)
    stage = os.path.join(root, _record_name(".stage-"))
    payload = os.path.join(stage, "payload")
    os.makedirs(stage)
    mirror_copy(source, payload)
    if require_current_payload:
        ok, missing = verify_payload(payload)
        if not ok:
            raise ValueError("Staged payload is incomplete: %s" % ", ".join(missing))
    ok, issues = verify_tree_manifest(payload, manifest)
    if not ok:
        raise ValueError("Staged payload failed integrity verification: %s" % "; ".join(issues))
    return stage, payload


def _move_install_to_backup(plugins_dir, dest, operation):
    """Atomically move an existing install into a self-verifying backup record."""
    root = backup_root_for(plugins_dir)
    os.makedirs(root, exist_ok=True)
    record = os.path.join(root, _record_name("backup-"))
    payload = os.path.join(record, "payload")
    os.makedirs(record)
    manifest = build_tree_manifest(dest)
    manifest.update({
        "kind": "sentinel-backup",
        "operation": operation,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    _write_manifest(os.path.join(record, BACKUP_MANIFEST_NAME), manifest)
    os.replace(dest, payload)
    try:
        ok, issues = verify_tree_manifest(payload, manifest)
    except Exception as exc:
        ok, issues = False, ["could not read moved backup: %s" % exc]
    if not ok:
        try:
            os.replace(payload, dest)
        except OSError as restore_error:
            raise RuntimeError(
                "Backup integrity failed (%s); restore also failed (%s). "
                "Recover from %s" % ("; ".join(issues), restore_error, payload))
        raise RuntimeError("Backup integrity failed; previous installation restored: %s"
                           % "; ".join(issues))
    return record


def _restore_after_failure(dest, backup_record):
    """Restore the displaced install; return ``(state, recovery, detail)``."""
    payload = os.path.join(backup_record, "payload")
    try:
        os.replace(payload, dest)
        return "previous_restored", None, None
    except OSError as exc:
        return "recovery_required", payload, str(exc)


def _new_result(plugins_dir):
    dest = os.path.join(plugins_dir, DEST_FOLDER_NAME)
    return {
        "plugins_dir": plugins_dir,
        "dest": dest,
        "ok": False,
        "missing": [],
        "warning": legacy_folder_warning(plugins_dir),
        "error": None,
        "backup": None,
        "recovery": None,
        "state": "unchanged",
    }


def install_to(plugins_dir, src_plugin_dir):
    """Stage, verify and atomically activate a payload in one plugins directory."""
    plugins_dir = os.path.abspath(plugins_dir)
    result = _new_result(plugins_dir)
    dest = result["dest"]
    ok, missing = verify_payload(src_plugin_dir)
    if not ok:
        result["missing"] = missing
        result["error"] = "Source payload is incomplete; existing installation preserved."
        return result
    source_manifest = build_tree_manifest(src_plugin_dir)
    try:
        stage, staged_payload = _stage_payload(
            plugins_dir, src_plugin_dir, source_manifest, require_current_payload=True)
    except Exception as exc:
        result["error"] = "Could not stage update: %s" % exc
        return result

    if os.path.exists(dest) and not os.path.isdir(dest):
        result["error"] = "Destination exists but is not a directory: %s" % dest
        result["recovery"] = staged_payload
        return result

    backup = None
    if os.path.isdir(dest):
        try:
            backup = _move_install_to_backup(plugins_dir, dest, "install")
            result["backup"] = backup
        except Exception as exc:
            result["error"] = "Could not preserve previous installation: %s" % exc
            result["recovery"] = staged_payload
            return result

    os.makedirs(plugins_dir, exist_ok=True)
    try:
        os.replace(staged_payload, dest)
    except Exception as exc:
        state, recovery, restore_error = (
            _restore_after_failure(dest, backup) if backup
            else ("unchanged", staged_payload, None))
        result["state"] = state
        result["recovery"] = recovery or staged_payload
        result["error"] = "Could not activate staged payload: %s" % exc
        if restore_error:
            result["error"] += "; automatic restore failed: %s" % restore_error
        return result

    ok, missing = verify_payload(dest)
    hashes_ok, hash_issues = verify_tree_manifest(dest, source_manifest)
    if not ok or not hashes_ok:
        result["missing"] = missing
        failed_candidate = os.path.join(
            backup_root_for(plugins_dir), _record_name("failed-candidate-"))
        try:
            os.replace(dest, failed_candidate)
            result["recovery"] = failed_candidate
        except OSError as quarantine_error:
            result["state"] = "recovery_required"
            result["recovery"] = backup and os.path.join(backup, "payload")
            result["error"] = "Activated payload failed verification and could not be moved: %s" % quarantine_error
            return result
        if backup:
            state, recovery, restore_error = _restore_after_failure(dest, backup)
            result["state"] = state
            if recovery:
                result["recovery"] = recovery
            result["error"] = "Activated payload failed verification; previous installation restored."
            if restore_error:
                result["error"] = "Activated payload failed verification; restore failed: %s" % restore_error
        else:
            result["state"] = "recovery_required"
            result["error"] = "Activated payload failed verification; failed candidate preserved."
        if hash_issues:
            result["error"] += " Integrity: %s" % "; ".join(hash_issues)
        return result

    result["ok"] = True
    result["state"] = "installed"
    try:
        os.rmdir(stage)
    except OSError:
        pass
    return result


def _load_backup_manifest(record):
    path = os.path.join(record, BACKUP_MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, UnicodeError, ValueError) as exc:
        return None, "unreadable backup manifest: %s" % exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "sentinel-backup":
        return None, "invalid backup manifest kind"
    return manifest, None


def list_backups(plugins_dir):
    """Return recorded backup directories, newest first."""
    root = backup_root_for(plugins_dir)
    try:
        names = sorted(os.listdir(root), reverse=True)
    except OSError:
        return []
    return [os.path.join(root, name) for name in names
            if name.startswith("backup-")
            and os.path.isdir(os.path.join(root, name, "payload"))
            and os.path.isfile(os.path.join(root, name, BACKUP_MANIFEST_NAME))]


def _resolve_backup(plugins_dir, backup):
    root = os.path.realpath(backup_root_for(plugins_dir))
    if backup in (None, "", "latest"):
        records = list_backups(plugins_dir)
        return records[0] if records else None
    candidate = backup if os.path.isabs(backup) else os.path.join(root, backup)
    candidate = os.path.realpath(candidate)
    try:
        inside = os.path.commonpath([root, candidate]) == root
    except ValueError:
        inside = False
    return candidate if inside else None


def rollback_to(plugins_dir, backup="latest"):
    """Restore a recorded backup, retaining the displaced current payload."""
    plugins_dir = os.path.abspath(plugins_dir)
    result = _new_result(plugins_dir)
    dest = result["dest"]
    record = _resolve_backup(plugins_dir, backup)
    if not record:
        result["error"] = "No recorded Sentinel backup found."
        return result
    manifest, error = _load_backup_manifest(record)
    payload = os.path.join(record, "payload")
    if error:
        result["error"] = "Backup integrity check failed: %s" % error
        return result
    ok, issues = verify_tree_manifest(payload, manifest)
    if not ok:
        result["error"] = "Backup integrity check failed: %s" % "; ".join(issues)
        result["recovery"] = payload
        return result

    try:
        stage, staged_payload = _stage_payload(
            plugins_dir, payload, manifest, require_current_payload=False)
    except Exception as exc:
        result["error"] = "Could not stage rollback: %s" % exc
        return result

    current_backup = None
    if os.path.exists(dest) and not os.path.isdir(dest):
        result["error"] = "Destination exists but is not a directory: %s" % dest
        result["recovery"] = staged_payload
        return result
    if os.path.isdir(dest):
        try:
            current_backup = _move_install_to_backup(plugins_dir, dest, "rollback")
            result["backup"] = current_backup
        except Exception as exc:
            result["error"] = "Could not preserve current installation: %s" % exc
            result["recovery"] = staged_payload
            return result

    os.makedirs(plugins_dir, exist_ok=True)
    try:
        os.replace(staged_payload, dest)
    except Exception as exc:
        state, recovery, restore_error = (
            _restore_after_failure(dest, current_backup) if current_backup
            else ("unchanged", staged_payload, None))
        result["state"] = state
        result["recovery"] = recovery or staged_payload
        result["error"] = "Could not activate rollback: %s" % exc
        if restore_error:
            result["error"] += "; automatic restore failed: %s" % restore_error
        return result

    ok, issues = verify_tree_manifest(dest, manifest)
    if not ok:
        failed = os.path.join(backup_root_for(plugins_dir), _record_name("failed-rollback-"))
        try:
            os.replace(dest, failed)
            result["recovery"] = failed
        except OSError as quarantine_error:
            result["state"] = "recovery_required"
            result["error"] = "Rollback verification failed and payload could not be moved: %s" % quarantine_error
            return result
        if current_backup:
            state, recovery, restore_error = _restore_after_failure(dest, current_backup)
            result["state"] = state
            if recovery:
                result["recovery"] = recovery
            result["error"] = "Rollback verification failed; current installation restored."
            if restore_error:
                result["error"] = "Rollback verification failed; restore failed: %s" % restore_error
        else:
            result["state"] = "recovery_required"
            result["error"] = "Rollback verification failed; failed payload preserved."
        result["error"] += " Integrity: %s" % "; ".join(issues)
        return result

    result["ok"] = True
    result["state"] = "rolled_back"
    result["restored_from"] = record
    try:
        os.rmdir(stage)
    except OSError:
        pass
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────
def _repo_plugin_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), PLUGIN_SRC_DIRNAME)


def _format_install_line(idx, install):
    flag = "" if install["plugins_exists"] else "  (plugins/ will be created)"
    return "  [%d] C4D %-8s  %s%s" % (idx, install["label"], install["plugins_dir"], flag)


def _print_list(installs, errors=()):
    for err in errors:
        print("Could not read %s: %s" % (err["root"], err["reason"]))
    if errors:
        print("Run from a normal user shell, or install explicitly with "
              "--target <C4D preferences>/plugins (C4D: Edit > Preferences > "
              "Open Preferences Folder).")
    if not installs:
        if not errors:
            print("No Cinema 4D installations found in the standard preferences paths.")
            print("Roots searched: %s" % ", ".join(default_prefs_roots()))
        return
    print("Discovered Cinema 4D installations:")
    for i, install in enumerate(installs, 1):
        print(_format_install_line(i, install))


def _prompt_selection(installs, errors=()):
    """Interactive picker. Returns the chosen install dicts (possibly empty)."""
    _print_list(installs, errors)
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
            if res["recovery"]:
                print("  Recovery payload: %s" % res["recovery"])
            any_fail = True
            continue
        if res["ok"]:
            print("  OK: payload verified at %s" % res["dest"])
            if res["backup"]:
                print("  Previous payload retained at %s" % res["backup"])
        else:
            any_fail = True
            print("  FAIL: payload incomplete — missing:")
            for rel in res["missing"]:
                print("      - %s" % rel)
    print("")
    print("Restart Cinema 4D to load Sentinel." if not any_fail
          else "Completed with errors — see FAIL lines above.")
    return 1 if any_fail else 0


def _run_rollback(plugins_dir, backup):
    print("Rolling back: %s" % plugins_dir)
    result = rollback_to(plugins_dir, backup)
    if result["error"]:
        print("  FAIL: %s" % result["error"])
        if result["recovery"]:
            print("  Recovery payload: %s" % result["recovery"])
        return 1
    print("  OK: restored %s" % result["restored_from"])
    if result["backup"]:
        print("  Displaced payload retained at %s" % result["backup"])
    print("Restart Cinema 4D to load the restored Sentinel version.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Install the Sentinel plugin into Cinema 4D plugin folders.")
    parser.add_argument("--list", action="store_true",
                        help="List discovered Cinema 4D installs and exit.")
    parser.add_argument("--all", action="store_true",
                        help="Install into every discovered install (non-interactive).")
    parser.add_argument("--target", metavar="PATH",
                        help="Install into this explicit <...>/plugins directory.")
    parser.add_argument("--rollback", nargs="?", const="latest", metavar="BACKUP",
                        help="Restore latest or named backup for --target.")
    args = parser.parse_args(argv)

    src_plugin_dir = _repo_plugin_dir()

    if args.rollback is not None:
        if not args.target:
            parser.error("--rollback requires one explicit --target plugins directory")
        return _run_rollback(os.path.abspath(args.target), args.rollback)

    if args.target:
        return _run_installs([os.path.abspath(args.target)], src_plugin_dir)

    errors = []
    installs = discover_all_installs(errors=errors)

    if args.list:
        _print_list(installs, errors)
        return 1 if errors else 0

    if args.all:
        if errors:
            # "Every install" is unknowable when a root could not be read.
            _print_list(installs, errors)
            return 1
        return _run_installs([i["plugins_dir"] for i in installs], src_plugin_dir)

    targets = [i["plugins_dir"] for i in _prompt_selection(installs, errors)]
    if errors and not targets:
        return 1
    return _run_installs(targets, src_plugin_dir)


if __name__ == "__main__":
    sys.exit(main())
