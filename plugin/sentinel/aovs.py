# -*- coding: utf-8 -*-
"""Redshift AOV tier management."""

import c4d

from sentinel.common.cache import check_cache
from sentinel.common.constants import MAX_OBJECTS_PER_CHECK
from sentinel.common.helpers import _iter_objs, _safe_name, safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.checks.scene import _is_light_obj

try:
    import redshift
    REDSHIFT_AVAILABLE = True
except ImportError:
    REDSHIFT_AVAILABLE = False

# ---------------- RS AOV management ----------------
# Per-AOV option IDs (no named constants in c4d module — see RS_AOV_PARAM_IDS.md)
_DEPTH_FILTER_TYPE = 1004      # 0=Full, 1=Min, 2=Max, 3=Center Sample
_DEPTH_MODE = 1019             # 0=Z, 1=Z Normalized, 2=Z Normalized Inverted
_DEPTH_CAMERA_NEARFAR = 1020   # 0=off, 1=on
_MV_RAW_VECTORS = 1008         # 0=off, 1=on
_MV_NO_CLAMP = 1009            # 0=off, 1=on
_MV_MAX_MOTION = 1010          # pixels (int)
_MV_FILTERING = 1013           # 0=off, 1=on
_APPLY_COLOR_PROCESSING = 1006 # 0=off, 1=on (default ON — should be OFF for compositing)

# AOV definitions: (const_candidates, bit_depth, data_type, compression)
_AOV_DEFS = {
    # Beauty reference
    "Beauty":               (["REDSHIFT_AOV_TYPE_BEAUTY", "REDSHIFT_AOV_TYPE_MAIN"], 16, "rgba", "dwab"),
    # Beauty rebuild components (RGBA, DWAB, 16-bit half)
    "Diffuse Lighting":     (["REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING"], 16, "rgba", "dwab"),
    "GI":                   (["REDSHIFT_AOV_TYPE_GI", "REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION", "REDSHIFT_AOV_TYPE_INDIRECT_DIFFUSE"], 16, "rgba", "dwab"),
    "Specular Lighting":    (["REDSHIFT_AOV_TYPE_SPECULAR_LIGHTING"], 16, "rgba", "dwab"),
    "Reflections":          (["REDSHIFT_AOV_TYPE_REFLECTIONS"], 16, "rgba", "dwab"),
    "SSS":                  (["REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER", "REDSHIFT_AOV_TYPE_SSS"], 16, "rgba", "dwab"),
    "Refractions":          (["REDSHIFT_AOV_TYPE_REFRACTIONS"], 16, "rgba", "dwab"),
    "Emission":             (["REDSHIFT_AOV_TYPE_EMISSION"], 16, "rgba", "dwab"),
    "Caustics":             (["REDSHIFT_AOV_TYPE_CAUSTICS"], 16, "rgba", "dwab"),
    "Volume Lighting":      (["REDSHIFT_AOV_TYPE_VOLUME_LIGHTING"], 16, "rgba", "dwab"),
    "Volume Fog Tint":      (["REDSHIFT_AOV_TYPE_VOLUME_FOG_TINT"], 16, "rgba", "dwab"),
    "Volume Fog Emission":  (["REDSHIFT_AOV_TYPE_VOLUME_FOG_EMISSION"], 16, "rgba", "dwab"),
    "Shadows":              (["REDSHIFT_AOV_TYPE_SHADOWS"], 16, "rgba", "dwab"),
    # Filter/Raw passes (RGBA, DWAB, 16-bit half)
    "Diffuse Filter":       (["REDSHIFT_AOV_TYPE_DIFFUSE_FILTER"], 16, "rgba", "dwab"),
    "Reflection Filter":    (["REDSHIFT_AOV_TYPE_REFLECTION_FILTER", "REDSHIFT_AOV_TYPE_REFLECTIONS_FILTER", "REDSHIFT_AOV_TYPE_REFL_FILTER"], 16, "rgba", "dwab"),
    "Diffuse Lighting Raw": (["REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING_RAW"], 16, "rgba", "dwab"),
    "Refractions Raw":      (["REDSHIFT_AOV_TYPE_REFRACTIONS_RAW", "REDSHIFT_AOV_TYPE_REFRACTION_RAW"], 16, "rgba", "dwab"),
    "Ambient Occlusion":    (["REDSHIFT_AOV_TYPE_AMBIENT_OCCLUSION"], 16, "rgba", "dwab"),
    # Utility passes (RGB, PIZ lossless, 32-bit float for precision)
    "Depth":                (["REDSHIFT_AOV_TYPE_DEPTH", "REDSHIFT_AOV_TYPE_Z_DEPTH"], 32, "rgb", "piz"),
    "Motion Vectors":       (["REDSHIFT_AOV_TYPE_MOTION_VECTORS"], 32, "rgb", "piz"),
    "Cryptomatte":          (["REDSHIFT_AOV_TYPE_CRYPTOMATTE"], 32, "rgb", "piz"),
    "World Position":       (["REDSHIFT_AOV_TYPE_WORLD_POSITION"], 32, "rgb", "piz"),
    # Utility passes (RGB, PIZ lossless, 16-bit half)
    "Normals":              (["REDSHIFT_AOV_TYPE_NORMALS"], 16, "rgb", "piz"),
    "Bump Normals":         (["REDSHIFT_AOV_TYPE_BUMP_NORMALS"], 16, "rgb", "piz"),
}

