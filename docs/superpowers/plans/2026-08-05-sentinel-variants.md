# Sentinel Variants (v1.36) — plan de implementación

> **Para quien ejecute esto:** SUB-SKILL OBLIGATORIA: `superpowers:subagent-driven-development` (recomendada) o `superpowers:executing-plans`, tarea a tarea. Los pasos usan checkbox (`- [ ]`).

**Goal:** un tag `Sentinel Variants` sobre un null de anclaje que guarda varias **opciones** (subárboles alternativos) de las que **exactamente una está montada** en la jerarquía; las demás viven aparcadas fuera de ella. Crear, duplicar, renombrar, borrar y cambiar de opción, **cada gesto un solo paso de deshacer**, y un "renderizar todas las opciones" que deja las imágenes nombradas por opción — según `docs/superpowers/specs/2026-08-05-sentinel-variants-design.md`.

**Architecture:** el mismo reparto que el Pin (v1.35), su hermano de verbo. Un **motor puro** (`plugin/sentinel/variants.py`, sin `import c4d`) decide todo lo decidible sin escena: nombres por defecto y su deduplicación, el plan de un cambio de opción (qué sale, qué entra, cuándo es no-op), los nombres de archivo del render por opción, y los textos de la fila (con `pins.pluralize_es`, **reutilizado, nunca duplicado**). Un **adaptador fino `TagData`** (`plugin/sentinel/ui/variant_tag.py`) hace las lecturas y escrituras vivas: mover subárboles, resolver `BaseLink`, abrir el bracket de undo y pintar la descripción del Attribute Manager. El estado vive en el `BaseContainer` propio del tag (viaja dentro del `.c4d`, sin sidecar — round-trip ya medido en el spike del Pin §1).

**Tech Stack:** Python; motor puro contra el arnés fake-c4d de pytest; `c4d.plugins.TagData` con `GetDDescription` dinámica; triplete `plugin/res/`; verificación viva en C4D 2026.303 vía MCP `exec_python` + eyeball del usuario.

**Branch:** `feat/sentinel-variants` (crear desde `main` antes de la Tarea 1).

---

## Global Constraints

- **Id del tag: `2099079`.** Decidido y verificado (2099069-2099078 ocupados). Descripción `Tsentinelvariants`.
- **Registro con `TAG_MULTIPLE`.** Su ausencia hizo que C4D **expulsara** tags en la v1.35 (single-instance implícito: `MakeTag`/`InsertTag` desaloja el tag existente del mismo tipo e invalida toda referencia Python a él). Aquí no está previsto poner dos tags de Variants en un mismo null, pero *previsto* no es *imposible* — duplicar un anclaje entero produce dos — y el modo de fallo es silencioso y destructivo. Se registra con `TAG_MULTIPLE` igual que el Pin.
- **Invariante estructural, comprobable de un vistazo: el null de anclaje tiene exactamente UN hijo, el null de la opción activa.** Cada opción es un null propio (`option null`) que contiene su subárbol. La opción activa cuelga del anclaje; **todas las demás cuelgan del contenedor de aparcado**. Este invariante es lo que hace que "cambiar de opción" sea siempre el mismo par de movimientos, independientemente del contenido.
- **Aparcado = fuera de la jerarquía**, a un contenedor gestionado **en la RAÍZ de la escena**, con visibilidad de editor y render apagadas. Medido en `docs/research/2026-08-05-variant-isolation-spike.md`: ocultar NO aísla (un Cloner sigue clonando la rama invisible: 2584 polys con y sin ocultar) y desactivar tampoco equivale a sacar (24 vs 54). El contenedor está en la raíz porque tiene que quedar **fuera del subárbol del anclaje**: si el anclaje cuelga de un Cloner, aparcar dentro seguiría contando. En la raíz nada lo consume, así que apagar la visibilidad basta para que no renderice.
- **Reencuentro de opciones por `BaseLink`, jamás por id de C4D.** Ningún id nativo sobrevive a guardar+cargar — `GetGUID()` y `FindUniqueID(MAXON_CREATOR_ID)` se regeneran (medido; es la causa raíz del bug de baseline de la v1.34.1 y la razón de las claves por ubicación del Pin). Los `BaseLink` sí se resuelven al cargar, y el Sentinel Frame ya los usa para sobrevivir a renombrados. Un enlace que no resuelva es una opción **perdida**: se reporta en la fila, nunca se inventa un sustituto.
- **Un solo paso de deshacer por gesto del artista**, verificado en vivo **contando pasos** (no asumido). El contrato ya estuvo roto en matwire con más de un material y lo encontró el usuario en uso normal.
- **Verificación en C4D vivo para todo lo que toque la escena**, no solo pytest. Razón, escrita aquí para que nadie la relaje: el arnés fake de este repo **ha dado verde sobre código roto siete veces esta semana** — `GetGUID` inexistente en materiales, `bool(maxon.Bool)`, un puerto nulo que no es `None`, `**kw` tragado por un fake, un entorno sin `maxon`, `MakeTag` que PREPENDE mientras el fake hacía append, y fakes con `SetData`/`SetMl` en `pass`. El fake modela el contrato que *creemos* tener; solo C4D dice el que hay.
- **Verificación por mutación de cada test nuevo**: romper la línea que lo hace pasar y comprobar que ese test — nombrado — falla. Un test que no puede fallar no es evidencia.
- **Comprobar que el caso base hace algo antes de creerse cualquier medición.** En el spike de aislamiento tres sondas devolvieron ceros que parecían respuestas y "desactivar == sacar" salió `SI` por vacuidad.
- **Los límites se muestran en la fila del tag**, no solo en la documentación (regla heredada del Pin).
- **Antes de añadir cualquier control al tag, mirar qué trae ya su pestaña Basic.** En el Pin se construyó dos veces algo que el host ya daba: un campo de nombre propio (que peleaba con el nativo y revertía renombrados un tick después) y un color de icono (que `Icon Color` ya ofrecía con selector y presets). El nombre del conjunto **es el nombre del tag**; el color **es el nativo**.
- Suite: `python3 -m pytest tests/ -q`. **Baseline al entrar en este plan: 1252 passed** (medido en `main@68a0229`).
- El Python del plugin solo se recarga con **reinicio completo de C4D**; `./sync.sh` copia el plugin a la carpeta de prefs activa.

