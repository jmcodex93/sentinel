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
    # Real SetDParameter writes the "Nombre" edit into BOTH the raw tag
    # name (above) AND the ID_PIN_NAME container field (this) — a
    # properly-named tag has both in sync, which is the baseline the
    # display-name self-heal tests below simulate drifting away from.
    tag.GetDataInstance().SetString(pin_tag.ID_PIN_NAME, name)

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
        # Models node[id] = value / node[id] (BaseList2D.__getitem__/
        # __setitem__ over SetParameter/GetParameter) as its OWN storage,
        # separate from GetDataInstance() — the real distinction the color
        # shortcut depends on: ID_BASELIST_ICON_COLORIZE_MODE/COLOR are
        # NATIVE base-list parameters, not entries in the tag's own
        # plugin-data container, so a test that only checked
        # GetDataInstance() would pass even if the real code wrote to the
        # wrong place.
        self._baselist = {}

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

    def Remove(self):
        if self._host is not None:
            try:
                self._host._tags.remove(self)
            except ValueError:
                pass

    def __setitem__(self, key, value):
        self._baselist[key] = value

    def __getitem__(self, key):
        return self._baselist.get(key)


class FakeObject:
    """Doubles as a c4d.BaseObject: a tag list + MakeTag that ALWAYS adds
    (the contract c4d.TAG_MULTIPLE is meant to guarantee). Most of this
    suite is about tag identity/attachment, not subtree traversal, so
    ``children`` defaults to none (``GetDown()`` returns ``None``, same as
    before this parameter existed); a handful of live-geometry-warning
    tests need an actual child to hang off the root, hence the optional
    linked-list wiring below (``GetNext()`` chains siblings the same way
    ``pin_tag._children_of`` walks a real C4D object list).
    """

    def __init__(self, name, c4d, doc, children=None, obj_type=5159):
        self._name = name
        self._tags = []
        self._c4d = c4d
        self._doc = doc
        # RECORDED, not swallowed. SetData/SetMl used to be bare ``pass``,
        # so deleting either write from ``_restore`` left the whole suite
        # green — the container and the matrix are the two things a restore
        # exists to put back, and neither could be asserted on. Same
        # "coverage follows the shape of the fake, not the contract" trap
        # this repo has now caught six times (see .superpowers/sdd/
        # progress.md); note the contrast with SetName, which WAS caught,
        # because the fake had always recorded it.
        self._data = c4d.BaseContainer()
        self._matrix = c4d.Matrix()
        self.set_data_calls = []
        self.set_ml_calls = []
        # A real host has a type, and a pin now records the type it was
        # captured on so a tag dragged onto a different object says so
        # (``_foreign_host_name``). Defaults to Ocube — an arbitrary real
        # object type; tests that care pass their own.
        self._type = obj_type
        self._children = list(children or [])
        for i, child in enumerate(self._children):
            child._next = self._children[i + 1] if i + 1 < len(self._children) else None
        self._next = None

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetTags(self):
        return list(self._tags)

    def MakeTag(self, plugin_id):
        # MEASURED LIVE (C1 regression, see docs/superpowers/sdd/
        # review-final-pin.diff): BaseObject.MakeTag with no ``pred``
        # PREPENDS in real C4D, not appends — an earlier version of this
        # fake modeled the wrong contract, which is exactly why the tag[N]
        # index-shift bug reproduced against the pure engine but was
        # invisible to this harness.
        tag = FakeTag(self, plugin_id, "Sentinel Pin", self._c4d, self._doc)
        self._tags.insert(0, tag)
        return tag

    def GetDown(self):
        return self._children[0] if self._children else None

    def GetNext(self):
        return getattr(self, "_next", None)

    def GetType(self):
        return self._type

    def GetData(self):
        return self._data

    def SetData(self, bc):
        self._data = bc
        self.set_data_calls.append(bc)

    def GetMl(self):
        return self._matrix

    def SetMl(self, m):
        self._matrix = m
        self.set_ml_calls.append(m)

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
    silently on a payload read that came back empty).

    "1 restaurado" (singular), not "1 restaurados" — this is a real
    ``_restore`` report for a single-object pin, so the live-geometry
    brief's Cambio 2 pluralization fix changes what this assertion must
    read, same as the two test files it names explicitly."""
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
    assert report == "1 restaurado"


def test_restore_from_the_safety_tag_does_not_back_up_itself(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    assert pin_tag._capture_safety_pin(original, host, doc) is True
    safety = [t for t in host.GetTags() if t is not original][0]
    # C4: the count-only assertion below stayed green under a mutation
    # that made ``_restore`` always capture a safety pin, even from the
    # safety tag itself — because that mutation just overwrites the SAME
    # tag rather than adding a third one. Pin the payload's identity
    # (object reference — `_store_pin` always builds and stores a BRAND
    # NEW BaseContainer, so any re-store swaps this reference even if its
    # content happened to match) so that overwrite is actually caught.
    safety_payload_before = safety.GetDataInstance().GetContainerInstance(
        pin_tag.ID_PIN_PAYLOAD)

    pin_tag._restore(safety)

    # Restoring FROM the safety tag must never create a THIRD tag (a
    # backup of the backup) — the coordinator's "restoring from it must
    # not overwrite it" requirement, checked from the other direction:
    # it also must not spawn a new one instead.
    assert len(host.GetTags()) == 2
    safety_payload_after = safety.GetDataInstance().GetContainerInstance(
        pin_tag.ID_PIN_PAYLOAD)
    assert safety_payload_after is safety_payload_before, (
        "restoring FROM the safety tag must never overwrite its own payload"
    )


# --- Display-name self-heal after a save/reload ------------------------
#
# Second Critical from the same live pass: C4D resets a Python-registered
# plugin tag's REAL name (node.GetName(), what the Object Manager shows)
# back to the plugin's registration string ("Sentinel Pin") on every load
# — confirmed live, with the stored payload/parameters completely intact.
# The fake harness can express the SYMPTOM directly (a tag whose
# GetName() disagrees with its own ID_PIN_NAME container field is exactly
# what a reloaded document produces) even though it can't reproduce C4D's
# reload machinery itself — same class of limitation as the eviction bug
# above: the trigger is C4D-internal, the RESPONSE is ours to test.

# --- Second live pass: the mirror-wins policy above was WRONG ----------
#
# C4D ticks Execute() continuously. Trusting the mirror any time it
# disagreed with the live name (the first version of this fix) meant a
# LIVE rename disagreed with the (stale) mirror for exactly one tick and
# then got silently reverted a moment later — the coordinator measured
# it directly: renamed a tag natively (SetName, exactly what the Basic
# tab does), read it back immediately (correct), read it back on the
# NEXT call (reverted). That's worse than an instant failure: the artist
# sees the rename work, looks away, and finds it undone.
#
# The policy is inverted below: the tag's own name wins, unconditionally,
# except when it reads EXACTLY the plugin's registration default — the
# one unambiguous signal that a load (not a rename) produced it.

def test_sync_display_name_restores_an_ordinary_pin_after_a_simulated_reload(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d, name="close up")

    # Simulate what a reload does: the container mirror survives, the raw
    # tag name reverts to the plugin's registration string.
    tag.SetName(pin_tag.PIN_TAG_DEFAULT_NAME)

    pin_tag._sync_display_name(tag)

    assert tag.GetName() == "close up"
    assert tag.GetDataInstance().GetString(pin_tag.ID_PIN_NAME) == "close up"


def test_sync_display_name_repairs_the_safety_tag_from_the_constant_not_its_own_field(sentinel_module):
    """The safety tag's OWN ID_PIN_NAME mirror is never written at
    creation time (_capture_safety_pin calls SetName directly, bypassing
    the mirror-write path) — exactly the drift the coordinator's live
    diagnostic caught: ``param NAME='Sentinel Pin' (la red)``. Trusting
    that mirror would just re-apply the wrong default, so the safety tag
    must repair from ``pins.SAFETY_PIN_NAME`` instead — and the mirror
    gets fixed too, closing the gap for good instead of leaving it to
    drift forever. Unlike an ordinary pin, this is NOT policy-invertible:
    renaming the safety tag must never be a path to becoming an ordinary
    pin, so it always wins over whatever name the artist gave it."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    from sentinel import pins
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    assert pin_tag._capture_safety_pin(original, host, doc) is True
    safety = [t for t in host.GetTags() if t is not original][0]

    # Simulate the reload exactly as the coordinator's live diagnostic
    # showed it: the raw name reverts to the plugin default AND its
    # never-written mirror explicitly reads that same default too — a
    # non-empty, wrong value, not merely an empty one, so a mutation that
    # trusted "whatever's in the mirror, if anything" instead of the
    # constant would read this as legitimate and fail to distinguish.
    safety.SetName(pin_tag.PIN_TAG_DEFAULT_NAME)
    safety.GetDataInstance().SetString(pin_tag.ID_PIN_NAME, pin_tag.PIN_TAG_DEFAULT_NAME)

    pin_tag._sync_display_name(safety)

    assert safety.GetName() == pins.SAFETY_PIN_NAME
    assert safety.GetDataInstance().GetString(pin_tag.ID_PIN_NAME) == pins.SAFETY_PIN_NAME

    # And renaming it by hand still doesn't stick — every tick forces it
    # back, same as the reload case above.
    safety.SetName("promoted to ordinary pin?")
    pin_tag._sync_display_name(safety)
    assert safety.GetName() == pins.SAFETY_PIN_NAME


