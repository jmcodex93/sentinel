# -*- coding: utf-8 -*-
"""Panel SPA Render-section ops — ``panel/render`` (per-block isolated read)
plus the mutation/action ops. Task 1: preset/frame mutations (``set_preset``,
``reset_all``, ``add_frame_tag``, ``select_frame_tag``).
Task 2: AOVs + snapshots (``aov_tier``, ``set_multipart``, ``aov_list``,
``toggle_watchfolder``, ``save_still``, ``open_folder``). Sibling of
``ui/panel_ops.py`` (same ``MainThreadQueue`` dispatch-target contract, same
doc-guard-first / per-block-isolation conventions — see that module's
docstring and ``_guarded_block`` for the invariant every handler below must
honor). Host-agnostic: no dialog imports at module scope; merged into
``reports_dialog._OPS`` alongside ``PANEL_OPS``/``HUB_OPS``.

Every field in ``panel/render`` is copied from an existing call site, never
invented:

- ``preset``: ``doc.GetActiveRenderData()`` name (as it reads in the Render
  Manager — normalization is a comparison key, not UI text) + XRES/YRES +
  ``doc.GetFps()`` — the same reads ``panel_ops._panel_render_block``
  makes (extended here with ``presets``, gathered by iterating
  ``doc.GetFirstRenderData()``/``GetNext()``, the same walk
  ``ui/panel.py`` ``_apply_preset``/``scene_tools._force_render_settings``
  already do).
- ``frame``: whether the scene has a Sentinel Frame tag anywhere and, if
  so, its host camera's name — ``_find_sentinel_frame_tag`` walks the
  object hierarchy checking ``tag.GetType() ==
  frame_tag.SENTINEL_FRAME_TAG_PLUGIN_ID``, the same check
  ``scene_tools._add_sentinel_frame_tag``/``safe_areas.py``
  ``_frame_tag_nudge_for_format`` make per-camera, generalized to the
  whole scene (no existing helper answers "does ANY camera have the tag").
- ``aovs``: ``aovs.check_rs_aovs(doc, AOV_TIER_PRODUCTION)`` for
  count/availability, ``aovs.get_aov_multipart(doc)``, and
  target/light-groups from the same reads ``ui/panel.py``'s
  ``BTN_INFO_AOVS`` handler makes (~line 2156-2196):
  ``GlobalSettings.get('comp_target', 0)`` + ``aovs._is_lg_active_on_beauty``
  + ``aovs._scan_light_groups``.
- ``snapshots``: ``ui.flows.get_effective_snapshot_dir()`` (returns
  ``(path, origin)``) + ``GlobalSettings.get_snapshot_watch()``.
- ``postrender``: the last saved ``<base>_sentinel_render_report.json`` —
  same ``postrender.report_path_for_doc`` lookup
  ``reports_dialog._op_report_render_validation`` uses, reduced here to
  just ``available``/``generated_at``/``passed`` (the panel's Post-Render
  block is a one-line status + a "Validate" deep-link, not the full report
  breakdown that page already renders).

``panel/render`` never triggers extra scene scans beyond these cheap reads
— no AOV list is expanded, no keyframe sweep runs; the SPA is responsible
for only calling this op when ``panel/state_stamp`` changes (see
``ui.hub_ops._stamp_for``, reused here unmodified via ``panel_ops``).
"""
import json
import os

import c4d
from c4d import documents

from sentinel import postrender
from sentinel.aovs import (
    AOV_TIER_ESSENTIALS,
    AOV_TIER_PRODUCTION,
    REDSHIFT_AVAILABLE,
    _build_aov_type_name_map,
    _is_lg_active_on_beauty,
    _scan_light_groups,
    aov_type_name,
    check_rs_aovs,
    force_aov_tier,
    get_aov_multipart,
    set_scene_multipart,
)
from sentinel.checks.render import normalize_preset_name
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.ui.frame_tag import _enabled_format_ids_from_params
from sentinel.ui.panel_ops import _guarded_block, _panel_render_block, _stamp_for


