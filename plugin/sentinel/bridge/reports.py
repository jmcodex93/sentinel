"""Pure report-payload transformations for Sentinel's web UI."""

import json
import os

from sentinel.qc.registry import CHECK_REGISTRY

# source_type values (see manifest.py / textures.py docstrings) that come
# from a material's shader/node graph. rs_object_fileref is deliberately
# NOT here: it is an object-level file reference (dome HDR, light gobo) and
# its ``channel`` is already a human label ("Dome HDR", "Light texture").
_MATERIAL_SOURCE_TYPES = frozenset({
    "rs_node", "arnold_node", "classic_shader", "octane_shader", "bc_param",
})


def _asset_provenance(entry):
    """Human-readable origin for one manifest asset entry, e.g.
    ``"material · Body Shell"`` — built from source_type/channel/host, the
    only fields manifest.py's ``build_asset_entries`` records for this.
    Never raises: every field defaults to "" and missing pieces are simply
    omitted from the joined string.
    """
    source_type = entry.get("source_type") or ""
    channel = entry.get("channel") or ""
    host = entry.get("host") or ""

    if source_type in _MATERIAL_SOURCE_TYPES:
        category = "material"
    elif source_type == "object_bc":
        category = "object"
    elif source_type == "alembic":
        category = "alembic cache"
    elif source_type == "rs_object_fileref":
        # channel is already descriptive here ("Dome HDR", "Light texture").
        category = channel or "object"
    else:
        category = source_type or "asset"

    return f"{category} · {host}" if host else category


def _delivery_asset(entry):
    return {
        "path": entry.get("path") or "",
        "status": entry.get("state") or "",
        "provenance": _asset_provenance(entry),
    }
# ---------------------------------------------------------------------------
# panel/qc grouping — ui/panel_ops.py (Fase 6.1 Task 1)
# ---------------------------------------------------------------------------

_FIX_ACTION_ID_BY_CHECK_ID = {
    "lights": "fix_lights",
    "cam": "fix_cameras",
    "unused_mats": "fix_materials",
    "fps_range": "fix_fps",
    "rs_colorspace": "fix_rs_colorspace",
}


def group_qc_by_severity(checks):
    """Pure: partition ``qc_report_payload``'s ``checks`` list into the
    ``panel/qc`` shape (``ui/panel_ops.py``) — FAIL cards, WARN cards, a
    folded OK count, and a disabled count. Never re-derives scoring, only
    reshapes rows ``qc_report_payload`` already built.

    Each FAIL/WARN card is enriched with the per-card action flags the SPA
    needs, sourced from ``CHECK_REGISTRY``/``PALETTE_ACTIONS`` — never
    invented: ``can_select``/``can_fix`` come straight from the entry's
    declared ``actions`` tuple (same source ``qc_report_payload`` uses for
    ``has_fix``), and ``fix_action_id`` is the matching ``PALETTE_ACTIONS``
    "Quick Fix" id for that check_id via ``_FIX_ACTION_ID_BY_CHECK_ID``
    (``None`` for a check with no entry in that mapping). Every
    ``has_fix`` check_id in the registry has an entry there today
    (``rs_colorspace``/``fix_rs_colorspace`` was the first has_fix check to
    ship WITHOUT one — a review fix closed that gap, see the final v1.38
    review) — but that is a fact about the current registry contents, not
    a guarantee this function enforces: a future ``has_fix`` check without
    a matching ``_FIX_ACTION_ID_BY_CHECK_ID`` entry gets ``fix_action_id:
    None`` and a Fix button that never enables, silently, same as
    ``rs_colorspace`` did.

    ``accepted_all`` is true when every CURRENT violation of the check is
    already baselined (``new == 0`` and ``accepted > 0``) — the row can
    still be a FAIL/WARN card (status derives from the raw legacy ``count``,
    not the baseline-aware ``new``), it just reads "0 new (N accepted)".
    Without an active baseline (``new`` is ``None``), ``accepted_all`` is
    always ``False``.

    A row with ``status`` "ok" or "disabled" is excluded from both card
    lists — the SPA renders the OK/disabled counts as a single folded line,
    not individual cards.
    """
    registry_by_id = {entry.check_id: entry for entry in CHECK_REGISTRY}
    fail, warn = [], []
    ok_count = 0
    disabled_count = 0

    for row in checks or []:
        status = row.get("status")
        if status == "disabled":
            disabled_count += 1
            continue
        if status == "ok":
            ok_count += 1
            continue

        check_id = row.get("id")
        entry = registry_by_id.get(check_id)
        actions = getattr(entry, "actions", ()) if entry else ()
        new = row.get("new")
        accepted = row.get("accepted")

        unverified = row.get("unverified_count", 0)
        card = {
            "id": check_id,
            "label": row.get("label"),
            "severity": row.get("severity"),
            "count": row.get("count"),
            "new": new,
            "accepted": accepted,
            "detail": row.get("details") or [],
            "can_select": "select" in actions,
            "can_fix": "fix" in actions and not (unverified and not row.get("count")),
            "fix_action_id": _FIX_ACTION_ID_BY_CHECK_ID.get(check_id),
            "accepted_all": bool(new == 0 and (accepted or 0) > 0 and not unverified),
        }
        if row.get("severity") == "FAIL":
            fail.append(card)
        else:
            warn.append(card)

    return {"fail": fail, "warn": warn, "ok_count": ok_count,
            "disabled_count": disabled_count}