## File Structure

- `plugin/sentinel/variants.py` — NUEVO, puro: nombres, plan de cambio, textos de fila, nombres de archivo de render. Sin `import c4d`.
- `plugin/sentinel/ui/variant_tag.py` — NUEVO: el `TagData`. Descripción, creación del conjunto, aparcar/montar, duplicar/renombrar/borrar, render de todas las opciones.
- `plugin/res/description/Tsentinelvariants.res` + `.h`, `plugin/res/strings_us/description/Tsentinelvariants.str` — NUEVO triplete (shell mínimo, copia de `Tsentinelpin.*`).
- `plugin/sentinel_panel.pyp` — registro del tag (bloque gemelo del Pin, líneas ~236-260).
- `tests/test_variants.py` — NUEVO, motor puro.
- `tests/test_variant_tag.py` — NUEVO, contrato del adaptador contra el fake.
- `docs/research/2026-08-05-variants-reparenting-spike.md` — NUEVO, evidencia de la Tarea 1.

---

### Task 1: SPIKE LIVE (BLOQUEANTE — nada de código de producción antes)

**Files:** crear `docs/research/2026-08-05-variants-reparenting-spike.md`.

Quedan tres cosas sin medir y las tres cambian el diseño si salen mal. Todas las sondas van por `mcp__cinema4d__batch` / `exec_python` contra C4D vivo. **Si C4D no está accesible, reportar BLOCKED — no adivinar.**

**Reglas de método, medidas y documentadas en `docs/research/2026-07-31-pin-storage-spike.md` §2 — no re-derivarlas:**

1. El documento throwaway va **insertado en la lista de documentos** (`c4d.documents.InsertBaseDocument`) y se cierra con `KillDocument` en un `finally`. Sobre un documento no insertado, el undo devuelve `True` y **no revierte**.
2. El undo se dispara con el **comando del menú** (`c4d.CallCommand(12105)`), no con `DoUndo()` desde script.
3. **Tras deshacer hay que volver a buscar el objeto en el documento.** C4D lo reemplaza al restaurar; leer el manejador anterior mide un huérfano y miente en la dirección peligrosa (te hace creer que el undo está roto cuando funciona).
4. **Comprobar el caso base antes de creerse la medición** (guarda del spike de aislamiento).

- [ ] **Step 1: ¿Un reparentado se revierte con UN solo Cmd+Z, a la jerarquía exacta de partida?**

Es la pregunta que sostiene el gesto central del sistema. Montar: `raiz` → `padre_a` → `hijo` (con un descendiente propio, `nieto`, para que se mida el subárbol y no un objeto suelto) y un `padre_b` hermano. Probar **tres variantes de `AddUndo`**, cada una en su documento limpio, y reportar las tres:

- (A) `doc.AddUndo(c4d.UNDOTYPE_CHANGE, hijo)` antes de `hijo.Remove()` + `hijo.InsertUnder(padre_b)`.
- (B) `doc.AddUndo(c4d.UNDOTYPE_CHANGE, padre_a)` y `(..., padre_b)` — undo sobre los PADRES, no sobre lo movido.
- (C) `doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, hijo)` antes de `Remove()`, y `AddUndo(c4d.UNDOTYPE_NEWOBJ, hijo)` después de `InsertUnder`.

Oráculo, leído **re-buscando en el documento** por nombre tras el undo: (a) nº de pasos de undo hasta volver al estado inicial —tiene que ser **1**—; (b) el padre de `hijo`; (c) que `nieto` siga colgando de `hijo`; (d) el **índice entre hermanos** de `hijo` bajo `padre_a` (un undo que lo devuelve al sitio pero en otro orden no es "la jerarquía exacta"); (e) que `hijo` siga vivo (no un objeto nuevo vacío).

Caso base obligatorio antes de creerse nada: comprobar que **sin** ningún `AddUndo` el undo NO revierte el movimiento. Si revierte igual, la sonda mide otra cosa y hay que arreglarla antes de seguir.

**Salida esperada del paso**: una de las tres variantes con `pasos=1` y las cinco lecturas correctas. **Si ninguna lo consigue**, PARAR y reportar: el contrato "un solo Cmd+Z" no es alcanzable con `Remove`/`InsertUnder` y el diseño necesita otro mecanismo (p. ej. `doc.InsertObject` con `checknames`, o `MoveObject`) — es una decisión de spec, no del implementador.

- [ ] **Step 2: ¿Un enlace que apunta DENTRO de lo que se mueve sigue resolviendo?**

Es el "requisito central" que el spec deriva del spike de aislamiento. Montar `hijo` con un descendiente `objetivo`, y **fuera** del subárbol un objeto con un tag que lo enlace: un `Constraint` (`Tconstraint`, `ID_CA_CONSTRAINT_TAG_PSR` + su link de destino) y, como segundo caso independiente por si el tag de constraint no está disponible, un **Sentinel Frame** o un `Ttargetexpression` (Target tag, cuyo link es `TARGETEXPRESSIONTAG_LINK`) — cualquier tag con un `BaseLink`, lo que importa es el enlace.

Sondas, en este orden, reportando cada una:
1. `link.GetLink(doc)` **antes** de mover → tiene que devolver `objetivo` (caso base: si ya sale `None`, el montaje está mal y el resto de la sonda no mide nada).
2. Mover `hijo` a `padre_b`. Leer otra vez.
3. Mover `hijo` al contenedor de aparcado **en la raíz** con visibilidad apagada. Leer otra vez.
4. `SaveDocument` a un `.c4d` temporal, `LoadDocument`, y leer otra vez **buscando el tag por nombre en el documento cargado** (nunca el manejador viejo).
5. Con `hijo` aparcado, guardar y cargar, y comprobar que el enlace **al objeto aparcado** también resuelve (es el caso que importa: la mitad de las opciones estarán aparcadas al guardar).

