# -*- coding: utf-8 -*-
"""Scene-mutation tools for the Sentinel panel (Phase 4 extraction).

Handler bodies moved verbatim out of YSPanel into module functions taking
(doc, ...). UI layer: these open dialogs and mutate the scene; panel methods
are thin delegates. Panel-state updates (button relabels, preset caption)
are injected via optional ``update_ui``/``refresh`` callbacks.
"""
import c4d
from c4d import documents
import os

from sentinel import postrender
from sentinel.aovs import (
    _get_rs_videopost,
    _is_lg_active_on_beauty,
    _scan_light_groups,
    check_rs_aovs,
    effective_mv_max_motion,
    force_aov_tier,
)
from sentinel.checks.render import normalize_preset_name
from sentinel.common.cache import check_cache
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.safe_areas import (
    is_object_marked_safe_area,
    mark_object_safe_area,
    unmark_object_safe_area,
)
from sentinel.ui.flows import _doc_full_path, snapshot_open_folder, snapshot_save_still

# Import Redshift module for AOV management
try:
    import redshift
    REDSHIFT_AVAILABLE = True
except ImportError:
    REDSHIFT_AVAILABLE = False

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _toggle_light_groups_core(doc):
    """Dialog-free core of the Light Groups on Beauty toggle — extracted
    from ``_toggle_light_groups`` (Fase 6.2 Task 2) so a non-interactive
    caller (``panel_render_ops.py``'s ``aov_tier`` op, ``tier="light_groups"``)
    can flip the flag without the native ``QuestionDialog``/diagnostic
    ``MessageDialog`` chain. Never asks for confirmation itself — the op
    layer owns the confirm-gate, same contract as ``_force_render_settings_core``.

    Returns a status dict, one of:
      ``{"status": "redshift_unavailable"}``
      ``{"status": "no_videopost"}``
      ``{"status": "no_lights"}``
      ``{"status": "no_groups_assigned", "ungrouped": [...]}``
      ``{"status": "no_beauty_aov"}``
      ``{"status": "activated"|"deactivated", "groups": [...]}``
    Never raises.
    """
    if not REDSHIFT_AVAILABLE:
        return {"status": "redshift_unavailable"}

    vprs = _get_rs_videopost(doc)
    if not vprs:
        return {"status": "no_videopost"}

    groups, ungrouped = _scan_light_groups(doc)
    lg_active = _is_lg_active_on_beauty(doc)

    if not groups and not ungrouped:
        return {"status": "no_lights"}

    if not groups:
        return {"status": "no_groups_assigned", "ungrouped": ungrouped}

    try:
        aovs = redshift.RendererGetAOVs(vprs)
        found = False
        for aov in aovs:
            try:
                if aov.GetParameter(c4d.REDSHIFT_AOV_NAME) == "Beauty":
                    new_state = not lg_active
                    aov.SetParameter(c4d.REDSHIFT_AOV_LIGHTGROUP_ALL, new_state)
                    found = True
                    break
            except Exception:
                pass

        if not found:
            return {"status": "no_beauty_aov"}

        redshift.RendererSetAOVs(vprs, aovs)
        check_cache.clear()
        c4d.EventAdd()
        if not lg_active:
            safe_print(f"Light Groups activated ({len(groups)} groups)")
            return {"status": "activated", "groups": sorted(groups.keys())}
        safe_print("Light Groups deactivated")
        return {"status": "deactivated", "groups": sorted(groups.keys())}

    except Exception as e:
        safe_print(f"Error toggling light groups: {e}")
        return {"status": "error", "error": str(e)}


def _toggle_light_groups(doc):
    """Toggle Light Groups on Beauty AOV with diagnostic. Thin dialog
    wrapper over ``_toggle_light_groups_core`` (Fase 6.2 Task 2) — asks the
    confirm question BEFORE toggling (the core has no side effects until
    called), so the diagnostic message + question are built from the same
    pre-toggle scan, then only calls the core once the artist confirms."""
    if not REDSHIFT_AVAILABLE:
        c4d.gui.MessageDialog("Redshift module not available.")
        return

    vprs = _get_rs_videopost(doc)
    if not vprs:
        c4d.gui.MessageDialog("Redshift VideoPost not found.")
        return

    groups, ungrouped = _scan_light_groups(doc)
    lg_active = _is_lg_active_on_beauty(doc)

    if not groups and not ungrouped:
        c4d.gui.MessageDialog("No lights found in the scene.")
        return

    # Build diagnostic message
    msg = f"LIGHT GROUPS — {'ACTIVE' if lg_active else 'INACTIVE'}\n\n"
    if groups:
        msg += f"Groups ({len(groups)}):\n"
        for gname, lights in sorted(groups.items()):
            msg += f"  [{gname}]: {', '.join(lights)}\n"
    if ungrouped:
        msg += f"\nUngrouped ({len(ungrouped)}): {', '.join(ungrouped)}\n"
        msg += f"  (These contribute to all groups)\n"

    if not groups:
        msg += "\nNo light groups assigned.\nAssign groups on your RS lights first."
        c4d.gui.MessageDialog(msg)
        return

    if lg_active:
        msg += "\nDeactivate Light Groups on Beauty AOV?"
    else:
        msg += "\nActivate Light Groups on Beauty AOV?"

    if not c4d.gui.QuestionDialog(msg):
        return

    result = _toggle_light_groups_core(doc)
    status = result.get("status")

    if status == "activated":
        c4d.gui.MessageDialog(f"Light Groups ACTIVATED on Beauty\n\n"
                             f"{len(result['groups'])} group(s): {', '.join(result['groups'])}\n"
                             f"RS will generate Beauty_[GroupName] sub-AOVs.")
    elif status == "deactivated":
        c4d.gui.MessageDialog("Light Groups DEACTIVATED on Beauty")
    elif status == "no_beauty_aov":
        c4d.gui.MessageDialog("Beauty AOV not found.\n\nRun Essentials or Production first.")
    elif status == "error":
        c4d.gui.MessageDialog(f"Error: {result.get('error')}")
    # redshift_unavailable/no_videopost/no_lights/no_groups_assigned can't
    # happen here — already handled above using the same pre-toggle scan.


