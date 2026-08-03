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

#: Nombre del tag que la herramienta gestiona sola: el estado de ANTES de
#: cada restauración. El artista nunca lo crea ni lo nombra. Reemplaza al
#: "reserved slot" del modelo de grid — en el modelo un-tag-por-pin ese
#: estado de seguridad es simplemente otro tag, distinguido por nombre en
#: vez de por índice.
SAFETY_PIN_NAME = "↩ Antes de restaurar"


def _escape_name_for_key(name):
    """A name is artist-controlled text — it can contain the very
    characters the key format itself uses to mean something (``/`` for
    nesting, ``[`` for the index suffix). Left unescaped, an object literally
    named ``a/b`` would be indistinguishable from a child ``b`` of a parent
    ``a``, and an object named ``Cube[0]`` would collide with the auto-index
    of an unrelated ``Cube``. Backslash is escaped FIRST so escaping itself
    doesn't introduce a fresh collision opportunity."""
    name = name or ""
    return name.replace("\\", "\\\\").replace("/", "\\/").replace("[", "\\[")


def location_keys(root):
    """Depth-first keys for a subtree, relative to ``root`` itself.

    ``root`` is ``{"name": str, "geometry": bool, "children": [...]}``. The
    root's own key is ``""``: keys are relative to the PINNED object, not to
    the scene, so moving the whole rig elsewhere keeps its pins valid.

    Every child segment is ``escaped_name[i]``, where ``i`` is the index
    among siblings that share that escaped name — UNCONDITIONALLY, not only
    for actual duplicates. Two things depend on that: (1) escaping alone
    isn't enough to avoid collisions (an object named ``Cube[0]`` next to two
    plain ``Cube`` siblings needs its own index too, or the escaped name and
    the auto-index syntax still collide), and (2) indexing only when a
    duplicate shows up made every existing pin unstable — a lone ``ctrl``
    keyed as bare ``ctrl``, and the moment a second ``ctrl`` appeared the
    first one silently renamed itself to ``ctrl[0]``. Indexing always keeps
    ``ctrl[0]`` stable whether or not a sibling ever joins it."""
    keys = []

    def walk(node, prefix):
        keys.append(prefix)
        seen = {}
        for child in node.get("children") or []:
            escaped = _escape_name_for_key(child.get("name"))
            index = seen.get(escaped, 0)
            seen[escaped] = index + 1
            part = "%s[%d]" % (escaped, index)
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


def pin_summary(pin):
    """Lo que muestra la fila de estado del tag.

    ``has_geometry`` y ``has_keyframes`` existen por la misma razón: son las
    dos cosas que el pin NO captura, y callarlas convierte una restauración
    en un no-op que el artista descubre tarde. Desde la Tarea 6,
    ``has_keyframes`` ya NO significa "hay algo animado" — significa "hay
    animación que este pin NO pudo capturar" (categoría CTRACK_CATEGORY_DATA
    /PLUGIN, o un pin de una build anterior a esta) — las pistas VALUE sí se
    capturan y restauran de verdad, así que ya no son un no-op silencioso."""
    if not pin:
        return {"filled": False, "label": "", "count": 0,
                "has_geometry": False, "has_keyframes": False,
                "tracks_captured": 0, "tracks_skipped": 0}
    entries = pin.get("entries") or []
    tracks_captured = sum(int(e.get("tracks_captured") or 0) for e in entries)
    tracks_skipped = sum(int(e.get("tracks_skipped") or 0) for e in entries)
    return {
        "filled": True,
        "label": pin.get("label") or "",
        "count": len(entries),
        "has_geometry": any(e.get("geometry") for e in entries),
        "has_keyframes": tracks_skipped > 0,
        "tracks_captured": tracks_captured,
        "tracks_skipped": tracks_skipped,
    }


# --- Animation tracks (Task 6) -----------------------------------------
#
# Measured in the Task 6 spike (docs/research/2026-07-31-pin-storage-spike.md
# §6): serialising a CTrack node is not a route Python exposes at all
# (TagData.Read/Write aren't bound, HyperFile.WriteObject doesn't exist,
# BaseContainer.SetData rejects raw bytes, and CTrack.GetClone() returns a
# NODE — a container can't hold one). The only route is writing each key's
# fields into nested containers by hand, which only works for
# CTRACK_CATEGORY_VALUE tracks (simple scalar keys) — CTRACK_CATEGORY_DATA
# and _PLUGIN (PLA, morphs, sound, third-party) have a different structure
# entirely and are out of scope. This module never imports c4d, so the
# category is passed in already normalized to one of the two strings below
# — the c4d-side adapter (pin_tag.py) does the classifying.

