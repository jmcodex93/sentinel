# -*- coding: utf-8 -*-
"""Snapshot / EXR-to-PNG helpers for Sentinel (cross-platform).

Pure helpers extracted from ui/panel.py (Phase 4). No c4d.gui here — the
dialog-bearing wrappers (snapshot_save_still / snapshot_open_folder) live in
sentinel.ui.flows.
"""
import os
import sys

from sentinel.common.settings import GlobalSettings
from sentinel.common.helpers import safe_print

_ROOT = os.path.dirname(os.path.dirname(__file__))


# ── Snapshot watchfolder (auto-convert) — pure logic ──────────────────────
#
# Registry = dict keyed by filename -> (mtime, size, state), where state is one
# of "pending" (sighted, awaiting settle confirmation) or "processed" (already
# handed to conversion). Session memory only; no sidecar. The settle rule is
# scan-count based (NOT wall-clock): a file is "ready" only when two consecutive
# scans report an IDENTICAL (mtime, size) — Redshift's write atomicity is
# undocumented, so a single sighting can be a half-written file.

def scan_snapshot_candidates(snap_dir, registry, now=None):
    """Scan ``snap_dir`` for EXR snapshots that are ready to auto-convert.

    Pure + importable without c4d. Returns a 3-tuple:
        (ready_to_convert, updated_registry, non_exr_alert)

    - ``ready_to_convert``: list of absolute paths to EXRs that just settled
      (stable across two consecutive scans) and were not already processed.
      A given name+mtime is returned at most once across the session.
    - ``updated_registry``: the new registry dict to pass into the next scan.
    - ``non_exr_alert``: True when the newest file in the directory is NOT an
      .exr and is newer than the newest .exr (Redshift silently switched away
      from EXR output). False when an EXR is newest, or the dir is empty.

    ``registry`` may be None/empty on the first call. ``now`` is accepted for
    signature stability but the settle rule does not depend on wall-clock time.
    Missing/unreadable directory -> ([], registry-as-dict, False); never raises.
    """
    registry = dict(registry) if registry else {}

    if not snap_dir or not os.path.isdir(snap_dir):
        return [], registry, False

    try:
        entries = list(os.scandir(snap_dir))
    except OSError:
        return [], registry, False

    # Collect (name, mtime, size) for regular files, tracking newest overall
    # and newest .exr for the non-EXR alert.
    stats = {}
    newest_any = None       # (mtime, name)
    newest_exr = None       # (mtime, name)
    for e in entries:
        try:
            if not e.is_file():
                continue
            st = e.stat()
        except OSError:
            continue
        name = e.name
        m, s = st.st_mtime, st.st_size
        is_exr = name.lower().endswith(".exr")
        # Ignore obvious hidden/partial dotfiles for the alert + settle logic.
        if name.startswith("."):
            continue
        if newest_any is None or m > newest_any[0]:
            newest_any = (m, name)
        if is_exr:
            stats[name] = (m, s)
            if newest_exr is None or m > newest_exr[0]:
                newest_exr = (m, name)

    ready = []
    updated = {}
    for name, (m, s) in stats.items():
        prev = registry.get(name)
        if prev is None:
            # First sighting — never ready.
            updated[name] = (m, s, "pending")
            continue
        pm, ps, pstate = prev
        if pstate == "processed":
            if (m, s) == (pm, ps):
                updated[name] = prev  # already converted; never again
            else:
                # File changed after processing (a new snapshot reused the
                # name) — re-arm the settle cycle.
                updated[name] = (m, s, "pending")
            continue
        # pstate == "pending"
        if (m, s) == (pm, ps):
            updated[name] = (m, s, "processed")
            ready.append(os.path.join(snap_dir, name))
        else:
            # Changed since last scan — settle reset.
            updated[name] = (m, s, "pending")

    # Non-EXR alert: newest file overall is a non-EXR and strictly newer than
    # the newest EXR (or there is no EXR at all but a non-EXR exists).
    non_exr_alert = False
    if newest_any is not None:
        if newest_exr is None:
            non_exr_alert = True
        elif newest_any[0] > newest_exr[0] and newest_any[1] != newest_exr[1]:
            non_exr_alert = True

    return ready, updated, non_exr_alert


def _get_stills_dir(doc, artist_name):
    """Get output directory: project_root/output/stills/Artist/YYMMDD/"""
    from datetime import datetime
    doc_path = doc.GetDocumentPath() or ""
    if doc_path:
        project_root = os.path.dirname(os.path.dirname(doc_path))
    else:
        project_root = os.path.join(os.path.expanduser("~"), "YS_Guardian_Output")

    output_dir = os.path.join(
        project_root, "output", "stills",
        artist_name or "Unknown",
        datetime.now().strftime("%y%m%d")
    )
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def _find_latest_exr():
    """Find the most recent EXR in the RS snapshot directory"""
    snap_dir = GlobalSettings.get_snapshot_dir()
    if not os.path.exists(snap_dir):
        return None, f"Snapshot directory not found:\n{snap_dir}\n\nConfigure it in Redshift RenderView > Preferences > Snapshots"

    exr_files = []
    for f in os.listdir(snap_dir):
        if f.lower().endswith('.exr'):
            full = os.path.join(snap_dir, f)
            exr_files.append((full, os.path.getmtime(full)))

    if not exr_files:
        return None, f"No EXR snapshots found in:\n{snap_dir}\n\nTake a snapshot in RS RenderView first."

    exr_files.sort(key=lambda x: x[1], reverse=True)
    return exr_files[0][0], None

