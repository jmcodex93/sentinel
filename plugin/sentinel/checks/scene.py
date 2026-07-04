# -*- coding: utf-8 -*-
"""Scene-level QC checks with structured result values."""

import c4d

from sentinel.common.cache import check_cache
from sentinel.common.constants import MAX_OBJECTS_PER_CHECK
from sentinel.common.helpers import _any_ancestor_named, _iter_objs, safe_print
from sentinel.qc.results import (
    CheckResult,
    cached_result as _cached_result,
    legacy_items,
    material_identity,
    object_identity,
    store_result as _store_result,
)
from sentinel.rules import get_active_rules


def _object_result(check_id, legacy_items_value, message, extras_builder=None):
    result = CheckResult(
        check_id=check_id,
        metadata={"legacy_count": len(legacy_items_value)},
        legacy_items=legacy_items_value,
    )
    for item in legacy_items_value:
        extras = extras_builder(item) if extras_builder else None
        result.add_violation(object_identity(item), message, extras)
    return result


def _material_result(check_id, legacy_items_value, message):
    result = CheckResult(
        check_id=check_id,
        metadata={"legacy_count": len(legacy_items_value)},
        legacy_items=legacy_items_value,
    )
    for item in legacy_items_value:
        result.add_violation(material_identity(item), message)
    return result


# ---------------- lights (optimized) ----------------
RS_LIGHT_ID = 1036751  # Redshift Light
C4D_LIGHT_ID = c4d.Olight
LIGHT_TYPE_CACHE = {}  # Cache light type checks


def _is_light_obj(op):
    """Optimized light detection with caching"""
    if not op:
        return False

    op_id = op.GetType()

    # Check cache first
    if op_id in LIGHT_TYPE_CACHE:
        return LIGHT_TYPE_CACHE[op_id]

    is_light = False

    try:
        # Fast checks first
        if op_id == C4D_LIGHT_ID or op_id == RS_LIGHT_ID:
            is_light = True
        elif op.CheckType(C4D_LIGHT_ID):
            is_light = True
        else:
            # Additional Redshift light types
            if op_id in (1036754, 1038653, 1036950, 1034355, 1036753):  # RS lights
                is_light = True
            else:
                # Slow check last
                tn = (op.GetTypeName() or "").lower()
                if "light" in tn:
                    is_light = True
    except Exception:
        pass

    # Cache result
    LIGHT_TYPE_CACHE[op_id] = is_light
    return is_light


def _lights_result(offenders):
    return _object_result(
        "lights",
        offenders,
        "Light is outside a light, lights, or lighting group",
    )


def check_lights(doc):
    """Check for lights outside proper containers - accepts 'light', 'lights', or 'lighting'"""
    cached_result = _cached_result(doc, "lights", _lights_result)
    if cached_result is not None:
        return cached_result

    offenders = []
    names = {"light", "lights", "lighting"}
    first = doc.GetFirstObject()

    if not first:
        return _store_result(doc, "lights", offenders, _lights_result(offenders))

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            if not _is_light_obj(o):
                continue

            if _any_ancestor_named(o, names):
                continue

            offenders.append(o)

            # Early exit if too many issues
            if len(offenders) > 50:
                safe_print(f"Too many light issues found ({len(offenders)}+), stopping check")
                break

    except Exception as e:
        safe_print(f"Error checking lights: {e}")

    return _store_result(doc, "lights", offenders, _lights_result(offenders))


# ---------------- visibility traps (optimized) ----------------
def _visibility_traps_result(traps):
    return _object_result(
        "visibility_traps",
        traps,
        "Object has inconsistent viewport/render visibility",
    )


