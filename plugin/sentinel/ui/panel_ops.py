# -*- coding: utf-8 -*-
"""Panel SPA ops (Fase 6.0 Task 1) — ``panel/state_stamp``, ``panel/overview``
and ``panel/open_form``. Sibling of ``ui/hub_ops.py``/``ui/web_ops.py`` (same
``MainThreadQueue`` dispatch-target contract — see
``webbridge.MainThreadQueue.drain`` for the invariant every handler below
must honor). Host-agnostic: no dialog imports at module scope; merged into
``reports_dialog._OPS`` by whichever task wires the route (Task 2).

Every field in ``panel/overview`` is copied from an existing call site, never
invented:

- QC (``passed``/``total``/``disabled``/``top``/``fixable``): the exact
  ``active_rules_for_doc`` -> ``run_all_checks`` -> ``compute_score`` call
  shape ``reports_dialog._op_report_qc``/``hub_ops._op_hub_preflight`` use,
  reshaped via the same ``webbridge.qc_report_payload`` those ops call
  (``top`` ranks its ``"checks"`` list via the new pure
  ``webbridge.top_qc_checks``); ``fixable`` reuses the *same*
  ``registry_results`` pass to build ``qc_counts`` for
  ``webbridge.palette_actions_payload``, exactly like
  ``web_ops._op_palette_actions`` — one QC run, not two.
- Scene (``shot_id``): ``doc.GetTakeData()`` (falling back to
  ``documents.GetTakeData(doc)``) -> ``GetMainTake().GetName()``, copied
  from ``ui/panel.py`` ``_sync_ui_from_doc`` (~line 1000-1008).
  ``version_label``/``version_age``: ``versioning.format_version_row(
  versioning.get_latest_version_info(doc))``, the same pair
  ``web_ops._op_form_save_version_state`` builds for its "Last version"
  pillbox replacement. ``polys_label``: ``ui.flows.get_scene_stats(doc)``,
  formatted with the same M/K-suffix rule ``ui/panel.py``
  ``_refresh`` uses for its "1.2M polys" caption (~line 1219-1226).
- Assets (``count``/``missing``/``disk_label``/``vram_label``):
  ``ui.flows.scan_scene_assets`` + ``assets.stat_sizes_batch`` +
  ``assets.compute_totals``, the same pipeline ``hub_ops._op_hub_inventory``
  runs; ``vram_label`` rolls up ``hub_ops._META_CACHE`` via
  ``hub_ops._totals_from_cache`` (same helper ``hub/meta_totals`` uses) over
  this scan's own resolved paths. The cache is empty until the Hub has been
  opened at least once this session — that "cold" state (``covered == 0``)
  reports ``vram_label: null`` instead of a misleading "0 B" (a scene can
  easily carry real VRAM the Hub simply hasn't parsed yet).
- Render (``preset_name``/``fps``/``resolution``): ``doc.GetActiveRenderData()``
  + ``checks.render.normalize_preset_name`` + ``doc.GetFps()`` +
  ``rd[c4d.RDATA_XRES]``/``rd[c4d.RDATA_YRES]``, the same reads
  ``ui/panel.py`` makes at ~line 1008-1010 and ~1082-1086.
  ``multiformat``: no existing engine helper answers "does this scene have
  any Sentinel Frame tag / multiformat Take" without walking the scene from
  scratch (grepped ``ui/frame_tag.py``/``multiformat.py`` — neither exposes
  one) — per the plan, this stays ``null`` rather than inventing new
  scene-walking logic.
- Deliver (``todos_pending``/``notes_present``): ``notes.get_notes_path`` +
  ``notes.load_notes``, the same pair
  ``web_ops._op_form_notes_state`` uses. ``last_delivery_age``: no existing
  helper surfaces a last-collected timestamp without scanning the delivery
  folder itself (manifest.py has no "last delivery" accessor) — left
  ``null`` for the same invent-nothing reason as ``multiformat``.

``panel/overview`` never triggers extra re-checks beyond this single QC run
plus the single asset scan above — no polling loop, no background timer;
the SPA is responsible for only calling this op when ``panel/state_stamp``
changes (see ``ui.hub_ops._stamp_for``, reused here unmodified).
"""
import os

