# -*- coding: utf-8 -*-
"""Typed container scans must not read entries through the wrong getter.

Measured live (C4D 2026.304, macOS, 2026-10-01): opening the Sentinel panel on
a one-cube scene printed 928 ``CRITICAL: Stop [ge_container.h(523)]`` /
``(602)`` / ``basecontainer.cpp(353)`` lines to C4D's stdout, against 0 with
the scene open and the panel closed. The Windows acceptance crash reports
carried the same three stops in bursts of the same size. The scans iterated
every ``(id, value)`` of a container — converting every value — and called
``GetFilename`` / ``GetLink`` on every id whatever its type.

The double below models what C4D does: values are only produced by the
typed getter matching the entry's type, and any other read is recorded as a
misuse, the way C4D asserts.
"""

from sentinel.common import helpers

DA_LONG, DA_FILENAME, DA_ALIASLINK = 15, 30, 133
NOTOK = -1


class TypedContainer:
    def __init__(self, entries):
        self._entries = list(entries)  # [(id, dtype, value)]
        self.misuses = []

    def __iter__(self):
        for cid, dtype, value in self._entries:
            self.misuses.append(("iterate", cid))
            yield cid, value

    def GetIndexId(self, index):
        if 0 <= index < len(self._entries):
            return self._entries[index][0]
        return NOTOK

    def GetType(self, cid):
        for eid, dtype, _ in self._entries:
            if eid == cid:
                return dtype
        return 0

    def _typed(self, cid, wanted):
        for eid, dtype, value in self._entries:
            if eid == cid:
                if dtype != wanted:
                    self.misuses.append(("wrong_type", cid))
                    return None
                return value
        return None

    def GetFilename(self, cid):
        return self._typed(cid, DA_FILENAME)

    def GetLink(self, cid, doc=None):
        return self._typed(cid, DA_ALIASLINK)


def _container():
    return TypedContainer([
        (1000, DA_LONG, 3),
        (1001, DA_FILENAME, "tex/a.png"),
        (1002, DA_ALIASLINK, "<material>"),
        (1003, DA_FILENAME, "hdri/sky.exr"),
    ])


def test_yields_only_ids_of_the_requested_type():
    bc = _container()
    assert list(helpers.container_ids_of_type(bc, DA_FILENAME, NOTOK)) == [1001, 1003]
    assert list(helpers.container_ids_of_type(bc, DA_ALIASLINK, NOTOK)) == [1002]


def test_typed_scan_reads_every_match_without_a_single_misuse():
    bc = _container()
    paths = [bc.GetFilename(cid)
             for cid in helpers.container_ids_of_type(bc, DA_FILENAME, NOTOK)]
    links = [bc.GetLink(cid)
             for cid in helpers.container_ids_of_type(bc, DA_ALIASLINK, NOTOK)]
    assert paths == ["tex/a.png", "hdri/sky.exr"]
    assert links == ["<material>"]
    assert bc.misuses == []


def test_empty_or_missing_container_yields_nothing():
    assert list(helpers.container_ids_of_type(TypedContainer([]), DA_FILENAME, NOTOK)) == []
    assert list(helpers.container_ids_of_type(None, DA_FILENAME, NOTOK)) == []


class _Obj:
    """Object double: ``obj[root, field]`` only succeeds when the root
    parameter exists on the object; touching it otherwise is recorded as the
    assertion C4D raises (measured: 5 ``basecontainer.cpp(353)`` per scan on
    a lone cube — one per entry of RS_OBJECT_FILE_REFS)."""

    def __init__(self, params):
        self._params = params  # {root_id: path}
        self.misuses = []
        root_ids = list(params)
        self._bc = TypedContainer([(rid, 1234, None) for rid in root_ids])

    def GetDataInstance(self):
        return self._bc

    def __getitem__(self, key):
        root, _field = key
        if root not in self._params:
            self.misuses.append(root)
            return None
        return self._params[root]


def test_rs_file_refs_skip_objects_without_the_parameter(sentinel_module):
    from sentinel import textures
    refs = [(501, "Dome HDR"), (502, "IES profile")]
    cube = _Obj({})
    assert textures._rs_object_file_refs(cube, refs, 9000) == []
    assert cube.misuses == []


def test_rs_file_refs_read_the_parameters_an_object_has(sentinel_module):
    from sentinel import textures
    refs = [(501, "Dome HDR"), (502, "IES profile")]
    dome = _Obj({501: "/hdri/sky.exr"})
    assert textures._rs_object_file_refs(dome, refs, 9000) == [
        (501, "Dome HDR", "/hdri/sky.exr")]
    assert dome.misuses == []
