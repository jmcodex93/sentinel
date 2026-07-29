# Tools Quick-Wins (v1.30) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four Tools quick-wins from the approved spec `docs/superpowers/specs/2026-07-29-tools-quickwins-design.md`: Delete Empty Nulls, Clean Material Tags, Keyframe Offset/Stagger, and a render-complete notification.

**Architecture:** Two new dialog-free cores in `scene_tools.py` (cleanup), a new `keyframes.py` engine (pure stagger plan + thin c4d adapter over `CTrack`/`CCurve`), a new `renderwatch.py` (pure state machine ticked from the existing `FrameSyncMessageData`), four thin ops in `panel_tools_ops.py`, a `render_notify` setting through the existing settings pipeline (native dialog + SPA page), and the Tools section's first parameterized control (Frames field + Offset/Stagger).

**Tech Stack:** Python 3 (C4D 2026 plugin; pure modules importable without c4d; pytest fake-c4d harness via the `sentinel_module` fixture), Vite+React+TS SPA in `web/` (vitest), bundle committed to `plugin/web/`.

**Branch:** `feat/tools-quickwins` (create from `main` before Task 1).

## Global Constraints

- **No dialogs in op paths** — every op-reachable core returns a status dict; a `MessageDialog` inside the panel's queue drain freezes C4D. `_forbid_dialog` tests on every new op route (pattern: `tests/test_panel_tools_ops.py`).
- **Empty null** = `Onull` with no children (bottom-up cascade) and NO tags of any kind (any tag saves it). Spec decision 2.
- **Material tags**: delete `Ttexture` with dead/None material link + EXACT duplicates on the same object (same material AND same selection restriction), keeping the LAST of each duplicate group. Selection-orphans are out of scope. Spec decision 3.
- **Keyframe shift**: ALL `CTrack`s of selection + children, hierarchy-deduped; N integer, may be negative, `frames != 0`, clamp |frames| ≤ 10000. Stagger = per selection ROOT in Object Manager order, root i (and its children) shifted `i*frames`; children of a root do not stagger among themselves. Spec decision 4.
- **Key-shift iteration order**: shifting keys later in time (positive N) must iterate keys in REVERSE index order; negative N in forward order — otherwise a moved key collides with / reorders past its neighbor inside `CCurve` and the shift corrupts.
- **Render notification**: threshold 30 s, setting key `render_notify` (default ON = 1) in `sentinel_settings.json` via `GlobalSettings`; macOS `osascript` only; the frame_sync tick must NEVER be able to raise out of the render-watch call.
- **One undo per tool invocation** (cleanups and shifts each wrap their whole batch).
- Existing Tools ops/copys unchanged. No QC/registry changes.
- Run pytest as `python3 -m pytest tests/ -q`; vitest as `cd web && npx vitest run`; SPA build `cd web && npm run build` (bundle in `plugin/web/` is committed, never hand-edited).

## File Structure

- `plugin/sentinel/ui/scene_tools.py` — add `_delete_empty_nulls_core`, `_clean_material_tags_core`.
- `plugin/sentinel/keyframes.py` — NEW: pure planning helpers + c4d-bound shift/stagger.
- `plugin/sentinel/renderwatch.py` — NEW: pure `RenderWatch` machine + `tick_active_document()` adapter + `_notify_macos`.
- `plugin/sentinel/ui/frame_sync.py` — call the render-watch tick from `FrameSyncMessageData.CoreMessage`.
- `plugin/sentinel/ui/panel_tools_ops.py` — 4 new ops.
- `plugin/sentinel/webbridge.py` — `validate_settings_submit` gains `render_notify`.
- `plugin/sentinel/ui/web_ops.py` — settings state/submit carry `render_notify`.
- `plugin/sentinel/ui/dialogs.py` — native Settings dialog gains the checkbox (fallback parity).
- `web/src/lib/panelTools.ts`, `web/src/components/panel/ToolsSection.tsx`, `web/src/pages/PanelPage.tsx`, `web/src/lib/api.ts`, `web/src/pages/SettingsPage.tsx`, `web/src/types.ts` — SPA.
- Tests: `tests/test_panel_tools_ops.py` (cores + ops), `tests/test_keyframes.py` (NEW), `tests/test_renderwatch.py` (NEW), `tests/test_web_ops.py` + `tests/test_webbridge.py` (settings), `web/src/lib/panelTools.test.ts`.

---

### Task 1: Cleanup cores — `_delete_empty_nulls_core` + `_clean_material_tags_core`

