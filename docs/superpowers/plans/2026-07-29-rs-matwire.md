# RS Material from Folder (v1.32) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-wire Redshift Standard materials from a texture folder (channels recognized by filename, multi-set, studio-convention colorspaces), per the approved spec `docs/superpowers/specs/2026-07-29-rs-matwire-design.md` and the implementation research `docs/research/2026-07-29-matwire-implementations.md`.

**Architecture:** Pure recognition engine (`matwire.py`: suffix tables, GL/DX normals, set grouping, resolution variants, precedence, name dedupe — all pytest), a LIVE SPIKE that validates the `maxon.GraphDescription` wiring path against the running C4D before anything is built on it (nobody in the market uses it — v1.28 spike-first pattern), then the c4d writer + two ops (`matwire_preview`/`matwire_create`, server-derived, one undo), and a `MatwireSubview` in Tools reusing `hub/pick_path` for the folder picker.

**Tech Stack:** Python 3 (pure module + fake-c4d pytest), maxon node graph API (per spike outcome), Vite+React+TS SPA (vitest), bundle committed to `plugin/web/`.

**Branch:** `feat/rs-matwire` (create from `main` before Task 1).

## Global Constraints

- **Study-yes/copy-no**: Node Ninja / RS Node Tools / TexToMatO are unlicensed or all-rights-reserved — take FACTS (IDs, values, precedences) from `docs/research/2026-07-29-matwire-implementations.md`, never code.
- **RS node/port IDs (verified in 3 live implementations — the writer and its verification use EXACTLY these):** nodespace `com.redshift3d.redshift4c4d.class.nodespace`; nodes `com.redshift3d.redshift4c4d.nodes.core.standardmaterial | texturesampler | bumpmap | displacement | rsmathinv` and `com.redshift3d.redshift4c4d.node.output`; ports: `texturesampler.tex0` is a GROUP port with children `path` and `colorspace` (values `"RS_INPUT_COLORSPACE_RAW"` / `"RS_INPUT_COLORSPACE_SRGB"` — ALWAYS explicit, never the auto default), `texturesampler.outcolor`; `bumpmap.input`, `bumpmap.out`, `bumpmap.inputtype` (1 = tangent-space normal), `bumpmap.flipy`; `displacement.texmap`, `displacement.out`; output node ports `node.output.surface` / `node.output.displacement`; standardmaterial ports `base_color`, `refl_roughness`, `refl_isglossiness`, `metalness`, `refl_color`, `opacity_color`, `emission_color`, `emission_weight`, `bump_input`, `outcolor`. (Full port id prefix = the node id + `.` + port name.)
- **Wiring rules (spec)**: BaseColor/Emission sRGB, everything else RAW; emission also sets `emission_weight = 1.0`; Normal via bumpmap `inputtype=1` (+ `flipy=True` when the set only has a DX normal); Height via displacement node → output node's displacement port; Gloss → `refl_roughness` + `refl_isglossiness=True` (no invert node); Spec/Gloss wired ONLY if the set has neither Roughness nor Metalness; AO texture node CREATED but left unconnected; opacity → `opacity_color`.
- **Path URLs**: if the writer needs `maxon.Url`, build `"file:///" + path.replace("\\", "/")` BY HAND — `pathlib.as_uri()` percent-encodes spaces and C4D fails to open the texture (Node Ninja-documented bug).
- **Node layout**: never `CallCommand` arrange (only works with the Node Editor open); if the chosen API doesn't auto-place, set `net.maxon.node.base.xpos/ypos` explicitly.
- **Ops**: dialog-free (`_forbid_dialog`), `matwire_create` re-derives server-side from `{folder, exclude, names}` (v1.31 pattern), whole batch ONE undo. Folder picking reuses the EXISTING `hub/pick_path` op (modal LoadDialog made safe by the queue's per-request lock — precedent `HubPage.tsx` `postHubPickPath(true, ...)`).
- Redshift availability: probe before preview/create (`redshift_unavailable`); optionally per-node via `maxon.AssetInterface.FindLatestAsset(NodeTemplate, Id).IsPopulated()` (spike confirms).
- Extension allowlist: jpg/jpeg/png/tif/tiff/exr/hdr/tga/bmp/webp/tx.
- Suites: pytest `python3 -m pytest tests/ -q`; vitest `cd web && npx vitest run`; build `cd web && npm run build` (bundle committed).

## File Structure

- `plugin/sentinel/matwire.py` — NEW pure engine (imports `split_res_token` from `sentinel.assets`; no c4d).
- `docs/research/2026-07-29-matwire-spike.md` — NEW: Task 2's live spike findings (the writer's recipe).
- `plugin/sentinel/matwire_c4d.py` — NEW c4d writer adapter (API per spike).
- `plugin/sentinel/ui/panel_tools_ops.py` — 2 new ops.
- `web/src/lib/panelMatwire.ts` (+ test), `web/src/components/panel/MatwireSubview.tsx`, `web/src/components/panel/ToolsSection.tsx` (Authoring group), `web/src/lib/api.ts`, `web/src/types.ts`.
- Tests: `tests/test_matwire.py` (NEW), `tests/test_panel_tools_ops.py` (append), `web/src/lib/panelMatwire.test.ts`.