def _approved_normalized_presets(doc):
    """The normalized names QC #5 considers standard — the ruleset's
    ``approved_presets`` through ``normalize_preset_name``. One helper, one
    criterion: the dropdown's "not in the standard set" marker and the Reset
    All confirm must never disagree about what standard means."""
    from sentinel.common.constants import PRESETS
    from sentinel.rules_context import active_rules_for_doc

    context = active_rules_for_doc(doc)
    return {
        normalize_preset_name(name)
        for name in context.params.get("approved_presets", PRESETS)
    }


def _panel_preset_block(doc):
    """Preset-card portion of ``panel/render`` — REUSES
    ``panel_ops._panel_render_block`` for the ``preset_name``/``resolution``/
    ``fps`` reads (rather than a second drifting copy of the same
    ``GetActiveRenderData``/``RDATA_XRES``/``RDATA_YRES`` reads), and adds
    ``presets``: one entry per render data in this scene's chain, in scene
    order, for the SPA's preset ``<select>``.

    Each entry is ``{"index": <position in the chain>, "name": <REAL scene
    name>, "standard": <bool>}``:

    - ``name`` is what the Render Manager shows. It used to be the
      *normalized* form, which is a comparison key, not UI text — the artist
      saw ``rs_lookdev_2026`` for a preset called ``RS-LookDev 2026``.
    - ``index`` is the identity the SPA sends back, so two presets whose
      names normalize to the same key (``Pre-Render`` / ``pre_render``, which
      QC #5 already reports as a duplicate) are two selectable entries that
      each activate THEMSELVES. Under name-only matching the second entry
      silently activated the first.
    - ``standard`` is QC #5's criterion (``_approved_normalized_presets``),
      never a second derivation and never the four template names by hand.
    """
    base = _panel_render_block(doc)

    try:
        approved = _approved_normalized_presets(doc)
    except Exception as exc:  # pragma: no cover - defensive
        # A ruleset read failure must not blank the dropdown; degrade to
        # "everything unmarked" rather than "everything flagged non-standard"
        # (a marker that is wrong in the alarming direction is worse than an
        # absent one), and say so instead of failing silently.
        safe_print(f"preset block could not resolve approved presets: {exc}")
        approved = None

    presets = []
    active_index = None
    active_rd = doc.GetActiveRenderData()
    walk = doc.GetFirstRenderData()
    index = 0
    while walk:
        raw = walk.GetName() or ""
        presets.append({
            "index": index,
            "name": raw,
            "standard": True if approved is None
                        else normalize_preset_name(raw) in approved,
        })
        if active_rd is not None and walk == active_rd:
            active_index = index
        walk = walk.GetNext()
        index += 1

    return {
        "preset_name": base.get("preset_name"),
        "preset_index": active_index,
        "presets": presets,
        "fps": base.get("fps"),
        "resolution": base.get("resolution"),
    }


def _find_sentinel_frame_tag(doc):
    """Walk the object hierarchy looking for a Sentinel Frame tag anywhere
    in the scene. Returns ``(tag, host_object)`` for the first one found (a
    scene is expected to carry at most a handful), or ``None`` if there is
    none. Pure hierarchy walk — no per-camera math, cheap enough to run on
    every ``panel/render`` fetch (same cost class as a tag-type check, not
    a keyframe sweep).
    """
    from sentinel.ui.frame_tag import SENTINEL_FRAME_TAG_PLUGIN_ID

    def _walk(op):
        while op is not None:
            for tag in op.GetTags():
                if tag.GetType() == SENTINEL_FRAME_TAG_PLUGIN_ID:
                    return tag, op
            found = _walk(op.GetDown())
            if found is not None:
                return found
            op = op.GetNext()
        return None

    return _walk(doc.GetFirstObject())


def _panel_frame_block(doc):
    """Frame-card portion of ``panel/render`` — whether a Sentinel Frame
    tag exists anywhere in the scene and, if so, its host camera's name and
    the count of enabled delivery formats."""
    found = _find_sentinel_frame_tag(doc)
    if found is None:
        return {"has_tag": False, "camera_name": None, "format_count": None,
                "slice_count": None}
    tag, host = found
    format_count = None
    try:
        format_count = len(_enabled_format_ids_from_params(tag))
    except Exception:
        pass
    slice_count = None
    try:
        from sentinel.ui.frame_tag import _total_slice_count
        slice_count = int(_total_slice_count(tag))
    except Exception:
        pass
    return {"has_tag": True, "camera_name": host.GetName() or "",
            "format_count": format_count, "slice_count": slice_count}