def test_sync_display_name_never_reverts_a_live_rename(sentinel_module):
    """The exact symptom the coordinator measured and pins down here:
    rename a tag natively (SetName — what the Basic tab does), then call
    the sync repeatedly (Execute ticks continuously) and confirm the name
    the artist typed survives every single tick, not just the first."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d, name="wide angle")

    tag.SetName("gran angular")

    for _ in range(5):
        pin_tag._sync_display_name(tag)
        assert tag.GetName() == "gran angular", "a live rename must never revert, tick or no tick"

    # The mirror follows the rename, so the NEXT load has something
    # correct to restore from.
    assert tag.GetDataInstance().GetString(pin_tag.ID_PIN_NAME) == "gran angular"


def test_sync_display_name_direct_object_manager_rename_also_survives(sentinel_module):
    """A rename typed straight into the Object Manager is the SAME
    SetName() call the Basic tab field makes — there is no separate path
    to distinguish anymore now that the description has no name field of
    its own, so this is really the same case as the test above, checked
    from the angle the coordinator originally raised it from."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d, name="close up")

    tag.SetName("renamed via OM")
    pin_tag._sync_display_name(tag)

    assert tag.GetName() == "renamed via OM"


def test_sync_display_name_a_fresh_never_named_pin_stays_at_the_default(sentinel_module):
    """A brand-new pin (never renamed, never synced) reads the plugin
    default and has an empty mirror — that must be a correct no-op, not
    a crash or a spurious rename to empty string."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = host.MakeTag(pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)
    assert tag.GetName() == pin_tag.PIN_TAG_DEFAULT_NAME
    assert tag.GetDataInstance().GetString(pin_tag.ID_PIN_NAME, "") == ""

    pin_tag._sync_display_name(tag)

    assert tag.GetName() == pin_tag.PIN_TAG_DEFAULT_NAME


def test_sync_display_name_is_idempotent(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d, name="close up")

    pin_tag._sync_display_name(tag)
    pin_tag._sync_display_name(tag)
    pin_tag._sync_display_name(tag)

    assert tag.GetName() == "close up"
    assert tag.GetDataInstance().GetString(pin_tag.ID_PIN_NAME) == "close up"


# --- C9: a failed safety-tag creation must never leave a dead, unflagged --
# --- tag behind that blocks every future retry -----------------------------

class _BrokenSafetyObject(FakeObject):
    """The FIRST tag ``MakeTag`` creates has a ``SetName`` that raises —
    simulating a failure partway through creating the safety tag — every
    tag created AFTER that one behaves normally, so the test can prove
    both halves: a half-made tag never lingers unflagged, and a retry
    afterwards succeeds cleanly instead of breaking again."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Off by default: ``_make_pin_tag`` (the test helper) creates the
        # ARTIST'S own pin tag via ``MakeTag`` first — that call must
        # succeed normally. The test below arms this right before the
        # call under test, so only the SAFETY tag's creation breaks.
        self._break_next_make_tag = False

    def MakeTag(self, plugin_id):
        tag = super().MakeTag(plugin_id)
        if self._break_next_make_tag:
            self._break_next_make_tag = False

            def _broken_set_name(name):
                raise RuntimeError("boom")

            tag.SetName = _broken_set_name
        return tag


