# -*- coding: utf-8 -*-
"""Material Graph — the c4d/maxon adapter (v1.38).

Task 2 of the Material Graph feature (``docs/superpowers/specs/
2026-08-25-material-graph-qc-design.md``): the SINGLE per-material graph
walk that BOTH QC check #13 (RS Colorspace, Task 3) and the Tools "Clean
Dead Nodes" button (Task 4) consume, plus the two mutating operations
(``write_colorspaces`` for the Fix path, ``clean_dead_nodes_core`` for the
Tools button). The pure engine (``sentinel.matgraph`` — ``CS_SRGB``/
``CS_RAW``, ``PASS_THROUGH_ASSETS``, ``find_dead_nodes``, ``audit_colorspaces``)
never imports ``c4d``/``maxon``; every maxon idiom lives here, verified live
in ``docs/research/2026-08-27-matgraph-spike.md`` (C4D 2026.304, Redshift).

Idioms this module rests on (see the spike doc for the measurements):

- **Node enumeration**: ``graph.GetViewRoot().GetInnerNodes(mask=
  maxon.NODE_KIND.NODE, includeThis=False)`` — the same idiom
  ``matwire_c4d.py`` uses everywhere.
- **Node id**: ``str(node.GetPath())`` — stable WITHIN one graph read,
  never persisted across a save/reload or a document undo (the same
  "re-acquire fresh, never trust a stale handle" lesson the spike's undo
  probe measured for node deletion applies here too).
- **Port lookup by SUFFIX, not exact id** (``child_by_suffix``): the
  spike measured that a node's TOP-LEVEL ``GetInputs()``/``GetOutputs()``
  children carry FULL ids (``com....texturesampler.tex0``), while a GROUP
  port's OWN children (``tex0``'s ``path``/``colorspace``) carry SHORT
  ids. One suffix-matching helper works at BOTH levels without the
  caller having to know which one applies — the alternative (hardcoding
  the RS core prefix at every call site, as ``matwire_c4d.py``'s WRITER
  does because it always knows the exact target) doesn't fit a READER
  that also has to recognize unknown/foreign node kinds.
- **Connections**: ``out_port.GetConnections(maxon.PORT_DIR.OUTPUT,
  a_list)`` fills the passed list with the connected ports on the other
  end (empty list = unconnected, not an error — measured live). Port ->
  owning node via ``port.GetAncestor(maxon.NODE_KIND.NODE)`` (studied
  from the DunHouGo ``renderEngine`` wrapper's ``GetTrueNode`` helper —
  facts taken, no code copied, per this repo's external-reference rule).
- **Assetid**: ``str(node.GetValue(_ASSETID_ATTR) or "")``, matched by
  substring — mirrors ``matwire_c4d._kind_from_assetid``'s caller sites.
- **Deletion**: ``node.Remove()`` inside ``graph.BeginTransaction()``/
  ``Commit()``, undo anchored by ``doc.AddUndo(UNDOTYPE_CHANGE, mat)``
  placed BEFORE the transaction (spike Q4) — one document undo step per
  material, restoring the removed node on a single Cmd+Z.

``collect()``'s dest-port trace crosses ``rscolorlayer`` on purpose (a
deferred Task 1 review decision, now implemented deliberately — see its
docstring below) because ``rscolorlayer`` is one of ``PASS_THROUGH_ASSETS``:
an AO sampler wired through an AO-multiply color layer into ``base_color``
traces all the way to the ``base_color`` port. That is CORRECT and safe
under ``matgraph.audit_colorspaces``'s fixed conflict semantics: the name
signal says ``ao`` (expects RAW), the port signal says ``basecolor``
(expects SRGB) — those expected colorspaces DIFFER, so ``infer_channel``
reports ``"conflict"`` and the check goes to Info, never Fix. An
AO-multiply sampler wired by matwire can therefore never be silently
"fixed" to sRGB by QC #13.
"""

import c4d

from sentinel.common.cache import check_cache
from sentinel.matgraph import CS_RAW, CS_SRGB, PASS_THROUGH_ASSETS, PORT_TO_CHANNEL, find_dead_nodes
from sentinel.matwire_c4d import _ASSETID_ATTR, _RS_OUTPUT
from sentinel.textures import RS_NODESPACE

try:
    import maxon
