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
    def __init__(self, tracks, down=None, next_=None, parent=None):
        self._tracks = tracks
        self._down = down
        self._next = next_
        self._parent = parent

    def GetCTracks(self):
        return list(self._tracks)

    def GetDown(self):
        return self._down

    def GetNext(self):
        return self._next

    def GetUp(self):
        return self._parent


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


class _FakeSelectionDoc:
    """Fake doc for run_offset/run_stagger: fps + selection + undo no-ops."""

    def __init__(self, roots, fps=25):
        self._roots = roots
        self._fps = fps
        self.undo_started = 0
        self.undo_ended = 0

    def GetFps(self):
        return self._fps

    def AddUndo(self, *_a):
        pass

    def GetActiveObjects(self, _flags):
        return list(self._roots)

    def StartUndo(self):
        self.undo_started += 1

    def EndUndo(self):
        self.undo_ended += 1


def test_run_stagger_offsets_0_n_2n(keyframes, monkeypatch):
    monkeypatch.setattr(keyframes, "_frames_to_time", lambda frames, fps: frames)
    monkeypatch.setattr(keyframes, "_add_time", lambda t, delta: t + delta)
    track0 = _FakeTrack([0])
    track1 = _FakeTrack([0])
    track2 = _FakeTrack([0])
    root0 = _FakeAnimObj([track0])
    root1 = _FakeAnimObj([track1])
    root2 = _FakeAnimObj([track2])
    doc = _FakeSelectionDoc([root0, root1, root2])

    result = keyframes.run_stagger(doc, 5)

    assert result["ok"] is True
    assert track0.curve.keys[0].frame == 0
    assert track1.curve.keys[0].frame == 5
    assert track2.curve.keys[0].frame == 10
    assert doc.undo_started == 1
    assert doc.undo_ended == 1


def test_run_stagger_nested_child_gets_no_own_rung(keyframes, monkeypatch):
    monkeypatch.setattr(keyframes, "_frames_to_time", lambda frames, fps: frames)
    monkeypatch.setattr(keyframes, "_add_time", lambda t, delta: t + delta)
    # Root 0 has a selected nested child; root 1 is a separate top root.
    root0_track = _FakeTrack([0])
    root0 = _FakeAnimObj([root0_track])
    child_track = _FakeTrack([0])
    child = _FakeAnimObj([child_track], parent=root0)
    root0._down = child
    root1_track = _FakeTrack([0])
    root1 = _FakeAnimObj([root1_track])

    # Selection order (OM order): root0, child (nested under root0), root1.
    doc = _FakeSelectionDoc([root0, child, root1])

    result = keyframes.run_stagger(doc, 5)

    assert result["ok"] is True
    # root0 (top root 0) stays at offset 0 -> its child (shifted as part of
    # root0's family) also stays at 0, NOT its own rung.
    assert root0_track.curve.keys[0].frame == 0
    assert child_track.curve.keys[0].frame == 0
    # root1 (top root 1) gets offset 1*5 = 5.
    assert root1_track.curve.keys[0].frame == 5


def test_run_stagger_root_plus_own_child_is_need_two(keyframes, monkeypatch):
    # Two raw selected roots (root + its own child) collapse into ONE
    # family after dedup -> must report "need_two", not a dishonest
    # "no_keys" (finding 1: the gate must run AFTER dedup, not before).
    monkeypatch.setattr(keyframes, "_frames_to_time", lambda frames, fps: frames)
    monkeypatch.setattr(keyframes, "_add_time", lambda t, delta: t + delta)
    root_track = _FakeTrack([0, 10])
    root = _FakeAnimObj([root_track])
    child_track = _FakeTrack([0])
    child = _FakeAnimObj([child_track], parent=root)
    root._down = child

    doc = _FakeSelectionDoc([root, child])

    result = keyframes.run_stagger(doc, 5)

    assert result == {"ok": False, "error": "need_two"}
    # Nothing shifted.
    assert [k.frame for k in root_track.curve.keys] == [0, 10]
    assert child_track.curve.keys[0].frame == 0


def test_run_stagger_family_dedup_is_order_independent(keyframes, monkeypatch):
    # Selection order [child, A, B] (child listed BEFORE its parent A) must
    # produce the identical result as [A, child, B]: A's family at offset 0,
    # B at offset 1*frames. A forward-only scan would wrongly give the
    # child its own rung and shift every later family an extra step
    # (finding 2).
    monkeypatch.setattr(keyframes, "_frames_to_time", lambda frames, fps: frames)
    monkeypatch.setattr(keyframes, "_add_time", lambda t, delta: t + delta)

    def build():
        a_track = _FakeTrack([0])
        a = _FakeAnimObj([a_track])
        child_track = _FakeTrack([0])
        child = _FakeAnimObj([child_track], parent=a)
        a._down = child
        b_track = _FakeTrack([0])
        b = _FakeAnimObj([b_track])
        return a, child, b, a_track, child_track, b_track

    # Ordering 1: child before its parent A.
    a1, child1, b1, a1_track, child1_track, b1_track = build()
    doc1 = _FakeSelectionDoc([child1, a1, b1])
    result1 = keyframes.run_stagger(doc1, 5)

    # Ordering 2: parent A before its child (canonical order).
    a2, child2, b2, a2_track, child2_track, b2_track = build()
    doc2 = _FakeSelectionDoc([a2, child2, b2])
    result2 = keyframes.run_stagger(doc2, 5)

    assert result1["ok"] is True
    assert result2["ok"] is True
    assert result1 == result2
    assert a1_track.curve.keys[0].frame == a2_track.curve.keys[0].frame == 0
    assert child1_track.curve.keys[0].frame == child2_track.curve.keys[0].frame == 0
    assert b1_track.curve.keys[0].frame == b2_track.curve.keys[0].frame == 5