def test_capture_safety_pin_removes_a_half_made_tag_on_failure_so_retry_is_clean(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = _BrokenSafetyObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    host._break_next_make_tag = True  # arm it only for the safety tag

    ok = pin_tag._capture_safety_pin(original, host, doc)

    assert ok is False
    assert len(host.GetTags()) == 1, (
        "a half-made, unflagged safety tag must not linger on the object"
    )
    assert host.GetTags()[0] is original

    # A second attempt (e.g. the artist just hits "Ir" again) must succeed
    # cleanly instead of piling up another dead tag next to the first.
    ok2 = pin_tag._capture_safety_pin(original, host, doc)

    assert ok2 is True
    assert len(host.GetTags()) == 2
    flagged = [t for t in host.GetTags() if pin_tag._is_safety_tag(t)]
    assert len(flagged) == 1


# --- N3: a failed safety-tag creation must register NOTHING to undo -------

def test_capture_safety_pin_failure_registers_no_undo_ops(sentinel_module):
    """N3 regression: an earlier version registered
    ``AddUndo(UNDOTYPE_NEW, tag)`` BEFORE ``SetName``/``SetBool`` ran, so
    the failure branch had to also register ``AddUndo(UNDOTYPE_DELETE,
    tag)`` to balance it — leaving two undo entries behind for a tag that
    was immediately removed outright (not through undo at all).
    ``UNDOTYPE_DELETE`` restores from a CLONE taken at registration time,
    so a Cmd+Z reaching that entry after this failure would re-insert a
    clone of the half-made, unflagged tag — which the ``NEW`` entry right
    above it never accounted for removing again. Registering ``NEW`` only
    AFTER the writes succeed means the failure path needs no undo
    bookkeeping at all: a bare ``Remove()`` with nothing registered to
    unwind, and this test proves exactly that — ``doc.undo_ops`` must stay
    empty when the safety tag's own creation fails."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = _BrokenSafetyObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    host._break_next_make_tag = True  # arm it only for the safety tag

    ok = pin_tag._capture_safety_pin(original, host, doc)

    assert ok is False
    assert doc.undo_ops == [], (
        "a failed safety-tag creation must not register ANY undo op — "
        "the tag was removed directly, not through undo"
    )


# --- C10: mutation survivors — name restore, last-restore clearing on ------
# --- re-pin, and the exact report-text branches -----------------------------

def test_restore_restores_the_pinned_name(sentinel_module):
    """The mutation ``live_obj.SetName(entry["name"]) -> pass`` survived
    the whole suite before this test existed — nothing checked that a
    restore actually puts the pinned NAME back, only the container/
    matrix."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("original name", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)  # captures "original name"

    host.SetName("renamed by mistake")

    pin_tag._restore(original)

    assert host.GetName() == "original name"


def test_store_pin_clears_a_previous_restore_note(sentinel_module):
    """The mutation ``_clear_last_restore -> pass`` survived the whole
    suite — nothing checked that a fresh (re-)pin drops the stale
    "N restaurados" note from a previous restore."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)

    pin_tag._restore(original)
    assert pin_tag._read_last_restore(original) != ""

    pin_tag._store_pin(original)

    assert pin_tag._read_last_restore(original) == ""


def test_restore_report_text_partial_match_format(sentinel_module):
    """Direct coverage of the "N de M restaurados · K no encontrados"
    branch — before this test, nothing in the suite asserted its exact
    text, only the all-matched "N restaurados" shape. Also covers the
    singular "1 no encontrado" concordance the brief spells out
    explicitly: the compound "N de M restaurados" form always keeps the
    plural "restaurados" (never forces an odd concordance there), but the
    trailing "no encontrado(s)" clause DOES concord with its own count."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")

    assert pin_tag._restore_report_text(2, 5) == "2 de 5 restaurados · 3 no encontrados"
    assert pin_tag._restore_report_text(4, 5) == "4 de 5 restaurados · 1 no encontrado"
    assert pin_tag._restore_report_text(3, 3) == "3 restaurados"
    # Missing TRACKS reach the row too (they used to go only to
    # safe_print), concording with their own count like every other clause.
    assert pin_tag._restore_report_text(3, 3, 0, 1) == (
        "3 restaurados · 1 pista no encontrada")
    assert pin_tag._restore_report_text(3, 3, 0, 2) == (
        "3 restaurados · 2 pistas no encontradas")


