# Sentinel Pin (v1.35) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `Sentinel Pin` tag, one tag per saved state, that stores its object and every descendant and restores it in one undo step — per `docs/superpowers/specs/2026-07-31-sentinel-pin-design.md`.

> **NOTA (2026-07-31, a media ejecución).** El Goal y las Global Constraints de abajo describían el modelo original — seis slots dentro de un tag — y se dejaron sin corregir cuando ese modelo se abandonó. El cambio real ocurrió en la Task 3 (marcada REHECHA más abajo): la primera implementación (commit `6f0fcea`) construyó un grid de seis filas dentro de un solo tag, y al verlo en vivo el texto de estado se truncaba (`4 obj · hace`) — y con él desaparecía el aviso de geometría, que el spec declara obligatorio, porque las columnas del Attribute Manager reparten ancho entre campos que compiten. Ver además la interfaz real de Recall (captura del usuario) mostró que su modelo es **un tag por estado**, lo cual además cumple mejor la promesa que justificaba usar un tag en primer lugar — ver los estados en el Object Manager sin abrir nada — que seis slots dentro de UN tag rompía. El texto de esta cabecera queda corregido al modelo final; el registro de por qué cambió vive aquí y en la Task 3.

**Architecture:** A pure engine (`pins.py`, no `import c4d`) owns everything decidable without a scene: the deterministic traversal order, the location key used to re-pair objects on restore, and the restore plan (matched / missing / extra). A thin TagData adapter (`ui/pin_tag.py`) reads and writes the live objects and renders the Attribute Manager rows. Storage is the tag's own `BaseContainer`, so pins travel inside the `.c4d` with no sidecar.