# AOVs that have the Apply Color Processing option (lighting/shading components)
# These should have it OFF for compositing (linear data for correct beauty rebuild)

# Compression lookup (defined once, not per-iteration)
_COMP_MAP = {
    "default": "REDSHIFT_AOV_FILE_COMPRESSION_DEFAULT",
    "zip": "REDSHIFT_AOV_FILE_COMPRESSION_EXR_ZIP",
    "zips": "REDSHIFT_AOV_FILE_COMPRESSION_EXR_ZIPS",
    "piz": "REDSHIFT_AOV_FILE_COMPRESSION_EXR_PIZ",
    "dwaa": "REDSHIFT_AOV_FILE_COMPRESSION_EXR_DWAA",
    "dwab": "REDSHIFT_AOV_FILE_COMPRESSION_EXR_DWAB",
}

# Tier definitions — names must match _AOV_DEFS keys
# Tier 1: Beauty rebuild + essential utility
# Beauty = Diffuse + GI + Specular + Reflections + SSS + Refractions + Emission (+ Caustics if enabled)
AOV_TIER_ESSENTIALS = [
    "Beauty",
    "Diffuse Lighting", "GI", "Specular Lighting", "Reflections",
    "SSS", "Refractions", "Emission",
    "Depth", "Motion Vectors", "Cryptomatte",
]

# Tier 2: Full compositing control — relighting, volumes, raw passes
# Volume AOVs added conditionally when RS Environment or RS Volume objects exist
AOV_TIER_PRODUCTION = AOV_TIER_ESSENTIALS + [
    "Diffuse Filter", "World Position", "Normals", "Ambient Occlusion",
    "Reflection Filter", "Refractions Raw",
]

def _get_rs_videopost(doc):
    if not REDSHIFT_AVAILABLE:
        return None
    try:
        rd = doc.GetActiveRenderData()
        return redshift.FindAddVideoPost(rd, redshift.VPrsrenderer) if rd else None
    except Exception:
        return None

RS_CAUSTICS_ENABLED_ID = 9013  # "Enabled" checkbox in RS Caustics tab

RS_ENVIRONMENT_ID = 1036757   # Redshift Environment object
RS_VOLUME_ID = 1038655        # Redshift Volume object

def _has_volumes_in_scene(doc):
    """Check if scene contains RS Environment or RS Volume objects"""
    first = doc.GetFirstObject()
    if not first:
        return False
    for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
        if not obj:
            continue
        obj_type = obj.GetType()
        if obj_type == RS_ENVIRONMENT_ID or obj_type == RS_VOLUME_ID:
            return True
    return False

def _are_caustics_enabled(doc):
    """Check if caustics are enabled in RS render settings"""
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return False
    try:
        return vprs[RS_CAUSTICS_ENABLED_ID] == 1
    except Exception:
        return False

def _scan_light_groups(doc):
    """Scan scene lights and return (groups_dict, ungrouped_list)."""
    groups = {}
    ungrouped = []
    first = doc.GetFirstObject()
    if first:
        for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not obj or not _is_light_obj(obj):
                continue
            light_name = _safe_name(obj)
            group = ""
            try:
                group = obj[c4d.REDSHIFT_LIGHT_LIGHT_GROUP] or ""
            except Exception:
                pass
            if not group:
                for tag in obj.GetTags():
                    try:
                        g = tag[c4d.REDSHIFT_LIGHT_GROUP_LIGHT_GROUP]
                        if g:
                            group = g
                            break
                    except Exception:
                        pass
            if group:
                groups.setdefault(group, []).append(light_name)
            else:
                ungrouped.append(light_name)
    return groups, ungrouped