---

### Task 1: Pure engine — `matwire.py`

**Files:**
- Create: `plugin/sentinel/matwire.py`
- Test: `tests/test_matwire.py` (create)

**Interfaces (produced, consumed by Tasks 3-4):**
- `IMAGE_EXTENSIONS: frozenset` — the allowlist above.
- `scan_texture_sets(filenames) -> {"sets": [set], "ignored": [(filename, reason)]}` where each `set` = `{"name": str, "channels": {channel: filename}, "normal_flipy": bool, "ignored": [(filename, reason)]}`. Channels use canonical keys: `basecolor, roughness, metalness, normal, height, ao, opacity, emission, specular, glossiness`. Global `ignored` reasons: `bad_extension`, `no_channel`, `packed_orm`. Per-set reasons: `lower_resolution`, `duplicate_channel`, `pbr_wins`, `dx_superseded`.
- `channel_colorspace(channel) -> "srgb"|"raw"` — srgb ONLY for `basecolor`/`emission`.
- `dedupe_names(names, existing) -> {name: final_name}` — case-insensitive collision against `existing` and within the batch → `_02`, `_03`… suffixes.

- [ ] **Step 1: Write the failing tests** — create `tests/test_matwire.py`:

```python
import importlib

import pytest


@pytest.fixture
def matwire(sentinel_module):
    return importlib.import_module("sentinel.matwire")


def _scan(matwire, *names):
    return matwire.scan_texture_sets(list(names))


def test_single_set_full_pbr(matwire):
    out = _scan(
        matwire,
        "plaster_BaseColor.jpg", "plaster_Roughness.jpg", "plaster_Metalness.jpg",
        "plaster_Normal.png", "plaster_Height.exr", "plaster_AO.jpg",
        "plaster_Opacity.png", "plaster_Emission.jpg",
    )
    assert out["ignored"] == []
    assert len(out["sets"]) == 1
    s = out["sets"][0]
    assert s["name"] == "plaster"
    assert set(s["channels"]) == {
        "basecolor", "roughness", "metalness", "normal", "height",
        "ao", "opacity", "emission"}
    assert s["normal_flipy"] is False


def test_suffix_synonyms_and_map_tolerance(matwire):
    out = _scan(
        matwire,
        "wood_albedo.png",          # basecolor
        "wood_rgh.png",             # roughness
        "wood_mtl.png",             # metalness
        "wood_nmap.png",            # normal
        "wood_depth.png",           # height
        "wood_occ.png",             # ao
        "wood_cutout.png",          # opacity
        "wood_emit.png",            # emission
        "brick_RoughnessMap.png",   # glued Map suffix
        "brick_Base_Color Map.png", # space separator + split words
    )
    sets = {s["name"]: s for s in out["sets"]}
    assert set(sets["wood"]["channels"]) == {
        "basecolor", "roughness", "metalness", "normal", "height",
        "ao", "opacity", "emission"}
    assert set(sets["brick"]["channels"]) == {"roughness", "basecolor"}


def test_normal_gl_dx_precedence(matwire):
    # GL wins over DX and over generic; DX-only sets flipy.
    both = _scan(matwire, "a_Normal_GL.png", "a_Normal_DX.png", "a_BaseColor.png")
    s = both["sets"][0]
    assert s["channels"]["normal"] == "a_Normal_GL.png"
    assert s["normal_flipy"] is False
    assert ("a_Normal_DX.png", "dx_superseded") in s["ignored"]

    dx_only = _scan(matwire, "b_NormalDX.png", "b_BaseColor.png")
    s2 = dx_only["sets"][0]
    assert s2["channels"]["normal"] == "b_NormalDX.png"
    assert s2["normal_flipy"] is True


def test_multi_set_grouping_and_res_variants(matwire):
    out = _scan(
        matwire,
        "plaster_A_4k_BaseColor.jpg", "plaster_A_8k_BaseColor.jpg",
        "plaster_A_Roughness.jpg",
        "plaster_B_BaseColor.jpg", "plaster_B_Roughness.jpg",
    )
    sets = {s["name"]: s for s in out["sets"]}
    assert set(sets) == {"plaster_A", "plaster_B"}
    a = sets["plaster_A"]
    assert a["channels"]["basecolor"] == "plaster_A_8k_BaseColor.jpg"  # highest wins
    assert ("plaster_A_4k_BaseColor.jpg", "lower_resolution") in a["ignored"]


def test_no_token_variant_outranks_tokened(matwire):
    # v1.18 Shrink lesson: the original carries NO res token and outranks proxies.
    out = _scan(matwire, "wall_BaseColor.jpg", "wall_2k_BaseColor.jpg",
                "wall_Roughness.jpg")
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "wall_BaseColor.jpg"
    assert ("wall_2k_BaseColor.jpg", "lower_resolution") in s["ignored"]


def test_spec_gloss_precedence(matwire):
    # PBR present -> spec/gloss suppressed per-set.
    pbr = _scan(matwire, "m_BaseColor.jpg", "m_Roughness.jpg",
                "m_Specular.jpg", "m_Glossiness.jpg")
    s = pbr["sets"][0]
    assert "specular" not in s["channels"] and "glossiness" not in s["channels"]
    reasons = {f: r for f, r in s["ignored"]}
    assert reasons["m_Specular.jpg"] == "pbr_wins"
    assert reasons["m_Glossiness.jpg"] == "pbr_wins"
    # Legacy-only set keeps them.
    legacy = _scan(matwire, "n_Diffuse.jpg", "n_Specular.jpg", "n_Glossiness.jpg")
    assert set(legacy["sets"][0]["channels"]) == {"basecolor", "specular", "glossiness"}


def test_orm_and_unknown_and_extension(matwire):
    out = _scan(matwire, "x_ORM.png", "x_BaseColor.png", "readme.txt", "x_thumb.png")
    reasons = {f: r for f, r in out["ignored"]}
    assert reasons["x_ORM.png"] == "packed_orm"
    assert reasons["readme.txt"] == "bad_extension"
    assert reasons["x_thumb.png"] == "no_channel"
    assert set(out["sets"][0]["channels"]) == {"basecolor"}


def test_duplicate_channel_first_wins(matwire):
    out = _scan(matwire, "y_col.png", "y_diffuse.png", "y_rough.png")
    s = out["sets"][0]
    assert s["channels"]["basecolor"] == "y_col.png"
    assert ("y_diffuse.png", "duplicate_channel") in s["ignored"]


def test_glued_stem_never_false_positives(matwire):
    # Separator required: "protocol" must NOT end-match "col" -> basecolor.
    out = _scan(matwire, "protocol.png", "gunmetal.png")
    reasons = {f: r for f, r in out["ignored"]}
    assert reasons["protocol.png"] == "no_channel"
    assert reasons["gunmetal.png"] == "no_channel"


def test_rootless_pack_groups_under_default_root(matwire):
    out = matwire.scan_texture_sets(
        ["albedo.png", "roughness.png", "normal.png"], default_root="plaster")
    assert len(out["sets"]) == 1
    s = out["sets"][0]
    assert s["name"] == "plaster"
    assert set(s["channels"]) == {"basecolor", "roughness", "normal"}


def test_channel_colorspace_single_source(matwire):
    assert matwire.channel_colorspace("basecolor") == "srgb"
    assert matwire.channel_colorspace("emission") == "srgb"
    for ch in ("roughness", "metalness", "normal", "height", "ao",
               "opacity", "specular", "glossiness"):
        assert matwire.channel_colorspace(ch) == "raw"


def test_dedupe_names(matwire):
    assert matwire.dedupe_names(["wood", "wood", "Plaster"], ["plaster"]) == {
        "wood": "wood", "wood_02": "wood_02", "Plaster": "Plaster_02"}
```

