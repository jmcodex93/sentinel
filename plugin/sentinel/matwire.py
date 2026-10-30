# -*- coding: utf-8 -*-
"""Material-from-folder recognition engine (v1.33) — PURE, no ``import c4d``.

Recognizes PBR texture sets from filenames (suffix tables cross-checked
against three live market implementations — see
docs/research/2026-07-29-matwire-implementations.md; facts only, no code:
those plugins are study-only). Grouping = filename root minus the channel
suffix minus the resolution token (``split_res_token``, v1.18); a file with
NO res token is the original and outranks tokened proxies (Shrink lesson).
Precedences: Normal GL > generic > DX (DX-only sets ``normal_flipy`` for
the writer's ``bumpmap.flipy``); Spec/Gloss are wired only when the set has
neither Roughness nor Metalness (modern PBR wins). The colorspace table is
the SINGLE source both the preview and the writer consume.
"""

import os
import re

from sentinel import udim
from sentinel.assets import split_res_token

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr",
     ".tga", ".bmp", ".webp", ".tx"})

# Ordered: more specific channels FIRST (normal_gl/normal_dx before normal;
# packed ORM detected before anything else could half-match).
_CHANNEL_VARIANTS = (
    ("packed_orm", ("orm", "arm")),
    # Coat BEFORE roughness/normal/basecolor (v1.42): "Coat_roughness"
    # must not be claimed by roughness with a "…_Coat" root.
    ("coat_weight", ("coat_weight", "clearcoat_weight")),
    ("coat_color", ("coat_color", "clearcoat_color")),
    ("coat_roughness", ("coat_roughness", "clearcoat_roughness")),
    ("coat_normal", ("coat_normal", "clearcoat_normal")),
    ("normal_gl", ("normalgl", "normal_gl", "nor_gl", "normalopengl",
                   "normal_opengl")),
    ("normal_dx", ("normaldx", "normal_dx", "nrm_dx", "dx_normal", "nor_dx",
                   "normal_directx")),
    ("normal", ("normal", "nrm", "nor", "norm", "nml", "nrml", "nmap")),
    ("basecolor", ("basecolor", "base_color", "albedo", "diffuse", "col",
                   "diff", "base", "dif")),
    # OpenPBR names (Painter's OpenPBR export): "Specular_roughness" and
    # "Base_metalness" would otherwise split the set at "…_Specular"/"…_Base".
    ("roughness", ("roughness", "rough", "rgh", "specular_roughness")),
    ("metalness", ("metalness", "metallic", "metal", "met", "mtl",
                   "base_metalness")),
    ("height", ("height", "displacement", "disp", "dsp", "depth")),
    ("ao", ("ambientocclusion", "ambient_occlusion", "occlusion", "ao", "occ")),
    ("opacity", ("opacity", "alpha", "cutout", "transparency")),
    ("emission", ("emission", "emissive", "emit")),
    ("specular", ("specular", "spec")),
    ("glossiness", ("glossiness", "gloss")),
)

#: Every channel key the tables know — the valid key set for
#: project-ruleset ``matwire_suffixes`` extensions (v1.32.1).
CANONICAL_CHANNELS = frozenset(channel for channel, _ in _CHANNEL_VARIANTS)

_SRGB_CHANNELS = frozenset({"basecolor", "emission", "coat_color"})


# Separator REQUIRED before the variant (self-caught plan bug: an optional
# separator lets glued stems false-positive — "protocol" would end-match
# "col" → basecolor). A file named exactly like a variant ("albedo.png",
# root empty) is legal: rootless files group under ``default_root``.
def _compile_channel_res(extra_suffixes=None):
    extra = extra_suffixes or {}
    table = []
    for channel, variants in _CHANNEL_VARIANTS:
        merged = tuple(variants) + tuple(extra.get(channel) or ())
        table.append((channel, re.compile(
            r"^(?P<root>.*?)(?:^|_)(?:"
            + "|".join(re.escape(v) for v in merged)
            + r")(?:_?map)?$", re.IGNORECASE)))
    return table


