# Sentinel v1.5.6

Quality control, render management, and workflow automation plugin for Cinema 4D production environments — keeping the watchdog spirit of YS Guardian.

![Sentinel Interface](https://github.com/user-attachments/assets/847c6930-f54c-4f7f-86e2-5308f9e0e7bd)

> **Sentinel** is the continuation of [YS Guardian](https://github.com/yamb0x/ys-guardian), originally built at Yambo Studio. This fork extends the watchdog spirit with mograph-native workflow tools (Smart Save Versions, Status Tags, Browse Versions, RS AOV Management, FPS/Range validation, and more). Maintained by Javier Melgar.

## Overview

Sentinel is a Cinema 4D plugin that **watches your scene in real-time** and helps you ship cleaner renders. It runs continuous quality checks, manages render presets and Redshift AOVs, captures versioned saves with full metadata, and automates the boring parts of mograph delivery.

Sentinel monitors Cinema 4D scenes in real-time with **11 quality checks**, catching production issues before they reach the render farm. It also provides **Redshift AOV management** (Essentials/Production tiers with per-compositor config), **Scene Collector** (pre-flight QC + asset collection + manifest), and a full suite of scene tools: camera rigs (by keyframe wizard Riccardo Bottoni), abc_retime integration (by Austin Marola & Axis), Hierarchy→Layers, Solo Layers, Drop to Floor, and more.

**IMPORTANT**: The snapshot feature requires Python 3.x with Pillow and NumPy for EXR→PNG conversion with ACES tone mapping.

**Tested on**: Cinema 4D 2024/2026 and Redshift. macOS and Windows.

## Core Features

### Pipeline Checks

Eleven continuous quality checks to keep your C4D files clean:

- **Lights Organization** – Validates proper light group structure (Select + Fix)
- **Visibility Consistency** – Detects viewport/render visibility mismatches (Select)
- **Keyframe Validation** – Flags problematic multi-axis animations (Select)
- **Camera Shift Detection** – Ensures proper camera framing (Select + Fix)
- **Render Preset Compliance** – Enforces standardized output settings (Info)
- **Assets / Textures** – Missing textures, absolute paths, RS Node material paths via maxon API (Info)
- **Unused Materials** – Materials not applied to any object (Select + Fix)
- **Default Names** – Objects still using C4D default names (Select)
- **Output Paths** – Missing tokens, empty render output paths (Info)
- **Take Validation** – Camera assigned per take, $take token in output paths (Info)
- **FPS / Frame Range** – FPS, start frame = 1001 (VFX standard), frame step, timeline + preview alignment, all presets (Info + Fix)

Status display with color coding provides instant visual feedback. Per-check Select/Info/Fix buttons for one-click correction. Auto-fix available for lights, cameras, and unused materials.

### Render Management

#### Presets
Standardized presets with resolution display, one-click switching:

- **Previz** – 1280×720 @ 25fps
- **Pre-Render** – 1920×1080 @ 25fps
- **Render** – 1920×1080 @ 25fps
- **Stills** – 3840×2160 @ 25fps

**Reset All** resets all presets from a template file. **Force 9:16 / 16:9** toggles aspect ratio for social media delivery.

#### Redshift AOV Management
Two-tier AOV system configured per compositor target:

- **Essentials** (11 AOVs) – Core passes including Beauty for rebuild verification
- **Production** (17+ AOVs) – Full pass set for compositing
- **Light Groups** – Independent button, diagnoses groups + toggles on Beauty AOV
- **Compositor target**: Nuke vs After Effects (changes Depth and Motion Vector formats)
- **Multi-Part EXR**: Global checkbox with 32-bit Float + DWAB 45 compression
- Conditional AOVs: Caustics (auto-detect RS setting), Volumes (auto-detect scene objects)

#### Scene Collector
Pre-flight workflow for scene delivery:
1. Runs all 10 QC checks with summary
2. Offers auto-fix for fixable issues
3. Calls `c4d.documents.SaveProject()` for native asset collection
4. Generates `sentinel_manifest.json` with scene info, assets, and missing file list

#### Smart Save Version
Versioned saves with full context, beyond C4D's stock Save Incremental:

- Bumps file to `<scene>_v###.c4d` (3-digit, VFX-standard naming)
- **Review status tags** baked into filename: `_TR` (Team Review) / `_CR` (Client Review) / `_FINAL` / Custom (e.g. `_PITCH`, `_ALT01`)
- Required comment per version (forces meaningful checkpoints)
- Sidecar `<scene>_history.json` log: timestamp, artist, comment, **status**, QC score, scene stats, active take, file path
- Optional QC pre-flight: records pass/fail snapshot at save time
- First-time save opens SaveDialog with suggested `scene_v001.c4d`
- After saving a TR/CR/FINAL version: prompts to **auto-create a continuation WIP** so the review snapshot stays untouched
- Live "Last version" caption above the button: `v007 TR · 2h ago`
- **Browse Recent Versions** inline list: last 5 versions with color-coded status badges, filter dropdown (All/WIP/TR/CR/FINAL), click any row to open that version

#### Scene Notes & TODOs
Per-scene notepad with persistent storage that survives Cmd+S, Save Versions, and reopening C4D:

- **Free-form notes** + **TODO checklist** in a sidecar `<base>_notes.json` (parallel to history JSON)
- Modal editor: textarea for notes + clickable TODO list with checkbox toggle and × delete
- Live caption in the panel: `⚠ Notes: text + 3 TODOs (2 pending)` (warning prefix when there are pending TODOs)
- Notes are **shared across all versions** of the same scene base — they describe the project, not the file. Version-specific commentary goes in the Save Version comment field.
- Notes included in **QC report** export and **Scene Collector** manifest
- Sidecar copied to delivery folder by Scene Collector

#### Clean delivery naming (Collect Scene)
C4D's `SaveProject` saves the project using the delivery folder's name. Sentinel automatically renames the collected `.c4d` back to the **original scene base** (stripped of `_v###[_status]` suffix), so deliveries have a clean, predictable identity:

- Original: `robot_010_v022_FINAL.c4d` collected to `/delivery/round3/`
- Result: `/delivery/round3/robot_010.c4d` (not `round3.c4d`)
- Manifest preserves traceability: `original_filename`, `original_version`, `original_status`

#### QC Report Export
One-click JSON export with quality score, scene complexity stats, and detailed results for all 10 checks.

### Workflow Automation

**Hierarchy → Layers**
Converts scene hierarchy into a clean layer structure with automatic color coding for lights, cameras, and environment groups.

**Solo Layers**
Isolate selected layers with a single click — a lightweight take on cv-layer-comps that plays nice with it.

**Vibrate Null**
A replacement for the classic Vibrate Tag — consistent results and perfect loops. Merges pre-configured null with vibration expression.

**Camera Rigs**
Three production-ready camera setups (Simple, Shakel, Path) by keyframe wizard **Riccardo Bottoni** (@riccardobottoni). One-click merge into scene.

**Drop to Floor**
Mini-remake of the old favorite plugin for snapping objects onto surfaces. Accurate Y=0 positioning for rotated/grouped objects.

**ABC Retime Shortcut**
Quick access to the excellent Alembic retime tool by **Austin Marola** (@zonedog) and **@axisfx**. One-click tag application for alembic retiming. [GitHub: abc_retime](https://github.com/axisfx2/abc_retime)

### Quick Tools

**Create Hierarchy**
Merges a pre-configured null hierarchy template into the scene for quick project setup.

### Grab Stills

Automatic snapshot workflow with color-accurate conversion using bundled global Python install — capture your work as you go:

- Captures Redshift RenderView snapshots as EXR
- Converts to PNG with ACES RRT/ODT tone mapping
- Organizes output: `Output/[Artist]/YYMMDD/scene_HHMMSS.png` (studio folder structure inherited from YS Guardian)
- Displays in Picture Viewer with metadata

This system maintains color accuracy by matching your scene's ACES tone mapping, providing convenient PNG output for client review and archival. **Please report if color seems off!**

## Installation

### Requirements

- Cinema 4D 2024 or later
- Redshift 3D (for AOV management and snapshot features)
- macOS or Windows
- Python 3.x with Pillow + NumPy (for snapshot EXR→PNG conversion)

### Quick Install (Windows)

```bash
# Run as Administrator
INSTALL_YS_GUARDIAN.bat
```

The installer handles:
- Plugin files → Cinema 4D plugins folder
- Python 3.x + Pillow + NumPy (global install)
- Directory structure creation (`C:\cache\rs snapshots\`)
- ABC Retime plugin integration

### Manual Install (macOS / Windows)

1. Copy the `plugin/` folder contents to your Cinema 4D plugins directory
2. For snapshot features: install Python dependencies (`pip3 install Pillow numpy OpenEXR`)
3. Restart Cinema 4D

### Redshift Configuration

For snapshot features to function properly:

1. Open Redshift RenderView → Preferences (gear icon) → Snapshots → Configuration
2. Set path: `C:/cache/rs snapshots`
3. Enable **"Save snapshots as EXR"** (not .rssnap2)
4. Click OK

The installer creates the cache directory automatically. This configuration is required for the Save Still feature.

## Usage

### Initial Setup

1. Extensions → Sentinel
2. Enter artist name (saved per computer)
3. Configure monitoring update rate (default: 800ms)
4. Verify Redshift snapshot format is set to EXR

### Quality Workflow

Status display shows real-time results for all 11 checks:

```
[FAIL] LIGHTS        : 3 lights outside lights group     [Select] [Fix]
[WARN] VISIBILITY    : Visibility mismatch on 2 objects  [Select]
[ OK ] KEYFRAMES     : Keyframes properly configured      [Select]
[ OK ] CAMERAS       : Camera shifts at 0%                [Select] [Fix]
[ OK ] PRESETS       : Render presets compliant            [Info]
[ OK ] ASSETS        : All textures found                 [Info]
[FAIL] UNUSED MATS   : 5 unused materials                [Select] [Fix]
[WARN] NAMES         : 12 default names                  [Select]
[ OK ] OUTPUT        : Output paths valid                 [Info]
[ OK ] TAKES         : All takes configured               [Info]
[FAIL] FPS/RANGE     : 4 FPS/range issue(s)              [Info]   [Fix]
```

**Select** buttons cycle through problematic objects. **Fix** buttons auto-resolve issues. **Info** buttons show detailed diagnostics.

### Stills Workflow

1. Render preview in Redshift RenderView
2. Take snapshot in RenderView (Redshift saves to cache as EXR)
3. Click **Save Still** in Sentinel panel
4. PNG appears in organized artist/date folder structure
5. Opens automatically in Picture Viewer

### Layer Management

**Hierarchy → Layers**:
1. Organize objects into top-level null groups
2. Click **Hierarchy→Layers (2x)** button
3. Plugin creates/syncs layers with automatic color coding

**Solo Layers**:
1. Select layers in Layer Manager
2. Click **Solo (2x)** button
3. Plugin isolates selected layers, hides all others
4. Click again to restore visibility

### Quick Actions

- **Hierarchy**: Merges null hierarchy template into scene
- **H → Layers**: Converts scene hierarchy into layer structure with auto color coding
- **Solo Layers**: Isolate selected layers (toggle)
- **Drop to Floor**: Snaps selected objects to Y=0 (handles rotation + hierarchy)
- **Vibrate Null**: Merges vibration null with expression
- **ABC Retime**: Applies Alembic Retime tag to selected cache objects
- **Cam Simple / Cam Shakel**: Merge production-ready camera rigs

## Technical Details

### Performance

- CoreMessage dirty-flag pattern — checks only run when scene actually changes
- CHECK_COOLDOWN 0.5s prevents redundant scans
- Chunked processing for large scenes (1000+ objects/cycle)
- Low memory footprint

### Data Persistence

- **Artist Name, Compositor Target, Multi-Part, Snapshot Dir**: Saved per computer in Cinema 4D preferences (`sentinel_settings.json`; legacy `ys_guardian_settings.json` is auto-migrated on first run)
- **Shot ID**: Synced with Take system (Main Take name)
- **Window Layout**: Preserved by Cinema 4D workspace

### EXR Conversion

The snapshot system uses external Python with Pillow for color-accurate conversion. Applies **ACES RRT/ODT display transform** to match Redshift RenderView output, maintaining professional color fidelity while providing convenient PNG output for review workflows.

**Technical Implementation**:
- Reads EXR linear data
- Converts ACEScg → linear sRGB
- Applies ACES RRT/ODT tone mapping
- Encodes to sRGB with proper OETF
- Saves as PNG with maximum quality (no compression)

### Supported Cache Types (ABC Retime)

- Alembic Object
- Alembic Tag
- Point Cache
- Mograph Cache
- X-Particles Cache

## Troubleshooting

**Quality checks not updating**
- Checks run on scene change via CoreMessage — make sure the scene has actually changed
- Try closing and reopening the panel if checks appear stuck

**Snapshot conversion fails**
- Verify Redshift saves EXR format (not .rssnap2)
- Check Python dependencies: `pip3 install Pillow numpy OpenEXR`
- Confirm snapshot directory is set (click "..." button in Output section)
- macOS: uses `/usr/bin/python3` by default

**AOVs not applying**
- Ensure Redshift is the active render engine
- Check the Comp target dropdown matches your pipeline (Nuke vs AE)
- Use **Show AOVs** to verify current state

**Layer sync errors**
- Organize objects in top-level null groups (no orphan objects)
- Ensure unique null names

**Preset switching issues**
- Preset names are case-insensitive: "pre_render", "pre-render", "Pre Render" all work
- Use **Reset All** to recreate presets from template

**Scene Collector issues**
- Runs SaveProject() — requires a saved .c4d file first
- Missing assets are listed in the manifest but not blocked

**ABC Retime not working**
- Verify selected object is a supported cache type
- Check if tag already exists on object
- Ensure abc_retime plugin is installed in Cinema 4D plugins folder

## Changelog

### v1.5.6 | 12.05.2026

**New: Cross-Aspect Safe-Area viewport overlay**

The QC #12 safe-area regions (deferred from v1.5.5 because `c4d.plugins.SceneHookData` was removed in C4D 2026) are now rendered live in the active camera viewport, so artists can compose against the actual delivery crops without having to switch between Takes or check the Info dialog.

- **Auto-managed marker object** — toggling the new "Show Safe-Area Overlay in viewport" checkbox (Render tab → Multi-Format Setup section) auto-creates a `Sentinel Safe-Area Overlay` object at the scene root. The object's `Draw()` renders the rectangles. If you delete the object manually, the next toggle ON recreates it. Identified by plugin TYPE (not name), so renames don't break detection.
- **Per-format colors**:
  - **16:9** white (broadcast master)
  - **9:16** orange (IG Reels / TikTok)
  - **1:1** cyan (IG Square)
  - **4:5** magenta (IG Feed portrait)
  - **21:9** yellow (cinema)
- Each rectangle labeled with its `fmt_id` in the top-left corner.
- Persists with the `.c4d` save and survives panel reopens (the toggle state and the marker object both stick).
- Same crop-interpretation math as QC #12: rectangles represent where each delivery aspect would crop the master view, with per-format safe-area insets applied (e.g. 9:16 caption/icon region). The overlay is a **composition aid**, not an exact render preview — its model is "compose for crops, deliver multi-aspect", matching the GSG Social Frame workflow and the default Composition Mode (None).
- Auto-refreshes the cached rectangles when Multi-Format Setup regenerates Takes — no manual refresh needed.

**Architecture — pivot from SceneHookData to ObjectData**

The viewport overlay was deferred from v1.5.5 because `c4d.plugins.SceneHookData` and `RegisterSceneHookPlugin` were removed/migrated in C4D 2026. v1.5.6 went through an investigation round to pick the right replacement:

1. **TagData with `Draw()`** — the obvious first candidate (tag-on-camera architecture). Verified empirically with a probe: TagData registers cleanly and `Init` + `Execute` fire as expected, but `Draw` is **never invoked** by C4D 2026's Python viewport pipeline. Only the tag's built-in handle gets drawn. Path abandoned.
2. **ObjectData with `Draw()`** — confirmed working. `DRAWPASS_OBJECT` fires regardless of selection. `bd.SetMatrix_Screen()` + `bd.DrawLine` + `bd.DrawHUDText` all work as expected. `bd.GetSafeFrame()` returns the rendered frame's letterboxed rectangle inside the viewport — exactly what's needed to position format rectangles correctly. This is the path Sentinel took.

The final architecture: one `SafeAreaOverlayObject` (ObjectData) per document, auto-managed by the panel. Communicates with the panel via a module-level singleton (`_overlay_state`) — the panel mutates state, the marker's Draw reads it. No per-frame scene scanning, no projection per draw — Draw just iterates a pre-computed list of pixel rectangles.

---

### v1.5.5 | 11.05.2026

**New: QC Check #12 — Cross-Aspect Safe Area**

Validates that key compositional elements stay inside the per-format safe-area regions when the same scene is delivered across multiple aspect ratios. Closes the loop with the Multi-Format Setup feature from v1.5.4 — generate the format Takes, mark the subjects that must stay framed, then let Sentinel flag any subject that would get cropped in any delivery aspect.

- **Opt-in via UserData marker.** Artists mark important subjects (logo, title, character) with a `[Sentinel] Safe Area Subject` UserData boolean — clean, persistent across save/reload, zero new tag plugins, no scene clutter. A new **"Mark / Unmark Safe Area Subject"** button in the Tools tab smart-toggles the marker on the current selection (mark-all / unmark-all / mark-mixed-to-marked).
- **Per-format safe-area insets** derived from real platform specs:
  - 16:9 — 5% all around (broadcast standard)
  - 9:16 — 8% top / **15% bottom** / 5% left / **10% right** (IG Reels caption + icon stack)
  - 1:1 — 5% top / 8% bottom (IG Square)
  - 4:5 — 5% top / 10% bottom (IG Feed portrait)
  - 21:9 — 5% all around (cinema)
- **Crop interpretation, not render interpretation.** The check matches the artist's mental model: "compose once in the master view, deliver as aspect-ratio crops". Bbox corners project ONCE into the master Take's NDC, then each format's safe area lives in master NDC as a centered crop region with the per-side insets applied. Subjects that fit the master might still violate the narrower vertical crops (9:16 / 1:1 / 4:5) — that's exactly the warning artists need before delivery.
- **Sample strategies.** Auto-refresh in the QC panel uses the current frame (cheap — no scene time-travel). Click **Info** to trigger a full keyframe sweep that samples each marked object's PSR keyframes + midpoints (catches arc swings that cross safe areas between keyframes). Original timeline position is always restored.
- **UI integration.** New row #12 in the QC tab with Select / Info buttons. Score header now reads `X/12`. The check is fully integrated with the existing dirty-flag refresh model.
- **Asymmetric safe areas modeled correctly.** A logo near the bottom of a 16:9 master may violate 9:16's bottom inset (15%) without violating 16:9's bottom (5%) — Sentinel reports the offending edge per format.

**Refactored: Multi-Format Setup — composition mode**

After user testing, replaced the v1.5.4 "Auto-FOV" toggle (vertical-FOV-constant focal override) with a **Composition Mode** dropdown that better matches real workflows:

- **None** (default) — camera unchanged; only resolution + output path overrides per Take. Matches Greyscalegorilla *Social Frame* behavior — the artist composes for the intersection of delivery formats, and each Take just changes the render aspect. Any stale FOV / focal-length / aperture overrides from prior runs are reset to the camera's native values (defensive cleanup of v1.5.4 takes).
- **Resize Canvas** — overrides `CAMERAOBJECT_APERTURE` (sensor size) per format using AR_ResizeCanvas's formula: `new_aperture = source_aperture × target_width / source_width`. Same math used by Arttu Rautio's [AR_ResizeCanvas](https://aturtur.com/) C4D community script and described in Kengo Ito's *"絵を変えずにレンダーサイズを拡張する"* (extending render size without changing the picture) note article. Sensor-based instead of focal-length so existing focal-length animations and DOF setups stay intact.

**Bug fixes in the Multi-Format orchestrator (v1.5.4 carry-over):**

- `take.SetCamera(td, source_cam)` now assigned to every generated Take — previously `take.GetCamera(td)` returned `None`, falling back to the scene's active camera.
- `FindOrAddOverrideParam` is **find-OR-add**, not find-AND-update. The orchestrator now calls `ovr.SetParameter(...)` explicitly after the find/add to ensure the intended value is written (previous behavior silently kept stale values from earlier runs).
- C4D's physical / Redshift cameras clamp `CAMERAOBJECT_FOV` overrides to the focal-derived native FOV. The new Resize Canvas mode uses the sensor (`CAMERAOBJECT_APERTURE`) instead, which isn't clamped.

**Bug fix: panel `_refresh` crash on non-QC tab reopen**

When the panel reopened on a Render / Versions / Tools tab (saved from the previous session), `self.ua` (the StatusArea UserArea) stayed `None` because `_build_tab_qc` hadn't run yet, and the auto-refresh crashed on `self.ua.set_state(...)`. Added the same `if self.ua is not None` guard already used for `self.score_ua`.

**Bug fix: camera Z convention in NDC projection**

The first iteration of QC #12's projection math assumed C4D cameras look down `-Z` (a common convention from OpenGL / Maya). Verified empirically that **C4D uses `+Z` forward** (left-handed system): points in front of the camera have `p_cam.z > 0`. Without this fix every projected bbox corner read as "behind camera" and the check returned zero violations against a clearly out-of-frame subject.

**Known limitation deferred to v1.5.6**

A viewport overlay (live colored rectangles showing each format's crop + safe area in the active camera view) was prototyped for v1.5.5 but couldn't ship: `c4d.plugins.SceneHookData` was removed / migrated in C4D 2026 and the replacement isn't documented in the local SDK clone. The QC check itself works fully — only the live viewport visualization is postponed. Probable replacements to evaluate for v1.5.6: TagData attached to the active camera, or a MessageData hook.

---

### v1.5.4 | 08.05.2026

**New: Multi-Format Render Setup**

One-click generator that creates Cinema 4D Takes for the standard delivery aspect ratios — each Take ships with its own cloned Render Data (resolution + output path overrides) and an optional camera FOV adjustment, so the same animation can be rendered to multiple formats without manual duplication.

- **Five formats** checked by default: 16:9 Landscape (1920×1080), 9:16 Vertical (1080×1920), 1:1 Square (1080×1080), 4:5 Portrait (1080×1350), 21:9 Cinema (2560×1080).
- **Auto-adjust FOV per ratio** (Social Frame pattern): the camera's horizontal FOV is overridden per Take so the **vertical FOV stays constant** across formats. Subjects framed in the master crop stay framed in all crops — no zoom-in surprise on the 9:16 Reel.
- **Output structure** options: per-format subfolder (`output/16x9/$prj`, `output/9x16/$prj`, ...) or filename suffix (`$prj_16x9`, `$prj_9x16`, ...). Subfolder is the default — easier to deliver per-aspect.
- **Idempotent**: re-running the command updates existing same-name Takes in place (or skips them if "Update existing" is off). Uses C4D's `FindOrAddOverrideParam` so FOV overrides update cleanly without duplicating.
- **Take hierarchy**: new Takes are created as children of the current/source Take (typically Main), so they inherit any animation/material overrides above them.
- **Full undo**: the entire batch operation lives inside `StartUndo`/`EndUndo` — Cmd+Z reverts all generated Takes in one step.
- **Summary dialog** after generation: created / updated / skipped / errors counts per Take name.

**Why this design?** Studio research (across mograph and broadcast pipelines) showed two compose-and-derive schools: (a) compose in 1:1 or 4:5 master and crop into all formats — works only if subjects stay near the safe area intersection — and (b) compose in your primary format and adjust FOV per ratio. The Multi-Format Setup supports both: artists can leave Auto-FOV off for school A or on for school B. The dialog hint surfaces this trade-off explicitly.

**Where**: Render tab → **Generate Format Takes...** button. The dialog seeds Source Take + resolution from the active document, all 5 formats are pre-checked, Auto-FOV is on, "Update existing" is on.

**Tokens**: this version uses literal path manipulation. A future iteration will adopt the `$take` and `$prj` token system more deeply (currently only `$take` is added in QC #10's output validation).

---

### v1.5.2 | 07.05.2026

**UI/UX redesign — Scene Header + Tabs**
- The panel now has a **Scene Header** always visible at the top: filename caption (`▸ Scene: name.c4d`) + Shot ID/Artist + QC progress bar with scene stats. This way the most critical info is glanceable regardless of which tab is active.
- Content is split into 4 tabs (`CUSTOMGUI_QUICKTAB`):
  - **QC**: 11 quality checks + Export QC Report
  - **Render**: Preset, Redshift AOVs, Snapshot system
  - **Versions**: Notes, Save Version, Collect Scene, Recent Versions browser
  - **Tools**: Layout & Hierarchy / Object & Animation / Camera Rigs
- A persistent **Footer** holds the GitHub + Report Bug links.

**Why a redesign?** After 5 versions of additions, the panel had ~70 visible elements stacked vertically with no clear hierarchy. The tabbed structure reduces visible density to ~20 elements at a time, while the always-visible header keeps the most critical info one glance away. Same approach used by professional C4D plugins (X-Particles, Greyscalegorilla ecosystem).

**Technical: dynamic tab rebuild**
- C4D 2026's `HideElement` returns success but does NOT collapse layout space for hidden groups (verified empirically). The fix: a single `TAB_CONTAINER` is flushed (`LayoutFlushGroup`) and rebuilt with the active tab's content on every switch.
- `StatusArea` and `HistoryArea` instances persist on `self` and are re-attached after rebuild.
- Combo boxes are repopulated and combo selections restored from settings on each tab build.

**Documented C4D limitation**: The docked panel **does not auto-shrink** when content gets smaller. Confirmed by Maxon SDK docs and Plugin Cafe staff: no `SetSize`/`ResizeWindow`/`FitToContent` API exists for docked panels. Maxon's own panels (Take Manager, AOV Manager) have this same behavior. The `BFV_SCALEFIT` spacers absorb gaps within the layout, but the window frame stays at its tallest seen size until manual user resize.

**Other fixes**
- Empty `GroupBegin/End` with `BFV_SCALEFIT` does NOT absorb space in C4D 2026 — must use `AddStaticText(..., BFV_SCALEFIT, ..., "", ...)` instead.
- Multiple internal cleanups: removed obsolete debug logging, consolidated combo population logic into per-tab builders.

### v1.5.1 | 06.05.2026

**New: Scene Notes & TODOs**
- Per-scene sidecar `<base>_notes.json` (mirrors the history JSON pattern)
- Modal editor with multiline notes + clickable TODO list (toggle done, delete, add)
- Panel caption with warning prefix when there are pending TODOs
- Notes shared across all versions of the same scene base (project-level scope)
- Dialog explicitly explains the shared-scope to avoid confusion: "These notes apply to ALL versions of this scene"
- Cancel discards changes (deepcopy semantics); Save persists atomically

**New: Clean delivery naming (Collect Scene)**
- After `SaveProject`, the collected `.c4d` is automatically renamed to the original scene base (stripped of `_v###[_status]`)
- Example: `test_v006.c4d` collected to `/Desktop/collected/` → produces `test.c4d` (not `collected.c4d`)
- Manifest preserves traceability via new fields: `original_filename`, `original_version`, `original_status`
- Doc path/name updated so C4D's title bar reflects the renamed file
- Defensive: refuses to overwrite an existing file at the desired path

**Notes integration**
- Scene Collector manifest includes `notes` section (summary, text, todos, pending_count, updated)
- Notes sidecar copied to delivery folder alongside the .c4d (matching base name)
- QC report export includes the same `notes` section (always present, with empty defaults if no sidecar)
- Collect Scene success dialog warns when there are pending TODOs

**Bugfix**
- Notes path was being read AFTER `SaveProject`, but SaveProject changes the doc's path/name to the delivery folder. Fixed by capturing notes path + data BEFORE SaveProject.

### v1.5.0 | 05.05.2026

**Rebrand: YS Guardian → Sentinel**
- Renamed the plugin to **Sentinel** to mark its evolution beyond the original Yambo Studio scope (which had grown to 11 QC checks, RS AOV management, Smart Save Versions with status tags, Browse Versions inline, FPS/Range validation, and full mograph workflow tooling)
- Plugin file: `ys_guardian_panel.pyp` → `sentinel_panel.pyp`
- Settings: `ys_guardian_settings.json` → `sentinel_settings.json` (auto-migrated from legacy file on first run — no preferences lost)
- Manifest: `ys_guardian_manifest.json` → `sentinel_manifest.json`
- C4D plugin folder: `YS_Guardian/` → `Sentinel/` (old folder must be removed manually)
- All references updated; YS Guardian heritage explicitly credited in README, CLAUDE.md, and the License section

**Why**: After 5 versions of additions (v1.4.0–v1.4.4) the plugin had outgrown the "YS Guardian" identity. Sentinel inherits the watchdog DNA but communicates the broader scope and signals that this is now a personal continuation by Javier Melgar — not the studio plugin it started as. The atribution to Yambo Studio remains explicit throughout the docs.

### v1.4.4 | 05.05.2026

**New: Browse Recent Versions inline**
- New custom-drawn list in the Output section showing the last 5 versions of the active scene
- Color-coded status badges: WIP (grey) / TR (amber) / CR (blue) / FINAL (green) / Custom (purple)
- Each row: version label, badge, comment, QC score (if recorded), relative time
- Filter dropdown: All / WIP / TR / CR / FINAL
- Click any row → confirmation dialog with version preview + opens the file via `c4d.documents.LoadFile`
- Edge cases handled: file deleted ("File not found"), already-active doc ("Already viewing"), unsaved changes warning

**Fix: user-area click coordinate conversion in C4D 2026**
- Discovered the documented `GeUserArea.Global2Local(x, y)` does not return area-local coordinates correctly in C4D 2026 Python
- Workaround: use `Local2Global()` (no args) to get the area's window origin, then subtract from raw `msg[BFM_INPUT_X/Y]`
- Shared helper `_ua_local_coords()` used by both `StatusArea` and `HistoryArea`
- Fixes click-row precision in the QC section (was working approximately, now exact)

**Why**: Smart Save Version (v1.4.2-v1.4.3) writes a rich history JSON, but until now only the latest entry was surfaced (via the pillbox). v1.4.4 closes the read side of the loop — artists can finally see and act on the version metadata they're capturing.

### v1.4.3 | 05.05.2026

**Smart Save UX (mograph-native workflow)**:
- Review status tags integrated into Save Version: WIP / TR (Team Review) / CR (Client Review) / FINAL / Custom (alphanumeric)
- Status appears as suffix in filename: `scene_v007_TR.c4d`, `scene_v012_CR.c4d`, `scene_v022_FINAL.c4d`
- Custom field overrides the dropdown when filled (sanitized to uppercase alphanumeric)
- Live filename preview updates as user changes status
- "final" written in comment triggers a soft advisory (suggests using the FINAL tag instead — non-blocking)

**"Continue from this version" — protect review snapshots**:
- After saving a TR/CR/FINAL version, prompts to auto-create a new WIP version
- Continuation has comment `"Continue from v007_TR"` and skips QC re-run (same scene state)
- The review snapshot stays untouched even if the artist Cmd+S afterwards
- Why: prevents the classic "the file the team is reviewing isn't what they were sent" bug

**"Last version" pillbox**:
- Live caption above Save Version button: `Last version: v007 TR · 2h ago`
- Reads latest entry from sidecar history JSON
- Relative time formatting (just now / Xm ago / Xh ago / Xd ago / absolute date for >30 days)
- Empty states handled: "scene not saved yet" / "none yet — click Save Version"

**Why these changes**: Research across the mograph community (Vinzent Britz, Matthew Creed, GSG forum) showed the de-facto convention isn't VFX-style `show_seq_shot` but `Client-Project-Description` with review-status suffixes. v1.4.3 brought the plugin in line with how mograph artists actually mark their checkpoints.

### v1.4.2 | 04.05.2026

**New: Smart Save Version**:
- Versioned saves with required comment, QC score, scene stats per version
- Naming convention enforced: `<scene>_v###.c4d` (3-digit, VFX-aligned with frame 1001 standard)
- Sidecar `<scene>_history.json` log with all versions (newest first)
- First-time save: opens SaveDialog with suggested `scene_v001.c4d`
- Subsequent saves: scans folder + history, bumps version automatically
- Captures: timestamp, artist, comment, QC score, polys/mats/lights, active take
- Updates document path so C4D title bar + Cmd+S follow the new version
- Refuses to overwrite existing files (defensive)

**Why over C4D's native Save Incremental**: native bumps numbers but stores no context. With 14 numbered files and no comments, version history is useless. Smart Save adds the layer of metadata that makes versioning actually useful for production review and rollback.

**UI polish**:
- New Score header above QC rows: progress bar + "QC X/Y" + PASS/WARN/FAIL + scene stats inline
- Click anywhere on a QC row to trigger its primary action (bigger click target)
- Output section reorganized: Save Version + Collect Scene as primary checkpoint actions
- "..." snapshot dir button → "Browse" (clearer)

### v1.4.1 | 23.04.2026

**New QC Check #11: FPS / Frame Range**:
- Validates document FPS, render data FPS (independent), frame range, frame step, timeline, and preview/loop alignment
- Enforces VFX/cinema standard: start frame = **1001** (with handles before, room for pre-roll)
- Per-preset behavior: animation presets require Manual range; **stills** preset accepts Current Frame mode
- Auto-fix iterates ALL presets in the document, not just the active one
- Fix preserves frame duration, aligns timeline + preview/loop, and snaps playhead to range if it fell outside
- Confirmation dialog before applying fix, with preview of all changes
- Configurable studio FPS via `standard_fps` key in `sentinel_settings.json` (default 25)
- Frame step validation (warns if != 1, catches accidental frame skipping)
- Full undo support (Ctrl+Z reverts entire fix in one step)
- Included in QC report export

**Why 1001?**: De facto VFX/cinema standard. Frame 1001 is the first frame of editorial action; frames 993-1000 are head handles (pre-roll). 4-digit padding ensures correct file sorting. Used by ILM, Weta, Framestore, MPC, DNEG, ShotGrid defaults.

### v1.4.0 | 08.04.2026

**Major Features**:
- **Take-based QC** (check #10) - Validates camera assigned per take and $take token in output paths
- **Scene Collector** - Pre-flight QC + `SaveProject()` + manifest JSON for scene delivery
- **Light Groups AOV** - Independent button: diagnose light group assignments + toggle on Beauty AOV
- **UI reorganized by workflow**: Scene Info → Quality Checks → Scene Tools → Render → Output

**Render Section**:
- Unified presets + AOVs in single Render section
- Resolution display next to preset dropdown
- Reset All from template (with confirmation dialog)
- Force 9:16 ↔ 16:9 toggle (reversible)

**Code Quality**:
- Replaced 40+ bare `except:` with `except Exception:`
- Removed ~400 lines of dead code
- CoreMessage dirty-flag pattern (efficient scene change detection)
- Safe name access for dead C4D objects (`_safe_name` helper)

### v1.3.0 | March 2026

**RS AOV Management**:
- 2-tier system: Essentials (11 AOVs) / Production (17+ AOVs)
- Per-compositor config: Nuke vs After Effects (Depth + Motion Vector formats)
- Multi-Part EXR with 32-bit Float + DWAB 45 compression
- Conditional AOVs: Caustics (auto-detect setting), Volumes (auto-detect objects)
- All param IDs documented in RS_AOV_PARAM_IDS.md

**Render Presets**:
- Reset All from template file
- Force 9:16 toggle for social media delivery

### v1.2.0 | March 2026

**New QC Checks** (#6-#9):
- Unused materials detection (Select + Fix: delete cycling one-by-one)
- Default naming conventions (Select: cycling through offenders)
- Output path validation (missing tokens, empty paths)
- Missing textures (files not found on disk, RS Node materials via maxon API)
- Unified 3 texture checks into single "Assets" check

**Power Features**:
- Auto-fix: lights → group, camera shift → reset, unused mats → delete
- QC Report export (JSON with score, scene stats, all check details)
- Scene complexity stats (objects, polygons, materials, lights)

### v1.1.0 | March 2026

**Foundation & UI**:
- Fixed safe_print used before definition
- Fixed duplicate widget IDs
- Cross-platform support: replaced `os.startfile` with platform-aware opener
- Added CoreMessage() for instant scene change reaction
- Section headers with BORDER_WITH_TITLE_BOLD
- Per-check Select/Info/Fix buttons
- Data-driven StatusArea renderer

**Snapshot System Rewrite**:
- Cross-platform EXR→PNG via external Python + OpenEXR
- Full ACES pipeline: ACEScg → sRGB matrix → ACES tonemap → sRGB OETF
- Configurable RS snapshot directory (UI button + persisted settings)
- Auto-discover system Python on macOS + Windows

### v1.0.3 | 16.02.2026

- Added Create Hierarchy button (one-click null hierarchy template)
- Removed absolute path popup warning (status shown passively)
- Removed Cam3 (Path) button — replaced by Create Hierarchy

### v1.0.2 | 09.11.2025

- Fixed absolute path detection for node materials (was missing standard C4D node materials)
- Now scans all material parameter containers for file paths
- Detects both `/` and `\` absolute path formats

### v1.0.1 | 11.10.2025

- Fixed null print spam in console
- Corrected stills tone mapping to proper ACES RRT/ODT
- Added abc_retime plugin integration by @zonedog + @axisfx
- Thanks @thodos for the tips ❤️

### v1.0.0 | 10.10.2025

Initial release:
- Five pipeline quality checks
- Render preset management
- Hierarchy→Layers and Solo Layers
- Vibrate Null, Camera Rigs, Drop to Floor
- Redshift snapshot conversion with ACES tone mapping
- Quick tools

## License

Free for personal and commercial use. Redistribution not permitted without permission.
Originally developed as YS Guardian at Yambo Studio. Sentinel is the continued maintenance and extension of that work by Javier Melgar.

## Support

**Found a bug or have a feature request?**
Use the **Report Bug** button in the plugin or visit the [Issues page](https://github.com/jmcodex93/sentinel/issues/new).

**When reporting bugs**, please include:
- Cinema 4D version and Redshift version
- Error description and steps to reproduce
- Logs from: `C:\Sentinel_Output\snapshot_log.txt`

## Special Thanks

- **Yambo Studio** — for building YS Guardian, the foundation Sentinel grew from.
- **Riccardo Bottoni** (@riccardobottoni) – Camera rigs (Simple, Shakel, Path). The keyframe wizard himself.
- **Austin Marola** (@zonedog) and **@axisfx** – [ABC Retime plugin](https://github.com/axisfx2/abc_retime). Incredible little tool for alembic retiming.
- **Drop to Floor** original creators – Took the concept and rewrote it for modern C4D.
- **@thodos** – For tips that led to v1.0.1 improvements.

## Links

[GitHub Repository](https://github.com/jmcodex93/sentinel) · [Report Bug](https://github.com/jmcodex93/sentinel/issues/new) · [Development Guide](CLAUDE.md) · [Original YS Guardian](https://github.com/yamb0x/ys-guardian)

---

**Sentinel** — continuing the watchdog tradition. Maintained with ❤️ by Javier Melgar.
