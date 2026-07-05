# -*- coding: utf-8 -*-
"""Cross-aspect safe-area math and scene helpers."""

import math as _math

import c4d

from sentinel.common.helpers import _safe_name, safe_print
from sentinel.multiformat import (
    MULTIFORMAT_DEFS,
    _resolve_source_camera,
    _resolve_source_render_data,
    format_aspect,
    get_multiformat_def,
)

# ============================================================
# Cross-Aspect Safe-Area QC (#12) — Pure helpers
# ============================================================
# Per-format safe-area insets: fraction of frame "consumed" by
# platform UI overlays (caption text, social icons, headers).
# Top/bottom/left/right are expressed as fractions [0..1) of the
# FULL frame extent in that axis.
#
# Defaults derived from real platform specs (Meta creator guide
# for Reels, IG Stories UI, TikTok layout, broadcast standards):
#  - 16x9: broadcast 5% all around (legacy CRT overscan)
#  - 9x16: 8/15/5/10 — IG Reels caption + icon stack on right
#  - 1x1:  feed shows captions BELOW the media, minimal overlay
#  - 4x5:  feed portrait, slight bottom UI
#  - 21x9: cinema, no social overlays
SAFE_AREA_INSETS = {
    "16x9": {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05},
    "9x16": {"top": 0.08, "bottom": 0.15, "left": 0.05, "right": 0.10},
    "1x1":  {"top": 0.05, "bottom": 0.08, "left": 0.05, "right": 0.05},
    "4x5":  {"top": 0.05, "bottom": 0.10, "left": 0.05, "right": 0.05},
    "21x9": {"top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05},
}


def _safe_area_insets(fmt_id, rules_context=None, fallback=None):
    try:
        if rules_context is not None:
            insets = rules_context.params.get("safe_area_insets", {}).get(fmt_id)
            if insets:
                return insets
    except Exception:
        pass
    return SAFE_AREA_INSETS.get(fmt_id, fallback)


def safe_area_ndc_box(fmt_id, rules_context=None):
    """Return safe-area rectangle in NDC space (Normalized Device Coords).

    NDC convention used by Sentinel:
      x in [-1, +1] left→right
      y in [-1, +1] bottom→top  (C4D camera +Y is up)

    A point (ndc_x, ndc_y) is inside the safe area iff:
        left <= ndc_x <= right  AND  bottom <= ndc_y <= top

    Unknown format ids return the full NDC range (no insets) so
    the check degrades gracefully instead of false-positive flooding.
    """
    insets = _safe_area_insets(fmt_id, rules_context, fallback=None)
    if not insets:
        return {"left": -1.0, "right": 1.0, "bottom": -1.0, "top": 1.0}
    return {
        "left":   -1.0 + 2.0 * insets["left"],
        "right":   1.0 - 2.0 * insets["right"],
        "bottom": -1.0 + 2.0 * insets["bottom"],
        "top":     1.0 - 2.0 * insets["top"],
    }


def format_safe_area_in_master_ndc(fmt_id, master_aspect, rules_context=None, offset=None):
    """Return the format's safe-area rectangle expressed in MASTER NDC.

    This is the "crop interpretation" of cross-aspect safe area —
    it answers: "if I were to crop the master view (e.g. 16:9) into
    this delivery format, where would the safe area land in master
    coordinates?" — which is what the artist composes against in the
    GSG Social Frame workflow.

    Math:
      Let M_a = master_aspect, F_a = format_aspect.
      The format's centered crop region in master NDC:
        - F_a <= M_a (taller-or-equal than master): vertical fills
          the master, horizontal is narrowed to ±(F_a / M_a).
        - F_a >  M_a (wider than master): horizontal fills the master,
          vertical is narrowed to ±(M_a / F_a).
      Within that crop region, per-side insets shrink the safe rect.

    Args:
        fmt_id: format id ('16x9', '9x16', '1x1', '4x5', '21x9')
        master_aspect: master frame aspect (W / H), e.g. 1.778 for 16:9
        offset: optional (x, y) nudge as fractional travel within the master
            crop frame. None/(0, 0) preserves the previous centered behavior.

    Returns:
        dict {left, right, bottom, top} — bounds expressed in master
        NDC ([-1, +1] in both axes). Caller projects bbox corners to
        master NDC once, then checks against this rect for each format.
    """
    fmt_def = get_multiformat_def(fmt_id)
    if not fmt_def or master_aspect is None or master_aspect <= 0:
        return {"left": -1.0, "right": 1.0, "bottom": -1.0, "top": 1.0}

    f_aspect = format_aspect(fmt_def)
    insets = _safe_area_insets(fmt_id, rules_context, {
        "top": 0.05, "bottom": 0.05, "left": 0.05, "right": 0.05,
    })

    if f_aspect <= master_aspect:
        # Format is taller than master (or equal): vertical fills master.
        crop_x = f_aspect / master_aspect  # half-width in master NDC
        crop_y = 1.0
    else:
        # Format is wider than master: horizontal fills master.
        crop_x = 1.0
        crop_y = master_aspect / f_aspect  # half-height in master NDC

    shift_x = 0.0
    shift_y = 0.0
    if offset is not None:
        try:
            offset_x, offset_y = offset
            offset_x = max(-1.0, min(1.0, float(offset_x)))
            offset_y = max(-1.0, min(1.0, float(offset_y)))
            shift_x = (1.0 - crop_x) * offset_x
            # Positive C4DMultiFrame Y nudge moves down; master NDC Y grows up.
            shift_y = -(1.0 - crop_y) * offset_y
        except Exception:
            shift_x = 0.0
            shift_y = 0.0

    # Apply per-side insets within the crop region.
    return {
        "left":   -crop_x + shift_x + (2.0 * crop_x) * insets["left"],
        "right":   crop_x + shift_x - (2.0 * crop_x) * insets["right"],
        "bottom": -crop_y + shift_y + (2.0 * crop_y) * insets["bottom"],
        "top":     crop_y + shift_y - (2.0 * crop_y) * insets["top"],
    }


def project_world_to_ndc(camera_mg_inv, world_point, h_fov_rad, aspect):
    """Project a world-space point to normalized device coords.

    Args:
        camera_mg_inv: inverse of camera global matrix (world→camera).
                       Caller should compute `~camera.GetMg()` once and
                       reuse for many points (matrix inversion is the
                       expensive part).
        world_point:   c4d.Vector in world space.
        h_fov_rad:     camera horizontal FOV in radians (CAMERAOBJECT_FOV).
        aspect:        target frame aspect = width / height.

    Returns:
        tuple (ndc_x, ndc_y, in_front).
        in_front = False when the point is at or behind the camera plane
        (z <= 0 in camera-local space) — ndc values then are not meaningful.

    Math (perspective projection, C4D left-handed +Z forward):
        Cinema 4D uses a left-handed coordinate system; the camera's local
        +Z axis points INTO the scene (the direction the camera looks).
        Points in front of the camera therefore have p_cam.z > 0 (verified
        empirically — early v1.5.5 dev iterations assumed -Z forward and
        wrongly tagged every visible point as "behind camera").

            p_cam = camera_mg_inv * p_world
            ndc_x = (p_cam.x / tan(h_fov/2)) / p_cam.z
            ndc_y = (p_cam.y / tan(v_fov/2)) / p_cam.z
            v_fov derived from h_fov + aspect: tan(v/2) = tan(h/2) / aspect
    """
    p_cam = camera_mg_inv * world_point
    if p_cam.z <= 0:
        return (0.0, 0.0, False)
    half_h = h_fov_rad * 0.5
    tan_h = _math.tan(half_h)
    if tan_h <= 0:
        return (0.0, 0.0, False)
    tan_v = tan_h / aspect if aspect > 0 else tan_h
    ndc_x = (p_cam.x / tan_h) / p_cam.z
    ndc_y = (p_cam.y / tan_v) / p_cam.z
    return (ndc_x, ndc_y, True)


def world_bbox_corners(obj):
    """Compute the 8 world-space corners of an object's axis-aligned
    bounding box, falling back to cache geometry for generators
    (cloners, MoText, splines) where `GetRad()` is stale or zero.

    Returns:
        list[c4d.Vector] — typically 8 corners. Single-element list
        [origin] if no extent could be determined (degenerate case).
    """
    if obj is None:
        return []
    mp = obj.GetMp()
    rad = obj.GetRad()
    mg = obj.GetMg()
    has_extent = (abs(rad.x) > 1e-6 or
                  abs(rad.y) > 1e-6 or
                  abs(rad.z) > 1e-6)
    if not has_extent:
        cached = _walk_cache_for_extent(obj)
        if cached is not None:
            mp, rad = cached
            has_extent = True
    if not has_extent:
        return [mg.off]
    corners = []
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                local = c4d.Vector(mp.x + sx * rad.x,
                                   mp.y + sy * rad.y,
                                   mp.z + sz * rad.z)
                corners.append(mg * local)
    return corners


def _walk_cache_for_extent(obj):
    """Recursively walk `obj.GetDeformCache()` / `obj.GetCache()` to find
    real geometry, accumulating an AABB across all leaves.

    Returns:
        tuple (mp, rad) in obj's LOCAL space (cache shares obj's frame),
        or None if no extent was found anywhere in the cache tree.
    """
    if obj is None:
        return None
    cache = obj.GetDeformCache() or obj.GetCache()
    if cache is None:
        return None
    state = {"min": None, "max": None}

    def _accumulate(node):
        if node is None:
            return
        m, r = node.GetMp(), node.GetRad()
        if abs(r.x) > 1e-6 or abs(r.y) > 1e-6 or abs(r.z) > 1e-6:
            mn = c4d.Vector(m.x - r.x, m.y - r.y, m.z - r.z)
            mx = c4d.Vector(m.x + r.x, m.y + r.y, m.z + r.z)
            if state["min"] is None:
                state["min"] = mn
                state["max"] = mx
            else:
                state["min"] = c4d.Vector(min(state["min"].x, mn.x),
                                          min(state["min"].y, mn.y),
                                          min(state["min"].z, mn.z))
                state["max"] = c4d.Vector(max(state["max"].x, mx.x),
                                          max(state["max"].y, mx.y),
                                          max(state["max"].z, mx.z))
        sub = node.GetDeformCache() or node.GetCache()
        if sub is not None:
            _accumulate(sub)
        child = node.GetDown()
        while child is not None:
            _accumulate(child)
            child = child.GetNext()

    _accumulate(cache)
    if state["min"] is None:
        return None
    mn, mx = state["min"], state["max"]
    mp = c4d.Vector((mn.x + mx.x) * 0.5,
                    (mn.y + mx.y) * 0.5,
                    (mn.z + mx.z) * 0.5)
    rad = c4d.Vector((mx.x - mn.x) * 0.5,
                     (mx.y - mn.y) * 0.5,
                     (mx.z - mn.z) * 0.5)
    return (mp, rad)


def corners_violation_sides(corners_ndc, safe_box):
    """Identify which sides of `safe_box` are exceeded by any of the
    projected corners.

    Args:
        corners_ndc: list of (ndc_x, ndc_y) tuples — corners that
                     project IN FRONT of the camera. Caller should
                     filter out behind-camera corners (in_front=False).
        safe_box:    dict {left, right, bottom, top} from
                     `safe_area_ndc_box(fmt_id)`.

    Returns:
        set[str] — subset of {"left", "right", "bottom", "top"}.
        Empty set means the bbox is fully inside the safe area
        (or corners_ndc is empty — caller decides what to do with
        the "all-behind-camera" case).
    """
    sides = set()
    if not corners_ndc:
        return sides
    for ndc_x, ndc_y in corners_ndc:
        if ndc_x < safe_box["left"]:
            sides.add("left")
        if ndc_x > safe_box["right"]:
            sides.add("right")
        if ndc_y < safe_box["bottom"]:
            sides.add("bottom")
        if ndc_y > safe_box["top"]:
            sides.add("top")
    return sides


# ============================================================
# Cross-Aspect Safe-Area QC (#12) — UserData marker
# ============================================================
# Artists mark "important compositional elements" (logo, title,
# character) by attaching a magic UserData boolean to the object.
# We use UserData (not a custom TagData plugin) because:
#   - Zero new resource files / plugin IDs to register
#   - Persists natively in the .c4d save (no sidecar needed)
#   - Trivial to add/remove/query from Python
#
# Collision avoidance: the DESC_NAME is prefixed with "[Sentinel]"
# so it can't be confused with another plugin's UserData.

SAFE_AREA_USERDATA_NAME = "[Sentinel] Safe Area Subject"


def _find_safe_area_userdata_id(obj):
    """Walk obj's UserData container looking for the Safe Area marker.

    Returns:
        c4d.DescID of the UserData entry, or None if the object is
        not marked.
    """
    if obj is None:
        return None
    try:
        ud_container = obj.GetUserDataContainer()
    except Exception:
        return None
    if not ud_container:
        return None
    for descid, bc in ud_container:
        try:
            if bc[c4d.DESC_NAME] == SAFE_AREA_USERDATA_NAME:
                return descid
        except Exception:
            continue
    return None


def is_object_marked_safe_area(obj):
    """Return True iff `obj` carries the Safe Area marker AND it's set
    to True. (A marker entry set to False counts as 'unmarked' so
    the artist can toggle without removing the UD entry.)
    """
    descid = _find_safe_area_userdata_id(obj)
    if descid is None:
        return False
    try:
        return bool(obj[descid])
    except Exception:
        return False


def mark_object_safe_area(obj, enable=True, doc=None):
    """Mark or unmark `obj` as a Safe Area subject.

    Idempotent: calling repeatedly with the same `enable` value is a
    no-op (after the first call adds the UD entry). Calling with the
    opposite value flips the boolean without removing the entry.

    If `doc` is provided, wraps the modification in `AddUndo` so the
    artist's Cmd+Z reverts the marking action.

    Returns:
        bool — True if the operation succeeded, False on failure.
    """
    if obj is None:
        return False
    descid = _find_safe_area_userdata_id(obj)
    if descid is None:
        # First-time marking: add the UD entry
        try:
            bc = c4d.GetCustomDatatypeDefault(c4d.DTYPE_BOOL)
            bc[c4d.DESC_NAME] = SAFE_AREA_USERDATA_NAME
            bc[c4d.DESC_SHORT_NAME] = SAFE_AREA_USERDATA_NAME
            bc[c4d.DESC_DEFAULT] = bool(enable)
            bc[c4d.DESC_ANIMATE] = c4d.DESC_ANIMATE_OFF
            if doc:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
            descid = obj.AddUserData(bc)
            if descid is None:
                return False
            obj[descid] = bool(enable)
        except Exception as e:
            safe_print(f"mark_object_safe_area: AddUserData failed for "
                       f"{_safe_name(obj)}: {e}")
            return False
    else:
        # Already marked: just flip the boolean
        try:
            if doc:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
            obj[descid] = bool(enable)
        except Exception as e:
            safe_print(f"mark_object_safe_area: SetParameter failed for "
                       f"{_safe_name(obj)}: {e}")
            return False
    return True


def unmark_object_safe_area(obj, doc=None):
    """Remove the Safe Area UserData entry from `obj` entirely.

    Use this when the artist wants to clean up — `mark_object_safe_area
    (obj, False)` only sets the bool to False but leaves the UD entry.
    `unmark_object_safe_area` removes the entry, restoring the object
    to a "never been marked" state.
    """
    if obj is None:
        return False
    descid = _find_safe_area_userdata_id(obj)
    if descid is None:
        return True  # Already unmarked
    try:
        if doc:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, obj)
        return bool(obj.RemoveUserData(descid))
    except Exception as e:
        safe_print(f"unmark_object_safe_area: RemoveUserData failed for "
                   f"{_safe_name(obj)}: {e}")
        return False