#: A CTrack whose GetTrackCategory() the writer can actually store/restore.
TRACK_CATEGORY_VALUE = "value"
#: Everything else (CTRACK_CATEGORY_DATA / _PLUGIN) — captured is impossible,
#: so it must be COUNTED and REPORTED, never silently dropped.
TRACK_CATEGORY_OTHER = "other"


def is_captured_track_category(category):
    """Whether a (normalized) track category is one this tool can actually
    store and restore key-by-key. The single source of truth for "in scope"
    — pin_tag.py must never re-decide this on its own."""
    return category == TRACK_CATEGORY_VALUE


def tag_owner_key(tag_type, tag_name, index):
    """The ``owner`` half of a ``track_key`` for a track that lives on a
    TAG: ``"tag[<type>:<escaped name>:<index>]"``, where ``index`` counts
    only among the tags sharing that same (type, escaped name) pair.

    Why the NAME and not an id — MEASURED LIVE (C4D 2026.303): a tag has
    no durable native identity at all. ``GetGUID()`` is ``BaseObject``
    API and does not exist on a tag; ``FindUniqueID(MAXON_CREATOR_ID)``
    is unique among live tags but is REGENERATED by save+reload (compared
    as hex: ``…857c625c…`` -> ``…9c7d625c…`` — and note the probe trap:
    ``FindUniqueID`` returns a ``memoryview``, so ``str(...)`` compares
    the address of a temporary buffer and makes two different tags look
    identical; ``bytes(...).hex()`` is the comparison that means
    anything). ``GetName()`` survives. So, exactly as for objects, the
    most durable identity available is type + name + position among
    homonyms.

    The name goes through ``_escape_name_for_key`` — the SAME escaper
    ``location_keys`` uses, never a second one — because a tag name is
    artist text and can contain the characters the key format itself
    uses. And the index is written UNCONDITIONALLY, for the same reason
    as in ``location_keys``: indexing only once a homonym appears makes a
    lone tag's key rewrite itself the moment a second tag takes its name,
    silently invalidating every pin written before that.

    Worth recording so nobody re-derives it: the unconditional index is
    ALSO what makes this format injective on its own — it terminates the
    string, so the last ``:`` always splits name from index whatever the
    name contains — which means the escaping above is consistency with
    ``location_keys`` and insurance against a format change, not the
    thing keeping collisions out today (measured by mutation: dropping
    the escaper does not produce a colliding pair here)."""
    return "tag[%d:%s:%d]" % (
        int(tag_type), _escape_name_for_key(tag_name), int(index))


