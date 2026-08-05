# -*- coding: utf-8 -*-
"""Motor puro de Sentinel Variants: nombres de opción, plan de cambio y de
borrado, nombres de archivo del render por opción, y los textos de la fila
del tag. Nunca importa c4d — todo lo de aquí es decidible sin escena, así
que se prueba directamente (misma división que pins.py, su hermano).

Lo que este módulo NO decide, a propósito: dónde vive una opción aparcada y
cómo se mueve. Eso es escena viva y vive en ui/variant_tag.py."""

from sentinel.pins import pluralize_es

#: Prefijo de los nombres automáticos. El artista renombra en cuanto la
#: opción significa algo ("sin bend, subdiv 3"), que es la mitad del valor
#: de la herramienta; esto solo tiene que ser un sitio donde empezar.
DEFAULT_OPTION_PREFIX = "Opción"

#: Caracteres que un nombre de archivo no puede llevar en ninguno de los dos
#: sistemas donde corre esto (macOS y Windows). Se sustituyen por "_" al
#: componer el nombre de la imagen de un render — nunca se recorta el nombre,
#: que es lo que identifica la opción para quien mira las imágenes.
_UNSAFE_PATH_CHARS = '/\\:*?"<>|'


def _letters(index):
    """"A", "B", ... "Z", "AA", "AB", ... — base 26 con letras, para que
    pasar de la Z siga dando un nombre legible en vez de un número."""
    out = ""
    index = int(index)
    while True:
        out = chr(ord("A") + index % 26) + out
        index = index // 26 - 1
        if index < 0:
            return out


def next_option_name(existing_names):
    """El primer "Opción X" que no esté cogido.

    Mira solo los nombres automáticos: una opción renombrada a mano no
    reserva ninguna letra, porque el artista ya no la piensa como "la B"."""
    taken = {(name or "").strip().lower() for name in (existing_names or [])}
    index = 0
    while True:
        candidate = "%s %s" % (DEFAULT_OPTION_PREFIX, _letters(index))
        if candidate.lower() not in taken:
            return candidate
        index += 1


def dedupe_option_name(name, existing_names):
    """``name`` si está libre, y si no ``name (2)``, ``name (3)``...

    Insensible a mayúsculas porque el sitio donde se eligen las opciones es
    el Object Manager, donde "Hero" y "hero" son indistinguibles de un
    vistazo. Un nombre vacío cae al automático en vez de producir una opción
    sin nombre que nadie puede volver a elegir."""
    text = (name or "").strip()
    if not text:
        return next_option_name(existing_names)
    taken = {(other or "").strip().lower() for other in (existing_names or [])}
    if text.lower() not in taken:
        return text
    suffix = 2
    while ("%s (%d)" % (text, suffix)).lower() in taken:
        suffix += 1
    return "%s (%d)" % (text, suffix)


def _bad(reason, **fields):
    """Dict de rechazo compartido por ``plan_switch`` y ``plan_delete`` — cada
    llamador pasa las claves de datos que su plan usa (``park``/``mount`` o
    ``delete``/``new_active``), todas puestas a ``None``, para que un test
    que compare el dict entero no pueda colarse comparando solo ``ok`` y
    ``reason``."""
    result = {"ok": False, "reason": reason}
    result.update(fields)
    return result


def plan_switch(option_count, active_index, target_index):
    """Qué mueve un cambio de opción: qué sale de la jerarquía y qué entra.

    Devuelve ``ok=False`` sin plan cuando no hay nada que hacer — y el
    llamador NO debe abrir un bracket de undo en ese caso: un paso de
    deshacer que no deshace nada es peor que ninguno, porque el siguiente
    Cmd+Z del artista se lo gasta sin que la escena cambie."""
    count = int(option_count or 0)
    if target_index is None or not (0 <= int(target_index) < count):
        return _bad("bad_index", park=None, mount=None)
    target = int(target_index)
    if active_index is not None and int(active_index) == target:
        return _bad("already_active", park=None, mount=None)
    park = int(active_index) if active_index is not None else None
    if park is not None and not (0 <= park < count):
        # La activa apunta fuera de la lista (enlace perdido, lista
        # reescrita a mano): montar la elegida es correcto, aparcar un
        # fantasma no.
        park = None
    return {"ok": True, "reason": "", "park": park, "mount": target}


