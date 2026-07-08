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
