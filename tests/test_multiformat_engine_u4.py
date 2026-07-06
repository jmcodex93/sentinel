import pytest

from sentinel import framing


class FakeRenderData(dict):
    def __init__(self, c4d, name="Source", width=1920, height=1080, path="out/$prj_$frame"):
        super().__init__()
        self._name = name
        self[c4d.RDATA_XRES] = float(width)
        self[c4d.RDATA_YRES] = float(height)
        self[c4d.RDATA_PATH] = path

    def GetClone(self, flags):
        clone = FakeRenderData.__new__(FakeRenderData)
        dict.__init__(clone, self)
        clone._name = self._name
        return clone

    def SetName(self, name):
        self._name = name

    def GetName(self):
        return self._name


class FakeOverride:
    def __init__(self):
        self.params = {}
        self.updated = []

    def IsOverriddenParam(self, descid):
        return descid[0].id in self.params

    def SetParameter(self, descid, value, flags):
        self.params[descid[0].id] = value
        return True

    def UpdateSceneNode(self, take_data, descid):
        self.updated.append(descid[0].id)
        return True


class FakeCamera(dict):
    def __bool__(self):
        return True

    def GetType(self):
        return 5103  # c4d.Ocamera — a standard camera (aperture crop supported)

    __hash__ = object.__hash__


class FakeTake:
    def __init__(self, name, parent=None):
        self._name = name
        self.parent = parent
        self.children = []
        self.render_data = None
        self.camera = None
        self.overrides = {}
        self.override_requests = []
        if parent is not None:
            parent.children.append(self)

    def GetName(self):
        return self._name

    def SetName(self, name):
        self._name = name

    def GetDown(self):
        return self.children[0] if self.children else None

    def GetNext(self):
        if self.parent is None:
            return None
        siblings = self.parent.children
        try:
            index = siblings.index(self)
        except ValueError:
            return None
        return siblings[index + 1] if index + 1 < len(siblings) else None

    def GetEffectiveRenderData(self, take_data):
        return self.render_data or take_data.doc.render_datas[0]

    def GetRenderData(self, take_data):
        return self.render_data

    def SetRenderData(self, take_data, render_data):
        self.render_data = render_data

    def GetCamera(self, take_data):
        return self.camera

    def SetCamera(self, take_data, camera):
        self.camera = camera

    def FindOverride(self, take_data, camera):
        return self.overrides.get(camera)

    def FindOrAddOverrideParam(self, take_data, camera, descid, value):
        self.override_requests.append(descid[0].id)
        override = self.overrides.setdefault(camera, FakeOverride())
        override.SetParameter(descid, value, 0)
        return override


class FakeTakeData:
    def __init__(self, doc):
        self.doc = doc
        self.main = FakeTake("Main")
        self.main.render_data = doc.render_datas[0]
        self.current = self.main

    def GetMainTake(self):
        return self.main

    def GetCurrentTake(self):
        return self.current

    def AddTake(self, name, parent, pred):
        return FakeTake(name, parent or self.main)


class FakeBaseDraw:
    def __init__(self, camera):
        self.camera = camera

    def GetSceneCamera(self, doc):
        return self.camera