def find_marked_safe_area_objects(doc):
    """Return a list of all objects in `doc` that are marked as Safe
    Area subjects (active marker = True).

    Walks the full document hierarchy depth-first via GetDown/GetNext.
    """
    if doc is None:
        return []
    result = []

    def _walk(op):
        while op is not None:
            if is_object_marked_safe_area(op):
                result.append(op)
            child = op.GetDown()
            if child is not None:
                _walk(child)
            op = op.GetNext()

    _walk(doc.GetFirstObject())
    return result


# ============================================================
# Cross-Aspect Safe-Area QC (#12) — Take resolution helpers
# ============================================================
# Resolve which camera, FOV, and frame aspect apply to each
# multi-format Take so the safe-area check can project bbox
# corners using the right perspective per Take.

def find_active_multiformat_takes(doc):
    """Find Takes whose name matches a known fmt_id from MULTIFORMAT_DEFS.

    Multi-Format Setup (v1.5.4) creates child Takes named with the
    bare fmt_id ("16x9", "9x16", ...) when the source is the Main
    take, or with a "<source>_<fmt_id>" suffix otherwise. Both
    conventions are recognized.

    Returns:
        list[(fmt_id, BaseTake)] — empty if no multi-format Takes
        are present in the document.
    """
    if not doc:
        return []
    td = doc.GetTakeData()
    if td is None:
        return []
    main = td.GetMainTake()
    if main is None:
        return []

    known_ids = {fmt["id"] for fmt in MULTIFORMAT_DEFS}
    result = []

    def _walk(take):
        while take is not None:
            name = (take.GetName() or "").strip()
            matched_id = None
            if name in known_ids:
                matched_id = name
            else:
                for kid in known_ids:
                    if name.endswith("_" + kid):
                        matched_id = kid
                        break
            if matched_id:
                result.append((matched_id, take))
            child = take.GetDown()
            if child is not None:
                _walk(child)
            take = take.GetNext()

    _walk(main.GetDown())
    return result


