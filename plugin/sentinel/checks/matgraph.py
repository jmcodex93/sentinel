# -*- coding: utf-8 -*-
"""QC check #13 — RS Colorspace (v1.38).

Wires Tasks 1-2 (``sentinel.matgraph`` — pure engine; ``sentinel.matgraph_c4d``
— the c4d/maxon adapter, ``collect()``/``write_colorspaces()``) into the
declarative registry (``qc/registry.py``), mirroring the cache/result
conventions ``checks/render.py`` already established (v1.36.5's ordering
rule) so this check behaves exactly like every other registry entry.

Only ``mismatch`` verdicts are violations (and so counted, cached, and
baseline-acceptable). Every verdict except the two ``audit_colorspaces``
itself documents as SILENT (``unknown`` — no signal fired; ``ok`` —
compliant) rides in ``CheckResult.metadata["info"]`` — including
``mismatch`` itself — so the Info button shows the check's whole picture,
not just what didn't count; ``auto_unverified``/``conflict``/``foreign_cs``
never count towards the score, only ``mismatch`` does. See
``matgraph.audit_colorspaces`` for why those three verdicts must never be
treated as fixable findings.
"""

from sentinel.matgraph import audit_colorspaces
from sentinel.matgraph_c4d import collect
from sentinel.qc.results import (
    CheckResult,
    cached_result as _cached_result,
    param_identity,
    store_result as _store_result,
)
from sentinel.rules_context import active_rules_for_doc


def _rules_context(doc, rules_context=None):
    if rules_context is not None:
        return rules_context
    return active_rules_for_doc(doc)


def _basename(path):
    """Filename component of ``path``, cross-platform (mirrors
    ``matgraph._name_channel``'s own separator handling — never a second,
    diverging implementation of "strip the folder off a path")."""
    if not path:
        return ""
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def entries_for_audit(materials):
    """Flatten ``matgraph_c4d.collect()``'s per-material ``samplers`` list
    into ``matgraph.audit_colorspaces``'s entry shape (``material``/
    ``file``/``assigned``/``dest_port``), one entry per sampler.

    ``audit_colorspaces`` copies every input key through into its verdict
    dicts (``out = dict(entry)``) untouched, so extra bookkeeping keys
    (``material``, ``material_name``, ``node_id``) survive into the
    verdict and are what the check/fix below key off of — never
    re-derived from the material a second time.

    A material entry carrying an ``error`` (the walk itself failed) is
    skipped: auditing data known to be incomplete/wrong is exactly what
    ``clean_dead_nodes_core`` also refuses to do, for the same reason.
    """
    entries = []
    for mat_entry in materials or []:
        if mat_entry.get("error"):
            continue
        mat = mat_entry.get("material")
        name = mat_entry.get("name") or ""
        for sampler in mat_entry.get("samplers") or []:
            entries.append({
                "material": mat,
                "material_name": name,
                "node_id": sampler.get("node_id"),
                "file": _basename(sampler.get("path")),
                "assigned": sampler.get("assigned"),
                "dest_port": sampler.get("dest_port"),
            })
    return entries


def _rs_colorspace_result(legacy_items, info_rows=None):
    """Build the ``CheckResult`` from an already-computed ``legacy_items``
    list (one dict per ``mismatch`` verdict). Mirrors ``render.py``'s
    ``_output_paths_result``/``_takes_result`` shape: called with a single
    positional arg by ``cached_result``'s cache-hit rebuild path (only the
    legacy list survives that path, never the freshly-computed
    ``info_rows`` — the same "structured extras are lost on a legacy-only
    cache hit" limitation those checks already accept), and with both args
    on a fresh compute (see ``check_rs_colorspace`` below)."""
    result = CheckResult(
        check_id="rs_colorspace",
        metadata={"legacy_count": len(legacy_items), "info": info_rows or []},
        legacy_items=legacy_items,
    )
    for item in legacy_items:
        result.add_violation(
            param_identity(
                "rs_colorspace",
                item.get("file"),
                preset=item.get("material_name"),
                field=item.get("channel"),
            ),
            "{material}: {file} is {assigned}, {channel} expects {expected}".format(
                material=item.get("material_name"),
                file=item.get("file"),
                assigned=item.get("assigned"),
                channel=item.get("channel"),
                expected=item.get("expected"),
            ),
            {"node_id": item.get("node_id"), "assigned": item.get("assigned"),
             "expected": item.get("expected")},
        )
    return result


def check_rs_colorspace(doc, rules_context=None):
    """QC #13 — RS Colorspace. Cache key ``"rscs"``.

    Resolves the rules context BEFORE reading the cache (the v1.36.5
    ordering rule, replicated verbatim from ``checks/render.py``): the
    ruleset resolution is what invalidates ``check_cache`` on a ruleset
    change via ``rules_context.active_rules_for_doc``/``get_active_rules``
    — this check has no ruleset params of its own, but the ORDER still
    matters, because it is context resolution (not this check's own
    logic) that clears the cache when the project's ``sentinel_rules.json``
    changes on disk. Swapping these two lines would make this check serve
    a stale cached result across a ruleset edit like any other check would.
    """
    _rules_context(doc, rules_context)
    cached_result = _cached_result(doc, "rscs", _rs_colorspace_result)
    if cached_result is not None:
        return cached_result

    legacy_items = []
    info_rows = []
    try:
        materials = collect(doc)
        entries = entries_for_audit(materials)
        verdicts = audit_colorspaces(entries)
        for verdict in verdicts:
            reason = verdict.get("verdict")
            # "unknown" (neither signal fired) and "ok" (compliant) are the
            # two verdicts ``audit_colorspaces`` documents as SILENT by
            # design — no false positives, nothing worth an Info row for
            # either. Every other verdict (including "mismatch" itself)
            # rides in ``info`` so the Info button shows the check's full
            # picture, not just what didn't count.
            if reason == "mismatch":
                legacy_items.append({
                    "material": verdict.get("material"),
                    "material_name": verdict.get("material_name"),
                    "node_id": verdict.get("node_id"),
                    "file": verdict.get("file"),
                    "channel": verdict.get("channel"),
                    "assigned": verdict.get("assigned"),
                    "expected": verdict.get("expected"),
                })
                info_rows.append({
                    "material": verdict.get("material_name"),
                    "file": verdict.get("file"),
                    "assigned": verdict.get("assigned"),
                    "channel": verdict.get("channel"),
                    "reason": reason,
                })
            elif reason in ("auto_unverified", "conflict", "foreign_cs"):
                info_rows.append({
                    "material": verdict.get("material_name"),
                    "file": verdict.get("file"),
                    "assigned": verdict.get("assigned"),
                    "channel": verdict.get("channel"),
                    "reason": reason,
                })
    except Exception:
        legacy_items = []
        info_rows = []

    result = _rs_colorspace_result(legacy_items, info_rows)
    return _store_result(doc, "rscs", legacy_items, result)
