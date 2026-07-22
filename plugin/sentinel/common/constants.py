# -*- coding: utf-8 -*-
"""Plugin-wide constants with no UI widget IDs."""

# Plugin ID - change if ID collision
PLUGIN_ID = 2099069

# (2099072 was the retired v1.5.6 Safe-Area Overlay ObjectData id — freed in
# v1.8.0 when the Sentinel Frame per-camera tag took over viewport drawing.)

# Fase 6.0 (Panel SPA host) — grepped the 2099xxx range before picking this:
# PLUGIN_ID=2099069, SENTINEL_FRAME_TAG_PLUGIN_ID=2099073 (frame_tag.py),
# SENTINEL_PALETTE_PLUGIN_ID=2099075 (sentinel_panel.pyp), 2099072 retired.
# 2099074 is documented in ROADMAP.md as the never-shipped v1.6.0
# CameraFrameDrawer prototype (superseded by Sentinel Frame, not registered
# anywhere in the current codebase) — skipped anyway to avoid confusion with
# that history rather than reclaim it. 2099076 is the next id with no
# reference anywhere in the repo — free.
SENTINEL_PANEL_SPA_PLUGIN_ID = 2099076

# Preset names - normalized to lowercase with underscores
# The system accepts both "pre_render" and "pre-render" (case-insensitive)
PRESETS = ["previz", "pre_render", "render", "stills"]

# Tokens (normalized form) that mark a preset as "stills" for QC #11 fps_range,
# so descriptive lookdev/beauty preset names (e.g. "RS-LookDev 2026") count as
# stills instead of being flagged as an invalid animation range. Ruleset-configurable
# via sentinel_rules.json "stills_presets".
STILLS_PRESET_TOKENS = ["stills", "lookdev", "look_dev", "beauty"]

DEFAULT_OBJECT_NAMES = (
    "null",
    "cube",
    "sphere",
    "cylinder",
    "cone",
    "plane",
    "disc",
    "torus",
    "capsule",
    "oil tank",
    "platonic",
    "pyramid",
    "gem",
    "tube",
    "landscape",
    "figure",
    "spline",
    "circle",
    "rectangle",
    "n-side",
    "arc",
    "helix",
    "sweep",
    "extrude",
    "lathe",
    "loft",
    "boole",
    "symmetry",
    "instance",
    "cloner",
    "fracture",
    "voronoi fracture",
    "matrix",
    "mograph",
    "camera",
    "light",
    "floor",
    "sky",
    "environment",
    "physical sky",
)

# C4D core message id for a take-change event (empirically observed; not in the SDK symbols).
EVMSG_TAKECHANGED = 431000159

# Performance settings for watcher
MAX_OBJECTS_PER_CHECK = 1000  # Process in chunks
CACHE_DURATION = 2.0  # Cache results for 2 seconds (optimized for performance)
CHECK_COOLDOWN = 0.5  # Minimum time between checks

# Global settings file for artist name (Sentinel)
SETTINGS_FILE = "sentinel_settings.json"
LEGACY_SETTINGS_FILE = "ys_guardian_settings.json"  # pre-rebrand, auto-migrated on first load