import c4d
from c4d import documents

from sentinel import assets as assets_engine
from sentinel import webbridge
from sentinel.checks.render import normalize_preset_name
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.notes import get_notes_path, load_notes
from sentinel.qc.score import compute_score, count_violations, run_all_checks
from sentinel.rules_context import active_rules_for_doc
from sentinel.ui.hub_ops import _stamp_for, _totals_from_cache
from sentinel.versioning import format_version_row, get_latest_version_info


def _op_panel_state_stamp(payload):
    """``panel/state_stamp`` — the same cheap fingerprint the Hub polls
    with (``ui.hub_ops._stamp_for``), reused unmodified rather than growing
    a second, panel-specific notion of "did anything change"."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    return {"stamp": _stamp_for(doc)}


# Palette action ids the overview surfaces as "currently runnable quick
# fixes" — the same four ids web_ops._op_palette_actions/
# webbridge.PALETTE_ACTIONS know about (fix_lights/fix_cameras/
# fix_materials/fix_fps), and the check_id each one's violation count comes
# from (fps_range is spelled out separately below to mirror
# _op_palette_actions's own qc_counts loop exactly).
_PANEL_FIX_CHECK_ID = {
    "fix_lights": "lights",
    "fix_cameras": "cam",
    "fix_materials": "unused_mats",
    "fix_fps": "fps_range",
}


def _panel_qc_block(doc):
    """QC portion of ``panel/overview`` — one ``run_all_checks`` pass
    reused for both the score/top-checks payload (via
    ``webbridge.qc_report_payload``, same call shape as
    ``reports_dialog._op_report_qc``) and the fixable-action gating (via
    ``webbridge.palette_actions_payload``, same call shape as
    ``web_ops._op_palette_actions``)."""
    from sentinel.ui.flows import _baseline_path_for_doc, _current_module

    rules_context = active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    baseline_path = _baseline_path_for_doc(doc, only_existing=True)
    score_kwargs = {"baseline_path": baseline_path,
                     "current_params": rules_context.params} if baseline_path else {}
    score = compute_score(registry_results, rules_context, **score_kwargs)

    structured_by_check = {
        check_id: pair.get("structured_result")
        for check_id, pair in registry_results.items()
    }
    ruleset = {
        "name": (os.path.basename(rules_context.rules_path)
                 if rules_context.rules_path else "defaults"),
        "path": rules_context.rules_path,
        "shadowed": list(rules_context.shadowed_paths or []),
        "severity_overrides": (rules_context.params or {}).get("check_severity", {}),
    }
    scene_name = doc.GetDocumentName() or "Untitled"
    qc_report = webbridge.qc_report_payload(scene_name, ruleset, score, structured_by_check)

    qc_counts = {}
    for action_id, check_id in _PANEL_FIX_CHECK_ID.items():
        pair = registry_results.get(check_id) or {}
        qc_counts[check_id] = count_violations(check_id, pair.get("legacy_result"))

    doc_saved = bool(doc.GetDocumentPath())
    palette_actions = webbridge.palette_actions_payload(True, doc_saved, qc_counts)
    fixable = [a["id"] for a in palette_actions
               if a["id"] in _PANEL_FIX_CHECK_ID and a["enabled"]]

    return {
        "passed": qc_report["score"]["passed"],
        "total": qc_report["score"]["total"],
        "disabled": qc_report["score"]["disabled_count"],
        "top": webbridge.top_qc_checks(qc_report["checks"]),
        "fixable": fixable,
    }


def _panel_scene_block(doc):
    """Scene-identity portion of ``panel/overview`` — shot id, artist,
    last-version label/age, and a formatted poly count. See the module
    docstring for the exact source line each field is copied from."""
    from sentinel.ui.flows import get_scene_stats

    shot_id = ""
    try:
        td = doc.GetTakeData()
    except Exception:
        try:
            td = documents.GetTakeData(doc)
        except Exception:
            td = None
    if td:
        main_take = td.GetMainTake()
        if main_take:
            shot_id = main_take.GetName() or ""

    version_row = format_version_row(get_latest_version_info(doc))
    version_label = version_row["version_label"] if version_row else None
    version_age = version_row["time_label"] if version_row else None

    scene_stats = get_scene_stats(doc) or {}
    polys = scene_stats.get("polygons", 0)
    if polys >= 1_000_000:
        polys_label = f"{polys/1_000_000:.1f}M polys"
    elif polys >= 1_000:
        polys_label = f"{polys/1_000:.0f}K polys"
    else:
        polys_label = f"{polys} polys"

    return {
        "name": doc.GetDocumentName() or "",
        "path_set": bool(doc.GetDocumentPath()),
        "shot_id": shot_id,
        "artist": GlobalSettings.load_artist_name(),
        "version_label": version_label,
        "version_age": version_age,
        "polys_label": polys_label,
    }


def _vram_label_or_none(covered, vram_bytes):
    """``vram_label`` for the Assets card: ``None`` while the Hub's image
    metadata cache is cold (``covered == 0`` — no resolved path from this
    scan has a parsed cache entry yet, whether because the Hub was never
    opened this session or the scene has no thumbnailable images), else the
    formatted total over whatever the cache does cover. Cold cache renders
    as "no data" rather than the misleading "0 B" a genuinely-empty scan
    would also produce."""
    if covered == 0:
        return None
    return assets_engine.format_size(vram_bytes)


def _panel_assets_block(doc):
    """Assets-card portion of ``panel/overview`` — same scan + totals
    pipeline as ``hub_ops._op_hub_inventory``. ``vram_label`` rolls up
    ``hub_ops._META_CACHE`` (via ``hub_ops._totals_from_cache``, the same
    helper ``hub/meta_totals`` uses) over this scan's own resolved paths,
    rather than the Hub's ``_THUMB_PATHS`` memo — the panel can be opened
    without ever opening the Hub, so it has no reason to depend on that
    memo being populated. ``null`` (not "0 B") while the cache is cold."""
    from sentinel.ui.flows import scan_scene_assets

    records, _tex_records, _skipped = scan_scene_assets(doc)
    start = 0
    while start < len(records):
        start = assets_engine.stat_sizes_batch(records, start, 64)
    totals = assets_engine.compute_totals(records)
    resolved_paths = [r.get("resolved_path") for r in records]
    vram_totals = _totals_from_cache(resolved_paths)

    return {
        "count": totals["count"],
        "missing": totals["missing"],
        "disk_label": assets_engine.format_size(totals["total_bytes"]),
        "vram_label": _vram_label_or_none(vram_totals["covered"], vram_totals["vram_bytes"]),
    }


def _panel_render_block(doc):
    """Render-card portion of ``panel/overview`` — same reads
    ``ui/panel.py`` makes to sync its own render preset/resolution UI.
    ``multiformat`` is ``None`` — see module docstring."""
    rd = doc.GetActiveRenderData()
    preset_name = normalize_preset_name(rd.GetName() or "") if rd else None
    resolution = None
    if rd:
        try:
            resolution = "%dx%d" % (int(rd[c4d.RDATA_XRES]), int(rd[c4d.RDATA_YRES]))
        except Exception:
            resolution = None

    return {
        "preset_name": preset_name,
        "fps": doc.GetFps(),
        "resolution": resolution,
        "multiformat": None,
    }


def _panel_deliver_block(doc):
    """Deliver-card portion of ``panel/overview`` — same sidecar reads as
    ``web_ops._op_form_notes_state``. ``last_delivery_age`` is ``None`` —
    see module docstring."""
    notes_path = get_notes_path(doc)
    notes = load_notes(notes_path) if notes_path else {}
    todos = notes.get("todos") or []
    todos_pending = sum(1 for t in todos if not t.get("done"))
    notes_present = bool((notes.get("notes") or "").strip()) or bool(todos)

    return {
        "todos_pending": todos_pending,
        "notes_present": notes_present,
        "last_delivery_age": None,
    }


def _guarded_block(name, builder, doc):
    """Run one ``panel/overview`` card builder in isolation: a failure in
    ONE subsystem (e.g. a broken asset scan, an unreadable notes sidecar)
    must never blank the whole dashboard — same isolation pattern
    ``ui/panel.py`` ``_sync_ui_from_doc`` uses per-field (~line 985-1013,
    each block wrapped in its own ``try/except`` with a ``safe_print`` on
    failure, so one bad read doesn't take down the others). A failed block
    comes back as ``None`` — the SPA renders that card as unavailable
    instead of the whole response erroring out.
    """
    try:
        return builder(doc)
    except Exception as exc:
        safe_print(f"panel/overview: {name} block failed: {exc}")
        return None


def build_panel_overview(doc):
    """Pure(ish) aggregation of the 4-card ``panel/overview`` payload from
    an already-resolved ``doc`` — split out from ``_op_panel_overview`` so
    the per-block isolation is testable by handing in a fake/monkeypatched
    ``doc`` and builder, without needing the fake-c4d harness's real
    ``documents.GetActiveDocument()`` (which is always ``None`` there).
    Every block is wrapped by ``_guarded_block``: one raising builder never
    prevents the other four from populating their card.
    """
    return {
        "scene": _guarded_block("scene", _panel_scene_block, doc),
        "qc": _guarded_block("qc", _panel_qc_block, doc),
        "assets": _guarded_block("assets", _panel_assets_block, doc),
        "render": _guarded_block("render", _panel_render_block, doc),
        "deliver": _guarded_block("deliver", _panel_deliver_block, doc),
    }


def _op_panel_overview(payload):
    """``panel/overview`` — read-only "shot health" dashboard payload (4
    cards). Doc-guard-first like every sibling op; see the module docstring
    for the source of every field below. Each card is built via
    ``build_panel_overview``'s per-block isolation, so a failure in one
    subsystem degrades that card to ``null`` instead of blanking the whole
    response."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    return build_panel_overview(doc)


_VALID_FORM_PAGES = ("form/save_version", "form/notes", "form/settings")


def _validate_form_page(page):
    """Pure: ``panel/open_form`` ``page`` validation, split out so it's
    testable without a document (same convention as
    ``hub_ops._validate_shrink_payload``)."""
    if page not in _VALID_FORM_PAGES:
        return "invalid_page"
    return None


def _op_panel_open_form(payload):
    """``panel/open_form`` — open one of the three absorbed-later native
    windows (Save Version / Notes / Settings) from a panel card button,
    exactly like ``web_ops._palette_open_hub`` opens the Hub: local import
    of ``open_form`` (avoids a module-load cycle — ``reports_dialog``
    imports this module's ``PANEL_OPS``) wrapped in try/except so a server
    bind failure or missing web build never raises out of the dispatch
    table, it just reports ``{"ok": False, "error": str(exc)}``.

    Doc-guard-first like every sibling op; ``page`` is validated after the
    doc guard (matching that convention), via the pure ``_validate_form_page``
    above.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    page = payload.get("page")
    error = _validate_form_page(page)
    if error:
        return {"ok": False, "error": error}

    try:
        from sentinel.ui.reports_dialog import open_form
        open_form(doc, page)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


PANEL_OPS = {
    "panel/state_stamp": _op_panel_state_stamp,
    "panel/overview": _op_panel_overview,
    "panel/open_form": _op_panel_open_form,
}