**Si un enlace se rompe al aparcar**, eso no invalida el diseño pero sí obliga a decirlo en la fila del tag (Tarea 6) — anotarlo como límite medido, con el tipo de tag exacto en el que se rompió.

- [ ] **Step 3: ¿Reparentar conserva la transformación en el mundo?**

El spec **afirma** que un null en identidad la conserva. Eso se mide, no se asume.

Montar `hijo` con una matriz global no trivial (posición, rotación **y** escala — el caso fácil es solo posición y es justo el que no distingue nada). Casos:
1. Mover a un null **en identidad** → leer `hijo.GetMg()` antes y después y comparar componente a componente con tolerancia `1e-6`.
2. Mover a un null **con transformación** (posición + rotación + escala no unitarias) → mismo oráculo. Aquí se espera que NO se conserve; medirlo fija cuánto vale la regla "el anclaje nace en identidad".
3. Mover al contenedor de aparcado y de vuelta al anclaje → comprobar que la matriz global vuelve a ser la de partida (ida y vuelta, que es exactamente lo que hace un cambio de opción de A a B y de vuelta a A).
4. Repetir el caso 1 con un `hijo` **animado en posición** (dos claves) y comprobar que las claves no se recomponen: leer el valor de la pista en dos frames antes y después.

**Salida esperada**: caso 1 y 3 conservan; caso 2 documentado con su desviación. Si el caso 1 NO conserva, la creación del conjunto tiene que recomponer la matriz (`SetMg` tras insertar) y eso pasa a ser un requisito escrito de la Tarea 3, no un detalle.

- [ ] **Step 4: escribir el spike y commitear**

`docs/research/2026-08-05-variants-reparenting-spike.md`, una sección por paso: la pregunta, la sonda exacta, la salida cruda, el veredicto. **Los resultados negativos entran** (una variante de `AddUndo` que no funciona es tan útil como la que sí), y también las trampas de método que aparezcan, con el mismo detalle con que el spike de aislamiento registró la suya.

```bash
git add docs/research/2026-08-05-variants-reparenting-spike.md
git commit -m "docs: spike — reparentado, undo en un paso, BaseLinks y transformacion (Variants)"
```

---

### Task 2: motor puro (`variants.py`)

**Files:** crear `plugin/sentinel/variants.py`; crear `tests/test_variants.py`.

**Interfaces producidas** (firmas exactas — el adaptador de la Tarea 3 consume solo esto):

- `DEFAULT_OPTION_PREFIX = "Opción"`
- `next_option_name(existing_names) -> str`
- `dedupe_option_name(name, existing_names) -> str`
- `plan_switch(option_count, active_index, target_index) -> dict` → `{"ok": bool, "reason": str, "park": int|None, "mount": int|None}`
- `plan_delete(option_count, active_index, target_index) -> dict` → `{"ok": bool, "reason": str, "delete": int|None, "new_active": int|None}`
- `render_image_stem(scene_stem, set_name, option_name) -> str`
- `status_text(state) -> str`
- `warning_text(state) -> str`

**Interfaces consumidas:** `sentinel.pins.pluralize_es(count, singular, plural=None) -> str` — **reutilizado tal cual**. Encaja sin cambios: `pluralize_es(3, "opción", "opciones")` da `"3 opciones"` y el plural irregular se pasa explícito, que es justo el caso para el que la firma acepta `plural`. No se escribe un segundo pluralizador.

`state` es un dict plano (el adaptador lo construye leyendo la escena; el motor nunca ve un objeto de C4D):

```python
# {"options": [{"name": str, "resolved": bool, "objects": int, "geometry": bool}, ...],
#  "active": int|None, "parked_objects": int, "orphans": int}
```

- [ ] **Step 1: escribir los tests (deben fallar)**

Crear `tests/test_variants.py`:

```python
"""Motor puro de Sentinel Variants. Importado por paquete (no por ruta):
conftest.py ya pone plugin/ en sys.path e instala el fake de c4d, y
variants.py reutiliza sentinel.pins.pluralize_es, así que el import por
paquete es el que ejercita la reutilización real en vez de simularla."""

from sentinel import variants


def option(name, resolved=True, objects=1, geometry=False):
    return {"name": name, "resolved": resolved, "objects": objects,
            "geometry": geometry}


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
    assert plan["ok"] is False
    assert plan["reason"] == "last_option"


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
```

- [ ] **Step 2: correrlos — deben fallar**

`python3 -m pytest tests/test_variants.py -q`
Esperado: `ModuleNotFoundError: No module named 'sentinel.variants'` (colección fallida). No pasar del paso hasta ver ese error, no otro.

- [ ] **Step 3: implementar `variants.py`**

```python
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


def _bad(reason):
    return {"ok": False, "reason": reason, "park": None, "mount": None}


def plan_switch(option_count, active_index, target_index):
    """Qué mueve un cambio de opción: qué sale de la jerarquía y qué entra.

    Devuelve ``ok=False`` sin plan cuando no hay nada que hacer — y el
    llamador NO debe abrir un bracket de undo en ese caso: un paso de
    deshacer que no deshace nada es peor que ninguno, porque el siguiente
    Cmd+Z del artista se lo gasta sin que la escena cambie."""
    count = int(option_count or 0)
    if target_index is None or not (0 <= int(target_index) < count):
        return _bad("bad_index")
    target = int(target_index)
    if active_index is not None and int(active_index) == target:
        return _bad("already_active")
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
        return {"ok": False, "reason": "bad_index",
                "delete": None, "new_active": None}
    if count <= 1:
        return {"ok": False, "reason": "last_option",
                "delete": None, "new_active": None}
    target = int(target_index)
    active = int(active_index) if active_index is not None else None
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
```

