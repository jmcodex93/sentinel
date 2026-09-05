#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build and verify a traceable local Sentinel candidate archive (stdlib only)."""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import uuid
import zipfile


CANDIDATE_MANIFEST_NAME = "SENTINEL_CANDIDATE.json"
INSTALL_GUIDE_NAME = "INSTALLATION_README.md"


def _git(repo_dir, *args):
    try:
        return subprocess.check_output(
            ["git", "-C", os.path.abspath(repo_dir)] + list(args),
            stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "output", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace").strip()
        raise ValueError("git command failed%s" % (": " + detail if detail else ""))


def _committed_files(repo_dir, commit):
    raw = _git(repo_dir, "ls-tree", "-r", "-z", "--name-only", commit, "--",
               "install.py", "plugin", INSTALL_GUIDE_NAME)
    return [path.decode("utf-8") for path in raw.split(b"\0") if path]


def _read_committed(repo_dir, commit, relative):
    return _git(repo_dir, "show", "%s:%s" % (commit, relative))


def _load_installer(path):
    spec = importlib.util.spec_from_file_location(
        "sentinel_candidate_installer_%s" % uuid.uuid4().hex, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _materialize_commit(repo_dir, commit, root):
    paths = _committed_files(repo_dir, commit)
    for required in ("install.py", INSTALL_GUIDE_NAME):
        if required not in paths:
            raise ValueError("Committed source is missing %s" % required)
    if not any(path.startswith("plugin/") for path in paths):
        raise ValueError("Committed source has no plugin payload")
    for relative in paths:
        target = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as stream:
            stream.write(_read_committed(repo_dir, commit, relative))


def _candidate_files(extracted_root, installer):
    files = ["install.py", INSTALL_GUIDE_NAME]
    plugin_root = os.path.join(extracted_root, "plugin")
    for current, dir_names, file_names in os.walk(plugin_root, topdown=True):
        dir_names[:] = sorted(name for name in dir_names if not installer._is_ignored(name))
        for name in sorted(file_names):
            if installer._is_ignored(name):
                continue
            path = os.path.join(current, name)
            if os.path.isfile(path):
                relative = os.path.relpath(path, plugin_root).replace(os.sep, "/")
                files.append("plugin/" + relative)
    return sorted(files)


def verify_candidate_archive(archive_path):
    """Verify archive paths/hashes, extract it, then run the real payload verifier."""
    issues = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                duplicates = sorted(name for name in set(names) if names.count(name) > 1)
                issues.extend("duplicate archive entry: %s" % name for name in duplicates)
            for name in names:
                normalized = name.replace("\\", "/")
                if (normalized.startswith("/") or ".." in normalized.split("/")
                        or normalized != name):
                    issues.append("unsafe archive path: %s" % name)
            if CANDIDATE_MANIFEST_NAME not in names:
                return {"ok": False, "issues": issues + ["missing candidate manifest"]}
            try:
                manifest = json.loads(archive.read(CANDIDATE_MANIFEST_NAME).decode("utf-8"))
            except (KeyError, UnicodeError, ValueError) as exc:
                return {"ok": False, "issues": issues + ["unreadable candidate manifest: %s" % exc]}
            if not isinstance(manifest, dict):
                return {"ok": False, "issues": issues + ["invalid candidate manifest"]}
            records = manifest.get("files")
            if manifest.get("schema") != 1 or not isinstance(records, dict):
                return {"ok": False, "issues": issues + ["invalid candidate manifest"]}
            expected_names = set(records) | {CANDIDATE_MANIFEST_NAME}
            for name in sorted(expected_names - set(names)):
                issues.append("missing archive entry: %s" % name)
            for name in sorted(set(names) - expected_names):
                issues.append("unexpected archive entry: %s" % name)
            for name in sorted(set(records) & set(names)):
                data = archive.read(name)
                record = records[name]
                if not isinstance(record, dict):
                    issues.append("invalid hash record: %s" % name)
                elif len(data) != record.get("size"):
                    issues.append("size mismatch: %s" % name)
                elif _sha256(data) != record.get("sha256"):
                    issues.append("sha256 mismatch: %s" % name)
            if issues:
                return {"ok": False, "issues": issues, "manifest": manifest}
            with tempfile.TemporaryDirectory(prefix="sentinel-candidate-verify-") as extracted:
                archive.extractall(extracted)
                installer = _load_installer(os.path.join(extracted, "install.py"))
                ok, missing = installer.verify_payload(os.path.join(extracted, "plugin"))
                if not ok:
                    issues.append("extracted payload incomplete: %s" % ", ".join(missing))
                extracted_files = set(_candidate_files(extracted, installer))
                if extracted_files != set(records):
                    issues.append("extracted payload file set differs from manifest")
    except (OSError, zipfile.BadZipFile) as exc:
        issues.append("unreadable candidate archive: %s" % exc)
        manifest = None
    result = {"ok": not issues, "issues": issues}
    if manifest is not None:
        result["manifest"] = manifest
    return result


def build_candidate(repo_dir, output_path, source_ref="HEAD", built_at=None):
    """Build from ``source_ref``'s commit, never from uncommitted worktree bytes."""
    commit = _git(repo_dir, "rev-parse", "--verify", "%s^{commit}" % source_ref)
    commit = commit.decode("ascii").strip()
    if built_at is None:
        built_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory(prefix="sentinel-candidate-source-") as source:
        _materialize_commit(repo_dir, commit, source)
        installer = _load_installer(os.path.join(source, "install.py"))
        plugin_root = os.path.join(source, "plugin")
        ok, missing = installer.verify_payload(plugin_root)
        if not ok:
            raise ValueError("Committed plugin payload is incomplete: %s" % ", ".join(missing))
        paths = _candidate_files(source, installer)
        file_records = {}
        file_data = {}
        for relative in paths:
            path = os.path.join(source, *relative.split("/"))
            with open(path, "rb") as stream:
                data = stream.read()
            file_data[relative] = data
            file_records[relative] = {"sha256": _sha256(data), "size": len(data)}
        manifest = {
            "schema": 1,
            "kind": "sentinel-beta-candidate",
            "commit": commit,
            "source_ref": source_ref,
            "built_utc": built_at,
            "build_id": "%s-%s" % (commit[:12], built_at.replace(":", "").replace("-", "")),
            "files": file_records,
        }
        manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temporary = output_path + ".tmp-" + uuid.uuid4().hex
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for relative in paths:
                    archive.writestr(relative, file_data[relative])
                archive.writestr(CANDIDATE_MANIFEST_NAME, manifest_data)
            verification = verify_candidate_archive(temporary)
            if not verification["ok"]:
                raise RuntimeError("Candidate verification failed: %s"
                                   % "; ".join(verification["issues"]))
            os.replace(temporary, output_path)
        finally:
            try:
                os.remove(temporary)
            except OSError:
                pass
    with open(output_path, "rb") as stream:
        archive_sha256 = _sha256(stream.read())
    return {
        "ok": True,
        "path": output_path,
        "commit": commit,
        "build_id": manifest["build_id"],
        "sha256": archive_sha256,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a verified local Sentinel beta archive.")
    parser.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)),
                        help="Git worktree containing the committed source (default: this directory).")
    parser.add_argument("--source-ref", default="HEAD",
                        help="Committed git ref to package (default: HEAD).")
    parser.add_argument("--output", help="Output zip path (default: dist/sentinel-beta-<sha>.zip).")
    args = parser.parse_args(argv)
    commit = _git(args.repo, "rev-parse", "--verify", "%s^{commit}" % args.source_ref)
    commit = commit.decode("ascii").strip()
    output = args.output or os.path.join(args.repo, "dist", "sentinel-beta-%s.zip" % commit[:12])
    result = build_candidate(args.repo, output, args.source_ref)
    print("Built verified candidate: %s" % result["path"])
    print("Source commit: %s" % result["commit"])
    print("Archive SHA256: %s" % result["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
