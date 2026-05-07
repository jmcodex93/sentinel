# -*- coding: utf-8 -*-
import c4d
from c4d import plugins, gui, documents
import os
import json
import time
import sys
import webbrowser
from collections import defaultdict

# ---------------- Safe Print Function ----------------
def safe_print(msg):
    """Print to console with null safety. Prefix matches plugin brand."""
    try:
        if msg is not None:
            print(f"[Sentinel] {msg}")
    except (UnicodeEncodeError, AttributeError):
        pass  # Print failed, continue silently

# ---------------- Platform Utilities ----------------
def open_in_explorer(path):
    """Open a file or folder in the system file manager (cross-platform)"""
    import subprocess
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        safe_print(f"Could not open path: {path} - {e}")

# Import maxon for node material access
try:
    import maxon
    MAXON_AVAILABLE = True
except ImportError:
    MAXON_AVAILABLE = False

# Import Redshift module for AOV management
try:
    import redshift
    REDSHIFT_AVAILABLE = True
except ImportError:
    REDSHIFT_AVAILABLE = False

# Import maxon module path
sys.path.insert(0, os.path.dirname(__file__))

# Plugin ID - change if ID collision
PLUGIN_ID = 2099069
PLUGIN_NAME = "Sentinel v1.5.2"

# Preset names - normalized to lowercase with underscores
# The system accepts both "pre_render" and "pre-render" (case-insensitive)
PRESETS = ["previz", "pre_render", "render", "stills"]

def normalize_preset_name(name):
    """Normalize preset name: lowercase, replace hyphens/spaces with underscores"""
    if not name:
        return ""
    return name.strip().lower().replace("-", "_").replace(" ", "_")

# Performance settings for watcher
MAX_OBJECTS_PER_CHECK = 1000  # Process in chunks
CACHE_DURATION = 2.0  # Cache results for 2 seconds (optimized for performance)
CHECK_COOLDOWN = 0.5  # Minimum time between checks

# Global settings file for artist name (Sentinel)
SETTINGS_FILE = "sentinel_settings.json"
LEGACY_SETTINGS_FILE = "ys_guardian_settings.json"  # pre-rebrand, auto-migrated on first load

# ---------------- Settings Persistence ----------------
class GlobalSettings:
    """Manages computer-level settings (not scene-specific)"""

    @staticmethod
    def get_settings_path():
        prefs_path = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
        return os.path.join(prefs_path, SETTINGS_FILE)

    @staticmethod
    def _legacy_path():
        prefs_path = c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS)
        return os.path.join(prefs_path, LEGACY_SETTINGS_FILE)

    @staticmethod
    def _load():
        settings_path = GlobalSettings.get_settings_path()
        # Try new file first
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        # One-time migration from legacy YS Guardian settings
        legacy_path = GlobalSettings._legacy_path()
        if os.path.exists(legacy_path):
            try:
                with open(legacy_path, 'r') as f:
                    data = json.load(f)
                # Persist to new path so future loads skip the migration check
                with open(settings_path, 'w') as f:
                    json.dump(data, f, indent=2)
                safe_print(f"Migrated legacy settings: {LEGACY_SETTINGS_FILE} -> {SETTINGS_FILE}")
                return data
            except Exception as e:
                safe_print(f"Could not migrate legacy settings: {e}")
        return {}

    @staticmethod
    def _save(settings):
        try:
            with open(GlobalSettings.get_settings_path(), 'w') as f:
                json.dump(settings, f, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def get(key, default=''):
        return GlobalSettings._load().get(key, default)

    @staticmethod
    def set(key, value):
        settings = GlobalSettings._load()
        settings[key] = value
        return GlobalSettings._save(settings)

    @staticmethod
    def load_artist_name():
        return GlobalSettings.get('artist_name', '')

    @staticmethod
    def save_artist_name(artist_name):
        return GlobalSettings.set('artist_name', artist_name)

    @staticmethod
    def get_snapshot_dir():
        """Get configured RS snapshot directory, or platform default"""
        saved = GlobalSettings.get('snapshot_dir', '')
        if saved:
            return saved
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Caches/Redshift/Snapshots")
        return r"C:\cache\rs snapshots"

    @staticmethod
    def set_snapshot_dir(path):
        return GlobalSettings.set('snapshot_dir', path)

    @staticmethod
    def get_standard_fps():
        """Get studio standard FPS (default 25)"""
        return int(GlobalSettings.get('standard_fps', 25))

    @staticmethod
    def set_standard_fps(fps):
        return GlobalSettings.set('standard_fps', int(fps))

# ---------------- Performance Cache ----------------
class CheckCache:
    def __init__(self):
        self.cache = {}
        self.last_update = 0
        self.doc_id = None
        self.ancestor_vis_cache = {}  # Persistent ancestor visibility cache

    def get(self, doc, key):
        doc_id = id(doc)
        now = time.time()

        if (self.doc_id == doc_id and
            key in self.cache and
            now - self.last_update < CACHE_DURATION):
            return self.cache[key]
        return None

    def set(self, doc, key, value):
        self.doc_id = id(doc)
        self.cache[key] = value
        self.last_update = time.time()

    def get_ancestor_visibility(self, obj):
        """Get cached ancestor visibility or calculate and cache"""
        obj_id = id(obj)
        if obj_id in self.ancestor_vis_cache:
            return self.ancestor_vis_cache[obj_id]
        return None

    def set_ancestor_visibility(self, obj, vis_tuple):
        """Cache ancestor visibility for object"""
        obj_id = id(obj)
        self.ancestor_vis_cache[obj_id] = vis_tuple

    def clear(self):
        self.cache.clear()
        self.ancestor_vis_cache.clear()
        self.doc_id = None

# Global cache instance
check_cache = CheckCache()

def _safe_name(obj):
    """Get object name safely, returns 'unknown' if object is dead"""
    try:
        return obj.GetName() or "unnamed"
    except Exception:
        return "unknown"

# ---------------- utils ----------------
def _iter_objs(op, max_count=None):
    """Optimized object iterator with limit"""
    count = 0
    stack = [op]

    while stack and (max_count is None or count < max_count):
        current = stack.pop()
        if current is None:
            continue

        yield current
        count += 1

        child = current.GetDown()
        if child:
            stack.append(child)

        sibling = current.GetNext()
        if sibling:
            stack.append(sibling)

def _any_ancestor_named(o, names_lower):
    """Check if any ancestor has one of the specified names"""
    if not o:
        return False

    p = o.GetUp()
    depth = 0
    max_depth = 100

    while p and depth < max_depth:
        try:
            nm = (p.GetName() or "").strip().lower()
            if nm in names_lower:
                return True
        except Exception:
            pass
        p = p.GetUp()
        depth += 1
    return False

# ---------------- lights (optimized) ----------------
RS_LIGHT_ID = 1036751  # Redshift Light
C4D_LIGHT_ID = c4d.Olight
LIGHT_TYPE_CACHE = {}  # Cache light type checks

def _is_light_obj(op):
    """Optimized light detection with caching"""
    if not op:
        return False

    op_id = op.GetType()

    # Check cache first
    if op_id in LIGHT_TYPE_CACHE:
        return LIGHT_TYPE_CACHE[op_id]

    is_light = False

    try:
        # Fast checks first
        if op_id == C4D_LIGHT_ID or op_id == RS_LIGHT_ID:
            is_light = True
        elif op.CheckType(C4D_LIGHT_ID):
            is_light = True
        else:
            # Additional Redshift light types
            if op_id in (1036754, 1038653, 1036950, 1034355, 1036753):  # RS lights
                is_light = True
            else:
                # Slow check last
                tn = (op.GetTypeName() or "").lower()
                if "light" in tn:
                    is_light = True
    except Exception:
        pass

    # Cache result
    LIGHT_TYPE_CACHE[op_id] = is_light
    return is_light

def check_lights(doc):
    """Check for lights outside proper containers - accepts 'light', 'lights', or 'lighting'"""
    cached = check_cache.get(doc, "lights")
    if cached is not None:
        return cached

    offenders = []
    names = {"light", "lights", "lighting"}
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "lights", offenders)
        return offenders

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            if not _is_light_obj(o):
                continue

            if _any_ancestor_named(o, names):
                continue

            offenders.append(o)

            # Early exit if too many issues
            if len(offenders) > 50:
                safe_print(f"Too many light issues found ({len(offenders)}+), stopping check")
                break

    except Exception as e:
        safe_print(f"Error checking lights: {e}")

    check_cache.set(doc, "lights", offenders)
    return offenders

# ---------------- visibility traps (optimized) ----------------
def check_visibility_traps(doc):
    """Check for visibility inconsistencies between viewport and render"""
    cached = check_cache.get(doc, "vis")
    if cached is not None:
        return cached

    traps = []
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "vis", traps)
        return traps

    def ed(o):
        try:
            return o[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR]
        except Exception:
            return c4d.OBJECT_ON

    def rd(o):
        try:
            return o[c4d.ID_BASEOBJECT_VISIBILITY_RENDER]
        except Exception:
            return c4d.OBJECT_ON

    try:
        # Performance optimization: Use persistent ancestor visibility cache
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                obj_id = id(o)
                ed_vis = ed(o)
                rd_vis = rd(o)

                # Check direct visibility trap
                if ed_vis == c4d.OBJECT_OFF and rd_vis != c4d.OBJECT_OFF:
                    traps.append(o)
                    continue

                # Check ancestor visibility using persistent cache
                p = o.GetUp()
                if p:
                    # Try persistent cache first
                    cached_vis = check_cache.get_ancestor_visibility(p)

                    if cached_vis is not None:
                        ancE, ancR = cached_vis
                    else:
                        # Calculate ancestor visibility and cache it
                        ancE = False
                        ancR = False
                        temp_p = p
                        depth = 0

                        while temp_p and depth < 50:
                            if ed(temp_p) == c4d.OBJECT_OFF:
                                ancE = True
                            if rd(temp_p) == c4d.OBJECT_OFF:
                                ancR = True
                            temp_p = temp_p.GetUp()
                            depth += 1

                        # Store in persistent cache for reuse across timer ticks
                        check_cache.set_ancestor_visibility(p, (ancE, ancR))

                    if (ancE and ed_vis == c4d.OBJECT_ON) or (ancR and rd_vis == c4d.OBJECT_ON):
                        traps.append(o)

                # Early exit
                if len(traps) > 50:
                    safe_print(f"Too many visibility issues ({len(traps)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking visibility: {e}")

    check_cache.set(doc, "vis", traps)
    return traps

# ---------------- keyframe sanity (optimized) ----------------
def check_keys(doc):
    """Check for multi-axis position/rotation keyframes"""
    cached = check_cache.get(doc, "keys")
    if cached is not None:
        return cached

    offenders = []
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "keys", offenders)
        return offenders

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                tracks = o.GetCTracks()
                if not tracks:
                    continue

                pos_axes = set()
                rot_axes = set()

                for tr in tracks:
                    try:
                        did = tr.GetDescriptionID()
                        if not did or did.GetDepth() < 1:
                            continue

                        first_id = did[0].id

                        if first_id == c4d.ID_BASEOBJECT_POSITION:
                            if did.GetDepth() >= 2:
                                pos_axes.add(did[1].id)
                        elif first_id == c4d.ID_BASEOBJECT_ROTATION:
                            if did.GetDepth() >= 2:
                                rot_axes.add(did[1].id)
                    except Exception:
                        continue

                if len(pos_axes) > 1 or len(rot_axes) > 1:
                    offenders.append(o)

                # Early exit
                if len(offenders) > 50:
                    safe_print(f"Too many keyframe issues ({len(offenders)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking keyframes: {e}")

    check_cache.set(doc, "keys", offenders)
    return offenders

# ---------------- camera shift (optimized) ----------------
RS_CAMERA_ID = 1057516

def _camera_shift_values(o):
    """Get camera shift values"""
    if not o:
        return 0.0, 0.0
    try:
        x = float(o[c4d.CAMERAOBJECT_FILM_OFFSET_X] or 0.0)
        y = float(o[c4d.CAMERAOBJECT_FILM_OFFSET_Y] or 0.0)
        return x, y
    except Exception:
        return 0.0, 0.0

def check_camera_shift(doc):
    """Check for cameras with non-zero shift"""
    cached = check_cache.get(doc, "cam")
    if cached is not None:
        return cached

    bad = []
    first = doc.GetFirstObject()

    if not first:
        check_cache.set(doc, "cam", bad)
        return bad

    try:
        for o in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not o:
                continue

            try:
                # Quick type check
                obj_type = o.GetType()
                if obj_type != c4d.Ocamera and obj_type != RS_CAMERA_ID:
                    continue

                x, y = _camera_shift_values(o)
                if abs(x) > 1e-6 or abs(y) > 1e-6:
                    bad.append(o)

                # Early exit
                if len(bad) > 20:
                    safe_print(f"Too many camera shift issues ({len(bad)}+), stopping check")
                    break

            except Exception:
                continue

    except Exception as e:
        safe_print(f"Error checking camera shift: {e}")

    check_cache.set(doc, "cam", bad)
    return bad

# ---------------- render preset conflicts (optimized) ----------------
def check_render_conflicts(doc):
    """Check for render setting conflicts - accepts pre_render, pre-render, Pre-Render etc."""
    cached = check_cache.get(doc, "rdc")
    if cached is not None:
        return cached

    allowed = set(PRESETS)
    name_counts = defaultdict(int)
    extras = 0

    try:
        rd = doc.GetFirstRenderData()
        count = 0
        max_check = 100  # Limit iterations

        while rd and count < max_check:
            try:
                # Normalize the name (lowercase, replace hyphens/spaces with underscores)
                name = normalize_preset_name(rd.GetName() or "")
                if name in allowed:
                    name_counts[name] += 1
                else:
                    extras += 1
            except Exception:
                pass

            rd = rd.GetNext()
            count += 1

        dups = sum(max(0, c - 1) for c in name_counts.values())
        result = extras + dups

    except Exception as e:
        safe_print(f"Error checking render conflicts: {e}")
        result = 0

    check_cache.set(doc, "rdc", result)
    return result

def _is_absolute_path(filepath):
    """Check if a file path is absolute (not relative)"""
    if not filepath:
        return False
    if len(filepath) > 2:
        if filepath[1] == ':' or filepath.startswith('\\\\'):
            return True
    if filepath.startswith('/'):
        return True
    return False

# ---------------- unused materials ----------------
def check_unused_materials(doc):
    """Check for materials not assigned to any object via any tag type"""
    cached = check_cache.get(doc, "unused_mats")
    if cached is not None:
        return cached

    unused = []
    try:
        materials = doc.GetMaterials()
        if not materials:
            check_cache.set(doc, "unused_mats", unused)
            return unused

        # Collect all materials referenced by ANY tag on ANY object
        used_mats = set()
        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                for tag in obj.GetTags():
                    # Check texture tags (standard material assignment)
                    if tag.GetType() == c4d.Ttexture:
                        mat = tag[c4d.TEXTURETAG_MATERIAL]
                        if mat:
                            used_mats.add(mat.GetName())
                    # Check any tag that might link a material
                    try:
                        bc = tag.GetDataInstance()
                        if bc:
                            for desc_id, _ in bc:
                                link = bc.GetLink(desc_id, doc)
                                if link and link.IsInstanceOf(c4d.Mbase):
                                    used_mats.add(link.GetName())
                    except Exception:
                        pass

        # Also check materials referenced by other materials (multi/blend materials)
        for mat in materials:
            try:
                shader = mat.GetFirstShader()
                while shader:
                    try:
                        bc = shader.GetDataInstance()
                        if bc:
                            for desc_id, _ in bc:
                                link = bc.GetLink(desc_id, doc)
                                if link and link.IsInstanceOf(c4d.Mbase):
                                    used_mats.add(link.GetName())
                    except Exception:
                        pass
                    shader = shader.GetNext()
            except Exception:
                pass

        for mat in materials:
            if mat.GetName() not in used_mats:
                unused.append(mat)

    except Exception as e:
        safe_print(f"Error checking unused materials: {e}")

    check_cache.set(doc, "unused_mats", unused)
    return unused

# ---------------- default naming ----------------
# Common default object names that indicate unorganized scenes
_DEFAULT_NAMES = {
    "null", "cube", "sphere", "cylinder", "cone", "plane", "disc", "torus",
    "capsule", "oil tank", "platonic", "pyramid", "gem", "tube", "landscape",
    "figure", "spline", "circle", "rectangle", "n-side", "arc", "helix",
    "sweep", "extrude", "lathe", "loft", "boole", "symmetry", "instance",
    "cloner", "fracture", "voronoi fracture", "matrix", "mograph",
    "camera", "light", "floor", "sky", "environment", "physical sky",
}

def check_default_names(doc):
    """Check for objects with default/generic names (Cube, Null, Sphere.1, etc.)"""
    cached = check_cache.get(doc, "names")
    if cached is not None:
        return cached

    offenders = []
    first = doc.GetFirstObject()
    if not first:
        check_cache.set(doc, "names", offenders)
        return offenders

    try:
        for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
            if not obj:
                continue
            name = (obj.GetName() or "").strip()
            if not name:
                offenders.append(obj)
                continue

            # Strip trailing ".N" suffix (e.g., "Cube.1", "Null.23")
            base = name.rsplit(".", 1)[0].strip().lower() if "." in name else name.lower()

            if base in _DEFAULT_NAMES:
                offenders.append(obj)

            if len(offenders) > 50:
                break

    except Exception as e:
        safe_print(f"Error checking default names: {e}")

    check_cache.set(doc, "names", offenders)
    return offenders

# ---------------- output path validation ----------------
def check_output_paths(doc):
    """Check render output paths are configured with proper tokens"""
    cached = check_cache.get(doc, "output")
    if cached is not None:
        return cached

    issues = []
    try:
        rd = doc.GetFirstRenderData()
        count = 0
        while rd and count < 100:
            name = rd.GetName() or "unnamed"
            path = rd[c4d.RDATA_PATH] or ""

            if not path.strip():
                issues.append({"preset": name, "issue": "empty output path"})
            elif "$prj" not in path and "$take" not in path:
                issues.append({"preset": name, "issue": f"no tokens in path: {path}"})

            # Check multi-pass path if enabled
            try:
                if rd[c4d.RDATA_MULTIPASS_SAVEIMAGE]:
                    mp_path = rd[c4d.RDATA_MULTIPASS_FILENAME] or ""
                    if not mp_path.strip():
                        issues.append({"preset": name, "issue": "empty multi-pass path"})
            except Exception:
                pass

            rd = rd.GetNext()
            count += 1

    except Exception as e:
        safe_print(f"Error checking output paths: {e}")

    check_cache.set(doc, "output", issues)
    return issues

# ---------------- unified texture check ----------------
RS_NODESPACE = "com.redshift3d.redshift4c4d.class.nodespace"

def check_textures_unified(doc):
    """Unified check: scans classic shaders, RS nodes, and alembics for absolute paths and missing files"""
    cached = check_cache.get(doc, "textures")
    if cached is not None:
        return cached

    issues = []
    seen_paths = set()
    doc_path = doc.GetDocumentPath() or ""

    def resolve(filepath):
        if not filepath:
            return None
        filepath = str(filepath).strip()
        if not filepath:
            return None
        if _is_absolute_path(filepath):
            return filepath
        if doc_path:
            return os.path.join(doc_path, filepath)
        return None

    def add_issue(source, filepath):
        """Check a file path and add issue if absolute or missing"""
        if not filepath or filepath in seen_paths:
            return
        seen_paths.add(filepath)

        if _is_absolute_path(filepath):
            issues.append({"source": source, "path": filepath, "issue": "absolute"})
        else:
            resolved = resolve(filepath)
            if resolved and not os.path.exists(resolved):
                issues.append({"source": source, "path": filepath, "issue": "missing", "resolved": resolved})

    try:
        materials = doc.GetMaterials() or []

        for mat in materials:
            if not mat:
                continue
            mat_name = mat.GetName()

            # --- Classic shaders ---
            shader = mat.GetFirstShader()
            while shader:
                if shader.GetType() == c4d.Xbitmap:
                    try:
                        fp = shader[c4d.BITMAPSHADER_FILENAME]
                        if fp:
                            add_issue(f"Shader in '{mat_name}'", str(fp))
                    except Exception:
                        pass
                shader = shader.GetNext()

            # --- BaseContainer file params ---
            try:
                bc = mat.GetDataInstance()
                if bc:
                    for desc_id, _ in bc:
                        try:
                            fp = bc.GetFilename(desc_id)
                            if fp and str(fp).strip():
                                add_issue(f"Material '{mat_name}'", str(fp))
                        except Exception:
                            pass
            except Exception:
                pass

            # --- RS Node graph ---
            if MAXON_AVAILABLE:
                try:
                    nodeMat = mat.GetNodeMaterialReference()
                    if nodeMat and nodeMat.HasSpace(RS_NODESPACE):
                        graph = nodeMat.GetGraph(RS_NODESPACE)
                        if graph:
                            root = graph.GetViewRoot()

                            def check_port_value(port):
                                try:
                                    val = None
                                    try:
                                        val = port.GetPortValue()
                                    except Exception:
                                        try:
                                            val = port.GetDefaultValue()
                                        except Exception:
                                            return None
                                    if val is None:
                                        return None
                                    filepath = ""
                                    try:
                                        if hasattr(val, 'GetSystemPath'):
                                            filepath = str(val.GetSystemPath())
                                    except Exception:
                                        pass
                                    if not filepath:
                                        try:
                                            if hasattr(val, 'ToString'):
                                                filepath = str(val.ToString())
                                        except Exception:
                                            pass
                                    if not filepath:
                                        filepath = str(val)
                                    if (not filepath or filepath == "None" or len(filepath) < 4
                                            or not ("/" in filepath or "\\" in filepath)):
                                        return None
                                    if filepath.startswith("asset:") or filepath.startswith("preset:"):
                                        return None
                                    return filepath
                                except Exception:
                                    return None

                            def scan_ports(port):
                                if not port:
                                    return
                                fp = check_port_value(port)
                                if fp:
                                    add_issue(f"RS Node in '{mat_name}'", fp)
                                try:
                                    for child in port.GetChildren():
                                        scan_ports(child)
                                except Exception:
                                    pass

                            def scan_node(node, depth=0):
                                if not node or depth > 10:
                                    return
                                try:
                                    inputs = node.GetInputs()
                                    if inputs:
                                        for port in inputs.GetChildren():
                                            scan_ports(port)
                                    for child in node.GetChildren():
                                        scan_node(child, depth + 1)
                                except Exception:
                                    pass

                            scan_node(root)
                except Exception:
                    pass

            if len(issues) > 50:
                break

        # --- Alembic objects ---
        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                if obj.GetType() == 1028083:
                    try:
                        fp = obj[c4d.ALEMBIC_PATH]
                        if fp:
                            add_issue(f"Alembic '{obj.GetName()}'", str(fp))
                    except Exception:
                        pass
                if len(issues) > 50:
                    break

    except Exception as e:
        safe_print(f"Error in unified texture check: {e}")

    check_cache.set(doc, "textures", issues)
    return issues

# ---------------- scene complexity ----------------
def get_scene_stats(doc):
    """Get scene complexity statistics"""
    cached = check_cache.get(doc, "stats")
    if cached is not None:
        return cached

    stats = {"objects": 0, "polygons": 0, "materials": 0, "lights": 0}

    try:
        stats["materials"] = len(doc.GetMaterials() or [])

        first = doc.GetFirstObject()
        if first:
            for obj in _iter_objs(first, MAX_OBJECTS_PER_CHECK):
                if not obj:
                    continue
                stats["objects"] += 1
                try:
                    cache = obj.GetDeformCache() or obj.GetCache()
                    target = cache if cache else obj
                    if target.IsInstanceOf(c4d.Opolygon):
                        stats["polygons"] += target.GetPolygonCount()
                except Exception:
                    pass
                if _is_light_obj(obj):
                    stats["lights"] += 1

    except Exception as e:
        safe_print(f"Error getting scene stats: {e}")

    check_cache.set(doc, "stats", stats)
    return stats

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
                })
            except Exception:
                pass
    except Exception as e:
        safe_print(f"Error reading RS AOVs: {e}")
    return aovs

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

