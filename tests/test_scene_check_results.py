import json
import sys

import pytest


class FakeObject:
    def __init__(self, name, type_id=0, guid=None, params=None, tracks=None, tags=None):
        self._name = name
        self._type_id = type_id
        self._guid = guid or f"guid-{name}"
        self._params = params or {}
        self._tracks = tracks or []
        self._tags = tags or []
        self._up = None
        self._down = None
        self._next = None
        self._pred = None

    def add_child(self, child):
        child._up = self
        if self._down is None:
            self._down = child
            return child
        current = self._down
        while current._next is not None:
            current = current._next
        current._next = child
        child._pred = current
        return child

    def GetName(self):
        return self._name

    def GetGUID(self):
        return self._guid

    def GetType(self):
        return self._type_id

    def CheckType(self, type_id):
        return self._type_id == type_id

    def GetTypeName(self):
        return self._name

    def GetUp(self):
        return self._up

    def GetDown(self):
        return self._down

    def GetNext(self):
        return self._next

    def GetPred(self):
        return self._pred

    def GetCTracks(self):
        return self._tracks

    def GetTags(self):
        return self._tags

    def __getitem__(self, key):
        return self._params.get(key)


class FakeTrack:
    def __init__(self, desc_id):
        self._desc_id = desc_id

    def GetDescriptionID(self):
        return self._desc_id


class FakeTag:
    def __init__(self, type_id, params=None):
        self._type_id = type_id
        self._params = params or {}

    def GetType(self):
        return self._type_id

    def GetDataInstance(self):
        return {}

    def __getitem__(self, key):
        return self._params.get(key)


class FakeMaterial:
    def __init__(self, name, guid=None):
        self._name = name
        self._guid = guid or f"guid-{name}"

    def GetName(self):
        return self._name

    def GetGUID(self):
        return self._guid

    def GetFirstShader(self):
        return None

    def IsInstanceOf(self, type_id):
        return False


class FakeRenderData:
    def __init__(self, name, params=None):
        self._name = name
        self._params = params or {}
        self._next = None

    def GetName(self):
        return self._name

    def GetNext(self):
        return self._next

    def __getitem__(self, key):
        return self._params.get(key)


class FakeDoc:
    def __init__(self, first_object=None, materials=None, render_data=None):
        self._first_object = first_object
        self._materials = materials or []
        self._render_data = render_data or []
        for left, right in zip(self._render_data, self._render_data[1:]):
            left._next = right

    def GetFirstObject(self):
        return self._first_object

    def GetMaterials(self):
        return self._materials

    def GetFirstRenderData(self):
        return self._render_data[0] if self._render_data else None


def _c4d():
    return sys.modules["c4d"]


def _desc_id(root, axis):
    c4d = _c4d()
    return c4d.DescID(c4d.DescLevel(root), c4d.DescLevel(axis))


def _build_lights_doc():
    c4d = _c4d()
    obj = FakeObject("stray_key_light", c4d.Olight, guid="light-guid")
    return FakeDoc(obj), ["stray_key_light"]


def _build_visibility_doc():
    c4d = _c4d()
    obj = FakeObject(
        "hidden_in_editor_only",
        c4d.Onull,
        guid="vis-guid",
        params={
            c4d.ID_BASEOBJECT_VISIBILITY_EDITOR: c4d.OBJECT_OFF,
            c4d.ID_BASEOBJECT_VISIBILITY_RENDER: c4d.OBJECT_ON,
        },
    )
    return FakeDoc(obj), ["hidden_in_editor_only"]


def _build_keys_doc():
    c4d = _c4d()
    tracks = [
        FakeTrack(_desc_id(c4d.ID_BASEOBJECT_POSITION, 1)),
        FakeTrack(_desc_id(c4d.ID_BASEOBJECT_POSITION, 2)),
    ]
    obj = FakeObject("animated_multi_axis", c4d.Onull, guid="keys-guid", tracks=tracks)
    return FakeDoc(obj), ["animated_multi_axis"]