def track_key(owner, desc_id_parts):
    """Positional identity for ONE CTrack within a node, re-pairing a
    stored track with a live one the same way ``location_keys`` re-pairs
    OBJECTS: never a C4D id (neither GetGUID() nor
    FindUniqueID(MAXON_CREATOR_ID) survives save/reload — see the module
    docstring), but WHERE the track lives plus WHICH parameter it animates.

    ``owner`` is ``""`` for a track on the node itself, or whatever
    ``tag_owner_key`` builds — ``"tag[<type>:<escaped name>:N]"`` — for a
    track that lives on a TAG: type and name first, and only then the
    position among the tags that share BOTH. Position is still in there
    because same-type same-named tags are genuinely indistinguishable,
    the same residual weakness ``location_keys`` accepts for same-named
    siblings — but it is now the LAST discriminator instead of the only
    one. Unlike a MISSING key (which ``plan_restore`` puts in its
    ``missing`` bucket and a restore reports honestly), a mis-pair is
    INVISIBLE to ``plan_restore``: two different tags whose track happens
    to produce the same string key look like a correct match, get applied,
    and the report reads exactly like a real success — applied and
    reported as success, not flagged, because nothing about that
    duplicate-key situation looks abnormal from inside ``plan_restore``.

    This is not merely theoretical. Four causes were reproduced, three
    closed by what the key carries, one residual and accepted:

    - Sentinel Pin tags themselves shift every OTHER tag's flat position
      by creating/removing a pin (``MakeTag`` prepends, measured live) —
      closed by excluding Sentinel Pin tags from the index entirely
      (``pin_tag.py``'s ``_iter_node_tracks``).
    - Deleting an ordinary tag that sat BEFORE the animated ones (e.g. a
      Phong tag) shifted every later tag's flat position — closed by
      keying on (type, position-within-type) instead of a flat position
      among all tags.
    - Adding a NEW tag ahead of the animated ones — including via
      Sentinel's own "Add Sentinel Frame to camera" or ABC Retime buttons
      — had the same effect and is closed the same way.

    - Reordering (or inserting among) two tags of the SAME type — e.g.
      two Constraint tags on the same host swapping order — mis-paired
      each track onto the OTHER tag, applied it, and reported success.
      Closed by putting the tag's NAME in the key ahead of the index:
      the two tags in that case have different names, so neither one's
      key depends on where the other sits.

    NOT closed, and not claimed to be: two tags of the same type AND the
    same NAME, reordered, remain genuinely ambiguous — there is nothing
    left to tell them apart, exactly as for two same-named sibling
    objects in ``location_keys``. Their keys stay ``…:0]``/``…:1]`` in
    tag order and a reorder still swaps them silently.

    Priced in deliberately: RENAMING a tag now re-arms its tracks (they
    land in ``plan_restore``'s ``missing`` bucket and the row says "N
    pistas no encontradas"), the same trade renaming an OBJECT has always
    made — a rename is the artist saying "this is something else now",
    and the failure is visible instead of a wrong write. Note there is no
    fallback to the older ``tag[<type>:N]`` format: reading it would
    reintroduce exactly the mis-pairing this format removes, so pins
    written before this change report their tag tracks as not found.

    ``desc_id_parts`` is the track's ``GetDescriptionID()`` flattened to
    ``[(id, dtype, creator), ...]`` (one triple per DescLevel) — the
    parameter identity, which — unlike any C4D handle — DOES survive
    save/reload."""
    desc_key = "/".join("%d.%d.%d" % tuple(part) for part in desc_id_parts)
    return "%s::%s" % (owner, desc_key)


# --- Icon color (usability pass, v1.35.2) --------------------------------
#
# "Color" in the tag's own row is NOT a color of our own — it is the tag's
# NATIVE ID_BASELIST_ICON_COLORIZE_MODE + ID_BASELIST_ICON_COLOR (the exact
# pair the Basic tab's "Icon Color" checkbox + picker already edits, measured
# live: mode became 1, colour became Vector(0.85, 0.3, 0.25) — see the design
# spec's crux) exposed DIRECTLY in the tag's own description (pin_tag.py's
# GetDDescription) — C4D's real picker, any colour, eyedropper and presets
# included, instead of a fixed set of words we'd have to invent and
# maintain. The eight-swatch palette this module used to define here (v1.35.1)
# is gone along with the buttons that dispatched it: this feature has twice
# been burned by keeping our own copy of data C4D already owns, and now that
# the native picker is exposed there is no copy left to keep.


def pluralize_es(count, singular, plural=None):
    """``"%d %s" % (count, singular if count == 1 else plural)`` — the
    single source of truth for Spanish count/word agreement across every
    row string in ``pin_tag.py`` ("1 objeto" vs "N objetos", "1
    restaurado" vs "N restaurados", "1 pista de animación" vs "N pistas
    de animación", "1 pista nueva sin restaurar" vs "N pistas nuevas sin
    restaurar"). Lives here, not in ``pin_tag.py``, for the same reason
    ``location_keys``/``plan_restore`` do: pure and c4d-free, so it is
    tested directly (pin-live-geometry-brief.md, Cambio 2) instead of
    only indirectly through a live tag.

    ``plural`` defaults to ``singular + "s"`` for the common regular
    case; callers with an irregular or multi-word plural (e.g. "pista
    nueva" -> "pistas nuevas") always pass it explicitly."""
    if plural is None:
        plural = singular + "s"
    return "%d %s" % (count, singular if count == 1 else plural)


def track_capture_counts(track_categories):
    """Split a flat list of (normalized) categories — one per CTrack a
    node actually had something to say about — into captured vs
    skipped-by-category. Pure so the counting rule is tested without a
    scene: pin_tag.py walks the real tracks and hands over only the
    categories, this decides what they mean for the row."""
    categories = list(track_categories or [])
    captured = sum(1 for c in categories if is_captured_track_category(c))
    return {"captured": captured, "skipped": len(categories) - captured}
