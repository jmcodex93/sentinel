# Codex Handoff Brief — Post-Render Validation, Units U5 · U6 · U7

**Repo root:** `/Users/javiermelgar/Library/CloudStorage/SynologyDrive-01_WORK/99 - CODEX/10 YS Guardian`
**Feature:** Post-Render Validation (I1) for the Sentinel Cinema 4D plugin
**Plan of record:** `docs/plans/2026-07-06-001-feat-post-render-validation-plan.md` (you may read it, but this brief is authoritative and self-contained)
**Units already landed:** U1 (token/AOV/range contract — findings quoted below), U2–U4 (pure scan helpers already in `plugin/sentinel/postrender.py`)

---

## 0. How to read this brief (process constraint — READ FIRST)

**Codex runs HEADLESS. Codex CANNOT run Cinema 4D, cannot open a viewport, cannot import `c4d`/`redshift`.** Therefore:

- **Everything you (Codex) verify is via `pytest`.** Your definition of done is *green pytest for the pure surface you author*, plus code that satisfies the exact contracts quoted here.
- **You will author C4D-touching glue "to the contract."** For those functions (U5 scene reader, U7 UI) you write code that matches the verified signatures/param-IDs below, but you DO NOT verify them — a human verifies them **live in C4D 2026.301 via MCP** afterward, using the checklists in §5, §6, §8.
- **Never** instruct anyone (or yourself) to "run C4D", "open the viewport", "render a frame", or "verify live" as part of *your* work. Those are the human's post-handoff steps, enumerated separately.
- The whole design goal is to **push as much logic as possible into `import c4d`-free pure functions** so your pytest surface is maximal and the live-MCP debt is a thin field-reading adapter.

> ⛔ **HARD RULE (breaks the whole test surface if violated):** `plugin/sentinel/postrender.py` must stay **stdlib-only at module top**. `tests/test_postrender.py` loads it with `spec_from_file_location` + `exec_module` and **NO `c4d` stub** (unlike the `sentinel_module` fixture) — a module-level `import c4d` raises `ModuleNotFoundError` at collection and **every** U2–U6 pure test errors out, which you cannot even detect headlessly. Do **NOT** mirror `aovs.py`'s top-level `import c4d` (`aovs.py:4`). In `postrender.py`, `c4d`/`redshift` must be imported **function-locally** inside the impure adapter (`_read_scene_render_state`, `build_expected_manifest`, `audit_render_folder`) — never at module scope.

---

## 1. Objective

U5–U7 complete the Post-Render Validation feature. The chain:

1. **U5** reads the *scene's* render intent (output paths, frame range by mode, resolution/format, RS AOVs, Takes incl. the common single-render case) → produces an **expected manifest** (what files *should* exist on disk), then audits a chosen folder against it by calling the U2–U4 scan helpers, plus AOV-presence and per-Take/format coverage.
2. **U6** assembles the findings into a capped report dict, writes it **atomically** to `<base>_sentinel_render_report.json`, and appends a summary to a **separate** render sidecar `<base>_render_history.json` (NEVER the Versions-tab history — see KTD7).
3. **U7** surfaces a **"Validate Render Output…"** button in the Render tab that picks a folder, runs the audit, writes the report, and shows a summary dialog that echoes the resolved active version + frame range (so a farm/edited-scene mismatch is visible to the eye).

The feature is **on-demand** (no render-complete hook exists in C4D today) and **local** (validates the folder the user points at, against the currently open doc).

---

## 2. Scope

### IN (this handoff)

**U5 — `plugin/sentinel/postrender.py` + `plugin/sentinel/aovs.py`**
- Move light-group helpers `_scan_light_groups` / `_is_lg_active_on_beauty` from `ui/panel.py` → `aovs.py` (KTD1 circular-import fix; must happen *before* U5 logic).
- Extend `aovs.get_rs_aovs(doc)` to expose `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` + `REDSHIFT_AOV_FILE_FORMAT` per AOV (KTD6). Add `aovs.get_aov_multipart(doc)`.
- New in `postrender.py`: `_read_scene_render_state(doc)` (IMPURE thin adapter), `build_manifest_from_state(states, audit_folder=None)` (PURE), `build_expected_manifest(doc)` (thin wrapper), `resolve_output_template(...)` (PURE helper), `audit_render_folder(doc, folder)` (thin orchestrator).
- New test file `tests/test_postrender.py` gains U5's pure scenarios (it may already exist for U2–U4; append).

**U6 — `plugin/sentinel/postrender.py` + `plugin/sentinel/versioning.py`**
- `build_report(findings)` (PURE), `write_report_atomic(path, report)` (PURE, filesystem), `append_render_history(base_or_folder, summary)` (PURE, filesystem).
- `render_history_path(doc_path)` factored **into `versioning.py`** next to `get_history_path`, reusing `parse_version_filename`.

**U7 — `plugin/sentinel/ui/ids.py` + `plugin/sentinel/ui/panel.py` (+ optional `ui/dialogs.py`)**
- `G.BTN_VALIDATE_RENDER = 1215`.
- `_build_tab_render`: new `"Post-Render"` section + `AddButton`.
- `Command()`: `elif cid == G.BTN_VALIDATE_RENDER:` → `self._handle_validate_render(doc)` panel method.
- Folder picker + read-only summary dialog.

### OUT / DEFERRED (do NOT build)