def _delivery_version(manifest_dict):
    """Format ``original_version`` (an int or None in the manifest, see
    ui/flows.py) as the SPA's "v022"-style string, or None if unknown."""
    raw = manifest_dict.get("original_version")
    if raw is None:
        return None
    try:
        return f"v{int(raw):03d}"
    except (TypeError, ValueError):
        return None


def _delivery_qc(manifest_dict):
    """The manifest only carries a "qc" section when project rules were
    active at collect time (see ui/flows.py) — absent otherwise, never a
    KeyError."""
    qc = manifest_dict.get("qc")
    if not isinstance(qc, dict):
        return None
    return {
        "score": qc.get("score") or "",
        "passed": qc.get("passed", 0),
        "total": qc.get("total", 0),
    }


def _delivery_summary(manifest_dict):
    summary = manifest_dict.get("asset_summary")
    if not isinstance(summary, dict):
        summary = {}
    return {
        "total": summary.get("total", 0),
        "collected": summary.get("collected", 0),
        "missing": summary.get("missing", 0),
        "external": summary.get("external", 0),
    }


def _delivery_zip(manifest_dict):
    """The manifest currently never persists a "zip" section (the zip
    archive is a return value of the collect flow, not written to the
    sidecar — see ui/flows.py run_collect_pipeline). Mapped defensively in
    case a future version adds one."""
    zip_raw = manifest_dict.get("zip")
    if not isinstance(zip_raw, dict):
        return None
    path = zip_raw.get("path") or zip_raw.get("zip_path") or ""
    if not path:
        return None
    return {"path": path, "bytes": zip_raw.get("bytes", 0)}


def delivery_report_payload(manifest_dict, manifest_path):
    """Map a loaded ``sentinel_manifest.json`` dict to the exact SPA
    contract consumed by ``GET /api/report/delivery``
    (web/src/lib/api.ts + web/src/types.ts DeliveryReport).

    Pure: no c4d, no filesystem access — ``manifest_dict`` is whatever
    ``manifest.load_manifest_json`` returned, ``manifest_path`` is the path
    it was loaded from (passed through, not read from the dict). Never
    raises on a partial/legacy manifest — every field falls back to a
    sensible null/empty default instead of a KeyError.
    """
    manifest_dict = manifest_dict or {}
    notes = manifest_dict.get("notes")
    if not isinstance(notes, dict):
        notes = {}
    assets = manifest_dict.get("assets") or []

    return {
        "scene": manifest_dict.get("scene") or "",
        "collected_at": manifest_dict.get("timestamp") or "",
        "artist": manifest_dict.get("artist") or "",
        "version": _delivery_version(manifest_dict),
        "qc": _delivery_qc(manifest_dict),
        "summary": _delivery_summary(manifest_dict),
        "zip": _delivery_zip(manifest_dict),
        "assets": [_delivery_asset(entry) for entry in assets],
        "pending_todos": notes.get("pending_count", 0),
        "manifest_path": manifest_path or "",
    }