def _panel_aovs_block(doc):
    """AOVs-card portion of ``panel/render`` — same reads ``ui/panel.py``'s
    ``BTN_INFO_AOVS`` handler makes. ``{"error": "redshift_unavailable"}``
    when the Redshift Python module itself isn't importable (never a
    crash — the module-load ``REDSHIFT_AVAILABLE`` flag, same one
    ``aovs.check_rs_aovs`` already reports in its own ``"available"`` key)."""
    if not REDSHIFT_AVAILABLE:
        return {"error": "redshift_unavailable"}

    result = check_rs_aovs(doc, AOV_TIER_PRODUCTION)
    aov_list = result.get("aovs") or []
    count = sum(1 for aov in aov_list if aov.get("enabled"))
    target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
    groups, _stale = _scan_light_groups(doc)

    return {
        "count": count,
        "multipart": get_aov_multipart(doc),
        "target": target_name,
        "light_groups": bool(_is_lg_active_on_beauty(doc)),
        "light_group_names": sorted(groups.keys()) if groups else [],
    }


def _panel_snapshots_block(doc):
    """Snapshots-card portion of ``panel/render`` — same effective-dir
    resolution the panel caption uses (``ui.flows.get_effective_snapshot_dir``,
    Phase 3 IA consolidation) + the watch-folder toggle state."""
    from sentinel.ui.flows import get_effective_snapshot_dir

    snap_dir, origin = get_effective_snapshot_dir()
    return {
        "dir": snap_dir,
        "origin": origin,
        "watch_enabled": GlobalSettings.get_snapshot_watch(),
    }


def _panel_postrender_block(doc):
    """Post-Render-card portion of ``panel/render`` — same deterministic
    report path ``reports_dialog._op_report_render_validation`` locates
    (``postrender.report_path_for_doc``, version/status-stripped from the
    saved document path). ``{"available": False}`` for an unsaved document
    or one that has never run "Validate Render Output..." — same
    ``no_report`` condition that op treats as an empty state, reduced here
    to a boolean since the panel only shows a one-line status + deep-link."""
    doc_path = doc.GetDocumentPath()
    doc_name = doc.GetDocumentName()
    if not doc_path or not doc_name:
        return {"available": False}

    doc_full_path = os.path.join(doc_path, doc_name)
    report_path = postrender.report_path_for_doc(doc_full_path, "")
    if not report_path or not os.path.isfile(report_path):
        return {"available": False}

    try:
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except Exception:
        return {"available": False}

    return {
        "available": True,
        "generated_at": report.get("generated_at") or "",
        "passed": bool(report.get("passed", False)),
    }


def build_panel_render(doc):
    """Pure(ish) aggregation of the 5-card ``panel/render`` payload from an
    already-resolved ``doc`` — split out from ``_op_panel_render`` so the
    per-block isolation is testable with a fake ``doc``, same convention as
    ``panel_ops.build_panel_overview``. Every block is wrapped by
    ``panel_ops._guarded_block``: one raising builder never prevents the
    other four from populating their card.
    """
    return {
        "preset": _guarded_block("preset", _panel_preset_block, doc),
        "frame": _guarded_block("frame", _panel_frame_block, doc),
        "aovs": _guarded_block("aovs", _panel_aovs_block, doc),
        "snapshots": _guarded_block("snapshots", _panel_snapshots_block, doc),
        "postrender": _guarded_block("postrender", _panel_postrender_block, doc),
    }