Note on the dedupe test: `dedupe_names` takes the ORDERED list of set names and returns a mapping keyed by a unique per-input identity — since two inputs can share a name, return an ordered list instead: **adjust the interface to** `dedupe_names(names, existing) -> list[str]` (position-aligned final names) and rewrite that test accordingly:

```python
def test_dedupe_names(matwire):
    assert matwire.dedupe_names(["wood", "wood", "Plaster"], ["plaster"]) == [
        "wood", "wood_02", "Plaster_02"]
```

(Use the list form; drop the dict sketch.)

- [ ] **Step 2: Run to verify failure** — `python3 -m pytest tests/test_matwire.py -q` → FAIL.

- [ ] **Step 3: Implement** — create `plugin/sentinel/matwire.py`:

```python
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

_SRGB_CHANNELS = frozenset({"basecolor", "emission"})

# Separator REQUIRED before the variant (self-caught plan bug: an optional
# separator lets glued stems false-positive — "protocol" would end-match
# "col" → basecolor). A file named exactly like a variant ("albedo.png",
# root empty) is legal: rootless files group under ``default_root``.
_CHANNEL_RES = [
    (channel, re.compile(
        r"^(?P<root>.*?)(?:^|_)(?:" + "|".join(re.escape(v) for v in variants)
        + r")(?:_?map)?$"))
    for channel, variants in _CHANNEL_VARIANTS
]


def channel_colorspace(channel):
    return "srgb" if channel in _SRGB_CHANNELS else "raw"


def _normalize(stem):
    """Lowercase and collapse separators (space, ``-``, ``.``) to ``_``."""
    return re.sub(r"[\s\-.]+", "_", stem.strip().lower())


def _match_channel(norm_stem):
    """(channel, root) for the FIRST (most specific) matching channel.
    ``root`` may be "" (a file named exactly "albedo.png") — the caller
    groups those under ``default_root``."""
    for channel, rx in _CHANNEL_RES:
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


def scan_texture_sets(filenames, default_root="material"):
    """``default_root`` names the set for ROOTLESS files ("albedo.png") —
    the caller passes the folder's basename so bare-channel packs group
    naturally."""
    sets = {}
    order = []
    ignored = []

    for filename in filenames or []:
        base = os.path.basename(str(filename))
        stem, ext = os.path.splitext(base)
        if ext.lower() not in IMAGE_EXTENSIONS:
            ignored.append((filename, "bad_extension"))
            continue
        channel, root = _match_channel(_normalize(stem))
        if channel == "packed_orm":
            ignored.append((filename, "packed_orm"))
            continue
        if channel is None:
            ignored.append((filename, "no_channel"))
            continue
        root_key, px = _root_and_px(root)
        if not root_key:
            root_key = str(default_root) or "material"
        if root_key not in sets:
            sets[root_key] = {"candidates": {}, "ignored": []}
            order.append(root_key)
        sets[root_key]["candidates"].setdefault(channel, []).append((filename, px))

    out_sets = []
    for root_key in order:
        data = sets[root_key]
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

    return {"sets": out_sets, "ignored": ignored}


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
```

