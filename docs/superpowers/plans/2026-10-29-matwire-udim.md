# Matwire UDIM + export de Painter (OpenPBR, Coat) (v1.42) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Matwire builds RS materials from UDIM/UVTILE texture folders (the LOK Painter export: OpenPBR channel names, OCIO colourspace suffixes, Coat lobe), and the texture resolver / Asset Hub understand `<UDIM>` paths instead of reporting them missing or exploding them into one row per tile.

**Architecture:** A new pure module `sentinel/udim.py` owns everything about tile naming (split, pattern, token, regex, listing, labels). The Matwire engine collapses tiles into one channel entry whose filename IS the Redshift pattern (`…_<UDIM>.png`), so the writer only learns the Coat ports. The resolver, the Hub merge and the colourspace check reuse `udim.py`. Per-file Hub actions refuse UDIM rows by name.

**Tech Stack:** unchanged. Pure Python with the fake-c4d pytest harness (`tests/conftest.py`), `maxon.GraphDescription`, React SPA with vitest, and the bundle committed in `plugin/web/`.

**Spec:** `docs/superpowers/specs/2026-10-29-matwire-udim-design.md`. Measurements: `docs/research/2026-10-29-redshift-udim.md`.

**Branch:** `feat/matwire-udim` (already created from `main`; the spec and research doc are committed there).

## Global Constraints

- **Evidence base** is `docs/research/2026-10-29-redshift-udim.md`:
  - Redshift resolves `<UDIM>` and `<UVTILE>`, case-insensitively, and `<UVTILE>` absorbs the leading `_`.
  - A missing tile renders black.
  - `GetAllAssetsNew` lists each existing tile as its own asset.
  - Coat ports are `coat_weight`, `coat_color` and `coat_roughness` on both BRDFs, with the normal on `geometry_coat_normal` (OpenPBR) / `coat_bump_input` (Standard). `coat_weight` is born 0.
  - Nothing outside that doc is assumed. Measure it live first.
- **No-regression:** a folder with no tiles and no OCIO suffixes scans exactly as in v1.41. Every existing test stays green **unmodified**: never edit a test to make it pass; raise it instead. Baseline before Task 1: `python3.12 -m pytest -q` → **1927 passed**.
- **Python:** the system `python3` (3.15) has no pytest. Use `python3.12 -m pytest -q`. Use `PYTHONDONTWRITEBYTECODE=1` when mutation-testing (Synology mtime granularity).
- **Pure modules** (`udim.py`, `matwire.py`, `assets.py`, `matgraph.py`) never `import c4d`.
- **Colourspace writes:** only `RS_INPUT_COLORSPACE_SRGB` / `RS_INPUT_COLORSPACE_RAW`. Any other string written to `tex0/colorspace` can crash C4D. The OCIO suffix is stripped for **channel matching only**.
- **One Cmd+Z per batch:** the writer still builds the whole graph before `InsertMaterial`.
- **Visible degradation:** Hub actions that can't handle UDIM refuse and name the files. Never skip silently.
- **SPA:** every SPA change rebuilds and commits `plugin/web/` (CI checks parity). Status colours (`--color-status-warn`) are only for warn/fail/pass; the accent never marks state.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit messages follow the repo style (`feat(matwire): …`, in Spanish).

## File structure

| File | Responsibility |
|---|---|
| `plugin/sentinel/udim.py` (new) | Tile naming: `split_tile`, `pattern_name`, `has_token`, `strip_token`, `tile_regex`, `tile_number`, `tile_path`, `list_tiles`, `format_tiles` |
| `plugin/sentinel/matwire.py` | OCIO suffix strip, `match_stem` pipeline, OpenPBR + coat channel tables, tile grouping in `scan_texture_sets`, `coat_weight_source`, `tile_mismatch`, preview fields |
| `plugin/sentinel/matgraph.py` | `_name_channel` through `match_stem` + `udim.strip_token`; coat entries in `PORT_TO_CHANNEL` |
| `plugin/sentinel/matwire_c4d.py` | Coat ports (`BRDF_PORTS` + `BRDF_COAT_BUMP`), coat wiring in `build_description`, coat titles |
| `plugin/sentinel/ui/panel_tools_ops.py` | Height probe on the first tile |
| `plugin/sentinel/textures.py` | `_texture_exists` (pattern = at least one tile) in `_resolve_relative_texture` |
| `plugin/sentinel/assets.py` | Fold tile rows into the pattern row (`merge_inventories`), `udim_records` |
| `plugin/sentinel/bridge/hub.py` | `udim_tiles` on the row, no thumbnail for patterns |
| `plugin/sentinel/ui/hub_ops.py` | `udim_unsupported` refusals (shrink, copy, switch res, collect) |
| `web/src/lib/panelMatwire.ts`, `web/src/components/panel/MatwireSubview.tsx` | Tile note, mismatch warning, coat-weight note |
| `web/src/lib/hubTable.ts`, `web/src/pages/HubPage.tsx`, `web/src/components/hub/HubAssetsTable.tsx`, `web/src/types.ts` | UDIM badge, refusal messages |

---

### Task 1: `udim.py` — tile naming module

**Files:**
- Create: `plugin/sentinel/udim.py`
- Test: `tests/test_udim.py`

**Interfaces:**
- Produces (used by Tasks 2–6):
  - `split_tile(stem) -> dict | None`, where the dict is `{"base": str, "tile": int, "scheme": "udim"|"uvtile", "sep": str}`
  - `pattern_name(base, scheme, sep, ext) -> str`
  - `has_token(path) -> bool`
  - `strip_token(stem) -> str`
  - `tile_regex(pattern) -> re.Pattern | None`
  - `tile_number(match) -> int | None`
  - `tile_path(pattern, tile) -> str`
  - `list_tiles(pattern_path, listdir=os.listdir) -> list[int]`
  - `format_tiles(tiles) -> str`

- [ ] **Step 1: Write the failing tests** — `tests/test_udim.py`:

```python
"""Pure tests for sentinel.udim (v1.42) — tile naming shared by Matwire,
the texture resolver, the Asset Hub and the colourspace check. Facts:
docs/research/2026-10-29-redshift-udim.md."""

from sentinel import udim


def test_split_tile_udim_painter_and_mari():
    assert udim.split_tile("LOK_cuerpo_Height_Raw_1001") == {
        "base": "LOK_cuerpo_Height_Raw", "tile": 1001, "scheme": "udim", "sep": "_"}
    assert udim.split_tile("rock_diffuse.1012") == {
        "base": "rock_diffuse", "tile": 1012, "scheme": "udim", "sep": "."}


def test_split_tile_uvtile_is_converted_to_udim_numbers():
    assert udim.split_tile("rock_Albedo_u1_v1") == {
        "base": "rock_Albedo", "tile": 1001, "scheme": "uvtile", "sep": ""}
    assert udim.split_tile("rock_Albedo_U2_V1")["tile"] == 1002
    assert udim.split_tile("rock_Albedo_u1_v2")["tile"] == 1011


def test_split_tile_rejects_non_tiles():
    for stem in ("rock_BaseColor", "rock_1000", "rock_0999", "1001",
                 "rock_10001", "rock_BaseColor_4k", "rock_u11_v1", "rock_u0_v1"):
        assert udim.split_tile(stem) is None, stem


def test_pattern_name_keeps_separator_and_uvtile_absorbs_underscore():
    assert udim.pattern_name("rock_diffuse", "udim", ".", ".exr") == "rock_diffuse.<UDIM>.exr"
    assert udim.pattern_name("LOK_Height_Raw", "udim", "_", ".png") == "LOK_Height_Raw_<UDIM>.png"
    # measured: rock<UVTILE>.png loads rock_u1_v1.png; rock_<UVTILE> renders black
    assert udim.pattern_name("rock", "uvtile", "", ".png") == "rock<UVTILE>.png"


def test_has_token_and_strip_token_are_case_insensitive():
    assert udim.has_token("/tex/rock.<UDIM>.png")
    assert udim.has_token("relative:///tex/rock<uvtile>.png")
    assert not udim.has_token("/tex/rock.1001.png")
    assert not udim.has_token(None)
    assert udim.strip_token("rock_BaseColor.<UDIM>") == "rock_BaseColor"
    assert udim.strip_token("LOK_Height_Raw_<udim>") == "LOK_Height_Raw"
    assert udim.strip_token("rock<UVTILE>") == "rock"


def test_tile_regex_and_tile_number():
    rx = udim.tile_regex("/tex/rock_BaseColor.<UDIM>.png")
    assert udim.tile_number(rx.fullmatch("/tex/rock_BaseColor.1002.png")) == 1002
    assert rx.fullmatch("/TEX/ROCK_basecolor.1002.PNG") is not None
    assert rx.fullmatch("/tex/rock_BaseColor.png") is None
    assert rx.fullmatch("/tex/rock_Roughness.1002.png") is None
    rx = udim.tile_regex("rock<UVTILE>.png")
    assert udim.tile_number(rx.fullmatch("rock_u2_v3.png")) == 1022
    assert udim.tile_regex("/tex/rock.png") is None


def test_tile_path_inverts_the_pattern():
    assert udim.tile_path("4K/rock_Height.<UDIM>.exr", 1005) == "4K/rock_Height.1005.exr"
    assert udim.tile_path("rock<UVTILE>.png", 1012) == "rock_u2_v2.png"
    assert udim.tile_path("rock.png", 1001) == "rock.png"


def test_list_tiles_reads_the_folder_once_and_sorts(tmp_path):
    for name in ("a_col.1002.png", "a_col.1001.png", "a_col.1011.png",
                 "a_rough.1001.png", "a_col.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert udim.list_tiles(str(tmp_path / "a_col.<UDIM>.png")) == [1001, 1002, 1011]
    assert udim.list_tiles(str(tmp_path / "missing.<UDIM>.png")) == []
    assert udim.list_tiles(str(tmp_path / "nope" / "a.<UDIM>.png")) == []  # unreadable dir
    assert udim.list_tiles(str(tmp_path / "a_col.png")) == []  # no token


def test_list_tiles_uses_injected_listdir():
    seen = []

    def listdir(folder):
        seen.append(folder)
        return ["r_u1_v1.png", "r_u2_v1.png", "r_u1_v1.exr"]

    assert udim.list_tiles("/f/r<UVTILE>.png", listdir=listdir) == [1001, 1002]
    assert seen == ["/f"]


def test_format_tiles_compacts_runs():
    assert udim.format_tiles([1001, 1002, 1003, 1004, 1006, 1007, 1008, 1009, 1010]) \
        == "1001–1004, 1006–1010"
    assert udim.format_tiles([1005]) == "1005"
    assert udim.format_tiles([1002, 1001, 1001, 1011]) == "1001–1002, 1011"
    assert udim.format_tiles([]) == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3.12 -m pytest tests/test_udim.py -q`