def check_visibility_traps(doc):
    """Check for visibility inconsistencies between viewport and render"""
    cached_result = _cached_result(doc, "vis", _visibility_traps_result)
    if cached_result is not None:
        return cached_result

    traps = []
    first = doc.GetFirstObject()

    if not first:
        return _store_result(doc, "vis", traps, _visibility_traps_result(traps))

    def ed(o):
        try:
            return o[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR]
        except Exception:
            return c4d.OBJECT_ON

    def rd(o):
        try:
            return o[c4d.ID_BASEOBJECT_VISIBILITY_RENDER]
        except Exception:
            return c4d.OBJECT_ON

    try:
        # Performance optimization: Use persistent ancestor visibility cache
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                obj_id = id(o)
                ed_vis = ed(o)
                rd_vis = rd(o)

                # Check direct visibility trap
                if ed_vis == c4d.OBJECT_OFF and rd_vis != c4d.OBJECT_OFF:
                    traps.append(o)
                    continue

                # Check ancestor visibility using persistent cache
                p = o.GetUp()
                if p:
                    # Try persistent cache first
                    cached_vis = check_cache.get_ancestor_visibility(p)

                    if cached_vis is not None:
                        ancE, ancR = cached_vis
                    else:
                        # Calculate ancestor visibility and cache it
                        ancE = False
                        ancR = False
                        temp_p = p
                        depth = 0

                        while temp_p and depth < 50:
                            if ed(temp_p) == c4d.OBJECT_OFF:
                                ancE = True
                            if rd(temp_p) == c4d.OBJECT_OFF:
                                ancR = True
                            temp_p = temp_p.GetUp()
                            depth += 1

                        # Store in persistent cache for reuse across timer ticks
                        check_cache.set_ancestor_visibility(p, (ancE, ancR))

                    if (ancE and ed_vis == c4d.OBJECT_ON) or (ancR and rd_vis == c4d.OBJECT_ON):
                        traps.append(o)

                # Early exit
                if len(traps) > 50:
                    safe_print(f"Too many visibility issues ({len(traps)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking visibility: {e}")

    return _store_result(doc, "vis", traps, _visibility_traps_result(traps))


# ---------------- keyframe sanity (optimized) ----------------
def _keys_result(offenders):
    return _object_result(
        "keys",
        offenders,
        "Object has multi-axis position or rotation keyframes",
    )


def check_keys(doc):
    """Check for multi-axis position/rotation keyframes"""
    cached_result = _cached_result(doc, "keys", _keys_result)
    if cached_result is not None:
        return cached_result

    offenders = []
    first = doc.GetFirstObject()

    if not first:
        return _store_result(doc, "keys", offenders, _keys_result(offenders))

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                tracks = o.GetCTracks()
                if not tracks:
                    continue

                pos_axes = set()
                rot_axes = set()

                for tr in tracks:
                    try:
                        did = tr.GetDescriptionID()
                        if not did or did.GetDepth() < 1:
                            continue

                        first_id = did[0].id

                        if first_id == c4d.ID_BASEOBJECT_POSITION:
                            if did.GetDepth() >= 2:
                                pos_axes.add(did[1].id)
                        elif first_id == c4d.ID_BASEOBJECT_ROTATION:
                            if did.GetDepth() >= 2:
                                rot_axes.add(did[1].id)
                    except Exception:
                        continue

                if len(pos_axes) > 1 or len(rot_axes) > 1:
                    offenders.append(o)

                # Early exit
                if len(offenders) > 50:
                    safe_print(f"Too many keyframe issues ({len(offenders)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking keyframes: {e}")

    return _store_result(doc, "keys", offenders, _keys_result(offenders))


# ---------------- camera shift (optimized) ----------------
RS_CAMERA_ID = 1057516


def _camera_shift_values(o):
    """Get camera shift values"""
    if not o:
        return 0.0, 0.0
    try:
        x = float(o[c4d.CAMERAOBJECT_FILM_OFFSET_X] or 0.0)
        y = float(o[c4d.CAMERAOBJECT_FILM_OFFSET_Y] or 0.0)
        return x, y
    except Exception:
        return 0.0, 0.0


def _camera_shift_result(bad):
    return _object_result(
        "camera_shift",
        bad,
        "Camera has non-zero film offset",
        lambda item: {
            "film_offset_x": _camera_shift_values(item)[0],
            "film_offset_y": _camera_shift_values(item)[1],
        },
    )


def check_camera_shift(doc):
    """Check for cameras with non-zero shift"""
    cached_result = _cached_result(doc, "cam", _camera_shift_result)
    if cached_result is not None:
        return cached_result

    bad = []
    first = doc.GetFirstObject()

    if not first:
        return _store_result(doc, "cam", bad, _camera_shift_result(bad))

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                # Quick type check
                obj_type = o.GetType()
                if obj_type != c4d.Ocamera and obj_type != RS_CAMERA_ID:
                    continue

                x, y = _camera_shift_values(o)
                if abs(x) > 1e-6 or abs(y) > 1e-6:
                    bad.append(o)

                # Early exit
                if len(bad) > 20:
                    safe_print(f"Too many camera shift issues ({len(bad)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking camera shift: {e}")

    return _store_result(doc, "cam", bad, _camera_shift_result(bad))