def _force_aov_tier(doc, tier_list, tier_name):
    if not REDSHIFT_AVAILABLE:
        c4d.gui.MessageDialog("Redshift module not available.")
        return
    result = check_rs_aovs(doc, tier_list)
    if not result["missing"]:
        c4d.gui.MessageDialog(f"All {tier_name} AOVs already configured.")
        return
    missing_list = "\n".join(f"  - {n}" for n in result["missing"])
    if c4d.gui.QuestionDialog(f"Add {len(result['missing'])} {tier_name} AOVs?\n\n{missing_list}"):
        added, error = force_aov_tier(doc, tier_list)
        if error:
            c4d.gui.MessageDialog(f"Error: {error}")
        else:
            target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
            multipart = bool(int(GlobalSettings.get('aov_multipart', 1)))
            output_mode = "Multi-Part EXR (32-bit, ZIP lossless)" if multipart else "Direct Output (per-AOV settings)"
            safe_print(f"Added {added} {tier_name} AOVs for {target_name}")
            msg = f"Added {added} {tier_name} AOV(s)\n\n"
            msg += f"Compositor: {target_name}\n"
            msg += f"Output: {output_mode}\n\n"
            if target_name == "Nuke":
                msg += "Depth: Z raw, Center Sample\nMotion Vectors: Raw, No Clamp, No Filter"
            else:
                mv_max = effective_mv_max_motion(doc)
                msg += "Depth: Z Normalized Inverted, Center Sample\n"
                msg += f"Motion Vectors: Normalized 0-1, Max Motion={mv_max} px\n\n"
                msg += f"→ In RSMB (After Effects) set 'Max Displace' to {mv_max} to match this render."
            c4d.gui.MessageDialog(msg)


def _handle_validate_render(doc):
    """Run on-demand post-render validation for a chosen folder.

    Returns ``{"message": str}`` on success (a report was written, whether
    PASSED or ISSUES FOUND) so the caller (``panel._handle_validate_render``,
    Phase 2 Task 3) can open the Reports render_validation page and fall
    back to ``c4d.gui.MessageDialog(result["message"])`` if that fails to
    open. Returns ``None`` when the flow ended before producing a report
    (folder picker cancelled, invalid folder, audit exception) — those
    branches already showed their own MessageDialog, so there is nothing
    left for the caller to display.
    """
    folder = c4d.storage.LoadDialog(
        title="Select Render Output Folder",
        flags=c4d.FILESELECT_DIRECTORY,
    )
    if not folder:
        return None
    if not os.path.isdir(folder):
        c4d.gui.MessageDialog("Render validation cancelled:\n\nSelected folder is not valid.")
        return None

    try:
        findings = postrender.audit_render_folder(doc, folder)
        report = postrender.build_report(findings)
    except Exception as exc:
        safe_print(f"Render validation failed: {exc}")
        c4d.gui.MessageDialog(f"Render validation failed:\n\n{exc}")
        return None

    doc_path = _doc_full_path(doc)
    report_path = postrender.report_path_for_doc(doc_path, folder)
    wrote_report = postrender.write_report_atomic(report_path, report)
    wrote_history = postrender.append_render_history(doc_path or folder, report)

    context = report.get("context") or {}
    version = context.get("version") or "current scene"
    frame_start = context.get("frame_start")
    frame_end = context.get("frame_end")
    if frame_start is not None and frame_end is not None:
        frame_text = f"range {frame_start}-{frame_end}"
    else:
        frame_text = "range unavailable"
    mode = context.get("frame_mode") or "Unknown"
    status = "PASSED" if report.get("passed") else "ISSUES FOUND"
    summary = report.get("summary") or {}

    msg = (
        f"Post-render validation {status}\n\n"
        f"Validating {version} · {frame_text} · mode {mode}\n"
        f"Failures: {summary.get('failures', 0)}\n"
        f"Warnings: {summary.get('warnings', 0)}\n"
        f"Streams checked: {summary.get('streams', 0)}\n\n"
    )
    if not doc_path:
        msg += "Scene is unsaved; report and render history were written to the render folder.\n"
    msg += f"Report: {report_path if wrote_report else 'could not write report'}\n"
    if not wrote_history:
        msg += "Render history could not be updated.\n"
    return {"message": msg}


def _open_artist_folder(artist_name):
    """Open the artist's output folder"""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    snapshot_open_folder(doc, artist_name)


def _create_vibrate_null(doc):
    _merge_c4d_file(doc, "VibrateNull.c4d")


def _toggle_safe_area_mark_core(doc):
    """Mark / unmark the current selection as Safe Area Subjects.

    Dialog-free core (Fase 6.4 Task 3) — returns a status dict instead of
    showing a ``MessageDialog`` (a modal inside the panel's Timer drain
    freezes all of C4D). ``_toggle_safe_area_mark`` below is the thin native
    wrapper that re-shows the original dialog text on the tokened errors and
    (only there) calls an optional ``refresh()`` on success.

    Drives the QC #12 Cross-Aspect Safe-Area check. Smart toggle:
      - All selected objects ALREADY marked  → unmark them all
      - Any selected object NOT marked       → mark them all
                                               (aligns toward "marked")

    Marks persist as UserData boolean on each object — they survive
    save/reload and Cmd+Z reverts the operation as a single undo step.
    """
    if not doc:
        return {"ok": False, "error": "no_document"}

    sel = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN) or []
    if not sel:
        return {"ok": False, "error": "no_selection"}

    # Detect current state
    all_marked = all(is_object_marked_safe_area(o) for o in sel)
    target_state = not all_marked  # toggle: marked→unmark, otherwise mark

    marked_count = 0
    unmarked_count = 0
    failed_count = 0

    doc.StartUndo()
    try:
        for obj in sel:
            if target_state:
                # Marking pass
                ok = mark_object_safe_area(obj, True, doc)
                if ok:
                    marked_count += 1
                else:
                    failed_count += 1
            else:
                # Unmarking pass — fully remove the UserData entry so the
                # object returns to a "never been marked" state. Avoids
                # leaving fossil UD checkboxes on objects.
                ok = unmark_object_safe_area(obj, doc)
                if ok:
                    unmarked_count += 1
                else:
                    failed_count += 1
    finally:
        doc.EndUndo()
        c4d.EventAdd()

    # Invalidate the QC cache immediately so the next read reflects the
    # updated marks (the SPA polls; the native panel also calls refresh()).
    check_cache.clear()

    # Brief feedback (original native console message — preserved here on
    # the success path so it still fires exactly once, from the core).
    feedback_verb = "Marked" if target_state else "Unmarked"
    feedback_count = marked_count if target_state else unmarked_count
    msg = f"{feedback_verb} {feedback_count} object(s) as Safe Area Subject(s)"
    if failed_count:
        msg += f"\n({failed_count} failed — see Console for details)"
    safe_print(msg)

    return {
        "ok": True,
        "verb": "mark" if target_state else "unmark",
        "marked": marked_count,
        "unmarked": unmarked_count,
        "failed": failed_count,
    }


def _toggle_safe_area_mark(doc, refresh=None):
    """Mark / unmark the current selection as Safe Area Subjects.

    Native wrapper around ``_toggle_safe_area_mark_core`` — re-shows the
    original dialogs on the tokened errors, and calls ``refresh()`` (if
    provided) on success.
    """
    result = _toggle_safe_area_mark_core(doc)
    if result.get("error") == "no_document":
        c4d.gui.MessageDialog("No active document.")
    elif result.get("error") == "no_selection":
        c4d.gui.MessageDialog(
            "Select one or more objects first, then click again.\n\n"
            "Tip: mark important compositional elements (logo, title, "
            "character) so QC #12 can verify they stay inside the safe "
            "area of every multi-format delivery Take."
        )
    elif result.get("ok") and refresh is not None:
        try:
            refresh()
        except Exception:
            pass
    return result


