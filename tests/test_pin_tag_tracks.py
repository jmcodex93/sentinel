"""Task 6: capturing and restoring animation tracks on a Sentinel Pin.

Before this task, a pin's ``Estado`` row only WARNED that covered objects
have keyframes — restoring a value on an animated parameter changed
nothing visible, because the track overwrote it on the very next frame.
This suite proves the actual fix: a CTRACK_CATEGORY_VALUE track's keys are
captured, and a restore rewrites the LIVE track's keys back to the
captured state — including the case that matters most, an animated
parameter an artist has since wrecked.

Per the Task 6 spike (docs/research/2026-07-31-pin-storage-spike.md §6),
DATA/PLUGIN-category tracks (PLA, morphs, sound, third-party) have a
different structure and are out of scope — this suite also proves they are
COUNTED and REPORTED, never silently dropped, and that a restore never
touches their keys (it can't understand them, so it must leave them alone).

The fake CKey class below gives every setter — value AND every tangent
field — the curve-taking two-arg shape, matching what was MEASURED LIVE
in this task's own spike: SetValue/SetInterpolation/SetTimeLeft/
SetValueLeft/SetAutomaticTangentMode all require ``(curve, value)``, same
as the previously-confirmed SetTime. An earlier version of this fake
modeled a value-only one-arg shape for the tangent setters that does not
exist in real C4D — a dead branch that made ``_apply_key_setter`` LOOK
covered without ever exercising the shape production actually takes.
"""

import importlib


# --- Fakes -------------------------------------------------------------

class FakeDescLevel:
    def __init__(self, id_, dtype=0, creator=0):
        self.id = id_
        self.dtype = dtype
        self.creator = creator


class FakeDescID:
    """``levels`` is the convenient test-authoring shape — plain
    ``(id, dtype, creator)`` tuples — converted to ``FakeDescLevel``
    objects so ``__getitem__`` returns something with real ``.id``/
    ``.dtype``/``.creator`` attributes, matching what a real ``c4d.DescID``
    level exposes (and what ``pin_tag._track_desc_id_parts`` reads)."""

    def __init__(self, levels):
        self._levels = [
            lvl if isinstance(lvl, FakeDescLevel) else FakeDescLevel(*lvl)
            for lvl in levels
        ]

    def GetDepth(self):
        return len(self._levels)

    def __getitem__(self, i):
        return self._levels[i]


class FakeKey:
    """Every setter takes the curve as its first argument — the shape
    MEASURED LIVE for all of them (SetTime confirmed earlier in
    keyframes.py, v1.30; the rest confirmed in this task's own spike).
    There is no value-only shape in real C4D; modeling one here would
    hide a fake-vs-production mismatch instead of catching it."""

    def __init__(self, time, value=0.0):
        self.time = time
        self.value = value
        self.interpolation = 0
        self.value_left = 0.0
        self.value_right = 0.0
        self.time_left = None
        self.time_right = None
        self.auto_tangent = 0

    def GetTime(self):
        return self.time

    def SetTime(self, curve, time):
        self.time = time

    def GetValue(self):
        return self.value

    def SetValue(self, curve, value):
        self.value = value

    def GetInterpolation(self):
        return self.interpolation

    def SetInterpolation(self, curve, interpolation):
        self.interpolation = interpolation

    def GetValueLeft(self):
        return self.value_left

    def SetValueLeft(self, curve, value):
        self.value_left = value

    def GetValueRight(self):
        return self.value_right

    def SetValueRight(self, curve, value):
        self.value_right = value

    def GetTimeLeft(self):
        return self.time_left

    def SetTimeLeft(self, curve, time):
        self.time_left = time

    def GetTimeRight(self):
        return self.time_right

    def SetTimeRight(self, curve, time):
        self.time_right = time

    def GetAutomaticTangentMode(self):
        return self.auto_tangent

    def SetAutomaticTangentMode(self, curve, mode):
        self.auto_tangent = mode


class FakeCurve:
    def __init__(self, keys=None):
        self._keys = list(keys or [])

    def GetKeyCount(self):
        return len(self._keys)

    def GetKey(self, i):
        return self._keys[i]

    def AddKey(self, time):
        key = FakeKey(time)
        self._keys.append(key)
        return {"key": key, "idx": len(self._keys) - 1}

    def DelKey(self, i):
        del self._keys[i]
        return True