# ---------------- take validation ----------------
def check_takes(doc):
    """Validate all takes have camera and output path configured"""
    cached = check_cache.get(doc, "takes")
    if cached is not None:
        return cached

    issues = []
    try:
        td = doc.GetTakeData()
        if not td:
            check_cache.set(doc, "takes", issues)
            return issues

        main_take = td.GetMainTake()
        if not main_take:
            check_cache.set(doc, "takes", issues)
            return issues

        # Iterate child takes (skip Main — it's not a renderable shot)
        take = main_take.GetDown()
        while take:
            take_name = take.GetName() or "unnamed"

            # Check camera
            cam = take.GetCamera(td)
            if not cam:
                issues.append({"take": take_name, "issue": "No camera assigned"})

            # Check render data output path
            rd = take.GetRenderData(td)
            if rd:
                path = rd[c4d.RDATA_PATH] or ""
                if not path.strip():
                    issues.append({"take": take_name, "issue": "Empty output path"})
                elif "$take" not in path:
                    issues.append({"take": take_name, "issue": f"Output path missing $take token"})
            else:
                # No override — inherits from main, check main's path
                main_rd = doc.GetActiveRenderData()
                if main_rd:
                    path = main_rd[c4d.RDATA_PATH] or ""
                    if "$take" not in path:
                        issues.append({"take": take_name, "issue": "Inherited path missing $take token"})

            take = take.GetNext()

    except Exception as e:
        safe_print(f"Error checking takes: {e}")

    check_cache.set(doc, "takes", issues)
    return issues

def check_fps_range(doc):
    """Validate FPS, frame range, frame step, and timeline alignment across ALL presets.

    Doc-level FPS is checked once. Each render data is validated independently for
    FPS, frame step (=1), range start (1001), and mode. Timeline + preview alignment
    is validated against the ACTIVE preset (since timeline is shared).
    """
    cached = check_cache.get(doc, "fps_range")
    if cached is not None:
        return cached

    issues = []
    try:
        standard_fps = GlobalSettings.get_standard_fps()
        doc_fps = doc.GetFps()

        # --- Document-level FPS (checked once) ---
        if doc_fps != standard_fps:
            issues.append({
                "issue": f"Document FPS is {doc_fps}, expected {standard_fps}",
                "type": "doc_fps",
                "preset": None,
            })

        active_rd = doc.GetActiveRenderData()
        if not active_rd:
            check_cache.set(doc, "fps_range", issues)
            return issues

        # --- Iterate all render datas ---
        rd = doc.GetFirstRenderData()
        while rd:
            preset_name = rd.GetName()
            preset_norm = normalize_preset_name(preset_name)
            is_stills = preset_norm == "stills"
            is_active = (rd == active_rd)
            tag = f"[{preset_name}]"

            rd_fps = int(rd[c4d.RDATA_FRAMERATE])
            if rd_fps != standard_fps:
                issues.append({
                    "issue": f"{tag} Render FPS is {rd_fps}, expected {standard_fps}",
                    "type": "rd_fps",
                    "preset": preset_name,
                })

            # Frame step should always be 1 (no skipping)
            frame_step = int(rd[c4d.RDATA_FRAMESTEP])
            if frame_step != 1:
                issues.append({
                    "issue": f"{tag} Frame step is {frame_step}, expected 1 (frame skipping)",
                    "type": "frame_step",
                    "preset": preset_name,
                })

            frame_start = rd[c4d.RDATA_FRAMEFROM].GetFrame(rd_fps)
            frame_end = rd[c4d.RDATA_FRAMETO].GetFrame(rd_fps)
            frame_mode = rd[c4d.RDATA_FRAMESEQUENCE]

            if is_stills:
                if frame_mode == c4d.RDATA_FRAMESEQUENCE_MANUAL and frame_start != 1001:
                    issues.append({
                        "issue": f"{tag} Stills start frame is {frame_start}, expected 1001",
                        "type": "start_frame",
                        "preset": preset_name,
                    })
                if frame_mode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
                    issues.append({
                        "issue": f"{tag} Stills set to 'All Frames' (use Current Frame or 1001)",
                        "type": "mode",
                        "preset": preset_name,
                    })
            else:
                if frame_start != 1001:
                    issues.append({
                        "issue": f"{tag} Start frame is {frame_start}, expected 1001",
                        "type": "start_frame",
                        "preset": preset_name,
                    })
                if frame_end <= frame_start:
                    issues.append({
                        "issue": f"{tag} Frame range invalid: {frame_start}-{frame_end}",
                        "type": "range",
                        "preset": preset_name,
                    })
                if frame_mode == c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME:
                    issues.append({
                        "issue": f"{tag} Animation set to 'Current Frame' only",
                        "type": "mode",
                        "preset": preset_name,
                    })
                elif frame_mode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
                    issues.append({
                        "issue": f"{tag} Set to 'All Frames' (may render entire timeline)",
                        "type": "mode",
                        "preset": preset_name,
                    })
                frame_length = frame_end - frame_start + 1
                if frame_length > 1000 and frame_mode != c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
                    issues.append({
                        "issue": f"{tag} Very long render: {frame_length} frames",
                        "type": "length",
                        "preset": preset_name,
                    })

            # --- Timeline + preview alignment (against ACTIVE preset only) ---
            if is_active:
                tl_min = doc[c4d.DOCUMENT_MINTIME].GetFrame(doc_fps)
                tl_max = doc[c4d.DOCUMENT_MAXTIME].GetFrame(doc_fps)
                loop_min = doc[c4d.DOCUMENT_LOOPMINTIME].GetFrame(doc_fps)
                loop_max = doc[c4d.DOCUMENT_LOOPMAXTIME].GetFrame(doc_fps)

                if is_stills:
                    if not (tl_min <= 1001 <= tl_max):
                        issues.append({
                            "issue": f"Timeline ({tl_min}-{tl_max}) doesn't include frame 1001",
                            "type": "timeline",
                            "preset": None,
                        })
                else:
                    if frame_end > frame_start:
                        if tl_min != frame_start or tl_max != frame_end:
                            issues.append({
                                "issue": f"Timeline ({tl_min}-{tl_max}) doesn't match active render range ({frame_start}-{frame_end})",
                                "type": "timeline",
                                "preset": None,
                            })
                        if loop_min != frame_start or loop_max != frame_end:
                            issues.append({
                                "issue": f"Preview range ({loop_min}-{loop_max}) doesn't match active render range ({frame_start}-{frame_end})",
                                "type": "loop",
                                "preset": None,
                            })

            rd = rd.GetNext()

    except Exception as e:
        safe_print(f"Error checking FPS/range: {e}")

    check_cache.set(doc, "fps_range", issues)
    return issues