- [ ] **Step 4: correrlos — deben pasar**

`python3 -m pytest tests/test_variants.py -q` → esperado **26 passed**.
`python3 -m pytest tests/ -q` → esperado **1278 passed** (1252 + 26).

> Los 26 tests de arriba y la implementación del Step 3 se ejecutaron juntos al redactar este plan (fuera del repo, con `pluralize_es` inlineado): **26 passed**. Las mutaciones 1 y 4 del Step 5 se comprobaron ahí mismo — la 1 mata su test, y la 4 **no lo mataba** con la versión inicial del test (`parked_objects=0` hacía el orden indistinguible), que es por lo que ese test lleva ahora las dos advertencias a la vez.

- [ ] **Step 5: verificación por mutación (cuatro reglas que sostienen el resto)**

Aplicar cada mutación, comprobar que **falla el test nombrado** (y solo lo esperado), revertir, y reportar las cuatro:

1. En `plan_delete`, quitar la rama `elif active > target: new_active = active - 1` (dejar `new_active = active`) → debe fallar `test_deleting_an_option_before_the_active_one_shifts_its_index`.
2. En `plan_switch`, devolver `{"ok": True, ...}` cuando `active_index == target_index` → debe fallar `test_switching_to_the_active_option_is_a_no_op_not_an_error`.
3. En `dedupe_option_name`, comparar sin `.lower()` → debe fallar `test_dedupe_is_case_insensitive_because_the_object_manager_is_not`.
4. En `warning_text`, poner el peso antes que los huérfanos → debe fallar `test_warning_reports_lost_options_ahead_of_the_weight`.

- [ ] **Step 6: commit**

```bash
git add plugin/sentinel/variants.py tests/test_variants.py
git commit -m "feat(variants): motor puro — nombres, plan de cambio y borrado, textos de fila"
```

---

### Task 3: el tag — crear conjunto y cambiar de opción

**Files:** crear `plugin/sentinel/ui/variant_tag.py`, `plugin/res/description/Tsentinelvariants.res|.h`, `plugin/res/strings_us/description/Tsentinelvariants.str`, `tests/test_variant_tag.py`; modificar `plugin/sentinel_panel.pyp`.

**Consume:** `variants.plan_switch`, `variants.next_option_name`, `variants.status_text`, `variants.warning_text`; los veredictos de la Tarea 1 (`AddUndo` correcto, comportamiento de los `BaseLink`, recomposición de matriz sí/no).

**Produce:**
- `SENTINEL_VARIANT_TAG_PLUGIN_ID = 2099079`, `VARIANT_TAG_DEFAULT_NAME = "Sentinel Variants"`
- `create_variant_set(doc, objects) -> tag|None`
- `switch_to_option(tag, index) -> dict` → `{"ok": bool, "reason": str, "name": str}`
- `read_state(tag) -> dict` (la forma que consume `variants.status_text`)
- `class SentinelVariantsTag(plugins.TagData)`

- [ ] **Step 1: el triplete de recursos**

Copiar la forma de `Tsentinelpin.*` — shell mínimo, todos los parámetros son dinámicos en Python.

`plugin/res/description/Tsentinelvariants.res`:
```
// Minimal resource shell for the Sentinel Variants TagData plugin.
// Dynamic parameters are built in sentinel/ui/variant_tag.py.
CONTAINER Tsentinelvariants
{
	NAME Tsentinelvariants;
	INCLUDE Tbase;

	GROUP ID_TAGPROPERTIES
	{
	}
}
```

`plugin/res/description/Tsentinelvariants.h`: vacío de símbolos, con el mismo comentario que `Tsentinelpin.h` explicando por qué se conserva el fichero (convención de triplete de la casa; que C4D lo exija o no cuando el `.res` no declara ids **no está medido**).

`plugin/res/strings_us/description/Tsentinelvariants.str`:
```
STRINGTABLE Tsentinelvariants
{
	Tsentinelvariants "Sentinel Variants";
}
```

- [ ] **Step 2: layout de ids de descripción**

Mirar **primero** la pestaña Basic: el **nombre** del conjunto es el nombre del tag (`node.GetName()`, proxy de lectura/escritura como `ID_PIN_NAME_FIELD` del Pin, nunca un campo de datos propio — un campo propio compitió con el nativo en el Pin y revertía los renombrados un tick después) y el **color** es `ID_BASELIST_ICON_COLORIZE_MODE` + `ID_BASELIST_ICON_COLOR` nativos. Aquí no se construye ninguno de los dos.

Una sola columna de filas/grupos (lo que truncó el texto en el Pin fue un grid multi-columna repartiendo ancho entre campos que compiten):

```python
ID_GROUP_OPTIONS = 1100   # DTYPE_GROUP, 1 columna — la lista de opciones
ID_OPTION_BASE = 1200     # primer id de fila; stride ID_OPTION_STRIDE
ID_OPTION_STRIDE = 10     # +0 botón "montar", +1 nombre, +2 duplicar,
                          # +3 borrar (Tarea 4). Stride 10 deja sitio sin
                          # tocar los ids de arriba si una fila crece.
ID_VARIANTS_STATUS = 1002   # DTYPE_STATICTEXT — resumen (variants.status_text)
ID_VARIANTS_WARNING = 1003  # DTYPE_STATICTEXT — límites (variants.warning_text),
                            # SEPARADO del resumen a propósito
ID_VARIANTS_NEW = 1004      # DTYPE_BUTTON — "Duplicar opción activa" (Tarea 4)
ID_VARIANTS_RENDER_ALL = 1005  # DTYPE_BUTTON — "Renderizar todas" (Tarea 5)
ID_VARIANTS_SEPARATOR = 1006   # DTYPE_SEPARATOR — antes de lo destructivo
ID_VARIANTS_PAYLOAD = 20000    # sub-contenedor con el estado
```