def _op_panel_render(payload):
    """``panel/render`` — read-only Render-section payload (5 cards),
    doc-guard-first like every sibling op. See the module docstring for the
    source of every field."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}
    return build_panel_render(doc)


def _needs_confirm(payload):
    """Pure: the ``requires_confirm``/``confirm: true`` contract gate —
    mirrors ``web_ops._op_palette_run``'s check (``entry.get("requires_confirm")
    and payload.get("confirm") is not True``), specialized here since every
    caller of this helper IS a destructive op (no per-action registry
    lookup needed). ``True`` means the mutation must NOT run yet."""
    return (payload or {}).get("confirm") is not True


def _op_panel_render_set_preset(payload):
    """``panel/render/set_preset`` — apply the named render preset via
    ``scene_tools._apply_preset_core`` (the dialog-free core extracted from
    ``ui/panel.py`` ``_apply_preset`` for this task). Reversible, low-impact
    (just switches which render data is active) — no confirm gate, matching
    the native dropdown's own lack of a confirmation step.

    ``preset`` is the REAL scene name the dropdown displayed; the optional
    ``index`` is the position that entry occupied in the render data chain,
    which is what disambiguates two presets whose names normalize alike (see
    ``_apply_preset_core``). It is passed through unvalidated on purpose: an
    index that matches nothing simply falls through to the name scan, so a
    malformed one can never turn a working preset switch into an error."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.ui import scene_tools

    preset = (payload or {}).get("preset")
    if not preset:
        return {"ok": False, "error": "preset_required"}

    rd = scene_tools._apply_preset_core(doc, preset,
                                        index=(payload or {}).get("index"))
    if rd is None:
        return {"ok": False, "error": "preset_not_found"}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


_RESET_ALL_CONFIRM_LABEL = ("Reset ALL render presets from template? "
                             "This replaces existing presets with standard settings.")
#: How many preset names the confirm text spells out before it switches to
#: "…and N more" — a scene with a long tail of custom presets must still
#: fit a panel-width confirm bar.
_RESET_ALL_NAME_CAP = 5


def non_standard_preset_names(doc):
    """The scene's render presets that are NOT in the approved set — the
    ones "Reset All" is about to delete, in scene order, with their real
    names (the artist recognizes ``CLIENTE_9x16_final``, not its normalized
    form).

    The "standard" criterion is QC #5's, not a second one: the ruleset's
    ``approved_presets`` compared through ``normalize_preset_name`` (see
    ``checks/render.py`` ``check_render_conflicts``). Nothing here re-derives
    the list or hardcodes the four template names — it shares
    ``_approved_normalized_presets`` with the dropdown's own marker.
    """
    allowed = _approved_normalized_presets(doc)

    doomed = []
    rd = doc.GetFirstRenderData()
    while rd:
        raw = rd.GetName() or ""
        if normalize_preset_name(raw) not in allowed:
            doomed.append(raw)
        rd = rd.GetNext()
    return doomed


def reset_all_confirm_label(names):
    """Confirm copy for ``panel/render/reset_all``, built from the presets
    that are actually about to be lost (``names``, gathered from the scene
    at confirm time — never a fixed list).

    With nothing to lose this is an innocuous reset and must not read like
    an alarm; with something to lose it names it. English, like the rest of
    the panel surface (the native dialog keeps its own copy).
    """
    if not names:
        return ("Reset ALL render presets from template? "
                "No custom presets in this scene — the standard set is "
                "re-created from the template.")

    shown = names[:_RESET_ALL_NAME_CAP]
    listed = ", ".join(shown)
    hidden = len(names) - len(shown)
    if hidden > 0:
        listed = "%s and %d more" % (listed, hidden)
    if len(names) == 1:
        subject = "1 preset that is not"
    else:
        subject = "%d presets that are not" % len(names)
    return ("Reset ALL render presets from template? "
            "This deletes %s in the standard set: %s. "
            "Cmd+Z restores them." % (subject, listed))


def reset_all_confirm_verb(names):
    """What the confirm BUTTON says for ``panel/render/reset_all`` — the
    action, not "yes". Built from the same scene read as the label
    (``names`` = the presets about to be lost) so the two can never
    disagree: with something to lose the verb names the deletion, without
    it the button only promises the re-create that actually happens."""
    if not names:
        return "Re-create presets"
    return "Delete and re-create"


