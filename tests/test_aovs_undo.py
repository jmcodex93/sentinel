"""Focused regression coverage for Redshift AOV tier undo ownership."""


class _FakeAOV:
    def __init__(self, parameters=None):
        self.parameters = dict(parameters or {})

    def GetParameter(self, parameter_id):
        return self.parameters.get(parameter_id)

    def SetParameter(self, parameter_id, value):
        self.parameters[parameter_id] = value


class _FakeVideoPost(dict):
    def __init__(self, aovs=(), parameters=None):
        super().__init__(parameters or {})
        self.aovs = list(aovs)


class _UndoableAOVDoc:
    """Replay the CHANGE snapshot contract measured in the real C4D host."""

    def __init__(self, video_post):
        self.video_post = video_post
        self.render_data = object()
        self._bracket = None
        self.undo_stack = []
        self.start_undo_count = 0
        self.end_undo_count = 0
        self.undo_operations = []

    def GetActiveRenderData(self):
        return self.render_data

    def GetFirstObject(self):
        return None

    def StartUndo(self):
        assert self._bracket is None, "nested StartUndo"
        self._bracket = []
        self.start_undo_count += 1

    def AddUndo(self, undo_type, target):
        assert self._bracket is not None, "AddUndo outside a StartUndo bracket"
        self.undo_operations.append((undo_type, target))
        self._bracket.append((target, dict(target), list(target.aovs)))

    def EndUndo(self):
        assert self._bracket is not None, "EndUndo without StartUndo"
        self.undo_stack.append(self._bracket)
        self._bracket = None
        self.end_undo_count += 1

    def do_undo(self):
        assert self.undo_stack, "no undo step"
        for target, parameters, aovs in reversed(self.undo_stack.pop()):
            target.clear()
            target.update(parameters)
            target.aovs = list(aovs)


class _FakeRedshift:
    VPrsrenderer = 1036219

    def __init__(self, doc, fail_set=False):
        self.doc = doc
        self.fail_set = fail_set

    def FindAddVideoPost(self, render_data, renderer_id):
        assert render_data is self.doc.render_data
        assert renderer_id == self.VPrsrenderer
        return self.doc.video_post

    def RendererGetAOVs(self, video_post):
        return list(video_post.aovs)

    def RendererSetAOVs(self, video_post, aovs):
        if self.fail_set:
            raise RuntimeError("renderer rejected AOV list")
        video_post.aovs = list(aovs)

    def RSAOV(self):
        return _FakeAOV()


def _install_aov_host(monkeypatch, aovs, *, fail_set=False):
    import c4d

    original = _FakeAOV({
        c4d.REDSHIFT_AOV_NAME: "Artist Custom",
        c4d.REDSHIFT_AOV_TYPE: 900001,
    })
    video_post = _FakeVideoPost(
        [original],
        {
            c4d.REDSHIFT_RENDERER_AOV_GLOBAL_MODE: -1,
            c4d.REDSHIFT_RENDERER_AOV_MULTIPART: False,
            c4d.REDSHIFT_RENDERER_AOV_FILE_BIT_DEPTH: -2,
            c4d.REDSHIFT_RENDERER_AOV_FILE_COMPRESSION: -3,
        },
    )
    doc = _UndoableAOVDoc(video_post)
    redshift = _FakeRedshift(doc, fail_set=fail_set)

    monkeypatch.setattr(aovs, "REDSHIFT_AVAILABLE", True)
    monkeypatch.setattr(aovs, "redshift", redshift, raising=False)
    monkeypatch.setattr(aovs.GlobalSettings, "get", lambda key, default=None: default)
    monkeypatch.setattr(aovs.check_cache, "clear", lambda: None)
    return doc, original


def test_force_aov_tier_is_one_replayable_undo_for_globals_and_aovs(
        sentinel_module, monkeypatch):
    import c4d
    from sentinel import aovs

    doc, original = _install_aov_host(monkeypatch, aovs)
    before_globals = dict(doc.video_post)
    before_aovs = list(doc.video_post.aovs)

    added, error = aovs.force_aov_tier(doc, aovs.AOV_TIER_ESSENTIALS)

    assert error is None
    assert added == len(aovs.AOV_TIER_ESSENTIALS)
    assert doc.start_undo_count == 1
    assert doc.end_undo_count == 1
    assert doc.undo_operations == [(c4d.UNDOTYPE_CHANGE, doc.video_post)]
    assert doc.video_post[c4d.REDSHIFT_RENDERER_AOV_MULTIPART] is True
    assert doc.video_post.aovs[0] is original
    assert len(doc.video_post.aovs) == len(before_aovs) + added

    doc.do_undo()

    assert dict(doc.video_post) == before_globals
    assert doc.video_post.aovs == before_aovs


def test_force_aov_tier_balances_undo_when_renderer_write_fails(
        sentinel_module, monkeypatch):
    from sentinel import aovs

    doc, _original = _install_aov_host(monkeypatch, aovs, fail_set=True)

    added, error = aovs.force_aov_tier(doc, ["Beauty"])

    assert added == 0
    assert "renderer rejected AOV list" in error
    assert doc.start_undo_count == 1
    assert doc.end_undo_count == 1
    doc.do_undo()
