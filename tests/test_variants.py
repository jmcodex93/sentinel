"""Motor puro de Sentinel Variants. Importado por paquete (no por ruta):
conftest.py ya pone plugin/ en sys.path e instala el fake de c4d, y
variants.py reutiliza sentinel.pins.pluralize_es, así que el import por
paquete es el que ejercita la reutilización real en vez de simularla."""

from sentinel import variants


def option(name, resolved=True, objects=1):
    # La MISMA forma que produce variant_tag.read_state. Llevaba un
    # "geometry" que ningún consumidor leía y que se retiró de producción; un
    # fixture que siguiera fabricándolo mentiría sobre lo que llega aquí.
    return {"name": name, "resolved": resolved, "objects": objects}


def state(options, active=0, parked_objects=0, orphans=0):
    return {"options": list(options), "active": active,
            "parked_objects": parked_objects, "orphans": orphans}


# --- nombres --------------------------------------------------------------

def test_first_option_is_a():
    assert variants.next_option_name([]) == "Opción A"


def test_next_option_skips_the_names_already_taken():
    assert variants.next_option_name(["Opción A", "Opción B"]) == "Opción C"


def test_next_option_ignores_renamed_options_when_choosing_a_letter():
    """El artista renombra ("sin bend, subdiv 3") — eso no debe hacer que la
    siguiente opción vuelva a llamarse como una que ya existe."""
    assert variants.next_option_name(["sin bend", "Opción B"]) == "Opción A"


def test_next_option_past_z_keeps_going_without_colliding():
    taken = ["Opción %s" % chr(c) for c in range(ord("A"), ord("Z") + 1)]
    assert variants.next_option_name(taken) == "Opción AA"


def test_dedupe_leaves_a_free_name_alone():
    assert variants.dedupe_option_name("hero", ["otra"]) == "hero"


def test_dedupe_suffixes_a_taken_name():
    assert variants.dedupe_option_name("hero", ["hero"]) == "hero (2)"


def test_dedupe_keeps_counting_past_the_first_collision():
    assert variants.dedupe_option_name(
        "hero", ["hero", "hero (2)"]) == "hero (3)"


def test_dedupe_is_case_insensitive_because_the_object_manager_is_not():
    """Dos opciones llamadas "Hero" y "hero" son indistinguibles de un
    vistazo en el Object Manager, que es donde se eligen."""
    assert variants.dedupe_option_name("Hero", ["hero"]) == "Hero (2)"


def test_dedupe_of_an_empty_name_falls_back_to_a_default():
    assert variants.dedupe_option_name("   ", []) == "Opción A"


# --- cambio de opción -----------------------------------------------------

def test_switch_parks_the_active_and_mounts_the_target():
    plan = variants.plan_switch(3, 0, 2)
    assert plan == {"ok": True, "reason": "", "park": 0, "mount": 2}


def test_switching_to_the_active_option_is_a_no_op_not_an_error():
    """Pulsar la opción que ya está puesta no debe mover nada NI abrir un
    bracket de undo: un paso de deshacer que no deshace nada es peor que
    ninguno."""
    plan = variants.plan_switch(3, 1, 1)
    assert plan == {"ok": False, "reason": "already_active",
                    "park": None, "mount": None}


def test_switch_with_no_active_option_only_mounts():
    """Estado posible tras perder el enlace de la activa: montar la elegida
    sin intentar aparcar un fantasma."""
    plan = variants.plan_switch(2, None, 1)
    assert plan == {"ok": True, "reason": "", "park": None, "mount": 1}


def test_switch_to_an_index_out_of_range_is_refused():
    plan = variants.plan_switch(2, 0, 5)
    assert plan["ok"] is False
    assert plan["reason"] == "bad_index"


# --- borrado --------------------------------------------------------------

def test_deleting_an_inactive_option_keeps_the_active_one_active():
    plan = variants.plan_delete(3, 0, 2)
    assert plan == {"ok": True, "reason": "", "delete": 2, "new_active": 0}


def test_deleting_an_option_before_the_active_one_shifts_its_index():
    """Los índices son posiciones en la lista: borrar la 0 mueve la 2 a la 1.
    Si esto se equivoca, tras borrar queda ACTIVA otra opción distinta de la
    que estaba puesta, en silencio."""
    plan = variants.plan_delete(3, 2, 0)
    assert plan == {"ok": True, "reason": "", "delete": 0, "new_active": 1}


