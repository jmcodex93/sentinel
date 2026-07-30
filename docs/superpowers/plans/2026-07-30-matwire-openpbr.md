# Matwire OpenPBR (v1.34) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RS Material from Folder creates **OpenPBR** materials by default, with Standard still available from a selector, per `docs/superpowers/specs/2026-07-30-matwire-openpbr-design.md`.

**Architecture:** The BRDF's port ids move out of the writer's inline strings into **three parallel tables keyed by material type** (node id, channel→port, emission amount). Everything upstream of the BRDF (samplers, colorspaces, ORM splitter, Color Correct, AO layer, UV Context/UniversalXform, leftovers) and downstream (output node, displacement) is untouched. Exactly two branches diverge by type: glossiness (native bool vs interposed `rsmathinv`) and the emission amount parameter.

**Tech Stack:** Python (pure engine + fake-c4d pytest harness), `maxon.GraphDescription` writer, React/TS SPA with vitest, committed bundle.

**Branch:** `feat/matwire-openpbr` (create from `main` before Task 1).

## Global Constraints

- **Default material type is `"openpbr"`.** `"standard"` is reachable only via the selector. No `sentinel_rules.json` key in this release (explicit YAGNI — see spec "Decisiones cerradas" 1).
- **Unknown material strings normalize to the default, never raise** — same boundary-validation contract as `_matwire_projection`.
- **Honest degradation:** when the OpenPBR node is unavailable the selector is disabled with an inline reason and materials are built as Standard. The *effective* value is derived, never a mutation of the artist's choice (v1.33 `effectiveProjection` lesson).
- **The preview may not promise a wiring the writer won't make** (ORM row v1.32.1, AO row v1.33). Both the material type and the glossiness destination are stamped from the same source the writer uses.
- **Colorspaces and `flipy` stay ALWAYS explicit**; node defaults are never relied upon except where measured (the `rscolorcorrection` identity).
- **The whole graph is built BEFORE `doc.InsertMaterial`** — one Cmd+Z reverts a batch. Nothing in this plan may reorder that.
- **`material = "standard"` must produce the v1.33 graph unchanged** (no-regression).
- Suites: `python3 -m pytest tests/ -q`; `cd web && npx vitest run`; build `cd web && npm run build`. Baselines entering this plan: pytest 1123, vitest 201.
- Plugin Python only loads on a **full C4D restart**; `./sync.sh` copies the plugin into the active prefs folder.

## File Structure

- `plugin/sentinel/matwire.py` — pure: `gloss_destination(channels, material)`, the single source shared by the preview row and the writer (mirrors `ao_destination`).
- `plugin/sentinel/matwire_c4d.py` — the BRDF tables, `openpbr_available()`, and the `material`-aware `build_description` / `build_orm_plan` / `_apply_orm_plan` / `create_material_for_set`.
- `plugin/sentinel/ui/panel_tools_ops.py` — `_matwire_material` boundary normalizer, `openpbr_available` on the preview, `material` threaded to **both** create call sites.
- `docs/research/2026-07-30-openpbr-spike.md` — NEW: the live measurements Task 1 produces.
- SPA: `web/src/components/panel/MatwireSubview.tsx`, `web/src/lib/panelMatwire.ts` (+ `.test.ts`), `web/src/lib/api.ts`, `web/src/types.ts`.
- Tests: `tests/test_matwire.py`, `tests/test_panel_tools_ops.py`.

---

### Task 1: Live spike (BLOCKING — the writer cannot be written without it)

**Files:**
- Create: `docs/research/2026-07-30-openpbr-spike.md`

**Interfaces:**
- Produces: two exact code lines Task 2 copies verbatim — the `BRDF_EMISSION_AMOUNT` dict and the `rsmathinv` port id constants — plus a go/no-go on `geometry_normal`.

Run every probe through `mcp__cinema4d__batch` `exec_python` against the user's live C4D 2026.303. Build materials on a `c4d.documents.BaseDocument()` you create locally, or on a `BaseMaterial` you never insert; **never leave anything in the user's active document** (remove any material you insert before finishing). If C4D is unreachable, report **BLOCKED** — do not guess values.

- [ ] **Step 1: `geometry_normal` — the high-risk unknown**

In Standard the `bumpmap` node feeds `bump_input`. OpenPBR's port is called *normal*. Verify by RENDER, not by reading parameters: a wrong wiring still produces a visible material, just with wrong relief.

