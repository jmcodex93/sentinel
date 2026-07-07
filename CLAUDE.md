# Sentinel Plugin - Development Rules

## Project Overview
Sentinel (v1.9.0) is a Cinema 4D quality control and workflow automation plugin designed for professional 3D production workflows. **Originally built as YS Guardian at Yambo Studio**, now maintained and extended by Javier Melgar as Sentinel — keeping the watchdog spirit while expanding into versioning, status tracking, and modern mograph workflow tools. It acts as a real-time watchdog that continuously monitors scenes for production issues, plus provides render management and scene tools.

The plugin performs **12 quality checks** in real-time:
1. **Lights Organization** - Ensures all lights are properly organized in a "lights" group (Select + Fix)
2. **Visibility Consistency** - Detects objects with mismatched viewport/render visibility (Select)
3. **Keyframe Sanity** - Warns about multi-axis keyframes that can cause animation issues (Select)
4. **Camera Shift Detection** - Alerts when cameras have non-zero shift values (Select + Fix)
5. **Render Preset Compliance** - Ensures only approved render presets exist (Info)
6. **Assets (Textures)** - Missing textures, absolute paths, RS Node material paths (Info)
7. **Unused Materials** - Detects materials not applied to any object (Select + Fix)
8. **Default Names** - Objects still using C4D default names like "Cube", "Null" (Select)
9. **Output Paths** - Missing tokens, empty paths in render settings (Info)
10. **Take Validation** - Camera assigned per take, output paths with $take token (Info)
11. **FPS / Frame Range** - Validates FPS, start frame = 1001 (VFX standard), frame step, timeline + preview alignment, all presets (Info + Fix)
12. **Cross-Aspect Safe Area** - Verifies opt-in marked subjects (UserData) stay inside per-format safe-area regions when delivering across multiple aspect ratios via Multi-Format Setup. Auto-refresh uses current frame; Info button runs full keyframe sweep (Select + Info)

Additional features: RS AOV management (Essentials/Production/Light Groups), Scene Collector, QC Report export, Render Presets with aspect ratio toggle, Texture Repathing tool (multi-renderer bulk find/replace + smart-fix), and a full suite of scene tools.

## Core Files (DO NOT DELETE)
- `plugin/sentinel_panel.pyp` - Cinema 4D bootstrap only: inserts the plugin root on `sys.path`, imports the `sentinel/` package, keeps all `Register*` calls, and preserves the `__main__` guard.
- `plugin/sentinel/` - Sentinel Python package. Current layout:
  - `common/` - settings, cache, constants, shared helpers
  - `checks/` and `qc/` - QC check implementations, registry, result adapters, scoring
  - `aovs.py`, `baseline.py`, `multiformat.py`, `notes.py`, `rules.py`, `safe_areas.py`, `textures.py`, `versioning.py` - extracted workflow engines
  - `ui/ids.py`, `ui/user_areas.py`, `ui/dialogs.py`, `ui/overlay.py`, `ui/panel.py` - widget IDs, custom UserAreas, dialogs, ObjectData overlay, main GeDialog panel and CommandData
- `plugin/res/` - Resource descriptions required by C4D for plugins that need a `description` parameter (e.g. SafeAreaOverlayObject in v1.5.6). Contains `c4d_symbols.h`, `description/safearea_overlay.res|.h`, `strings_us/description/safearea_overlay.str`. Adding new ObjectData/TagData plugins needs new `.res|.h|.str` triplets here.
- `plugin/exr_converter_external.py` - Cross-platform EXR→PNG with ACES pipeline
- `plugin/abc_retime/` - Bundled ABC Retime plugin (by axisfx2)
- `plugin/legacy/` - Archived snapshot files (kept for reference)

## Development Flow
- After changing package structure or classes registered with Cinema 4D, restart Cinema 4D. Do not rely on "Reload Python Plugins" for package reloads: live ObjectData/GeDialog instances can keep references to old module objects and create split-brain state.
- Install/copy the full plugin folder contents together: `sentinel_panel.pyp`, `sentinel/`, `res/`, `abc_retime/`, and support scripts. The `.pyp` alone is not a complete plugin anymore.

## Development Rules

### 1. FOCUS
- **ONE PROBLEM AT A TIME**: Don't try to solve everything at once
- **CORE FUNCTIONALITY FIRST**: Get the basic feature working before adding complexity
- **NO FEATURE CREEP**: Don't add features that weren't requested

### 2. FILE MANAGEMENT
- **EDIT, DON'T CREATE**: Modify existing files instead of creating new versions
- **NO HELPER SCRIPTS**: Don't create installation scripts, test scripts, or diagnostic tools unless specifically requested
- **KEEP IT SIMPLE**: The fewer files, the better

### 3. PROBLEM SOLVING
- **IDENTIFY ROOT CAUSE**: Understand WHY something isn't working before trying to fix it
- **TEST INCREMENTALLY**: Make small changes and test each one
- **DOCUMENT FINDINGS**: Keep notes about what works and what doesn't in this file

### 4. CODE PRINCIPLES
- **MINIMAL DEPENDENCIES**: Use only Cinema 4D's built-in Python libraries when possible
- **FALLBACK GRACEFULLY**: If a feature can't work, fail silently with a simple message
- **NO OVER-ENGINEERING**: Simple solutions are better than complex ones

### 5. GOAL-DRIVEN EXECUTION
Before coding, restate the task as a verifiable success criterion so the loop can close on its own instead of waiting for the user to eyeball it.
- **"Add QC check X"** → "Open a scene that violates X, run QC, confirm the new check reports it; open a clean scene, confirm it doesn't."
- **"Fix bug Y"** → "Reproduce Y in C4D first, then verify the fix makes the repro pass."
- **"Refactor Z"** → "All 12 QC checks still produce the same results before and after."
- **"Add UI button"** → "Plugin reloads without errors, button appears in expected section, click triggers the action, status text updates."

For multi-step work, write the plan as `step → verify` pairs. Weak criteria ("make it work") force ping-pong; strong criteria let the work finish in one pass.

## Data Persistence

