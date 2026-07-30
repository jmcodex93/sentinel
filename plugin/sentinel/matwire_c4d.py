# -*- coding: utf-8 -*-
"""RS material writer for matwire (v1.33) — the c4d/maxon adapter.

Follows the LIVE-VERIFIED recipe in
``docs/research/2026-07-29-matwire-spike.md`` verbatim (C4D 2026.303):

- Material creation goes through the **material-handle** path (§8), but
  with the v1.32.1 **build-before-insert** correction (live-caught, see the
  "Corrección v1.32.1" section of the spike doc): the whole node graph is
  built on a NOT-YET-INSERTED ``BaseMaterial(Mmaterial)`` via
  ``GetGraph(mat, ...)`` — which works fine off-document — and only then
  ``InsertMaterial`` + ``AddUndo(NEWOBJ)``. Graph transactions run on a
  material the document has never seen, so they generate NO document undo
  steps: the batch's bracket only ever records N insertions and ONE Cmd+Z
  reverts the whole batch. (The old ``AddUndo(CHANGE)`` anchor made exactly
  ONE material's transaction join — batches of >1 needed 4+ undos.) Never
  ``GetGraph(name=...)`` (no handle → no graph to build on).
- Wiring is GraphDescription dict syntax (§1/§2): ``"#<id"`` marks an
  input port, ``/child`` a group-port child (tex0). Paths are **plain str**
  (§4 — never ``pathlib.as_uri()``); colorspaces always explicit.
  **One documented exception** (mini-spike v1.32.1): the ORM/ARM splitter
  feeds TWO target ports from ONE node, which the dict syntax cannot
  express (nesting duplicates the node — even the same dict instance — and
  there is no ``$ref``). That branch alone is imperative: an isolated
  ApplyDescription for splitter+sampler (AO pattern) followed by explicit
  ``Connect()`` calls in one transaction — see ``_apply_orm_plan``.
- AO sampler is a second, isolated ApplyDescription (§5).
- Node positions via a ``SetValue`` transaction with ``maxon.Float`` (§6);
  never the arrange ``CallCommand``.
- Availability probe: ``FindLatestAsset(...).IsNullValue()`` (§7 — never
  ``bool()``/``IsPopulated()``).

The CALLER (op ``matwire_create``) owns ``StartUndo``/``EndUndo`` around
the whole batch; a failed set is reported without aborting the batch — and
since insertion is the LAST step, a failure means the material never
reached the document, so there is nothing to clean up (no ``mat.Remove()``,
no balancing ``AddUndo(DELETE)``).
"""

import os

import c4d

from sentinel.common.helpers import safe_print
from sentinel.matwire import (ao_destination, channel_colorspace,
                              gloss_destination, orm_contributions)

try:
    import maxon
    MAXON_AVAILABLE = True
except ImportError:  # pytest fake harness / c4dpy without maxon
    maxon = None
    MAXON_AVAILABLE = False

_RS_CORE = "com.redshift3d.redshift4c4d.nodes.core."
_RS_OUTPUT = "com.redshift3d.redshift4c4d.node.output"
_CS_SRGB = "RS_INPUT_COLORSPACE_SRGB"
_CS_RAW = "RS_INPUT_COLORSPACE_RAW"
_ASSETID_ATTR = "net.maxon.node.attribute.assetid"
_RS_UVCTX = _RS_CORE + "uvcontextprojection"

# Port ids measured live in the Task 1 spike (docs/research/
# 2026-07-30-openpbr-spike.md): rsmathinv is born with math_op = 20, and
# 20 was confirmed by render oracle to be `1 - x`. Written explicitly on
# every use — never left to the node default (colorspace/flipy principle).
_RS_INVERT = _RS_CORE + "rsmathinv"
_RS_INVERT_INPUT = _RS_INVERT + ".input"
_RS_INVERT_MATH_OP = _RS_INVERT + ".math_op"
_RS_INVERT_OP_INVERT = 20          # measured: 1 - x

#: Material type -> BRDF node id. OpenPBR first: it is the DEFAULT.
BRDF_NODES = {
    "openpbr": _RS_CORE + "openpbrmaterial",
    "standard": _RS_CORE + "standardmaterial",
}
MATERIAL_TYPES = tuple(BRDF_NODES)
DEFAULT_MATERIAL = "openpbr"

#: Channel -> BRDF input port, per material type. The Standard column was
#: read from the v1.33 writer (where these ids were inline); the OpenPBR
#: column from the live node, cross-checked against TexToMatO
#: (Salad/Redshift/redshift_helper.py:406-445 — facts taken, no code).
BRDF_PORTS = {
    "openpbr": {
        "basecolor": "base_color",
        "roughness": "specular_roughness",
        "metalness": "base_metalness",
        "specular": "specular_color",
        "opacity": "geometry_opacity",
        "bump": "geometry_normal",
        "emission_color": "emission_color",
        "emission_amount": "emission_luminance",
    },
    "standard": {
        "basecolor": "base_color",
        "roughness": "refl_roughness",
        "metalness": "metalness",
        "specular": "refl_color",
        "opacity": "opacity_color",
        "bump": "bump_input",
        "emission_color": "emission_color",
        "emission_amount": "emission_weight",
    },
}

#: The emission amount each BRDF needs for a VISIBLE emission. Both ports
#: are born at 0 (measured), so this is always written — the v1.32
#: differential correction, now per type. The two numbers are NOT
#: interchangeable: Standard's is a 0-1 weight, OpenPBR's is a luminance
#: (nits, not a weight — equivalence with Standard is not scene-independent).
#: 1000 is the HDR reference white; it renders clearly visible, the goal
#: inherited from v1.32 (emission must never ship invisible). Measured in
#: the Task 1 spike (docs/research/2026-07-30-openpbr-spike.md).
BRDF_EMISSION_AMOUNT = {"standard": 1.0, "openpbr": 1000.0}


def _brdf(material):
    """(node id, port table, normalized key) for a material type,
    defaulting on anything unknown. The ops layer normalizes at the
    boundary, so this default is belt-and-braces rather than the
    contract."""
    key = material if material in BRDF_NODES else DEFAULT_MATERIAL
    return BRDF_NODES[key], BRDF_PORTS[key], key


#: Projection selector value -> the node's ``proj_type`` enum (measured
#: live, spike 2026-07-30: 1 = UV Channel, 2 = Tri-Planar). The strings are
#: what the ops payload / SPA carry; the ints never leave this module.
PROJECTION_TYPES = {"uv": 1, "triplanar": 2}

# Format translation ONLY: engine answer ("srgb"/"raw") -> RS constant.
# The DECISION of which channel is which colorspace lives in
# matwire.channel_colorspace (single source, matwire.py docstring) — this
# is not a second table of that decision.
_RS_COLORSPACE = {"srgb": _CS_SRGB, "raw": _CS_RAW}


def _rs_colorspace(channel):
    return _RS_COLORSPACE[channel_colorspace(channel)]

