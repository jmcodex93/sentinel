"""Regression coverage for the Task 4 Critical: creating the ``↩ Antes de
restaurar`` safety tag must ADD a second tag to the host object, never
evict, rename, reuse or displace the pin tag being restored.

Root cause (confirmed against the Maxon SDK docs for
``BaseObject.InsertTag``): a TagData type registered WITHOUT
``c4d.TAG_MULTIPLE`` gets single-instance enforcement from C4D itself —
``MakeTag``/``InsertTag`` implicitly evicts any existing tag of the same
type the moment a second one is added, and every previous Python reference
to the evicted tag becomes invalid. ``_capture_safety_pin`` creates the
safety tag with ``obj.MakeTag(SENTINEL_PIN_TAG_PLUGIN_ID)`` on the SAME
host object that already carries the pin being restored — so without
``c4d.TAG_MULTIPLE`` on the registration (fixed in ``sentinel_panel.pyp``),
that call evicted the very tag ``_restore`` was in the middle of reading,
which is why nothing ever got applied.

This suite can't reproduce C4D's own eviction behaviour (that lives in the
compiled application, not in Python) — the fake ``FakeObject.MakeTag``
below models the CORRECT contract (always adds, never evicts), i.e. the
behaviour ``c4d.TAG_MULTIPLE`` now guarantees. What it verifies is
``pin_tag.py``'s own responsibility on top of that: that it never manages
to defeat multi-tag support by reusing, renaming or otherwise colliding
with the pin it's supposed to be backing up — including the exact
name-based-identity trap the coordinator flagged (a tag renamed to the
safety tag's display string must not be mistaken for it).
"""

import importlib


def _make_pin_tag(host, pin_tag, c4d, timestamp="original", name="mi pin"):
    """A tag already 'pinned' once — one entry (the host itself, key ""),
    same shape ``_store_pin`` produces for a real single-node pin."""
    tag = host.MakeTag(pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)
    tag.SetName(name)

    entry = c4d.BaseContainer()
    entry.SetString(pin_tag._ENTRY_KEY, "")
    entry.SetString(pin_tag._ENTRY_NAME, host.GetName())
    entry.SetBool(pin_tag._ENTRY_GEOMETRY, False)
    entry.SetBool(pin_tag._ENTRY_KEYFRAMES, False)
    entry.SetContainer(pin_tag._ENTRY_CONTAINER, c4d.BaseContainer())
    entry.SetMatrix(pin_tag._ENTRY_MATRIX, c4d.Matrix())

    entries = c4d.BaseContainer()
    entries.SetContainer(0, entry)

    payload = c4d.BaseContainer()
    payload.SetInt32(pin_tag._PAYLOAD_SCHEMA, pin_tag.PIN_SCHEMA)
    payload.SetString(pin_tag._PAYLOAD_TIMESTAMP, timestamp)
    payload.SetInt32(pin_tag._PAYLOAD_COUNT, 1)
    payload.SetContainer(pin_tag._PAYLOAD_ENTRIES, entries)

    tag.GetDataInstance().SetContainer(pin_tag.ID_PIN_PAYLOAD, payload)
    return tag


class FakeDoc:
    def __init__(self):
        self.undo_depth = 0
        self.undo_ops = []

    def StartUndo(self):
        self.undo_depth += 1

    def EndUndo(self):
        self.undo_depth -= 1

    def AddUndo(self, undo_type, target):
        self.undo_ops.append((undo_type, target))


class FakeTag:
    """Doubles as a c4d.BaseTag for these harness tests."""

    def __init__(self, host, plugin_id, name, c4d, doc):
        self._host = host
        self._type = plugin_id
        self._name = name
        self._bc = c4d.BaseContainer()
        self._doc = doc

    def GetObject(self):
        return self._host

    def GetType(self):
        return self._type

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetDataInstance(self):
        return self._bc

    def GetDocument(self):
        return self._doc