# ---------------------------------------------------------------------------
# QC report payload — qc.score.compute_score() -> SPA contract
# ---------------------------------------------------------------------------

# Cap on violation rows per check, same rationale/value as postrender.py's
# REPORT_ITEM_CAP: a runaway check (e.g. hundreds of default-named objects)
# should not blow up the payload — the row's `count` already carries the
# true total, `details` is a preview.
_QC_DETAIL_CAP = 50


def _qc_violation_detail(violation):
    """One structured violation -> the SPA's compact detail row.

    ``violation`` is a qc/results.py ``Violation.to_dict()`` shape:
    ``{"check_id", "identity", "message", "extras"?}`` where ``identity`` is
    always a JSON-safe dict built by ``object_identity``/``material_identity``/
    ``param_identity`` (path+sibling_index+guid, or name+guid, or
    param+value+...) — never a live c4d object reference. Defensive against a
    malformed/non-dict entry (never raises, never drops the row silently).
    """
    if not isinstance(violation, dict):
        return {"label": "", "message": str(violation), "extras": None}
    identity = violation.get("identity") or {}
    label = identity.get("path") or identity.get("name") or identity.get("param") or ""
    return {
        "label": label,
        "message": violation.get("message") or "",
        "extras": violation.get("extras"),
    }


def _qc_info_detail(row):
    """One ``CheckResult.metadata["info"]`` row -> the same compact
    detail-row shape ``_qc_violation_detail`` builds from a violation
    (``{"label", "message", "extras"}``) — for a check (today: v1.38's
    ``rs_colorspace``) that ships a richer non-violation Info picture
    alongside its counted violations (``checks/matgraph.py``'s
    ``check_rs_colorspace``: every verdict except the two
    ``matgraph.audit_colorspaces`` itself documents as silent —
    ``unknown``/``ok`` — including the counted ``mismatch`` entries
    themselves, so the Info button shows the check's whole picture, not
    just what counted). Defensive against a malformed/non-dict row, same
    as ``_qc_violation_detail``.

    Message wording is intentionally reason-specific (mirrors the
    per-mismatch violation message format for ``mismatch`` itself,
    human-readable prose for the other three reasons) rather than a single
    generic template — a reader scanning the Info list needs to tell
    "already fixed by Fix" (mismatch) apart from "nothing to fix here, but
    worth knowing" (the other three) at a glance.
    """
    if not isinstance(row, dict):
        return {"label": "", "message": str(row), "extras": None}
    material = row.get("material") or ""
    file_name = row.get("file") or ""
    channel = row.get("channel")
    assigned = row.get("assigned")
    reason = row.get("reason")
    if reason == "mismatch":
        message = (
            f"{material}: {file_name} is {assigned}, "
            f"{channel} expects {row.get('expected')}"
        )
    elif reason == "scan_unverified":
        message = f"{material}: material graph unverified — could not complete the scan"
    elif reason == "auto_unverified":
        message = f"{material}: {file_name} — auto, unverified"
    elif reason == "conflict":
        message = (
            f"{material}: {file_name} — conflict: name and destination "
            f"channel signals disagree"
        )
    elif reason == "foreign_cs":
        message = f"{material}: {file_name} — foreign colorspace '{assigned}'"
    elif reason:
        # Some other real (non-empty) reason string this function doesn't
        # special-case above — render it bare rather than assuming it
        # deserves the same "— <reason>" template as the four known ones.
        message = f"{material}: {file_name} — {reason}"
    else:
        # Minor 6 (final v1.38 review): a row with no ``reason`` at all
        # (missing key -> ``.get`` returns ``None``) used to fall through
        # to the same f-string as a real reason, literally rendering
        # "— None" — worse than useless, since it looks like a genuine
        # (bogus) reason string instead of "this row is missing data".
        message = f"{material}: {file_name}"
    return {"label": material, "message": message, "extras": {"reason": reason}}


