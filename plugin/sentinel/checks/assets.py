# -*- coding: utf-8 -*-
"""Asset and texture QC check wrappers."""

from sentinel.common.cache import check_cache
from sentinel.common.helpers import safe_print
from sentinel.qc.results import CheckResult, structured_cache_key
from sentinel.textures import scan_all_texture_paths

def _texture_issue_from_record(record):
    status = record.get("status")
    if status not in ("absolute", "missing"):
        return None

    # Reconstruct the legacy `source` label
    host_name = record.get("host_name") or "<unknown>"
    stype = record.get("source_type") or ""
    if stype == "classic_shader":
        source = f"Shader in '{host_name}'"
    elif stype == "octane_shader":
        source = f"Octane in '{host_name}'"
    elif stype == "object_shader":
        source = f"Sky/Light shader on '{host_name}'"
    elif stype == "object_oct_shader":
        source = f"Octane shader on '{host_name}'"
    elif stype == "tag_shader":
        source = f"Tag shader on '{host_name}'"
    elif stype == "tag_oct_shader":
        source = f"Octane env tag on '{host_name}'"
    elif stype == "bc_param":
        source = f"Material '{host_name}'"
    elif stype == "object_bc":
        source = f"Object '{host_name}'"
    elif stype == "rs_object_fileref":
        source = f"RS Object '{host_name}'"
    elif stype in ("rs_node", "arnold_node"):
        renderer = {
            "rs_node":     "RS Node",
            "arnold_node": "Arnold Node",
        }[stype]
        source = f"{renderer} in '{host_name}'"
    elif stype == "alembic":
        source = f"Alembic '{host_name}'"
    else:
        source = host_name

    return {
        "legacy": {
            "source": source,
            "path": record.get("current_path", ""),
            "issue": status,
            "resolved": record.get("resolved"),
        },
        "identity": {
            "type": "texture_path",
            "owner_name": host_name,
            "path": record.get("current_path", ""),
            "issue": status,
        },
        "extras": {
            "source": source,
            "path": record.get("current_path", ""),
            "issue": status,
            "resolved": record.get("resolved"),
            "source_type": stype,
            "channel": record.get("channel"),
        },
    }


def _textures_result(issue_items):
    legacy_issues = [item["legacy"] for item in issue_items]
    result = CheckResult(
        "textures",
        metadata={"legacy_count": len(legacy_issues)},
        legacy_items=legacy_issues,
    )
    for item in issue_items:
        issue = item["legacy"]["issue"]
        result.add_violation(
            item["identity"],
            f"Texture path is {issue}",
            item["extras"],
        )
    return result


def check_textures_unified_structured(doc):
    """QC #6 structured result wrapper around scan_all_texture_paths."""
    cached = check_cache.get(doc, structured_cache_key("textures"))
    if cached is not None:
        return cached

    issue_items = []
    try:
        records = scan_all_texture_paths(doc)
        for record in records:
            issue_item = _texture_issue_from_record(record)
            if issue_item is None:
                continue
            issue_items.append(issue_item)
            if len(issue_items) >= 50:
                break
    except Exception as e:
        safe_print(f"Error in unified texture check: {e}")

    result = _textures_result(issue_items)
    check_cache.set(doc, "textures", result.to_legacy())
    check_cache.set(doc, structured_cache_key("textures"), result)
    return result


def check_textures_unified(doc):
    """QC #6 wrapper: returns the legacy-shaped issue list (kept for
    backwards-compat with the panel's existing render code). Internally
    delegates to `scan_all_texture_paths` and filters to only the
    problematic statuses.

    Legacy record shape:
        {"source": str, "path": str, "issue": "absolute" | "missing",
         "resolved": str | None}
    """
    cached = check_cache.get(doc, "textures")
    if cached is not None:
        return cached

    return check_textures_unified_structured(doc).to_legacy()