**Files:**
- Modify: `plugin/sentinel/ui/scene_tools.py` (append after `_drop_to_floor_core`'s wrapper region)
- Test: `tests/test_panel_tools_ops.py` (append)

**Interfaces:**
- Produces: `scene_tools._delete_empty_nulls_core(doc) -> {"ok": True, "removed": int}` or `{"ok": False, "error": "no_document"|"none_found"}`.
- Produces: `scene_tools._clean_material_tags_core(doc) -> {"ok": True, "removed_broken": int, "removed_dupes": int}` or `{"ok": False, "error": "no_document"|"none_found"}`.
- Both single-undo, dialog-free, `safe_print` for feedback lines (existing idiom).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_panel_tools_ops.py`; read its existing fake idioms FIRST and reuse its doc/object fake classes if present — otherwise define minimal fakes in the same style):

```python
class _FakeTag:
    def __init__(self, type_id=5616, material=None, restriction=""):
        self._type = type_id
        self._material = material
        self._restriction = restriction
        self.removed = False

    def GetType(self):
        return self._type

    def __getitem__(self, key):
        # c4d.TEXTURETAG_MATERIAL / c4d.TEXTURETAG_RESTRICTION reads
        if key == "material":
            return self._material
        return self._restriction

    def Remove(self):
        self.removed = True


class _FakeObj:
    def __init__(self, type_id, name, children=None, tags=None):
        self._type = type_id
        self._name = name
        self._children = list(children or [])
        self._tags = list(tags or [])
        self.removed = False
        for c in self._children:
            c._parent = self

    def GetType(self):
        return self._type

    def GetName(self):
        return self._name

    def GetDown(self):
        return self._children[0] if self._children else None

    def GetNext(self):
        parent = getattr(self, "_parent", None)
        if parent is None:
            return None
        siblings = parent._children
        i = siblings.index(self)
        return siblings[i + 1] if i + 1 < len(siblings) else None

    def GetFirstTag(self):
        return self._tags[0] if self._tags else None

    def GetTags(self):
        return list(self._tags)

    def Remove(self):
        self.removed = True
        parent = getattr(self, "_parent", None)
        if parent is not None and self in parent._children:
            parent._children.remove(self)


def test_delete_empty_nulls_cascade_and_tag_guard(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    c4d = sentinel_module.c4d
    ONULL = c4d.Onull
    # tree: keeper(cube) ; empty_leaf(null) ; group(null){inner(null)} -> both fall (cascade)
    # tagged(null with tag) -> saved ; parent_of_keeper(null){cube} -> saved (has child)
    empty_leaf = _FakeObj(ONULL, "empty_leaf")
    inner = _FakeObj(ONULL, "inner")
    group = _FakeObj(ONULL, "group", children=[inner])
    tagged = _FakeObj(ONULL, "tagged", tags=[_FakeTag()])
    cube = _FakeObj(5159, "cube")
    parent = _FakeObj(ONULL, "parent", children=[cube])
    doc = fake_doc_factory(objects=[empty_leaf, group, tagged, parent])
    result = scene_tools._delete_empty_nulls_core(doc)
    assert result == {"ok": True, "removed": 3}  # empty_leaf, inner, group
    assert empty_leaf.removed and inner.removed and group.removed
    assert not tagged.removed and not parent.removed and not cube.removed


def test_delete_empty_nulls_none_found(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    cube = _FakeObj(5159, "cube")
    doc = fake_doc_factory(objects=[cube])
    assert scene_tools._delete_empty_nulls_core(doc) == {"ok": False, "error": "none_found"}


def test_clean_material_tags_broken_and_exact_dupes(sentinel_module, fake_doc_factory):
    import importlib
    scene_tools = importlib.import_module("sentinel.ui.scene_tools")
    mat = object()
    broken = _FakeTag(material=None)
    dup_a = _FakeTag(material=mat, restriction="SelA")
    dup_b = _FakeTag(material=mat, restriction="SelA")   # exact dupe -> dup_a removed, dup_b (LAST) kept
    different = _FakeTag(material=mat, restriction="SelB")  # different restriction -> kept
    obj = _FakeObj(5159, "cube", tags=[broken, dup_a, dup_b, different])
    doc = fake_doc_factory(objects=[obj])
    result = scene_tools._clean_material_tags_core(doc)
    assert result == {"ok": True, "removed_broken": 1, "removed_dupes": 1}
    assert broken.removed and dup_a.removed
    assert not dup_b.removed and not different.removed
```

If `tests/test_panel_tools_ops.py` has no `fake_doc_factory` fixture, add one in that file returning an object with `GetFirstObject()` (linked-list root from the objects list, wiring `_parent`/siblings like `_FakeObj` expects), `StartUndo`/`EndUndo`/`AddUndo` no-ops that record calls, and nothing else. Mirror how the file's existing core tests build docs — do not invent a second idiom if one exists.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q`
Expected: FAIL (`AttributeError: _delete_empty_nulls_core`).

- [ ] **Step 3: Implement** (append to `plugin/sentinel/ui/scene_tools.py`):

```python
def _iter_objects_bottom_up(first):
    """Yield the hierarchy depth-first, CHILDREN BEFORE PARENTS, materializing
    the order up-front so removals during iteration can't skip siblings."""
    out = []

    def _walk(obj):
        while obj:
            child = obj.GetDown()
            if child:
                _walk(child)
            out.append(obj)
            obj = obj.GetNext()

    _walk(first)
    return out


def _delete_empty_nulls_core(doc):
    """Delete empty nulls: an Onull with no children and NO tags of any kind
    (any tag — XPresso/constraint/UserData — saves it). Bottom-up cascade: a
    null whose descendants were all empty nulls falls too. One undo step.
    Dialog-free core (v1.30) — status dict only."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    targets_seen = False
    removed = 0
    doc.StartUndo()
    try:
        for obj in _iter_objects_bottom_up(doc.GetFirstObject()):
            try:
                if obj.GetType() != c4d.Onull:
                    continue
                if obj.GetDown() is not None or obj.GetFirstTag() is not None:
                    continue
            except Exception:
                continue
            targets_seen = True
            try:
                doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, obj)
            except Exception:
                pass
            try:
                obj.Remove()
            except Exception:
                continue
            removed += 1
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    if not removed and not targets_seen:
        return {"ok": False, "error": "none_found"}
    safe_print(f"Sentinel: removed {removed} empty null(s)")
    return {"ok": True, "removed": removed}


def _texture_tag_identity(tag):
    """(material, restriction) key for exact-duplicate detection."""
    try:
        material = tag[c4d.TEXTURETAG_MATERIAL]
    except Exception:
        material = None
    try:
        restriction = tag[c4d.TEXTURETAG_RESTRICTION] or ""
    except Exception:
        restriction = ""
    return (material, restriction)


def _clean_material_tags_core(doc):
    """Remove broken texture tags (dead/None material) and EXACT duplicates
    on the same object (same material + same restriction, keep the LAST —
    the one C4D prioritizes). One undo step. Dialog-free core (v1.30)."""
    if not doc:
        return {"ok": False, "error": "no_document"}
    removed_broken = 0
    removed_dupes = 0
    doc.StartUndo()
    try:
        for obj in _iter_objects_bottom_up(doc.GetFirstObject()):
            try:
                tags = [t for t in (obj.GetTags() or []) if t.GetType() == c4d.Ttexture]
            except Exception:
                continue
            keep_last = {}
            for tag in tags:
                material, restriction = _texture_tag_identity(tag)
                if material is None:
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, tag)
                    except Exception:
                        pass
                    try:
                        tag.Remove()
                    except Exception:
                        continue
                    removed_broken += 1
                    continue
                key = (id(material), restriction)
                if key in keep_last:
                    prev = keep_last[key]
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, prev)
                    except Exception:
                        pass
                    try:
                        prev.Remove()
                    except Exception:
                        keep_last[key] = tag
                        continue
                    removed_dupes += 1
                keep_last[key] = tag
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    if not removed_broken and not removed_dupes:
        return {"ok": False, "error": "none_found"}
    safe_print(
        f"Sentinel: removed {removed_broken} broken + {removed_dupes} duplicate material tag(s)")
    return {"ok": True, "removed_broken": removed_broken, "removed_dupes": removed_dupes}
```

Notes for the implementer: the fake tag's `__getitem__` keys — in production the ids are `c4d.TEXTURETAG_MATERIAL`/`c4d.TEXTURETAG_RESTRICTION`; make the FAKE respond to whatever the fake-c4d harness defines for those constants (check `tests/conftest.py`; if the fake c4d lacks them, add them there as distinct ints, and key the fake's `__getitem__` off those ints — never strings; the string-keyed sketch in Step 1 must be adjusted to the real fake constants, that is part of making the test honest). `id(material)` as dupe key is correct here because both tags resolve the SAME BaseMaterial wrapper only in fakes — in real C4D two wrappers for one material differ by `id()`; use the material's `GetGUID()` when available, falling back to `id()`:

```python
def _material_key(material):
    try:
        return str(material.GetGUID())
    except Exception:
        return id(material)
```

Use `_material_key(material)` in the dupe key. Add a fake-material class with `GetGUID` in the test to pin this.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/scene_tools.py tests/test_panel_tools_ops.py
git commit -m "feat(tools): delete-empty-nulls + clean-material-tags dialog-free cores"
```

---

### Task 2: `keyframes.py` — shift/stagger engine

**Files:**
- Create: `plugin/sentinel/keyframes.py`
- Test: `tests/test_keyframes.py` (create)

**Interfaces:**
- Produces (pure, no c4d import needed to test): `collect_shift_set(roots, children_of) -> list` — hierarchy-deduped, order-preserving object list (roots in given order, each root followed by its descendants, an object never twice). `stagger_plan(roots, frames) -> list[(root, offset)]` — `[(root0, 0), (root1, frames), (root2, 2*frames)...]`.
- Produces (c4d-bound): `shift_object_tracks(doc, objs, frames) -> {"objects": int, "keys": int}` — shifts every key of every `CTrack` of every obj by `frames` frames (BaseTime(frames, doc.GetFps())); REVERSE key order for positive N, forward for negative (Global Constraints). Caller owns the undo block. `run_offset(doc, frames)` / `run_stagger(doc, frames)` -> status dicts `{"ok": True, "objects": N, "keys": M}` | `{"ok": False, "error": "no_document"|"bad_frames"|"no_selection"|"no_keys"}` — these own StartUndo/EndUndo and read the selection (`GETACTIVEOBJECTFLAGS_0` = Object Manager order).

- [ ] **Step 1: Write the failing tests** — create `tests/test_keyframes.py`:

```python
import importlib

import pytest


@pytest.fixture
def keyframes(sentinel_module):
    return importlib.import_module("sentinel.keyframes")


def test_collect_shift_set_dedupes_selected_children(keyframes):
    children = {"A": ["A1", "A2"], "A1": ["A1a"], "B": [], "A2": [], "A1a": []}
    out = keyframes.collect_shift_set(["A", "A1", "B"], lambda o: children[o])
    assert out == ["A", "A1", "A1a", "A2", "B"]


def test_stagger_plan_zero_first_om_order(keyframes):
    assert keyframes.stagger_plan(["x", "y", "z"], 5) == [("x", 0), ("y", 5), ("z", 10)]
    assert keyframes.stagger_plan(["x"], -3) == [("x", 0)]


class _FakeKey:
    def __init__(self, frame):
        self.frame = frame

    def GetTime(self):
        return self.frame

    def SetTime(self, curve, value):
        self.frame = value


class _FakeCurve:
    def __init__(self, frames):
        self.keys = [_FakeKey(f) for f in frames]
        self.set_order = []

    def GetKeyCount(self):
        return len(self.keys)

    def GetKey(self, i):
        key = self.keys[i]
        self.set_order.append(i)
        return key


class _FakeTrack:
    def __init__(self, frames):
        self.curve = _FakeCurve(frames)

    def GetCurve(self):
        return self.curve


class _FakeAnimObj:
    def __init__(self, tracks):
        self._tracks = tracks

    def GetCTracks(self):
        return list(self._tracks)


class _FakeDoc:
    def GetFps(self):
        return 25

    def AddUndo(self, *_a):
        pass


def test_shift_positive_iterates_keys_in_reverse(keyframes, sentinel_module, monkeypatch):
    # BaseTime in the fake harness: patch keyframes' frame->time conversion to
    # plain numbers so the fake keys stay numeric.
    monkeypatch.setattr(keyframes, "_frames_to_time", lambda frames, fps: frames)
    monkeypatch.setattr(keyframes, "_add_time", lambda t, delta: t + delta)
    track = _FakeTrack([0, 10, 20])
    result = keyframes.shift_object_tracks(_FakeDoc(), [_FakeAnimObj([track])], 5)
    assert result == {"objects": 1, "keys": 3}
    assert [k.frame for k in track.curve.keys] == [5, 15, 25]
    assert track.curve.set_order == [2, 1, 0]  # REVERSE for positive shift


def test_shift_negative_iterates_forward(keyframes, monkeypatch):
    monkeypatch.setattr(keyframes, "_frames_to_time", lambda frames, fps: frames)
    monkeypatch.setattr(keyframes, "_add_time", lambda t, delta: t + delta)
    track = _FakeTrack([10, 20])
    keyframes.shift_object_tracks(_FakeDoc(), [_FakeAnimObj([track])], -5)
    assert [k.frame for k in track.curve.keys] == [5, 15]
    assert track.curve.set_order == [0, 1]
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_keyframes.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** — create `plugin/sentinel/keyframes.py`:

```python
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
    if len(roots) < 2:
        return {"ok": False, "error": "need_two"}
    # Dedupe NESTED selected roots up-front: a selected child of a selected
    # root belongs to the parent's family (it must not get its own rung).
    family = {}
    top_roots = []
    for root in roots:
        members = collect_shift_set([root], _children_of)
        marker_set = {id(m) for m in members}
        if any(id(root) in fam for fam in family.values()):
            continue
        family[id(root)] = marker_set
        top_roots.append(root)
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
```

Also add a stagger test with the fakes: three `_FakeAnimObj`-like roots (give them `GetDown`→None, `GetNext`→None so `_children_of` works) with one track each at frame 0 → after `run_stagger(doc, 5)` (build a `_FakeDoc` with `GetActiveObjects` returning them, `StartUndo`/`EndUndo` no-ops), root 0 stays at 0, root 1 at 5, root 2 at 10. And a nested-selection test: selecting a root and its own child → the child gets NO independent rung (`top_roots` length 1 → `no_keys`... adjust: give the root keys so the result is ok and the child was shifted exactly once with offset 0 — i.e., unchanged).

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_keyframes.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/keyframes.py tests/test_keyframes.py
git commit -m "feat(keyframes): offset/stagger engine (pure plan + reverse-order-safe shift)"
```

---

### Task 3: `renderwatch.py` — state machine + frame_sync tick + notification

**Files:**
- Create: `plugin/sentinel/renderwatch.py`
- Modify: `plugin/sentinel/ui/frame_sync.py` (`CoreMessage`)
- Test: `tests/test_renderwatch.py` (create)

**Interfaces:**
- Produces (pure): `class RenderWatch(threshold=30.0)` with `observe(is_rendering: bool, now: float) -> float | None` — returns the render DURATION (seconds) exactly once per rendering→idle transition when duration > threshold, else `None`. `format_duration(seconds) -> "12m 34s"` / `"45s"`.
- Produces (c4d-bound): `tick_active_document(now=None)` — module singleton watch; reads `c4d.CheckIsRunning(c4d.CHECKISRUNNING_EXTERNALRENDERING)`; on a qualifying finish AND `GlobalSettings.get('render_notify', 1)` truthy → `_notify_macos("Render finished — " + format_duration(d))`. NEVER raises (outer try/except); `_notify_macos` uses `subprocess.Popen(["osascript", "-e", ...])` best-effort, only on `sys.platform == "darwin"`.
- `FrameSyncMessageData.CoreMessage` calls `renderwatch.tick_active_document()` inside its own try/except, alongside the existing `_drain`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_renderwatch.py`:

```python
import importlib

import pytest


@pytest.fixture
def renderwatch(sentinel_module):
    return importlib.import_module("sentinel.renderwatch")


def test_watch_notifies_once_over_threshold(renderwatch):
    w = renderwatch.RenderWatch(threshold=30.0)
    assert w.observe(False, 0.0) is None      # idle
    assert w.observe(True, 10.0) is None      # render starts
    assert w.observe(True, 30.0) is None      # still rendering
    d = w.observe(False, 55.0)                # finished after 45s
    assert d == pytest.approx(45.0)
    assert w.observe(False, 56.0) is None     # no repeat


def test_watch_short_render_is_silent(renderwatch):
    w = renderwatch.RenderWatch(threshold=30.0)
    w.observe(True, 0.0)
    assert w.observe(False, 5.0) is None      # 5s < 30s threshold


def test_watch_rendering_at_first_observation_counts_from_there(renderwatch):
    # C4D may already be rendering when the plugin loads: the first True
    # observation anchors the start; no crash, duration measured from it.
    w = renderwatch.RenderWatch(threshold=30.0)
    assert w.observe(True, 100.0) is None
    assert w.observe(False, 200.0) == pytest.approx(100.0)


def test_format_duration(renderwatch):
    assert renderwatch.format_duration(45.2) == "45s"
    assert renderwatch.format_duration(754.0) == "12m 34s"
    assert renderwatch.format_duration(3601.0) == "1h 0m 1s"
```

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_renderwatch.py -q` → FAIL.

- [ ] **Step 3: Implement** — create `plugin/sentinel/renderwatch.py`:

```python
# -*- coding: utf-8 -*-
"""Render-complete notification (v1.30 Tools quick-wins).

Pure state machine (:class:`RenderWatch`) ticked from the existing
``FrameSyncMessageData`` 250 ms pump (a second MessageData would burn a
plugin id for nothing). Detects the Picture Viewer render finishing via
``c4d.CheckIsRunning(CHECKISRUNNING_EXTERNALRENDERING)`` and posts a macOS
notification when the render lasted longer than the threshold (30 s — test
renders stay silent) and the ``render_notify`` setting is on (default ON).
The tick must NEVER raise into the pump.
"""

import subprocess
import sys
import time

try:
    import c4d
except ImportError:  # pragma: no cover
    c4d = None

THRESHOLD_SECONDS = 30.0


class RenderWatch(object):
    """idle -> rendering -> done, injectable clock, duration-once semantics."""

    def __init__(self, threshold=THRESHOLD_SECONDS):
        self._threshold = float(threshold)
        self._started = None

    def observe(self, is_rendering, now):
        if is_rendering:
            if self._started is None:
                self._started = float(now)
            return None
        if self._started is None:
            return None
        duration = float(now) - self._started
        self._started = None
        if duration > self._threshold:
            return duration
        return None


def format_duration(seconds):
    seconds = int(round(float(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%dh %dm %ds" % (hours, minutes, secs)
    if minutes:
        return "%dm %ds" % (minutes, secs)
    return "%ds" % secs


def _notify_macos(message, title="Sentinel"):
    if sys.platform != "darwin":
        return
    try:
        script = 'display notification "%s" with title "%s"' % (
            str(message).replace('"', "'"), str(title).replace('"', "'"))
        subprocess.Popen(["osascript", "-e", script])
    except Exception:
        pass


_watch = RenderWatch()


def tick_active_document(now=None):
    """Poll the external-render state; notify on a qualifying finish."""
    if c4d is None:
        return
    try:
        rendering = bool(c4d.CheckIsRunning(c4d.CHECKISRUNNING_EXTERNALRENDERING))
        duration = _watch.observe(rendering, time.monotonic() if now is None else now)
        if duration is None:
            return
        from sentinel.common.settings import GlobalSettings
        try:
            enabled = bool(int(GlobalSettings.get("render_notify", 1)))
        except Exception:
            enabled = True
        if enabled:
            _notify_macos("Render finished — %s" % format_duration(duration))
    except Exception:
        pass
```

In `plugin/sentinel/ui/frame_sync.py`, extend `FrameSyncMessageData.CoreMessage` — after the existing `_drain` call block, still inside the `if mid == EVENT_ID or ... MSG_TIMER` branch:

```python
                try:
                    from sentinel import renderwatch
                    renderwatch.tick_active_document()
                except Exception:
                    pass
```

(The tick piggybacks the same 250 ms cadence; its own outer try/except means it can never kill the sync pump — Global Constraints.)

- [ ] **Step 4: Run tests** — `python3 -m pytest tests/test_renderwatch.py tests/test_frame_sync.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/renderwatch.py plugin/sentinel/ui/frame_sync.py tests/test_renderwatch.py
git commit -m "feat(renderwatch): render-complete notification (pure watch + frame_sync tick, 30s threshold)"
```

---

### Task 4: Ops — 4 new `panel/tools/*` routes

**Files:**
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py` (append)

**Interfaces:**
- Consumes: Task 1 cores, Task 2 `keyframes.run_offset`/`run_stagger`.
- Produces: ops `panel/tools/delete_empty_nulls`, `panel/tools/clean_material_tags` (no payload), `panel/tools/keyframe_offset`, `panel/tools/keyframe_stagger` (payload `{"frames": int}` — validation happens in `keyframes._validated_frames`, the op just forwards).

- [ ] **Step 1: Failing tests** (append to `tests/test_panel_tools_ops.py`, mirroring its existing op tests and its `_forbid_dialog` idiom EXACTLY — read them first):

```python
def test_op_delete_empty_nulls_routes_to_core(...):
    # monkeypatch scene_tools._delete_empty_nulls_core -> sentinel record;
    # call PANEL_TOOLS_OPS["panel/tools/delete_empty_nulls"]({}) with a fake
    # active document patched in; assert the core got the doc and the dict
    # is returned verbatim.

def test_op_keyframe_offset_forwards_frames(...):
    # monkeypatch keyframes.run_offset; call op with {"frames": 7};
    # assert run_offset(doc, 7) and verbatim return.

def test_op_keyframe_ops_forbid_dialog(...):
    # same _forbid_dialog harness as the existing ops: no MessageDialog /
    # QuestionDialog reachable in any of the 4 new routes (exercise each
    # with no-document AND happy paths).
```

(Write them as real tests in the file's concrete idiom — the sketches above name the required behavior, the file dictates the mechanics.)

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement** (append to `panel_tools_ops.py`):

```python
def _op_tool_delete_empty_nulls(payload):
    return _tool(scene_tools._delete_empty_nulls_core)


def _op_tool_clean_material_tags(payload):
    return _tool(scene_tools._clean_material_tags_core)


def _op_tool_keyframe_offset(payload):
    from sentinel import keyframes
    return _tool(lambda doc: keyframes.run_offset(doc, (payload or {}).get("frames")))


def _op_tool_keyframe_stagger(payload):
    from sentinel import keyframes
    return _tool(lambda doc: keyframes.run_stagger(doc, (payload or {}).get("frames")))
```

Register in `PANEL_TOOLS_OPS`:

```python
    "panel/tools/delete_empty_nulls": _op_tool_delete_empty_nulls,
    "panel/tools/clean_material_tags": _op_tool_clean_material_tags,
    "panel/tools/keyframe_offset": _op_tool_keyframe_offset,
    "panel/tools/keyframe_stagger": _op_tool_keyframe_stagger,
```

- [ ] **Step 4: Run** — `python3 -m pytest tests/test_panel_tools_ops.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/ui/panel_tools_ops.py tests/test_panel_tools_ops.py
git commit -m "feat(panel): ops for cleanup + keyframe offset/stagger tools"
```

---

### Task 5: `render_notify` setting — validator, ops, native dialog, SPA settings page

**Files:**
- Modify: `plugin/sentinel/webbridge.py` (`validate_settings_submit`), `plugin/sentinel/ui/web_ops.py` (`_op_form_settings_state` / `_op_form_settings_submit`), `plugin/sentinel/ui/dialogs.py` (`SentinelSettingsDialog` — checkbox), `web/src/pages/SettingsPage.tsx`, `web/src/types.ts` (SettingsState)
- Test: `tests/test_webbridge.py`, `tests/test_web_ops.py` (append)

**Interfaces:**
- `validate_settings_submit` accepts optional `render_notify` (coerced to bool → `{"render_notify": 0|1}` in the updates dict; malformed → omitted, never raises — same contract as every other field).
- `form/settings/state` payload gains `"render_notify": bool` (from `GlobalSettings.get('render_notify', 1)`).
- `form/settings/submit` persists via `GlobalSettings.set('render_notify', updates["render_notify"])`.
- Native `SentinelSettingsDialog` gains a "Notify when render finishes (>30s)" checkbox wired in `InitValues`/`Command`'s save branch (find the next free widget id in `ui/ids.py` — do NOT reuse; check for collisions like the v1.16 id-1316 lesson).
- SPA `SettingsPage.tsx` renders the checkbox (mirror the existing `multipart_default`/`slate` checkbox field pattern) and submits it.

- [ ] **Step 1: Failing tests** — in `tests/test_webbridge.py`: `validate_settings_submit({"render_notify": False}) == {"render_notify": 0}` (plus true→1, malformed string → omitted). In `tests/test_web_ops.py`: settings state includes `render_notify` default True; submit with `render_notify: false` calls `GlobalSettings.set('render_notify', 0)` (mirror the file's existing settings-op test mechanics).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the four surfaces listed above (validator branch: `if "render_notify" in payload: updates["render_notify"] = 1 if bool(payload["render_notify"]) else 0` guarded by try/except-omit; state line: `"render_notify": bool(int(GlobalSettings.get('render_notify', 1)))` with try/except default True; submit branch mirrors `aov_multipart`; dialog checkbox mirrors `CHK_SLATE`'s wiring; SPA field mirrors the multipart checkbox including the submit payload key).
- [ ] **Step 4: Run** — `python3 -m pytest tests/test_webbridge.py tests/test_web_ops.py -q` and `cd web && npx vitest run` → PASS.
- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/webbridge.py plugin/sentinel/ui/web_ops.py plugin/sentinel/ui/dialogs.py \
        plugin/sentinel/ui/ids.py web/src/pages/SettingsPage.tsx web/src/types.ts \
        tests/test_webbridge.py tests/test_web_ops.py
git commit -m "feat(settings): render_notify toggle across validator, ops, native dialog and SPA"
```

---

### Task 6: SPA Tools — Cleanup group + Frames control + toasts + build

**Files:**
- Modify: `web/src/lib/panelTools.ts`, `web/src/components/panel/ToolsSection.tsx`, `web/src/pages/PanelPage.tsx`, `web/src/lib/api.ts` (`postPanelTool` payload)
- Test: `web/src/lib/panelTools.test.ts` (append)

**Interfaces:**
- `postPanelTool(op: string, payload?: Record<string, unknown>)` — payload forwarded as the POST body (existing no-payload calls unchanged).
- `ToolsSection` props: `onRunTool(id: string, payload?: Record<string, unknown>)`; local `frames` state (integer input, default 5).
- `TOOL_GROUPS` gains `{ title: "Cleanup", tools: [delete_empty_nulls "Delete Empty Nulls", clean_material_tags "Clean Material Tags"] }` after "Layout & Hierarchy". The keyframe pair does NOT go into `TOOL_GROUPS` (it needs the payload); it renders as a dedicated row inside the Animation group.
- `toolToast` new copys:
  - `delete_empty_nulls` ok → `Removed ${removed} empty null${s}.`
  - `clean_material_tags` ok → `Removed ${removed_broken} broken + ${removed_dupes} duplicate tag${s}.`
  - `keyframe_offset` ok → `Shifted ${keys} key${s} across ${objects} object${s} by ${frames}f.`
  - `keyframe_stagger` ok → `Staggered ${objects} object${s} (${frames}f step, ${keys} keys).`
  - ERROR_COPY additions: `none_found: "Nothing to clean — scene is already tidy."`, `no_keys: "Selection has no keyframes."`, `bad_frames: "Frames must be a non-zero integer (±10000)."`, `need_two: "Select two or more objects to stagger."`
  - Note: the nested-selection stagger test in Task 2 must select TWO top roots (plus a nested child) so the `need_two` guard doesn't short-circuit it.

- [ ] **Step 1: Failing vitest** (append to `panelTools.test.ts`): toast copy cases for the four new ids (ok with counts + the three new error keys), and `TOOL_GROUPS` containing the Cleanup group between Layout and Animation.
- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run`.
- [ ] **Step 3: Implement**: extend `postPanelTool` (optional second arg → JSON body), `TOOL_GROUPS`, `toolToast`; `ToolsSection` gains after the Animation group's buttons one row:

```tsx
<div className="mt-2 flex items-center gap-2">
  <label className="text-xs text-[var(--color-text-secondary)]">Frames</label>
  <input
    type="number"
    value={frames}
    onChange={(e) => setFrames(parseInt(e.target.value || "0", 10))}
    className="w-16 rounded border border-[var(--color-border)] bg-transparent px-2 py-1 text-sm"
  />
  <Button variant="secondary" disabled={isBusy} onClick={() => onRunTool("panel/tools/keyframe_offset", { frames })}>Offset</Button>
  <Button variant="secondary" disabled={isBusy} onClick={() => onRunTool("panel/tools/keyframe_stagger", { frames })}>Stagger</Button>
</div>
```

(match the input styling to existing form inputs in the codebase — grep for an existing `type="number"` input and reuse its classes verbatim instead of the sketch's if they differ). `PanelPage.handleRunTool(id, payload?)` forwards to `postPanelTool(id, payload)`; `toolToast(id, r)` already receives the result — pass `frames` through the op RESULT (`run_offset` returns `frames`), not through UI state, so the toast is truthful to what ran.

- [ ] **Step 4: Run + build** — `cd web && npx vitest run` → PASS; `cd web && npm run build` → bundle updates `plugin/web/`.
- [ ] **Step 5: Commit**

```bash
git add web/src plugin/web
git commit -m "feat(panel): Cleanup tool group + keyframe Frames control (first parameterized Tools row)"
```

---

### Task 7: Version bump, docs, full suites

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION = "1.30.0"`), `CLAUDE.md` (header + What Works + Version History entries for v1.30.0), `docs/superpowers/specs/2026-07-29-tools-quickwins-design.md` (Estado → implementado, pendiente live)

**Steps:**
- [ ] **Step 1:** Bump version; write the CLAUDE.md entries in the house style (Spanish, dense; cover the 4 tools, the decisions —Tools no QC—, the arc backlog v1.31–v1.33, test counts, "PENDIENTE verificación live" marker).
- [ ] **Step 2:** Full verification: `python3 -m pytest tests/ -q` (all green) and `cd web && npx vitest run` (all green) — record the real counts in CLAUDE.md.
- [ ] **Step 3: Commit**

```bash
git add plugin/sentinel/__init__.py CLAUDE.md docs/superpowers/specs/2026-07-29-tools-quickwins-design.md
git commit -m "docs: v1.30.0 — Tools quick-wins (pending live verification)"
```

---

## After the plan (session-level, not subagent tasks)

1. Final whole-branch adversarial review; fix Critical/Important.
2. Live verification (sync.sh + C4D restart + MCP): empty-null matrix (cascade, tag-saved), material tags (broken + dupes counts), offset ±N and stagger on an animated rig (dedupe proven), PV render short (silent) vs >30 s (notification with duration), toggle OFF silences; user eyeball of the Tools UI (Cleanup group, Frames row) and Cmd+Z per tool.
3. Merge `--no-ff` after user confirmation; update memory; next arc phase = v1.31 Batch Rename.