**Tech Stack:** Python (pure engine + the repo's fake-c4d pytest harness), `c4d.plugins.TagData` with a dynamic `GetDDescription`, `plugin/res/` description triplet.

**Branch:** `feat/sentinel-pin` (create from `main` before Task 1).

## Global Constraints

- **One tag = one pin.** Several pins on the same object are several tags, each with its own name. Plus one reserved tag (`↩ Antes de restaurar`, "Before restore"), written by the tool on every restore, never by the artist.
- **Captures**: each covered object's own `BaseContainer`, its local matrix, and its name — for the tag's object AND all descendants.
- **Does NOT capture** editable geometry (points/polygons) or maxon node graphs. Where a covered object has editable geometry the row says so, at store time, in the UI — never only in docs.
- **Re-pairing on restore is BY LOCATION, never by any C4D id**: no native id survives a save (`GetGUID()` and `FindUniqueID(MAXON_CREATOR_ID)` are both regenerated — measured, and the cause of the v1.34.1 baseline bug). The key is the name path from the tag's object down to the node, plus the index among same-named siblings, defined INSIDE the pin's subtree so moving the whole rig does not invalidate its pins.
- **Restore never creates or deletes objects.** Objects that no longer exist are reported; objects that appeared since are left alone.
- **One undo step** per restore, and per store.
- **Restore never asks for confirmation** — it is reversible twice over (Cmd+Z and the reserved slot).
- **Report, never fail silently**: every restore returns matched/missing counts and the missing keys.
- Tag plugin id is **`2099078`** (verified free in the `2099xxx` range; `2099069`/`2099073`/`2099075`/`2099077` in use, `2099072` retired).
- Suites: `python3 -m pytest tests/ -q`. Baseline entering this plan: **1149 passing**.
- Plugin Python only loads on a **full C4D restart**; `./sync.sh` copies the plugin into the active prefs folder.

## File Structure

- `plugin/sentinel/pins.py` — NEW, pure: traversal order, location keys, restore planning, slot model. No `import c4d`.
- `plugin/sentinel/ui/pin_tag.py` — NEW: the TagData. Description UI, capture from live objects, restore into them, undo bracketing.
- `plugin/res/description/Tsentinelpin.res` + `.h`, `plugin/res/strings_us/description/Tsentinelpin.str` — NEW triplet (C4D requires one for a tag with a description; `Tsentinelframe` is the template).
- `plugin/sentinel_panel.pyp` — register the tag.
- `tests/test_pins.py` — NEW, pure-engine tests.
- `docs/research/2026-07-31-pin-storage-spike.md` — NEW, Task 1's evidence.

---

### Task 1: Live spike (BLOCKING — a "no" on step 1 changes the storage design)

**Files:** Create `docs/research/2026-07-31-pin-storage-spike.md`

Run every probe through `mcp__cinema4d__batch` `exec_python` against the live C4D. Build on a `c4d.documents.BaseDocument()` you create locally and never insert into the document list; remove anything you do insert. If C4D is unreachable, report **BLOCKED** — do not guess.

- [ ] **Step 1: Does a nested BaseContainer inside a TAG survive save + reload?**

This is the decision the whole storage model rests on. The spec chose "no sidecar, pins live in the tag" on the strength of a container nesting inside another container **in memory**; nobody has checked that it round-trips through the `.c4d`.

Build a doc with an object carrying any tag; put a `BaseContainer` holding a string, a float, a `Vector` and a nested sub-container into the tag's container at a private id; save; load; read it all back. Report each value and whether it matched.

If it does NOT survive, STOP and report — the design needs a sidecar (`<base>_pins.json`), which is a different spec.

- [ ] **Step 2: Does `SetData` on a live object participate in one undo step?**

Insert an object into a real document, `doc.StartUndo()`, `doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)`, mutate via `SetData` + `SetMl` + `SetName`, `doc.EndUndo()`, then `doc.DoUndo()`. Report whether all three came back with a single undo. Repeat with three objects changed inside one bracket and confirm ONE `DoUndo()` reverts all three — that is the "one undo step" constraint, and `DoUndo()` from a script is not a perfect proxy for Cmd+Z, so ALSO report the `Edit` menu's undo label (`c4d.CallCommand(12105)` is the menu undo; check the resulting object state).

- [ ] **Step 3: Do per-row `DTYPE_BUTTON`s work inside a multi-column description group?**

The rows need three buttons each. `frame_tag.py:1775-1781` shows a button needs `DESC_CUSTOMGUI = CUSTOMGUI_BUTTON` to render. Build a throwaway TagData with a 4-column group holding 7 rows of (string, button, button, button), register it, put it on an object, and confirm in the Attribute Manager that the buttons render and that `MSG_DESCRIPTION_COMMAND` reports WHICH id was pressed. Report the id shape you receive.

- [ ] **Step 4: How is editable geometry detected?**

The UI must say "geometry not included" when a covered object has it. Probe: for a parametric cube, a polygon object, a null and a camera, report `isinstance(obj, c4d.PointObject)` and `obj.GetPointCount()` where applicable. Record the exact test the writer should use.

- [ ] **Step 5: Write the spike doc and commit**

One section per step: the question, the exact probe, the raw output, the verdict. State plainly anything that did not work.

```bash
git add docs/research/2026-07-31-pin-storage-spike.md
git commit -m "docs: spike — almacenamiento de pins en el tag, undo, botones por fila"
```

### Task 2: Pure engine (`pins.py`)

**Files:** Create `plugin/sentinel/pins.py`; create `tests/test_pins.py`.

**Interfaces produced:**
- `MAX_SLOTS = 6`, `RESERVED_SLOT = 6` (the seventh index, "Before restore")
- `location_keys(names_tree) -> list[str]` — deterministic traversal + key per node
- `plan_restore(pinned_keys, current_keys) -> dict` with `matched`, `missing`, `extra`
- `slot_summary(slot) -> dict` with `filled`, `label`, `count`, `has_geometry`

The engine never sees a C4D object. It works on a plain nested description of the subtree so it can be tested directly:

```python
# a node is {"name": str, "geometry": bool, "children": [node, ...]}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pins.py`:

```python
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS_PATH = ROOT / "plugin" / "sentinel" / "pins.py"
spec = importlib.util.spec_from_file_location("sentinel_pins_under_test", PINS_PATH)
pins = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pins
spec.loader.exec_module(pins)


def node(name, children=(), geometry=False):
    return {"name": name, "geometry": geometry, "children": list(children)}


def test_keys_are_relative_to_the_pinned_root():
    """Keys start at the tag's object, NOT at the scene root, so moving the
    whole rig somewhere else does not invalidate its pins."""
    tree = node("rig", [node("ctrl"), node("geo")])
    assert pins.location_keys(tree) == ["", "ctrl", "geo"]


def test_same_named_siblings_get_indices_in_traversal_order():
    tree = node("rig", [node("Cube"), node("Cube"), node("Sphere")])
    assert pins.location_keys(tree) == ["", "Cube[0]", "Cube[1]", "Sphere"]


def test_nesting_is_encoded_in_the_path():
    tree = node("rig", [node("arm", [node("hand")])])
    assert pins.location_keys(tree) == ["", "arm", "arm/hand"]


def test_traversal_is_depth_first_and_stable():
    """Restore pairs by key, but the ORDER also has to be stable so a pin
    written today lines up with a plan computed tomorrow."""
    tree = node("rig", [node("a", [node("a1"), node("a2")]), node("b")])
    assert pins.location_keys(tree) == ["", "a", "a/a1", "a/a2", "b"]


def test_restore_plan_reports_missing_and_extra():
    """Restore never creates or deletes: what vanished is reported, what
    appeared since is left alone."""
    plan = pins.plan_restore(["", "ctrl", "geo"], ["", "ctrl", "newthing"])
    assert plan["matched"] == ["", "ctrl"]
    assert plan["missing"] == ["geo"]
    assert plan["extra"] == ["newthing"]


def test_restore_plan_with_nothing_left_matches_nothing():
    plan = pins.plan_restore(["", "ctrl"], [])
    assert plan["matched"] == []
    assert plan["missing"] == ["", "ctrl"]


def test_slot_summary_of_an_empty_slot():
    assert pins.slot_summary(None) == {
        "filled": False, "label": "", "count": 0, "has_geometry": False}


def test_slot_summary_reports_geometry_so_the_row_can_warn():
    """The row must say "geometry not included" at STORE time — the artist
    who pins a polygon object will otherwise expect the modelling back."""
    slot = {"label": "wide", "entries": [
        {"key": "", "geometry": False}, {"key": "geo", "geometry": True}]}
    summary = pins.slot_summary(slot)
    assert summary == {
        "filled": True, "label": "wide", "count": 2, "has_geometry": True}


def test_reserved_slot_is_the_seventh_and_not_an_artist_slot():
    assert pins.MAX_SLOTS == 6
    assert pins.RESERVED_SLOT == 6
```

- [ ] **Step 2: Run them — expect failure**

Run: `python3 -m pytest tests/test_pins.py -q`
Expected: FAIL, `ModuleNotFoundError`/`AttributeError` — `pins.py` does not exist.

- [ ] **Step 3: Implement `pins.py`**

```python
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
```

- [ ] **Step 4: Run them — expect pass**

Run: `python3 -m pytest tests/test_pins.py -q`
Expected: 9 passed.

- [ ] **Step 5: Mutation-check the two load-bearing rules**

Apply each, confirm the named test fails, revert, and report both:
1. Make `location_keys` index EVERY sibling (`part = "%s[%d]" % (name, index)` unconditionally) → `test_keys_are_relative_to_the_pinned_root` must fail.
2. Make `plan_restore` put unmatched pinned keys into `matched` → `test_restore_plan_reports_missing_and_extra` must fail.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/pins.py tests/test_pins.py
git commit -m "feat(pins): motor puro — claves de ubicacion, orden de recorrido, plan de restauracion"
```

> **CORRECCIÓN (2026-07-31, review de la Tarea 2).** La implementación de
> referencia de `location_keys` que aparece arriba **produce claves que
> colisionan** y NO debe copiarse tal cual. Cuatro casos verificados: un objeto
> llamado literalmente `Cube[0]` junto a duplicados `Cube`; un nombre con `/`
> junto a una ruta anidada equivalente; un hijo con nombre vacío contra la raíz;
> y varios hijos sin nombre. Como la clave es lo ÚNICO que reempareja estado con
> objeto, una colisión aplica el estado al objeto equivocado **en silencio**.
>
> El código correcto **escapa** `\`, `/` y `[` en cada nombre y **indexa
> siempre** (`nombre[i]`), no solo a los duplicados. Eso además arregla una
> inestabilidad que nadie había visto: un hijo único pasaba de `ctrl` a
> `ctrl[0]` en cuanto aparecía un hermano homónimo, invalidando en silencio
> todos los pins existentes. Ver el fichero real `plugin/sentinel/pins.py`.

### Task 3 (REHECHA): un tag = un pin

> **Por qué se rehace.** La Tarea 3 original construyó un grid de seis slots dentro de un tag. Al verlo en vivo, el texto de estado **se truncaba** (`4 obj · hace`) y con él desaparecía la advertencia de geometría, que el spec declara obligatoria — las columnas del Attribute Manager reparten ancho entre campos que compiten. Y al ver la interfaz real de Recall quedó claro que su modelo es **un tag por estado**, lo cual cumple mejor la promesa que justificaba poner esto en un tag ("ves los estados en el Object Manager") y elimina el problema de layout en vez de maquillarlo. Ver la corrección en el spec.
>
> **Lo que se conserva del commit `6f0fcea`**: el registro del tag (id 2099078), el triplete de `plugin/res/`, la captura del subárbol (`GetData`/`GetMl`/`GetName`), el almacenamiento en el contenedor del tag, la detección de geometría y la síntesis del texto de estado en `GetDParameter`. **Lo que se tira**: el grid de seis filas, los ids con stride por slot y el slot reservado como fila.

**Files:** modify `plugin/sentinel/ui/pin_tag.py`, `plugin/sentinel/pins.py`, `tests/test_pins.py`.

- [ ] **Step 1: El motor pierde el modelo de slots**

En `pins.py`, `MAX_SLOTS` y `RESERVED_SLOT` dejan de tener sentido: un tag es un pin. Sustituir por:

```python
#: Nombre del tag que la herramienta gestiona sola: el estado de ANTES de
#: cada restauración. El artista nunca lo crea ni lo nombra.
SAFETY_PIN_NAME = "↩ Antes de restaurar"
```

`slot_summary(slot)` pasa a `pin_summary(pin)` con la misma forma de entrada y una clave más:

```python
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
```

Actualizar los tests de `slot_summary` a `pin_summary` (mismos casos) y añadir uno que fije que `has_keyframes` se reporta. Borrar los tests de `MAX_SLOTS`/`RESERVED_SLOT` y añadir uno que fije `SAFETY_PIN_NAME`.

`location_keys` y `plan_restore` **no se tocan** — su corrección de colisiones se conserva íntegra.

- [ ] **Step 2: La descripción del tag pasa a una sola fila**

Sustituir el grid por: un campo `DTYPE_STRING` **Nombre**, un `DTYPE_STATICTEXT` **Estado** (no un campo: es solo lectura, y meterlo en una caja fue lo que truncó el texto y lo que invita a editarlo), y dos `DTYPE_BUTTON` — `Pin` y `Ir`. Sin grupo multi-columna: sin columnas que competir, no hay nada que desalinear.

Ids planos, sin stride:

```python
ID_PIN_NAME = 1001      # DTYPE_STRING     — nombre del pin (= nombre del tag)
ID_PIN_STATUS = 1002    # DTYPE_STATICTEXT — "12 obj · hace 2 h · …"
ID_PIN_STORE = 1003     # DTYPE_BUTTON     — "Pin"
ID_PIN_GO = 1004        # DTYPE_BUTTON     — "Ir"
ID_PIN_PAYLOAD = 20000  # sub-contenedor con el estado guardado
```

Al escribir el nombre, **propagarlo al nombre del tag** (`node.SetName(...)`): es lo que hace que el Object Manager lo muestre sin abrir nada, que es la mitad del argumento para que esto sea un tag.

El texto de estado añade `" · N con keyframes"` cuando `has_keyframes`, junto al aviso de geometría ya existente.

- [ ] **Step 3: Suites y commit**

`python3 -m pytest tests/ -q` (baseline 1163; el recuento cambia al reescribir los tests de slots).

```bash
git add plugin/sentinel tests/test_pins.py
git commit -m "feat(pin): un tag = un pin — fila unica, estado en texto estatico, aviso de keyframes"
```

### Task 4 (REVISADA): restaurar, el tag de seguridad y el doble clic

**Files:** modify `plugin/sentinel/ui/pin_tag.py`.

- [ ] **Step 1: `_restore(node)`**

En este orden, porque el orden ES la propiedad de seguridad:
1. Construir el subárbol actual y sus claves.
2. **Si este tag NO es el de seguridad**, capturar el estado actual en un tag `SAFETY_PIN_NAME` sobre el mismo objeto — creándolo si no existe, sobrescribiéndolo si ya está. Si eso falla, abortar la restauración: sin la red el artista no puede volver, y una restauración que se la salta en silencio es peor que no restaurar.
   **Si este tag SÍ es el de seguridad, no se sobrescribe** — destruiría la única copia del estado del que estás volviendo. Dejar el motivo en un comentario.
3. Si el `PIN_SCHEMA` guardado no es el de este build, parar y decirlo en la fila.
4. `pins.plan_restore(pinned_keys, current_keys)`.
5. Si `matched` está vacío, no tocar nada y reportar — sin abrir bracket de undo para un no-op.
6. Si no: `doc.StartUndo()`, y por cada clave emparejada `doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)` seguido de `SetData` / `SetMl` / `SetName`; `doc.EndUndo()`. Un solo bracket para todo el subárbol.
7. `c4d.EventAdd()`.

- [ ] **Step 2: Reportar**

Escribir el resultado en la fila de estado: `"9 de 12 restaurados · 3 no encontrados"`, o `"12 restaurados"` si no falta nada. Además `safe_print` de las claves que faltan — la fila no tiene sitio para una lista.

- [ ] **Step 3: Doble clic**

En `Message`, manejar `c4d.MSG_EDIT` (id 21) llamando a `_restore`. Es el atajo de Recall y el camino más rápido posible: restaurar sin pasar por el Attribute Manager.

**No se sabe si un tag lo recibe** — no se pudo medir en el spike. El botón `Ir` es el camino garantizado; esto es un acelerador. Si en la verificación live no llega, anotarlo como limitación y seguir: la función no depende de ello.

- [ ] **Step 4: Verificación live (pedir reinicio al coordinador)**

1. Pin de un rig paramétrico (Cloner + Effector + falloff), destrozar los tres (parámetros Y transformaciones), restaurar, y comprobar los tres **leyendo parámetros**, no de vista. **Tras el undo hay que RE-BUSCAR el objeto en el documento**: C4D lo reemplaza al restaurar y el handle previo queda huérfano mostrando los valores mutados (spike §2 — esta trampa ya hizo creer que el undo estaba roto).
2. Un objeto de plugin de terceros en la jerarquía restaura igual (la captura es genérica).
3. Borrar un objeto y añadir otro: conteos y reporte correctos.
4. **Un solo Cmd+Z** (menú Edit) revierte la restauración entera.
5. El tag `↩ Antes de restaurar` aparece tras el primer salto y devuelve al estado previo; restaurar desde él NO lo sobrescribe.
6. Dos pins sobre el mismo objeto conviven y cada uno restaura el suyo.
7. Doble clic en el tag restaura (o queda anotado que `MSG_EDIT` no llega).
8. Guardar, reabrir, y comprobar que los pins siguen y siguen restaurando.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/pin_tag.py
git commit -m "feat(pin): restaurar con tag de seguridad, un solo undo, reporte y doble clic"
```

### Task 5 (NUEVA): icono por pin — color y carácter

> **Por qué entra en v1.35 y no después.** Elegimos *un tag por pin* argumentando que se ven los estados en el Object Manager sin abrir nada. Sin icono propio, varios pins se ven como iconos idénticos: el hueco ataca la razón misma del modelo. Referencia: Recall dedica una sección entera a esto.

**Files:** modify `plugin/sentinel/ui/pin_tag.py`, `plugin/sentinel/pins.py`, `tests/test_pins.py`.

Medido en el spike (§5) — usar estos hechos, no re-descubrirlos: `MSG_GETCUSTOMICON` = 1001090; `IconData` con campos `bmp/x/y/w/h/flags`; `GeClipMap.Init(32,32,32)` + `SetColor`/`FillRect` + `GetDefaultFont(GE_FONT_DEFAULT_SYSTEM)` + `SetFont` + `TextAt` **dibujan de verdad** (95 píxeles frente a 0); `SetFont(None, ...)` lanza.

- [ ] **Step 1: motor puro** — en `pins.py`, la paleta y la derivación del carácter:

```python
#: Paleta de identidad del pin. Siete tonos legibles sobre el fondo oscuro
#: del Object Manager, más "sin color" como valor por defecto — un pin sin
#: personalizar debe verse como el icono normal del plugin, no como un color
#: elegido al azar por nosotros.
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
```

Tests: paleta con `none` primero; `pin_badge("wide angle", 0) == "W"`; `pin_badge("", 2) == "3"`; `pin_badge("  ", 0) == "1"`; un nombre unicode devuelve su primera letra.

- [ ] **Step 2: parámetro de color en el tag** — un `DTYPE_LONG` con ciclo (`ID_PIN_COLOR = 1005`) construido desde `PIN_COLORS`, `animatable=False`, etiqueta `Color`. Default `none`.

- [ ] **Step 3: el icono** — responder a `MSG_GETCUSTOMICON` en `Message`: si el color es `none`, devolver False (icono normal del plugin). Si no, componer con `GeClipMap` el fondo del color y `pin_badge(...)` encima en blanco, y rellenar el `IconData` que llega en `data`. Cachear el bitmap por (color, carácter) — este mensaje se dispara al pintar el Object Manager, así que regenerarlo en cada llamada es coste por frame.

- [ ] **Step 4: verificación live (pedir reinicio)** — tres pins con colores distintos sobre un objeto se distinguen en el Object Manager; el pin sin color se ve como el icono normal; cambiar el color repinta; el carácter refleja el nombre y cambia al renombrar. **Si `MSG_GETCUSTOMICON` no llega a un TagData, reportarlo** — no es una limitación aceptable aquí, porque es la razón de la tarea.

- [ ] **Step 5: commit** `feat(pin): icono por pin — color y carácter en el Object Manager`

### Task 6 (NUEVA): keyframes

> **Por qué entra.** Hoy el pin solo **avisa** de que hay pistas de animación. Si un parámetro está animado, reponer su valor no cambia nada visible —la pista lo sobrescribe en el siguiente frame— así que el pin es un no-op silencioso justo en los rigs animados, que son media razón de ser de la herramienta. Recall los captura.

**Files:** modify `plugin/sentinel/pins.py`, `plugin/sentinel/ui/pin_tag.py`; tests.

- [ ] **Step 1: SPIKE live (bloqueante)** — antes de escribir nada, medir en C4D y anotar en `docs/research/2026-07-31-pin-storage-spike.md` §6:
  1. Qué expone una `CCurve`/`CKey` que haya que guardar para reproducir una pista: tiempo, valor, interpolación, tangentes. Listar los getters reales.
  2. Si una `CTrack` se puede **clonar** (`GetClone`) y re-insertar en el objeto — sería mucho más fiable que serializar claves a mano.
  3. Si un `BaseContainer` puede guardar lo necesario, o hace falta otra representación.
  4. Cómo se identifica una pista para reemparejarla al restaurar (su `DescID`).
  `plugin/sentinel/keyframes.py` (v1.30) ya recorre `CTrack`s incluidas las de tags — leerlo antes.

- [ ] **Step 2 en adelante:** el plan concreto lo fija el spike. Restricciones que NO cambian: un solo paso de undo; restaurar no crea ni borra objetos; lo que no se reencuentre se reporta; y el aviso `" · N con keyframes"` se sustituye por la captura real cuando esté.

### Task 5: Docs and version

- [ ] **Step 1:** `PLUGIN_VERSION = "1.35.0"` in `plugin/sentinel/__init__.py`; update the CLAUDE.md header and the `## Current Status` heading.
- [ ] **Step 2:** Add a v1.35.0 entry to BOTH the "What Works" list and "Version History Summary", house style: what it does, the Task 1 spike's measured facts with their numbers, the reserved-slot rationale, what it deliberately does not capture and why, the location-key weakness inherited from the identity finding, and real suite counts you observed. End with the live matrix as `**LIVE-VERIFIED**` (Task 4 ran it) rather than a pending marker.
- [ ] **Step 3:** Set the spec's `**Estado**:` to `implementado y live-verified en rama feat/sentinel-pin (pytest N)`.
- [ ] **Step 4:** Full suite, then commit `docs: v1.35.0 — Sentinel Pin`.

---

## After the plan (session-level)

1. Whole-branch adversarial review on the most capable model; fix Critical/Important.
2. User eyeball in C4D (the Task 4 matrix is engine-level; the artist checks the AM rows read well and the buttons feel right).
3. Merge `--no-ff`; update memory; next: **v1.36**, the automatic document snapshot before Sentinel's destructive operations.