class FakeTrack:
    def __init__(self, desc_levels, category, keys=None):
        self._desc_id = FakeDescID(desc_levels)
        self._category = category
        self._curve = FakeCurve(keys)

    def GetDescriptionID(self):
        return self._desc_id

    def GetTrackCategory(self):
        return self._category

    def GetCurve(self):
        return self._curve


class FakeTagWithTracks:
    def __init__(self, tracks=None):
        self._tracks = list(tracks or [])

    def GetCTracks(self):
        return list(self._tracks)


class FakeTrackObject:
    """Object double covering everything _store_pin/_restore need, plus
    GetCTracks()/GetTags() (each tag with its own GetCTracks()) — the two
    track sources this task walks, mirroring keyframes.py's traversal —
    AND MakeTag(), so a real ``_restore`` can attach the ``↩ Antes de
    restaurar`` safety pin onto it exactly like it would a live object."""

    def __init__(self, name, c4d_module, tracks=None, tags=None, doc=None):
        self._name = name
        self._c4d = c4d_module
        self._tracks = list(tracks or [])
        self._tags = list(tags or [])
        self._data = c4d_module.BaseContainer()
        self._matrix = c4d_module.Matrix()
        self._doc = doc

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetDown(self):
        return None

    def GetData(self):
        return self._data

    def SetData(self, bc):
        self._data = bc

    def GetMl(self):
        return self._matrix

    def SetMl(self, m):
        self._matrix = m

    def GetCTracks(self):
        return list(self._tracks)

    def GetTags(self):
        return list(self._tags)

    def MakeTag(self, plugin_id):
        # MEASURED LIVE (C1 regression): BaseObject.MakeTag with no
        # ``pred`` PREPENDS in real C4D — see the matching comment in
        # test_pin_tag.py's FakeObject.MakeTag.
        tag = FakeTag(self, plugin_id, self._c4d, self._doc)
        self._tags.insert(0, tag)
        return tag

    def GetDocument(self):
        return self._doc


class FakeDoc:
    def __init__(self):
        self.undo_ops = []

    def StartUndo(self):
        pass

    def EndUndo(self):
        pass

    def AddUndo(self, undo_type, target):
        self.undo_ops.append((undo_type, target))


class FakeTag:
    """Doubles as the c4d.BaseTag hosting a pin, mirroring test_pin_tag.py's
    own FakeTag — kept separate/local so this file's fake harness (with
    real GetCTracks support) doesn't have to match that file's shape."""

    def __init__(self, host, plugin_id, c4d_module, doc):
        self._host = host
        self._type = plugin_id
        self._name = "Sentinel Pin"
        self._bc = c4d_module.BaseContainer()
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

    def GetTags(self):
        return []


# --- Capture -------------------------------------------------------------

def test_capture_node_tracks_captures_value_category_only(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    value_cat = c4d.CTRACK_CATEGORY_VALUE
    data_cat = c4d.CTRACK_CATEGORY_DATA
    obj = FakeTrackObject("ctrl", c4d, tracks=[
        FakeTrack([(1000, 19, 5000)], value_cat, keys=[FakeKey(c4d.BaseTime(0), 1.0)]),
        FakeTrack([(2000, 0, 5000)], data_cat, keys=[FakeKey(c4d.BaseTime(0), 1.0)]),
    ])

    tracks_bc, captured, skipped = pin_tag._capture_node_tracks(obj)

    assert captured == 1
    assert skipped == 1
    assert tracks_bc.GetContainerInstance(0).GetString(pin_tag._TRACK_KEY) == "::1000.19.5000"


def test_capture_node_tracks_includes_tag_tracks(sentinel_module):
    """A rig usually animates through its tags (constraints, XPresso) as
    much as through the object itself — keyframes.py already established
    both sources must be walked; capture must not regress to object-only."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    value_cat = c4d.CTRACK_CATEGORY_VALUE
    tag = FakeTagWithTracks(tracks=[
        FakeTrack([(3000, 0, 5000)], value_cat, keys=[FakeKey(c4d.BaseTime(0), 5.0)]),
    ])
    obj = FakeTrackObject("ctrl", c4d, tracks=[
        FakeTrack([(1000, 19, 5000)], value_cat, keys=[FakeKey(c4d.BaseTime(0), 1.0)]),
    ], tags=[tag])

    tracks_bc, captured, skipped = pin_tag._capture_node_tracks(obj)

    assert captured == 2
    assert skipped == 0
    keys_found = {tracks_bc.GetContainerInstance(i).GetString(pin_tag._TRACK_KEY) for i in range(captured)}
    assert keys_found == {"::1000.19.5000", "tag[0]::3000.0.5000"}


def test_capture_node_tracks_ignores_empty_value_tracks(sentinel_module):
    """A VALUE track with zero keys carries nothing to lose and nothing to
    warn about — it must be neither captured nor counted as skipped."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    obj = FakeTrackObject("ctrl", c4d, tracks=[
        FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[]),
    ])

    tracks_bc, captured, skipped = pin_tag._capture_node_tracks(obj)

    assert captured == 0
    assert skipped == 0