def get_take_camera_h_fov_rad(take, cam, td):
    """Return the camera's effective horizontal FOV (radians) in `take`.

    Resolution order:
      1. Focal-length override (CAMERA_FOCUS) — preferred since v1.5.5;
         converted back to FOV via `2·atan(aperture / (2·focal))`. This is
         what the Multi-Format Setup orchestrator writes for physical / RS
         cameras where FOV overrides get clamped to the focal-derived
         native value at render time.
      2. FOV override (CAMERAOBJECT_FOV) — legacy fallback for takes
         generated before the v1.5.5 fix, OR for non-physical cameras where
         FOV is the master.
      3. Camera's native CAMERAOBJECT_FOV.

    Override-reading pattern follows the official Maxon SDK example
    `takesystem_sphere_override_r17.py`:
        baseOverride = take.FindOverride(td, cam)
        if baseOverride.IsOverriddenParam(descid):
            value = baseOverride.GetParameter(descid, DESCFLAGS_GET_0)

    Returns:
        float (radians) or None on failure / missing camera.
    """
    if cam is None:
        return None
    focus_id = c4d.DescID(c4d.DescLevel(c4d.CAMERA_FOCUS, c4d.DTYPE_REAL, 0))
    fov_id = c4d.DescID(c4d.DescLevel(c4d.CAMERAOBJECT_FOV,
                                     c4d.DTYPE_REAL, 0))
    if take is not None and td is not None:
        try:
            base_override = take.FindOverride(td, cam)
            if base_override is not None:
                # Prefer focal-length override (v1.5.5+ convention)
                if base_override.IsOverriddenParam(focus_id):
                    focal = base_override.GetParameter(focus_id,
                                                      c4d.DESCFLAGS_GET_0)
                    if focal is not None and float(focal) > 0:
                        aperture = 36.0
                        try:
                            ap = float(cam[c4d.CAMERAOBJECT_APERTURE])
                            if ap > 0:
                                aperture = ap
                        except Exception:
                            pass
                        return 2.0 * _math.atan(aperture / (2.0 * float(focal)))
                # Legacy FOV override fallback
                if base_override.IsOverriddenParam(fov_id):
                    value = base_override.GetParameter(fov_id,
                                                       c4d.DESCFLAGS_GET_0)
                    if value is not None:
                        return float(value)
        except Exception:
            pass
    # Final fallback: camera's native FOV
    try:
        return float(cam[c4d.CAMERAOBJECT_FOV])
    except Exception:
        return None