def _qc_check_details(check_id, score, structured_by_check):
    """Detail rows to show for one check_id, capped at ``_QC_DETAIL_CAP``.

    ``CheckResult.metadata["info"]`` is PREFERRED, when present and
    non-empty, over the plain ``violations`` list — today only
    ``rs_colorspace`` (v1.38, QC #13) ever sets it, and its whole point is
    to show MORE than what counted (see ``_qc_info_detail``'s docstring),
    so a check that populates it must never be shown the narrower
    violations-only view instead. Every other check (no ``metadata.info``
    at all) falls through UNCHANGED to the original behavior below.

    That original behavior mirrors ``ui/dialogs.py``
    ``AssetHubDialog._new_violations_for_check`` exactly: when a baseline
    sidecar is active, prefer its "new" diff (``score["baseline_matches"]``)
    so accepted violations don't reappear; otherwise fall back to the raw
    structured violations for that check. (``rs_colorspace``'s baseline
    diffing, if a project ever accepts one of its mismatches, still keys
    off ``violations``, not ``metadata.info``: baseline identity/acceptance
    is a ``Violation`` concept the non-violation info rows never
    participate in — but that path is only reached when ``metadata.info``
    is absent/empty for this check_id, which never happens for a
    ``rs_colorspace`` result computed by ``check_rs_colorspace`` itself.)
    """
    structured = structured_by_check.get(check_id)
    metadata = (structured or {}).get("metadata") or {}
    info_rows = metadata.get("info") if isinstance(metadata, dict) else None
    if info_rows:
        return [_qc_info_detail(row) for row in info_rows[:_QC_DETAIL_CAP]]

    baseline_matches = score.get("baseline_matches")
    if baseline_matches:
        match = baseline_matches.get(check_id) or {}
        violations = match.get("new") or []
    else:
        violations = (structured or {}).get("violations") or []
    return [_qc_violation_detail(v) for v in violations[:_QC_DETAIL_CAP]]


def _qc_check_row(entry, score, structured_by_check, severity_overrides):
    check_id = entry.check_id
    disabled = check_id in (score.get("disabled") or [])
    has_baseline = "new_counts" in score
    unverified = 0 if disabled else (score.get("unverified_counts") or {}).get(check_id, 0)

    if disabled:
        count = new = accepted = None
        status = "disabled"
        details = []
    else:
        count = (score.get("counts") or {}).get(check_id, 0)
        new = (score.get("new_counts") or {}).get(check_id) if has_baseline else None
        accepted = (score.get("accepted_counts") or {}).get(check_id) if has_baseline else None
        status = "fail" if count or unverified else "ok"
        details = _qc_check_details(check_id, score, structured_by_check)

    row = {
        "id": check_id,
        "label": entry.row_label + (" — unverified" if unverified else ""),
        "severity": severity_overrides.get(check_id, entry.severity),
        "has_fix": entry.has_fix and not (unverified and not count),
        "status": status,
        "count": count,
        "new": new,
        "accepted": accepted,
        "details": details,
    }
    if unverified:
        row["unverified_count"] = unverified
    return row


