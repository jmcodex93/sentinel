# Matwire UV Context + Color Correct + AO opcional (v1.33) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared `uvcontextprojection` per material (Projection selector UV/Triplanar), a permanent identity Color Correct on basecolor, an opt-in AO multiply, and semantic node titles — per `docs/superpowers/specs/2026-07-30-matwire-uvcontext-design.md`.

**Architecture:** The writer grows three plan builders (context, color-correct interposition, AO layer) that reuse the ORM branch's proven imperative fan-out recipe; ops pass two new payload fields and report `uvcontext_available`; the sub-view gains a Projection segmented control and an AO checkbox.

**Tech Stack:** unchanged (pure Python + fake-c4d pytest, GraphDescription + imperative maxon transactions, React SPA + vitest, committed bundle).

**Branch:** `feat/matwire-uvcontext` (create from `main` before Task 1).

## Global Constraints

- **Evidence base**: `docs/research/2026-07-30-uvcontext-and-graph-cost.md` (the live spike) is authoritative for node/port/enum facts. The three measured traps are MANDATORY in the writer: `uv_tiling = 0` (**1 is hexagonal tiling**), vec2 values are `maxon.Vector(x, y, 0.0)` (tuple/list are rejected), and each sampler's own `scale`/`offset`/`rotate` are **left at their defaults** (they MULTIPLY with the context — one source of truth).
- **Verified ids**: node `com.redshift3d.redshift4c4d.nodes.core.uvcontextprojection`, output port `…uvcontextprojection.outcontext`, sampler input `…texturesampler.uv_context`, `…uvcontextprojection.proj_type` (1 = UV Channel, 2 = Tri-Planar), `…rscolorlayer.layer1_blend_mode = 4` (**Multiply**; 2 is NOT), `…rscolorcorrection`. Anything not in the spike doc must be introspected live before use, never guessed.
- **Fan-out is imperative**: one `outcontext` feeding N `uv_context` ports cannot be expressed in GraphDescription (nesting duplicates the node; there is no `$ref`) — reuse the ORM recipe: isolated `ApplyDescription` + `Connect()` pairs in ONE transaction (`_apply_orm_plan` is the template).
- **The one-undo contract is untouchable**: the full graph is built BEFORE `doc.InsertMaterial` (v1.32.1 root fix). Every new graph step goes inside that pre-insert window.
- **Degrade honestly**: if `uvcontext_available()` is false the material is built exactly as v1.32.1 and the preview says so; never promise what the writer won't do.
- **No-regression**: `projection="uv"` + `multiply_ao=False` must render identically to v1.32.1 (identity context measured as neutral); the graph just gains two ≈0-cost nodes.
- Colorspaces/flipy stay always-explicit; `orm_contributions` stays the single source for the ORM rules.
- Suites: pytest `python3 -m pytest tests/ -q`; vitest `cd web && npx vitest run`; build `cd web && npm run build` (bundle committed).

## File Structure

- `plugin/sentinel/matwire_c4d.py` — `uvcontext_available`, `build_uvcontext_plan`, `_apply_uvcontext_plan`, Color Correct + AO branches in `build_description`, node titles, layout column.
- `plugin/sentinel/matwire.py` — `ao_destination(channels, multiply_ao)` pure helper (single source for "where does AO go", consumed by writer AND preview — the `orm_contributions` pattern).
- `plugin/sentinel/ui/panel_tools_ops.py` — payload fields, `uvcontext_available` in preview.
- `web/src/components/panel/MatwireSubview.tsx`, `web/src/lib/panelMatwire.ts` (+test), `web/src/lib/api.ts`, `web/src/types.ts`.
- Tests: `tests/test_matwire.py`, `tests/test_panel_tools_ops.py`, `web/src/lib/panelMatwire.test.ts`.

---

### Task 1: Writer — Color Correct, AO multiply, node titles

**Files:** modify `plugin/sentinel/matwire_c4d.py`, `plugin/sentinel/matwire.py`; test `tests/test_matwire.py` (append).

