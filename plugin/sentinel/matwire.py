# -*- coding: utf-8 -*-
"""Material-from-folder recognition engine (v1.32) — PURE, no ``import c4d``.

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

from sentinel.assets import split_res_token

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr",
     ".tga", ".bmp", ".webp", ".tx"})

# Ordered: more specific channels FIRST (normal_gl/normal_dx before normal;
# packed ORM detected before anything else could half-match).
_CHANNEL_VARIANTS = (
    ("packed_orm", ("orm", "arm")),
    ("normal_gl", ("normalgl", "normal_gl", "nor_gl", "normalopengl")),
    ("normal_dx", ("normaldx", "normal_dx", "nrm_dx", "dx_normal", "nor_dx")),
    ("normal", ("normal", "nrm", "nor", "norm", "nml", "nrml", "nmap")),
    ("basecolor", ("basecolor", "base_color", "albedo", "diffuse", "col",
                   "diff", "base", "dif")),
    ("roughness", ("roughness", "rough", "rgh")),
    ("metalness", ("metalness", "metallic", "metal", "met", "mtl")),
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

_SRGB_CHANNELS = frozenset({"basecolor", "emission"})


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
    """Which standard-material inputs a set's packed ORM/ARM ACTUALLY feeds
    — the single source for both the preview note (``preview_payload``) and
    the writer's connect pairs (``matwire_c4d.build_orm_plan``), so the
    preview can never promise a wiring the writer won't make (review I2).

    Dedicated maps win per output: ``outg`` -> roughness only when the set
    has neither a dedicated roughness nor a glossiness map (glossiness
    occupies ``refl_roughness`` via ``refl_isglossiness``); ``outb`` ->
    metalness only without a dedicated metalness map; ``outr`` (AO) is
    NEVER wired (existing AO policy). An empty list means the ORM lands as
    a bare unconnected sampler (visible, never silently dropped)."""
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
    prefix-matches those against set names (``assign_leftovers``)."""
    table = (_compile_channel_res(extra_suffixes) if extra_suffixes
             else _CHANNEL_RES)
    sets = {}
    order = []
    display_names = {}
    ignored = []
    leftover_hints = {}

    for filename in filenames or []:
        base = os.path.basename(str(filename))
        stem, ext = os.path.splitext(base)
        if ext.lower() not in IMAGE_EXTENSIONS:
            ignored.append((filename, "bad_extension"))
            continue
        norm_stem, trailing_px = _strip_trailing_res(_normalize(stem))
        channel, root = _match_channel(norm_stem, table)
        if channel is None:
            ignored.append((filename, "no_channel"))
            leftover_hints[filename] = _normalize(stem).lower()
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
        sets[group_key]["candidates"].setdefault(channel, []).append((filename, px))

    out_sets = []
    for group_key in order:
        root_key = display_names[group_key]
        data = sets[group_key]
        channels = {}
        set_ignored = list(data["ignored"])
        for channel, entries in data["candidates"].items():
            ranked = sorted(entries, key=lambda e: -_rank(e[1]))
            best_rank = _rank(ranked[0][1])
            channels[channel] = ranked[0][0]
            for filename, px in ranked[1:]:
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
        })

    return {"sets": out_sets, "ignored": ignored,
            "leftover_hints": leftover_hints}


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


def preview_payload(scan_result, existing_names):
    """Shape a ``scan_texture_sets`` result for the SPA preview: channel
    rows annotated with their colorspace (single source:
    ``channel_colorspace``), tuples flattened to JSON-friendly lists, and
    default material names deduped against ``existing_names`` (the
    Material Manager) position-aligned with ``sets``.

    The ``packed_orm`` row also carries ``contributes`` (``orm_contributions``
    — the SAME function the writer's connect pairs come from): without it
    the row looked like any other wired channel while the writer could be
    degrading it to a bare unconnected sampler, i.e. the preview lied
    exactly where "preview before create" earns its keep (review I2)."""
    sets = []
    for tex_set in scan_result.get("sets") or []:
        channels = []
        for channel, filename in sorted(tex_set["channels"].items()):
            row = {"channel": channel, "file": filename,
                   "colorspace": channel_colorspace(channel)}
            if channel == "packed_orm":
                row["contributes"] = orm_contributions(tex_set["channels"])
            channels.append(row)
        sets.append({
            "name": tex_set["name"],
            "channels": channels,
            "normal_flipy": tex_set["normal_flipy"],
            "ignored": [list(row) for row in tex_set["ignored"]],
        })
    names = dedupe_names([s["name"] for s in sets], existing_names)
    return {
        "sets": sets,
        "ignored": [list(row) for row in scan_result.get("ignored") or []],
        "names": names,
    }


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
