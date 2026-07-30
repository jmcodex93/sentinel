# -*- coding: utf-8 -*-
"""RS material writer for matwire (v1.32) — the c4d/maxon adapter.

Follows the LIVE-VERIFIED recipe in
``docs/research/2026-07-29-matwire-spike.md`` verbatim (C4D 2026.303):

- Material creation goes through the **material-handle** path (§8):
  ``BaseMaterial(Mmaterial)`` + ``InsertMaterial`` + ``AddUndo(NEWOBJ)`` +
  ``AddUndo(CHANGE)`` anchor (MANDATORY — without it the maxon Apply
  transaction is its own undo step) + ``GetGraph(mat, ...)``. Never
  ``GetGraph(name=...)`` (no handle → no undo anchor, no cleanup).
- Wiring is pure GraphDescription dict syntax (§1/§2): ``"#<id"`` marks an
  input port, ``/child`` a group-port child (tex0). Paths are **plain str**
  (§4 — never ``pathlib.as_uri()``); colorspaces always explicit.
- AO sampler is a second, isolated ApplyDescription (§5).
- Node positions via a ``SetValue`` transaction with ``maxon.Float`` (§6);
  never the arrange ``CallCommand``.
- Availability probe: ``FindLatestAsset(...).IsNullValue()`` (§7 — never
  ``bool()``/``IsPopulated()``).

The CALLER (op ``matwire_create``) owns ``StartUndo``/``EndUndo`` around
the whole batch; a failed set removes its material (``mat.Remove()``, §8c)
and reports the error without aborting the batch.
"""

import os

import c4d

from sentinel.matwire import channel_colorspace

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

# Format translation ONLY: engine answer ("srgb"/"raw") -> RS constant.
# The DECISION of which channel is which colorspace lives in
# matwire.channel_colorspace (single source, matwire.py docstring) — this
# is not a second table of that decision.
_RS_COLORSPACE = {"srgb": _CS_SRGB, "raw": _CS_RAW}


def _rs_colorspace(channel):
    return _RS_COLORSPACE[channel_colorspace(channel)]

# Column x per node kind (§6 suggested layout); samplers stack on y.
_LAYOUT_COLS = {
    "texturesampler": -600.0,
    "bumpmap": -300.0,
    "displacement": -300.0,
    "standardmaterial": 0.0,
    "output": 300.0,
}
_LAYOUT_ROW_STEP = 220.0


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


def _sampler(path, colorspace):
    return {
        "$type": "#" + _RS_CORE + "texturesampler",
        "#<" + _RS_CORE + "texturesampler.tex0/path": path,
        "#<" + _RS_CORE + "texturesampler.tex0/colorspace": colorspace,
    }


def build_description(folder, tex_set):
    """(main_desc, ao_desc | None) — pure dict assembly per §2/§2b and the
    Global Constraints wiring rules. The engine already enforces the
    channel precedences (glossiness never coexists with roughness/metalness,
    normal is a single resolved key), so each key is written at most once."""
    channels = tex_set.get("channels") or {}

    def path(channel):
        return os.path.join(folder, channels[channel])

    sm = "#<" + _RS_CORE + "standardmaterial."
    material = {"$type": "#" + _RS_CORE + "standardmaterial"}
    if "basecolor" in channels:
        material[sm + "base_color"] = _sampler(path("basecolor"), _rs_colorspace("basecolor"))
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
    ao_desc = _sampler(path("ao"), _rs_colorspace("ao")) if "ao" in channels else None
    return desc, ao_desc


def _layout_nodes(graph):
    """GraphDescription assigns no positions (§6) — set xpos/ypos explicitly
    so the graph never stacks at (0,0). Nodes located by assetid; rows are
    keyed by COLUMN (x value), not kind — bumpmap and displacement share
    column -300.0, so keying by kind would stack them at the same (x,y)
    whenever a set has both normal and height."""
    rows = {}
    with graph.BeginTransaction() as tr:
        for node in graph.GetViewRoot().GetInnerNodes(
                mask=maxon.NODE_KIND.NODE, includeThis=False):
            asset_id = str(node.GetValue(_ASSETID_ATTR) or "")
            kind = asset_id.rsplit(".", 1)[-1]
            col = _LAYOUT_COLS.get(kind, 0.0)
            index = rows.get(col, 0)
            rows[col] = index + 1
            node.SetValue("net.maxon.node.base.xpos", maxon.Float(col))
            node.SetValue("net.maxon.node.base.ypos",
                          maxon.Float(index * _LAYOUT_ROW_STEP))
        tr.Commit()


def create_material_for_set(doc, folder, tex_set, name):
    """Build ONE RS Standard material for ``tex_set`` (engine shape from
    ``matwire.scan_texture_sets``). ``name`` arrives already deduped. The
    caller owns the undo block; any failure after insertion removes the
    material (§8c) and is reported, never raised."""
    mat = None
    try:
        desc, ao_desc = build_description(folder, tex_set)
        mat = c4d.BaseMaterial(c4d.Mmaterial)
        mat.SetName(name)
        doc.InsertMaterial(mat)
        doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, mat)   # AFTER insert (NEWOBJ contract)
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)   # anchor BEFORE touching the graph (§8b)
        graph = maxon.GraphDescription.GetGraph(
            mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)
        maxon.GraphDescription.ApplyDescription(graph, desc)
        if ao_desc is not None:
            maxon.GraphDescription.ApplyDescription(graph, ao_desc)  # isolated (§5)
        _layout_nodes(graph)
        return {"ok": True, "material_name": name, "error": None}
    except Exception as exc:
        if mat is not None:
            try:
                # NEWOBJ/CHANGE were already recorded inside the batch's open
                # undo bracket above — a bare Remove() here would leave that
                # bracket unbalanced (redo could resurrect the half-built
                # material). Balance it with a DELETE record first, matching
                # the repo convention (fixes.py:258, scene_tools.py:1475).
                doc.AddUndo(c4d.UNDOTYPE_DELETE, mat)
                mat.Remove()
            except Exception:
                pass
        return {"ok": False, "material_name": name, "error": str(exc)}
