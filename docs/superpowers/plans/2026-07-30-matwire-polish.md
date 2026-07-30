# Matwire Polish (v1.32.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The four approved matwire improvements — recursive folder scan, real ORM/ARM wiring, ruleset-extensible suffix tables, and opt-in leftover import — per `docs/superpowers/specs/2026-07-30-matwire-polish-design.md`.

**Architecture:** Engine grows `extra_suffixes` + `packed_orm` channel + `root_hint`; `rules.py` gains the `matwire_suffixes` key (per-key validation, additive semantics applied in matwire); the writer gains the colorsplitter branch (mini-spiked live first) and leftover samplers; ops do the recursive listing + ruleset resolution; the subview gains the leftover checkbox.

**Tech Stack:** same as v1.32 (pure Python + fake-c4d pytest, GraphDescription writer, React SPA + vitest, committed bundle).

**Branch:** `feat/matwire-polish` (create from `main` before Task 1).

## Global Constraints

- No-regression: carpeta plana + sin ruleset + leftover OFF ⇒ byte-idéntico a v1.32 SALVO ORM (de `ignored` a canal `packed_orm`) — el cambio deseado.
- ORM mapping FIJO: splitter `.input` ← sampler RAW; `.outg` → `refl_roughness` SOLO sin roughness dedicado; `.outb` → `metalness` SOLO sin metalness dedicado; `.outr` (AO) SIEMPRE sin conectar. Los ids del splitter salen del research catalog (`com.redshift3d.redshift4c4d.nodes.core.rscolorsplitter`, puertos `.input/.outr/.outg/.outb`) pero el writer NO los usa sin wire-test: **mini-spike live obligatorio** al inicio de la tarea del writer (patrón v1.32; evidencia añadida al spike doc).
- `matwire_suffixes` AÑADE a las tablas embebidas, nunca reemplaza; canales válidos = canónicos del motor (incl. `normal_gl`/`normal_dx` y `packed_orm`); validación per-key estilo ruleset (clave/valor malo → rechazado por nombre, el resto aplica).
- Recursión: `os.walk(followlinks=False)`, profundidad máx 5 bajo la raíz, directorios que empiezan por `.` podados; los archivos viajan como ruta RELATIVA con `/` (normalizar `os.sep`); la agrupación usa el BASENAME (ya lo hace el motor); el writer une `folder + relpath` con `os.path.join` normalizado.
- Leftover: default OFF; solo `no_channel` (jamás `bad_extension`/`lower_resolution`); asignación = set cuyo nombre lowercased + separador es PREFIJO del stem lowercased (match más largo), si no → material `<default_root>_leftovers` (un Standard vacío + samplers sueltos — mismo path de creación, cero casos especiales). Samplers sueltos = patrón AO (segundo ApplyDescription), RAW.
- Todo lo demás hereda las Global Constraints de v1.32 (dialog-free, re-derivación server-side, un undo con anchors, colorspaces/flipy explícitos, siempre-explícito).
- Suites: pytest `python3 -m pytest tests/ -q`; vitest `cd web && npx vitest run`; build `cd web && npm run build`.

## File Structure

- `plugin/sentinel/matwire.py` — extra_suffixes, validate_extra_suffixes, packed_orm channel, root_hint.
- `plugin/sentinel/rules.py` — DEFAULTS + `_validate_key` branch `matwire_suffixes`.
- `plugin/sentinel/matwire_c4d.py` — splitter branch + leftover samplers.
- `plugin/sentinel/ui/panel_tools_ops.py` — recursive listing, ruleset resolution + `suffix_warnings`, `leftovers`, `import_leftovers`.
- `docs/research/2026-07-29-matwire-spike.md` — append the colorsplitter mini-spike evidence.
- SPA: `MatwireSubview.tsx`, `panelMatwire.ts` (+ test), `api.ts`, `types.ts`.
- Tests: `tests/test_matwire.py`, `tests/test_rules.py`, `tests/test_panel_tools_ops.py`, `web/src/lib/panelMatwire.test.ts`.

---

