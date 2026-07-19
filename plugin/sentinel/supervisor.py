# -*- coding: utf-8 -*-
"""Supervisor — folder-wide QC aggregation from per-scene sidecars (I5-A).

Point Sentinel at a project folder and aggregate every scene's history/notes
sidecars WITHOUT opening any ``.c4d`` file: a per-shot supervisor table (last
version, status, QC score, pending TODOs, days idle, flags) + a per-shot QC
trajectory (which registry check broke/recovered in which version) + a single
self-contained static HTML export. Filesystem is the database — no server.

Follows the postrender.py / doctor.py house pattern: the core is stdlib-only
and PURE (no top-level ``import c4d``), so pytest can cover it without Cinema
4D. It reuses the real sidecar readers from ``sentinel.versioning`` /
``sentinel.notes`` and the check labels from ``sentinel.qc.registry`` — nothing
is reimplemented. ``now`` is injectable everywhere so time-based flags are
deterministic under test.
"""

import html
import os
import re
from datetime import datetime, timedelta

# Reuse the real sidecar readers + check registry. Prefer the package import;
# fall back to loading the pure modules by path so supervisor stays importable
# with no ``sentinel`` package on sys.path (same defence as postrender.py).
try:
    from sentinel.versioning import load_history, format_history_qc_label
    from sentinel.notes import load_notes
    from sentinel.qc.registry import CHECK_REGISTRY