def test_capture_node_tracks_round_trips_every_key_field(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    key = FakeKey(c4d.BaseTime(10), 42.0)
    key.interpolation = 2
    key.value_left = -1.0
    key.value_right = 1.0
    key.time_left = c4d.BaseTime(9)
    key.time_right = c4d.BaseTime(11)
    key.auto_tangent = 1
    obj = FakeTrackObject("ctrl", c4d, tracks=[
        FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[key]),
    ])

    tracks_bc, captured, skipped = pin_tag._capture_node_tracks(obj)
    track_bc = tracks_bc.GetContainerInstance(0)
    keys_bc = track_bc.GetContainerInstance(pin_tag._TRACK_KEYS)
    stored_key = keys_bc.GetContainerInstance(0)

    assert stored_key[pin_tag._KEY_VALUE] == 42.0
    assert stored_key[pin_tag._KEY_INTERPOLATION] == 2
    assert stored_key[pin_tag._KEY_VALUE_LEFT] == -1.0
    assert stored_key[pin_tag._KEY_VALUE_RIGHT] == 1.0
    assert stored_key[pin_tag._KEY_AUTO_TANGENT] == 1


# --- Store + status row --------------------------------------------------

def test_store_pin_writes_track_counts_and_status_reports_them(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeTrackObject("ctrl", c4d, tracks=[
        FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[FakeKey(c4d.BaseTime(0), 1.0)]),
        FakeTrack([(2000, 0, 5000)], c4d.CTRACK_CATEGORY_DATA, keys=[FakeKey(c4d.BaseTime(0), 1.0)]),
    ])
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)

    assert pin_tag._store_pin(fake_tag) is True
    text = pin_tag._pin_status_text(fake_tag)

    assert "1 pistas" in text
    assert "1 pistas no incluidas" in text


def test_store_pin_with_only_captured_tracks_has_no_skip_warning(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeTrackObject("ctrl", c4d, tracks=[
        FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[FakeKey(c4d.BaseTime(0), 1.0)]),
    ])
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)

    pin_tag._store_pin(fake_tag)
    text = pin_tag._pin_status_text(fake_tag)

    assert "1 pistas" in text
    assert "no incluidas" not in text


# --- Restore: the actual "un-wreck an animated parameter" case -----------

def test_restore_rewrites_a_wrecked_animated_parameter_back_to_the_pinned_keys(sentinel_module):
    """The core claim of this task: an artist blows up an animated
    parameter (changes a key's value, or adds/removes keys) and Restore
    puts the ORIGINAL keyframed animation back — not a value that the
    track would silently overwrite on the next frame, but the actual keys."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    from sentinel import pins
    import c4d

    doc = FakeDoc()
    live_track = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 5.0),
        FakeKey(c4d.BaseTime(10), 20.0),
    ])
    host = FakeTrackObject("ctrl", c4d, tracks=[live_track], doc=doc)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)

    assert pin_tag._store_pin(fake_tag) is True

    # The artist wrecks it: values change AND a key is added.
    live_track.GetCurve()._keys[0].value = 999.0
    live_track.GetCurve()._keys[1].value = -1.0
    live_track.GetCurve().AddKey(c4d.BaseTime(20))
    assert live_track.GetCurve().GetKeyCount() == 3

    report = pin_tag._restore(fake_tag)

    curve = live_track.GetCurve()
    assert curve.GetKeyCount() == 2, "restore must reproduce the EXACT pinned key set, not merge"
    values = sorted(k.value for k in curve._keys)
    assert values == [5.0, 20.0]
    assert "restaurados" in report


def test_restore_never_touches_an_out_of_scope_track(sentinel_module):
    """A DATA/PLUGIN track can't be understood, let alone restored — a
    restore must leave its keys completely alone rather than guess."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    out_of_scope_track = FakeTrack([(2000, 0, 5000)], c4d.CTRACK_CATEGORY_DATA, keys=[
        FakeKey(c4d.BaseTime(0), 1.0),
    ])
    host = FakeTrackObject("ctrl", c4d, tracks=[out_of_scope_track], doc=doc)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)

    pin_tag._store_pin(fake_tag)
    out_of_scope_track.GetCurve()._keys[0].value = 12345.0  # "wrecked" post-pin

    pin_tag._restore(fake_tag)

    assert out_of_scope_track.GetCurve()._keys[0].value == 12345.0, (
        "an out-of-scope track's keys must never be rewritten by a restore"
    )