def _reset_all_confirm_for(doc):
    """The whole confirm half of ``panel/render/reset_all``'s gate —
    ``confirm_label`` (the question), ``confirm_verb`` (the button) and
    ``destructive`` (which licenses the red, non-primary button) — from ONE
    scene read, so the three can't drift apart.

    ``destructive`` is ``bool(names)``: a reset with no custom presets in
    the scene destroys nothing, and painting it red would spend the color
    on a no-loss action (DESIGN.md reserves the fail hue for real state).

    Degrades to the generic constant if the scene read fails for any
    reason — a confirm prompt must never be the thing that breaks the op —
    and in that degraded state assumes the WORST (destructive), because an
    unreadable scene is not evidence that nothing is at stake. It logs
    rather than failing silently."""
    try:
        names = non_standard_preset_names(doc)
    except Exception as exc:  # pragma: no cover - defensive
        safe_print(f"reset_all confirm label fell back to generic: {exc}")
        return {"confirm_label": _RESET_ALL_CONFIRM_LABEL,
                "confirm_verb": "Delete and re-create",
                "destructive": True}
    return {"confirm_label": reset_all_confirm_label(names),
            "confirm_verb": reset_all_confirm_verb(names),
            "destructive": bool(names)}


def _op_panel_render_reset_all(payload):
    """``panel/render/reset_all`` — destructive (replaces every render
    preset in the scene from the bundled template), confirm-gated per the
    contract (``{"ok": False, "error": "confirm_required", "confirm_label":
    ...}`` without ``confirm: true``). Runs
    ``scene_tools._force_render_settings_core`` — the dialog-free core
    extracted from ``_force_render_settings`` — instead of the native
    ``QuestionDialog``/summary ``MessageDialog`` path.

    The confirm copy is built from the SCENE at confirm time
    (``_reset_all_confirm_for``): it names the presets that are about to be
    deleted instead of a fixed sentence the artist confirms blind, the
    button says the same thing (``confirm_verb``) instead of a mute
    "Confirm", and ``destructive`` tells the SPA whether this particular
    reset is actually losing anything."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    if _needs_confirm(payload):
        response = {"ok": False, "error": "confirm_required"}
        response.update(_reset_all_confirm_for(doc))
        return response

    from sentinel.ui import scene_tools

    result = scene_tools._force_render_settings_core(doc)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


def _op_panel_render_add_frame_tag(payload):
    """``panel/render/add_frame_tag`` — runs
    ``scene_tools._add_sentinel_frame_tag_core`` (CRITICAL fix: the dialog-
    free core, NOT ``_add_sentinel_frame_tag`` itself — that function has 3
    ``MessageDialog`` branches that would block the ``MainThreadQueue``
    drain, freezing all of C4D, since a headless HTTP caller can never
    dismiss a dialog it can't see). No confirm gate — additive/idempotent,
    same as the native "Add Sentinel Frame to camera" button.

    Propagates the core's real status instead of a hardcoded success: only
    ``"ok"`` (a tag was actually created) returns ``{"ok": True, ...}``.
    Every other status — ``no_camera``/``already_tagged``/``import_failure``/
    ``create_failed`` — returns ``{"ok": False, "error": <status>}`` so the
    SPA never toasts success for a click that didn't create anything."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.ui import scene_tools

    result = scene_tools._add_sentinel_frame_tag_core(doc)
    status = result.get("status")

    if status == "ok":
        return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}

    return {"ok": False, "error": status or "unknown"}