# Module-cached compiled defaults — the hot path (no extras) never
# recompiles; a merged copy is built per call only when extras are present.
_CHANNEL_RES = _compile_channel_res()


def validate_extra_suffixes(raw):
    """``(valid, rejected)`` for a ruleset ``matwire_suffixes`` dict.
    Unknown channel keys and non-str-list values are rejected BY KEY NAME
    (the rest applies — per-key ruleset style); suffixes are normalized
    lowercase/stripped and empty entries dropped (a key left with no
    usable suffixes is rejected). Non-dict input yields ``({}, [])`` —
    the type-level rejection is the rules layer's job.

    KNOWN LIMIT (pinned judgment, review M8 v1.32.1): a valid extra suffix
    that COLLIDES with an embedded suffix of ANOTHER channel loses to
    ``_CHANNEL_VARIANTS`` table order — the table is scanned most-specific
    first and the FIRST match wins, so ``{"metalness": ["col"]}`` will NOT
    claim ``rock_col.png`` (``basecolor`` sits above ``metalness`` and
    already owns ``col``). Extras EXTEND the tables; they never re-order
    or override them."""
    valid = {}
    rejected = []
    if not isinstance(raw, dict):
        return valid, rejected
    for key, value in raw.items():
        key_name = str(key)
        if key_name not in CANONICAL_CHANNELS:
            rejected.append(key_name)
            continue
        if not isinstance(value, (list, tuple)) or not all(
                isinstance(item, str) for item in value):
            rejected.append(key_name)
            continue
        suffixes = [item.strip().lower() for item in value if item.strip()]
        if not suffixes:
            rejected.append(key_name)
            continue
        valid[key_name] = suffixes
    return valid, rejected


def channel_colorspace(channel):
    return "srgb" if channel in _SRGB_CHANNELS else "raw"


def _normalize(stem):
    """Collapse separators (space, ``-``, ``.``) to ``_`` — case is
    PRESERVED (channel matching is case-insensitive, see ``_CHANNEL_RES``,
    but the captured ``root`` must keep the artist's original casing for
    the set name, e.g. ``plaster_A`` must not become ``plaster_a``)."""
    return re.sub(r"[\s\-.]+", "_", stem.strip())


#: OCIO colourspace names Painter's ``$colorSpace`` export token appends
#: (``LOK_body_Base_color_sRGB Encoded Rec.709 (sRGB)_1001.png``, v1.42).
#: Stripped for CHANNEL MATCHING only: the sampler's colourspace stays
#: ``channel_colorspace`` (studio convention, and only SRGB/RAW are ever
#: written). Stripped BEFORE ``_normalize`` — these names carry spaces, dots
#: and parentheses that normalizing would scramble. Longest first.
OCIO_SUFFIXES = (
    "Utility - sRGB - Texture", "sRGB Encoded Rec.709 (sRGB)",
    "Utility - Linear - sRGB", "Linear Rec.709 (sRGB)", "Utility - Raw",
    "sRGB - Texture", "ACES - ACEScg", "ACES2065-1", "ACEScg", "Raw",
)
_OCIO_SUFFIX_RE = re.compile(
    r"_(?:" + "|".join(re.escape(s) for s in OCIO_SUFFIXES) + r")$",
    re.IGNORECASE)


def strip_colorspace_suffix(stem):
    return _OCIO_SUFFIX_RE.sub("", str(stem))