def _create_hierarchy(doc):
    _merge_c4d_file(doc, "nulls.c4d")


def _merge_camera_file(doc, filename):
    _merge_c4d_file(doc, filename)


def _merge_c4d_file_core(doc, filename):
    """Dialog-free core of ``_merge_c4d_file`` (Fase 6.4) — merges a bundled
    template .c4d (nulls / vibrate null / camera rigs) into the doc. Returns
    a status dict; NEVER shows a dialog (a MessageDialog inside the panel's
    Timer drain freezes C4D — v1.21.0 pattern)."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    c4d_file = os.path.join(_ROOT, "c4d", filename)
    if not os.path.exists(c4d_file):
        safe_print(f"{filename} not found at: {c4d_file}")
        return {"ok": False, "error": "file_not_found", "filename": filename}
    try:
        merged = c4d.documents.MergeDocument(
            doc, c4d_file, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)
    except Exception as e:
        safe_print(f"Error merging camera file {filename}: {e}")
        return {"ok": False, "error": "merge_error", "detail": str(e)}
    if not merged:
        safe_print(f"Failed to merge {filename}")
        return {"ok": False, "error": "merge_failed"}
    c4d.EventAdd()
    camera_name = filename.replace(".c4d", "").replace("cam_", "").replace("_", " ").title()
    safe_print(f"Merged {camera_name} setup from {filename}")
    return {"ok": True, "camera_name": camera_name}


def _merge_c4d_file(doc, filename):
    """Merge a bundled template .c4d. Thin dialog wrapper over
    ``_merge_c4d_file_core`` — keeps the native MessageDialog UX."""
    result = _merge_c4d_file_core(doc, filename)
    if result.get("error") == "file_not_found":
        c4d.gui.MessageDialog(f"{filename} file not found in c4d folder")
    elif result.get("error") == "merge_error":
        c4d.gui.MessageDialog(f"Error loading camera setup: {result.get('detail')}")
    return result


def _bundled_template_path():
    """The template scene shipped inside the plugin — the fallback used when
    the project ruleset says nothing."""
    return os.path.join(_ROOT, "c4d", "new.c4d")


def _resolve_template_scene(doc=None):
    """Where the studio template scene lives for ``doc``, and which of the
    two origins it came from.

    Two origins, not three (artist decision): what the PROJECT ruleset says
    (``template_scene`` in ``sentinel_rules.json``, shared with the whole
    team through the folder it lives in) and, when the ruleset says
    nothing, the plugin's bundled ``c4d/new.c4d``. There is deliberately no
    per-machine override — a studio standard that a single workstation can
    quietly shadow is not a standard, and it would add a third place to
    look when something does not add up.

    Returns ``{"path": str, "origin": "project" | "plugin"}``. Existence is
    NOT checked here: the distinction that matters lives in the caller —
    "the ruleset said nothing" is normal and silent, "the ruleset named a
    path and it is not there" is an error that must refuse to run rather
    than fall back to a different standard.
    """
    try:
        from sentinel import rules as rules_module
        from sentinel.rules_context import active_rules_for_doc

        declared = rules_module.resolve_template_scene(active_rules_for_doc(doc))
    except Exception as exc:  # pragma: no cover - defensive
        # Not the "declared but missing" case — we could not read the
        # ruleset at all. Say so instead of swallowing it.
        safe_print(f"Could not resolve project template scene: {exc}")
        declared = None

    if declared:
        return {"path": declared, "origin": "project"}
    return {"path": _bundled_template_path(), "origin": "plugin"}


def _get_template_path(doc=None):
    """Path of the studio template scene for ``doc`` (see
    ``_resolve_template_scene`` for the two origins)."""
    return _resolve_template_scene(doc)["path"]


def _template_missing_result(template):
    """The refusal, worded so the two failures never read alike.

    ``project``: the ruleset named a file that is not there — Reset All
    does NOT run and does NOT fall back to the bundled template. Receiving a
    different standard than the one your studio defined, in silence, is
    exactly the failure mode this codebase keeps deleting; not being able to
    reset and knowing why is better.

    ``plugin``: the bundled template is missing — a broken install, and the
    historical message for it is kept verbatim.
    """
    if template["origin"] == "project":
        return {
            "ok": False,
            "reason": "project_template_missing",
            "error": ("Studio template scene not found!\n\n"
                      "The project ruleset (sentinel_rules.json) points at:\n"
                      f"{template['path']}\n\n"
                      "Render presets were NOT reset — fix the path or the "
                      "server mount rather than resetting from a different "
                      "template."),
        }
    return {
        "ok": False,
        "reason": "template_missing",
        "error": f"Template file not found!\n\nExpected at:\n{template['path']}",
    }


def _template_empty_result(template):
    """The only failure left once Reset All stopped filtering by name: the
    template file holds no render data at all.

    The old wording (``No standard presets found in template``) named
    neither the file nor which of the two it was, so a supervisor with a
    project template AND a bundled one could not tell which of their two
    files was wrong without opening both. It says both now.
    """
    if template["origin"] == "project":
        return {
            "ok": False,
            "reason": "template_empty",
            "error": ("Studio template scene has no render presets!\n\n"
                      "The project ruleset (sentinel_rules.json) points at:\n"
                      f"{template['path']}\n\n"
                      "Reset All copies whatever presets that file holds — "
                      "add the studio presets to it (any names you like) and "
                      "run this again."),
        }
    return {
        "ok": False,
        "reason": "template_empty",
        "error": ("Template file has no render presets!\n\n"
                  f"Found at:\n{template['path']}\n\n"
                  "This is the template bundled with the plugin — a broken "
                  "install, or point sentinel_rules.json at your studio "
                  "template instead."),
    }


def _apply_preset_core(doc, preset_name, index=None):
    """Dialog-free core of preset switching — extracted from ``ui/panel.py``
    ``_apply_preset`` (Fase 6.2 Task 1) so a non-``GeDialog`` caller
    (``panel_render_ops.py``) can apply a preset without touching
    ``self._active_preset``/UI widgets. Returns the matched ``RenderData``
    object, or ``None`` if ``doc`` is falsy or nothing matches. The native
    ``ui/panel.py`` ``_apply_preset`` calls this, then owns its own
    button/caption/``_active_preset`` updates and log line.

    Two ways to identify the target, in this order:

    - ``index`` (the position in the render data chain the panel dropdown
      showed) is used ONLY if the render data still sitting at that position
      carries exactly ``preset_name``. That makes two presets whose names
      normalize alike — ``Pre-Render`` and ``pre_render``, which QC #5
      reports as a duplicate — individually selectable instead of both
      activating the first one.
    - Otherwise (no index, or the scene changed under a stale panel read) it
      falls back to the historical behavior: the first render data whose
      NORMALIZED name matches. Normalization is right for matching — it is
      only wrong for display.
    """
    if not doc:
        return None

    def _activate(rd):
        doc.SetActiveRenderData(rd)
        check_cache.clear()  # Clear cache to update compliance check immediately
        c4d.EventAdd()
        return rd

    if index is not None:
        position = 0
        rd = doc.GetFirstRenderData()
        while rd:
            if position == index:
                if (rd.GetName() or "") == preset_name:
                    return _activate(rd)
                break  # stale index — fall through to the name scan
            rd = rd.GetNext()
            position += 1

    normalized_target = normalize_preset_name(preset_name)
    rd = doc.GetFirstRenderData()
    while rd:
        normalized_rd = normalize_preset_name(rd.GetName() or "")
        if normalized_rd == normalized_target:
            return _activate(rd)
        rd = rd.GetNext()
    return None


def _force_render_settings_core(doc, update_ui=None):
    """Dialog-free core of the "Reset All" flow — extracted from
    ``_force_render_settings`` (Fase 6.2 Task 1) so a non-interactive
    caller (``panel_render_ops.py``'s confirm-gated op) can run the reset
    without the native ``QuestionDialog``/summary ``MessageDialog``.
    Clones EVERY render data the template holds, in the template's own
    order, and replaces the doc's render data entries with them.

    THE TEMPLATE IS THE STANDARD (v1.36.10). Until now this filtered the
    template's presets against a list hardcoded here (``previz``,
    ``pre_render``, ``render``, ``stills``), so a studio could point the
    ruleset at its own template and still be told "No standard presets
    found in template" because its presets are called ``draft``/``final``
    — measured live. Since v1.36.5 QC #5 already validates against the
    project's ``required_presets``/``approved_presets``, so that studio had
    a conformant QC and an unusable Reset All at the same time.

    The rule adopted: the template creates, the ruleset validates. Three
    sources could disagree (the template, ``required_presets``,
    ``approved_presets``); making Reset All read one of the JSON lists just
    moves the same failure to a different list. Instead Reset All brings
    whatever the supervisor put in the file they actually edit, and if the
    ruleset disagrees QC #5 says so — disagreement detection for free, with
    no third source and no sync tool. Deliberately NOT done: deriving
    ``required_presets`` from the template — QC runs constantly (auto
    refresh, 0.5 s cache cooldown) and that would mean opening a ``.c4d``
    off a network share on every pass.

    ACCEPTED RISK: a junk preset left behind in the template now reaches
    the whole team. That is the supervisor's file to keep clean, which is
    the right place for the responsibility — and for today's artist nothing
    changes, their template holds exactly the four.

    The active preset on exit is the template's FIRST render data. Kept
    from the previous behavior and still meaningful with an arbitrary
    count: it is the supervisor's own ordering of the file, not a name this
    code guesses at.

    Returns ``{"ok": True, "count": N, "active_name": str, "resolution":
    "WxH"}`` on success, or ``{"ok": False, "error": <message>}`` — never
    shows a dialog, never raises. ``_force_render_settings`` below still
    shows both the confirm question and the result dialog, calling this
    core in between (byte-equivalent native behavior).

    UNDO (v1.36.3): the scene mutation runs inside ONE ``StartUndo``/
    ``EndUndo`` bracket with ``AddUndo(UNDOTYPE_DELETE, rd)`` BEFORE each
    ``Remove()`` and ``AddUndo(UNDOTYPE_NEW, clone)`` after each
    ``InsertRenderData``. Both halves are required and both are per-object
    — measured live (C4D 2026.303, throwaway document): with no ``AddUndo``
    at all a Cmd+Z restores nothing (the artist's presets are gone for
    good); registering only the deletions brings the originals back but
    leaves the 4 template clones behind (7 presets); with both, a single
    undo restores the exact starting state, including which render data was
    active. The bracket opens only once the clones exist, so every early
    error return above still leaves no undo step behind (an empty bracket
    does not materialize a step — measured in the v1.36 spike).
    """
    if not doc:
        return {"ok": False, "error": "no_document"}

    template = _resolve_template_scene(doc)
    template_path = template["path"]
    if not os.path.exists(template_path):
        return _template_missing_result(template)

    template_doc = None
    try:
        template_doc = c4d.documents.LoadDocument(template_path, c4d.SCENEFILTER_NONE)
        if not template_doc:
            return {"ok": False, "error": "Failed to load template file"}

        # Clone every preset the template holds, in its own order — no
        # name filter (see the docstring: the template IS the standard).
        cloned = []
        template_rd = template_doc.GetFirstRenderData()
        while template_rd:
            cloned.append(template_rd.GetClone(c4d.COPYFLAGS_NONE))
            template_rd = template_rd.GetNext()

        # Kill template before modifying scene
        c4d.documents.KillDocument(template_doc)
        template_doc = None

        if not cloned:
            return _template_empty_result(template)

        doc.StartUndo()
        try:
            # Remove existing presets (AddUndo BEFORE the mutation, once per
            # render data — the "works with one, breaks with N" trap).
            rd = doc.GetFirstRenderData()
            while rd:
                next_rd = rd.GetNext()
                doc.AddUndo(c4d.UNDOTYPE_DELETE, rd)
                rd.Remove()
                rd = next_rd

            # Insert cloned presets
            for clone in cloned:
                doc.InsertRenderData(clone)
                doc.AddUndo(c4d.UNDOTYPE_NEW, clone)

            doc.SetActiveRenderData(cloned[0])
        finally:
            doc.EndUndo()

        if update_ui is not None:
            update_ui()
        check_cache.clear()
        c4d.EventAdd()

        safe_print(f"Reset {len(cloned)} presets from template")
        return {
            "ok": True,
            "count": len(cloned),
            "active_name": cloned[0].GetName(),
            "resolution": "%dx%d" % (int(cloned[0][c4d.RDATA_XRES]), int(cloned[0][c4d.RDATA_YRES])),
        }

    except Exception as e:
        safe_print(f"Error resetting presets: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if template_doc:
            c4d.documents.KillDocument(template_doc)


def _force_render_settings(doc, update_ui=None):
    """Reset every render preset from the studio template file"""
    if not doc:
        return

    template = _resolve_template_scene(doc)
    if not os.path.exists(template["path"]):
        c4d.gui.MessageDialog(_template_missing_result(template)["error"])
        return

    if not c4d.gui.QuestionDialog("Reset ALL render presets from template?\n\nThis replaces existing presets with standard settings."):
        return

    result = _force_render_settings_core(doc, update_ui=update_ui)
    if not result["ok"]:
        c4d.gui.MessageDialog(result["error"])
        return

    c4d.gui.MessageDialog(f"Reset {result['count']} render presets from template\n\n"
                         f"Active: {result['active_name']}\n"
                         f"Resolution: {result['resolution']}")


def _add_sentinel_frame_tag_core(doc):
    """Dialog-free core of the Sentinel Frame tag add/select flow —
    extracted from ``_add_sentinel_frame_tag`` (Fase 6.2 Task 1 fix, CRITICAL:
    a non-interactive caller running this inside the ``MainThreadQueue``
    drain must never hit a native ``MessageDialog`` — any of the 3 dialog
    branches the old inline version had would otherwise freeze ALL of C4D
    until someone manually dismissed a dialog nobody could see, since the
    op runs headless over HTTP).

    Resolves a camera (active selection if it's a camera, else the
    viewport's scene camera), then either selects an existing Sentinel
    Frame tag or creates a new one. Returns a status dict, never raises,
    never shows a dialog:

      {"status": "no_document"}
      {"status": "import_failure", "error": str}
      {"status": "no_camera"}
      {"status": "already_tagged", "tag": <BaseTag>, "camera": <BaseObject>}
      {"status": "create_failed", "camera": <BaseObject>}
      {"status": "ok", "tag": <BaseTag>, "camera": <BaseObject>}

    ``_add_sentinel_frame_tag`` below calls this then shows its own
    dialogs based on the returned status — same text/order as before this
    extraction (byte-equivalent native behavior).
    """
    if doc is None:
        return {"status": "no_document"}

    try:
        from sentinel.ui.frame_tag import (
            SENTINEL_FRAME_TAG_PLUGIN_ID, is_valid_camera_host)
    except Exception as e:
        return {"status": "import_failure", "error": str(e)}

    # Resolve a camera: the active selected object if it's a camera, else
    # the camera the viewport is looking through.
    cam = None
    active = doc.GetActiveObject()
    if active is not None and is_valid_camera_host(active.GetType()):
        cam = active
    if cam is None:
        try:
            bd = doc.GetActiveBaseDraw()
            scene_cam = bd.GetSceneCamera(doc) if bd else None
            if scene_cam is not None and is_valid_camera_host(scene_cam.GetType()):
                cam = scene_cam
        except Exception:
            cam = None
    if cam is None:
        return {"status": "no_camera"}

    existing = None
    for t in cam.GetTags():
        if t.GetType() == SENTINEL_FRAME_TAG_PLUGIN_ID:
            existing = t
            break
    if existing is not None:
        try:
            doc.SetActiveTag(existing, c4d.SELECTION_NEW)
            c4d.EventAdd()
        except Exception:
            pass
        return {"status": "already_tagged", "tag": existing, "camera": cam}

    tag = None
    doc.StartUndo()
    try:
        tag = cam.MakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        if tag is not None:
            doc.AddUndo(c4d.UNDOTYPE_NEW, tag)
            try:
                doc.SetActiveTag(tag, c4d.SELECTION_NEW)
            except Exception:
                pass
    finally:
        doc.EndUndo()
        c4d.EventAdd()

    if tag is None:
        return {"status": "create_failed", "camera": cam}

    safe_print(f"Sentinel Frame tag added to '{cam.GetName()}'")
    return {"status": "ok", "tag": tag, "camera": cam}


def _add_sentinel_frame_tag(doc):
    """Add a Sentinel Frame tag to the active/selected camera, or select the
    existing one. The tag is the recommended per-camera multi-format entry
    point (live guides + one-click, rename-safe WYSIWYG-crop delivery Takes).

    Thin dialog wrapper over ``_add_sentinel_frame_tag_core`` (Fase 6.2
    Task 1 fix) — same dialog text/order as before the extraction.
    """
    result = _add_sentinel_frame_tag_core(doc)
    status = result.get("status")

    if status == "no_document":
        return
    if status == "import_failure":
        c4d.gui.MessageDialog(f"Sentinel Frame tag unavailable: {result['error']}")
        return
    if status == "no_camera":
        c4d.gui.MessageDialog(
            "Select a camera (standard or Redshift), or look through one, "
            "then click 'Add Sentinel Frame to camera'.")
        return
    if status == "already_tagged":
        c4d.gui.MessageDialog(
            f"'{result['camera'].GetName()}' already has a Sentinel Frame tag — "
            "selected it in the Attribute Manager.")
        return
    if status == "create_failed":
        c4d.gui.MessageDialog("Could not create the Sentinel Frame tag.")
        return
    # status == "ok" — safe_print already logged inside the core.


def _hierarchy_to_layers_core(doc):
    """Link main project nulls and their children to layers with matching names.

    Dialog-free core (Fase 6.4 Task 2) — returns a status dict instead of
    showing a ``MessageDialog`` (a modal inside the panel's Timer drain
    freezes all of C4D). ``_hierarchy_to_layers`` below is the thin native
    wrapper that re-shows the original dialog text on the tokened errors.
    """
    if not doc:
        return {"ok": False, "error": "no_document"}

    safe_print("Starting Hierarchy to Layers sync...")

    # Check for objects outside nulls first
    root_objects = []
    orphan_objects = []

    obj = doc.GetFirstObject()
    while obj:
        # Only consider top-level objects
        if obj.GetUp() is None:
            if obj.GetType() == c4d.Onull:
                root_objects.append(obj)
            else:
                # Check if it's a camera or light (they might be allowed outside)
                obj_type = obj.GetType()
                if obj_type not in [c4d.Ocamera, c4d.Olight]:
                    orphan_objects.append(obj)
        obj = obj.GetNext()

    # If there are orphan objects, report the error
    if orphan_objects:
        orphan_names = [obj.GetName() for obj in orphan_objects[:5]]  # First 5
        safe_print(f"Aborted: {len(orphan_objects)} objects found outside null groups")
        return {
            "ok": False,
            "error": "orphans",
            "count": len(orphan_objects),
            "names": orphan_names,
        }

    # No orphans, proceed with layer sync
    if not root_objects:
        return {"ok": False, "error": "no_groups"}

    # Start undo
    doc.StartUndo()

    # Get or create layer root
    layer_root = doc.GetLayerObjectRoot()
    if not layer_root:
        safe_print("Error: Could not get layer root")
        doc.EndUndo()
        return {"ok": False, "error": "no_layer_root"}

    created_layers = 0
    updated_layers = 0

    for null in root_objects:
        null_name = null.GetName()

        # Find or create layer with matching name (returns layer and is_new flag)
        layer, is_new = _find_or_create_layer(doc, layer_root, null_name)

        if layer:
            # Assign null and all children to this layer
            _assign_to_layer_recursive(doc, null, layer)

            if is_new:
                created_layers += 1
                safe_print(f"Created new layer '{null_name}' and synced objects")
            else:
                updated_layers += 1
                safe_print(f"Updated existing layer '{null_name}' with objects")

    doc.EndUndo()
    c4d.EventAdd()

    safe_print(f"Hierarchy→Layers complete: {created_layers} new, {updated_layers} updated layers, {len(root_objects)} nulls synced")
    return {
        "ok": True,
        "created": created_layers,
        "updated": updated_layers,
        "synced": len(root_objects),
    }


def _hierarchy_to_layers(doc):
    """Link main project nulls and their children to layers with matching names.

    Thin dialog wrapper over ``_hierarchy_to_layers_core`` (Fase 6.4 Task 2) —
    same dialog text/order as before the extraction.
    """
    result = _hierarchy_to_layers_core(doc)
    error = result.get("error")

    if error == "orphans":
        orphan_names = result["names"]
        more = f" and {result['count']-5} more" if result["count"] > 5 else ""
        msg = f"Found {result['count']} object(s) outside of null groups:\n"
        msg += "\n".join(orphan_names) + more
        msg += "\n\nPlease organize all objects into null groups first."
        c4d.gui.MessageDialog(msg)
    elif error == "no_groups":
        c4d.gui.MessageDialog("No null groups found in the scene.")
    # "no_document"/"no_layer_root" had no dialog originally — silent.
    return result


def _find_or_create_layer(doc, layer_root, name):
    """Find existing layer by name or create new one. Returns (layer, is_new)"""
    # First, search for existing layer
    layer = layer_root.GetDown()
    while layer:
        if layer.GetName() == name:
            return layer, False  # Found existing
        layer = layer.GetNext()

    # Create new layer
    new_layer = c4d.documents.LayerObject()
    new_layer.SetName(name)
    new_layer.InsertUnder(layer_root)

    # Generate unique random color based on layer name hash
    # This ensures same name always gets same color (consistent)
    import hashlib

    # Create hash from name
    name_hash = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)

    # Generate pleasant, distinct colors using golden ratio
    # This creates visually distinct colors that are evenly distributed
    golden_ratio = 0.618033988749895
    hue = (name_hash * golden_ratio) % 1.0

    # Convert HSV to RGB (S=0.6, V=0.95 for pleasant, bright colors)
    saturation = 0.6
    value = 0.95

    def hsv_to_rgb(h, s, v):
        """Convert HSV to RGB"""
        h_i = int(h * 6)
        f = h * 6 - h_i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)

        if h_i == 0:
            r, g, b = v, t, p
        elif h_i == 1:
            r, g, b = q, v, p
        elif h_i == 2:
            r, g, b = p, v, t
        elif h_i == 3:
            r, g, b = p, q, v
        elif h_i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q

        return c4d.Vector(r, g, b)

    unique_color = hsv_to_rgb(hue, saturation, value)
    new_layer[c4d.ID_LAYER_COLOR] = unique_color

    doc.AddUndo(c4d.UNDOTYPE_NEW, new_layer)
    return new_layer, True  # Return new layer and flag


def _solo_layers_core(doc):
    """Solo selected layers - disable all other layers and their objects.

    Dialog-free core (Fase 6.4 Task 2) — returns a status dict instead of
    showing a ``MessageDialog``. ``_solo_layers`` below is the thin native
    wrapper that re-shows the original dialog text on the tokened errors.
    """
    if not doc:
        return {"ok": False, "error": "no_document"}

    # Check if any layers are currently disabled (solo is active)
    # If so, restore all layers
    layer_root = doc.GetLayerObjectRoot()
    if not layer_root:
        safe_print("Error: Could not get layer root")
        return {"ok": False, "error": "no_layer_root"}

    # Check if we're in solo mode
    def check_solo_mode(layer):
        """Check if any layer is disabled (indicating solo mode)"""
        while layer:
            if not layer[c4d.ID_LAYER_VIEW]:
                return True
            child = layer.GetDown()
            if child and check_solo_mode(child):
                return True
            layer = layer.GetNext()
        return False

    first_layer = layer_root.GetDown()
    if first_layer and check_solo_mode(first_layer):
        # We're in solo mode, restore all
        _unsolo_layers(doc)
        return {"ok": True, "unsolo": True}

    # Get all selected layers
    selected_layers = []

    def collect_selected_layers(layer):
        """Recursively collect selected layers"""
        while layer:
            if layer.GetBit(c4d.BIT_ACTIVE):
                selected_layers.append(layer)
            # Check children
            child = layer.GetDown()
            if child:
                collect_selected_layers(child)
            layer = layer.GetNext()

    # Start from first layer
    first_layer = layer_root.GetDown()
    if not first_layer:
        return {"ok": False, "error": "no_layers"}

    collect_selected_layers(first_layer)

    if not selected_layers:
        return {"ok": False, "error": "no_selection"}

    safe_print(f"Solo mode: Isolating {len(selected_layers)} layer(s)")

    # Start undo
    doc.StartUndo()

    # Track what we're doing
    layers_disabled = 0
    layers_soloed = 0
    objects_affected = 0

    # First pass: Process all layers
    def process_layer(layer, is_soloed):
        """Process a layer and return count of affected objects"""
        nonlocal layers_disabled, layers_soloed

        doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

        if is_soloed:
            # Enable this layer
            layer[c4d.ID_LAYER_VIEW] = True
            layer[c4d.ID_LAYER_RENDER] = True
            layer[c4d.ID_LAYER_MANAGER] = True
            layer[c4d.ID_LAYER_GENERATORS] = True
            layer[c4d.ID_LAYER_DEFORMERS] = True
            layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
            layer[c4d.ID_LAYER_ANIMATION] = True
            layer[c4d.ID_LAYER_LOCKED] = False
            # Try XPresso specific flag if it exists
            if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                layer[c4d.ID_LAYER_XPRESSO] = True
            layers_soloed += 1
            safe_print(f"  Enabled layer: {layer.GetName()}")
        else:
            # Disable this layer completely
            layer[c4d.ID_LAYER_VIEW] = False
            layer[c4d.ID_LAYER_RENDER] = False
            layer[c4d.ID_LAYER_MANAGER] = False
            layer[c4d.ID_LAYER_GENERATORS] = False
            layer[c4d.ID_LAYER_DEFORMERS] = False
            layer[c4d.ID_LAYER_EXPRESSIONS] = False  # This controls XPresso
            layer[c4d.ID_LAYER_ANIMATION] = False
            # Try XPresso specific flag if it exists
            if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                layer[c4d.ID_LAYER_XPRESSO] = False
            layers_disabled += 1

    # Process all layers
    def process_all_layers(layer):
        while layer:
            is_selected = layer in selected_layers
            process_layer(layer, is_selected)

            # Process children
            child = layer.GetDown()
            if child:
                process_all_layers(child)

            layer = layer.GetNext()

    process_all_layers(first_layer)

    # Second pass: Handle objects without layers (disable them too)
    def disable_unassigned_objects(obj):
        """Disable objects not assigned to any layer"""
        nonlocal objects_affected

        while obj:
            # Check if object has no layer assignment
            if not obj.GetLayerObject(doc):
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                # Disable the object
                obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 1  # Hide in editor
                obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 1  # Hide in render

                # Disable generators and deformers
                obj.SetDeformMode(False)

                # If it's a generator, try to disable it
                if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                    obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = False

                objects_affected += 1

            # Process children
            child = obj.GetDown()
            if child:
                disable_unassigned_objects(child)

            obj = obj.GetNext()

    # Disable unassigned objects
    first_object = doc.GetFirstObject()
    if first_object:
        disable_unassigned_objects(first_object)

    doc.EndUndo()
    c4d.EventAdd()

    # Report to console
    safe_print(f"Solo Layers complete: {layers_soloed} soloed, {layers_disabled} disabled, {objects_affected} unassigned objects hidden")
    return {
        "ok": True,
        "soloed": layers_soloed,
        "disabled": layers_disabled,
        "objects_hidden": objects_affected,
    }


def _solo_layers(doc):
    """Solo selected layers - disable all other layers and their objects.

    Thin dialog wrapper over ``_solo_layers_core`` (Fase 6.4 Task 2) — same
    dialog text/order as before the extraction.
    """
    result = _solo_layers_core(doc)
    error = result.get("error")

    if error == "no_layers":
        c4d.gui.MessageDialog(
            "No layers found in the scene.\nCreate layers first using Hierarchy→Layers.")
    elif error == "no_selection":
        c4d.gui.MessageDialog("Please select one or more layers to solo.")
    # "no_document"/"no_layer_root" had no dialog originally — silent.
    return result


def _unsolo_layers(doc):
    """Restore all layers to their default visible state"""
    if not doc:
        return

    safe_print("Restoring all layers...")

    # Get layer root
    layer_root = doc.GetLayerObjectRoot()
    if not layer_root:
        return

    doc.StartUndo()

    layers_restored = 0

    def restore_layer(layer):
        """Restore a layer to default visible state"""
        nonlocal layers_restored

        while layer:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

            # Enable everything
            layer[c4d.ID_LAYER_VIEW] = True
            layer[c4d.ID_LAYER_RENDER] = True
            layer[c4d.ID_LAYER_MANAGER] = True
            layer[c4d.ID_LAYER_GENERATORS] = True
            layer[c4d.ID_LAYER_DEFORMERS] = True
            layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
            layer[c4d.ID_LAYER_ANIMATION] = True
            layer[c4d.ID_LAYER_LOCKED] = False
            # Try XPresso specific flag if it exists
            if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                layer[c4d.ID_LAYER_XPRESSO] = True

            layers_restored += 1

            # Process children
            child = layer.GetDown()
            if child:
                restore_layer(child)

            layer = layer.GetNext()

    # Restore all layers
    first_layer = layer_root.GetDown()
    if first_layer:
        restore_layer(first_layer)

    # Restore objects without layers
    def restore_unassigned_objects(obj):
        while obj:
            if not obj.GetLayerObject(doc):
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
                obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 2  # Show
                obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 2  # Show
                obj.SetDeformMode(True)
                if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                    obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = True

            child = obj.GetDown()
            if child:
                restore_unassigned_objects(child)

            obj = obj.GetNext()

    first_object = doc.GetFirstObject()
    if first_object:
        restore_unassigned_objects(first_object)

    doc.EndUndo()
    c4d.EventAdd()

    safe_print(f"Restored {layers_restored} layers to visible state")


def _assign_to_layer_recursive(doc, obj, layer):
    """Assign object and all its children to a layer"""
    if not obj or not layer:
        return

    # Add undo for the object
    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

    # Assign to layer
    obj.SetLayerObject(layer)

    # Process all children recursively
    child = obj.GetDown()
    while child:
        _assign_to_layer_recursive(doc, child, layer)
        child = child.GetNext()


def _drop_to_floor_core(doc):
    """Drop selected objects to floor (Y=0 plane) - handles rotation and
    hierarchy correctly.

    Dialog-free core (Fase 6.4 Task 2) — returns a status dict. The original
    function had no dialog on the no-selection branch (``safe_print`` only),
    so the wrapper below does nothing extra for it.
    """
    if not doc:
        return {"ok": False, "error": "no_document"}

    # Get selected objects
    selected = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_SELECTIONORDER)
    if not selected:
        safe_print("Please select one or more objects to drop to floor")
        return {"ok": False, "error": "no_selection"}

    # Start undo
    doc.StartUndo()

    dropped_count = 0

    for obj in selected:
        # Get object's global matrix
        mg = obj.GetMg()

        # Get cache (the actual geometry for display/render)
        cache = obj.GetCache()
        if cache is None:
            cache = obj.GetDeformCache()

        # If we have a cache, use it to get the accurate global bounding box
        if cache:
            # Initialize with first point
            min_y = None

            # Recursively process cache and all children
            def process_cache(cache_obj, parent_mg):
                """Recursively get all points from cache hierarchy"""
                nonlocal min_y

                if not cache_obj:
                    return

                # Get cache's local matrix
                cache_mg = cache_obj.GetMl()
                # Combine with parent matrix to get global position
                global_mg = parent_mg * cache_mg

                # Get points if this is a PointObject
                if cache_obj.CheckType(c4d.Opoint):
                    points = cache_obj.GetAllPoints()
                    if points:
                        for point in points:
                            # Transform point to global space
                            global_point = global_mg * point
                            if min_y is None or global_point.y < min_y:
                                min_y = global_point.y

                # Process children
                child = cache_obj.GetDown()
                if child:
                    process_cache(child, global_mg)

                # Process siblings
                next_obj = cache_obj.GetNext()
                if next_obj:
                    process_cache(next_obj, parent_mg)

            # Process cache hierarchy
            process_cache(cache, mg)

            # If we didn't find any points, fall back to bounding box method
            if min_y is None:
                # Use bounding box as fallback
                mp = obj.GetMp()
                rad = obj.GetRad()

                if rad.GetLength() == 0:
                    rad = c4d.Vector(50, 50, 50)

                # Calculate all 8 corners
                corners = [
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                ]

                min_y = float('inf')
                for corner in corners:
                    world_corner = mg * corner
                    if world_corner.y < min_y:
                        min_y = world_corner.y
        else:
            # No cache - use bounding box method
            mp = obj.GetMp()
            rad = obj.GetRad()

            if rad.GetLength() == 0:
                rad = c4d.Vector(50, 50, 50)

            # Calculate all 8 corners
            corners = [
                c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
            ]

            min_y = float('inf')
            for corner in corners:
                world_corner = mg * corner
                if world_corner.y < min_y:
                    min_y = world_corner.y

        # Calculate how much to move the object
        if min_y is not None and abs(min_y) > 0.001:  # Small threshold to avoid tiny movements
            move_distance = -min_y

            # Record undo for position change
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

            # Move the object in global space
            current_pos = obj.GetAbsPos()
            new_pos = c4d.Vector(current_pos.x, current_pos.y + move_distance, current_pos.z)
            obj.SetAbsPos(new_pos)

            dropped_count += 1
            safe_print(f"Dropped '{obj.GetName()}' by {move_distance:.2f} units")

    # End undo
    doc.EndUndo()

    # Update the scene
    c4d.EventAdd()

    # Show result message in console only (no popup for smooth workflow)
    if dropped_count == 1:
        safe_print(f"Dropped 1 object to floor")
    elif dropped_count > 1:
        safe_print(f"Dropped {dropped_count} objects to floor")
    else:
        safe_print("No objects needed dropping - already on floor")

    return {"ok": True, "dropped": dropped_count}


def _drop_to_floor(doc):
    """Drop selected objects to floor (Y=0 plane) - handles rotation and
    hierarchy correctly.

    Thin wrapper over ``_drop_to_floor_core`` (Fase 6.4 Task 2) — the
    original had no dialog on any branch, so this simply forwards the
    result.
    """
    return _drop_to_floor_core(doc)


def _take_renderview_snapshot(artist_name):
    """Take a snapshot from RenderView"""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return

    snapshot_save_still(doc, artist_name)


def _apply_abc_retime_tag_core(doc):
    """Apply ABC Retime tag to selected object(s).

    Dialog-free core (Fase 6.4 Task 3) — returns a status dict instead of
    showing a ``MessageDialog`` (a modal inside the panel's Timer drain
    freezes all of C4D). ``_apply_abc_retime_tag`` below is the thin native
    wrapper (no-arg signature preserved) that re-shows the original dialogs
    on the tokened errors.
    """
    if not doc:
        return {"ok": False, "error": "no_document"}

    selection = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN)
    if not selection:
        return {"ok": False, "error": "no_selection"}

    # ABC Retime plugin ID
    ABC_RETIME_TAG_ID = 1058910

    applied_count = 0
    skipped_count = 0
    failed_count = 0

    for obj in selection:
        # Check if tag already exists
        existing_tag = obj.GetTag(ABC_RETIME_TAG_ID)
        if existing_tag:
            safe_print(f"ABC Retime tag already exists on {obj.GetName()}")
            skipped_count += 1
            continue

        # Apply the tag
        tag = obj.MakeTag(ABC_RETIME_TAG_ID)
        if tag:
            applied_count += 1
            safe_print(f"ABC Retime tag applied to {obj.GetName()}")
        else:
            failed_count += 1
            safe_print(f"Failed to apply ABC Retime tag to {obj.GetName()}")

    # Update the scene
    if applied_count > 0:
        c4d.EventAdd()

    if applied_count == 0 and skipped_count == 0:
        return {"ok": False, "error": "apply_failed"}

    return {
        "ok": True,
        "applied": applied_count,
        "skipped": skipped_count,
        "failed": failed_count,
    }


def _apply_abc_retime_tag():
    """Apply ABC Retime tag to selected object(s).

    Native wrapper around ``_apply_abc_retime_tag_core`` — fetches the
    active document itself (preserves the original no-arg signature) and
    re-shows the original dialogs on the tokened errors.
    """
    doc = documents.GetActiveDocument()
    result = _apply_abc_retime_tag_core(doc)
    if result.get("error") == "no_document":
        c4d.gui.MessageDialog("No active document")
    elif result.get("error") == "no_selection":
        c4d.gui.MessageDialog("Please select an object first\n\n(Works with Alembic, Point Cache, Mograph Cache, or X-Particles Cache objects)")
    elif result.get("error") == "apply_failed":
        c4d.gui.MessageDialog("ABC Retime tag could not be applied\n\nPossible reasons:\n- ABC Retime plugin not installed\n- Invalid object type\n\nManual access: Right-click Tags → Extensions → Alembic Retime")
    return result


def _iter_objects_bottom_up(first):
    """Yield the hierarchy depth-first, CHILDREN BEFORE PARENTS, materializing
    the order up-front so removals during iteration can't skip siblings."""
    out = []

    def _walk(obj):
        while obj:
            child = obj.GetDown()
            if child:
                _walk(child)
            out.append(obj)
            obj = obj.GetNext()

    _walk(first)
    return out


def _delete_empty_nulls_core(doc):
    """Delete empty nulls: an Onull with no children and NO tags of any kind
    (any tag — XPresso/constraint/UserData — saves it). Bottom-up cascade: a
    null whose descendants were all empty nulls falls too. One undo step.
    Dialog-free core (v1.30) — status dict only."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    targets_seen = False
    removed = 0
    doc.StartUndo()
    try:
        for obj in _iter_objects_bottom_up(doc.GetFirstObject()):
            try:
                if obj.GetType() != c4d.Onull:
                    continue
                if obj.GetDown() is not None or obj.GetFirstTag() is not None:
                    continue
            except Exception:
                continue
            targets_seen = True
            try:
                doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, obj)
            except Exception:
                pass
            try:
                obj.Remove()
            except Exception:
                continue
            removed += 1
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    if not removed and not targets_seen:
        return {"ok": False, "error": "none_found"}
    safe_print(f"Sentinel: removed {removed} empty null(s)")
    return {"ok": True, "removed": removed}


def _material_key(material):
    """Identity key for a material. Materials have NO ``GetGUID()`` — that's
    BaseObject-only API (same live-caught class as the BaseTag lesson in
    ``frame_sync._tag_key``). Two BaseMaterial *wrappers* in real C4D can
    point at the same underlying node and differ by ``id()``, so the correct
    identity is ``FindUniqueID(MAXON_CREATOR_ID)`` (BaseList2D-level, equal
    across wrappers of the same material — verified live in C4D 2026.303).
    Fall back to ``id()`` only when FindUniqueID is unavailable/raises."""
    try:
        uid = material.FindUniqueID(c4d.MAXON_CREATOR_ID)
        if uid:
            return bytes(uid).hex()
    except Exception:
        pass
    return id(material)


def _texture_tag_identity(tag):
    """(material_key, restriction) key for exact-duplicate detection."""
    try:
        material = tag[c4d.TEXTURETAG_MATERIAL]
    except Exception:
        material = None
    try:
        restriction = tag[c4d.TEXTURETAG_RESTRICTION] or ""
    except Exception:
        restriction = ""
    return material, restriction


def _clean_material_tags_core(doc):
    """Remove broken texture tags (dead/None material) and EXACT duplicates
    on the same object (same material + same restriction, keep the LAST —
    the one C4D prioritizes). One undo step. Dialog-free core (v1.30)."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    removed_broken = 0
    removed_dupes = 0
    doc.StartUndo()
    try:
        for obj in _iter_objects_bottom_up(doc.GetFirstObject()):
            try:
                tags = [t for t in (obj.GetTags() or []) if t.GetType() == c4d.Ttexture]
            except Exception:
                continue
            keep_last = {}
            for tag in tags:
                material, restriction = _texture_tag_identity(tag)
                if material is None:
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, tag)
                    except Exception:
                        pass
                    try:
                        tag.Remove()
                    except Exception:
                        continue
                    removed_broken += 1
                    continue
                key = (_material_key(material), restriction)
                if key in keep_last:
                    prev = keep_last[key]
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, prev)
                    except Exception:
                        pass
                    try:
                        prev.Remove()
                    except Exception:
                        keep_last[key] = tag
                        continue
                    removed_dupes += 1
                keep_last[key] = tag
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    if not removed_broken and not removed_dupes:
        return {"ok": False, "error": "none_found"}
    safe_print(
        f"Sentinel: removed {removed_broken} broken + {removed_dupes} duplicate material tag(s)")
    return {"ok": True, "removed_broken": removed_broken, "removed_dupes": removed_dupes}
