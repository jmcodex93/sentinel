# -*- coding: utf-8 -*-
"""Client-readable QC report — a self-contained HTML page (I7).

Pure module (stdlib only, NO top-level ``import c4d``) so pytest can cover it
without Cinema 4D. Consumes the SAME report dict that
``sentinel.ui.reports.build_qc_report`` produces, plus an optional version
timeline (history entries) and an optional embedded snapshot (base64 PNG).

Reuses the Sentinel "SAFE AREA" design system (the ``_LIGHT_TOKENS`` /
``_DARK_TOKENS`` / theme-toggle pattern from ``supervisor.py``) copied inline —
single file, inline CSS, no ``<script src``, no ``<link``, no external URLs.
Audience = a producer/client: lead with the big verdict (score + status badge),
plain-language check rows, notes/TODOs, version timeline.
"""

import html

# ── SAFE AREA design tokens (copied from supervisor.py; kept in sync by hand).
# Dark instrument theme by default, warm-paper light variant. prefers-color-scheme
# is the default signal; a manual [data-theme] attribute (set by the tiny inline
# toggle) wins in BOTH directions. Semantic colors only ever pair with a label.
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
.verdict { display:flex; align-items:center; flex-wrap:wrap; gap:16px;
  margin:24px 0 8px; padding:20px 22px; background:var(--bg-1);
  border:1px solid var(--line-1); border-radius:8px; }
.verdict .big { font-family:var(--mono); font-variant-numeric:tabular-nums;
  font-size:clamp(2rem,5vw,3rem); line-height:1; color:var(--text-1); }
.verdict .big.partial { color:var(--warn); }
.verdict .big.clean { color:var(--pass); }
.verdict .vlabel { font-family:var(--mono); font-size:.66rem;
  text-transform:uppercase; letter-spacing:.14em; color:var(--text-3);
  margin-top:8px; }
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
th,td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--line-1); }
th { font-family:var(--mono); font-weight:500; font-size:.66rem;
  text-transform:uppercase; letter-spacing:.14em; color:var(--text-3);
  background:var(--bg-2); white-space:nowrap; }
tr:last-child td { border-bottom:none; }
td { font-family:var(--mono); color:var(--text-1); }
td.check { font-family:var(--sans); }
td .sub { color:var(--text-3); }
.chip { display:inline-flex; align-items:center; gap:6px; padding:2px 8px;
  border-radius:2px; font-family:var(--mono); font-size:.68rem; font-weight:500;
  text-transform:uppercase; letter-spacing:.08em; border:1px solid var(--line-2);
  color:var(--text-2); white-space:nowrap; }
.chip::before { content:""; width:7px; height:7px; border-radius:50%;
  background:var(--text-3); }
.chip.review { color:var(--accent); border-color:var(--accent);
  background:var(--accent-dim); }
.chip.review::before { background:var(--accent); }
.chip.final { color:var(--pass); border-color:var(--pass);
  background:var(--pass-dim); }
.chip.final::before { background:var(--pass); }
.chip.failf { color:var(--fail); border-color:var(--fail);
  background:var(--fail-dim); }
.chip.failf::before { background:var(--fail); }
.snap { margin:8px 0 4px; border:1px solid var(--line-1); border-radius:8px;
  overflow:hidden; background:var(--bg-2); }
.snap img { display:block; width:100%; height:auto; }
.notes { background:var(--bg-1); border:1px solid var(--line-1); border-radius:6px;
  padding:18px 22px; }
.notes p { margin:0 0 10px; color:var(--text-2); white-space:pre-wrap; }
.todo { font-family:var(--mono); font-size:.82rem; padding:4px 0;
  display:flex; gap:10px; align-items:baseline; }
.todo .box { color:var(--text-3); }
.todo.done { color:var(--text-3); text-decoration:line-through; }
.todo.pending .box { color:var(--warn); }
.muted { color:var(--text-3); }
footer { margin-top:56px; padding-top:16px; border-top:1px solid var(--line-1);
  font-family:var(--mono); font-size:.68rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--text-3); display:flex;
  justify-content:space-between; flex-wrap:wrap; gap:8px; }
