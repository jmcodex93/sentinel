# Sentinel — Roadmap

> Originally **YS Guardian** (Yambo Studio). Rebranded to Sentinel in v1.5.0 — see CLAUDE.md and README.md for the heritage and attribution.

## Completed (v1.0.4 → v1.4.0)

### Fase 1 — Fix & Foundation ✅
- [x] Fix bug: safe_print used before definition
- [x] Fix bug: duplicate widget IDs in class G
- [x] Cross-platform: replace os.startfile with platform-aware opener
- [x] Add CoreMessage() for instant scene change reaction
- [x] Clean dead code: remove unused IDs, imports, threading

### Fase 2 — UI Upgrade ✅
- [x] Section headers with BORDER_WITH_TITLE_BOLD
- [x] Per-check Select/Info/Fix buttons (1 click instead of checkbox + Select)
- [x] Fix truncated labels (Shot ID, Artist)
- [x] Data-driven StatusArea renderer (lookup table, pre-allocated colors)
- [x] Reorganize layout by workflow: Scene Info → QC → Scene Tools → Render → Output

### Fase 3 — New QC Checks ✅
- [x] Unused materials (Select + Fix, cycling one-by-one)
- [x] Default naming conventions (Select, cycling)
- [x] Output path validation (tokens, empty paths)
- [x] Missing textures (files not found on disk)
- [x] RS Node texture paths via maxon API (recursive port scan)
- [x] Unify 3 texture checks into single "Assets" check

### Fase 4 — Power Features ✅
- [x] Auto-fix: lights → group, camera shift → reset, unused mats → delete
- [x] Export QC Report (JSON with score, scene stats, all check details)
- [x] Scene complexity stats (objects, polygons, materials, lights)

### Snapshot System Rewrite ✅
- [x] Cross-platform EXR→PNG via external Python + OpenEXR
- [x] Full ACES pipeline: ACEScg → sRGB matrix → ACES tonemap → sRGB OETF
- [x] Configurable RS snapshot directory (UI button + persisted settings)
- [x] Auto-discover system Python on macOS + Windows

### RS AOV Management ✅
- [x] 2-tier system: Essentials (11) / Production (17+)
- [x] Beauty pass in Essentials for rebuild verification
- [x] Conditional AOVs: Caustics (auto-detect setting), Volumes (auto-detect objects)
- [x] Compositor target dropdown: Nuke vs After Effects (persisted)
- [x] Multi-Part EXR checkbox (persisted)
- [x] Per-AOV Direct Output config: bit depth, data type, compression
- [x] Depth config per compositor: Z raw (Nuke) vs Z Normalized Inverted (AE/Frischluft)
- [x] Motion Vectors per compositor: Raw (Nuke) vs Normalized 0-1 (AE/RSMB Pro)
- [x] Global Multi-Part settings: 32-bit Float + DWAB 45
- [x] All param IDs documented in RS_AOV_PARAM_IDS.md
- [x] Named constants used throughout (discovered via dir(c4d))

### Render Presets ✅
- [x] Resolution display next to dropdown
- [x] Reset All from template (with confirmation)
- [x] Force 9:16 ↔ 16:9 toggle (reversible)
- [x] Rename buttons: Force → Reset All / Force 9:16

### Code Quality ✅
- [x] Replace 40 bare except: with except Exception:
- [x] Remove dead code (~400 lines: _force_vertical_aspect, _search_3d_model, _ask_chatgpt, etc.)
- [x] CoreMessage dirty-flag pattern (no more cache clearing on every EVMSG_CHANGE)
- [x] CHECK_COOLDOWN 0.1s → 0.5s
- [x] Safe name access for dead C4D objects (_safe_name helper)
- [x] Widget IDs renamed to match function (BTN_FORCE_VERTICAL, BTN_RESET_ALL, etc.)

---

### v1.10.0 — Collect Confiable (I4) ✅ SHIPPED (PR #13)

The delivery guarantee: after `SaveProject()`, the Collector **reopens the collected package**, re-scans its dependencies on that copy (the step Save-with-Assets skips) and seals a per-asset manifest; the receiver gets a Delivery Summary + on-disk verify.

- [x] Pure engine `plugin/sentinel/manifest.py` (stdlib-only, no `import c4d`): classify collected/missing/external, receiver-side `verify_package`, atomic IO; 24 pytest
- [x] `collect_scene` Phase 2.6: reopen delivered `.c4d` → `scan_all_texture_paths` on the copy → asset section merged into the existing `sentinel_manifest.json` (never silently empty: `scan_status` travels); success dialog with counts, no blocking on missing
- [x] Plugin inventory (objects+tags+materials, `>= 1M` IDs) with **native-Maxon denylist** (XPresso/SDS/Cloner/Data Tag/Bevel verified live); renderer IDs always flagged
- [x] Reception: conditional «Delivery Summary...» (Versions tab, only with an asset-schema manifest adjacent) + «Verify» → LOST-in-transfer detection
- [x] Cross-platform: manifest paths normalized to `/` at write, tolerant join at verify (final-review Critical)
- [x] Verification ladder: pytest 305/305 + per-task adversarial reviews + fixtures live (violating → 1 missing with provenance; clean → 0) + **real production delivery** (39 assets, 4 missing corroborated 1:1 by SaveProject, 0 false positives; LOST test with 3 deleted textures) — 2 production-found bugs fixed same-day (stale re-scan on rename-refusal, native-ID noise), documented in `docs/solutions/`
- [x] Process ledger: `docs/audit/2026-07-16_i4_sdd_ledger.md`; design + plan in `docs/superpowers/`
- [ ] **v2 deferred**: `hash` field (reserved, null), standalone `verify.py` for receivers without C4D, farm pre-flight, Delivery Summary button visible without tab switch (rebuild-on-doc-change)

### v1.9.0 — Post-Render Validation (I1) ✅ SHIPPED (PR #4)

The render safety net: a "Validate Render Output..." button (Render tab → Post-Render) audits rendered frames **on disk** against what the scene says should exist — closing the gap where Sentinel guarded everything up to the render button and nothing after.