def test_deleting_the_active_option_promotes_a_neighbour():
    plan = variants.plan_delete(3, 1, 1)
    assert plan == {"ok": True, "reason": "", "delete": 1, "new_active": 0}


def test_deleting_the_last_remaining_option_is_refused():
    """Un conjunto sin ninguna opción no es un estado que el sistema sepa
    representar — el anclaje se quedaría vacío y el tag mintiendo."""
    plan = variants.plan_delete(1, 0, 0)
    assert plan == {"ok": False, "reason": "last_option",
                    "delete": None, "new_active": None}


def test_deleting_an_index_out_of_range_is_refused():
    plan = variants.plan_delete(3, 0, 5)
    assert plan == {"ok": False, "reason": "bad_index",
                    "delete": None, "new_active": None}


def test_deleting_with_no_target_index_is_refused():
    """``target_index=None`` es un estado real (nada seleccionado en la
    lista) — sin esta guarda, ``int(None)`` revienta con TypeError en vez
    de devolver un rechazo legible."""
    plan = variants.plan_delete(3, 0, None)
    assert plan == {"ok": False, "reason": "bad_index",
                    "delete": None, "new_active": None}


def test_deleting_with_an_orphaned_active_index_falls_back_cleanly():
    """La activa apunta fuera de la lista (enlace perdido) — mismo caso que
    ``plan_switch`` ya cubre. Sin la guarda, ``new_active`` puede acabar
    apuntando fuera de la lista resultante tras el borrado."""
    plan = variants.plan_delete(3, 5, 0)
    assert plan == {"ok": True, "reason": "", "delete": 0, "new_active": 0}


# --- nombres de archivo del render ---------------------------------------

def test_render_stem_joins_scene_set_and_option():
    assert variants.render_image_stem(
        "SHOT_18", "brazo", "Opción A") == "SHOT_18_brazo_Opción A"


def test_render_stem_replaces_the_characters_a_path_cannot_carry():
    assert variants.render_image_stem(
        "SHOT_18", "brazo/robot", "A:B*C?") == "SHOT_18_brazo_robot_A_B_C_"


def test_render_stem_survives_an_unnamed_scene():
    assert variants.render_image_stem("", "brazo", "A") == "brazo_A"


# --- textos de la fila ----------------------------------------------------

def test_status_of_a_healthy_set_names_the_active_option():
    text = variants.status_text(state(
        [option("A", objects=4), option("B", objects=7)],
        active=0, parked_objects=7))
    assert text == "A · 2 opciones · 4 objetos montados"


def test_status_uses_the_singular_for_one_option():
    text = variants.status_text(state([option("A", objects=1)], active=0))
    assert text == "A · 1 opción · 1 objeto montado"


def test_status_says_so_when_nothing_is_mounted():
    text = variants.status_text(state(
        [option("A", resolved=False)], active=None))
    assert text == "ninguna opción montada · 1 opción"


def test_warning_reports_the_weight_of_the_parked_options():
    """El límite honesto nº1 del spec: las copias son reales y la escena
    pesa. Se dice en la fila, no solo en los docs."""
    text = variants.warning_text(state(
        [option("A", objects=4), option("B", objects=7)],
        active=0, parked_objects=7))
    assert text == "⚠ 7 objetos aparcados siguen en la escena"


def test_warning_reports_lost_options_ahead_of_the_weight():
    """Un BaseLink que no resuelve es la única forma de perder trabajo aquí,
    así que va primero. Las DOS advertencias tienen que estar presentes en
    este caso o el test no distingue el orden — verificado por mutación:
    con parked_objects=0 este test pasaba con las partes intercambiadas."""
    text = variants.warning_text(state(
        [option("A", objects=4), option("B", resolved=False)],
        active=0, parked_objects=3, orphans=1))
    assert text == ("⚠ 1 opción no encontrada · "
                    "3 objetos aparcados siguen en la escena")


def test_warning_is_empty_when_there_is_nothing_to_warn_about():
    text = variants.warning_text(state([option("A", objects=2)], active=0))
    assert text == ""