def qc_report_payload(scene_name, ruleset, score, structured_by_check):
    """Map one ``run_all_checks`` + ``compute_score`` run (qc/score.py) to
    the SPA's QcReport contract (``GET/POST /api/report/qc``).

    Pure: no c4d. Callers (see ``ui/reports_dialog.py`` ``_op_report_qc``)
    must gather everything on the C4D main thread first, exactly the way
    ``ui/dialogs.py`` ``AssetHubDialog._refresh_preflight`` /
    ``ui/flows.py`` ``_build_qc_summary`` do — this function never re-derives
    scoring logic, only reshapes its output:

    - ``scene_name``: ``doc.GetDocumentName()`` (or "" for an unsaved doc).
    - ``ruleset``: ``{"name", "path", "shadowed", "severity_overrides"}`` —
      built by the caller from the ``RulesContext`` returned by
      ``rules_context.active_rules_for_doc`` (``rules_path``,
      ``shadowed_paths``, and ``params.get("check_severity", {})`` — see
      ``rules.py`` ``RulesContext`` / ``qc/registry.py`` ``entry_severity``).
      ``name`` is expected to already be a display name (e.g. the rules
      file's basename, or "defaults" when no project ruleset applies).
    - ``score``: the dict ``qc.score.compute_score`` returns, passed through
      unmodified. Already JSON-safe — every violation embedded in it
      (``baseline_matches[...]["new"/"accepted"]``) traces back to
      ``qc/results.py`` ``Violation.to_dict()``, which never stores a live
      c4d object. Legacy shape (no baseline sidecar) has
      score/pass/passed/total/counts/disabled/disabled_count; the baseline
      shape additionally has new_counts/accepted_counts/stale_counts/
      baseline_matches/baseline_status/baseline_path/schema/new/accepted/stale.
    - ``structured_by_check``: ``{check_id: CheckResult-shaped dict or None}``
      — one entry per ``CHECK_REGISTRY`` id, taken verbatim from
      ``run_all_checks``'s ``result_pair["structured_result"]`` (a
      ``CheckResult`` IS a dict — ``{"check_id", "violations", "metadata"}``
      — so this is passed through, never re-derived). ``None`` for a
      disabled check.

    Output (TS-ready — Task 2 mirrors this as ``QcReport``)::

        {
          "scene": str,
          "ruleset": {"name": str, "path": str|None, "shadowed": [str, ...]},
          "score": {"score": "9/12", "passed": int, "total": int,
                    "disabled_count": int, "baseline_status": str|None},
          "checks": [
            {"id": str, "label": str, "severity": "FAIL"|"WARN",
             "has_fix": bool, "status": "ok"|"fail"|"disabled",
             "count": int|None, "new": int|None, "accepted": int|None,
             "details": [{"label": str, "message": str, "extras": dict|None}]}
          ],
          "disabled": [str, ...],
        }

    Never raises on missing/partial input — every field defaults sensibly.
    """
    score = score or {}
    structured_by_check = structured_by_check or {}
    ruleset = ruleset or {}
    severity_overrides = ruleset.get("severity_overrides") or {}

    checks = [
        _qc_check_row(entry, score, structured_by_check, severity_overrides)
        for entry in CHECK_REGISTRY
    ]

    return {
        "scene": scene_name or "",
        "ruleset": {
            "name": ruleset.get("name") or "defaults",
            "path": ruleset.get("path"),
            "shadowed": list(ruleset.get("shadowed") or []),
        },
        "score": {
            "score": score.get("score") or "",
            "passed": score.get("passed", 0),
            "total": score.get("total", 0),
            "disabled_count": score.get("disabled_count", 0),
            "baseline_status": score.get("baseline_status"),
        },
        "checks": checks,
        "disabled": list(score.get("disabled") or []),
    }


