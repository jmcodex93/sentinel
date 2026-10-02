# Sentinel — Development Rules

## Project Overview
Sentinel (v1.39.0) is a Cinema 4D quality-control and workflow-automation plugin for professional 3D production (Redshift-first, macOS + Windows, C4D 2026). It runs as a real-time watchdog over the scene and adds render management, versioning, delivery and scene tools.

**Origin.** It began as YS Guardian at Yambo Studio (v1.0, Oct 2025: 5 QC checks, render presets, a few scene tools, the snapshot system). Everything since — the modular engine, 8 of the 13 checks, rulesets/baseline/gates, the SPA panel, Asset Hub, Sentinel Frame/Pin/Variants, Matwire, Material Graph, delivery manifest, installer — was developed by Javier Melgar as Sentinel. Per-release detail: `docs/HISTORY.md`.

**13 QC checks** (declared in `plugin/sentinel/qc/registry.py`; severity FAIL/WARN and on/off per project):
lights organized in a group · viewport/render visibility mismatch · multi-axis keyframes · camera shift · render preset compliance (extra, duplicate and missing studio presets) · assets/textures (missing, absolute, RS node paths) · unused materials · default names · output paths/tokens · takes (camera, `$take`) · FPS/frame range (start 1001, all presets) · cross-aspect safe area (opt-in subjects vs Frame formats) · RS colorspace (Texture Sampler colorspace vs inferred channel).

**Other surfaces:** dockable SPA panel (Overview/QC/Render/Deliver/Tools), Command Palette, Reports (QC, Doctor, Supervisor, Render Validation, Delivery Summary), Asset Hub (inventory, repath, shrink, resolution switch, collect with sealed manifest), Smart Save Version + notes/TODOs, RS AOV tiers, Snapshot Watch (EXR→PNG ACES), post-render validation, project standard (publish / new shot), Sentinel Frame (per-camera multi-format takes with crop and slices), Sentinel Pin (per-object states), Sentinel Variants (structural options), Matwire (RS material from folder), Batch Rename, cleanup and keyframe tools.

## Current state
- **v1.39.0** on `main`. Studio target: **C4D 2026.4.0**. Accepted on Windows 11 + C4D 2026.4.0 (clean profile, Sentinel as the only third-party plugin) after three external rounds, and live-checked on macOS + C4D 2026.304. Candidate ZIPs come from `build_candidate.py` (add the `.sha256` beside them).
- Still open: RenderView's "Save snapshots as EXR" box on the Windows host, a Frame/Hub pass on Windows with the studio's usual plugins loaded, and an `http.handler_failed` console entry seen once on Windows (cause unknown, needs the full text).
- Windows + C4D 2026.3.4 crashes when expanding the Sentinel Frame tag in the Attribute Manager (native null call in `gui.module`, no Python on the stack, cause not isolated) — documented limitation, not pursued.

## Where things are
- `ROADMAP.md` — roadmap and backlog. `docs/HISTORY.md` — what each release did and why.
- `docs/audit/2026-09-05-*.md` — product readiness, beta and GUI acceptance, release prerequisites. `docs/audit/2026-09-24-windows-acceptance.md` — the three Windows rounds, their findings and fixes, crash-report analysis. Read these before claiming a package or a C4D/OS combination is verified.
- `docs/solutions/` — one file per solved problem (YAML frontmatter). `docs/research/` — measured spikes (C4D API behavior with numbers). `docs/design/DESIGN.md` — design tokens and UI rules.
- `RS_AOV_PARAM_IDS.md` — Redshift AOV parameter IDs.