footer .amber { color:var(--accent); }
"""

_THEME_SCRIPT = (
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


def _esc(value):
    return html.escape(str(value if value is not None else ""))


def _status_badge(status):
    """Status chip: dot + mono uppercase label (never color-only meaning)."""
    status = (status or "WIP")
    upper = str(status).upper()
    if upper == "FINAL":
        cls = "chip final"
    elif upper == "WIP":
        cls = "chip"
    else:
        cls = "chip review"  # TR / CR / custom review tags
    return '<span class="%s">%s</span>' % (cls, _esc(status))


def _check_badge(status):
    """Chip for a single QC check's PASS / FAIL / DISABLED state."""
    upper = str(status or "").upper()
    if upper == "PASS":
        return '<span class="chip final">PASS</span>'
    if upper == "DISABLED":
        return '<span class="chip">OFF</span>'
    return '<span class="chip failf">FAIL</span>'


def _latest_version(versions):
    if versions and isinstance(versions, list):
        first = versions[0]
        if isinstance(first, dict):
            return first
    return {}


def _version_label(entry):
    try:
        return "v%03d" % int(entry.get("version"))
    except (TypeError, ValueError):
        filename = entry.get("filename") or ""
        import os
        return os.path.splitext(filename)[0] or "?"


def build_client_report_html(report_dict, snapshot_b64=None, versions=None):
    """Render the QC report dict as one self-contained client-facing HTML page.

    Pure function: inline CSS only, no <script src>, no <link>, no external URLs.

    Args:
        report_dict: the dict from sentinel.ui.reports.build_qc_report.
        snapshot_b64: optional base64 PNG string; embedded as a data: URI.
        versions: optional list of history entries (newest first) for the
                  version timeline.
    """
    report_dict = report_dict or {}
    checks = report_dict.get("checks", {}) or {}
    summary = report_dict.get("summary", {}) or {}
    notes = report_dict.get("notes", {}) or {}
    versions = versions or []

    scene = report_dict.get("scene", "") or "untitled"
    artist = report_dict.get("artist", "") or ""
    timestamp = report_dict.get("timestamp", "") or ""
    shot_id = report_dict.get("shot_id", "") or ""

    latest = _latest_version(versions)
    status = (latest.get("status") or "").upper() or "WIP"

    score = summary.get("score", "") or ""
    passed = summary.get("passed", sum(1 for c in checks.values() if c.get("status") == "PASS"))
    total = summary.get("total_checks", len(checks))
    pending_todos = notes.get("pending_count", 0) or 0

    # Verdict class: clean = all passed, partial otherwise.
    verdict_cls = "big clean" if (total and passed == total) else "big partial"
    if not score:
        score = "%s/%s" % (passed, total)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Sentinel QC Report &mdash; %s</title>" % _esc(scene),
        "<style>%s</style>" % _HTML_STYLE,
        "</head><body>",
        '<button id="tt" class="themetoggle" hidden>[ LIGHT ]</button>',
        '<div class="wrap">',
        '<div class="eyebrow"><span class="idx">S</span>'
        '<span class="tick"></span><span>SENTINEL &mdash; QC REPORT</span></div>',
        "<h1>%s</h1>" % _esc(scene),
    ]

    meta_bits = []
    if latest:
        meta_bits.append("<b>%s</b>" % _esc(_version_label(latest)))
    if shot_id:
        meta_bits.append("shot %s" % _esc(shot_id))
    if artist:
        meta_bits.append("artist %s" % _esc(artist))
    if timestamp:
        meta_bits.append("generated %s" % _esc(timestamp))
    if meta_bits:
        parts.append('<div class="meta">%s</div>' % " &middot; ".join(meta_bits))

    # Big verdict: score + status badge.
    parts.append('<div class="verdict">')
    parts.append('<div><div class="%s">%s</div>'
                 '<div class="vlabel">checks passed</div></div>' % (verdict_cls, _esc(score)))
    parts.append('<div>%s</div>' % _status_badge(status))
    parts.append("</div>")

    # Embedded snapshot (review still) when available.
    if snapshot_b64:
        parts.append(
            '<div class="snap"><img alt="Review snapshot" '
            'src="data:image/png;base64,%s"></div>' % snapshot_b64
        )

    # Readout strip.
    parts.append('<div class="readouts">')
    for n, label in (
        (score, "score"),
        (passed, "checks passed"),
        (pending_todos, "todos pending"),
        (len(versions), "versions"),
    ):
        parts.append(
            '<div class="readout"><div class="n">%s</div>'
            '<div class="l">%s</div></div>' % (_esc(n), _esc(label))
        )
    parts.append("</div>")

    # Check rows — plain-language label + PASS/FAIL chip, identical set to panel.
    parts.append("<h2>Quality checks</h2>")
    parts.append('<div class="scroll"><table><thead><tr>')
    for col in ("Check", "Result", "Issues"):
        parts.append("<th>%s</th>" % _esc(col))
    parts.append("</tr></thead><tbody>")
    for key, check in checks.items():
        if not isinstance(check, dict):
            continue
        label = check.get("label") or key
        status_c = check.get("status", "")
        count = check.get("count", 0) or 0
        if str(status_c).upper() == "DISABLED":
            issues = '<span class="muted">&ndash;</span>'
        elif count:
            issues = "%d" % count
        else:
            issues = '<span class="muted">clean</span>'
        parts.append("<tr>")
        parts.append('<td class="check">%s</td>' % _esc(label))
        parts.append("<td>%s</td>" % _check_badge(status_c))
        parts.append("<td>%s</td>" % issues)
        parts.append("</tr>")
    parts.append("</tbody></table></div>")

    # Notes + TODOs.
    notes_text = notes.get("text", "") or ""
    todos = notes.get("todos", []) or []
    if notes_text or todos:
        parts.append("<h2>Scene notes</h2>")
        parts.append('<div class="notes">')
        if notes_text:
            parts.append("<p>%s</p>" % _esc(notes_text))
        for todo in todos:
            if not isinstance(todo, dict):
                continue
            done = bool(todo.get("done"))
            cls = "todo done" if done else "todo pending"
            box = "[x]" if done else "[ ]"
            parts.append('<div class="%s"><span class="box">%s</span>'
                         '<span>%s</span></div>' % (cls, box, _esc(todo.get("text", ""))))
        parts.append("</div>")

    # Version timeline.
    if versions:
        parts.append("<h2>Version timeline</h2>")
        parts.append('<div class="scroll"><table><thead><tr>')
        for col in ("Version", "Status", "QC", "Date", "Comment"):
            parts.append("<th>%s</th>" % _esc(col))
        parts.append("</tr></thead><tbody>")
        for entry in versions:
            if not isinstance(entry, dict):
                continue
            v_status = (entry.get("status") or "").upper() or "WIP"
            parts.append("<tr>")
            parts.append("<td>%s</td>" % _esc(_version_label(entry)))
            parts.append("<td>%s</td>" % _status_badge(v_status))
            parts.append("<td>%s</td>" % _esc(entry.get("qc_score", "") or "&ndash;"))
            parts.append("<td>%s</td>" % _esc(entry.get("timestamp", "") or ""))
            parts.append('<td class="check">%s</td>' % _esc(entry.get("comment", "") or ""))
            parts.append("</tr>")
        parts.append("</tbody></table></div>")

    parts.append(
        '<footer><span>SENTINEL &mdash; <span class="amber">ON WATCH.</span></span>'
        "<span>%s</span></footer>" % _esc(report_dict.get("version", ""))
    )
    parts.append("</div>")
    parts.append(_THEME_SCRIPT)
    parts.append("</body></html>")
    return "".join(parts)


def write_client_report_html(report_dict, out_path, snapshot_b64=None, versions=None):
    """Write the client report HTML atomically (tmp + rename). Returns the path."""
    import os

    if not out_path:
        raise ValueError("out_path is required")
    content = build_client_report_html(report_dict, snapshot_b64=snapshot_b64, versions=versions)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, out_path)
    return out_path