def test_pin_warning_text_warns_about_geometry(sentinel_module):
    """Direct coverage of the "⚠ geometría no incluida" string — before
    this test, nothing in the suite asserted it appears when a pinned
    entry actually has geometry. v1.35.2: this note lives on its OWN
    derived row (_pin_warning_text), separate from the count+time summary
    (_pin_status_text) — see both functions' docstrings for why."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d)
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entries = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES)
    entries.GetContainerInstance(0).SetBool(pin_tag._ENTRY_GEOMETRY, True)

    text = pin_tag._pin_warning_text(tag)

    assert text.startswith("⚠ ")
    assert "geometría no incluida" in text
    # And the summary line stays clean — no warning text bleeding into it.
    assert "geometría" not in pin_tag._pin_status_text(tag)


def test_pin_warning_text_warns_about_geometry_from_the_live_object_too(sentinel_module):
    """Live-geometry brief (pin-live-geometry-brief.md), Cambio 1: measured
    live in C4D 2026.303 — a parametric cube pinned (payload says
    ``geometry=False``, correctly, for what it was AT PIN TIME), then made
    editable (CallCommand MAKEEDITABLE) BEFORE restoring, restores its
    position but silently keeps the wrecked shape while the row still
    reports "N restaurados" as if everything came back — the exact silent
    no-op this feature exists to eliminate. The warning must also
    consider what the restore would touch RIGHT NOW, not only what the
    payload said when it was captured."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    class LiveGeometryObject(FakeObject, c4d.PointObject):
        """The live object turned editable since pinning — geometry now,
        even though the stored payload entry says otherwise."""

    doc = FakeDoc()
    host = LiveGeometryObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d)
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entries = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES)
    # Payload says NO geometry — this is the state at pin time, and it is
    # exactly what a real parametric-then-made-editable object produces.
    entries.GetContainerInstance(0).SetBool(pin_tag._ENTRY_GEOMETRY, False)

    text = pin_tag._pin_warning_text(tag)

    assert text.startswith("⚠ ")
    assert "geometría no incluida" in text


def test_pin_warning_text_ignores_geometry_on_an_unpaired_new_child(sentinel_module):
    """Precisión requerida por el brief: el conjunto a comprobar son
    exactamente los nodos vivos EMPAREJADOS con el pin (los que
    ``plan_restore`` mete en ``matched``), no todo el subárbol vivo. Un
    hijo nuevo que el pin no conoce no se restaura de ninguna forma, así
    que su geometría no es asunto de este aviso — solo pinea el objeto
    raíz (entrada única, clave ``""``); un hijo geometry-only añadido
    DESPUÉS de pinear no debe disparar el aviso."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    class LiveGeometryChild(FakeObject, c4d.PointObject):
        """A brand-new child the pin never captured."""

    doc = FakeDoc()
    new_child = LiveGeometryChild("mesh_new", c4d, doc)
    host = FakeObject("rig", c4d, doc, children=[new_child])
    tag = _make_pin_tag(host, pin_tag, c4d)
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entries = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES)
    entries.GetContainerInstance(0).SetBool(pin_tag._ENTRY_GEOMETRY, False)

    assert pin_tag._pin_warning_text(tag) == ""


def test_pin_warning_text_keeps_geometry_warning_after_a_restore(sentinel_module):
    """C3 (carried into v1.35.2): those notes are binding, not decoration
    — they must not disappear just because a restore already happened
    once and _pin_status_text is now showing its own "N restaurados"
    text. _pin_warning_text is computed independently of last-restore
    state, so it must keep warning regardless.

    Uses "1 restaurado" (singular), not "1 restaurados" — copy fix
    explicitly requested in the live-geometry brief
    (pin-live-geometry-brief.md, Cambio 2): _pin_status_text must simply
    echo back whatever ``_write_last_restore`` wrote, so this only pins
    down the REALISTIC singular text a real restore of one object would
    now produce, not new behaviour of ``_pin_status_text`` itself."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d)
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entries = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES)
    entries.GetContainerInstance(0).SetBool(pin_tag._ENTRY_GEOMETRY, True)

    pin_tag._write_last_restore(tag, "1 restaurado")

    assert pin_tag._pin_status_text(tag) == "1 restaurado"
    assert "geometría no incluida" in pin_tag._pin_warning_text(tag)