class FakeDocument:
    def __init__(self, c4d, camera=None):
        self.render_datas = [FakeRenderData(c4d)]
        self.camera = camera or FakeCamera()
        self.camera[framing.CAMERA_FOCUS] = 36.0
        self.camera[framing.CAMERAOBJECT_APERTURE] = 36.0
        self.camera[framing.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
        self.camera[framing.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
        self.take_data = FakeTakeData(self)
        self.take_data.main.SetCamera(self.take_data, self.camera)
        self.undo = []
        self.start_undo_count = 0
        self.end_undo_count = 0

    def GetTakeData(self):
        return self.take_data

    def GetActiveRenderData(self):
        return self.render_datas[0]

    def GetActiveBaseDraw(self):
        return FakeBaseDraw(self.camera)

    def InsertRenderDataLast(self, render_data):
        self.render_datas.append(render_data)

    def StartUndo(self):
        self.start_undo_count += 1

    def EndUndo(self):
        self.end_undo_count += 1

    def AddUndo(self, undo_type, target):
        self.undo.append((undo_type, target))


def _child_names(take):
    return [child.GetName() for child in take.children]


def _child_by_name(take, name):
    for child in take.children:
        if child.GetName() == name:
            return child
    raise AssertionError(f"missing child take {name}")


def test_generate_takes_uses_name_prefix_and_keeps_legacy_names_without_prefix(sentinel_module):
    mf = sentinel_module.multiformat

    prefixed_doc = FakeDocument(sentinel_module.c4d)
    prefixed = mf.generate_multiformat_takes(
        prefixed_doc,
        {
            "formats": ["16x9", "9x16"],
            "name_prefix": "CamA",
            "update_existing": True,
        },
    )

    assert prefixed["success"] is True
    assert prefixed["created"] == ["CamA_16x9", "CamA_9x16"]
    assert _child_names(prefixed_doc.take_data.main) == ["CamA_16x9", "CamA_9x16"]

    legacy_doc = FakeDocument(sentinel_module.c4d)
    legacy = mf.generate_multiformat_takes(
        legacy_doc,
        {"formats": ["16x9"], "update_existing": True},
    )

    assert legacy["created"] == ["16x9"]
    assert legacy["orphaned"] == []
    assert legacy["adopted"] == []
    assert _child_names(legacy_doc.take_data.main) == ["16x9"]


def test_generate_takes_applies_film_offsets_only_for_requested_formats(sentinel_module):
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)

    report = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["16x9", "9x16"],
            "name_prefix": "CamA",
            "film_offsets": {"9x16": (0.05, -0.03)},
        },
    )

    assert report["errors"] == []
    landscape = _child_by_name(doc.take_data.main, "CamA_16x9")
    vertical = _child_by_name(doc.take_data.main, "CamA_9x16")
    vertical_override = vertical.FindOverride(doc.take_data, doc.camera)

    # 16x9 requested with (0,0) nudge -> its override, if any, is a zero offset.
    landscape_override = landscape.FindOverride(doc.take_data, doc.camera)
    if landscape_override is not None:
        assert landscape_override.params.get(framing.CAMERAOBJECT_FILM_OFFSET_X, 0.0) == pytest.approx(0.0)
    # The nudge is a fraction of available travel: the engine must scale it by
    # the per-format film travel (same math the viewport guide uses), NOT write
    # the raw nudge. Expected values come straight from framing.
    _f, exp_x, exp_y = framing.format_camera_framing_values(
        36.0, 1920, 1080, 1080, 1920, framing.COMPENSATE_OFF, (0.05, -0.03), 0.0, 0.0)
    assert exp_x == pytest.approx(0.05 * (0.5 * (1.0 - (1080.0 / 1920.0) / (1920.0 / 1080.0))))
    assert vertical_override.params[framing.CAMERAOBJECT_FILM_OFFSET_X] == pytest.approx(exp_x)
    assert vertical_override.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] == pytest.approx(exp_y)


def test_source_cam_option_binds_takes_and_offsets_to_host_camera(sentinel_module):
    # A Sentinel Frame tag on CamA must generate Takes bound to CamA even when
    # the viewport/Main take resolves to a different camera. The engine binds
    # to options["source_cam"] when given (the tag passes its host camera).
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)  # doc.camera = the "wrong" viewport cam
    host = FakeCamera()
    host[framing.CAMERA_FOCUS] = 36.0
    host[framing.CAMERAOBJECT_APERTURE] = 36.0
    host[framing.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
    host[framing.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0

    report = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["9x16"],
            "name_prefix": "CamA",
            "source_cam": host,
            "film_offsets": {"9x16": (0.12, -0.06)},
        },
    )

    assert report["errors"] == []
    take = _child_by_name(doc.take_data.main, "CamA_9x16")
    assert take.camera is host
    assert take.camera is not doc.camera
    # Film offset override lands on the host camera, not the viewport camera,
    # and is travel-scaled (matches the guide), not the raw nudge.
    assert take.FindOverride(doc.take_data, doc.camera) is None
    host_override = take.FindOverride(doc.take_data, host)
    _f, exp_x, exp_y = framing.format_camera_framing_values(
        36.0, 1920, 1080, 1080, 1920, framing.COMPENSATE_OFF, (0.12, -0.06), 0.0, 0.0)
    assert host_override.params[framing.CAMERAOBJECT_FILM_OFFSET_X] == pytest.approx(exp_x)
    assert host_override.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] == pytest.approx(exp_y)


def test_generate_takes_without_source_cam_falls_back_to_resolved_camera(sentinel_module):
    # Regression: legacy dialog path (no source_cam) still binds to the
    # resolved viewport/Main camera exactly as before.
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)

    report = mf.generate_multiformat_takes(
        doc,
        {"formats": ["16x9"], "name_prefix": "CamA"},
    )

    assert report["errors"] == []
    take = _child_by_name(doc.take_data.main, "CamA_16x9")
    assert take.camera is doc.camera


