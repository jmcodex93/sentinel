# -*- coding: utf-8 -*-
"""RS material writer for matwire (v1.32) — the c4d/maxon adapter.

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

from sentinel.matwire import ao_destination, channel_colorspace, orm_contributions

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
    "standardmaterial": 0.0,
    "output": 300.0,
}
_LAYOUT_ROW_STEP = 220.0

_TITLE_ATTR = "net.maxon.node.attribute.title"

#: Semantic titles by node KIND (v1.33). The material and the output keep
#: their native identity — renaming them would only hide what they are.
NODE_TITLES = {
    "rscolorcorrection": "Color Correct",
    "rscolorlayer": "AO Multiply",
    "rscolorsplitter": "ORM Split",
    "bumpmap": "Bump",
    "displacement": "Displacement",
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


def build_description(folder, tex_set, multiply_ao=False):
    """(main_desc, ao_desc | None) — pure dict assembly per §2/§2b and the
    Global Constraints wiring rules. The engine already enforces the
    channel precedences (glossiness never coexists with roughness/metalness,
    normal is a single resolved key), so each key is written at most once.

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

    sm = "#<" + _RS_CORE + "standardmaterial."
    cc = _RS_CORE + "rscolorcorrection"
    layer = _RS_CORE + "rscolorlayer"
    ao_dest = ao_destination(channels, multiply_ao)
    material = {"$type": "#" + _RS_CORE + "standardmaterial"}
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
        material[sm + "base_color"] = base_branch
    if "roughness" in channels:
        material[sm + "refl_roughness"] = _sampler(path("roughness"), _rs_colorspace("roughness"))
    if "metalness" in channels:
        material[sm + "metalness"] = _sampler(path("metalness"), _rs_colorspace("metalness"))
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
        material[sm + "bump_input"] = bump
    if "opacity" in channels:
        material[sm + "opacity_color"] = _sampler(path("opacity"), _rs_colorspace("opacity"))
    if "emission" in channels:
        material[sm + "emission_color"] = _sampler(path("emission"), _rs_colorspace("emission"))
        material[sm + "emission_weight"] = 1.0  # literal + sampler, same scope (§2b)
    if "specular" in channels:
        material[sm + "refl_color"] = _sampler(path("specular"), _rs_colorspace("specular"))
    if "glossiness" in channels:
        material[sm + "refl_roughness"] = _sampler(path("glossiness"), _rs_colorspace("glossiness"))
        material[sm + "refl_isglossiness"] = True  # no invert node
    desc = {
        "$type": "#" + _RS_OUTPUT,
        "#<" + _RS_OUTPUT + ".surface": material,
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


def build_orm_plan(folder, tex_set):
    """Pure assembly of the packed_orm splitter branch, or ``None``.

    Per the v1.32.1 mini-spike (spike doc, "Mini-spike v1.32.1"): ONE
    splitter feeding TWO target ports is NOT expressible declaratively —
    dict nesting duplicates the node (even the same dict instance) and
    GraphDescription has no ``$ref`` mechanism — so the plan carries a
    splitter desc for a second ISOLATED ApplyDescription (AO pattern) plus
    imperative ``(out_port_id, in_port_id)`` connect pairs for one
    transaction (``_apply_orm_plan``).

    Dedicated-wins per output: ``outg`` -> refl_roughness only without a
    dedicated roughness/glossiness map (glossiness occupies refl_roughness
    via ``refl_isglossiness``); ``outb`` -> metalness only without a
    dedicated metalness map. ``outr`` (AO) is NEVER connected. That RULE
    lives once, in ``matwire.orm_contributions`` — the same function the
    preview's ``contributes`` note reads, so the row the artist sees and
    the wiring they get can't drift (review I2). If both dedicated maps
    exist the splitter contributes nothing: the ORM file still lands as a
    visible unconnected sampler (M1)."""
    channels = tex_set.get("channels") or {}
    if "packed_orm" not in channels:
        return None
    split = _RS_CORE + "rscolorsplitter"
    contributes = orm_contributions(channels)
    connects = []
    if "roughness" in contributes:
        connects.append((split + ".outg",
                         _RS_CORE + "standardmaterial.refl_roughness"))
    if "metalness" in contributes:
        connects.append((split + ".outb",
                         _RS_CORE + "standardmaterial.metalness"))
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
        }
    return {
        "splitter_desc": {
            "$type": "#" + split,
            "#<" + split + ".input": _sampler(
                _join(folder, channels["packed_orm"]),
                _rs_colorspace("packed_orm")),
        },
        "connects": connects,
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
        elif "standardmaterial" in asset_id:
            sm_node = node
    if split_node is None or sm_node is None:
        raise RuntimeError("ORM splitter wiring: node lookup failed")
    with graph.BeginTransaction() as tr:
        for out_id, in_id in plan["connects"]:
            out_port = split_node.GetOutputs().FindChild(out_id)
            in_port = sm_node.GetInputs().FindChild(in_id)
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
        tr.Commit()


def create_material_for_set(doc, folder, tex_set, name, leftover_files=None,
                            multiply_ao=False, projection="uv"):
    """Build ONE RS Standard material for ``tex_set`` (engine shape from
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
    ``proj_type``; when the context node isn't available in this build the
    plan is ``None`` and the material is written exactly as v1.32.1."""
    try:
        desc, ao_desc = build_description(folder, tex_set,
                                          multiply_ao=multiply_ao)
        orm_plan = build_orm_plan(folder, tex_set)
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
        # LAST — the document's only record of this material is the insertion.
        doc.InsertMaterial(mat)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)   # AFTER insert (NEWOBJ contract)
        return {"ok": True, "material_name": name, "error": None}
    except Exception as exc:
        return {"ok": False, "material_name": name, "error": str(exc)}