- Per-layer EXR decode / real corruption / NaN detection / counting layers in Multi-Part (needs external OpenEXR — KTD4).
- Real per-Take pixel-resolution verification (read header dims). v1 verifies *format coverage* only (KTD5).
- Render-complete hook / MessageData RENDER trigger (does not exist today).
- "Trace render" correlation query (folder → version/status/score + version-timestamp staleness) and its UI.
- Delivery-spec matrix, render cost/time estimator.
- Rolling-window SPC.
- **Light-group AOV coverage (DEFERRED, v1).** A scene with All-Light-Groups active on Beauty emits an extra `Beauty_<group>` file per group, but the exact on-disk naming is a still-unconfirmed U1 residual — expanding it now would emit false-WARN on wrong names. v1 validates the regular AOV set (via RS's confirmed `effective_path`) and the beauty/multipass only. The reader still *exposes* `light_groups` for a future unit, but `build_manifest_from_state` does NOT emit expected light-group files in v1. Note this gap in the report ("light-group AOVs not validated") so it isn't a silent false-GREEN. (Human live-MCP can confirm the naming later, then a follow-up consumes it.)
- Any change to the QC engine/registry/score, or texture-scanner hardening.

---

## 3. Confirmed U1 contract (authoritative — build on this, do NOT re-derive or "spike")

U1 was verified live in **C4D 2026.301** against a real Redshift scene. These are facts; treat them as given.

### 3.1 Token expansion (KTD3)
```python
import c4d
rpd = {'_doc': doc, '_rData': rd, '_rBc': rd.GetDataInstance(), '_frame': frame_int}
# add '_take': take_obj to resolve $take (REQUIRED for $take, else it stays literal)
resolved = c4d.modules.tokensystem.StringConvertTokens(path, rpd)
```
- `$frame` → **4-digit zero-padded** (frame 5 → `0005`).
- If the resolved path has **no** frame number and it's a multi-frame sequence, the C4D pipeline auto-appends the digits → **Sentinel replicates: append `str(frame).zfill(4)`**.
- The **extension is NOT appended by the converter** — the caller appends it from `RDATA_FORMAT → ext`.
- `$pass` does **NOT** resolve via `StringConvertTokens` (RS-internal — do not try).
- `FilenameConvertTokens` is discarded (prefixes `./`, no extension).

### 3.2 `RDATA_FORMAT` → extension (BitmapSaver ids)
Read `rbc[c4d.RDATA_FORMAT]` (beauty) and `rbc[c4d.RDATA_MULTIPASS_SAVEFORMAT]` (multipass). Keep a static dict for the common ids; optionally enumerate live via `c4d.plugins.FilterPluginList(c4d.PLUGINTYPE_BITMAPSAVER, True)`.
```
1100 tif  1101 tga  1102 bmp  1103 iff  1104 jpg  1105 pct  1106 psd
1107 rla  1108 rpf  1109 b3d  1111 psb  1125 mp4  1001379 hdr
1016606 exr  1023671 png  1023737 dpx  1073775603 dds  1073784596 mov
```

### 3.3 Redshift AOV model (KTD6 — READ RS's resolved path, do NOT replicate its naming)
Per enabled AOV from `redshift.RendererGetAOVs(vp)` (read via `aov.GetParameter(...)`, **not** subscript):
- `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` — RS's already-resolved path (convention `<beauty base>_AOV_<name>`), NO extension.
- `REDSHIFT_AOV_FILE_FORMAT` → **0=EXR(.exr), 1=TIFF(.tif), 2=PNG(.png)** (per-AOV extension).
- Also useful: `REDSHIFT_AOV_FILE_ENABLED` (Direct Output on/off), `REDSHIFT_AOV_MULTIPASS_ENABLED`, `REDSHIFT_AOV_NAME`.

Global (videopost params, subscript access `vprs[ID]`):
- `REDSHIFT_RENDERER_AOV_MULTIPART` → **0 = Direct Output (one file per AOV); 1 = combined single multilayer .exr per frame**. Multi-Part ON → verify only *existence + non-zero* of the combined `.exr` (per-layer verification deferred).
- `REDSHIFT_RENDERER_AOV_PATH` — global base fallback.

### 3.4 Frame range by mode (R12)
`rbc[c4d.RDATA_FRAMESEQUENCE]` → **MANUAL=0, CURRENTFRAME=1, ALLFRAMES=2** (live-confirmed C4D 2026.301).

> ⚠️ **Use LITERAL ints 0/1/2 in the pure builder — do NOT reference `c4d.RDATA_FRAMESEQUENCE_*`.** The fake-`c4d` stub in `tests/conftest.py:201-203` has these **REVERSED** (CURRENTFRAME=0, ALLFRAMES=1, MANUAL=2 — the stub is wrong; real C4D's dropdown is Manual-first per this table). The impure reader reads the real `rbc[c4d.RDATA_FRAMESEQUENCE]` (correct at runtime) and passes the raw int to the pure builder, which branches on the literals 0/1/2. `conftest.py:201-203` is flagged for correction; do not trust it for "the real values".
- MANUAL → `rd[RDATA_FRAMEFROM].GetFrame(fps)` … `rd[RDATA_FRAMETO].GetFrame(fps)`
- ALLFRAMES → `doc.GetMinTime().GetFrame(fps)` … `doc.GetMaxTime().GetFrame(fps)`
- CURRENTFRAME → `doc.GetTime().GetFrame(fps)` (single frame)
- fps = `int(rd[c4d.RDATA_FRAMERATE])` per-preset (fallback `doc.GetFps()`).

### 3.5 The 3 residual on-disk confirmations (human's FIRST live-MCP step for U5 — NOT Codex's)
Cheap, non-architecture-shaping; confirm against a real 1–2 frame RS render (Multi-Part OFF/ON + light groups), then adjust only the string-building constants if reality differs:
1. Exact frame-digit **separator/padding** RS inserts into a Direct-Output AOV `EFFECTIVE_PATH` for a sequence (`_AOV_Diffuse.0001.exr` vs `_AOV_Diffuse1001.exr`).
2. Beauty auto-appends the 4-digit frame when `RDATA_PATH` lacks `$frame`.
3. `EFFECTIVE_PATH` directory picks up the `RDATA_PATH` directory (via RS's `$filepath`).

> **Design intent:** the pure engine receives **already-resolved paths**. Only U5's `_read_scene_render_state` (the sole impure function) runs `StringConvertTokens`, reads the live AOV set (`get_rs_aovs`, never hardcoded), and reads RS's own per-AOV effective path + format instead of reconstructing RS naming.

---

## 4. Existing U2–U4 API (already in `plugin/sentinel/postrender.py`, pure, no `import c4d`)

U5 imports and orchestrates these four. **Do not modify them**; wire to these exact shapes.

```python
expected_frames(start, end, step) -> list[int]
#   inclusive: list(range(start, end+1, step)).
#   U5 uses this to turn an R12 range mode into the entry's frame_set.

detect_stale_cluster(mtimes_by_frame, gap_factor=6.0) -> list[int]
#   mtimes_by_frame = {frame: mtime}. Returns sorted frames in the OLDEST
#   mtime cluster when a session gap (largest_gap > gap_factor*median_delta)
#   is found, else []. [] if <3 frames or median_delta==0.
#   Called INTERNALLY by scan_sequence — U5 does NOT call it directly.

scan_sequence(folder, prefix, frame_set, ext) -> dict
#   -> {"found":[...], "missing":[...], "zero_byte":[...],
#       "truncated":[...], "stale":[...]}   (all sorted int lists)
#   prefix = stem before the frame number; parser takes the LAST digit run,
#   tolerates '_'/'.' separators; getsize==0 -> zero_byte; <1024
#   (MIN_VIABLE_BYTES) -> truncated; a stale frame is EXCLUDED from found.
#   U5: call once per manifest entry with the resolved (folder, prefix,
#   frame_set, ext).

size_outliers(sizes_by_frame, sigma=3.0) -> list[int]
#   sizes_by_frame = {frame: size_bytes}. Sorted frames where
#   |size-median| > sigma*(MAD*1.4826). [] if <=2 frames or MAD==0.
#   U5/U6 MUST pre-filter the population: pass ONLY healthy frames
#   (exclude already-classified stale/zero_byte/truncated) — a stale frame
#   from another render session has a legit-but-different size and would
#   contaminate median/MAD, masking a real black frame or fabricating outliers.
```

**Two carry-forwards from the U2–U4 review that U5/U6 MUST honor:**

- **Prefix collision (carry-forward, verified):** `scan_sequence` filters by `prefix` + `os.listdir` last-wins, so a foreign AOV sharing a prefix (`beautyMask` vs `beauty`) can non-deterministically shadow a valid frame (`beautyMask_1001.exr` at 100 B marks the good `beauty_1001.exr` as `truncated`). **U5 must anchor to the EXACT stem** (or dedup deterministically by frame) when it resolves prefixes for multi-AOV folders — never a lax `startswith`.
- **MAD absolute-floor (carry-forward, ACCEPT):** with >50 % of frames byte-identical, `MAD==0` → `size_outliers` returns `[]` and a real black frame escapes. This is inherent to MAD, not a bug. U5/U6: add a **low-variance/flat-plane fixture**, consider a secondary **absolute-floor** size check, and **surface all size anomalies as WARN, never FAIL** (see §7).

---

## 5. Verification posture — the headless split

The repo's proven ladder (CLAUDE.md "Development Flow"; Sentinel Frame shipped pytest 129/129 + live MCP in C4D 2026.301): **pure math/logic in an `import c4d`-free module, unit-tested with pytest; every C4D-bound surface verified LIVE via MCP.** Codex owns only the pytest half.

### 5.1 Ownership table

| File · function | Kind | Verified by |
|---|---|---|
| `postrender.build_manifest_from_state(states, audit_folder)` | PURE | **Codex — pytest** |
| `postrender.resolve_output_template(...)` | PURE | **Codex — pytest** |
| `postrender.audit_manifest(manifest, folder)` — the aggregation seam (over hand-built manifest vs dummy dirs) | PURE (filesystem) | **Codex — pytest** |
| `postrender.audit_render_folder(doc, folder)` — 3-line impure glue (reader→builder→audit_manifest) | IMPURE (calls reader) | **Human — live MCP** |
| `postrender.build_report(findings)` | PURE | **Codex — pytest** |
| `postrender.write_report_atomic(path, report)` | PURE (filesystem) | **Codex — pytest** |
| `postrender.append_render_history(...)` | PURE (filesystem) | **Codex — pytest** |
| `versioning.render_history_path(doc_path)` | PURE (string) | **Codex — pytest** |
| `aovs.get_rs_aovs` extension (2 new keys) | IMPURE (RS reads) | **Human — live MCP** |
| `aovs.get_aov_multipart(doc)` | IMPURE (RS read) | **Human — live MCP** |
| `aovs._scan_light_groups` / `_is_lg_active_on_beauty` (moved) | IMPURE (scene reads) | **Human — live MCP** (behavior-preserving move; Codex verifies it *imports* cleanly) |
| `postrender._read_scene_render_state(doc)` | IMPURE (all C4D/RS/token reads) | **Human — live MCP** |
| `postrender.build_expected_manifest(doc)` thin wrapper | IMPURE (calls reader) | **Human — live MCP** |
| U7 button / `Command` branch / dialog | IMPURE (UI) | **Human — live MCP smoke** |

### 5.2 Human's live-MCP checklist (post-handoff — the human runs these, NOT Codex)

Run in C4D 2026.301 with the plugin reloaded (restart C4D after the package change — see §9).

**A. U1 residuals (do first, cheap):** the 3 confirmations in §3.5. Adjust only string constants if disproven.

**B. Light-group helper move (KTD1):**
1. Plugin package imports with no error; panel opens; RS AOV / Light Groups status caption still renders correctly.
2. Tools/Render "toggle light groups" still works (behavior-preserving; bodies copied verbatim minus `self`).

**C. `aovs` extensions:** on an RS scene, `get_rs_aovs(doc)` returns each AOV with non-empty `effective_path` + integer `file_format`; `get_aov_multipart(doc)` returns the live videopost flag (flip Multi-Part in RS and re-read → value changes).

**D. U5 scene reader / manifest (the false-RED-prone cases):**
1. **Single-render (Main take, NO child takes):** `build_expected_manifest(doc)` yields exactly ONE valid entry (R11); auditing a complete folder reports OK — it must NOT say "nothing to validate".
2. **Child takes present + Main NOT render-selected:** manifest EXCLUDES Main (by `IsChecked`/current-take), so the Main's sequence is NOT reported "missing" (no false-RED).
3. **Manifest dedup:** a child take with no `RDATA_PATH` override (inherits Main's render data) collapses into ONE entry; the report does NOT duplicate the same gaps/outliers under two Takes.
4. **Range mode:** a preset in ALLFRAMES resolves the frame_set to the doc timeline (not FRAMEFROM/TO); CURRENTFRAME resolves to a single frame; MANUAL to FRAMEFROM/TO.
5. **Real RS paths match disk:** resolved beauty + Direct-Output AOV paths match the actual files of a real RS render, Multi-Part ON and OFF, with light groups (this closes the U1 gate).
6. **R10 fallbacks:** no Redshift → standard C4D multipass path, no crash; no render data / invalid folder → clear message, no crash; **unsaved doc** (`GetDocumentPath()` empty) → report + sidecar written INTO the audited folder + the dialog says so.

**E. U6 (mostly pytest; one live assert):** after a live audit, confirm `<base>_render_history.json` exists and the Versions tab / `<base>_history.json` is byte-unchanged (Codex already asserts this in pytest; confirm once live).

**F. U7 UI smoke:** reload with no errors → "Validate Render Output…" appears in the Render tab **Post-Render** section → click → directory picker → summary dialog shows the resolved **active version + frame range + mode** ("Validating v007 · range 1001–1100 · mode Manual") → report JSON written → invalid folder / unsaved doc → message, no crash.

---

## 6. U5 — Scene-aware expected manifest + orchestrator

**Goal:** produce the expected manifest by reading the scene (paths, range-by-mode, resolution/format, AOVs, Takes incl. single-render), then run U3/U4 + AOV-presence + per-Take coverage over a chosen folder.
**Requirements:** R2, R5, R6, R10, R11, R12. **Consumes:** KTD1, KTD3, KTD6.

### 6.1 Pure/impure split (the core design — maximizes your pytest surface)

Split the C4D read from all decision logic:

```python
# ── IMPURE, THIN, NO LOGIC — the ONLY C4D-touching function. Live-MCP verified. ──
def _read_scene_render_state(doc) -> list[dict]:
    """Return one flat, JSON-serializable dict per candidate render-state.
    Does the C4D/RS reads + token expansion, and NOTHING else:
    no dedup, no mode branching, no Main-inclusion decision, no false-RED logic.
    """
    # per state:
    # {
    #   "take_name": str, "is_main": bool, "is_checked": bool,
    #   "raw_path": str,            # rd[RDATA_PATH]
    #   "multipass_save": bool,     # rd[RDATA_MULTIPASS_SAVEIMAGE]
    #   "multipass_path": str,      # rd[RDATA_MULTIPASS_FILENAME] (only if save)
    #   "xres": int, "yres": int,   # int(rd[RDATA_XRES] or 1920) / (... or 1080)
    #   "format_id": int,           # rd[RDATA_FORMAT]
    #   "multipass_format_id": int, # rd[RDATA_MULTIPASS_SAVEFORMAT]
    #   "frame_mode": int,          # rd[RDATA_FRAMESEQUENCE]  0/1/2
    #   "frame_from": int, "frame_to": int,   # .GetFrame(fps)
    #   "timeline_min": int, "timeline_max": int,
    #   "current_frame": int, "fps": int, "frame_step": int,
    #   "resolved_beauty_path": str,  # StringConvertTokens(raw_path, rpd+_take) ONLY.
    #                                 # NO ext, NO zfill here — the PURE layer
    #                                 # (resolve_output_template) appends ext(format_id)
    #                                 # and the zfill(4) fallback, so that logic is pytest-able.
    #   "redshift_available": bool,
    #   "aov_multipart": bool,        # aovs.get_aov_multipart(doc)
    #   "aov_global_path": str,       # REDSHIFT_RENDERER_AOV_PATH
    #   "aovs": [ {"name","effective_path","file_format","direct_enabled","multipass_enabled"} ],
    #   "light_groups": [str],        # groups, _ = aovs._scan_light_groups(doc); list(groups.keys())
    #                                 # (helper returns a (groups_dict, ungrouped_list) TUPLE — unpack it)
    #                                 # EXPOSED for a future unit; NOT consumed by the v1 builder (deferred, §2 OUT)
    # }

# ── PURE, NO import c4d — fully pytest-able with dict fixtures. Owns ALL decisions. ──
def build_manifest_from_state(states: list[dict], audit_folder: str | None = None) -> list[dict]:
    """Turn raw states into manifest entries, applying every false-RED guard:
    - single-render inclusion (no child takes -> one Main entry)
    - child-take Main-inclusion by is_checked/current (NOT unconditional)
    - dedup by resolved (folder, template, ext, frozenset(frame_set))
    - range-mode -> frame_set via expected_frames()
    - RDATA_FORMAT->ext table lookup
    - AOV Direct-Output (per-AOV files) vs Multi-Part (one .exr, existence only)
    - zfill(4) fallback when the resolved path lacks a frame number
    - exact-stem anchoring for multi-AOV folders (prefix collision carry-forward)
    - R10: when doc has no path, audit_folder is the write base
    Returns list of entries, each:
    {
      "take_name", "folder", "beauty_prefix", "ext", "frame_set":[...],
      "xres", "yres", "format_id",
      "aov_mode": "direct"|"multipart"|"none",
      "aov_files": [ {"name","prefix","ext"} ],          # direct only
      "multipart": {"prefix","ext"} | None,              # multipart only
    }
    """

def build_expected_manifest(doc) -> list[dict]:      # thin: reader -> pure builder
    return build_manifest_from_state(_read_scene_render_state(doc))

def resolve_output_template(raw_path, take_name, format_id, is_sequence) -> tuple[str,str,str]:
    """PURE. -> (folder, stem_prefix, ext). No import c4d. The token-RESOLVED
    path comes in already (from the reader); this does path splitting,
    ext-from-format, and the zfill(4)-fallback flag. Backslashes normalized."""

def audit_manifest(manifest: list[dict], folder: str) -> dict:   # PURE, no import c4d
    """The pytest-able aggregation seam. For each manifest entry:
       scan_sequence(folder, prefix, frame_set, ext)  (beauty + each direct AOV)
       + pre-filtered size_outliers(sizes_by_frame)   (exclude stale/zero/truncated)
       + AOV-presence / per-Take coverage.
    Aggregate -> findings dict (fed to U6 build_report). NO import c4d — Codex
    pytest-verifies this over a hand-built manifest + dummy dirs (§6.7 d/e)."""

def audit_render_folder(doc, folder) -> dict:        # thin orchestrator (IMPURE)
    """import c4d (function-local); states = _read_scene_render_state(doc);
       manifest = build_manifest_from_state(states, folder);
       return audit_manifest(manifest, folder)."""
```

> **The pure seam matters (HIGH fix):** `audit_manifest(manifest, folder)` is the named PURE function that owns the whole scan/size/AOV aggregation loop, so it is pytest-verifiable over hand-built manifests + `tmp_path` dirs with **no `c4d` mock**. `audit_render_folder(doc, folder)` is only the 3-line impure glue (reader → builder → `audit_manifest`). Do NOT put aggregation logic inside `audit_render_folder`.

### 6.2 How to read render data + takes (reuse these verified anchors)

All line numbers verified current — no drift.

- **Enumerate every preset's output config** — `checks/render.py:147` `check_output_paths`:
  ```python
  rd = doc.GetFirstRenderData(); count = 0
  while rd and count < 100:
      path = rd[c4d.RDATA_PATH] or ""
      if rd[c4d.RDATA_MULTIPASS_SAVEIMAGE]:
          mp_path = rd[c4d.RDATA_MULTIPASS_FILENAME] or ""
      rd = rd.GetNext(); count += 1
  ```
- **Take tree walk** — `checks/render.py:210` `check_takes`:
  ```python
  td = doc.GetTakeData()
  main_take = td.GetMainTake()
  take = main_take.GetDown()          # Main is skipped as a container
  while take:
      cam = take.GetCamera(td)
      rd  = take.GetRenderData(td) or doc.GetActiveRenderData()  # override-or-inherit
      take = take.GetNext()
  ```
  - **Single-render (R11):** if `main_take.GetDown()` is `None` → build **one** entry from `doc.GetActiveRenderData()` bound to the Main take. This is the most common case; it must NOT read as "nothing to validate".
  - **Render-selection gate (false-RED guard):** `check_takes` validates *all* child takes unconditionally and there is **no existing helper** for "which takes are actually queued to render" — **`IsChecked` does not exist anywhere in the codebase**. The only current-take API is `td.GetCurrentTake()` (`multiformat.py:496`, `panel.py:1081`, `ui/frame_tag.py:1023`). So in `_read_scene_render_state` you must set `is_checked` from the real render selection — attempt `take.IsChecked()` (the C4D Take API method) and fall back to "is this the current take" via `td.GetCurrentTake()`. Do NOT expand an unchecked Main into a full expected sequence (that would report an entire sequence "missing"). The **decision** ("include Main or not") lives in the PURE `build_manifest_from_state` reading the `is_checked`/`is_main` flags — the reader only reports them.
- **Range/mode (R12)** — `checks/render.py:290` `check_fps_range`, endpoints at `:365-367`, invalid-range guard `:407`, inclusive `end-start+1` at `:443`. Read `RDATA_FRAMESEQUENCE`, branch MANUAL/ALLFRAMES/CURRENTFRAME, endpoints via `RDATA_FRAMEFROM/TO.GetFrame(rd_fps)`, `rd_fps = int(rd[RDATA_FRAMERATE])`.
- **Resolution** — NOT in render.py. Use the `multiformat.py:508-509` idiom: `int(rd[c4d.RDATA_XRES] or 1920)` / `int(rd[c4d.RDATA_YRES] or 1080)`.
- **Per-format resolution table + path derivation** (multi-format Takes) — `multiformat.py:19` `MULTIFORMAT_DEFS` (5 dicts `{id,label,description,width,height}`: `16x9`=1920×1080, `9x16`=1080×1920, `1x1`=1080×1080, `4x5`=1080×1350, `21x9`=2560×1080) and `multiformat.py:154` `compute_format_output_path(source_path, fmt_id, mode="subfolder")` (tokens left literal; subfolder inserts `/<fmt_id>/`, suffix appends `_<fmt_id>`; both idempotent). Reuse rather than re-deriving format paths.

### 6.3 Manifest dedup (R6 + false-RED)

A child take without a `RDATA_PATH` override resolves to the **same** `(folder, template, ext, frame_set)` as the Main. In `build_manifest_from_state`, **collapse colliding entries into one before scanning** (key by resolved output tuple, using `frozenset(frame_set)`), else the folder is scanned twice and the report duplicates gaps/outliers under two Take names. Per-Take/format **coverage (R6)** is satisfied by verifying each expected Take/format produced its file set in its expected folder (KTD5 — no pixel read).

### 6.4 AOVs (R5, KTD6)

- Read the AOV set **LIVE** via the extended `aovs.get_rs_aovs(doc)` — never hardcode.
- `aovs.get_aov_multipart(doc) == True` (Multi-Part) → the entry's `aov_mode = "multipart"`; expect **one combined `.exr` per frame**, verify existence + non-zero only (per-layer deferred).
- `False` (Direct Output) → `aov_mode = "direct"`; per AOV with `direct_enabled=True` use its own `effective_path` + `file_format→ext`. **Skip AOVs with `direct_enabled=False`** (they write no separate file → expecting them is a false-WARN). A `direct_enabled` AOV whose files are missing for a frame is a **WARN** (never FAIL). In Multi-Part the same missing AOV is NOT reported (only the combined file's existence).
- Guard `REDSHIFT_AVAILABLE`; no RS → standard C4D multipass (read `RDATA_MULTIPASS_*`), `aov_mode = "none"` or a single multipass stream.
- **Exact-stem anchoring (carry-forward §4):** `scan_sequence` matches `stem.startswith(prefix)`, so a bare `prefix="beauty"` still matches `beautyMask_1001.exr` and can shadow the good `beauty_1001.exr`. **Set each entry's `prefix` to the resolved stem UP TO AND INCLUDING the separator before the frame digits** (e.g. `"beauty_"` — then `"beautyMask_1001".startswith("beauty_")` is False). This resolves the common `_`-separated case (RS AOV files are always `<base>_AOV_<name>`). **Residual (accept, note in PR):** when the resolved name has NO separator before the digits (`beauty0001`), the separator-qualified prefix can't disambiguate — a further carry-forward for a future `scan_sequence` boundary check; do NOT modify the frozen `scan_sequence` in this handoff.

### 6.5 R10 fallbacks
- No Redshift → C4D multipass, no crash.
- No valid folder / no render data → clear message, no crash.
- **Unsaved doc** (no `doc.GetDocumentPath()`): pass the audited `folder` as the report/sidecar write base and note it in the U7 dialog.
- **Cross-platform:** normalize `\`→`/` (`.replace("\\","/")`) like the existing helpers.

### 6.6 Light-group helper move (KTD1 — do this FIRST, before U5 logic)

**Why:** `postrender.py` must never import `ui/panel.py` (which will import `postrender` in U7). Circular import → package fails to load. The helpers move to `aovs.py`, which already owns `_get_rs_videopost` + the `redshift` guard.

**Move `_scan_light_groups` (currently `panel.py:3434-3462`) and `_is_lg_active_on_beauty` (`panel.py:3464-3475`) to module-level functions in `aovs.py`.** Both use `self` purely as a namespace (no `self.` attributes, no globals) → drop `self`, they become `def _scan_light_groups(doc):` / `def _is_lg_active_on_beauty(doc):` verbatim otherwise.

Free names needed in `aovs.py` and their status:

| Name | Used by | In `aovs.py`? |
|---|---|---|
| `_iter_objs` | `_scan_light_groups` | ✅ `aovs.py:8` |
| `MAX_OBJECTS_PER_CHECK` | `_scan_light_groups` | ✅ `aovs.py:7` |
| `_get_rs_videopost` | `_is_lg_active_on_beauty` | ✅ `aovs.py:91` |
| `redshift`, `c4d` | both | ✅ |
| `_safe_name` | `_scan_light_groups` | ❌ **add** → extend `from sentinel.common.helpers import _iter_objs, _safe_name, safe_print` |
| `_is_light_obj` | `_scan_light_groups` | ❌ **add** → `from sentinel.checks.scene import _is_light_obj` |

**Circular-import check (verified clean):** `checks/scene.py` does NOT import `aovs`; `aovs.py` imports nothing from `checks` today. The new `aovs → checks.scene` edge is one-way, no cycle.

**Update `panel.py`:**
1. Add `_is_lg_active_on_beauty,` and `_scan_light_groups,` to the existing `from sentinel.aovs import ( ... )` block (`panel.py:234-259`).
2. Drop the `self.` receiver at the 4 call sites: `self._is_lg_active_on_beauty(doc)` → `_is_lg_active_on_beauty(doc)` at **`panel.py:2809`** and **`:3489`**; `self._scan_light_groups(doc)` → `_scan_light_groups(doc)` at **`:2810`** and **`:3488`**.
3. Delete the two method defs (`panel.py:3434-3462`, `:3464-3475`).
4. Leave `panel.py`'s own imports of `_is_light_obj` (`:31`) and `_safe_name` (`:34`) — unaffected.

**Extend `aovs.get_rs_aovs` (`aovs.py:140-159`):** inside the per-AOV `aovs.append({...})` dict (`:150-154`), add these reads (SAME key names the reader/builder use — no `path`/`format` aliases), keeping them inside the existing per-AOV `try/except Exception: pass`:
```python
"effective_path":     aov.GetParameter(c4d.REDSHIFT_AOV_FILE_EFFECTIVE_PATH) or "",
"file_format":        aov.GetParameter(c4d.REDSHIFT_AOV_FILE_FORMAT),
"direct_enabled":     bool(aov.GetParameter(c4d.REDSHIFT_AOV_FILE_ENABLED)),
"multipass_enabled":  bool(aov.GetParameter(c4d.REDSHIFT_AOV_MULTIPASS_ENABLED)),
```
`check_rs_aovs` (`aovs.py:161-173`) only reads `["name"]`/`["enabled"]`, so the new keys are additive. **The builder must SKIP AOVs with `direct_enabled=False` in Direct-Output mode** (an AOV with Direct Output off writes no separate file → expecting it would be a false-WARN).

**Add `aovs.get_aov_multipart(doc)`** (read the *effective* flag back from the live videopost, not the GlobalSettings preference — they can diverge). Mirror `_are_caustics_enabled` (`aovs.py:118-126`), subscript access:
```python
def get_aov_multipart(doc):
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return False
    try:
        return bool(vprs[c4d.REDSHIFT_RENDERER_AOV_MULTIPART])
    except Exception:
        return False
```
(Do NOT read `GlobalSettings['aov_multipart']` — that's the *desired* value pushed at `aovs.py:196-199`, not what the scene will actually render.)

### 6.7 U5 pure-core test scenarios (Codex pytest — dict fixtures + dummy dirs)

Build these in `tests/test_postrender.py`. **U5 constructs its own in-test fixtures `missing_aov/` and `multi_take/`** (deferred from U2 because they exercise U5's manifest/AOV/Take logic). Use `tmp_path` for on-disk dummy files.

1. **(d) missing AOV, Direct-Output** (drive `audit_manifest` directly): a hand-built manifest entry with AOV `Beauty_Denoised` in `aov_mode="direct"` + a `missing_aov/` dummy dir lacking that AOV's files → `audit_manifest(manifest, folder)` returns a WARN on the affected frame(s). Same entry with `aov_mode="multipart"` → the missing AOV is NOT reported (only the combined `.exr` existence).
2. **(e) multi-take coverage** (drive `audit_manifest` directly): a hand-built manifest of 5 formats + a `multi_take/` dummy dir missing the `9x16` files → `audit_manifest` marks `9x16` not rendered, grouped by Take.
3. **Manifest dedup:** two `states` where a child take has no path override (inherits Main) → `build_manifest_from_state` collapses to ONE entry; auditing a dir does not double-count the same gaps.
4. **Range-mode → frame_set:** state with `frame_mode=2` (ALLFRAMES) uses `timeline_min/max`; `frame_mode=1` (CURRENTFRAME) → single-frame set; `frame_mode=0` (MANUAL) → `frame_from..frame_to`. Assert via `expected_frames`.
5. **Single-render inclusion:** `states` with one `is_main=True` state and no child → exactly one entry.
6. **Main-not-checked exclusion:** `states` with `is_main=True, is_checked=False` + checked children → manifest excludes the Main entry.
7. **Exact-stem anchoring:** a dummy dir with `beauty_1001.exr` (good) + `beautyMask_1001.exr` (100 B) → the entry's prefix is the separator-qualified `"beauty_"` (NOT bare `"beauty"`), so `scan_sequence` matches only `beauty_1001.exr` and does NOT mark 1001 as `truncated`. (Assert the builder emits the separator-qualified prefix.)
8. **`zfill(4)` fallback:** a resolved path with no frame number → builder flags sequence and the scan prefix expects an appended 4-digit frame.
9. **R10 unsaved-doc:** `build_manifest_from_state(states, audit_folder="/x")` when states carry no doc path → write base is the audit folder (assert entries carry that folder; no crash).
10. **Low-variance/flat-plane fixture (MAD carry-forward):** >50 % byte-identical sizes → confirm `size_outliers` returns `[]` and the aggregation surfaces size anomalies as WARN (documenting the known escape; add the absolute-floor secondary check if you implement it).

> `_read_scene_render_state`, `build_expected_manifest`, and the actual RS/token reads are **NOT** pytest-covered — they are live-MCP only (§5.2 D). Do not mock `c4d`/`redshift` to "test" them; that proves nothing and violates the split.

---

## 7. U6 — Atomic report + separate render sidecar

**Goal:** assemble the report (with dedup), write it atomically, append a summary to the SEPARATE render sidecar.
**Requirements:** R7, R8, R9, R10. **This unit is fully PURE → Codex self-verifies everything here with pytest.**

### 7.1 `build_report(findings)` — shape + cap (mirror `export_qc_report`)

Per-check dict: `{"status": "OK"|"WARN"|"FAIL", "count": int, "label": str, "items": items[:cap]}`. Mirror `panel.py:586` `export_qc_report`. Verified caps there are **non-uniform**: object-list checks `[:50]` (`:631`), textures/cross_aspect `[:30]` (`:640`/`:688`), output_paths `[:10]` (`:662`), takes `[:20]` (`:666`). **Use one uniform cap of `50` for U6** (the dominant value; 500 missing frames → `items` length 50, `count == 500`).

**Severity framing (WARN vs FAIL):**
- `missing` frames, `zero_byte`, `truncated` → **FAIL**-worthy (files genuinely absent/broken).
- `stale` (mtime cluster) and `size_outliers` → **WARN only** — mtime is a signal the codebase distrusts (Synology conflicted-copy, `baseline.py`); label stale rows *"based on mtime; unreliable on synced/copied folders"*. Never a hard FAIL. This also honors the MAD absolute-floor carry-forward (size anomalies are WARN).

### 7.2 Dedup (single-category invariant)

- A frame in `zero_byte`/`truncated` is EXCLUDED from `size_outliers` (already enforced by the §4 pre-filter rule — the caller passes only healthy frames to `size_outliers`).
- A `stale` frame does NOT count as `found`.
- **Every frame appears in exactly ONE report category.**

### 7.3 `write_report_atomic(path, report)` — mirror `baseline._write_entries` (`baseline.py:220-241`)

Copy the **mechanics**, not the payload keys:
```python
folder = os.path.dirname(path)
if folder:
    os.makedirs(folder, exist_ok=True)
tmp_path = f"{path}.tmp.{os.getpid()}"          # PID-suffixed sibling, same FS
try:
    with open(tmp_path, "w", encoding="utf-8") as h:
        json.dump(report, h, indent=2, sort_keys=True)   # report = your shape
        h.write("\n")
    os.replace(tmp_path, path)                   # atomic rename
except Exception:
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)                  # best-effort cleanup
    except Exception:
        pass
    return False
return True
```
Target `<base>_sentinel_render_report.json`, or **inside the audited folder** when the doc has no path (R10). Do NOT copy baseline's `{"schema": SCHEMA_VERSION, "entries": ...}` payload — that's baseline-specific.

### 7.4 `render_history_path(doc_path)` — factor into `versioning.py`, REUSE `parse_version_filename` (KTD7)

Add next to `get_history_path` (`versioning.py:84`), reusing the SAME stripper so all `_v###[_status]` versions share ONE render sidecar:
```python
def render_history_path(doc_path):
    """Version-stripped sidecar for U6 render-history — shares ONE file across
    all _v###[_status] versions, SEPARATE from the Versions-tab history."""
    if not doc_path:
        return None
    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _ver, _status = parse_version_filename(name_no_ext)   # REUSE :45 stripper
    return os.path.join(folder, f"{base}_render_history.json")  # NOT "_history.json"
```
`parse_version_filename` (`versioning.py:45-68`) strips `_v###[_status]` via `_VERSION_RE` (`:20`). So `robot_010_v022_FINAL.c4d` and `robot_010_v001.c4d` both → `robot_010_render_history.json`.

**KTD7 hard rule — poison pill:** the Versions tab reads/writes EXCLUSIVELY through `get_history_path` → `..._history.json` (writers: `append_history_entry:163`, `panel.py:1141`; readers: `_update_history_area:2159`, `get_latest_version_info:176`, `load_versions_for_doc:196`, pillbox). **U6 must NEVER call `append_history_entry` / `save_history`, and never write a path ending `_history.json`.** Touching any of those pollutes the Versions tab (broken rows, "File not found" on click, mis-read pillbox).

### 7.5 `append_render_history(base_or_folder, summary)`

Own load/append/atomic-write against `render_history_path` (or the audit folder for an unsaved doc). Reuse `load_history`'s defensive shape (`versioning.py:98-112`: malformed/missing → default, never crash) but with your own top-level key. Entry: `{"type": "render_validation", "version": <resolved version str>, "timestamp": <iso>, "passed": bool, "issues": {<per-check counts>}}`. Newest-first is fine. Write via your atomic writer.

### 7.6 U6 pytest scenarios (Codex self-verifies — this unit is pure)

1. **(f) OK + no contamination:** audit a `single_complete/` dummy dir → report all-OK; `append_render_history` writes `<base>_render_history.json`; **assert explicitly** the co-located `<base>_history.json` is byte-unchanged (create one first, hash before/after).
2. **Shared base across versions:** append from `robot_010_v007_TR.c4d` then `robot_010_v008.c4d` → both write the SAME `robot_010_render_history.json` (2 entries), not two per-version files.
3. **Atomic write leaves prior intact:** monkeypatch `json.dump` to raise → the pre-existing target file is unchanged and the `.tmp.<pid>` is removed; function returns `False`.
4. **Dedup single-category:** a 0-byte frame appears in exactly ONE report category (in `zero_byte`, NOT in `truncated` or `size_outliers`).
5. **Non-vacuous masking (harden the U4 `stale_plus_black` test):** the U4-era test passed vacuously (contamination only fabricated false positives; the OR "sets differ" satisfied it). In U6, where masking is exercised on a pre-filtered population, **harden the assertion to `1020 not in contaminated_result`** so it's non-vacuous — a stale/foreign frame must not mask the real anomaly at 1020, and stale/size anomalies surface as WARN not FAIL.
6. **Cap:** report with 500 missing frames → `len(items) == 50` (or your cap) and `count == 500`.
7. **Doc without path (R10):** report written into the audited folder, no crash.
8. **Missing/malformed render sidecar:** no crash; a new sidecar is created.

**U6 verification (Codex):** pytest green; explicit assert that `<base>_history.json` / Versions tab is untouched.

---

## 8. U7 — Render-tab button + report dialog

**Goal:** on-demand surface in the Render tab, showing the resolved active version + frame range so a farm/edited-scene mismatch is visible.
**Requirements:** R1, R10. **Author to the contract; human live-MCP verifies (§5.2 F). `Test expectation: none` — no pytest.**

3-step wiring (KTD2), all anchors verified current:

**Step 1 — `plugin/sentinel/ui/ids.py`, class `G`.** `1215` is FREE (grep `= 1215` → nothing; neighbors 1204, 1206, 1210–1213 TAB_GROUP block, 1214 `BTN_ADD_FRAME_TAG`). Add right after line 49:
```python
BTN_VALIDATE_RENDER = 1215  # Post-render validation (U7)
```

**Step 2 — `plugin/sentinel/ui/panel.py` `_build_tab_render` (`:1920`).** Insert AFTER the Snapshots section (ends `:1978`) and BEFORE the trailing `BFV_SCALEFIT` spacer (`:1981` — spacer must stay last). Follow the Sentinel-Frame pattern (`:1938-1942`) and `_add_section_label` (`:1856`, emits `▸ {title}`):
```python
# ── Post-Render (U7) ──
self._add_section_label("Post-Render")
self.GroupBegin(84, c4d.BFH_SCALEFIT, 1, 0)   # 84 is unused in this builder (20/80/82/61/0 taken)
self.AddButton(G.BTN_VALIDATE_RENDER, c4d.BFH_SCALEFIT, 0, 0, "Validate Render Output...")
self.GroupEnd()
```

**Step 3 — `Command()` dispatch (`:2760`).** Mirror the simple `_add_sentinel_frame_tag` sibling (`:2781`), NOT the module-level `collect_scene`:
```python
elif cid == G.BTN_VALIDATE_RENDER:
    self._handle_validate_render(doc)
```

**Handler — new panel method `self._handle_validate_render(doc)`** (the plan U7 sketch called it `_validate_render_output`; use `_handle_validate_render` — this brief is authoritative and it matches the `_handle_*` sibling pattern). Model it on `_add_sentinel_frame_tag` / `_handle_save_version`, i.e. a `SentinelPanel` method, not a module function:
1. Folder picker — `c4d.storage.LoadDialog(flags=c4d.FILESELECT_DIRECTORY)` (precedent: `panel.py:1367` collect_scene, `:2849` snapshot dir). Optionally default to the folder derived from the resolved beauty output path. `if not folder: return`.
2. `report = postrender.audit_render_folder(doc, folder)` and write it via U6 `write_report_atomic` + `append_render_history`.
3. Summary dialog that **echoes the resolved active version + frame range + mode** — e.g. *"Validating v007 · range 1001–1100 · mode Manual"* — so a farm/Team-Render mismatch (doc edited after submit) is caught by eye (mitigates the farm blind-spot; robust correlation is the deferred Trace-render query).
4. Unsaved doc → the message states the report goes to the render folder (R10). Invalid folder / no render data → clear message, no crash.
5. **Thin — NO scan logic in the panel.**

**Dialog kind (grounding E):** a read-only results view does NOT need the scene interactive while open (unlike Texture Repathing, which is async only for live Cmd+Z). Use **MODAL** — either `c4d.gui.MessageDialog(text)` for a plain summary (simplest), or a `gui.GeDialog` subclass modeled on `GateTriageDialog`/`NotesDialog` (`dialogs.py:348`/`:617`) opened `Open(c4d.DLG_TYPE_MODAL, defaultw=..., defaulth=...)` if you want a scrollable per-check list. Do NOT use `DLG_TYPE_ASYNC`.

**Human live-MCP smoke (§5.2 F):** reload no errors → button in Post-Render section → click → picker → summary with version+range+mode → report JSON written → invalid folder / unsaved doc → message, no crash.

---

## 9. House rules (CLAUDE.md — non-negotiable)

- **Edit, don't create.** U5/U6 ADD functions to the EXISTING `plugin/sentinel/postrender.py`, `aovs.py`, `versioning.py`, `ui/panel.py`, `ui/ids.py` (and optionally `ui/dialogs.py`). **No new modules.** Only new file allowed: test additions in `tests/test_postrender.py` (append if it exists).
- **No helper/installer/diagnostic scripts.**
- **Dependencies:** Python stdlib only in the pure core (`os`, `json`, `re`, `time`); `c4d`/`redshift` allowed ONLY in the impure adapter `_read_scene_render_state`, the extended `aovs.py` readers, and `ui/panel.py`. The pure functions must have **zero `import c4d`**.
- **Fallback gracefully** (R10): no RS / no render data / no folder / unsaved doc → message, never crash. Defensive style of `checks/render.py` and `versioning.load_history`.
- **Restart C4D after the package change** (the human does this before live MCP) — do NOT rely on "Reload Python Plugins" for package structure changes (live ObjectData/GeDialog instances split-brain).
- **Cross-platform:** normalize `\`→`/`.
- **KTD1 ordering:** do the light-group helper move + `aovs` extension FIRST; if `postrender.py` ends up importing `ui/panel.py`, the package won't load.
- **KTD7:** never write `_history.json` / never call `append_history_entry`/`save_history`.

---

## 10. Suggested delivery order + review checkpoint

**Order (each a reviewable slice):**

1. **KTD1 prep** — move light-group helpers to `aovs.py`, extend `get_rs_aovs`, add `get_aov_multipart`, rewire `panel.py` call sites. *(Codex: package imports clean in a stub/pure sense; human confirms live.)*
2. **U6 pure** (fully pytest-able, no C4D) — `render_history_path`, `build_report`, `write_report_atomic`, `append_render_history` + all §7.6 tests green. Landing U6 first de-risks the report/sidecar contract that U5's orchestrator feeds.
3. **U5 pure core** — `build_manifest_from_state`, `resolve_output_template`, and the PURE `audit_manifest(manifest, folder)` aggregation seam over hand-built manifests + dummy dirs; all §6.7 tests green. (`audit_render_folder`/`_read_scene_render_state` are the impure glue, author-to-contract, live-MCP only.)
4. **U5 C4D reader** — `_read_scene_render_state` + `build_expected_manifest` (author to contract; NOT pytest-verified). Flag clearly in the PR: "live-MCP verification pending."
5. **U7 UI** — ids + button + Command branch + handler + dialog (author to contract).

**Review checkpoint — what the human adversarially verifies:**
- **pytest green** for everything in §5.1 marked "Codex — pytest" (U6 fully; U5 pure core; `render_history_path`). No test mocks `c4d`/`redshift` to fake-verify the impure surface.
- **Non-contamination assert present and non-vacuous:** the U6 test proves `<base>_history.json` / Versions tab untouched; the masking test uses `1020 not in contaminated_result`.
- **Single-category dedup invariant** holds; stale + size anomalies are WARN, not FAIL.
- **Live-MCP** (human, C4D 2026.301): §5.2 A–F — U1 residuals, helper-move behavior preserved, AOV extensions read real values, U5 single-render / Main-not-checked / dedup / range-mode / real-path-match / R10, U7 smoke.
- **Scope:** no new modules; no touch to QC engine/registry/score, texture scanner, or the Versions feature; no deferred items built.
- **Single-undo:** N/A here (this feature only reads the scene + writes JSON sidecars; it makes no undoable scene edits).