def test_pin_status_text_spells_out_objetos(sentinel_module):
    """Target copy: "1 objeto · hace 2 h" / "12 objetos · hace 2 h", not
    the abbreviated "obj" — part of reading as a real sentence rather
    than cryptic shorthand.

    Was "1 objetos · " until the live-geometry brief's Cambio 2
    (pin-live-geometry-brief.md) flagged the wrong plural at n=1 as a
    copy bug to fix, explicitly, not a test to weaken — updated to the
    correct singular "1 objeto · "."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d)

    text = pin_tag._pin_status_text(tag)

    assert text.startswith("1 objeto · ")


# --- Usability pass (v1.35.1/.2): Nombre/Color as shortcuts to native -----
# --- parameters, and "Quitar todos los pins de este objeto" --------------

def test_color_ids_are_never_intercepted_by_get_set_dparameter(sentinel_module):
    """v1.35.2: the Color row now declares the tag's NATIVE
    ID_BASELIST_ICON_COLORIZE_MODE/ID_BASELIST_ICON_COLOR directly in the
    description (see GetDDescription's "Color" section) — the exact ids
    the Basic tab's own "Icon Color" checkbox + picker already edit, so
    C4D's real picker handles them. There must be NO special-casing for
    either id in GetDParameter/SetDParameter (unlike Nombre/Estado, which
    genuinely proxy/derive) — both must fall through (return False) so the
    base class's default read/write is what actually runs, or a future
    edit could silently reintroduce a duplicate store of data C4D already
    owns, exactly the mistake this pass exists to undo."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = host.MakeTag(pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)

    instance = pin_tag.SentinelPinTag()
    mode_id = c4d.DescID(c4d.DescLevel(pin_tag._ICON_COLORIZE_MODE_ID))
    color_id = c4d.DescID(c4d.DescLevel(pin_tag._ICON_COLOR_ID))

    assert instance.GetDParameter(tag, mode_id, 0) is False
    assert instance.GetDParameter(tag, color_id, 0) is False
    assert instance.SetDParameter(tag, mode_id, True, 0) is False
    assert instance.SetDParameter(tag, color_id, c4d.Vector(0.1, 0.2, 0.3), 0) is False


def test_pin_name_field_get_set_proxy_the_real_tag_name(sentinel_module):
    """Nombre must read/write node.GetName()/SetName() directly — the SAME
    call the Basic tab's own name field makes — never a copy in our own
    container. Exercised through the class's GetDParameter/SetDParameter
    hooks directly (the AM's actual call path), not just the underlying
    proxy functions."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = host.MakeTag(pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)
    tag.SetName("wide angle")

    instance = pin_tag.SentinelPinTag()
    desc_id = c4d.DescID(c4d.DescLevel(pin_tag.ID_PIN_NAME_FIELD))

    ok, value, _flags = instance.GetDParameter(tag, desc_id, 0)
    assert ok is True
    assert value == "wide angle"

    instance.SetDParameter(tag, desc_id, "gran angular", 0)

    assert tag.GetName() == "gran angular"
    # The reload-survival mirror (see _sync_display_name) must be updated
    # immediately by the same edit, not left to the next Execute tick.
    assert tag.GetDataInstance().GetString(pin_tag.ID_PIN_NAME) == "gran angular"


def test_remove_all_pins_deletes_every_pin_tag_on_the_host_in_one_undo(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d, name="mi pin")
    assert pin_tag._capture_safety_pin(original, host, doc) is True
    assert len(host.GetTags()) == 2  # the pin + the safety net

    ok = pin_tag._remove_all_pins(original)

    assert ok is True
    assert host.GetTags() == []
    # One undo bracket for the whole batch, not one per tag.
    assert doc.undo_depth == 0
    delete_ops = [op for op, _ in doc.undo_ops if op == c4d.UNDOTYPE_DELETEOBJ]
    assert len(delete_ops) == 2


def test_remove_all_pins_is_a_no_op_when_the_host_has_none(sentinel_module):
    """Guard: nothing to do when there are none — no undo bracket opened
    for an empty batch."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)

    class _Orphan:
        def GetObject(self):
            return None

    ok = pin_tag._remove_all_pins(_Orphan())

    assert ok is False
    assert doc.undo_ops == []


def test_remove_all_pins_opens_no_undo_bracket_when_the_host_carries_none(sentinel_module):
    """Narrower than the orphan case above: the host itself resolves fine,
    it just carries zero Sentinel Pin tags (the node calling this isn't
    even attached to it — a defensive shape per the function's own
    docstring, not reachable from the real button, but the guard exists
    precisely so an empty batch never opens/closes an undo bracket for
    nothing)."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)  # no tags at all

    class _Detached:
        def GetObject(self):
            return host

        def GetDocument(self):
            return doc

    ok = pin_tag._remove_all_pins(_Detached())

    assert ok is False
    assert doc.undo_ops == []
    assert doc.undo_depth == 0


def test_remove_all_pins_does_not_touch_an_unrelated_tag(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    other = FakeTag(host, 999999, "Phong", c4d, doc)
    host._tags.append(other)

    pin_tag._remove_all_pins(original)

    assert host.GetTags() == [other]


# --- Final review wave: a pin dragged onto another object -------------------

def test_pin_warning_text_flags_a_pin_dragged_onto_another_object(sentinel_module):
    """A tag is trivially dragged from one object to another in C4D, and
    NOTHING in the location keys catches it: the subtree root keys as the
    empty string, which ``plan_restore`` matches against any host. So the
    cube's container and matrix land on the light and the row reads
    "1 restaurado". The restore is still allowed (the artist may mean it),
    but the row must SAY it."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    cube = FakeObject("mi cubo", c4d, doc, obj_type=c4d.Ocube)
    tag = FakeObject.MakeTag(cube, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)
    assert pin_tag._store_pin(tag) is True
    assert pin_tag._pin_warning_text(tag) == "", "pinned on its own host: nothing to warn about"

    # The drag: same tag, different host, different TYPE.
    light = FakeObject("mi luz", c4d, doc, obj_type=c4d.Olight)
    tag._host = light

    assert pin_tag._pin_warning_text(tag) == (
        "⚠ pin capturado sobre otro objeto («mi cubo»)"
    )


def test_pin_warning_text_ignores_a_renamed_host_of_the_same_type(sentinel_module):
    """Compared by TYPE, never by name: renaming is everyday and the
    location keys already re-arm on it by themselves. Warning on a rename
    would cry wolf on the most common edit there is."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    cube = FakeObject("mi cubo", c4d, doc, obj_type=c4d.Ocube)
    tag = FakeObject.MakeTag(cube, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)
    assert pin_tag._store_pin(tag) is True

    cube.SetName("cubo renombrado")

    assert pin_tag._pin_warning_text(tag) == ""


def test_pin_warning_text_never_warns_when_the_pin_recorded_no_host_type(sentinel_module):
    """A pin from a build older than this field has no host type stored —
    absence of the datum is never evidence of a mismatch, so the row must
    stay quiet rather than accuse every legacy pin."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc, obj_type=c4d.Ocube)
    # _make_pin_tag builds the payload by hand, exactly like a pre-field
    # build did: no _PAYLOAD_HOST_TYPE anywhere in it.
    tag = _make_pin_tag(host, pin_tag, c4d)
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    assert payload.GetInt32(pin_tag._PAYLOAD_HOST_TYPE, 0) == 0

    other = FakeObject("otra cosa", c4d, doc, obj_type=c4d.Olight)
    tag._host = other

    assert pin_tag._pin_warning_text(tag) == ""


# --- Final review wave: the safety net is the restore's own precondition ----

class _StorelessSafetyObject(FakeObject):
    """The next tag ``MakeTag`` creates comes back orphaned (``GetObject()``
    is ``None``), which is exactly what makes ``_store_pin`` on it return
    False — i.e. the safety tag gets created but its state can NOT be
    written into it. Armed per-call like ``_BrokenSafetyObject`` above, so
    the artist's own pin tag is created normally first."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._break_next_store = False

    def MakeTag(self, plugin_id):
        tag = super().MakeTag(plugin_id)
        if self._break_next_store:
            self._break_next_store = False
            tag.GetObject = lambda: None
        return tag


def test_restore_aborts_and_touches_nothing_when_the_safety_net_fails(sentinel_module):
    """The invariant "if the net fails, the restore ABORTS" had nothing
    pinning it: two separate mutations (dropping ``_restore``'s ``return
    report`` on the failure branch, and making ``_capture_safety_pin``
    return True regardless of what ``_store_pin`` said) both survived the
    full suite, because every existing test exercised
    ``_capture_safety_pin`` in isolation and never ``_restore``'s reaction
    to it. Restoring net-less is the one thing this feature promises never
    to do — there is no way back from it."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = _StorelessSafetyObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)  # captured name: "rig"
    host.SetName("renombrado por error")  # something a restore WOULD undo
    host._break_next_store = True

    report = pin_tag._restore(original)

    assert report == "no se pudo respaldar el estado actual — restauración cancelada"
    assert pin_tag._read_last_restore(original) == report
    # NOTHING in the scene may have moved: not the container, not the
    # matrix, not the name, and no undo entry claiming otherwise.
    assert host.set_data_calls == []
    assert host.set_ml_calls == []
    assert host.GetName() == "renombrado por error"
    assert (c4d.UNDOTYPE_CHANGE, host) not in doc.undo_ops


# --- Final review wave: the restore's own writes, asserted at last ----------

def test_restore_writes_the_pinned_container_matrix_and_undo_entry(sentinel_module):
    """Three mutations survived the full suite until this test — deleting
    ``SetData`` (parameters never come back), deleting ``SetMl`` (the
    transform never comes back) and deleting ``AddUndo(UNDOTYPE_CHANGE,
    live_obj)`` (Cmd+Z reverts nothing). All three were invisible because
    ``FakeObject.SetData``/``SetMl`` were bare ``pass``: the code paths
    could not run under test at all. The fake records them now."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)

    payload = original.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entry = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES).GetContainerInstance(0)
    pinned_container = entry.GetContainerInstance(pin_tag._ENTRY_CONTAINER)
    pinned_matrix = entry.GetMatrix(pin_tag._ENTRY_MATRIX, None)

    pin_tag._restore(original)

    assert host.set_data_calls == [pinned_container], (
        "the pinned container must be written back onto the live object"
    )
    assert host.set_ml_calls == [pinned_matrix], (
        "the pinned matrix must be written back onto the live object"
    )
    assert (c4d.UNDOTYPE_CHANGE, host) in doc.undo_ops, (
        "without this undo entry a single Cmd+Z reverts nothing"
    )


def test_restore_applies_nothing_at_all_when_the_schema_is_unknown(sentinel_module):
    """The schema gate mutated to ``if False`` survived the whole suite:
    an unrecognised payload would then be applied HALF-understood, which
    is worse than an untouched rig — the one thing PIN_SCHEMA exists to
    prevent."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    payload = original.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    payload.SetInt32(pin_tag._PAYLOAD_SCHEMA, pin_tag.PIN_SCHEMA + 1)
    host.SetName("renombrado por error")

    report = pin_tag._restore(original)

    assert report == ""
    assert host.set_data_calls == []
    assert host.set_ml_calls == []
    assert host.GetName() == "renombrado por error"


def test_unknown_schema_never_overwrites_the_safety_net(sentinel_module):
    """The order of the two gates IS a safety property. With the schema
    check AFTER the safety capture, a restore that applies nothing still
    overwrote the net with the current state — silently destroying the
    artist's only way back to what the PREVIOUS restore had backed up, with
    no dialog, no note and no undo."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    assert pin_tag._capture_safety_pin(original, host, doc) is True
    safety = pin_tag._find_safety_tag(host)
    # `_store_pin` always builds a BRAND NEW container, so an overwrite
    # swaps this reference even when the content would look identical.
    net_before = safety.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)

    payload = original.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    payload.SetInt32(pin_tag._PAYLOAD_SCHEMA, pin_tag.PIN_SCHEMA + 1)

    assert pin_tag._restore(original) == ""

    net_after = safety.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    assert net_after is net_before, (
        "a restore that applies nothing must not overwrite the safety net"
    )


# --- Final review wave: the AM repaint path must not unpack tracks ----------

def test_matched_live_nodes_never_unpacks_the_stored_tracks(sentinel_module):
    """``_matched_live_nodes`` runs on EVERY Attribute Manager repaint (via
    the live-geometry warning) and needs only the list of location keys —
    yet it used to build, per repaint, one dict per keyframe of per track
    of per node and throw the whole lot away. The entry below refuses to
    answer any track question, so reading a track field at all is a hard
    failure instead of a silent cost."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    class _TrackTrapContainer(c4d.BaseContainer):
        def GetInt32(self, key, default=0):
            if key == pin_tag._ENTRY_TRACKS_COUNT:
                raise AssertionError(
                    "reading the location keys must not touch the tracks")
            return super().GetInt32(key, default)

        def GetContainerInstance(self, key):
            if key == pin_tag._ENTRY_TRACKS:
                raise AssertionError(
                    "reading the location keys must not touch the tracks")
            return super().GetContainerInstance(key)

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d)
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entries = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES)
    trap = _TrackTrapContainer(entries.GetContainerInstance(0))
    entries.SetContainer(0, trap)

    assert pin_tag._matched_live_nodes(tag, payload) == [host]


