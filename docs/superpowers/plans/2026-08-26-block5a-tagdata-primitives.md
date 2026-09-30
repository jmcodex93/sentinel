# Block 5A — Shared TagData Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Sentinel Frame, Pin, and Variants one tested implementation of their duplicated Cinema 4D host-adaptation and dynamic-description primitives without sharing tag lifecycle behaviour.

**Architecture:** Add free functions in `sentinel.ui.tag_support`; keep the three concrete `TagData` classes, registration probes, callbacks, storage, and business logic in their current modules. Migrate Frame separately because its description controls use numeric bounds/cycles/units; migrate Pin and Variants together because their duplicated builders are equivalent.

**Tech Stack:** Python 3.11-compatible code running in Cinema 4D 2026; pytest; existing fake-C4D harness in `tests/conftest.py`.

**Spec:** `docs/superpowers/specs/2026-08-25-block5-maintainability-design.md`

## Global Constraints

- No new feature, endpoint, setting, sidecar, dialog, or UI control.
- No tag schema or stored `BaseContainer` layout changes.
- No common `TagData` base class or mixin. Each registered plugin keeps its own concrete class and lifecycle callbacks.
- Existing tag callback signatures and fallback plugin IDs remain unchanged.
- Production is never adapted to a permissive fake; additive fake changes must model a documented C4D surface.
- Run Python tests with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`.
- Baseline in the isolated worktree: `1589 passed`.

---

### Task 1: Host-adaptation primitives

**Files:**
- Create: `plugin/sentinel/ui/tag_support.py`
- Create: `tests/test_tag_support.py`

**Interfaces:**
- Produces: `desc_level_id(cid) -> int`
- Produces: `set_bc_value(bc, method_name, key, value) -> None`
- Produces: `node_creator_type(node, fallback_creator) -> int`
- Produces: `description_parent(node, parameter_id, dtype, fallback_creator) -> c4d.DescID`
- Produces: `document_from_node(node) -> object | None`
- Produces: `is_main_thread() -> bool`
- Produces: `safe_node_name(node, fallback="") -> str`
- Produces: `event_add() -> None`
- Produces: `command_id_from_data(data) -> int`

- [ ] **Step 1: Write characterization tests that fail because `tag_support` does not exist**

```python
# tests/test_tag_support.py
def test_desc_level_id_accepts_descid_integer_and_bad_input(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    assert tag_support.desc_level_id(c4d.DescID(c4d.DescLevel(42))) == 42
    assert tag_support.desc_level_id(43) == 43
    assert tag_support.desc_level_id(object()) == 0


def test_description_parent_preserves_the_callers_fallback_creator(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    class DeadNode:
        def GetType(self):
            raise RuntimeError("dead")

    desc_id = tag_support.description_parent(DeadNode(), 7001, c4d.DTYPE_BOOL, 2099073)
    assert desc_id[0].id == 7001
    assert desc_id[0].dtype == c4d.DTYPE_BOOL
    assert desc_id[0].creator == 2099073


def test_document_from_node_prefers_owner_then_active_document(sentinel_module, monkeypatch):
    import c4d
    from sentinel.ui import tag_support

    owner_doc = object()
    active_doc = object()

    class OwnedNode:
        def GetDocument(self):
            return owner_doc

    class DetachedNode:
        def GetDocument(self):
            return None

    monkeypatch.setattr(c4d.documents, "GetActiveDocument", lambda: active_doc)
    assert tag_support.document_from_node(OwnedNode()) is owner_doc
    assert tag_support.document_from_node(DetachedNode()) is active_doc


def test_command_id_and_safe_name_are_failure_tolerant(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    class DeadNode:
        def GetName(self):
            raise RuntimeError("dead")

    assert tag_support.command_id_from_data({"id": c4d.DescID(c4d.DescLevel(8123))}) == 8123
    assert tag_support.command_id_from_data({}) == 0
    assert tag_support.safe_node_name(DeadNode(), "fallback") == "fallback"
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_tag_support.py -q -p no:cacheprovider`

Expected: collection/import failure because `sentinel.ui.tag_support` does not exist.

- [ ] **Step 3: Implement the nine free functions with the exact fallback order used by the three tags**

```python
# plugin/sentinel/ui/tag_support.py
import c4d


def desc_level_id(cid):
    try:
        return int(cid[0].id)
    except Exception:
        try:
            return int(cid)
        except Exception:
            return 0


def set_bc_value(bc, method_name, key, value):
    method = getattr(bc, method_name, None)
    if callable(method):
        try:
            method(key, value)
            return
        except Exception:
            pass
    try:
        bc[key] = value
    except Exception:
        pass


def node_creator_type(node, fallback_creator):
    try:
        return node.GetType()
    except Exception:
        return fallback_creator


def description_parent(node, parameter_id, dtype, fallback_creator):
    creator = node_creator_type(node, fallback_creator)
    return c4d.DescID(c4d.DescLevel(parameter_id, dtype, creator))


def document_from_node(node):
    getter = getattr(node, "GetDocument", None)
    if callable(getter):
        try:
            doc = getter()
            if doc is not None:
                return doc
        except Exception:
            pass
    try:
        return c4d.documents.GetActiveDocument()
    except Exception:
        return None


def is_main_thread():
    threading_module = getattr(c4d, "threading", None)
    checker = getattr(threading_module, "GeIsMainThread", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    checker = getattr(c4d, "GeIsMainThread", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return True


def safe_node_name(node, fallback=""):
    getter = getattr(node, "GetName", None)
    if callable(getter):
        try:
            name = getter()
            if name:
                return str(name)
        except Exception:
            pass
    return str(fallback or "")


def event_add():
    try:
        c4d.EventAdd()
    except Exception:
        pass


def command_id_from_data(data):
    try:
        cid = data["id"]
    except Exception:
        cid = None
    return desc_level_id(cid)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_tag_support.py -q -p no:cacheprovider`

Expected: all tests pass.

- [ ] **Step 5: Mutation-check the fallback creator test**

Temporarily change `return fallback_creator` to `return 0`; run `test_description_parent_preserves_the_callers_fallback_creator`; verify that named test fails; restore the production line and rerun it green.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/tag_support.py tests/test_tag_support.py
git commit -m "refactor(tags): centralize C4D host primitives"
```

---

### Task 2: Dynamic-description builders

**Files:**
- Modify: `plugin/sentinel/ui/tag_support.py`
- Modify: `tests/test_tag_support.py`

**Interfaces:**
- Consumes: Task 1 `description_parent` and `set_bc_value`
- Produces: `add_description_parameter(node, description, parameter_id, dtype, name, parent, fallback_creator, *, animatable=True, minimum=None, maximum=None, step=None, unit=None, cycle=None, custom_gui=None) -> bool`
- Produces: `add_description_group(node, description, group_id, name, parent, fallback_creator, *, columns=None, titlebar=True) -> bool`

- [ ] **Step 1: Add failing tests for the full Frame superset and group contract**

```python
class RecordingDescription:
    def __init__(self):
        self.calls = []

    def SetParameter(self, desc_id, bc, parent):
        self.calls.append((desc_id, bc, parent))
        return True


def test_parameter_builder_writes_bounds_cycle_unit_and_button_gui(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    description = RecordingDescription()
    parent = c4d.DescID(c4d.DescLevel(9000))
    ok = tag_support.add_description_parameter(
        object(), description, 9001, c4d.DTYPE_BUTTON, "Run", parent, 2099073,
        animatable=False, minimum=0.0, maximum=1.0, step=0.1,
        unit=c4d.DESC_UNIT_PERCENT, cycle=((1, "One"), (2, "Two")),
        custom_gui=c4d.CUSTOMGUI_BUTTON,
    )
    assert ok is True
    desc_id, bc, actual_parent = description.calls[0]
    assert desc_id[0].creator == 2099073
    assert actual_parent == parent
    assert bc[c4d.DESC_NAME] == "Run"
    assert bc[c4d.DESC_SHORT_NAME] == "Run"
    assert bc[c4d.DESC_MIN] == 0.0
    assert bc[c4d.DESC_MAX] == 1.0
    assert bc[c4d.DESC_STEP] == 0.1
    assert bc[c4d.DESC_UNIT] == c4d.DESC_UNIT_PERCENT
    assert bc[c4d.DESC_CUSTOMGUI] == c4d.CUSTOMGUI_BUTTON
    assert bc[c4d.DESC_CYCLE].GetString(2) == "Two"


def test_group_builder_writes_layout_contract(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    description = RecordingDescription()
    assert tag_support.add_description_group(
        object(), description, 9100, "Actions", None, 2099078,
        columns=2, titlebar=False,
    ) is True
    desc_id, bc, parent = description.calls[0]
    assert desc_id[0].creator == 2099078
    assert parent is None
    assert bc[c4d.DESC_TITLEBAR] is False
    assert bc[c4d.DESC_DEFAULT] is False
    assert bc[c4d.DESC_COLUMNS] == 2
```

- [ ] **Step 2: Run the two tests and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_tag_support.py -q -p no:cacheprovider`

Expected: failures because both builder functions are absent.

- [ ] **Step 3: Implement builders using explicit options, with no domain IDs**

The implementation must create defaults through `c4d.GetCustomDatatypeDefault`, write `DESC_NAME`/`DESC_SHORT_NAME`, set slider bounds together with numeric bounds, create a `BaseContainer` for cycles, and return `False` when `description.SetParameter` raises. It must not mention Frame, Pin, Variants, or `ID_LINE_WIDTH`.

- [ ] **Step 4: Run Task 2 tests and the three existing tag suites**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_tag_support.py tests/test_frame_tag.py tests/test_pin_tag.py tests/test_variant_tag.py -q -p no:cacheprovider`

Expected: all pass.

- [ ] **Step 5: Mutation-check `animatable=False` and cycle wiring**

Remove the `DESC_ANIMATE` write and verify `test_parameter_builder_writes_bounds_cycle_unit_and_button_gui` fails; restore it. Then replace the cycle key with `int(value) + 1`, verify the same test fails, restore, and rerun green.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/tag_support.py tests/test_tag_support.py
git commit -m "refactor(tags): centralize description builders"
```

---

### Task 3: Migrate Sentinel Frame

**Files:**
- Modify: `plugin/sentinel/ui/frame_tag.py:297-429,1727-1805`
- Modify: `tests/test_frame_tag.py`

**Interfaces:**
- Consumes: every Task 1/2 function
- Preserves: `SentinelFrameTag` callback signatures, `_SENTINEL_FRAME_TAG_AVAILABLE`, plugin ID `2099073`, percentage-unit behaviour for every fractional real except `ID_LINE_WIDTH`

- [ ] **Step 1: Add a failing ownership test**

Add a test that imports `frame_tag` and `tag_support`, then asserts signature-compatible private names such as `_desc_level_id` and `_set_bc_value` are aliases of the shared functions. For helpers whose old signature injects the Frame plugin ID, assert their thin adapter calls the shared implementation and preserves `SENTINEL_FRAME_TAG_PLUGIN_ID`. Also assert the concrete class no longer owns `_set_description_parameter` or `_set_description_group`, and that a real Frame description build records its own creator ID.

- [ ] **Step 2: Run the ownership test and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_frame_tag.py -q -p no:cacheprovider`

Expected: alias/delegation and class-builder ownership assertions fail because the implementations are still local.

- [ ] **Step 3: Replace local helpers and class builders with shared imports**

Import signature-compatible primitives under their existing private names. Keep only tiny adapters where the legacy signature must inject `SENTINEL_FRAME_TAG_PLUGIN_ID` or reorder arguments; those adapters contain no host fallback logic. Call the shared description builders directly from `GetDDescription`. For real-valued controls, pass `unit=c4d.DESC_UNIT_PERCENT` only where the old code did; leave `ID_LINE_WIDTH` with `unit=None`. Pass button GUI, bounds, cycle, step, and animation options explicitly from each existing call.

- [ ] **Step 4: Run Frame and shared tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_tag_support.py tests/test_frame_tag.py tests/test_framing_v2.py tests/test_multiformat_slices.py -q -p no:cacheprovider`

Expected: all pass with no callback or payload changes.

- [ ] **Step 5: Mutation-check the line-width unit exception**

Force `ID_LINE_WIDTH` to pass `DESC_UNIT_PERCENT`; run the existing Frame description assertion covering line width and verify it fails. If no existing assertion discriminates this, add one before restoring production. Restore and rerun green.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/ui/frame_tag.py tests/test_frame_tag.py
git commit -m "refactor(frame): consume shared TagData primitives"
```

---

### Task 4: Migrate Sentinel Pin and Variants

**Files:**
- Modify: `plugin/sentinel/ui/pin_tag.py:326-431,2017-2067`
- Modify: `plugin/sentinel/ui/variant_tag.py:150-256,1566-1612`
- Modify: `tests/test_pin_tag.py`
- Modify: `tests/test_variant_tag.py`

**Interfaces:**
- Consumes: Task 1/2 primitives/builders
- Preserves: Pin fallback plugin ID `2099078`, Variants fallback plugin ID `2099079`, both concrete classes and all stored payload schemas

- [ ] **Step 1: Add failing ownership tests for both modules**

Assert signature-compatible private helper names are aliases of `tag_support`; assert legacy-signature adapters only inject/reorder each module's fallback plugin ID; assert both concrete classes no longer own `_set_description_parameter` or `_set_description_group`. Exercise one dynamic-description row in each module and assert its creator remains its own plugin ID.

- [ ] **Step 2: Run Pin/Variants tests and verify RED**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_pin_tag.py tests/test_variant_tag.py -q -p no:cacheprovider`

Expected: ownership tests fail while existing behavioural tests remain green.

- [ ] **Step 3: Migrate both modules to shared free functions**

Replace duplicated helper bodies with direct aliases or thin signature adapters, and delete the class-local builder methods. Keep `_safe_node_type` in Pin and `_report` in Variants because they are domain-specific. Pass `animatable=False` and `custom_gui=c4d.CUSTOMGUI_BUTTON` exactly where the old builders inferred them; pass each module's own plugin ID as fallback creator.

- [ ] **Step 4: Run all tag-focused suites**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_tag_support.py tests/test_frame_tag.py tests/test_pin_tag.py tests/test_pin_tag_description.py tests/test_pin_tag_tracks.py tests/test_variant_tag.py tests/test_variants.py -q -p no:cacheprovider`

Expected: all pass.

- [ ] **Step 5: Run the full Python suite outside the socket sandbox**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider`

Expected: at least 1589 tests plus new Block-5A tests, zero failures.

- [ ] **Step 6: Confirm the SPA bundle is untouched**

Run: `git diff --exit-code ab8f5f6 -- plugin/web web`

Expected: no output and exit code 0.

- [ ] **Step 7: Commit**

```bash
git add plugin/sentinel/ui/pin_tag.py plugin/sentinel/ui/variant_tag.py tests/test_pin_tag.py tests/test_variant_tag.py
git commit -m "refactor(tags): migrate Pin and Variants to shared support"
```