Expected: collection error `ImportError: cannot import name 'udim'`.

- [ ] **Step 3: Implement `plugin/sentinel/udim.py`**

```python
# -*- coding: utf-8 -*-
"""UDIM / UVTILE tile naming (v1.42) — PURE, no ``import c4d``.

The single source of what a tiled texture looks like on disk and in a
Redshift sampler path, shared by the Matwire engine, the texture resolver,
the Asset Hub and the colourspace check. Measured
(docs/research/2026-10-29-redshift-udim.md): Redshift resolves ``<UDIM>``
(1001 + v·10 + u) and ``<UVTILE>`` in ``tex0/path``, case-insensitively;
``<UVTILE>`` absorbs the underscore before ``u1_v1``; a tile missing on disk
renders black, silently.

Tiles are recognized only at the END of a filename stem (Painter
``…_1001``, Mari ``….1001``, Mudbox ``…_u1_v1``). UVTILE numbers are kept
as their UDIM equivalent (``u1_v1`` = 1001) so labels read the same.
"""

import os
import re

UDIM = "udim"
UVTILE = "uvtile"

_UDIM_TAIL = re.compile(r"^(?P<base>.+?)(?P<sep>[._])(?P<tile>1\d{3})$")
_UVTILE_TAIL = re.compile(r"^(?P<base>.+?)_u(?P<u>\d+)_v(?P<v>\d+)$", re.IGNORECASE)
_TOKEN = re.compile(r"<(?:udim|uvtile)>", re.IGNORECASE)
_STRIP_TOKEN = re.compile(r"[._]?<udim>|<uvtile>", re.IGNORECASE)
#: UDIM has ten columns (u 0..9); UVTILE columns past that have no UDIM number.
_MAX_U = 10


def _uvtile_number(u, v):
    if 1 <= u <= _MAX_U and v >= 1:
        return 1000 + u + (v - 1) * 10
    return None


def split_tile(stem):
    """``{"base", "tile", "scheme", "sep"}`` when ``stem`` ends in a tile,
    else ``None``. ``sep`` is the separator found before a UDIM number
    (``.`` or ``_``) and is empty for UVTILE, whose token absorbs it."""
    stem = str(stem or "")
    m = _UDIM_TAIL.match(stem)
    if m and int(m.group("tile")) >= 1001:
        return {"base": m.group("base"), "tile": int(m.group("tile")),
                "scheme": UDIM, "sep": m.group("sep")}
    m = _UVTILE_TAIL.match(stem)
    if m:
        tile = _uvtile_number(int(m.group("u")), int(m.group("v")))
        if tile is not None:
            return {"base": m.group("base"), "tile": tile,
                    "scheme": UVTILE, "sep": ""}
    return None


def pattern_name(base, scheme, sep, ext):
    """The Redshift path for a tile family: ``base.<UDIM>.ext`` keeps the
    separator found on disk; ``base<UVTILE>.ext`` drops it (measured: the
    token stands for ``_u1_v1``)."""
    if scheme == UVTILE:
        return "%s<UVTILE>%s" % (base, ext)
    return "%s%s<UDIM>%s" % (base, sep, ext)


def has_token(path):
    return bool(_TOKEN.search(str(path or "")))


def strip_token(stem):
    """``stem`` without its tile token (and the separator before a UDIM
    token) — so a sampler path's name can be matched to a channel."""
    return _STRIP_TOKEN.sub("", str(stem or ""))


def tile_regex(pattern):
    """Case-insensitive regex that FULL-matches the tile files of
    ``pattern`` (a name or a whole path holding one token); ``None`` when
    there is no token. Groups: ``tile`` for UDIM, ``u``/``v`` for UVTILE —
    read them with ``tile_number``."""
    text = str(pattern or "")
    m = _TOKEN.search(text)
    if not m:
        return None
    if m.group(0).lower() == "<udim>":
        body = r"(?P<tile>1\d{3})"
    else:
        body = r"_u(?P<u>\d+)_v(?P<v>\d+)"
    return re.compile(re.escape(text[:m.start()]) + body
                      + re.escape(text[m.end():]), re.IGNORECASE)


def tile_number(match):
    """UDIM number of a ``tile_regex`` match, or ``None`` when the numbers
    are outside what UDIM can address."""
    if match is None:
        return None
    groups = match.groupdict()
    if groups.get("tile"):
        tile = int(groups["tile"])
        return tile if tile >= 1001 else None
    return _uvtile_number(int(groups["u"]), int(groups["v"]))


def tile_path(pattern, tile):
    """The concrete file of ``tile`` in ``pattern`` (the inverse of
    ``pattern_name``); ``pattern`` unchanged when it has no token."""
    text = str(pattern or "")
    m = _TOKEN.search(text)
    if not m:
        return text
    tile = int(tile)
    if m.group(0).lower() == "<udim>":
        body = str(tile)
    else:
        body = "_u%d_v%d" % ((tile - 1001) % 10 + 1, (tile - 1001) // 10 + 1)
    return text[:m.start()] + body + text[m.end():]


def list_tiles(pattern_path, listdir=os.listdir):
    """Sorted tile numbers of ``pattern_path`` present on disk — one
    ``listdir`` of its folder. ``[]`` when there is no token or the folder
    can't be read (never raises: callers report that as missing)."""
    folder, name = os.path.split(str(pattern_path or ""))
    rx = tile_regex(name)
    if rx is None:
        return []
    try:
        entries = listdir(folder or os.curdir)
    except OSError:
        return []
    tiles = set()
    for entry in entries:
        tile = tile_number(rx.fullmatch(str(entry)))
        if tile is not None:
            tiles.add(tile)
    return sorted(tiles)


def format_tiles(tiles):
    """``"1001–1004, 1006–1010"`` — consecutive numbers collapse to a run."""
    nums = sorted({int(t) for t in tiles or ()})
    parts = []
    start = prev = None
    for n in nums:
        if start is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            parts.append(str(start) if start == prev else "%d–%d" % (start, prev))
        start = prev = n
    if start is not None:
        parts.append(str(start) if start == prev else "%d–%d" % (start, prev))
    return ", ".join(parts)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3.12 -m pytest tests/test_udim.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/udim.py tests/test_udim.py
git commit -m "feat(udim): módulo puro de nombres de teselas UDIM/UVTILE

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Painter naming in the Matwire engine (OCIO suffix, OpenPBR names, Coat channels)

**Files:**
- Modify: `plugin/sentinel/matwire.py` (`_CHANNEL_VARIANTS` :27-42, `_SRGB_CHANNELS` :48, new `OCIO_SUFFIXES`/`strip_colorspace_suffix`/`match_stem`, `scan_texture_sets` :377-381)
- Modify: `plugin/sentinel/matgraph.py` (imports :46-52, `_name_channel` :124-135)
- Test: `tests/test_matwire.py`, `tests/test_matgraph.py`

**Interfaces:**
- Consumes: `udim.strip_token` (Task 1).
- Produces:
  - `matwire.strip_colorspace_suffix(stem) -> str`
  - `matwire.match_stem(stem, table=None) -> (channel|None, root|None, trailing_px|None)`
  - New canonical channels `coat_weight`, `coat_color`, `coat_roughness`, `coat_normal` (`coat_color` is sRGB).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_matwire.py`:

