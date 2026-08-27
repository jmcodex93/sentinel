# -*- coding: utf-8 -*-
"""Material Graph — pure engine (v1.38), no ``import c4d``/``import maxon``.

Backs QC check #13 "RS Colorspace" and the Tools "Clean Dead Nodes" button
(see ``docs/superpowers/specs/2026-08-25-material-graph-qc-design.md``).
Two design collapses, both settled by the live spike
(``docs/research/2026-08-27-matgraph-spike.md``), that keep this module
simpler than the spec's first draft:

- **``auto`` always resolves to Info, never to a fixable violation.** The
  spike measured the RS ``tex0/colorspace`` port live: the "auto" state IS
  the port having no value at all (``GetPortValue()`` returns ``None``),
  and there is no readable "what auto resolved to" port anywhere on the
  sampler. The brainstorm's decision 3 ("auto that resolves badly is a
  mismatch") is therefore unreachable by construction — ``assigned=None``
  is unconditionally ``auto_unverified``, and no branch tries to guess
  what auto would have picked.
- **No enumeration of the RS colorspace vocabulary.** The spike also found
  that writing any string outside ``RS_INPUT_COLORSPACE_SRGB``/``RAW`` to
  that port crashes C4D outright (``EXC_BAD_ACCESS`` in
  ``redshift4c4d.xlib``, measured). Rather than maintain a combo of known
  values, this module treats exactly those two strings as the known
  vocabulary and anything else (a custom OCIO name, whatever) as
  ``foreign_cs`` — Info, never a Fix target. The Fix writer (Task 3) must
  mirror this: it may only ever WRITE ``CS_SRGB``/``CS_RAW``.

Channel inference is a two-signal system per the design doc's decision 4:
filename (delegated to ``sentinel.matwire`` — the single source of the
channel-suffix tables, never duplicated here) and BRDF/utility destination
port (this module's own ``PORT_TO_CHANNEL`` table, the inverse of
``matwire_c4d``'s channel->port tables). One signal present -> use it;
both present and equal -> higher-confidence agreement; both present and
different -> ``conflict``, reported but never used to pick a channel (no
guessing which signal is right).

``find_dead_nodes`` is a plain reachability BFS (ancestors of roots ∪
sinks are alive) — the walking/tracing through a live C4D node graph
(``PASS_THROUGH_ASSETS``-aware) is the adapter's job (``matgraph_c4d.py``,
a later task), not this module's.
"""

from collections import deque

from sentinel.matwire import (
    _CHANNEL_RES,
    _match_channel,
    _normalize,
    _strip_trailing_res,
    channel_colorspace,
)

#: The only two colorspace strings this codebase ever writes to the RS
#: ``tex0/colorspace`` port. Measured live (spike, Q1): any other string
#: written there crashes C4D. The Fix writer (Task 3) must only ever emit
#: one of these two constants — never a value derived dynamically.
CS_SRGB = "RS_INPUT_COLORSPACE_SRGB"
CS_RAW = "RS_INPUT_COLORSPACE_RAW"

#: engine channel_colorspace() answer ("srgb"/"raw") -> the RS constant.
#: Mirrors the same-shaped table in matwire_c4d.py — the DECISION of which
#: channel is which colorspace still lives only in
#: ``matwire.channel_colorspace``; this is just the format translation.
_CS_BY_NAME = {"srgb": CS_SRGB, "raw": CS_RAW}

#: BRDF/utility DESTINATION port id -> canonical matwire channel. This is
#: the INVERSE of matwire_c4d.py's channel->port tables (``BRDF_PORTS``
#: for both material types), plus the two single-owner utility ports a
#: texture sampler connects to directly for normal maps and displacement
#: (``bumpmap.input``, ``displacement.texmap`` — there is exactly one
#: node type of each, so no BRDF-name qualification is needed to
#: disambiguate them the way e.g. "roughness" would need one).
#:
#: Deliberately does NOT include the BRDF's own bump-input ports
#: (``geometry_normal``/``bump_input``): a normal-map sampler never
#: connects to those directly, only to ``bumpmap.input`` — the bumpmap
#: node's OWN output is what feeds the BRDF. Since ``bumpmap.input`` is
#: already a recognized destination, a trace that walks through
#: ``PASS_THROUGH_ASSETS`` (the adapter's job) stops there and never needs
#: to continue on to the BRDF's bump port.
#:
#: Matching is by LONGEST SUFFIX against a caller-supplied ``dest_port``
#: string (full or partial id) — see ``_port_channel`` — so this table
#: intentionally uses bare port names, no ``com.redshift3d...`` prefix.
PORT_TO_CHANNEL = {
    # basecolor — identical port name on both BRDFs.
    "base_color": "basecolor",
    # roughness — different names per BRDF, also the destination a
    # glossiness map lands on (inverted for openpbr, native bool for
    # standard) — see the design doc's "conflict" case.
    "specular_roughness": "roughness",
    "refl_roughness": "roughness",
    # metalness — different names per BRDF.
    "base_metalness": "metalness",
    "metalness": "metalness",
    # specular color.
    "specular_color": "specular",
    "refl_color": "specular",
    # opacity.
    "geometry_opacity": "opacity",
    "opacity_color": "opacity",
    # emission — identical port name on both BRDFs.
    "emission_color": "emission",
    # single-owner utility ports (no BRDF ambiguity).
    "bumpmap.input": "normal",
    "displacement.texmap": "height",
}