def _build_camera_shift_doc():
    c4d = _c4d()
    obj = FakeObject(
        "shifted_camera",
        c4d.Ocamera,
        guid="camera-guid",
        params={
            c4d.CAMERAOBJECT_FILM_OFFSET_X: 0.1,
            c4d.CAMERAOBJECT_FILM_OFFSET_Y: -0.05,
        },
    )
    return FakeDoc(obj), ["shifted_camera"]


def _build_unused_materials_doc():
    c4d = _c4d()
    used = FakeMaterial("used_mat", guid="used-guid")
    unused = FakeMaterial("unused_mat", guid="unused-guid")
    tag = FakeTag(c4d.Ttexture, {c4d.TEXTURETAG_MATERIAL: used})
    obj = FakeObject("textured_obj", c4d.Ocube, guid="textured-guid", tags=[tag])
    return FakeDoc(obj, [used, unused]), ["unused_mat"]


def _build_default_names_doc():
    c4d = _c4d()
    obj = FakeObject("Cube.1", c4d.Ocube, guid="default-guid")
    return FakeDoc(obj), ["Cube.1"]


def test_object_identity_distinguishes_same_named_siblings(sentinel_module):
    from sentinel.qc.results import CheckResult, object_identity

    c4d = _c4d()
    parent = FakeObject("parent", c4d.Onull, guid="parent-guid")
    first = parent.add_child(FakeObject("Child", c4d.Ocube, guid="child-guid-0"))
    second = parent.add_child(FakeObject("Child", c4d.Ocube, guid="child-guid-1"))

    first_identity = object_identity(first)
    second_identity = object_identity(second)

    assert first_identity["path"] == "/parent/Child[0]"
    assert second_identity["path"] == "/parent/Child[1]"
    assert first_identity["guid"] == "child-guid-0"
    assert second_identity["guid"] == "child-guid-1"
    assert json.loads(json.dumps(CheckResult("empty_check"))) == {
        "check_id": "empty_check",
        "violations": [],
        "metadata": {},
    }


@pytest.mark.parametrize(
    "builder,structured_name,legacy_name",
    [
        (_build_lights_doc, "check_lights", "check_lights"),
        (_build_visibility_doc, "check_visibility_traps", "check_visibility_traps"),
        (_build_keys_doc, "check_keys", "check_keys"),
        (_build_camera_shift_doc, "check_camera_shift", "check_camera_shift"),
        (_build_unused_materials_doc, "check_unused_materials", "check_unused_materials"),
        (_build_default_names_doc, "check_default_names", "check_default_names"),
    ],
)
def test_migrated_scene_check_wrappers_return_structured_legacy_shape(
    sentinel_module, builder, structured_name, legacy_name
):
    from sentinel.checks import scene

    doc, expected_names = builder()
    sentinel_module.check_cache.clear()

    structured = getattr(scene, structured_name)(doc)
    legacy = getattr(sentinel_module, legacy_name)(doc)

    assert legacy == structured.to_legacy()
    assert [item.GetName() for item in legacy] == expected_names
    json.dumps(structured)


def test_render_conflicts_structured_identity_reduces_to_legacy_int(sentinel_module):
    from sentinel.checks import render

    doc = FakeDoc(render_data=[
        FakeRenderData("render"),
        FakeRenderData("Render"),
        FakeRenderData("custom_preview"),
        FakeRenderData("pre-render"),
        FakeRenderData("rogue preset"),
    ])
    sentinel_module.check_cache.clear()

    structured = render.check_render_conflicts(doc)
    legacy = sentinel_module.check_render_conflicts(doc)

    assert legacy == 3
    assert structured.to_legacy() == legacy
    assert len(structured.violations) == legacy
    assert sentinel_module.check_cache.get(doc, "rdc") == legacy
    assert sentinel_module.check_cache.get(doc, "rdc_structured") == structured

    identities = [violation["identity"] for violation in structured.violations]
    assert identities == [
        {
            "type": "parameter",
            "param": "render_preset",
            "value": "render",
            "preset": "render",
            "field": "duplicate",
        },
        {
            "type": "parameter",
            "param": "render_preset",
            "value": "custom_preview",
            "preset": "custom_preview",
            "field": "extra",
        },
        {
            "type": "parameter",
            "param": "render_preset",
            "value": "rogue_preset",
            "preset": "rogue_preset",
            "field": "extra",
        },
    ]
    json.dumps(structured)