def _find_system_python():
    """Find a system Python 3 with OpenEXR support (cross-platform)"""
    import subprocess

    candidates = []
    if sys.platform == "darwin":
        candidates = ["/usr/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3"]
    else:
        import glob
        candidates = ["python", "python3"]
        for pattern in [r"C:\Program Files\Python*\python.exe",
                        r"C:\Program Files (x86)\Python*\python.exe"]:
            candidates.extend(glob.glob(pattern))
        user_local = os.path.expanduser("~")
        for pattern in [os.path.join(user_local, r"AppData\Local\Programs\Python\Python*\python.exe")]:
            candidates.extend(glob.glob(pattern))

    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import OpenEXR, numpy, PIL; print('OK')"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and "OK" in result.stdout:
                safe_print(f"Found system Python with OpenEXR: {py}")
                return py
        except Exception:
            continue

    return None

_CACHED_PYTHON = None


def build_slate_data(doc, artist_name, frame=None):
    """Assemble the review-slate fields from the doc + its version history.

    Pure adapter: reads the LATEST entry of the scene's ``<base>_history.json``
    via sentinel.versioning and combines it with shot (active take/doc) + now.
    Returns a JSON-serializable dict; never raises.
    """
    from datetime import datetime
    from sentinel.versioning import get_latest_version_info

    shot = ""
    try:
        td = doc.GetTakeData() if doc else None
        if td:
            cur = td.GetCurrentTake()
            if cur:
                shot = cur.GetName() or ""
    except Exception:
        shot = ""
    if not shot and doc:
        try:
            shot = os.path.splitext(doc.GetDocumentName() or "")[0]
        except Exception:
            shot = ""

    version_label = ""
    status = "WIP"
    score = ""
    try:
        latest = get_latest_version_info(doc)
        if latest:
            try:
                version_label = "v%03d" % int(latest.get("version"))
            except (TypeError, ValueError):
                version_label = ""
            status = (latest.get("status") or "").upper() or "WIP"
            score = latest.get("qc_score", "") or ""
    except Exception:
        pass

    if frame is None and doc is not None:
        try:
            frame = doc.GetTime().GetFrame(doc.GetFps())
        except Exception:
            frame = None

    return {
        "shot": shot or "",
        "version": version_label,
        "status": status,
        "score": score,
        "artist": artist_name or "",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "frame": frame if frame is not None else "",
    }


def _convert_exr_to_png(exr_path, png_path, slate_data=None):
    """Convert EXR to PNG via external Python with OpenEXR + ACES pipeline.

    When ``slate_data`` is provided it is written to a temp JSON and passed to
    the converter via ``--slate`` so a review-slate strip + PNG metadata are
    burned in. None keeps the legacy (byte-identical) conversion.
    """
    import subprocess
    import tempfile

    global _CACHED_PYTHON
    if not _CACHED_PYTHON:
        _CACHED_PYTHON = _find_system_python()

    if not _CACHED_PYTHON:
        return False, ("System Python with OpenEXR not found.\n\n"
                       "Install dependencies:\n"
                       "  pip3 install OpenEXR numpy Pillow")

    # Use the existing external converter script
    converter = os.path.join(_ROOT, "exr_converter_external.py")
    if not os.path.exists(converter):
        return False, f"Converter script not found: {converter}"

    slate_path = None
    if slate_data:
        try:
            import json
            fd, slate_path = tempfile.mkstemp(prefix="sentinel_slate_", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(slate_data, handle, ensure_ascii=False)
        except Exception as e:
            safe_print(f"Could not write slate data (skipping slate): {e}")
            slate_path = None

    cmd = [_CACHED_PYTHON, converter, exr_path, png_path, "aces"]
    if slate_path:
        cmd += ["--slate", slate_path]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )

        if result.returncode == 0 and os.path.exists(png_path):
            safe_print(f"Conversion complete: {os.path.basename(png_path)}")
            return True, None
        else:
            error = result.stderr or result.stdout or "Unknown error"
            safe_print(f"Converter error: {error}")
            return False, f"Conversion failed:\n{error[:300]}"

    except subprocess.TimeoutExpired:
        return False, "Conversion timed out (>120s)"
    except Exception as e:
        return False, f"Error running converter: {e}"
    finally:
        if slate_path:
            try:
                os.remove(slate_path)
            except Exception:
                pass
