# -*- coding: utf-8 -*-
"""Tests for the Material Graph c4d adapter (``sentinel.matgraph_c4d``).

Two-surface fake graph harness (per the Task 2 brief): models exactly what
the live spike measured (``docs/research/2026-08-27-matgraph-spike.md``) —

- A node's TOP-LEVEL ``GetInputs()``/``GetOutputs()`` children carry FULL
  id strings (e.g. ``"com...texturesampler.tex0"``).
- A GROUP port's OWN children (``tex0``'s ``path``/``colorspace``) carry
  SHORT id strings (``"path"``, ``"colorspace"``).
- ``GetConnections(direction, out_list)`` FILLS the passed list with the
  connected ports on the other end and returns ``True``; an empty fill
  means "unconnected", not an error.
- ``GetPortValue()`` returns ``None`` for an unset colorspace (the "auto"
  state — no sentinel string exists for it, per the spike).
- Node deletion is ``node.Remove()`` inside a
  ``graph.BeginTransaction()``/``Commit()`` pair.

What this harness does NOT model (stated once, house rule — fakes lie
otherwise): real maxon ``Id``/``Data`` typing and coercion, wire "modes"
or partial connections, more than one level of port-group nesting beyond
``tex0``, and anything about undo REPLAY (the fake's
``StartUndo``/``EndUndo``/``AddUndo`` only record calls; they never
actually revert a mutation, and a rolled-back ``Commit()`` in this
harness leaves whatever ``SetPortValue``/``Remove`` calls already ran
recorded — only the module-under-test's OWN counters are expected to
stay honest about that, not the fake's bookkeeping).

``GraphNode`` wrapper identity across reads: the DEFAULT harness
(``FakeGraph``/``FakeNode``/``FakeMaterial``) keeps node objects stable
across "reads" (calling ``GetGraph()`` twice returns the same objects),
which is fine for every test that doesn't care about cross-read handle
identity. ``MultiReadMaterial``/``_MultiReadNodeMatRef`` are a SEPARATE,
opt-in surface that DOES model the real API's fresh-wrapper-per-read
behavior (see ``reference_c4d_wrapper_identity``) — a new graph object,
with new node objects but the SAME ``GetPath()`` strings, on each
successive ``GetGraph()`` call — used specifically to prove a mutation
only touches handles from the read its transaction is bound to.
"""

import pytest


# ---------------------------------------------------------------------------
# Fake maxon surface
# ---------------------------------------------------------------------------

class _NODE_KIND:
    NODE = "NODE_KIND.NODE"


class _PORT_DIR:
    OUTPUT = "PORT_DIR.OUTPUT"


class _FakeMaxon:
    """Just enough of the ``maxon`` namespace for the module under test —
    two enum-ish holders, nothing about the real type system."""
    NODE_KIND = _NODE_KIND
    PORT_DIR = _PORT_DIR


class FakePort:
    """One port (leaf or group). ``full_id`` is what ``GetId()`` returns —
    the caller decides whether that's a full or short id string, matching
    which level of the tree it models."""

    def __init__(self, full_id, node):
        self.full_id = full_id
        self.node = node          # owning FakeNode
        self._children = []
        self._value = None
        self._targets = []        # FakePort list — GetConnections(OUTPUT) fill

    def add_child(self, port):
        self._children.append(port)
        return port

    def GetId(self):
        return self.full_id

    def GetChildren(self):
        return list(self._children)

    def GetPortValue(self):
        return self._value

    def SetPortValue(self, value):
        self.node.graph.set_port_calls.append((self.node.node_id, self.full_id, value))
        self._value = value

    def connect_to(self, other_port):
        self._targets.append(other_port)

    def GetConnections(self, direction, out_list):
        # MEASURED LIVE (v1.38 verification): the real API fills the list
        # with TUPLES ``(port, wire-data)`` — the SDK example reads
        # ``connection[0]``. The first version of this fake extended bare
        # ports and let production ship code that called GraphNode methods
        # on the tuple ('tuple' object has no attribute 'GetAncestor' on
        # every real material). The fake now models the real shape.
        out_list.extend((t, object()) for t in self._targets)
        return True

    def GetAncestor(self, kind):
        return self.node


class FakeNode:
    def __init__(self, graph, node_id, assetid):
        self.graph = graph
        self.node_id = node_id
        self._assetid = assetid
        self._values = {"net.maxon.node.attribute.assetid": assetid}
        self.inputs = FakePort(node_id + ".$in", self)
        self.outputs = FakePort(node_id + ".$out", self)
        self.raise_on_get_value = False

    def GetPath(self):
        return self.node_id

    def GetValue(self, key):
        if self.raise_on_get_value:
            raise RuntimeError("boom: unreadable node")
        return self._values.get(key)

    def GetInputs(self):
        return self.inputs

    def GetOutputs(self):
        return self.outputs

    def Remove(self):
        self.graph.remove_calls.append(self.node_id)