**Interfaces:**
- `matwire.ao_destination(channels, multiply_ao) -> "base_color_multiply" | "unconnected" | None` — `None` when the set has no AO. SINGLE source: the writer decides the graph from it and `preview_payload` annotates the AO row from it (same discipline as `orm_contributions`).
- `matwire_c4d.build_description(folder, tex_set, multiply_ao=False)` — Color Correct ALWAYS interposed between the basecolor sampler and `base_color`; when `multiply_ao` and AO exists, an `rscolorlayer` sits between the corrected basecolor and `base_color` (base layer = corrected color, layer 1 = AO sampler, `layer1_blend_mode = 4`), and `ao_desc` returns `None` (the AO is wired, not loose). Default `multiply_ao=False` keeps every existing caller byte-identical apart from the Color Correct.
- `matwire_c4d.NODE_TITLES: dict` + titles applied in `_layout_nodes` (rename to `_layout_and_title_nodes` or keep the name and document it) via `net.maxon.node.attribute.title`, mapping node kind → label, with the basecolor/roughness/etc. samplers titled by their CHANNEL (pass the channel→node association through the plan, or title samplers by their `tex0/path` basename — pick by what's readable in the graph and say why in the docstring).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_matwire.py`, `TestBuildDescription` idioms):

```python
def test_ao_destination_single_source(matwire):
    ch_ao = {"basecolor": "b.png", "ao": "a.png"}
    assert matwire.ao_destination(ch_ao, True) == "base_color_multiply"
    assert matwire.ao_destination(ch_ao, False) == "unconnected"
    assert matwire.ao_destination({"basecolor": "b.png"}, True) is None


def test_color_correct_always_interposed(matwire, matwire_c4d):
    scan = matwire.scan_texture_sets(["p_BaseColor.png", "p_Roughness.png"])
    desc, _ao = matwire_c4d.build_description("/tex", scan["sets"][0])
    RS = matwire_c4d._RS_CORE
    material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
    cc = material["#<" + RS + "standardmaterial.base_color"]
    assert cc["$type"] == "#" + RS + "rscolorcorrection"
    inner = cc["#<" + RS + "rscolorcorrection.input"]
    assert inner["$type"] == "#" + RS + "texturesampler"
    assert inner["#<" + RS + "texturesampler.tex0/path"].endswith("p_BaseColor.png")
    # roughness untouched by the correction
    assert material["#<" + RS + "standardmaterial.refl_roughness"]["$type"] == \
        "#" + RS + "texturesampler"


def test_ao_multiply_wires_layer_and_drops_loose_sampler(matwire, matwire_c4d):
    scan = matwire.scan_texture_sets(["p_BaseColor.png", "p_AO.png"])
    tex_set = scan["sets"][0]
    RS = matwire_c4d._RS_CORE
    # OFF: AO stays a loose sampler (v1.32 behavior)
    desc_off, ao_off = matwire_c4d.build_description("/tex", tex_set, multiply_ao=False)
    assert ao_off is not None
    assert desc_off["#<" + matwire_c4d._RS_OUTPUT + ".surface"][
        "#<" + RS + "standardmaterial.base_color"]["$type"] == "#" + RS + "rscolorcorrection"
    # ON: color layer between the corrected color and base_color; no loose AO
    desc_on, ao_on = matwire_c4d.build_description("/tex", tex_set, multiply_ao=True)
    assert ao_on is None
    layer = desc_on["#<" + matwire_c4d._RS_OUTPUT + ".surface"][
        "#<" + RS + "standardmaterial.base_color"]
    assert layer["$type"] == "#" + RS + "rscolorlayer"
    assert layer["#<" + RS + "rscolorlayer.layer1_blend_mode"] == 4  # Multiply (verified)
    base = layer["#<" + RS + "rscolorlayer.base_color"]
    assert base["$type"] == "#" + RS + "rscolorcorrection"       # correction still first
    lay1 = layer["#<" + RS + "rscolorlayer.layer1_color"]
    assert lay1["#<" + RS + "texturesampler.tex0/path"].endswith("p_AO.png")


def test_ao_multiply_without_basecolor_is_noop(matwire, matwire_c4d):
    # An AO-only set has nothing to multiply INTO: the layer must not appear
    # and the AO stays loose (never a dangling color layer).
    scan = matwire.scan_texture_sets(["p_AO.png", "p_Roughness.png"])
    desc, ao = matwire_c4d.build_description("/tex", scan["sets"][0], multiply_ao=True)
    RS = matwire_c4d._RS_CORE
    material = desc["#<" + matwire_c4d._RS_OUTPUT + ".surface"]
    assert "#<" + RS + "standardmaterial.base_color" not in material
    assert ao is not None
```

Note for the implementer: the exact child-port ids of `rscolorlayer` (`base_color`/`layer1_color` above are PLACEHOLDERS from the market research) and of `rscolorcorrection` (`input`) MUST be confirmed by live introspection before writing production code — the spike doc records `layer1_blend_mode` but not necessarily the color port names. Introspect (small MCP op, throwaway doc, port dump like the spike did), fix both the test and the implementation to the REAL ids, and note them in your report. Do not ship guessed ids.

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement (Color Correct always; AO layer only when `multiply_ao` AND both `basecolor` and `ao` exist; titles).
- [ ] **Step 4:** `python3 -m pytest tests/test_matwire.py tests/test_panel_tools_ops.py -q` green; full suite green.
- [ ] **Step 5:** Commit `feat(matwire): identity Color Correct, opt-in AO multiply, semantic node titles`.

---

### Task 2: Writer — shared UV Context (live-introspect first)

**Files:** modify `plugin/sentinel/matwire_c4d.py`; test `tests/test_matwire.py` (append); append evidence to `docs/research/2026-07-30-uvcontext-and-graph-cost.md`.

**Interfaces:**
- `uvcontext_available() -> bool` — probe of the context node (same `FindLatestAsset(...).IsNullValue()` idiom as `redshift_available`).
- `build_uvcontext_plan(proj_type) -> {"desc": {...}, "connect_to": "uv_context-port-id"} | None` — `None` when the node isn't available. The desc sets `proj_type` and `uv_tiling = 0` explicitly.
- `_apply_uvcontext_plan(graph, plan)` — isolated ApplyDescription then, in ONE transaction, connect the context's `outcontext` to the `uv_context` input of EVERY texturesampler in the graph (samplers are discovered by assetid, like `_apply_orm_plan` does). Runs AFTER all sampler-creating applies (main desc, ORM, AO, leftovers) and BEFORE layout — order matters and must be commented.
- `create_material_for_set(doc, folder, tex_set, name, leftover_files=None, multiply_ao=False, projection="uv")`.

- [ ] **Step 1 (live introspection, blocking):** MCP ping; in a THROWAWAY doc dump the real port ids of `uvcontextprojection` (confirm `proj_type`, `uv_tiling`, `outcontext`) and of a texturesampler's `uv_context`; confirm a `maxon.Vector(x,y,0.0)` write on any vec2 you intend to set. Paste the evidence into the research doc under "## Confirmación de puertos v1.33". Clean up.
- [ ] **Step 2:** Failing tests: `build_uvcontext_plan(1)`/`(2)` desc pins (`proj_type`, `uv_tiling == 0`), `None` when unavailable (monkeypatch the probe), and — since `_apply_uvcontext_plan` is c4d-bound — a test asserting `create_material_for_set` passes `projection` through to the plan builder (monkeypatch the builder and assert the argument), plus one asserting the sampler's own `scale`/`offset`/`rotate` are NEVER written by any desc (grep-style assertion over the built dicts).
- [ ] **Step 3:** Implement per the spike recipe.
- [ ] **Step 4:** Suites green.
- [ ] **Step 5:** Commit `feat(matwire): shared uvcontextprojection wired into every sampler (live-verified ids)`.

---

### Task 3: Ops + SPA

**Files:** modify `plugin/sentinel/ui/panel_tools_ops.py`, `web/src/components/panel/MatwireSubview.tsx`, `web/src/lib/panelMatwire.ts` (+test), `web/src/lib/api.ts`, `web/src/types.ts`; tests `tests/test_panel_tools_ops.py`, `web/src/lib/panelMatwire.test.ts`.

- `matwire_create` payload gains `projection` (`"uv"`|`"triplanar"`, default `"uv"` → `proj_type` 1/2) and `multiply_ao` (bool, default False), threaded to `create_material_for_set`. Unknown projection value → treat as `"uv"` (never raise).
- `matwire_preview` response gains `uvcontext_available: bool`; every channel row for `ao` gains `destination` from `matwire.ao_destination(channels, multiply_ao)` — which means preview must accept `multiply_ao` in its payload too (default False) so the row reflects the CURRENT checkbox. Confirm this is consistent with the SPA calling preview on toggle (debounced) — if the SPA prefers to compute the label client-side from `multiply_ao`, keep the single source by exporting a tiny pure helper in `panelMatwire.ts` that mirrors `ao_destination`'s three outcomes and pin it against the server's values in vitest.
- SPA: `SegmentedControl` Projection (UV Channel / Triplanar; disabled + inline reason when `uvcontext_available` is false) and checkbox "Multiply AO into base color" (off), both next to the leftovers checkbox; AO row shows its destination.
- [ ] TDD both sides; `npm run build`; suites green. Commit `feat(panel): Projection selector + AO multiply toggle (matwire)`.

---

### Task 4: Docs + version

- `PLUGIN_VERSION = "1.33.0"`; CLAUDE.md entries (house style: the spike's two measured conclusions, the three traps, the imperative fan-out, the honest degradation, the AO/Color-Correct decisions and their measured costs, "PENDIENTE verificación live" + matrix); spec Estado → implementado en rama.
- Full suites with real counts. Commit `docs: v1.33.0 — matwire UV Context + Color Correct + AO opcional (pending live verification)`.

---

## After the plan (session-level)

1. Final whole-branch review; fix Critical/Important.
2. Live (sync + restart + MCP + user eyeball): geo SIN UVs con `triplanar` → proyección correcta EN RENDER (no por params); UV Channel en geo con UVs; AO on/off comparado por píxeles; censo de conexiones probando que el contexto llega a TODOS los samplers (incluidos ORM y leftovers); un solo Cmd+Z; y el caso degradado (si es forzable) del nodo no disponible.
3. Merge `--no-ff` tras confirmación; memoria; siguiente = Recall/template (cierre del arco de Tools) u OpenPBR.
