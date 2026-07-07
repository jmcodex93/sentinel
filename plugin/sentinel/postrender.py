"""Pure post-render validation helpers for Sentinel."""

import importlib.util
import json
import os
import re
import statistics
import time

# Single source for the version-stripped render-history sidecar path. Kept
# standalone-importable (postrender is stdlib-only): prefer the package import,
# fall back to loading versioning.py by path — same pattern as baseline.py.
try:
    from sentinel.versioning import parse_version_filename, render_history_path
except ModuleNotFoundError:
    _versioning_path = os.path.join(os.path.dirname(__file__), "versioning.py")
    _versioning_spec = importlib.util.spec_from_file_location(
        "sentinel_versioning_fallback", _versioning_path
    )
    _versioning_module = importlib.util.module_from_spec(_versioning_spec)
    _versioning_spec.loader.exec_module(_versioning_module)
    parse_version_filename = _versioning_module.parse_version_filename
    render_history_path = _versioning_module.render_history_path


# Conservative floor for a viable rendered image header/payload. Zero-byte files
# are classified separately; 1..1023 bytes are hard-truncated render artifacts.
MIN_VIABLE_BYTES = 1024
MIN_STALE_GAP_SECONDS = 300
REPORT_ITEM_CAP = 50

C4D_BITMAP_EXTENSIONS = {
    1100: "tif",
    1101: "tga",
    1102: "bmp",
    1103: "iff",
    1104: "jpg",
    1105: "pct",
    1106: "psd",
    1107: "rla",
    1108: "rpf",
    1109: "b3d",
    1111: "psb",
    1125: "mp4",
    1001379: "hdr",
    1016606: "exr",
    1023671: "png",
    1023737: "dpx",
    1073775603: "dds",
    1073784596: "mov",
}

RS_AOV_EXTENSIONS = {
    0: "exr",
    1: "tif",
    2: "png",
}

FRAME_MODE_MANUAL = 0
FRAME_MODE_CURRENT = 1
FRAME_MODE_ALL = 2


def _normalized_path(path):
    return str(path or "").replace("\\", "/")


def _extension_for_format(format_id):
    try:
        key = int(format_id)
    except Exception:
        key = None
    if key in C4D_BITMAP_EXTENSIONS:
        return C4D_BITMAP_EXTENSIONS[key]
    if key in RS_AOV_EXTENSIONS:
        return RS_AOV_EXTENSIONS[key]
    return "exr"


def _frame_set_for_state(state):
    mode = int(state.get("frame_mode", FRAME_MODE_MANUAL) or FRAME_MODE_MANUAL)
    step = int(state.get("frame_step", 1) or 1)
    if step <= 0:
        step = 1

    if mode == FRAME_MODE_CURRENT:
        current = int(state.get("current_frame", 0) or 0)
        return [current]
    if mode == FRAME_MODE_ALL:
        start = int(state.get("timeline_min", 0) or 0)
        end = int(state.get("timeline_max", start) or start)
    else:
        start = int(state.get("frame_from", 0) or 0)
        end = int(state.get("frame_to", start) or start)

    if end < start:
        return []
    return expected_frames(start, end, step)


def _mode_label(frame_mode):
    try:
        mode = int(frame_mode)
    except Exception:
        mode = FRAME_MODE_MANUAL
    if mode == FRAME_MODE_CURRENT:
        return "Current Frame"
    if mode == FRAME_MODE_ALL:
        return "All Frames"
    return "Manual"


def _stem_prefix_for_scan(stem, is_sequence, has_frame_token):
    """Return the scan prefix from an explicitly-known frame-token context."""
    stem = str(stem or "")
    if not has_frame_token:
        return stem
    digit_runs = list(re.finditer(r"\d+", stem))
    if digit_runs:
        last = digit_runs[-1]
        start = last.start()
        if start > 0 and stem[start - 1] in "._-":
            return stem[:start]
        return stem[:start] or stem
    return stem if is_sequence else stem


def resolve_output_template(raw_path, take_name, format_id, is_sequence, has_frame_token=False):
    """Split a token-resolved render path into (folder, frame-prefix, ext)."""
    path = _normalized_path(raw_path)
    if "$take" in path:
        path = path.replace("$take", str(take_name or "Main"))
    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    if ext:
        ext_value = ext.lstrip(".").lower()
    else:
        ext_value = _extension_for_format(format_id)
    prefix = _stem_prefix_for_scan(stem, is_sequence, bool(has_frame_token))
    return folder, prefix, ext_value