def get_take_resolution(take, td, doc):
    """Return (width, height) ints from the render data effective in `take`.

    Multi-Format Setup overrides RDATA_XRES/YRES on the cloned render
    data per Take, so this returns the format-specific resolution.

    Returns (None, None) on failure.
    """
    if take is None or td is None or doc is None:
        return (None, None)
    rd = _resolve_source_render_data(take, td, doc)
    if rd is None:
        return (None, None)
    try:
        w = int(rd[c4d.RDATA_XRES])
        h = int(rd[c4d.RDATA_YRES])
        return (w, h)
    except Exception:
        return (None, None)


def get_take_aspect(take, td, doc):
    """Return frame aspect (width / height) for `take`.

    Returns None when resolution cannot be resolved.
    """
    w, h = get_take_resolution(take, td, doc)
    if w is None or h is None or h <= 0:
        return None
    return float(w) / float(h)


def resolve_take_projection_params(take, td, doc):
    """Resolve everything needed to project world points into a Take's frame.

    One-stop helper used by the QC #12 orchestrator: given a Take,
    returns the camera object, its inverse global matrix (for re-use
    across many points), the effective horizontal FOV (radians), and
    the frame aspect.

    Returns:
        dict with keys: camera, camera_mg_inv, h_fov_rad, aspect,
                       resolution (tuple w,h).
        Any value may be None if it couldn't be resolved — the caller
        is responsible for skipping the Take in that case.
    """
    out = {
        "camera": None,
        "camera_mg_inv": None,
        "h_fov_rad": None,
        "aspect": None,
        "resolution": (None, None),
    }
    if take is None or td is None or doc is None:
        return out
    cam = _resolve_source_camera(take, td, doc)
    out["camera"] = cam
    if cam is not None:
        try:
            out["camera_mg_inv"] = ~cam.GetMg()
        except Exception:
            out["camera_mg_inv"] = None
    out["h_fov_rad"] = get_take_camera_h_fov_rad(take, cam, td)
    out["resolution"] = get_take_resolution(take, td, doc)
    out["aspect"] = get_take_aspect(take, td, doc)
    return out