```python
def test_painter_ocio_suffix_is_stripped_for_matching_only(matwire):
    out = _scan(matwire,
                "LOK_body_Base_color_sRGB Encoded Rec.709 (sRGB).png",
                "LOK_body_Height_Raw.png",
                "LOK_body_Roughness_ACEScg.png")
    assert out["ignored"] == []
    s = out["sets"][0]
    assert s["name"] == "LOK_body"
    assert s["channels"]["basecolor"] == "LOK_body_Base_color_sRGB Encoded Rec.709 (sRGB).png"
    # the colourspace stays the studio convention, whatever the suffix says
    assert matwire.channel_colorspace("roughness") == "raw"


def test_openpbr_channel_names_keep_one_root(matwire):
    out = _scan(matwire, "LOK_body_Base_color.png", "LOK_body_Base_metalness.png",
                "LOK_body_Specular_roughness.png", "LOK_body_Normal_OpenGL.png",
                "LOK_body_Normal_DirectX.png")
    assert [s["name"] for s in out["sets"]] == ["LOK_body"]
    s = out["sets"][0]
    assert set(s["channels"]) == {"basecolor", "metalness", "roughness", "normal"}
    assert s["channels"]["normal"] == "LOK_body_Normal_OpenGL.png"
    assert ["LOK_body_Normal_DirectX.png", "dx_superseded"] in [list(r) for r in s["ignored"]]


def test_coat_channels_are_recognized_before_their_base_channels(matwire):
    out = _scan(matwire, "car_Base_color.png", "car_Coat_color.png",
                "car_Coat_weight.png", "car_Coat_roughness.png",
                "car_Coat_normal.png", "car_Roughness.png", "car_Normal.png",
                "van_clearcoat_roughness.png")
    by_name = {s["name"]: s for s in out["sets"]}
    assert set(by_name["car"]["channels"]) == {
        "basecolor", "coat_color", "coat_weight", "coat_roughness",
        "coat_normal", "roughness", "normal"}
    assert set(by_name["van"]["channels"]) == {"coat_roughness"}
    assert matwire.channel_colorspace("coat_color") == "srgb"
    for channel in ("coat_weight", "coat_roughness", "coat_normal"):
        assert matwire.channel_colorspace(channel) == "raw"
    assert {"coat_weight", "coat_color", "coat_roughness",
            "coat_normal"} <= matwire.CANONICAL_CHANNELS


def test_match_stem_is_the_shared_pipeline(matwire):
    assert matwire.match_stem("rock_BaseColor_8k_Raw") == ("basecolor", "rock", 8192)
    assert matwire.match_stem("protocol") == (None, None, None)
```

Append to `tests/test_matgraph.py`:

```python
def test_infer_channel_reads_painter_udim_names():
    # v1.42: a token + OCIO suffix used to lose the name signal entirely
    # (measured: Roughness.<UDIM> fell back to the port).
    assert infer_channel("LOK_body_Specular_roughness_Raw_<UDIM>.png", None) == ("roughness", "name")
    assert infer_channel("/t/LOK_body_Base_color_sRGB Encoded Rec.709 (sRGB)_<UDIM>.png",
                         None) == ("basecolor", "name")
    assert infer_channel("rock<UVTILE>.png", None) == (None, None)
    assert infer_channel("rock_Normal.<udim>.exr", None) == ("normal", "name")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3.12 -m pytest tests/test_matwire.py tests/test_matgraph.py -q -k "painter or openpbr or coat_channels or match_stem or painter_udim"`
Expected: FAIL. `no_channel` ignored rows, `AttributeError: match_stem`, and `infer_channel` returning `(None, None)`.

- [ ] **Step 3: Implement in `plugin/sentinel/matwire.py`**

In `_CHANNEL_VARIANTS`:
- Insert the coat rows right after `packed_orm`.
- Extend `normal_gl`, `normal_dx`, `metalness` and `roughness` with the OpenPBR names (the lazy `.*?` root makes the compound variant win at the shorter root, `LOK_body`).

```python
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
```

Then `_SRGB_CHANNELS = frozenset({"basecolor", "emission", "coat_color"})`.

After `_normalize`, add:

```python
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
```

`_strip_trailing_res` and `_match_channel` are defined further down the file than `match_stem`, which is fine because they are only resolved at call time.

In `scan_texture_sets`, replace:

```python
        norm_stem, trailing_px = _strip_trailing_res(_normalize(stem))
        channel, root = _match_channel(norm_stem, table)
        if channel is None:
            ignored.append((filename, "no_channel"))
            leftover_hints[filename] = _normalize(stem).lower()
            continue
```

with:

```python
        channel, root, trailing_px = match_stem(stem, table)
        if channel is None:
            ignored.append((filename, "no_channel"))
            leftover_hints[filename] = _normalize(
                strip_colorspace_suffix(stem)).lower()
            continue
```

In `plugin/sentinel/matgraph.py`, replace the import block (:46-52) with:

```python
from sentinel import udim
from sentinel.matwire import (
    channel_colorspace,
    match_stem,
)
```

Then replace the body of `_name_channel` after `base = …` with:

```python
    stem = base.rsplit(".", 1)[0] if "." in base else base
    channel, _root, _px = match_stem(udim.strip_token(stem))
    return channel
```

Update its docstring's first sentence to: "Channel inferred from a filename alone, via matwire's own stem pipeline (`match_stem`) after removing a UDIM/UVTILE token."

- [ ] **Step 4: Run the full suite**

Run: `python3.12 -m pytest -q`
Expected: 1942 passed (1927 + 10 from Task 1 + 5 here), 0 failed. If an existing Matwire test fails, stop and report it. Do not edit it.

- [ ] **Step 5: Prove a test by mutation**

Temporarily move the four coat rows below `roughness`, then run `PYTHONDONTWRITEBYTECODE=1 python3.12 -m pytest tests/test_matwire.py -q -k coat_channels`. Expected: FAIL. Restore the order, delete `plugin/sentinel/__pycache__`, and re-run: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/matwire.py plugin/sentinel/matgraph.py tests/test_matwire.py tests/test_matgraph.py
git commit -m "feat(matwire): nombres de Painter — sufijo OCIO, canales OpenPBR y Coat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tile grouping, `coat_weight_source`, `tile_mismatch` and preview fields

**Files:**
- Modify: `plugin/sentinel/matwire.py` (`scan_texture_sets` :348-442, new `coat_weight_source`/`tile_mismatch`, `preview_payload` :465-517)
- Test: `tests/test_matwire.py`

**Interfaces:**
- Consumes: `udim.split_tile`, `udim.pattern_name`, `udim.format_tiles` (Task 1); `match_stem`, `strip_colorspace_suffix` (Task 2).
- Produces:
  - Each scanned set gains `"tiles": {channel: [int, ...]}` (only tiled channels; `{}` otherwise).
  - A tiled channel's value in `channels` is the pattern relpath, e.g. `"4K/rock_BaseColor.<UDIM>.png"`.
  - `coat_weight_source(channels) -> "map" | "constant" | None`.
  - `tile_mismatch(tex_set) -> {channel: [missing tiles]}`.
  - In `preview_payload`: tiled channel rows gain `tiles` + `tiles_label`; every set gains `tile_mismatch` and `coat_weight_source`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_matwire.py`:

```python
_LOK_CHANNELS = (
    "Base_color_sRGB Encoded Rec.709 (sRGB)", "Base_metalness_Raw",
    "Coat_color_sRGB Encoded Rec.709 (sRGB)", "Coat_normal_Raw",
    "Coat_roughness_Raw", "Coat_weight_Raw", "Height_Raw",
    "Normal_OpenGL_Raw", "Normal_Raw", "Specular_roughness_Raw")
_LOK_TILES = {"LOK_cuerpo": (1001, 1002, 1003, 1004, 1006, 1007, 1008, 1009, 1010),
              "LOK_grip": (1005,)}


def _lok_files():
    """The real LOK-003 Painter export (EXPORT_PAINTER, 100 PNGs, listed
    2026-10-29): <mesh>_<set>_<channel>_<OCIO colourspace>_<tile>.png."""
    return sorted("%s_%s_%d.png" % (name, channel, tile)
                  for name, tiles in _LOK_TILES.items()
                  for channel in _LOK_CHANNELS for tile in tiles)


def test_lok_painter_export_scans_into_two_udim_sets(matwire):
    files = _lok_files()
    assert len(files) == 100
    out = matwire.scan_texture_sets(files, default_root="EXPORT_PAINTER")
    assert out["ignored"] == []
    by_name = {s["name"]: s for s in out["sets"]}
    assert sorted(by_name) == ["LOK_cuerpo", "LOK_grip"]
    for name, tiles in _LOK_TILES.items():
        s = by_name[name]
        assert set(s["channels"]) == {
            "basecolor", "metalness", "roughness", "normal", "height",
            "coat_color", "coat_weight", "coat_roughness", "coat_normal"}
        assert s["channels"]["normal"] == name + "_Normal_OpenGL_Raw_<UDIM>.png"
        assert s["channels"]["basecolor"] == (
            name + "_Base_color_sRGB Encoded Rec.709 (sRGB)_<UDIM>.png")
        assert s["tiles"]["basecolor"] == list(tiles)
        assert set(s["tiles"]) == set(s["channels"])
        assert [name + "_Normal_Raw_<UDIM>.png", "dx_superseded"] in [
            list(r) for r in s["ignored"]]
        assert matwire.tile_mismatch(s) == {}
        assert matwire.coat_weight_source(s["channels"]) == "map"