# Column x per node kind (§6 suggested layout); samplers stack on y.
# rscolorsplitter shares the intermediary column with bump/displacement
# (rows are keyed by COLUMN, so cohabitation never stacks — see
# _layout_and_title_nodes).
_LAYOUT_COLS = {
    "uvcontextprojection": -900.0,  # upstream of every sampler (v1.33)
    "texturesampler": -600.0,
    "rscolorcorrection": -450.0,   # one stage BEFORE the AO layer it feeds
    "bumpmap": -300.0,
    "displacement": -300.0,
    "rscolorsplitter": -300.0,
    "rscolorlayer": -300.0,
    "rsmathinv": -300.0,            # glossiness -> roughness invert (OpenPBR)
    "standardmaterial": 0.0,
    "openpbrmaterial": 0.0,
    "output": 300.0,
}
_LAYOUT_ROW_STEP = 220.0

# The Node Editor's VISIBLE label is ``net.maxon.node.base.name`` — NOT
# ``…attribute.title`` (live-caught by the user in the v1.33 matrix: the
# titles were written and read back correctly, yet the editor still showed
# each sampler's FILENAME and each utility node's native type name, because
# `title` is not what it renders). Both are written: `name` is what the
# artist sees, `title` stays for any consumer that reads it.
_TITLE_ATTR = "net.maxon.node.attribute.title"
_NAME_ATTR = "net.maxon.node.base.name"

#: Semantic titles by node KIND (v1.33). The material and the output keep
#: their native identity — renaming them would only hide what they are.
NODE_TITLES = {
    "rscolorcorrection": "Color Correct",
    "rscolorlayer": "AO Multiply",
    "rscolorsplitter": "ORM Split",
    "bumpmap": "Bump",
    "displacement": "Displacement",
    "rsmathinv": "Gloss → Roughness",
}

#: Semantic titles for the SAMPLERS, keyed by the channel they carry.
_CHANNEL_TITLES = {
    "basecolor": "Base Color",
    "roughness": "Roughness",
    "metalness": "Metalness",
    "normal": "Normal",
    "height": "Height",
    "ao": "AO",
    "packed_orm": "ORM",
    "opacity": "Opacity",
    "emission": "Emission",
    "specular": "Specular",
    "glossiness": "Glossiness",
}


def redshift_available():
    """Probe the RS Standard material node asset (§7). The discriminator is
    ``IsNullValue()`` — a bogus id returns an AssetDescription without
    raising and ``bool()`` is True either way."""
    if not MAXON_AVAILABLE:
        return False
    try:
        repo = maxon.AssetInterface.GetUserPrefsRepository()
        desc = repo.FindLatestAsset(
            maxon.AssetTypes.NodeTemplate(),
            maxon.Id(_RS_CORE + "standardmaterial"),
            maxon.Id(), maxon.ASSET_FIND_MODE.LATEST)
        return not desc.IsNullValue()
    except Exception:
        return False


def uvcontext_available():
    """Probe the shared ``uvcontextprojection`` node (RS 2026.2+). Same
    ``IsNullValue()`` idiom as ``redshift_available`` — a bogus id still
    returns a truthy AssetDescription, so ``bool()`` is not a probe.
    Confirmed live 2026-07-30 (spike doc, "Confirmación de puertos v1.33":
    the node probes True, a bogus id False)."""
    if not MAXON_AVAILABLE:
        return False
    try:
        repo = maxon.AssetInterface.GetUserPrefsRepository()
        desc = repo.FindLatestAsset(
            maxon.AssetTypes.NodeTemplate(),
            maxon.Id(_RS_UVCTX),
            maxon.Id(), maxon.ASSET_FIND_MODE.LATEST)
        return not desc.IsNullValue()
    except Exception:
        return False


def openpbr_available():
    """Probe the OpenPBR BRDF node. Same ``IsNullValue()`` idiom as
    ``redshift_available``/``uvcontext_available`` — a bogus id still
    returns a truthy AssetDescription, so ``bool()`` is not a probe.
    Confirmed live 2026-07-30: the node probes True in C4D 2026.303."""
    if not MAXON_AVAILABLE:
        return False
    try:
        repo = maxon.AssetInterface.GetUserPrefsRepository()
        desc = repo.FindLatestAsset(
            maxon.AssetTypes.NodeTemplate(),
            maxon.Id(BRDF_NODES["openpbr"]),
            maxon.Id(), maxon.ASSET_FIND_MODE.LATEST)
        return not desc.IsNullValue()
    except Exception:
        return False


def build_uvcontext_plan(proj_type):
    """Plan for the ONE shared UV context, or ``None`` when the node isn't
    available in this build (then the material is written exactly as
    v1.32.1 — degrade honestly, never promise a wiring we won't make).

    ``proj_type``: 1 = UV Channel, 2 = Tri-Planar (measured live; see
    ``PROJECTION_TYPES`` for the string→int mapping the ops layer uses).

    Two live-measured traps are pinned here:

    - **``uv_tiling = 0`` is written EXPLICITLY.** Its value 1 is *hexagonal*
      tiling, not "tiling on" — the spike rendered hexagons to find that
      out. Never left to the node default (colorspace/flipy principle).
    - **The context's own transform params are NOT written either, and
      that neutrality is DEFAULT-CONDITIONED — measured, not assumed.**
      A context node created with EXACTLY the two keys below (nothing
      else) reads back, live in C4D 2026.303 (2026-07-30, research doc
      "Defaults del contexto (v1.33, cierre de no-regresión)"):
      ``uv_tiles_u = 1.0``, ``uv_tiles_v = 1.0``, ``uv_uniform_tiles =
      True``, ``uv_offset = (0, 0)`` (compares equal to an explicitly
      written ``maxon.Vector(0,0,0)``), ``uv_rotate = 0.0``,
      ``wrap_u/wrap_v = 0``, ``flip_u/flip_v = False``. That is the
      identity transform, so the Global Constraint (``projection="uv"``
      renders identically to v1.32.1) holds on the DEFAULTED node — and
      it was verified end-to-end through this very writer: two materials
      from the same texture set, one with the context and one with the
      probe forced False, rendered 200x200 in Redshift → **40000/40000
      pixels identical, max abs diff 0**. Same yield as the Color Correct
      above: the default state IS the measured one, and writing "neutral"
      constants would only pre-dirty the node the artist is meant to
      grab. If a param here is ever written, RE-MEASURE both claims.
    - **The samplers' own ``scale``/``offset``/``rotate`` are NOT written**
      anywhere. They MULTIPLY with the context (measured: sampler scale 4 ×
      context tiles 2 = 8 tiles), so writing both would give the artist two
      chained transforms instead of one source of truth. Leaving them at
      their defaults keeps the context the single edit point and leaves the
      per-texture tweak free for the artist.

    The connect is imperative, not part of the desc: one ``outcontext``
    feeding N ``uv_context`` ports is not expressible in GraphDescription
    (nesting duplicates the node, there is no ``$ref``) — same reason as
    the ORM splitter."""
    if not uvcontext_available():
        return None
    return {
        "desc": {
            "$type": "#" + _RS_UVCTX,
            "#<" + _RS_UVCTX + ".proj_type": int(proj_type),
            "#<" + _RS_UVCTX + ".uv_tiling": 0,  # 0 = rectangular; 1 = HEX
        },
        "connect_to": _RS_CORE + "texturesampler.uv_context",
    }