### Saved Per Computer/User (Persistent via `sentinel_settings.json`; legacy `ys_guardian_settings.json` is auto-migrated on first run)
- **Artist Name**: Stored in Cinema 4D preferences folder
- **Compositor Target**: Nuke vs After Effects selection
- **Multi-Part EXR**: On/off preference
- **Snapshot Directory**: RS snapshot source path
- **Standard FPS**: Studio FPS standard for QC check #11 (default 25, key `standard_fps`). A project `sentinel_rules.json` `fps` overrides this and disables the machine control with a "defined by project ruleset" caption (v1.6.0)
- **Texture Repathing presets**: Last 5 Find/Replace pairs (key in `sentinel_settings.json`)
- **Panel Layout**: Window position and docking state (managed by Cinema 4D)

### Per Project (Shared, via `sentinel_rules.json`) — v1.6.0
- **Ruleset**: FPS, start frame, approved presets, default names, safe-area insets, per-check severity (FAIL/WARN), and per-check on/off. Discovered from the scene folder + up to 3 ancestors (nearest wins, no cross-file merge; shadowed files surfaced in the header + QC Report). Precedence: **project rules > machine settings > embedded defaults**. Per-key validation (one bad key is rejected by name, the rest applies). Resolution cached by (path, mtime), invalidated with the QC cache — edits/deletes take effect without restart. Absent file → current defaults. Publishable to a shared folder so a whole team validates against the same rules.

### Per Scene Base (Sidecar JSON next to the `.c4d`, shared across all `_v###` versions)
- **`<base>_history.json`**: Smart Save Version log (comment, QC score, scene stats). As of v1.6.0 each entry is schema v2 `{passed, total, new, accepted}`; older entries render as "X/12 (legacy)"
- **`<base>_notes.json`**: Free-form scene notes + TODO checklist (v1.5.1)
- **`<base>_baseline.json`** (v1.6.0): Accepted QC violations with author + reason, schema v1. Identity = `check_id` + hierarchical path + sibling index + object GUID (parametric checks snapshot the rule value). Merge-on-write (atomic tmp+rename), Synology conflicted-copy detection + merge on load, read-only lockout on an unreadable sidecar. Scene Collector copies + renames it (plus the effective `sentinel_rules.json`) into the delivery
- **Note**: sidecars are copied to the delivery folder by Scene Collector and renamed to the clean delivery base

### Fetched From Scene (Per Document)
- **Shot ID**: Read from Main Take name, synchronized with scene
- **Render Preset**: Read from active render data, matches scene settings

### Runtime Only (Per Session)
- **QC check results**: Cached with 0.5s cooldown, dirty-flag invalidation via CoreMessage
- **Scene stats**: Object count, polygon count, materials, lights

## Current Status (v1.9.0)