def match_stem(stem, table=None):
    """``(channel, root, trailing_px)`` for a filename stem with no
    extension and no tile — THE stem pipeline, shared by
    ``scan_texture_sets`` and ``matgraph._name_channel`` (v1.42): OCIO
    suffix off, separators normalized, a trailing resolution token off, then
    the channel table (``_CHANNEL_RES`` unless a merged ``table`` is given).
    ``(None, None, None)`` when no channel matches."""
    norm_stem, trailing_px = _strip_trailing_res(
        _normalize(strip_colorspace_suffix(stem)))
    channel, root = _match_channel(norm_stem, table or _CHANNEL_RES)
    if channel is None:
        return None, None, None
    return channel, root, trailing_px


def _match_channel(norm_stem, table):
    """(channel, root) for the FIRST (most specific) matching channel in
    ``table``. ``root`` may be "" (a file named exactly "albedo.png") —
    the caller groups those under ``default_root``."""
    for channel, rx in table:
        m = rx.match(norm_stem)
        if m:
            return channel, m.group("root").rstrip("_")
    return None, None


def _root_and_px(root):
    """Split a residual resolution token off the grouping root.
    No token → px None (treated as HIGHEST — Shrink-lesson originals)."""
    try:
        prefix, px, suffix = split_res_token(root)
    except Exception:
        return root, None
    if px is None:
        return root, None
    merged = (prefix.rstrip("_-. ") + ("_" + suffix.lstrip("_-. ") if suffix.strip("_-. ") else ""))
    return merged.rstrip("_"), px


def _rank(px):
    """Sort key where no-token (None) outranks every explicit px."""
    return float("inf") if px is None else float(px)


def _strip_trailing_res(norm_stem):
    """Strip a TRAILING resolution token off ``norm_stem`` (the Poliigon
    pattern — ``plaster_BaseColor_8k``, token AFTER the channel suffix,
    which the end-anchored channel regex can't see past). Uses
    ``split_res_token``: a match only counts as trailing when its
    ``suffix`` is empty/separator-only (a token in the MIDDLE, like the
    pre-token ``plaster_A_4k_BaseColor`` case, leaves a non-empty suffix
    and is left for ``_root_and_px`` to handle on the extracted root
    instead). Returns ``(stem, px)`` — ``(norm_stem, None)`` when there is
    no trailing token."""
    try:
        result = split_res_token(norm_stem)
    except Exception:
        return norm_stem, None
    if result is None:
        return norm_stem, None
    prefix, px, suffix = result
    if suffix.strip("_-. "):
        return norm_stem, None
    return prefix.rstrip("_-. "), px


def _dir_px(relpath):
    """Resolution rank read from the DIRECTORY segments of a scan-relative
    path (review I1, v1.32.1). The recursive lister (v1.32.1) delivers real
    packs as ``1K/albedo.png`` / ``4K/albedo.png``: the filenames are
    IDENTICAL, so ranking from the name alone collapsed a multi-res pack
    into one arbitrary winner (whatever ``sorted()`` put first —
    ``16K`` < ``1K`` lexically), contradicting the engine's "highest wins"
    policy. Walk the segments and let the DEEPEST one carrying a token win
    (``Textures/4K/rock/…``); the caller consults this ONLY when the
    filename itself yields no token, so filename tokens keep priority. A
    flat path has no segments → ``None`` → byte-parity with v1.32."""
    parts = str(relpath).replace("\\", "/").split("/")[:-1]
    px = None
    for part in parts:
        try:
            result = split_res_token(part)
        except Exception:
            result = None
        if result is not None and result[1] is not None:
            px = result[1]
    return px


