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
from sentinel.qc.registry import CHECK_REGISTRY
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


def _run_qc_scoring(doc):
    """One ``run_all_checks`` + ``compute_score`` + ``qc_report_payload``
    pass — the exact call shape shared by ``panel/overview``'s QC card
    (``_panel_qc_block``, top-3 + fixable) and ``panel/qc``'s full
    per-check list (``_op_panel_qc``), so either read op computes the
    score exactly once, never twice for the same request.

    Returns ``(rules_context, registry_results, qc_report)`` — callers pick
    whichever pieces they need (``_panel_qc_block`` also needs
    ``registry_results`` for its own ``qc_counts``/fixable pass;
    ``_op_panel_qc`` only needs ``qc_report``).
    """
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
    return rules_context, registry_results, qc_report


def _panel_qc_block(doc):
    """QC portion of ``panel/overview`` — reuses ``_run_qc_scoring``'s
    single check pass for both the score/top-checks payload and the
    fixable-action gating (via ``webbridge.palette_actions_payload``, same
    call shape as ``web_ops._op_palette_actions``)."""
    _rules_context, registry_results, qc_report = _run_qc_scoring(doc)

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


# Assets-card cache — see ``_assets_signature``/``_panel_assets_block``
# below. Module-level (not per-doc) because the panel only ever tracks the
# active document at a time, same singleton-cache convention as
# ``hub_ops._META_CACHE``/``_THUMB_PATHS``.
_ASSETS_BLOCK_CACHE = {"signature": None, "payload": None}


def _assets_signature(doc):
    """Cheap fingerprint for the Assets-card cache — deliberately NARROWER
    than ``hub_ops._stamp_for`` (which also reads ``doc.GetDirty(DATA|
    CHILDREN)``, bumped by every geometry/animation edit). Asset paths only
    ever change via materials/textures, so this signature only looks at
    material identity + material dirty state: ``(doc_path, material_count,
    sum_of_material_dirty)``. All three reads are in-memory container
    lookups, no filesystem — cheap enough to call on every
    ``panel/overview`` fetch. Returns ``None`` when ``doc`` doesn't support
    these reads, which the caller treats as an unconditional cache miss
    (never stored, never matched) rather than raising.
    """
    try:
        materials = doc.GetMaterials()
        mat_dirty = sum(m.GetDirty(c4d.DIRTYFLAGS_DATA) for m in materials)
        return (doc.GetDocumentPath() or "", len(materials), mat_dirty)
    except Exception:
        return None


def _panel_assets_block(doc):
    """Assets-card portion of ``panel/overview`` — same scan + totals
    pipeline as ``hub_ops._op_hub_inventory``. ``vram_label`` rolls up
    ``hub_ops._META_CACHE`` (via ``hub_ops._totals_from_cache``, the same
    helper ``hub/meta_totals`` uses) over this scan's own resolved paths,
    rather than the Hub's ``_THUMB_PATHS`` memo — the panel can be opened
    without ever opening the Hub, so it has no reason to depend on that
    memo being populated. ``null`` (not "0 B") while the cache is cold.

    Cached by ``_assets_signature`` (materials-only, see above): an
    always-docked panel re-fetches ``panel/overview`` on every
    ``panel/state_stamp`` change, and that stamp bumps on ANY scene edit
    (``doc.GetDirty(DATA|CHILDREN)``). Without this cache, plain
    modeling/animation work — which never touches a material — would
    re-run the full asset scan + a filesystem ``stat()`` sweep over every
    resolved path (often a Synology network share) on the C4D main thread
    on every single edit. Only a material add/remove or a material-data
    dirty bump (texture repath, shader edit, undo of either) invalidates
    the cache and triggers a real re-scan.
    """
    signature = _assets_signature(doc)
    if signature is not None and signature == _ASSETS_BLOCK_CACHE["signature"]:
        return _ASSETS_BLOCK_CACHE["payload"]

    from sentinel.ui.flows import scan_scene_assets

    records, _tex_records, _skipped = scan_scene_assets(doc)
    start = 0
    while start < len(records):
        start = assets_engine.stat_sizes_batch(records, start, 64)
    totals = assets_engine.compute_totals(records)
    resolved_paths = [r.get("resolved_path") for r in records]
    vram_totals = _totals_from_cache(resolved_paths)

    payload = {
        "count": totals["count"],
        "missing": totals["missing"],
        "disk_label": assets_engine.format_size(totals["total_bytes"]),
        "vram_label": _vram_label_or_none(vram_totals["covered"], vram_totals["vram_bytes"]),
    }

    if signature is not None:
        _ASSETS_BLOCK_CACHE["signature"] = signature
        _ASSETS_BLOCK_CACHE["payload"] = payload

    return payload


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