def _apply_uvcontext_plan(graph, plan):
    """Materialize a ``build_uvcontext_plan`` result: isolated
    ApplyDescription for the context node, then ONE transaction connecting
    its ``outcontext`` to the ``uv_context`` input of EVERY texturesampler
    in the graph (``_apply_orm_plan`` is the template; fan-out verified
    live: one context → N samplers).

    "EVERY sampler" is literal and deliberate: samplers are discovered by
    assetid on the live graph, so the ORM sampler and the unconnected
    leftovers get the context too — otherwise the shared control would
    silently skip exactly the textures the artist is most likely to be
    fixing up.

    COUNT FIRST, APPLY AFTER: a set with zero samplers can't happen today
    (every set the scanner yields has at least one file), but applying the
    desc before knowing that would leave an ORPHAN context node dangling
    in the graph. Checking first means the node is never created rather
    than created-then-abandoned."""
    samplers = [
        node for node in graph.GetViewRoot().GetInnerNodes(
            mask=maxon.NODE_KIND.NODE, includeThis=False)
        if "texturesampler" in str(node.GetValue(_ASSETID_ATTR) or "")
    ]
    if not samplers:
        return
    maxon.GraphDescription.ApplyDescription(graph, plan["desc"])
    ctx_node = None
    for node in graph.GetViewRoot().GetInnerNodes(
            mask=maxon.NODE_KIND.NODE, includeThis=False):
        if "uvcontextprojection" in str(node.GetValue(_ASSETID_ATTR) or ""):
            ctx_node = node
    if ctx_node is None:
        raise RuntimeError("UV context wiring: context node lookup failed")
    out_id = _RS_UVCTX + ".outcontext"
    with graph.BeginTransaction() as tr:
        out_port = ctx_node.GetOutputs().FindChild(out_id)
        for sampler in samplers:
            out_port.Connect(sampler.GetInputs().FindChild(plan["connect_to"]))
        tr.Commit()


#: Generic maxon Value node — the building block of the UniTransform group.
_VALUE_NODE = "net.maxon.node.type"
_VEC2_TYPE = "net.maxon.parametrictype.vec<2,float>"
_UT_GROUP_ID = "SentinelUniversalXform"
_UT_TITLE = "UniversalXform"
_RS_MULVECTOR = _RS_CORE + "rsmathmulvector"
_UT_MUL_NAME = "Scale"

#: The Value nodes inside the group: ``(node name, port label, datatype or
#: None, identity value)``.
#:
#: The identity values are NOT decoration — a maxon Value node is born at
#: **zero**, so an unwritten Scale would drive every sampler to a 0x0 tiling
#: and the material would render a single stretched texel. Same
#: "siempre explícito" rule that already governs colorspace and flipy.
#:
#: Only the vec2 knobs need a ``datatype`` write: the node's own default is
#: ``float``, which is exactly what ``UniScale`` and ``rotate`` want
#: (measured live 2026-07-30: sampler ``scale``/``offset`` are vec2,
#: ``rotate`` is Float64).
#:
#: ``Scale2D`` is the node name and ``Scale`` the label the artist reads —
#: the same split TexToMatO uses, because the multiply node downstream is
#: what actually carries the name "Scale".
_UT_INPUTS = (
    ("Scale2D", "Scale", _VEC2_TYPE, (1.0, 1.0)),
    ("UniScale", "UniScale", None, 1.0),
    ("Offset", "Offset", _VEC2_TYPE, (0.0, 0.0)),
    ("Rotation", "Rotation", None, 0.0),
)

#: What each group OUTPUT emits and which sampler port it drives:
#: ``(label, source node name, sampler port suffix)``. Scale comes from the
#: multiply (UniScale x Scale2D), the other two straight from their Value.
_UT_OUTPUTS = (
    ("Scale", _UT_MUL_NAME, "texturesampler.scale"),
    ("Offset", "Offset", "texturesampler.offset"),
    ("Rotation", "Rotation", "texturesampler.rotate"),
)


def build_unitransform_plan():
    """Plan for the classic **UniversalXform** group — the fallback shared
    tiling control for Redshift builds WITHOUT ``uvcontextprojection``
    (pre-2026.2). Pure data, so the shape is pytest-pinnable; the wiring
    itself is imperative for the same reason as the UV context (one output
    feeding N ports has no GraphDescription expression).

    Shape: one group node "UniversalXform" holding four Value nodes
    (Scale2D, UniScale, Offset, Rotation) plus a Vector Mul that multiplies
    UniScale x Scale2D. Its three outputs fan out to the ``scale`` /
    ``offset`` / ``rotate`` port of EVERY texturesampler in the material —
    the same single-point-of-edit the UV context gives, built from
    primitives that exist in every Redshift version.

    Modelled on TexToMatO's ``AddUniTransforms`` (read 2026-07-30), keeping
    its UniScale multiply (one field that scales both axes, on top of the
    per-axis Scale) with one deliberate divergence: **the group's INPUT
    ports are kept**, where TexToMatO removes them. Keeping them puts the
    four knobs on the group node itself, so the artist edits them in the
    Attribute Manager without entering the group. Verified live: writing the
    group input port drives the inner Value node.

    Returns ``None`` only when maxon is missing (the pytest harness)."""
    if not MAXON_AVAILABLE:
        return None
    return {
        "value_desc": {"$type": "#" + _VALUE_NODE},
        "mul_desc": {"$type": "#" + _RS_MULVECTOR},
        "mul_name": _UT_MUL_NAME,
        "mul_ports": {
            "uniscale": _RS_MULVECTOR + ".input1",
            "scale": _RS_MULVECTOR + ".input2",
            "out": _RS_MULVECTOR + ".out",
        },
        "group_id": _UT_GROUP_ID,
        "title": _UT_TITLE,
        "column": _LAYOUT_COLS["uvcontextprojection"],
        "inputs": [
            {"node": node, "label": label, "datatype": datatype,
             "value": value}
            for node, label, datatype, value in _UT_INPUTS
        ],
        "outputs": [
            {"label": label, "source": source,
             "connect_to": _RS_CORE + port}
            for label, source, port in _UT_OUTPUTS
        ],
    }


def _ut_value(knob):
    """The maxon value a knob's ``in`` port is written with. vec2 travels as
    a 3-component Vector with z unused (measured: the port accepts it and
    reads back as Vector64)."""
    raw = knob["value"]
    if knob["datatype"] is None:
        return maxon.Float(raw)
    return maxon.Vector(raw[0], raw[1], 0.0)