Payload dentro del contenedor propio del tag:
```python
_PAYLOAD_SCHEMA = 1        # int32, VARIANT_SCHEMA
_PAYLOAD_ACTIVE = 2        # int32, índice de la opción montada (-1 = ninguna)
_PAYLOAD_COUNT = 3         # int32
_PAYLOAD_OPTIONS = 4       # BaseContainer indexado 0..N-1
_PAYLOAD_PARK = 5          # BaseLink al contenedor de aparcado
_OPTION_NAME = 1           # string
_OPTION_LINK = 2           # BaseLink al null de la opción
VARIANT_SCHEMA = 1
```
Todos los parámetros de fila van `animatable=False` (`DESC_ANIMATE_OFF`) y los `DTYPE_BUTTON` con `DESC_CUSTOMGUI = CUSTOMGUI_BUTTON` — sin eso el botón sale como celda vacía (`frame_tag.py:1775`, confirmado en vivo ahí; no re-descubrir).

- [ ] **Step 3: `create_variant_set(doc, objects)`**

En un solo `StartUndo`/`EndUndo`, con el `AddUndo` que dictó la Tarea 1:
1. Rechazar la selección vacía (`{"ok": False, "reason": "no_selection"}`) — sin abrir bracket.
2. Descartar de la selección los objetos que sean descendientes de otro seleccionado (si no, un padre y su hijo se envolverían dos veces). Mismo problema que `keyframes.collect_shift_set` (v1.30) ya resolvió — **leerlo antes de escribir otro**.
3. Crear el null de **anclaje** en identidad, insertarlo en el sitio del primer objeto seleccionado (mismo padre, misma posición entre hermanos — un anclaje que aparece al final del Object Manager es un anclaje que el artista no encuentra).
4. Crear el null de la **opción** (`variants.next_option_name([])` → "Opción A"), en identidad, bajo el anclaje.
5. Mover cada objeto seleccionado bajo el null de la opción, **conservando el orden entre hermanos**. Si la Tarea 1 §3 midió que la transformación en el mundo NO se conserva, recomponer con `SetMg` la matriz global leída ANTES de mover.
6. Crear el tag sobre el anclaje (`MakeTag(SENTINEL_VARIANT_TAG_PLUGIN_ID)`) y escribir el payload: una opción, activa = 0, enlace al null de la opción.
7. El **contenedor de aparcado** NO se crea aquí: se crea perezosamente la primera vez que hace falta aparcar algo (Step 4). Una escena con un conjunto de una sola opción no tiene por qué llevar un null de más en la raíz.

`c4d.EventAdd()` al terminar, fuera del bracket.

- [ ] **Step 4: aparcar y montar — `switch_to_option(tag, index)`**

```python
def switch_to_option(tag, index):
    """Cambia la opción montada. UN solo paso de deshacer para el par
    completo (aparcar la activa + montar la elegida): son medio gesto cada
    una y deshacer solo la mitad deja el anclaje vacío o con dos opciones
    dentro, que es un estado que el invariante no admite."""
```

Orden, y el orden es la propiedad de seguridad:
1. `read_state(tag)` y `variants.plan_switch(...)`. Si `ok` es `False`, **no abrir bracket** y devolver el motivo (`already_active` no es un error: no se dice nada, no se toca nada).
2. Resolver los `BaseLink` de lo que se va a mover. Si el de la opción a montar no resuelve → devolver `{"ok": False, "reason": "lost_option"}` y **no tocar nada**: mejor un conjunto que no cambia y lo dice, que un anclaje vacío.
3. `doc.StartUndo()`.
4. Aparcar la activa: asegurar el contenedor de aparcado (crearlo en la raíz con visibilidad de editor y render **apagadas** si no existe, con su `AddUndo` de creación), y mover ahí el null de la opción activa.
5. Montar la elegida bajo el anclaje.
6. Escribir el payload (`AddUndo(UNDOTYPE_CHANGE, tag)` antes) con el nuevo `active`.
7. `doc.EndUndo()`, `c4d.EventAdd()`.

El contenedor de aparcado se enlaza desde el payload (`_PAYLOAD_PARK`) para reencontrarlo tras guardar+cargar; si el enlace no resuelve, se crea otro (no se busca por nombre: un null que el artista renombró seguiría siendo el bueno y uno que llamó igual no lo sería).

- [ ] **Step 5: la descripción y los handlers**

`GetDDescription` pinta: grupo de opciones con una fila por opción (botón "montar" con el nombre de la opción como etiqueta + marca de cuál está puesta), la línea de resumen, la línea de advertencia, el separador y los botones de la Tarea 4/5. `GetDParameter` deriva `ID_VARIANTS_STATUS` y `ID_VARIANTS_WARNING` en cada lectura (nunca almacenados) y hace de proxy del nombre del tag. `Message`/`MSG_DESCRIPTION_COMMAND` despacha por id de fila (`(command_id - ID_OPTION_BASE) // ID_OPTION_STRIDE` = índice, `% ID_OPTION_STRIDE` = acción), con la guarda de hilo principal (`_is_main_thread`) que ya usa el Pin.

- [ ] **Step 6: tests del adaptador**

Crear `tests/test_variant_tag.py` contra el fake (mismo estilo que `tests/test_pin_tag.py`), cubriendo lo que el fake **sí** puede decir con honestidad — el contrato del módulo, no el comportamiento de C4D:

