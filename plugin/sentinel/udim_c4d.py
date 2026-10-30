# -*- coding: utf-8 -*-
"""UDIM tiles under the polygons of the scene (QC #14, v1.43) — the thin
C4D adapter over ``sentinel.udim``.

Which material a polygon renders with follows C4D's own rules: Texture Tags
apply in order and the last one wins; a tag restricted to a Polygon
Selection covers only the polygons of the selection with that name on the
mesh; tags inherited from parents sit under the object's own. Only a tag
with UVW projection reads the mesh UVs, so only those can hit a tile.

UVs are read from the UVW tag's low-level buffer (measured on 2026.304:
8 float32 per polygon, corners a–d as (u, v)), and the result per mesh is
cached on its dirty counters so an unchanged scene never re-reads them.
"""

import array

import c4d

from sentinel import udim

# Results of the last pass, keyed by (GUID, dirty counters…). Rebuilt on
# every pass with only the keys that pass used, so it never grows.
_TILE_CACHE = {}


def udim_materials(texture_records):
    """``[(material, [(map name, tiles on disk)])]`` for the materials whose
    texture records hold a UDIM/UVTILE path, from ``scan_all_texture_paths``.
    A pattern with no tile at all is skipped: QC Assets reports it missing."""
    out = []
    for rec in texture_records or []:
        path = rec.get("current_path") or ""
        if not udim.has_token(path):
            continue
        tiles = udim.list_tiles(rec.get("resolved") or path)
        if not tiles:
            continue
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        for material, maps in out:
            if material == rec.get("host"):
                if (name, tiles) not in maps:
                    maps.append((name, tiles))
                break
        else:
            out.append((rec.get("host"), [(name, tiles)]))
    return out


def unresolved_maps(texture_records):
    """``[(material, map name, reason)]`` for the tiled maps Redshift reports
    ``Not Found`` although tiles exist (``udim.redshift_unresolved`` on the
    resolved path). Patterns with no tile at all are left to QC Assets, as in
    ``udim_materials``; a map read by several samplers is listed once."""
    out = []
    for rec in texture_records or []:
        path = rec.get("current_path") or ""
        if not udim.has_token(path):
            continue
        resolved = rec.get("resolved") or path
        tiles = udim.list_tiles(resolved)
        if not tiles:
            continue
        reason = udim.redshift_unresolved(resolved, tiles)
        if not reason:
            continue
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if not any(m == rec.get("host") and n == name for m, n, _r in out):
            out.append((rec.get("host"), name, reason))
    return out


def _texture_tags(obj):
    return [tag for tag in obj.GetTags() if tag.GetType() == c4d.Ttexture]


def _material_index(materials, material):
    for i, (candidate, _maps) in enumerate(materials):
        if candidate == material:
            return i
    return None


def _cache_polygons(node):
    """Polygon objects a generator without children builds (its cache)."""
    found = []
    stack = [node.GetDeformCache() or node.GetCache()]
    while stack:
        current = stack.pop()
        while current is not None:
            deformed = current.GetDeformCache()
            if deformed is not None:
                stack.append(deformed)
            elif isinstance(current, c4d.PolygonObject):
                found.append(current)
            else:
                cache = current.GetCache()
                if cache is not None:
                    stack.append(cache)
            if current.GetDown() is not None:
                stack.append(current.GetDown())
            current = current.GetNext()
    return found


def _selection_indices(poly, name, count):
    for tag in poly.GetTags():
        if tag.GetType() == c4d.Tpolygonselection and tag.GetName() == name:
            flags = tag.GetBaseSelect().GetAll(count)
            return [i for i, on in enumerate(flags) if on]
    return []


def _polygon_tiles(poly, stack, wanted):
    """``{stack index: tiles}`` for the UVW tags of ``stack`` listed in
    ``wanted``, over the polygons each one actually wins on ``poly``."""
    count = poly.GetPolygonCount()
    owner = None  # None = every polygon still uncovered
    for index, tag in enumerate(stack):
        name = tag[c4d.TEXTURETAG_RESTRICTION] or ""
        if not name:
            owner = array.array("i", [index]) * count
            continue
        if owner is None:
            owner = array.array("i", [-1]) * count
        for i in _selection_indices(poly, name, count):
            owner[i] = index
    floats = array.array("f")
    floats.frombytes(bytes(poly.GetTag(c4d.Tuvw).GetLowlevelDataAddressR()))
    result = {}
    for index in wanted:
        if owner is None:
            continue
        hits = owner.count(index)
        if hits == 0:
            continue
        if hits == count:
            result[index] = udim.tiles_of_polygons(floats)
        else:
            result[index] = udim.tiles_of_polygons(
                floats, [i for i, o in enumerate(owner) if o == index])
    return result


def _cache_key(poly, stack, wanted):
    """The tiles depend on the mesh, its UVs and selections, the tag stack
    and which of its tags hold a UDIM material (``wanted``): relinking a
    material to or from a pattern dirties neither the mesh nor its tags."""
    uvw = poly.GetTag(c4d.Tuvw)
    selections = tuple(tag.GetDirty(c4d.DIRTYFLAGS_DATA) for tag in poly.GetTags()
                       if tag.GetType() == c4d.Tpolygonselection)
    return (poly.GetGUID(),
            poly.GetDirty(c4d.DIRTYFLAGS_DATA | c4d.DIRTYFLAGS_SELECT),
            uvw.GetDirty(c4d.DIRTYFLAGS_DATA),
            tuple(tag.GetDirty(c4d.DIRTYFLAGS_DATA) for tag in stack),
            selections,
            tuple(wanted))


def used_tiles(doc, materials):
    """``[(object, {material index: tiles})]`` — the tiles each UDIM
    material of ``materials`` (``udim_materials``) is rendered on, per
    object of the hierarchy. A generator without children (a primitive) is
    read from its cache and reported as itself. Meshes without a UVW tag
    are skipped: they have no UVs to land in a tile."""
    global _TILE_CACHE
    fresh = {}
    out = []
    stack_of = [(doc.GetFirstObject(), [])]
    while stack_of:
        obj, inherited = stack_of.pop()
        while obj is not None:
            stack = inherited + _texture_tags(obj)
            wanted = []
            for index, tag in enumerate(stack):
                if tag[c4d.TEXTURETAG_PROJECTION] != c4d.TEXTURETAG_PROJECTION_UVW:
                    continue
                if _material_index(materials, tag[c4d.TEXTURETAG_MATERIAL]) is not None:
                    wanted.append(index)
            if wanted:
                if isinstance(obj, c4d.PolygonObject):
                    polys = [obj]
                elif obj.GetDown() is None:
                    polys = _cache_polygons(obj)
                else:
                    polys = []
                per_material = {}
                for poly in polys:
                    if poly.GetTag(c4d.Tuvw) is None or not poly.GetPolygonCount():
                        continue
                    key = _cache_key(poly, stack, wanted)
                    tiles = _TILE_CACHE.get(key)
                    if tiles is None:
                        tiles = _polygon_tiles(poly, stack, wanted)
                    fresh[key] = tiles
                    for index, found in tiles.items():
                        mat = _material_index(materials, stack[index][c4d.TEXTURETAG_MATERIAL])
                        if mat is not None:
                            per_material.setdefault(mat, set()).update(found)
                if per_material:
                    out.append((obj, per_material))
            if obj.GetDown() is not None:
                stack_of.append((obj.GetDown(), stack))
            obj = obj.GetNext()
    _TILE_CACHE = fresh
    return out