## Core files
- `plugin/sentinel_panel.pyp` — bootstrap only: puts the plugin root on `sys.path`, imports `sentinel/`, holds every `Register*` call and the `__main__` guard.
- `plugin/sentinel/` — engines, mostly pure (no `import c4d`, pytest-able): `qc/` + `checks/` (registry, scoring), `rules.py`, `baseline.py`, `gate.py`, `fixes.py`, `assets.py`, `manifest.py`, `postrender.py`, `imagemeta.py`, `matwire.py`, `matgraph.py`, `renaming.py`, `keyframes.py`, `pins.py`, `variants.py`, `projectstd.py`, `framing.py`, `snapshots.py`, `payload.py` (shared by installer and Doctor). C4D adapters sit beside them (`*_c4d.py`, `textures.py`, `aovs.py`, `multiformat.py`, …).
- `plugin/sentinel/ui/` — `panel_spa.py` (the only panel, a `CUSTOMGUI_HTMLVIEWER`), thin op adapters `*_ops.py`, tags (`frame_tag.py` + `frame_sync.py`, `pin_tag.py`, `variant_tag.py`, shared `tag_support.py`), `dialogs.py` (native form fallbacks if the web server fails), `flows.py`, `scene_tools.py`, `reports_dialog.py`.
- `plugin/sentinel/bridge/` + `webbridge.py` (facade) — localhost HTTP server (ports 8347-8356), main-thread queue, jobs.
- `web/` — SPA source (Vite + React + TS + Tailwind v4). Its build is **committed** in `plugin/web/`; CI checks source/build parity, so rebuild and commit the bundle with every SPA change.
- `plugin/res/` — `.res/.h/.str` for the Frame, Pin and Variants tags; a new description-based plugin needs its own triplet.
- `plugin/c4d/` — scene assets merged by tools (`nulls`, `VibrateNull`, camera rigs) and the fallback template `new.c4d`. They must live inside `plugin/`: `sync.sh` and the installer copy only `plugin/`. The `backup/` folder C4D writes next to them is gitignored and excluded from the payload.
- `plugin/fonts/Inter-Regular.ttf` (slate font, registered for the C4D process only), `plugin/exr_converter_external.py` (EXR→PNG in system Python, only for C4D before 2025.2), `plugin/abc_retime/` (bundled third-party, AXISFX), `plugin/legacy/` (reference only).
- Plugin IDs: 2099069 (base), Frame tag 2099073, Palette 2099075, SPA panel 2099076, MessageData 2099077, Pin tag 2099078, Variants tag 2099079; 2099072 and 2099074 are retired/never shipped. Check `common/constants.py` before picking a new one.

## Development flow
- **Restart C4D** after changing the package or any registered class. Never rely on "Reload Python Plugins": live ObjectData/GeDialog instances keep old module objects (split brain). Reopening the panel only reloads the SPA bundle, not Python.
- Deploy with `sync.sh` (dev) or `install.py` (staged, verified install with backup and `--rollback`). Check which C4D preferences folder is active — C4D creates `_p`/`_x` folders on updates.
- Tests: `python3 -m pytest -q` (a Python that has pytest installed; the suite fakes `c4d` in `tests/conftest.py`), `cd web && npm test && npm run lint && npm run build`. CI (`.github/workflows/verify.yml`) runs pytest on Linux, macOS and **Windows** plus the web job on every PR and push to `main`. Host checks run in a fresh `c4dpy -g_console=true` process with the script's absolute path: `tests/c4d_runner/run_fixtures.py` (frozen oracle), `run_product_checks.py`, `run_beta_checks.py`. `build_candidate.py` packages committed source into `dist/`.
- Live verification goes through the C4D MCP / `c4dpy` on throwaway documents (`KillDocument` in `finally`), never the artist's open scene.

## Development Rules
Scope is one problem at a time, core behavior before refinements, nothing that was not requested (the global rules cover this in detail).

### Files
Edit the existing file rather than creating `foo_v2.py`-style copies. Diagnostic or throwaway scripts don't belong in the repo; test and host-acceptance runners do, under `tests/` (e.g. `tests/c4d_runner/`), because they are how "done" gets proven.

### Problem solving
Find the root cause before fixing — C4D API behavior is often counter-intuitive, so measure it in a live/`c4dpy` session instead of assuming. Durable lessons go to `docs/solutions/` (one file per problem, YAML frontmatter) and, if they are general API facts, one line in the gotchas below; the release narrative goes to `docs/HISTORY.md`, not into this file.