def _ut_api_available(graph):
    """Whether this build exposes the group/port calls the UniversalXform
    needs. Checked BEFORE the first mutation, so a build that simply lacks
    them is a clean no-op instead of a half-built group left in the graph —
    the same "count first, apply after" discipline as the UV context, which
    matters more here because this branch only ever runs where we cannot
    test."""
    helper = getattr(maxon, "GraphModelHelper", None)
    return bool(
        getattr(graph, "MoveToGroup", None)
        and getattr(helper, "CreateInputPort", None)
        and getattr(helper, "CreateOutputPort", None))


def _ut_same_value(written, read_back):
    """Whether a port kept the identity we wrote. vec2 reads back as a
    Vector64 and floats as Float64, so compare component-wise with a
    tolerance rather than by type or identity."""
    try:
        if hasattr(written, "x"):
            return all(abs(getattr(written, a) - getattr(read_back, a)) < 1e-6
                       for a in ("x", "y"))
        return abs(float(written) - float(read_back)) < 1e-6
    except Exception:
        return False


def _ut_port(ports, port_id, owner):
    """A port that must exist. maxon's ``FindChild`` answers a missing id
    with a null node, and ``Connect`` on one can no-op — which would leave a
    node reading its birth value (zero) while everything downstream looks
    wired. Refuse instead, so the caller degrades honestly.

    Shared by the UniversalXform fallback AND ``_apply_orm_plan`` (the
    release's only other imperative wire) — ``owner`` is caller-supplied so
    the error names the real thing that's missing a port, not a fixed
    subsystem."""
    # NOTE: the write and the Connect on a Value node's ``in`` are both
    # routed here and are redundant for that one port (the write fires
    # first). Kept as belt-and-braces: every end of every wire in this
    # function resolves the same way, so no future edit can reintroduce a
    # bare FindChild by looking like the code next to it.
    port = ports.FindChild(port_id)
    if port is None or port.IsNullValue():
        raise RuntimeError("%s has no port %r" % (owner, port_id))
    return port


def _ut_fresh_node(graph, kind):
    """The one node of ``kind`` in the root graph that hasn't been named yet
    — i.e. the one the ApplyDescription just before this call created.

    Identity by ABSENCE OF NAME, not by position: the caller names each node
    the moment it exists, so exactly one nameless node of that kind can be
    outstanding. Anything else means the graph is not what we think it is,
    and guessing would mis-assign an identity value."""
    fresh = [
        node for node in graph.GetViewRoot().GetInnerNodes(
            mask=maxon.NODE_KIND.NODE, includeThis=False)
        if kind in str(node.GetValue(_ASSETID_ATTR) or "")
        and not str(node.GetValue(_NAME_ATTR) or "").strip()
    ]
    if len(fresh) != 1:
        raise RuntimeError(
            "UniversalXform: expected exactly 1 fresh %s node, found %d"
            % (kind, len(fresh)))
    return fresh[0]


def _apply_unitransform_plan(graph, plan):
    """Materialize ``build_unitransform_plan``.

    Sequence (every step measured live, C4D 2026.303, 2026-07-30):

    1. Count samplers FIRST — the orphan rule from ``_apply_uvcontext_plan``:
       no samplers means the control has nothing to drive, so it is never
       created rather than created-and-abandoned.
    2. Apply the Value desc once per input plus the Vector Mul (identical
       descs create distinct nodes, verified), then set datatype, identity
       value and name on each.
    3. ``MoveToGroup`` — **this INVALIDATES the node handles**. The moved
       nodes live at a new path, and touching the old handle raises "Node
       with path … doesn't exist any longer" (hit in the spike). The inner
       nodes are therefore re-found through ``GetInnerNodes`` on the group
       and matched by the name written in step 2 — which is exactly why
       step 2 names them BEFORE the move.
    4. Wire the multiply (UniScale x Scale2D), create the group's in/out
       ports, and fan the outputs out to every sampler.
    5. Position the group in the upstream column (this runs AFTER the layout
       pass, which only walks the ROOT graph and would put an assetid-less
       group node in column 0 on top of the material).

    Nodes are located by NAME, never by creation order or handle identity:
    ``GetInnerNodes`` hands back fresh wrapper objects on every call, so any
    scheme keyed on ``id()`` silently degenerates into "match everything"."""
    samplers = [
        node for node in graph.GetViewRoot().GetInnerNodes(
            mask=maxon.NODE_KIND.NODE, includeThis=False)
        if "texturesampler" in str(node.GetValue(_ASSETID_ATTR) or "")
    ]
    if not samplers:
        return
    if not _ut_api_available(graph):
        # RAISE, don't return: the caller logs exceptions, and this is the
        # one outcome the artist is actively told otherwise about (the
        # disabled-selector copy promises "one control — a UniversalXform
        # group"). A silent return would make the UI's promise unfalsifiable
        # and leave nothing to debug from. Nothing has been created yet, so
        # there is nothing to clean up.
        raise RuntimeError(
            "UniversalXform: this build exposes no node-group API")
    made = []
    try:
        _ut_build(graph, plan, samplers, made)
    except Exception:
        # Leave NO debris. Everything up to the group move is already
        # committed by the time anything downstream can fail, and an orphan
        # Value node would sit at (0,0) on top of the material — after the
        # layout pass, so nothing would ever reposition it. Removing it
        # restores exactly the v1.32.1 graph the caller degrades to.
        #
        # Newest first, so the group goes before the handles it swallowed;
        # those are dead after the move and raise on touch, which is why
        # each removal is guarded individually rather than as one batch.
        # Removing the group takes its whole interior with it — MEASURED,
        # not assumed (live 2026-07-30: a graph of 8 nodes drops to 2, with
        # 0 Value nodes and 0 multiplies left).
        for node in reversed(made):
            try:
                with graph.BeginTransaction() as tr:
                    node.Remove()
                    tr.Commit()
            except Exception:
                pass
        raise