def _op_panel_render_select_frame_tag(payload):
    """``panel/render/select_frame_tag`` — selects the scene's existing
    Sentinel Frame tag (found via ``_find_sentinel_frame_tag``) in the
    Attribute Manager. ``{"ok": False, "error": "no_tag"}`` when there is
    none."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    found = _find_sentinel_frame_tag(doc)
    if found is None:
        return {"ok": False, "error": "no_tag"}

    tag, _host = found
    try:
        doc.SetActiveTag(tag, c4d.SELECTION_NEW)
        c4d.EventAdd()
    except Exception as exc:
        safe_print(f"panel/render/select_frame_tag: {exc}")
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


_AOV_TIERS = {
    "essentials": AOV_TIER_ESSENTIALS,
    "production": AOV_TIER_PRODUCTION,
}


def _op_panel_render_aov_tier(payload):
    """``panel/render/aov_tier`` — additive (adds any AOVs missing up to the
    named tier; never removes existing ones), NOT confirm-gated: Essentials/
    Production are nested coverage LEVELS applied as one-shot actions, fully
    Cmd+Z-able, not a destructive rewrite. ``tier`` must be one of
    ``essentials``/``production``; anything else is ``invalid_tier``
    (a bad tier is a client bug — there is no confirm step to gate it
    behind any more).

    ``light_groups`` is no longer a valid value here — it was never an AOV
    tier (no list of AOV names to add), it's the independent Light Groups
    on/off toggle, now its own op: ``panel/render/set_light_groups``.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    tier = (payload or {}).get("tier")
    tier_list = _AOV_TIERS.get(tier)
    if tier_list is None:
        return {"ok": False, "error": "invalid_tier"}

    added, error = force_aov_tier(doc, tier_list)
    if error:
        return {"ok": False, "error": error}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


def _op_panel_render_set_light_groups(payload):
    """``panel/render/set_light_groups`` — Light Groups on Beauty is an
    independent on/off TOGGLE (state), not an AOV tier — sets it to the
    EXPLICIT ``enabled`` value the SPA's segmented toggle sends (never a
    blind flip, so two quick clicks can't race a read-then-flip — same
    convention as ``set_multipart``). Idempotent: if the scene is already in
    the requested state, this is a no-op success and
    ``scene_tools._toggle_light_groups_core`` (which only knows how to flip)
    is never called.

    ``no_groups_assigned`` (there ARE lights, but none carry a light-group
    assignment) is reported as an explicit failure —
    ``{"ok": False, "error": "no_groups_assigned"}`` — never silently
    swallowed into a false success, so the SPA can toast "No light groups
    assigned in the scene" instead of the toggle silently not flipping.
    """
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    if not REDSHIFT_AVAILABLE:
        return {"ok": False, "error": "redshift_unavailable"}

    enabled = bool((payload or {}).get("enabled"))

    current = bool(_is_lg_active_on_beauty(doc))
    if current == enabled:
        return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}

    from sentinel.ui import scene_tools

    result = scene_tools._toggle_light_groups_core(doc)
    status = result.get("status")
    if status in ("activated", "deactivated"):
        return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}
    if status == "no_groups_assigned":
        return {"ok": False, "error": "no_groups_assigned"}
    return {"ok": False, "error": result.get("error") or status or "unknown"}


def _op_panel_render_set_multipart(payload):
    """``panel/render/set_multipart`` — sets the Multi-Part EXR / Direct
    Output mode to an EXPLICIT ``enabled`` value (``aovs.set_scene_multipart``,
    the same reversible scene-scoped writer the Render tab's own switch
    uses). Idempotent (setting the mode it's already in is a no-op write,
    not an error) — the SPA's segmented switch always sends the value of
    the option clicked, never a flip of the current state, so there's no
    read-then-flip race between two quick clicks. No confirm gate —
    reversible, matches the native control's own lack of a confirmation
    step."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    enabled = bool((payload or {}).get("enabled"))
    ok, error = set_scene_multipart(doc, enabled)
    if not ok:
        return {"ok": False, "error": error}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


def _op_panel_render_aov_list(payload):
    """``panel/render/aov_list`` — read-only, for the inline "Show AOVs"
    expand. Mirrors the exact data ``ui/panel.py``'s ``BTN_INFO_AOVS``
    handler assembles (~line 2152-2192) into a JSON-shaped payload instead
    of a ``MessageDialog`` string: ``{aovs: [{name, type}], target,
    light_groups, tier_coverage: {essentials_missing, production_missing}}``.
    ``{"error": "redshift_unavailable"}`` when the Redshift Python module
    itself isn't importable — never a crash.

    ``aov["name"]`` is ``REDSHIFT_AOV_NAME`` — empty for every standard AOV
    the artist never manually renamed, which used to leave the SPA showing
    just the raw ``REDSHIFT_AOV_TYPE`` int (e.g. "(41)"). Each entry's
    ``name`` here is resolved to a display label instead: the artist's own
    name if set, else the friendly Sentinel name for that type
    (``aovs.aov_type_name``), else ``"AOV #<type>"`` for a type outside
    ``_AOV_DEFS`` (a custom AOV). ``type`` is still returned as the raw int
    for callers that want it."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"error": "no_document"}

    if not REDSHIFT_AVAILABLE:
        return {"error": "redshift_unavailable"}

    ess = check_rs_aovs(doc, AOV_TIER_ESSENTIALS)
    prod = check_rs_aovs(doc, AOV_TIER_PRODUCTION)
    target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
    lg_active = bool(_is_lg_active_on_beauty(doc))
    prod_only_missing = [n for n in prod.get("missing") or [] if n not in (ess.get("missing") or [])]

    type_map = _build_aov_type_name_map()
    aov_entries = []
    for aov in (prod.get("aovs") or []):
        aov_type = aov.get("type")
        display = aov.get("name") or aov_type_name(aov_type, type_map) or f"AOV #{aov_type}"
        aov_entries.append({"name": display, "type": aov_type})

    return {
        "aovs": aov_entries,
        "target": target_name,
        "light_groups": lg_active,
        "tier_coverage": {
            "essentials_missing": ess.get("missing") or [],
            "production_missing": prod_only_missing,
        },
    }