# --- v1.36.1: icon colour written ONCE, at creation ----------------------
#
# The artist could not tell his own pins from the tool's `↩ Antes de
# restaurar` tag in the Object Manager — same grey icon for both. Sentinel
# now sets the tag's NATIVE tint (the same two base-list parameters the
# Basic tab's "Icon Color" checkbox + picker edit) at creation time and
# NEVER again, so a colour the artist picks by hand is never reverted.
# These tests pin both halves of that: the write happens where it should,
# and does NOT happen anywhere else.

def _colour_of(tag, pin_tag):
    """(mode, (r, g, b)) as stored in the tag's NATIVE base-list params —
    read from `_baselist`, not `GetDataInstance()`, because writing to our
    own plugin container instead of the native ids would tint nothing."""
    mode = tag[pin_tag._ICON_COLORIZE_MODE_ID]
    colour = tag[pin_tag._ICON_COLOR_ID]
    return mode, (None if colour is None
                  else (colour.x, colour.y, colour.z))


def test_init_tints_a_new_pin_with_the_accent(sentinel_module):
    """A pin created through C4D's tag menu goes through Init — that is
    where an ordinary pin gets its colour, and the only place it does."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = host.MakeTag(pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)

    assert pin_tag.SentinelPinTag().Init(tag) is True

    mode, rgb = _colour_of(tag, pin_tag)
    assert mode == pin_tag._ICON_COLORIZE_MODE_ON
    assert rgb == (pin_tag.PIN_ICON_COLOR.x, pin_tag.PIN_ICON_COLOR.y,
                   pin_tag.PIN_ICON_COLOR.z)


def test_the_two_creation_colours_are_actually_distinguishable(sentinel_module):
    """The whole point is telling them apart at a glance: they must differ
    in hue AND in saturation (so the distinction survives colour-blindness
    and a grey-ish display), not just be two different tuples."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")

    pin, safety = pin_tag.PIN_ICON_COLOR, pin_tag.SAFETY_ICON_COLOR

    def _spread(v):
        return max(v.x, v.y, v.z) - min(v.x, v.y, v.z)

    assert (pin.x, pin.y, pin.z) != (safety.x, safety.y, safety.z)
    # The accent is chromatic; the automatic tone is near-neutral.
    assert _spread(pin) > 0.3
    assert _spread(safety) < 0.1