1. `create_variant_set(doc, [])` devuelve `no_selection` y **no abre bracket** (el fake cuenta `StartUndo`/`EndUndo`: 0 y 0).
2. `create_variant_set` con un padre y su hijo seleccionados envuelve **una sola vez** (el hijo no acaba en dos sitios).
3. Un `switch_to_option` con `index` igual al activo devuelve `already_active` y **no abre bracket** (contador a 0 — es la mitad barata del contrato de undo que sí se puede fijar aquí).
4. Un `switch_to_option` válido abre **exactamente un** `StartUndo`/`EndUndo` (el contador del fake), y deja el payload con `active` = índice pedido.
5. Un `switch_to_option` cuyo enlace de destino no resuelve devuelve `lost_option`, **no abre bracket**, y deja `active` como estaba.
6. `read_state` de un payload con un enlace roto reporta `orphans=1` y `resolved=False` en esa opción — y `variants.status_text` sobre él no revienta.

Escribir en la cabecera del fichero, como hace `test_pin_tag.py`, **qué NO puede probar este arnés**: que el movimiento real conserve la jerarquía, que el undo del menú revierta en un paso, y que los `BaseLink` sobrevivan a guardar+cargar. Eso es Step 8, y está ahí precisamente porque el fake ha dado verde sobre código roto siete veces esta semana.

- [ ] **Step 7: registro en `sentinel_panel.pyp`**

Bloque gemelo del Pin (líneas ~236-260): import con `try/except` guardando `_VARIANT_TAG_IMPORT_ERROR`, y

```python
variant_tag_info = c4d.TAG_VISIBLE | c4d.TAG_EXPRESSION | c4d.TAG_MULTIPLE
plugins.RegisterTagPlugin(
    id=SENTINEL_VARIANT_TAG_PLUGIN_ID,
    str=VARIANT_TAG_DEFAULT_NAME,   # la constante, nunca un literal retecleado
    info=variant_tag_info,
    g=SentinelVariantsTag,
    description="Tsentinelvariants",
    icon=icon,
)
```

**`TAG_MULTIPLE` no es opcional** — ver Global Constraints. Añadir el comentario que diga por qué, para que nadie lo "limpie".

Comprobar además que **el nombre del tag sobrevive a cargar**: C4D repone el nombre de un tag de plugin desde su string de registro en cada carga (medido en la v1.35). Si el nombre del conjunto vive solo en `GetName()`, se pierde al reabrir. Reutilizar la política del Pin: espejo del nombre en el contenedor propio, que solo se re-aplica cuando se detecta el reset (`_sync_display_name` en `pin_tag.py` — **leerla, no re-derivarla**), enganchada al `Execute` del tag.

- [ ] **Step 8: VERIFICACIÓN LIVE (pedir `./sync.sh` + reinicio de C4D al coordinador)**

Nada de esto lo puede decir pytest. Reportar cada punto con la lectura, no con "OK":

1. Crear un conjunto sobre **un** objeto: el anclaje aparece en el sitio del original (mismo padre y misma posición entre hermanos), la transformación en el mundo del objeto es idéntica (leer `GetMg()` antes y después, tolerancia `1e-6`).
2. Crear un conjunto sobre **varios** objetos a la vez (un setup de luces): los tres entran en la opción A en el mismo orden, y sus transformaciones se conservan.
3. Crear un conjunto sobre un padre **y** su hijo seleccionados a la vez: se envuelve una sola vez.
4. **Un solo Cmd+Z** (menú Edit, contando pasos) revierte la creación entera y la escena queda exactamente como estaba — **re-buscando los objetos en el documento**, nunca leyendo los manejadores previos (spike del Pin §2).
5. Con dos opciones, cambiar de A a B: B queda bajo el anclaje, A dentro del contenedor de aparcado en la raíz con visibilidad apagada, y el Object Manager enseña cuál está puesta.
6. **Un solo Cmd+Z** revierte el cambio de opción completo (las dos mitades).
7. **El oráculo de aislamiento, repetido sobre el sistema real**: montar el anclaje bajo un Cloner con la opción A activa y aplicar *Current State to Object*; comparar el conteo de polígonos con el de la misma escena donde la opción B **nunca existió**. Tienen que ser iguales — es la promesa entera del sistema ("la escena se comporta exactamente como si B no existiera") y es la única forma de comprobarla de verdad.
8. Guardar, cerrar, reabrir: las opciones siguen, el nombre del conjunto sigue, la activa sigue siendo la activa, y cambiar de opción sigue funcionando (los `BaseLink` resolvieron tras la carga).
9. Un enlace que apunte **dentro** de una opción (una constraint) sigue resolviendo tras cambiar de opción y tras guardar+cargar — o queda anotado el caso exacto en que no, con el tipo de tag, para la fila de límites de la Tarea 6.

- [ ] **Step 9: commit**

```bash
git add plugin/sentinel/ui/variant_tag.py plugin/res plugin/sentinel_panel.pyp tests/test_variant_tag.py
git commit -m "feat(variants): tag, crear conjunto y cambiar de opcion en un solo undo"
```

---

### Task 4: duplicar, renombrar y borrar opciones

**Files:** modificar `plugin/sentinel/ui/variant_tag.py`, `tests/test_variant_tag.py`; `plugin/sentinel/variants.py` solo si aparece lógica pura nueva.

**Consume:** `variants.dedupe_option_name`, `variants.plan_delete`, `variants.next_option_name`.

**Produce:** `duplicate_active_option(tag) -> dict`, `rename_option(tag, index, name) -> dict`, `delete_option(tag, index) -> dict`.

- [ ] **Step 1: duplicar la opción activa**

Es el gesto que sustituye al "Cmd+C y arrastrar al backup" de hoy, así que tiene que dejar al artista **trabajando sobre la copia**. En un bracket:
1. Clonar el null de la opción activa **con su subárbol** (`GetClone(c4d.COPYFLAGS_0)` — el clon se lleva jerarquía, parámetros, pistas de animación con sus claves y **tags de material apuntando a los mismos materiales**, que es la razón por la que el Material Manager no engorda; verificarlo en vivo, no asumirlo).
2. Nombrarlo con `variants.dedupe_option_name(variants.next_option_name(nombres), nombres)`.
3. Aparcar la activa, montar el clon, escribir el payload con la nueva opción y `active` apuntando a ella.
4. Un solo `StartUndo`/`EndUndo` para todo.