def orm_contributions(channels):
    """Which BRDF inputs a set's packed ORM/ARM ACTUALLY feeds — the single
    source for both the preview note (``preview_payload``) and the writer's
    connect pairs (``matwire_c4d.build_orm_plan``), so the preview can never
    promise a wiring the writer won't make (review I2). Type-neutral: the
    ports themselves are ``matwire_c4d.BRDF_PORTS``' concern, not this
    function's — this is only the RULE, which holds for both BRDF types.

    Dedicated maps win per output: ``outg`` -> the roughness port only when
    the set has neither a dedicated roughness nor a glossiness map (the
    roughness port is already taken when one exists — natively via
    Standard's ``refl_isglossiness`` bool, or via the interposed
    ``rsmathinv`` under OpenPBR); ``outb`` -> the metalness port only
    without a dedicated metalness map; ``outr`` (AO) is NEVER wired
    (existing AO policy). An empty list means the ORM lands as a bare
    unconnected sampler (visible, never silently dropped)."""
    channels = channels or {}
    if "packed_orm" not in channels:
        return []
    out = []
    if "roughness" not in channels and "glossiness" not in channels:
        out.append("roughness")
    if "metalness" not in channels:
        out.append("metalness")
    return out


def ao_destination(channels, multiply_ao):
    """Where a set's AO map ACTUALLY lands — the single source for both the
    writer's graph and the preview's AO row (same discipline as
    ``orm_contributions``, review I2): the row the artist reads can never
    promise a wiring the writer won't make.

    ``None`` when the set has no AO at all. ``"base_color_multiply"`` when
    the opt-in ``multiply_ao`` is on AND the set has a basecolor to multiply
    INTO (an AO-only set has no target: it would leave a dangling color
    layer, so the AO stays loose). Otherwise ``"unconnected"`` — the v1.32
    behavior: a visible, unwired sampler (recognized files never vanish
    silently)."""
    channels = channels or {}
    if "ao" not in channels:
        return None
    if multiply_ao and "basecolor" in channels:
        return "base_color_multiply"
    return "unconnected"


def gloss_destination(channels, material):
    """Where a set's GLOSSINESS map lands — the single source for both the
    writer's graph and the preview's row (same discipline as
    ``ao_destination``/``orm_contributions``).

    ``None`` when the set has no glossiness. On Standard the map goes
    straight to the roughness port and the native ``refl_isglossiness``
    bool flips the interpretation — no extra node. OpenPBR has NO such port
    (measured live: ``specular_isglossiness`` is absent), so the only
    correct wiring interposes an invert node."""
    channels = channels or {}
    if "glossiness" not in channels:
        return None
    return ("roughness_isglossiness" if material == "standard"
            else "roughness_inverted")


#: Displacement remap per height convention — ``(newrange_min,
#: newrange_max)`` written on the RS Displacement node. Integer maps follow
#: the dominant convention (Blender Midlevel 0.5, ZBrush/3ds Max 50% grey,
#: Octane mid level 0.5): mid-grey = no displacement. A float map is judged
#: by its pixels (``float_height_convention``): zero-centred bakes
#: (ZBrush/Mudbox) keep Redshift's own 0..1 (measured: a fresh node reads
#: 0..1), a float copy of a mid-grey map is centred like an integer one, and
#: anything the pixels can't settle keeps 0..1 and is flagged "unverified".
HEIGHT_RANGES = {"centered": (-0.5, 0.5), "zero_based": (0.0, 1.0),
                 "unverified": (0.0, 1.0)}

#: A float map wholly inside [0, 1] reads as mid-grey = flat when its mean
#: is within this of 0.5. Flat area dominates a height map, so a mid-grey
#: map's mean sits near 0.5 and a black-flat map's mean is coverage ×
#: average relief, well below: the black-background dome map of
#: docs/research/2026-10-23-matwire-height-only-displacement.md measures
#: 0.35, outside the ±0.1 window.
MIDGREY_MEAN_TOLERANCE = 0.1

_FLOAT_EXTENSIONS = frozenset({".exr", ".hdr"})


def height_is_float(filename, height_float=None):
    """True for a float height: .exr/.hdr by extension, or a file whose
    header the caller probed as float (``height_float``, e.g. a 32-bit
    float .tif via ``imagemeta``)."""
    ext = os.path.splitext(str(filename or ""))[1].lower()
    return ext in _FLOAT_EXTENSIONS or bool(height_float)