def _ut_build(graph, plan, samplers, made):
    """The mutating half of ``_apply_unitransform_plan``; separated so the
    caller can undo a partial build. EVERY node it creates is appended to
    ``made`` as soon as it exists — including the group — because a failure
    after the group move leaves only that handle alive to clean up with."""
    # ONE apply, then IMMEDIATELY name what it made — never a batch of
    # identical applies zipped against the plan by position. Graph
    # enumeration order is NOT guaranteed to be creation order (measured:
    # three runs of this very function enumerated the group's ports in three
    # different orders), and a permutation would quietly write Scale's
    # identity into Rotation. Naming one at a time makes the only node
    # without a name the one just created.
    for knob in plan["inputs"]:
        maxon.GraphDescription.ApplyDescription(graph, plan["value_desc"])
        node = _ut_fresh_node(graph, _VALUE_NODE)
        # Track it BEFORE the transaction that can raise: ApplyDescription
        # already committed the node, so a failure in the writes below would
        # otherwise strand it in the root graph where the cleanup can't see
        # it — the exact debris this whole path exists to avoid.
        made.append(node)
        with graph.BeginTransaction() as tr:
            if knob["datatype"] is not None:
                _ut_port(node.GetInputs(), "datatype",
                         knob["node"]).SetPortValue(maxon.Id(knob["datatype"]))
            _ut_port(node.GetInputs(), "in",
                     knob["node"]).SetPortValue(_ut_value(knob))
            node.SetValue(_NAME_ATTR, maxon.String(knob["node"]))
            tr.Commit()
    maxon.GraphDescription.ApplyDescription(graph, plan["mul_desc"])
    mul_node = _ut_fresh_node(graph, "rsmathmulvector")
    made.append(mul_node)
    with graph.BeginTransaction() as tr:
        mul_node.SetValue(_NAME_ATTR, maxon.String(plan["mul_name"]))
        tr.Commit()
    with graph.BeginTransaction() as tr:
        group = graph.MoveToGroup(maxon.GraphNode(),
                                  maxon.Id(plan["group_id"]), list(made))
        tr.Commit()
    made.append(group)
    # Handles above are dead from here on — re-find by the names just written.
    inner = []
    group.GetInnerNodes(maxon.NODE_KIND.NODE, False, inner)
    by_name = {str(node.GetValue(_NAME_ATTR)): node for node in inner}

    def _inner(name):
        node = by_name.get(name)
        if node is None:
            raise RuntimeError(
                "UniversalXform: inner node %r lost in the group move" % name)
        return node

    # ONE transaction for the whole wiring, and that span is LOAD-BEARING:
    # a raise below leaves it uncommitted, so maxon rolls back every port
    # created and every sampler already fanned out, and the cleanup then
    # only has to remove the group. Splitting this into two transactions
    # would commit a half-wired fan-out that the removal can no longer undo.
    with graph.BeginTransaction() as tr:
        group.SetValue(_NAME_ATTR, maxon.String(plan["title"]))
        group.SetValue(_TITLE_ATTR, maxon.String(plan["title"]))
        group.SetValue("net.maxon.node.base.xpos", maxon.Float(plan["column"]))
        group.SetValue("net.maxon.node.base.ypos", maxon.Float(0.0))
        # UniScale (float) x Scale2D (vec2) -> the Scale the samplers see.
        # Both ends are resolved through _ut_port, which refuses a missing
        # port instead of letting Connect no-op: an unfed multiply input
        # sits at its birth value and delivers Scale=0 to every sampler —
        # the same stretched-texel failure the read-back guard below covers
        # for the group ports.
        mul = _inner(plan["mul_name"])
        mul_ports = plan["mul_ports"]
        _ut_port(_inner("UniScale").GetOutputs(), "out", "UniScale").Connect(
            _ut_port(mul.GetInputs(), mul_ports["uniscale"], "multiply"))
        _ut_port(_inner("Scale2D").GetOutputs(), "out", "Scale2D").Connect(
            _ut_port(mul.GetInputs(), mul_ports["scale"], "multiply"))
        for row, name in enumerate(sorted(by_name)):
            # The inner nodes are created after the layout pass and would
            # otherwise all sit at (0,0): five overlapping nodes greeting
            # anyone who opens the group. Same bug class as the v1.32.1
            # layout root-fix, invisible from outside the group.
            by_name[name].SetValue("net.maxon.node.base.xpos",
                                   maxon.Float(0.0))
            by_name[name].SetValue("net.maxon.node.base.ypos",
                                   maxon.Float(row * _LAYOUT_ROW_STEP))
        for knob in plan["inputs"]:
            node = _inner(knob["node"])
            in_port = maxon.GraphModelHelper.CreateInputPort(
                group, "ut_in_" + knob["node"].lower(), knob["label"])
            # Through _ut_port like every other end: a null node here would
            # make Connect no-op, the knob would drive nothing, and the
            # read-back below would still pass (it reads the GROUP port,
            # which does hold the identity) while the samplers received the
            # inner Values' birth zeros. The one route to the 0-scale
            # material that every other guard here would miss.
            in_port.Connect(_ut_port(node.GetInputs(), "in", knob["node"]))
            # The identity value is written on the GROUP port, not only on
            # the inner node: once the group port drives the inner ``in``,
            # the group port is the live value — and it is born at zero, so
            # skipping this write would push Scale=(0,0) into every sampler
            # and render one stretched texel. The inner write above stays as
            # the node's own base value.
            written = _ut_value(knob)
            in_port.SetPortValue(written)
            # READ IT BACK before anything is wired to it. The datatype of a
            # port created by CreateInputPort is chosen by the build, and
            # this branch only runs on builds nobody here can test: if the
            # write silently no-ops or coerces, the fan-out below would push
            # Scale=(0,0) into every sampler and the material would ship one
            # stretched texel while reporting success. Failing here instead
            # gives the caller the honest v1.32.1 degrade.
            if not _ut_same_value(written, in_port.GetPortValue()):
                raise RuntimeError(
                    "UniversalXform: %s port did not keep its identity value "
                    "— refusing to drive the samplers from it" % knob["node"])
        for spec in plan["outputs"]:
            label = spec["label"]
            source = _inner(spec["source"])
            out_id = (mul_ports["out"] if spec["source"] == plan["mul_name"]
                      else "out")
            out_port = maxon.GraphModelHelper.CreateOutputPort(
                group, "ut_out_" + label.lower(), label)
            _ut_port(source.GetOutputs(), out_id,
                     spec["source"]).Connect(out_port)
            for sampler in samplers:
                out_port.Connect(_ut_port(sampler.GetInputs(),
                                          spec["connect_to"], "sampler"))
        tr.Commit()
    return group


def _sampler(path, colorspace):
    return {
        "$type": "#" + _RS_CORE + "texturesampler",
        "#<" + _RS_CORE + "texturesampler.tex0/path": path,
        "#<" + _RS_CORE + "texturesampler.tex0/colorspace": colorspace,
    }


def _join(folder, rel):
    """Join a scan-relative path (always ``/``-separated, per the recursive
    lister contract) onto ``folder`` with the platform separator."""
    return os.path.join(folder, *rel.split("/"))


