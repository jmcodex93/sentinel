# -*- coding: utf-8 -*-
"""Plugin-wide constants with no UI widget IDs."""

from sentinel import PLUGIN_NAME, PLUGIN_VERSION

# Plugin ID - change if ID collision
PLUGIN_ID = 2099069

# Secondary plugin: SafeAreaOverlayObject (ObjectData) for the
# cross-aspect safe-area viewport overlay (QC #12 visualization,
# v1.5.6).
#
# Investigation history:
#   - v1.5.5: prototyped via SceneHookData -> API removed in C4D 2026
#   - v1.5.6 probe round 1: TagData.Draw -> registers cleanly but Draw
#     is NEVER invoked by C4D 2026's viewport pipeline (only Init +
#     Execute fire). Only the tag's built-in handle is drawn.
#   - v1.5.6 probe round 2: ObjectData.Draw -> fires in DRAWPASS_OBJECT
#     even without selection. Screen-space drawing via
#     `bd.SetMatrix_Screen()` + `bd.DrawLine` + `bd.DrawHUDText` all
#     work as expected. `bd.GetSafeFrame()` returns the rendered
#     frame's letterboxed rectangle inside the viewport -- exactly
#     what we need to position our format overlay correctly.
#
# Architecture: one ObjectData marker object per document (auto-created
# at scene root when the panel toggle is enabled). Reads from the
# module-level `_overlay_state` singleton so the panel can toggle it
# without finding/modifying the object.
SAFE_AREA_OVERLAY_PLUGIN_ID = 2099072  # dev-range; replace with
                                       # Maxon-allocated for production

# Preset names - normalized to lowercase with underscores
# The system accepts both "pre_render" and "pre-render" (case-insensitive)
PRESETS = ["previz", "pre_render", "render", "stills"]

# Performance settings for watcher
MAX_OBJECTS_PER_CHECK = 1000  # Process in chunks
CACHE_DURATION = 2.0  # Cache results for 2 seconds (optimized for performance)
CHECK_COOLDOWN = 0.5  # Minimum time between checks

# Global settings file for artist name (Sentinel)
SETTINGS_FILE = "sentinel_settings.json"
LEGACY_SETTINGS_FILE = "ys_guardian_settings.json"  # pre-rebrand, auto-migrated on first load