# ============================================================
# Cross-Aspect Safe-Area QC (#12) — Orchestrator
# ============================================================

def _gather_keyframe_sample_frames(obj, fps, max_samples=50):
    """Collect frame numbers worth checking for `obj`'s animation.

    Strategy: union of keyframes on PSR tracks + midpoints between
    consecutive keyframes (catches arc/ease-out swings that exit the
    safe area between two "safe" keyframes).

    Returns:
        list of int frame numbers, sorted, deduplicated. Capped at
        `max_samples` to prevent runaway sampling on heavily-keyed
        objects (we'd return early-frame samples, the user can scrub
        the timeline for full coverage if needed).
    """
    if obj is None or fps is None or fps <= 0:
        return []
    keyframes = set()
    try:
        tracks = obj.GetCTracks() or []
    except Exception:
        return []
    for track in tracks:
        try:
            curve = track.GetCurve()
            if curve is None:
                continue
            for i in range(curve.GetKeyCount()):
                key = curve.GetKey(i)
                if key is None:
                    continue
                t = key.GetTime()
                if t is None:
                    continue
                try:
                    f = t.GetFrame(fps)
                    keyframes.add(int(f))
                except Exception:
                    continue
        except Exception:
            continue

    if not keyframes:
        return []

    sorted_keys = sorted(keyframes)
    samples = set(sorted_keys)
    # Add midpoints
    for a, b in zip(sorted_keys, sorted_keys[1:]):
        if b - a > 1:
            samples.add((a + b) // 2)

    result = sorted(samples)
    if len(result) > max_samples:
        # Subsample evenly across the range
        step = max(1, len(result) // max_samples)
        result = result[::step][:max_samples]
    return result


def _evaluate_object_at_frame(doc, frame, fps):
    """Set the doc's current time to `frame` and force a scene
    re-evaluation so subsequent reads of `obj.GetMg()` reflect the
    object's pose at that frame.

    The caller is responsible for restoring the original time
    afterwards (scope it with try/finally for safety).
    """
    if doc is None or fps is None or fps <= 0:
        return
    try:
        doc.SetTime(c4d.BaseTime(int(frame), int(fps)))
        # Build flag 0 = full evaluation including animations + caches
        doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_0)
    except Exception:
        pass


def _scan_cross_aspect_safe_area(doc, sample_strategy="keyframes", rules_context=None):
    """QC #12 — verify Safe Area subjects stay within per-format safe
    areas across all active Multi-Format delivery Takes.

    Uses **CROP interpretation**: matches the artist's mental model
    of "compose once in the master frame, deliver multiple aspect
    crops" (the GSG Social Frame workflow). Every marked object's
    AABB is projected ONCE into the master take's NDC space, then
    each format's safe-area rectangle is computed in master NDC via
    `format_safe_area_in_master_ndc`, and we check whether the
    projected bbox fits.

    Why crop instead of per-take render projection:
      Under Composition Mode = None (the default), each delivery
      Take renders with the source camera UNCHANGED — it doesn't
      crop, it extends/shrinks the frustum to fit the new aspect.
      A render-mode check would say "9x16 sees MORE world vertically,
      so subject is fine" — but the artist composed in 16:9 and
      will deliver as a 9:16 CROP, expecting only the central
      vertical strip to remain. The crop interpretation catches
      this mismatch correctly.

      For Composition Mode = Resize Canvas (sensor overrides per
      Take), the crop interpretation isn't strictly accurate but
      remains a useful heuristic — the user gets advisory warnings
      based on master framing.

    Args:
        doc: active BaseDocument.
        sample_strategy: when to evaluate object pose:
          - "current_frame" — only at doc.GetTime() (cheap, but misses
            in-betweens).
          - "keyframes" (default) — sample at every PSR keyframe on
            each marked object PLUS midpoints between consecutive keys
            (catches arc swings). Falls back to "current_frame" for
            objects with no keyframes.

    Returns:
        list of violation dicts. Each:
            {
              "object":     BaseObject (live ref for select),
              "object_name": str,
              "fmt_id":     str (e.g. "9x16"),
              "sides":      set of {"left","right","bottom","top"},
              "frames":     list of int frames where the violation
                            occurred,
            }
        Empty list = pass.
    """
    if doc is None:
        return []
    marked = find_marked_safe_area_objects(doc)
    if not marked:
        return []

    mf_takes = find_active_multiformat_takes(doc)
    if not mf_takes:
        return []

    td = doc.GetTakeData()
    if td is None:
        return []

    # Resolve the MASTER projection (the frame we project into and against
    # which we measure crop regions). We use Main take — that's the source
    # the artist composed in before generating multi-format children.
    main_take = td.GetMainTake()
    if main_take is None:
        return []

    master_params = resolve_take_projection_params(main_take, td, doc)
    master_cam = master_params.get("camera")
    master_mg_inv = master_params.get("camera_mg_inv")
    master_h_fov = master_params.get("h_fov_rad")
    master_aspect = master_params.get("aspect")

    if (master_cam is None or master_mg_inv is None or
            master_h_fov is None or master_aspect is None):
        return []

    # Pre-compute each format's safe rectangle in MASTER NDC space.
    # This is the crop region (centered, fitted to format aspect) with
    # the format's per-side insets applied within it.
    format_safe_boxes = {}
    for fmt_id, _take in mf_takes:
        format_safe_boxes[fmt_id] = format_safe_area_in_master_ndc(
            fmt_id, master_aspect, rules_context)

    fps = doc.GetFps()
    original_time = doc.GetTime()
    violations = []

    try:
        for obj in marked:
            if obj is None:
                continue
            obj_name = _safe_name(obj)

            # Determine sample frames for this object
            if sample_strategy == "keyframes":
                sample_frames = _gather_keyframe_sample_frames(obj, fps)
                if not sample_frames:
                    sample_frames = [original_time.GetFrame(fps)]
                needs_time_travel = True
            else:
                sample_frames = [original_time.GetFrame(fps)]
                needs_time_travel = False

            # Per-format violation accumulators
            per_fmt = {}

            for frame in sample_frames:
                if needs_time_travel:
                    _evaluate_object_at_frame(doc, frame, fps)
                world_corners = world_bbox_corners(obj)
                if not world_corners:
                    continue

                # Project bbox corners to MASTER NDC ONCE per frame.
                corners_ndc = []
                for wp in world_corners:
                    nx, ny, in_front = project_world_to_ndc(
                        master_mg_inv, wp, master_h_fov, master_aspect)
                    if in_front:
                        corners_ndc.append((nx, ny))
                # If all corners behind master camera, the object is
                # outside the shot entirely — skip.
                if not corners_ndc:
                    continue

                # Check the same projected bbox against each format's
                # safe rectangle (all in master NDC space).
                for fmt_id, safe_box in format_safe_boxes.items():
                    sides = corners_violation_sides(corners_ndc, safe_box)
                    if not sides:
                        continue
                    rec = per_fmt.setdefault(fmt_id, {
                        "sides": set(),
                        "frames": [],
                    })
                    rec["sides"].update(sides)
                    rec["frames"].append(int(frame))

            # Emit one violation per (object, fmt_id) pair
            for fmt_id, rec in per_fmt.items():
                violations.append({
                    "object": obj,
                    "object_name": obj_name,
                    "fmt_id": fmt_id,
                    "sides": rec["sides"],
                    "frames": sorted(set(rec["frames"])),
                })

    finally:
        # Always restore the original time + re-evaluate so the user
        # doesn't end up on a different frame after the check.
        try:
            doc.SetTime(original_time)
            doc.ExecutePasses(None, True, True, True, c4d.BUILDFLAGS_0)
        except Exception:
            pass
        c4d.EventAdd()

    return violations
