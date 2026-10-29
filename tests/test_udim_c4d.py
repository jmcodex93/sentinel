# -*- coding: utf-8 -*-
"""QC #14 adapter (v1.43): which tiles each UDIM material is rendered on.
The fakes model what the adapter relies on from C4D: tags in order, a
Polygon Selection restriction by name, tags inherited from parents, the
projection, the UVW tag's low-level float32 buffer (8 floats per polygon,
measured 2026.304), a primitive's cache, and dirty counters."""

import array
import itertools

import pytest

_GUIDS = itertools.count(1)


class _Select:
    def __init__(self, indices):
        self._on = set(indices)

    def GetAll(self, count):
        return [1 if i in self._on else 0 for i in range(count)]


class _Tag:
    def __init__(self, type_id, name="", data=None, dirty=0, select=None, uv=None):
        self._type = type_id
        self._name = name
        self._data = dict(data or {})
        self.dirty = dirty
        self._select = select
        self._uv = uv
        self.reads = 0

    def GetType(self):
        return self._type

    def GetName(self):
        return self._name

    def __getitem__(self, key):
        return self._data.get(key)

    def GetDirty(self, _flags):
        return self.dirty

    def GetBaseSelect(self):
        return self._select

    def GetLowlevelDataAddressR(self):
        self.reads += 1
        return memoryview(self._uv.tobytes())


class _Obj:
    def __init__(self, name, tags=(), children=(), cache=None):
        self._name = name
        self._tags = list(tags)
        self._children = list(children)
        self._cache = cache
        self._next = None
        self._guid = next(_GUIDS)
        self.dirty = 0
        for a, b in zip(self._children, self._children[1:]):
            a._next = b

    def GetName(self):
        return self._name

    def GetTags(self):
        return list(self._tags)

    def GetTag(self, type_id):
        return next((t for t in self._tags if t.GetType() == type_id), None)

    def GetDown(self):
        return self._children[0] if self._children else None

    def GetNext(self):
        return self._next

    def GetCache(self):
        return self._cache

    def GetDeformCache(self):
        return None

    def GetGUID(self):
        return self._guid

    def GetDirty(self, _flags):
        return self.dirty


class _Doc:
    def __init__(self, *roots):
        self._roots = list(roots)
        for a, b in zip(self._roots, self._roots[1:]):
            a._next = b

    def GetFirstObject(self):
        return self._roots[0] if self._roots else None


def _quad(u0, v0, u1, v1):
    return [u0, v1, u0, v0, u1, v0, u1, v1]


@pytest.fixture()
def env(sentinel_module, monkeypatch):
    import c4d
    from sentinel import udim_c4d

    class Poly(_Obj):
        def __init__(self, name, quads, tags=(), selections=None, **kw):
            self.uvw = _Tag(c4d.Tuvw, uv=array.array("f", [f for q in quads for f in q]))
            sel_tags = [_Tag(c4d.Tpolygonselection, name=n, select=_Select(ix))
                        for n, ix in (selections or {}).items()]
            super().__init__(name, list(tags) + [self.uvw] + sel_tags, **kw)
            self._count = len(quads)

        def GetPolygonCount(self):
            return self._count

    monkeypatch.setattr(c4d, "PolygonObject", Poly, raising=False)
    monkeypatch.setattr(udim_c4d, "_TILE_CACHE", {})

    def texture(material, restriction="", projection=None):
        return _Tag(c4d.Ttexture, data={
            c4d.TEXTURETAG_MATERIAL: material,
            c4d.TEXTURETAG_RESTRICTION: restriction,
            c4d.TEXTURETAG_PROJECTION: (c4d.TEXTURETAG_PROJECTION_UVW
                                        if projection is None else projection)})

    return c4d, udim_c4d, Poly, texture


QUADS = [_quad(0, 0, 1, 1), _quad(1, 0, 2, 1), _quad(4, 0, 5, 1)]  # 1001, 1002, 1005