except ImportError:  # pytest fake harness / c4dpy without maxon
    maxon = None

#: Asset-id SUBSTRINGS (case-insensitive) that mark a node as an AOV store
#: — the "sinks" per the design doc: alive regardless of whether anything
#: downstream of them reads their (nonexistent) output.
_SINK_ASSET_TERMS = ("storecolortoaov", "storescalartoaov", "storeintegertoaov")

#: Trace depth cap (spike-adjacent, defensive): a pass-through chain in
#: practice is 1-2 nodes (Color Correct, an AO layer, a Bump). 8 is
#: generous headroom against a pathological/cyclic graph without walking
#: forever.
_TRACE_DEPTH_CAP = 8

def _empty_material_result():
    """A blank material-result dict with FRESH (never shared) mutable
    containers for every list/dict field. Review fix (Minor 2, final
    v1.38 review): the earlier module-level ``_EMPTY_MATERIAL_RESULT``
    constant plus ``dict(_EMPTY_MATERIAL_RESULT)`` at each call site only
    shallow-copies the dict's own keys — every list/dict VALUE
    (``node_ids``, ``nodes_by_id``, ``edges``, ``samplers``, ``sink_ids``)
    stayed the SAME shared object across every call. ``_walk_material``
    happened to reassign every one of those keys before returning, so it
    was never exploitable there, but ``collect()``'s error-entry branch
    (an exception mid-walk) does NOT reassign them — a mutation of one
    material's "empty" ``node_ids`` would have silently corrupted every
    other error entry's ``node_ids`` in the same batch, since they'd all
    be the exact same list object. This factory hands back brand-new
    containers on every call instead."""
    return {
        "node_ids": [], "nodes_by_id": {}, "edges": [], "samplers": [],
        "root_id": None, "sink_ids": [],
    }


def child_by_suffix(port_group, suffix):
    """The first child of ``port_group`` whose id string ends with
    ``suffix`` — NOT an exact-id lookup. Works uniformly whether the
    children carry full ids (a node's top-level ``GetInputs()``/
    ``GetOutputs()``) or short ids (a group port's own children, e.g.
    ``tex0``'s ``path``/``colorspace``) — see the module docstring.
    Returns ``None`` for a missing/empty group (never raises: an unknown
    or foreign node kind not exposing the expected shape is a normal,
    silent "no signal", not an error)."""
    if port_group is None:
        return None
    for child in port_group.GetChildren() or ():
        if str(child.GetId()).endswith(suffix):
            return child
    return None


def _leaf_ports(port_group):
    """Every LEAF port reachable from ``port_group``, recursing into any
    child that itself has children (a group port, e.g. ``tex0``). Every RS
    node kind this feature touches has flat outputs, so the recursion is
    defensive rather than load-bearing today — but a generic reader
    shouldn't assume that stays true forever."""
    ports = []
    for child in port_group.GetChildren() or ():
        grandchildren = child.GetChildren() or ()
        if grandchildren:
            ports.extend(_leaf_ports(child))
        else:
            ports.append(child)
    return ports




def _undo_join_user_data():
    """Transaction user_data that makes the maxon transaction JOIN the
    caller's open StartUndo/EndUndo bracket instead of pushing its own
    document undo step.

    MEASURED LIVE (v1.38 verification): with a bare ``BeginTransaction()``
    a two-material Fix needed TWO Cmd+Z presses — each material's
    transaction landed as its own step despite the outer bracket and the
    per-material CHANGE anchors (the matwire v1.32.1 step-per-transaction
    behavior). ``textures.py``'s repathing (single Cmd+Z across materials,
    live-verified in v1.5.7) does it by passing ``UNDO_MODE.ADD`` in the
    transaction's user_data — the same idiom the official
    ``create_redshift_nodematerial_2024.py`` example pairs with a prior
    ``doc.AddUndo``. ``None`` (bare call) when maxon lacks the enum."""
    try:
        user_data = maxon.DataDictionary()
        user_data.Set(maxon.nodes.UndoMode, maxon.nodes.UNDO_MODE.ADD)
        return user_data
    except Exception:
        return None


def _begin_join_transaction(graph):
    """``graph.BeginTransaction`` with the undo-joining user_data when
    available, bare otherwise (fallback keeps pre-2026 builds working)."""
    user_data = _undo_join_user_data()
    if user_data is not None:
        return graph.BeginTransaction(user_data)
    return graph.BeginTransaction()