def test_mari_and_uvtile_and_subfolder_patterns(matwire):
    out = _scan(matwire, "tex/rock_diffuse.1001.exr", "tex/rock_diffuse.1002.exr",
                "tex/rock_rough.1001.exr", "head_Albedo_u1_v1.png",
                "head_Albedo_u2_v1.png")
    by_name = {s["name"]: s for s in out["sets"]}
    assert by_name["rock"]["channels"] == {
        "basecolor": "tex/rock_diffuse.<UDIM>.exr",
        "roughness": "tex/rock_rough.<UDIM>.exr"}
    assert by_name["rock"]["tiles"] == {"basecolor": [1001, 1002], "roughness": [1001]}
    assert matwire.tile_mismatch(by_name["rock"]) == {"roughness": [1002]}
    assert by_name["head"]["channels"] == {"basecolor": "head_Albedo<UVTILE>.png"}
    assert by_name["head"]["tiles"] == {"basecolor": [1001, 1002]}


def test_untiled_folder_is_unchanged_and_has_empty_tiles(matwire):
    out = _scan(matwire, "plaster_BaseColor_4k.jpg", "plaster_BaseColor_8k.jpg",
                "plaster_Roughness.jpg")
    s = out["sets"][0]
    assert s["channels"] == {"basecolor": "plaster_BaseColor_8k.jpg",
                             "roughness": "plaster_Roughness.jpg"}
    assert s["tiles"] == {}
    assert ["plaster_BaseColor_4k.jpg", "lower_resolution"] in [list(r) for r in s["ignored"]]


def test_tiled_beats_untiled_at_equal_rank_and_res_tokens_still_rank(matwire):
    out = _scan(matwire, "rock_BaseColor.png", "rock_BaseColor.1001.png",
                "rock_Roughness_2k.1001.png", "rock_Roughness_4k.1001.png")
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "rock_BaseColor.<UDIM>.png"
    assert ["rock_BaseColor.png", "duplicate_channel"] in [list(r) for r in s["ignored"]]
    assert s["channels"]["roughness"] == "rock_Roughness_4k.<UDIM>.png"
    assert ["rock_Roughness_2k.<UDIM>.png", "lower_resolution"] in [list(r) for r in s["ignored"]]


def test_unrecognized_tiles_are_one_ignored_row(matwire):
    out = _scan(matwire, "rock_BaseColor.1001.png", "rock_Mask.1001.png",
                "rock_Mask.1002.png")
    assert out["ignored"] == [("rock_Mask.<UDIM>.png", "no_channel")]


def test_coat_weight_source(matwire):
    assert matwire.coat_weight_source({"coat_weight": "w.png"}) == "map"
    assert matwire.coat_weight_source({"coat_color": "c.png"}) == "constant"
    assert matwire.coat_weight_source({"basecolor": "b.png"}) is None
    assert matwire.coat_weight_source(None) is None