def _by_name(result, materials):
    return {obj.GetName(): {materials[i][0]: tiles for i, tiles in per.items()}
            for obj, per in result}


def test_unrestricted_tag_covers_every_polygon(env):
    _c4d, udim_c4d, Poly, texture = env
    mats = [("body", [("b.<UDIM>.png", [1001])])]
    mesh = Poly("Mesh", QUADS, tags=[texture("body")])
    assert _by_name(udim_c4d.used_tiles(_Doc(mesh), mats), mats) == \
        {"Mesh": {"body": {1001, 1002, 1005}}}


def test_a_later_restricted_tag_takes_its_selection(env):
    """LOK: grip (1005) restricted to its selection over cuerpo on the mesh."""
    _c4d, udim_c4d, Poly, texture = env
    mats = [("cuerpo", []), ("grip", [])]
    mesh = Poly("LOK", QUADS, tags=[texture("cuerpo"), texture("grip", "grip_sel")],
                selections={"grip_sel": [2]})
    assert _by_name(udim_c4d.used_tiles(_Doc(mesh), mats), mats) == \
        {"LOK": {"cuerpo": {1001, 1002}, "grip": {1005}}}


def test_restriction_to_a_missing_selection_covers_nothing(env):
    _c4d, udim_c4d, Poly, texture = env
    mats = [("grip", [])]
    mesh = Poly("LOK", QUADS, tags=[texture("grip", "nope")])
    assert udim_c4d.used_tiles(_Doc(mesh), mats) == []


def test_parent_tags_sit_under_the_child_own(env):
    _c4d, udim_c4d, Poly, texture = env
    mats = [("parent_mat", []), ("child_mat", [])]
    plain = Poly("Plain", QUADS[:1])
    tagged = Poly("Tagged", QUADS[1:2], tags=[texture("child_mat")])
    group = _Obj("Group", tags=[texture("parent_mat")], children=[plain, tagged])
    assert _by_name(udim_c4d.used_tiles(_Doc(group), mats), mats) == {
        "Plain": {"parent_mat": {1001}}, "Tagged": {"child_mat": {1002}}}


def test_non_uvw_projection_and_non_udim_materials_read_no_uvs(env):
    c4d, udim_c4d, Poly, texture = env
    mats = [("body", [])]
    cubic = Poly("Cubic", QUADS, tags=[texture("body", projection=c4d.TEXTURETAG_PROJECTION_UVW + 1)])
    other = Poly("Other", QUADS, tags=[texture("plain_mat")])
    assert udim_c4d.used_tiles(_Doc(cubic, other), mats) == []
    assert cubic.uvw.reads == 0 and other.uvw.reads == 0


def test_a_non_udim_tag_on_top_hides_the_polygons_below(env):
    _c4d, udim_c4d, Poly, texture = env
    mats = [("body", [])]
    mesh = Poly("Mesh", QUADS, tags=[texture("body"), texture("plain_mat", "top")],
                selections={"top": [0, 1]})
    assert _by_name(udim_c4d.used_tiles(_Doc(mesh), mats), mats) == {"Mesh": {"body": {1005}}}


def test_a_primitive_is_read_from_its_cache_and_reported_as_itself(env):
    _c4d, udim_c4d, Poly, texture = env
    mats = [("body", [])]
    cache = Poly("cache", QUADS[:2])
    prim = _Obj("Sphere", tags=[texture("body")], cache=cache)
    assert _by_name(udim_c4d.used_tiles(_Doc(prim), mats), mats) == {"Sphere": {"body": {1001, 1002}}}


def test_unchanged_mesh_is_not_read_again_until_it_is_dirty(env):
    _c4d, udim_c4d, Poly, texture = env
    mats = [("body", [])]
    mesh = Poly("Mesh", QUADS, tags=[texture("body")])
    doc = _Doc(mesh)
    first = udim_c4d.used_tiles(doc, mats)
    assert udim_c4d.used_tiles(doc, mats) == first
    assert mesh.uvw.reads == 1
    mesh.uvw.dirty += 1
    udim_c4d.used_tiles(doc, mats)
    assert mesh.uvw.reads == 2


