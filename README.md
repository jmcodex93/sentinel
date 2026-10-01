# Sentinel v1.39.0

Quality control, render management and delivery tools for Cinema 4D + Redshift production.

![Sentinel Interface](https://github.com/user-attachments/assets/847c6930-f54c-4f7f-86e2-5308f9e0e7bd)

> Sentinel began as [YS Guardian](https://github.com/yamb0x/ys-guardian), built at Yambo Studio (v1.0: 5 QC checks, render presets, scene tools, snapshot conversion). It has since grown into a much larger tool — modular QC engine, project rulesets, delivery pipeline, web-based panel, Sentinel Frame/Pin/Variants, material tools — developed and maintained by Javier Melgar.

**Compatibility target:** Cinema 4D 2024+ with Redshift, macOS and Windows. Recorded evidence: C4D 2026.4.0 on Windows 11 (accepted), C4D 2026.3 on macOS (live-checked) and C4D 2025 on Windows (Frame check passed). Known issue: C4D 2026.3.4 on one Windows host with other plugins loaded closed when the Sentinel Frame tag was expanded; 2026.4.0 does not. Release criteria and host results: [Windows acceptance](docs/audit/2026-09-24-windows-acceptance.md), [product readiness](docs/audit/2026-09-05-product-readiness.md), [beta acceptance](docs/audit/2026-09-05-beta-acceptance.md), [GUI acceptance](docs/audit/2026-09-05-gui-acceptance.md).

## What it does

### Quality checks
Thirteen checks run as the scene changes. Each one can be selected, fixed where a safe fix exists, or accepted into a per-scene baseline with author and reason.

| # | Check | Actions |
|---|---|---|
| 1 | Lights organized in a lights group | Select · Fix |
| 2 | Viewport/render visibility mismatch | Select |
| 3 | Multi-axis keyframes | Select |
| 4 | Camera shift not zero | Select · Fix |
| 5 | Render presets: extra, duplicate or missing studio presets | Info |
| 6 | Assets: missing textures, absolute paths, RS node paths | Info |
| 7 | Unused materials | Select · Fix |
| 8 | Default object names | Select |
| 9 | Output paths and tokens | Info |
| 10 | Takes: camera per take, `$take` in outputs | Info |
| 11 | FPS and frame range (start 1001, all presets aligned) | Info · Fix |
| 12 | Cross-aspect safe area for marked subjects | Select · Info |
| 13 | Redshift texture colorspace vs channel (the ACEScg trap) | Select · Info · Fix |

A project can pin its own standard in `sentinel_rules.json` (FPS, start frame, required and approved presets, default names, safe-area insets, per-check severity and on/off). Sentinel finds it in the scene folder or up to three parent folders, so a whole team validates against the same rules. Optional quality gates stop Save Version and Collect on failing checks.

### Panel
A dockable panel with Overview, QC, Render, Deliver and Tools, plus a Command Palette for every action. Destructive actions ask first and say what will be lost; everything else is one Cmd+Z.

### Render
- **Presets:** the scene's real preset names, with non-standard ones marked. *Reset All* rebuilds them from the studio template (undoable, and the confirmation names what it deletes).
- **Sentinel Frame:** a camera tag for multi-format delivery (16:9, 9:16, 1:1, 4:5, 21:9 and a custom ratio). Viewport guides and safe zones, one take per format with a true crop, per-format framing nudge, optional slices for ultra-wide deliveries. Takes and outputs stay in sync automatically.
- **Redshift AOVs:** Essentials (11) and Production (17+) tiers per compositor (Nuke or After Effects), Light Groups on the Beauty AOV, Multi-Part EXR or direct output.
- **Snapshots:** saves RenderView EXR snapshots as PNG with an ACES display transform. Snapshot Watch converts each new snapshot automatically.
- **Post-render validation:** checks rendered frames on disk: sequence gaps, empty or truncated files, size outliers, missing AOVs, stale frames from an earlier session.

### Deliver
- **Smart Save Version:** `scene_v###.c4d` with a required comment, review status in the filename (`_TR`, `_CR`, `_FINAL`, custom), QC score and scene stats in a history sidecar, and a recent-versions list.
- **Scene notes and TODOs**, shared by every version of the scene.
- **Asset Hub:** every file the scene uses, with status, size, resolution and estimated VRAM. Bulk find/replace, search a folder for missing files, make paths relative, shrink textures to 4K/2K/1K, switch between resolution variants, copy external files into the project. All of it undoable.
- **Collect:** pre-flight QC, native asset collection, re-scan of the collected copy, and a sealed `sentinel_manifest.json` the receiver can verify on their disk. Optional ZIP.
- **Project standard:** a supervisor publishes a clean template scene and ruleset from a shot that passes QC; artists start new shots from it.

### Tools
- **Sentinel Pin:** save an object's state (parameters, transform, name, animation) and restore it later. Each restore first saves what you have now.
- **Sentinel Variants:** keep several versions of a branch (modeling, animation, lighting) and switch between them, or render them all.
- **RS Material from Folder:** builds Redshift materials (OpenPBR or Standard) from a texture folder with the right colorspaces and a shared UV control.
- **Clean Dead Nodes**, Delete Empty Nulls, Clean Material Tags.
- **Batch Rename** for objects and materials, with tokens and a live preview.
- **Keyframe offset and stagger.**
- Scene tools: Hierarchy template, Hierarchy → Layers, Solo Layers, Drop to Floor, Vibrate Null, camera rigs, ABC Retime tag.
- A notification when a long render finishes.

## Installation

### Requirements
- Cinema 4D 2024 or later, with Redshift for AOVs, snapshots and material tools
- macOS or Windows
- For snapshot conversion: a system Python 3 with `pip3 install Pillow numpy OpenEXR`

### Install with `install.py`
Close Cinema 4D first.

```bash
python3 install.py            # interactive: pick one, several or all detected C4D installs
python3 install.py --list     # list detected installs
python3 install.py --all      # install into every detected C4D
python3 install.py --target "/path/to/Maxon Cinema 4D 2026_XXXX/plugins"
python3 install.py --target "/path/to/.../plugins" --rollback latest
```

The installer verifies the complete payload before activating it and keeps the previous version under `Sentinel Backups/` in the preferences folder, so `--rollback` can restore it. Details in [INSTALLATION_README.md](INSTALLATION_README.md). Restart Cinema 4D afterwards.

### Manual install
Close Cinema 4D, copy the contents of `plugin/` to `<plugins>/Sentinel/`, restart. Keep the whole payload together: `sentinel_panel.pyp` only registers the plugins, the code lives in `sentinel/`. A manual copy skips the installer's verification and backup.

### Redshift snapshots
In RenderView → Preferences → Snapshots, enable **Save snapshots as EXR**. Redshift doesn't remember this setting between RenderView sessions, so tick it each session. Sentinel reads the snapshot folder from Redshift's own preferences, which Redshift writes when Cinema 4D quits. You can set a fallback folder in Settings.

## Quick start
1. Open **Extensions → Sentinel Panel (SPA)** and dock it.
2. In Settings, enter your artist name (saved per computer; Snapshot Watch requires it).
3. Run **Doctor** from the panel rail to check the installation, Redshift and the external Python.
4. Work normally: the QC score updates as the scene changes. Use Select, Fix or Accept on each check.

Stills are saved as `<scene>_snap_###.png` under `output/stills/<artist>/<YYMMDD>/`, inside the folder that contains the scene's folder.

## Troubleshooting
- **Checks look stale:** they run when the scene changes; closing and reopening the panel forces a fresh read.
- **Snapshot conversion fails:** confirm RenderView saves EXR (not `.rssnap2`), install the Python packages above, and run Doctor.
- **AOVs don't apply:** Redshift must be the active renderer; check the compositor target.
- **Hierarchy → Layers:** organize objects under uniquely named top-level nulls.
- **Presets:** names match case-insensitively (`pre_render`, `Pre-Render`, `Pre Render`). *Reset All* rebuilds them from the template.
- **Collect:** the scene must be saved first. Missing assets are recorded in the manifest, not blocked.
- **ABC Retime:** select a supported cache (Alembic object/tag, Point Cache, MoGraph Cache, X-Particles Cache) and make sure the tag isn't already there.
- **After updating Sentinel:** fully restart Cinema 4D. *Reload Python Plugins* is not enough.

## License
Free for personal and commercial use. Redistribution not permitted without permission.
Originally developed as YS Guardian at Yambo Studio. Sentinel is the continued maintenance and extension of that work by Javier Melgar.

## Support
Report bugs from the panel's Help menu or on the [Issues page](https://github.com/jmcodex93/sentinel/issues/new). Include your Cinema 4D and Redshift versions, the steps to reproduce, and the diagnostic block from Doctor.

## Thanks
- **Yambo Studio**, for YS Guardian, the foundation Sentinel grew from.
- **Riccardo Bottoni** (@riccardobottoni), camera rigs.
- **Austin Marola** (@zonedog) and **@axisfx**, [ABC Retime](https://github.com/axisfx2/abc_retime).
- The original **Drop to Floor** creators, and **@thodos** for early tips.

## Links
[Repository](https://github.com/jmcodex93/sentinel) · [Roadmap](ROADMAP.md) · [History](docs/HISTORY.md) · [Development guide](CLAUDE.md) · [Original YS Guardian](https://github.com/yamb0x/ys-guardian)