def height_stats(values):
    """``{"min", "max", "mean", "count"}`` of sampled height values, or
    ``None`` when there are none — the pure reduction behind the C4D
    adapter's pixel sampling (``matwire_c4d.height_float_stats``)."""
    count = 0
    total = 0.0
    low = high = None
    for value in values or ():
        value = float(value)
        count += 1
        total += value
        if low is None or value < low:
            low = value
        if high is None or value > high:
            high = value
    if not count:
        return None
    return {"min": low, "max": high, "mean": total / count, "count": count}


def float_height_convention(stats):
    """Convention of a FLOAT height map from its pixel stats.

    Any value below zero → ``"zero_based"``: the map is zero-centred, so
    Redshift's 0..1 already leaves zero flat. Wholly inside [0, 1] with a
    mean within ``MIDGREY_MEAN_TOLERANCE`` of 0.5 → ``"centered"``: a float
    copy of a mid-grey map, remapped like an integer one. Anything else,
    or no readable pixels → ``"unverified"``: keeps 0..1 (the float
    default) and the preview says the convention wasn't confirmed."""
    if not stats:
        return "unverified"
    low, high, mean = stats.get("min"), stats.get("max"), stats.get("mean")
    if low is None or high is None or mean is None:
        return "unverified"
    if low < 0:
        return "zero_based"
    if high <= 1 and abs(mean - 0.5) <= MIDGREY_MEAN_TOLERANCE:
        return "centered"
    return "unverified"


def height_range(channels, height_float=None, height_stats=None):
    """Which ``HEIGHT_RANGES`` convention a set's height map gets — the
    single source for both the preview's height row and the writer's
    Displacement node (same discipline as ``ao_destination``).

    ``None`` when the set has no height. A float map (``height_is_float``)
    is decided by ``float_height_convention`` on ``height_stats``, the
    pixel sample the ops layer took. Everything else — 8/16-bit
    png/jpg/tif/tga, and a file whose header couldn't be read — is
    ``"centered"``."""
    channels = channels or {}
    filename = channels.get("height")
    if not filename:
        return None
    if height_is_float(filename, height_float):
        return float_height_convention(height_stats)
    return "centered"


_COAT_CHANNELS = ("coat_weight", "coat_color", "coat_roughness", "coat_normal")

#: Written on the BRDF when a set has coat maps but no weight map (v1.42):
#: both BRDFs are born with coat_weight = 0 (measured), so the coat would
#: ship invisible — the same trap as emission (BRDF_EMISSION_AMOUNT).
COAT_WEIGHT_CONSTANT = 1.0


def coat_weight_source(channels):
    """Where a set's coat weight comes from — the single source for both the
    writer and the preview note: ``"map"`` (a coat_weight texture),
    ``"constant"`` (coat maps without one → ``COAT_WEIGHT_CONSTANT``), or
    ``None`` (no coat)."""
    channels = channels or {}
    if "coat_weight" in channels:
        return "map"
    if any(channel in channels for channel in _COAT_CHANNELS):
        return "constant"
    return None


def tile_mismatch(tex_set):
    """``{channel: [tiles]}`` — tiles that OTHER tiled channels of the set
    have and this one lacks (Redshift renders them black, silently —
    measured). ``{}`` when the tiled channels agree or fewer than two are
    tiled. A gap shared by every channel is not reported: it is a tile the
    set doesn't use (LOK's ``cuerpo`` skips 1005, where ``grip`` lives)."""
    tiles = (tex_set or {}).get("tiles") or {}
    if len(tiles) < 2:
        return {}
    union = set()
    for row in tiles.values():
        union.update(row)
    out = {}
    for channel, row in tiles.items():
        missing = sorted(union - set(row))
        if missing:
            out[channel] = missing
    return out