def plan_delete(option_count, active_index, target_index):
    """Qué borra un borrado, y QUÉ QUEDA ACTIVO después.

    La segunda mitad es la que se equivoca sola: los índices son posiciones
    en una lista, así que borrar una opción anterior a la activa desplaza la
    activa una posición. Sin este ajuste, tras borrar queda montada una
    opción distinta de la que estaba puesta, en silencio."""
    count = int(option_count or 0)
    if target_index is None or not (0 <= int(target_index) < count):
        return _bad("bad_index", delete=None, new_active=None)
    if count <= 1:
        return _bad("last_option", delete=None, new_active=None)
    target = int(target_index)
    active = int(active_index) if active_index is not None else None
    if active is not None and not (0 <= active < count):
        # La activa apunta fuera de la lista (mismo enlace perdido que
        # plan_switch ya contempla): tratarla como "sin activa" en vez de
        # aritmética sobre un índice fantasma.
        active = None
    if active is None:
        new_active = 0
    elif active == target:
        # Se borra la que está puesta: hay que montar otra, y la de al lado
        # es la elección menos sorprendente.
        new_active = target - 1 if target > 0 else 0
    elif active > target:
        new_active = active - 1
    else:
        new_active = active
    return {"ok": True, "reason": "", "delete": target, "new_active": new_active}


def render_image_stem(scene_stem, set_name, option_name):
    """Nombre base de la imagen de una opción: escena, conjunto y opción,
    en ese orden, con los caracteres que una ruta no admite sustituidos por
    "_". Sin recortes: el nombre de la opción ES lo que identifica la imagen
    para quien la mira, y una versión truncada las hace indistinguibles."""
    parts = [part for part in (scene_stem, set_name, option_name)
             if (part or "").strip()]
    stem = "_".join(part.strip() for part in parts)
    for char in _UNSAFE_PATH_CHARS:
        stem = stem.replace(char, "_")
    return stem


#: Por qué NO se cambió de opción, en palabras. ``already_active`` no está:
#: no es un error (se pidió lo que ya estaba puesto), así que no se dice
#: nada — decirlo sería ruido en el gesto más frecuente de la herramienta.
_SWITCH_REASONS = {
    "bad_index": "esa opción ya no está en la lista",
    "lost_option": "la opción elegida no se encuentra en la escena",
    "no_anchor": "el tag no está sobre un objeto",
    "no_document": "sin documento",
    "no_payload": "el conjunto no tiene datos",
    "no_park_container": "no se pudo crear el contenedor de aparcado",
}


def switch_report_text(result):
    """Lo que hay que decirle al artista después de un cambio de opción, o
    "" si no hay nada que decir.

    Existe porque un cambio hace DOS cosas y sólo una es visible: monta la
    opción elegida (se ve) y saca del anclaje todo lo demás que colgara de
    él (no se ve — acaba en un contenedor de la raíz con la visibilidad
    apagada). Un objeto que el artista había arrastrado ahí a mano
    desaparecía de su sitio sin una palabra. Política de la casa fijada en
    la v1.35: el resultado siempre se reporta.
    """
    result = result or {}
    if not result.get("ok"):
        reason = result.get("reason") or ""
        text = _SWITCH_REASONS.get(reason)
        if not text:
            return ""
        return "no se cambió de opción — %s" % text
    parts = ['montada "%s"' % (result.get("name") or "")]
    evacuated = [name for name in (result.get("evacuated") or [])]
    if evacuated:
        parts.append("%s del anclaje: %s" % (
            pluralize_es(len(evacuated), "objeto suelto sacado",
                         "objetos sueltos sacados"),
            ", ".join(name or "(sin nombre)" for name in evacuated)))
    return " · ".join(parts)