def test_existing_take_resolver_is_rename_safe_and_avoids_duplicates(sentinel_module):
    # KTD4: a re-run must re-find its own Takes via the tag's tracked links
    # even after the take — or the host camera (the name prefix) — is renamed,
    # instead of orphaning them and creating duplicates.
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)

    links = {}
    first = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["16x9", "9x16"],
            "name_prefix": "CamA",
            "tag_link_writer": lambda fmt_id, take: links.__setitem__(fmt_id, take),
        },
    )
    assert sorted(first["created"]) == ["CamA_16x9", "CamA_9x16"]
    assert set(links) == {"16x9", "9x16"}

    # Simulate the host camera renamed CamA -> CamB: the prefix changes, but the
    # resolver still hands back the original takes by link.
    second = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["16x9", "9x16"],
            "name_prefix": "CamB",
            "existing_take_resolver": lambda fmt_id: links.get(fmt_id),
            "tag_link_writer": lambda fmt_id, take: links.__setitem__(fmt_id, take),
        },
    )

    names = _child_names(doc.take_data.main)
    # Exactly two takes, renamed to the new prefix — no CamA_* orphans/duplicates.
    assert sorted(names) == ["CamB_16x9", "CamB_9x16"]
    assert second["created"] == []
    assert sorted(second["updated"]) == ["CamB_16x9", "CamB_9x16"]
    # The very same take objects were adopted, not recreated.
    assert links["16x9"].GetName() == "CamB_16x9"


def test_crop_mode_overrides_aperture_and_gate_relative_film_offset(sentinel_module):
    # The default "crop" mode must scale the film gate (aperture) to the
    # inscribed crop and pan with a gate-relative film offset — matching the
    # viewport guide (WYSIWYG), leaving focal length untouched.
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)  # source 1920x1080, aperture 36

    mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["1x1"],
            "name_prefix": "CamA",
            "composition_mode": "crop",
            "film_offsets": {"1x1": (1.0, 0.0)},  # full-right nudge
        },
    )

    take = _child_by_name(doc.take_data.main, "CamA_1x1")
    override = take.FindOverride(doc.take_data, doc.camera)
    exp_ap, exp_fx, exp_fy = framing.format_crop_values(
        36.0, 1920, 1080, 1080, 1080, (1.0, 0.0), 0.0, 0.0)

    assert override.params[framing.CAMERAOBJECT_APERTURE] == pytest.approx(exp_ap)
    assert override.params[framing.CAMERAOBJECT_APERTURE] == pytest.approx(20.25)
    assert override.params[framing.CAMERAOBJECT_FILM_OFFSET_X] == pytest.approx(exp_fx)
    assert override.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] == pytest.approx(exp_fy)
    # Focal length is NOT overridden in crop mode (DOF/zoom preserved).
    assert framing.CAMERA_FOCUS not in override.params


def test_crop_mode_wider_target_needs_no_aperture_override(sentinel_module):
    # A wider-or-equal target crops via the resolution change alone (C4D keeps
    # horizontal FOV, aspect crops top/bottom). No aperture override is written,
    # so it works identically on any camera, including Redshift.
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)  # 16:9 master
    mf.generate_multiformat_takes(
        doc, {"formats": ["21x9"], "name_prefix": "CamA", "composition_mode": "crop"})

    take = _child_by_name(doc.take_data.main, "CamA_21x9")
    override = take.FindOverride(doc.take_data, doc.camera)
    assert override is None or framing.CAMERAOBJECT_APERTURE not in override.params


def test_crop_mode_on_redshift_camera_skips_aperture_for_narrower_target(sentinel_module):
    # A narrower-than-master crop needs a horizontal aperture change, which
    # Redshift cameras don't track cleanly — the engine skips it (falls back to
    # EXTEND) and records a note instead of producing a wrong, snapped crop.
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)

    class RSCam(FakeCamera):
        def GetType(self):
            return 1057516  # Orscamera

    rs = RSCam()
    rs[framing.CAMERA_FOCUS] = 36.0
    rs[framing.CAMERAOBJECT_APERTURE] = 36.0
    rs[framing.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
    rs[framing.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0

    report = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["9x16"],  # narrower than the 16:9 master
            "name_prefix": "CamA",
            "composition_mode": "crop",
            "source_cam": rs,
        },
    )

    take = _child_by_name(doc.take_data.main, "CamA_9x16")
    override = take.FindOverride(doc.take_data, rs)
    assert override is None or framing.CAMERAOBJECT_APERTURE not in override.params
    assert any("narrower" in n.lower() for n in report.get("notes", []))