def _frame_from_prefixed_stem(stem, prefix):
    """Parse only <prefix><optional single sep><digits> stems."""
    stem = str(stem or "")
    prefix = str(prefix or "")
    prefix_lower = prefix.lower()
    if not stem.lower().startswith(prefix_lower):
        return None
    remainder = stem[len(prefix):]
    if remainder and remainder[0] in "._-":
        remainder = remainder[1:]
    if not remainder.isdigit():
        return None
    return int(remainder)


def _stream_descriptor(entry, kind, prefix, ext, label, aov_name=None):
    return {
        "take_name": entry.get("take_name", ""),
        "folder": entry.get("folder", ""),
        "kind": kind,
        "prefix": prefix,
        "ext": ext,
        "label": label,
        "aov_name": aov_name,
        "frame_set": list(entry.get("frame_set") or []),
    }


def _choose_scan_folder(entry_folder, audit_folder):
    entry_folder = _normalized_path(entry_folder)
    audit_folder = _normalized_path(audit_folder)
    if entry_folder and os.path.isdir(entry_folder):
        return entry_folder
    return audit_folder or entry_folder


def _paths_by_frame(folder, prefix, frames, ext):
    expected = set(frames)
    ext_lower = "." + str(ext).lower().lstrip(".")
    found = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return found
    for name in names:
        if not name.lower().endswith(ext_lower):
            continue
        stem = name[: -len(ext_lower)]
        frame = _frame_from_prefixed_stem(stem, prefix)
        if frame is None:
            continue
        if frame in expected and frame not in found:
            found[frame] = os.path.join(folder, name)
    return found


def _sizes_for_frames(folder, prefix, frames, ext):
    paths = _paths_by_frame(folder, prefix, frames, ext)
    sizes = {}
    for frame, path in paths.items():
        try:
            sizes[frame] = os.path.getsize(path)
        except OSError:
            pass
    return sizes


def build_manifest_from_state(states, audit_folder=None):
    """Turn raw scene render-state dictionaries into expected output entries."""
    states = [state for state in (states or []) if isinstance(state, dict)]
    if not states:
        return []

    has_child = any(not state.get("is_main") for state in states)
    included = []
    for state in states:
        if state.get("is_main") and not has_child:
            included.append(state)
        elif state.get("is_checked"):
            included.append(state)

    manifest = []
    seen = set()
    for state in included:
        frame_set = _frame_set_for_state(state)
        if not frame_set:
            continue

        raw_path = (
            state.get("resolved_beauty_path")
            or state.get("raw_path")
            or os.path.join(audit_folder or "", "render")
        )
        is_sequence = len(frame_set) > 1
        folder, beauty_prefix, ext = resolve_output_template(
            raw_path,
            state.get("take_name", ""),
            state.get("format_id"),
            is_sequence,
            state.get("resolved_beauty_has_frame_token", False),
        )
        if not folder and audit_folder:
            folder = _normalized_path(audit_folder)
        folder = _normalized_path(folder)

        aov_mode = "none"
        aov_files = []
        multipart = None
        if state.get("redshift_available") and state.get("aovs"):
            if state.get("aov_multipart"):
                aov_mode = "multipart"
                mp_folder, mp_prefix, _mp_ext = resolve_output_template(
                    raw_path,
                    state.get("take_name", ""),
                    1016606,
                    is_sequence,
                    state.get("resolved_beauty_has_frame_token", False),
                )
                multipart = {
                    "prefix": mp_prefix,
                    "ext": "exr",
                    "folder": _normalized_path(mp_folder or folder),
                }
            else:
                aov_mode = "direct"
                for aov in state.get("aovs") or []:
                    if not aov.get("direct_enabled"):
                        continue
                    effective_path = aov.get("effective_path") or ""
                    if not effective_path:
                        continue
                    aov_folder, aov_prefix, aov_ext = resolve_output_template(
                        effective_path,
                        state.get("take_name", ""),
                        aov.get("file_format"),
                        is_sequence,
                        aov.get("effective_has_frame_token", False),
                    )
                    aov_files.append({
                        "name": aov.get("name", ""),
                        "prefix": aov_prefix,
                        "ext": aov_ext,
                        "folder": _normalized_path(aov_folder or folder),
                    })
        elif state.get("multipass_save") and state.get("multipass_path"):
            mp_folder, mp_prefix, mp_ext = resolve_output_template(
                state.get("multipass_path"),
                state.get("take_name", ""),
                state.get("multipass_format_id"),
                is_sequence,
                state.get("multipass_has_frame_token", False),
            )
            aov_mode = "multipart"
            multipart = {
                "prefix": mp_prefix,
                "ext": mp_ext,
                "folder": _normalized_path(mp_folder or folder),
            }

        key = (
            folder,
            beauty_prefix,
            ext,
            tuple(frame_set),
            aov_mode,
            tuple((a.get("folder"), a.get("prefix"), a.get("ext"), a.get("name")) for a in aov_files),
            tuple(sorted((multipart or {}).items())),
        )
        if key in seen:
            continue
        seen.add(key)
        manifest.append({
            "take_name": state.get("take_name", ""),
            "folder": folder,
            "beauty_prefix": beauty_prefix,
            "ext": ext,
            "frame_set": frame_set,
            "xres": int(state.get("xres", 0) or 0),
            "yres": int(state.get("yres", 0) or 0),
            "format_id": state.get("format_id"),
            "frame_mode": state.get("frame_mode"),
            "frame_mode_label": _mode_label(state.get("frame_mode")),
            "doc_path": state.get("doc_path", ""),
            "version": state.get("version", ""),
            "aov_mode": aov_mode,
            "aov_files": aov_files,
            "multipart": multipart,
            "light_groups": list(state.get("light_groups") or []),
        })
    return manifest