def build_description(folder, tex_set, multiply_ao=False,
                      material=DEFAULT_MATERIAL):
    """(main_desc, ao_desc | None) — pure dict assembly per §2/§2b and the
    Global Constraints wiring rules. The engine already enforces the
    channel precedences (glossiness never coexists with roughness/metalness,
    normal is a single resolved key), so each key is written at most once.

    ``material`` ("openpbr" | "standard", default OpenPBR — v1.34) selects
    the BRDF node and its port table via ``_brdf``; unknown values default
    rather than raise (the ops layer normalizes at the boundary). OpenPBR
    has no ``specular_isglossiness`` port (measured live), so a glossiness
    map there is inverted through an ``rsmathinv`` node instead of the
    native bool — see ``gloss_destination``.

    v1.33 adds two nodes on the basecolor branch:

    - an **identity ``rscolorcorrection`` ALWAYS** between the basecolor
      sampler and ``base_color``. Measured cost ≈0 and measured identity
      (spike 2026-07-30 §B.2, ``T_CC``: max diff 0 over hundreds of
      samples), and it is exactly where the artist ends up reaching.
      NOTE (review): that identity is DEFAULT-conditioned — the spike
      measured the node with NO params written, so this branch writes
      none. Writing "neutral" constants would be guessing values whose
      neutrality was never measured (and would pre-dirty the very node
      the artist is meant to grab). This is the one place where "never
      depend on node defaults" yields: the default state IS the measured
      one. If a param is ever written here, the identity claim above must
      be re-measured.
    - an **opt-in ``rscolorlayer``** (``multiply_ao``) multiplying the AO
      over the corrected color: base layer = the correction, layer 1 = the
      AO sampler, ``layer1_blend_mode = 4`` (**Multiply** — enum measured;
      2 is NOT multiply and produced a radically different image). Then the
      AO is no longer emitted as a loose sampler (``ao_desc is None``).

    WHERE the AO goes is decided ONCE, by ``matwire.ao_destination`` — the
    same function the preview's AO row reads, so the row can't promise a
    wiring this writer won't make. In particular an AO-only set (no
    basecolor) has nothing to multiply into: no layer is built and the AO
    stays loose. ``multiply_ao=False`` (the default) leaves every existing
    caller byte-identical apart from the correction."""
    channels = tex_set.get("channels") or {}

    def path(channel):
        return _join(folder, channels[channel])

    node_id, ports, material = _brdf(material)
    sm = "#<" + node_id + "."
    cc = _RS_CORE + "rscolorcorrection"
    layer = _RS_CORE + "rscolorlayer"
    ao_dest = ao_destination(channels, multiply_ao)
    brdf = {"$type": "#" + node_id}
    if "basecolor" in channels:
        base_branch = {
            "$type": "#" + cc,
            "#<" + cc + ".input": _sampler(
                path("basecolor"), _rs_colorspace("basecolor")),
        }
        if ao_dest == "base_color_multiply":
            base_branch = {
                "$type": "#" + layer,
                "#<" + layer + ".base_color": base_branch,
                "#<" + layer + ".layer1_color": _sampler(
                    path("ao"), _rs_colorspace("ao")),
                # ALWAYS explicit — never depend on node defaults
                # (colorspace/flipy principle). The live default IS True,
                # but nothing in the graph should rest on that.
                "#<" + layer + ".layer1_enable": True,
                "#<" + layer + ".layer1_blend_mode": 4,  # Multiply (measured)
            }
        brdf[sm + ports["basecolor"]] = base_branch
    if "roughness" in channels:
        brdf[sm + ports["roughness"]] = _sampler(path("roughness"), _rs_colorspace("roughness"))
    if "metalness" in channels:
        brdf[sm + ports["metalness"]] = _sampler(path("metalness"), _rs_colorspace("metalness"))
    if "normal" in channels:
        bump = {
            "$type": "#" + _RS_CORE + "bumpmap",
            "#<" + _RS_CORE + "bumpmap.inputtype": 1,  # Tangent-Space Normal
            "#<" + _RS_CORE + "bumpmap.input": _sampler(path("normal"), _rs_colorspace("normal")),
            # ALWAYS explicit — same principle as the colorspaces: never
            # depend on node defaults. (Registro honesto: el default nativo
            # de flipy es FALSE — verificado live con lectura correcta; el
            # "bug" que motivó esto era un artefacto del harness de
            # verificación: bool(maxon.Bool) devuelve la truthiness del
            # OBJETO, no el dato — leer con repr()/comparación al dato.
            # El write explícito se queda como endurecimiento.)
            "#<" + _RS_CORE + "bumpmap.flipy": bool(tex_set.get("normal_flipy")),
        }
        brdf[sm + ports["bump"]] = bump
    if "opacity" in channels:
        brdf[sm + ports["opacity"]] = _sampler(path("opacity"), _rs_colorspace("opacity"))
    if "emission" in channels:
        brdf[sm + ports["emission_color"]] = _sampler(path("emission"), _rs_colorspace("emission"))
        # ALWAYS written: both amount ports are born at 0 (measured), so
        # leaving it default ships invisible emission — the v1.32
        # differential correction, now per BRDF (the two values are NOT
        # interchangeable: weight vs luminance).
        brdf[sm + ports["emission_amount"]] = BRDF_EMISSION_AMOUNT[material]
    if "specular" in channels:
        brdf[sm + ports["specular"]] = _sampler(path("specular"), _rs_colorspace("specular"))
    gloss_dest = gloss_destination(channels, material)
    if gloss_dest is not None:
        gloss = _sampler(path("glossiness"), _rs_colorspace("glossiness"))
        if gloss_dest == "roughness_inverted":
            # OpenPBR has no isglossiness port (measured), so the map is
            # inverted into roughness. This is the node v1.32 catalogued
            # and deliberately left unused — the native bool made it bloat
            # THERE; here it is the only correct wiring. math_op = 20 is
            # the measured invert operation (1 - x) — written explicitly,
            # never inherited from the node's default (Task 1 spike,
            # docs/research/2026-07-30-openpbr-spike.md).
            gloss = {"$type": "#" + _RS_INVERT,
                     "#<" + _RS_INVERT_INPUT: gloss,
                     "#<" + _RS_INVERT_MATH_OP: _RS_INVERT_OP_INVERT}
        brdf[sm + ports["roughness"]] = gloss
        if gloss_dest == "roughness_isglossiness":
            brdf[sm + "refl_isglossiness"] = True  # Standard only
    desc = {
        "$type": "#" + _RS_OUTPUT,
        "#<" + _RS_OUTPUT + ".surface": brdf,
    }
    if "height" in channels:
        desc["#<" + _RS_OUTPUT + ".displacement"] = {
            "$type": "#" + _RS_CORE + "displacement",
            "#<" + _RS_CORE + "displacement.texmap": _sampler(path("height"), _rs_colorspace("height")),
        }
    # Loose sampler ONLY when the AO isn't wired into the color layer.
    ao_desc = (_sampler(path("ao"), _rs_colorspace("ao"))
               if ao_dest == "unconnected" else None)
    return desc, ao_desc