def _connection_port(conn):
    """Unwrap one ``GetConnections`` result entry to its port.

    MEASURED LIVE (v1.38 verification, C4D 2026.304): the real API fills
    the list with TUPLES — ``(port, wire-data...)`` — exactly as the
    official SDK example reads them (``nodegraph_selection_r26.py``:
    ``connection[0]``). The first fake modeled the list as bare ports, so
    production written against the fake raised ``'tuple' object has no
    attribute 'GetAncestor'`` on every real material (the fake-shape
    lesson, once more). Tolerates both shapes so the probe-style truthy
    checks stay valid either way."""
    if isinstance(conn, (tuple, list)):
        return conn[0]
    return conn

def _first_connected_output(node):
    """The first of ``node``'s own output ports that has at least one
    downstream connection — the continuation point when a dest-port trace
    walks THROUGH a pass-through node (design doc: "first output port
    with connections"). ``None`` if none of its outputs connect anywhere."""
    for port in _leaf_ports(node.GetOutputs()):
        probe = []
        port.GetConnections(maxon.PORT_DIR.OUTPUT, probe)
        if probe:
            return port
    return None


def _trace_dest_port(sampler_node):
    """From ``sampler_node``'s ``outcolor`` output, follow downstream
    connections, walking THROUGH any node whose assetid matches
    ``PASS_THROUGH_ASSETS`` (Color Correct, an AO layer, the glossiness
    Invert, Bump, an unused-today Ramp) until hitting the first
    non-pass-through target, whose FULL port id string is returned.
    A mapped semantic utility input (e.g. bumpmap.input) terminates first:
    its normal-map meaning would be lost at the downstream BRDF port.

    **Fan-out choice** (design doc leaves this to the implementation,
    documented here as instructed): if ``outcolor`` feeds more than one
    target, only the FIRST one returned by ``GetConnections`` is traced
    and reported. A sampler multiply-wired to two different destinations
    is rare in matwire-authored graphs (matwire never does it) and an
    artist-wired branch with genuinely different colorspace expectations
    on each branch is a case no single ``dest_port`` string could
    represent anyway — reporting one real destination beats inventing a
    list nothing else in this feature consumes.

    Returns ``None`` when the sampler has no ``outcolor`` port, the chain
    dead-ends unconnected, the depth cap is hit (a defensive guard against
    a cyclic/pathological graph, never expected in practice), or a node
    along the way can't be identified at all (its assetid read raises —
    an exotic/unreadable node kind). That last case mirrors
    ``matgraph.PASS_THROUGH_ASSETS``'s own docstring verbatim: "an unknown
    asset along the way stops the trace with no port signal — never a
    guess." A node whose assetid IS readable but simply isn't in
    ``PASS_THROUGH_ASSETS`` is NOT "unknown" in that sense — it is a real,
    identifiable destination (known or not to ``matgraph``'s channel
    table is Task 1's concern, not this trace's), so its port IS reported;
    only a node this trace cannot even inspect gets the "no guess" None."""
    current_port = child_by_suffix(sampler_node.GetOutputs(), "outcolor")
    if current_port is None:
        return None
    for _ in range(_TRACE_DEPTH_CAP):
        targets = []
        current_port.GetConnections(maxon.PORT_DIR.OUTPUT, targets)
        if not targets:
            return None
        target_port = _connection_port(targets[0])
        try:
            target_node = target_port.GetAncestor(maxon.NODE_KIND.NODE)
            assetid = str(target_node.GetValue(_ASSETID_ATTR) or "")
        except Exception:
            return None
        port_id = str(target_port.GetId())
        # Qualified semantic utility inputs (e.g. bumpmap.input) describe
        # the texture itself; tracing through loses that signal at the BRDF.
        if any("." in key and port_id.endswith(key) for key in PORT_TO_CHANNEL):
            return port_id
        if any(term in assetid for term in PASS_THROUGH_ASSETS):
            next_port = _first_connected_output(target_node)
            if next_port is None:
                return None
            current_port = next_port
            continue
        return str(target_port.GetId())
    return None