def audit_manifest(manifest, folder):
    """Scan rendered files for a hand-built or scene-derived manifest."""
    manifest = [entry for entry in (manifest or []) if isinstance(entry, dict)]
    findings = {
        "manifest": manifest,
        "streams": [],
        "categories": {
            "missing": [],
            "zero_byte": [],
            "truncated": [],
            "stale": [],
            "size_outliers": [],
            "aov_missing": [],
            "coverage_missing": [],
            "notes": [],
            "error": [],
        },
    }
    if not manifest:
        findings["categories"]["notes"].append({
            "message": "No render outputs to validate.",
        })
        return findings

    for entry in manifest:
        streams = [
            _stream_descriptor(
                entry,
                "beauty",
                entry.get("beauty_prefix", ""),
                entry.get("ext", "exr"),
                f"{entry.get('take_name') or 'Main'} beauty",
            )
        ]
        if entry.get("aov_mode") == "direct":
            for aov in entry.get("aov_files") or []:
                streams.append(_stream_descriptor(
                    entry,
                    "aov",
                    aov.get("prefix", ""),
                    aov.get("ext", "exr"),
                    f"{entry.get('take_name') or 'Main'} AOV {aov.get('name') or aov.get('prefix')}",
                    aov_name=aov.get("name", ""),
                ))
                streams[-1]["folder"] = aov.get("folder") or entry.get("folder", "")
        elif entry.get("aov_mode") == "multipart" and entry.get("multipart"):
            mp = entry.get("multipart") or {}
            streams.append(_stream_descriptor(
                entry,
                "multipart",
                mp.get("prefix", ""),
                mp.get("ext", "exr"),
                f"{entry.get('take_name') or 'Main'} Multi-Part EXR",
            ))
            streams[-1]["folder"] = mp.get("folder") or entry.get("folder", "")

        if entry.get("light_groups"):
            findings["categories"]["notes"].append({
                "take_name": entry.get("take_name", ""),
                "message": "Light-group AOVs not validated in this version.",
                "light_groups": list(entry.get("light_groups") or []),
            })

        beauty_found_count = None
        for stream in streams:
            scan_folder = _choose_scan_folder(stream.get("folder"), folder)
            scan = scan_sequence(
                scan_folder,
                stream.get("prefix", ""),
                stream.get("frame_set") or [],
                stream.get("ext", "exr"),
            )
            healthy_frames = list(scan.get("found") or [])
            sizes = _sizes_for_frames(
                scan_folder,
                stream.get("prefix", ""),
                healthy_frames,
                stream.get("ext", "exr"),
            )
            outliers = size_outliers(sizes)
            stream_result = dict(stream)
            stream_result["folder"] = scan_folder
            stream_result["scan"] = scan
            stream_result["size_outliers"] = outliers
            findings["streams"].append(stream_result)

            for category in ("missing", "zero_byte", "truncated", "stale"):
                for frame in scan.get(category) or []:
                    item = {
                        "take_name": stream.get("take_name", ""),
                        "stream": stream.get("label", ""),
                        "kind": stream.get("kind", ""),
                        "aov_name": stream.get("aov_name", ""),
                        "folder": scan_folder,
                        "prefix": stream.get("prefix", ""),
                        "ext": stream.get("ext", "exr"),
                        "frame": frame,
                    }
                    if stream.get("kind") == "aov" and category in ("missing", "zero_byte", "truncated"):
                        findings["categories"]["aov_missing"].append(item)
                    else:
                        findings["categories"][category].append(item)
            for frame in outliers:
                findings["categories"]["size_outliers"].append({
                    "take_name": stream.get("take_name", ""),
                    "stream": stream.get("label", ""),
                    "kind": stream.get("kind", ""),
                    "folder": scan_folder,
                    "prefix": stream.get("prefix", ""),
                    "ext": stream.get("ext", "exr"),
                    "frame": frame,
                })

            if stream.get("kind") == "beauty":
                beauty_found_count = len(scan.get("found") or [])

        if beauty_found_count == 0:
            findings["categories"]["coverage_missing"].append({
                "take_name": entry.get("take_name", ""),
                "folder": entry.get("folder", ""),
                "xres": entry.get("xres"),
                "yres": entry.get("yres"),
            })

    return findings