class FakeTransaction:
    def __init__(self, graph):
        self.graph = graph

    def __enter__(self):
        self.graph.transactions.append("begin")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def Commit(self):
        if self.graph.raise_on_commit:
            self.graph.transactions.append("commit-raised")
            raise RuntimeError("boom: commit failed, transaction rolled back")
        self.graph.transactions.append("commit")


class FakeViewRoot:
    def __init__(self, graph):
        self.graph = graph
        self.raise_on_get_inner_nodes = False

    def GetInnerNodes(self, mask=None, includeThis=False):
        if self.raise_on_get_inner_nodes:
            raise RuntimeError("boom: broken graph enumeration")
        return list(self.graph.nodes)


class FakeGraph:
    def __init__(self):
        self.begin_transaction_user_data = []
        self.nodes = []
        self.remove_calls = []
        self.set_port_calls = []
        self.transactions = []
        self.raise_on_commit = False
        self._view_root = FakeViewRoot(self)

    def add_node(self, node_id, assetid):
        node = FakeNode(self, node_id, assetid)
        self.nodes.append(node)
        return node

    def GetViewRoot(self):
        return self._view_root

    def BeginTransaction(self, user_data=None):
        # Real signature accepts optional user_data (UNDO_MODE.ADD join —
        # measured live in v1.38: without it a two-material Fix needed two
        # Cmd+Z presses). Recorded so the join idiom is pinned.
        self.begin_transaction_user_data.append(user_data)
        return FakeTransaction(self)


class FakeNodeMatRef:
    def __init__(self, graph, has_space=True):
        self._graph = graph
        self._has_space = has_space

    def HasSpace(self, space_id):
        return self._has_space

    def GetGraph(self, space_id):
        return self._graph


class FakeMaterial:
    """``graph=None`` models a Standard (non-node) material — a
    ``GetNodeMaterialReference()`` call some real materials answer with
    ``None`` rather than raising. ``broken=True`` models one that raises
    on that call (also just a non-RS material, from this module's POV)."""

    def __init__(self, name, graph=None, has_space=True, broken=False):
        self._name = name
        self._graph = graph
        self._has_space = has_space
        self._broken = broken

    def GetName(self):
        return self._name

    def GetNodeMaterialReference(self):
        if self._broken:
            raise RuntimeError("boom: no node material reference")
        if self._graph is None:
            return None
        return FakeNodeMatRef(self._graph, self._has_space)


class _MultiReadNodeMatRef:
    """Hands back a DIFFERENT graph object on each successive
    ``GetGraph()`` call — mirrors the real API's fresh-``GraphNode``-
    wrapper-per-read behavior (``reference_c4d_wrapper_identity``), which
    the single-graph ``FakeNodeMatRef`` above does NOT model (it always
    returns the same object, which is fine for every test that doesn't
    care about cross-read handle identity). Calls beyond the prepared
    list reuse the last graph."""

    def __init__(self, graphs, has_space=True):
        self._graphs = list(graphs)
        self._has_space = has_space
        self.calls = 0

    def HasSpace(self, space_id):
        return self._has_space

    def GetGraph(self, space_id):
        index = min(self.calls, len(self._graphs) - 1)
        self.calls += 1
        return self._graphs[index]


class MultiReadMaterial:
    """A material whose node-material reference returns a NEW graph
    object (fresh node wrappers) on each ``GetGraph()`` call — the
    harness surface needed to prove a mutation only touches handles from
    the SAME read its transaction is bound to, never a handle carried
    over from an earlier read."""

    def __init__(self, name, graphs, has_space=True):
        self._name = name
        self.ref = _MultiReadNodeMatRef(graphs, has_space)

    def GetName(self):
        return self._name

    def GetNodeMaterialReference(self):
        return self.ref


class FakeDoc:
    def __init__(self, materials):
        self._materials = materials
        self.undo_calls = []
        self.start_count = 0
        self.end_count = 0

    def GetMaterials(self):
        return list(self._materials)

    def StartUndo(self):
        self.start_count += 1
        self.undo_calls.append("start")

    def EndUndo(self):
        self.end_count += 1
        self.undo_calls.append("end")

    def AddUndo(self, kind, obj):
        self.undo_calls.append(("add", kind, obj))


# ---------------------------------------------------------------------------
# Graph-building helpers
# ---------------------------------------------------------------------------