Implementer note: `test_duplicate_channel_first_wins` requires FIRST-in wins among equal ranks — `sorted` is stable, and both entries have px None → equal rank, first listed stays first. The GL/DX ignored-attribution: when GL and DX coexist, the DX FILE must land in `ignored` with `dx_superseded` (the code pops `normal_dx` from channels — make sure its ignored entry records the FILENAME, as written). Trace `test_normal_gl_dx_precedence` by hand before running. If `split_res_token`'s actual signature differs (read `plugin/sentinel/assets.py` FIRST), adapt `_root_and_px` to it — the tests define the behavior, not the sketch.

- [ ] **Step 4: Run** — `python3 -m pytest tests/test_matwire.py -q` → PASS; full suite → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/matwire.py tests/test_matwire.py
git commit -m "feat(matwire): pure texture-set recognition engine (suffix tables, GL/DX, variants, precedences)"
```

---

### Task 2: LIVE SPIKE — validate the RS wiring path in the running C4D

**Files:**
- Create: `docs/research/2026-07-29-matwire-spike.md` (findings = the writer's recipe)

**Interfaces:**
- Produces: a written, live-verified recipe Task 3 follows verbatim: which API builds the graph (`maxon.GraphDescription.ApplyDescription` preferred; imperative `GraphNode` + `BeginTransaction` fallback), exact call shapes for: creating an RS node material, adding a texturesampler with `tex0.path` + `tex0.colorspace`, connecting to `standardmaterial.base_color`, bumpmap chain (`inputtype=1`, `flipy`), displacement → output-node displacement port, `refl_isglossiness` bool, `emission_weight`, node positioning, and the Redshift-availability probe. Each recipe item marked VERIFIED with the live evidence.

- [ ] **Step 1:** Confirm C4D reachable (`mcp__cinema4d__ping` or `exec_python` via the batch op). If unreachable, STOP and report BLOCKED (this task cannot run headless).
- [ ] **Step 2:** In a THROWAWAY document (never the user's scene; create via `c4d.documents.BaseDocument()` + insert, and remove it at the end), attempt the GraphDescription path: build one RS Standard material with a basecolor texturesampler (sRGB, a real dummy file path WITH A SPACE in the name to exercise the URL gotcha), a normal→bumpmap chain, a height→displacement→output chain, `refl_isglossiness=True`, `emission_weight=1.0`. Read the graph back (`list_graph_nodes`-style traversal or `GetGraph()` iteration) and verify every node/port id matches the Global Constraints catalog.
- [ ] **Step 3:** If GraphDescription cannot express something (group port children, output-node displacement, bools), fall back to imperative GraphNode wiring for THAT piece and record the exact working calls. Also verify: node auto-layout (are positions sane without the editor open?), and `FindLatestAsset(...).IsPopulated()` as the availability probe.
- [ ] **Step 4:** Write `docs/research/2026-07-29-matwire-spike.md` with the full recipe + evidence (code snippets that RAN, read-back values). Clean up the throwaway document.
- [ ] **Step 5: Commit**

```bash
git add docs/research/2026-07-29-matwire-spike.md
git commit -m "docs: matwire live spike — verified RS graph-building recipe (GraphDescription vs GraphNode)"
```

---

### Task 3: Writer + ops — `matwire_c4d.py` + `matwire_preview`/`matwire_create`

**Files:**
- Create: `plugin/sentinel/matwire_c4d.py`
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py` (append), `tests/test_matwire.py` (append pure parts)