def _safe_assetid(node):
    """``str(node.GetValue(_ASSETID_ATTR) or "")``, tolerating a node whose
    attribute read raises. Used everywhere in ``_walk_material`` that scans
    ALL nodes for a structural role (root/sink/sampler detection): one
    exotic/broken node's assetid failing to read must not disqualify it
    from ``node_ids``/``edges`` (still structurally present) nor blow up
    the whole material's walk over a role-classification question it
    simply doesn't answer either way — it's treated as assetid ``""``,
    which matches no role.

    This is DELIBERATELY different from ``_trace_dest_port``'s own
    exception handling: there, "can't identify this node" must stop the
    trace and report no port signal (never fall through and treat the
    unreadable node as some ordinary unmatched destination), so that
    function keeps its own explicit try/except rather than calling this
    helper."""
    try:
        return str(node.GetValue(_ASSETID_ATTR) or "")
    except Exception:
        return ""


def _rs_node_material_graph(mat, strict=False):
    """Return an RS graph or None for an out-of-scope material.

    A failing node-reference probe is normal for non-node materials.
    Once a node reference exists, strict reads preserve HasSpace/GetGraph
    failures for collect's error entry; mutation callers retain the safe
    None fallback and skip the material instead of writing blindly.
    """
    try:
        node_mat = mat.GetNodeMaterialReference()
    except Exception:
        return None
    if node_mat is None:
        return None
    try:
        if not node_mat.HasSpace(RS_NODESPACE):
            return None
        graph = node_mat.GetGraph(RS_NODESPACE)
        if graph is None and strict:
            raise RuntimeError("Redshift graph is unavailable")
        return graph
    except Exception:
        if strict:
            raise
        return None


def _walk_material(graph):
    """The single per-material walk both QC #13 and Clean Dead Nodes
    consume. Returns the ``node_ids``/``nodes_by_id``/``edges``/
    ``samplers``/``root_id``/``sink_ids`` fields of one ``collect()``
    entry (never ``material``/``name``/``error`` — the caller adds those).

    ``edges`` is the LITERAL set of direct connections across the WHOLE
    graph (every node's output ports -> what they connect to), not just
    the sampler dest-port traces — that is what makes ``find_dead_nodes``'s
    plain reachability BFS work: a Color Correct sitting between a live
    sampler and the BRDF is itself an ancestor of the root through a
    normal edge, so it comes out alive without ``find_dead_nodes`` (or
    this walk) needing to know anything about pass-through semantics.
    Pass-through awareness is ONLY needed for the sampler dest-port label,
    which is a separate, narrower trace (``_trace_dest_port``)."""
    out = _empty_material_result()
    nodes = list(graph.GetViewRoot().GetInnerNodes(
        mask=maxon.NODE_KIND.NODE, includeThis=False))

    node_ids = []
    nodes_by_id = {}
    for node in nodes:
        nid = str(node.GetPath())
        node_ids.append(nid)
        nodes_by_id[nid] = node
    out["node_ids"] = node_ids
    out["nodes_by_id"] = nodes_by_id

    edges = []
    for node in nodes:
        from_id = str(node.GetPath())
        for out_port in _leaf_ports(node.GetOutputs()):
            targets = []
            out_port.GetConnections(maxon.PORT_DIR.OUTPUT, targets)
            for conn in targets:
                target_port = _connection_port(conn)
                target_node = target_port.GetAncestor(maxon.NODE_KIND.NODE)
                edges.append((from_id, str(target_node.GetPath())))
    out["edges"] = edges

    root_id = None
    for node in nodes:
        assetid = _safe_assetid(node)
        if _RS_OUTPUT in assetid:
            root_id = str(node.GetPath())
            break
    out["root_id"] = root_id

    sink_ids = []
    for node in nodes:
        assetid = _safe_assetid(node).lower()
        if any(term in assetid for term in _SINK_ASSET_TERMS):
            sink_ids.append(str(node.GetPath()))
    out["sink_ids"] = sink_ids

    samplers = []
    for node in nodes:
        assetid = _safe_assetid(node)
        if "texturesampler" not in assetid:
            continue
        tex0 = child_by_suffix(node.GetInputs(), "tex0")
        path_port = child_by_suffix(tex0, "path") if tex0 is not None else None
        cs_port = child_by_suffix(tex0, "colorspace") if tex0 is not None else None
        path_val = str(path_port.GetPortValue() or "") if path_port is not None else ""
        assigned = cs_port.GetPortValue() if cs_port is not None else None
        samplers.append({
            "node_id": str(node.GetPath()),
            "path": path_val,
            "assigned": str(assigned) if assigned is not None else None,
            "dest_port": _trace_dest_port(node),
        })
    out["samplers"] = samplers

    return out