### Code principles
Use only Cinema 4D's bundled Python where possible — artists install by copying a folder, there is no dependency manager. When a feature can't work, degrade gracefully and **say so** (toast, row text or log line): a failure the artist can't see is the class of bug this project keeps removing. Limitations belong in the UI where the artist meets them, not only in docs.

### Goal-driven execution
Before coding, restate the task as a verifiable success criterion:
- **"Add QC check X"** → a scene that violates X reports it, a clean scene doesn't, the check is added to the oracle tuple in `run_fixtures.py` and the oracle is refrozen.
- **"Fix bug Y"** → reproduce Y in C4D first, then show the fix makes the repro pass.
- **"Refactor Z"** → every registered QC check produces the same results before and after (frozen oracle).
- **"Add UI button"** → plugin loads without errors after a C4D restart, the button appears where expected, the click performs the action, and the result is visible.

For multi-step work, write the plan as `step → verify` pairs.

## House patterns
- **Engine/adapter split.** Logic in pure modules; the C4D adapter is thin. New behavior gets pytest coverage on the pure side.
- **SPA ops never open a modal.** A `MessageDialog`/`QuestionDialog` inside the queue drain freezes all of C4D. Each tool has a dialog-free `_<name>_core` returning a status dict; native wrappers keep their dialogs; op tests use `_forbid_dialog`.
- **The server re-derives, never trusts the client.** Mutations recompute plans from the current scene (selection, folder scan, material availability) and ignore client-sent rows. Ops return flat JSON (never C4D objects); read ops build blocks in isolation so one failure doesn't blank the rest.
- **One Cmd+Z per user gesture.** One `StartUndo`/`EndUndo` per batch, opened after early-return checks, closed in `finally`. Verify by counting real undo steps, with a base case that shows the scene changed.
- **Confirmations are server-owned.** Ops return `confirm_required` with `confirm_label`, `confirm_verb` and a per-call `destructive`; the client only renders `lib/confirmBar.ts`. Destructive buttons leave the habitual last slot.
- **UI language.** Accent `#5e6ad2` never marks state; status colors are exclusive to fail/warn/pass. Hard errors inline next to their cause; toasts are success/info/warn only. Cleaners are Tools actions → toast, not QC checks.
- **Identity is location.** Anything persisted across loads (baseline, Pin keys) is keyed by escaped name path + sibling index, never by a C4D id.
- **Rulesets.** `sentinel_rules.json` is discovered from the scene folder up 3 ancestors, nearest wins, validated per key (a bad key is rejected by name, the rest applies). The template scene creates; the ruleset validates.

## Data persistence
### Saved Per Computer/User
`sentinel_settings.json` in the C4D preferences folder (legacy `ys_guardian_settings.json` auto-migrates): artist name, compositor target, multi-part EXR, snapshot directory fallback, `standard_fps` (overridden and locked by a project ruleset), repath presets, `render_notify`, Hub column widths (`hub_spa_ui`). Panel layout is C4D's.

### Per project — `sentinel_rules.json`
FPS, start frame, `slate` (on/off) and `slate_style` (snapshot slate look: `position` below/overlay, `slots` left/center/right as lists of `{token}` items, `badge`, `size`; project-only, unset options keep the defaults, which reproduce the original slate), `approved_presets` (whitelist) and `required_presets` (must exist), default names, safe-area insets, `matwire_suffixes` (additive), `template_scene`, `shot_pattern` (relative, `{shot}` required, Windows-safe segments), `published` (provenance), per-check severity and on/off, `gates_enabled`. Precedence: project > machine > embedded defaults. Resolution cached by (path, mtime) and invalidated with the QC cache.
`template_scene`: a relative path resolves against the folder of the ruleset that declared it. No ruleset value → plugin `new.c4d`. A declared path that is missing → *Reset All* and *New shot* refuse (`project_template_missing` / `template_missing`) and never fall back. Publish Standard writes `sentinel_standard.c4d` + derived keys, merging with manual keys.