_CHECK_REGISTRY_BY_ID = {entry.check_id: entry for entry in CHECK_REGISTRY}


def _op_panel_qc(payload):
    """``panel/qc`` — the full per-check FAIL/WARN/OK/disabled breakdown
    for the panel's QC section (Fase 6.1 Task 1). Reuses
    ``_run_qc_scoring``'s single ``run_all_checks``/``compute_score`` pass
    — the SAME call ``panel/overview``'s QC card (``_panel_qc_block``)
    makes — reshaped via the new pure ``webbridge.group_qc_by_severity``.
    This op never triggers a second check pass; the SPA polls
    ``panel/state_stamp`` and only re-fetches on change. Read-only.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    _rules_context, _registry_results, qc_report = _run_qc_scoring(doc)
    grouped = webbridge.group_qc_by_severity(qc_report["checks"])
    return {
        "score": {
            "passed": qc_report["score"]["passed"],
            "total": qc_report["score"]["total"],
            "disabled": qc_report["score"]["disabled_count"],
        },
        "fail": grouped["fail"],
        "warn": grouped["warn"],
        "ok_count": grouped["ok_count"],
        "disabled_count": grouped["disabled_count"],
    }


def _validate_select_check_id(check_id):
    """Pure: ``panel/qc/select``'s check_id validation — a check_id must be
    a known registry entry that declares the ``"select"`` action. Split out
    so it's testable without a document (same convention as
    ``_validate_form_page``): the op itself is doc-guard-first, so this
    branch is unreachable through the op under the fake-c4d harness
    (``GetActiveDocument()`` is always ``None`` there).
    """
    entry = _CHECK_REGISTRY_BY_ID.get(check_id)
    if entry is None or "select" not in entry.actions:
        return "not_selectable"
    return None


# Per-check select cursor (Fase 6.1 live-caught fix #2) — REVERSES the
# earlier select-all deviation. The native ``ui/panel.py`` handlers
# (``_qc_select_unused_mats``/``_qc_select_names``, and by user request now
# every selectable check) cycle ONE flagged item per click via a GeDialog
# instance attribute (``self._unused_mats_idx``/``self._names_idx``) that
# remembers the cursor between clicks. This op is stateless HTTP — there is
# no per-request instance to carry that state — so the cursor lives here at
# module scope instead, keyed by ``check_id``. Same kind of module-level
# singleton exception as ``hub_ops._META_CACHE``/panel_ops's own
# ``_ASSETS_BLOCK_CACHE``: one active document at a time, one cursor per
# check_id is enough.
_QC_SELECT_CURSOR = {}


def _advance_cursor(prior_pos, prior_total, new_total):
    """Pure: the index to select THIS click, given the cursor stored from
    the previous click (``prior_pos``/``prior_total``) and the freshly
    computed flagged-count for this check right now (``new_total``).

    Mirrors the native ``if self._idx >= len(self._bad): self._idx = 0``
    guard (wrap when the stored position has run off the end), plus resets
    to 0 whenever the flagged set's SIZE has changed since the last click
    (an object was fixed/added/removed between clicks — the stored position
    no longer points at the same conceptual "next" item). ``new_total == 0``
    always yields ``0`` (nothing to select; caller checks ``new_total``
    before indexing).
    """
    if new_total <= 0:
        return 0
    if prior_total != new_total or prior_pos >= new_total:
        return 0
    return prior_pos


def _qc_flagged_items(check_id, legacy_result):
    """The list of concrete items (objects, or materials for
    ``unused_mats``) one check's ``legacy_result`` flags, in cycle order.
    ``cross_aspect``'s ``legacy_result`` is a list of violation dicts keyed
    by ``"object"`` — deduped here the same way the native
    ``_qc_select_cross_aspect`` handler dedupes (an object can violate more
    than one format). Every other selectable check's ``legacy_result`` is
    already the flagged-item list itself (materials for ``unused_mats``,
    objects otherwise).
    """
    if check_id == "cross_aspect":
        objs = []
        seen = set()
        for violation in legacy_result or []:
            obj = violation.get("object") if isinstance(violation, dict) else None
            if obj is None or id(obj) in seen:
                continue
            seen.add(id(obj))
            objs.append(obj)
        return objs
    return list(legacy_result or [])


def _select_single_qc_item(doc, check_id, item):
    """Select exactly ONE flagged item in the scene — the cycle-one-per-click
    counterpart to the old select-all. ``unused_mats`` cycles MATERIALS
    (deselect-all-materials then ``SetBit(BIT_ACTIVE)`` on the one, same
    primitive ``_qc_select_unused_mats`` uses); every other check cycles
    OBJECTS via the native ``ui/panel._select_objects`` helper (which itself
    deselects everything first), passed a single-item list.
    """
    if check_id == "unused_mats":
        for mat in doc.GetMaterials():
            mat.DelBit(c4d.BIT_ACTIVE)
        if item is not None:
            try:
                item.SetBit(c4d.BIT_ACTIVE)
            except Exception:
                pass
        c4d.EventAdd()
    else:
        from sentinel.ui.panel import _select_objects
        _select_objects(doc, [item] if item is not None else [])


def _op_panel_qc_select(payload):
    """``panel/qc/select`` — cycle to the NEXT flagged object/material one
    QC check currently flags, one item per click (mirrors the native
    per-instance idx cycle — see ``_QC_SELECT_CURSOR`` above for why the
    cursor lives at module scope instead of a GeDialog instance attribute).

    This REVERSES the earlier Fase 6.1 select-all deviation per user
    feedback: select-all was a deliberate but unwanted departure from the
    native cycle-one-per-click behavior; this restores parity (see
    ``docs/superpowers/specs/2026-07-22-panel-qc-design.md`` Desviación 1).

    Doc-guard first, then check_id validation (``_validate_select_check_id``)
    — an unknown/info-only check_id is rejected without running a scan.
    Runs its own fresh ``run_all_checks`` pass (mutation-adjacent scene op,
    not the cached ``panel/qc`` read) to get the current flagged list,
    advances the cursor (``_advance_cursor``), and selects only that one
    item via ``_select_single_qc_item``.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    check_id = payload.get("check_id")
    error = _validate_select_check_id(check_id)
    if error:
        return {"ok": False, "error": error}

    from sentinel.ui.flows import _current_module

    rules_context = active_rules_for_doc(doc)
    registry_results = run_all_checks(doc, _current_module(), rules_context)
    pair = registry_results.get(check_id) or {}
    flagged = _qc_flagged_items(check_id, pair.get("legacy_result"))
    total = len(flagged)

    prior = _QC_SELECT_CURSOR.get(check_id) or {}
    pos = _advance_cursor(prior.get("pos", 0), prior.get("total", -1), total)

    item = flagged[pos] if total else None
    _select_single_qc_item(doc, check_id, item)

    next_pos = (pos + 1) % total if total else 0
    _QC_SELECT_CURSOR[check_id] = {"pos": next_pos, "total": total}

    return {
        "ok": True,
        "stamp": _stamp_for(doc),
        "cursor_pos": (pos + 1) if total else 0,
        "total": total,
    }