- [x] Pure engine `plugin/sentinel/postrender.py` (stdlib-only, **no module-level `import c4d`**; C4D reads function-local in a thin adapter). Escalera de verificación: pytest + mutation + fixtures deterministas.
- [x] Audits: sequence gaps (range-by-mode Manual/Current/All), 0-byte/truncated, size-outlier SPC (MAD, WARN), previous-session **stale** cluster (bimodal mtime, WARN, `MIN_STALE_GAP_SECONDS=300` floor), AOV presence (WARN), per-Take/format coverage
- [x] Scene-aware **expected manifest**: render data + takes with render-selection gate (`IsChecked`/current take — Main excluded when not the render target), resolution/format→ext, RS AOVs via extended `aovs.get_rs_aovs` (`effective_path`/`file_format`/`direct_enabled`) + `get_aov_multipart`
- [x] Atomic JSON report + **separate** `<base>_render_history.json` sidecar (never the Versions-tab history — KTD7); light-group helpers moved to `aovs.py`
- [x] Built via the Codex-implements / we-review loop (grounding→brief→adversarial critique→Codex→pytest+mutation+adversarial review→**live-MCP**). First real production run caught 2 false-positives (beauty↔AOV prefix collision, stale sub-second jitter) → fixed
- [x] 171 pytest + mutation + two adversarial passes + live-MCP on a real RS scene; merged to main (PR #4); v1.9.0; CLAUDE.md + README + changelog updated
- [ ] **v2 deferred** (Scope Boundaries): per-layer EXR decode / real corruption (needs external OpenEXR), render-complete hook (no MessageData RENDER today), "Trace render" folder→version query, delivery-spec matrix, render cost/time estimator, rolling-window SPC. Minor open: reader broad-except surfacing, light-group AOV file-count coverage

### v1.8.0 — Sentinel Frame (per-camera multi-format tag) ✅ SHIPPED (PR #3)

Supersedes the two WIP entries below. A single per-camera `SentinelFrameTag` (TagData, plugin id 2099073) is the one entry point for the whole multi-format workflow: live viewport guides/mask/HUD, one-click **rename-safe** delivery Takes, and true **WYSIWYG crop** that matches the guides.

- [x] `TagData.Draw` **works** with `TAG_VISIBLE | TAG_EXPRESSION | TAG_IMPLEMENTS_DRAW_FUNCTION` — no ObjectData companion drawer needed (corrects the v1.5.6/v1.6.0 hybrid assumption; CLAUDE.md fixed)
- [x] Draw computes guides inline from the BaseContainer (clone-safe, no cross-context cache); mask with opacity; per-format nudge; HUD + "Takes out of date" staleness
- [x] Engine extensions (additive): camera-scoped take naming, host-camera binding, rename-safe re-run via BaseLink resolver, single-undo, idempotent Set Output
- [x] **Crop-first**: `format_crop_values` — inscribed crop via **focal** (universal — works on standard AND Redshift; aperture doesn't), gate-relative film-offset nudge; wider/equal targets crop by resolution alone; guides suppressed when viewing a format take
- [x] QC #12 nudge-aware (reads the tag's per-format nudge; identical without a tag)
- [x] Panel entry: Render tab → "Add Sentinel Frame to camera"
- [x] 129 pytest + live MCP verification (standard + Redshift, all formats)
- [x] Merged to main (PR #3); version bumped to v1.8.0; README + CLAUDE.md + changelog updated
- [x] Legacy panel entries retired (Multi-Format dialog + Safe-Area Overlay); overlay ObjectData fully unregistered
- [x] `MultiFormatDialog` + dead `_open_multiformat_dialog` removed from the code (−304 lines); the shared engine (`generate_multiformat_takes`) stays, so old Takes keep working

### v1.5.8 — Multi-Format polish 🚧 SUPERSEDED by v1.8.0 (Sentinel Frame)

> Harvested into Sentinel Frame: Preserve-Vertical focal math (now the universal crop lever), the dim intersection mask (→ tag mask + opacity), and `format_crop_in_master_ndc` (→ `crop_rect_in_master_ndc` for the guides). Branch closes after the harvest.

Refinements to the Safe-Area Overlay + Multi-Format suite, in the working tree alongside v1.6.0.

- [x] **Preserve Vertical composition mode** — third Composition Mode option mirroring the C4D Frame plugin's default: focal-length override per format keeping the vertical field constant (`compute_target_focal_preserve_vertical(source_focal, src_w, src_h, ...)`)
- [x] Enriched per-format HUD labels in the viewport overlay (pretty aspect id + canonical resolution)
- [x] Optional dim mask outside the **intersection** of all active formats' safe areas (pass 1 underneath the outline rectangles)
- [x] `format_crop_in_master_ndc(fmt_id, master_aspect)` helper
- [ ] Verify in C4D: HUD labels, dim mask toggle, Preserve Vertical focal override per take

### v1.6.0 — Camera Frame per-camera overlay 🚧 SUPERSEDED by v1.8.0 (Sentinel Frame)

> This hybrid tag+drawer prototype was built on the (incorrect) assumption that `TagData.Draw` never fires in C4D 2026. Sentinel Frame proved `TagData.Draw` works with `TAG_IMPLEMENTS_DRAW_FUNCTION`, so the ObjectData companion drawer is unnecessary — the whole feature is a pure tag. Superseded; the `CameraFrameTag`/`CameraFrameDrawer` prototype is not shipped.

Per-camera multi-format framing config (vs the scene-global v1.5.6 overlay). Benchmark parity with the mariosundays "C4D Frame" tag plugin.

- [x] `CameraFrameTag` (TagData, plugin id 2099073) attached to a camera — per-format enable + color params (`CAMFRAME_*` ids 1011–1502)
- [x] `CameraFrameDrawer` (ObjectData, plugin id 2099074) — auto-managed companion marker that does the actual viewport drawing, because `TagData.Draw` registers but never fires in C4D 2026 (hybrid architecture)
- [x] `find_or_create_camera_frame_drawer(doc)` — locate by plugin TYPE or create at scene root
- [x] Resource triplets: `plugin/res/description/camera_frame.res|.h`, `camera_frame_drawer.res|.h`, `strings_us` .str files
- [x] Registration in `Register()` guarded by `_CAMERA_FRAME_TAG_AVAILABLE` (graceful fallback)
- [ ] Verify in C4D: tag on camera draws frames, colors editable in AM, drawer auto-created on first tag
- [ ] Document in CLAUDE.md + README on release

---

### v1.5.7 — Texture Repathing Tool ✅

Multi-renderer bulk find/replace + smart-fix utility for texture paths. Pulled forward from the v1.6.0 "Asset Health & Validation" tier — texture path breakage is a daily pain point and the highest-impact item in that bucket.

#### Investigation phase (multi-renderer texture storage)
- [x] Probed how each renderer stores texture paths — they are all different. Redshift/Arnold use maxon node graphs; Octane uses a legacy shader chain (`ID_OCTANE_IMAGE_TEXTURE` 1029508, not a maxon graph); RS Dome Light HDR is a compound DescID (`obj[ROOT_ID, REDSHIFT_FILE_PATH]`); Arnold Sky HDR is an Xbitmap on the object; Octane Environment HDR lives in a tag shader chain.
- [x] Discovered `node.GetInputs()` does not return texture-bearing ports in C4D 2026 — must walk `GetChildren()` recursively and read `GetPortValue()` on every leaf.
- [x] Confirmed node-graph writes need an explicit `transaction.Commit()` — the `with graph.BeginTransaction()` block rolls back silently on exit otherwise.
- [x] Probed undo: `doc.AddUndo(c4d.UNDOTYPE_CHANGE, material)` anchors the `StartUndo`/`EndUndo` bracket so the transaction's `UndoMode.ADD` joins the document undo step. Also found `doc.DoUndo()` from the Script Manager is an unreliable test proxy — real Cmd+Z verified via the Edit menu.

#### Scan + writers (sentinel_panel.pyp)
- [x] `scan_all_texture_paths(doc)` — structured TextureRecord scan across node graphs, classic shader chains, BaseContainer params, RS object file-refs, Alembic, tag shader chains
- [x] `_scan_node_graph` (RS/Arnold) + `_scan_shader_chain` (Xbitmap + Octane image, material/object/tag)
- [x] `_classify_texture_path` — OK / absolute / missing / asset_uri / empty; `relative://` resolved via common subdir search
- [x] `apply_texture_path_change` — per-source-type writer dispatch; maxon transaction with mandatory Commit for node graphs
- [x] Pure helpers: `compute_relative_texture_path`, `find_missing_texture_candidates`, `_resolve_relative_texture`, `_looks_like_texture_path`

#### Dialog + UI
- [x] `TextureRepathingDialog` — async (not modal, so Cmd+Z works), `CoreMessage`/`Timer` auto-refresh
- [x] `TextureListArea` UserArea wrapped in a native `ScrollGroup` (vertical scroll); status filter; counts summary header
- [x] Bulk Find/Replace — case-insensitive default + "Match case" toggle; `re.sub` lambda replacement (Windows backslash-safe)
- [x] Last-5 Find/Replace presets persisted in `sentinel_settings.json` (`load_repath_presets` / `save_repath_preset`), Recent combo
- [x] Smart Actions — Auto-Find Missing, Make All Relative, Clear pending; per-row `[...]` file picker
- [x] Apply All — single undo step (`StartUndo`/`EndUndo`), per-change error capture, summary dialog
- [x] Tools tab → Asset Management → "Texture Repathing..." button; QC #6 Assets Info → contextual launch

**Why this version**: closes the loop opened by QC #6 — the check already *detected* asset path problems; now Sentinel also *fixes* them, in bulk, across every renderer, undo-safe. V-Ray support intentionally dropped (out of studio scope).

---

### v1.5.6 — Cross-Aspect Safe-Area Viewport Overlay ✅

Closes the v1.5.5 deferred work: live colored rectangles rendered in the active camera viewport showing each multi-format Take's crop region. Same crop-interpretation math as QC #12, so the artist composes against the same safe areas the check validates against.

#### Investigation phase
- [x] Probed `TagData.Draw` in C4D 2026 — registers cleanly but `Draw` is never invoked by the Python viewport pipeline (only `Init` + `Execute` fire). Verified with a throwaway probe plugin.
- [x] Probed `ObjectData.Draw` in C4D 2026 — `Draw` fires reliably in `DRAWPASS_OBJECT` regardless of selection. `bd.SetMatrix_Screen()`, `bd.DrawLine`, `bd.DrawHUDText`, `bd.GetSafeFrame()` all verified working. Confirmed via the OCIO node 2025 SDK example.
- [x] Discovered `bd.GetSafeFrame()` returns the letterboxed render-frame rectangle within the viewport — eliminates the need for manual letterbox math.
- [x] Selected ObjectData architecture (rejected TagData hybrid as unnecessary complexity for a scene-wide overlay).

#### Resource files (new `plugin/res/` folder)
- [x] `c4d_symbols.h` — module-wide symbol table (dummy + room for future)
- [x] `description/safearea_overlay.res` — `INCLUDE Obase`, no user-facing parameters (all state in the panel singleton)
- [x] `description/safearea_overlay.h` — header
- [x] `strings_us/description/safearea_overlay.str` — localized name "Sentinel Safe-Area Overlay"

#### Plugin code (sentinel_panel.pyp additions)
- [x] `SAFE_AREA_OVERLAY_PLUGIN_ID = 2099072` constant
- [x] `_SAFE_AREA_COLORS` palette — white master, orange Reels, cyan square, magenta portrait, yellow cinema
- [x] `_SafeAreaOverlayState` module-level singleton — `enabled` flag + `master_aspect` + cached `format_rects` list of (fmt_id, color, master_ndc_safe_box). `update_from_doc()` recomputes the cached rectangles from the active multi-format Takes
- [x] `_overlay_state` global instance, shared between the panel and the marker
- [x] Defensive `_SAFE_AREA_OBJECT_AVAILABLE` flag — if `plugins.ObjectData` or any draw constants are missing in this C4D build, fall back to `object` base and skip registration (panel still works)
- [x] `SafeAreaOverlayObject(plugins.ObjectData)` — `Init` + `Draw`. Draw body: only fires on `DRAWPASS_OBJECT`; reads `_overlay_state`; queries `bd.GetSafeFrame()`; maps each format's master-NDC safe-box to pixel coords; draws 4 outline lines + HUD label per format
- [x] `find_or_create_safe_area_overlay_object(doc)` — locate by plugin TYPE (not name → robust to rename) or create at scene root with `StartUndo/EndUndo`
- [x] `RegisterObjectPlugin` call in `Register()`, guarded by `_SAFE_AREA_OBJECT_AVAILABLE` flag, non-fatal failure (just logs)

#### Panel UI
- [x] `CHK_SAFE_AREA_OVERLAY` checkbox added to Render tab → Multi-Format Setup section
- [x] Checkbox state synced from `_overlay_state.enabled` on every tab rebuild (singleton survives rebuild)
- [x] Command handler: toggle ON → `find_or_create_safe_area_overlay_object(doc)` + `update_from_doc(doc)`; toggle OFF → just flips flag (Draw becomes no-op)
- [x] `EventAdd` after toggle for immediate viewport refresh
- [x] Multi-Format orchestrator dialog's post-action also calls `_overlay_state.update_from_doc(doc)` so regenerating Takes refreshes the cached rectangles for the next redraw

#### Composition Mode interaction (documented)
- [x] Overlay uses the crop-interpretation model regardless of Composition Mode (matches QC #12)
- [x] Mode "None" + overlay: rectangles match what you'd get by cropping the master in post (the GSG Social Frame workflow)
- [x] Mode "Resize Canvas" + overlay: rectangles are a composition reference, not an exact render preview (each take recomposes the camera per format)
- [x] User-facing docs in README + CLAUDE.md explain this clearly

**Why this version**: closes the live-feedback loop on cross-aspect delivery. With the overlay enabled, artists compose against the actual delivery crops in real time, the QC #12 check validates those crops, and the Multi-Format Setup generates the per-aspect Takes. End-to-end multi-format workflow without leaving the viewport.

---

### v1.5.5 — Cross-Aspect Safe-Area QC + Multi-Format refactor ✅

After v1.5.4 shipped Multi-Format Setup, user testing showed two things: the "Auto-FOV" option (vertical-FOV-constant) didn't match the artist's mental model, and there was no automated way to verify subject framing across the generated delivery formats. v1.5.5 addresses both.

#### QC Check #12 — Cross-Aspect Safe Area

The check answers "if I deliver this scene as 16:9, 9:16, 1:1, 4:5, and 21:9, will my key compositional elements stay inside each format's safe area?". Opt-in marking via UserData; runs against all active Multi-Format Takes; reports per-(object × format × frames) violations with offending edges.

##### Pure helpers (Step 1)
- [x] `SAFE_AREA_INSETS` per-format dict with platform-grounded defaults (16x9: 5% symmetric; 9x16: 8/15/5/10 for IG Reels; 1x1, 4x5, 21x9 calibrated per platform UI)
- [x] `safe_area_ndc_box(fmt_id)` — convert insets to format-local NDC bounds
- [x] `format_safe_area_in_master_ndc(fmt_id, master_aspect)` — **crop interpretation** of the safe area in master NDC space
- [x] `project_world_to_ndc(camera_mg_inv, world_point, h_fov_rad, aspect)` — manual perspective projection (C4D left-handed +Z forward)
- [x] `world_bbox_corners(obj)` — 8 AABB corners with recursive `GetCache()` fallback for generators (cloners, MoText)
- [x] `corners_violation_sides(corners_ndc, safe_box)` — set of `{left, right, bottom, top}` violated edges
- [x] Math verified standalone with 10 sanity tests (NDC convention, edge cases, asymmetric insets, behind-camera handling)

##### UserData marker (Step 2)
- [x] `[Sentinel] Safe Area Subject` UserData boolean (prefix avoids cross-plugin collisions)
- [x] `mark_object_safe_area` / `unmark_object_safe_area` / `is_object_marked_safe_area` / `find_marked_safe_area_objects`
- [x] Persists natively in `.c4d` save (no sidecar JSON needed)
- [x] Idempotent mark; full removal of UD entry on unmark (no fossil False entries)

##### Take projection resolvers (Step 3)
- [x] `find_active_multiformat_takes(doc)` — match by name against `MULTIFORMAT_DEFS` ids (bare or `_suffix` patterns)
- [x] `get_take_camera_h_fov_rad(take, cam, td)` — effective horizontal FOV reading focal-length override (v1.5.5+ convention) → FOV override (legacy) → camera native
- [x] `get_take_resolution` / `get_take_aspect` / `resolve_take_projection_params` — one-stop helper for the orchestrator

##### Orchestrator (Step 4) — `check_cross_aspect_safe_area`
- [x] Crop-interpretation model: project bbox once into the master Take's NDC, then check each format as a centered crop region with per-side insets
- [x] Sample strategies: `current_frame` (cheap, auto-refresh) and `keyframes` (full sweep, click Info)
- [x] `_gather_keyframe_sample_frames` — union of PSR-track keyframes + midpoints between consecutive keys; cap of 50 samples
- [x] `_evaluate_object_at_frame` — `SetTime` + `ExecutePasses` per sample frame; original time restored via try/finally
- [x] Returns flat list of violation dicts (one per object × fmt_id) — matches the pattern of other QC checks
- [x] Handles all-corners-behind-camera (skips the object for that take)

##### UI integration (Steps 5–6)
- [x] Row #12 in QC tab with Select + Info buttons (`BTN_SEL_CROSS_ASPECT`, `BTN_INFO_CROSS_ASPECT`)
- [x] Score header reads `X/12` (was `X/11`)
- [x] StatusArea + click-row mapping updated to include `cross_aspect`
- [x] Info dialog shows per-object breakdown: `✗ 9x16: out by left, right, bottom @ frames 1010–1030`
- [x] Select button selects all objects with at least one violation (deduplicated, ignores fmt_id)
- [x] Tools tab → **QC Marking** sub-section with "Mark / Unmark Safe Area Subject" smart-toggle button (`BTN_MARK_SAFE_AREA`)
- [x] Smart toggle: all marked → unmark; any unmarked → mark all (align toward "marked")
- [x] Empty selection → friendly hint dialog
- [x] Full undo wrap; `check_cache.clear()` + `self._refresh()` after operation for immediate panel update

##### Step 7 — Viewport overlay (deferred to v1.5.6)
- [ ] `c4d.plugins.SceneHookData` and `RegisterSceneHookPlugin` were removed/migrated in C4D 2026
- [ ] Local SDK clone (Maxon 2026 examples) confirms zero references to SceneHookData registration
- [ ] Prototype code removed cleanly from v1.5.5; QC #12 ships without live overlay
- [ ] Probable replacement paths for v1.5.6: TagData on active camera (Draw fires per redraw, API confirmed in 2026); MessageData with EVMSG_DOCUMENTRECALCULATED

#### Multi-Format Setup — composition mode refactor

The v1.5.4 "Auto-FOV" toggle is replaced by a clearer **Composition Mode** dropdown:

- [x] **None** (default) — only resolution + output path overrides; camera intact. Matches GSG Social Frame plugin behavior.
- [x] **Resize Canvas** — `CAMERAOBJECT_APERTURE` (sensor) override using AR_ResizeCanvas math: `new_aperture = source × target_width / source_width`. Sensor-based avoids breaking focal-length animations + DOF.
- [x] Helper `compute_target_aperture(src_aperture, src_w, target_w)` (replaces the now-unused vertical-FOV-constant math)
- [x] Mode "None" defensively clears any stale FOV/focal/aperture overrides on re-run (clean state for users with v1.5.4-generated Takes)
- [x] Helper `_reset_camera_dimensions_to_native(take, td, cam)` — sets overrides to native values when full removal isn't reliably available across C4D versions

#### Multi-Format bug fixes (v1.5.4 carry-over)

- [x] `take.SetCamera(td, source_cam)` now called on every generated Take (was missing → fell back to scene active camera)
- [x] `FindOrAddOverrideParam` is find-OR-add, not find-and-update — explicit `SetParameter` call afterwards ensures the value is written
- [x] C4D physical / Redshift cameras clamp `CAMERAOBJECT_FOV` overrides to focal-derived native; the new Resize Canvas mode uses sensor (`CAMERAOBJECT_APERTURE`) which isn't clamped

#### Other bug fixes shipped in v1.5.5

- [x] Panel `_refresh()` crash when reopening on a non-QC tab: `self.ua` was `None` because `_build_tab_qc` hadn't run yet — added `if self.ua is not None` guard matching the existing `score_ua` guard
- [x] NDC projection sign convention: corrected from `-Z forward` (OpenGL) to `+Z forward` (C4D left-handed). First iteration of QC #12 reported every visible corner as "behind camera"

**Why this version**: closes the multi-format delivery loop. v1.5.4 generated the Takes; v1.5.5 verifies the subjects stay framed across them. The artist marks what matters, Sentinel watches the boundaries.

---

### v1.5.4 — Multi-Format Render Setup ✅

One-click generator: creates child Takes for the standard delivery aspect ratios, each with its own cloned Render Data and optional camera FOV adjustment. Eliminates manual duplication when shipping the same animation to social formats.

#### Format definitions
- [x] 16:9 Landscape (1920×1080) — YouTube, TV, default
- [x] 9:16 Vertical (1080×1920) — Reels, Stories, TikTok
- [x] 1:1 Square (1080×1080) — IG Square, Twitter
- [x] 4:5 Portrait (1080×1350) — IG Feed
- [x] 21:9 Cinema (2560×1080) — Wide banner, cinema
- [x] All 5 formats pre-checked by default in dialog

#### Orchestrator (`generate_multiformat_takes`)
- [x] Resolves source Take, source Render Data, source camera (handles `GetEffectiveRenderData` returning a tuple in some C4D versions)
- [x] Creates child Take per format under the current/source Take via `td.AddTake(name, parent, None)`
- [x] Clones source Render Data with `GetClone(COPYFLAGS_0)` + `InsertRenderDataLast` + `take.SetRenderData(td, rd)`
- [x] Overrides per-Take resolution (`RDATA_XRES/YRES`) + output path (`RDATA_PATH`)
- [x] Auto-FOV: `take.FindOrAddOverrideParam(td, source_cam, fov_id, target_fov)` keeps Vertical FOV constant by computing `target_h_fov = 2*atan((target_aspect/source_aspect)*tan(source_h_fov/2))`
- [x] Idempotent: re-running reuses existing Takes by name, updates RD + FOV in place; "Update existing OFF" → skip and report
- [x] Full `StartUndo`/`EndUndo` wrapping → single Cmd+Z reverts the whole batch
- [x] Returns `report` dict with `created` / `updated` / `skipped` / `errors` lists for the UI

#### Modal dialog (`MultiFormatDialog`)
- [x] 5 format checkboxes with resolution + description columns
- [x] Output structure combo: per-format subfolder (default) or filename suffix
- [x] Auto-adjust FOV checkbox (default ON)
- [x] Update-existing-Takes checkbox (default ON)
- [x] Tip text surfacing the two compose-and-derive schools (master 1:1 crop vs primary format + FOV)
- [x] Source caption seeded from active document: `"Source: Take 'Main' · 1920×1080"`

#### Panel integration
- [x] New section in Render tab between Render Preset and Redshift AOVs
- [x] Single button "Generate Format Takes..." opens the modal
- [x] On confirm → orchestrator → summary `MessageDialog` with per-Take counts
- [x] `check_cache.clear()` + `EventAdd` after generation so panel re-syncs

**Why**: Studios deliver the same animation in 3–5 formats. Manual duplication (clone render data, change res, change path, fix camera FOV per format) is repetitive and error-prone. Multi-Format Setup turns ~10 minutes of clicking per scene into one dialog. Maintaining vertical FOV across formats is the **Social Frame** pattern used widely in the mograph community for keeping subject framing consistent across crops.

**Future work** (not blocking v1.5.4):
- Cross-aspect safe-area QC (warn if keyframed objects exit the safe area intersection of active formats) — slated for v1.5.5
- Deeper token integration (`$take`, `$prj`) in the output path field
- Configurable format presets per studio

---

### v1.5.2 — UI/UX Redesign: Scene Header + Tabs ✅

After 5 versions of additions (v1.4.0–v1.5.1), the panel had grown to ~70 visible elements stacked vertically with no clear hierarchy. This release introduces a tabbed structure with a always-visible Scene Header.

#### Scene Header (always visible, top of panel)
- [x] Filename caption (read-only, centered) showing the active document — uses `▸` BMP triangle (📁 emoji renders as fallback glyph in C4D static text on macOS)
- [x] Shot ID + Artist editable fields
- [x] `ScoreHeader` UserArea moved here from inside QC group — provides project-wide health summary regardless of active tab

#### Tabs (4 tabs via `CUSTOMGUI_QUICKTAB`)
- [x] **QC** — 11 quality check rows + Select/Fix/Info buttons + Export QC Report
- [x] **Render** — Preset row, Redshift AOVs (Comp + Multi-Part + tier buttons), Snapshots (dir + Save Still + Open Folder)
- [x] **Versions** — Notes summary + Edit, Last version pillbox, Save Version + Collect Scene, Recent Versions list with filter
- [x] **Tools** — Layout & Hierarchy / Object & Animation / Camera Rigs sub-sections
- [x] Tab labels declared via `_quicktab.AppendString(idx, label, selected)`
- [x] Tab switch handled via `Command(G.TAB_BAR)` → check `IsSelected(i)` for each tab

#### Dynamic rebuild on tab switch
- [x] `HideElement` reports True but does **NOT** collapse layout space in C4D 2026 (verified empirically with debug logging)
- [x] Solution: single `TAB_CONTAINER` group; `LayoutFlushGroup` on switch + rebuild via `_build_tab_*()` methods + `LayoutChanged`
- [x] StatusArea / HistoryArea instances persist on `self`; re-attached after rebuild
- [x] Combo boxes (preset, comp target, history filter) repopulated via `AddChild` in each rebuild
- [x] Click callbacks (StatusArea, HistoryArea) re-wired after `AttachUserArea`
- [x] Per-tab labels (snapshot dir, last version, notes summary, history list) refreshed immediately after rebuild

#### Footer (always visible, bottom of panel)
- [x] GitHub + Report Bug buttons — the only two persistent secondary actions

#### Documented C4D limitation: panel does not auto-shrink
- [x] When tab content gets smaller, the panel window does NOT shrink. Confirmed by Maxon SDK docs and Plugin Cafe staff: there is no `SetSize`, `ResizeWindow`, or `FitToContent` API for docked panels. Even Maxon's own panels (Take Manager, AOV Manager) have this behavior.
- [x] `BFV_SCALEFIT` spacer at the end of each tab absorbs the gap WITHIN the layout (no orphan widgets visible), but the window frame stays at its tallest seen size until manual resize.
- [x] Documented in CLAUDE.md "Known Limitations" so future contributors don't waste time looking for an API that doesn't exist.

#### Key bugfix during the redesign
- [x] Empty `GroupBegin/End` with `BFV_SCALEFIT` does NOT absorb space in C4D 2026 — must use `AddStaticText(..., BFV_SCALEFIT, ..., "", ...)` instead. Empty groups have zero min-size and BFV_SCALEFIT does not "wake them up".
- [x] `Global2Local(x, y)` does NOT return user-area-local coords in C4D 2026. The fix (already in v1.4.4): `Local2Global()` with no args returns `{'x': N, 'y': M}` — the user-area's window origin; subtract from raw `msg[BFM_INPUT_X/Y]`.

**Why**: Mograph artists scan the panel hundreds of times per session. ~70 visible elements with no hierarchy = high cognitive load. Tabbed layout reduces visible elements to ~20 at a time, while the Scene Header keeps the most critical info (filename, QC score, scene metadata) always glanceable regardless of active tab. Mirrors how professional plugins (X-Particles, GSG ecosystem) organize density.

---

### v1.5.1 — Scene Notes & TODOs + Clean Delivery Naming ✅

#### Scene Notes & TODOs (per-scene sidecar)
- [x] Pure helpers: `get_notes_path`, `load_notes`, `save_notes`, `add_todo`, `toggle_todo`, `delete_todo`, `summarize_notes`, `has_pending_todos` — all unit-tested
- [x] Sidecar JSON `<base>_notes.json` (parallel to `<base>_history.json`) — shared across all versions of the same scene base
- [x] `NotesDialog` modal: free-form notes textarea + TodoArea custom user area with checkbox toggle + delete (×) + add new TODO
- [x] `TodoArea` GeUserArea: alternating row backgrounds, custom drawn checkboxes (green when done), text dimming for completed items, click zones (left=toggle, middle=toggle, right=delete)
- [x] Panel caption: `⚠ Notes: text + 3 TODOs (2 pending)` with warning prefix when there are pending TODOs
- [x] Cancel discards changes (deepcopy on dialog open); Save persists via `save_notes`
- [x] Dialog header explicitly explains "Notes apply to ALL versions of this scene. For version-specific commentary, use the Save Version comment field."

**Why**: Mograph artists return to projects weeks later and lose context (client feedback, pending fixes, decisions). Save Version comment captures version-specific changes; Scene Notes captures project-level state that spans the whole scene's lifetime.

#### Clean delivery naming (Collect Scene)
- [x] Capture original scene base BEFORE `SaveProject` (which moves the doc to the delivery folder and changes its name)
- [x] After SaveProject, rename C4D's auto-generated `<folder>.c4d` → original clean base `.c4d` (e.g., `collected.c4d` → `test.c4d` from `test_v006.c4d`)
- [x] Update `doc.SetDocumentPath/Name` + `EventAdd` so the C4D title bar and panel reflect the rename
- [x] Refuse to overwrite an existing file at the desired path (defensive)
- [x] Manifest now includes `original_filename`, `original_version`, `original_status` for traceability — the receiver knows which version this delivery came from

**Why**: C4D's `SaveProject` uses the delivery folder's basename as the .c4d filename, which loses the scene's identity (`test_v006.c4d` collected to `/Desktop/collected/` becomes `collected.c4d`). For a delivery, the receiver wants `test.c4d` with all the version metadata in the manifest, not the folder name. This matches how ShotGrid/Prism/Maya pipelines treat published files.

#### Notes integration (manifest + QC report)
- [x] Scene Collector manifest includes `notes` section: summary, text, todos array, pending_count, updated timestamp
- [x] Sidecar `<base>_notes.json` copied to delivery folder (so it travels with the .c4d)
- [x] Naming match preserved: clean delivery name + matching sidecar (`test.c4d` ↔ `test_notes.json`)
- [x] QC report export includes the same `notes` section (always present, with empty defaults if no sidecar)
- [x] Collect Scene success dialog warns when there are pending TODOs: `⚠ 2 pending TODO(s) in scene notes`

**Why**: Notes and TODOs are useful only if they reach the receiver and get included in QC reports. Otherwise they live only on the artist's machine.

#### Bugfix: pre-capture notes for Collect Scene
- [x] Originally, notes were read AFTER `SaveProject` — but SaveProject changes the doc's path/name, breaking `get_notes_path()`. Fixed by capturing notes path + data BEFORE SaveProject and using the cached values for manifest/copy.

---

### v1.5.0 — Rebrand: YS Guardian → Sentinel ✅

After 5 versions of additions (v1.4.0–v1.4.4), the plugin had outgrown the "YS Guardian" identity. v1.5.0 marks the rebrand to **Sentinel** while keeping the Yambo Studio heritage explicitly credited throughout.

#### Code changes
- [x] `PLUGIN_NAME` → `"Sentinel v1.5.0"`
- [x] Plugin file renamed: `ys_guardian_panel.pyp` → `sentinel_panel.pyp`
- [x] Settings file: `ys_guardian_settings.json` → `sentinel_settings.json` with **silent auto-migration** on first load (no preferences lost)
- [x] Manifest key: `ys_guardian_manifest` → `sentinel_manifest`
- [x] Scene Collector manifest filename: `ys_guardian_manifest.json` → `sentinel_manifest.json`
- [x] GitHub URLs: `jmcodex93/ys-guardian` → `jmcodex93/sentinel`

#### Build / install
- [x] `sync.sh` updated — copies to `plugins/Sentinel/` (mkdir -p safe)
- [x] Old `plugins/YS_Guardian/` must be removed manually (sync.sh prints a reminder)

#### Documentation
- [x] README.md: title, header, all references; new "Rebrand" changelog entry; License section credits Yambo Studio origin; Special Thanks adds Yambo Studio
- [x] CLAUDE.md: project overview rewritten with rebrand context; version history v1.5.0 entry; settings filename
- [x] ROADMAP.md: header note about rebrand; this section
- [x] Plugin file constants and references all updated

#### Why "Sentinel"
After 5 rounds of community-naming exploration (covering watchdog/guardian synonyms, mograph craft words, Italian/Spanish heritage options, mythology, cinema terms), Sentinel won as the natural evolution of Guardian — same watchdog DNA, more adult/professional brand, single word, easy global pronunciation. The Yambo Studio origin is explicitly credited everywhere, not buried.

---

### v1.4.4 — Browse Recent Versions inline ✅

#### HistoryArea custom-drawn list
- [x] Pure helpers: `load_versions_for_doc`, `filter_versions_by_status`, `format_version_row` + `FILTER_ALL` sentinel
- [x] `HistoryArea` GeUserArea with custom drawing — color-coded status badges (WIP grey / TR amber / CR blue / FINAL green / custom purple), version label, comment, QC score, relative time
- [x] Alternating row backgrounds (zebra) for legibility
- [x] Empty states: "scene not saved yet" / "no versions yet" / "no versions match filter"
- [x] Filter ComboBox: All / WIP / TR / CR / FINAL
- [x] Click row → confirmation dialog with version preview + open via `c4d.documents.LoadFile`
- [x] Smart unsaved-changes warning, "File not found" handling, same-doc detection

#### Critical fix: user-area click coordinate conversion
- [x] Discovered C4D 2026 Python `Global2Local(x, y)` does NOT return area-local coordinates — empirical test showed `local_y=610` for a click in a user area only 120px tall
- [x] Workaround: `Local2Global()` (no args) returns the user area's window origin as `{'x': N, 'y': M}`; subtract from raw `msg[BFM_INPUT_X/Y]` to get reliable local coords
- [x] Shared helper `_ua_local_coords(user_area, mx, my)` used by both `StatusArea` and `HistoryArea`
- [x] Fixed StatusArea click handling (was working "by luck" because rows are near top of panel)

**Why**: Smart Save Version writes a rich history JSON, but in v1.4.3 only the latest entry was surfaced (via the "Last version" pillbox). The full list closes the read side of the loop and lets artists actually use the metadata they're capturing — filter by status, click to open a previous review, etc.

---

### v1.4.3 — Status Tags + Continue + Last-version pillbox ✅

#### Review Status Tags (mograph-native)
- [x] ComboBox in SaveVersionDialog with 4 fixed options: WIP / TR (Team Review) / CR (Client Review) / Final Delivery
- [x] Custom field for arbitrary tags (`PITCH`, `ALT01`, `REV2`, etc.) — sanitized to uppercase alphanumeric
- [x] Custom overrides combo when non-empty
- [x] Live filename preview updates as user changes status
- [x] Status appears as suffix in filename: `scene_v007_TR.c4d`, `scene_v012_CR.c4d`, `scene_v022_FINAL.c4d`
- [x] Stored in history JSON as `"status"` field per entry
- [x] Filename parser/scanner handles status suffix transparently — version bump is independent of status
- [x] "final" written in comment triggers soft advisory dialog (suggests using FINAL tag, but doesn't block)

**Why**: Research across mograph community (Vinzent Britz, Matthew Creed, GSG forums) showed that the de-facto convention isn't VFX-style `show_seq_shot` but `Client-Project-Description` with review-status suffixes (`-TR`, `-CR`). The status carries the meaning of *what this version is for*, which is more useful than rigid templates for motion design workflows.

#### "Continue from this version" (Gap 1: prevent accidental overwrite)
- [x] After Save Version with TR / CR / FINAL status, replaces success MessageDialog with a QuestionDialog
- [x] User can opt to immediately auto-create a new WIP version
- [x] Continuation comment auto-set: `"Continue from v007_TR"`
- [x] Skips QC re-run (same scene state)
- [x] Doc switches to the new WIP file, leaving the review file untouched even on next Cmd+S

**Why**: Without this, an artist saves `_v007_TR.c4d`, shares for review, keeps editing, hits Cmd+S → the file the team is reviewing is no longer what they're reviewing. Auto-continuation surfaces the right next step instead of relying on artist memory.

#### Last-version pillbox (Gap 2: discoverability)
- [x] Static text caption above Save Version button
- [x] Reads latest entry from sidecar history JSON
- [x] Format: `Last version: v007 TR · 2h ago` (or `v007 WIP` if no status)
- [x] Relative time: "just now", "Xm/h/d ago", or absolute date for >30 days
- [x] Empty states: "scene not saved yet" / "none yet — click Save Version to start"
- [x] Updates on Timer refresh + after Save Version + on document switch

**Why**: Artists in flow forget to checkpoint. A passive caption ("you saved 4h ago") nudges them without being intrusive.

---

### v1.4.2 — Smart Save Version + UI polish ✅

#### Smart Save Version
- [x] Pure helpers: `parse_version_filename`, `build_versioned_filename`, `compute_next_version`
- [x] Sidecar history JSON (`<base>_history.json`) — load/save/append entries (newest-first)
- [x] Modal `SaveVersionDialog`: required comment + "Run QC before save" checkbox
- [x] `smart_save_version(doc, comment, run_qc, artist)` orchestrator with full undo-safe flow
- [x] First-time save: opens SaveDialog with suggested `scene_v001.c4d`
- [x] Subsequent saves: scans folder + history, bumps version (3-digit, VFX-aligned)
- [x] Captures QC score, scene stats (polys/mats/lights), active take, timestamp, artist
- [x] Updates `doc.SetDocumentPath/Name` + `EventAdd` so title bar + future Cmd+S follow new file
- [x] Refuses to overwrite existing files (defensive)
- [x] "Save Version" button in Output section (paired with Collect Scene as primary actions)

**Why**: Native C4D Save Incremental only bumps numbers. Without comments, version history is useless ("scene_v014.c4d... what's in there?"). Sidecar JSON adds context: comment + QC score + scene stats per version, browseable later.

#### UI polish
- [x] Score header above QC rows: progress bar + "QC X/Y" + PASS/WARN/FAIL + scene stats
- [x] Click-anywhere-on-row triggers primary action (bigger click target)
- [x] "..." snapshot dir button → "Browse" (clearer)
- [x] Output section reorganized: primary checkpoint actions on top (Save Version + Collect Scene)

**Limitations discovered**:
- Native tooltips (`SetTooltip`) not available in C4D 2026 GeDialog Python — only `CUSTOMGUI_BITMAPBUTTON` has built-in tooltip support
- Hover effects on `GeUserArea` not feasible — `BFM_GETCURSORINFO` is not routed to embedded user areas in C4D 2026
- Click-row works via `InputEvent` override; hint added to section title to aid discovery

---

### v1.4.1 — QC Check #11 (FPS / Frame Range) ✅

#### FPS + Frame Range Validation
- [x] Document FPS check (must equal studio standard)
- [x] Render data FPS check (RDATA_FRAMERATE — independent from doc FPS)
- [x] Start frame must be 1001 (VFX/cinema standard) for all animation presets
- [x] Frame step = 1 (no frame skipping)
- [x] Frame mode validation (Manual for animation, Current Frame allowed for stills)
- [x] Timeline (DOCUMENT_MIN/MAXTIME) must match active render range
- [x] Preview/loop range (DOCUMENT_LOOPMIN/MAXTIME) must match active render range
- [x] Stills preset has relaxed rules (Current Frame OK, timeline only needs to include 1001)
- [x] Playhead auto-snap to range start if outside range after fix
- [x] Auto-fix iterates ALL render presets (not just active)
- [x] Confirmation dialog before fix with diff preview of all changes
- [x] Configurable studio FPS via `standard_fps` in `sentinel_settings.json` (default 25)
- [x] Full undo support (Ctrl+Z reverts entire fix in one step)
- [x] Included in QC report export

**Why**: Wrong FPS, frame range starting at 0, or timeline misaligned with render are silent errors that waste hours. 1001 is the VFX/cinema convention (4-digit padding, room for handles before frame 1001).

---

### v1.4.0 Features ✅

#### Take-based QC ✅
- [x] Validate camera assigned per take
- [x] Validate output path contains $take token per take
- [x] Handle inherited render data from Main Take
- [x] Info button with per-take detail
- [x] Included in QC report export

#### Scene Collector ✅
- [x] Pre-flight: runs all 10 QC checks, shows summary, offers auto-fix
- [x] Collect: calls c4d.documents.SaveProject() (native asset collection)
- [x] Manifest: generates sentinel_manifest.json with scene info, assets, missing list (was ys_guardian_manifest.json before v1.5.0)
- [x] Complements C4D native — does NOT duplicate it

#### Light Groups AOV ✅
- [x] Independent button (not tied to Essentials/Production)
- [x] Scans lights for group assignments (RS Light + RS Object Tag + RS Sky)
- [x] Diagnostic: shows groups found, ungrouped lights
- [x] Toggle: activate/deactivate "All Light Groups" on Beauty AOV only
- [x] Show AOVs displays Light Groups status + group names
- [x] Avoids explosion problem (only on Beauty, not per material AOV)

#### Apply Color Processing ✅ (Investigated, left at default)
- [x] Investigated: in ACEScg pipeline, ON/OFF produces identical results
- [x] Decision: leave at RS default (ON) — no-op in properly configured OCIO pipeline
- [x] Documented in RS_AOV_PARAM_IDS.md

#### Other v1.4.0 changes ✅
- [x] UI reorganized by workflow: QC → Scene Tools → Render → Output
- [x] Render section unified (Presets + AOVs)
- [x] Reset All from template + Force 9:16 toggle
- [x] Resolution display next to preset dropdown
- [x] Legacy snapshot files moved to plugin/legacy/

---

## Pending — Next Phases

### Tier A — Production Workflow polish (high impact, easy)

> Most of this tier already shipped across v1.4.1–v1.5.1 (FPS/Range validation, Smart Save, Status Tags, Browse Versions, Scene Notes). What remains:

#### Review Slate on Snapshots
Burn metadata into Save Still PNGs:
- Shot ID, Artist name, Frame number, Date, Resolution
- Small overlay bar at bottom (like editorial slates)
- Supervisor instantly knows the context of every image

**Why**: Unnamed PNGs on a server are useless without context. Every image should be self-documenting.

#### FPS Settings UI (polish for QC #11)
Add a dropdown or settings dialog to change the studio standard FPS without editing the JSON manually. Group FPS/Range issues by category in Info dialog (FPS / Range / Timeline) for clearer reading.

**Why**: Currently only configurable via `sentinel_settings.json`. Most artists won't open it.

### Tier B — Asset Health & Validation (high impact, medium effort)

> The multi-format + texture parts of this tier shipped across v1.5.4–v1.8.0 (Multi-Format Setup → Sentinel Frame, Cross-Aspect Safe-Area QC #12, Texture Repathing). **Post-Render Validation (I1) shipped in v1.9.0 (PR #4)** — see the shipped entry above. What remains:

#### ~~Post-Render Validation (I1)~~ ✅ SHIPPED v1.9.0 (PR #4)
Verify render output after completion — expected AOV files, zero-byte/truncated detection, sequence completeness, size-outlier SPC, stale-cluster detection, atomic report + `<base>_render_history.json` sidecar. Full details in the v1.9.0 shipped entry above.

#### Scene Complexity Budget
Visual budget meter for scene resources:
- Total polygon count vs configurable budget
- Texture memory estimate vs GPU VRAM
- Object count, light count
- Green/yellow/red status per metric
- Configurable thresholds per studio

**Why**: Artists don't realize a scene is too heavy until render fails with out-of-memory.

### Backlog — Consider Later

#### Sentinel Frame follow-ups *(deferred in the v1.8.0 plan)*
- Format catalog: cinema (2.39 / 1.85 / 2:1) + print (A4 / A3 / Letter) — needs QC-name-matching-compatible ids.
- User-defined custom formats (ratio/resolution) — cheap given the dynamic description.
- QC #13 "Take override drift" — verify overrides still apply after save (frail C4D Takes; today mitigated by idempotent re-run + staleness hash).
- Versioned/updatable platform safe-area presets (per-platform dates, refreshable from a shared ruleset).
- Slice-takes (tiles) from C4DMultiFrame; stage/ortho cameras; advanced multi-tag (several configs per camera).
- Confirm whether QC score **severity weighting** (FAIL vs WARN) is still display-only after Quality Gates.

#### MessageData Plugin
Background monitoring with panel closed. Invasive — reconsider when plugin is mature.

#### Template Configurable
Supervisor chooses .c4d template from shared server. Add "..." button next to Reset All.

#### Dropdown Dinámico de Presets
Show presets that exist in scene, not just hardcoded 4.

#### Keyboard Shortcuts
Atajos for Export QC, refresh, panel toggle.

#### Denoise Toggle per AOV
Auto-enable denoise on noisy passes (GI, SSS). Needs param ID probe.

#### Slack/Teams Webhook
Notify channel on Collect Scene or QC pass. Low effort, nice-to-have.

#### Comp Tag Manager
Bulk view/edit Object Buffer IDs, detect duplicates.

### Rediseño UI/UX — fases pendientes (spec 2026-07-18)

Fase 1 (fundación: DESIGN.md + webbridge + Reports/Delivery Summary) entregada en v1.13.0. Pendientes:

- [x] **Fase 2 — Reports completo** ✅ (v1.14.0): QC/Doctor/Supervisor/Render Validation en Reports; triage: 12 informativos convertidos, 71 decisiones, 12 diferidos a toasts (doc: specs/2026-07-19-popup-triage.md)
- [x] **Fase 3 — Consolidación IA nativa** ✅ (v1.15.0): snapshots efectivo+origen (bug Save Still cazado), Multi-Part ya conforme, pestaña Deliver, menú Help
- [x] **Fase 4 — Formularios a SPA** ✅ (v1.16.0): Save Version/Notes/Settings/Gate en HTML, toasts, Command Palette con confirm contractual; cancelación de peticiones en la cola
- [x] **Fase 5 — Asset Hub en SPA** ✅ (v1.17.0): página `hub` con inventario virtualizado (tanstack/react-virtual), repathing con pending model + undo único, gate/collect inline como job en vivo (JobRegistry + `/thumb` binario); entradas migradas con fallback nativo
- **Fase 6 (candidata, pendiente de brainstorm in-depth)**: panel completo como SPA embebida (viabilidad técnica probada en fases 1-2; requiere spike de refresco vivo PostWebMessage/polling)

### Deuda conocida (Asset Hub v1.11)

Items menores identificados en la review final de rama de Asset Hub (feat/asset-hub) que no bloquean el merge pero quedan anotados para no perderse:

- Test de 2 carpetas vacías simultáneas en `build_file_index`/`match_missing_in_folder`
- Colisión sintética cuando `tex_idx` es `None` en el merge de records
- Bloque append-owner duplicado en el merge de `AssetRecords`
- Tests de borde para `format_size` (0 bytes, negativos, tamaños muy grandes)
- `abspath` no aplicado consistentemente en `build_file_index` (rutas relativas del root de búsqueda)
- Clip-culling / rango de viewport en `AssetListArea` (hoy dibuja toda la lista, no solo lo visible)
- Evicción FIFO de placeholders `None` en el thumb cache no cuenta como entradas reales cuando supera 200 (>200 thumbs)
- Extraer un helper compartido para el loop de preflight issues (`dialogs.py` ↔ `flows.py` duplican la misma iteración de `CHECK_REGISTRY` + `preflight_template`) — **el más prioritario**
- Renombrar `_build_collect_preflight_payload`: el nombre no deja ver que puede abrir un modal (quality gate) como side effect
- "Used by" clicable para records genéricos (hoy solo funciona para los que tienen `owner_ref` resuelto)
- Marcar visualmente las filas `ambiguous` del Search-Folder-for-Missing en la tabla (hoy solo se resuelven desde el diálogo de selección)
- Unlink del zip parcial cuando `create_zip_archive` falla a mitad de camino (hoy puede dejar un `.zip` truncado en disco)

Añadidos en la review final de la pasada de pulido (feat/hub-polish, v1.11.1):

- La ventana de supresión del rescan (selección de fila) puede tragarse un cambio legítimo de escena hecho en <1s tras el click; se auto-corrige con el siguiente cambio o con Rescan manual
- Heurística de letra de unidad en `canonical_asset_key` (`.search` de `[a-z]:/`): un path POSIX con un segmento tipo `a:/` se truncaría; solo afecta a la clave de dedupe, nunca a los writers
- Al arrastrar una columna muy ancha, el fit-to-viewport encoge visualmente las demás hacia el mínimo (display-only, se recupera al soltar; documentado en el docstring)

---

## Research Notes

### RS AOV System
- All parameter IDs documented in `RS_AOV_PARAM_IDS.md`
- Named constants exist in c4d module but are NOT in Maxon's SDK docs
- Discovery method: `dir(c4d)` filter + manual probe comparison
- Multi-Part EXR overrides per-AOV bit depth/compression with global settings
- Caustics detection: RS VideoPost param 9013
- Volume detection: scene scan for RS Environment (1036757) / RS Volume (1038655)
- C4D 2026 API changes: GetViewRoot (not GetRoot), GetPortValue (not GetDefaultValue)

### Snapshot System
- BaseBitmap.GetPixelDirect clamps HDR to 0-1 — cannot do ACES tonemap in C4D Python
- External Python + OpenEXR is the only way to read raw float data
- ACES pipeline: ACEScg→sRGB matrix → 0.6 exposure → tone map curve → sRGB OETF
- macOS Python: /usr/bin/python3 with pip3 install OpenEXR numpy Pillow

### Compositing Compatibility
- Frischluft Lenscare: works with both raw Z and normalized — but Z Normalized Inverted is plug-and-play
- RSMB Pro: expects normalized 0-1 (0.5=no motion), NOT raw displacement
- Nuke ZDefocus: expects raw Z in world units
- Nuke VectorBlur: expects raw pixel displacement
- Depth Filter Type: always Center Sample (no interpolation at edges)
- Motion Vector Filtering: always OFF (prevents smearing)

### Sources
- [Maxon RS AOV Documentation](https://help.maxon.net/r3d/cinema/en-us/#html/Intro+to+AOVs.html)
- [Compositing Mentor CG Series](https://compositingmentor.com/category/cg-compositing-series/)
- [RE:Vision RSMB Motion Vector Format](https://revisionfx.com/faq/motion_vector/)
- [Frischluft Lenscare](https://www.frischluft.com/lenscare/)
- RS resource files: `vprsrenderer.h`, `drsaov.h` in C4D 2026 plugins folder