def test_restore_reports_missing_track_without_crashing(sentinel_module):
    """A stored track whose desc_id no longer exists on the live node
    (param/track deleted since pinning) must be REPORTED, never crash the
    rest of the restore — same honesty contract as a missing object key."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    live_track = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 1.0),
    ])
    host = FakeTrackObject("ctrl", c4d, tracks=[live_track], doc=doc)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)
    pin_tag._store_pin(fake_tag)

    # The track (and its whole underlying param) is gone by restore time.
    host._tracks = []

    report = pin_tag._restore(fake_tag)

    assert "restaurados" in report  # the object itself still restores fine


def test_restore_captures_a_fresh_safety_pin_including_its_own_tracks(sentinel_module):
    """The safety net taken right before a restore must ALSO capture live
    tracks — otherwise "undo the undo" (restoring from the safety pin)
    would silently drop animation the artist had a moment before."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    live_track = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 3.0),
    ])
    host = FakeTrackObject("ctrl", c4d, tracks=[live_track], doc=doc)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)
    pin_tag._store_pin(fake_tag)

    pin_tag._restore(fake_tag)

    safety = pin_tag._find_safety_tag(host)
    assert safety is not None
    payload = safety.GetDataInstance().GetContainerInstance(pin_tag.ID_PIN_PAYLOAD)
    entries_bc = payload.GetContainerInstance(pin_tag._PAYLOAD_ENTRIES)
    entry_bc = entries_bc.GetContainerInstance(0)
    assert entry_bc.GetInt32(pin_tag._ENTRY_TRACKS_COUNT, 0) == 1


# --- Legacy pins (written before Task 6) ---------------------------------

def test_legacy_bool_only_pin_still_warns_without_new_track_fields(sentinel_module):
    """A pin written by the PREVIOUS build only ever set the deprecated
    bool _ENTRY_KEYFRAMES — no _ENTRY_TRACKS_COUNT/_SKIPPED at all. The row
    must still warn (folded into "skipped"), not go silent just because
    this build now looks for fields that pin never wrote."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeTrackObject("ctrl", c4d)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)

    entry = c4d.BaseContainer()
    entry.SetString(pin_tag._ENTRY_KEY, "")
    entry.SetString(pin_tag._ENTRY_NAME, "ctrl")
    entry.SetBool(pin_tag._ENTRY_GEOMETRY, False)
    entry.SetBool(pin_tag._ENTRY_KEYFRAMES, True)  # legacy-only signal
    entry.SetContainer(pin_tag._ENTRY_CONTAINER, c4d.BaseContainer())
    entry.SetMatrix(pin_tag._ENTRY_MATRIX, c4d.Matrix())
    entries = c4d.BaseContainer()
    entries.SetContainer(0, entry)
    payload = c4d.BaseContainer()
    payload.SetInt32(pin_tag._PAYLOAD_SCHEMA, pin_tag.PIN_SCHEMA)
    payload.SetString(pin_tag._PAYLOAD_TIMESTAMP, "original")
    payload.SetInt32(pin_tag._PAYLOAD_COUNT, 1)
    payload.SetContainer(pin_tag._PAYLOAD_ENTRIES, entries)
    fake_tag.GetDataInstance().SetContainer(pin_tag.ID_PIN_PAYLOAD, payload)

    text = pin_tag._pin_status_text(fake_tag)

    assert "no incluidas" in text


# --- _apply_key_setter: the (single) call shape production actually uses -

def test_apply_key_setter_calls_the_curve_taking_setter(sentinel_module):
    """C6: the dual-signature fallback this test used to exercise is gone
    — measured live, EVERY CKey setter used here takes ``(curve, value)``,
    with no value-only shape in real C4D at all."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")

    calls = []

    def curve_taking_setter(curve, value):
        calls.append((curve, value))

    ok = pin_tag._apply_key_setter(curve_taking_setter, "CURVE", 5)

    assert ok is True
    assert calls == [("CURVE", 5)]


