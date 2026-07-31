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


#: Paleta de identidad del pin. Siete tonos legibles sobre el fondo oscuro
#: del Object Manager, más "sin color" como valor por defecto — un pin sin
#: personalizar debe verse como el icono normal del plugin, no como un color
#: elegido al azar por nosotros. Verificado en el spike de la Tarea 1 (§5):
#: GeClipMap.SetColor + FillRect rellenan el bitmap con estos valores tal
#: cual (píxel central leído de vuelta idéntico al fill).
PIN_COLORS = [
    ("none", None), ("red", (200, 70, 60)), ("orange", (215, 130, 50)),
    ("yellow", (210, 190, 70)), ("green", (95, 175, 95)),
    ("blue", (80, 130, 210)), ("violet", (150, 110, 200)),
    ("grey", (150, 150, 150)),
]


def pin_badge(label, index):
    """El carácter que va sobre el icono: la primera letra del nombre si el
    artista puso uno, y si no el ordinal del pin sobre su objeto.

    Un solo carácter a propósito: en 32x32 dos ya no se leen, y el nombre
    completo está a un hover de distancia."""
    text = (label or "").strip()
    if text:
        return text[0].upper()
    return str(index + 1)[-1]


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
    en un no-op que el artista descubre tarde. La de keyframes es la peor de
    las dos porque es invisible — si un parámetro está animado, reponer su
    valor no cambia nada: la pista lo sobrescribe en el siguiente frame."""
    if not pin:
        return {"filled": False, "label": "", "count": 0,
                "has_geometry": False, "has_keyframes": False}
    entries = pin.get("entries") or []
    return {
        "filled": True,
        "label": pin.get("label") or "",
        "count": len(entries),
        "has_geometry": any(e.get("geometry") for e in entries),
        "has_keyframes": any(e.get("keyframes") for e in entries),
    }