def build_orm_plan(folder, tex_set, material=DEFAULT_MATERIAL):
    """Pure assembly of the packed_orm splitter branch, or ``None``.

    Per the v1.32.1 mini-spike (spike doc, "Mini-spike v1.32.1"): ONE
    splitter feeding TWO target ports is NOT expressible declaratively —
    dict nesting duplicates the node (even the same dict instance) and
    GraphDescription has no ``$ref`` mechanism — so the plan carries a
    splitter desc for a second ISOLATED ApplyDescription (AO pattern) plus
    imperative ``(out_port_id, in_port_id)`` connect pairs for one
    transaction (``_apply_orm_plan``).

    Dedicated-wins per output: ``outg`` -> the roughness port only without a
    dedicated roughness/glossiness map (the roughness port is already taken
    when one exists — natively via Standard's ``refl_isglossiness`` bool, or
    via the interposed ``rsmathinv`` under OpenPBR); ``outb`` -> the
    metalness port only without a dedicated metalness map. ``outr`` (AO) is
    NEVER connected. That RULE lives once, in ``matwire.orm_contributions``
    — the same function the
    preview's ``contributes`` note reads, so the row the artist sees and
    the wiring they get can't drift (review I2). If both dedicated maps
    exist the splitter contributes nothing: the ORM file still lands as a
    visible unconnected sampler (M1)."""
    channels = tex_set.get("channels") or {}
    if "packed_orm" not in channels:
        return None
    node_id, ports, _ = _brdf(material)
    split = _RS_CORE + "rscolorsplitter"
    contributes = orm_contributions(channels)
    connects = []
    if "roughness" in contributes:
        connects.append((split + ".outg", node_id + "." + ports["roughness"]))
    if "metalness" in contributes:
        connects.append((split + ".outb", node_id + "." + ports["metalness"]))
    brdf_kind = node_id.rsplit(".", 1)[-1]   # "openpbrmaterial" | "standardmaterial"
    if not connects:
        # Both target channels covered by dedicated maps: the splitter would
        # contribute NOTHING (outr/AO never wires) — but the ORM FILE must
        # still be visible in the graph (same philosophy as AO/leftovers:
        # recognized files never vanish silently; review M1, v1.32.1).
        return {
            "splitter_desc": _sampler(
                _join(folder, channels["packed_orm"]),
                _rs_colorspace("packed_orm")),
            "connects": [],
            "brdf_kind": brdf_kind,
        }
    return {
        "splitter_desc": {
            "$type": "#" + split,
            "#<" + split + ".input": _sampler(
                _join(folder, channels["packed_orm"]),
                _rs_colorspace("packed_orm")),
        },
        "connects": connects,
        "brdf_kind": brdf_kind,
    }


def build_leftover_descriptions(folder, files):
    """Unconnected RAW samplers for opt-in leftover import — one isolated
    ApplyDescription scope each (AO pattern, §5). RAW: leftovers are
    unrecognized files, never color-managed on faith."""
    return [_sampler(_join(folder, f), _CS_RAW) for f in (files or [])]


def _apply_orm_plan(graph, plan):
    """Materialize a ``build_orm_plan`` result: second isolated
    ApplyDescription for splitter+sampler, then the connect pairs in ONE
    transaction (mini-spike v1.32.1 recipe — sharing one splitter across
    two ports is not expressible declaratively). Node lookup by assetid
    substring, same discovery walk as ``_layout_and_title_nodes``."""
    maxon.GraphDescription.ApplyDescription(graph, plan["splitter_desc"])
    if not plan["connects"]:
        # Both-dedicated case (review M1): the desc above was a bare
        # unconnected ORM sampler — nothing to wire, and the splitter
        # lookup below would rightly fail.
        return
    split_node = sm_node = None
    for node in graph.GetViewRoot().GetInnerNodes(
            mask=maxon.NODE_KIND.NODE, includeThis=False):
        asset_id = str(node.GetValue(_ASSETID_ATTR) or "")
        if "rscolorsplitter" in asset_id:
            split_node = node
        elif plan["brdf_kind"] in asset_id:
            sm_node = node
    if split_node is None or sm_node is None:
        raise RuntimeError("ORM splitter wiring: node lookup failed")
    with graph.BeginTransaction() as tr:
        for out_id, in_id in plan["connects"]:
            # This is the release's ONLY fail-silent wire. Every other
            # OpenPBR port id rides GraphDescription.ApplyDescription, which
            # fails LOUD on a bad id — that loudness is the whole premise of
            # the server-side degradation. This connect is imperative
            # (mini-spike v1.32.1: one splitter into two ports isn't
            # declarative), and maxon answers a missing port id with a null
            # node whose Connect() silently no-ops (measured; see
            # ``_ut_port``'s docstring). Route both ends through it so a
            # wrong id — e.g. if ``base_metalness``/``specular_roughness``
            # ever aren't the literal input id on some Redshift build —
            # raises instead of returning ok:True with the splitter wired to
            # nothing and the preview row lying "-> roughness + metalness".
            out_port = _ut_port(split_node.GetOutputs(), out_id, "ORM splitter")
            in_port = _ut_port(sm_node.GetInputs(), in_id, plan["brdf_kind"])
            out_port.Connect(in_port)
        tr.Commit()


def _kind_from_assetid(value):
    """Node KIND (last dotted segment) from a raw ``assetid`` attribute read
    — pure, so it can be pytest-pinned without a graph.

    ``node.GetValue(assetid)`` returns a maxon **Pair** whose ``str()`` is
    ``"(com...texturesampler,)"`` — verified live 2026-07-30 (v1.32.1
    mini-spike). Without stripping the parens/comma every kind read
    ``"texturesampler,)"``, ``_LAYOUT_COLS`` never matched, and every
    material created since v1.32 stacked in column 0.0. A plain id string
    (``"com...texturesampler"``) passes through unchanged."""
    return str(value or "").strip("(),").rsplit(".", 1)[-1]


def build_node_titles(folder, tex_set, leftover_files=None):
    """``{absolute texture path: sampler title}`` — pure, so the titling
    decision is pytest-pinnable without a graph.

    Samplers are titled by their CHANNEL ("Base Color", "Roughness", …),
    NOT by their filename: the file path is already displayed on the node,
    and real pack filenames are long, resolution-tokened and near-identical
    across a set ("plaster_A_8k_BaseColor.jpg") — the channel is the one
    thing that says what the node DOES in this graph. Leftovers have no
    channel, so they keep their basename (which is exactly the information
    the artist needs to decide what to do with them)."""
    titles = {}
    for channel, rel in (tex_set.get("channels") or {}).items():
        title = _CHANNEL_TITLES.get(channel)
        if title:
            titles[_join(folder, rel)] = title
    for rel in leftover_files or []:
        full = _join(folder, rel)
        titles[full] = os.path.basename(full)
    return titles


def _node_title(kind, sampler_path, titles):
    """The ONE title decision the layout pass applies (``None`` = leave the
    node's native name). Samplers resolve through the channel map, falling
    back to the basename; every other kind through ``NODE_TITLES``."""
    if kind == "texturesampler":
        if sampler_path in (titles or {}):
            return titles[sampler_path]
        return os.path.basename(sampler_path) or None
    return NODE_TITLES.get(kind)