except ModuleNotFoundError:  # pragma: no cover - exercised only fully standalone
    import importlib.util

    _here = os.path.dirname(os.path.abspath(__file__))

    def _load_by_path(mod_name, rel_path):
        spec = importlib.util.spec_from_file_location(
            mod_name, os.path.join(_here, rel_path)
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    _versioning = _load_by_path("sentinel_supervisor_versioning", "versioning.py")
    load_history = _versioning.load_history
    format_history_qc_label = _versioning.format_history_qc_label
    _registry = _load_by_path(
        "sentinel_supervisor_registry", os.path.join("qc", "registry.py")
    )
    CHECK_REGISTRY = _registry.CHECK_REGISTRY

    def load_notes(notes_path):
        """Minimal stand-in when the notes package cannot be imported."""
        import json as _json

        default = {"scene": "", "updated": "", "notes": "", "todos": []}
        if not notes_path or not os.path.exists(notes_path):
            return default
        try:
            with open(notes_path, "r") as fh:
                data = _json.load(fh)
        except Exception:
            return default
        if not isinstance(data, dict):
            return default
        if not isinstance(data.get("todos"), list):
            data["todos"] = []
        if not isinstance(data.get("notes"), str):
            data["notes"] = ""
        return data


# ── Module constants ─────────────────────────────────────────────────────────
STALE_DAYS = 7
REGRESSION_WINDOW = 3
# Depth cap for the recursive folder walk. A shot tree rarely nests this deep;
# the cap keeps a mis-pointed scan (e.g. a whole drive) from walking forever.
MAX_WALK_DEPTH = 6
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_EXPORT_NAME = "sentinel_supervisor.html"

_HISTORY_SUFFIX = "_history.json"
_RENDER_HISTORY_SUFFIX = "_render_history.json"
_SCORE_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


# ── Pure helpers ─────────────────────────────────────────────────────────────
def check_label_map():
    """check_id -> registry row label (e.g. 'textures' -> 'Assets')."""
    out = {}
    for entry in CHECK_REGISTRY:
        cid = getattr(entry, "check_id", None)
        if cid:
            out[cid] = getattr(entry, "row_label", cid)
    return out


def parse_timestamp(value):
    """Parse the sidecar timestamp format written by flows/versioning.

    Returns a naive ``datetime`` or ``None`` when the value is missing/malformed.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIMESTAMP_FORMAT)
    except (ValueError, TypeError):
        return None


def parse_score(qc_score):
    """Parse a 'passed/total' QC score string into (passed, total) or None."""
    if not qc_score:
        return None
    match = _SCORE_RE.search(str(qc_score))
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def _version_label(entry):
    """'v008' from an entry's numeric version, falling back to its filename."""
    try:
        return "v%03d" % int(entry.get("version"))
    except (TypeError, ValueError):
        filename = entry.get("filename") or ""
        return os.path.splitext(filename)[0] or "?"


def _status_display(entry):
    status = (entry.get("status") or "").upper()
    return status if status else "WIP"


def notes_path_for_history(history_path):
    """Sibling ``<base>_notes.json`` for a ``<base>_history.json`` path."""
    if not history_path:
        return None
    folder = os.path.dirname(history_path)
    filename = os.path.basename(history_path)
    if not filename.endswith(_HISTORY_SUFFIX):
        return None
    base = filename[: -len(_HISTORY_SUFFIX)]
    return os.path.join(folder, base + "_notes.json")


def find_history_files(folder, max_depth=MAX_WALK_DEPTH):
    """Return every ``*_history.json`` under ``folder`` (recursive, depth-capped).

    ``*_render_history.json`` (the post-render sidecar) is explicitly excluded —
    it is NOT the Versions-tab history and carries no version trajectory.
    """
    results = []
    if not folder or not os.path.isdir(folder):
        return results
    base_depth = folder.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(folder):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        for name in files:
            if name.endswith(_RENDER_HISTORY_SUFFIX):
                continue
            if name.endswith(_HISTORY_SUFFIX):
                results.append(os.path.join(root, name))
    return sorted(results)


def _read_history(history_path):
    """Read a history sidecar, distinguishing corruption from a clean read.

    Returns ``(data, warning)``. ``data`` is None when the file could not be
    parsed as a valid history dict; ``warning`` is a human string in that case.
    """
    import json

    try:
        with open(history_path, "r") as fh:
            data = json.load(fh)
    except ValueError as exc:
        return None, "Corrupted (unparseable JSON): %s (%s)" % (history_path, exc)
    except OSError as exc:
        return None, "Unreadable: %s (%s)" % (history_path, exc)
    if not isinstance(data, dict) or not isinstance(data.get("versions"), list):
        return None, "Corrupted (unexpected structure): %s" % history_path
    return data, None


# ── Flags ────────────────────────────────────────────────────────────────────
def is_regression(versions, window=REGRESSION_WINDOW):
    """True when the last ``window`` scored versions strictly worsen over time.

    ``versions`` is newest-first (as stored). We take the most recent ``window``
    entries that carry a parseable score and require the passed-count to be
    strictly descending chronologically (older > ... > newer).
    """
    scored = []
    for entry in versions:
        parsed = parse_score(entry.get("qc_score"))
        if parsed is not None:
            scored.append(parsed[0])
        if len(scored) >= window:
            break
    if len(scored) < window:
        return False
    # scored is newest-first; strictly descending over time == newest < ... < oldest.
    for i in range(len(scored) - 1):
        if not scored[i] < scored[i + 1]:
            return False
    return True


def is_stale(versions, now, stale_days=STALE_DAYS):
    """True when the latest entry is WIP/empty AND older than ``stale_days``."""
    if not versions:
        return False
    latest = versions[0]
    status = (latest.get("status") or "").upper()
    if status not in ("", "WIP"):
        return False
    ts = parse_timestamp(latest.get("timestamp"))
    if ts is None:
        return False
    return (now - ts) > timedelta(days=stale_days)


def compute_flags(versions, now):
    flags = []
    if is_regression(versions):
        flags.append("regression")
    if is_stale(versions, now):
        flags.append("stale")
    return flags


# ── Trajectory ───────────────────────────────────────────────────────────────
def build_trajectory(versions, label_map=None):
    """Per-hop broke/recovered lists across consecutive versions.

    Compares each pair's ``qc_counts`` (check_id -> new-violation count). A check
    "broke" when its count goes 0/absent -> >0; "recovered" when >0 -> 0. A hop
    where either side lacks ``qc_counts`` (legacy entries) is marked no_data.
    """
    if label_map is None:
        label_map = check_label_map()
    order = {cid: idx for idx, cid in enumerate(label_map)}
    chron = list(reversed(versions))  # oldest -> newest
    hops = []
    for older, newer in zip(chron, chron[1:]):
        hop = {
            "from_version": _version_label(older),
            "to_version": _version_label(newer),
            "broke": [],
            "recovered": [],
            "no_data": False,
        }
        older_counts = older.get("qc_counts")
        newer_counts = newer.get("qc_counts")
        if not isinstance(older_counts, dict) or not isinstance(newer_counts, dict):
            hop["no_data"] = True
            hops.append(hop)
            continue
        keys = set(older_counts) | set(newer_counts)
        for cid in sorted(keys, key=lambda c: (order.get(c, 10 ** 6), c)):
            label = label_map.get(cid, cid)
            try:
                old_n = int(older_counts.get(cid, 0) or 0)
                new_n = int(newer_counts.get(cid, 0) or 0)
            except (TypeError, ValueError):
                continue
            if old_n == 0 and new_n > 0:
                hop["broke"].append(label)
            elif old_n > 0 and new_n == 0:
                hop["recovered"].append(label)
        hops.append(hop)
    return hops


def _version_rows(versions):
    """Chronological (oldest-first) compact rows for display."""
    rows = []
    for entry in reversed(versions):
        rows.append(
            {
                "version": _version_label(entry),
                "status": _status_display(entry),
                "score": entry.get("qc_score", "") or "",
                "qc_label": format_history_qc_label(entry),
            }
        )
    return rows


# ── Shot summary + scan ──────────────────────────────────────────────────────
def build_shot_summary(history_path, data, notes, now, label_map=None):
    """Build one shot's summary from already-loaded sidecar data."""
    if label_map is None:
        label_map = check_label_map()
    versions = data.get("versions") or []
    latest = versions[0] if versions else {}

    filename = os.path.basename(history_path)
    base = data.get("scene") or (
        filename[: -len(_HISTORY_SUFFIX)] if filename.endswith(_HISTORY_SUFFIX) else filename
    )

    todos = (notes or {}).get("todos") or []
    todos_total = len(todos)
    todos_pending = sum(1 for t in todos if not t.get("done"))

    ts = parse_timestamp(latest.get("timestamp"))
    days_idle = (now - ts).days if ts is not None else None

    return {
        "base": base,
        "folder": os.path.dirname(history_path),
        "history_path": history_path,
        "version_count": len(versions),
        "last_version": _version_label(latest) if latest else "",
        "status": _status_display(latest) if latest else "",
        "score": latest.get("qc_score", "") or "",
        "qc_label": format_history_qc_label(latest) if latest else "",
        "todos_total": todos_total,
        "todos_pending": todos_pending,
        "notes_text": (notes or {}).get("notes", "") or "",
        "days_idle": days_idle,
        "last_timestamp": latest.get("timestamp", "") or "",
        "artist": latest.get("artist", "") or "",
        "flags": compute_flags(versions, now),
        "version_rows": _version_rows(versions),
        "trajectory": build_trajectory(versions, label_map),
    }


def scan_folder(folder, now=None):
    """Aggregate every history sidecar under ``folder`` into per-shot summaries.

    Returns ``(shots, meta)``. ``meta`` carries the folder, a generated
    timestamp, the shot count and a ``warnings`` list (one entry per corrupted
    or unreadable sidecar, which is skipped rather than crashing the scan).
    """
    if now is None:
        now = datetime.now()
    label_map = check_label_map()

    shots = []
    warnings = []
    for history_path in find_history_files(folder):
        data, warning = _read_history(history_path)
        if warning:
            warnings.append(warning)
            continue
        if not (data.get("versions") or []):
            continue  # valid but empty — nothing to report
        notes = load_notes(notes_path_for_history(history_path))
        shots.append(build_shot_summary(history_path, data, notes, now, label_map))

    shots.sort(key=lambda s: s["base"].lower())
    meta = {
        "folder": folder or "",
        "generated": now.strftime(TIMESTAMP_FORMAT),
        "shot_count": len(shots),
        "warnings": warnings,
    }
    return shots, meta


# ── Plain-text report (for the modal's monospaced field) ─────────────────────
def _flag_tags(flags):
    if not flags:
        return ""
    return "  [" + ", ".join(f.upper() for f in flags) + "]"


def build_supervisor_report(shots, meta):
    """Assemble a monospaced plain-text report for the dialog."""
    lines = ["Sentinel Supervisor", "=" * 30]
    lines.append("Folder    : %s" % meta.get("folder", "?"))
    lines.append("Generated : %s" % meta.get("generated", "?"))
    lines.append("Shots     : %s" % meta.get("shot_count", 0))
    warnings = meta.get("warnings") or []
    if warnings:
        lines.append("Warnings  : %d skipped sidecar(s)" % len(warnings))
    lines.append("-" * 30)

    if not shots:
        lines.append("")
        lines.append("No scene sidecars found in this folder.")
        lines.append("Save a version (Deliver tab) to create one.")
        if warnings:
            lines.append("")
            lines.append("Skipped:")
            for warn in warnings:
                lines.append("  - %s" % warn)
        return "\n".join(lines)

    header = "%-24s %-6s %-6s %-9s %-6s %-6s %s" % (
        "SHOT", "VER", "STATUS", "SCORE", "TODO", "IDLE", "FLAGS",
    )
    lines.append(header)
    for shot in shots:
        idle = "-" if shot["days_idle"] is None else "%dd" % shot["days_idle"]
        todo = "%d/%d" % (shot["todos_pending"], shot["todos_total"])
        lines.append(
            "%-24s %-6s %-6s %-9s %-6s %-6s %s"
            % (
                _truncate(shot["base"], 24),
                shot["last_version"],
                shot["status"],
                _truncate(shot["score"], 9),
                todo,
                idle,
                ", ".join(shot["flags"]),
            )
        )

    lines.append("")
    lines.append("=" * 30)
    lines.append("QC TRAJECTORIES")
    lines.append("=" * 30)
    for shot in shots:
        lines.append("")
        lines.append("%s%s" % (shot["base"], _flag_tags(shot["flags"])))
        for row in shot["version_rows"]:
            label = row["qc_label"] or row["score"] or "(no QC)"
            lines.append("   %-6s %-6s %s" % (row["version"], row["status"], label))
        for hop in shot["trajectory"]:
            arrow = "%s->%s" % (hop["from_version"], hop["to_version"])
            if hop["no_data"]:
                lines.append("     %s  no data" % arrow)
                continue
            if hop["broke"]:
                lines.append("     %s  broke: %s" % (arrow, ", ".join(hop["broke"])))
            if hop["recovered"]:
                lines.append(
                    "     %s  recovered: %s" % (arrow, ", ".join(hop["recovered"]))
                )

    if warnings:
        lines.append("")
        lines.append("Skipped sidecars:")
        for warn in warnings:
            lines.append("  - %s" % warn)
    return "\n".join(lines)


def _truncate(text, width):
    text = str(text or "")
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


# ── HTML export (pure) ───────────────────────────────────────────────────────
def _esc(value):
    return html.escape(str(value if value is not None else ""))


# Sentinel "SAFE AREA" design system (shared with docs/index.html): dark
# instrument theme by default, warm-paper light variant. Theme resolution:
# prefers-color-scheme is the default signal; a manual [data-theme] attribute
# (set by the tiny inline toggle script) wins in BOTH directions. Mono =
# vigilance (HUD/data), serif = judgment (headings), amber = the tally light.
# Semantic colors only ever appear paired with a text label (chip anatomy).
_LIGHT_TOKENS = """
  --bg-0:#F6F5F1; --bg-1:#FFFFFF; --bg-2:#ECEAE3;
  --line-1:#DCD9D0; --line-2:#B9B4A7;
  --text-1:#1A1B1E; --text-2:#565B63; --text-3:#8D9199;
  --accent:#8A5C00; --accent-dim:rgba(154,103,0,.10);
  --pass:#157F3D; --pass-dim:rgba(21,127,61,.10);
  --warn:#8A5C00; --warn-dim:rgba(154,103,0,.10);
  --fail:#C42B30; --fail-dim:rgba(196,43,48,.10);
  color-scheme: light;
"""

_DARK_TOKENS = """
  --bg-0:#0B0D10; --bg-1:#11141A; --bg-2:#171C23;
  --line-1:#232933; --line-2:#39424E;
  --text-1:#E9EDF2; --text-2:#A6B0BC; --text-3:#5F6B78;
  --accent:#FFB224; --accent-dim:rgba(255,178,36,.10);
  --pass:#45D183; --pass-dim:rgba(69,209,131,.12);
  --warn:#FFB224; --warn-dim:rgba(255,178,36,.12);
  --fail:#FF6161; --fail-dim:rgba(255,97,97,.12);
  color-scheme: dark;
"""

_HTML_STYLE = """
:root {
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --serif:ui-serif,"New York","Iowan Old Style",Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
""" + _DARK_TOKENS + """}
@media (prefers-color-scheme: light) { :root:not([data-theme]) {""" + _LIGHT_TOKENS + """} }
:root[data-theme="light"] {""" + _LIGHT_TOKENS + """}
:root[data-theme="dark"] {""" + _DARK_TOKENS + """}
.themetoggle { position:fixed; top:14px; right:14px; z-index:9;
  font-family:var(--mono); font-size:.68rem; letter-spacing:.12em;
  text-transform:uppercase; color:var(--text-3); background:var(--bg-1);
  border:1px solid var(--line-1); border-radius:4px; padding:5px 10px;
  cursor:pointer; }
.themetoggle:hover { color:var(--accent); border-color:var(--line-2); }
* { box-sizing: border-box; }
body { margin:0; padding:clamp(20px,4vw,48px); background:var(--bg-0);
  color:var(--text-1); font-family:var(--sans); line-height:1.55;
  -webkit-font-smoothing:antialiased; }
.wrap { max-width:1040px; margin:0 auto; }
.eyebrow { font-family:var(--mono); font-size:.72rem; font-weight:500;
  text-transform:uppercase; letter-spacing:.16em; color:var(--text-3);
  display:flex; align-items:center; gap:12px; }
.eyebrow .idx { color:var(--accent); }
.eyebrow .tick { display:inline-block; width:24px; height:1px;
  background:var(--line-2); }
h1 { font-family:var(--serif); font-weight:600; font-size:clamp(1.7rem,4vw,2.4rem);
  line-height:1.1; letter-spacing:-.005em; margin:.35em 0 .2em; }
.meta { font-family:var(--mono); font-size:.78rem; color:var(--text-2);
  margin-bottom:8px; overflow-wrap:anywhere; }
.meta b { color:var(--text-1); font-weight:500; }
.readouts { display:flex; flex-wrap:wrap; margin:28px 0 36px;
  border-top:1px solid var(--line-1); border-bottom:1px solid var(--line-1); }
.readout { flex:1 1 120px; padding:16px 20px 14px;
  border-right:1px solid var(--line-1); }
.readout:last-child { border-right:none; }
.readout .n { font-family:var(--mono); font-size:clamp(1.6rem,3vw,2.2rem);
  font-variant-numeric:tabular-nums; line-height:1; }
.readout .n::before { content:""; display:block; width:12px; height:2px;
  background:var(--accent); margin-bottom:10px; }
.readout .l { font-family:var(--mono); font-size:.66rem; text-transform:uppercase;
  letter-spacing:.14em; color:var(--text-3); margin-top:6px; }
h2 { font-family:var(--serif); font-weight:600; font-size:1.35rem;
  margin:44px 0 14px; }
.scroll { overflow-x:auto; border:1px solid var(--line-1); border-radius:6px;
  background:var(--bg-1); }
table { border-collapse:collapse; width:100%; font-size:.82rem; }
th,td { text-align:left; padding:10px 14px; white-space:nowrap;
  border-bottom:1px solid var(--line-1); }
th { font-family:var(--mono); font-weight:500; font-size:.66rem;
  text-transform:uppercase; letter-spacing:.14em; color:var(--text-3);
  background:var(--bg-2); }
tr:last-child td { border-bottom:none; }
td { font-family:var(--mono); color:var(--text-1); }
td .sub { color:var(--text-3); }
.chip { display:inline-flex; align-items:center; gap:6px; padding:2px 8px;
  border-radius:2px; font-family:var(--mono); font-size:.68rem; font-weight:500;
  text-transform:uppercase; letter-spacing:.08em; border:1px solid var(--line-2);
  color:var(--text-2); }
.chip::before { content:""; width:7px; height:7px; border-radius:50%;
  background:var(--text-3); }
.chip.review { color:var(--accent); border-color:var(--accent);
  background:var(--accent-dim); }
.chip.review::before { background:var(--accent); }
.chip.final { color:var(--pass); border-color:var(--pass);
  background:var(--pass-dim); }
.chip.final::before { background:var(--pass); }
.chip.warnf { color:var(--warn); border-color:var(--warn);
  background:var(--warn-dim); }
.chip.warnf::before { background:var(--warn); }
.chip.failf { color:var(--fail); border-color:var(--fail);
  background:var(--fail-dim); }
.chip.failf::before { background:var(--fail); }
.bar { display:inline-block; vertical-align:middle; width:64px; height:6px;
  background:var(--bg-2); border-radius:2px; margin-left:10px;
  overflow:hidden; }
.bar i { display:block; height:100%; background:var(--pass); }
.bar.partial i { background:var(--warn); }
.muted { color:var(--text-3); }
.shot { background:var(--bg-1); border:1px solid var(--line-1); border-radius:6px;
  padding:18px 22px; margin-bottom:14px; }
.shot h3 { font-family:var(--mono); font-weight:600; font-size:.95rem;
  margin:0 0 12px; display:flex; align-items:center; gap:10px; }
.vrow { font-family:var(--mono); font-size:.78rem; color:var(--text-2);
  display:flex; gap:18px; padding:3px 0; }
.vrow .v { color:var(--text-1); min-width:44px; }
.vrow .s { min-width:52px; }
.hops { margin-top:10px; padding-top:10px; border-top:1px solid var(--line-1); }
.hop { font-family:var(--mono); font-size:.78rem; padding:2px 0; }
.hop .arrow { color:var(--text-3); }
.hop.broke { color:var(--fail); }
.hop.recovered { color:var(--pass); }
.hop.nodata { color:var(--text-3); }
.warnbox { margin-top:28px; font-size:.8rem; color:var(--text-2);
  background:var(--warn-dim); border-left:3px solid var(--warn);
  border-radius:0 4px 4px 0; padding:12px 16px; font-family:var(--mono); }
.empty { background:var(--bg-1); border:1px solid var(--line-1); border-radius:6px;
  padding:48px 32px; text-align:center; color:var(--text-2); }
footer { margin-top:56px; padding-top:16px; border-top:1px solid var(--line-1);
  font-family:var(--mono); font-size:.68rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--text-3); display:flex;
  justify-content:space-between; flex-wrap:wrap; gap:8px; }
footer .amber { color:var(--accent); }
"""

_REVIEW_STATUSES = ("TR", "CR")


def _status_badge(status):
    """Status chip: dot + mono uppercase label (never color-only meaning)."""
    status = status or "WIP"
    upper = status.upper()
    if upper == "FINAL":
        cls = "chip final"
    elif upper == "WIP":
        cls = "chip"
    else:
        # TR / CR / custom review tags (REV02...) — the "in review" family.
        cls = "chip review"
    return '<span class="%s">%s</span>' % (cls, _esc(status))


def _flag_badges(flags):
    if not flags:
        return '<span class="muted">&ndash;</span>'
    out = []
    for f in flags:
        cls = "chip failf" if f == "regression" else "chip warnf"
        out.append('<span class="%s">%s</span>' % (cls, _esc(f.upper())))
    return " ".join(out)


def _score_cell(score):
    """Score as mono text + a small proportional bar (text carries the meaning)."""
    parsed = parse_score(score)
    if not parsed:
        return '<span class="muted">&ndash;</span>'
    passed, total = parsed
    pct = int(round(100.0 * passed / total)) if total else 0
    bar_cls = "bar" if passed == total else "bar partial"
    return ('%s<span class="%s"><i style="width:%d%%"></i></span>'
            % (_esc(score), bar_cls, pct))


def build_supervisor_html(shots, meta):
    """Render the aggregated table + trajectories as one self-contained HTML page.

    Pure function: inline CSS only, no <script>, no <link>, no external URLs.
    """
    stale_count = sum(1 for s in shots if "stale" in (s.get("flags") or []))
    regr_count = sum(1 for s in shots if "regression" in (s.get("flags") or []))
    todos_pending = sum(int(s.get("todos_pending") or 0) for s in shots)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Sentinel Supervisor</title>",
        "<style>%s</style>" % _HTML_STYLE,
        "</head><body>",
        # Manual theme toggle (shows the TARGET theme). Hidden without JS —
        # the page then simply follows prefers-color-scheme.
        '<button id="tt" class="themetoggle" hidden>[ LIGHT ]</button>',
        '<div class="wrap">',
        # Slate header: mono eyebrow + serif title + mono meta.
        '<div class="eyebrow"><span class="idx">S</span>'
        '<span class="tick"></span><span>SENTINEL &mdash; FOLDER QC</span></div>',
        "<h1>Supervisor report</h1>",
        '<div class="meta"><b>%s</b> &middot; generated %s</div>'
        % (_esc(meta.get("folder", "")), _esc(meta.get("generated", ""))),
    ]

    if not shots:
        parts.append(
            '<div class="empty">No scene sidecars found in this folder.<br>'
            "Save a version from the Deliver tab to create one.</div>"
        )
    else:
        # Readout strip: the supervisor's four numbers.
        parts.append('<div class="readouts">')
        for n, label in (
            (len(shots), "shots"),
            (stale_count, "stale"),
            (regr_count, "regressions"),
            (todos_pending, "todos pending"),
        ):
            parts.append(
                '<div class="readout"><div class="n">%s</div>'
                '<div class="l">%s</div></div>' % (_esc(n), _esc(label))
            )
        parts.append("</div>")

        parts.append('<div class="scroll"><table><thead><tr>')
        for col in (
            "Shot", "Last version", "Status", "Score", "TODOs", "Days idle", "Flags",
        ):
            parts.append("<th>%s</th>" % _esc(col))
        parts.append("</tr></thead><tbody>")
        for shot in shots:
            idle = ("<span class=\"muted\">&ndash;</span>"
                    if shot["days_idle"] is None else "%dd" % shot["days_idle"])
            todo = "%d <span class=\"sub\">/ %d</span>" % (
                shot["todos_pending"], shot["todos_total"])
            parts.append("<tr>")
            parts.append("<td>%s</td>" % _esc(shot["base"]))
            parts.append("<td>%s</td>" % _esc(shot["last_version"]))
            parts.append("<td>%s</td>" % _status_badge(shot["status"]))
            parts.append("<td>%s</td>" % _score_cell(shot["score"]))
            parts.append("<td>%s</td>" % todo)
            parts.append("<td>%s</td>" % idle)
            parts.append("<td>%s</td>" % _flag_badges(shot["flags"]))
            parts.append("</tr>")
        parts.append("</tbody></table></div>")

        # Trajectory cards.
        parts.append("<h2>QC trajectories</h2>")
        for shot in shots:
            parts.append('<div class="shot">')
            parts.append(
                "<h3>%s %s</h3>" % (_esc(shot["base"]), _flag_badges(shot["flags"]))
            )
            for row in shot["version_rows"]:
                label = row["qc_label"] or row["score"] or "(no QC)"
                parts.append(
                    '<div class="vrow"><span class="v">%s</span>'
                    '<span class="s">%s</span><span>%s</span></div>'
                    % (_esc(row["version"]), _esc(row["status"]), _esc(label))
                )
            hops_html = []
            for hop in shot["trajectory"]:
                arrow = ('<span class="arrow">%s &rarr; %s</span>'
                         % (_esc(hop["from_version"]), _esc(hop["to_version"])))
                if hop["no_data"]:
                    hops_html.append(
                        '<div class="hop nodata">%s &middot; no data</div>' % arrow)
                    continue
                if hop["broke"]:
                    hops_html.append(
                        '<div class="hop broke">%s &middot; broke: %s</div>'
                        % (arrow, _esc(", ".join(hop["broke"]))))
                if hop["recovered"]:
                    hops_html.append(
                        '<div class="hop recovered">%s &middot; recovered: %s</div>'
                        % (arrow, _esc(", ".join(hop["recovered"]))))
            if hops_html:
                parts.append('<div class="hops">%s</div>' % "".join(hops_html))
            parts.append("</div>")

    warnings = meta.get("warnings") or []
    if warnings:
        parts.append('<div class="warnbox"><strong>Skipped %d sidecar(s):</strong><br>'
                     % len(warnings))
        parts.append("<br>".join(_esc(w) for w in warnings))
        parts.append("</div>")

    parts.append(
        '<footer><span>SENTINEL &mdash; <span class="amber">ON WATCH.</span></span>'
        "<span>%s shot(s) &middot; filesystem is the database</span></footer>"
        % _esc(meta.get("shot_count", len(shots)))
    )
    parts.append("</div>")
    # Inline theme-toggle script (no src, no network — stays self-contained).
    parts.append(
        "<script>(function(){"
        "var b=document.getElementById('tt');if(!b)return;b.hidden=false;"
        "var mq=window.matchMedia('(prefers-color-scheme: light)');"
        "function eff(){var a=document.documentElement.getAttribute('data-theme');"
        "return a||(mq.matches?'light':'dark');}"
        "function paint(){b.textContent=eff()==='dark'?'[ LIGHT ]':'[ DARK ]';}"
        "b.addEventListener('click',function(){"
        "document.documentElement.setAttribute('data-theme',"
        "eff()==='dark'?'light':'dark');paint();});"
        "mq.addEventListener&&mq.addEventListener('change',paint);"
        "paint();})();</script>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def default_export_path(folder):
    return os.path.join(folder or "", DEFAULT_EXPORT_NAME)


def write_supervisor_html(shots, meta, out_path):
    """Write the HTML export atomically (tmp + rename). Returns the path."""
    if not out_path:
        raise ValueError("out_path is required")
    content = build_supervisor_html(shots, meta)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp_path, out_path)
    return out_path