def test_udim_materials_groups_maps_and_skips_patterns_without_tiles(env, tmp_path):
    _c4d, udim_c4d, _Poly, _texture = env
    for name in ("rock_Base.1001.png", "rock_Base.1002.png", "rock_Rough.1001.png"):
        (tmp_path / name).write_bytes(b"x")
    mat, other = object(), object()
    recs = [
        {"host": mat, "current_path": "tex/rock_Base.<UDIM>.png",
         "resolved": str(tmp_path / "rock_Base.<UDIM>.png")},
        {"host": mat, "current_path": "tex/rock_Rough.<UDIM>.png",
         "resolved": str(tmp_path / "rock_Rough.<UDIM>.png")},
        {"host": other, "current_path": "tex/gone.<UDIM>.png",
         "resolved": str(tmp_path / "gone.<UDIM>.png")},
        {"host": other, "current_path": "tex/plain.png", "resolved": str(tmp_path / "plain.png")},
    ]
    assert udim_c4d.udim_materials(recs) == [
        (mat, [("rock_Base.<UDIM>.png", [1001, 1002]), ("rock_Rough.<UDIM>.png", [1001])])]


class _Named:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name

    def GetUp(self):
        return None

    def GetNext(self):
        return None

    def GetPred(self):
        return None


def _run_check(monkeypatch, materials, used):
    from sentinel.checks import udim as udim_check
    from sentinel.common.cache import check_cache
    check_cache.clear()
    monkeypatch.setattr(udim_check, "scan_all_texture_paths", lambda doc: [])
    monkeypatch.setattr(udim_check, "udim_materials", lambda recs: materials)
    monkeypatch.setattr(udim_check, "used_tiles",
                        used if callable(used) else (lambda doc, mats: used))
    try:
        return udim_check.check_udim_tiles(object(), rules_context=object())
    finally:
        check_cache.clear()


def test_check_flags_the_object_and_names_tiles_and_materials(sentinel_module, monkeypatch):
    body = _Named("Body")
    mats = [(_Named("LOK_cuerpo"), [("a.<UDIM>.png", [1001]), ("b.<UDIM>.png", [1001]),
                                    ("c.<UDIM>.png", [1001, 1005])])]
    result = _run_check(monkeypatch, mats, [(body, {0: {1001, 1005}})])
    assert result.to_legacy() == [body]  # the select action cycles objects
    (violation,) = result.violations
    assert violation.message == "Body: tile 1005 has no texture (LOK_cuerpo: 2 maps) — renders black"
    assert violation.identity["path"] == "/Body"
    assert violation.extras["materials"][0]["missing"] == [1005]


def test_check_is_ok_when_every_used_tile_has_texture(sentinel_module, monkeypatch):
    mats = [(_Named("m"), [("a.<UDIM>.png", [1001, 1002])])]
    result = _run_check(monkeypatch, mats, [(_Named("Body"), {0: {1001}})])
    assert result.violations == [] and result.to_legacy() == []


def test_check_reads_no_uvs_without_udim_materials(sentinel_module, monkeypatch):
    calls = []
    result = _run_check(monkeypatch, [], lambda doc, mats: calls.append(mats) or [])
    assert result.violations == [] and calls == []


def test_violation_message_out_of_range_and_several_tiles(sentinel_module):
    from sentinel.checks.udim import violation_message
    gaps = [{"material": "m", "missing": [1003, 1004], "maps": ["a"], "out_of_range": True}]
    assert violation_message("Plane", gaps) == \
        "Plane: tiles 1003–1004 have no texture (m: 1 map); UVs outside the UDIM range — renders black"