def _sampler_path(node):
    """The ``tex0/path`` value of a live sampler node, or "" — the join key
    between the graph and ``build_node_titles``. Child ports are addressed
    by their SHORT id ("path") under the group port, and the value str()s to
    the plain path (both verified live, C4D 2026.303, 2026-07-30)."""
    try:
        tex0 = node.GetInputs().FindChild(_RS_CORE + "texturesampler.tex0")
        if tex0 is None or tex0.IsNullValue():
            return ""
        child = tex0.FindChild("path")
        if child is None or child.IsNullValue():
            return ""
        return str(child.GetPortValue() or "")
    except Exception:
        return ""


def _layout_and_title_nodes(graph, titles=None):
    """Position AND name every node — one transaction, since both are plain
    node-attribute writes on the same walk.

    Positions: GraphDescription assigns none (§6), so xpos/ypos are set
    explicitly or the graph stacks at (0,0). Nodes located by assetid; rows
    are keyed by COLUMN (x value), not kind — bumpmap, displacement,
    rscolorsplitter and rscolorlayer share column -300.0, so keying by kind
    would stack cohabitants at the same (x,y).

    Titles: ``net.maxon.node.attribute.title`` (write+read-back verified
    live 2026-07-30) via ``_node_title`` — semantic labels so the artist
    reads "Base Color → Color Correct → AO Multiply" instead of four
    identical "Texture" nodes."""
    rows = {}
    with graph.BeginTransaction() as tr:
        for node in graph.GetViewRoot().GetInnerNodes(
                mask=maxon.NODE_KIND.NODE, includeThis=False):
            kind = _kind_from_assetid(node.GetValue(_ASSETID_ATTR))
            col = _LAYOUT_COLS.get(kind, 0.0)
            index = rows.get(col, 0)
            rows[col] = index + 1
            node.SetValue("net.maxon.node.base.xpos", maxon.Float(col))
            node.SetValue("net.maxon.node.base.ypos",
                          maxon.Float(index * _LAYOUT_ROW_STEP))
            title = _node_title(
                kind,
                _sampler_path(node) if kind == "texturesampler" else "",
                titles or {})
            if title:
                node.SetValue(_TITLE_ATTR, maxon.String(title))
                node.SetValue(_NAME_ATTR, maxon.String(title))
        tr.Commit()


def create_material_for_set(doc, folder, tex_set, name, leftover_files=None,
                            multiply_ao=False, projection="uv",
                            material=DEFAULT_MATERIAL):
    """Build ONE RS material for ``tex_set`` (engine shape from
    ``matwire.scan_texture_sets``). ``name`` arrives already deduped;
    ``leftover_files`` (opt-in) ride along as extra unconnected RAW
    samplers. The caller owns the undo block.

    ORDERING IS THE CONTRACT (v1.32.1, live-caught): the ENTIRE graph is
    built on the off-document material and ``InsertMaterial`` is the LAST
    step. Graph transactions on an ALREADY-INSERTED material each generate
    their own document undo step (that is why a 2-material batch needed 4+
    Cmd+Z); off-document they generate none, so the batch bracket records
    only N insertions → ONE Cmd+Z reverts everything. Consequence for the
    failure path: anything that raises happens BEFORE insertion, the
    document never saw the material and no undo record exists for it — so
    there is nothing to remove and no DELETE record to balance. Just
    report.

    ``projection`` ("uv" | "triplanar") selects the shared UV context's
    ``proj_type``. When the context node isn't available in this build the
    plan is ``None`` and the material falls back to the classic UniTransform
    group — the same single point of tiling edit, built from primitives that
    exist in every Redshift version. Projection stays UV-only there: the
    context is what makes tri-planar a property of the shared control, and
    the SPA disables the selector accordingly. ``material`` ("openpbr" |
    "standard", default OpenPBR — v1.34) selects the BRDF via ``_brdf``,
    threaded into both ``build_description`` and ``build_orm_plan`` so the
    ORM splitter targets whichever BRDF is actually in the graph."""
    try:
        desc, ao_desc = build_description(folder, tex_set,
                                          multiply_ao=multiply_ao,
                                          material=material)
        orm_plan = build_orm_plan(folder, tex_set, material=material)
        uvctx_plan = build_uvcontext_plan(
            PROJECTION_TYPES.get(projection, PROJECTION_TYPES["uv"]))
        titles = build_node_titles(folder, tex_set, leftover_files)
        mat = c4d.BaseMaterial(c4d.Mmaterial)
        mat.SetName(name)
        graph = maxon.GraphDescription.GetGraph(
            mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)
        maxon.GraphDescription.ApplyDescription(graph, desc)
        if orm_plan is not None:
            _apply_orm_plan(graph, orm_plan)  # mini-spike v1.32.1 recipe
        if ao_desc is not None:
            maxon.GraphDescription.ApplyDescription(graph, ao_desc)  # isolated (§5)
        for leftover_desc in build_leftover_descriptions(folder, leftover_files):
            maxon.GraphDescription.ApplyDescription(graph, leftover_desc)
        # ORDER MATTERS: the context connects to EVERY sampler by walking the
        # live graph, so it must run AFTER every sampler-creating apply
        # (main desc, ORM, loose AO, leftovers) — a sampler born later would
        # silently miss the shared control. And BEFORE the layout/title pass,
        # which positions whatever nodes exist at that moment (the context
        # needs its column, -900).
        if uvctx_plan is not None:
            _apply_uvcontext_plan(graph, uvctx_plan)
        _layout_and_title_nodes(graph, titles)
        # FALLBACK, and deliberately AFTER the layout pass: on Redshift
        # builds without the context node, the classic UniversalXform group
        # gives the same single point of tiling edit. It positions itself
        # and its own contents (an assetid-less group node would land in
        # column 0 on top of the material if the layout pass saw it), and
        # the four Value nodes plus the multiply live INSIDE the group, so
        # that pass never walks them.
        #
        # Best-effort by design: this branch only ever executes on Redshift
        # versions we cannot test against, so a failure here must not take
        # down a material that is otherwise complete and correct. The plan
        # cleans up after itself, so what the artist gets is exactly the
        # v1.32.1 graph — tiling is then adjusted per sampler. It is logged,
        # not swallowed: silence would leave the disabled-selector copy
        # promising a control that isn't there, with nothing to debug from.
        if uvctx_plan is None:
            ut_plan = build_unitransform_plan()
            if ut_plan is not None:
                try:
                    _apply_unitransform_plan(graph, ut_plan)
                except Exception as exc:
                    safe_print(
                        "UniversalXform fallback skipped for %r (%s); the "
                        "material is complete but has no shared tiling "
                        "control" % (name, exc))
        # LAST — the document's only record of this material is the insertion.
        doc.InsertMaterial(mat)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)   # AFTER insert (NEWOBJ contract)
        return {"ok": True, "material_name": name, "error": None}
    except Exception as exc:
        return {"ok": False, "material_name": name, "error": str(exc)}