def _validate_accept_payload(payload):
    """Pure: ``panel/qc/accept``'s ``{check_id, author, reason}``
    validation — runs BEFORE the doc guard (unlike every other mutating
    panel op; the interface calls for author/reason to be checked first),
    but is still split out and unit tested directly, same convention as
    ``_validate_form_page``.
    """
    payload = payload or {}
    if not payload.get("check_id"):
        return "check_id_required"
    if not (payload.get("author") or "").strip():
        return "author_required"
    if not (payload.get("reason") or "").strip():
        return "reason_required"
    return None


def _op_panel_qc_accept(payload):
    """``panel/qc/accept`` — accept every CURRENT violation of ONE check
    into the baseline (author + reason mandatory). COPIES the ``accept``
    branch of ``web_ops._op_form_gate_submit`` (``_gate_new_violations`` +
    ``baseline.entry_from_violation`` + ``baseline.add_acceptance``),
    restricted to a single ``check_id`` instead of a list — the panel's
    "Accept" button accepts one check's violations at a time, never a
    batch of checks. Invalidates ``check_cache`` on any real acceptance and
    echoes a fresh ``panel/qc`` payload so the SPA never needs a second
    round trip.

    Unsaved-document guard (live-caught fix, Fase 6.1): ``_baseline_path_for_doc``
    returns ``None`` for a document with no ``.c4d`` path — there is no sidecar
    to write the acceptance to. Before this guard the op returned ``{"ok":
    True}`` anyway, silently discarding the acceptance (the score never
    changed) — a misleading success. Same unsaved-doc guard convention as
    ``copy_into_project``/``collect`` in ``ui/flows.py``.
    """
    error = _validate_accept_payload(payload)
    if error:
        return {"ok": False, "error": error}

    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    if not doc.GetDocumentPath():
        return {"ok": False, "error": "unsaved_document"}

    from sentinel import baseline as baseline_engine
    from sentinel.common.cache import check_cache
    from sentinel.ui.flows import _compute_gate_snapshot, _doc_full_path, _gate_new_violations

    check_id = payload.get("check_id")
    author = payload.get("author").strip()
    reason = payload.get("reason").strip()

    rules_context = active_rules_for_doc(doc)
    doc_full_path = _doc_full_path(doc)
    snapshot = _compute_gate_snapshot(doc, rules_context, doc_full_path)
    gate_result = snapshot["gate_result"]

    path = snapshot["baseline_path"]
    accepted_any = False
    for violation in _gate_new_violations(gate_result, check_id):
        acceptance = baseline_engine.entry_from_violation(
            violation, author, reason,
            current_params=getattr(rules_context, "params", {}))
        if acceptance and baseline_engine.add_acceptance(path, acceptance):
            accepted_any = True

    if accepted_any:
        check_cache.clear()
        c4d.EventAdd()

    return {"ok": True, "stamp": _stamp_for(doc), "qc": _op_panel_qc({})}


