"""Contracts for the shared Cinema 4D TagData host adapters."""


def test_desc_level_id_accepts_descid_integer_and_bad_input(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    assert tag_support.desc_level_id(c4d.DescID(c4d.DescLevel(42))) == 42
    assert tag_support.desc_level_id(43) == 43
    assert tag_support.desc_level_id(object()) == 0


def test_set_bc_value_prefers_typed_setter_and_falls_back_to_assignment(sentinel_module):
    from sentinel.ui import tag_support

    calls = []

    class Typed(dict):
        def SetBool(self, key, value):
            calls.append((key, value))

    typed = Typed()
    tag_support.set_bc_value(typed, "SetBool", 7, True)
    assert calls == [(7, True)]
    assert typed == {}

    fallback = {}
    tag_support.set_bc_value(fallback, "SetBool", 8, False)
    assert fallback == {8: False}


def test_description_parent_preserves_the_callers_fallback_creator(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    class DeadNode:
        def GetType(self):
            raise RuntimeError("dead")

    assert tag_support.node_creator_type(DeadNode(), 2099073) == 2099073
    desc_id = tag_support.description_parent(
        DeadNode(), 7001, c4d.DTYPE_BOOL, 2099073
    )
    assert desc_id[0].id == 7001
    assert desc_id[0].dtype == c4d.DTYPE_BOOL
    assert desc_id[0].creator == 2099073


def test_document_from_node_prefers_owner_then_active_document(
    sentinel_module, monkeypatch
):
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


def test_main_thread_detection_uses_threading_then_legacy_api(
    sentinel_module, monkeypatch
):
    from types import SimpleNamespace

    import c4d
    from sentinel.ui import tag_support

    monkeypatch.setattr(
        c4d,
        "threading",
        SimpleNamespace(GeIsMainThread=lambda: False),
    )
    assert tag_support.is_main_thread() is False

    monkeypatch.setattr(c4d, "threading", SimpleNamespace())
    monkeypatch.setattr(c4d, "GeIsMainThread", lambda: True)
    assert tag_support.is_main_thread() is True


def test_event_name_and_command_adapters_are_failure_tolerant(
    sentinel_module, monkeypatch
):
    import c4d
    from sentinel.ui import tag_support

    class DeadNode:
        def GetName(self):
            raise RuntimeError("dead")

    events = []
    monkeypatch.setattr(c4d, "EventAdd", lambda: events.append("event"))
    tag_support.event_add()

    assert events == ["event"]
    assert tag_support.safe_node_name(DeadNode(), "fallback") == "fallback"
    assert tag_support.command_id_from_data(
        {"id": c4d.DescID(c4d.DescLevel(8123))}
    ) == 8123
    assert tag_support.command_id_from_data({}) == 0


class RecordingDescription:
    def __init__(self):
        self.calls = []

    def SetParameter(self, desc_id, bc, parent):
        self.calls.append((desc_id, bc, parent))
        return True


def test_parameter_builder_writes_the_complete_explicit_contract(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    description = RecordingDescription()
    parent = c4d.DescID(c4d.DescLevel(9000))
    ok = tag_support.add_description_parameter(
        object(),
        description,
        9001,
        c4d.DTYPE_BUTTON,
        "Run",
        parent,
        2099073,
        animatable=False,
        minimum=0.0,
        maximum=1.0,
        step=0.1,
        unit=c4d.DESC_UNIT_PERCENT,
        cycle=((1, "One"), (2, "Two")),
        custom_gui=c4d.CUSTOMGUI_BUTTON,
    )

    assert ok is True
    desc_id, bc, actual_parent = description.calls[0]
    assert desc_id[0].creator == 2099073
    assert actual_parent == parent
    assert bc[c4d.DESC_NAME] == "Run"
    assert bc[c4d.DESC_SHORT_NAME] == "Run"
    assert bc[c4d.DESC_ANIMATE] == c4d.DESC_ANIMATE_OFF
    assert bc[c4d.DESC_MIN] == 0.0
    assert bc[c4d.DESC_MINSLIDER] == 0.0
    assert bc[c4d.DESC_MAX] == 1.0
    assert bc[c4d.DESC_MAXSLIDER] == 1.0
    assert bc[c4d.DESC_STEP] == 0.1
    assert bc[c4d.DESC_UNIT] == c4d.DESC_UNIT_PERCENT
    assert bc[c4d.DESC_CUSTOMGUI] == c4d.CUSTOMGUI_BUTTON
    assert bc[c4d.DESC_CYCLE].GetString(2) == "Two"


def test_group_builder_writes_layout_contract(sentinel_module):
    import c4d
    from sentinel.ui import tag_support

    description = RecordingDescription()
    assert tag_support.add_description_group(
        object(),
        description,
        9100,
        "Actions",
        None,
        2099078,
        columns=2,
        titlebar=False,
    ) is True

    desc_id, bc, parent = description.calls[0]
    assert desc_id[0].creator == 2099078
    assert parent is None
    assert bc[c4d.DESC_NAME] == "Actions"
    assert bc[c4d.DESC_SHORT_NAME] == "Actions"
    assert bc[c4d.DESC_TITLEBAR] is False
    assert bc[c4d.DESC_DEFAULT] is False
    assert bc[c4d.DESC_COLUMNS] == 2


def test_description_builders_return_false_when_c4d_rejects_the_row(
    sentinel_module
):
    import c4d
    from sentinel.ui import tag_support

    class BrokenDescription:
        def SetParameter(self, *_args):
            raise RuntimeError("description unavailable")

    assert tag_support.add_description_parameter(
        object(), BrokenDescription(), 1, c4d.DTYPE_BOOL, "Enabled", None, 7
    ) is False
    assert tag_support.add_description_group(
        object(), BrokenDescription(), 2, "Group", None, 7
    ) is False