### What Works ✅
- **All 12 Quality Checks**: Lights, visibility, keyframes, camera shift, presets, assets/textures, unused materials, default names, output paths, take validation, FPS/frame range, cross-aspect safe area
- **Auto-fix**: Lights→group, camera shift→reset, unused mats→delete, FPS/range→studio standard (all presets at once with confirmation)
- **Modular `sentinel/` package** (v1.6.0): `.pyp` is a 115-line bootstrap; engine (`checks/`, `qc/`, `rules.py`, `baseline.py`, workflow engines) and UI (`ui/`) are importable modules. Reload policy = restart C4D (no `sys.modules` purge — see Development Flow). Verification ladder: pytest 70/70 + frozen fixture oracle in C4D 2026.3
- **QC Check Registry** (v1.6.0): the 12 checks are declarative entries in `qc/registry.py` (id, label, severity FAIL/WARN, fix capability, params); panel, QC Report, Save Version summary and Collector preflight all iterate the registry — a 13th check costs one entry, not N edits. Severity is display-only in v1 (equal score weight)
- **Per-Project Rules** (v1.6.0): `sentinel_rules.json` sets FPS, start frame, approved presets, default names, safe-area insets, per-check severity and on/off. Discovered from the scene folder + up to 3 ancestors (nearest wins; shadowed files surfaced), precedence project > machine > defaults, per-key validation, live re-resolution on edit/delete. Header shows the active ruleset; a disabled check dims and drops out of the score denominator (`X/11 · 1 disabled`)
- **Baseline / Accepted Violations** (v1.6.0): accept known violations from the panel with mandatory author + reason (`<base>_baseline.json`, schema v1); the score then counts only **new** violations, a mixed row reads `N new (M accepted)`. Identity = path + sibling index + object GUID (delete/rename re-arms, never mis-inherits); merge-on-write with Synology conflicted-copy merge; accept/retire invalidates the QC cache; Collector transports the sidecar + effective ruleset into the delivery
- **Smart Save Version**: Versioned saves (`scene_v###.c4d`) with required comment, QC score, scene stats, sidecar `<scene>_history.json` log
- **Review Status Tags**: WIP / TR (Team Review) / CR (Client Review) / FINAL / Custom → suffix in filename (`scene_v007_TR.c4d`)
- **"Continue from this version"**: After saving a TR/CR/FINAL, offers to auto-create a new WIP version so the review snapshot stays untouched
- **"Last version" pillbox**: Live caption above Save Version showing `v007 TR · 2h ago`
- **Browse Recent Versions**: Inline list of last 5 versions in the panel with status badges (color-coded), filter dropdown (All/WIP/TR/CR/FINAL), click row to open
- **Scene Notes & TODOs**: Per-scene sidecar JSON (`<base>_notes.json`) with free-form notes + checklist of TODOs. Modal editor with checkbox toggle + delete. Live caption in panel ("⚠ Notes: text + 3 TODOs (2 pending)"). Notes shared across all versions of the same scene base. Included in QC report export and Scene Collector manifest. Sidecar copied to delivery folder.
- **Scene Collector — clean delivery naming**: Renames the collected `.c4d` to the original scene base (stripping `_v###[_status]`) so deliveries have clean identity (e.g., `robot_010_v022_FINAL.c4d` → `robot_010.c4d`). Manifest preserves traceability via `original_filename`, `original_version`, `original_status`
- **Tabbed UI** (v1.5.2): Scene Header (filename + Shot/Artist + QC bar) always visible above 4 tabs (QC / Render / Versions / Tools); footer (GitHub / Report Bug) always visible below. Tab content is dynamically rebuilt via `LayoutFlushGroup` — only the active tab lives in the layout (HideElement does not collapse layout space in C4D 2026)
- **QC Report Export**: JSON with score, scene stats, all check details
- **RS AOV Management**: Essentials (11) / Production (17+) tiers, per-compositor config (Nuke vs AE)
- **Light Groups AOV**: Diagnose + toggle on Beauty AOV
- **Scene Collector**: Pre-flight QC + SaveProject() + manifest JSON
- **Take Validation**: Camera per take, $take token in output paths
- **Render Presets**: Dropdown with resolution display, Reset All from template, Force 9:16 toggle
- **Multi-Format Render Setup** (v1.5.4, refactored v1.5.5): One-click child-Take generator for the 5 standard delivery aspects (16:9, 9:16, 1:1, 4:5, 21:9). Each Take gets a cloned Render Data with format-specific resolution + output path. **Composition Mode** dropdown chooses between (a) "None" — camera unchanged, only resolution/output overrides (default, matches GSG Social Frame plugin); or (b) "Resize Canvas" — sensor-size override per format using AR_ResizeCanvas math (`new_aperture = src × target_w / src_w`), safer than focal-length override (doesn't break zoom animations or DOF). Idempotent; explicit `take.SetCamera` + `SetParameter` after `FindOrAddOverrideParam` (defends against find-OR-add silent skip); cleans up stale FOV/focal/aperture overrides on re-run. Full undo wrapping; summary dialog with composition mode
- **Cross-Aspect Safe Area** (v1.5.5): QC #12 verifies opt-in marked subjects stay inside per-format safe-area regions across all active Multi-Format delivery Takes. **Crop interpretation** model: bbox projects once into the master Take's NDC, then each format's safe area is computed as a centered crop region with per-side insets (e.g. 9:16 inset 8/15/5/10 for IG Reels caption + icon stack). Auto-refresh uses current frame (cheap); Info button runs full keyframe sweep (PSR keyframes + midpoints, original timeline position restored via try/finally). Tools tab → "Mark / Unmark Safe Area Subject" smart-toggle button drives the UserData marker. Sample frame violations reported per (object × format × frames + edges)
- **Safe-Area Viewport Overlay** (v1.5.6): Live colored rectangles rendered in the active camera viewport showing each multi-format Take's crop region (16x9 white, 9x16 orange, 1x1 cyan, 4x5 magenta, 21x9 yellow). Toggle in Render tab auto-creates a managed `SafeAreaOverlayObject` (ObjectData) marker at scene root; persists with `.c4d` save. Same crop-interpretation math as QC #12. Implementation pivoted from `SceneHookData` (removed in C4D 2026) → `TagData.Draw` (registers but never invoked by viewport pipeline) → `ObjectData.Draw` in `DRAWPASS_OBJECT` (confirmed working, fires regardless of selection)
- **Texture Repathing** (v1.5.7): Multi-renderer bulk find/replace + smart-fix tool for texture paths. Tools tab → "Asset Management" → "Texture Repathing..." (also reachable from QC #6 Assets Info). Async dialog (keeps C4D interactive so Cmd+Z works). Comprehensive `scan_all_texture_paths` covers RS/Arnold maxon node graphs, classic Xbitmap shader chains, Octane legacy image shaders, material/object BaseContainer params, RS Dome Light HDR (compound DescID), Alembic caches, and tag shader chains (Octane Environment Tag). Per-path status: OK / absolute / missing / asset_uri / empty (`relative://` resolved by searching common subdirs like Redshift does). Scrollable `TextureListArea` UserArea (ScrollGroup-backed) with status filter. Bulk Find/Replace (case-insensitive default + Match case toggle), last-5 presets persisted in `sentinel_settings.json`. Smart Actions: Auto-Find Missing, Make All Relative, Clear pending. Per-row `[...]` file picker. Apply All wraps the batch in one undo step (`StartUndo`/`EndUndo` + node-graph `doc.AddUndo(UNDOTYPE_CHANGE, mat)` anchor so the maxon `UndoMode.ADD` transaction joins the document undo). Auto-refreshes on scene change via `CoreMessage`/`Timer`
- **Snapshot System**: Cross-platform EXR→PNG with full ACES pipeline (ACEScg→sRGB)
- **Scene Tools**: Hierarchy, H→Layers, Solo Layers, Drop to Floor, Vibrate Null, ABC Retime, Camera Rigs
- **CoreMessage dirty-flag**: Instant scene change detection, no polling waste
- **Cross-platform**: macOS + Windows (platform-aware file opener, Python discovery)

### Known Limitations ❌
- **Forcing Redshift Snapshot Directory**: Can't override Redshift's save location at runtime
- **Programmatic Snapshot Triggering**: No API access to trigger snapshots from code
- **Redshift must be configured manually**: RenderView → Preferences → Snapshots → EXR format
- **C4D docked panel does not auto-shrink**: When tab content gets smaller (e.g., switching from QC → Versions), the panel window stays at its taller size. This is a confirmed C4D 2026 framework limitation (no `SetSize`/`ResizeWindow`/`FitToContent` API for docked panels — Maxon staff confirmed). Even Maxon's own panels (Take Manager, AOV Manager) have this behavior. The user must drag-resize manually if they want compact mode. Our `BFV_SCALEFIT` spacers absorb the gap correctly within the layout, but the window frame itself stays put.
- **No native tooltips on widgets**: `BFM_GETCURSORINFO` is not routed to embedded `GeUserArea` in C4D 2026 Python. Section titles include hints (e.g., "click any row...") instead of hover tooltips.
- **C4D 2026 deprecated plugin types**: `c4d.plugins.SceneHookData` and `RegisterSceneHookPlugin` were removed/migrated in C4D 2026 (verified empirically — local 2026 SDK clone has zero references). Sentinel uses `ObjectData.Draw` in `DRAWPASS_OBJECT` for the v1.5.6 Safe-Area Overlay (a scene-root marker, no camera needed) and `TagData.Draw` for the v1.8.0 Sentinel Frame per-camera tag — both confirmed working.
- **CORRECTION (v1.8.0): `TagData.Draw` DOES fire in C4D 2026.** The v1.5.6 note that "`TagData.Draw` is never invoked" was WRONG — the root cause was a missing registration flag, not a removed API. `TagData.Draw` fires reliably when the tag is registered with `info = c4d.TAG_VISIBLE | c4d.TAG_EXPRESSION | c4d.TAG_IMPLEMENTS_DRAW_FUNCTION` (the flag `TAG_IMPLEMENTS_DRAW_FUNCTION` = 256 is REQUIRED; verified live in C4D 2026.301, and confirmed against the working C4DMultiFrame prototype + Maxon staff on developers.maxon.net/forum/topic/12708). Draw signature `Draw(self, tag, op, bd, bh) -> bool`; gate with `if bd.GetDrawPass() != c4d.DRAWPASS_OBJECT: return True` (else it draws 3–4× per frame), filter viewport with `bd.GetSceneCamera(doc) == op`, and treat the draw thread as READ-ONLY (the tag/node come from a CLONED document — Python attributes set via `setattr` do NOT survive the clone; per-node state Draw reads must live in the BaseContainer/params). So an always-on drawer on a camera can be a plain TagData; the ObjectData-marker workaround is only needed for scene-root drawing with no host object.

## Active Tasks
See `ROADMAP.md` for the full feature roadmap and pending phases (v1.5.0, v1.6.0, backlog).

## Do NOT:
- Create multiple versions of the same file
- Add complex dependency management
- Create installation/setup scripts (unless updating the existing one)
- Promise automatic features that require Redshift API access we don't have
- Over-complicate the solution

## Keep It Simple
The plugin should do what it can do well, and clearly communicate its limitations.

## External References (C4D / Redshift SDK)

When writing new C4D or Redshift code, consult these references **before inventing patterns from scratch**. All are located outside the plugin repo, in the sibling folder `../11 C4D DEV/`.

### 1. Maxon Official Python API Examples (local clone)
- **Path**: `../11 C4D DEV/Cinema-4D-Python-API-Examples/`
- **Upstream**: https://github.com/Maxon-Computer/Cinema-4D-Python-API-Examples (Apache-2.0, maintained by Ferdinand Hoppe @ Maxon)
- **Covers**: Official plugin hooks, GUI patterns, token system, mograph, volumes, node graphs, 2024/2026 examples (persistent dialogs, bidirectional scene updates, OCIO, licensing, render tokens)
- **Use for**: Any generic C4D Python API pattern — GUI (GeDialog), tokens, CoreMessage, threading, node graph (maxon.GraphNode), file I/O

### 2. renderEngine — Community Render Engine Wrapper (local clone)
- **Path**: `../11 C4D DEV/renderEngine/`
- **Upstream**: https://github.com/DunHouGo/renderEngine
- **⚠️ No license** — read and learn from it, but do NOT copy code verbatim into Sentinel without asking permission
- **Covers**: Redshift (AOVs, materials, scene lights), plus Arnold/Octane/Vray/Corona/CentiLeo
- **Use for**: Redshift API patterns (the official Redshift Python API has no public docs). Key files:
  - `Redshift/aov.py` — AOV helper (cross-check our hard-coded IDs)
  - `Redshift/material.py` — RS material node graph wrapper
  - `Redshift/scene.py` — RS lights, tags, proxies, HDR dome
  - `constants/` — REDSHIFT_AOVS and description IDs
  - `utils/node_helper.py` — `NodeGraghHelper` for maxon.GraphNode

### 3. Official Maxon Python Docs (online)
- **URL**: https://developers.maxon.net/docs/py
- **Use for**: Written manuals and full API index. Pair with the local examples clone for complete coverage.

### 4. C4D Window / Manager IDs (undocumented)
Not in `symbol.h`. Obtained empirically via `FindShortcutAssign`. Verify in live C4D before relying on them.
```python
MATERIAL_MANAGER        = 150041
OBJECT_MANAGER          = 100004709
LAYER_MANAGER           = 100004704
PICTURE_VIEWER          = 430000700
ATTRIBUTE_MANAGER       = 1000468
NODEEDITOR_MANAGER      = 465002211
TAKE_MANAGER            = 431000053
TIMELINE_MANAGER        = 465001516
XPRESSO_MANAGER         = 1001148
RENDER_QUEUE            = 465003500
RENDER_SETTING          = 12161
ASSET_BROWSER           = 1054225
PROJECT_ASSET_INSPECTOR = 1029486
CONSOLE                 = 10214
VIEWPORT                = 59000
ARNOLD_IPR              = 1032195
ARNOLD_SHADER_NETWORK   = 1033989
CORONA_NODE_MANAGER     = 1040908
```
Source: https://github.com/DunHouGo/cinema4d_Shortcut (not cloned, too small).

### Updating the local clones
Manual pull when needed (Maxon updates ~monthly, renderEngine sporadically):
```bash
cd "../11 C4D DEV/Cinema-4D-Python-API-Examples" && git pull
cd "../11 C4D DEV/renderEngine" && git pull
```

## Version History Summary
- **v1.0.0** (Oct 2025): Initial release — 5 QC checks, presets, scene tools, snapshot system
- **v1.0.1** (Oct 2025): ABC Retime integration, ACES tone mapping fix
- **v1.0.2** (Nov 2025): Fixed absolute path detection for node materials
- **v1.0.3** (Feb 2026): Create Hierarchy button, removed path popup warning
- **v1.0.4→v1.3.x**: Foundation fixes, UI upgrade, 5 new QC checks, auto-fix, QC report, RS AOV system
- **v1.4.0** (Apr 2026): Take QC, Scene Collector, Light Groups AOV, UI reorganized by workflow
- **v1.4.1** (Apr 2026): QC #11 — FPS/Frame Range validation (start=1001 VFX standard, frame step, timeline+preview alignment, all presets, configurable FPS, playhead snap)
- **v1.4.2** (May 2026): UI polish — score header, click-row in QC; Smart Save Version (versioned `_v###` files with comment + QC score + scene stats + sidecar history JSON)
- **v1.4.3** (May 2026): Smart Save UX — review status tags (WIP/TR/CR/FINAL/custom) baked into filename; "Continue from this version" auto-WIP after review saves; "Last version" live caption above Save Version
- **v1.4.4** (May 2026): Browse Recent Versions inline (custom GeUserArea with status badges + filter dropdown + click-to-open); fixed user-area click coord conversion in C4D 2026 (Local2Global() + msg subtraction) — affects both StatusArea and HistoryArea
- **v1.5.0** (May 2026): **Rebrand YS Guardian → Sentinel** — plugin file renamed (`sentinel_panel.pyp`), settings file renamed (`sentinel_settings.json` with auto-migration from legacy), C4D plugin folder `Sentinel/`, GitHub URLs updated, attribution to Yambo Studio explicit in README/CLAUDE.md/License
- **v1.5.1** (May 2026): Scene Notes & TODOs (sidecar JSON, modal editor, panel caption); Collect Scene clean delivery naming (strips `_v###[_status]` from filename, preserves traceability in manifest); notes integrated in QC report export and Scene Collector manifest + sidecar copied to delivery
- **v1.5.2** (May 2026): UI/UX redesign — Scene Header always visible (filename caption + Shot/Artist + QC progress bar) + 4 tabs (QC / Render / Versions / Tools) using QuickTab CustomGUI + dynamic rebuild via `LayoutFlushGroup` (HideElement does not collapse layout space in C4D 2026, hence rebuild on tab switch). Footer (GitHub / Report Bug) always visible. Documented C4D auto-shrink limitation in known limitations.
- **v1.5.4** (May 2026): **Multi-Format Render Setup** — Render tab → "Generate Format Takes..." opens a modal that creates child Takes for the 5 standard delivery aspects (16:9 / 9:16 / 1:1 / 4:5 / 21:9). Each Take gets a cloned Render Data with format-specific resolution + output path (subfolder or suffix mode). Optional auto-FOV keeps vertical FOV constant across formats via `take.FindOrAddOverrideParam(td, cam, fov_id, target_fov)` (idempotent, updates on re-run). Full undo wrapping. Summary dialog with created/updated/skipped/errors counts. Backed by orchestrator `generate_multiformat_takes(doc, options)` and `MultiFormatDialog` (modal). Math: `target_h_fov = 2*atan((target_aspect/source_aspect)*tan(source_h_fov/2))`.
- **v1.6.0** (Jul 2026): **Motor QC 2.0 — declarative registry + per-project rules + baseline, via incremental modularization**. The monolithic `.pyp` (11,067 lines) becomes a 115-line bootstrap; the engine and UI move into the `sentinel/` package (see Core Files). Three new user-facing capabilities, each shipped as a phase verified against a frozen v1.5.7 oracle: **(1) Declarative check registry** — the 12 checks are entries in `qc/registry.py` (`CHECK_REGISTRY`: id, label, severity FAIL/WARN, fix capability, params); panel, QC Report, Save Version summary and Collector preflight all iterate the registry, so check #13 costs one entry, not N edits. Severity is display-only in v1 (FAIL/WARN formalized but weighted equally in the score — weighting is deferred to the gates work). **(2) Per-project rules** (`sentinel_rules.json`, `rules.py`) — FPS, start frame, approved presets, default names, safe-area insets, per-check severity and on/off, discovered from the scene folder + up to 3 ancestors (nearest wins, no cross-file merge; shadowed files shown in the header and QC Report). Precedence: project rules > machine settings > embedded defaults; per-key validation (a bad `fps: "twenty"` is rejected with a named warning, the rest of the file still applies); the header shows the active ruleset name; resolution is cached by (path, mtime) and invalidated alongside the QC cache so editing/deleting the file takes effect without restart. A disabled check dims its row and drops out of the denominator (`X/11 · 1 disabled`), and the artifacts list disabled checks. **(3) Baseline of accepted violations** (`baseline.py`, `<base>_baseline.json`, schema v1) — accept known violations with mandatory author + reason; the score then counts only **new** violations (a mixed row reads `N new (M accepted)`). Identity = `check_id` + hierarchical path + sibling index + object `GetGUID()` (deleting an accepted `Cube[0]` never lets sibling `Cube[1]` inherit the acceptance; renaming re-arms — assumed RuboCop-style weakness); parametric checks snapshot the rule value and re-arm if the ruleset changes; QC #12 uses `check_id + object + format`, never frames. Merge-on-write (re-read, union by identity, atomic tmp+rename), Synology conflicted-copy detection + merge on load, read-only lockout on an unreadable sidecar (never overwritten with empty). Accept/retire invalidates the QC cache explicitly (an acceptance doesn't dirty the scene). History entries become schema v2 `{passed, total, new, accepted}`; pre-v1.6.0 entries render as `8/12 (legacy)` so the series doesn't read as improvement when only the metric changed. Scene Collector copies and renames the baseline sidecar and the effective `sentinel_rules.json` into the delivery, and the manifest lists acceptances + ruleset origin. **Verification ladder** (audit-mandated, precedes the first extraction): pytest 70/70 on pure helpers + rules/baseline/registry engines, plus a frozen dual oracle (v1.5.7 text byte-identical across the whole arc + a structured oracle) run in **C4D 2026.3** after each unit; deterministic fixtures (`tests/fixtures/violating.c4d` trips all 12 checks, `clean.c4d` passes 12/12) via `tests/c4d_runner/run_fixtures.py`. Reload policy: **restart C4D** — no `sys.modules` purge (purging split-brains live ObjectData/overlay instances). The installer now copies the whole `sentinel_panel.pyp` + `sentinel/` + `res/` folder, not a single file.
- **v1.7.0** (Jul 2026): **Quality Gates (I3)** — QC severity (FAIL/WARN, per-check in `sentinel_rules.json`) becomes actionable at Smart Save Version and Scene Collector. A `GateTriageDialog` lists failing checks with severity and offers: auto-fix the batchable ones (lights→group, camera shift→reset, unused mats→delete, FPS/range→standard) in a **single undo step**, accept into the baseline, or proceed anyway. Fallback dialog rows are tagged with their `check_id`. Gated behind a `gates_enabled` flag (off by default). Core in `gate.py`, wired into Save + Collect. Merged via PR #2.
- **v1.8.0** (Jul 2026): **Sentinel Frame — per-camera multi-format tag with WYSIWYG crop**. One `SentinelFrameTag` (TagData, id 2099073) is the single entry point for the multi-format workflow, subsuming the modal dialog + overlay toggle + mark button. Live viewport guides/mask(opacity)/platform-zones/HUD via `Draw` — **corrects the false v1.5.6 limitation**: `TagData.Draw` DOES fire with `TAG_VISIBLE|TAG_EXPRESSION|TAG_IMPLEMENTS_DRAW_FUNCTION` (flag 256), so no ObjectData companion drawer is needed. Buttons (Create/Update, Set Output, Remove Stale, Mark Subject) call the additive engine: camera-scoped Take naming, host-camera binding, **rename-safe** re-run via BaseLink resolver, single-undo, idempotent Set Output, staleness hash + "Takes out of date" HUD. **Crop-first (`framing.format_crop_values`)**: true inscribed crop via **focal** (universal — works on standard AND Redshift; aperture doesn't, RS ignores it — see [[reference_redshift_camera_params]]), gate-relative film-offset nudge; wider/equal formats crop by resolution alone; guides suppressed while viewing a format Take. QC #12 made nudge-aware (reads the tag's per-format nudge; identical without a tag). Panel: "Add Sentinel Frame to camera"; legacy Multi-Format dialog + Safe-Area Overlay retired from the panel (overlay `ObjectData` fully unregistered, `overlay.py` deleted; `MultiFormatDialog` kept in code so old Takes still work). Verification: pytest 129/129 + live MCP in C4D 2026.301 (standard + Redshift, all formats, render-verified). Merged via PR #3.
- **v1.9.0** (Jul 2026): **Post-Render Validation (I1) — the render safety net**. A "Validate Render Output..." button (Render tab → Post-Render) audits rendered frames **on disk** against what the scene says should exist — closing the gap where Sentinel protected everything up to the render button and nothing after. Pure engine in `plugin/sentinel/postrender.py` (stdlib-only, no `import c4d`; C4D reads are function-local in a thin adapter): sequence gaps, 0-byte/truncated frames, size-outlier SPC (MAD, WARN), previous-session "stale" cluster detection, AOV presence (WARN), per-Take/format coverage. Scene-aware **expected manifest** reads render data + takes (render-selection gate via `IsChecked`/current take — Main correctly excluded when not the render target), range-by-mode (Manual/Current/All), resolution/format→ext, and RS AOVs via extended `aovs.get_rs_aovs` (`effective_path`/`file_format`/`direct_enabled`) + `get_aov_multipart`. Atomic JSON report + a **separate** `<base>_render_history.json` sidecar (never the Versions-tab history — KTD7). Built via the Codex-implements / we-review loop (grounding→brief→adversarial critique→Codex→pytest+mutation+adversarial review→live-MCP). **Confirmed U1 contract** (C4D 2026.301): `c4d.modules.tokensystem.StringConvertTokens`; RS per-AOV `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` (see [[reference_c4d_render_output_naming]]). The first real production run caught two false-positives pytest+review missed and now fixed: beauty↔AOV **prefix collision** (77 false size-outliers — same folder, shared base → anchored `<prefix><sep?><digits>` parser + frame-token detection) and `detect_stale_cluster` **sub-second jitter** (false stale → `MIN_STALE_GAP_SECONDS=300` absolute floor). Verification: pytest 171/171 + mutation + two adversarial passes + live-MCP on the real RS scene (beauty clean, 0 outliers, real gaps flagged).
- **v1.5.7** (May 2026): **Texture Repathing tool**. New multi-renderer bulk find/replace + smart-fix utility for texture paths — built for both project supervision (whole-scene asset validation) and artists (one-button fixes, undo-safe). Tools tab → "Asset Management" → "Texture Repathing...", plus a contextual launch from QC #6 Assets Info. Backbone: `scan_all_texture_paths(doc)` returns structured TextureRecords across every storage mechanism found by empirical probing — RS/Arnold maxon node graphs (`GetChildren()` walk, `GetPortValue()` leaves), classic Xbitmap shader chains, Octane legacy image shaders (`ID_OCTANE_IMAGE_TEXTURE` 1029508), material/object BaseContainer filename params, RS Dome Light HDR (`obj[ROOT_ID, REDSHIFT_FILE_PATH]` compound DescID), Alembic caches, and tag shader chains (Octane Environment Tag, Arnold Sky). Writers in `apply_texture_path_change` dispatch per source_type; node-graph writes use a maxon transaction with **mandatory** explicit `transaction.Commit()` (the `with` exit rolls back silently otherwise). UI: scrollable `TextureListArea` UserArea wrapped in a native `ScrollGroup`, status filter dropdown, Bulk Find/Replace (case-insensitive by default + "Match case" checkbox; `re.sub` with a lambda replacement so Windows backslash paths survive), last-5 Find/Replace presets persisted in `sentinel_settings.json`, Smart Actions (Auto-Find Missing, Make All Relative, Clear pending), per-row `[...]` file picker. **Undo**: Apply All wraps the batch in `StartUndo`/`EndUndo`; for node graphs `doc.AddUndo(c4d.UNDOTYPE_CHANGE, mat)` is the anchor that lets the transaction's `UndoMode.ADD` join the document undo step — a single Cmd+Z reverts the whole batch (verified: `Edit → Undo Modify <mat>`). Dialog is **async** not modal (a modal dialog captures the keyboard, so Cmd+Z never reached C4D); `CoreMessage`/`Timer` auto-refresh keeps the list in sync after an external undo. Diagnostic note: `doc.DoUndo()` called from the Script Manager is unreliable and is NOT a valid proxy for real Cmd+Z — verify undo via the Edit menu instead. V-Ray support intentionally dropped (out of studio scope).
- **v1.5.6** (May 2026): **Safe-Area Viewport Overlay**. Closes the v1.5.5 deferred work. After confirming `c4d.plugins.SceneHookData` is gone in C4D 2026 AND `TagData.Draw` is registered but never invoked (Init+Execute fire, Draw doesn't), pivoted to `ObjectData.Draw` in `DRAWPASS_OBJECT` which works reliably. Architecture: `SafeAreaOverlayObject(plugins.ObjectData)` auto-created at scene root when the Render-tab toggle is enabled. Marker is identified by plugin TYPE (`SAFE_AREA_OVERLAY_PLUGIN_ID = 2099072`), not name. Draw queries `bd.GetSafeFrame()` for the in-viewport letterboxed render rectangle, maps each format's master-NDC safe-box to pixel coords, draws 4 outline lines + HUD label per format. Per-format colors (white master, orange Reels, cyan square, magenta portrait, yellow cinema). Module-level `_overlay_state` singleton shared between panel and marker. New `plugin/res/` folder with `description/safearea_overlay.res` (`INCLUDE Obase`), `.h`, and `.str` for the localized name. Multi-Format orchestrator now also refreshes the overlay cache after Take regeneration. Composition Mode interaction documented: overlay always uses crop-interpretation model (matches QC #12), so Mode None + post-crop matches exactly; Mode Resize Canvas overlay is a composition reference (each take recomposes the camera per format).
- **v1.5.5** (May 2026): **Cross-Aspect Safe-Area QC (#12) + Multi-Format refactor**. New QC check verifies opt-in marked subjects (UserData boolean `[Sentinel] Safe Area Subject`) stay inside per-format safe areas across all active Multi-Format delivery Takes. Uses crop-interpretation math: bbox projects ONCE into master NDC, each format's safe area lives there as a centered crop region with per-side insets. Sample strategies "current_frame" (auto-refresh, cheap) and "keyframes" (Info button, full sweep with `SetTime`+`ExecutePasses` per sample). Tools tab → smart-toggle "Mark / Unmark Safe Area Subject" button. Score header now `X/12`. Multi-Format refactor: replaced Auto-FOV checkbox with Composition Mode dropdown (None / Resize Canvas). Resize Canvas uses sensor-size override (`new_aperture = src × target_w / src_w`) matching AR_ResizeCanvas community script. v1.5.4 carry-over fixes: `take.SetCamera` now assigned; `SetParameter` explicit after `FindOrAddOverrideParam` (defends against find-OR-add silent skip); C4D physical/RS cameras clamp FOV overrides — switched to sensor (aperture) override which isn't clamped. Other fixes: panel `_refresh` crash on non-QC tab reopen; NDC projection corrected from `-Z forward` to `+Z forward` (C4D left-handed convention). **Deferred to v1.5.6**: live viewport overlay (`c4d.plugins.SceneHookData` removed in C4D 2026 — pending TagData / MessageData investigation).

## Testing Checklist
- [ ] Main plugin file loads without errors
- [ ] All 12 quality checks function correctly
- [ ] Select/Fix/Info buttons work per check
- [ ] Auto-fix: lights→group, cameras→reset shift, unused mats→delete, FPS/range→standard
- [ ] FPS/range fix preserves duration, aligns timeline + preview, snaps playhead
- [ ] FPS/range fix shows confirmation dialog with diff preview
- [ ] FPS/range fix iterates ALL presets (not just active)
- [ ] Stills preset accepts Current Frame mode; animation presets require Manual range starting at 1001
- [ ] Save Version: doc unsaved → SaveDialog → file saved as `<base>_v001.c4d`, doc renamed
- [ ] Save Version: subsequent calls bump version, history JSON appended (newest first)
- [ ] Save Version: empty comment is rejected, Cancel is no-op
- [ ] Save Version: title bar updates after save, future Cmd+S overwrites latest version
- [ ] Status tags: WIP/TR/CR/FINAL applied as `_TR`, `_CR`, `_FINAL` filename suffixes (custom alphanumeric supported)
- [ ] Status tags: version bump correct across mixed status (`v002_TR` → `v003_REV02` → `v004`)
- [ ] "Continue from this version" prompt only after TR/CR/FINAL; auto-creates WIP version on Yes
- [ ] "Last version" pillbox updates on save and shows relative time ("just now" → "Xm/h/d ago")
- [ ] "final" in comment triggers soft warning (advisory dialog, doesn't block)
- [ ] Recent Versions list shows last 5 entries with color-coded status badges (WIP/TR/CR/FINAL)
- [ ] Filter dropdown (All/WIP/TR/CR/FINAL) updates the list correctly (WIP shows only `""` status entries)
- [ ] Click on a version row → confirmation dialog + opens that .c4d file via LoadFile
- [ ] Click row edge cases: file deleted → "File not found", same-as-active → "Already viewing", unsaved changes → warning
- [ ] Scene Notes: edit dialog opens with hint about shared-across-versions scope
- [ ] Scene Notes: notes + TODOs persist across Cmd+S and Save Version
- [ ] Scene Notes: panel caption shows ⚠ prefix when there are pending TODOs
- [ ] Scene Notes: TODOs toggle/delete/add work in dialog, Cancel discards changes
- [ ] Collect Scene: collected `.c4d` is renamed to clean original base (no `_v###` suffix)
- [ ] Collect Scene: manifest contains `original_filename`, `original_version`, `original_status`
- [ ] Collect Scene: notes sidecar copied with matching base name, panel reads it correctly
- [ ] Collect Scene: success dialog warns when there are pending TODOs
- [ ] RS AOV Essentials + Production tiers apply correctly
- [ ] Light Groups: diagnose + toggle on Beauty
- [ ] Scene Collector: pre-flight + SaveProject + manifest
- [ ] Take QC: validates camera and output tokens
- [ ] QC Report export produces valid JSON
- [ ] Render Presets: dropdown, resolution label, Reset All, Force 9:16
- [ ] Multi-Format: "Generate Format Takes..." opens modal seeded from current take/resolution
- [ ] Multi-Format: 5 child takes created under source take (16x9, 9x16, 1x1, 4x5, 21x9)
- [ ] Multi-Format: each take's render data has correct resolution + output path (subfolder or suffix)
- [ ] Multi-Format: Composition Mode "None" → camera intact across formats; vertical extent of master subject changes per format aspect (default C4D behavior)
- [ ] Multi-Format: Composition Mode "Resize Canvas" → CAMERAOBJECT_APERTURE overridden per format via `new_aperture = src × target_w / src_w`; angular field "rotates" between formats
- [ ] Multi-Format: re-run with "Update existing" ON → existing takes updated; stale FOV/focal overrides from prior runs reset to native
- [ ] Multi-Format: re-run with "Update existing" OFF → existing takes go to Skipped list
- [ ] Multi-Format: single Cmd+Z reverts the entire batch (StartUndo/EndUndo wrap)
- [ ] Multi-Format: every generated Take has source camera assigned via `take.SetCamera(td, cam)`
- [ ] QC #12: row appears in QC tab with Select + Info buttons; score header reads X/12
- [ ] QC #12: with no marked objects → row always reads `[ OK ]`
- [ ] QC #12: with no Multi-Format Takes → row always reads `[ OK ]`
- [ ] QC #12: cube marked + filling master → row reports violations (auto-refresh = current frame)
- [ ] QC #12: Info button → full keyframe sweep dialog with per-object, per-format, per-frames + edges breakdown
- [ ] QC #12: Select button → selects all marked objects with at least one violation (deduplicated)
- [ ] QC #12: after Info sweep, current timeline frame is restored (no scrub leakage)
- [ ] QC #12: keyframed object samples include union of PSR-track keyframes + midpoints
- [ ] QC #12: crop interpretation — same cube might fit in 16:9 master but violate 9:16 horizontal crop (and vice versa for 21:9 vertical)
- [ ] QC #12: asymmetric insets respected (9:16 violates bottom 15% before top 8%)
- [ ] Tools: "Mark / Unmark Safe Area Subject" button smart-toggles selection (all marked → unmark; any unmarked → mark all; empty → hint dialog)
- [ ] Tools: Mark operation is single-undoable via Cmd+Z
- [ ] Safe-Area Overlay: Render tab checkbox toggles overlay on/off
- [ ] Safe-Area Overlay: toggle ON auto-creates "Sentinel Safe-Area Overlay" object at scene root
- [ ] Safe-Area Overlay: 5 colored rectangles visible in viewport (white/orange/cyan/magenta/yellow per format) with fmt_id labels
- [ ] Safe-Area Overlay: deleting the marker object + toggle ON recreates it
- [ ] Safe-Area Overlay: regenerating Multi-Format Takes auto-refreshes the cached rectangles
- [ ] Safe-Area Overlay: rectangles correctly positioned inside `bd.GetSafeFrame()` (handles letterbox/pillarbox)
- [ ] Texture Repathing: Tools tab → Asset Management → "Texture Repathing..." opens the async dialog
- [ ] Texture Repathing: QC #6 Assets Info → offers to launch the tool when there are path issues
- [ ] Texture Repathing: scan lists RS/Arnold node textures, classic shaders, Octane image shaders, RS Dome HDR
- [ ] Texture Repathing: status filter (All/Missing/Absolute/OK/Asset URI) updates the list + scrollbar
- [ ] Texture Repathing: list scrolls (ScrollGroup) when there are more rows than fit
- [ ] Texture Repathing: Find/Replace is case-insensitive by default; "Match case" toggle enforces exact case
- [ ] Texture Repathing: Preview shows pending changes in green; Apply All commits + shows summary
- [ ] Texture Repathing: Apply All on a node-graph texture is reverted by a single Cmd+Z (Edit → Undo Modify <mat>)
- [ ] Texture Repathing: Make All Relative / Auto-Find Missing / per-row [...] file picker work
- [ ] Texture Repathing: last-5 Find/Replace presets persist in sentinel_settings.json, recallable via Recent combo
- [ ] Texture Repathing: list auto-refreshes after an external Cmd+Z (CoreMessage/Timer)
- [ ] Scene Tools: all 8 buttons functional (Hierarchy, H→Layers, Solo, Drop, Vibrate, ABC Retime, Cam Simple, Cam Shakel)
- [ ] Output: Open Folder, Save Still, Export QC, Collect Scene
- [ ] Snapshot dir picker ("...") persists between sessions
- [ ] Artist name persistence works
- [ ] Shot ID syncs with Take system
- [ ] Cross-platform: macOS and Windows

### Current UI Layout (v1.8.0):
```
┌─ Sentinel v1.8.0 ──────────────────────────────┐
│  Scene Header (always visible) ─────────────   │
│  ▸ Scene:  test_v007_TR.c4d                    │  ← filename caption
│  Shot ID: [Main]   Artist: [Motioneer]         │  ← editable
│  QC 9/12  ⚠  ████░░░░  ·  1.2M polys           │  ← score line
│ ─────────────────────────────────────────────  │
│  ┌───┬────────┬──────────┬───────┐             │
│  │QC●│ Render │ Versions │ Tools │ ← QuickTab  │
│  └───┴────────┴──────────┴───────┘             │
│ ─────────────────────────────────────────────  │
│  (active tab content — dynamically rebuilt     │
│   via LayoutFlushGroup on switch; only one     │
│   tab is in the layout at a time because       │
│   HideElement does not collapse layout space   │
│   in C4D 2026)                                 │
│                                                │
│  Tabs:                                         │
│    QC: 12 quality check rows + Export QC       │
│        (#12 = Cross-Aspect Safe Area)          │
│    Render: Preset + Multi-Format + AOVs + Snap │
│    Versions: Notes + Save Version + Recent     │
│    Tools: Layout / Animation / QC Marking /    │
│           Asset Management (Texture Repathing) │
│                                                │
│ ─────────────────────────────────────────────  │
│  Footer (always visible)                       │
│  [GitHub]                  [Report Bug]        │
└────────────────────────────────────────────────┘
```
