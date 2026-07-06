# -*- coding: utf-8 -*-
"""Plugin-wide constants with no UI widget IDs."""

# Plugin ID - change if ID collision
PLUGIN_ID = 2099069

# (2099072 was the retired v1.5.6 Safe-Area Overlay ObjectData id — freed in
# v1.8.0 when the Sentinel Frame per-camera tag took over viewport drawing.)

# Preset names - normalized to lowercase with underscores
# The system accepts both "pre_render" and "pre-render" (case-insensitive)
PRESETS = ["previz", "pre_render", "render", "stills"]

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

# Performance settings for watcher
MAX_OBJECTS_PER_CHECK = 1000  # Process in chunks
CACHE_DURATION = 2.0  # Cache results for 2 seconds (optimized for performance)
CHECK_COOLDOWN = 0.5  # Minimum time between checks

# Global settings file for artist name (Sentinel)
SETTINGS_FILE = "sentinel_settings.json"
LEGACY_SETTINGS_FILE = "ys_guardian_settings.json"  # pre-rebrand, auto-migrated on first load
