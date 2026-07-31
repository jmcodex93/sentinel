# Sentinel Pin (v1.35) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `Sentinel Pin` tag that stores up to six named states of its object and every descendant, and restores any of them in one undo step — per `docs/superpowers/specs/2026-07-31-sentinel-pin-design.md`.

**Architecture:** A pure engine (`pins.py`, no `import c4d`) owns everything decidable without a scene: the deterministic traversal order, the location key used to re-pair objects on restore, and the restore plan (matched / missing / extra). A thin TagData adapter (`ui/pin_tag.py`) reads and writes the live objects and renders the Attribute Manager rows. Storage is the tag's own `BaseContainer`, so pins travel inside the `.c4d` with no sidecar.

**Tech Stack:** Python (pure engine + the repo's fake-c4d pytest harness), `c4d.plugins.TagData` with a dynamic `GetDDescription`, `plugin/res/` description triplet.

**Branch:** `feat/sentinel-pin` (create from `main` before Task 1).

## Global Constraints

- **Six artist slots + one reserved** ("Before restore"), written by the tool on every restore. Never more, never fewer.
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

### Task 3: The tag — registration, description UI, and storing a pin

**Files:** Create `plugin/sentinel/ui/pin_tag.py`, `plugin/res/description/Tsentinelpin.res`, `plugin/res/description/Tsentinelpin.h`, `plugin/res/strings_us/description/Tsentinelpin.str`; modify `plugin/sentinel_panel.pyp`.

**Interfaces consumed:** `pins.MAX_SLOTS`, `pins.RESERVED_SLOT`, `pins.location_keys`, `pins.slot_summary`.

Read `plugin/sentinel/ui/frame_tag.py` first — it is the working template for every mechanism here: `_description_parent`, `_set_description_parameter` (including the `DTYPE_BUTTON` + `DESC_CUSTOMGUI` requirement at line 1775), `_set_description_group(columns=...)`, and `Message` → `MSG_DESCRIPTION_COMMAND` → `_handle_command`. Copy the patterns, not the semantics.

- [ ] **Step 1: The resource triplet**

`plugin/res/description/Tsentinelpin.res`:

```
CONTAINER Tsentinelpin
{
	NAME Tsentinelpin;
	INCLUDE Tbase;

	GROUP ID_TAGPROPERTIES
	{
	}
}
```

`plugin/res/description/Tsentinelpin.h`: empty file (the ids are assigned dynamically in `GetDDescription`, exactly as `Tsentinelframe.h` does).

`plugin/res/strings_us/description/Tsentinelpin.str`:

```
STRINGTABLE Tsentinelpin
{
	Tsentinelpin "Sentinel Pin";
}
```

- [ ] **Step 2: Id layout**

In `pin_tag.py`, define the parameter ids. Slots are strided so a row's ids are derivable, the same way `frame_tag._format_ids` does it:

```python
ID_GROUP_SLOTS = 1000
ID_SLOT_BASE = 2000       # slot i occupies ID_SLOT_BASE + i * ID_SLOT_STRIDE
ID_SLOT_STRIDE = 10
ID_SLOT_LABEL = 0         # DTYPE_STRING  — editable name
ID_SLOT_INFO = 1          # DTYPE_STRING  — "12 obj · hace 2 h" (read-only text)
ID_SLOT_STORE = 2         # DTYPE_BUTTON  — "Pin aquí" / "Re-pin"
ID_SLOT_GO = 3            # DTYPE_BUTTON  — "Ir"
ID_SLOT_CLEAR = 4         # DTYPE_BUTTON  — "✕"
#: Pin payloads live under a private container id inside the tag's own
#: container, so they travel with the .c4d (Task 1 step 1 proved the
#: round-trip). Kept well clear of the description id range above.
ID_PIN_STORE_BASE = 20000

#: Bumped only if the payload shape changes. A pin whose schema this build
#: does not know is IGNORED with a note in its row — never applied
#: partially, because a half-applied rig is worse than an untouched one.
PIN_SCHEMA = 1
```

The row ids come from the stride, so nothing is hand-numbered:

```python
def _slot_ids(index):
    base = ID_SLOT_BASE + index * ID_SLOT_STRIDE
    return {"label": base + ID_SLOT_LABEL, "info": base + ID_SLOT_INFO,
            "store": base + ID_SLOT_STORE, "go": base + ID_SLOT_GO,
            "clear": base + ID_SLOT_CLEAR}


def _slot_from_id(param_id):
    """(slot index, action) for a pressed button id, or (None, None)."""
    offset = param_id - ID_SLOT_BASE
    if offset < 0:
        return None, None
    index, action = divmod(offset, ID_SLOT_STRIDE)
    if index > pins.RESERVED_SLOT:
        return None, None
    return index, {ID_SLOT_STORE: "store", ID_SLOT_GO: "go",
                   ID_SLOT_CLEAR: "clear"}.get(action)
```

- [ ] **Step 3: `GetDDescription` — six rows plus the reserved one**

One 5-column group holding every row's cells directly. `frame_tag.py:1911-1917` explains why a single grid instead of per-row sub-groups: per-row groups size their own columns from their own label width, so nothing lines up vertically.

For each of the six slots, in order: label (`DTYPE_STRING`), info (`DTYPE_STRING`), then Store / Go / Clear buttons. A slot that is empty shows only the Store button enabled; the spec's row mock is the target. The reserved row renders after a separator, with its info and a single `Ir` button, and NO label field — the artist does not name it.

The info cell is where the honest notes live. Build its text from
`pins.slot_summary(slot)`: `"12 obj · hace 2 h"`, and when `has_geometry` is
true append `" · geometría no incluida"`. That note is REQUIRED by the spec
and must appear at store time, not only in docs — an artist who pins a
polygon object will otherwise expect the modelling back, and it will not
come back. A slot whose stored `PIN_SCHEMA` this build does not recognise
shows `"pin de una versión anterior — no se aplicará"` and its `Ir` button
does nothing.

Every parameter is `animatable=False` (the Frame tag learned this live: animatable parameters render a diamond per row and the diamonds were the biggest cost in row width).

- [ ] **Step 4: Store a pin**

`_store_pin(node, slot_index)`:
1. Resolve the tag's object (`node.GetObject()`); if absent, return without touching anything.
2. Walk the object and all descendants depth-first, building both the `pins.location_keys` input tree and, per node, `{"key", "name", "geometry", "container", "matrix"}` — `obj.GetData()`, `obj.GetMl()`, `obj.GetName()`, and the geometry test recorded in Task 1 step 4.
3. Write the payload — including `PIN_SCHEMA` — into the tag's container under `ID_PIN_STORE_BASE + slot_index`, wrapped in `doc.StartUndo()` / `doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)` / `doc.EndUndo()` so storing is itself one undo step.
4. Stamp the slot's label (keep an existing one on re-pin; otherwise leave it empty for the artist to fill) and the timestamp.

- [ ] **Step 5: Register the tag**

In `plugin/sentinel_panel.pyp`, beside the Sentinel Frame registration (line ~179), register with `id=2099078`, `str="Sentinel Pin"`, `description="Tsentinelpin"`, `info=c4d.TAG_VISIBLE | c4d.TAG_EXPRESSION`. **No `TAG_IMPLEMENTS_DRAW_FUNCTION`** — this tag draws nothing, and that flag exists only to make `Draw` fire. Extend the id comment at line 25-27 to record `2099078` as taken.

- [ ] **Step 6: Verify live**

`./sync.sh`, restart C4D, add the tag to an object with children, and confirm: the tag appears in the tag list with its name, six rows render with aligned columns, the buttons are clickable, and pressing Store fills the row's info text with the object count. Report what you saw.

- [ ] **Step 7: Commit**

```bash
git add plugin/sentinel/ui/pin_tag.py plugin/res plugin/sentinel_panel.pyp
git commit -m "feat(pin): tag Sentinel Pin — registro, UI de seis slots y guardado"
```

### Task 4: Restore, the reserved slot, and the report

**Files:** Modify `plugin/sentinel/ui/pin_tag.py`.

- [ ] **Step 1: `_restore_pin(node, slot_index)`**

In this order, because the order IS the safety property:
1. Build the current subtree and its keys.
2. **Store the current state into `pins.RESERVED_SLOT` first** — before touching anything. If this fails, abort the restore: without the safety net the artist cannot get back, and a restore that silently drops it is worse than no restore.
3. If the stored payload's `PIN_SCHEMA` is not this build's, stop here and report it in the row — never apply a payload whose shape you do not know.
4. `pins.plan_restore(pinned_keys, current_keys)`.
5. If `matched` is empty, change nothing and report — do not open an undo bracket for a no-op.
6. Otherwise `doc.StartUndo()`, then for every matched key `doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)` followed by `SetData` / `SetMl` / `SetName`, then `doc.EndUndo()`. One bracket for the whole subtree — one Cmd+Z.
7. `c4d.EventAdd()`.

- [ ] **Step 2: Report the outcome**

Write the result into the slot's info field: `"9 de 12 restaurados · 3 no encontrados"` when anything is missing, `"12 restaurados"` when nothing is. Also `safe_print` the missing keys (`from sentinel.common.helpers import safe_print`), so the artist can see WHICH ones in the console — the row has no space for a list.

- [ ] **Step 3: Wire the buttons**

`Message` → `MSG_DESCRIPTION_COMMAND` → `_handle_command`, deriving the slot index and the action from the pressed id via the stride (`frame_tag._handle_command` is the template). Store / Go / Clear map to `_store_pin` / `_restore_pin` / `_clear_pin`. The reserved row's `Ir` restores slot `RESERVED_SLOT` and, per the spec, does NOT overwrite the reserved slot with the state it is leaving — otherwise going back would destroy the only copy of what you are returning FROM. Add a comment recording that.

- [ ] **Step 4: Verify live — the matrix from the spec**

`./sync.sh`, restart C4D, then:
1. Pin a parametric rig (Cloner + Effector + falloff), wreck all three (parameters AND transforms), restore, and verify each of the three by reading parameters back — not by eyeball.
2. Put a third-party plugin object in the hierarchy and confirm it restores too (the capture is generic).
3. Delete one object and add another, restore, and confirm the counts and the report.
4. **One Cmd+Z** (the Edit menu, not `DoUndo`) reverts a whole restore.
5. Restore, then use the reserved row to come back.
6. Save the scene, reopen it, and confirm the pins are still there AND still restore — the case the baseline bug proved must be tested explicitly.

Report each with what you observed.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/pin_tag.py
git commit -m "feat(pin): restaurar con slot reservado, un solo undo y reporte honesto"
```

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