def test_init_on_a_clone_leaves_the_copied_colour_alone(sentinel_module):
    """A clone is about to receive the source tag's own data, colour
    included — writing the default here would stomp a colour the artist
    chose on the tag being copied."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = host.MakeTag(pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID)
    tag[pin_tag._ICON_COLOR_ID] = c4d.Vector(0.9, 0.1, 0.1)

    assert pin_tag.SentinelPinTag().Init(tag, True) is True

    assert _colour_of(tag, pin_tag)[1] == (0.9, 0.1, 0.1)


def test_capture_safety_pin_gives_the_new_safety_tag_its_own_colour(sentinel_module):
    """The tool's own tag must not wear the colour that means "you made
    this" — in real C4D MakeTag has already run Init by this point, so the
    safety branch has to overwrite it."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)

    assert pin_tag._capture_safety_pin(original, host, doc) is True

    safety = pin_tag._find_safety_tag(host)
    mode, rgb = _colour_of(safety, pin_tag)
    assert mode == pin_tag._ICON_COLORIZE_MODE_ON
    assert rgb == (pin_tag.SAFETY_ICON_COLOR.x, pin_tag.SAFETY_ICON_COLOR.y,
                   pin_tag.SAFETY_ICON_COLOR.z)


def test_overwriting_the_safety_pin_never_touches_its_colour(sentinel_module):
    """The safety net is re-captured on EVERY restore. Only its creation
    writes a colour: by the second restore the tag exists, so whatever
    colour it carries is the artist's."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    original = _make_pin_tag(host, pin_tag, c4d)
    assert pin_tag._capture_safety_pin(original, host, doc) is True

    safety = pin_tag._find_safety_tag(host)
    safety[pin_tag._ICON_COLOR_ID] = c4d.Vector(0.2, 0.8, 0.4)

    assert pin_tag._capture_safety_pin(original, host, doc) is True

    assert pin_tag._find_safety_tag(host) is safety
    assert _colour_of(safety, pin_tag)[1] == (0.2, 0.8, 0.4)


def test_storing_a_pin_never_writes_the_icon_colour(sentinel_module):
    """Re-pinning is the most frequent gesture on an existing tag — if it
    wrote the tint, every artist colour would silently revert on the next
    "Guardar estado"."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)
    tag = _make_pin_tag(host, pin_tag, c4d)
    tag[pin_tag._ICON_COLOR_ID] = c4d.Vector(0.1, 0.9, 0.9)
    tag[pin_tag._ICON_COLORIZE_MODE_ID] = pin_tag._ICON_COLORIZE_MODE_ON

    assert pin_tag._store_pin(tag) is True

    assert _colour_of(tag, pin_tag)[1] == (0.1, 0.9, 0.9)