**Interfaces:**
- Consumes: Task 1 engine, Task 2 recipe (read `docs/research/2026-07-29-matwire-spike.md` FIRST and follow it verbatim — it is live-verified truth; the plan deliberately does not duplicate its call shapes).
- Produces: `matwire_c4d.redshift_available() -> bool`; `matwire_c4d.create_material_for_set(doc, folder, tex_set, name) -> {"ok": bool, "material_name": str, "error": str|None}` — builds ONE RS Standard material per the recipe (per-channel wiring rules from Global Constraints; files resolved as `os.path.join(folder, filename)`); caller owns the undo block.
- Produces ops:
  - `panel/tools/matwire_preview` — payload `{"folder": str}` → `{"ok": True, "sets": [{"name","channels":[{"channel","file","colorspace"}],"normal_flipy","ignored":[[file,reason]]}], "ignored": [...], "names": [...dedeuped defaults]}` or errors `no_document|bad_folder|no_sets|redshift_unavailable`. Folder listing = `os.listdir` (non-recursive, v1), sorted for determinism; `scan_texture_sets(files, default_root=os.path.basename(folder.rstrip(os.sep)))` so bare-channel packs (`albedo.png`…) group under the folder's name.
  - `panel/tools/matwire_create` — payload `{"folder", "exclude": [set_name], "names": {set_name: custom}}` → re-derives the scan server-side, dedupes final names against the Material Manager, wires each included set inside ONE `doc.StartUndo()/EndUndo()` (per-set failures collected in `errors`, never abort the batch), `EventAdd`; returns `{"ok": True, "created": N, "materials": [names], "errors": [[set, reason]]}`.
