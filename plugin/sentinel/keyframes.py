# -*- coding: utf-8 -*-
"""Keyframe offset / stagger engine (v1.30 Tools quick-wins).

Planning helpers (:func:`collect_shift_set`, :func:`stagger_plan`) are pure.
The shift itself is c4d-bound but written against duck-typed tracks/curves so
the pytest fakes exercise the REAL iteration-order logic: shifting keys later
in time must walk indexes in REVERSE (a moved key would otherwise collide
with / reorder past its right neighbor inside CCurve); earlier in time walks
forward. Callers of :func:`shift_object_tracks` own the undo block;
:func:`run_offset` / :func:`run_stagger` are the op-facing wrappers that own
undo + selection + validation (dialog-free, status dicts only).
"""

try:
    import c4d
except ImportError:  # pragma: no cover - pure-test path
    c4d = None

MAX_ABS_FRAMES = 10000


def collect_shift_set(roots, children_of):
    """Order-preserving, hierarchy-deduped worklist: each root followed by
    its descendants (depth-first); an object reached twice (a selected child
    of a selected parent) appears once — it must never double-shift."""
    seen = set()
    out = []

    def _add(obj):
        marker = id(obj)
        if marker in seen:
            return
        seen.add(marker)
        out.append(obj)
        for child in children_of(obj) or []:
            _add(child)

    for root in roots or []:
        _add(root)
    return out


def stagger_plan(roots, frames):
    """[(root, offset)] — root i shifted i*frames; first root stays put."""
    return [(root, index * int(frames)) for index, root in enumerate(roots or [])]


def _frames_to_time(frames, fps):
    return c4d.BaseTime(int(frames), int(fps) or 30)


def _add_time(time_value, delta):
    return time_value + delta


def shift_object_tracks(doc, objs, frames):
    """Shift every key of every CTrack of ``objs`` by ``frames`` frames.
    Caller owns the undo block. Returns ``{"objects": N, "keys": M}`` where
    N counts objects that actually had keys."""
    frames = int(frames)
    fps = doc.GetFps()
    delta = _frames_to_time(frames, fps)
    objects_with_keys = 0
    total_keys = 0
    for obj in objs or []:
        obj_keys = 0
        for track in obj.GetCTracks() or []:
            curve = track.GetCurve()
            if curve is None:
                continue
            count = curve.GetKeyCount()
            if not count:
                continue
            try:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, track)
            except Exception:
                pass
            indexes = range(count - 1, -1, -1) if frames > 0 else range(count)
            for i in indexes:
                key = curve.GetKey(i)
                if key is None:
                    continue
                key.SetTime(curve, _add_time(key.GetTime(), delta))
                obj_keys += 1
        if obj_keys:
            objects_with_keys += 1
            total_keys += obj_keys
    return {"objects": objects_with_keys, "keys": total_keys}


def _children_of(obj):
    out = []
    child = obj.GetDown()
    while child:
        out.append(child)
        child = child.GetNext()
    return out


def _get_up(obj):
    try:
        return obj.GetUp()
    except Exception:
        return None


def _validated_frames(frames):
    try:
        frames = int(frames)
    except Exception:
        return None
    if frames == 0 or abs(frames) > MAX_ABS_FRAMES:
        return None
    return frames


def _selection_roots(doc):
    """Selected objects in Object Manager order (GETACTIVEOBJECTFLAGS_0)."""
    try:
        return doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_0) or []
    except Exception:
        return []


def run_offset(doc, frames):
    """Op-facing: shift the whole selection (+ children, deduped) by N."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    frames = _validated_frames(frames)
    if frames is None:
        return {"ok": False, "error": "bad_frames"}
    roots = _selection_roots(doc)
    if not roots:
        return {"ok": False, "error": "no_selection"}
    doc.StartUndo()
    try:
        result = shift_object_tracks(doc, collect_shift_set(roots, _children_of), frames)
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd(c4d.EVENT_ANIMATE)
        except Exception:
            pass
    if not result["keys"]:
        return {"ok": False, "error": "no_keys"}
    return {"ok": True, "objects": result["objects"], "keys": result["keys"], "frames": frames}


def run_stagger(doc, frames):
    """Op-facing: root i of the selection (OM order) shifted i*frames, its
    children inheriting the root's offset (they don't stagger among
    themselves). Root 0 stays put by design (offset 0)."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    frames = _validated_frames(frames)
    if frames is None:
        return {"ok": False, "error": "bad_frames"}
    roots = _selection_roots(doc)
    if not roots:
        return {"ok": False, "error": "no_selection"}
    # Dedupe NESTED selected roots, order-independently: a selected child of
    # a selected root belongs to the parent's family (it must not get its
    # own rung). Membership is checked against the FULL selected-id set (not
    # a forward-only scan of previously-seen roots), so selection order
    # (e.g. child listed before its parent) can't leak an extra rung.
    selected_ids = {id(r) for r in roots}
    seen_ids = set()
    top_roots = []
    for root in roots:
        marker = id(root)
        if marker in seen_ids:
            continue  # literal duplicate entry in the selection
        seen_ids.add(marker)
        ancestor = _get_up(root)
        is_top = True
        while ancestor is not None:
            if id(ancestor) in selected_ids:
                is_top = False
                break
            ancestor = _get_up(ancestor)
        if is_top:
            top_roots.append(root)
    # Gate AFTER dedup: two raw selected roots that collapse into one family
    # (e.g. a root + its own child) must report the same honest "need_two"
    # as selecting a single object, not a misleading "no_keys".
    if len(top_roots) < 2:
        return {"ok": False, "error": "need_two"}
    doc.StartUndo()
    total_objects = 0
    total_keys = 0
    try:
        for root, offset in stagger_plan(top_roots, frames):
            if offset == 0:
                continue
            result = shift_object_tracks(
                doc, collect_shift_set([root], _children_of), offset)
            total_objects += result["objects"]
            total_keys += result["keys"]
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd(c4d.EVENT_ANIMATE)
        except Exception:
            pass
    if not total_keys:
        return {"ok": False, "error": "no_keys"}
    return {"ok": True, "objects": total_objects, "keys": total_keys, "frames": frames}