# --- v1.36.1: pin_object — the entry point behind Tools → "Pin State" ----

def test_pin_object_creates_a_tag_and_captures_it_immediately(sentinel_module):
    """An empty pin is of no use to the artist: "pin this" means "remember
    this", so the state must already be in the tag when this returns."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)

    tag = pin_tag.pin_object(host, doc)

    assert tag is not None
    assert tag.GetType() == pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID
    payload = tag.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    assert payload is not None
    assert payload.GetInt32(pin_tag._PAYLOAD_COUNT, 0) == 1


def test_pin_object_registers_the_new_tag_for_undo(sentinel_module):
    """Without the NEW undo the tag survives the Cmd+Z that is supposed to
    remove it, and the batch leaves pins behind."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)

    tag = pin_tag.pin_object(host, doc)

    assert (c4d.UNDOTYPE_NEW, tag) in doc.undo_ops
    # Every bracket it opened is closed — a leaked StartUndo would swallow
    # everything the caller does after it into one undo step.
    assert doc.undo_depth == 0


def test_pin_object_never_makes_the_new_tag_the_safety_net(sentinel_module):
    """The safety flag is the tool's own; a pin the artist asked for must
    never be mistaken for `↩ Antes de restaurar` (which would make the next
    restore overwrite it)."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeObject("rig", c4d, doc)

    tag = pin_tag.pin_object(host, doc)

    assert pin_tag._is_safety_tag(tag) is False
    assert pin_tag._find_safety_tag(host) is None


def test_pin_object_returns_none_when_the_tag_cannot_be_made(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()

    class _NoTags(FakeObject):
        def MakeTag(self, plugin_id):
            return None

    assert pin_tag.pin_object(_NoTags("rig", c4d, doc), doc) is None