def test_external_undo_skips_engine_undo_block(sentinel_module):
    # The tag owns the undo block (so a single Cmd+Z reverts takes + its
    # BaseLink/signature writes); the engine must not open a nested one.
    mf = sentinel_module.multiformat

    managed = FakeDocument(sentinel_module.c4d)
    mf.generate_multiformat_takes(managed, {"formats": ["16x9"], "name_prefix": "CamA"})
    assert managed.start_undo_count == 1
    assert managed.end_undo_count == 1

    external = FakeDocument(sentinel_module.c4d)
    mf.generate_multiformat_takes(
        external, {"formats": ["16x9"], "name_prefix": "CamA", "external_undo": True})
    assert external.start_undo_count == 0
    assert external.end_undo_count == 0


def test_adopted_take_with_shared_render_data_gets_a_fresh_clone(sentinel_module):
    # A take adopted via existing_take_resolver may point at the SHARED source
    # render data; the engine must clone a dedicated one instead of writing this
    # format's resolution/path onto the source (which would corrupt base output).
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)
    source_rd = doc.render_datas[0]

    # Pre-existing take whose render data IS the shared source render data.
    victim = FakeTake("CamA_16x9", doc.take_data.main)
    victim.SetRenderData(doc.take_data, source_rd)

    mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["16x9"],
            "name_prefix": "CamA",
            "existing_take_resolver": lambda fmt_id: victim,
        },
    )

    # The take now owns a dedicated clone, and the source render data is intact.
    assert victim.render_data is not source_rd
    assert victim.render_data.GetName() == "Source_16x9"
    assert source_rd[sentinel_module.c4d.RDATA_XRES] == pytest.approx(1920.0)
    assert source_rd[sentinel_module.c4d.RDATA_YRES] == pytest.approx(1080.0)


def test_preserve_vertical_overrides_camera_focus_with_compensated_value(sentinel_module):
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)
    doc.camera[framing.CAMERA_FOCUS] = 36.0

    report = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["9x16"],
            "name_prefix": "CamA",
            "composition_mode": mf.COMPOSITION_MODE_PRESERVE_VERTICAL,
        },
    )

    take = _child_by_name(doc.take_data.main, "CamA_9x16")
    override = take.FindOverride(doc.take_data, doc.camera)
    expected = framing.compensated_focus(
        36.0,
        1920,
        1080,
        1080,
        1920,
        mf.COMPOSITION_MODE_PRESERVE_VERTICAL,
    )

    assert report["errors"] == []
    assert override.params[framing.CAMERA_FOCUS] == pytest.approx(expected)


def test_reset_camera_dimensions_to_native_clears_film_offset_overrides(sentinel_module):
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)
    take = FakeTake("CamA_9x16", doc.take_data.main)
    override = take.overrides.setdefault(doc.camera, FakeOverride())
    override.params[framing.CAMERAOBJECT_FILM_OFFSET_X] = 0.25
    override.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] = -0.10

    mf._reset_camera_dimensions_to_native(take, doc.take_data, doc.camera)

    assert override.params[framing.CAMERAOBJECT_FILM_OFFSET_X] == pytest.approx(0.0)
    assert override.params[framing.CAMERAOBJECT_FILM_OFFSET_Y] == pytest.approx(0.0)
    assert framing.CAMERAOBJECT_FILM_OFFSET_X in override.updated
    assert framing.CAMERAOBJECT_FILM_OFFSET_Y in override.updated


def test_prefixed_existing_takes_report_orphaned_and_adopted_without_deleting(sentinel_module):
    mf = sentinel_module.multiformat
    doc = FakeDocument(sentinel_module.c4d)
    existing = FakeTake("CamA_16x9", doc.take_data.main)
    orphan = FakeTake("CamA_1x1", doc.take_data.main)

    links = []
    report = mf.generate_multiformat_takes(
        doc,
        {
            "formats": ["16x9"],
            "name_prefix": "CamA",
            "tag_link_writer": lambda fmt_id, take: links.append((fmt_id, take)),
        },
    )

    assert report["updated"] == ["CamA_16x9"]
    assert report["adopted"] == ["CamA_16x9"]
    assert report["orphaned"] == ["1x1"]
    assert orphan in doc.take_data.main.children
    assert existing in doc.take_data.main.children
    assert links == [("16x9", existing)]