def build_report(findings):
    """Build a capped JSON-serializable post-render validation report."""
    categories = (findings or {}).get("categories") or {}
    checks = {}
    specs = [
        ("missing", "FAIL", "Missing frames"),
        ("zero_byte", "FAIL", "Zero-byte frames"),
        ("truncated", "FAIL", "Truncated frames"),
        ("stale", "WARN", "Stale frames based on mtime; unreliable on synced/copied folders"),
        ("size_outliers", "WARN", "Size outliers"),
        ("aov_missing", "WARN", "Missing direct-output AOV frames"),
        ("coverage_missing", "WARN", "Missing Take/format coverage"),
        ("error", "FAIL", "Scene read error"),
        ("notes", "WARN", "Validation notes"),
    ]
    for key, severity, label in specs:
        items = list(categories.get(key) or [])
        checks[key] = {
            "status": severity if items else "OK",
            "count": len(items),
            "label": label,
            "items": items[:REPORT_ITEM_CAP],
        }

    fail_count = sum(check["count"] for check in checks.values() if check["status"] == "FAIL")
    warn_count = sum(check["count"] for check in checks.values() if check["status"] == "WARN")
    manifest = list((findings or {}).get("manifest") or [])
    context = {}
    if manifest:
        first = manifest[0]
        frames = first.get("frame_set") or []
        context = {
            "take_name": first.get("take_name", ""),
            "version": first.get("version", ""),
            "frame_start": frames[0] if frames else None,
            "frame_end": frames[-1] if frames else None,
            "frame_mode": first.get("frame_mode_label", _mode_label(first.get("frame_mode"))),
            "manifest_entries": len(manifest),
        }
    return {
        "schema": 1,
        "type": "sentinel_render_report",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": fail_count == 0,
        "summary": {
            "failures": fail_count,
            "warnings": warn_count,
            "streams": len((findings or {}).get("streams") or []),
            "manifest_entries": len(manifest),
        },
        "context": context,
        "checks": checks,
    }


def write_report_atomic(path, report):
    """Atomically write a render report JSON file."""
    if not path:
        return False
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
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


def _load_render_history(path):
    default = {"schema": 1, "render_validations": []}
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return default
        entries = data.get("render_validations")
        if not isinstance(entries, list):
            return default
        return {"schema": int(data.get("schema", 1) or 1), "render_validations": entries}
    except Exception:
        return default