def test_preview_payload_carries_tiles_mismatch_and_coat_source(matwire):
    scan = _scan(matwire, "rock_BaseColor.1001.png", "rock_BaseColor.1002.png",
                 "rock_Roughness.1001.png", "rock_Coat_color.png")
    out = matwire.preview_payload(scan, [])
    s = out["sets"][0]
    rows = {r["channel"]: r for r in s["channels"]}
    assert rows["basecolor"]["tiles"] == [1001, 1002]
    assert rows["basecolor"]["tiles_label"] == "1001–1002"
    assert "tiles" not in rows["coat_color"]
    assert s["tile_mismatch"] == {"roughness": [1002]}
    assert s["coat_weight_source"] == "constant"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3.12 -m pytest tests/test_matwire.py -q -k "lok or mari or untiled or tiled_beats or unrecognized_tiles or coat_weight_source or carries_tiles"`
Expected: FAIL (tiles land in `no_channel`; `KeyError: 'tiles'`; `AttributeError: tile_mismatch`).

- [ ] **Step 3: Implement**

At the top of `matwire.py`, add `from sentinel import udim` next to the existing `from sentinel.assets import split_res_token`. Then replace `scan_texture_sets` with the version below. Keep the existing docstring and append the v1.42 paragraph shown.

```python
def scan_texture_sets(filenames, default_root="material", extra_suffixes=None):
    """<keep the existing docstring text, then append:>

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
    scan_entries = []
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
            scan_entries.append((filename, stem, False))
            continue
        folder = rel[:len(rel) - len(base)]
        key = (folder.lower(), tile["base"].lower(), tile["scheme"],
               tile["sep"], ext.lower())
        group = tiled.get(key)
        if group is None:
            pattern = folder + udim.pattern_name(
                tile["base"], tile["scheme"], tile["sep"], ext)
            group = tiled[key] = {"pattern": pattern, "tiles": set()}
            scan_entries.append((pattern, tile["base"], True))
        group["tiles"].add(tile["tile"])
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

        # <normal precedence block — unchanged>
        # <spec/gloss precedence block — unchanged>

        out_sets.append({
            "name": root_key,
            "channels": channels,
            "normal_flipy": normal_flipy,
            "ignored": set_ignored,
            "tiles": {ch: tiles_of[f] for ch, f in channels.items()
                      if f in tiles_of},
        })

    return {"sets": out_sets, "ignored": ignored,
            "leftover_hints": leftover_hints}
```

Copy the two precedence blocks verbatim from the current function: do not retype them.

Add after `height_range`:

```python
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
```

In `preview_payload`, inside the channel loop after the `height` block:

```python
            tiles = (tex_set.get("tiles") or {}).get(channel)
            if tiles:
                row["tiles"] = list(tiles)
                row["tiles_label"] = udim.format_tiles(tiles)
```

Extend the per-set dict:

```python
        sets.append({
            "name": tex_set["name"],
            "channels": channels,
            "normal_flipy": tex_set["normal_flipy"],
            "ignored": [list(row) for row in tex_set["ignored"]],
            "tile_mismatch": tile_mismatch(tex_set),
            "coat_weight_source": coat_weight_source(tex_set["channels"]),
        })
```

- [ ] **Step 4: Run the full suite**

Run: `python3.12 -m pytest -q`
Expected: everything passes, with 7 more than after Task 2.

- [ ] **Step 5: Run against the real LOK folder** (read-only)

```bash
cd plugin && python3.12 -c "
import os; from sentinel import matwire
d='/Users/javiermelgar/DeveloperData/source-assets/freelance-os/source/lok-gen3/models/LOK-003 MAX HYPE (Attack)/cages/produccion/v4/texturizado/EXPORT_PAINTER'
r=matwire.scan_texture_sets(sorted(os.listdir(d)),'EXPORT_PAINTER')
print([(s['name'], sorted(s['channels']), s['tiles'].get('basecolor')) for s in r['sets']], r['ignored'])"
```

Expected: `LOK_cuerpo` with 9 channels and tiles `[1001, 1002, 1003, 1004, 1006, 1007, 1008, 1009, 1010]`; `LOK_grip` with 9 channels and `[1005]`; ignored `[]`.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/matwire.py tests/test_matwire.py
git commit -m "feat(matwire): agrupar teselas UDIM/UVTILE en un patrón por canal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Writer — Coat wiring, coat titles, and the height probe on the first tile

**Files:**
- Modify: `plugin/sentinel/matwire_c4d.py` (imports :46-49, `BRDF_PORTS` :86-107, new `BRDF_COAT_BUMP`, `_CHANNEL_TITLES` :184-196, `build_description` :846-860)
- Modify: `plugin/sentinel/matgraph.py` (`PORT_TO_CHANNEL`)
- Modify: `plugin/sentinel/ui/panel_tools_ops.py` (`_matwire_request` height probe :384-393)
- Test: `tests/test_matwire.py` (class with the `matwire_c4d` fixture near :492), `tests/test_panel_tools_ops.py` (`TestMatwireOps`)

**Interfaces:**
- Consumes: `matwire.coat_weight_source`, `matwire.COAT_WEIGHT_CONSTANT` (Task 3); `udim.tile_path` (Task 1); `tex_set["tiles"]` (Task 3).
- Produces: `matwire_c4d.BRDF_COAT_BUMP = {"openpbr": "geometry_coat_normal", "standard": "coat_bump_input"}`.

- [ ] **Step 1: Write the failing tests**

Append inside the existing class that defines the `matwire_c4d` fixture in `tests/test_matwire.py` (the one holding `test_full_set_desc_shape`):

```python
    @pytest.mark.parametrize("material,bump_port", [
        ("openpbr", "geometry_coat_normal"), ("standard", "coat_bump_input")])
    def test_coat_maps_are_wired_on_both_brdfs(self, matwire, matwire_c4d,
                                               material, bump_port):
        tex_set = {"name": "car", "normal_flipy": True, "channels": {
            "coat_weight": "car_Coat_weight.<UDIM>.png",
            "coat_color": "car_Coat_color.png",
            "coat_roughness": "car_Coat_roughness.png",
            "coat_normal": "car_Coat_normal.png"}}
        desc, _ao = matwire_c4d.build_description("/tex", tex_set, material=material)
        RS = matwire_c4d._RS_CORE
        node_id = matwire_c4d.BRDF_NODES[material]
        brdf = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        sm = "#<" + node_id + "."
        weight = brdf[sm + "coat_weight"]
        assert weight["#<" + RS + "texturesampler.tex0/path"] == os.path.join(
            "/tex", "car_Coat_weight.<UDIM>.png")
        assert brdf[sm + "coat_color"]["#<" + RS + "texturesampler.tex0/colorspace"] \
            == matwire_c4d._RS_COLORSPACE["srgb"]
        assert brdf[sm + "coat_roughness"]["#<" + RS + "texturesampler.tex0/colorspace"] \
            == matwire_c4d._RS_COLORSPACE["raw"]
        bump = brdf[sm + bump_port]
        assert bump["$type"] == "#" + RS + "bumpmap"
        assert bump["#<" + RS + "bumpmap.inputtype"] == 1
        assert bump["#<" + RS + "bumpmap.flipy"] is True
        assert bump["#<" + RS + "bumpmap.input"]["#<" + RS + "texturesampler.tex0/path"] \
            == os.path.join("/tex", "car_Coat_normal.png")

    def test_coat_without_weight_map_writes_constant(self, matwire, matwire_c4d):
        tex_set = {"name": "car", "normal_flipy": False,
                   "channels": {"coat_color": "car_Coat_color.png"}}
        desc, _ao = matwire_c4d.build_description("/tex", tex_set, material="openpbr")
        brdf = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        key = "#<" + matwire_c4d.BRDF_NODES["openpbr"] + ".coat_weight"
        assert brdf[key] == matwire.COAT_WEIGHT_CONSTANT == 1.0

    def test_no_coat_writes_no_coat_port(self, matwire, matwire_c4d):
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"basecolor": "p_col.png"}}
        desc, _ao = matwire_c4d.build_description("/tex", tex_set)
        brdf = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
        assert not [k for k in brdf if "coat" in k]
```

Append to `TestMatwireOps` in `tests/test_panel_tools_ops.py`:

```python
    def test_udim_height_probes_its_first_tile(self, sentinel_module, monkeypatch, tmp_path):
        """A pattern path opens no file (measured: height_float_stats on
        <UDIM> returned None), so the float probes read the lowest tile."""
        import os
        from sentinel import matwire_c4d
        ops = self._setup(monkeypatch, _FakeMatwireDoc())
        folder = self._folder(tmp_path, "rock_BaseColor.1001.png",
                              "rock_Height.1002.exr", "rock_Height.1001.exr")
        probed = []
        monkeypatch.setattr(matwire_c4d, "height_float_stats",
                            lambda path: probed.append(os.path.basename(path)))
        preview = ops._op_matwire_preview({"folder": folder})
        assert preview["ok"] is True
        assert probed == ["rock_Height.1001.exr"]
        rows = {r["channel"]: r for r in preview["sets"][0]["channels"]}
        assert rows["height"]["file"] == "rock_Height.<UDIM>.exr"
        assert rows["height"]["tiles"] == [1001, 1002]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3.12 -m pytest tests/test_matwire.py tests/test_panel_tools_ops.py -q -k "coat or udim_height"`
Expected: FAIL with `KeyError` on the coat ports, and `probed == ["rock_Height.<UDIM>.exr"]`.

- [ ] **Step 3: Implement**

`matwire_c4d.py` imports: add `COAT_WEIGHT_CONSTANT, coat_weight_source` to the `from sentinel.matwire import (...)` list, in alphabetical order with the others.

`BRDF_PORTS`: add these lines to **both** dicts (the port names are identical on OpenPBR and Standard, measured):

```python
        "coat_weight": "coat_weight",
        "coat_color": "coat_color",
        "coat_roughness": "coat_roughness",
```

After `BRDF_EMISSION_AMOUNT`, add:

```python
#: The BRDF's OWN coat bump input per type (measured 2026-10-29). Kept out
#: of BRDF_PORTS on purpose: like the "bump" slot it is never fed by a
#: sampler directly (a bumpmap node sits between), and matgraph's inverse
#: table (PORT_TO_CHANNEL, cross-checked against BRDF_PORTS) lists only
#: sampler destinations.
BRDF_COAT_BUMP = {
    "openpbr": "geometry_coat_normal",
    "standard": "coat_bump_input",
}
```

In `_CHANNEL_TITLES`, add:

```python
    "coat_weight": "Coat Weight",
    "coat_color": "Coat Color",
    "coat_roughness": "Coat Roughness",
    "coat_normal": "Coat Normal",
```

In `build_description`, right after the `if "normal" in channels:` block, add:

```python
    for coat in ("coat_weight", "coat_color", "coat_roughness"):
        if coat in channels:
            brdf[sm + ports[coat]] = _sampler(path(coat), _rs_colorspace(coat))
    if coat_weight_source(channels) == "constant":
        # Born 0 on both BRDFs (measured): coat maps with no weight map
        # would ship an invisible coat — same rule as emission.
        brdf[sm + ports["coat_weight"]] = COAT_WEIGHT_CONSTANT
    if "coat_normal" in channels:
        brdf[sm + BRDF_COAT_BUMP[material]] = {
            "$type": "#" + _RS_CORE + "bumpmap",
            "#<" + _RS_CORE + "bumpmap.inputtype": 1,  # Tangent-Space Normal
            "#<" + _RS_CORE + "bumpmap.input": _sampler(
                path("coat_normal"), _rs_colorspace("coat_normal")),
            # Same convention as the set's main normal (Painter exports both
            # from one preset); explicit, never the node default.
            "#<" + _RS_CORE + "bumpmap.flipy": bool(tex_set.get("normal_flipy")),
        }
```

`matgraph.py` `PORT_TO_CHANNEL`: add before the `# single-owner utility ports` comment:

```python
    # coat (v1.42) — identical port names on both BRDFs. The coat NORMAL
    # reaches the BRDF through a bumpmap, so it lands on bumpmap.input.
    "coat_color": "coat_color",
    "coat_weight": "coat_weight",
    "coat_roughness": "coat_roughness",
```

`panel_tools_ops.py`, in `_matwire_request`'s height loop, replace:

```python
        rel = tex_set["channels"].get("height")
        if rel:
            path = matwire_c4d._join(folder, rel)
```

with:

```python
        rel = tex_set["channels"].get("height")
        if rel:
            # A UDIM height is a pattern no file answers to (v1.42): probe
            # its lowest tile — the same header + pixels question.
            tiles = (tex_set.get("tiles") or {}).get("height")
            path = matwire_c4d._join(
                folder, udim.tile_path(rel, tiles[0]) if tiles else rel)
```

Add `from sentinel import udim` next to the function's other local imports (`from sentinel import imagemeta`).

- [ ] **Step 4: Run the full suite**

Run: `python3.12 -m pytest -q`
Expected: all pass. That includes the matgraph `BRDF_PORTS` ↔ `PORT_TO_CHANNEL` cross-check test, unmodified. If it fails, the tables disagree: fix the tables, not the test.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/matwire_c4d.py plugin/sentinel/matgraph.py plugin/sentinel/ui/panel_tools_ops.py tests/test_matwire.py tests/test_panel_tools_ops.py
git commit -m "feat(matwire): cablear Coat en OpenPBR y Standard; altura UDIM sondea la primera tesela

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Resolver — a UDIM path exists when at least one tile does

**Files:**
- Modify: `plugin/sentinel/textures.py` (`_resolve_relative_texture` :319-367, plus the new `_texture_exists`)
- Test: `tests/test_texture_path_helpers.py`

**Interfaces:**
- Consumes: `udim.has_token`, `udim.list_tiles` (Task 1).
- Produces: `textures._texture_exists(path) -> bool`. `_classify_texture_path` gives `ok` for relative patterns with tiles and `missing` without.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_texture_path_helpers.py`:

```python
def test_classify_udim_pattern_is_ok_when_a_tile_exists(sentinel_module, tmp_path):
    """v1.42: os.path.isfile on '<UDIM>' is always False — every relative
    UDIM map read as missing (QC Assets FAIL) though Redshift renders it."""
    import importlib
    textures = importlib.import_module("sentinel.textures")
    tex = tmp_path / "tex"
    tex.mkdir()
    (tex / "rock_BaseColor.1001.png").write_bytes(b"x")
    (tex / "rock_BaseColor.1002.png").write_bytes(b"x")
    status, resolved = textures._classify_texture_path(
        "rock_BaseColor.<UDIM>.png", str(tmp_path))
    assert status == "ok"
    assert resolved == os.path.normpath(str(tex / "rock_BaseColor.<UDIM>.png"))
    assert textures._classify_texture_path(
        "relative:///tex/rock_BaseColor.<udim>.png", str(tmp_path))[0] == "ok"


def test_classify_udim_pattern_without_tiles_is_missing(sentinel_module, tmp_path):
    import importlib
    textures = importlib.import_module("sentinel.textures")
    (tmp_path / "rock_BaseColor.png").write_bytes(b"x")  # untiled ≠ a tile
    assert textures._classify_texture_path(
        "rock_BaseColor.<UDIM>.png", str(tmp_path))[0] == "missing"
```

Check the top of the file for `import os`, and add it if absent.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3.12 -m pytest tests/test_texture_path_helpers.py -q -k udim`
Expected: the first test FAILs with `'missing' != 'ok'`. The second already passes; it is the guard.

- [ ] **Step 3: Implement** in `textures.py`

Add `from sentinel import udim` after `from sentinel.common.helpers import …` (line 28), then add above `_resolve_relative_texture`:

```python
def _texture_exists(path):
    """A file on disk — or, for a UDIM/UVTILE pattern (v1.42), at least one
    of its tiles: Redshift renders the tiles that are there (missing ones
    come out black — measured), so a pattern with no tile at all is the
    real "missing"."""
    if udim.has_token(path):
        return bool(udim.list_tiles(path))
    return os.path.isfile(path)
```

Inside `_resolve_relative_texture`, replace each of the five `os.path.isfile(` calls with `_texture_exists(`. Do not change anything else.

- [ ] **Step 4: Run the full suite**

Run: `python3.12 -m pytest -q`
Expected: all pass (including `test_texture_path_classifier_corpus_pins_current_behavior`, unmodified).

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/textures.py tests/test_texture_path_helpers.py
git commit -m "fix(textures): una ruta UDIM existe si hay al menos una tesela

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Asset Hub engine and ops — one row per UDIM map, visible refusals

**Files:**
- Modify: `plugin/sentinel/assets.py` (`merge_inventories` :149-228, new `_fold_tile` + `udim_records`)
- Modify: `plugin/sentinel/bridge/hub.py` (`hub_inventory_payload` :12-45)
- Modify: `plugin/sentinel/ui/hub_ops.py` (new `_udim_refusal` + `_udim_files_in_scene`; `_op_hub_shrink_start` :517, `_op_hub_copy_into_project` :652, `_op_hub_switch_res` :1285, `_op_hub_collect_start` :960)
- Test: `tests/test_assets.py`, `tests/test_hub_ops.py`

**Interfaces:**
- Consumes: `udim.has_token`, `udim.tile_regex`, `udim.tile_number` (Task 1).
- Produces:
  - Merged records may carry `"udim": {"tiles": [int, ...]}`.
  - `assets.udim_records(records) -> list`.
  - The Hub row field `udim_tiles: list[int] | None`.
  - Op error `{"ok": False, "error": "udim_unsupported", "udim_files": [basename, ...]}` from `hub/shrink_start`, `hub/copy_into_project`, `hub/switch_res` and `hub/collect_start`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assets.py`, inside `class TestMergeInventories`:

```python
    def test_udim_tiles_fold_into_the_pattern_row(self):
        """GetAllAssetsNew lists every tile on its own (measured); the Hub
        shows ONE row per UDIM map, counting its tiles."""
        out = assets.merge_inventories(
            [_tex("/p/tex/rock_BaseColor.<UDIM>.png")],
            [_gen("/p/tex/rock_BaseColor.1001.png", owner_name="RS_Mat", owner_kind="material"),
             _gen("/p/tex/rock_BaseColor.1002.png", owner_name="RS_Mat", owner_kind="material"),
             _gen("/p/tex/rock_Roughness.1001.png")])
        assert len(out) == 2
        row = next(r for r in out if "<udim>" in r["key"])
        assert row["udim"] == {"tiles": [1001, 1002]}
        assert row["repathable"] is True
        assert ("RS_Mat", "material", "") in row["owners"]
        assert not [r for r in out if r["key"].endswith("basecolor.1001.png")]

    def test_rows_without_token_carry_no_udim(self):
        out = assets.merge_inventories([_tex("/p/tex/a.png")], [_gen("/p/tex/b.1001.png")])
        assert all("udim" not in r for r in out)

    def test_udim_records(self):
        recs = [{"key": "a", "udim": {"tiles": [1001]}}, {"key": "b"}]
        assert assets.udim_records(recs) == [recs[0]]
        assert assets.udim_records(None) == []
```

Append to `tests/test_hub_ops.py`:

```python
class TestHubUdimRefusals:
    """v1.42: per-file Hub actions don't handle tiles yet — they refuse and
    NAME the UDIM files instead of skipping them silently."""

    _UDIM = {"key": "/p/tex/rock.<udim>.png", "path": "tex/rock.<UDIM>.png",
             "resolved_path": "/p/tex/rock.<UDIM>.png", "status": "ok",
             "asset_type": "texture", "repathable": True, "tex_idxs": [0],
             "udim": {"tiles": [1001, 1002]}}

    class _Doc:
        def __init__(self, path):
            self._path = path

        def GetDocumentPath(self):
            return self._path

        def GetDocumentName(self):
            return "a_v001.c4d"

    def _patch(self, monkeypatch, tmp_path):
        from sentinel.ui import flows, hub_ops
        doc = self._Doc(str(tmp_path))
        monkeypatch.setattr(hub_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(flows, "scan_scene_assets",
                            lambda d: ([dict(self._UDIM)], [], []))
        return hub_ops

    def test_shrink_copy_and_switch_refuse_udim_rows(self, sentinel_module, monkeypatch, tmp_path):
        hub_ops = self._patch(monkeypatch, tmp_path)
        key = self._UDIM["key"]
        expected = {"ok": False, "error": "udim_unsupported", "udim_files": ["rock.<UDIM>.png"]}
        assert hub_ops.HUB_OPS["hub/shrink_start"]({"keys": [key], "target_px": 2048}) == expected
        assert hub_ops.HUB_OPS["hub/copy_into_project"]({"keys": [key]}) == expected
        assert hub_ops.HUB_OPS["hub/switch_res"]({"keys": [key], "target": "highest"}) == expected

    def test_collect_refuses_before_qc(self, sentinel_module, monkeypatch, tmp_path):
        hub_ops = self._patch(monkeypatch, tmp_path)
        monkeypatch.setattr(hub_ops, "run_all_checks",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("QC ran")))
        response = hub_ops.HUB_OPS["hub/collect_start"]({"target_dir": str(tmp_path / "out")})
        assert response == {"ok": False, "error": "udim_unsupported",
                            "udim_files": ["rock.<UDIM>.png"]}

    def test_hub_row_has_udim_tiles_and_no_thumb(self, sentinel_module):
        from sentinel.bridge import hub
        rec = dict(self._UDIM, owners=[], size_bytes=None)
        row = hub.hub_inventory_payload([rec], {"count": 1, "total_bytes": 0})["assets"][0]
        assert row["udim_tiles"] == [1001, 1002]
        assert row["has_thumb"] is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3.12 -m pytest tests/test_assets.py tests/test_hub_ops.py -q -k "udim"`
Expected: FAIL. You get three rows instead of two, `AttributeError: udim_records`, ops returning other errors or proceeding, and `KeyError: 'udim_tiles'`.

- [ ] **Step 3: Implement**

`assets.py`: add `from sentinel import udim` after the stdlib imports (after `import zipfile`, line 9), next to wherever the module imports `imagemeta`. `udim` imports nothing from `sentinel`, so there is no cycle. Add above `merge_inventories`:

```python
def _fold_tile(key, patterns, by_key, owner):
    """Fold a generic record that is ONE TILE of a UDIM texture row into
    that row (v1.42): GetAllAssetsNew lists every tile on its own (measured
    2026-10-29), which turned one map into a pattern row plus N tile rows.
    True when folded."""
    for rx, pattern_key in patterns:
        match = rx.fullmatch(key)
        if not match:
            continue
        row = by_key[pattern_key]
        tile = udim.tile_number(match)
        if tile is not None and tile not in row["udim"]["tiles"]:
            row["udim"]["tiles"].append(tile)
            row["udim"]["tiles"].sort()
        if owner not in row["owners"]:
            row["owners"].append(owner)
        return True
    return False


def udim_records(records):
    """Merged records that are UDIM patterns — the per-file Hub actions
    (shrink, copy, switch resolution, collect) refuse them by name."""
    return [rec for rec in records or [] if rec.get("udim")]
```

In `merge_inventories`, declare `patterns = []` next to `by_key`/`order`. In the texture loop, right after `by_key[key] = {...}` and before `order.append(key)`:

```python
        if udim.has_token(key):
            by_key[key]["udim"] = {"tiles": []}
            patterns.append((udim.tile_regex(key), key))
```

In the generic loop, right after `owner = (...)`:

```python
        if patterns and _fold_tile(key, patterns, by_key, owner):
            continue
```

Append one sentence to the docstring: "UDIM texture rows (v1.42) absorb the per-tile generic records (`_fold_tile`) and carry `udim: {"tiles": [...]}`."

`bridge/hub.py` `hub_inventory_payload`: change the `has_thumb` expression to add `and not rec.get("udim")`, and add the field after `"repathable"`:

```python
            "udim_tiles": (list((rec.get("udim") or {}).get("tiles") or [])
                           if rec.get("udim") else None),
```

Then add a comment over `has_thumb`: `# A UDIM pattern names no file: no thumbnail (v1.42).`

`hub_ops.py`: add near the other private helpers (above `_op_hub_shrink_start`):

```python
def _udim_refusal(records):
    """The ``udim_unsupported`` refusal when any of ``records`` is a UDIM
    pattern, else None. v1.42: shrink / copy / switch resolution / collect
    work file by file and don't handle tiles yet; they refuse and NAME the
    maps (the artist deselects them) instead of skipping them silently."""
    blocked = assets_engine.udim_records(records)
    if not blocked:
        return None
    names = sorted({os.path.basename(str(rec.get("path") or "").replace("\\", "/"))
                    for rec in blocked})
    return {"ok": False, "error": "udim_unsupported", "udim_files": names}


def _udim_files_in_scene(doc):
    """``_udim_refusal`` over the whole scene for Collect. A scan failure
    here is logged and lets Collect continue to its own pipeline (which
    scans again and reports its own failure) — the guard never makes a
    delivery impossible on its own."""
    from sentinel.ui.flows import scan_scene_assets
    try:
        records, _tex_records, _skipped = scan_scene_assets(doc)
    except Exception as exc:
        safe_print("Collect: UDIM pre-check skipped (%s)" % exc)
        return None
    return _udim_refusal(records)
```

`hub_ops.py` does not import `safe_print` today: add `from sentinel.common.helpers import safe_print` to its imports.

Insert the guards:
- `_op_hub_shrink_start`, right after `selected_records = [...]`:
  ```python
      refusal = _udim_refusal(selected_records)
      if refusal:
          return refusal
  ```
- `_op_hub_copy_into_project`, right after `_remember_thumb_paths(records)`:
  ```python
      refusal = _udim_refusal([r for r in records if r.get("key") in keys_set])
      if refusal:
          return refusal
  ```
- `_op_hub_switch_res`, right after `requested_records = [...]`: the same three lines on `requested_records`.
- `_op_hub_collect_start`, right after the `_delivery_target_occupied` block:
  ```python
      # Before the QC pre-flight, like the occupied-target refusal: a
      # delivery that can't carry its UDIM tiles is refused up front.
      refusal = _udim_files_in_scene(doc)
      if refusal:
          return refusal
  ```

- [ ] **Step 4: Run the full suite**

Run: `python3.12 -m pytest -q`
Expected: all pass, including `tests/test_collect_durability.py::test_collect_start_binds_document_and_path_into_job_spec`, unmodified. Its fake doc makes the real scan raise or return nothing, and `_udim_files_in_scene` logs and continues. If it fails, report it; do not edit it.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/assets.py plugin/sentinel/bridge/hub.py plugin/sentinel/ui/hub_ops.py tests/test_assets.py tests/test_hub_ops.py
git commit -m "feat(hub): una fila por mapa UDIM y negativa visible en shrink/copy/res/collect

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: SPA — Matwire tile notes, Hub UDIM badge and refusal messages

**Files:**
- Modify: `web/src/types.ts`
  - `MatwireChannelRow` :1295
  - `MatwireSet` :1321
  - `HubAsset` :510
  - `HubShrinkStartResponse` :662
  - `HubCopyResponse` :695
  - `HubSwitchResponse` :785
  - `HubCollectStartResponse` :635
- Modify: `web/src/lib/panelMatwire.ts`, `web/src/components/panel/MatwireSubview.tsx` (row render :336-390)
- Modify: `web/src/lib/hubTable.ts` (`collectStartRefusal` :445, new `udimBadge`/`udimRefusalMessage`), `web/src/pages/HubPage.tsx` (:451, :465, :493), `web/src/components/hub/HubAssetsTable.tsx` (:460)
- Test: `web/src/lib/panelMatwire.test.ts`, `web/src/lib/hubTable.test.ts`
- Build: `plugin/web/` (committed bundle)

**Interfaces:**
- Consumes these server fields:
  - From Task 3: `tiles`, `tiles_label`, `tile_mismatch`, `coat_weight_source`.
  - From Task 6: `udim_tiles`, `udim_files`, and `error: "udim_unsupported"`.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/lib/panelMatwire.test.ts` (import the three new functions in its import list):

```ts
describe("UDIM notes (v1.42)", () => {
  it("labels tiled rows and stays silent for untiled ones", () => {
    expect(tilesNote({ tiles: [1001, 1002, 1003, 1004, 1006, 1007, 1008, 1009, 1010], tiles_label: "1001–1004, 1006–1010" }))
      .toBe("UDIM · 9 tiles (1001–1004, 1006–1010)");
    expect(tilesNote({ tiles: [1005], tiles_label: "1005" })).toBe("UDIM · 1 tile (1005)");
    expect(tilesNote({})).toBeNull();
  });

  it("warns when maps of one set cover different tiles", () => {
    expect(tileMismatchNote({ roughness: [1002, 1003] }))
      .toBe("Tiles differ between maps — roughness lacks 1002, 1003. Those areas render black.");
    expect(tileMismatchNote({})).toBeNull();
    expect(tileMismatchNote(undefined)).toBeNull();
  });

  it("says when the coat weight is a constant", () => {
    expect(coatWeightNote("constant")).toBe("coat weight → 1.0 (no weight map)");
    expect(coatWeightNote("map")).toBeNull();
    expect(coatWeightNote(null)).toBeNull();
  });
});
```

Append to `web/src/lib/hubTable.test.ts` (import `udimBadge`, `udimRefusalMessage`):

```ts
describe("UDIM in the Hub (v1.42)", () => {
  it("badges UDIM rows with their tile count", () => {
    expect(udimBadge({ udim_tiles: [1001, 1002] })).toBe("UDIM · 2");
    expect(udimBadge({ udim_tiles: [] })).toBe("UDIM");
    expect(udimBadge({ udim_tiles: null })).toBeNull();
    expect(udimBadge({})).toBeNull();
  });

  it("names the refused files", () => {
    expect(udimRefusalMessage("Shrink", ["rock.<UDIM>.png"]))
      .toBe("Shrink doesn't support UDIM textures yet: rock.<UDIM>.png. Deselect them and try again.");
    expect(udimRefusalMessage("Copy into project", undefined))
      .toBe("Copy into project doesn't support UDIM textures yet. Deselect them and try again.");
  });

  it("collect refusal for UDIM stays on the form", () => {
    expect(collectStartRefusal({ ok: false, error: "udim_unsupported", udim_files: ["a.<UDIM>.png", "b.<UDIM>.exr"] }))
      .toEqual({ message: "Collect doesn't support UDIM textures yet: a.<UDIM>.png, b.<UDIM>.exr. Nothing was delivered." });
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npx vitest run src/lib/panelMatwire.test.ts src/lib/hubTable.test.ts`
Expected: FAIL (`tilesNote is not a function`, etc.).

- [ ] **Step 3: Implement**

`types.ts`:

```ts
// MatwireChannelRow — add:
  /** v1.42, tiled channels only: tile numbers and their compact label
   * (`udim.format_tiles`), both server-derived. */
  tiles?: number[];
  tiles_label?: string;
// MatwireSet — add:
  /** v1.42: channel -> tiles other maps of the set have and it lacks. */
  tile_mismatch?: Record<string, number[]>;
  /** v1.42: `matwire.coat_weight_source` — "constant" means 1.0 is written. */
  coat_weight_source?: "map" | "constant" | null;
// HubAsset — add:
  /** v1.42: tiles of a UDIM pattern row; null for ordinary files. */
  udim_tiles?: number[] | null;
// HubShrinkStartResponse, HubCopyResponse, HubSwitchResponse, HubCollectStartResponse — add:
  /** v1.42: with `error: "udim_unsupported"`, the UDIM maps that were refused. */
  udim_files?: string[];
```

`panelMatwire.ts`: add `MatwireChannelRow` to the type import, then:

```ts
/** Suffix note for a tiled channel row (v1.42) — the file shown is the
 * Redshift pattern (`…<UDIM>.png`); this says which tiles back it.
 * Server-derived (`tiles`/`tiles_label`); null for untiled rows. */
export function tilesNote(row: Pick<MatwireChannelRow, "tiles" | "tiles_label">): string | null {
  const count = row.tiles?.length ?? 0;
  if (count === 0) return null;
  return `UDIM · ${count} tile${count === 1 ? "" : "s"} (${row.tiles_label ?? ""})`;
}

/** Set-level warning (v1.42): maps of one set that don't cover the same
 * tiles — Redshift renders a missing tile black, silently (measured). */
export function tileMismatchNote(mismatch: Record<string, number[]> | undefined): string | null {
  const entries = Object.entries(mismatch ?? {});
  if (entries.length === 0) return null;
  const parts = entries.map(([channel, tiles]) => `${channelLabel(channel)} lacks ${tiles.join(", ")}`);
  return `Tiles differ between maps — ${parts.join("; ")}. Those areas render black.`;
}

/** Note when the coat has maps but no weight map: the writer writes 1.0
 * (both BRDFs are born at 0 — an invisible coat otherwise). */
export function coatWeightNote(source: string | null | undefined): string | null {
  return source === "constant" ? "coat weight → 1.0 (no weight map)" : null;
}
```

`MatwireSubview.tsx`:
- Import the three helpers.
- Inside the row `<div>`, right before `<ColorspaceChip … />`, add:
  ```tsx
                          {tilesNote(row) && (
                            <span className="shrink-0" style={{ color: "var(--color-muted)" }}>
                              {tilesNote(row)}
                            </span>
                          )}
  ```
- Right before `<IgnoredFold rows={texSet.ignored} title="file(s) skipped" />`, add:
  ```tsx
                    {tileMismatchNote(texSet.tile_mismatch) && (
                      <p className="text-caption" style={{ color: "var(--color-status-warn)" }}>
                        {tileMismatchNote(texSet.tile_mismatch)}
                      </p>
                    )}
                    {coatWeightNote(texSet.coat_weight_source) && (
                      <p className="text-caption" style={{ color: "var(--color-muted)" }}>
                        {coatWeightNote(texSet.coat_weight_source)}
                      </p>
                    )}
  ```

`hubTable.ts`:

```ts
/** "UDIM · N" for a UDIM pattern row (v1.42), null for ordinary files. */
export function udimBadge(asset: Pick<HubAsset, "udim_tiles">): string | null {
  if (!asset.udim_tiles) return null;
  return asset.udim_tiles.length > 0 ? `UDIM · ${asset.udim_tiles.length}` : "UDIM";
}

/** Toast for a per-file Hub action that refused UDIM maps (v1.42). */
export function udimRefusalMessage(action: string, files: string[] | undefined): string {
  const list = files && files.length > 0 ? `: ${files.join(", ")}` : "";
  return `${action} doesn't support UDIM textures yet${list}. Deselect them and try again.`;
}
```

Then change the head of `collectStartRefusal` to:

```ts
export function collectStartRefusal(res: HubCollectStartResponse): { message: string } | null {
  if (res.ok) return null;
  if (res.error === "udim_unsupported") {
    // v1.42: a delivery that can't carry its UDIM tiles is refused up front.
    const list = res.udim_files && res.udim_files.length > 0 ? `: ${res.udim_files.join(", ")}` : "";
    return { message: `Collect doesn't support UDIM textures yet${list}. Nothing was delivered.` };
  }
  if (res.error !== "target_not_empty") return null;
```

`HubPage.tsx`: import `udimRefusalMessage`. In the three toasts (:451, :465, :493), prefix the message expression with the UDIM branch, e.g. for shrink:

```ts
      toast({ message: res.error === "udim_unsupported"
        ? udimRefusalMessage("Shrink", res.udim_files)
        : SHRINK_ERROR_MESSAGES[res.error ?? ""] ?? res.error ?? "Couldn't start shrink.", variant: "warn" });
```

Use `"Copy into project"` for copy and `"Switch resolution"` for switch res.

`HubAssetsTable.tsx`: import `udimBadge` from `../../lib/hubTable`. Replace the `{basename}` span content:

```tsx
                      <span className="truncate" style={{ color: "var(--color-ink)" }}>
                        {basename}
                        {udimBadge(a) && (
                          <span className="text-caption" style={{ color: "var(--color-muted)" }}>
                            {" · "}{udimBadge(a)}
                          </span>
                        )}
                      </span>
```

- [ ] **Step 4: Run the web checks and build**

Run: `cd web && npm test && npm run lint && npm run build`
Expected: vitest all pass (previous count + 6), lint clean, and the build writes `plugin/web/`.

- [ ] **Step 5: Commit, including the bundle**

```bash
git add web/src plugin/web
git commit -m "feat(spa): notas de teselas UDIM en Matwire y distintivo/negativas UDIM en el Hub

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Live verification, frozen oracle, release v1.42.0

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION = "1.42.0"`), `README.md`, `ROADMAP.md`, `CLAUDE.md`, `docs/HISTORY.md`, `docs/superpowers/specs/2026-10-29-matwire-udim-design.md` (Estado)

- [ ] **Step 1: Deploy and restart**

Run: `./sync.sh` (check which C4D preferences folder it targets; see CLAUDE.md "Development flow"). Then **ask the user to restart C4D**: the artist may have a scene open, so never quit C4D yourself. Wait for confirmation, then run the MCP `ping`.

- [ ] **Step 2: Live — the LOK folder through the real writer** (throwaway document only)

Run with MCP `exec_python`:

```python
import c4d, os
from sentinel import matwire, matwire_c4d
from sentinel.ui import panel_tools_ops
LOK = "/Users/javiermelgar/DeveloperData/source-assets/freelance-os/source/lok-gen3/models/LOK-003 MAX HYPE (Attack)/cages/produccion/v4/texturizado/EXPORT_PAINTER"
scan = matwire.scan_texture_sets(panel_tools_ops._list_folder_files(LOK), default_root="EXPORT_PAINTER")
doc = c4d.documents.BaseDocument()
try:
    doc.StartUndo()
    made = [matwire_c4d.create_material_for_set(doc, LOK, s, s["name"]) for s in scan["sets"]]
    doc.EndUndo()
    mats = [m.GetName() for m in doc.GetMaterials()]
    result = {"made": made, "mats": mats, "tiles": {s["name"]: s["tiles"].get("basecolor") for s in scan["sets"]}}
finally:
    c4d.documents.KillDocument(doc)
```

Expected: two `ok` results, materials `LOK_cuerpo` and `LOK_grip`, tiles as in Task 3 Step 5. Then build the same materials in a throwaway document left **open** in a new tab (`documents.InsertBaseDocument`). The user eyeballs the Node Editor: the Coat lobe is wired on OpenPBR, the samplers show `…_<UDIM>.png`, and there are two Bumps. Then run `KillDocument`.

- [ ] **Step 3: Live — tile render through the writer**

Re-run the five-quad probe from `docs/research/2026-10-29-redshift-udim.md` (same mesh, camera, `TEXTURETAG_PROJECTION_UVW` and render settings). Two things change:

- The material comes from `matwire_c4d.create_material_for_set(doc, folder, {"name": "rock", "normal_flipy": False, "channels": {"emission": "rock_Emit.<UDIM>.png"}, "ignored": [], "tiles": {}}, "rock", material="standard")`, so it goes through the real UV Context node.
- The tiles are **dim**: `rock_Emit.1001.png` = (64, 0, 0), `.1002` = (0, 64, 0), `.1011` = (0, 0, 64). They live in a fresh `<scratchpad>/udim writer probe` folder. In the research run, full-intensity tiles plus the lit default base colour saturated A and B to white. Dim tiles keep the dominant channel readable on top of the ~129 grey.

Expected: A red-dominant, B green-dominant, C and D grey (no tile colour), E blue-dominant. Record the pixel values in the research doc under a "Writer re-check (v1.42)" heading, then `KillDocument`.

- [ ] **Step 4: Live — resolver, Hub and Collect on a saved throwaway scene**

1. Save a throwaway document with one material whose sampler path is `tex/rock_BaseColor.<UDIM>.png` into a scratch folder containing `tex/rock_BaseColor.1001.png` and `tex/rock_BaseColor.1002.png`.
2. Run `textures.scan_all_texture_paths(doc)` → status `ok`.
3. Run `flows.scan_scene_assets(doc)` → exactly one row with `udim == {"tiles": [1001, 1002]}`.
4. Run `hub_ops._udim_files_in_scene(doc)` → the refusal naming `rock_BaseColor.<UDIM>.png`.
5. Rename the tiles away → `missing`.
6. `KillDocument`, then delete the scratch folder.

- [ ] **Step 5: Frozen oracle and host checks**

Find the c4dpy binary (`ls "/Applications/Maxon Cinema 4D 2026"*/`), then run, each with an absolute script path:

```bash
"<c4d dir>/c4dpy.app/Contents/MacOS/c4dpy" -g_console=true "$PWD/tests/c4d_runner/run_fixtures.py"
"<c4d dir>/c4dpy.app/Contents/MacOS/c4dpy" -g_console=true "$PWD/tests/c4d_runner/run_product_checks.py"
```

Expected: the oracle matches (no QC result changed) and the product checks pass. Paste the summary lines into the PR description.

- [ ] **Step 6: Release docs**

- Set `PLUGIN_VERSION = "1.42.0"`, and update every other `1.41.0` reference that names the *current* version in `README.md`, `ROADMAP.md` and `CLAUDE.md` (Project Overview + Current state). Leave history mentions alone.
- `docs/HISTORY.md`: add the v1.42.0 entry at the top, in the house narrative style. Cover:
  - The LOK trigger.
  - The measured Redshift facts.
  - `udim.py`.
  - The Painter naming (OCIO strip, OpenPBR names, Coat).
  - Tile grouping and the pattern as filename.
  - Coat weight 1.0.
  - The resolver.
  - The Hub fold and the refusals.
  - What stays out (per-tile Collect/Shrink, the UV-tile coverage check).
  - Test counts from Step 7.
- `CLAUDE.md` gotchas, under "Render, Redshift, host", one line each:
  - "Redshift resolves `<UDIM>`/`<UVTILE>` (any case) in `tex0/path`; there is no tile-mode port. `<UVTILE>` stands for `_u1_v1` including the underscore. A tile missing on disk renders black, silently. `GetAllAssetsNew` lists each existing tile as its own asset. UDIM row 1 (1011) is C4D UV v in [−1, 0] (measured 2026-10-29)."
  - "Coat ports: `coat_weight`/`coat_color`/`coat_roughness` on OpenPBR and Standard, normal on `geometry_coat_normal` / `coat_bump_input`; `coat_weight` is born 0."
  - Matwire in the Project Overview list: mention UDIM + Painter OpenPBR export.
- Spec "Estado": `LIVE-VERIFIED (C4D 2026.304) — pytest N, vitest M`.

- [ ] **Step 7: Final checks and commit**

Run:
- `python3.12 -m pytest -q`
- `cd web && npm test && npm run lint && npm run build && git status --short plugin/web` (expected: no diff after the build)

Record both counts.

```bash
git add -A plugin/sentinel/__init__.py README.md ROADMAP.md CLAUDE.md docs/HISTORY.md docs/superpowers/specs/2026-10-29-matwire-udim-design.md docs/research/2026-10-29-redshift-udim.md
git commit -m "release: Sentinel 1.42.0 — Matwire UDIM + export de Painter (OpenPBR, Coat)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Opening the PR is the user's call. Offer it; don't push without a yes.
