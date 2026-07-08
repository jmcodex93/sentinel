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

def _convert_exr_to_png(exr_path, png_path):
    """Convert EXR to PNG via external Python with OpenEXR + ACES pipeline"""
    import subprocess

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

    try:
        result = subprocess.run(
            [_CACHED_PYTHON, converter, exr_path, png_path, "aces"],
            capture_output=True, text=True, timeout=120
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