def _is_lg_active_on_beauty(doc):
    """Check if All Light Groups is active on Beauty AOV."""
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return False
    try:
        for aov in redshift.RendererGetAOVs(vprs):
            if aov.GetParameter(c4d.REDSHIFT_AOV_NAME) == "Beauty":
                return bool(aov.GetParameter(c4d.REDSHIFT_AOV_LIGHTGROUP_ALL))
    except Exception:
        pass
    return False


def _resolve_aov_type(name):
    """Resolve AOV name to c4d constant value"""
    aov_def = _AOV_DEFS.get(name)
    if not aov_def:
        return None
    candidates = aov_def[0]
    for const_name in candidates:
        val = getattr(c4d, const_name, None)
        if val is not None:
            return val
    return None

def get_rs_aovs(doc):
    """Get list of current RS AOVs"""
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return None

    aovs = []
    try:
        for aov in redshift.RendererGetAOVs(vprs):
            try:
                aovs.append({
                    "name": aov.GetParameter(c4d.REDSHIFT_AOV_NAME) or "",
                    "type": aov.GetParameter(c4d.REDSHIFT_AOV_TYPE),
                    "enabled": aov.GetParameter(c4d.REDSHIFT_AOV_ENABLED),
                    "effective_path": aov.GetParameter(c4d.REDSHIFT_AOV_FILE_EFFECTIVE_PATH) or "",
                    "file_format": aov.GetParameter(c4d.REDSHIFT_AOV_FILE_FORMAT),
                    "direct_enabled": bool(aov.GetParameter(c4d.REDSHIFT_AOV_FILE_ENABLED)),
                    "multipass_enabled": bool(aov.GetParameter(c4d.REDSHIFT_AOV_MULTIPASS_ENABLED)),
                })
            except Exception:
                pass
    except Exception as e:
        safe_print(f"Error reading RS AOVs: {e}")
    return aovs


def get_aov_multipart(doc):
    """Read Redshift's effective AOV Multi-Part flag from the live videopost."""
    vprs = _get_rs_videopost(doc)
    if not vprs:
        return False
    try:
        return bool(vprs[c4d.REDSHIFT_RENDERER_AOV_MULTIPART])
    except Exception:
        return False

def check_rs_aovs(doc, tier=None):
    """Check AOVs against a tier. tier=None uses Essentials."""
    tier_list = _build_tier_list(doc, tier or AOV_TIER_ESSENTIALS)
    result = {"available": REDSHIFT_AVAILABLE, "aovs": [], "missing": [], "tier": tier_list}

    aovs = get_rs_aovs(doc)
    if aovs is None:
        return result

    result["aovs"] = aovs
    active_names = {a["name"] for a in aovs if a.get("enabled", True)}
    result["missing"] = [name for name in tier_list if name not in active_names]
    return result

def _build_tier_list(doc, tier_list):
    """Build effective tier list, adding conditional AOVs based on scene content"""
    effective = list(tier_list)
    if "Caustics" not in effective and _are_caustics_enabled(doc):
        effective.append("Caustics")
        safe_print("  Caustics enabled - adding AOV")
    if "Volume Lighting" not in effective and _has_volumes_in_scene(doc):
        effective.extend(["Volume Lighting", "Volume Fog Tint", "Volume Fog Emission"])
        safe_print("  Volumetric objects found - adding Volume AOVs")
    return effective