- Both dialog-free; `redshift_available()` gate first (error `redshift_unavailable`).

- [ ] **Step 1:** Failing tests: pure preview-shaping helpers in `test_matwire.py` (channels list with colorspace annotation — add a pure `preview_payload(scan_result, existing_names)` helper to `matwire.py` if shaping grows beyond trivial); op tests in `test_panel_tools_ops.py` in the file's idiom — routing, `bad_folder` (nonexistent path), `no_sets` (folder of txt files — use `tmp_path`), exclude/names honored, re-derivation (poisoned payload rows ignored), one StartUndo/EndUndo, per-set error collection (monkeypatch `matwire_c4d.create_material_for_set` to fail for one set), `redshift_unavailable` gate (monkeypatch `redshift_available` → False), `_forbid_dialog` both routes.
- [ ] **Step 2:** Run to verify failure.
- [ ] **Step 3:** Implement writer per the spike recipe + ops per the interfaces (registry entries `panel/tools/matwire_preview` / `panel/tools/matwire_create`).
- [ ] **Step 4:** `python3 -m pytest tests/test_matwire.py tests/test_panel_tools_ops.py -q` green; full suite green.
- [ ] **Step 5: Commit**

```bash
git add plugin/sentinel/matwire_c4d.py plugin/sentinel/ui/panel_tools_ops.py \
        plugin/sentinel/matwire.py tests/test_matwire.py tests/test_panel_tools_ops.py
git commit -m "feat(matwire): RS writer per live-spiked recipe + preview/create ops (server-derived, one undo)"
```

---

### Task 4: SPA — `MatwireSubview` + Authoring group

**Files:**
- Create: `web/src/lib/panelMatwire.ts`, `web/src/lib/panelMatwire.test.ts`, `web/src/components/panel/MatwireSubview.tsx`
- Modify: `web/src/components/panel/ToolsSection.tsx`, `web/src/lib/api.ts`, `web/src/types.ts`