#: Asset-id SUBSTRINGS a destination trace may walk THROUGH (the adapter's
#: job) — the matwire-interposed utilities: identity Color Correct on
#: basecolor, an (unused-by-matwire-today-but-possible) Ramp, the
#: glossiness Invert, the AO Color Layer, and Bump. An unknown asset along
#: the way stops the trace with no port signal — never a guess.
PASS_THROUGH_ASSETS = (
    "rscolorcorrection",
    "rsramp",
    "rsmathinv",
    "rscolorlayer",
    "bumpmap",
)


def _name_channel(filename):
    """Channel inferred from a filename alone, via matwire's own stem
    pipeline — extension stripped, separators normalized, a trailing
    resolution token stripped, then matched against matwire's channel
    table. Never duplicates that table; reuses it verbatim."""
    if not filename:
        return None
    base = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    norm_stem, _trailing_px = _strip_trailing_res(_normalize(stem))
    channel, _root = _match_channel(norm_stem, _CHANNEL_RES)
    return channel


def _port_channel(dest_port):
    """Channel inferred from a destination port id, by LONGEST matching
    suffix in ``PORT_TO_CHANNEL`` (so ``...openpbrmaterial.base_metalness``
    picks the 14-char ``base_metalness`` key over the 9-char ``metalness``
    key, which is also technically a suffix of it)."""
    if not dest_port:
        return None
    best_key = None
    for key in PORT_TO_CHANNEL:
        if dest_port.endswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return PORT_TO_CHANNEL.get(best_key)


def infer_channel(filename, dest_port):
    """``(channel, source)`` combining the two signals per the design
    doc's decision 4. ``source`` is one of ``"name"``, ``"port"``,
    ``"both"`` (both signals agree), ``"conflict"`` (both present, differ
    — channel is ``None``, callers must not guess which signal wins), or
    ``None`` (neither signal fired — channel is ``None``, silent)."""
    name_channel = _name_channel(filename)
    port_channel = _port_channel(dest_port)
    if name_channel and port_channel:
        if name_channel == port_channel:
            return name_channel, "both"
        return None, "conflict"
    if name_channel:
        return name_channel, "name"
    if port_channel:
        return port_channel, "port"
    return None, None


def _expected_colorspace(channel):
    return _CS_BY_NAME[channel_colorspace(channel)]


def audit_colorspaces(entries):
    """``list[verdict]`` — one verdict per entry, entry + ``{"channel",
    "source", "expected", "verdict"}``. Verdict semantics (exact order
    matters — see the design doc + module docstring):

    1. ``assigned is None`` (auto) -> ``auto_unverified``, unconditionally
       — even when the channel IS known by name/port. Never a mismatch.
    2. ``assigned`` not in the known RS vocabulary -> ``foreign_cs``.
    3. the two inference signals disagree -> ``conflict`` — no
       channel-based judgment is made either way.
    4. no signal fired at all -> ``unknown`` (silent — no false
       positives by design).
    5. otherwise -> ``ok`` if ``assigned`` matches what the channel
       expects, else ``mismatch`` (the only Fix-able verdict; carries
       ``expected``).
    """
    verdicts = []
    for entry in entries or []:
        assigned = entry.get("assigned")
        filename = entry.get("file")
        dest_port = entry.get("dest_port")
        channel, source = infer_channel(filename, dest_port)
        out = dict(entry)
        out["channel"] = channel
        out["source"] = source
        out["expected"] = None
        if assigned is None:
            out["verdict"] = "auto_unverified"
        elif assigned not in (CS_SRGB, CS_RAW):
            out["verdict"] = "foreign_cs"
        elif source == "conflict":
            out["verdict"] = "conflict"
        elif channel is None:
            out["verdict"] = "unknown"
        else:
            expected = _expected_colorspace(channel)
            out["expected"] = expected
            out["verdict"] = "ok" if assigned == expected else "mismatch"
        verdicts.append(out)
    return verdicts


def find_dead_nodes(node_ids, edges, root_ids, sink_ids):
    """Set of node ids with NO path to any root or sink. ``edges`` are
    ``(from_id, to_id)`` pairs in data-flow direction. Alive = every
    ancestor of roots ∪ sinks (including the roots/sinks themselves) —
    a single reversed-adjacency BFS, O(nodes + edges).

    "Ancestor" here means: following edges FORWARD, there is a path from
    that node to a root or a sink. To find every such node from the
    roots/sinks without walking the whole graph per node, the BFS walks
    BACKWARD from the seed set over a reversed adjacency map (for edge
    ``(u, v)``, ``v``'s reverse-neighbor is ``u``)."""
    node_ids = set(node_ids or ())
    seed = set(root_ids or ()) | set(sink_ids or ())

    reverse_adj = {}
    for u, v in edges or ():
        reverse_adj.setdefault(v, []).append(u)

    alive = set(seed)
    queue = deque(seed)
    while queue:
        current = queue.popleft()
        for pred in reverse_adj.get(current, ()):
            if pred not in alive:
                alive.add(pred)
                queue.append(pred)

    return node_ids - alive