def _fix_one_render_data(doc, rd, standard_fps):
    """Fix a single render data. Returns list of human-readable change strings.

    Caller is responsible for StartUndo/EndUndo and AddUndo. Returns final
    (start, end) frames after the fix, useful for timeline alignment.
    """
    changes = []
    preset_name = rd.GetName()
    preset_norm = normalize_preset_name(preset_name)
    is_stills = preset_norm == "stills"
    tag = f"[{preset_name}]"

    rd_fps_old = int(rd[c4d.RDATA_FRAMERATE])
    current_start = rd[c4d.RDATA_FRAMEFROM].GetFrame(rd_fps_old)
    current_end = rd[c4d.RDATA_FRAMETO].GetFrame(rd_fps_old)
    frame_mode = rd[c4d.RDATA_FRAMESEQUENCE]
    frame_step = int(rd[c4d.RDATA_FRAMESTEP])

    # Render FPS
    if rd_fps_old != standard_fps:
        rd[c4d.RDATA_FRAMERATE] = float(standard_fps)
        changes.append(f"{tag} Render FPS {rd_fps_old} -> {standard_fps}")

    # Frame step
    if frame_step != 1:
        rd[c4d.RDATA_FRAMESTEP] = 1
        changes.append(f"{tag} Frame step {frame_step} -> 1")

    final_start = 1001
    final_end = 1001

    if is_stills:
        if frame_mode == c4d.RDATA_FRAMESEQUENCE_MANUAL and current_start != 1001:
            duration = max(0, current_end - current_start)
            final_end = 1001 + duration
            rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(1001, standard_fps)
            rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(final_end, standard_fps)
            changes.append(f"{tag} Frame range {current_start}-{current_end} -> 1001-{final_end}")
        elif frame_mode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
            rd[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
            changes.append(f"{tag} Frame mode 'All Frames' -> 'Current Frame'")
        elif rd_fps_old != standard_fps:
            # Re-anchor BaseTime to new fps
            rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(current_start, standard_fps)
            rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(current_end, standard_fps)
            final_end = current_end if current_end >= 1001 else 1001
        else:
            final_end = current_end if current_end >= 1001 else 1001
    else:
        # Animation: range start at 1001, preserve duration
        duration = max(0, current_end - current_start)
        final_end = 1001 + duration
        if current_start != 1001 or rd_fps_old != standard_fps:
            rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(final_start, standard_fps)
            rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(final_end, standard_fps)
            if current_start != 1001:
                changes.append(f"{tag} Frame range {current_start}-{current_end} -> {final_start}-{final_end}")
        if frame_mode in (c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME, c4d.RDATA_FRAMESEQUENCE_ALLFRAMES):
            rd[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_MANUAL
            changes.append(f"{tag} Frame mode -> 'Manual'")

    return changes, final_start, final_end


def fix_fps_range(doc):
    """Auto-fix FPS/range across ALL render presets. Aligns timeline to active preset."""
    fixes = []
    if not doc.GetFirstRenderData():
        return fixes

    standard_fps = GlobalSettings.get_standard_fps()
    active_rd = doc.GetActiveRenderData()

    doc.StartUndo()
    try:
        # --- Document-level FPS (once) ---
        doc_fps = doc.GetFps()
        if doc_fps != standard_fps:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE_SMALL, doc)
            doc.SetFps(standard_fps)
            fixes.append(f"Document FPS: {doc_fps} -> {standard_fps}")

        # --- Iterate all render datas ---
        active_final_start = 1001
        active_final_end = 1001

        rd = doc.GetFirstRenderData()
        while rd:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, rd)
            changes, final_start, final_end = _fix_one_render_data(doc, rd, standard_fps)
            fixes.extend(changes)
            if rd == active_rd:
                active_final_start = final_start
                active_final_end = final_end
            rd = rd.GetNext()

        # --- Align timeline + preview to ACTIVE preset's range ---
        tl_min = doc[c4d.DOCUMENT_MINTIME].GetFrame(standard_fps)
        tl_max = doc[c4d.DOCUMENT_MAXTIME].GetFrame(standard_fps)
        loop_min = doc[c4d.DOCUMENT_LOOPMINTIME].GetFrame(standard_fps)
        loop_max = doc[c4d.DOCUMENT_LOOPMAXTIME].GetFrame(standard_fps)

        if tl_min != active_final_start or tl_max != active_final_end:
            # Avoid intermediate min > max state
            if active_final_start >= tl_max:
                doc[c4d.DOCUMENT_MAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
                doc[c4d.DOCUMENT_MINTIME] = c4d.BaseTime(active_final_start, standard_fps)
            else:
                doc[c4d.DOCUMENT_MINTIME] = c4d.BaseTime(active_final_start, standard_fps)
                doc[c4d.DOCUMENT_MAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
            fixes.append(f"Timeline: {tl_min}-{tl_max} -> {active_final_start}-{active_final_end}")

        if loop_min != active_final_start or loop_max != active_final_end:
            if active_final_start >= loop_max:
                doc[c4d.DOCUMENT_LOOPMAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
                doc[c4d.DOCUMENT_LOOPMINTIME] = c4d.BaseTime(active_final_start, standard_fps)
            else:
                doc[c4d.DOCUMENT_LOOPMINTIME] = c4d.BaseTime(active_final_start, standard_fps)
                doc[c4d.DOCUMENT_LOOPMAXTIME] = c4d.BaseTime(active_final_end, standard_fps)
            fixes.append(f"Preview range: {loop_min}-{loop_max} -> {active_final_start}-{active_final_end}")

        # --- Snap playhead to range if it fell outside ---
        playhead = doc.GetTime().GetFrame(standard_fps)
        if playhead < active_final_start or playhead > active_final_end:
            doc.SetTime(c4d.BaseTime(active_final_start, standard_fps))
            fixes.append(f"Playhead: frame {playhead} -> {active_final_start} (out of range)")

    except Exception as e:
        safe_print(f"Error fixing FPS/range: {e}")
    finally:
        doc.EndUndo()

    check_cache.clear()
    c4d.EventAdd()
    return fixes

# ---------------- auto-fix functions ----------------
def fix_lights(doc, lights_bad):
    """Move stray lights into a 'lights' group null"""
    if not lights_bad:
        return 0

    doc.StartUndo()

    # Find or create the lights group
    lights_group = None
    obj = doc.GetFirstObject()
    while obj:
        if obj.GetType() == c4d.Onull and obj.GetName().strip().lower() in {"light", "lights", "lighting"}:
            lights_group = obj
            break
        obj = obj.GetNext()

    if not lights_group:
        lights_group = c4d.BaseObject(c4d.Onull)
        lights_group.SetName("lights")
        doc.InsertObject(lights_group)
        doc.AddUndo(c4d.UNDOTYPE_NEW, lights_group)

    moved = 0
    for light in lights_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, light)
        light.Remove()
        light.InsertUnderLast(lights_group)
        moved += 1

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return moved

def fix_camera_shift(doc, cam_bad):
    """Reset camera shift to 0 on all flagged cameras"""
    if not cam_bad:
        return 0

    doc.StartUndo()
    fixed = 0
    for cam in cam_bad:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, cam)
        try:
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
            cam[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
            fixed += 1
        except Exception:
            pass

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return fixed

def fix_unused_materials(doc, unused_mats):
    """Delete unused materials from the scene"""
    if not unused_mats:
        return 0

    doc.StartUndo()
    deleted = 0
    for mat in unused_mats:
        doc.AddUndo(c4d.UNDOTYPE_DELETE, mat)
        mat.Remove()
        deleted += 1

    doc.EndUndo()
    check_cache.clear()
    c4d.EventAdd()
    return deleted

def export_qc_report(doc, results, artist_name):
    """Export QC report as JSON to a user-chosen location"""
    from datetime import datetime

    # Build report
    report = {
        "report": "Sentinel QC Report",
        "version": PLUGIN_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scene": doc.GetDocumentName() or "untitled",
        "path": doc.GetDocumentPath() or "",
        "artist": artist_name or "",
        "shot_id": "",
        "checks": {}
    }

    # Get shot ID
    try:
        td = doc.GetTakeData()
        if td:
            main_take = td.GetMainTake()
            if main_take:
                report["shot_id"] = main_take.GetName() or ""
    except Exception:
        pass

    # Populate checks
    for key, label, items in [
        ("lights", "Lights outside group", results.get("lights_bad", [])),
        ("visibility", "Visibility mismatches", results.get("vis_bad", [])),
        ("keyframes", "Multi-axis keyframes", results.get("keys_bad", [])),
        ("camera_shift", "Camera shift != 0", results.get("cam_bad", [])),
        ("unused_materials", "Unused materials", results.get("unused_mats_bad", [])),
        ("default_names", "Default/generic names", results.get("names_bad", [])),
    ]:
        obj_list = []
        for item in (items or []):
            try:
                obj_list.append(item.GetName() or "unnamed")
            except Exception:
                obj_list.append(str(item))
        report["checks"][key] = {
            "status": "PASS" if not obj_list else "FAIL",
            "count": len(obj_list),
            "label": label,
            "items": obj_list[:50],
        }

    # Unified textures check
    tex_bad = results.get("textures_bad", [])
    report["checks"]["textures"] = {
        "status": "PASS" if not tex_bad else "FAIL",
        "count": len(tex_bad),
        "label": "Texture issues (absolute paths + missing files)",
        "items": [f"[{t['issue'].upper()}] {t['source']}: {t['path']}" for t in tex_bad[:30]],
    }

    # Scene stats
    stats = results.get("scene_stats", {})
    if stats:
        report["scene_stats"] = stats

    # Info-only checks
    for key, label, count in [
        ("render_presets", "Non-standard presets", results.get("rdc_count", 0)),
        ("output_paths", "Output path issues", results.get("output_count", 0)),
        ("takes", "Take configuration issues", len(results.get("takes_bad", []))),
    ]:
        report["checks"][key] = {
            "status": "PASS" if count == 0 else "FAIL",
            "count": count,
            "label": label,
        }

    if results.get("output_bad"):
        report["checks"]["output_paths"]["items"] = [
            f"[{i['preset']}] {i['issue']}" for i in results["output_bad"][:10]
        ]
    if results.get("takes_bad"):
        report["checks"]["takes"]["items"] = [
            f"[{t['take']}] {t['issue']}" for t in results["takes_bad"][:20]
        ]

    # FPS / Frame Range check
    fps_bad = results.get("fps_range_bad", [])
    report["checks"]["fps_range"] = {
        "status": "PASS" if not fps_bad else "FAIL",
        "count": len(fps_bad),
        "label": "FPS & frame range validation",
        "items": [issue["issue"] for issue in fps_bad],
    }

    # Summary
    total = len(report["checks"])
    passed = sum(1 for c in report["checks"].values() if c["status"] == "PASS")
    report["summary"] = {
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "score": f"{passed}/{total}"
    }

    # Always include scene notes section in the report (empty defaults if no
    # sidecar exists yet — keeps the JSON shape consistent for tooling)
    notes_path = get_notes_path(doc)
    notes_section = {
        "summary": "Notes: empty",
        "text": "",
        "todos": [],
        "pending_count": 0,
        "updated": "",
    }
    if notes_path and os.path.exists(notes_path):
        try:
            notes_data = load_notes(notes_path)
            notes_section = {
                "summary": summarize_notes(notes_data),
                "text": notes_data.get("notes", "") or "",
                "todos": notes_data.get("todos", []) or [],
                "pending_count": sum(1 for t in (notes_data.get("todos") or []) if not t.get("done")),
                "updated": notes_data.get("updated", ""),
            }
        except Exception as e:
            safe_print(f"Could not include notes in QC report: {e}")
    report["notes"] = notes_section

    # Ask user where to save
    save_path = c4d.storage.SaveDialog(
        title="Save QC Report",
        force_suffix="json",
    )

    if not save_path:
        return None

    if not save_path.endswith(".json"):
        save_path += ".json"

    with open(save_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return save_path

# ---------------- Smart Incremental Save (versioning + history) ----------------
# Pure helpers — no UI, no document mutation. Tested via reasoning + step-by-step verification.
import re as _re

# Version + optional status tag suffix (e.g. _v003, _v003_TR, _v003_CR, _v003_PITCH).
# Status must be alphanumeric (letters first); we sanitize on write.
_VERSION_RE = _re.compile(r'_v(\d+)(?:_([A-Za-z][A-Za-z0-9]*))?$', _re.IGNORECASE)

# Mograph-native review status tags. Convention from Matthew Creed / community.
STATUS_NONE = ""        # WIP — no suffix
STATUS_TR = "TR"        # Team Review
STATUS_CR = "CR"        # Client Review
STATUS_FINAL = "FINAL"  # Final Delivery

# (combo_label, suffix). Order = combobox order.
STATUS_OPTIONS = [
    ("Work in Progress (WIP)",   STATUS_NONE),
    ("Team Review (TR)",         STATUS_TR),
    ("Client Review (CR)",       STATUS_CR),
    ("Final Delivery",           STATUS_FINAL),
]


def _sanitize_status(status):
    """Strip non-alphanumeric chars; uppercase. Returns "" if nothing left."""
    if not status:
        return ""
    cleaned = _re.sub(r'[^A-Za-z0-9]', '', status).upper()
    return cleaned


def parse_version_filename(name_no_ext):
    """Parse a basename (no extension) into (base, version_int, status_or_None).

    Examples:
      'scene_v003'        -> ('scene', 3, None)
      'scene_v003_TR'     -> ('scene', 3, 'TR')
      'robot_010_v014_CR' -> ('robot_010', 14, 'CR')
      'scene'             -> ('scene', None, None)
      'scene_v'           -> ('scene_v', None, None)
    """
    if not name_no_ext:
        return "", None, None
    m = _VERSION_RE.search(name_no_ext)
    if m:
        base = name_no_ext[:m.start()]
        try:
            ver = int(m.group(1))
        except ValueError:
            return name_no_ext, None, None
        status = m.group(2)
        status = status.upper() if status else None
        if base:
            return base, ver, status
    return name_no_ext, None, None


def build_versioned_filename(base, version, status=None, extension="c4d"):
    """('scene', 3) -> 'scene_v003.c4d'
       ('scene', 3, 'TR') -> 'scene_v003_TR.c4d'
    """
    if not base:
        base = "scene"
    suffix = ""
    cleaned = _sanitize_status(status)
    if cleaned:
        suffix = f"_{cleaned}"
    return f"{base}_v{int(version):03d}{suffix}.{extension}"


def get_history_path(doc_path):
    """Return the sidecar history JSON path for a given .c4d file path.

    Strips any '_v###[_status]' suffix so all versions of the same scene share one history.
    Returns None if doc_path is empty.
    """
    if not doc_path:
        return None
    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _ver, _status = parse_version_filename(name_no_ext)
    return os.path.join(folder, f"{base}_history.json")


def load_history(history_path):
    """Load history JSON. Always returns a dict with 'versions' list (empty if missing/invalid)."""
    default = {"scene": None, "versions": []}
    if not history_path or not os.path.exists(history_path):
        return default
    try:
        with open(history_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict) or "versions" not in data or not isinstance(data["versions"], list):
            safe_print(f"History file malformed, ignoring: {history_path}")
            return default
        return data
    except Exception as e:
        safe_print(f"Could not load history: {e}")
        return default


def save_history(history_path, history_data):
    """Write history JSON. Returns True/False."""
    if not history_path:
        return False
    try:
        with open(history_path, 'w') as f:
            json.dump(history_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        safe_print(f"Could not save history: {e}")
        return False


def compute_next_version(doc_path):
    """Determine the next version number to use, given the current document path.

    Looks at:
      - The current filename's version (if it follows _v### pattern)
      - All sibling files in the folder matching <base>_v###*.c4d (status tag ignored)
    Returns (base_name, next_version_int).

    If no current path, returns (None, 1) — caller must prompt for base name.
    """
    if not doc_path:
        return None, 1

    folder = os.path.dirname(doc_path)
    name_no_ext = os.path.splitext(os.path.basename(doc_path))[0]
    base, _current_v, _current_s = parse_version_filename(name_no_ext)

    # Scan folder for max existing version with this base — status tag ignored
    max_ver = 0
    if os.path.isdir(folder):
        try:
            for f in os.listdir(folder):
                if not f.lower().endswith('.c4d'):
                    continue
                f_name = os.path.splitext(f)[0]
                f_base, f_ver, _f_status = parse_version_filename(f_name)
                if f_base == base and f_ver is not None:
                    if f_ver > max_ver:
                        max_ver = f_ver
        except Exception as e:
            safe_print(f"Error scanning folder for versions: {e}")

    return base, max_ver + 1


def append_history_entry(history_path, entry):
    """Add a new version entry to the history JSON. Creates file if missing."""
    history = load_history(history_path)
    if "versions" not in history:
        history["versions"] = []
    # Newest first
    history["versions"].insert(0, entry)
    # Keep "scene" name updated for clarity
    if entry.get("scene"):
        history["scene"] = entry["scene"]
    return save_history(history_path, history)


def get_latest_version_info(doc):
    """Read the latest version entry from the doc's history sidecar.

    Returns the dict for the most recent version, or None if no history exists.
    """
    if not doc:
        return None
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path or not doc_name:
        return None
    full_path = os.path.join(doc_path, doc_name)
    history_path = get_history_path(full_path)
    if not history_path or not os.path.exists(history_path):
        return None
    history = load_history(history_path)
    versions = history.get("versions") or []
    return versions[0] if versions else None


def load_versions_for_doc(doc):
    """Read the full versions list (newest first) from the doc's sidecar history.

    Returns [] if no doc, no path, or no history file. Always returns a list.
    """
    if not doc:
        return []
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path or not doc_name:
        return []
    full_path = os.path.join(doc_path, doc_name)
    history_path = get_history_path(full_path)
    if not history_path or not os.path.exists(history_path):
        return []
    history = load_history(history_path)
    versions = history.get("versions") or []
    return versions if isinstance(versions, list) else []


# Filter token for "show all versions" — distinct from STATUS_NONE ("") so the UI
# can have an "All" choice that's different from "WIP only".
FILTER_ALL = "__ALL__"


def filter_versions_by_status(versions, status_filter):
    """Filter a versions list by status tag.

    status_filter:
      FILTER_ALL  -> return all
      ""          -> only WIP entries (status "" or missing)
      "TR"|"CR"|"FINAL"|<custom>  -> only entries whose status matches (case-insensitive)
    """
    if not versions:
        return []
    if status_filter == FILTER_ALL:
        return list(versions)
    target = (status_filter or "").upper()
    out = []
    for entry in versions:
        s = (entry.get("status") or "").upper()
        if s == target:
            out.append(entry)
    return out


def format_version_row(entry):
    """Build display strings for one version entry. Returns a dict of pre-formatted parts.

    Keys:
      version_label  : 'v007'
      status_label   : 'TR' | 'CR' | 'FINAL' | 'WIP' | <custom>
      time_label     : '2h ago' | '2026-04-01' (or '')
      comment        : raw comment string (caller may truncate)
      qc_label       : '9/11' | '' if no QC was run for this entry
      qc_pass        : True | False | None
      filename       : the .c4d filename
      path           : the full saved path
    """
    if entry is None:
        return None
    try:
        ver_int = int(entry.get("version", 0))
    except Exception:
        ver_int = 0
    status = (entry.get("status") or "").upper()
    return {
        "version_label": f"v{ver_int:03d}",
        "version_int":   ver_int,
        "status_label":  status if status else "WIP",
        "time_label":    _humanize_time_diff(entry.get("timestamp", "")),
        "comment":       entry.get("comment", "") or "",
        "qc_label":      entry.get("qc_score", "") or "",
        "qc_pass":       entry.get("qc_pass"),
        "filename":      entry.get("filename", "") or "",
        "path":          entry.get("path", "") or "",
        "artist":        entry.get("artist", "") or "",
    }


def _humanize_time_diff(timestamp_str):
    """Convert '2026-05-05 13:02:29' to a friendly relative string."""
    from datetime import datetime
    try:
        ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""
    delta = datetime.now() - ts
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days < 30:
        return f"{days}d ago"
    return ts.strftime("%Y-%m-%d")


def _build_qc_summary(doc):
    """Run all 11 QC checks (using cache) and return a compact summary dict."""
    counts = {
        "lights":      len(check_lights(doc) or []),
        "vis":         len(check_visibility_traps(doc) or []),
        "keys":        len(check_keys(doc) or []),
        "cam":         len(check_camera_shift(doc) or []),
        "rdc":         int(check_render_conflicts(doc) or 0),
        "textures":    len(check_textures_unified(doc) or []),
        "unused_mats": len(check_unused_materials(doc) or []),
        "names":       len(check_default_names(doc) or []),
        "output":      len(check_output_paths(doc) or []),
        "takes":       len(check_takes(doc) or []),
        "fps_range":   len(check_fps_range(doc) or []),
    }
    total = len(counts)
    passed = sum(1 for v in counts.values() if v == 0)
    return {
        "score": f"{passed}/{total}",
        "pass": passed == total,
        "passed": passed,
        "total": total,
        "counts": counts,
    }


def preview_next_filename(doc, status=None):
    """Compute what the next version filename will be, without saving.

    Returns a string like 'scene_v003.c4d' (or 'scene_v003_TR.c4d' with status).
    Returns None if no doc.
    """
    if not doc:
        return None
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path:
        suggested_base = os.path.splitext(doc_name)[0] if doc_name else "scene"
        suggested_base, _v, _s = parse_version_filename(suggested_base)
        if not suggested_base or suggested_base.lower().startswith("untitled"):
            suggested_base = "scene"
        return build_versioned_filename(suggested_base, 1, status=status)
    full_doc_path = os.path.join(doc_path, doc_name) if doc_name else doc_path
    base, next_version = compute_next_version(full_doc_path)
    if not base:
        base = os.path.splitext(doc_name or "scene")[0] or "scene"
        # strip any version artifact from doc_name fallback
        base, _v, _s = parse_version_filename(base)
        if not base:
            base = "scene"
    return build_versioned_filename(base, next_version, status=status)


class SaveVersionDialog(gui.GeDialog):
    """Modal dialog: comment + run-QC + review status tag.

    After Open(c4d.DLG_TYPE_MODAL), check `confirmed`. If True, read
    `result_comment`, `result_run_qc`, `result_status`.
    """

    # Widget IDs (local to this dialog)
    EDT_COMMENT = 1001
    CHK_RUN_QC = 1002
    BTN_SAVE = 1003
    BTN_CANCEL = 1004
    LBL_INFO = 1005
    COMBO_STATUS = 1006
    EDT_CUSTOM = 1007

    def __init__(self, doc=None, run_qc_default=True):
        super().__init__()
        self._doc = doc
        self._run_qc_default = bool(run_qc_default)
        self.result_comment = ""
        self.result_run_qc = run_qc_default
        self.result_status = ""
        self.confirmed = False

    def _current_status(self):
        """Compute the effective status from current widget state.
        Custom field takes priority if non-empty."""
        custom = (self.GetString(self.EDT_CUSTOM) or "").strip()
        if custom:
            return _sanitize_status(custom)
        try:
            idx = int(self.GetInt32(self.COMBO_STATUS))
        except Exception:
            idx = 0
        if 0 <= idx < len(STATUS_OPTIONS):
            return STATUS_OPTIONS[idx][1]
        return ""

    def _refresh_preview(self):
        """Update the 'Will save as: ...' label based on current status selection."""
        status = self._current_status()
        preview = preview_next_filename(self._doc, status=status) if self._doc else None
        if preview:
            self.SetString(self.LBL_INFO, f"Will save as:  {preview}")
        else:
            self.SetString(self.LBL_INFO, "Will save as:  scene_v001.c4d")

    def CreateLayout(self):
        self.SetTitle("Save Version")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)

        # Header: filename preview (updates on status change)
        self.AddStaticText(self.LBL_INFO, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddSeparatorH(6)

        # Status row: combo + custom
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 4, 0)
        self.GroupSpace(8, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Status:", 0)
        self.AddComboBox(self.COMBO_STATUS, c4d.BFH_LEFT, 180, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 80, 0, "Custom:", 0)
        self.AddEditText(self.EDT_CUSTOM, c4d.BFH_SCALEFIT, 100, 0)
        self.GroupEnd()

        self.AddSeparatorH(6)

        # Comment label + multiline input
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Comment (required):", 0)
        try:
            multiline_flags = c4d.DR_MULTILINE_WORDWRAP
        except AttributeError:
            multiline_flags = 0
        self.AddMultiLineEditText(
            self.EDT_COMMENT,
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
            440, 100,
            multiline_flags,
        )

        self.AddSeparatorH(6)

        # Run QC checkbox
        self.AddCheckbox(
            self.CHK_RUN_QC, c4d.BFH_LEFT, 0, 0,
            "Run quality checks and record QC score with this version"
        )

        self.AddSeparatorH(8)

        # Action buttons (right-aligned)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(self.BTN_SAVE, c4d.BFH_RIGHT, 110, 0, "Save Version")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        # Populate status combo
        for i, (label, _suffix) in enumerate(STATUS_OPTIONS):
            self.AddChild(self.COMBO_STATUS, i, label)
        self.SetInt32(self.COMBO_STATUS, 0)  # default: WIP
        self.SetString(self.EDT_CUSTOM, "")
        self.SetBool(self.CHK_RUN_QC, self._run_qc_default)
        self.SetString(self.EDT_COMMENT, "")
        self._refresh_preview()
        return True

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.confirmed = False
            self.Close()
            return True

        # Live preview update on status changes
        if cid in (self.COMBO_STATUS, self.EDT_CUSTOM):
            self._refresh_preview()
            return True

        if cid == self.BTN_SAVE:
            comment = (self.GetString(self.EDT_COMMENT) or "").strip()
            if not comment:
                c4d.gui.MessageDialog(
                    "Please enter a comment describing this version.\n\n"
                    "A short note like 'rim lights pass' or 'client feedback' is enough."
                )
                return True

            # Soft warning if user wrote 'final' in comment — should use status tag
            if "final" in comment.lower():
                c4d.gui.MessageDialog(
                    "Tip: instead of writing 'final' in the comment, use the\n"
                    "'Final Delivery' status tag — it bakes the marker into the\n"
                    "filename (e.g. scene_v007_FINAL.c4d) and the history log.\n\n"
                    "(continuing — your comment will be saved as-is)"
                )
                # Don't return — let the save proceed

            self.result_comment = comment
            self.result_run_qc = self.GetBool(self.CHK_RUN_QC)
            self.result_status = self._current_status()
            self.confirmed = True
            self.Close()
            return True

        return True


def smart_save_version(doc, comment, run_qc=True, artist_name="", status=None):
    """Save the document as a numbered version + append metadata to sidecar history.

    Args:
      status: optional review-status tag (e.g. 'TR', 'CR', 'FINAL', or any custom alphanumeric)
              -> appears as suffix _<STATUS> in filename. None or '' = no suffix (WIP).

    Returns a dict:
      { 'success': bool,
        'message': str,
        'path': str (new file path on success),
        'version': int (the version number written),
        'status': str ('' if WIP),
        'history_path': str,
        'qc_summary': dict | None,
      }
    """
    from datetime import datetime

    result = {"success": False, "message": "", "path": None, "version": None,
              "status": "", "history_path": None, "qc_summary": None}

    if not doc:
        result["message"] = "No active document"
        return result

    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""

    # Sanitize status — uppercase alphanumeric only
    clean_status = _sanitize_status(status) if status else ""

    # ── Resolve target folder + base name ──
    if not doc_path:
        # First-time save: ask the user where to put the scene
        suggested_base = os.path.splitext(doc_name)[0] if doc_name else "scene"
        suggested_base, _v, _s = parse_version_filename(suggested_base)
        if not suggested_base or suggested_base.lower().startswith("untitled"):
            suggested_base = "scene"
        suggested_filename = build_versioned_filename(suggested_base, 1, status=clean_status)

        save_path = None
        try:
            save_path = c4d.storage.SaveDialog(
                title="Save Versioned Scene (will be saved as scene_vNNN.c4d)",
                force_suffix="c4d",
                def_file=suggested_filename,
            )
        except TypeError:
            save_path = c4d.storage.SaveDialog(
                title="Save Versioned Scene",
                force_suffix="c4d",
            )

        if not save_path:
            result["message"] = "Save cancelled by user"
            return result

        folder = os.path.dirname(save_path)
        chosen_name = os.path.splitext(os.path.basename(save_path))[0]
        base, _user_ver, _user_status = parse_version_filename(chosen_name)
        if not base:
            base = "scene"
        next_version = 1  # always start fresh from v001 when first saving
    else:
        folder = doc_path
        full_doc_path = os.path.join(folder, doc_name) if doc_name else folder
        base, next_version = compute_next_version(full_doc_path)
        if not base:
            base = os.path.splitext(doc_name or "scene")[0] or "scene"

    # ── Build new filename + full path ──
    new_filename = build_versioned_filename(base, next_version, status=clean_status)
    new_path = os.path.join(folder, new_filename)

    # Refuse to overwrite an existing file (defensive — should not happen)
    if os.path.exists(new_path):
        result["message"] = f"Target already exists: {new_filename} (refusing to overwrite)"
        return result

    # ── Capture metadata BEFORE saving (so QC reflects pre-save state) ──
    qc_summary = _build_qc_summary(doc) if run_qc else None
    stats = get_scene_stats(doc) or {}
    active_take = ""
    try:
        td = doc.GetTakeData()
        if td:
            cur = td.GetCurrentTake()
            if cur:
                active_take = cur.GetName() or ""
    except Exception:
        pass

    # ── Save the document ──
    try:
        ok = c4d.documents.SaveDocument(
            doc,
            new_path,
            c4d.SAVEDOCUMENTFLAGS_NONE,
            c4d.FORMAT_C4DEXPORT,
        )
        if not ok:
            result["message"] = f"SaveDocument returned False (path: {new_path})"
            return result
    except Exception as e:
        result["message"] = f"Save error: {e}"
        return result

    # ── Update the active document's path/name so C4D's title bar + future
    # saves reflect the new versioned file (SaveDocument doesn't always
    # propagate this in C4D 2026). ──
    try:
        doc.SetDocumentPath(os.path.dirname(new_path))
        doc.SetDocumentName(os.path.basename(new_path))
        c4d.EventAdd()
    except Exception as e:
        safe_print(f"Could not update document path metadata: {e}")

    # ── Append history entry ──
    history_path = get_history_path(new_path)
    entry = {
        "version": next_version,
        "filename": new_filename,
        "path": new_path,
        "status": clean_status,           # NEW: review status tag
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "artist": artist_name or "",
        "comment": (comment or "").strip(),
        "active_take": active_take,
        "scene": base,
        "stats": stats,
    }
    if qc_summary:
        entry["qc_score"] = qc_summary["score"]
        entry["qc_pass"] = qc_summary["pass"]
        entry["qc_counts"] = qc_summary["counts"]

    appended = append_history_entry(history_path, entry)

    result.update({
        "success": True,
        "message": f"Saved {new_filename}" + (" (history updated)" if appended else " (history write failed)"),
        "path": new_path,
        "version": next_version,
        "status": clean_status,
        "history_path": history_path,
        "qc_summary": qc_summary,
    })
    return result


# ---------------- Scene Notes / TODO ----------------
# Pure helpers for managing per-scene notes + TODOs in a sidecar JSON
# (`<base>_notes.json`) — mirrors the Smart Save history pattern.

def get_notes_path(doc):
    """Return the path to the notes sidecar for the given doc, or None.

    Strips any `_v###[_status]` suffix so all versions of the same scene
    share one notes file (consistent with how history.json works).
    """
    if not doc:
        return None
    doc_path = doc.GetDocumentPath() or ""
    doc_name = doc.GetDocumentName() or ""
    if not doc_path or not doc_name:
        return None
    folder = doc_path
    name_no_ext = os.path.splitext(doc_name)[0]
    base, _ver, _status = parse_version_filename(name_no_ext)
    if not base:
        base = name_no_ext or "scene"
    return os.path.join(folder, f"{base}_notes.json")


def _empty_notes():
    """Return a fresh, valid notes dict with empty notes + empty todos list."""
    return {
        "scene": "",
        "updated": "",
        "notes": "",
        "todos": [],
    }


def load_notes(notes_path):
    """Load notes JSON. Always returns a valid dict (defaults if missing/malformed)."""
    default = _empty_notes()
    if not notes_path or not os.path.exists(notes_path):
        return default
    try:
        with open(notes_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        # Ensure required fields exist
        if "notes" not in data or not isinstance(data.get("notes"), str):
            data["notes"] = ""
        if "todos" not in data or not isinstance(data.get("todos"), list):
            data["todos"] = []
        if "scene" not in data:
            data["scene"] = ""
        if "updated" not in data:
            data["updated"] = ""
        return data
    except Exception as e:
        safe_print(f"Could not load notes: {e}")
        return default


def save_notes(notes_path, data):
    """Atomically write notes JSON. Stamps `updated` timestamp on save."""
    if not notes_path or data is None:
        return False
    from datetime import datetime
    try:
        if not isinstance(data, dict):
            return False
        # Normalize required fields
        data.setdefault("scene", "")
        data.setdefault("notes", "")
        data.setdefault("todos", [])
        data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(notes_path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        safe_print(f"Could not save notes: {e}")
        return False


def _next_todo_id(notes):
    """Compute the next TODO id (max existing + 1, starting at 1)."""
    todos = notes.get("todos") or []
    max_id = 0
    for t in todos:
        try:
            tid = int(t.get("id", 0))
            if tid > max_id:
                max_id = tid
        except Exception:
            pass
    return max_id + 1


def add_todo(notes, text):
    """Add a new TODO. Mutates and returns the notes dict for chaining.

    Returns the notes unchanged if text is empty/whitespace.
    """
    from datetime import datetime
    if not text or not text.strip():
        return notes
    if not isinstance(notes, dict):
        return notes
    notes.setdefault("todos", [])
    todo = {
        "id": _next_todo_id(notes),
        "text": text.strip(),
        "done": False,
        "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    notes["todos"].append(todo)
    return notes


def toggle_todo(notes, todo_id):
    """Flip the done state of a TODO by id. Returns True if changed, False if not found."""
    from datetime import datetime
    if not isinstance(notes, dict):
        return False
    for t in notes.get("todos", []):
        try:
            if int(t.get("id", 0)) == int(todo_id):
                new_state = not bool(t.get("done", False))
                t["done"] = new_state
                if new_state:
                    t["completed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    t.pop("completed", None)
                return True
        except Exception:
            continue
    return False


def delete_todo(notes, todo_id):
    """Remove a TODO by id. Returns True if removed, False if not found."""
    if not isinstance(notes, dict):
        return False
    todos = notes.get("todos") or []
    before = len(todos)
    notes["todos"] = [t for t in todos
                       if not (str(t.get("id", "")) == str(todo_id))]
    return len(notes["todos"]) < before


def summarize_notes(notes):
    """Return a one-line caption for the panel.

    Examples:
      "Notes: empty"
      "Notes: 3 TODOs (1 pending)"
      "Notes: text + 5 TODOs (all done)"
      "Notes: free-form notes"
    """
    if not isinstance(notes, dict):
        return "Notes: empty"
    has_text = bool((notes.get("notes") or "").strip())
    todos = notes.get("todos") or []
    n = len(todos)
    pending = sum(1 for t in todos if not t.get("done"))

    if not has_text and n == 0:
        return "Notes: empty"
    if has_text and n == 0:
        return "Notes: free-form notes"

    todo_part = f"{n} TODO" if n == 1 else f"{n} TODOs"
    if pending == 0:
        status = "all done"
    elif pending == n:
        status = f"{pending} pending"
    else:
        status = f"{pending} pending"
    pieces = []
    if has_text:
        pieces.append("text")
    pieces.append(f"{todo_part} ({status})")
    return "Notes: " + " + ".join(pieces)


def has_pending_todos(notes):
    """Return True if the notes contain any unfinished TODOs (used for color hint)."""
    if not isinstance(notes, dict):
        return False
    return any(not t.get("done") for t in (notes.get("todos") or []))


# ---------------- TodoArea (GeUserArea for the TODO list) ----------------
# Renders TODOs with checkbox + text + delete affordance. Two click zones per
# row: left (CHECKBOX_W px) toggles done; right (DELETE_W px) deletes.

_COL_TODO_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_TODO_ROW = c4d.Vector(0.14, 0.14, 0.14)
_COL_TODO_ROW_ALT = c4d.Vector(0.16, 0.16, 0.16)
_COL_TODO_TEXT = c4d.Vector(0.85, 0.85, 0.85)
_COL_TODO_TEXT_DONE = c4d.Vector(0.40, 0.40, 0.40)
_COL_TODO_CHECK = c4d.Vector(0.60, 0.60, 0.60)
_COL_TODO_CHECK_ON = c4d.Vector(0.30, 0.75, 0.35)
_COL_TODO_DELETE = c4d.Vector(0.55, 0.30, 0.30)


class TodoArea(gui.GeUserArea):
    """Custom-drawn TODO list with click zones for toggle and delete."""

    ROW_HEIGHT = 22
    ROW_PAD = 2
    CHECKBOX_W = 26          # left click zone width
    DELETE_W = 26            # right click zone width
    EMPTY_HEIGHT = 30

    def __init__(self):
        super().__init__()
        self.todos = []
        self.toggle_callback = None  # callable(todo_id)
        self.delete_callback = None  # callable(todo_id)
        self.font = c4d.FONT_DEFAULT

    def GetMinSize(self):
        n = len(self.todos)
        if n == 0:
            return 400, self.EMPTY_HEIGHT
        h = n * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 2
        return 400, h

    def set_todos(self, todos):
        self.todos = list(todos) if todos else []
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    def _y_to_index(self, y):
        try:
            y = int(y) - self.ROW_PAD
            if y < 0:
                return -1
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            idx = y // row_pixel
            if 0 <= idx < len(self.todos):
                return idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            idx = self._y_to_index(int(local_y))
            if idx < 0:
                return False
            todo = self.todos[idx]
            todo_id = todo.get("id")
            w = self.GetWidth()
            # Left zone → toggle
            if int(local_x) <= self.CHECKBOX_W and self.toggle_callback is not None:
                self.toggle_callback(todo_id)
                return True
            # Right zone → delete
            if int(local_x) >= w - self.DELETE_W and self.delete_callback is not None:
                self.delete_callback(todo_id)
                return True
            # Middle: also toggle (forgiving UX)
            if self.toggle_callback is not None:
                self.toggle_callback(todo_id)
                return True
        except Exception as e:
            safe_print(f"TodoArea.InputEvent error: {e}")
        return False

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_TODO_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self.todos:
                self.DrawSetTextCol(_COL_TODO_TEXT_DONE, _COL_TODO_BG)
                self.DrawText("No TODOs yet — add one below", 8, (h - 12) // 2)
                return

            x = self.ROW_PAD
            y = self.ROW_PAD
            for i, todo in enumerate(self.todos):
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                bg = _COL_TODO_ROW_ALT if (i % 2) else _COL_TODO_ROW
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top), int(w - self.ROW_PAD), int(row_bot))

                done = bool(todo.get("done"))
                text = todo.get("text", "") or ""
                text_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)

                # Checkbox
                cb_x = int(x + 6)
                cb_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)
                cb_size = 12
                # Outer box (frame)
                self.DrawSetPen(_COL_TODO_CHECK)
                self.DrawRectangle(cb_x, cb_y, cb_x + cb_size, cb_y + cb_size)
                # Inner fill (bg or checked)
                if done:
                    self.DrawSetPen(_COL_TODO_CHECK_ON)
                else:
                    self.DrawSetPen(bg)
                self.DrawRectangle(cb_x + 1, cb_y + 1, cb_x + cb_size - 1, cb_y + cb_size - 1)

                # Text
                text_x = int(x + self.CHECKBOX_W + 4)
                avail_w = w - self.CHECKBOX_W - self.DELETE_W - 12
                truncated = text
                try:
                    if int(self.DrawGetTextWidth(truncated)) > avail_w:
                        while truncated and int(self.DrawGetTextWidth(truncated + "...")) > avail_w:
                            truncated = truncated[:-1]
                        truncated = truncated + "..." if truncated != text else truncated
                except Exception:
                    if len(truncated) > 50:
                        truncated = truncated[:47] + "..."
                text_color = _COL_TODO_TEXT_DONE if done else _COL_TODO_TEXT
                self.DrawSetTextCol(text_color, bg)
                self.DrawText(truncated, text_x, text_y)

                # Delete affordance: × on the right
                del_x = int(w - self.DELETE_W + 8)
                self.DrawSetTextCol(_COL_TODO_DELETE, bg)
                self.DrawText("×", del_x, text_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"TodoArea.DrawMsg error: {e}")


# ---------------- NotesDialog (modal: free-form notes + TODO list) ----------------
class NotesDialog(gui.GeDialog):
    """Modal dialog for editing per-scene notes and TODOs.

    After Open(c4d.DLG_TYPE_MODAL), check `confirmed`. If True, read
    `result_notes` (a dict matching the load_notes shape).
    """

    EDT_NOTES = 1001
    AREA_TODOS = 1002
    EDT_NEW_TODO = 1003
    BTN_ADD_TODO = 1004
    BTN_CANCEL = 1005
    BTN_SAVE = 1006
    LBL_SUMMARY = 1007
    LBL_HINT = 1008

    def __init__(self, notes_data):
        super().__init__()
        # Work on a deep copy so Cancel discards changes
        import copy
        self._working = copy.deepcopy(notes_data) if notes_data else _empty_notes()
        self._working.setdefault("notes", "")
        self._working.setdefault("todos", [])
        self.todo_ua = TodoArea()
        self.confirmed = False
        self.result_notes = None

    def CreateLayout(self):
        scene_label = self._working.get("scene") or "scene"
        self.SetTitle(f"Scene Notes — {scene_label}  (shared across all versions)")

        self.GroupBegin(0, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(10, 10, 10, 10)
        self.GroupSpace(0, 6)

        # Summary line
        self.AddStaticText(self.LBL_SUMMARY, c4d.BFH_SCALEFIT, 0, 0, "", 0)

        # Hint: explains the model so users don't get confused about scope
        self.AddStaticText(
            self.LBL_HINT, c4d.BFH_SCALEFIT, 0, 0,
            "These notes apply to ALL versions of this scene. "
            "For version-specific commentary, use the Save Version comment field.",
            0
        )

        self.AddSeparatorH(4)

        # Notes section
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Notes (free-form):", 0)
        try:
            multiline_flags = c4d.DR_MULTILINE_WORDWRAP
        except AttributeError:
            multiline_flags = 0
        self.AddMultiLineEditText(
            self.EDT_NOTES,
            c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT,
            500, 130,
            multiline_flags,
        )

        self.AddSeparatorH(4)

        # TODOs list
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "TODOs (click to toggle, × to delete):", 0)
        self.AddUserArea(self.AREA_TODOS, c4d.BFH_SCALEFIT | c4d.BFV_FIT, 0, TodoArea.EMPTY_HEIGHT)
        self.AttachUserArea(self.todo_ua, self.AREA_TODOS)

        # Add new TODO row
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddEditText(self.EDT_NEW_TODO, c4d.BFH_SCALEFIT, 0, 0)
        self.AddButton(self.BTN_ADD_TODO, c4d.BFH_RIGHT, 80, 0, "+ Add")
        self.GroupEnd()

        self.AddSeparatorH(8)

        # Action buttons (right-aligned)
        self.GroupBegin(0, c4d.BFH_RIGHT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddButton(self.BTN_CANCEL, c4d.BFH_RIGHT, 90, 0, "Cancel")
        self.AddButton(self.BTN_SAVE, c4d.BFH_RIGHT, 90, 0, "Save")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        self.SetString(self.EDT_NOTES, self._working.get("notes", "") or "")
        self.SetString(self.EDT_NEW_TODO, "")
        # Wire TodoArea callbacks (after Attach)
        self.todo_ua.toggle_callback = self._on_toggle_todo
        self.todo_ua.delete_callback = self._on_delete_todo
        self._refresh_todos()
        self._update_summary()
        return True

    def _refresh_todos(self):
        self.todo_ua.set_todos(self._working.get("todos", []))

    def _update_summary(self):
        # Pull live notes text from the edit field so summary reflects what user typed
        live = dict(self._working)
        live["notes"] = self.GetString(self.EDT_NOTES) or ""
        self.SetString(self.LBL_SUMMARY, summarize_notes(live))

    def _on_toggle_todo(self, todo_id):
        if toggle_todo(self._working, todo_id):
            self._refresh_todos()
            self._update_summary()

    def _on_delete_todo(self, todo_id):
        if delete_todo(self._working, todo_id):
            self._refresh_todos()
            self._update_summary()

    def Command(self, cid, msg):
        if cid == self.BTN_CANCEL:
            self.confirmed = False
            self.Close()
            return True

        if cid == self.BTN_ADD_TODO:
            text = (self.GetString(self.EDT_NEW_TODO) or "").strip()
            if text:
                add_todo(self._working, text)
                self.SetString(self.EDT_NEW_TODO, "")
                self._refresh_todos()
                self._update_summary()
            return True

        if cid == self.EDT_NOTES:
            # Live summary update as user types (cheap)
            self._update_summary()
            return True

        if cid == self.EDT_NEW_TODO:
            return True  # no-op; pressing Enter doesn't auto-add (avoid surprise)

        if cid == self.BTN_SAVE:
            # Pull notes text + return the working copy
            self._working["notes"] = (self.GetString(self.EDT_NOTES) or "").strip()
            self.result_notes = self._working
            self.confirmed = True
            self.Close()
            return True

        return True


# ---------------- Scene Collector ----------------
def collect_scene(doc, artist_name):
    """Pre-flight QC + Save Project with Assets + Verify + Manifest"""
    from datetime import datetime

    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    doc_path = doc.GetDocumentPath()
    if not doc_path:
        c4d.gui.MessageDialog("Please save the scene first before collecting.")
        return

    # Capture original metadata BEFORE SaveProject runs — SaveProject changes
    # the doc's path/name to the delivery folder, losing the original identity.
    original_doc_name = doc.GetDocumentName() or "scene.c4d"
    original_name_no_ext = os.path.splitext(original_doc_name)[0]
    original_base, original_version_int, original_status = parse_version_filename(original_name_no_ext)
    if not original_base:
        original_base = original_name_no_ext
    # The "clean" delivery name strips _v###[_status] — pure scene identity.
    delivery_filename = f"{original_base}.c4d"

    # Capture the notes sidecar path/data BEFORE SaveProject so we don't lose them.
    original_notes_path = get_notes_path(doc)
    original_notes_data = None
    if original_notes_path and os.path.exists(original_notes_path):
        try:
            original_notes_data = load_notes(original_notes_path)
        except Exception as e:
            safe_print(f"Scene Collector: Could not pre-load notes: {e}")

    # ── Phase 1: Pre-flight QC ──
    safe_print("Scene Collector: Running pre-flight checks...")

    issues = []
    lights = check_lights(doc)
    if lights:
        issues.append(f"  {len(lights)} lights outside group")
    vis = check_visibility_traps(doc)
    if vis:
        issues.append(f"  {len(vis)} visibility mismatches")
    textures = check_textures_unified(doc)
    if textures:
        issues.append(f"  {len(textures)} asset path issues")
    unused = check_unused_materials(doc)
    if unused:
        issues.append(f"  {len(unused)} unused materials")
    names = check_default_names(doc)
    if names:
        issues.append(f"  {len(names)} objects with default names")
    takes = check_takes(doc)
    if takes:
        issues.append(f"  {len(takes)} take issues")
    output = check_output_paths(doc)
    if output:
        issues.append(f"  {len(output)} output path issues")

    # Show pre-flight results
    if issues:
        msg = f"PRE-FLIGHT: {len(issues)} issue(s) found\n\n"
        msg += "\n".join(issues)
        msg += "\n\nFix issues before collecting?"
        msg += "\n\nYes = Fix auto-fixable issues, then collect"
        msg += "\nNo = Collect anyway"

        # 3-way: fix + collect, collect anyway, cancel
        result = c4d.gui.MessageDialog(msg, c4d.GEMB_YESNOCANCEL)
        if result == c4d.GEMB_R_CANCEL:
            safe_print("Scene Collector: Cancelled")
            return
        if result == c4d.GEMB_R_YES:
            # Auto-fix what we can
            fixed = 0
            if lights:
                fixed += fix_lights(doc, lights)
            if unused:
                fixed += fix_unused_materials(doc, unused)
            cam_bad = check_camera_shift(doc)
            if cam_bad:
                fixed += fix_camera_shift(doc, cam_bad)
            safe_print(f"Scene Collector: Auto-fixed {fixed} issues")
    else:
        if not c4d.gui.QuestionDialog("Pre-flight: All checks passed!\n\nProceed with Save Project with Assets?"):
            return

    # ── Phase 2: Collect via C4D native ──
    safe_print("Scene Collector: Running Save Project with Assets...")

    target_dir = c4d.storage.LoadDialog(
        title="Select folder to collect project into",
        flags=c4d.FILESELECT_DIRECTORY
    )
    if not target_dir:
        safe_print("Scene Collector: No folder selected")
        return

    assets = []
    missing_assets = []

    try:
        flags = (c4d.SAVEPROJECT_ASSETS |
                 c4d.SAVEPROJECT_SCENEFILE |
                 c4d.SAVEPROJECT_PROGRESSALLOWED |
                 c4d.SAVEPROJECT_DONTFAILONMISSINGASSETS)

        result = c4d.documents.SaveProject(doc, flags, target_dir, assets, missing_assets)

        if not result:
            c4d.gui.MessageDialog("Save Project failed!\n\nCheck console for details.")
            safe_print("Scene Collector: SaveProject returned False")
            return

    except Exception as e:
        c4d.gui.MessageDialog(f"Save Project error:\n{e}")
        safe_print(f"Scene Collector error: {e}")
        return

    safe_print(f"Scene Collector: Collected {len(assets)} assets")
    if missing_assets:
        safe_print(f"Scene Collector: {len(missing_assets)} missing assets!")

    # ── Phase 2.5: Rename the saved file to the clean delivery name ──
    # C4D's SaveProject saves to <target_dir>/<folder_basename>.c4d. We rename
    # it to the clean original scene base (stripped of _v### suffix) so the
    # delivery has a clean identity matching the notes sidecar naming.
    saved_folder_basename = os.path.basename(target_dir.rstrip(os.sep)) + ".c4d"
    saved_at = os.path.join(target_dir, saved_folder_basename)
    desired_at = os.path.join(target_dir, delivery_filename)

    if saved_at != desired_at:
        if os.path.exists(saved_at):
            try:
                if os.path.exists(desired_at):
                    # Defensive: refuse to overwrite an existing file
                    safe_print(f"Scene Collector: refused to overwrite existing {delivery_filename}")
                else:
                    os.rename(saved_at, desired_at)
                    safe_print(f"Scene Collector: Renamed {saved_folder_basename} -> {delivery_filename}")
                    # Update the active doc's identity so the panel + future Cmd+S
                    # reflect the renamed file
                    try:
                        doc.SetDocumentPath(target_dir)
                        doc.SetDocumentName(delivery_filename)
                        c4d.EventAdd()
                    except Exception as e:
                        safe_print(f"Scene Collector: Could not update doc metadata: {e}")
            except Exception as e:
                safe_print(f"Scene Collector: Could not rename to delivery name: {e}")
        else:
            safe_print(f"Scene Collector: expected file {saved_folder_basename} not found after SaveProject")

    # ── Phase 3: Generate manifest ──
    safe_print("Scene Collector: Generating manifest...")

    manifest = {
        "sentinel_manifest": True,
        "version": PLUGIN_NAME,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # Delivery identity (clean name, what the receiver sees)
        "scene": delivery_filename,
        # Original version metadata (traceability — where this came from)
        "original_filename": original_doc_name,
        "original_version": original_version_int,
        "original_status": (original_status or ""),
        "artist": artist_name or "",
        "shot_id": "",
        "collected_to": target_dir,
        "assets_collected": len(assets),
        "assets_missing": len(missing_assets),
        "missing_list": [],
        "pre_flight_issues": issues,
    }

    # Get shot ID
    try:
        td = doc.GetTakeData()
        if td:
            main_take = td.GetMainTake()
            if main_take:
                manifest["shot_id"] = main_take.GetName() or ""
    except Exception:
        pass

    # Log missing assets
    for m in missing_assets:
        try:
            manifest["missing_list"].append(str(m))
        except Exception:
            pass

    # Calculate total size
    total_size = 0
    for a in assets:
        try:
            filepath = str(a.get("filename", ""))
            if filepath and os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
        except Exception:
            pass
    manifest["total_size_mb"] = round(total_size / (1024 * 1024), 1)

    # ── Include scene notes + TODOs in manifest (and copy sidecar to delivery) ──
    # Uses original_notes_path/data captured before SaveProject moved the doc.
    if original_notes_data is not None:
        manifest["notes"] = {
            "summary": summarize_notes(original_notes_data),
            "text": original_notes_data.get("notes", "") or "",
            "todos": original_notes_data.get("todos", []) or [],
            "pending_count": sum(1 for t in (original_notes_data.get("todos") or []) if not t.get("done")),
            "updated": original_notes_data.get("updated", ""),
        }
        # Also copy the sidecar file alongside the .c4d so it travels with delivery
        if original_notes_path:
            try:
                import shutil
                shutil.copy2(original_notes_path, target_dir)
                safe_print(f"Scene Collector: Notes sidecar copied to delivery: {os.path.basename(original_notes_path)}")
            except Exception as e:
                safe_print(f"Scene Collector: Could not copy notes sidecar: {e}")
    else:
        manifest["notes"] = {"summary": "Notes: empty", "text": "", "todos": [], "pending_count": 0}

    # Save manifest
    manifest_path = os.path.join(target_dir, "sentinel_manifest.json")
    try:
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        safe_print(f"Scene Collector: Manifest saved to {manifest_path}")
    except Exception as e:
        safe_print(f"Scene Collector: Could not save manifest: {e}")

    # ── Summary ──
    msg = f"Scene Collected!\n\n"
    msg += f"Location: {target_dir}\n"
    msg += f"Assets: {len(assets)} collected"
    if missing_assets:
        msg += f"\nMissing: {len(missing_assets)} (check manifest)"
    msg += f"\nSize: {manifest['total_size_mb']} MB"
    msg += f"\nManifest: sentinel_manifest.json"
    notes_pending = manifest.get("notes", {}).get("pending_count", 0)
    if notes_pending:
        msg += f"\n⚠ {notes_pending} pending TODO(s) in scene notes"

    c4d.gui.MessageDialog(msg)
    safe_print("Scene Collector: Complete")

# ---------------- UI StatusArea ----------------
# Pre-allocated colors to avoid GC pressure in DrawMsg
_COL_GREEN = c4d.Vector(0.3, 1, 0.3)
_COL_RED = c4d.Vector(1, 0.3, 0.3)
_COL_YELLOW = c4d.Vector(1, 1, 0.3)
_COL_GRAY = c4d.Vector(0.5, 0.5, 0.5)
_COL_BG = c4d.Vector(0.08, 0.08, 0.08)
_COL_BLACK = c4d.Vector(0, 0, 0)
_COL_BG_OK = c4d.Vector(0.15, 0.15, 0.15)
_COL_BG_WARN = c4d.Vector(0.25, 0.20, 0.10)
_COL_BG_FAIL = c4d.Vector(0.25, 0.10, 0.10)


# Helper: convert msg[BFM_INPUT_X/Y] (window-global in C4D 2026 Python) to
# user-area-local coordinates. GeUserArea.Local2Global() with NO args returns
# the user area's window origin as {'x': ..., 'y': ...}. Subtracting that from
# the raw msg coords gives correct local coords. Verified empirically — the
# documented Global2Local(x, y) does NOT return area-local in C4D 2026.
def _ua_local_coords(user_area, mx, my):
    """Return (local_x, local_y) for a window-global click on the given GeUserArea."""
    try:
        origin = user_area.Local2Global()
    except Exception:
        return mx, my
    try:
        if isinstance(origin, dict):
            ox = origin.get("x", 0)
            oy = origin.get("y", 0)
        else:
            ox, oy = origin[0], origin[1]
        return int(mx) - int(ox), int(my) - int(oy)
    except Exception:
        return mx, my

# Score header colors (lighter palette for the badge area)
_COL_SCORE_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_SCORE_GREEN = c4d.Vector(0.30, 0.80, 0.40)
_COL_SCORE_YELLOW = c4d.Vector(0.95, 0.75, 0.25)
_COL_SCORE_RED = c4d.Vector(0.90, 0.35, 0.35)
_COL_SCORE_TRACK = c4d.Vector(0.20, 0.20, 0.20)
_COL_SCORE_TEXT = c4d.Vector(0.95, 0.95, 0.95)
_COL_SCORE_TEXT_DIM = c4d.Vector(0.60, 0.60, 0.60)


class ScoreHeader(gui.GeUserArea):
    """Visual summary header: progress bar + pass count + scene stats — single line."""

    HEIGHT = 26

    def __init__(self):
        super().__init__()
        self.passed = 0
        self.total = 0
        self.stats_text = ""

    def GetMinSize(self):
        return 400, self.HEIGHT

    def set_state(self, passed, total, stats_text):
        self.passed = max(0, int(passed))
        self.total = max(1, int(total))
        self.stats_text = stats_text or ""
        self.Redraw()

    def _measure(self, text):
        try:
            return int(self.DrawGetTextWidth(text))
        except Exception:
            return len(text) * 6

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            # Background
            self.DrawSetPen(_COL_SCORE_BG)
            self.DrawRectangle(0, 0, w, h)

            # Status color/label
            ratio = self.passed / self.total if self.total > 0 else 0.0
            if ratio >= 0.999:
                bar_color = _COL_SCORE_GREEN
                status_label = "PASS"
            elif ratio >= 0.7:
                bar_color = _COL_SCORE_YELLOW
                status_label = "WARN"
            else:
                bar_color = _COL_SCORE_RED
                status_label = "FAIL"

            # Single-line vertical centering
            text_h = 12
            text_y = (h - text_h) // 2
            bar_h = 6
            bar_y = (h - bar_h) // 2

            margin = 8
            try:
                self.DrawSetFont(c4d.FONT_BOLD)
            except Exception:
                pass

            # 1. "QC X/Y" label (left)
            qc_label = f"QC {self.passed}/{self.total}"
            self.DrawSetTextCol(_COL_SCORE_TEXT, _COL_SCORE_BG)
            self.DrawText(qc_label, margin, text_y)
            qc_w = self._measure(qc_label)

            # 2. Status word right after
            status_x = margin + qc_w + 10
            self.DrawSetTextCol(bar_color, _COL_SCORE_BG)
            self.DrawText(status_label, status_x, text_y)
            status_w = self._measure(status_label)

            try:
                self.DrawSetFont(c4d.FONT_DEFAULT)
            except Exception:
                pass

            # 3. Stats text (right-aligned, dim grey) — measure FIRST to reserve space
            stats_x_start = w - margin
            if self.stats_text:
                tx_w = self._measure(self.stats_text)
                stats_x_start = w - margin - tx_w
                self.DrawSetTextCol(_COL_SCORE_TEXT_DIM, _COL_SCORE_BG)
                self.DrawText(self.stats_text, stats_x_start, text_y)

            # 4. Progress bar fills the middle space between status and stats
            bar_x_start = status_x + status_w + 12
            bar_x_end = stats_x_start - 12

            if bar_x_end > bar_x_start + 20:
                self.DrawSetPen(_COL_SCORE_TRACK)
                self.DrawRectangle(bar_x_start, bar_y, bar_x_end, bar_y + bar_h)
                if ratio > 0:
                    fill_w = max(2, int((bar_x_end - bar_x_start) * ratio))
                    self.DrawSetPen(bar_color)
                    self.DrawRectangle(bar_x_start, bar_y, bar_x_start + fill_w, bar_y + bar_h)

        except Exception as e:
            safe_print(f"Error in ScoreHeader.DrawMsg: {e}")


# Check display config: (severity, ok_message, fail_template, name_key_for_first)
_CHECK_DISPLAY = {
    "lights":      ("FAIL", "All lights properly organized", "{n} lights outside lights group", None),
    "vis":         ("WARN", "Visibility settings consistent", "Visibility mismatch on '{first}'", "vis_names"),
    "keys":        ("WARN", "Keyframes properly configured", "Multi-axis keys on '{first}'", "keys_names"),
    "cam":         ("FAIL", "Camera shifts at 0%", "{n} camera(s) with non-zero shift", None),
    "rdc":         ("FAIL", "Render presets compliant", "{n} non-standard render preset(s)", None),
    "textures":    ("FAIL", "All assets OK", "{n} asset issue(s)", None),
    "unused_mats": ("WARN", "All materials assigned", "{n} unused material(s)", None),
    "names":       ("WARN", "All objects named", "Default name '{first}'", "names_list"),
    "output":      ("FAIL", "Output paths configured", "{n} output path issue(s)", None),
    "takes":       ("FAIL", "Takes configured", "{n} take issue(s)", None),
    "fps_range":   ("FAIL", "FPS & frame range OK", "{n} FPS/range issue(s)", None),
}

class StatusArea(gui.GeUserArea):
    # Row order matches DrawMsg iteration; index here = clickable row index
    ROW_KEYS = ["lights", "vis", "keys", "cam", "rdc", "textures",
                "unused_mats", "names", "output", "takes", "fps_range"]

    def __init__(self):
        super().__init__()
        self.data = {}
        self.show = {k: True for k in _CHECK_DISPLAY}
        self.pad = 3
        self.rowh = 20
        self.font = c4d.FONT_MONOSPACED
        self.last_draw_time = 0
        self.min_draw_interval = 0.05
        # Click interaction (hover not supported: C4D 2026 Python does not route
        # BFM_GETCURSORINFO to embedded GeUserAreas)
        self.click_callback = None  # set by parent dialog: callable(row_key)

    def GetMinSize(self):
        rows = sum(1 for _, v in self.show.items() if v)
        return 400, max(1, rows) * (self.rowh + self.pad) + self.pad + 4

    def set_state(self, data, show):
        self.data = data or {}
        self.show = show or self.show

        # Throttle redraws
        now = time.time()
        if now - self.last_draw_time > self.min_draw_interval:
            self.Redraw()
            self.last_draw_time = now

    # ---- mouse interaction ----
    def _y_to_row(self, y):
        """Map y coordinate (local) to a visible row index, or -1 if outside."""
        try:
            y = int(y) - self.pad
            if y < 0:
                return -1
            row_pixel = self.rowh + self.pad
            visible_idx = y // row_pixel
            visible_keys = [k for k in self.ROW_KEYS if self.show.get(k, False)]
            if 0 <= visible_idx < len(visible_keys):
                return visible_idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        """Handle clicks. Called by C4D on mouse interaction over the GeUserArea."""
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            row = self._y_to_row(int(local_y))
            if row >= 0 and self.click_callback is not None:
                visible_keys = [k for k in self.ROW_KEYS if self.show.get(k, False)]
                if row < len(visible_keys):
                    self.click_callback(visible_keys[row])
                    return True
        except Exception as e:
            safe_print(f"StatusArea.InputEvent error: {e}")
        return False

    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            x = self.pad
            y = self.pad

            for label, key in [("Lights","lights"), ("Visibility","vis"), ("Keyframes","keys"),
                               ("Cameras","cam"), ("Presets","rdc"), ("Assets","textures"),
                               ("Materials","unused_mats"), ("Naming","names"), ("Output","output"),
                               ("Takes","takes"), ("FPS/Range","fps_range")]:
                if not self.show.get(key, False):
                    continue

                val = int(self.data.get(key, 0))
                cfg = _CHECK_DISPLAY.get(key)
                if not cfg:
                    continue

                severity, ok_msg, fail_tpl, name_key = cfg

                if val > 0:
                    status = f"[{severity}]"
                    first = ""
                    if name_key:
                        names = self.data.get(name_key, [])
                        first = names[0] if names else "object"
                    message = fail_tpl.format(n=val, first=first)
                    if name_key and val > 1:
                        message += f" (+{val-1} more)"
                    text_col = _COL_RED if severity == "FAIL" else _COL_YELLOW
                    bg = _COL_BG_FAIL if severity == "FAIL" else _COL_BG_WARN
                else:
                    status = "[ OK ]"
                    message = ok_msg
                    text_col = _COL_GREEN
                    bg = _COL_BG_OK

                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(y), int(w - self.pad), int(y + self.rowh))

                text_y = int(y + (self.rowh - 12) // 2)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(status, int(x + 5), text_y)

                self.DrawSetTextCol(_COL_GRAY, _COL_BLACK)
                self.DrawText(f"{label.ljust(13)}:", int(x + 55), text_y)

                self.DrawSetTextCol(text_col, _COL_BLACK)
                self.DrawText(message, int(x + 175), text_y)

                y += self.rowh + self.pad

        except Exception as e:
            safe_print(f"Error in DrawMsg: {e}")


# ---------------- Browse Versions UserArea ----------------
# Color palette for status badges (subtle backgrounds, ~70% saturation)
_COL_BADGE_WIP = c4d.Vector(0.35, 0.35, 0.35)        # neutral grey
_COL_BADGE_TR = c4d.Vector(0.55, 0.42, 0.18)         # amber
_COL_BADGE_CR = c4d.Vector(0.20, 0.40, 0.65)         # blue
_COL_BADGE_FINAL = c4d.Vector(0.25, 0.55, 0.30)      # green
_COL_BADGE_CUSTOM = c4d.Vector(0.45, 0.30, 0.55)     # purple

_COL_HISTORY_BG = c4d.Vector(0.10, 0.10, 0.10)
_COL_HISTORY_ROW_BG = c4d.Vector(0.14, 0.14, 0.14)
_COL_HISTORY_ROW_ALT = c4d.Vector(0.16, 0.16, 0.16)
_COL_HISTORY_TEXT = c4d.Vector(0.85, 0.85, 0.85)
_COL_HISTORY_DIM = c4d.Vector(0.55, 0.55, 0.55)


def _badge_color_for_status(status):
    """Pick the badge background color for a status string."""
    s = (status or "").upper()
    if s == "" or s == "WIP":
        return _COL_BADGE_WIP
    if s == "TR":
        return _COL_BADGE_TR
    if s == "CR":
        return _COL_BADGE_CR
    if s == "FINAL":
        return _COL_BADGE_FINAL
    return _COL_BADGE_CUSTOM


class HistoryArea(gui.GeUserArea):
    """Custom-drawn list of recent versions. One row per entry, status-coded badges.

    set_entries(entries) updates the list. click_callback(entry_dict) fires on row click.
    """

    ROW_HEIGHT = 22
    ROW_PAD = 2
    EMPTY_HEIGHT = 28

    def __init__(self):
        super().__init__()
        self.entries = []                # list of formatted dicts (output of format_version_row)
        self.click_callback = None       # callable(entry_dict)
        self.empty_msg = "No versions yet"
        self.font = c4d.FONT_DEFAULT

    def GetMinSize(self):
        rows = max(1, len(self.entries))
        h = rows * (self.ROW_HEIGHT + self.ROW_PAD) + self.ROW_PAD + 2
        if not self.entries:
            h = self.EMPTY_HEIGHT
        return 400, h

    def set_entries(self, entries):
        self.entries = list(entries) if entries else []
        try:
            self.LayoutChanged()
        except Exception:
            pass
        self.Redraw()

    # ── click detection ─────────────────────────────
    def _y_to_index(self, y):
        try:
            y = int(y) - self.ROW_PAD
            if y < 0:
                return -1
            row_pixel = self.ROW_HEIGHT + self.ROW_PAD
            idx = y // row_pixel
            if 0 <= idx < len(self.entries):
                return idx
        except Exception:
            pass
        return -1

    def InputEvent(self, msg):
        try:
            device = msg[c4d.BFM_INPUT_DEVICE]
            channel = msg[c4d.BFM_INPUT_CHANNEL]
            if device != c4d.BFM_INPUT_MOUSE or channel != c4d.BFM_INPUT_MOUSELEFT:
                return False
            mx = int(msg[c4d.BFM_INPUT_X])
            my = int(msg[c4d.BFM_INPUT_Y])
            local_x, local_y = _ua_local_coords(self, mx, my)
            idx = self._y_to_index(int(local_y))
            if idx >= 0 and self.click_callback is not None:
                self.click_callback(self.entries[idx])
                return True
        except Exception as e:
            safe_print(f"HistoryArea.InputEvent error: {e}")
        return False

    # ── drawing ─────────────────────────────────────
    def DrawMsg(self, x1, y1, x2, y2, msg):
        try:
            self.OffScreenOn()
            w = self.GetWidth()
            h = self.GetHeight()

            self.DrawSetPen(_COL_HISTORY_BG)
            self.DrawRectangle(0, 0, w, h)

            try:
                self.DrawSetFont(self.font)
            except Exception:
                pass

            if not self.entries:
                # Empty state
                self.DrawSetTextCol(_COL_HISTORY_DIM, _COL_HISTORY_BG)
                self.DrawText(self.empty_msg, 8, (h - 12) // 2)
                return

            # Layout: [v###] [BADGE] [comment............] [QC] [time]
            COL_VER_W = 50
            COL_BADGE_W = 50
            COL_QC_W = 50
            COL_TIME_W = 70
            margin = 6

            x = self.ROW_PAD
            y = self.ROW_PAD

            for i, entry in enumerate(self.entries):
                row_top = y
                row_bot = y + self.ROW_HEIGHT
                # Alternating row background
                bg = _COL_HISTORY_ROW_ALT if (i % 2) else _COL_HISTORY_ROW_BG
                self.DrawSetPen(bg)
                self.DrawRectangle(int(x), int(row_top), int(w - self.ROW_PAD), int(row_bot))

                text_y = int(row_top + (self.ROW_HEIGHT - 12) // 2)
                cx = int(x + margin)

                # Version label
                self.DrawSetTextCol(_COL_HISTORY_TEXT, bg)
                self.DrawText(entry.get("version_label", "v???"), cx, text_y)
                cx += COL_VER_W

                # Status badge — colored rect with status text inside
                status = entry.get("status_label", "WIP")
                badge_col = _badge_color_for_status(status)
                badge_x0 = cx
                badge_x1 = cx + COL_BADGE_W - 6
                badge_y0 = row_top + 4
                badge_y1 = row_bot - 4
                self.DrawSetPen(badge_col)
                self.DrawRectangle(int(badge_x0), int(badge_y0), int(badge_x1), int(badge_y1))
                # Center the text inside the badge
                try:
                    txt_w = int(self.DrawGetTextWidth(status))
                except Exception:
                    txt_w = len(status) * 6
                badge_text_x = int(badge_x0 + ((badge_x1 - badge_x0) - txt_w) // 2)
                self.DrawSetTextCol(c4d.Vector(1, 1, 1), badge_col)
                self.DrawText(status, badge_text_x, text_y)
                cx += COL_BADGE_W

                # Time (right-aligned)
                tx_right = w - margin
                time_label = entry.get("time_label", "")
                if time_label:
                    try:
                        tw = int(self.DrawGetTextWidth(time_label))
                    except Exception:
                        tw = len(time_label) * 6
                    self.DrawSetTextCol(_COL_HISTORY_DIM, bg)
                    self.DrawText(time_label, int(tx_right - tw), text_y)
                    tx_right -= (tw + margin * 2)

                # QC label (just left of time, if present)
                qc_label = entry.get("qc_label", "")
                if qc_label:
                    try:
                        qw = int(self.DrawGetTextWidth(qc_label))
                    except Exception:
                        qw = len(qc_label) * 6
                    qc_color = _COL_HISTORY_DIM
                    qc_pass = entry.get("qc_pass")
                    if qc_pass is True:
                        qc_color = _COL_GREEN
                    elif qc_pass is False:
                        qc_color = _COL_YELLOW
                    self.DrawSetTextCol(qc_color, bg)
                    self.DrawText(qc_label, int(tx_right - qw), text_y)
                    tx_right -= (qw + margin * 2)

                # Comment (fills remaining space — may need truncation)
                comment = entry.get("comment", "")
                if comment:
                    avail_w = max(20, tx_right - cx - margin)
                    # Crude truncation: clip if too long
                    truncated = comment
                    try:
                        full_w = int(self.DrawGetTextWidth(truncated))
                        if full_w > avail_w:
                            # binary chop
                            while truncated and int(self.DrawGetTextWidth(truncated + "...")) > avail_w:
                                truncated = truncated[:-1]
                            truncated = truncated + "..." if truncated != comment else truncated
                    except Exception:
                        if len(truncated) > 60:
                            truncated = truncated[:57] + "..."
                    self.DrawSetTextCol(_COL_HISTORY_TEXT, bg)
                    self.DrawText(f'"{truncated}"', cx, text_y)

                y += self.ROW_HEIGHT + self.ROW_PAD

        except Exception as e:
            safe_print(f"Error in HistoryArea.DrawMsg: {e}")


# ---------------- Snapshot Handler ----------------
# ---------------- Snapshot System (cross-platform) ----------------

def _get_stills_dir(doc, artist_name):
    """Get output directory: project_root/output/stills/Artist/YYMMDD/"""
    from datetime import datetime
    doc_path = doc.GetDocumentPath() or ""
    if doc_path:
        project_root = os.path.dirname(os.path.dirname(doc_path))
    else:
        project_root = os.path.join(os.path.expanduser("~"), "YS_Guardian_Output")

    output_dir = os.path.join(
        project_root, "output", "stills",
        artist_name or "Unknown",
        datetime.now().strftime("%y%m%d")
    )
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def _find_latest_exr():
    """Find the most recent EXR in the RS snapshot directory"""
    snap_dir = GlobalSettings.get_snapshot_dir()
    if not os.path.exists(snap_dir):
        return None, f"Snapshot directory not found:\n{snap_dir}\n\nConfigure it in Redshift RenderView > Preferences > Snapshots"

    exr_files = []
    for f in os.listdir(snap_dir):
        if f.lower().endswith('.exr'):
            full = os.path.join(snap_dir, f)
            exr_files.append((full, os.path.getmtime(full)))

    if not exr_files:
        return None, f"No EXR snapshots found in:\n{snap_dir}\n\nTake a snapshot in RS RenderView first."

    exr_files.sort(key=lambda x: x[1], reverse=True)
    return exr_files[0][0], None

def _find_system_python():
    """Find a system Python 3 with OpenEXR support (cross-platform)"""
    import subprocess

    candidates = []
    if sys.platform == "darwin":
        candidates = ["/usr/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3"]
    else:
        import glob
        candidates = ["python", "python3"]
        for pattern in [r"C:\Program Files\Python*\python.exe",
                        r"C:\Program Files (x86)\Python*\python.exe"]:
            candidates.extend(glob.glob(pattern))
        user_local = os.path.expanduser("~")
        for pattern in [os.path.join(user_local, r"AppData\Local\Programs\Python\Python*\python.exe")]:
            candidates.extend(glob.glob(pattern))

    for py in candidates:
        try:
            result = subprocess.run(
                [py, "-c", "import OpenEXR, numpy, PIL; print('OK')"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and "OK" in result.stdout:
                safe_print(f"Found system Python with OpenEXR: {py}")
                return py
        except Exception:
            continue

    return None

_CACHED_PYTHON = None

def _convert_exr_to_png(exr_path, png_path):
    """Convert EXR to PNG via external Python with OpenEXR + ACES pipeline"""
    import subprocess

    global _CACHED_PYTHON
    if not _CACHED_PYTHON:
        _CACHED_PYTHON = _find_system_python()

    if not _CACHED_PYTHON:
        return False, ("System Python with OpenEXR not found.\n\n"
                       "Install dependencies:\n"
                       "  pip3 install OpenEXR numpy Pillow")

    # Use the existing external converter script
    converter = os.path.join(os.path.dirname(__file__), "exr_converter_external.py")
    if not os.path.exists(converter):
        return False, f"Converter script not found: {converter}"

    try:
        result = subprocess.run(
            [_CACHED_PYTHON, converter, exr_path, png_path, "aces"],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode == 0 and os.path.exists(png_path):
            safe_print(f"Conversion complete: {os.path.basename(png_path)}")
            return True, None
        else:
            error = result.stderr or result.stdout or "Unknown error"
            safe_print(f"Converter error: {error}")
            return False, f"Conversion failed:\n{error[:300]}"

    except subprocess.TimeoutExpired:
        return False, "Conversion timed out (>120s)"
    except Exception as e:
        return False, f"Error running converter: {e}"

def snapshot_save_still(doc, artist_name):
    """Main entry point: find latest EXR, convert with ACES, save to project"""
    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return

    # Find latest EXR
    exr_path, error = _find_latest_exr()
    if not exr_path:
        c4d.gui.MessageDialog(error)
        return

    # Build output path
    output_dir = _get_stills_dir(doc, artist_name)
    doc_name = doc.GetDocumentName() or "untitled"
    scene_name = os.path.splitext(doc_name)[0]
    png_path = os.path.join(output_dir, f"{scene_name}.png")

    safe_print(f"Converting {os.path.basename(exr_path)} -> {png_path}")

    # Convert
    success, error = _convert_exr_to_png(exr_path, png_path)
    if not success:
        c4d.gui.MessageDialog(f"Conversion failed:\n{error}")
        return

    # Show in Picture Viewer
    bmp = c4d.bitmaps.BaseBitmap()
    if bmp.InitWith(png_path)[0] == c4d.IMAGERESULT_OK:
        c4d.bitmaps.ShowBitmap(bmp)
        w, h = bmp.GetBw(), bmp.GetBh()
        c4d.gui.MessageDialog(f"Still saved!\n\nFile: {os.path.basename(png_path)}\nResolution: {w}x{h}\nFolder: {output_dir}")
    else:
        c4d.gui.MessageDialog(f"Still saved!\n\n{png_path}")

    safe_print(f"Still saved: {png_path}")

def snapshot_open_folder(doc, artist_name):
    """Open the artist's stills folder"""
    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return
    output_dir = _get_stills_dir(doc, artist_name)
    if os.path.exists(output_dir):
        open_in_explorer(output_dir)
    else:
        c4d.gui.MessageDialog(f"Folder not found:\n{output_dir}")

# ---------------- UI Widget IDs ----------------
class G:
    # Scene info
    SHOT = 1001
    ARTIST = 1003
    CANVAS = 1008
    SCORE_CANVAS = 1180  # ScoreHeader UserArea
    LABEL_FILENAME = 1192  # Scene identity caption (filename of active doc)

    # Tabbed layout (Phase 2 of UI redesign)
    TAB_BAR = 1200            # CUSTOMGUI_QUICKTAB widget
    TAB_CONTAINER = 1209      # Single container — only active tab content lives inside
    TAB_GROUP_QC = 1210       # Inner group ID for QC content
    TAB_GROUP_RENDER = 1211   # Inner group ID for Render content
    TAB_GROUP_VERSIONS = 1212 # Inner group ID for Versions content
    TAB_GROUP_TOOLS = 1213    # Inner group ID for Tools content

    # Per-check action buttons (1 click to select/info)
    BTN_SEL_LIGHTS = 1130
    BTN_SEL_VIS = 1131
    BTN_SEL_KEYS = 1132
    BTN_SEL_CAMS = 1133
    BTN_INFO_PRESET = 1134
    BTN_INFO_TEXTURES = 1135
    BTN_SEL_UNUSED_MATS = 1136
    BTN_SEL_NAMES = 1137
    BTN_INFO_OUTPUT = 1138
    BTN_INFO_FPS = 1139

    # Auto-fix buttons
    BTN_FIX_LIGHTS = 1140
    BTN_FIX_CAMS = 1141
    BTN_FIX_UNUSED_MATS = 1142
    BTN_FIX_FPS = 1143

    # Export
    BTN_EXPORT_QC = 1150

    # Render preset
    PRESET_DROPDOWN = 1002
    LABEL_RESOLUTION = 1170
    BTN_FORCE_VERTICAL = 1204  # Force 9:16
    BTN_RESET_ALL = 1206      # Reset all presets from template

    # Quick Actions
    BTN_CREATE_HIERARCHY = 1126
    BTN_HIERARCHY_TO_LAYERS = 1101
    BTN_SOLO = 1103
    BTN_DROP_TO_FLOOR = 1122
    BTN_VIBRATE_NULL = 1120
    BTN_ABC_RETIME = 1020
    BTN_CAM_SIMPLE = 1123
    BTN_CAM_SHAKEL = 1124
    BTN_CAM_PATH = 1125

    # Output
    BTN_OPEN_FOLDER = 1010
    BTN_SNAPSHOT = 1009
    BTN_COLLECT_SCENE = 1171
    BTN_SAVE_VERSION = 1172
    LABEL_LAST_VERSION = 1173
    HISTORY_CANVAS = 1181
    COMBO_HISTORY_FILTER = 1182
    LABEL_NOTES_SUMMARY = 1190
    BTN_EDIT_NOTES = 1191
    COMP_TARGET = 1154
    CHK_MULTIPART = 1153
    BTN_INFO_TAKES = 1152
    BTN_INFO_AOVS = 1155
    BTN_LIGHT_GROUPS = 1158
    BTN_FORCE_ESSENTIALS = 1156
    BTN_FORCE_PRODUCTION = 1157
    BTN_SET_SNAPSHOT_DIR = 1160
    LABEL_SNAPSHOT_DIR = 1161
    BTN_GITHUB = 1306
    BTN_BUG_REPORT = 1307

class YSPanel(gui.GeDialog):
    def __init__(self):
        super().__init__()
        self._last_doc = None
        self._last_check_time = 0
        self.ua = None
        self.score_ua = None  # ScoreHeader instance
        self.history_ua = None  # HistoryArea instance
        self._history_filter = FILTER_ALL
        self._history_max_rows = 5
        self._artist_name = ""
        self._quicktab = None  # QuickTab CustomGUI for tabs
        self._active_tab = 0   # 0=QC, 1=Render, 2=Versions, 3=Tools
        self._dirty = False  # Set by CoreMessage, consumed by Timer

        # Store selection results
        self._lights_bad = []
        self._vis_bad = []
        self._keys_bad = []
        self._cam_bad = []
        self._textures_bad = []
        self._unused_mats_bad = []
        self._names_bad = []
        self._output_bad = []
        self._takes_bad = []
        self._fps_range_bad = []
        self._scene_stats = {}

        # Cycling indices for one-by-one selection
        self._unused_mats_idx = 0
        self._names_idx = 0

    # ── Tab switching: dynamic rebuild via LayoutFlushGroup ─────────────────
    # C4D 2026's HideElement returns True but does NOT collapse layout space
    # for hidden groups (verified empirically). The robust solution is to
    # keep only the active tab's content in the layout: flush the container
    # and rebuild on every switch.

    def _set_active_tab(self, idx):
        """Switch to tab `idx` by flushing the container and rebuilding."""
        if not 0 <= idx <= 3:
            return
        self._active_tab = idx
        try:
            self.LayoutFlushGroup(G.TAB_CONTAINER)
        except Exception as e:
            safe_print(f"LayoutFlushGroup error: {e}")
            return
        try:
            self._build_active_tab_content()
        except Exception as e:
            safe_print(f"_build_active_tab_content error: {e}")
        try:
            self.LayoutChanged(G.TAB_CONTAINER)
        except Exception as e:
            safe_print(f"LayoutChanged error: {e}")
        # Repopulate per-tab labels with current data (widgets just got created).
        try:
            doc = c4d.documents.GetActiveDocument()
            if idx == 1:  # Render
                self._update_snapshot_dir_label()
            elif idx == 2:  # Versions
                self._update_last_version_label(doc)
                self._update_notes_summary(doc)
                self._update_history_area(doc)
        except Exception as e:
            safe_print(f"Per-tab label refresh error: {e}")
        # Mark dirty so the QC StatusArea redraws on the next Timer tick.
        self._dirty = True

    def _build_active_tab_content(self):
        """Dispatch to the appropriate tab builder based on self._active_tab."""
        if self._active_tab == 0:
            self._build_tab_qc()
        elif self._active_tab == 1:
            self._build_tab_render()
        elif self._active_tab == 2:
            self._build_tab_versions()
        elif self._active_tab == 3:
            self._build_tab_tools()

    # ── Tab content builders ─────────────────────────────────────────────────

    def _build_tab_qc(self):
        """Build QC tab content (no outer group; lives inside TAB_CONTAINER)."""
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "Click any row to run its primary action.", 0)

        self.GroupBegin(40, c4d.BFH_SCALEFIT|c4d.BFV_TOP, 2, 0)
        self.GroupSpace(4, 0)

        # Left: terminal status display (StatusArea instance persists across rebuilds)
        self.AddUserArea(G.CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 260)
        if self.ua is None:
            self.ua = StatusArea()
        self.AttachUserArea(self.ua, G.CANVAS)
        self.ua.click_callback = self._on_qc_row_click

        # Right: per-check Select + Fix buttons (2 columns × 11 rows)
        self.GroupBegin(407, c4d.BFH_RIGHT|c4d.BFV_SCALEFIT, 2, 11)
        self.GroupBorderSpace(0, 3, 0, 3)
        self.GroupSpace(2, 3)
        self.AddButton(G.BTN_SEL_LIGHTS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_LIGHTS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_SEL_VIS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_SEL_KEYS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_SEL_CAMS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_CAMS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_INFO_PRESET, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_TEXTURES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_SEL_UNUSED_MATS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddButton(G.BTN_FIX_UNUSED_MATS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.AddButton(G.BTN_SEL_NAMES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Select")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_OUTPUT, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_TAKES, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "", 0)
        self.AddButton(G.BTN_INFO_FPS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 50, 0, "Info")
        self.AddButton(G.BTN_FIX_FPS, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 35, 0, "Fix")
        self.GroupEnd()

        self.GroupEnd()  # status row

        self.AddSeparatorH(4)
        self.AddButton(G.BTN_EXPORT_QC, c4d.BFH_SCALEFIT, 0, 0, "Export QC Report")

        # Spacer absorbs remaining vertical space
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _build_tab_render(self):
        """Build Render tab content."""
        # Preset row
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Render Preset", 0)
        self.GroupBegin(20, c4d.BFH_SCALEFIT, 4, 0)
        self.AddComboBox(G.PRESET_DROPDOWN, c4d.BFH_SCALEFIT, 100, 0)
        self.AddStaticText(G.LABEL_RESOLUTION, c4d.BFH_LEFT, 100, 0, "", 0)
        self.AddButton(G.BTN_RESET_ALL, c4d.BFH_SCALEFIT, 0, 0, "Reset All")
        self.AddButton(G.BTN_FORCE_VERTICAL, c4d.BFH_SCALEFIT, 0, 0, "Force 9:16")
        self.GroupEnd()
        # Repopulate preset combo (must happen after AddComboBox each rebuild)
        self.AddChild(G.PRESET_DROPDOWN, 0, "Previz")
        self.AddChild(G.PRESET_DROPDOWN, 1, "Pre-Render")
        self.AddChild(G.PRESET_DROPDOWN, 2, "Render")
        self.AddChild(G.PRESET_DROPDOWN, 3, "Stills")

        self.AddSeparatorH(4)

        # AOVs
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Redshift AOVs", 0)
        self.GroupBegin(81, c4d.BFH_SCALEFIT, 4, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Comp", 0)
        self.AddComboBox(G.COMP_TARGET, c4d.BFH_LEFT, 100, 0)
        self.AddCheckbox(G.CHK_MULTIPART, c4d.BFH_LEFT, 0, 0, "Multi-Part")
        self.AddButton(G.BTN_INFO_AOVS, c4d.BFH_SCALEFIT, 0, 0, "Show AOVs")
        self.GroupEnd()
        # Repopulate comp combo + restore state
        self.AddChild(G.COMP_TARGET, 0, "Nuke")
        self.AddChild(G.COMP_TARGET, 1, "After Effects")
        self.SetInt32(G.COMP_TARGET, int(GlobalSettings.get('comp_target', 0)))
        self.SetBool(G.CHK_MULTIPART, bool(int(GlobalSettings.get('aov_multipart', 1))))

        self.GroupBegin(80, c4d.BFH_SCALEFIT, 3, 0)
        self.AddButton(G.BTN_FORCE_ESSENTIALS, c4d.BFH_SCALEFIT, 0, 0, "Essentials")
        self.AddButton(G.BTN_FORCE_PRODUCTION, c4d.BFH_SCALEFIT, 0, 0, "Production")
        self.AddButton(G.BTN_LIGHT_GROUPS, c4d.BFH_SCALEFIT, 0, 0, "Light Groups")
        self.GroupEnd()

        self.AddSeparatorH(4)

        # Snapshots
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Snapshots", 0)
        self.GroupBegin(61, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(G.LABEL_SNAPSHOT_DIR, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddButton(G.BTN_SET_SNAPSHOT_DIR, c4d.BFH_RIGHT, 60, 0, "Browse")
        self.GroupEnd()
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_SNAPSHOT, c4d.BFH_SCALEFIT, 0, 0, "Save Still")
        self.AddButton(G.BTN_OPEN_FOLDER, c4d.BFH_SCALEFIT, 0, 0, "Open Folder")
        self.GroupEnd()

        # Spacer
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _build_tab_versions(self):
        """Build Versions tab content."""
        # Notes
        self.GroupBegin(64, c4d.BFH_SCALEFIT, 2, 0)
        self.GroupSpace(6, 0)
        self.AddStaticText(G.LABEL_NOTES_SUMMARY, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.AddButton(G.BTN_EDIT_NOTES, c4d.BFH_RIGHT, 110, 0, "Edit Notes...")
        self.GroupEnd()

        self.AddSeparatorH(4)

        # Last version + primary actions
        self.AddStaticText(G.LABEL_LAST_VERSION, c4d.BFH_SCALEFIT, 0, 0, "", 0)
        self.GroupBegin(62, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_SAVE_VERSION, c4d.BFH_SCALEFIT, 0, 0, "Save Version")
        self.AddButton(G.BTN_COLLECT_SCENE, c4d.BFH_SCALEFIT, 0, 0, "Collect Scene")
        self.GroupEnd()

        self.AddSeparatorH(4)

        # Recent versions list
        self.GroupBegin(63, c4d.BFH_SCALEFIT, 2, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Recent Versions", 0)
        self.AddComboBox(G.COMBO_HISTORY_FILTER, c4d.BFH_RIGHT, 100, 0)
        self.GroupEnd()
        # Repopulate history filter combo
        for i, label in enumerate(self._HISTORY_FILTER_LABELS):
            self.AddChild(G.COMBO_HISTORY_FILTER, i, label)
        # Restore selection
        try:
            current_filter = self._history_filter
            for i, f in enumerate(self._HISTORY_FILTERS):
                if f == current_filter:
                    self.SetInt32(G.COMBO_HISTORY_FILTER, i)
                    break
        except Exception:
            self.SetInt32(G.COMBO_HISTORY_FILTER, 0)

        self.AddUserArea(G.HISTORY_CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_FIT, 0, HistoryArea.EMPTY_HEIGHT)
        if self.history_ua is None:
            self.history_ua = HistoryArea()
        self.AttachUserArea(self.history_ua, G.HISTORY_CANVAS)
        self.history_ua.click_callback = self._on_history_row_click

        # Spacer
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _build_tab_tools(self):
        """Build Tools tab content."""
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Layout & Hierarchy", 0)
        self.GroupBegin(50, c4d.BFH_SCALEFIT, 4, 0)
        self.AddButton(G.BTN_CREATE_HIERARCHY, c4d.BFH_SCALEFIT, 0, 0, "Hierarchy")
        self.AddButton(G.BTN_HIERARCHY_TO_LAYERS, c4d.BFH_SCALEFIT, 0, 0, "H -> Layers")
        self.AddButton(G.BTN_SOLO, c4d.BFH_SCALEFIT, 0, 0, "Solo Layers")
        self.AddButton(G.BTN_DROP_TO_FLOOR, c4d.BFH_SCALEFIT, 0, 0, "Drop to Floor")
        self.GroupEnd()

        self.AddSeparatorH(4)

        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Object & Animation", 0)
        self.GroupBegin(51, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_VIBRATE_NULL, c4d.BFH_SCALEFIT, 0, 0, "Vibrate Null")
        self.AddButton(G.BTN_ABC_RETIME, c4d.BFH_SCALEFIT, 0, 0, "ABC Retime")
        self.GroupEnd()

        self.AddSeparatorH(4)

        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Camera Rigs", 0)
        self.GroupBegin(52, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_CAM_SIMPLE, c4d.BFH_SCALEFIT, 0, 0, "Cam Simple")
        self.AddButton(G.BTN_CAM_SHAKEL, c4d.BFH_SCALEFIT, 0, 0, "Cam Shakel")
        self.GroupEnd()

        # Spacer
        self.AddStaticText(0, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 0, 0, "", 0)

    def _update_filename_label(self, doc=None):
        """Refresh the scene identity caption in the panel header.

        Uses '▸' (BMP) instead of the folder emoji because C4D's AddStaticText
        on macOS renders supplementary-plane characters (📁 etc.) as fallback
        glyphs. ▸ is a basic-multilingual-plane char that renders cleanly.
        """
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if not doc:
            self.SetString(G.LABEL_FILENAME, "▸ Scene:  (no document)")
            return
        name = doc.GetDocumentName() or ""
        if not name:
            self.SetString(G.LABEL_FILENAME, "▸ Scene:  Untitled  ·  not saved yet")
            return
        # Show the full filename including version + status — the user is
        # working ON this exact file; transparency over abstraction.
        self.SetString(G.LABEL_FILENAME, f"▸ Scene:  {name}")

    def _update_snapshot_dir_label(self):
        snap_dir = GlobalSettings.get_snapshot_dir()
        # Shorten for display: show last 2 path components
        parts = snap_dir.replace("\\", "/").rstrip("/").split("/")
        short = "/".join(parts[-2:]) if len(parts) > 2 else snap_dir
        self.SetString(G.LABEL_SNAPSHOT_DIR, f"Snapshots: .../{short}")

    def _update_last_version_label(self, doc=None):
        """Refresh the 'Last version' caption above Save Version button."""
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if not doc:
            self.SetString(G.LABEL_LAST_VERSION, "Last version: —")
            return

        info = get_latest_version_info(doc)
        if not info:
            if doc.GetDocumentPath():
                txt = "Last version: none yet  ·  click Save Version to start"
            else:
                txt = "Last version: —  ·  scene not saved yet"
            self.SetString(G.LABEL_LAST_VERSION, txt)
            return

        try:
            ver = int(info.get("version", 0))
        except Exception:
            ver = 0
        status = info.get("status", "") or ""
        ts = info.get("timestamp", "")
        rel = _humanize_time_diff(ts)
        status_str = status if status else "WIP"
        rel_part = f"  ·  {rel}" if rel else ""
        self.SetString(G.LABEL_LAST_VERSION, f"Last version: v{ver:03d} {status_str}{rel_part}")

    def _update_notes_summary(self, doc=None):
        """Refresh the Notes summary caption above the Edit Notes button."""
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if not doc:
            self.SetString(G.LABEL_NOTES_SUMMARY, "Notes: —")
            return
        notes_path = get_notes_path(doc)
        if not notes_path:
            self.SetString(G.LABEL_NOTES_SUMMARY, "Notes: —  ·  scene not saved yet")
            return
        notes = load_notes(notes_path)
        summary = summarize_notes(notes)
        if has_pending_todos(notes):
            # Lightweight visual cue that there's something pending
            summary = f"⚠ {summary}"
        self.SetString(G.LABEL_NOTES_SUMMARY, summary)

    # Filter combobox value mapping (combobox index -> filter token)
    _HISTORY_FILTERS = [FILTER_ALL, "", "TR", "CR", "FINAL"]
    _HISTORY_FILTER_LABELS = ["All", "WIP", "TR", "CR", "FINAL"]

    def _update_history_area(self, doc=None):
        """Refresh the Recent Versions list (HistoryArea)."""
        if doc is None:
            doc = c4d.documents.GetActiveDocument()
        if self.history_ua is None:
            return
        if not doc:
            self.history_ua.set_entries([])
            return
        versions = load_versions_for_doc(doc)
        # Use explicit None check — '' is the valid WIP filter token, not "no filter".
        active_filter = self._history_filter if self._history_filter is not None else FILTER_ALL
        filtered = filter_versions_by_status(versions, active_filter)
        limited = filtered[: self._history_max_rows]
        formatted = [format_version_row(e) for e in limited if e]
        formatted = [f for f in formatted if f]
        # Set empty message based on context
        if not versions:
            if doc.GetDocumentPath():
                self.history_ua.empty_msg = "No versions yet — click Save Version"
            else:
                self.history_ua.empty_msg = "Save the scene first"
        elif not formatted:
            label = "WIP" if active_filter == "" else (active_filter if active_filter != FILTER_ALL else "All")
            self.history_ua.empty_msg = f"No versions match filter ({label})"
        else:
            self.history_ua.empty_msg = "No versions yet"
        self.history_ua.set_entries(formatted)

    # ---- read scene -> UI
    def _sync_from_doc(self, doc):
        """Sync UI with document state"""
        if not doc:
            return

        try:
            td = None
            try:
                td = doc.GetTakeData()
            except Exception:
                try:
                    td = documents.GetTakeData(doc)
                except Exception:
                    pass

            shot = ""
            if td:
                main_take = td.GetMainTake()
                if main_take:
                    shot = main_take.GetName() or ""
            self.SetString(G.SHOT, shot)
        except Exception as e:
            safe_print(f"Error syncing shot name: {e}")

        try:
            ard = doc.GetActiveRenderData()
            if ard:
                name = normalize_preset_name(ard.GetName() or "")
                if name in PRESETS:
                    self._active_preset = name
                self._update_preset_buttons()
        except Exception as e:
            safe_print(f"Error syncing render preset: {e}")

    # ---- write UI -> scene
    def _apply_shot(self, doc):
        if not doc:
            return

        try:
            name = self.GetString(G.SHOT)
            td = None

            try:
                td = doc.GetTakeData()
            except Exception:
                try:
                    td = documents.GetTakeData(doc)
                except Exception:
                    pass

            if td:
                main_take = td.GetMainTake()
                if main_take:
                    main_take.SetName(name)
                    c4d.EventAdd()
        except Exception as e:
            safe_print(f"Error applying shot name: {e}")

    def _apply_preset(self, doc, preset_name):
        """Apply preset - accepts pre_render, pre-render, Pre-Render, etc."""
        if not doc:
            return

        try:
            # Normalize the target preset name
            normalized_target = normalize_preset_name(preset_name)
            rd = doc.GetFirstRenderData()

            while rd:
                # Normalize the render data name for comparison
                normalized_rd = normalize_preset_name(rd.GetName() or "")
                if normalized_rd == normalized_target:
                    doc.SetActiveRenderData(rd)
                    check_cache.clear()  # Clear cache to update compliance check immediately
                    c4d.EventAdd()
                    self._active_preset = normalized_target
                    self._update_preset_buttons()
                    safe_print(f"Switched to render preset: {rd.GetName()} (normalized: {normalized_target})")
                    break
                rd = rd.GetNext()
        except Exception as e:
            safe_print(f"Error applying render preset: {e}")

    def _update_preset_buttons(self):
        """Update preset dropdown and resolution label"""
        preset_to_index = {
            "previz": 0, "pre_render": 1, "render": 2, "stills": 3
        }
        normalized_preset = normalize_preset_name(self._active_preset)
        if normalized_preset in preset_to_index:
            self.SetInt32(G.PRESET_DROPDOWN, preset_to_index[normalized_preset])

        # Update resolution label and aspect button
        doc = c4d.documents.GetActiveDocument()
        if doc:
            rd = doc.GetActiveRenderData()
            if rd:
                try:
                    w = int(rd[c4d.RDATA_XRES])
                    h = int(rd[c4d.RDATA_YRES])
                    self.SetString(G.LABEL_RESOLUTION, f"{w}x{h}")
                    self.SetString(G.BTN_FORCE_VERTICAL, "Force 16:9" if h > w else "Force 9:16")
                except Exception:
                    pass

    def _refresh(self):
        """Throttled refresh with performance optimization"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return

        # Check cooldown
        now = time.time()
        if now - self._last_check_time < CHECK_COOLDOWN:
            return
        self._last_check_time = now

        try:
            # Clear stale references before running checks
            check_cache.clear()

            # Run checks
            lights_bad = check_lights(doc)
            vis_bad = check_visibility_traps(doc)
            keys_bad = check_keys(doc)
            cam_bad = check_camera_shift(doc)
            rdc_bad = check_render_conflicts(doc)
            textures_bad = check_textures_unified(doc)
            unused_mats_bad = check_unused_materials(doc)
            names_bad = check_default_names(doc)
            output_bad = check_output_paths(doc)
            takes_bad = check_takes(doc)
            fps_range_bad = check_fps_range(doc)
            scene_stats = get_scene_stats(doc)

            # Count issues
            lights_count = len(lights_bad) if lights_bad else 0
            vis_count = len(vis_bad) if vis_bad else 0
            keys_count = len(keys_bad) if keys_bad else 0
            cam_count = len(cam_bad) if cam_bad else 0
            rdc_count = int(rdc_bad) if rdc_bad else 0
            textures_count = len(textures_bad) if textures_bad else 0
            unused_mats_count = len(unused_mats_bad) if unused_mats_bad else 0
            names_count = len(names_bad) if names_bad else 0
            output_count = len(output_bad) if output_bad else 0
            takes_count = len(takes_bad) if takes_bad else 0
            fps_range_count = len(fps_range_bad) if fps_range_bad else 0

            # Update StatusArea
            self.ua.set_state(
                dict(
                    lights=lights_count,
                    vis=vis_count,
                    vis_names=[_safe_name(o) for o in (vis_bad[:10] if vis_bad else [])],
                    keys=keys_count,
                    keys_names=[_safe_name(o) for o in (keys_bad[:10] if keys_bad else [])],
                    cam=cam_count,
                    rdc=rdc_count,
                    textures=textures_count,
                    unused_mats=unused_mats_count,
                    names=names_count,
                    names_list=[_safe_name(o) for o in (names_bad[:10] if names_bad else [])],
                    output=output_count,
                    takes=takes_count,
                    fps_range=fps_range_count,
                ),
                self.ua.show,
            )

            # Update Score header — pass count + scene stats summary
            counts = [lights_count, vis_count, keys_count, cam_count, rdc_count,
                      textures_count, unused_mats_count, names_count,
                      output_count, takes_count, fps_range_count]
            total_checks = len(counts)
            passed = sum(1 for c in counts if c == 0)
            stats_str = ""
            if scene_stats:
                # Compact one-liner: "1.2M polys · 47 mats · 12 lights"
                polys = scene_stats.get("polygons", 0)
                if polys >= 1_000_000:
                    poly_str = f"{polys/1_000_000:.1f}M polys"
                elif polys >= 1_000:
                    poly_str = f"{polys/1_000:.0f}K polys"
                else:
                    poly_str = f"{polys} polys"
                stats_str = f"{poly_str}  ·  {scene_stats.get('materials', 0)} mats  ·  {scene_stats.get('lights', 0)} lights"
            if self.score_ua is not None:
                self.score_ua.set_state(passed, total_checks, stats_str)

            # Store results
            self._lights_bad = lights_bad
            self._vis_bad = vis_bad
            self._keys_bad = keys_bad
            self._cam_bad = cam_bad
            self._textures_bad = textures_bad
            self._scene_stats = scene_stats
            # Reset cycling indices when result count changes
            if len(unused_mats_bad) != len(self._unused_mats_bad):
                self._unused_mats_idx = 0
            if len(names_bad) != len(self._names_bad):
                self._names_idx = 0

            self._unused_mats_bad = unused_mats_bad
            self._names_bad = names_bad
            self._output_bad = output_bad
            self._takes_bad = takes_bad
            self._fps_range_bad = fps_range_bad

            # Refresh header captions + Recent Versions list (all cheap reads)
            self._update_filename_label(doc)
            self._update_last_version_label(doc)
            self._update_history_area(doc)
            self._update_notes_summary(doc)

        except Exception as e:
            safe_print(f"Error during refresh: {e}")

    # ---- layout
    def CreateLayout(self):
        self.SetTitle(PLUGIN_NAME)

        # Main container
        self.GroupBegin(1, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 1, 0)
        self.GroupBorderSpace(4, 4, 4, 4)

        # ── Scene Header (always visible — scene identity + project meta + QC bar) ──
        self.GroupBegin(9, c4d.BFH_SCALEFIT, 1, 0)
        self.GroupBorder(c4d.BORDER_THIN_IN)
        self.GroupBorderSpace(6, 4, 6, 4)
        self.GroupSpace(0, 4)

        # Filename caption — read-only, prominent, centered
        self.AddStaticText(G.LABEL_FILENAME, c4d.BFH_CENTER, 0, 0, "", 0)

        # Editable project metadata: Shot ID + Artist
        self.GroupBegin(10, c4d.BFH_SCALEFIT, 4, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 60, 0, "Shot ID", 0)
        self.AddEditText(G.SHOT, c4d.BFH_SCALEFIT, 80, 0)
        self.AddStaticText(0, c4d.BFH_LEFT, 0, 0, "Artist  ", 0)
        self.AddEditText(G.ARTIST, c4d.BFH_SCALEFIT, 100, 0)
        self.GroupEnd()

        # Score line (was inside QC group; now in the always-visible header)
        self.AddUserArea(G.SCORE_CANVAS, c4d.BFH_SCALEFIT|c4d.BFV_FIT, 0, ScoreHeader.HEIGHT)
        self.score_ua = ScoreHeader()
        self.AttachUserArea(self.score_ua, G.SCORE_CANVAS)

        self.GroupEnd()  # end Scene Header

        # ── Tab bar ──
        self.AddSeparatorH(4)
        tab_bc = c4d.BaseContainer()
        tab_bc.SetBool(c4d.QUICKTAB_BAR, False)         # tab style (not bar)
        tab_bc.SetBool(c4d.QUICKTAB_SHOWSINGLE, True)
        tab_bc.SetBool(c4d.QUICKTAB_NOMULTISELECT, True)
        self._quicktab = self.AddCustomGui(
            G.TAB_BAR, c4d.CUSTOMGUI_QUICKTAB, "",
            c4d.BFH_SCALEFIT, 0, 0, tab_bc
        )
        if self._quicktab is not None:
            self._quicktab.AppendString(0, "QC", True)
            self._quicktab.AppendString(1, "Render", False)
            self._quicktab.AppendString(2, "Versions", False)
            self._quicktab.AppendString(3, "Tools", False)

        # ── Tab content container — only the active tab's content lives inside.
        # Switching tabs flushes this group and rebuilds with the new content
        # (HideElement does not collapse layout space in C4D 2026).
        self.GroupBegin(G.TAB_CONTAINER, c4d.BFH_SCALEFIT|c4d.BFV_SCALEFIT, 1, 0)
        self._build_active_tab_content()
        self.GroupEnd()

        # ───────── Footer (always visible) ─────────
        self.AddSeparatorH(4)
        self.GroupBegin(70, c4d.BFH_SCALEFIT, 2, 0)
        self.AddButton(G.BTN_GITHUB, c4d.BFH_SCALEFIT, 0, 0, "GitHub")
        self.AddButton(G.BTN_BUG_REPORT, c4d.BFH_SCALEFIT, 0, 0, "Report Bug")
        self.GroupEnd()

        self.GroupEnd()  # Main container

        self.SetTimer(3000)
        return True

    def InitValues(self):
        # Load artist name from computer-level settings
        self._artist_name = GlobalSettings.load_artist_name()
        if self._artist_name:
            self.SetString(G.ARTIST, self._artist_name)

        # Initialize active preset
        self._active_preset = "previz"
        self._history_filter = FILTER_ALL

        # Header captions (always visible — outside tabs)
        self._update_filename_label()

        # The QC tab was built in CreateLayout — refresh its caption-driven
        # widgets and the cross-tab labels (snapshot dir, last version, notes).
        # Other tabs' widgets are populated when the user switches to them.
        self._update_snapshot_dir_label()
        self._update_last_version_label()
        self._update_notes_summary()
        self._update_history_area()

        doc = c4d.documents.GetActiveDocument()
        self._sync_from_doc(doc)
        self._refresh()
        self._last_doc = doc
        return True

    def _on_qc_row_click(self, row_key):
        """Called by StatusArea when the user clicks a QC row.
        Routes to the same handler as the primary button (Select or Info)."""
        primary = {
            "lights":      G.BTN_SEL_LIGHTS,
            "vis":         G.BTN_SEL_VIS,
            "keys":        G.BTN_SEL_KEYS,
            "cam":         G.BTN_SEL_CAMS,
            "rdc":         G.BTN_INFO_PRESET,
            "textures":    G.BTN_INFO_TEXTURES,
            "unused_mats": G.BTN_SEL_UNUSED_MATS,
            "names":       G.BTN_SEL_NAMES,
            "output":      G.BTN_INFO_OUTPUT,
            "takes":       G.BTN_INFO_TAKES,
            "fps_range":   G.BTN_INFO_FPS,
        }
        btn_id = primary.get(row_key)
        if btn_id is not None:
            try:
                self.Command(btn_id, c4d.BaseContainer())
            except Exception as e:
                safe_print(f"Row click dispatch error: {e}")

    def _on_history_row_click(self, entry):
        """Called by HistoryArea when the user clicks a version row.
        Confirms with the user, then opens the .c4d file via LoadFile.
        Warns about unsaved changes in the current document.
        """
        if not entry:
            return
        path = (entry.get("path") or "").strip()
        filename = entry.get("filename") or os.path.basename(path) or "(unknown)"

        if not path or not os.path.exists(path):
            c4d.gui.MessageDialog(
                f"File not found:\n  {filename}\n\n"
                f"It may have been moved, renamed, or deleted.\n"
                f"The history entry remains in the JSON for reference."
            )
            return

        # Don't reopen the current doc
        current = c4d.documents.GetActiveDocument()
        if current:
            try:
                cur_full = os.path.join(current.GetDocumentPath() or "", current.GetDocumentName() or "")
                if os.path.normcase(os.path.normpath(cur_full)) == os.path.normcase(os.path.normpath(path)):
                    c4d.gui.MessageDialog(f"Already viewing {filename}.")
                    return
            except Exception:
                pass

        # Build confirmation prompt
        version_label = entry.get("version_label", "")
        status_label = entry.get("status_label", "")
        comment = entry.get("comment", "") or "(no comment)"
        ts = entry.get("time_label", "")

        prompt_lines = [
            f"Open {filename}?",
            "",
            f"  {version_label}  [{status_label}]  ·  {ts}",
            f"  \"{comment}\"",
        ]
        # Warn about unsaved changes in the current doc
        try:
            if current and current.GetChanged():
                prompt_lines.append("")
                prompt_lines.append("⚠ Current document has unsaved changes.")
                prompt_lines.append("The new file will open in a separate Cinema 4D window.")
        except Exception:
            pass

        if not c4d.gui.QuestionDialog("\n".join(prompt_lines)):
            return

        # Open the file
        try:
            ok = c4d.documents.LoadFile(path)
            if ok:
                safe_print(f"Opened {filename} via Browse Versions")
                self._dirty = True  # force panel refresh against new doc
            else:
                c4d.gui.MessageDialog(
                    f"Cinema 4D could not open:\n  {filename}\n\n"
                    f"(LoadFile returned False — file may be locked or corrupted)"
                )
        except Exception as e:
            c4d.gui.MessageDialog(f"Error opening file:\n\n{e}")
            safe_print(f"Browse Versions LoadFile error: {e}")

    def Timer(self, msg):
        doc = c4d.documents.GetActiveDocument()

        # Document change detection
        if doc is not self._last_doc:
            check_cache.clear()
            self._sync_from_doc(doc)
            self._dirty = True
            self._last_doc = doc

        # Only refresh if dirty or cache expired
        if self._dirty:
            self._dirty = False
            self._refresh()
        else:
            self._refresh()  # Cache handles skip if still valid

    def CoreMessage(self, id, msg):
        if id == c4d.EVMSG_CHANGE:
            self._dirty = True  # Don't clear cache or refresh here - let Timer handle it
            return True

        if id == 431000159:  # EVMSG_TAKECHANGED
            doc = c4d.documents.GetActiveDocument()
            if doc:
                self._sync_from_doc(doc)
            self._dirty = True
            return True

        return gui.GeDialog.CoreMessage(self, id, msg)

    def Command(self, cid, msg):
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            return True

        if cid == G.SHOT:
            self._apply_shot(doc)

        # Handle preset dropdown selection
        elif cid == G.PRESET_DROPDOWN:
            selected_index = self.GetInt32(G.PRESET_DROPDOWN)
            index_to_preset = {0: "previz", 1: "pre_render", 2: "render", 3: "stills"}
            if selected_index in index_to_preset:
                self._apply_preset(doc, index_to_preset[selected_index])

        elif cid == G.BTN_FORCE_VERTICAL:
            self._toggle_aspect(doc)

        elif cid == G.BTN_RESET_ALL:
            self._force_render_settings(doc)

        elif cid == G.ARTIST:
            # Artist name changed - save to global settings
            new_artist_name = self.GetString(G.ARTIST).strip()
            if new_artist_name != self._artist_name:
                self._artist_name = new_artist_name
                GlobalSettings.save_artist_name(self._artist_name)

        elif cid == G.BTN_SNAPSHOT:
            self._take_renderview_snapshot()

        elif cid == G.COMP_TARGET:
            GlobalSettings.set('comp_target', self.GetInt32(G.COMP_TARGET))

        elif cid == G.CHK_MULTIPART:
            GlobalSettings.set('aov_multipart', 1 if self.GetBool(G.CHK_MULTIPART) else 0)

        elif cid == G.BTN_LIGHT_GROUPS:
            self._toggle_light_groups(doc)

        elif cid == G.BTN_INFO_AOVS:
            result = check_rs_aovs(doc, AOV_TIER_PRODUCTION)
            if not result["available"]:
                c4d.gui.MessageDialog("Redshift module not available.\n\nMake sure Redshift is installed and active.")
            elif not result["aovs"]:
                c4d.gui.MessageDialog("No AOVs configured.\n\nUse 'Essentials' or 'Production' to add passes.")
            else:
                target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
                lg_status = "ON" if self._is_lg_active_on_beauty(doc) else "OFF"
                groups, _ = self._scan_light_groups(doc)
                lg_info = f"Light Groups: {lg_status}"
                if groups and lg_status == "ON":
                    lg_info += f" ({', '.join(sorted(groups.keys()))})"
                msg = f"REDSHIFT AOVs: {len(result['aovs'])}  |  Target: {target_name}\n{lg_info}\n\n"
                msg += "ACTIVE:\n"
                for aov in result["aovs"]:
                    status = "ON" if aov.get("enabled") else "OFF"
                    msg += f"  [{status}] {aov['name']}\n"

                # Check against both tiers
                ess = check_rs_aovs(doc, AOV_TIER_ESSENTIALS)
                prod = check_rs_aovs(doc, AOV_TIER_PRODUCTION)

                if ess["missing"]:
                    msg += f"\nMISSING ESSENTIALS ({len(ess['missing'])}):\n"
                    for n in ess["missing"]:
                        msg += f"  ! {n}\n"

                prod_only = [n for n in prod["missing"] if n not in ess["missing"]]
                if prod_only:
                    msg += f"\nMISSING PRODUCTION ({len(prod_only)}):\n"
                    for n in prod_only:
                        msg += f"  - {n}\n"

                if not prod["missing"]:
                    msg += "\nAll Production AOVs present."
                elif not ess["missing"]:
                    msg += "\nAll Essentials AOVs present."

                c4d.gui.MessageDialog(msg)

        elif cid == G.BTN_FORCE_ESSENTIALS:
            self._force_aov_tier(doc, AOV_TIER_ESSENTIALS, "Essentials")

        elif cid == G.BTN_FORCE_PRODUCTION:
            self._force_aov_tier(doc, AOV_TIER_PRODUCTION, "Production")

        elif cid == G.BTN_SET_SNAPSHOT_DIR:
            new_dir = c4d.storage.LoadDialog(title="Select RS Snapshot Folder", flags=c4d.FILESELECT_DIRECTORY)
            if new_dir:
                GlobalSettings.set_snapshot_dir(new_dir)
                self._update_snapshot_dir_label()
                safe_print(f"Snapshot directory set to: {new_dir}")

        elif cid == G.BTN_OPEN_FOLDER:
            self._open_artist_folder()

        elif cid == G.BTN_ABC_RETIME:
            self._apply_abc_retime_tag()

        elif cid == G.BTN_VIBRATE_NULL:
            self._create_vibrate_null(doc)

        elif cid == G.BTN_CAM_SIMPLE:
            self._merge_camera_file(doc, "cam_simple.c4d")

        elif cid == G.BTN_CAM_SHAKEL:
            self._merge_camera_file(doc, "cam_w_shakel.c4d")

        elif cid == G.BTN_CAM_PATH:
            self._merge_camera_file(doc, "cam_path.c4d")

        elif cid == G.BTN_CREATE_HIERARCHY:
            self._create_hierarchy(doc)

        elif cid == G.BTN_DROP_TO_FLOOR:
            self._drop_to_floor(doc)

        elif cid == G.BTN_HIERARCHY_TO_LAYERS:
            self._hierarchy_to_layers(doc)

        elif cid == G.BTN_SOLO:
            self._solo_layers(doc)

        elif cid == G.BTN_GITHUB:
            # Open GitHub repository
            github_url = "https://github.com/jmcodex93/sentinel"
            webbrowser.open(github_url)
            safe_print(f"Opening GitHub repository: {github_url}")

        elif cid == G.BTN_BUG_REPORT:
            # Open GitHub issues page for bug reports
            bug_url = "https://github.com/jmcodex93/sentinel/issues/new"
            webbrowser.open(bug_url)
            safe_print(f"Opening bug report page: {bug_url}")

        # Per-check Select buttons (1 click to select problematic objects)
        elif cid == G.BTN_SEL_LIGHTS:
            if self._lights_bad:
                _select_objects(doc, self._lights_bad)
                safe_print(f"Selected {len(self._lights_bad)} lights outside group")
            else:
                safe_print("No light issues found")

        elif cid == G.BTN_SEL_VIS:
            if self._vis_bad:
                _select_objects(doc, self._vis_bad)
                safe_print(f"Selected {len(self._vis_bad)} objects with visibility mismatch")
            else:
                safe_print("No visibility issues found")

        elif cid == G.BTN_SEL_KEYS:
            if self._keys_bad:
                _select_objects(doc, self._keys_bad)
                safe_print(f"Selected {len(self._keys_bad)} objects with multi-axis keyframes")
            else:
                safe_print("No keyframe issues found")

        elif cid == G.BTN_SEL_CAMS:
            if self._cam_bad:
                _select_objects(doc, self._cam_bad)
                safe_print(f"Selected {len(self._cam_bad)} cameras with non-zero shift")
            else:
                safe_print("No camera shift issues found")

        elif cid == G.BTN_INFO_PRESET:
            info_msg = "RENDER PRESETS:\n\n"
            info_msg += "Standard presets: previz, pre_render, render, stills\n\n"
            rd = doc.GetFirstRenderData()
            while rd:
                name = rd.GetName()
                normalized = normalize_preset_name(name)
                status = "OK" if normalized in set(PRESETS) else "NON-STANDARD"
                info_msg += f"  [{status}] {name}\n"
                rd = rd.GetNext()
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_TEXTURES:
            if self._textures_bad:
                absolute = [t for t in self._textures_bad if t["issue"] == "absolute"]
                missing = [t for t in self._textures_bad if t["issue"] == "missing"]
                info_msg = f"ASSET ISSUES: {len(self._textures_bad)}\n\n"
                if absolute:
                    info_msg += f"ABSOLUTE PATHS ({len(absolute)}):\n"
                    for i, t in enumerate(absolute[:10], 1):
                        info_msg += f"  {i}. {t['source']}\n     {t['path']}\n"
                    info_msg += "\n"
                if missing:
                    info_msg += f"MISSING FILES ({len(missing)}):\n"
                    for i, t in enumerate(missing[:10], 1):
                        info_msg += f"  {i}. {t['source']}\n     {t['path']}\n"
                    info_msg += "\n"
                info_msg += "Fix: Project > Save Project with Assets"
            else:
                info_msg = "All assets OK. No absolute paths or missing files."
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_SEL_UNUSED_MATS:
            if self._unused_mats_bad:
                # Cycle through unused materials one by one
                if self._unused_mats_idx >= len(self._unused_mats_bad):
                    self._unused_mats_idx = 0

                mat = self._unused_mats_bad[self._unused_mats_idx]
                # Deselect all materials first
                for m in doc.GetMaterials():
                    m.DelBit(c4d.BIT_ACTIVE)
                # Select this one
                mat.SetBit(c4d.BIT_ACTIVE)
                c4d.EventAdd()

                safe_print(f"Unused material [{self._unused_mats_idx + 1}/{len(self._unused_mats_bad)}]: '{mat.GetName()}'")
                self._unused_mats_idx += 1
            else:
                safe_print("No unused materials found")

        elif cid == G.BTN_SEL_NAMES:
            if self._names_bad:
                # Cycle through default-named objects one by one
                if self._names_idx >= len(self._names_bad):
                    self._names_idx = 0

                obj = self._names_bad[self._names_idx]
                _select_objects(doc, [obj])

                safe_print(f"Default name [{self._names_idx + 1}/{len(self._names_bad)}]: '{obj.GetName()}'")
                self._names_idx += 1
            else:
                safe_print("No naming issues found")

        elif cid == G.BTN_INFO_OUTPUT:
            if hasattr(self, '_output_bad') and self._output_bad:
                info_msg = f"OUTPUT PATH ISSUES: {len(self._output_bad)}\n\n"
                for i, issue in enumerate(self._output_bad[:10], 1):
                    info_msg += f"{i}. [{issue['preset']}] {issue['issue']}\n"
                info_msg += "\nUse $prj and $take tokens in output paths."
            else:
                info_msg = "All output paths are properly configured."
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_TAKES:
            if self._takes_bad:
                info_msg = f"TAKE ISSUES: {len(self._takes_bad)}\n\n"
                for i, t in enumerate(self._takes_bad[:20], 1):
                    info_msg += f"{i}. [{t['take']}] {t['issue']}\n"
            else:
                # Check if there are any takes at all
                td = doc.GetTakeData()
                has_takes = td and td.GetMainTake() and td.GetMainTake().GetDown()
                if has_takes:
                    info_msg = "All takes properly configured."
                else:
                    info_msg = "No takes found (only Main Take)."
            c4d.gui.MessageDialog(info_msg)

        elif cid == G.BTN_INFO_FPS:
            standard_fps = GlobalSettings.get_standard_fps()
            doc_fps = doc.GetFps()
            rd = doc.GetActiveRenderData()
            info_msg = f"FPS & FRAME RANGE\n\n"
            info_msg += f"Document FPS: {doc_fps} (standard: {standard_fps})\n"
            if rd:
                preset_name = rd.GetName()
                preset_norm = normalize_preset_name(preset_name)
                is_stills = preset_norm == "stills"
                rd_fps = int(rd[c4d.RDATA_FRAMERATE])
                frame_start = rd[c4d.RDATA_FRAMEFROM].GetFrame(rd_fps)
                frame_end = rd[c4d.RDATA_FRAMETO].GetFrame(rd_fps)
                frame_mode = rd[c4d.RDATA_FRAMESEQUENCE]
                mode_names = {
                    c4d.RDATA_FRAMESEQUENCE_ALLFRAMES: "All Frames",
                    c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME: "Current Frame",
                    c4d.RDATA_FRAMESEQUENCE_MANUAL: "Manual",
                }
                mode_str = mode_names.get(frame_mode, f"Unknown ({frame_mode})")
                info_msg += f"Active preset: {preset_name}"
                info_msg += " (stills mode)\n" if is_stills else "\n"
                info_msg += f"Render FPS: {rd_fps}\n"
                info_msg += f"Render range: {frame_start} - {frame_end} ({frame_end - frame_start + 1} frames)\n"
                info_msg += f"Frame mode: {mode_str}\n"

                # Timeline + loop range + playhead
                tl_min = doc[c4d.DOCUMENT_MINTIME].GetFrame(doc_fps)
                tl_max = doc[c4d.DOCUMENT_MAXTIME].GetFrame(doc_fps)
                loop_min = doc[c4d.DOCUMENT_LOOPMINTIME].GetFrame(doc_fps)
                loop_max = doc[c4d.DOCUMENT_LOOPMAXTIME].GetFrame(doc_fps)
                playhead = doc.GetTime().GetFrame(doc_fps)
                info_msg += f"Timeline: {tl_min} - {tl_max}\n"
                info_msg += f"Preview/loop: {loop_min} - {loop_max}\n"
                info_msg += f"Playhead: frame {playhead}\n"

                if is_stills:
                    info_msg += f"\nStills: 'Current Frame' is OK; range start expected at 1001."
                else:
                    info_msg += f"\nAnimation: timeline + preview must match render range."
            if self._fps_range_bad:
                info_msg += f"\n\nISSUES ({len(self._fps_range_bad)}):\n"
                for i, issue in enumerate(self._fps_range_bad, 1):
                    info_msg += f"  {i}. {issue['issue']}\n"
            else:
                info_msg += "\n\nAll OK."
            info_msg += f"\n\nTo change standard FPS, edit sentinel_settings.json."
            c4d.gui.MessageDialog(info_msg)

        # ── Auto-fix handlers ──
        elif cid == G.BTN_FIX_LIGHTS:
            if self._lights_bad:
                count = fix_lights(doc, self._lights_bad)
                safe_print(f"Moved {count} lights into 'lights' group")
                c4d.gui.MessageDialog(f"Moved {count} light(s) into 'lights' group.\n\nUndo available (Ctrl+Z).")
            else:
                safe_print("No light issues to fix")

        elif cid == G.BTN_FIX_CAMS:
            if self._cam_bad:
                count = fix_camera_shift(doc, self._cam_bad)
                safe_print(f"Reset shift on {count} cameras")
                c4d.gui.MessageDialog(f"Reset shift to 0 on {count} camera(s).\n\nUndo available (Ctrl+Z).")
            else:
                safe_print("No camera shift issues to fix")

        elif cid == G.BTN_FIX_UNUSED_MATS:
            if self._unused_mats_bad:
                count = len(self._unused_mats_bad)
                if c4d.gui.QuestionDialog(f"Delete {count} unused material(s)?\n\nThis can be undone (Ctrl+Z)."):
                    deleted = fix_unused_materials(doc, self._unused_mats_bad)
                    safe_print(f"Deleted {deleted} unused materials")
                    self._unused_mats_idx = 0
            else:
                safe_print("No unused materials to delete")

        elif cid == G.BTN_FIX_FPS:
            if self._fps_range_bad:
                standard_fps = GlobalSettings.get_standard_fps()
                # Build confirmation listing what will change
                count = len(self._fps_range_bad)
                preview = f"FIX FPS / FRAME RANGE\n\n"
                preview += f"Standard: {standard_fps} fps, start frame 1001\n\n"
                preview += f"Issues to fix ({count}):\n"
                for issue in self._fps_range_bad[:15]:
                    preview += f"  - {issue['issue']}\n"
                if count > 15:
                    preview += f"  ... and {count - 15} more\n"
                preview += "\nThis will modify ALL render presets, document FPS, "
                preview += "timeline, and preview range. Undo available (Ctrl+Z).\n\n"
                preview += "Continue?"

                if c4d.gui.QuestionDialog(preview):
                    fixes = fix_fps_range(doc)
                    if fixes:
                        fix_msg = f"Applied {len(fixes)} fix(es):\n\n"
                        for f in fixes[:25]:
                            fix_msg += f"  - {f}\n"
                        if len(fixes) > 25:
                            fix_msg += f"  ... and {len(fixes) - 25} more\n"
                        c4d.gui.MessageDialog(fix_msg)
                        self._dirty = True
                    else:
                        c4d.gui.MessageDialog("No fixes were applied.")
                else:
                    safe_print("FPS/range fix cancelled by user")
            else:
                safe_print("No FPS/range issues to fix")

        # ── Export QC Report ──
        elif cid == G.BTN_EXPORT_QC:
            results = {
                "lights_bad": self._lights_bad,
                "vis_bad": self._vis_bad,
                "keys_bad": self._keys_bad,
                "cam_bad": self._cam_bad,
                "rdc_count": int(check_render_conflicts(doc) or 0),
                "textures_bad": self._textures_bad,
                "unused_mats_bad": self._unused_mats_bad,
                "names_bad": self._names_bad,
                "output_bad": self._output_bad,
                "takes_bad": self._takes_bad,
                "fps_range_bad": self._fps_range_bad,
                "output_count": len(self._output_bad) if self._output_bad else 0,
                "scene_stats": self._scene_stats,
            }
            save_path = export_qc_report(doc, results, self._artist_name)
            if save_path:
                safe_print(f"QC report saved to: {save_path}")
                c4d.gui.MessageDialog(f"QC Report saved!\n\n{save_path}")

        elif cid == G.BTN_COLLECT_SCENE:
            collect_scene(doc, self._artist_name)

        elif cid == G.BTN_SAVE_VERSION:
            self._handle_save_version(doc)

        elif cid == G.BTN_EDIT_NOTES:
            self._handle_edit_notes(doc)

        elif cid == G.TAB_BAR:
            # Tab clicked — find which one is selected and switch
            if self._quicktab is not None:
                for i in range(4):
                    try:
                        if self._quicktab.IsSelected(i):
                            self._set_active_tab(i)
                            break
                    except Exception:
                        pass

        elif cid == G.COMBO_HISTORY_FILTER:
            try:
                idx = int(self.GetInt32(G.COMBO_HISTORY_FILTER))
            except Exception:
                idx = 0
            if 0 <= idx < len(self._HISTORY_FILTERS):
                self._history_filter = self._HISTORY_FILTERS[idx]
            self._update_history_area()

        return True

    # ── Scene Notes handler ──
    def _handle_edit_notes(self, doc):
        """Open the Notes dialog. On Save, persist to sidecar JSON."""
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return
        notes_path = get_notes_path(doc)
        if not notes_path:
            c4d.gui.MessageDialog(
                "Save the scene first to a folder before adding notes."
            )
            return

        notes = load_notes(notes_path)
        # Stamp scene name from filename (used in dialog title) if not yet set
        if not notes.get("scene"):
            doc_name = doc.GetDocumentName() or ""
            name_no_ext = os.path.splitext(doc_name)[0]
            base, _ver, _status = parse_version_filename(name_no_ext)
            notes["scene"] = base or name_no_ext or "scene"

        dlg = NotesDialog(notes)
        dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=560, defaulth=520)

        if dlg.confirmed and dlg.result_notes is not None:
            ok = save_notes(notes_path, dlg.result_notes)
            if ok:
                safe_print(f"Notes saved: {os.path.basename(notes_path)}")
                self._dirty = True
            else:
                c4d.gui.MessageDialog("Failed to save notes file.")
        else:
            safe_print("Notes edit cancelled by user")

    # ── Smart Save Version handler ──
    def _handle_save_version(self, doc):
        """Open the SaveVersion dialog and dispatch to smart_save_version."""
        if not doc:
            c4d.gui.MessageDialog("No active document.")
            return

        dlg = SaveVersionDialog(doc=doc, run_qc_default=True)
        try:
            dlg.Open(c4d.DLG_TYPE_MODAL, defaultw=520, defaulth=280)
        except Exception as e:
            safe_print(f"SaveVersionDialog open error: {e}")
            return

        if not dlg.confirmed:
            safe_print("Save Version cancelled by user")
            return

        result = smart_save_version(
            doc,
            comment=dlg.result_comment,
            run_qc=dlg.result_run_qc,
            artist_name=self._artist_name or "",
            status=dlg.result_status,
        )

        # Build feedback message
        if result.get("success"):
            lines = [result.get("message", "Saved")]
            if result.get("status"):
                lines.append(f"Status: {result['status']}")
            qc = result.get("qc_summary")
            if qc:
                status_word = "PASS" if qc.get("pass") else "FAIL"
                lines.append(f"QC: {qc.get('score','')}  [{status_word}]")
            hp = result.get("history_path")
            if hp:
                lines.append("")
                lines.append(f"History: {os.path.basename(hp)}")

            saved_status = (result.get("status") or "").upper()
            review_status = saved_status in ("TR", "CR", "FINAL")
            base_msg = "\n".join(lines)
            safe_print(f"Saved version v{result.get('version')} status={saved_status or 'WIP'} -> {result.get('path')}")
            self._dirty = True

            if review_status:
                # Gap 1: offer to immediately create a continuation WIP version
                # so the artist doesn't accidentally overwrite the review snapshot
                # on the next Cmd+S.
                prompt = (
                    base_msg
                    + "\n\n──────────\n"
                    + f"This {saved_status} version is locked-in for review.\n"
                    + "Continue editing in a new WIP version?\n"
                    + "(keeps the current file untouched)"
                )
                if c4d.gui.QuestionDialog(prompt):
                    cont = smart_save_version(
                        doc,
                        comment=f"Continue from v{result.get('version'):03d}_{saved_status}",
                        run_qc=False,
                        artist_name=self._artist_name or "",
                        status="",
                    )
                    if cont.get("success"):
                        safe_print(f"Continued in v{cont.get('version'):03d} WIP")
                        self._dirty = True
                    else:
                        c4d.gui.MessageDialog(
                            f"Could not create continuation version:\n\n"
                            f"{cont.get('message','unknown error')}"
                        )
            else:
                c4d.gui.MessageDialog(base_msg)
        else:
            c4d.gui.MessageDialog(f"Save Version failed:\n\n{result.get('message','unknown error')}")
            safe_print(f"Save Version failed: {result.get('message')}")

    def _scan_light_groups(self, doc):
        """Scan scene lights and return (groups_dict, ungrouped_list)"""
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

    def _is_lg_active_on_beauty(self, doc):
        """Check if All Light Groups is active on Beauty AOV"""
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

    def _toggle_light_groups(self, doc):
        """Toggle Light Groups on Beauty AOV with diagnostic"""
        if not REDSHIFT_AVAILABLE:
            c4d.gui.MessageDialog("Redshift module not available.")
            return

        vprs = _get_rs_videopost(doc)
        if not vprs:
            c4d.gui.MessageDialog("Redshift VideoPost not found.")
            return

        groups, ungrouped = self._scan_light_groups(doc)
        lg_active = self._is_lg_active_on_beauty(doc)

        if not groups and not ungrouped:
            c4d.gui.MessageDialog("No lights found in the scene.")
            return

        # Build diagnostic message
        msg = f"LIGHT GROUPS — {'ACTIVE' if lg_active else 'INACTIVE'}\n\n"
        if groups:
            msg += f"Groups ({len(groups)}):\n"
            for gname, lights in sorted(groups.items()):
                msg += f"  [{gname}]: {', '.join(lights)}\n"
        if ungrouped:
            msg += f"\nUngrouped ({len(ungrouped)}): {', '.join(ungrouped)}\n"
            msg += f"  (These contribute to all groups)\n"

        if not groups:
            msg += "\nNo light groups assigned.\nAssign groups on your RS lights first."
            c4d.gui.MessageDialog(msg)
            return

        if lg_active:
            msg += "\nDeactivate Light Groups on Beauty AOV?"
        else:
            msg += "\nActivate Light Groups on Beauty AOV?"

        if not c4d.gui.QuestionDialog(msg):
            return

        # Toggle on Beauty AOV
        try:
            aovs = redshift.RendererGetAOVs(vprs)
            found = False
            for aov in aovs:
                try:
                    if aov.GetParameter(c4d.REDSHIFT_AOV_NAME) == "Beauty":
                        new_state = not lg_active
                        aov.SetParameter(c4d.REDSHIFT_AOV_LIGHTGROUP_ALL, new_state)
                        found = True
                        break
                except Exception:
                    pass

            if found:
                redshift.RendererSetAOVs(vprs, aovs)
                check_cache.clear()
                c4d.EventAdd()
                if not lg_active:
                    safe_print(f"Light Groups activated ({len(groups)} groups)")
                    c4d.gui.MessageDialog(f"Light Groups ACTIVATED on Beauty\n\n"
                                         f"{len(groups)} group(s): {', '.join(sorted(groups.keys()))}\n"
                                         f"RS will generate Beauty_[GroupName] sub-AOVs.")
                else:
                    safe_print("Light Groups deactivated")
                    c4d.gui.MessageDialog("Light Groups DEACTIVATED on Beauty")
            else:
                c4d.gui.MessageDialog("Beauty AOV not found.\n\nRun Essentials or Production first.")

        except Exception as e:
            safe_print(f"Error toggling light groups: {e}")
            c4d.gui.MessageDialog(f"Error: {e}")

    def _force_aov_tier(self, doc, tier_list, tier_name):
        if not REDSHIFT_AVAILABLE:
            c4d.gui.MessageDialog("Redshift module not available.")
            return
        result = check_rs_aovs(doc, tier_list)
        if not result["missing"]:
            c4d.gui.MessageDialog(f"All {tier_name} AOVs already configured.")
            return
        missing_list = "\n".join(f"  - {n}" for n in result["missing"])
        if c4d.gui.QuestionDialog(f"Add {len(result['missing'])} {tier_name} AOVs?\n\n{missing_list}"):
            added, error = force_aov_tier(doc, tier_list)
            if error:
                c4d.gui.MessageDialog(f"Error: {error}")
            else:
                target_name = "Nuke" if int(GlobalSettings.get('comp_target', 0)) == 0 else "After Effects"
                multipart = bool(int(GlobalSettings.get('aov_multipart', 1)))
                output_mode = "Multi-Part EXR (32-bit, DWAB)" if multipart else "Direct Output (per-AOV settings)"
                safe_print(f"Added {added} {tier_name} AOVs for {target_name}")
                msg = f"Added {added} {tier_name} AOV(s)\n\n"
                msg += f"Compositor: {target_name}\n"
                msg += f"Output: {output_mode}\n\n"
                if target_name == "Nuke":
                    msg += "Depth: Z raw, Center Sample\nMotion Vectors: Raw, No Clamp, No Filter"
                else:
                    msg += "Depth: Z Normalized Inverted, Center Sample\nMotion Vectors: Normalized 0-1, Max Motion=64"
                c4d.gui.MessageDialog(msg)

    def _open_artist_folder(self):
        """Open the artist's output folder"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document!")
            return

        snapshot_open_folder(doc, self._artist_name)

    def _create_vibrate_null(self, doc):
        self._merge_c4d_file(doc, "VibrateNull.c4d")

    def _create_hierarchy(self, doc):
        self._merge_c4d_file(doc, "nulls.c4d")

    def _merge_camera_file(self, doc, filename):
        self._merge_c4d_file(doc, filename)

    def _merge_c4d_file(self, doc, filename):
        """Merge camera setup from C4D file"""
        if not doc:
            return

        try:
            # Get path to the C4D file (in the same plugin directory)
            plugin_dir = os.path.dirname(__file__)
            c4d_file = os.path.join(plugin_dir, "c4d", filename)

            # Check if file exists
            if not os.path.exists(c4d_file):
                safe_print(f"{filename} not found at: {c4d_file}")
                c4d.gui.MessageDialog(f"{filename} file not found in c4d folder")
                return

            # Merge the C4D file into the current document
            merge_doc = c4d.documents.MergeDocument(doc, c4d_file, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)

            if merge_doc:
                c4d.EventAdd()
                camera_name = filename.replace(".c4d", "").replace("cam_", "").replace("_", " ").title()
                safe_print(f"Merged {camera_name} camera setup from {filename}")
            else:
                safe_print(f"Failed to merge {filename}")

        except Exception as e:
            safe_print(f"Error merging camera file {filename}: {e}")
            c4d.gui.MessageDialog(f"Error loading camera setup: {e}")

    def _get_template_path(self):
        return os.path.join(os.path.dirname(__file__), "c4d", "new.c4d")

    def _force_render_settings(self, doc):
        """Reset all 4 render presets from template file"""
        if not doc:
            return

        template_path = self._get_template_path()
        if not os.path.exists(template_path):
            c4d.gui.MessageDialog(f"Template file not found!\n\nExpected at:\n{template_path}")
            return

        if not c4d.gui.QuestionDialog("Reset ALL render presets from template?\n\nThis replaces existing presets with standard settings."):
            return

        template_doc = None
        try:
            template_doc = c4d.documents.LoadDocument(template_path, c4d.SCENEFILTER_NONE)
            if not template_doc:
                c4d.gui.MessageDialog("Failed to load template file")
                return

            # Clone all presets from template
            standard_presets = ["previz", "pre_render", "render", "stills"]
            cloned = []
            template_rd = template_doc.GetFirstRenderData()
            while template_rd:
                name = normalize_preset_name(template_rd.GetName() or "")
                if name in standard_presets:
                    clone = template_rd.GetClone(c4d.COPYFLAGS_NONE)
                    cloned.append(clone)
                template_rd = template_rd.GetNext()

            # Kill template before modifying scene
            c4d.documents.KillDocument(template_doc)
            template_doc = None

            if not cloned:
                c4d.gui.MessageDialog("No standard presets found in template")
                return

            # Remove existing presets
            rd = doc.GetFirstRenderData()
            while rd:
                next_rd = rd.GetNext()
                rd.Remove()
                rd = next_rd

            # Insert cloned presets
            for clone in cloned:
                doc.InsertRenderData(clone)

            doc.SetActiveRenderData(cloned[0])
            self._active_preset = "previz"
            self._update_preset_buttons()
            check_cache.clear()
            c4d.EventAdd()

            safe_print(f"Reset {len(cloned)} presets from template")
            c4d.gui.MessageDialog(f"Reset {len(cloned)} render presets from template\n\n"
                                 f"Active: {cloned[0].GetName()}\n"
                                 f"Resolution: {int(cloned[0][c4d.RDATA_XRES])}x{int(cloned[0][c4d.RDATA_YRES])}")

        except Exception as e:
            safe_print(f"Error resetting presets: {e}")
            c4d.gui.MessageDialog(f"Error: {e}")
        finally:
            if template_doc:
                c4d.documents.KillDocument(template_doc)

    def _toggle_aspect(self, doc):
        """Toggle between 16:9 and 9:16 aspect ratio"""
        if not doc:
            return

        try:
            rd = doc.GetActiveRenderData()
            if not rd:
                c4d.gui.MessageDialog("No active render preset")
                return

            old_w = int(rd[c4d.RDATA_XRES])
            old_h = int(rd[c4d.RDATA_YRES])
            is_vertical = old_h > old_w

            if is_vertical:
                # Currently vertical → switch to horizontal 16:9
                if old_h >= 3840:
                    w, h = 3840, 2160
                elif old_h >= 1920:
                    w, h = 1920, 1080
                else:
                    w, h = 1280, 720
            else:
                # Currently horizontal → switch to vertical 9:16
                if old_w >= 3840:
                    w, h = 2160, 3840
                elif old_w >= 1920:
                    w, h = 1080, 1920
                else:
                    w, h = 720, 1280

            rd[c4d.RDATA_XRES] = w
            rd[c4d.RDATA_YRES] = h

            check_cache.clear()
            c4d.EventAdd()
            self._update_preset_buttons()
            self._update_aspect_button()

            label = "16:9" if w > h else "9:16"
            safe_print(f"Aspect: {old_w}x{old_h} → {w}x{h} ({label})")

        except Exception as e:
            safe_print(f"Error toggling aspect: {e}")

    def _update_aspect_button(self):
        """Update the aspect button label based on current render data"""
        try:
            doc = c4d.documents.GetActiveDocument()
            if doc:
                rd = doc.GetActiveRenderData()
                if rd:
                    w = int(rd[c4d.RDATA_XRES])
                    h = int(rd[c4d.RDATA_YRES])
                    is_vertical = h > w
                    self.SetString(G.BTN_FORCE_VERTICAL, "Force 16:9" if is_vertical else "Force 9:16")
        except Exception:
            pass

    def _hierarchy_to_layers(self, doc):
        """Link main project nulls and their children to layers with matching names"""
        if not doc:
            return

        safe_print("Starting Hierarchy to Layers sync...")

        # Check for objects outside nulls first
        root_objects = []
        orphan_objects = []

        obj = doc.GetFirstObject()
        while obj:
            # Only consider top-level objects
            if obj.GetUp() is None:
                if obj.GetType() == c4d.Onull:
                    root_objects.append(obj)
                else:
                    # Check if it's a camera or light (they might be allowed outside)
                    obj_type = obj.GetType()
                    if obj_type not in [c4d.Ocamera, c4d.Olight]:
                        orphan_objects.append(obj)
            obj = obj.GetNext()

        # If there are orphan objects, show error
        if orphan_objects:
            orphan_names = [obj.GetName() for obj in orphan_objects[:5]]  # Show first 5
            more = f" and {len(orphan_objects)-5} more" if len(orphan_objects) > 5 else ""

            msg = f"Found {len(orphan_objects)} object(s) outside of null groups:\n"
            msg += "\n".join(orphan_names) + more
            msg += "\n\nPlease organize all objects into null groups first."
            c4d.gui.MessageDialog(msg)
            safe_print(f"Aborted: {len(orphan_objects)} objects found outside null groups")
            return

        # No orphans, proceed with layer sync
        if not root_objects:
            c4d.gui.MessageDialog("No null groups found in the scene.")
            return

        # Start undo
        doc.StartUndo()

        # Get or create layer root
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            safe_print("Error: Could not get layer root")
            doc.EndUndo()
            return

        created_layers = 0
        updated_layers = 0

        for null in root_objects:
            null_name = null.GetName()

            # Find or create layer with matching name (returns layer and is_new flag)
            layer, is_new = self._find_or_create_layer(doc, layer_root, null_name)

            if layer:
                # Assign null and all children to this layer
                self._assign_to_layer_recursive(doc, null, layer)

                if is_new:
                    created_layers += 1
                    safe_print(f"Created new layer '{null_name}' and synced objects")
                else:
                    updated_layers += 1
                    safe_print(f"Updated existing layer '{null_name}' with objects")

        doc.EndUndo()
        c4d.EventAdd()

        # Just report to console, no popup
        safe_print(f"Hierarchy→Layers complete: {created_layers} new, {updated_layers} updated layers, {len(root_objects)} nulls synced")

    def _find_or_create_layer(self, doc, layer_root, name):
        """Find existing layer by name or create new one. Returns (layer, is_new)"""
        # First, search for existing layer
        layer = layer_root.GetDown()
        while layer:
            if layer.GetName() == name:
                return layer, False  # Found existing
            layer = layer.GetNext()

        # Create new layer
        new_layer = c4d.documents.LayerObject()
        new_layer.SetName(name)
        new_layer.InsertUnder(layer_root)

        # Generate unique random color based on layer name hash
        # This ensures same name always gets same color (consistent)
        import hashlib

        # Create hash from name
        name_hash = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)

        # Generate pleasant, distinct colors using golden ratio
        # This creates visually distinct colors that are evenly distributed
        golden_ratio = 0.618033988749895
        hue = (name_hash * golden_ratio) % 1.0

        # Convert HSV to RGB (S=0.6, V=0.95 for pleasant, bright colors)
        saturation = 0.6
        value = 0.95

        def hsv_to_rgb(h, s, v):
            """Convert HSV to RGB"""
            h_i = int(h * 6)
            f = h * 6 - h_i
            p = v * (1 - s)
            q = v * (1 - f * s)
            t = v * (1 - (1 - f) * s)

            if h_i == 0:
                r, g, b = v, t, p
            elif h_i == 1:
                r, g, b = q, v, p
            elif h_i == 2:
                r, g, b = p, v, t
            elif h_i == 3:
                r, g, b = p, q, v
            elif h_i == 4:
                r, g, b = t, p, v
            else:
                r, g, b = v, p, q

            return c4d.Vector(r, g, b)

        unique_color = hsv_to_rgb(hue, saturation, value)
        new_layer[c4d.ID_LAYER_COLOR] = unique_color

        doc.AddUndo(c4d.UNDOTYPE_NEW, new_layer)
        return new_layer, True  # Return new layer and flag

    def _solo_layers(self, doc):
        """Solo selected layers - disable all other layers and their objects"""
        if not doc:
            return

        # Check if any layers are currently disabled (solo is active)
        # If so, restore all layers
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            safe_print("Error: Could not get layer root")
            return

        # Check if we're in solo mode
        def check_solo_mode(layer):
            """Check if any layer is disabled (indicating solo mode)"""
            while layer:
                if not layer[c4d.ID_LAYER_VIEW]:
                    return True
                child = layer.GetDown()
                if child and check_solo_mode(child):
                    return True
                layer = layer.GetNext()
            return False

        first_layer = layer_root.GetDown()
        if first_layer and check_solo_mode(first_layer):
            # We're in solo mode, restore all
            self._unsolo_layers(doc)
            return

        # Get all selected layers
        selected_layers = []

        def collect_selected_layers(layer):
            """Recursively collect selected layers"""
            while layer:
                if layer.GetBit(c4d.BIT_ACTIVE):
                    selected_layers.append(layer)
                # Check children
                child = layer.GetDown()
                if child:
                    collect_selected_layers(child)
                layer = layer.GetNext()

        # Start from first layer
        first_layer = layer_root.GetDown()
        if not first_layer:
            c4d.gui.MessageDialog("No layers found in the scene.\nCreate layers first using Hierarchy→Layers.")
            return

        collect_selected_layers(first_layer)

        if not selected_layers:
            c4d.gui.MessageDialog("Please select one or more layers to solo.")
            return

        safe_print(f"Solo mode: Isolating {len(selected_layers)} layer(s)")

        # Start undo
        doc.StartUndo()

        # Track what we're doing
        layers_disabled = 0
        layers_soloed = 0
        objects_affected = 0

        # First pass: Process all layers
        def process_layer(layer, is_soloed):
            """Process a layer and return count of affected objects"""
            nonlocal layers_disabled, layers_soloed

            doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

            if is_soloed:
                # Enable this layer
                layer[c4d.ID_LAYER_VIEW] = True
                layer[c4d.ID_LAYER_RENDER] = True
                layer[c4d.ID_LAYER_MANAGER] = True
                layer[c4d.ID_LAYER_GENERATORS] = True
                layer[c4d.ID_LAYER_DEFORMERS] = True
                layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = True
                layer[c4d.ID_LAYER_LOCKED] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = True
                layers_soloed += 1
                safe_print(f"  Enabled layer: {layer.GetName()}")
            else:
                # Disable this layer completely
                layer[c4d.ID_LAYER_VIEW] = False
                layer[c4d.ID_LAYER_RENDER] = False
                layer[c4d.ID_LAYER_MANAGER] = False
                layer[c4d.ID_LAYER_GENERATORS] = False
                layer[c4d.ID_LAYER_DEFORMERS] = False
                layer[c4d.ID_LAYER_EXPRESSIONS] = False  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = False
                layers_disabled += 1

        # Process all layers
        def process_all_layers(layer):
            while layer:
                is_selected = layer in selected_layers
                process_layer(layer, is_selected)

                # Process children
                child = layer.GetDown()
                if child:
                    process_all_layers(child)

                layer = layer.GetNext()

        process_all_layers(first_layer)

        # Second pass: Handle objects without layers (disable them too)
        def disable_unassigned_objects(obj):
            """Disable objects not assigned to any layer"""
            nonlocal objects_affected

            while obj:
                # Check if object has no layer assignment
                if not obj.GetLayerObject(doc):
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                    # Disable the object
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 1  # Hide in editor
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 1  # Hide in render

                    # Disable generators and deformers
                    obj.SetDeformMode(False)

                    # If it's a generator, try to disable it
                    if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                        obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = False

                    objects_affected += 1

                # Process children
                child = obj.GetDown()
                if child:
                    disable_unassigned_objects(child)

                obj = obj.GetNext()

        # Disable unassigned objects
        first_object = doc.GetFirstObject()
        if first_object:
            disable_unassigned_objects(first_object)

        doc.EndUndo()
        c4d.EventAdd()

        # Report to console
        safe_print(f"Solo Layers complete: {layers_soloed} soloed, {layers_disabled} disabled, {objects_affected} unassigned objects hidden")

    def _unsolo_layers(self, doc):
        """Restore all layers to their default visible state"""
        if not doc:
            return

        safe_print("Restoring all layers...")

        # Get layer root
        layer_root = doc.GetLayerObjectRoot()
        if not layer_root:
            return

        doc.StartUndo()

        layers_restored = 0

        def restore_layer(layer):
            """Restore a layer to default visible state"""
            nonlocal layers_restored

            while layer:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, layer)

                # Enable everything
                layer[c4d.ID_LAYER_VIEW] = True
                layer[c4d.ID_LAYER_RENDER] = True
                layer[c4d.ID_LAYER_MANAGER] = True
                layer[c4d.ID_LAYER_GENERATORS] = True
                layer[c4d.ID_LAYER_DEFORMERS] = True
                layer[c4d.ID_LAYER_EXPRESSIONS] = True  # This controls XPresso
                layer[c4d.ID_LAYER_ANIMATION] = True
                layer[c4d.ID_LAYER_LOCKED] = False
                # Try XPresso specific flag if it exists
                if hasattr(c4d, 'ID_LAYER_XPRESSO'):
                    layer[c4d.ID_LAYER_XPRESSO] = True

                layers_restored += 1

                # Process children
                child = layer.GetDown()
                if child:
                    restore_layer(child)

                layer = layer.GetNext()

        # Restore all layers
        first_layer = layer_root.GetDown()
        if first_layer:
            restore_layer(first_layer)

        # Restore objects without layers
        def restore_unassigned_objects(obj):
            while obj:
                if not obj.GetLayerObject(doc):
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = 2  # Show
                    obj[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = 2  # Show
                    obj.SetDeformMode(True)
                    if obj.GetType() in [c4d.Oarray, c4d.Osymmetry, c4d.Oboole, c4d.Oinstance]:
                        obj[c4d.ID_BASEOBJECT_GENERATOR_FLAG] = True

                child = obj.GetDown()
                if child:
                    restore_unassigned_objects(child)

                obj = obj.GetNext()

        first_object = doc.GetFirstObject()
        if first_object:
            restore_unassigned_objects(first_object)

        doc.EndUndo()
        c4d.EventAdd()

        safe_print(f"Restored {layers_restored} layers to visible state")

    def _assign_to_layer_recursive(self, doc, obj, layer):
        """Assign object and all its children to a layer"""
        if not obj or not layer:
            return

        # Add undo for the object
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

        # Assign to layer
        obj.SetLayerObject(layer)

        # Process all children recursively
        child = obj.GetDown()
        while child:
            self._assign_to_layer_recursive(doc, child, layer)
            child = child.GetNext()

    def _drop_to_floor(self, doc):
        """Drop selected objects to floor (Y=0 plane) - handles rotation and hierarchy correctly"""
        if not doc:
            return

        # Get selected objects
        selected = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_SELECTIONORDER)
        if not selected:
            safe_print("Please select one or more objects to drop to floor")
            return

        # Start undo
        doc.StartUndo()

        dropped_count = 0

        for obj in selected:
            # Get object's global matrix
            mg = obj.GetMg()

            # Get cache (the actual geometry for display/render)
            cache = obj.GetCache()
            if cache is None:
                cache = obj.GetDeformCache()

            # If we have a cache, use it to get the accurate global bounding box
            if cache:
                # Initialize with first point
                min_y = None

                # Recursively process cache and all children
                def process_cache(cache_obj, parent_mg):
                    """Recursively get all points from cache hierarchy"""
                    nonlocal min_y

                    if not cache_obj:
                        return

                    # Get cache's local matrix
                    cache_mg = cache_obj.GetMl()
                    # Combine with parent matrix to get global position
                    global_mg = parent_mg * cache_mg

                    # Get points if this is a PointObject
                    if cache_obj.CheckType(c4d.Opoint):
                        points = cache_obj.GetAllPoints()
                        if points:
                            for point in points:
                                # Transform point to global space
                                global_point = global_mg * point
                                if min_y is None or global_point.y < min_y:
                                    min_y = global_point.y

                    # Process children
                    child = cache_obj.GetDown()
                    if child:
                        process_cache(child, global_mg)

                    # Process siblings
                    next_obj = cache_obj.GetNext()
                    if next_obj:
                        process_cache(next_obj, parent_mg)

                # Process cache hierarchy
                process_cache(cache, mg)

                # If we didn't find any points, fall back to bounding box method
                if min_y is None:
                    # Use bounding box as fallback
                    mp = obj.GetMp()
                    rad = obj.GetRad()

                    if rad.GetLength() == 0:
                        rad = c4d.Vector(50, 50, 50)

                    # Calculate all 8 corners
                    corners = [
                        c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                        c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                    ]

                    min_y = float('inf')
                    for corner in corners:
                        world_corner = mg * corner
                        if world_corner.y < min_y:
                            min_y = world_corner.y
            else:
                # No cache - use bounding box method
                mp = obj.GetMp()
                rad = obj.GetRad()

                if rad.GetLength() == 0:
                    rad = c4d.Vector(50, 50, 50)

                # Calculate all 8 corners
                corners = [
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z - rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y - rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x - rad.x, mp.y + rad.y, mp.z + rad.z),
                    c4d.Vector(mp.x + rad.x, mp.y + rad.y, mp.z + rad.z)
                ]

                min_y = float('inf')
                for corner in corners:
                    world_corner = mg * corner
                    if world_corner.y < min_y:
                        min_y = world_corner.y

            # Calculate how much to move the object
            if min_y is not None and abs(min_y) > 0.001:  # Small threshold to avoid tiny movements
                move_distance = -min_y

                # Record undo for position change
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)

                # Move the object in global space
                current_pos = obj.GetAbsPos()
                new_pos = c4d.Vector(current_pos.x, current_pos.y + move_distance, current_pos.z)
                obj.SetAbsPos(new_pos)

                dropped_count += 1
                safe_print(f"Dropped '{obj.GetName()}' by {move_distance:.2f} units")

        # End undo
        doc.EndUndo()

        # Update the scene
        c4d.EventAdd()

        # Show result message in console only (no popup for smooth workflow)
        if dropped_count == 1:
            safe_print(f"Dropped 1 object to floor")
        elif dropped_count > 1:
            safe_print(f"Dropped {dropped_count} objects to floor")
        else:
            safe_print("No objects needed dropping - already on floor")

    def _take_renderview_snapshot(self):
        """Take a snapshot from RenderView"""
        doc = c4d.documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document!")
            return

        if not self._artist_name:
            c4d.gui.MessageDialog("Please set your artist name first!")
            return

        snapshot_save_still(doc, self._artist_name)

    def _apply_abc_retime_tag(self):
        """Apply ABC Retime tag to selected object(s)"""
        doc = documents.GetActiveDocument()
        if not doc:
            c4d.gui.MessageDialog("No active document")
            return

        selection = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN)
        if not selection:
            c4d.gui.MessageDialog("Please select an object first\n\n(Works with Alembic, Point Cache, Mograph Cache, or X-Particles Cache objects)")
            return

        # ABC Retime plugin ID
        ABC_RETIME_TAG_ID = 1058910

        applied_count = 0
        skipped_count = 0
        failed_count = 0

        for obj in selection:
            # Check if tag already exists
            existing_tag = obj.GetTag(ABC_RETIME_TAG_ID)
            if existing_tag:
                safe_print(f"ABC Retime tag already exists on {obj.GetName()}")
                skipped_count += 1
                continue

            # Apply the tag
            tag = obj.MakeTag(ABC_RETIME_TAG_ID)
            if tag:
                applied_count += 1
                safe_print(f"ABC Retime tag applied to {obj.GetName()}")
            else:
                failed_count += 1
                safe_print(f"Failed to apply ABC Retime tag to {obj.GetName()}")

        # Update the scene
        if applied_count > 0:
            c4d.EventAdd()

        # Show error message only if failed
        if applied_count == 0 and skipped_count == 0:
            c4d.gui.MessageDialog("ABC Retime tag could not be applied\n\nPossible reasons:\n- ABC Retime plugin not installed\n- Invalid object type\n\nManual access: Right-click Tags → Extensions → Alembic Retime")

    def DestroyWindow(self):
        """Clean up when panel closes"""
        pass  # No cleanup needed anymore

def _select_objects(doc, objs):
    """Select objects in the scene"""
    if not doc or not objs:
        return

    first = doc.GetFirstObject()
    if first:
        for o in _iter_objs(first):
            o.DelBit(c4d.BIT_ACTIVE)

    for o in objs:
        try:
            if o:
                o.SetBit(c4d.BIT_ACTIVE)
        except Exception:
            pass

    c4d.EventAdd()

# -------------- registration --------------
class YSPanelCmd(plugins.CommandData):
    dlg = None

    def Execute(self, doc):
        if self.dlg is None:
            self.dlg = YSPanel()
            safe_print(f"{PLUGIN_NAME} initialized")
        # Pass plugin ID as second argument for layout persistence
        return self.dlg.Open(dlgtype=c4d.DLG_TYPE_ASYNC, pluginid=PLUGIN_ID,
                            defaultw=420, defaulth=360)

    def RestoreLayout(self, sec_ref):
        """Required for layout persistence - called when C4D restores layouts"""
        if self.dlg is None:
            self.dlg = YSPanel()
        # Restore the dialog with the plugin ID
        return self.dlg.Restore(pluginid=PLUGIN_ID, secret=sec_ref)

def Register():
    # Load plugin icon (PNG format for best Cinema 4D compatibility).
    # Tries the new Sentinel icon first; falls back to legacy YS Guardian icon
    # if the new file is missing (defensive — should never happen in practice).
    icon = c4d.bitmaps.BaseBitmap()
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    candidates = [
        os.path.join(icons_dir, "Sentinel_IC_v02.png"),
        os.path.join(icons_dir, "Sentinel_IC_v01.png"),  # previous Sentinel icon
        os.path.join(icons_dir, "ys-logo-alpha-32.png"),  # legacy YS Guardian fallback
    ]

    icon_path = None
    for candidate in candidates:
        if os.path.exists(candidate):
            icon_path = candidate
            break

    if icon_path:
        result = icon.InitWith(icon_path)
        if result[0] == c4d.IMAGERESULT_OK:
            width = icon.GetBw()
            height = icon.GetBh()
            depth = icon.GetBt()
            safe_print(f"Plugin icon loaded: {os.path.basename(icon_path)} ({width}x{height}, {depth}-bit)")
        else:
            safe_print(f"Warning: Failed to load icon from {icon_path}")
            icon = None
    else:
        safe_print(f"Warning: No icon found in {icons_dir}")
        icon = None

    ok = plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        icon=icon,
        help="Open Sentinel Panel",
        dat=YSPanelCmd()
    )
    if ok:
        safe_print(f"{PLUGIN_NAME} registered successfully")
    else:
        safe_print("Failed to register Guardian panel")
    return ok

if __name__ == "__main__":
    # Print setup info using safe_print to avoid None returns in console
    safe_print("\n" + "="*50)
    safe_print(f"{PLUGIN_NAME}")
    safe_print(f"  Snapshot dir: {GlobalSettings.get_snapshot_dir()}")
    safe_print(f"  9 Quality Checks | ACES tone mapping")
    safe_print("="*50 + "\n")

    Register()