def test_apply_key_setter_never_raises_when_the_setter_fails(sentinel_module):
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")

    def broken_setter(curve, value):
        raise ValueError("nope")

    assert pin_tag._apply_key_setter(broken_setter, "CURVE", 1) is False


# --- C7: a track with nothing applicable must never lose its live keys ---

def test_apply_track_keys_never_destroys_existing_keys_when_nothing_is_applicable(sentinel_module):
    """Before this fix, ``_apply_track_keys`` deleted every live key
    FIRST and only then discovered (per-record) whether there was
    anything to rebuild — a stored payload whose records all have
    ``time is None`` (a corrupted/partial capture) destroyed real,
    perfectly fine live animation for a net loss of zero keys gained."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    track = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 1.0),
    ])

    applied = pin_tag._apply_track_keys(track, [{"time": None, "value": 99.0}])

    assert applied == 0
    curve = track.GetCurve()
    assert curve.GetKeyCount() == 1
    assert curve.GetKey(0).GetValue() == 1.0


# --- C1: MakeTag prepending must never mis-pair a tag-owned track --------

def test_restore_pairs_tag_owned_tracks_correctly_even_when_the_safety_tag_shifts_indices(sentinel_module):
    """CRITICAL regression: ``BaseObject.MakeTag`` PREPENDS in real C4D
    (measured live), so creating the ``↩ Antes de restaurar`` safety tag
    during ``_restore`` — BEFORE the pinned tag-owned tracks are resolved
    against the live scene — shifts where every OTHER tag sits in
    ``GetTags()``. Two ordinary tags on the SAME host, each animating the
    SAME parameter, pinned at 10 and 20: without excluding Sentinel Pin
    tags from the ``tag[N]`` index, the shift makes ``plan_restore`` pair
    tag[1]'s pinned keys onto what is now tag[1] live — actually the FIRST
    ordinary tag, not the one that was tag[1] at capture time — so one
    tag ends up with the OTHER tag's value and the other stays wrecked.
    After the fix both must read back their OWN pinned value."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    track_a = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 10.0),
    ])
    track_b = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 20.0),
    ])
    tag_a = FakeTagWithTracks(tracks=[track_a])
    tag_b = FakeTagWithTracks(tracks=[track_b])
    host = FakeTrackObject("ctrl", c4d, tags=[tag_a, tag_b], doc=doc)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)

    assert pin_tag._store_pin(fake_tag) is True

    # The artist wrecks both.
    track_a.GetCurve()._keys[0].value = -2.0
    track_b.GetCurve()._keys[0].value = -2.0

    pin_tag._restore(fake_tag)

    assert track_a.GetCurve()._keys[0].value == 10.0, "tag_a's own pinned value must come back"
    assert track_b.GetCurve()._keys[0].value == 20.0, "tag_b's own pinned value must come back"


# --- C2: animation added to a covered node AFTER it was pinned -----------

def test_restore_reports_tracks_added_after_pinning(sentinel_module):
    """C2: ``track_plan["extra"]`` (live VALUE tracks with no pinned
    counterpart, e.g. animation added AFTER the pin) was computed by
    ``plan_restore`` and thrown away — worse, the ``if stored_tracks:``
    guard skipped computing it AT ALL when the node had nothing pinned in
    the first place, which is exactly the case here (pinned with zero
    tracks, animated afterwards). The restore must surface the count."""
    pin_tag = importlib.import_module("sentinel.ui.pin_tag")
    import c4d

    doc = FakeDoc()
    host = FakeTrackObject("ctrl", c4d, tracks=[], doc=doc)
    fake_tag = FakeTag(host, pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID, c4d, doc)
    assert pin_tag._store_pin(fake_tag) is True

    # Animation added AFTER pinning — nothing pinned knows about this.
    new_track = FakeTrack([(1000, 19, 5000)], c4d.CTRACK_CATEGORY_VALUE, keys=[
        FakeKey(c4d.BaseTime(0), 7.0),
    ])
    host._tracks = [new_track]

    report = pin_tag._restore(fake_tag)

    assert "1 pistas nuevas sin restaurar" in report