Build two materials from the same normal map — one Standard (`bump_input`), one OpenPBR (`geometry_normal`) — each with a flat mid-grey base color and no roughness map. Render both at 100x100 on a sphere lit from one side, using the pattern already proven in `docs/research/2026-07-30-uvcontext-and-graph-cost.md` (clone the active doc's RenderData, `RDATA_FRAMESEQUENCE_CURRENTFRAME`, `RENDERFLAGS_EXTERNAL`, read pixels with `GetPixel`).

Then render the OpenPBR material a second time with the bump node DISCONNECTED. Record the pixel-difference counts.

Expected: connected vs disconnected differ substantially (the normal map is doing something), and the Standard/OpenPBR pair show relief in the same direction. Record the numbers. If the OpenPBR connected/disconnected pair is pixel-identical, the port does not accept a bump node — report that as a **finding that changes the design** and stop.

- [ ] **Step 2: `emission_luminance` — find the value equivalent to Standard's `emission_weight = 1.0`**

`emission_luminance` is luminance, not a 0-1 weight, so 1.0 is almost certainly wrong. Render a Standard material with an emission texture and `emission_weight = 1.0`, then render OpenPBR materials with the same texture sweeping `emission_luminance` over `[1, 10, 100, 1000]`. Compare mean pixel value against the Standard render and pick the closest.

Record the sweep table and the chosen value, then write the exact line Task 2 will copy:

```python
BRDF_EMISSION_AMOUNT = {"standard": 1.0, "openpbr": <chosen>}
```

If no value in the sweep lands close, widen the sweep rather than picking the least-bad — and record that the units are not comparable, which is itself the finding.

- [ ] **Step 3: `rsmathinv` — port ids and that it inverts**

Probe the node's ports:

```python
import c4d, maxon
RS = 'com.redshift3d.redshift4c4d.nodes.core.'
mat = c4d.BaseMaterial(c4d.Mmaterial)
g = maxon.GraphDescription.GetGraph(mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)
maxon.GraphDescription.ApplyDescription(g, {'$type': '#' + RS + 'rsmathinv'})
n = [x for x in g.GetViewRoot().GetInnerNodes(mask=maxon.NODE_KIND.NODE, includeThis=False)
     if 'rsmathinv' in str(x.GetValue('net.maxon.node.attribute.assetid'))][0]
print('IN ', [str(p.GetId()) for p in n.GetInputs().GetChildren()])
print('OUT', [str(p.GetId()) for p in n.GetOutputs().GetChildren()])
```

If `rsmathinv` is not available, probe `rsmathinvcolor` and `rscolorinvert` and record which exists. Record the exact input and output ids as the constants Task 2 will use.

- [ ] **Step 4: displacement unchanged**

Build an OpenPBR material with a height map through the existing `_RS_OUTPUT.displacement` branch and confirm the displacement node is present and connected to the output. Record pass/fail.

- [ ] **Step 5: Write the spike doc and commit**

Create `docs/research/2026-07-30-openpbr-spike.md` with one section per step: the question, the exact probe, the raw numbers, and the verdict. Include the two literal code lines (emission dict, invert port ids) under a heading "Constantes que consume el writer". State plainly anything that did NOT work.

```bash
git add docs/research/2026-07-30-openpbr-spike.md
git commit -m "docs: spike live OpenPBR — geometry_normal, emission_luminance, rsmathinv, displacement"
```

### Task 2: Engine — BRDF tables, per-type wiring, glossiness invert

**Files:**
- Modify: `plugin/sentinel/matwire.py` (add `gloss_destination`)
- Modify: `plugin/sentinel/matwire_c4d.py`
- Test: `tests/test_matwire.py` (append)

**Interfaces:**
- Consumes: from Task 1, the `BRDF_EMISSION_AMOUNT` line and the `rsmathinv` input/output port ids.
- Produces:
  - `matwire.gloss_destination(channels, material) -> None | "roughness_isglossiness" | "roughness_inverted"`
  - `matwire_c4d.MATERIAL_TYPES: tuple` — `("openpbr", "standard")`, first entry is the default
  - `matwire_c4d.DEFAULT_MATERIAL: str` — `"openpbr"`
  - `matwire_c4d.openpbr_available() -> bool`
  - `matwire_c4d.build_description(folder, tex_set, multiply_ao=False, material=DEFAULT_MATERIAL)`
  - `matwire_c4d.build_orm_plan(folder, tex_set, material=DEFAULT_MATERIAL)`
  - `matwire_c4d.create_material_for_set(..., material=DEFAULT_MATERIAL)`

- [ ] **Step 1: Write the failing pure-engine test for `gloss_destination`**

Append to `tests/test_matwire.py`:

```python
class TestGlossDestination:
    """Single source for the preview row and the writer — the row can never
    promise a wiring the writer won't make (ao_destination discipline)."""

    def test_no_glossiness_channel_has_no_destination(self, matwire):
        assert matwire.gloss_destination({"roughness": "r.png"}, "openpbr") is None

    def test_standard_uses_the_native_bool(self, matwire):
        assert matwire.gloss_destination({"glossiness": "g.png"}, "standard") \
            == "roughness_isglossiness"

    def test_openpbr_needs_an_invert_node(self, matwire):
        # OpenPBR has no specular_isglossiness port (measured live), so the
        # only correct wiring is an interposed invert.
        assert matwire.gloss_destination({"glossiness": "g.png"}, "openpbr") \
            == "roughness_inverted"
```

Use the same `matwire` fixture the neighbouring classes in this file use.

- [ ] **Step 2: Run it — expect failure**

Run: `python3 -m pytest tests/test_matwire.py -q -k GlossDestination`
Expected: FAIL, `AttributeError: module 'sentinel.matwire' has no attribute 'gloss_destination'`

- [ ] **Step 3: Implement `gloss_destination`**

Add to `plugin/sentinel/matwire.py`, directly after `ao_destination`:

```python
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
```

- [ ] **Step 4: Run it — expect pass**

Run: `python3 -m pytest tests/test_matwire.py -q -k GlossDestination`
Expected: 3 passed

- [ ] **Step 5: Write the failing writer tests**

Append to `tests/test_matwire.py`. `_flat_keys` collects every dict key recursively so a test can assert on port ids wherever they sit in the nesting:

```python
def _flat_keys(node):
    keys = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(key)
            keys.extend(_flat_keys(value))
    return keys


class TestMaterialTypes:
    """OpenPBR is the default; Standard stays reachable and unchanged."""

    def test_default_is_openpbr(self, matwire_c4d):
        assert matwire_c4d.DEFAULT_MATERIAL == "openpbr"
        assert matwire_c4d.MATERIAL_TYPES[0] == "openpbr"
        assert set(matwire_c4d.MATERIAL_TYPES) == {"openpbr", "standard"}

    def test_openpbr_ports_replace_the_standard_ones(self, matwire_c4d):
        tex_set = {"name": "p", "normal_flipy": False, "channels": {
            "basecolor": "c.png", "roughness": "r.png", "metalness": "m.png",
            "opacity": "o.png", "normal": "n.png"}}
        desc, _ = matwire_c4d.build_description("/t", tex_set,
                                                material="openpbr")
        keys = _flat_keys(desc)
        joined = " ".join(keys)
        assert "openpbrmaterial" in joined
        assert "standardmaterial" not in joined, \
            "a Standard port id leaked into the OpenPBR graph"
        for port in ("specular_roughness", "base_metalness",
                     "geometry_opacity", "geometry_normal", "base_color"):
            assert any(k.endswith("openpbrmaterial." + port) for k in keys), \
                "missing OpenPBR port " + port

    def test_standard_graph_is_unchanged(self, matwire_c4d):
        """No-regression: asking for Standard yields the v1.33 wiring."""
        tex_set = {"name": "p", "normal_flipy": False, "channels": {
            "basecolor": "c.png", "roughness": "r.png", "metalness": "m.png"}}
        desc, _ = matwire_c4d.build_description("/t", tex_set,
                                                material="standard")
        joined = " ".join(_flat_keys(desc))
        assert "standardmaterial.refl_roughness" in joined
        assert "standardmaterial.metalness" in joined
        assert "openpbr" not in joined

    def test_glossiness_openpbr_goes_through_an_invert(self, matwire_c4d):
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"glossiness": "g.png"}}
        desc, _ = matwire_c4d.build_description("/t", tex_set,
                                                material="openpbr")
        keys = _flat_keys(desc)
        assert any("rsmathinv" in k for k in keys), \
            "OpenPBR gloss must be inverted — it has no isglossiness port"
        assert not any(k.endswith("refl_isglossiness") for k in keys)
        assert any(k.endswith("openpbrmaterial.specular_roughness")
                   for k in keys)

    def test_glossiness_standard_uses_the_bool_and_no_invert(self,
                                                             matwire_c4d):
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"glossiness": "g.png"}}
        desc, _ = matwire_c4d.build_description("/t", tex_set,
                                                material="standard")
        keys = _flat_keys(desc)
        assert any(k.endswith("refl_isglossiness") for k in keys)
        assert not any("rsmathinv" in k for k in keys), \
            "the native bool makes the invert node pure bloat"

    def test_emission_amount_is_per_type(self, matwire_c4d):
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"emission": "e.png"}}
        for material, port in (("standard", "emission_weight"),
                               ("openpbr", "emission_luminance")):
            desc, _ = matwire_c4d.build_description("/t", tex_set,
                                                    material=material)
            keys = _flat_keys(desc)
            assert any(k.endswith(port) for k in keys), \
                "%s must write %s" % (material, port)
            # The amount is ALWAYS written: both ports are born at 0
            # (measured), so an unwritten one ships invisible emission.
            assert matwire_c4d.BRDF_EMISSION_AMOUNT[material] > 0

    def test_orm_splitter_targets_the_active_brdf(self, matwire_c4d):
        tex_set = {"name": "p", "normal_flipy": False,
                   "channels": {"packed_orm": "orm.png"}}
        plan = matwire_c4d.build_orm_plan("/t", tex_set, material="openpbr")
        targets = [in_id for _, in_id in plan["connects"]]
        assert targets, "the splitter must contribute on a bare ORM set"
        for target in targets:
            assert "openpbrmaterial" in target, \
                "splitter still wired to standardmaterial: " + target
        assert any(t.endswith("specular_roughness") for t in targets)
        assert any(t.endswith("base_metalness") for t in targets)
```

Drop the confusing `__wrapped__` clause from `test_standard_graph_is_unchanged` — keep only the three concrete assertions below it.

- [ ] **Step 6: Run them — expect failure**

Run: `python3 -m pytest tests/test_matwire.py -q -k MaterialTypes`
Expected: FAIL (no `DEFAULT_MATERIAL`, `build_description` takes no `material`)

- [ ] **Step 7: Add the tables to `matwire_c4d.py`**

Insert after `_RS_UVCTX` (near the other module constants). Substitute the emission value and the invert port ids with the exact ones Task 1 recorded:

```python
_RS_INVERT = _RS_CORE + "rsmathinv"          # port ids from the Task 1 spike

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
#: interchangeable: Standard's is a 0-1 weight, OpenPBR's is a luminance.
#: The OpenPBR value was measured against Standard's look in the Task 1
#: spike (docs/research/2026-07-30-openpbr-spike.md).
BRDF_EMISSION_AMOUNT = {"standard": 1.0, "openpbr": <value from Task 1 §2>}


def _brdf(material):
    """(node id, port table) for a material type, defaulting on anything
    unknown. The ops layer normalizes at the boundary, so this default is
    belt-and-braces rather than the contract."""
    key = material if material in BRDF_NODES else DEFAULT_MATERIAL
    return BRDF_NODES[key], BRDF_PORTS[key], key
```

- [ ] **Step 8: Add `openpbr_available()`**

Insert directly after `uvcontext_available` in `matwire_c4d.py`:

```python
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
```

- [ ] **Step 9: Make `build_description` type-aware**

In `build_description`, change the signature and replace the hardcoded prefix and the four diverging branches. Keep every existing comment; only the marked lines change.

Signature:

```python
def build_description(folder, tex_set, multiply_ao=False,
                      material=DEFAULT_MATERIAL):
```

Replace `sm = "#<" + _RS_CORE + "standardmaterial."` with:

```python
    node_id, ports, material = _brdf(material)
    sm = "#<" + node_id + "."
```

Replace `material = {"$type": "#" + _RS_CORE + "standardmaterial"}` with (rename the local so it does not shadow the new parameter):

```python
    brdf = {"$type": "#" + node_id}
```

…and rename every subsequent `material[...] = ...` in this function to `brdf[...] = ...`, and the `"#<" + _RS_OUTPUT + ".surface": material` entry to `: brdf`.

Replace each channel key with its table lookup:

```python
    brdf[sm + ports["basecolor"]] = base_branch
    ...
    brdf[sm + ports["roughness"]] = _sampler(path("roughness"), _rs_colorspace("roughness"))
    ...
    brdf[sm + ports["metalness"]] = _sampler(path("metalness"), _rs_colorspace("metalness"))
    ...
    brdf[sm + ports["bump"]] = bump
    ...
    brdf[sm + ports["opacity"]] = _sampler(path("opacity"), _rs_colorspace("opacity"))
    ...
    brdf[sm + ports["specular"]] = _sampler(path("specular"), _rs_colorspace("specular"))
```

Emission becomes:

```python
    if "emission" in channels:
        brdf[sm + ports["emission_color"]] = _sampler(
            path("emission"), _rs_colorspace("emission"))
        # ALWAYS written: both amount ports are born at 0 (measured), so
        # leaving it default ships invisible emission — the v1.32
        # differential correction, now per BRDF (the two values are NOT
        # interchangeable: weight vs luminance).
        brdf[sm + ports["emission_amount"]] = BRDF_EMISSION_AMOUNT[material]
```

Glossiness becomes:

```python
    gloss_dest = gloss_destination(channels, material)
    if gloss_dest is not None:
        gloss = _sampler(path("glossiness"), _rs_colorspace("glossiness"))
        if gloss_dest == "roughness_inverted":
            # OpenPBR has no isglossiness port (measured), so the map is
            # inverted into roughness. This is the node v1.32 catalogued
            # and deliberately left unused — the native bool made it bloat
            # THERE; here it is the only correct wiring.
            gloss = {"$type": "#" + _RS_INVERT,
                     "#<" + _RS_INVERT + ".<input port from Task 1>": gloss}
        brdf[sm + ports["roughness"]] = gloss
        if gloss_dest == "roughness_isglossiness":
            brdf[sm + "refl_isglossiness"] = True  # Standard only
```

Add the import at the top of the file: extend the existing `from sentinel.matwire import ...` line with `gloss_destination`.

- [ ] **Step 10: Make the ORM splitter target the active BRDF**

`build_orm_plan` and `_apply_orm_plan` both hardcode `standardmaterial`; on OpenPBR the node lookup would fail and take the whole material down. In `build_orm_plan`, add the parameter and use the table:

```python
def build_orm_plan(folder, tex_set, material=DEFAULT_MATERIAL):
```

```python
    node_id, ports, _ = _brdf(material)
    ...
    if "roughness" in contributes:
        connects.append((split + ".outg", node_id + "." + ports["roughness"]))
    if "metalness" in contributes:
        connects.append((split + ".outb", node_id + "." + ports["metalness"]))
```

In `_apply_orm_plan`, the node is currently found by the literal `"standardmaterial"`. Add the BRDF node id to the plan so the apply does not need to know the type:

```python
    return {
        "splitter_desc": {...},
        "connects": connects,
        "brdf_kind": node_id.rsplit(".", 1)[-1],   # "openpbrmaterial" | "standardmaterial"
    }
```

…and in the empty-`connects` early-return branch add `"brdf_kind": node_id.rsplit(".", 1)[-1]` too, so the shape is uniform. Then in `_apply_orm_plan` replace `elif "standardmaterial" in asset_id:` with:

```python
        elif plan["brdf_kind"] in asset_id:
```

- [ ] **Step 11: Layout and titles for the two new node kinds**

In `_LAYOUT_COLS` add `"openpbrmaterial": 0.0,` beside `"standardmaterial": 0.0,` and `"rsmathinv": -300.0,` beside the other intermediary nodes (rows are keyed by COLUMN, so cohabitation never stacks). In `NODE_TITLES` add `"rsmathinv": "Gloss → Roughness",`.

- [ ] **Step 12: Thread `material` through `create_material_for_set`**

```python
def create_material_for_set(doc, folder, tex_set, name, leftover_files=None,
                            multiply_ao=False, projection="uv",
                            material=DEFAULT_MATERIAL):
```

Inside, pass it to both builders:

```python
        desc, ao_desc = build_description(folder, tex_set,
                                          multiply_ao=multiply_ao,
                                          material=material)
        orm_plan = build_orm_plan(folder, tex_set, material=material)
```

Extend the docstring's `projection` paragraph with one sentence naming `material` and its default.

- [ ] **Step 13: Run the suites**

Run: `python3 -m pytest tests/ -q`
Expected: all pass, count 1123 + the new tests.

- [ ] **Step 14: Mutation-check the two riskiest lines**

These verify the tests bite rather than merely pass:

```bash
# 1. ORM splitter reverted to the hardcoded Standard port
#    -> test_orm_splitter_targets_the_active_brdf must FAIL
# 2. gloss_destination always returning "roughness_isglossiness"
#    -> test_glossiness_openpbr_goes_through_an_invert must FAIL
```

Apply each mutation, run `python3 -m pytest tests/test_matwire.py -q`, confirm the named test fails, then revert. Report both results.

- [ ] **Step 15: Commit**

```bash
git add plugin/sentinel/matwire.py plugin/sentinel/matwire_c4d.py tests/test_matwire.py
git commit -m "feat(matwire): OpenPBR BRDF tables, per-type wiring, glossiness invert"
```

### Task 3: Ops — boundary normalization and threading

**Files:**
- Modify: `plugin/sentinel/ui/panel_tools_ops.py`
- Test: `tests/test_panel_tools_ops.py` (append)

**Interfaces:**
- Consumes: `matwire_c4d.MATERIAL_TYPES`, `DEFAULT_MATERIAL`, `openpbr_available`, `create_material_for_set(..., material=)`.
- Produces: `matwire_preview` response gains `openpbr_available: bool`; `matwire_create` accepts `{"material": "openpbr"|"standard"}`.

- [ ] **Step 1: Write the failing op tests**

Append to `tests/test_panel_tools_ops.py`, following the fixtures the neighbouring matwire tests use:

```python
class TestMatwireMaterialType:
    def test_unknown_material_normalizes_to_the_default(self, ops):
        assert ops._matwire_material({"material": "nonsense"}) == "openpbr"
        assert ops._matwire_material({}) == "openpbr"
        assert ops._matwire_material({"material": 7}) == "openpbr"

    def test_known_values_survive_case_and_whitespace(self, ops):
        assert ops._matwire_material({"material": " Standard "}) == "standard"
        assert ops._matwire_material({"material": "OPENPBR"}) == "openpbr"

    def test_preview_reports_openpbr_availability(self, ops, monkeypatch,
                                                  tmp_path):
        # The sub-view disables the selector from this flag, so it must be a
        # real probe result and a plain bool — not the AssetDescription the
        # probe wraps (bool() on one is True either way).
        (tmp_path / "p_BaseColor.png").write_bytes(b"x")
        monkeypatch.setattr(ops_matwire_c4d, "openpbr_available",
                            lambda: False)
        payload = ops._op_matwire_preview({"folder": str(tmp_path)})
        assert payload["openpbr_available"] is False

    def test_create_threads_material_to_every_call_site(self, ops,
                                                        monkeypatch):
        """v1.33 lesson: `import_leftovers` routes through a SECOND
        create_material_for_set call, and a kwarg added to only one of them
        keeps every test green while half the batch gets the default."""
        seen = []

        def _fake_create(doc, folder, tex_set, name, **kw):
            seen.append(kw.get("material"))
            return {"ok": True, "material_name": name, "error": None}

        monkeypatch.setattr(ops_matwire_c4d, "create_material_for_set",
                            _fake_create)
        # BOTH call sites must run: a set whose material is created, plus an
        # unassigned leftover (a file matching no set's root prefix), which
        # is what triggers the second `create_material_for_set`.
        payload = {"folder": FOLDER, "material": "standard",
                   "import_leftovers": True}
        result = ops._op_matwire_create(payload)
        assert result["ok"] is True
        assert len(seen) >= 2, \
            "the leftovers call site did not run — the test proves nothing"
        assert all(m == "standard" for m in seen), \
            "a call site dropped the material type"
```

Build `FOLDER` and the fixtures by copying the setup of the existing `import_leftovers` create test in this same file verbatim (it already produces a set plus an unassigned leftover); reuse its module alias for `matwire_c4d` as `ops_matwire_c4d`. Do not invent a new folder shape — the point of this test is the real two-call-site path.

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m pytest tests/test_panel_tools_ops.py -q -k MatwireMaterialType`
Expected: FAIL (`_matwire_material` does not exist)

- [ ] **Step 3: Add the boundary normalizer**

In `plugin/sentinel/ui/panel_tools_ops.py`, directly after `_matwire_projection`:

```python
def _matwire_material(payload):
    """VALIDATE AT THE BOUNDARY, exactly like ``_matwire_projection``: the
    writer degrades an unknown material type to the default silently, so a
    typo from the client would render as "Standard requested, OpenPBR
    delivered". Case and whitespace tolerated; anything the writer's table
    doesn't know becomes the default, never a raise. ``MATERIAL_TYPES`` is
    the single source of the accepted strings."""
    from sentinel import matwire_c4d
    raw = (payload or {}).get("material")
    if not isinstance(raw, str):
        return matwire_c4d.DEFAULT_MATERIAL
    value = raw.strip().lower()
    return (value if value in matwire_c4d.MATERIAL_TYPES
            else matwire_c4d.DEFAULT_MATERIAL)
```

- [ ] **Step 4: Report availability on the preview**

In `_op_matwire_preview`, beside the existing `uvcontext_available` line:

```python
    # Honest degradation (spec): without the OpenPBR node in this build the
    # Material selector has nothing to drive, and the sub-view says so
    # instead of offering a control that silently delivers Standard.
    out["openpbr_available"] = bool(matwire_c4d.openpbr_available())
```

- [ ] **Step 5: Thread it into create — BOTH call sites**

In `_op_matwire_create`, next to `projection = _matwire_projection(payload)`:

```python
    material = _matwire_material(payload)  # normalized, never raises
```

Then add `material=material` to **both** `create_material_for_set(...)` calls (the per-set one and the leftovers one). Extend the existing comment above them so it names `material` alongside `projection`/`multiply_ao`.

- [ ] **Step 6: Run the suites**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Mutation-check the threading**

Remove `material=material` from the leftovers call site only, run `python3 -m pytest tests/test_panel_tools_ops.py -q`, and confirm `test_create_threads_material_to_every_call_site` fails. Revert. Report the result — if it does NOT fail, the fake is swallowing kwargs and the test is worthless; fix the fake so it fails.

- [ ] **Step 8: Commit**

```bash
git add plugin/sentinel/ui/panel_tools_ops.py tests/test_panel_tools_ops.py
git commit -m "feat(panel): material type boundary + openpbr availability + create threading"
```

### Task 4: SPA — Material selector and honest gloss row

**Files:**
- Modify: `web/src/lib/panelMatwire.ts`, `web/src/lib/panelMatwire.test.ts`
- Modify: `web/src/components/panel/MatwireSubview.tsx`, `web/src/lib/api.ts`, `web/src/types.ts`

**Interfaces:**
- Consumes: preview field `openpbr_available?: boolean`; create payload field `material: string`.
- Produces: `MATERIAL_OPTIONS`, `MATWIRE_OPENPBR_UNAVAILABLE_COPY`, `openpbrUnavailableNote(available)`, `effectiveMaterial(selected, unavailableNote)`, `glossDestinationLabel(channels, material)`.

- [ ] **Step 1: Write the failing vitest**

Append to `web/src/lib/panelMatwire.test.ts`:

```ts
describe("material type", () => {
  it("offers OpenPBR first — it is the default", () => {
    expect(MATERIAL_OPTIONS[0].value).toBe("openpbr");
    expect(MATERIAL_OPTIONS.map((o) => o.value).sort()).toEqual([
      "openpbr", "standard",
    ]);
  });

  it("notes the degradation only when the node is missing", () => {
    expect(openpbrUnavailableNote(true)).toBeNull();
    expect(openpbrUnavailableNote(undefined)).toBeNull();
    expect(openpbrUnavailableNote(false)).toBe(
      MATWIRE_OPENPBR_UNAVAILABLE_COPY,
    );
  });

  it("never sends a material the writer will not build", () => {
    // v1.33 effectiveProjection lesson: an OpenPBR chosen before the
    // preview reported the node missing must not keep riding the payload
    // or lighting a disabled control — but the choice itself survives.
    expect(effectiveMaterial("openpbr", null)).toBe("openpbr");
    expect(effectiveMaterial("openpbr", "missing")).toBe("standard");
    expect(effectiveMaterial("standard", null)).toBe("standard");
  });

  it("labels the gloss row by what actually gets wired", () => {
    expect(glossDestinationLabel(["glossiness"], "openpbr")).toBe(
      "→ specular roughness (inverted)",
    );
    expect(glossDestinationLabel(["glossiness"], "standard")).toBe(
      "→ roughness (glossiness mode)",
    );
    expect(glossDestinationLabel(["roughness"], "openpbr")).toBeNull();
  });
});
```

Add the new symbols to the file's existing import from `./panelMatwire`.

- [ ] **Step 2: Run — expect failure**

Run: `cd web && npx vitest run panelMatwire`
Expected: FAIL (symbols not exported)

- [ ] **Step 3: Implement in `panelMatwire.ts`**

Append, next to the projection helpers:

```ts
/** Material type options. OpenPBR is FIRST because it is the default; the
 * values are the op's accepted strings (`matwire_c4d.MATERIAL_TYPES` — the
 * op normalizes anything else to the default, never raises). */
export const MATERIAL_OPTIONS: { value: string; label: string }[] = [
  { value: "openpbr", label: "OpenPBR" },
  { value: "standard", label: "Standard" },
];

export const MATWIRE_OPENPBR_UNAVAILABLE_COPY =
  "This Redshift build has no OpenPBR node — materials are built as Standard Surface.";

/** Inline reason for the disabled Material selector, or null when OpenPBR
 * is available. A preview without the field (pre-v1.34 shape) counts as
 * available: the degradation is server-reported, never guessed. */
export function openpbrUnavailableNote(
  available: boolean | undefined,
): string | null {
  return available === false ? MATWIRE_OPENPBR_UNAVAILABLE_COPY : null;
}

/** The material the writer will ACTUALLY build — what both the payload and
 * the (disabled) selector must show. Derived, never a state mutation on
 * render, so the artist's pick survives if a later preview reports the node
 * present again. */
export function effectiveMaterial(
  selected: string,
  unavailableNote: string | null,
): string {
  return unavailableNote === null ? selected : "standard";
}

/** Destination fragment after a glossiness filename — a MIRROR of the
 * engine's `matwire.gloss_destination`, for the same reason the AO mirror
 * exists: the row must relabel the instant the selector flips, and
 * re-fetching the preview would discard the artist's name edits. */
export function glossDestinationLabel(
  channels: string[],
  material: string,
): string | null {
  if (!channels.includes("glossiness")) return null;
  return material === "standard"
    ? "→ roughness (glossiness mode)"
    : "→ specular roughness (inverted)";
}
```

- [ ] **Step 4: Run — expect pass**

Run: `cd web && npx vitest run panelMatwire`
Expected: all pass.

- [ ] **Step 5: Wire the sub-view**

In `MatwireSubview.tsx`, mirroring the Projection block exactly:

- `const [material, setMaterial] = useState("openpbr");`
- `const openpbrNote = preview ? openpbrUnavailableNote(preview.openpbr_available) : null;`
- `const wiredMaterial = effectiveMaterial(material, openpbrNote);`
- A `SegmentedControl` labelled **Material** with `options={MATERIAL_OPTIONS}`, `value={wiredMaterial}`, `onChange={setMaterial}`, disabled when `openpbrNote !== null`, rendering the note inline underneath — the same structure the Projection control uses.
- Pass `wiredMaterial` into the create call.
- Render `glossDestinationLabel(channels, wiredMaterial)` on the glossiness channel row, the same way `aoDestinationLabel` is rendered on the AO row.

- [ ] **Step 6: Extend api and types**

In `web/src/types.ts`, add `openpbr_available?: boolean;` beside `uvcontext_available?: boolean;` with a one-line comment matching its neighbour's style.

In `web/src/lib/api.ts`, add a `material = "openpbr"` parameter to the create call and put `material` in the posted body next to `projection`; add `openpbr_available: true` to the mock preview beside `uvcontext_available: true`.

- [ ] **Step 7: Build and run everything**

Run: `cd web && npx vitest run && npm run build`
Expected: vitest all pass; build writes `plugin/web/`.
Run: `python3 -m pytest tests/ -q` — expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add web/src plugin/web
git commit -m "feat(panel): Material selector (OpenPBR default) + honest gloss row"
```

### Task 5: Docs and version

**Files:**
- Modify: `plugin/sentinel/common/constants.py` (or wherever `PLUGIN_VERSION` lives — grep for it)
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-07-30-matwire-openpbr-design.md`

- [ ] **Step 1: Bump the version**

Run `grep -rn "1\.33\.0" plugin/ --include=*.py | head` and set `PLUGIN_VERSION = "1.34.0"`.

- [ ] **Step 2: CLAUDE.md**

Add a v1.34.0 entry to **both** the "What Works" list and "Version History Summary", in the house style of the v1.33 entries: what it does, the measured facts from the Task 1 spike (with numbers), the two diverging branches, the ORM-splitter type-awareness catch, the honest-degradation path, real suite counts, and a `**PENDIENTE verificación live**` marker with the matrix from the spec's "Verificación" section.

- [ ] **Step 3: Spec status**

Change the spec's `**Estado**:` line to `implementado en rama feat/matwire-openpbr (pytest N, vitest M), pendiente de verificación live`, with the real counts.

- [ ] **Step 4: Full suites, then commit**

```bash
python3 -m pytest tests/ -q
cd web && npx vitest run
git add -A && git commit -m "docs: v1.34.0 — matwire OpenPBR (pending live verification)"
```

---

## After the plan (session-level)

1. Whole-branch adversarial review on the most capable model; fix Critical/Important.
2. `./sync.sh`, user restarts C4D, then the live matrix from the spec:
   - **Invert oracle**: a Glossiness set under OpenPBR must render **pixel-identical** to the same material given a roughness map that is `1 − gloss`.
   - Per-channel response under OpenPBR: metalness, roughness, normal (visible relief), emission, opacity.
   - An ORM pack under OpenPBR: splitter outputs reach `specular_roughness` / `base_metalness`.
   - `material = "standard"` still produces the v1.33 graph.
   - One Cmd+Z reverts a batch.
3. Merge `--no-ff`; update memory; next: Recall-checkpoint / scene-template to close the Tools arc.
