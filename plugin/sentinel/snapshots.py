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

# Display-referred snapshot exts RenderView can write when "Save snapshots as
# EXR" is off. Tracked through the SAME settle registry as .exr so a stable
# PNG/JPG/TIFF also becomes "ready" (streamlined flow: passthrough-copy these
# instead of treating them as an error state — see ui.flows.snapshot_auto_convert).
DISPLAY_REFERRED_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff")
SNAPSHOT_EXTS = (".exr",) + DISPLAY_REFERRED_EXTS


def scan_snapshot_candidates(snap_dir, registry, now=None):
    """Scan ``snap_dir`` for snapshots that are ready to auto-convert/copy.

    Pure + importable without c4d. Returns a 3-tuple:
        (ready_to_convert, updated_registry, non_exr_alert)

    - ``ready_to_convert``: list of absolute paths to snapshots (.exr AND
      display-referred exts in SNAPSHOT_EXTS) that just settled (stable
      across two consecutive scans) and were not already processed. A given
      name+mtime is returned at most once across the session. Mixed exts
      share one settle registry.
    - ``updated_registry``: the new registry dict to pass into the next scan.
    - ``non_exr_alert``: True when the newest file in the directory is NOT an
      .exr and is newer than the newest .exr (Redshift silently switched away
      from EXR output). False when an EXR is newest, or the dir is empty.
      This is now an informational flag for the caller (display-referred
      snapshots are still handled, just copied instead of ACES-converted),
      not an error condition.

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
        lname = name.lower()
        is_exr = lname.endswith(".exr")
        is_snapshot = lname.endswith(SNAPSHOT_EXTS)
        # Ignore obvious hidden/partial dotfiles for the alert + settle logic.
        if name.startswith("."):
            continue
        if newest_any is None or m > newest_any[0]:
            newest_any = (m, name)
        if is_snapshot:
            # Both .exr and display-referred exts feed the same settle
            # registry — a stable PNG/JPG is just as "ready" as a stable EXR.
            stats[name] = (m, s)
        if is_exr:
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


class SnapshotWatch:
    """Main-thread scheduler with one daemon converter and no queued C4D refs.

    Unstarted files remain in the settle registry while busy. Switching context
    primes a fresh registry, so old snapshots never acquire a new scene target.
    An in-flight conversion may finish after disabling, at its captured target.
    """
    def __init__(self):
        import queue
        self._registry = {}
        self._context = None
        self._thread = None
        self._results = queue.Queue(maxsize=1)
        self._generation = 0
        self._last_error = ""
        self._status = {"state": "off", "message": ""}

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def status(self):
        return dict(self._status, last_error=self._last_error)

    def tick(self, enabled, snap_dir, context, prepare, execute):
        import queue
        import threading
        try:
            generation, ok, message = self._results.get_nowait()
            if generation == self._generation:
                if not ok:
                    self._last_error = message
                self._status = {"state": "ready" if ok else "error", "message": message}
        except queue.Empty:
            pass
        key = (os.path.normcase(os.path.abspath(snap_dir)), context) if enabled and snap_dir else None
        if key != self._context:
            self._generation += 1
            self._last_error = ""
            self._context = key
            self._registry = {}
            self._status = {"state": "watching" if key else "off", "message": ""}
            if key:
                _, initial, _ = scan_snapshot_candidates(snap_dir, {})
                self._registry = {name: (m, size, "processed") for name, (m, size, _) in initial.items()}
            return
        if key is None:
            return
        if not os.path.isdir(snap_dir):
            self._status = {"state": "error", "message": "Snapshot directory unavailable"}
            return
        ready, self._registry, _ = scan_snapshot_candidates(snap_dir, self._registry)
        # Apply backpressure without allocating a task queue: unstarted files
        # stay pending and are reconsidered at the next scan.
        chosen = None if self.busy else next(iter(sorted(ready)), None)
        for path in ready:
            if path != chosen:
                name = os.path.basename(path)
                m, size, _ = self._registry[name]
                self._registry[name] = (m, size, "pending")
        if chosen is None:
            return
        try:
            task = prepare(chosen)  # Only this callback may read C4D.
        except Exception as exc:
            self._last_error = str(exc)
            self._status = {"state": "error", "message": str(exc)}
            return
        generation = self._generation
        self._status = {"state": "running", "message": "Processing " + os.path.basename(chosen)}
        def run():
            try:
                ok, message = execute(task)
            except Exception as exc:
                ok, message = False, str(exc)
            self._results.put((generation, ok, message))
        self._thread = threading.Thread(target=run, name="SentinelSnapshot", daemon=True)
        self._thread.start()


def run_snapshot_task(task):
    """Filesystem/converter worker.

    The task holds captured scalars plus, on C4D 2025.2+, the document's OCIO
    converter (``ocio``) and the slate font description (``font``) taken on
    the main thread — neither is a scene node, and both were measured safe to
    use from this worker. Without ``ocio`` the external converter is used.
    """
    import tempfile
    source = task["source"]
    output_dir = task["output_dir"]
    os.makedirs(output_dir, exist_ok=True)
    is_exr = source.lower().endswith(".exr")
    ext = ".png" if is_exr else (os.path.splitext(source)[1] or ".png")
    temporary = None
    try:
        if is_exr:
            fd, temporary = tempfile.mkstemp(prefix=".sentinel_snapshot_", suffix=".png", dir=output_dir)
            os.close(fd)
            if task.get("ocio") is not None:
                from sentinel.snapshot_c4d import convert_snapshot
                ok, error = convert_snapshot(source, temporary, task["ocio"],
                                             slate=task.get("slate"), font=task.get("font"),
                                             style=task.get("slate_style"))
            else:
                ok, error = _convert_exr_to_png(source, temporary, slate_data=task.get("slate"))
            if not ok:
                return False, error or "Conversion failed"
        # Exclusive creation protects snapshots from concurrent writers.
        name = publish_numbered(temporary or source, output_dir, task["scene_name"], ext=ext)
        message = ("converted " if is_exr else "copied ") + name
        # In-C4D conversion reports the RenderView post it re-applied or not.
        if is_exr and task.get("ocio") is not None and error:
            message += " · " + error
        return True, message
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass


snapshot_watch = SnapshotWatch()


# ── EXR header — what RenderView recorded with each snapshot ─────────────

_EXR_MAGIC = b"\x76\x2f\x31\x01"
_EXR_HEADER_LIMIT = 4 * 1024 * 1024


def read_exr_attributes(path):
    """``{name: value}`` for the string/int/float/double/v2f attributes of an EXR's
    first header. Pure, stdlib only; ``{}`` when the file is not a readable
    EXR. Redshift snapshots carry hundreds of attributes, including
    ``FrameID``, ``capDate`` and the RenderView OCIO view (``ocioView``)."""
    import struct
    attrs = {}
    try:
        with open(path, "rb") as handle:
            data = handle.read(_EXR_HEADER_LIMIT)
    except OSError:
        return attrs
    if data[:4] != _EXR_MAGIC:
        return attrs
    pos = 8
    while pos < len(data):
        end = data.find(b"\x00", pos)
        if end < 0 or end == pos:          # empty name ends the header
            break
        name = data[pos:end].decode("latin-1")
        tend = data.find(b"\x00", end + 1)
        if tend < 0 or tend + 5 > len(data):
            break
        kind = data[end + 1:tend]
        size = struct.unpack("<i", data[tend + 1:tend + 5])[0]
        value = data[tend + 5:tend + 5 + size]
        if size < 0 or len(value) < size:
            break
        if kind == b"string":
            attrs[name] = value.decode("utf-8", "replace")
        elif kind == b"int" and size == 4:
            attrs[name] = struct.unpack("<i", value)[0]
        elif kind == b"float" and size == 4:
            attrs[name] = struct.unpack("<f", value)[0]
        elif kind == b"double" and size == 8:
            attrs[name] = struct.unpack("<d", value)[0]
        elif kind == b"v2f" and size == 8:
            attrs[name] = struct.unpack("<2f", value)
        pos = tend + 5 + size
    return attrs


def snapshot_capture_fields(attrs):
    """Slate fields RenderView recorded at capture time: frame, date, time, view.

    ``capDate`` is ``YYYY:MM:DD HH:MM:SS``. Missing attributes are omitted, so
    the caller keeps its own fallback (the document frame, today's date).
    """
    fields = {}
    if isinstance(attrs.get("FrameID"), int):
        fields["frame"] = attrs["FrameID"]
    stamp = str(attrs.get("capDate") or "").strip()
    if len(stamp) >= 16 and stamp[4] == ":" and stamp[7] == ":":
        fields["date"] = stamp[:10].replace(":", "-")
        fields["time"] = stamp[11:16]
    if attrs.get("ocioView"):
        fields["view"] = str(attrs["ocioView"])
    return fields


# ── RenderView snapshot dir auto-detect — pure parser ─────────────────────

def parse_rv_snapshot_dir(cfg_text):
    """Extract the "snapshotDir" value from a redshift_rv.cfg dump.

    Pure + importable without c4d. The file is JSON-LIKE (tab-indented,
    verified real-world line shape:
        \t\t"snapshotDir" : "/Users/artist/Documents/RS Snapshots",
    ) but not always strict JSON (trailing commas appear in some builds), so
    a whole-text json.loads is tried first (fast path when the file happens
    to be valid JSON) and a regex scan for the "snapshotDir" key is the
    fallback for the more common malformed/older cfg shape. Returns None
    when the key is absent, its value is empty, or the text can't be parsed
    at all. Never raises.
    """
    if not cfg_text:
        return None

    try:
        import json
        data = json.loads(cfg_text)
        if isinstance(data, dict):
            value = data.get("snapshotDir")
            if isinstance(value, str) and value:
                return value
    except (ValueError, TypeError):
        pass

    import re
    match = re.search(r'"snapshotDir"\s*:\s*"([^"]*)"', cfg_text)
    if match and match.group(1):
        return match.group(1)
    return None


# ── Unique still naming — pure logic ───────────────────────────────────────

def next_snapshot_name(existing_names, scene_name, ext=".png"):
    """Return the next unique "<scene>_snap_NNN<ext>" name for a stills dir.

    Pure + importable without c4d. Scans ``existing_names`` (typically
    ``os.listdir()`` of the output dir) for any file belonging to this scene
    (``<scene>_snap_`` prefix) REGARDLESS of extension — a prior .png and a
    freshly-copied .jpg must not collide on the same index — and returns the
    next zero-padded 3-digit index. Uses a plain string prefix match (not a
    regex built from ``scene_name``) so scene names containing regex-special
    characters (parentheses, brackets, dots...) are handled safely. Unrelated
    filenames (no matching prefix, or a non-digit suffix) are ignored.
    """
    prefix = f"{scene_name}_snap_"
    highest = 0
    for name in existing_names or ():
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        digits = ""
        for ch in rest:
            if not ch.isdigit():
                break
            digits += ch
        if digits:
            idx = int(digits)
            if idx > highest:
                highest = idx
    return f"{prefix}{highest + 1:03d}{ext}"


# RenderView writes .rssnap2 (its own format) when "Save snapshots as EXR" is
# off — counted here so the panel can say so, never converted.
SOURCE_EXTS = SNAPSHOT_EXTS + (".rssnap2", ".rssnap")
_SOURCE_STATE_CACHE = {}


def snapshot_source_state(snap_dir):
    """What the RenderView snapshot folder says about the EXR setting.

    ``{"newest_ext": ".exr"|".rssnap2"|…|None, "alert": None|"non_exr"|"empty"|"missing"}``.
    Only snapshot-like files count (a stray .txt never raises the alarm).
    Cached by the folder's mtime, which changes when a file is added, so the
    panel's 2 s poll scans once per new snapshot, not every poll.
    """
    if not snap_dir or not os.path.isdir(snap_dir):
        return {"newest_ext": None, "alert": "missing"}
    try:
        key = (os.path.normcase(os.path.abspath(snap_dir)), os.stat(snap_dir).st_mtime_ns)
    except OSError:
        return {"newest_ext": None, "alert": "missing"}
    cached = _SOURCE_STATE_CACHE.get(key[0])
    if cached and cached[0] == key[1]:
        return dict(cached[1])
    newest = None
    try:
        for entry in os.scandir(snap_dir):
            name = entry.name
            if name.startswith(".") or not name.lower().endswith(SOURCE_EXTS):
                continue
            try:
                if not entry.is_file():
                    continue
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest[0]:
                newest = (mtime, os.path.splitext(name)[1].lower())
    except OSError:
        return {"newest_ext": None, "alert": "missing"}
    if newest is None:
        state = {"newest_ext": None, "alert": "empty"}
    else:
        state = {"newest_ext": newest[1], "alert": None if newest[1] == ".exr" else "non_exr"}
    _SOURCE_STATE_CACHE[key[0]] = (key[1], dict(state))
    return state


def stills_location(doc, artist_name):
    """``(absolute, relative-to-project or None)`` of where stills land —
    the same folder ``_get_stills_dir`` creates, without creating it. The
    relative form is None for an unsaved scene (the home-folder fallback)."""
    absolute = _get_stills_dir(doc, artist_name or "<artist>", create=False)
    doc_path = doc.GetDocumentPath() or ""
    if not doc_path:
        return absolute, None
    root = os.path.dirname(os.path.dirname(doc_path))
    try:
        return absolute, os.path.relpath(absolute, root)
    except ValueError:            # different drives on Windows
        return absolute, None


def publish_numbered(source_path, output_dir, scene_name, ext=".png", attempts=50):
    """Copy ``source_path`` into ``output_dir`` as the next free
    ``<scene>_snap_NNN<ext>`` and return that name.

    The name is claimed with exclusive creation, so Save Still and the
    watch-folder worker can never overwrite each other: when another writer
    takes the number first, the next one is tried.
    """
    import shutil
    for _attempt in range(attempts):
        name = next_snapshot_name(os.listdir(output_dir), scene_name, ext=ext)
        output = os.path.join(output_dir, name)
        try:
            dest = open(output, "xb")
        except FileExistsError:
            continue
        try:
            with dest, open(source_path, "rb") as src:
                shutil.copyfileobj(src, dest)
        except Exception:
            try:
                os.remove(output)
            except OSError:
                pass
            raise
        return name
    raise RuntimeError("No free snapshot number in %s" % output_dir)


def _get_stills_dir(doc, artist_name, create=True):
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
    if create:
        os.makedirs(output_dir, exist_ok=True)
    return output_dir

def _find_latest_exr(snap_dir=None):
    """Find the most recent EXR in the RS snapshot directory.

    ``snap_dir`` lets a caller pass an already-resolved effective directory
    (e.g. ui.flows.get_effective_snapshot_dir(), which auto-detects the live
    RenderView dir before falling back to the manual Settings value). This
    module stays c4d-free, so when omitted it falls back to the manual
    Settings value directly rather than auto-detecting.
    """
    if snap_dir is None:
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


def build_slate_data(doc, artist_name, frame=None, project=""):
    """Assemble the review-slate fields from the doc + its version history.

    Pure adapter: reads the LATEST entry of the scene's ``<base>_history.json``
    via sentinel.versioning and combines it with shot (active take/doc) + now.
    Also the extra slate tokens: ``scene`` (base name without ``_v###``),
    ``take`` (empty on the Main take), ``camera`` and ``time``. ``project`` is
    passed in (the folder of the active ruleset). Frame, date, time and view
    are replaced at conversion time by what the snapshot EXR recorded.
    Returns a JSON-serializable dict; never raises.
    """
    from datetime import datetime
    from sentinel.versioning import get_latest_version_info, parse_version_filename

    shot = ""
    take = ""
    try:
        td = doc.GetTakeData() if doc else None
        if td:
            cur = td.GetCurrentTake()
            if cur:
                shot = cur.GetName() or ""
                if cur != td.GetMainTake():
                    take = shot
    except Exception:
        shot = ""
    scene = ""
    try:
        scene = parse_version_filename(os.path.splitext(doc.GetDocumentName() or "")[0])[0]
    except Exception:
        scene = ""
    camera = ""
    try:
        cam = doc.GetRenderBaseDraw().GetSceneCamera(doc)
        camera = cam.GetName() if cam else ""
    except Exception:
        camera = ""
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
        "time": datetime.now().strftime("%H:%M"),
        "frame": frame if frame is not None else "",
        "scene": scene or "",
        "take": take or "",
        "camera": camera or "",
        "project": project or "",
    }


def _convert_exr_to_png(exr_path, png_path, slate_data=None):
    """Convert EXR to PNG via external Python with OpenEXR + ACES pipeline.

    Only for C4D older than 2025.2: newer hosts convert in-process with the
    document's OCIO view (``sentinel.snapshot_c4d``), which matches RenderView
    exactly; this converter approximates the ACES curve.

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
