# -*- coding: utf-8 -*-
"""Pure engine for Sentinel Pin: traversal order, location keys and restore
planning. Never imports c4d — everything here is decidable without a scene,
so it is tested directly.

The location key is the ONLY way a restore re-pairs a stored state with a
live object. It cannot be a C4D id: neither GetGUID() nor
FindUniqueID(MAXON_CREATOR_ID) survives saving and reloading a document
(measured 2026-07-31; the same fact caused the baseline bug fixed in
v1.34.1). So the key is positional, with the weaknesses that implies —
renaming breaks the pairing, and renumbering same-named siblings can pair
the wrong one. That is why every restore REPORTS what it matched instead of
assuming it went well."""

#: Artist-visible slots. Six covers the most demanding real case (a camera
#: set: wide/mid/close/top/side/hero) and past that nobody remembers what
#: they stored. A fixed count also forces a decision about what to
#: overwrite, which beats hoarding unnamed states.
MAX_SLOTS = 6

#: The seventh slot, written by the tool on every restore — never by the
#: artist. The real fear when restoring is losing what you have RIGHT NOW,
#: which you hadn't stored because you were only going to try something for
#: a second. Cmd+Z covers that only if nothing else happens afterwards, and
#: something always happens afterwards.
RESERVED_SLOT = 6


def location_keys(root):
    """Depth-first keys for a subtree, relative to ``root`` itself.

    ``root`` is ``{"name": str, "geometry": bool, "children": [...]}``. The
    root's own key is ``""``: keys are relative to the PINNED object, not to
    the scene, so moving the whole rig elsewhere keeps its pins valid.

    Same-named siblings get ``name[i]`` in traversal order — the only way to
    tell them apart without an id."""
    keys = []

    def walk(node, prefix):
        keys.append(prefix)
        counts = {}
        for child in node.get("children") or []:
            counts[child.get("name")] = counts.get(child.get("name"), 0) + 1
        seen = {}
        for child in node.get("children") or []:
            name = child.get("name") or ""
            if counts.get(name, 0) > 1:
                index = seen.get(name, 0)
                seen[name] = index + 1
                part = "%s[%d]" % (name, index)
            else:
                part = name
            walk(child, part if not prefix else prefix + "/" + part)

    walk(root, "")
    return keys


def plan_restore(pinned_keys, current_keys):
    """Split a stored pin against the subtree as it is NOW.

    ``matched`` keeps the pin's order (the order the writer will apply in),
    ``missing`` is what the pin knew and the scene no longer has, ``extra``
    is what appeared since. Restore touches only ``matched``: it never
    creates the missing nor removes the extra."""
    current = set(current_keys or [])
    pinned = list(pinned_keys or [])
    pinned_set = set(pinned)
    return {
        "matched": [key for key in pinned if key in current],
        "missing": [key for key in pinned if key not in current],
        "extra": [key for key in (current_keys or []) if key not in pinned_set],
    }


def slot_summary(slot):
    """What a slot's row shows. ``has_geometry`` drives the honest
    "geometry not included" note: points and polygons live outside the
    object's container, so a pinned polygon object comes back with its
    parameters and its transform but not its modelling."""
    if not slot:
        return {"filled": False, "label": "", "count": 0, "has_geometry": False}
    entries = slot.get("entries") or []
    return {
        "filled": True,
        "label": slot.get("label") or "",
        "count": len(entries),
        "has_geometry": any(entry.get("geometry") for entry in entries),
    }