def _op_panel_render_toggle_watchfolder(payload):
    """``panel/render/toggle_watchfolder`` — flips the snapshot watchfolder
    auto-convert flag (``GlobalSettings.get_snapshot_watch``/
    ``set_snapshot_watch``, the same key ``CHK_SNAPSHOT_WATCH`` writes).
    No confirm gate — reversible, matches the native checkbox."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    GlobalSettings.set_snapshot_watch(not GlobalSettings.get_snapshot_watch())

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


def _op_panel_render_save_still(payload):
    """``panel/render/save_still`` — runs
    ``flows.snapshot_save_still_core`` (the dialog-free/Picture-Viewer-free
    core extracted from ``snapshot_save_still`` for this task — CRITICAL:
    NOT ``scene_tools._take_renderview_snapshot``/``flows.snapshot_save_still``
    themselves, which show ``MessageDialog`` and open the Picture Viewer, a
    modal/blocking pair that would freeze the ``MainThreadQueue`` drain).
    Artist name comes from ``GlobalSettings.load_artist_name()`` (no widget
    to read in the op path). Toast in the SPA takes the place of the
    native's ``StatusSetText``/Picture-Viewer confirmation."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.ui import flows

    artist_name = GlobalSettings.load_artist_name()
    result = flows.snapshot_save_still_core(doc, artist_name)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or result.get("stage") or "unknown"}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


def _op_panel_render_open_folder(payload):
    """``panel/render/open_folder`` — runs
    ``flows.snapshot_open_folder_core`` (the dialog-free core extracted
    from ``snapshot_open_folder``) to launch the effective snapshot stills
    dir in the OS file manager. Artist name from ``GlobalSettings``."""
    doc = documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}

    from sentinel.ui import flows

    artist_name = GlobalSettings.load_artist_name()
    result = flows.snapshot_open_folder_core(doc, artist_name)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}

    return {"ok": True, "stamp": _stamp_for(doc), "render": build_panel_render(doc)}


PANEL_RENDER_OPS = {
    "panel/render": _op_panel_render,
    "panel/render/set_preset": _op_panel_render_set_preset,
    "panel/render/reset_all": _op_panel_render_reset_all,
    "panel/render/add_frame_tag": _op_panel_render_add_frame_tag,
    "panel/render/select_frame_tag": _op_panel_render_select_frame_tag,
    "panel/render/aov_tier": _op_panel_render_aov_tier,
    "panel/render/set_light_groups": _op_panel_render_set_light_groups,
    "panel/render/set_multipart": _op_panel_render_set_multipart,
    "panel/render/aov_list": _op_panel_render_aov_list,
    "panel/render/toggle_watchfolder": _op_panel_render_toggle_watchfolder,
    "panel/render/save_still": _op_panel_render_save_still,
    "panel/render/open_folder": _op_panel_render_open_folder,
}
