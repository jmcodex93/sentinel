def _new_doc(sentinel_module, render_datas=None):
    return sentinel_module.c4d.documents.BaseDocument(render_datas=render_datas)


def test_apply_fixes_batches_lights_and_camera_in_single_undo(sentinel_module, monkeypatch):
    from sentinel import fixes
    doc = _new_doc(sentinel_module)
    light = object()
    cam = object()
    calls = []

    def apply_lights(active_doc, bad_list):
        calls.append(("lights", active_doc, list(bad_list)))
        active_doc.AddUndo(101, bad_list[0])
        return len(bad_list)

    def apply_camera_shift(active_doc, bad_list):
        calls.append(("cam", active_doc, list(bad_list)))
        active_doc.AddUndo(102, bad_list[0])
        return len(bad_list)

    monkeypatch.setattr(fixes, "_apply_lights", apply_lights)
    monkeypatch.setattr(fixes, "_apply_camera_shift", apply_camera_shift)

    result = fixes.apply_fixes(
        doc,
        [
            {"check_id": "lights", "objects": [light]},
            {"check_id": "cam", "objects": [cam]},
        ],
    )

    assert doc.start_undo_count == 1
    assert doc.end_undo_count == 1
    assert len(doc.undo_operations) == 2
    assert calls == [
        ("lights", doc, [light]),
        ("cam", doc, [cam]),
    ]
    assert result == [
        {"check_id": "lights", "result": 1},
        {"check_id": "cam", "result": 1},
    ]


def test_apply_fixes_passes_unused_material_bad_list_unchanged(sentinel_module, monkeypatch):
    from sentinel import fixes
    doc = _new_doc(sentinel_module)
    new_mat = object()
    seen = []

    def apply_unused_materials(active_doc, bad_list):
        seen.append((active_doc, list(bad_list)))
        active_doc.AddUndo(103, bad_list[0])
        return len(bad_list)

    monkeypatch.setattr(fixes, "_apply_unused_materials", apply_unused_materials)

    result = fixes.apply_fixes(doc, [{"check_id": "unused_mats", "objects": [new_mat]}])

    assert doc.start_undo_count == 1
    assert doc.end_undo_count == 1
    assert seen == [(doc, [new_mat])]
    assert result == [{"check_id": "unused_mats", "result": 1}]


def test_public_fix_wrappers_still_open_their_own_undo(sentinel_module, monkeypatch):
    from sentinel import fixes

    wrappers = [
        ("fix_lights", "_apply_lights", [object()], 1),
        ("fix_camera_shift", "_apply_camera_shift", [object()], 1),
        ("fix_unused_materials", "_apply_unused_materials", [object()], 1),
    ]

    for wrapper_name, apply_name, bad_list, expected in wrappers:
        doc = _new_doc(sentinel_module)

        def apply_one(active_doc, objects, count=expected):
            active_doc.AddUndo(104, objects[0])
            return count

        monkeypatch.setattr(fixes, apply_name, apply_one)

        assert getattr(fixes, wrapper_name)(doc, bad_list) == expected
        assert doc.start_undo_count == 1
        assert doc.end_undo_count == 1
        assert len(doc.undo_operations) == 1


def test_public_fps_wrapper_still_opens_its_own_undo(sentinel_module, monkeypatch):
    from sentinel import fixes
    doc = _new_doc(sentinel_module, render_datas=[object()])

    def apply_fps_range(active_doc):
        active_doc.AddUndo(105, active_doc)
        return ["fps"]

    monkeypatch.setattr(fixes, "_apply_fps_range", apply_fps_range)

    assert fixes.fix_fps_range(doc) == ["fps"]
    assert doc.start_undo_count == 1
    assert doc.end_undo_count == 1
    assert len(doc.undo_operations) == 1


class _FakeRenderData(dict):
    """Minimal RenderData stand-in: dict-backed container + GetName/GetNext."""

    def __init__(self, name, values):
        super().__init__(values)
        self._name = name

    def GetName(self):
        return self._name

    def GetNext(self):
        return None


def test_fix_one_render_data_does_not_rewrite_stills_token_preset_to_animation(sentinel_module):
    """Parity with check_fps_range's is_stills_preset: a token-matched stills
    preset (e.g. 'RS-LookDev 2026') left in Current Frame mode must NOT be
    forced into a 1001-anchored Manual animation range by the fix, even
    though its name isn't the exact literal 'stills'.
    """
    import c4d
    from sentinel.fixes import _fix_one_render_data

    standard_fps = 25
    start_frame = 1001
    current_start, current_end = 1, 100

    rd = _FakeRenderData("RS-LookDev 2026", {
        c4d.RDATA_FRAMERATE: float(standard_fps),
        c4d.RDATA_FRAMEFROM: c4d.BaseTime(current_start, standard_fps),
        c4d.RDATA_FRAMETO: c4d.BaseTime(current_end, standard_fps),
        c4d.RDATA_FRAMESEQUENCE: c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME,
        c4d.RDATA_FRAMESTEP: 1,
    })

    changes, final_start, final_end = _fix_one_render_data(
        None, rd, standard_fps, start_frame, stills_tokens=["stills", "lookdev"])

    assert not any("Frame range" in c for c in changes)
    assert not any("Frame mode" in c for c in changes)
    assert rd[c4d.RDATA_FRAMESEQUENCE] == c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME


def test_fix_one_render_data_rewrites_animation_preset_to_start_frame(sentinel_module):
    """Control case: a non-stills-token preset in Current Frame mode IS
    forced into a 1001-anchored Manual range by the fix, proving the
    stills-token case above is actually exercising the branch (not
    passing vacuously)."""
    import c4d
    from sentinel.fixes import _fix_one_render_data

    standard_fps = 25
    start_frame = 1001
    current_start, current_end = 1, 100

    rd = _FakeRenderData("RS-HighRez Animation 2026", {
        c4d.RDATA_FRAMERATE: float(standard_fps),
        c4d.RDATA_FRAMEFROM: c4d.BaseTime(current_start, standard_fps),
        c4d.RDATA_FRAMETO: c4d.BaseTime(current_end, standard_fps),
        c4d.RDATA_FRAMESEQUENCE: c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME,
        c4d.RDATA_FRAMESTEP: 1,
    })

    changes, final_start, final_end = _fix_one_render_data(
        None, rd, standard_fps, start_frame, stills_tokens=["stills", "lookdev"])

    assert any("Frame mode" in c for c in changes)
    assert rd[c4d.RDATA_FRAMESEQUENCE] == c4d.RDATA_FRAMESEQUENCE_MANUAL
    assert final_start == start_frame
    assert final_end == start_frame + (current_end - current_start)