_RS_CORE = "com.redshift3d.redshift4c4d.nodes.core."
_RS_OUTPUT = "com.redshift3d.redshift4c4d.node.output"


def _add_sampler(graph, node_id, path, colorspace):
    """A texturesampler node with a ``tex0`` group port (SHORT-id children
    ``path``/``colorspace``, per the spike) and an ``outcolor`` output
    (FULL id, per the spike)."""
    node = graph.add_node(node_id, _RS_CORE + "texturesampler")
    tex0 = node.inputs.add_child(FakePort(_RS_CORE + "texturesampler.tex0", node))
    path_port = tex0.add_child(FakePort("path", node))
    path_port._value = path
    cs_port = tex0.add_child(FakePort("colorspace", node))
    cs_port._value = colorspace
    node.outputs.add_child(FakePort(_RS_CORE + "texturesampler.outcolor", node))
    return node


def _out_port(node, suffix):
    for child in node.outputs.GetChildren():
        if child.GetId().endswith(suffix):
            return child
    raise AssertionError("no output port %r on %s" % (suffix, node.node_id))


def _in_port(node, suffix):
    for child in node.inputs.GetChildren():
        if child.GetId().endswith(suffix):
            return child
    raise AssertionError("no input port %r on %s" % (suffix, node.node_id))


def _add_brdf(graph, node_id, input_suffixes):
    node = graph.add_node(node_id, _RS_CORE + "standardmaterial")
    for suffix in input_suffixes:
        node.inputs.add_child(FakePort(_RS_CORE + "standardmaterial." + suffix, node))
    node.outputs.add_child(FakePort(_RS_CORE + "standardmaterial.outcolor", node))
    return node


def _add_output(graph, node_id):
    node = graph.add_node(node_id, _RS_OUTPUT)
    node.inputs.add_child(FakePort(_RS_OUTPUT + ".surface", node))
    return node


def _add_colorlayer(graph, node_id):
    node = graph.add_node(node_id, _RS_CORE + "rscolorlayer")
    node.inputs.add_child(FakePort(_RS_CORE + "rscolorlayer.base_color", node))
    node.inputs.add_child(FakePort(_RS_CORE + "rscolorlayer.layer1_color", node))
    node.outputs.add_child(FakePort(_RS_CORE + "rscolorlayer.outcolor", node))
    return node


def _add_aov_store(graph, node_id, kind="storecolortoaov"):
    node = graph.add_node(node_id, _RS_CORE + kind)
    node.inputs.add_child(FakePort(_RS_CORE + kind + ".value", node))
    return node


def _simple_chain_graph():
    """sampler(basecolor) --outcolor--> standardmaterial.base_color
       standardmaterial --outcolor--> output.surface"""
    graph = FakeGraph()
    sampler = _add_sampler(graph, "sampler1", "/tex/plaster_basecolor.png",
                           "RS_INPUT_COLORSPACE_SRGB")
    brdf = _add_brdf(graph, "brdf1", ["base_color"])
    out = _add_output(graph, "out1")
    _out_port(sampler, "outcolor").connect_to(_in_port(brdf, "base_color"))
    _out_port(brdf, "outcolor").connect_to(_in_port(out, "surface"))
    return graph, sampler, brdf, out


@pytest.fixture
def matgraph_c4d(sentinel_module, monkeypatch):
    from sentinel import matgraph_c4d as module
    monkeypatch.setattr(module, "maxon", _FakeMaxon)
    return module


# ---------------------------------------------------------------------------
# collect()
# ---------------------------------------------------------------------------