**Interfaces:**
- `panelMatwire.ts`: `matwireToast(r)` — success `Created 3 RS material(s).` (+ ` (N set(s) failed)` warn variant when errors non-empty); error copys `no_sets: "No texture sets recognized in that folder."`, `bad_folder: "That folder doesn't exist."`, `redshift_unavailable: "Redshift is not available."`, `nothing_selected: "All sets are excluded."`, default generic. Pure ignored-reason labels map (`lower_resolution: "lower resolution"`, `packed_orm: "packed ORM/ARM (v2)"`, `pbr_wins: "PBR maps take precedence"`, `dx_superseded: "GL normal preferred"`, `no_channel: "unrecognized"`, `bad_extension: "not an image"`).
- `api.ts`: `fetchMatwirePreview(folder)`, `postMatwireCreate(folder, exclude, names)` typed against the REAL op shapes (mock-shape law); types in `types.ts`.
- `ToolsSection`: sub-router grows `"matwire"`; the **Naming** group is RENAMED **Authoring** and holds `Batch Rename →` + `Material from Folder →`.
- `MatwireSubview` (self-contained): folder field + **Browse** button → `postHubPickPath(true, "Choose texture folder")` (EXISTS in api.ts — reuse, do not duplicate) → on pick, set folder + fetch preview; per-set card: include checkbox, editable name (default from op's deduped `names`), channel rows `channel · filename · colorspace-chip`, folded ignored with reason labels; global ignored folded at the bottom; **Create N materials** primary (N = included count; disabled while applying or none included) → `postMatwireCreate` → `matwireToast` → `restoreFocus()` (lib/focus.ts) — no 2s poll here (disk folder, not scene state; refresh = re-pick or a manual Refresh button); `← Tools` with `restoreFocus()`. Inline states: no folder yet ("Pick a folder to scan"), op errors inline (not toasts) like RenameSubview's `PREVIEW_EMPTY_COPY` pattern.
- [ ] **Step 1:** Failing vitest — toast copys (success/failed-sets warn variant/errors) + ignored-reason label map completeness (every reason the engine can emit has a label — pin the list).
- [ ] **Step 2:** vitest fails.
- [ ] **Step 3:** Implement (mirror RenameSubview's structure/idioms; SegmentedControl not needed here).
- [ ] **Step 4:** vitest green; `npm run build` OK; full pytest untouched-green.
- [ ] **Step 5: Commit**

```bash
git add web/src plugin/web
git commit -m "feat(panel): Material from Folder sub-view (Authoring group, server-driven preview)"
```

---

### Task 5: Version bump, docs, full suites

**Files:**
- Modify: `plugin/sentinel/__init__.py` (`PLUGIN_VERSION = "1.32.0"`), `CLAUDE.md` (header + top entries, house style, "PENDIENTE verificación live" marker + the spec's live matrix), `docs/superpowers/specs/2026-07-29-rs-matwire-design.md` (Estado → implementado en rama, pendiente live)

**Steps:**
- [ ] **Step 1:** Bump + entries covering: motor puro (tablas + GL/DX + variantes + precedencias + dedupe), spike live del wiring (qué API ganó y por qué), writer con la convención del estudio (colorspaces explícitos, emission_weight, refl_isglossiness, AO sin conectar — decisión contra-mercado), ops server-derived, sub-vista con pick_path reutilizado, procedencia del research (estudiar-sí/copiar-no), arco v1.33 siguiente, fixes de review del ledger.
- [ ] **Step 2:** Full pytest + vitest — real counts into CLAUDE.md.
- [ ] **Step 3: Commit**

```bash
git add plugin/sentinel/__init__.py CLAUDE.md docs/superpowers/specs/2026-07-29-rs-matwire-design.md
git commit -m "docs: v1.32.0 — RS Material from Folder (pending live verification)"
```

---

## After the plan (session-level)

1. Final whole-branch adversarial review; fix Critical/Important.
2. Live verification (sync.sh + C4D restart + MCP + user eyeball), spec matrix: pack real single-set → material RS con nodos/colorspaces correctos (node editor + render); multi-set → N materiales; legacy spec/gloss → `refl_isglossiness`; variantes 4k/8k → gana 8k visiblemente; DX-only → flipy; AO presente sin conectar; emission visible (weight=1); un Cmd+Z revierte el lote; Browse con el picker nativo; ruta con espacios.
3. Merge `--no-ff` tras confirmación del usuario; memoria; siguiente = v1.33 (Recall/template — brainstorm propio).