### Per scene base (sidecars next to the `.c4d`, shared across `_v###` versions)
`<base>_history.json` (Save Version log, entries `{passed, total, new, accepted}`), `<base>_notes.json`, `<base>_baseline.json` (accepted violations: author + reason; identity = `check_id` + path + sibling index; merge-on-write, Synology conflicted-copy merge, read-only lockout if unreadable), `<base>_render_history.json`. Writes are atomic (tmp + `os.replace`). Collect copies and renames them, plus the effective ruleset, into the delivery.

### Runtime
QC results cached with a 0.5 s cooldown, invalidated by CoreMessage dirty flags. The panel polls a state stamp every 2 s; the stamp includes document dirty, the sum of materials' `GetDirty(DATA)` (repaths don't dirty the document) and the take count (takes aren't in hierarchy or materials).

## C4D / Redshift API gotchas (measured, C4D 2026.3)
**Objects, tags, identity**
- Python wrappers are fresh on every read: `id()` / `is` never match between reads; `==` and `hash()` do. Never key dicts by `id()` of a C4D node (open suspicion: `keyframes.py` dedupes by `id()`).
- `BaseTag` and materials have no `GetGUID()`; use `FindUniqueID(c4d.MAXON_CREATOR_ID)`. GUIDs and unique IDs are regenerated on every document load — never persist them as identity.
- `TagData.Draw` fires only when registered with `TAG_VISIBLE | TAG_EXPRESSION | TAG_IMPLEMENTS_DRAW_FUNCTION`. Gate on `DRAWPASS_OBJECT`, filter with `bd.GetSceneCamera(doc) == op`; the draw thread works on a cloned document, so state it reads must live in the BaseContainer. `SceneHookData` is gone in 2026; for scene-root drawing use `ObjectData.Draw`.
- A tag that may appear more than once needs `TAG_MULTIPLE`, or C4D evicts the second instance.
- C4D restores a plugin tag's name from its registration string on load, and a custom "Name" field fights the native one. Use the native name; mirror it in the container. The Basic tab already has Icon Color (`ID_BASELIST_ICON_COLORIZE_MODE` / `ID_BASELIST_ICON_COLOR`); `MSG_GETCUSTOMICON` never reaches a `TagData`. Look at the Basic tab before building something for a tag.
- Double-click on a tag in the Object Manager arrives as `MSG_EDIT` (21). A right-click reset in the AM does not send `MSG_DESCRIPTION_POSTSETPARAMETER` — detect drift in `Execute` too.
- `InsertObject` and `InsertRenderData` insert at the **start**; use `InsertRenderDataLast` to keep order. `OBJECT_UNDEF` (2) is the default visible state, not "hidden".
- Native lights keep `LIGHT_BRIGHTNESS`/`LIGHT_COLOR`/`LIGHT_TYPE` outside the BaseContainer: `GetData()` misses them; use `GetParameter`/`SetParameter` from the description.
- `TagData.Read/Write` aren't exposed to Python, `HyperFile.WriteObject` doesn't exist and `BaseContainer.SetData` rejects bytes — nodes can't be serialized into a tag. Editable geometry: `isinstance(obj, c4d.PointObject)`. Only `CTRACK_CATEGORY_VALUE` tracks are plain scalar keys.
- Hiding or disabling a child does not remove it from a generator (Cloner still counts it); only taking it out of the hierarchy isolates it.
- Moving a `CCurve` key forward: iterate in reverse, or keys collide with unmoved neighbours.
- Calling a typed getter (`GetFilename`, `GetLink`) on a container entry of another type, or reading `obj[root, field]` on an object that lacks `root`, makes C4D log `CRITICAL: Stop [ge_container.h(523)/(602)]` / `[basecontainer.cpp(353)]` and carry on — hundreds per scan if done over whole containers. Walk ids with `GetIndexId`/`GetType` (`common.helpers.container_ids_of_type`) and check `bc.GetType(root)` before a compound read.
- `GeDialog.Timer` must return None in C4D 2026.304: returning `True` raises `TypeError: Timer expected None, not bool` on every tick (the work before the `return` still runs, so nothing looks broken).

**Undo**
- Test undo with `c4d.CallCommand(12105)`, not `doc.DoUndo()` from a script, and re-find objects afterwards (C4D replaces them).
- Reparenting: `AddUndo(UNDOTYPE_CHANGE, obj)` before the move is enough. BaseLinks survive moving, parking and save+load. A null at identity preserves world transforms.
- RenderData: `UNDOTYPE_DELETE` before each `Remove()` and `UNDOTYPE_NEW` after each insert, inside one bracket, restores the presets and their order but **not which one was active** (C4D leaves the last one active). Add `AddUndo(UNDOTYPE_BITS, previously_active)` before deleting — the active flag is `BIT_ACTIVERENDERDATA` on the node; `UNDOTYPE_ACTIVATE` and `CHANGE_SMALL` on the document don't restore it (measured 2026-10-01).
- An empty `StartUndo`/`EndUndo` bracket creates no step.

**Takes and cameras** (details: `docs/solutions/workflow-issues/2026-07-28-rs-camera-take-overrides.md`, `docs/solutions/logic-errors/2026-07-28-take-override-descid-and-viewport.md`)
- The Redshift camera (`ORSCAMERA` 1057516) has its own parameters: render FOV = sensor `7002` ÷ focal `500` (`7003` is UI-only), shift `7012` is a fraction of the frame; `Ocamera` aperture and film offset are inert on it. Never write base camera parameters (it poisons coupled state) — use per-Take overrides.
- A hand-built `DescID` doesn't match an existing override: use the stored ones from `GetAllOverrideDescID`. `UpdateSceneNode` pushes into the scene even for a non-active take — call it only for the active one. After a take or view change, force `EVENT_FORCEREDRAW` + `DrawViews`.

**Maxon node graphs (Redshift materials)**
- Build the whole graph on a `BaseMaterial` **before** `InsertMaterial` (`GetGraph` works uninserted), then insert + `AddUndo(NEWOBJ)` last — N materials, one undo step. When modifying already-inserted materials, pass `UNDO_MODE.ADD` in `BeginTransaction`'s user data (idiom in `textures.py`), and always call `transaction.Commit()` explicitly — leaving the `with` block rolls back silently.
- After an undo, or between two reads, re-acquire doc → material → graph; old handles lie without erroring. Don't mix handles from different reads.
- `GetConnections(PORT_DIR.OUTPUT, list)` fills the list with `(port, wire)` tuples.
- Writing any string other than SRGB/RAW to `tex0/colorspace` crashes C4D (`EXC_BAD_ACCESS` in `redshift4c4d.xlib`) — whitelist. Colorspace "auto" is a port with no value; there is no readable resolution.
- Always write port values explicitly; node defaults are traps: `uv_tiling=1` is **hex** tiling (use 0); `rsramp` defaults to `smoothknot`; Value nodes and group ports start at zero; `emission_weight` starts at 0 (Standard, write 1.0); OpenPBR `emission_luminance` starts at 0 and is in nits (write 1000); `rsmathinv math_op=20` is `1−x`; `rscolorlayer layer1_blend_mode=4` is Multiply. Standard has `refl_isglossiness`; OpenPBR doesn't.
- `bool(maxon.Bool)` is the truthiness of the object, not the value. Vec2 values need `maxon.Vector(x, y, 0.0)` (tuples/lists fail); an unwritten vec2 reads as `maxon.UnknownDataType` — compare against `maxon.Vector(0, 0, 0)`. Read an asset id as the id, not `str(Pair)`.
- `GraphDescription`: node type `"#<full id>"`, input port `"#<" + id`, group child `parent/child`. It can't share one node between two destinations (no `$ref`) — apply in isolation, then `Connect()` in a transaction. Paths are plain POSIX strings (spaces allowed), never `pathlib.as_uri()`. Availability probe: `FindLatestAsset(...).IsNullValue()`. Title: `net.maxon.node.attribute.title`. Layout with `SetValue(xpos/ypos, maxon.Float)`.
- `MoveToGroup` invalidates the moved handles, created port ids get an `@uuid` suffix (keep the returned handle), and enumeration order ≠ creation order — name each node when you create it; never match by position.
- The open Node Editor doesn't repaint on `EventAdd`.

**Render, Redshift, host**
- Render running: `c4d.CheckIsRunning(CHECKISRUNNING_EXTERNALRENDERING)`. Sync `RenderDocument` works with Redshift; an empty scene returns a black bitmap with `RENDERRESULT_OK` (always check a base case). Clone the render data before rendering so you never write to delivery paths.
- Tokens: `c4d.modules.tokensystem.StringConvertTokens`; RS AOV output path: `REDSHIFT_AOV_FILE_EFFECTIVE_PATH`. Dome HDR: `obj[ROOT_ID, REDSHIFT_FILE_PATH]`.
- RenderView's snapshot folder is `snapshotDir` in `prefs/redshift_rv.cfg`, written only when C4D quits. Each snapshot EXR's header records the frame (`FrameID`), capture time (`capDate`, `YYYY:MM:DD HH:MM:SS`), the RV OCIO view (`ocioView`) and the RV post settings (LUT, colour controls, curve points as `v2f`); `snapshots.read_exr_attributes` parses it with the standard library. The snapshot **pixels never include RV post** (LUT-on and post-off snapshots of one frame were pixel-identical): `rvpost.py` re-applies LUT (`.cube` × strength, after the OCIO view, sampled like a GPU 3D texture: lattice coordinate `v·size − 0.5`) then the master RGB curve (natural spline) — ~0.3 levels mean vs RenderView PNG exports, the same floor as RV's post-off pipeline — and names every other post effect instead of guessing it. A LUT at 0 % strength is a no-op and is skipped. "Save snapshots as EXR" is session-only Qt state and can't be persisted.
- `GetAllAssetsNew` lists the document itself — exclude it. Unsaved scenes resolve textures from `tex/` and `GetGlobalTexturePaths()`. Relinks must preserve the stored path form (`relative:///`, `tex/`, absolute).
- Snapshot EXR → PNG runs in C4D (2025.2+): `doc.GetColorConverter().TransformColors(rows, COLORSPACETRANSFORMATION_OCIO_RENDERING_TO_VIEW)` equals PyOpenColorIO with Redshift's config; `BakeOcioViewToBitmap` returns None for disk-loaded bitmaps and `ColorProfileConvert` render→view is wrong. `GetPixelCnt` returns a falsy value even on success — never test it. Measurements: `docs/research/2026-10-02-snapshot-in-c4d.md`.
- `GeClipMap`: every call (including `SetFont`, `TextWidth`, `GetPixelRGBA`) between `BeginDraw`/`EndDraw`; `GetClone()` the bitmap from `GetBitmap()` before the clip map dies. Fonts resolve only by PostScript name, and an unknown name silently returns another font — compare `GetFontName(desc, GE_FONT_NAME_POSTSCRIPT)`. Copy containers with `c4d.BaseContainer(desc)` (`GetClone` needs flags).
- macOS notifications via `osascript` can be swallowed silently (exit 0, no banner): deliver in C4D (panel toast + `StatusSetText`).

**Windows**
- Paths: don't normalize to `/` and then `os.path.join` (mixed separators) — keep native for local paths shown to the artist; `/` only where a format needs it (manifest, cross-OS render paths). The Windows CI job catches the rest.
- Only C4D older than 2025.2 uses the external EXR converter, which needs a Python 3.12-ish interpreter with OpenEXR/numpy/Pillow (no OpenEXR wheel for 3.14) on PATH or where `_find_system_python` searches. Doctor resolves a bare `python` via PATH. Registering the bundled slate font on Windows (`AddFontResourceExW`, FR_PRIVATE) is unmeasured; Arial is the fallback.

**HTML viewer / SPA**
- `CUSTOMGUI_HTMLVIEWER` is modern WebKit, and Cmd+Z reaches the document. `Close()` + `Open()` on a live viewer crashes C4D — reuse it and navigate with `SetUrl`. `PostWebMessage` push is a no-op, so the SPA polls.
- Unmounting the focused element sends focus nowhere and Cmd+Z stops reaching C4D: call `restoreFocus()` when a dialog closes. Don't use `disabled` for a busy lock (it dims the section); block with `pointerEvents`.
- `hub/job_status` is answered on the HTTP thread, bypassing the main-thread queue, so progress polls work while a job holds the main thread.

## Test harness gotchas
- The fake `c4d` is the usual suspect when a bug reaches live testing with a green suite. Fakes must model real shapes and behaviors (tuples from `GetConnections`, fresh wrappers per read, prepend on insert, rigid `DescID` matching, description-only parameters, undo replay), and must record calls instead of `pass` — a no-op fake makes its line untestable. Fix a broken fake; never bend production code to fit it.
- Prove a test by mutation: break the line and confirm the named test fails. On this Synology Drive volume, mtime granularity lets Python reuse the mutant's `.pyc` — use `PYTHONDONTWRITEBYTECODE=1` and delete `__pycache__`.
- The frozen oracle enumerates checks from a hardcoded tuple in `run_fixtures.py`, not from the registry — a new check is invisible until you add it there and refreeze.
- A probe that returns zero or "OK" must first prove it can measure something (base case).
- Live harness on macOS: launch C4D with `open -a "…/Cinema 4D.app" --stdout <log> --stderr <log>` to capture `CRITICAL` stops and tracebacks (running the binary directly fails licensing; `c4dpy` needs a command-line licence). A `.py` in `<prefs>/library/scripts/` registers as a command at startup (find its id with the MCP `list_plugins`, run it with `call_command`); its `print` goes to C4D's console, so write results to a file. Remove probes afterwards.
- Synthetic background clicks reach the SPA panel (web view) but not native C4D controls (Attribute Manager buttons): those need full-screen input.

## Known limitations
- No API to redirect Redshift's snapshot folder or trigger a snapshot; the EXR toggle must be re-ticked per RenderView session.
- A docked C4D panel doesn't shrink to its content (framework limitation).
- The viewport tints rather than hides out-of-frame areas; the RenderView is the exact preview.
- Windows + C4D 2026.3.4: expanding the Sentinel Frame tag in the Attribute Manager can crash C4D (see Current state); the studio runs 2026.4.0, where it doesn't.
- Promise nothing that needs Redshift API access we don't have. Installation changes go through `install.py`/`sync.sh`, not new setup scripts.

## External references (C4D / Redshift SDK)
Consult these before inventing patterns. Local clones live in the sibling folder `../11 C4D DEV/` (update with `git pull`):
- `Cinema-4D-Python-API-Examples/` — Maxon's official examples (Apache-2.0): plugin hooks, GUI, tokens, node graphs, 2026 examples.
- `renderEngine/` (DunHouGo) — Redshift AOV/material/scene patterns. **No license**: learn from it, don't copy code without permission.
- https://developers.maxon.net/docs/py — official manuals and API index.

Undocumented manager IDs (from `FindShortcutAssign`; verify live before relying on them):
```python
MATERIAL_MANAGER = 150041;  OBJECT_MANAGER = 100004709;  LAYER_MANAGER = 100004704
PICTURE_VIEWER = 430000700;  ATTRIBUTE_MANAGER = 1000468;  NODEEDITOR_MANAGER = 465002211
TAKE_MANAGER = 431000053;  TIMELINE_MANAGER = 465001516;  XPRESSO_MANAGER = 1001148
RENDER_QUEUE = 465003500;  RENDER_SETTING = 12161;  ASSET_BROWSER = 1054225
PROJECT_ASSET_INSPECTOR = 1029486;  CONSOLE = 10214;  VIEWPORT = 59000
ARNOLD_IPR = 1032195;  ARNOLD_SHADER_NETWORK = 1033989;  CORONA_NODE_MANAGER = 1040908
```
Undo command for tests: `12105`.