class FakeObject:
    """Doubles as a c4d.BaseObject: a tag list + MakeTag that ALWAYS adds
    (the contract c4d.TAG_MULTIPLE is meant to guarantee), no children —
    these tests are about tag identity/attachment, not subtree traversal.
    """

    def __init__(self, name, c4d, doc):
        self._name = name
        self._tags = []
        self._c4d = c4d
        self._doc = doc

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetTags(self):
        return list(self._tags)

    def MakeTag(self, plugin_id):
        tag = FakeTag(self, plugin_id, "Sentinel Pin", self._c4d, self._doc)
        self._tags.append(tag)
        return tag

    def GetDown(self):
        return None

    def GetData(self):
        return self._c4d.BaseContainer()

    def SetData(self, bc):
        pass

    def GetMl(self):
        return self._c4d.Matrix()

    def SetMl(self, m):
        pass

    def GetDocument(self):
        return self._doc


def test_capture_safety_pin_adds_a_second_tag_without_touching_the_first(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)

    ok = pin_tag._capture_safety_pin(original, host, doc)

    assert ok is True
    tags = host.GetTags()
    assert len(tags) == 2, "capture must ADD a tag, never replace the original"
    assert original in tags, "the artist's own pin tag must still be attached"
    assert original.GetName() == "mi pin", "the original tag's name must be untouched"

    original_payload = original.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    assert original_payload.GetString(pin_tag._PAYLOAD_TIMESTAMP) == "original", (
        "the original tag's payload must be untouched by the capture"
    )

    safety = [t for t in tags if t is not original][0]
    assert safety.GetType() == pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID
    assert pin_tag._is_safety_tag(safety) is True
    assert pin_tag._is_safety_tag(original) is False


def test_capture_safety_pin_reuses_the_existing_safety_tag_on_a_second_call(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)

    assert pin_tag._capture_safety_pin(original, host, doc) is True
    assert pin_tag._capture_safety_pin(original, host, doc) is True

    tags = host.GetTags()
    assert len(tags) == 2, "a second capture must overwrite the SAME safety tag, not add a third"


def test_safety_identity_is_a_flag_not_a_name(sentinel_module):
    """The exact defect the coordinator flagged: matching by name means
    renaming an ORDINARY pin to the safety tag's display name would
    silently make it act as the safety net (and lose the artist's data on
    the very next restore, since the safety-net path never overwrites
    what it thinks is itself)."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    from sentinel import pins
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    ordinary = _make_pin_tag(host, pin_tag, c4d, name=pins.SAFETY_PIN_NAME)

    # Name matches the reserved safety string, but the flag was never set.
    assert pin_tag._is_safety_tag(ordinary) is False

    ok = pin_tag._capture_safety_pin(ordinary, host, doc)

    assert ok is True
    tags = host.GetTags()
    assert len(tags) == 2, (
        "capture must not mistake the name-alike ordinary tag for the "
        "safety tag and must add a real one instead of a no-op"
    )
    flagged = [t for t in tags if pin_tag._is_safety_tag(t)]
    assert len(flagged) == 1
    assert flagged[0] is not ordinary


def test_restore_from_an_ordinary_pin_adds_the_safety_tag_alongside_it(sentinel_module):
    """End-to-end shape of the coordinator's repro: pin, then restore.
    Before the fix this ended with exactly ONE tag on the object (the
    safety tag) and the original detached; it must now end with BOTH
    attached, and the restore itself must actually have run (not aborted
    silently on a payload read that came back empty)."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)

    report = pin_tag._restore(original)

    tags = host.GetTags()
    assert len(tags) == 2, "restoring must ADD the safety tag, never evict the pin being restored"
    assert original in tags
    assert original.GetName() == "mi pin"

    original_payload = original.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    assert original_payload.GetString(pin_tag._PAYLOAD_TIMESTAMP) == "original", (
        "the source tag's OWN payload must be unchanged after restoring from it"
    )

    # The restore itself must have actually run — this is the "nothing was
    # restored" half of the bug: before the fix, the eviction invalidated
    # `node` mid-restore and _read_payload_bc came back empty, so _restore
    # bailed out at the schema gate with "" instead of applying anything.
    assert report == "1 restaurados"


def test_restore_from_the_safety_tag_does_not_back_up_itself(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    assert pin_tag._capture_safety_pin(original, host, doc) is True
    safety = [t for t in host.GetTags() if t is not original][0]

    pin_tag._restore(safety)

    # Restoring FROM the safety tag must never create a THIRD tag (a
    # backup of the backup) — the coordinator's "restoring from it must
    # not overwrite it" requirement, checked from the other direction:
    # it also must not spawn a new one instead.
    assert len(host.GetTags()) == 2