def scan_texture_sets(filenames, default_root="material", extra_suffixes=None):
    """``default_root`` names the set for ROOTLESS files ("albedo.png") —
    the caller passes the folder's basename so bare-channel packs group
    naturally.

    ``extra_suffixes`` (validated ``{channel: [suffix, ...]}``) EXTENDS
    the embedded variant lists for matching — never replaces them.

    Set identity is CASE-INSENSITIVE (``root_key.lower()``) so
    ``Rock_Cliff_BaseColor.jpg`` and ``rock_cliff_AO.jpg`` land in one
    set — the DISPLAY name keeps the first-seen casing.

    ``leftover_hints`` maps each ``no_channel`` file to its normalized
    stem (lowercase, separators collapsed to ``_``) — the ops layer
    prefix-matches those against set names (``assign_leftovers``).

    Tiled files (v1.42, ``udim.split_tile``: Mari ``rock_diffuse.1001.exr``,
    Painter ``…_1001.png``, Mudbox ``…_u1_v1.png``) collapse into ONE entry
    per (folder, base, scheme, separator, extension) whose filename is the
    Redshift PATTERN (``rock_diffuse.<UDIM>.exr``), so ``channels`` keeps its
    ``{channel: relpath}`` shape and the writer needs no tile logic. Each set
    gains ``tiles`` = ``{channel: [tile, ...]}`` for its tiled channels. At
    an equal resolution rank a tiled entry beats an untiled one for the same
    channel. Known risk (spec): an image sequence numbered from 1001 reads as
    UDIM — the preview shows the tile count, so it is visible."""
    table = (_compile_channel_res(extra_suffixes) if extra_suffixes
             else _CHANNEL_RES)
    sets = {}
    order = []
    display_names = {}
    ignored = []
    leftover_hints = {}

    # Pass 1: extension filter + tile families. Each scan entry is
    # (filename-or-pattern, stem-to-match, is_tiled), first-seen order.
    items = []
    tiled = {}
    for filename in filenames or []:
        rel = str(filename)
        base = os.path.basename(rel)
        stem, ext = os.path.splitext(base)
        if ext.lower() not in IMAGE_EXTENSIONS:
            ignored.append((filename, "bad_extension"))
            continue
        tile = udim.split_tile(stem)
        if tile is None:
            items.append((filename, stem, None))
            continue
        folder = rel[:len(rel) - len(base)]
        key = (folder.lower(), tile["base"].lower(), tile["scheme"],
               tile["sep"], ext.lower())
        group = tiled.get(key)
        if group is None:
            pattern = folder + udim.pattern_name(
                tile["base"], tile["scheme"], tile["sep"], ext)
            group = tiled[key] = {"pattern": pattern, "tiles": set(),
                                  "base": tile["base"], "scheme": tile["scheme"]}
        group["tiles"].add(tile["tile"])
        items.append((filename, stem, key))
    # A UDIM family whose only tile is 1024 is a pixel-size suffix
    # (``brick_albedo_1024.jpg``), not tile 1024: read it as untiled, as
    # v1.41 did. Real ``<UDIM>`` paths elsewhere still accept 1024.
    for key in [k for k, g in tiled.items()
                if g["scheme"] == udim.UDIM and g["tiles"] == {1024}]:
        del tiled[key]
    scan_entries = []
    seen = set()
    for filename, stem, key in items:
        group = tiled.get(key) if key is not None else None
        if group is None:
            scan_entries.append((filename, stem, False))
        elif key not in seen:
            seen.add(key)
            scan_entries.append((group["pattern"], group["base"], True))
    tiles_of = {g["pattern"]: sorted(g["tiles"]) for g in tiled.values()}

    for filename, stem, is_tiled in scan_entries:
        channel, root, trailing_px = match_stem(stem, table)
        if channel is None:
            ignored.append((filename, "no_channel"))
            leftover_hints[filename] = _normalize(
                strip_colorspace_suffix(stem)).lower()
            continue
        root_key, root_px = _root_and_px(root)
        if not root_key:
            root_key = str(default_root) or "material"
        px = trailing_px if trailing_px is not None else root_px
        if px is None:
            # No token in the FILENAME: fall back to the subfolder the file
            # came from (`4K/albedo.png` — review I1). Filename tokens win.
            px = _dir_px(filename)
        group_key = root_key.lower()
        if group_key not in sets:
            sets[group_key] = {"candidates": {}, "ignored": []}
            order.append(group_key)
            display_names[group_key] = root_key
        sets[group_key]["candidates"].setdefault(channel, []).append(
            (filename, px, is_tiled))

    out_sets = []
    for group_key in order:
        root_key = display_names[group_key]
        data = sets[group_key]
        channels = {}
        set_ignored = list(data["ignored"])
        for channel, entries in data["candidates"].items():
            # Highest resolution first; at an equal rank a tiled entry wins
            # (sorted is stable, so untiled ties keep first-seen order).
            ranked = sorted(entries, key=lambda e: (-_rank(e[1]), not e[2]))
            best_rank = _rank(ranked[0][1])
            channels[channel] = ranked[0][0]
            for filename, px, _tiled in ranked[1:]:
                reason = ("duplicate_channel"
                          if _rank(px) == best_rank else "lower_resolution")
                set_ignored.append((filename, reason))

        # Normal precedence: GL > generic > DX; DX-only flips Y.
        normal_flipy = False
        chosen_normal = None
        for key, flipy in (("normal_gl", False), ("normal", False),
                           ("normal_dx", True)):
            if key in channels:
                if chosen_normal is None:
                    chosen_normal = channels[key]
                    normal_flipy = flipy
                else:
                    set_ignored.append((channels[key], "dx_superseded"))
                channels.pop(key)
        if chosen_normal is not None:
            channels["normal"] = chosen_normal

        # Spec/Gloss precedence: modern PBR wins.
        if ("roughness" in channels or "metalness" in channels):
            for legacy in ("specular", "glossiness"):
                if legacy in channels:
                    set_ignored.append((channels.pop(legacy), "pbr_wins"))

        out_sets.append({
            "name": root_key,
            "channels": channels,
            "normal_flipy": normal_flipy,
            "ignored": set_ignored,
            "tiles": {ch: tiles_of[f] for ch, f in channels.items()
                      if f in tiles_of},
        })

    return {"sets": out_sets, "ignored": ignored,
            "leftover_hints": leftover_hints, "pattern_tiles": tiles_of}