def collect(doc):
    """One walk per RS node material in ``doc``. Returns
    ``list[{"material", "name", "node_ids", "nodes_by_id", "edges",
    "samplers", "root_id", "sink_ids", "error"}]``.

    Non-RS/non-node materials (Standard, Octane, a material with no node
    graph at all) are skipped SILENTLY — they never appear in the result,
    same as "this check doesn't apply to you". That is different from a
    material that IS an RS node material but whose walk raises for some
    other reason (a maxon call failing mid-read): that material is still
    returned, with ``error`` set and every list empty — so a caller
    iterating the result never has to special-case "this entry might not
    have the keys the shape promises", and one bad material never hides
    the others.

    See the module docstring for the ``rscolorlayer``/AO-multiply
    dest-port rationale: an AO sampler traced through a color layer into
    ``base_color`` is intentional and safe (it resolves to ``"conflict"``
    in ``matgraph.audit_colorspaces``, never a false Fix)."""
    if doc is None:
        return []
    try:
        materials = doc.GetMaterials() or []
    except Exception as exc:
        entry = _empty_material_result()
        entry.update(material=None, name="Scene materials", error=str(exc))
        return [entry]

    results = []
    for mat in materials:
        if mat is None:
            continue
        try:
            name = mat.GetName() or ""
        except Exception:
            name = ""
        try:
            graph = _rs_node_material_graph(mat, strict=True)
            if graph is None:
                continue  # Non-RS/non-node materials are out of scope.
            entry = _walk_material(graph)
            entry["material"] = mat
            entry["name"] = name
            entry["error"] = None
        except Exception as exc:
            entry = _empty_material_result()
            entry["material"] = mat
            entry["name"] = name
            entry["error"] = str(exc)
        results.append(entry)
    return results