#: Prefijo del parte de un gesto que NO se hizo, por acción. Va delante del
#: motivo porque un parte que dijera sólo "es la única opción del conjunto"
#: no dice qué se intentó hacer.
_ACTION_FAILED = {
    "duplicate": "no se duplicó la opción",
    "rename": "no se renombró la opción",
    "delete": "no se borró la opción",
}

#: Por qué no se hizo. ``unchanged`` no está a propósito (mismo criterio que
#: ``already_active`` arriba): renombrar al nombre que ya tenía no es un
#: fallo, y el Attribute Manager reescribe el campo con lo que acaba de leer
#: en cada repintado — decirlo sería ruido constante.
_ACTION_REASONS = {
    "bad_index": "esa opción ya no está en la lista",
    "clone_failed": "no se pudo copiar la opción",
    "last_option": "es la única opción del conjunto",
    "lost_option": "la opción elegida no se encuentra en la escena",
    "no_active": "no hay ninguna opción montada",
    "no_anchor": "el tag no está sobre un objeto",
    "no_document": "sin documento",
    "no_park_container": "no se pudo crear el contenedor de aparcado",
    "no_payload": "el conjunto no tiene datos",
}


def action_report_text(result):
    """Lo que hay que decirle al artista tras duplicar, renombrar o borrar, o
    "" si no hay nada que decir.

    Mismo motivo que ``switch_report_text``: estos tres gestos cambian la
    escena de formas que no se ven enteras — duplicar monta OTRA cosa
    (la copia), borrar se lleva un subárbol entero, y renombrar puede
    entregar un nombre distinto del pedido por deduplicación. Política de la
    casa fijada en la v1.35: el resultado siempre se reporta."""
    result = result or {}
    action = result.get("action") or ""
    name = result.get("name") or ""
    if not result.get("ok"):
        prefix = _ACTION_FAILED.get(action)
        text = _ACTION_REASONS.get(result.get("reason") or "")
        if not prefix or not text:
            return ""
        return "%s — %s" % (prefix, text)
    if action == "duplicate":
        return 'duplicada como "%s" · montada' % name
    if action == "rename":
        return 'renombrada a "%s"' % name
    if action == "delete":
        mounted = result.get("mounted") or ""
        if mounted:
            return 'borrada "%s" · montada "%s"' % (name, mounted)
        return 'borrada "%s"' % name
    return ""


def _active_option(state):
    options = (state or {}).get("options") or []
    index = (state or {}).get("active")
    if index is None or not (0 <= int(index) < len(options)):
        return None
    return options[int(index)]


def status_text(state):
    """La línea de resumen: qué opción está puesta y cuánto hay. Derivada en
    cada repintado (mismo patrón que ID_PIN_STATUS del Pin), nunca
    almacenada, para que no pueda quedarse vieja."""
    options = (state or {}).get("options") or []
    active = _active_option(state)
    count = pluralize_es(len(options), "opción", "opciones")
    if active is None:
        return "ninguna opción montada · %s" % count
    mounted = pluralize_es(int(active.get("objects") or 0), "objeto montado",
                           "objetos montados")
    return "%s · %s · %s" % (active.get("name") or "", count, mounted)


def warning_text(state):
    """La línea de límites, SEPARADA del resumen (lección del Pin: al
    concatenarlas detrás del conteo, la advertencia es lo primero que se
    trunca). Devuelve "" cuando no hay nada que advertir.

    Orden deliberado: primero lo que puede ser trabajo perdido (una opción
    cuyo enlace no resuelve), después el peso — que es el límite honesto
    nº1 del spec (las copias son reales y la escena pesa lo mismo que
    hoy)."""
    state = state or {}
    parts = []
    orphans = int(state.get("orphans") or 0)
    if orphans:
        parts.append(pluralize_es(orphans, "opción no encontrada",
                                  "opciones no encontradas"))
    parked = int(state.get("parked_objects") or 0)
    if parked:
        parts.append("%s siguen en la escena" % pluralize_es(
            parked, "objeto aparcado", "objetos aparcados"))
    if not parts:
        return ""
    return "⚠ " + " · ".join(parts)