def _render_history_target(base_or_folder):
    base_or_folder = _normalized_path(base_or_folder)
    if not base_or_folder:
        return None
    # A render folder can legitimately contain a dot in its leaf name (e.g. ".../final.v2"),
    # so splitext is unreliable — use isdir to distinguish an audited folder from a doc file.
    if os.path.isdir(base_or_folder):
        return os.path.join(base_or_folder, "sentinel_render_history.json")
    # Single owner of the per-scene sidecar path lives in versioning.py.
    return render_history_path(base_or_folder)


def append_render_history(base_or_folder, summary):
    """Append a render-validation entry to the separate render sidecar."""
    path = _render_history_target(base_or_folder)
    if not path:
        return False
    history = _load_render_history(path)
    report_summary = summary if isinstance(summary, dict) else {}
    checks = report_summary.get("checks") or {}
    issue_counts = {
        key: int(value.get("count", 0) or 0)
        for key, value in checks.items()
        if isinstance(value, dict) and int(value.get("count", 0) or 0)
    }
    context = report_summary.get("context") or {}
    entry = {
        "type": "render_validation",
        "version": context.get("version") or report_summary.get("version") or "",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": bool(report_summary.get("passed", False)),
        "issues": issue_counts,
    }
    history["render_validations"].insert(0, entry)
    return write_report_atomic(path, history)


def report_path_for_doc(doc_path, audit_folder):
    """Return the render report path for a saved doc, or audit folder fallback."""
    doc_path = _normalized_path(doc_path)
    audit_folder = _normalized_path(audit_folder)
    if doc_path:
        folder = os.path.dirname(doc_path)
        name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
        base, _ver, _status = parse_version_filename(name_no_ext)
        return os.path.join(folder, f"{base}_sentinel_render_report.json")
    return os.path.join(audit_folder, "sentinel_render_report.json")