def write_colorspaces(doc, fixes):
    """Apply a batch of colorspace fixes: ``fixes`` = ``[{"material",
    "node_id", "expected"}]``. Returns ``{"written": n, "materials": m}``
    (``n`` = ports actually written, ``m`` = distinct materials that had
    at least one write).

    **Whitelist guard — the crash lesson.** Any ``expected`` outside
    ``{CS_SRGB, CS_RAW}`` is counted as skipped and the corresponding
    ``SetPortValue`` is NEVER called: the spike measured that writing an
    arbitrary string to the RS ``tex0/colorspace`` port crashes C4D
    outright (``EXC_BAD_ACCESS`` in ``redshift4c4d.xlib``). This is the
    one call in the whole feature that must never receive a value this
    codebase didn't itself choose.

    Nodes are re-located by ``node_id`` against a FRESHLY re-read graph
    for each material, never against a ``GraphNode`` handle carried over
    from an earlier ``collect()`` call — the same "re-acquire fresh"
    discipline the spike's delete/undo probe measured as necessary (a
    stale graph handle silently reports the pre-mutation state with no
    error).

    Per material: ONE ``doc.AddUndo(UNDOTYPE_CHANGE, mat)`` anchor before
    ONE maxon transaction covering every fix for that material. This
    function does NOT open a ``StartUndo``/``EndUndo`` bracket — the
    caller (``fixes.py``'s ``apply_fixes``, per its existing contract for
    every other fix function) owns the batch-level undo step.

    The written value is a plain Python ``str`` (``CS_SRGB``/``CS_RAW``
    themselves), not wrapped in ``maxon.String(...)``: the spike's Q1
    probe measured writing those exact values via ``SetPortValue`` as
    plain Python strings and reading them back verbatim — this is the
    measured-good call, not a guess (a belt-and-braces live check before
    this path ships a Fix button is still worthwhile, but it is no
    longer an open risk).

    **Counters are only credited AFTER `Commit()` returns** (review
    fix): a mid-batch exception at ``Commit()`` rolls the WHOLE
    transaction back — the repo's own v1.5.7 lesson that a maxon
    transaction which never commits never lands — so ``written`` is
    accumulated per-material in a local ``pending_written`` and only
    added to the running total once ``tr.Commit()`` returns without
    raising. On an exception anywhere inside that material's transaction
    block, its ENTIRE ``known`` batch is counted as ``skipped`` instead
    (never partially credited): the fake/real transaction may have
    applied some writes before the failure, but nothing here can tell
    which, so reporting anything other than "zero landed, all skipped"
    for that material would risk overstating what a caller can rely on."""
    written = 0
    skipped = 0
    by_material = []
    seen_keys = {}
    for fix in fixes or []:
        mat = fix.get("material")
        node_id = fix.get("node_id")
        expected = fix.get("expected")
        if mat is None or node_id is None or expected not in (CS_SRGB, CS_RAW):
            skipped += 1
            continue
        key = id(mat)
        if key not in seen_keys:
            seen_keys[key] = len(by_material)
            by_material.append((mat, []))
        by_material[seen_keys[key]][1].append((node_id, expected))

    materials_written = 0
    for mat, entries in by_material:
        graph = _rs_node_material_graph(mat)
        if graph is None:
            skipped += len(entries)
            continue
        try:
            nodes_by_id = {
                str(n.GetPath()): n
                for n in graph.GetViewRoot().GetInnerNodes(
                    mask=maxon.NODE_KIND.NODE, includeThis=False)
            }
        except Exception:
            skipped += len(entries)
            continue

        # Resolve node ids up front so a batch that turns out to name
        # NOTHING findable in this material's CURRENT graph never anchors
        # a no-op undo step — the anchor only fires once we know at least
        # one write is actually about to happen.
        known = [(nodes_by_id[nid], expected) for nid, expected in entries
                if nid in nodes_by_id]
        skipped += len(entries) - len(known)
        if not known:
            continue

        try:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)
            pending_written = 0
            pending_skipped = 0
            with _begin_join_transaction(graph) as tr:
                for node, expected in known:
                    tex0 = child_by_suffix(node.GetInputs(), "tex0")
                    cs_port = child_by_suffix(tex0, "colorspace") if tex0 is not None else None
                    if cs_port is None:
                        pending_skipped += 1
                        continue
                    cs_port.SetPortValue(expected)
                    pending_written += 1
                tr.Commit()
        except Exception:
            # Commit (or anything else in the block) raised: the WHOLE
            # transaction rolled back, so none of this material's known
            # entries can be credited — not even the ones that looked
            # like they succeeded before the failure.
            skipped += len(known)
            continue

        written += pending_written
        skipped += pending_skipped
        if pending_written:
            materials_written += 1

    return {"written": written, "materials": materials_written}


#: Substrings that mark a node as AOV-STORE-SHAPED without being one of
#: the three known store ids in ``_SINK_ASSET_TERMS`` — e.g. a real
#: Redshift ``storenormaltoaov`` node, which this codebase's sink list
#: doesn't enumerate (Task 1 scoped the known list to color/scalar/
#: integer). Deliberately broad (bare "aov"/"store"), matching
#: ``_SINK_ASSET_TERMS``'s own case-insensitive-substring style.
_UNKNOWN_STORE_HINT_TERMS = ("aov", "store")


def _unknown_store_like_terminal(entry):
    """Whether ``entry`` (a ``collect()`` per-material dict) contains a
    STORE-SHAPED STRANGER: a node with at least one incoming edge and no
    outgoing edges (a graph TERMINAL, same shape as the Output node and
    the known AOV stores) whose assetid hints at "aov"/"store" but is
    NOT the material's root (output) node and NOT one of the three known
    store ids already in ``sink_ids``.

    Rationale: in a healthy graph the only terminal consumers are the
    Output and the AOV stores this codebase recognizes. A store-SHAPED
    node we don't recognize might be writing data somewhere this walk
    can't see (a newer/renamed Redshift AOV-store node kind, e.g.) — so
    treating its upstream nodes as safely dead because they don't feed
    the KNOWN sinks would risk exactly the silent data loss
    ``clean_dead_nodes_core`` exists to avoid. The whole material is
    skipped rather than guessing which of its "dead" nodes are actually
    safe."""
    node_ids = entry.get("node_ids") or ()
    root_id = entry.get("root_id")
    known_sinks = set(entry.get("sink_ids") or ())
    nodes_by_id = entry.get("nodes_by_id") or {}
    outgoing = set()
    incoming = set()
    for from_id, to_id in entry.get("edges") or ():
        outgoing.add(from_id)
        incoming.add(to_id)
    for node_id in node_ids:
        if node_id == root_id or node_id in known_sinks:
            continue
        if node_id not in incoming or node_id in outgoing:
            continue
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        assetid = _safe_assetid(node).lower()
        if any(term in assetid for term in _UNKNOWN_STORE_HINT_TERMS):
            return True
    return False