class TestCollect:
    def test_live_chain_yields_sampler_with_correct_dest_port_edges_root(
            self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.collect(doc)

        assert len(result) == 1
        entry = result[0]
        assert entry["error"] is None
        assert entry["material"] is mat
        assert entry["name"] == "mat1"
        assert set(entry["node_ids"]) == {"sampler1", "brdf1", "out1"}
        assert entry["root_id"] == "out1"
        assert entry["sink_ids"] == []
        assert len(entry["samplers"]) == 1
        s = entry["samplers"][0]
        assert s["node_id"] == "sampler1"
        assert s["path"] == "/tex/plaster_basecolor.png"
        assert s["assigned"] == "RS_INPUT_COLORSPACE_SRGB"
        assert s["dest_port"] == _RS_CORE + "standardmaterial.base_color"
        assert ("sampler1", "brdf1") in entry["edges"]
        assert ("brdf1", "out1") in entry["edges"]

    def test_sampler_traced_through_pass_through_reaches_brdf_port(
            self, matgraph_c4d):
        """AO sampler -> rscolorlayer (pass-through) -> standardmaterial.base_color.
        Also exercises the deferred Task 1 review decision: an AO-named
        sampler tracing to base_color is CORRECT (it becomes a
        colorspace "conflict" in matgraph.audit_colorspaces, never a
        false Fix) — this test only proves the ADAPTER's trace crosses
        the color layer; the conflict semantics are Task 1's own tests."""
        graph = FakeGraph()
        ao_sampler = _add_sampler(graph, "ao1", "/tex/plaster_ao.png",
                                  "RS_INPUT_COLORSPACE_RAW")
        layer = _add_colorlayer(graph, "layer1")
        brdf = _add_brdf(graph, "brdf1", ["base_color"])
        out = _add_output(graph, "out1")
        _out_port(ao_sampler, "outcolor").connect_to(_in_port(layer, "layer1_color"))
        _out_port(layer, "outcolor").connect_to(_in_port(brdf, "base_color"))
        _out_port(brdf, "outcolor").connect_to(_in_port(out, "surface"))
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.collect(doc)

        entry = result[0]
        assert entry["error"] is None
        sampler_entry = next(s for s in entry["samplers"] if s["node_id"] == "ao1")
        assert sampler_entry["dest_port"] == _RS_CORE + "standardmaterial.base_color"

    def test_unknown_intermediate_node_yields_dest_port_none(self, matgraph_c4d):
        """"Unknown" here means the trace cannot even IDENTIFY the node on
        the other end (its assetid read raises) — the "never guess" case
        from matgraph.PASS_THROUGH_ASSETS's own docstring. This is
        different from a node whose assetid is perfectly readable but not
        in PASS_THROUGH_ASSETS (a real, reportable destination) — see
        test_live_chain_... for that case (BRDF port IS reported)."""
        graph = FakeGraph()
        sampler = _add_sampler(graph, "sampler1", "/tex/foo.png",
                               "RS_INPUT_COLORSPACE_SRGB")
        mystery = graph.add_node("mystery1", "com.thirdparty.somenode")
        mystery.raise_on_get_value = True
        mystery.inputs.add_child(FakePort("com.thirdparty.somenode.input", mystery))
        _out_port(sampler, "outcolor").connect_to(_in_port(mystery, "input"))
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.collect(doc)

        # The material walk as a whole must NOT fail just because one
        # sampler's dest-port trace hit an unreadable node.
        assert result[0]["error"] is None
        s = result[0]["samplers"][0]
        assert s["dest_port"] is None

    def test_unset_colorspace_is_assigned_none(self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        cs_port = None
        tex0 = sampler.inputs.GetChildren()[0]
        for child in tex0.GetChildren():
            if child.GetId() == "colorspace":
                cs_port = child
        cs_port._value = None
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.collect(doc)

        assert result[0]["samplers"][0]["assigned"] is None

    def test_aov_store_node_lands_in_sink_ids(self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        aov = _add_aov_store(graph, "aov1", kind="storecolortoaov")
        _out_port(brdf, "outcolor").connect_to(_in_port(aov, "value"))
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.collect(doc)

        assert result[0]["sink_ids"] == ["aov1"]

    def test_material_whose_walk_raises_gets_error_others_unaffected(
            self, matgraph_c4d):
        """A structural failure — the graph itself refuses to enumerate its
        nodes — must produce an ``error`` entry for THIS material without
        affecting any other. This is deliberately NOT modeled as one
        node's assetid read raising: ``_walk_material``'s root/sink/
        sampler scans tolerate that per-node (see ``_safe_assetid``), so
        the failure here has to be something no per-node guard catches."""
        graph_ok, _, _, _ = _simple_chain_graph()
        graph_broken = FakeGraph()
        graph_broken.add_node("broken1", _RS_CORE + "texturesampler")
        graph_broken._view_root.raise_on_get_inner_nodes = True
        mat_ok = FakeMaterial("ok_mat", graph=graph_ok)
        mat_broken = FakeMaterial("broken_mat", graph=graph_broken)
        doc = FakeDoc([mat_broken, mat_ok])

        result = matgraph_c4d.collect(doc)

        assert len(result) == 2
        broken_entry = next(e for e in result if e["name"] == "broken_mat")
        assert broken_entry["error"] is not None
        assert broken_entry["node_ids"] == []
        assert broken_entry["samplers"] == []
        ok_entry = next(e for e in result if e["name"] == "ok_mat")
        assert ok_entry["error"] is None
        assert len(ok_entry["samplers"]) == 1

    def test_non_node_material_skipped_silently(self, matgraph_c4d):
        mat = FakeMaterial("standard_mat", graph=None)
        doc = FakeDoc([mat])

        result = matgraph_c4d.collect(doc)

        assert result == []

    def test_material_with_broken_node_reference_skipped_silently(
            self, matgraph_c4d):
        mat = FakeMaterial("weird_mat", broken=True)
        doc = FakeDoc([mat])

        assert matgraph_c4d.collect(doc) == []

    def test_no_document_returns_empty_list(self, matgraph_c4d):
        assert matgraph_c4d.collect(None) == []


# ---------------------------------------------------------------------------
# write_colorspaces()
# ---------------------------------------------------------------------------

class TestWriteColorspaces:
    def test_whitelist_rejects_unknown_value_never_calls_set_port_value(
            self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        fixes = [{"material": mat, "node_id": "sampler1", "expected": "ACEScg"}]

        result = matgraph_c4d.write_colorspaces(doc, fixes)

        assert result == {"written": 0, "materials": 0}
        assert graph.set_port_calls == []

    def test_valid_fix_writes_and_counts(self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        fixes = [{"material": mat, "node_id": "sampler1",
                  "expected": matgraph_c4d.CS_SRGB}]

        result = matgraph_c4d.write_colorspaces(doc, fixes)

        assert result == {"written": 1, "materials": 1}
        assert graph.set_port_calls == [("sampler1", "colorspace", matgraph_c4d.CS_SRGB)]
        assert doc.undo_calls == [("add", _undotype_change(), mat)]
        assert graph.transactions == ["begin", "commit"]

    def test_never_opens_start_end_undo_bracket(self, matgraph_c4d):
        """The caller (fixes.py's apply_fixes) owns StartUndo/EndUndo — this
        function must never call it itself."""
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        fixes = [{"material": mat, "node_id": "sampler1",
                  "expected": matgraph_c4d.CS_SRGB}]

        matgraph_c4d.write_colorspaces(doc, fixes)

        assert doc.start_count == 0
        assert doc.end_count == 0

    def test_two_fixes_same_material_share_one_undo_anchor_and_transaction(
            self, matgraph_c4d):
        graph = FakeGraph()
        s1 = _add_sampler(graph, "s1", "/a.png", None)
        s2 = _add_sampler(graph, "s2", "/b.png", None)
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        fixes = [
            {"material": mat, "node_id": "s1", "expected": matgraph_c4d.CS_SRGB},
            {"material": mat, "node_id": "s2", "expected": matgraph_c4d.CS_RAW},
        ]

        result = matgraph_c4d.write_colorspaces(doc, fixes)

        assert result == {"written": 2, "materials": 1}
        add_undos = [c for c in doc.undo_calls if isinstance(c, tuple)]
        assert len(add_undos) == 1
        assert graph.transactions == ["begin", "commit"]

    def test_unknown_node_id_counted_skipped(self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        fixes = [{"material": mat, "node_id": "does-not-exist",
                  "expected": matgraph_c4d.CS_SRGB}]

        result = matgraph_c4d.write_colorspaces(doc, fixes)

        assert result == {"written": 0, "materials": 0}

    def test_commit_failure_reports_zero_written_not_the_attempted_count(
            self, matgraph_c4d):
        """A mid-batch exception at ``Commit()`` rolls the transaction
        back (the repo's own v1.5.7 lesson: a maxon transaction that
        never commits never lands). The counters must report that
        honestly — 0 written for this material — not the number of
        ``SetPortValue`` calls that were attempted before the rollback."""
        graph, sampler, brdf, out = _simple_chain_graph()
        graph.raise_on_commit = True
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        fixes = [{"material": mat, "node_id": "sampler1",
                  "expected": matgraph_c4d.CS_SRGB}]

        result = matgraph_c4d.write_colorspaces(doc, fixes)

        assert result == {"written": 0, "materials": 0}


def _undotype_change():
    import c4d
    return c4d.UNDOTYPE_CHANGE


# ---------------------------------------------------------------------------
# clean_dead_nodes_core()
# ---------------------------------------------------------------------------

class TestCleanDeadNodesCore:
    def _graph_with_dead_island(self):
        graph, sampler, brdf, out = _simple_chain_graph()
        # A dead island: two nodes connected to each other, connected to
        # nothing alive.
        orphan_a = graph.add_node("orphan_a", _RS_CORE + "texturesampler")
        orphan_a.outputs.add_child(FakePort(_RS_CORE + "texturesampler.outcolor", orphan_a))
        orphan_b = graph.add_node("orphan_b", "com.thirdparty.somenode")
        orphan_b.inputs.add_child(FakePort("com.thirdparty.somenode.input", orphan_b))
        _out_port(orphan_a, "outcolor").connect_to(_in_port(orphan_b, "input"))
        return graph, sampler, brdf, out, orphan_a, orphan_b

    def test_dead_island_removed_in_one_batch_bracket(self, matgraph_c4d):
        graph, sampler, brdf, out, orphan_a, orphan_b = self._graph_with_dead_island()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["ok"] is True
        assert result["materials"] == 1
        assert result["removed"] == 2
        assert result["skipped"] == 0
        assert set(graph.remove_calls) == {"orphan_a", "orphan_b"}
        assert doc.start_count == 1
        assert doc.end_count == 1

    def test_batch_bracket_covers_multiple_materials_as_one_pair(
            self, matgraph_c4d):
        g1, s1, b1, o1, oa1, ob1 = self._graph_with_dead_island()
        g2, s2, b2, o2, oa2, ob2 = self._graph_with_dead_island()
        mat1 = FakeMaterial("mat1", graph=g1)
        mat2 = FakeMaterial("mat2", graph=g2)
        doc = FakeDoc([mat1, mat2])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 4
        assert doc.start_count == 1
        assert doc.end_count == 1

    def test_commit_failure_reports_zero_removed_and_skips_the_material(
            self, matgraph_c4d):
        """A mid-batch exception at ``Commit()`` rolls the transaction
        back (v1.5.7 lesson). ``removed`` must not count nodes whose
        ``Remove()`` call happened before the rollback, and the material
        must land in ``skipped`` — the same "never touched" posture as
        every other skip reason in this function."""
        graph, sampler, brdf, out, orphan_a, orphan_b = self._graph_with_dead_island()
        graph.raise_on_commit = True
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 0
        assert result["skipped"] == 1

    def test_removal_uses_a_freshly_reacquired_graphs_own_node_handles(
            self, matgraph_c4d):
        """``collect()`` (called internally) reads the material's graph
        ONCE; removal must happen against a SECOND, freshly re-fetched
        read of that same material — never against the node objects
        ``collect()``'s own read produced. Mixing handles from two
        different reads is the wrapper-identity trap class documented in
        ``reference_c4d_wrapper_identity`` (8+ recurrences in this repo).
        ``MultiReadMaterial`` hands back a DIFFERENT graph object (with
        fresh node wrappers, same node-id strings) on each ``GetGraph()``
        call, so this test can tell which read's handles actually got
        ``Remove()``d."""
        graph1, s1, b1, o1, oa1, ob1 = self._graph_with_dead_island()
        graph2, s2, b2, o2, oa2, ob2 = self._graph_with_dead_island()
        mat = MultiReadMaterial("mat1", [graph1, graph2])
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 2
        assert graph1.remove_calls == [], (
            "removal must never touch collect()'s own (first) read")
        assert set(graph2.remove_calls) == {"orphan_a", "orphan_b"}, (
            "removal must happen against the second, freshly re-fetched read")

    def test_missing_path_on_reread_skips_material_without_removing(
            self, matgraph_c4d):
        """If a dead node id from ``collect()``'s read no longer exists on
        the SECOND (removal) read — the scene changed between the two
        reads — the whole material is skipped rather than removing only
        the subset that still resolves."""
        graph1, s1, b1, o1, oa1, ob1 = self._graph_with_dead_island()
        # The second read is missing "orphan_b" entirely (simulates it
        # having vanished between collect()'s read and the removal read).
        graph2 = FakeGraph()
        s2 = _add_sampler(graph2, "sampler1", "/tex/plaster_basecolor.png",
                          "RS_INPUT_COLORSPACE_SRGB")
        b2 = _add_brdf(graph2, "brdf1", ["base_color"])
        o2 = _add_output(graph2, "out1")
        _out_port(s2, "outcolor").connect_to(_in_port(b2, "base_color"))
        _out_port(b2, "outcolor").connect_to(_in_port(o2, "surface"))
        oa2 = graph2.add_node("orphan_a", _RS_CORE + "texturesampler")
        oa2.outputs.add_child(FakePort(_RS_CORE + "texturesampler.outcolor", oa2))
        # orphan_b deliberately NOT added to graph2.
        mat = MultiReadMaterial("mat1", [graph1, graph2])
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 0
        assert result["skipped"] == 1
        assert graph1.remove_calls == []
        assert graph2.remove_calls == []

    def test_material_with_collect_error_skipped_and_counted_untouched(
            self, matgraph_c4d):
        """A material whose ``collect()`` walk raised (``error`` set) must
        be skipped and counted, and NOTHING removed from it — deleting
        based on data we know is incomplete/wrong is the one thing this
        button must never do."""
        graph = FakeGraph()
        graph.add_node("broken1", _RS_CORE + "texturesampler")
        graph._view_root.raise_on_get_inner_nodes = True
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["skipped"] == 1
        assert result["removed"] == 0
        assert graph.remove_calls == []

    def test_material_with_no_root_id_skipped_and_counted_untouched(
            self, matgraph_c4d):
        """A material with no ``node.output`` node — an unrecognizable
        graph structure — is also skipped without being touched (the
        brief's "unrecognized potential sink" case, read here as "no
        anchor to compute reachability from")."""
        graph = FakeGraph()
        orphan = graph.add_node("orphan1", _RS_CORE + "texturesampler")
        orphan.outputs.add_child(FakePort(_RS_CORE + "texturesampler.outcolor", orphan))
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["skipped"] == 1
        assert result["removed"] == 0
        assert graph.remove_calls == []

    def test_unknown_store_like_terminal_skips_whole_material_untouched(
            self, matgraph_c4d):
        """A terminal node (has an incoming edge, no outgoing edges) whose
        assetid contains "aov"/"store" but is NOT one of the three known
        AAOV-store ids — e.g. a real Redshift ``storenormaltoaov`` node,
        which this codebase's ``_SINK_ASSET_TERMS`` doesn't enumerate — is
        a store-shaped stranger. In a healthy graph the only terminal
        consumers are the Output and known AOV stores; deleting a dead
        island upstream of an unrecognized one risks removing something
        that unknown consumer actually reads. The WHOLE material must be
        skipped and counted, and a genuine dead island elsewhere in that
        same material must NOT be removed."""
        graph, sampler, brdf, out, orphan_a, orphan_b = self._graph_with_dead_island()
        unknown_store = graph.add_node(
            "unknown_store1", _RS_CORE + "storenormaltoaov")
        unknown_store.inputs.add_child(
            FakePort(_RS_CORE + "storenormaltoaov.value", unknown_store))
        _out_port(brdf, "outcolor").connect_to(_in_port(unknown_store, "value"))
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["skipped"] == 1
        assert result["removed"] == 0
        assert graph.remove_calls == []

    def test_no_document_returns_error(self, matgraph_c4d):
        assert matgraph_c4d.clean_dead_nodes_core(None) == {
            "ok": False, "error": "no_document"}

    def test_no_dead_nodes_removes_nothing_but_still_ok(self, matgraph_c4d):
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        # "materials" counts materials actually CLEANED, not scanned —
        # semantics changed deliberately after live verification (v1.38):
        # the scanned count made the toast say "Cleaned 2 dead nodes in 5
        # materials" on a 5-material scene with one dirty material.
        assert result == {"ok": True, "materials": 0, "removed": 0, "skipped": 0}
        assert graph.remove_calls == []

    def test_event_add_called_when_nodes_removed(self, matgraph_c4d, monkeypatch):
        """Review fix (Important 2, final v1.38 review): a batch that
        actually removed dead nodes must call ``c4d.EventAdd()`` so the
        Object Manager/Node Editor/viewport refresh — the same
        unconditional-EventAdd discipline every sibling scene-mutating
        core (e.g. ``_delete_empty_nulls_core``) follows in its own
        ``finally``."""
        calls = []
        monkeypatch.setattr(matgraph_c4d.c4d, "EventAdd", lambda: calls.append("event"))
        graph, sampler, brdf, out, orphan_a, orphan_b = self._graph_with_dead_island()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 2
        assert calls == ["event"]

    def test_event_add_called_even_when_nothing_removed(self, matgraph_c4d, monkeypatch):
        """EventAdd is unconditional (mirrors ``_delete_empty_nulls_core``)
        — a no-op batch still refreshes."""
        calls = []
        monkeypatch.setattr(matgraph_c4d.c4d, "EventAdd", lambda: calls.append("event"))
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 0
        assert calls == ["event"]

    def test_check_cache_cleared_when_nodes_removed(self, matgraph_c4d, monkeypatch):
        """Review fix (Important 2): a batch that removed dead nodes must
        invalidate the QC cache — a removed sampler can flip QC #13's
        rs_colorspace count, and the cache must not serve a stale
        pre-removal result."""
        calls = []
        monkeypatch.setattr(matgraph_c4d.check_cache, "clear", lambda: calls.append("clear"))
        graph, sampler, brdf, out, orphan_a, orphan_b = self._graph_with_dead_island()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 2
        assert calls == ["clear"]

    def test_check_cache_not_cleared_when_nothing_removed(self, matgraph_c4d, monkeypatch):
        calls = []
        monkeypatch.setattr(matgraph_c4d.check_cache, "clear", lambda: calls.append("clear"))
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["removed"] == 0
        assert calls == []

    def test_dead_set_stranger_with_outgoing_edge_into_dead_island_skips_material(
            self, matgraph_c4d):
        """Minor 7 (final v1.38 review): ``_unknown_store_like_terminal``
        only catches an unrecognized store-shaped node when it has NO
        outgoing edges (terminal shape). A stranger that sits INSIDE a
        dead island — feeding only another dead node, so it HAS an
        outgoing edge — slipped past that guard and got deleted along
        with the island. Build a dead island where the "downstream" node
        of the pair is itself store/aov-shaped BY NAME (an outgoing edge
        into the other orphan): the whole material must be skipped and
        NOTHING removed."""
        graph, sampler, brdf, out = _simple_chain_graph()
        # orphan_a --outcolor--> orphan_store (aov-shaped, has an outgoing
        # edge of its own into orphan_sink) --> orphan_sink. Nothing here
        # is reachable from the live root, so the whole trio is dead, but
        # orphan_store's assetid hints "aov" and it has an OUTGOING edge
        # (not a terminal) — the pre-existing terminal-only guard misses it.
        orphan_a = graph.add_node("orphan_a", _RS_CORE + "texturesampler")
        orphan_a.outputs.add_child(FakePort(_RS_CORE + "texturesampler.outcolor", orphan_a))
        orphan_store = graph.add_node("orphan_store", _RS_CORE + "storenormaltoaov")
        orphan_store.inputs.add_child(
            FakePort(_RS_CORE + "storenormaltoaov.value", orphan_store))
        orphan_store.outputs.add_child(
            FakePort(_RS_CORE + "storenormaltoaov.outvalue", orphan_store))
        orphan_sink = graph.add_node("orphan_sink", "com.thirdparty.somenode")
        orphan_sink.inputs.add_child(FakePort("com.thirdparty.somenode.input", orphan_sink))
        _out_port(orphan_a, "outcolor").connect_to(_in_port(orphan_store, "value"))
        _out_port(orphan_store, "outvalue").connect_to(_in_port(orphan_sink, "input"))
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])

        result = matgraph_c4d.clean_dead_nodes_core(doc)

        assert result["skipped"] == 1
        assert result["removed"] == 0
        assert graph.remove_calls == []


class TestUndoJoinUserData:
    """Pin of the UNDO_MODE.ADD join idiom (measured live, v1.38): every
    mutating transaction must pass the undo-joining user_data when maxon
    exposes it — a bare BeginTransaction() pushes its OWN document undo
    step per material and a two-material Fix needs two Cmd+Z presses
    (matwire v1.32.1 behavior, re-measured). textures.py's repathing is
    the in-repo precedent."""

    def test_undo_join_user_data_built_from_maxon_enum(self, matgraph_c4d, monkeypatch):

        class _DD(dict):
            def Set(self, key, value):
                self[key] = value

        class _Nodes:
            UndoMode = "undo-mode-key"
            class UNDO_MODE:
                ADD = "add"

        class _Maxon:
            DataDictionary = _DD
            nodes = _Nodes

        monkeypatch.setattr(matgraph_c4d, "maxon", _Maxon)
        ud = matgraph_c4d._undo_join_user_data()
        assert ud is not None and ud["undo-mode-key"] == "add"

    def test_write_colorspaces_passes_join_user_data(self, matgraph_c4d, monkeypatch):

        class _DD(dict):
            def Set(self, key, value):
                self[key] = value

        class _Nodes:
            UndoMode = "undo-mode-key"
            class UNDO_MODE:
                ADD = "add"

        real_maxon = matgraph_c4d.maxon

        class _Maxon:
            """Delegating stub: adds the undo-join enum surface on top of
            the harness maxon (which the walk still needs for NODE_KIND
            etc.) — replacing it wholesale silently breaks the walk and
            the material gets skipped, which is exactly what the first
            version of this test measured."""
            DataDictionary = _DD
            nodes = _Nodes

            def __getattr__(self, name):
                return getattr(real_maxon, name)

        monkeypatch.setattr(matgraph_c4d, "maxon", _Maxon())
        graph, sampler, brdf, out = _simple_chain_graph()
        mat = FakeMaterial("mat1", graph=graph)
        doc = FakeDoc([mat])
        result = matgraph_c4d.write_colorspaces(
            doc, [{"material": mat, "node_id": "sampler1",
                   "expected": matgraph_c4d.CS_SRGB}])
        assert result["written"] == 1
        assert graph.begin_transaction_user_data, "no transaction opened"
        assert all(ud is not None for ud in graph.begin_transaction_user_data)

    def test_fallback_bare_call_when_maxon_lacks_enum(self, matgraph_c4d, monkeypatch):
        monkeypatch.setattr(matgraph_c4d, "maxon", None)
        assert matgraph_c4d._undo_join_user_data() is None