def _read_scene_render_state(doc):
    """Read C4D/Redshift render state into flat JSON-serializable dictionaries."""
    import c4d

    try:
        from sentinel import aovs as aov_engine
    except Exception:
        aov_engine = None

    def _frame(value, fps, fallback=0):
        try:
            return int(value.GetFrame(fps))
        except Exception:
            try:
                return int(value)
            except Exception:
                return int(fallback)

    def _take_name(take):
        try:
            return take.GetName() or "Main"
        except Exception:
            return "Main"

    def _doc_full_path():
        try:
            doc_path = doc.GetDocumentPath() or ""
            doc_name = doc.GetDocumentName() or ""
        except Exception:
            return ""
        if not doc_path or not doc_name:
            return ""
        return os.path.join(doc_path, doc_name)

    def _version_from_doc():
        full_path = _doc_full_path()
        if not full_path:
            return ""
        try:
            from sentinel.versioning import parse_version_filename
            name_no_ext = os.path.splitext(os.path.basename(full_path))[0]
            _base, version, status = parse_version_filename(name_no_ext)
            if version is None:
                return ""
            suffix = f"_{status}" if status else ""
            return f"v{version:03d}{suffix}"
        except Exception:
            return ""

    def _resolve_tokens(path, rd, take, frame):
        path = path or ""
        try:
            rpd = {
                "_doc": doc,
                "_rData": rd,
                "_rBc": rd.GetDataInstance(),
                "_frame": int(frame),
                "_take": take,
            }
            return c4d.modules.tokensystem.StringConvertTokens(path, rpd) or path
        except Exception:
            return path

    def _resolve_path_and_frame_token(path, rd, take, frame):
        current = _resolve_tokens(path, rd, take, frame)
        next_path = _resolve_tokens(path, rd, take, frame + 1)
        return current, _normalized_path(current) != _normalized_path(next_path)

    def _is_checked(take, td):
        try:
            return bool(take.IsChecked())
        except Exception:
            try:
                return take == td.GetCurrentTake()
            except Exception:
                return False

    def _state_for_take(take, rd, td, is_main):
        if not rd:
            return None
        try:
            fps = int(rd[c4d.RDATA_FRAMERATE] or doc.GetFps() or 25)
        except Exception:
            fps = 25
        try:
            frame_mode = int(rd[c4d.RDATA_FRAMESEQUENCE])
        except Exception:
            frame_mode = FRAME_MODE_MANUAL
        try:
            frame_step = int(rd[c4d.RDATA_FRAMESTEP] or 1)
        except Exception:
            frame_step = 1
        try:
            frame_from = _frame(rd[c4d.RDATA_FRAMEFROM], fps)
            frame_to = _frame(rd[c4d.RDATA_FRAMETO], fps, frame_from)
        except Exception:
            frame_from = frame_to = 0
        try:
            timeline_min = _frame(doc.GetMinTime(), fps, frame_from)
            timeline_max = _frame(doc.GetMaxTime(), fps, frame_to)
            current_frame = _frame(doc.GetTime(), fps, frame_from)
        except Exception:
            timeline_min = frame_from
            timeline_max = frame_to
            current_frame = frame_from
        try:
            raw_path = rd[c4d.RDATA_PATH] or ""
        except Exception:
            raw_path = ""
        try:
            multipass_save = bool(rd[c4d.RDATA_MULTIPASS_SAVEIMAGE])
        except Exception:
            multipass_save = False
        try:
            multipass_path = rd[c4d.RDATA_MULTIPASS_FILENAME] or ""
        except Exception:
            multipass_path = ""
        try:
            aovs = aov_engine.get_rs_aovs(doc) if aov_engine else None
        except Exception:
            aovs = None
        try:
            light_groups, _ungrouped = aov_engine._scan_light_groups(doc) if aov_engine else ({}, [])
        except Exception:
            light_groups = {}
        try:
            vprs = aov_engine._get_rs_videopost(doc) if aov_engine else None
            aov_global_path = vprs[c4d.REDSHIFT_RENDERER_AOV_PATH] if vprs else ""
        except Exception:
            aov_global_path = ""
        redshift_available = bool(getattr(aov_engine, "REDSHIFT_AVAILABLE", False)) if aov_engine else False
        take_name = _take_name(take)
        resolved_beauty_path, resolved_beauty_has_frame_token = _resolve_path_and_frame_token(
            raw_path, rd, take, frame_from
        )
        resolved_multipass_path, multipass_has_frame_token = _resolve_path_and_frame_token(
            multipass_path, rd, take, frame_from
        )
        resolved_aovs = []
        for aov in aovs or []:
            if not isinstance(aov, dict):
                continue
            aov_data = dict(aov)
            effective_path = aov_data.get("effective_path") or ""
            resolved_effective, effective_has_frame_token = _resolve_path_and_frame_token(
                effective_path, rd, take, frame_from
            )
            aov_data["effective_path"] = resolved_effective
            aov_data["effective_has_frame_token"] = effective_has_frame_token
            resolved_aovs.append(aov_data)
        return {
            "take_name": take_name,
            "is_main": bool(is_main),
            "is_checked": _is_checked(take, td),
            "raw_path": raw_path,
            "multipass_save": multipass_save,
            "multipass_path": resolved_multipass_path,
            "multipass_has_frame_token": multipass_has_frame_token,
            "xres": int(rd[c4d.RDATA_XRES] or 1920),
            "yres": int(rd[c4d.RDATA_YRES] or 1080),
            "format_id": int(rd[c4d.RDATA_FORMAT]),
            "multipass_format_id": int(rd[c4d.RDATA_MULTIPASS_SAVEFORMAT]),
            "frame_mode": frame_mode,
            "frame_from": frame_from,
            "frame_to": frame_to,
            "timeline_min": timeline_min,
            "timeline_max": timeline_max,
            "current_frame": current_frame,
            "fps": fps,
            "frame_step": frame_step,
            "resolved_beauty_path": resolved_beauty_path,
            "resolved_beauty_has_frame_token": resolved_beauty_has_frame_token,
            "redshift_available": redshift_available,
            "aov_multipart": bool(aov_engine.get_aov_multipart(doc)) if aov_engine else False,
            "aov_global_path": aov_global_path or "",
            "aovs": resolved_aovs,
            "light_groups": list(light_groups.keys()) if isinstance(light_groups, dict) else [],
            "doc_path": _doc_full_path(),
            "version": _version_from_doc(),
        }

    states = []
    try:
        active_rd = doc.GetActiveRenderData()
        td = doc.GetTakeData()
        if not td:
            state = _state_for_take(None, active_rd, None, True)
            return [state] if state else []
        main_take = td.GetMainTake()
        main_rd = active_rd
        try:
            main_rd = main_take.GetRenderData(td) or active_rd if main_take else active_rd
        except Exception:
            main_rd = active_rd
        main_state = _state_for_take(main_take, main_rd, td, True)
        if main_state:
            states.append(main_state)
        take = main_take.GetDown() if main_take else None
        count = 0
        while take and count < 100:
            try:
                rd = take.GetRenderData(td) or active_rd
            except Exception:
                rd = active_rd
            state = _state_for_take(take, rd, td, False)
            if state:
                states.append(state)
            take = take.GetNext()
            count += 1
    except Exception:
        # A catastrophic scene-read failure must NOT masquerade as a clean render
        # (false-GREEN). Propagate so audit_render_folder surfaces it as an error.
        raise
    return states