def top_qc_checks(checks, limit=3):
    """Pure: the worst ``limit`` checks by violation count, for
    ``panel/overview``'s ``qc.top`` (see ``ui/panel_ops.py``). ``checks`` is
    the ``"checks"`` list ``qc_report_payload`` already builds — this never
    re-derives scoring, only ranks its output.

    Count preference per row: ``new`` (baseline-aware violation count) when
    present, else ``count`` (legacy violation count). ``_qc_check_row``
    populates BOTH ``count`` and ``new`` for an enabled, non-disabled check
    once a baseline is active (``count`` stays the raw legacy total,
    ``new`` is the baseline-aware subset) — ranking prefers ``new`` in that
    case so a scene with a large accepted-baseline count doesn't crowd out
    a check with few-but-unaccepted new violations. A row with no count at
    all (``None`` or ``0`` — i.e. passing or disabled) is excluded, never
    ranked as a zero-severity "worst" entry.
    """
    scored = []
    for entry in checks or []:
        count = entry.get("new")
        if count is None:
            count = entry.get("count")
        count = (count or 0) + (entry.get("unverified_count") or 0)
        if not count:
            continue
        scored.append((count, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {"check_id": entry.get("id"), "label": entry.get("label"), "count": count}
        for count, entry in scored[:limit]
    ]


# ---------------------------------------------------------------------------
# Doctor report payload — doctor.run_all_diagnostics() -> SPA contract
# ---------------------------------------------------------------------------

def _doctor_item(item):
    item = item or {}
    return {
        "id": item.get("id") or "",
        "label": item.get("label") or "",
        "status": item.get("status") or "info",
        "detail": item.get("detail") or "",
        "hint": item.get("hint") or "",
    }


def doctor_report_payload(items, meta):
    """Map ``doctor.run_all_diagnostics()``'s ``(items, meta)`` to the SPA's
    DoctorReport contract (``GET /api/report/doctor``).

    Pure: no c4d, no filesystem/network access — ``items``/``meta`` are
    whatever the doctor engine already computed. Deliberately NOT nested
    into "sections" (the plan's initial sketch): ``run_all_diagnostics``
    returns one flat item list with no natural grouping in the real engine
    (payload/settings/renderers/python/permissions checks are siblings, not
    categorized) and ``meta`` is a handful of environment strings — inventing
    a grouping here would not be grounded in what doctor.py actually
    produces. The optional, explicit-only ``check_for_update`` item (network
    call, never run automatically — see doctor.py's docstring) is out of
    scope for this read-only report op; ``report/doctor`` only surfaces the
    non-network diagnostics.

    Output (TS-ready — Task 2 mirrors this as ``DoctorReport``)::

        {
          "meta": {"sentinel_version": str, "c4d_version": str, "os": str,
                    "renderers": str, "settings_path": str},
          "items": [{"id": str, "label": str, "status": "ok"|"warn"|"fail"|"info",
                      "detail": str, "hint": str}, ...],
        }

    Never raises on missing/partial input.
    """
    meta = meta or {}
    return {
        "meta": {
            "sentinel_version": meta.get("sentinel_version") or "",
            "c4d_version": meta.get("c4d_version") or "",
            "os": meta.get("os") or "",
            "renderers": meta.get("renderers") or "",
            "settings_path": meta.get("settings_path") or "",
        },
        "items": [_doctor_item(item) for item in (items or [])],
    }


# ---------------------------------------------------------------------------
# Supervisor report payload — supervisor.scan_folder() -> SPA contract
# ---------------------------------------------------------------------------

def _supervisor_shot(shot):
    shot = shot or {}
    return {
        "base": shot.get("base") or "",
        "folder": shot.get("folder") or "",
        "version_count": shot.get("version_count", 0),
        "last_version": shot.get("last_version") or "",
        "status": shot.get("status") or "",
        "score": shot.get("score") or "",
        "qc_label": shot.get("qc_label") or "",
        "todos_total": shot.get("todos_total", 0),
        "todos_pending": shot.get("todos_pending", 0),
        "days_idle": shot.get("days_idle"),
        "last_timestamp": shot.get("last_timestamp") or "",
        "artist": shot.get("artist") or "",
        "flags": list(shot.get("flags") or []),
        "trajectory": list(shot.get("trajectory") or []),
    }


def supervisor_report_payload(shots, meta):
    """Map ``supervisor.scan_folder()``'s ``(shots, meta)`` to the SPA's
    SupervisorReport contract (``GET/POST /api/report/supervisor``).

    Pure: no c4d, no filesystem access — ``supervisor.py`` itself is already
    pure stdlib (it reads sidecars via ``sentinel.versioning``/``sentinel.notes``,
    never opens a ``.c4d``), so every field here is already JSON-safe and is
    reshaped/renamed, never re-derived. Dropped versus the raw shot dict:
    ``history_path`` (an on-disk detail, not report content), ``notes_text``
    and ``version_rows`` (redundant with ``qc_label``/``trajectory`` for a
    report view — Task 2 can reintroduce them from the same source if a page
    needs the detail).

    Output (TS-ready — Task 2 mirrors this as ``SupervisorReport``)::

        {
          "folder": str, "generated_at": str, "shot_count": int,
          "warnings": [str, ...],
          "shots": [
            {"base": str, "folder": str, "version_count": int,
             "last_version": str, "status": str, "score": str,
             "qc_label": str, "todos_total": int, "todos_pending": int,
             "days_idle": int|None, "last_timestamp": str, "artist": str,
             "flags": [str, ...],
             "trajectory": [{"from_version", "to_version", "broke": [str],
                              "recovered": [str], "no_data": bool}, ...]}
          ],
        }

    Never raises on missing/partial input.
    """
    meta = meta or {}
    return {
        "folder": meta.get("folder") or "",
        "generated_at": meta.get("generated") or "",
        "shot_count": meta.get("shot_count", 0),
        "warnings": list(meta.get("warnings") or []),
        "shots": [_supervisor_shot(shot) for shot in (shots or [])],
    }


# ---------------------------------------------------------------------------
# Render validation payload — postrender.build_report() -> SPA contract
# ---------------------------------------------------------------------------

def _render_validation_check(check_id, check):
    check = check or {}
    return {
        "id": check_id,
        "label": check.get("label") or "",
        "status": check.get("status") or "OK",
        "count": check.get("count", 0),
        "items": list(check.get("items") or []),
    }


def render_validation_payload(report, report_path):
    """Map a loaded ``<base>_sentinel_render_report.json`` dict (written by
    ``postrender.build_report`` + ``postrender.write_report_atomic``, see
    ``ui/scene_tools.py`` ``_handle_validate_render``) to the SPA's
    RenderValidationReport contract (``GET /api/report/render_validation``).

    Pure: no c4d, no filesystem access — ``report`` is whatever ``json.load``
    produced from that file, ``report_path`` is passed through (not read
    from the dict, same convention as ``delivery_report_payload``). Never
    raises on a partial/legacy report.

    Output (TS-ready — Task 2 mirrors this as ``RenderValidationReport``)::

        {
          "report_path": str, "generated_at": str, "passed": bool,
          "context": {"take_name": str, "version": str,
                       "frame_start": int|None, "frame_end": int|None,
                       "frame_mode": str},
          "summary": {"failures": int, "warnings": int, "streams": int},
          "checks": [
            {"id": str, "label": str, "status": "OK"|"FAIL"|"WARN",
             "count": int, "items": [dict, ...]}, ...
          ],
        }
    """
    report = report or {}
    context = report.get("context") or {}
    summary = report.get("summary") or {}
    checks = report.get("checks") or {}

    return {
        "report_path": report_path or "",
        "generated_at": report.get("generated_at") or "",
        "passed": bool(report.get("passed", False)),
        "context": {
            "take_name": context.get("take_name") or "",
            "version": context.get("version") or "",
            "frame_start": context.get("frame_start"),
            "frame_end": context.get("frame_end"),
            "frame_mode": context.get("frame_mode") or "",
        },
        "summary": {
            "failures": summary.get("failures", 0),
            "warnings": summary.get("warnings", 0),
            "streams": summary.get("streams", 0),
        },
        "checks": [
            _render_validation_check(check_id, check)
            for check_id, check in checks.items()
        ],
    }