### Task 1: Engine — extra suffixes, packed_orm channel, root_hint

**Files:** modify `plugin/sentinel/matwire.py`; test `tests/test_matwire.py` (append).

**Interfaces:**
- `CANONICAL_CHANNELS: frozenset` — every channel key the tables know (incl. `normal_gl`, `normal_dx`, `packed_orm`).
- `validate_extra_suffixes(raw) -> (valid: dict[str, list[str]], rejected: list[str])` — dict str→list[str]; unknown channel keys and non-str-list values land in `rejected` (key names); suffixes normalized lowercase/stripped; empty entries dropped.
- `scan_texture_sets(filenames, default_root="material", extra_suffixes=None)` — extras EXTEND the embedded variant lists for matching (compiled per call only when extras present; module-level compiled defaults otherwise — the hot path stays cached).
- `packed_orm` becomes a real channel: an ORM/ARM file joins its set's `channels["packed_orm"]` (grouped by its root like any channel; second ORM in a set → `duplicate_channel`; a ROOTLESS orm file groups under default_root). It never suppresses nor is suppressed by dedicated maps at ENGINE level (the writer applies dedicated-wins per splitter output).
- Global `ignored` entries for `no_channel` become `(filename, "no_channel", root_hint)` — 3-tuples ONLY for no_channel? NO: keep the 2-tuple shape everywhere (SPA/type stability) and add a SEPARATE top-level key `leftover_hints: {filename: root_hint}` where `root_hint` = normalized stem (lowercase, separators collapsed). The ops layer does the prefix-match assignment.

