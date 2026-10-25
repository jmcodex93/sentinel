# -*- coding: utf-8 -*-
"""Plugin-wide constants with no UI widget IDs."""

# Plugin IDs — registered on Plugin Café (account jmelpri) on 2026-10-25, one
# per registered plugin. Never pick an ID by hand: generate a new one at
# https://plugincafe.maxon.net/c4dpluginid_cp and add it here. They replace
# the unregistered 2099xxx range used up to v1.40.1 (scenes saved with the
# old tag IDs no longer load those tags; there were no production scenes).
SENTINEL_PANEL_SPA_PLUGIN_ID = 1072205     # CommandData: the dockable panel
SENTINEL_PALETTE_PLUGIN_ID = 1072206       # CommandData: Command Palette
SENTINEL_FRAME_TAG_PLUGIN_ID = 1072207     # TagData: Sentinel Frame
SENTINEL_FRAME_SYNC_PLUGIN_ID = 1072208    # MessageData: Frame auto-sync pump
SENTINEL_PIN_TAG_PLUGIN_ID = 1072209       # TagData: Sentinel Pin
SENTINEL_VARIANT_TAG_PLUGIN_ID = 1072210   # TagData: Sentinel Variants

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