- [ ] **Step 2: renombrar**

El campo de nombre por fila escribe el nombre de la **opción** (el string del payload) y el nombre del **null de la opción** a la vez — el segundo es lo que el artista ve en el Object Manager. Pasar siempre por `variants.dedupe_option_name` (dos opciones con el mismo nombre son indistinguibles en la fila y en los nombres de archivo del render). Un solo undo.

Ojo con la lección del Pin: el nombre del **conjunto** es el del tag y no se toca aquí; el de la **opción** es dato propio y sí.

- [ ] **Step 3: borrar**

`variants.plan_delete` decide qué se borra y **qué queda activo** después. En un bracket: si se borra la activa, montar primero la que promociona el plan y luego borrar; `AddUndo(UNDOTYPE_DELETEOBJ, ...)` antes de `Remove()` (patrón ya en uso en `fixes.py` y `scene_tools.py`), y el payload reescrito. **Sin confirmación**: borrar una opción borra su contenido y es revertible con un Cmd+Z como todo lo demás (el spec lo dice explícitamente) — y esa reversibilidad se comprueba en vivo, no se promete.

`plan_delete` rechaza borrar la última opción (`last_option`): el resultado se dice en la fila, no en un diálogo.

- [ ] **Step 4: tests del adaptador (contra el fake, con su límite escrito)**

1. Duplicar con el conjunto en "Opción A" produce "Opción B", la deja activa, y `read_state` la ve montada.
2. Duplicar dos veces produce "Opción C", no un segundo "Opción B".
3. Renombrar a un nombre ya usado guarda `"hero (2)"` en el payload **y** en el null.
4. Borrar la opción **anterior** a la activa deja activa la misma opción (por nombre, no por índice — es el test que caza el fallo de desplazamiento de índices con datos reales).
5. Borrar la única opción devuelve `last_option` y no abre bracket.
6. Cada mutación abre **exactamente un** `StartUndo`/`EndUndo`.

- [ ] **Step 5: verificación por mutación**

Romper, en el adaptador, el paso de `new_active` del plan al payload (escribir el índice pedido en vez del que devuelve `plan_delete`) y comprobar que falla el test 4. Reportarlo.

- [ ] **Step 6: VERIFICACIÓN LIVE (pedir reinicio)**

1. **Una variante de cada área real del spec**, que es el criterio de terminado: **estructura** (opción A con un Bend, opción B sin él — cambiar de una a otra y comprobar que el Bend deja de deformar de verdad, no solo que desaparece de la lista); **valores** (dos intensidades de luz); **curvas** (dos timings distintos del mismo objeto — comprobar leyendo las claves en dos frames, no de vista).
2. Duplicar una opción con materiales asignados: el **Material Manager no crece** (contar materiales antes y después — el límite honesto nº2 del spec, verificado en vez de citado).
3. Renombrar en la fila cambia el nombre en el Object Manager y sobrevive a guardar+reabrir.
4. Borrar una opción y **un solo Cmd+Z** la trae de vuelta entera, con su subárbol y su sitio en la lista.
5. Cada una de las cuatro acciones: **un solo paso de deshacer, contado**.

- [ ] **Step 7: commit**

```bash
git add plugin/sentinel tests/test_variant_tag.py
git commit -m "feat(variants): duplicar, renombrar y borrar opciones — un undo por gesto"
```

---

### Task 5: renderizar todas las opciones

**Files:** modificar `plugin/sentinel/ui/variant_tag.py`; `plugin/sentinel/variants.py` (ya trae `render_image_stem`); tests.

Es la sustituta de la salida a Takes, que el spike descartó por mecanismo. El objetivo del spec es exacto: **sin montaje manual, con las imágenes nombradas por opción**.

- [ ] **Step 1: SONDA LIVE BLOQUEANTE — ¿cómo se lanza un render desde aquí?**

**No hay ni un solo `RenderDocument` en el plugin hoy** (verificado por grep en `plugin/`): esto no tiene patrón previo en la casa y no se puede diseñar a ciegas. Medir en C4D vivo, con el motor real de la escena de trabajo (Redshift), y anotar los resultados en el spike de la Tarea 1 como §4:

1. `c4d.documents.RenderDocument(doc, rd.GetDataInstance(), bmp, c4d.RENDERFLAGS_EXTERNAL)` sobre un documento pequeño: ¿devuelve `RENDERRESULT_OK`? ¿el `BaseBitmap` trae píxeles distintos de cero? (**caso base**: renderizar una escena vacía y otra con un objeto iluminado y comprobar que difieren — un bitmap negro devuelto por una llamada "correcta" es exactamente el resultado nulo que parece una respuesta).
2. ¿Bloquea el hilo principal mientras rinde? ¿Se puede llamar N veces seguidas en un bucle sin colgar C4D?
3. ¿`bmp.Save(path, formato, None, c4d.SAVEBIT_0)` escribe el archivo, y con qué formato/extensión (`c4d.FILTER_PNG`, `FILTER_EXR`)?
4. ¿Qué pasa con Redshift concretamente? Si `RENDERFLAGS_EXTERNAL` no le vale, probar sin ese flag y reportar.

**Regla de decisión, escrita antes de medir:**
- Si (1)+(3) funcionan → esa es la implementación: bucle de opciones, `RenderDocument` a bitmap, `Save` con `variants.render_image_stem`.
- Si no → segunda vía a medir: fijar la ruta de salida del render por opción y lanzar el render nativo (`c4d.CallCommand(12099)`, Render to Picture Viewer) **una opción por vez**, con el problema conocido de que es asíncrono y hay que esperar (`c4d.threading.GeIsRunning`/`CheckIsRunning(CHECKISRUNNING_EXTERNALRENDERING)` — el mismo predicado que `renderwatch.py` de la v1.30 ya usa; **leerlo antes de escribir otro**).
- Si **ninguna** de las dos vías funciona, **PARAR y reportar**. No se entrega un botón que no rinde: sería exactamente el "no-op silencioso" contra el que este proyecto lleva tres releases escribiendo reglas.