- [ ] **Step 1:** Failing tests: extras extend (a ruleset synonym `col_especial` recognized as basecolor; embedded synonyms still work), validate_extra_suffixes (valid/rejected mix, per-key), packed_orm in channels (with basecolor sibling; rootless ORM; second ORM → duplicate_channel; `x_ORM_2k` still packed_orm with px ranking), no_channel files appear in `leftover_hints`, and the v1.32 regression pins still green (run the whole file).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement (keep `_CHANNEL_RES` as the cached default; build a merged table copy when extras present; `packed_orm` moves from the early-ignore branch into normal channel flow).
- [ ] **Step 4:** `python3 -m pytest tests/test_matwire.py -q` → PASS; full suite PASS (the ops layer still treats packed_orm as a channel it doesn't know → check nothing breaks; if preview colorspace annotation hits packed_orm, `channel_colorspace("packed_orm")` must return `"raw"`).
- [ ] **Step 5:** Commit `feat(matwire): ruleset-extensible suffixes, packed_orm as channel, leftover hints`.

### Task 2: rules.py — `matwire_suffixes` key

**Files:** modify `plugin/sentinel/rules.py`; test `tests/test_rules.py` (append).

- `DEFAULTS["matwire_suffixes"] = {}`; `_validate_key` branch delegating to `matwire.validate_extra_suffixes` (import at module top — matwire is pure): valid if `rejected == []`… NO: per-key granularity INSIDE the dict mirrors `safe_area_insets`' style — accept the valid subset and surface rejected channel names in the reason? Follow the file's existing convention EXACTLY: read `_validate_safe_area_insets` first; if it accepts-partial, do the same; if it's all-or-nothing per key, then `matwire_suffixes` is all-or-nothing too (reject with a reason naming the bad channels) — match the house pattern, do not invent a third.
- NOT added to `MAP_MERGE_KEYS` (default is `{}`; additive semantics live in matwire).
- [ ] Tests: valid dict accepted + normalized; bad channel name → rejected with reason; non-dict → rejected; DEFAULTS carries `{}`; a full rules file with one bad `matwire_suffixes` key keeps every other key working (existing per-key contract test idiom).
- [ ] Commit `feat(rules): matwire_suffixes project key (additive suffix tables)`.

### Task 3: Writer — colorsplitter mini-spike + splitter branch + leftover samplers

**Files:** modify `plugin/sentinel/matwire_c4d.py`; append evidence to `docs/research/2026-07-29-matwire-spike.md`; test `tests/test_matwire.py` (TestBuildDescription append).

- [ ] **Step 1 (MINI-SPIKE, live, blocking):** via MCP exec_python in a throwaway doc: wire-test `rscolorsplitter` — sampler → `.input`, `.outg` → standardmaterial `refl_roughness`, `.outb` → `metalness`, `.outr` unconnected; read back connections + confirm port ids. Append "## Mini-spike v1.32.1: rscolorsplitter" with evidence to the spike doc. If C4D unreachable → BLOCKED.
- [ ] **Step 2:** Failing build_description tests: set with packed_orm + dedicated roughness → splitter present, `.outg` NOT connected to refl_roughness (dedicated sampler is), `.outb` → metalness; set with packed_orm alone → both outg/outb connected, outr never; ORM sampler RAW. Leftover: `build_leftover_descriptions(folder, files) -> list[sampler_desc]` (RAW, unconnected — reuse `_sampler`).
- [ ] **Step 3:** Implement per spike evidence: the splitter is expressible in GraphDescription as a nested value on each TARGET port? NO — one splitter feeding TWO ports needs a shared node: GraphDescription dict nesting duplicates it. Follow the spike finding; if sharing isn't expressible declaratively, build the splitter via the SECOND ApplyDescription + imperative connect (transaction) per the spike's recorded working calls — the mini-spike decides, the plan does not guess. `create_material_for_set` gains `leftover_files=None` param (appended as extra unconnected samplers via the AO-pattern apply); ops pass them per assignment.
- [ ] **Step 4:** Suites green. Commit `feat(matwire): ORM/ARM colorsplitter wiring (live-spiked) + leftover samplers`.

### Task 4: Ops + SPA

**Files:** modify `plugin/sentinel/ui/panel_tools_ops.py`, `web/src/components/panel/MatwireSubview.tsx`, `web/src/lib/panelMatwire.ts` (+test), `web/src/lib/api.ts`, `web/src/types.ts`; test `tests/test_panel_tools_ops.py`.

- Recursive lister `_list_folder_files(folder) -> list[str]` (relative paths, `/` separators, walk cap 5, prune dot-dirs, no symlink follow, sorted) — used by BOTH ops.
- Ruleset: `from sentinel.rules_context import active_rules_for_doc` (same lazy import style as frame_tag) → `params.get("matwire_suffixes")` → `validate_extra_suffixes` → pass valid to scan; response gains `"suffix_warnings": [rejected...]` (empty list normally).
- Preview response gains `"leftovers": [{"file", "set": name|null}]` (prefix-match assignment per Global Constraints — pure helper `assign_leftovers(hints, set_names)` in matwire.py with its own tests). Create payload gains `"import_leftovers": bool` (default False): when True, per-set leftovers ride `create_material_for_set(..., leftover_files=...)` and unassigned ones create the `<default_root>_leftovers` material (deduped name, same undo batch).
- SPA: checkbox "Import unrecognized files" (default off) + folded leftovers list with destination; inline suffix_warnings note; `packed_orm` channel row label "ORM/ARM (packed)". Toast unchanged except leftover material counts naturally in `created`.
- [ ] TDD both sides; `npm run build`; full suites. Commit `feat(panel): recursive scan, ruleset suffixes, leftover import (matwire polish)`.

### Task 5: Docs + version

- `PLUGIN_VERSION = "1.32.1"`; CLAUDE.md entries (house style; cover the four features + the mini-spike outcome + "PENDIENTE verificación live" con matriz corta del spec); spec Estado → implementado en rama.
- Full suites, real counts. Commit `docs: v1.32.1 — matwire polish (pending live verification)`.

---

## After the plan (session-level)

1. Final whole-branch review; fix Critical/Important.
2. Live corta (sync + restart + MCP): pack anidado recursivo; ORM + roughness dedicado → G libre/B conectado; sufijo custom por ruleset; leftover ON; un Cmd+Z. Eyeball usuario.
3. Merge `--no-ff`; memoria; siguiente = v1.33 Recall/template (brainstorm propio).
