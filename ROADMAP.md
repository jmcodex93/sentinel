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

### v1.5.0 — Production Workflow (Tier A: High impact, easy)

> Note: FPS + Frame Range Validation shipped early as v1.4.1.
> Note: Smart Incremental Save shipped early as v1.4.2.
> Note: Status Tags + Continue from review + Last-version pillbox shipped as v1.4.3.
> Note: Browse Recent Versions inline shipped as v1.4.4.
> Note: Scene Notes / TODO + clean delivery naming shipped as v1.5.1.

#### Review Slate on Snapshots
Burn metadata into Save Still PNGs:
- Shot ID, Artist name, Frame number, Date, Resolution
- Small overlay bar at bottom (like editorial slates)
- Supervisor instantly knows the context of every image

**Why**: Unnamed PNGs on a server are useless without context. Every image should be self-documenting.

#### FPS Settings UI (polish for QC #11)
Add a dropdown or settings dialog to change the studio standard FPS without editing the JSON manually. Group FPS/Range issues by category in Info dialog (FPS / Range / Timeline) for clearer reading.

**Why**: Currently only configurable via `sentinel_settings.json`. Most artists won't open it.

### v1.6.0 — Asset Health & Validation (Tier B: High impact, medium effort)

> Note: Multi-Format Render Setup shipped early as v1.5.4.

#### Cross-Aspect Safe-Area QC (planned v1.5.5)
QC check #12: warn when keyframed objects (or their bounding box) exit the safe-area intersection of the active multi-format Takes. Closes the loop with the Multi-Format Render Setup so artists know when their composition won't survive a 9:16 crop.

#### Texture Repathing Tool
Bulk find-and-replace for texture paths:
- Show all textures with current paths
- Find/replace path prefixes (e.g., `/Users/old/` → `/server/project/`)
- One-click "make all relative"
- Works with classic shaders AND RS node materials

**Why**: Moving projects between machines/servers breaks all texture paths. This is a daily pain point.

#### Post-Render Validation
Verify render output after completion:
- Check all expected AOV files exist
- Detect zero-byte files (failed frames)
- Verify frame sequence completeness (no gaps: frame 1-100 should have 100 files)
- Report missing/corrupt frames

**Why**: Discovering missing frames after a 12-hour render wastes another render cycle.

#### Scene Complexity Budget
Visual budget meter for scene resources:
- Total polygon count vs configurable budget
- Texture memory estimate vs GPU VRAM
- Object count, light count
- Green/yellow/red status per metric
- Configurable thresholds per studio

**Why**: Artists don't realize a scene is too heavy until render fails with out-of-memory.

### Backlog — Consider Later

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