- [ ] **Step 2: implementar `render_all_options(tag)`**

Contrato, y cada punto está por una razón:
- Recuerda cuál era la opción activa y **la deja montada al terminar**, pase lo que pase (`try/finally`). Una herramienta de enseñar opciones que deja la escena en la última no es aceptable.
- Recorre las opciones **en el orden de la lista**, no en el de aparcado.
- Cada imagen sale a `variants.render_image_stem(nombre_escena, nombre_conjunto, nombre_opción)` dentro de la carpeta de salida del render de la escena (o la del documento si no hay ninguna configurada — y si tampoco hay documento guardado, devolver `unsaved_scene` sin renderizar nada, porque no hay dónde escribir).
- **Los cambios de opción del recorrido NO son gestos del artista**: van en un único bloque, y al terminar la escena está como estaba. Verificar en vivo qué deja esto en la pila de undo y **decirlo en el reporte del plan** — lo aceptable es que no deje pasos (nada cambió al final) o que deje uno; lo inaceptable es dejar 2N pasos que el artista tenga que deshacer uno a uno.
- Reporta siempre: `{"ok": bool, "rendered": int, "failed": [(nombre, motivo)], "folder": str}`. Un fallo de una opción **no aborta** el resto (patrón del lote de matwire).

- [ ] **Step 3: tests**

Puros, sobre `render_image_stem` (ya escritos en la Tarea 2) más, en `test_variant_tag.py`: que `render_all_options` sobre un documento sin guardar devuelve `unsaved_scene` sin renderizar; que restaura la opción activa incluso cuando el render de una opción lanza (fake que revienta en la segunda opción → la activa original queda montada y esa opción sale en `failed`).

- [ ] **Step 4: VERIFICACIÓN LIVE (pedir reinicio)**

1. Tres opciones → tres imágenes en disco, **abiertas y miradas**: son distintas entre sí y cada una corresponde a su nombre de archivo (una herramienta que rinde tres veces la misma opción y les pone tres nombres distintos pasaría cualquier comprobación que solo cuente archivos).
2. Al terminar, la opción que estaba puesta sigue puesta.
3. Pasos de undo que deja el recorrido: contarlos y anotarlos.
4. Un nombre de opción con acentos y espacios produce un archivo con nombre válido y legible.

- [ ] **Step 5: commit**

```bash
git add plugin/sentinel tests/
git commit -m "feat(variants): renderizar todas las opciones con las imagenes nombradas por opcion"
```

---

### Task 6: límites en la fila, versión y documentación

**Files:** modificar `plugin/sentinel/ui/variant_tag.py`, `plugin/sentinel/__init__.py`, `CLAUDE.md`, `docs/superpowers/specs/2026-08-05-sentinel-variants-design.md`.

- [ ] **Step 1: los límites, en la fila**

`variants.warning_text` ya cubre el peso y las opciones perdidas. Completar la línea con lo que las Tareas 3-5 hayan **medido** (no con lo que suponíamos):
- Si algún tipo de enlace se rompió al aparcar (Tarea 1 §2 / Tarea 3 §9), decirlo cuando el conjunto tenga uno de esos.
- Si el recorrido del render deja pasos de undo, decir cuántos antes de lanzarlo.

Los que **no** van a la fila y por qué: "los materiales no se duplican" es una buena noticia, no un límite (y su sitio es la documentación); "borrar una opción borra su contenido" ya lo dice el propio botón.

Cada texto nuevo, con su test en `test_variants.py` y su verificación por mutación.

- [ ] **Step 2: versión**

`PLUGIN_VERSION = "1.36.0"` en `plugin/sentinel/__init__.py`; actualizar la cabecera de `CLAUDE.md` y el encabezado `## Current Status`.

- [ ] **Step 3: documentación**

Entrada de v1.36.0 en **las dos** listas de `CLAUDE.md` ("What Works" y "Version History Summary"), al estilo de la casa: qué hace; **los números medidos** del spike de aislamiento (2584 oculto = no aísla; 24 desactivado ≠ 54 fuera) y del spike de reparentado de la Tarea 1 (la variante de `AddUndo` que ganó y las que no, el veredicto de los `BaseLink`, el de la transformación); por qué los Takes quedaron fuera **dos veces** (por producto y luego por mecanismo); el límite honesto del peso y por qué es inseparable de que la herramienta funcione donde el Pin no llega; los recuentos reales de suite observados; y la matriz live como `**LIVE-VERIFIED**` con la versión de C4D — nunca un marcador de pendiente si ya se corrió.

`**Estado**:` del spec → `implementado y live-verified en rama feat/sentinel-variants (pytest N)`.

- [ ] **Step 4: suite completa y commit**

`python3 -m pytest tests/ -q` — reportar el número real observado (baseline 1252 + lo añadido).

```bash
git add plugin/sentinel/__init__.py CLAUDE.md docs/superpowers/specs/2026-08-05-sentinel-variants-design.md plugin/sentinel/ui/variant_tag.py tests/
git commit -m "docs: v1.36.0 — Sentinel Variants"
```

---

## Después del plan (nivel sesión)

1. Review adversarial de toda la rama en el modelo más capaz; corregir Critical/Important.
2. Eyeball del usuario en C4D (las matrices de las Tareas 3-5 son de motor; el artista dice si las filas se leen bien y si los gestos se sienten bien).
3. Merge `--no-ff`; actualizar memoria.
4. **Deuda anotada por el spec, sin versión propia**: auditar en C4D vivo que cada operación destructiva de Sentinel se revierte con un solo Cmd+Z (tiene evidencia real detrás — matwire con más de un material, y una rama del pin que escribía fuera del bloque de undo).