def _dead_set_has_unknown_store_like_node(entry, dead):
    """Whether the already-computed DEAD set itself contains a store-shaped
    stranger, regardless of that node's own edges.

    Review fix (Minor 7, final v1.38 review): ``_unknown_store_like_terminal``
    only catches an unrecognized store node when it has the TERMINAL shape
    (incoming edge, no outgoing edges) — the shape a real AOV store or the
    Output node has. But a store-shaped stranger that sits entirely INSIDE
    a dead island (it has an outgoing edge feeding another node that is
    ALSO dead, so nothing downstream of the stranger is reachable from a
    live root either) has an outgoing edge and slips past that guard —
    the whole island, stranger included, then gets deleted anyway,
    contradicting the "never guess, never touch what an unrecognized
    consumer might read" posture the terminal guard exists for. This
    checks every node NAME in ``dead`` (not just terminals) for the same
    "aov"/"store" hint, so a stranger anywhere in the dead set — feeding
    only other dead nodes or not — still stops the whole material from
    being touched. The terminal-only guard above stays as-is for a
    stranger sitting on a LIVE branch (never in ``dead`` in the first
    place, so this function alone wouldn't catch it)."""
    root_id = entry.get("root_id")
    known_sinks = set(entry.get("sink_ids") or ())
    nodes_by_id = entry.get("nodes_by_id") or {}
    for node_id in dead:
        if node_id == root_id or node_id in known_sinks:
            continue
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        assetid = _safe_assetid(node).lower()
        if any(term in assetid for term in _UNKNOWN_STORE_HINT_TERMS):
            return True
    return False