def assign_leftovers(hints, set_names):
    """Pure prefix-match assignment of ``no_channel`` leftovers to sets
    (Task 4 ops consume it). A hint matches a set when the set's
    lowercased name — exactly, or followed by a ``_`` separator (hints
    already have separators collapsed to ``_``) — prefixes the hint;
    the LONGEST matching name wins; no match → ``None``."""
    out = []
    names = [str(n) for n in set_names or []]
    for filename, hint in (hints or {}).items():
        h = str(hint).lower()
        best = None
        for name in names:
            low = name.lower()
            if (h == low or h.startswith(low + "_")) and (
                    best is None or len(name) > len(best)):
                best = name
        out.append({"file": filename, "set": best})
    return out


def preview_payload(scan_result, existing_names, multiply_ao=False, folder=""):
    """Shape a ``scan_texture_sets`` result for the SPA preview: channel
    rows annotated with their colorspace (single source:
    ``channel_colorspace``), tuples flattened to JSON-friendly lists, and
    default material names deduped against ``existing_names`` (the
    Material Manager) position-aligned with ``sets``.

    The ``packed_orm`` row also carries ``contributes`` (``orm_contributions``
    — the SAME function the writer's connect pairs come from): without it
    the row looked like any other wired channel while the writer could be
    degrading it to a bare unconnected sampler, i.e. the preview lied
    exactly where "preview before create" earns its keep (review I2).

    Same discipline for the AO row (v1.33): it carries ``destination`` from
    ``ao_destination`` — the SAME function the writer's graph decision comes
    from — evaluated against the CURRENT ``multiply_ao`` (the sub-view's
    checkbox), so the row can never advertise a multiply the writer would
    skip (e.g. an AO-only set, which has no base color to multiply into).

    And for the height row: ``range`` is ``height_range`` — the same
    function the writer's Displacement remap comes from — so the row says
    whether mid-grey or zero is the flat level, or that a float map's
    convention is unverified. The header probe (``height_float``) and the
    pixel sample (``height_stats``) ride on the set, set by the ops layer,
    which owns I/O.

    Each set also carries ``redshift_unresolved`` (W5, Windows round 7):
    ``{channel: reason}`` for the tiled maps Redshift will report Not Found
    — ``udim.redshift_unresolved`` on ``folder`` + the map's pattern, the
    same rule QC #14 applies to the created sampler."""
    sets = []
    for tex_set in scan_result.get("sets") or []:
        channels = []
        for channel, filename in sorted(tex_set["channels"].items()):
            row = {"channel": channel, "file": filename,
                   "colorspace": channel_colorspace(channel)}
            if channel == "packed_orm":
                row["contributes"] = orm_contributions(tex_set["channels"])
            if channel == "ao":
                row["destination"] = ao_destination(tex_set["channels"],
                                                    multiply_ao)
            if channel == "height":
                row["range"] = height_range(tex_set["channels"],
                                            tex_set.get("height_float"),
                                            tex_set.get("height_stats"))
            tiles = (tex_set.get("tiles") or {}).get(channel)
            if tiles:
                row["tiles"] = list(tiles)
                row["tiles_label"] = udim.format_tiles(tiles)
            channels.append(row)
        sets.append({
            "name": tex_set["name"],
            "channels": channels,
            "normal_flipy": tex_set["normal_flipy"],
            "ignored": [list(row) for row in tex_set["ignored"]],
            "tile_mismatch": tile_mismatch(tex_set),
            "coat_weight_source": coat_weight_source(tex_set["channels"]),
            "redshift_unresolved": _redshift_unresolved(tex_set, folder),
        })
    names = dedupe_names([s["name"] for s in sets], existing_names)
    # A skipped tile family is ONE pattern name (v1.42): carry its tiles so
    # the fold says "UDIM · N tiles" — keyed by the skipped file name, which
    # also keys the leftover rows built from the same ``no_channel`` files.
    pattern_tiles = scan_result.get("pattern_tiles") or {}
    skipped = [row[0] for row in scan_result.get("ignored") or []]
    for tex_set in scan_result.get("sets") or []:
        skipped.extend(row[0] for row in tex_set["ignored"])
    ignored_tiles = {name: {"tiles": list(pattern_tiles[name]),
                            "tiles_label": udim.format_tiles(pattern_tiles[name])}
                     for name in skipped if name in pattern_tiles}
    return {
        "sets": sets,
        "ignored": [list(row) for row in scan_result.get("ignored") or []],
        "names": names,
        "ignored_tiles": ignored_tiles,
    }


def _redshift_unresolved(tex_set, folder):
    out = {}
    for channel, tiles in ((tex_set or {}).get("tiles") or {}).items():
        filename = tex_set["channels"].get(channel) or ""
        path = os.path.join(folder, *filename.split("/")) if folder else filename
        reason = udim.redshift_unresolved(path, tiles)
        if reason:
            out[channel] = reason
    return out


def dedupe_names(names, existing):
    """Position-aligned final names, case-insensitively unique against
    ``existing`` and within the batch (``_02``, ``_03``…)."""
    taken = {str(n).lower() for n in existing or []}
    out = []
    for name in names or []:
        name = str(name)
        final = name
        counter = 2
        while final.lower() in taken:
            final = "%s_%02d" % (name, counter)
            counter += 1
        taken.add(final.lower())
        out.append(final)
    return out