def _op_panel_qc_fix_all(payload):
    """``panel/qc/fix_all`` — batch-fix every currently fixable check in
    ONE undo step. COPIES the ``fix_all`` branch of
    ``web_ops._op_form_gate_submit`` (``fixes.apply_fixes`` via
    ``_gate_fix_payload``) verbatim — same single-undo batch, all
    fixables, not restricted to one check. Invalidates ``check_cache`` and
    echoes a fresh ``panel/qc`` payload.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.common.cache import check_cache
    from sentinel.fixes import apply_fixes
    from sentinel.ui.flows import _compute_gate_snapshot, _doc_full_path, _gate_fix_payload

    rules_context = active_rules_for_doc(doc)
    doc_full_path = _doc_full_path(doc)
    snapshot = _compute_gate_snapshot(doc, rules_context, doc_full_path)
    gate_result = snapshot["gate_result"]

    fixable_ids = [item.get("check_id") for item in gate_result.get("fixable") or []]
    if fixable_ids:
        fixes = [
            _gate_fix_payload(check_id, snapshot["registry_results"], gate_result)
            for check_id in fixable_ids
        ]
        apply_fixes(doc, fixes)
        check_cache.clear()
        c4d.EventAdd()

    return {"ok": True, "stamp": _stamp_for(doc), "qc": _op_panel_qc({})}


PANEL_OPS = {
    "panel/state_stamp": _op_panel_state_stamp,
    "panel/overview": _op_panel_overview,
    "panel/open_form": _op_panel_open_form,
    "panel/qc": _op_panel_qc,
    "panel/qc/select": _op_panel_qc_select,
    "panel/qc/accept": _op_panel_qc_accept,
    "panel/qc/fix_all": _op_panel_qc_fix_all,
}