def clean_dead_nodes_core(doc):
    """Remove every dead node (per ``matgraph.find_dead_nodes``) from
    every RS node material in ``doc``, in ONE ``StartUndo``/``EndUndo``
    bracket for the WHOLE batch — this is a standalone Tools action (no
    ``fixes.py`` caller owns the bracket for it), unlike ``write_colorspaces``.

    Returns ``{"ok": True, "materials": n, "removed": k, "skipped": s}``
    where ``materials`` counts the materials actually CLEANED (>=1 node
    removed) — not the materials scanned. MEASURED LIVE (v1.38): with the
    scanned count a 5-material scene with one dirty material toasted
    "Cleaned 2 dead nodes in 5 materials", which is a lie with a number in it.
    with ``n`` = RS node materials found (``collect()``'s result length),
    ``k`` = dead nodes actually removed, ``s`` = materials skipped without
    being touched; or ``{"ok": False, "error": "no_document"}``.

    A material is skipped (counted, never touched) when: it already
    carries a ``collect()`` ``error`` (the walk itself failed — deleting
    from data we know is incomplete/wrong is the one thing this button
    must never do); it has no identifiable ``root_id`` (no ``node.output``
    node found — no anchor to compute reachability from); OR it contains
    an "unrecognized potential sink" per the design doc — read here (per
    review) as a STORE-SHAPED STRANGER: a terminal node (has an incoming
    edge, no outgoing edges — same shape as the Output node and the known
    AOV stores) whose assetid hints at "aov"/"store" but isn't one of the
    three ids ``_SINK_ASSET_TERMS`` actually recognizes (see
    ``_unknown_store_like_terminal``) — OR the computed dead set for that
    material contains such a stranger by name alone, regardless of its
    own edges (see ``_dead_set_has_unknown_store_like_node``, review fix,
    Minor 7 of the final v1.38 review: a stranger with an outgoing edge
    into another dead node slips past the terminal-only guard). Such a
    node might be consuming data this walk can't account for, so nothing
    in that material is touched rather than guessing which of its "dead"
    nodes are safe.

    Root passed to ``find_dead_nodes`` is simply ``{root_id}`` (the
    output node), not also its direct feeders: the reverse-BFS in
    ``find_dead_nodes`` discovers those feeders itself, one hop back,
    through the material's own edges — computing them separately here
    would be redundant with what the BFS already does.

    **Removal happens against a SECOND, freshly re-fetched graph read —
    never against the node handles ``collect()``'s own (first) read
    produced** (review fix — the wrapper-identity trap class,
    ``reference_c4d_wrapper_identity``, 8+ recurrences in this repo: the
    real API hands back a fresh ``GraphNode`` wrapper on every read, so
    calling ``.Remove()`` on a handle from one read while a transaction
    is bound to a DIFFERENT read is exactly the kind of cross-read
    mixing that trap class warns about — even though ``str(node.GetPath())``
    stays stable across reads and is what everything else in this module
    keys off of). Concretely: once ``dead`` is known from ``collect()``'s
    data, this function calls ``_rs_node_material_graph(mat)`` AGAIN,
    re-enumerates ITS nodes, and maps ``str(node.GetPath())`` -> node
    from THAT read only; every ``Remove()`` call in the transaction below
    uses one of those second-read handles. If any dead id from the first
    read is missing on the second (the scene changed between the two
    reads — genuinely possible given ``collect()`` and this removal are
    not atomic with respect to anything else that could touch the
    document), the WHOLE material is skipped rather than removing only
    the subset that still resolves — the same "never guess, never
    partially act" posture as every other skip reason here.

    **Counters are only credited AFTER `Commit()` returns** (review fix,
    same reasoning as ``write_colorspaces``): ``removed`` is accumulated
    per-material in a local ``pending_removed`` and only added to the
    running total once ``tr.Commit()`` returns without raising; an
    exception anywhere in that material's transaction block counts the
    WHOLE material as ``skipped`` instead, never a partial ``removed``
    count for nodes whose ``Remove()`` ran before a rollback."""
    if doc is None:
        return {"ok": False, "error": "no_document"}

    materials = collect(doc)
    removed = 0
    materials_cleaned = 0
    skipped = 0

    doc.StartUndo()
    try:
        for entry in materials:
            if entry.get("error") or entry.get("root_id") is None:
                skipped += 1
                continue
            if _unknown_store_like_terminal(entry):
                skipped += 1
                continue
            root_ids = [entry["root_id"]]
            dead = find_dead_nodes(entry["node_ids"], entry["edges"],
                                   root_ids, entry["sink_ids"])
            if not dead:
                continue
            if _dead_set_has_unknown_store_like_node(entry, dead):
                skipped += 1
                continue
            mat = entry["material"]
            try:
                # Fresh, SECOND read — see the docstring. Handles for the
                # Remove() calls below come from THIS enumeration, never
                # from entry["nodes_by_id"] (collect()'s earlier read).
                graph = _rs_node_material_graph(mat)
                if graph is None:
                    skipped += 1
                    continue
                fresh_by_id = {
                    str(n.GetPath()): n
                    for n in graph.GetViewRoot().GetInnerNodes(
                        mask=maxon.NODE_KIND.NODE, includeThis=False)
                }
                if any(node_id not in fresh_by_id for node_id in dead):
                    # Scene changed between the two reads — removing only
                    # the subset that still resolves would be a guess.
                    skipped += 1
                    continue
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)
                pending_removed = 0
                with _begin_join_transaction(graph) as tr:
                    for node_id in dead:
                        fresh_by_id[node_id].Remove()
                        pending_removed += 1
                    tr.Commit()
                removed += pending_removed
                if pending_removed:
                    materials_cleaned += 1
            except Exception:
                skipped += 1
    finally:
        doc.EndUndo()
        # Review fix (Important 2, final v1.38 review): this button used to
        # send no refresh signal at all — every sibling scene-mutating core
        # (e.g. ``ui/scene_tools.py`` ``_delete_empty_nulls_core``) calls
        # ``c4d.EventAdd()`` unconditionally in its own ``finally`` so the
        # Object/Node Manager and viewport redraw even when nothing was
        # removed, and clears the QC cache when something WAS removed (a
        # dead-node deletion can flip QC #13's rs_colorspace count, since a
        # removed sampler can no longer report a mismatch).
        try:
            c4d.EventAdd()
        except Exception:
            pass
        if removed:
            try:
                check_cache.clear()
            except Exception:
                pass

    return {"ok": True, "materials": materials_cleaned, "removed": removed,
            "skipped": skipped}