# ---------------- unused materials ----------------
def _unused_materials_result(unused):
    return _material_result(
        "unused_materials",
        unused,
        "Material is not assigned to any object",
    )


def check_unused_materials(doc):
    """Check for materials not assigned to any object via any tag type"""
    cached_result = _cached_result(doc, "unused_mats", _unused_materials_result)
    if cached_result is not None:
        return cached_result

    unused = []
    try:
        materials = doc.GetMaterials()
        if not materials:
            return _store_result(doc, "unused_mats", unused, _unused_materials_result(unused))

        # Collect all materials referenced by ANY tag on ANY object
        used_mats = set()
        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                for tag in obj.GetTags():
                    # Check texture tags (standard material assignment)
                    if tag.GetType() == c4d.Ttexture:
                        mat = tag[c4d.TEXTURETAG_MATERIAL]
                        if mat:
                            used_mats.add(mat.GetName())
                    # Check any tag that might link a material
                    try:
                        bc = tag.GetDataInstance()
                        if bc:
                            for desc_id, _ in bc:
                                link = bc.GetLink(desc_id, doc)
                                if link and link.IsInstanceOf(c4d.Mbase):
                                    used_mats.add(link.GetName())
                    except Exception:
                        pass

        # Also check materials referenced by other materials (multi/blend materials)
        for mat in materials:
            try:
                shader = mat.GetFirstShader()
                while shader:
                    try:
                        bc = shader.GetDataInstance()
                        if bc:
                            for desc_id, _ in bc:
                                link = bc.GetLink(desc_id, doc)
                                if link and link.IsInstanceOf(c4d.Mbase):
                                    used_mats.add(link.GetName())
                    except Exception:
                        pass
                    shader = shader.GetNext()
            except Exception:
                pass

        for mat in materials:
            if mat.GetName() not in used_mats:
                unused.append(mat)

    except Exception as e:
        safe_print(f"Error checking unused materials: {e}")

    return _store_result(doc, "unused_mats", unused, _unused_materials_result(unused))


# ---------------- default naming ----------------
# Common default object names that indicate unorganized scenes
_DEFAULT_NAMES = {
    "null", "cube", "sphere", "cylinder", "cone", "plane", "disc", "torus",
    "capsule", "oil tank", "platonic", "pyramid", "gem", "tube", "landscape",
    "figure", "spline", "circle", "rectangle", "n-side", "arc", "helix",
    "sweep", "extrude", "lathe", "loft", "boole", "symmetry", "instance",
    "cloner", "fracture", "voronoi fracture", "matrix", "mograph",
    "camera", "light", "floor", "sky", "environment", "physical sky",
}


def _doc_path_for_rules(doc):
    try:
        return doc.GetDocumentPath() or ""
    except Exception:
        return ""


def check_default_names(doc, rules_context=None):
    """Check for objects with default/generic names (Cube, Null, Sphere.1, etc.)"""
    if rules_context is None:
        rules_context = get_active_rules(_doc_path_for_rules(doc))
    cached_result = _cached_result(doc, "names", _default_names_result)
    if cached_result is not None:
        return cached_result

    default_names = {
        str(name).strip().lower()
        for name in rules_context.params.get("default_names", _DEFAULT_NAMES)
        if str(name).strip()
    }

    offenders = []
    first = doc.GetFirstObject()
    if not first:
        return _store_result(doc, "names", offenders, _default_names_result(offenders))

    try:
        for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not obj:
                continue
            name = (obj.GetName() or "").strip()
            if not name:
                offenders.append(obj)
                continue

            # Strip trailing ".N" suffix (e.g., "Cube.1", "Null.23")
            base = name.rsplit(".", 1)[0].strip().lower() if "." in name else name.lower()

            if base in default_names:
                offenders.append(obj)

            if len(offenders) > 50:
                break

    except Exception as e:
        safe_print(f"Error checking default names: {e}")

    return _store_result(doc, "names", offenders, _default_names_result(offenders))


def _default_names_result(offenders):
    return _object_result(
        "default_names",
        offenders,
        "Object has a default or generic name",
        lambda item: {"name": item.GetName() if item else ""},
    )