def build_expected_manifest(doc):
    """Build the expected render manifest from the live C4D document."""
    return build_manifest_from_state(_read_scene_render_state(doc))


def _error_findings(message):
    """Pure findings dict flagging a scene-read failure (scored FAIL, not passed)."""
    findings = audit_manifest([], "")
    findings["categories"]["error"].append({"message": str(message)})
    return findings


def audit_render_folder(doc, folder):
    """Read scene state, build a manifest for the chosen folder, and audit it."""
    import c4d  # noqa: F401 - function-local by contract; this function is C4D-bound.

    try:
        states = _read_scene_render_state(doc)
    except Exception as exc:
        # Read failure -> explicit FAIL report, never a false-GREEN "nothing to validate".
        return _error_findings(exc)
    manifest = build_manifest_from_state(states, folder)
    return audit_manifest(manifest, folder)


def expected_frames(start, end, step):
    """Return the inclusive expected frame list for a render range."""
    return list(range(start, end + 1, step))


def detect_stale_cluster(mtimes_by_frame, gap_factor=6.0):
    """Return frames in the oldest mtime cluster when a session gap is detected."""
    if len(mtimes_by_frame) < 3:
        return []

    ordered = sorted(mtimes_by_frame.items(), key=lambda item: item[1])
    mtimes = [mtime for _, mtime in ordered]
    deltas = [b - a for a, b in zip(mtimes, mtimes[1:])]
    median_delta = statistics.median(deltas)
    if median_delta == 0:
        return []

    largest_index, largest_gap = max(enumerate(deltas), key=lambda item: item[1])
    if largest_gap > gap_factor * median_delta and largest_gap >= MIN_STALE_GAP_SECONDS:
        return sorted(frame for frame, _ in ordered[: largest_index + 1])
    return []


def scan_sequence(folder, prefix, frame_set, ext):
    """Enumerate a rendered sequence and classify missing or suspect frames."""
    expected = set(frame_set)
    result = {
        "found": [],
        "missing": [],
        "zero_byte": [],
        "truncated": [],
        "stale": [],
    }
    try:
        paths_by_frame = _paths_by_frame(folder, prefix, expected, ext)
    except OSError:
        result["missing"] = sorted(expected)
        return result

    valid_mtimes = {}
    candidates = []
    for frame in sorted(expected):
        path = paths_by_frame.get(frame)
        if path is None:
            result["missing"].append(frame)
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            result["missing"].append(frame)
            continue
        if size == 0:
            result["zero_byte"].append(frame)
            continue
        if size < MIN_VIABLE_BYTES:
            result["truncated"].append(frame)
            continue
        try:
            valid_mtimes[frame] = os.path.getmtime(path)
        except OSError:
            result["missing"].append(frame)
            continue
        candidates.append(frame)

    # Mtime can be unreliable on copied/synced folders, so later units should
    # treat this as a warning signal. U3 only separates older-session frames.
    stale = set(detect_stale_cluster(valid_mtimes))
    result["stale"] = sorted(stale)
    result["found"] = [frame for frame in candidates if frame not in stale]
    return result


def size_outliers(sizes_by_frame, sigma=3.0):
    """Flag frames whose size deviates beyond a robust median/MAD threshold."""
    if len(sizes_by_frame) <= 2:
        return []

    sizes = list(sizes_by_frame.values())
    median_size = statistics.median(sizes)
    deviations = [abs(size - median_size) for size in sizes]
    # MAD scaled by 1.4826 gives a sigma-comparable robust deviation estimate.
    robust_deviation = statistics.median(deviations) * 1.4826
    if robust_deviation == 0:
        return []

    threshold = sigma * robust_deviation
    return sorted(
        frame
        for frame, size in sizes_by_frame.items()
        if abs(size - median_size) > threshold
    )
