# -*- coding: utf-8 -*-
"""QC check #14 — UDIM Tiles (v1.43).

A mesh rendered with a UDIM/UVTILE material whose UVs sit in a tile that
has no texture on disk renders that area black, with no error and no log
line (measured, docs/research/2026-10-29-redshift-udim.md). This check
reads which tiles each object's polygons use (``udim_c4d.used_tiles``) and
compares them with the tiles of every tiled map of the material
(``udim.tile_gaps``). One violation per object, naming its materials.

Scenes without a tiled path return ``ok`` before reading any UV.
"""

from sentinel import udim
from sentinel.common.helpers import safe_print
from sentinel.qc.results import (
    CheckResult,
    cached_result as _cached_result,
    object_identity,
    store_result as _store_result,
)
from sentinel.rules_context import active_rules_for_doc
from sentinel.textures import scan_all_texture_paths
from sentinel.udim_c4d import udim_materials, used_tiles


def _name(item, fallback):
    try:
        return item.GetName() or fallback
    except Exception:
        return fallback


def violation_message(object_name, gaps):
    """``Body: tiles 1005 have no texture (LOK_cuerpo: 3 maps) — renders
    black`` — one line per object, every material with a gap in it."""
    tiles = sorted({t for gap in gaps for t in gap["missing"]})
    parts = []
    if tiles:
        parts.append("tile%s %s %s no texture (%s)" % (
            "" if len(tiles) == 1 else "s", udim.format_tiles(tiles),
            "has" if len(tiles) == 1 else "have",
            ", ".join("%s: %d map%s" % (gap["material"], len(gap["maps"]),
                                        "" if len(gap["maps"]) == 1 else "s")
                      for gap in gaps if gap["missing"])))
    if any(gap["out_of_range"] for gap in gaps):
        parts.append("UVs outside the UDIM range")
    return "%s: %s — renders black" % (object_name, "; ".join(parts))


def _udim_tiles_result(objects, details=None):
    """``CheckResult`` from the flagged objects. A legacy-only cache hit
    rebuilds without ``details`` (the same limitation ``render.py``'s checks
    accept), so its messages fall back to a generic line."""
    result = CheckResult(
        check_id="udim_tiles",
        metadata={"legacy_count": len(objects)},
        legacy_items=objects,
    )
    sibling_scan_cache = {}
    for i, obj in enumerate(objects):
        detail = (details or [None] * len(objects))[i]
        message = detail["message"] if detail else "%s: UDIM tiles without texture" % _name(obj, "object")
        result.add_violation(object_identity(obj, sibling_scan_cache), message,
                             {"materials": detail["gaps"]} if detail else None)
    return result


def check_udim_tiles(doc, rules_context=None):
    """QC #14 — UDIM Tiles. Cache key ``"udim"``. Resolves the rules
    context before reading the cache (the v1.36.5 ordering rule, see
    ``checks/matgraph.py``)."""
    if rules_context is None:
        active_rules_for_doc(doc)
    cached = _cached_result(doc, "udim", _udim_tiles_result)
    if cached is not None:
        return cached

    objects = []
    details = []
    try:
        materials = udim_materials(scan_all_texture_paths(doc))
        if materials:
            for obj, per_material in used_tiles(doc, materials):
                gaps = []
                for index, tiles in per_material.items():
                    material, maps = materials[index]
                    gap = udim.tile_gaps(tiles, maps)
                    if gap:
                        gaps.append(dict(gap, material=_name(material, "material")))
                if gaps:
                    objects.append(obj)
                    details.append({"message": violation_message(_name(obj, "object"), gaps),
                                    "gaps": gaps})
    except Exception as exc:
        safe_print("UDIM tiles check failed: %s" % exc)

    return _store_result(doc, "udim", objects, _udim_tiles_result(objects, details))