def force_aov_tier(doc, tier_list):
    """Add missing AOVs from a tier to RS render settings, with proper bit depth"""
    if not REDSHIFT_AVAILABLE:
        return 0, "Redshift module not available"

    vprs = _get_rs_videopost(doc)
    if not vprs:
        return 0, "Redshift VideoPost not found"

    # Enable AOV system + configure output mode
    use_multipart = bool(int(GlobalSettings.get('aov_multipart', 1)))
    try:
        vprs[c4d.REDSHIFT_RENDERER_AOV_GLOBAL_MODE] = c4d.REDSHIFT_RENDERER_AOV_GLOBAL_MODE_ENABLE
        vprs[c4d.REDSHIFT_RENDERER_AOV_MULTIPART] = use_multipart
        if use_multipart:
            # Multi-Part forces uniform settings — 32-bit for Depth/MV precision
            vprs[c4d.REDSHIFT_RENDERER_AOV_FILE_BIT_DEPTH] = c4d.REDSHIFT_RENDERER_AOV_FILE_BIT_DEPTH_FLOAT32
            vprs[c4d.REDSHIFT_RENDERER_AOV_FILE_COMPRESSION] = c4d.REDSHIFT_RENDERER_AOV_FILE_COMPRESSION_EXR_DWAB
            vprs[c4d.REDSHIFT_RENDERER_AOV_FILE_EXR_DWA_COMPRESSION] = 45.0
            safe_print("  Multi-Part EXR: ON (32-bit Float, DWAB 45)")
        else:
            safe_print("  Multi-Part EXR: OFF (per-AOV Direct Output)")
    except Exception as e:
        safe_print(f"  Warning: Could not set AOV global settings: {e}")

    tier_list = _build_tier_list(doc, tier_list)

    try:
        existing_aovs = redshift.RendererGetAOVs(vprs)
        existing_names = {aov.GetParameter(c4d.REDSHIFT_AOV_NAME) or ""
                          for aov in existing_aovs}

        comp_target = int(GlobalSettings.get('comp_target', 0))  # 0=Nuke, 1=AE
        added = 0
        new_aovs = list(existing_aovs)

        for name in tier_list:
            if name in existing_names:
                continue

            aov_type = _resolve_aov_type(name)
            if aov_type is None:
                safe_print(f"  Skipped AOV '{name}': constant not found")
                continue

            _, bit_depth, data_type, compression = _AOV_DEFS[name]

            try:
                new_aov = redshift.RSAOV()
                new_aov.SetParameter(c4d.REDSHIFT_AOV_TYPE, aov_type)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_NAME, name)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_ENABLED, True)

                # Output mode: Direct ON, Multi-Pass OFF
                new_aov.SetParameter(c4d.REDSHIFT_AOV_MULTIPASS_ENABLED, False)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_FILE_ENABLED, True)

                # Direct Output: bit depth, data type, compression
                new_aov.SetParameter(c4d.REDSHIFT_AOV_FILE_BIT_DEPTH,
                    c4d.REDSHIFT_AOV_FILE_BIT_DEPTH_FLOAT32 if bit_depth == 32
                    else c4d.REDSHIFT_AOV_FILE_BIT_DEPTH_FLOAT16)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_FILE_DATA_TYPE,
                    c4d.REDSHIFT_AOV_FILE_DATATYPE_RGBA if data_type == "rgba"
                    else c4d.REDSHIFT_AOV_FILE_DATATYPE_RGB)
                comp_const = getattr(c4d, _COMP_MAP.get(compression, "REDSHIFT_AOV_FILE_COMPRESSION_DEFAULT"),
                                     c4d.REDSHIFT_AOV_FILE_COMPRESSION_DEFAULT)
                new_aov.SetParameter(c4d.REDSHIFT_AOV_FILE_COMPRESSION, comp_const)
                if compression in ("dwab", "dwaa"):
                    new_aov.SetParameter(c4d.REDSHIFT_AOV_FILE_EXR_DWA_COMPRESSION, 45.0)

                # Compositor-specific settings for utility AOVs
                if name == "Depth":
                    new_aov.SetParameter(_DEPTH_FILTER_TYPE, 3)  # Center Sample
                    if comp_target == 0:  # Nuke
                        new_aov.SetParameter(_DEPTH_MODE, 0)          # Z raw
                        new_aov.SetParameter(_DEPTH_CAMERA_NEARFAR, 0) # OFF
                    else:  # After Effects
                        new_aov.SetParameter(_DEPTH_MODE, 2)          # Z Normalized Inverted
                        new_aov.SetParameter(_DEPTH_CAMERA_NEARFAR, 1) # ON
                elif name == "Motion Vectors":
                    new_aov.SetParameter(_MV_FILTERING, 0)  # OFF
                    if comp_target == 0:  # Nuke
                        new_aov.SetParameter(_MV_RAW_VECTORS, 1)  # ON
                        new_aov.SetParameter(_MV_NO_CLAMP, 1)     # ON
                    else:  # After Effects (RSMB Pro)
                        new_aov.SetParameter(_MV_RAW_VECTORS, 0)  # OFF (normalized)
                        new_aov.SetParameter(_MV_NO_CLAMP, 0)     # OFF
                        new_aov.SetParameter(_MV_MAX_MOTION, 64)  # Match RSMB MaxDisplace

                new_aovs.append(new_aov)
                added += 1
                safe_print(f"  Added AOV: {name} ({bit_depth}-bit, direct)")
            except Exception as e:
                safe_print(f"  Failed: '{name}': {e}")

        if added > 0:
            redshift.RendererSetAOVs(vprs, new_aovs)


            check_cache.clear()
            c4d.EventAdd()

        return added, None

    except Exception as e:
        safe_print(f"Error forcing AOVs: {e}")
        return 0, f"Error: {e}"
