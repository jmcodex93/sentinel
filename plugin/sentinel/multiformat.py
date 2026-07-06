# -*- coding: utf-8 -*-
"""Multi-format render setup engine."""

import math as _math

import c4d

from sentinel import framing

# ---------------- Multi-Format Render Setup ----------------
# Generates C4D Takes for each delivery aspect ratio (16:9, 9:16, 1:1, 4:5,
# 21:9). Each Take overrides the render data resolution + output path, and
# optionally adjusts the camera FOV to maintain the vertical visible extent
# (so the subject stays consistent across formats — the "Social Frame" pattern).


# Standard mograph delivery formats. Order matters: this is the order shown
# in the Multi-Format dialog and applied left-to-right when generating Takes.
MULTIFORMAT_DEFS = [
    {
        "id": "16x9",
        "label": "16:9 Landscape",
        "description": "YouTube, TV, default",
        "width": 1920,
        "height": 1080,
    },
    {
        "id": "9x16",
        "label": "9:16 Vertical",
        "description": "Reels, Stories, TikTok",
        "width": 1080,
        "height": 1920,
    },
    {
        "id": "1x1",
        "label": "1:1 Square",
        "description": "IG Square, Twitter",
        "width": 1080,
        "height": 1080,
    },
    {
        "id": "4x5",
        "label": "4:5 Portrait",
        "description": "IG Feed",
        "width": 1080,
        "height": 1350,
    },
    {
        "id": "21x9",
        "label": "21:9 Cinema",
        "description": "Wide banner, cinema",
        "width": 2560,
        "height": 1080,
    },
]


def get_multiformat_def(fmt_id):
    """Return the format definition dict for a given id, or None."""
    for f in MULTIFORMAT_DEFS:
        if f["id"] == fmt_id:
            return f
    return None


def format_aspect(fmt_def):
    """Aspect ratio (width / height) for a format definition."""
    if not fmt_def:
        return 1.0
    h = fmt_def.get("height", 1) or 1
    return float(fmt_def.get("width", 1)) / float(h)


def compute_target_horizontal_fov(source_h_fov_rad, source_aspect, target_aspect):
    """Compute horizontal FOV that maintains vertical FOV constant across aspect change.

    NOTE (v1.5.5): kept for reference / potential future use. Sentinel's
    Multi-Format Setup no longer uses "vertical FOV constant" by default —
    user research showed this behavior is rarely the desired one (it
    forces a heavy lens-character change per format). The default
    Composition Mode is now "None" (camera unchanged), with optional
    "Resize Canvas" mode that changes sensor size proportionally to the
    width ratio (matches the AR_ResizeCanvas community script convention).

    Math:
        vertical_fov is constant; horizontal_fov = 2 * atan(aspect * tan(vertical_fov / 2))
        target_h_fov = 2 * atan((target_aspect / source_aspect) * tan(source_h_fov / 2))
    """
    if source_aspect <= 0 or target_aspect <= 0:
        return source_h_fov_rad
    return 2.0 * _math.atan(
        (target_aspect / source_aspect) * _math.tan(source_h_fov_rad / 2.0)
    )


# ---- Composition modes for Multi-Format Setup ----
# How the orchestrator handles the camera when generating per-format Takes.
COMPOSITION_MODE_NONE = "none"
# "none" — Camera UNCHANGED across formats. Each Take only overrides
#   resolution + output path. Default C4D behavior: vertical formats see
#   MORE vertical content (camera frustum extends), wider formats see less.
#   Matches Greyscalegorilla "Social Frame" plugin behavior — the artist is
#   expected to compose for the intersection of all delivery formats.

COMPOSITION_MODE_RESIZE_CANVAS = "resize_canvas"
# "resize_canvas" — Mimics Arttu Rautio's AR_ResizeCanvas community script:
#   change SENSOR SIZE proportionally to width ratio so the camera "rotates"
#   its angular field as if you'd physically swapped to a different sensor.
#   We use sensor (CAMERAOBJECT_APERTURE) instead of focal length because:
#     - Focal-length animations / zoom keyframes stay intact (user's habitual
#       workflow with AR script also picks the sensor method for this reason)
#     - Renderer DOF calculations keyed on focal length stay stable
#     - C4D physical/RS cameras don't clamp aperture overrides (FOV is the
#       derived value), so this works in both directions (wider AND narrower)

# "crop" — TRUE inscribed crop that matches the viewport guides (WYSIWYG),
#   implemented by scaling the film gate (aperture) to the inscribed rect and
#   panning with a gate-relative film offset. Focal length is untouched so DOF
#   and zoom animations stay intact. This is the Sentinel Frame default.
COMPOSITION_MODE_CROP = "crop"

# Legacy focal-compensation modes kept for the old Multi-Format dialog path.
COMPOSITION_MODE_PRESERVE_VERTICAL = framing.COMPENSATE_PRESERVE_VERTICAL
COMPOSITION_MODE_PRESERVE_HORIZONTAL = framing.COMPENSATE_PRESERVE_HORIZONTAL
FOCAL_COMPOSITION_MODES = (
    COMPOSITION_MODE_PRESERVE_VERTICAL,
    COMPOSITION_MODE_PRESERVE_HORIZONTAL,
)


def compute_target_aperture(source_aperture, source_width, target_width):
    """AR_ResizeCanvas formula for sensor-size resize.

    Returns the aperture (sensor width in mm) that — combined with the
    camera's current focal length — produces the same world-space view at
    the new render width that the original aperture produced at the old
    render width. Effectively rotates the angular field across aspects.

    Math (from AR_ResizeCanvas, Arttu Rautio):
        new_aperture = source_aperture * (target_width / source_width)

    Note that this does NOT preserve any specific FOV axis — instead it
    makes `(world_units_visible) / (rendered_pixels)` constant at the new
    aspect. For 16:9 (1920) → 9:16 (1080):
        new_aperture = 36 * 1080/1920 = 20.25mm
        new_h_fov = 2*atan(20.25/2 / focal) — narrower than source
        new_v_fov (derived from aspect) = matches old h_fov approximately
    """
    if source_width <= 0 or source_aperture <= 0:
        return source_aperture
    return float(source_aperture) * (float(target_width) / float(source_width))


def compute_format_output_path(source_path, fmt_id, mode="subfolder"):
    """Generate output path for a format variant.

    Args:
        source_path: original render output path. May contain C4D tokens
            ($prj, $take, $frame, $camera). Empty string allowed.
        fmt_id: format identifier (e.g., "16x9", "9x16").
        mode: "subfolder" (insert /<fmt>/ before filename) or
              "suffix" (append _<fmt> to filename).

    Returns:
        Modified output path. Forward-slash style on all platforms (C4D's
        token system handles slash conversion at render time).

    Examples:
        ("output/$prj_$frame", "16x9", "subfolder") -> "output/16x9/$prj_$frame"
        ("output/$prj_$frame", "16x9", "suffix")    -> "output/$prj_$frame_16x9"
        ("$prj_$frame", "9x16", "subfolder")        -> "9x16/$prj_$frame"
        ("", "1x1", "subfolder")                    -> "1x1/$prj_$frame"
    """
    if not fmt_id:
        return source_path or ""
    if not source_path:
        # Reasonable default for an unset path
        return f"{fmt_id}/$prj_$frame" if mode == "subfolder" else f"$prj_{fmt_id}_$frame"

    # Use posix-style splitting to keep token-friendly forward slashes
    # (C4D handles platform-specific separators internally at render time).
    norm = source_path.replace("\\", "/")
    if "/" in norm:
        head, tail = norm.rsplit("/", 1)
    else:
        head, tail = "", norm

    if mode == "suffix":
        # Idempotency guard: don't stack _<fmt> if it's already there (Set
        # Output can re-run on an already-formatted path).
        if tail.endswith(f"_{fmt_id}"):
            return norm
        # Append _<fmt> to filename portion
        new_tail = f"{tail}_{fmt_id}" if tail else f"_{fmt_id}"
        return f"{head}/{new_tail}" if head else new_tail

    # Idempotency guard: if the fmt subfolder is already the immediate parent
    # of the filename, don't nest it again (avoids output/16x9/16x9/... when
    # Set Output re-applies to an already-formatted path).
    head_parts = head.split("/") if head else []
    if head_parts and head_parts[-1] == fmt_id:
        return norm

    # default: subfolder mode — insert /<fmt>/ between head and tail
    if head and tail:
        return f"{head}/{fmt_id}/{tail}"
    if head and not tail:
        return f"{head}/{fmt_id}"
    if tail and not head:
        return f"{fmt_id}/{tail}"
    return fmt_id


def take_name_for_format(fmt_def, source_take_name=""):
    """Compose the Take name for a format variant.

    For most cases, the format id is enough ("16x9", "9x16"). If the source
    take is something other than Main, prefix with it ("shot_010_16x9") so
    multi-shot scenes stay organized.
    """
    if not fmt_def:
        return ""
    fid = fmt_def.get("id", "")
    base = (source_take_name or "").strip()
    if base and base.lower() not in ("main", ""):
        return f"{base}_{fid}"
    return fid


def _take_name_for_options(fmt_def, source_take_name="", name_prefix=None):
    """Compose the Take name, optionally scoped to a camera/tag prefix."""
    if not fmt_def:
        return ""
    prefix = (name_prefix or "").strip()
    if prefix:
        return f"{prefix}_{fmt_def.get('id', '')}"
    return take_name_for_format(fmt_def, source_take_name)


def _find_take_by_name(takeData, name):
    """Walk all takes (depth-first) and return the first with matching name."""
    if not takeData or not name:
        return None
    main = takeData.GetMainTake()
    if not main:
        return None

    def _walk(node):
        while node:
            try:
                if node.GetName() == name:
                    return node
            except Exception:
                pass
            child = node.GetDown()
            if child:
                found = _walk(child)
                if found:
                    return found
            node = node.GetNext()
        return None

    return _walk(main.GetDown())


def _walk_child_takes(takeData):
    """Yield every non-main take depth-first."""
    if not takeData:
        return
    try:
        main = takeData.GetMainTake()
    except Exception:
        main = None
    if not main:
        return

    def _walk(node):
        while node:
            yield node
            child = node.GetDown()
            if child:
                for found in _walk(child):
                    yield found
            node = node.GetNext()

    for take in _walk(main.GetDown()):
        yield take


def _existing_prefixed_format_ids(takeData, name_prefix):
    """Return fmt ids for existing takes named '<prefix>_<fmt_id>'."""
    prefix = (name_prefix or "").strip()
    if not prefix:
        return set()
    name_to_id = {
        f"{prefix}_{fmt_def['id']}": fmt_def["id"]
        for fmt_def in MULTIFORMAT_DEFS
    }
    found = set()
    for take in _walk_child_takes(takeData):
        try:
            fmt_id = name_to_id.get(take.GetName())
        except Exception:
            fmt_id = None
        if fmt_id:
            found.add(fmt_id)
    return found


def _real_descid(param_id):
    """Build a REAL parameter DescID."""
    return c4d.DescID(c4d.DescLevel(param_id, c4d.DTYPE_REAL, 0))


def _read_real_param(node, param_id, fallback):
    try:
        value = float(node[param_id])
        if value > 0 or fallback <= 0:
            return value
    except Exception:
        pass
    return fallback


def _set_camera_override(take, takeData, cam, param_id, value):
    """Find-or-add and explicitly set a camera override parameter."""
    descid = _real_descid(param_id)
    ovr = take.FindOrAddOverrideParam(takeData, cam, descid, value)
    if ovr:
        # C4D's API is find-OR-add; SetParameter makes re-runs idempotent.
        ovr.SetParameter(descid, value, c4d.DESCFLAGS_SET_0)
        ovr.UpdateSceneNode(takeData, descid)
    return ovr


def _resolve_source_render_data(source_take, takeData, doc):
    """Get the effective render data for the source take.

    `BaseTake.GetEffectiveRenderData` may return a tuple (rdata, fromTake) on
    some C4D versions, or just the RenderData. We normalize.
    """
    rd = None
    if source_take is not None:
        try:
            res = source_take.GetEffectiveRenderData(takeData)
            if isinstance(res, tuple) and res:
                rd = res[0]
            else:
                rd = res
        except Exception:
            rd = None
    if rd is None:
        rd = doc.GetActiveRenderData()
    return rd


def _resolve_source_camera(source_take, takeData, doc):
    """Best-effort lookup of the camera that the source take uses."""
    cam = None
    if source_take is not None:
        try:
            cam = source_take.GetCamera(takeData)
        except Exception:
            cam = None
    if cam is None:
        try:
            bd = doc.GetActiveBaseDraw()
            if bd:
                cam = bd.GetSceneCamera(doc)
        except Exception:
            cam = None
    return cam


def _reset_camera_dimensions_to_native(take, takeData, cam):
    """Reset any FOV / focal-length / aperture overrides on `cam` within
    `take` to the camera's NATIVE (unaltered) values.

    Used by Mode "none" so re-running Multi-Format on takes that previously
    had Auto-FOV / focal-length overrides (early v1.5.5 dev iterations)
    produces a clean state — the camera renders identically across all
    generated takes. Defensive: silent on any per-parameter failure.

    Why "set to native" instead of "remove the override":
        `BaseOverride.RemoveOverrideParam` isn't reliably exposed in
        the C4D 2026 Python API across versions. Setting the override to
        the native value achieves the same visual effect (no-op render)
        and is portable.
    """
    if take is None or takeData is None or cam is None:
        return
    try:
        ovr = take.FindOverride(takeData, cam)
    except Exception:
        return
    if ovr is None:
        return

    # Parameters Sentinel may have touched in any prior version
    targets = [
        (c4d.CAMERAOBJECT_FOV, c4d.CAMERAOBJECT_FOV),
        (framing.CAMERA_FOCUS, framing.CAMERA_FOCUS),
        (framing.CAMERAOBJECT_APERTURE, framing.CAMERAOBJECT_APERTURE),
        (framing.CAMERAOBJECT_FILM_OFFSET_X, framing.CAMERAOBJECT_FILM_OFFSET_X),
        (framing.CAMERAOBJECT_FILM_OFFSET_Y, framing.CAMERAOBJECT_FILM_OFFSET_Y),
    ]
    for param_id, native_attr in targets:
        try:
            descid = _real_descid(param_id)
            if not ovr.IsOverriddenParam(descid):
                continue
            try:
                native = float(cam[native_attr])
            except Exception:
                continue
            ovr.SetParameter(descid, native, c4d.DESCFLAGS_SET_0)
            ovr.UpdateSceneNode(takeData, descid)
        except Exception:
            continue


def generate_multiformat_takes(doc, options):
    """Generate child Takes for the selected delivery formats.

    Each Take always gets:
      - cloned Render Data with format-specific resolution + output path
      - explicit camera assignment (`take.SetCamera`) so it doesn't fall
        back to the scene's active camera

    Camera dimension overrides depend on `composition_mode`:
      - "none" (default): camera is UNCHANGED. Each Take just renders the
        source camera at the new aspect — vertical formats see more
        vertical content, wider formats see less. Matches Greyscalegorilla
        Social Frame plugin behavior. The artist composes for the
        intersection of delivery formats. Any stale dimension overrides
        from prior runs are reset to the camera's native values.
      - "resize_canvas": overrides CAMERAOBJECT_APERTURE per format using
        AR_ResizeCanvas's formula (`new_aperture = src_aperture *
        target_width / src_width`). Effectively rotates the angular field
        between formats — narrower aspect = narrower horizontal angular
        coverage but wider vertical. Sensor-based (not focal) so existing
        focal-length animations / DOF setups stay intact.

    Args:
        doc: active BaseDocument.
        options: dict with keys:
            - formats: list of fmt_id strings (e.g., ['16x9', '9x16'])
            - output_mode: 'subfolder' or 'suffix'
            - composition_mode: 'none' | 'resize_canvas' |
              'preserve_vertical' | 'preserve_horizontal' | 'crop'
              (default: 'none')
            - update_existing: bool — reuse takes with same name if present
            - source_take: BaseTake (optional, defaults to current take)
            - name_prefix: optional camera/tag prefix. When present, takes
              are named '<name_prefix>_<fmt_id>' and existing prefixed takes
              outside the requested formats are reported as orphaned.
            - film_offsets: optional dict fmt_id -> (x, y) camera film offset
              override values.
            - tag_link_writer: optional callback(fmt_id, take). This keeps
              BaseLink tracking owned by the tag/UI layer while letting the
              engine expose the created/adopted take objects at the right time.

    Returns:
        dict report:
            success: bool
            created: list[str] — take names that were freshly created
            updated: list[str] — take names that were updated in place
            skipped: list[str] — takes that existed and update_existing was False
            orphaned: list[str] — prefixed fmt ids that exist but were not requested
            adopted: list[str] — existing prefixed takes updated in place
            errors: list[str] — non-fatal issues encountered
            source_take_name, source_resolution, composition_mode
    """
    report = {
        "success": False,
        "created": [],
        "updated": [],
        "skipped": [],
        "orphaned": [],
        "adopted": [],
        "errors": [],
        "notes": [],
        "source_take_name": "",
        "source_resolution": None,
    }

    if not doc:
        report["errors"].append("No active document")
        return report

    td = doc.GetTakeData()
    if not td:
        report["errors"].append("Document has no take data")
        return report

    source_take = options.get("source_take") or td.GetCurrentTake() or td.GetMainTake()
    if not source_take:
        report["errors"].append("Could not resolve source take")
        return report

    report["source_take_name"] = source_take.GetName() or "Main"

    source_rd = _resolve_source_render_data(source_take, td, doc)
    if not source_rd:
        report["errors"].append("No render data found for source take")
        return report

    src_w = int(source_rd[c4d.RDATA_XRES] or 1920)
    src_h = int(source_rd[c4d.RDATA_YRES] or 1080)
    src_path = source_rd[c4d.RDATA_PATH] or ""
    src_aspect = float(src_w) / float(src_h) if src_h > 0 else 1.0
    report["source_resolution"] = (src_w, src_h)

    # An explicit source_cam (passed by the Sentinel Frame tag = its host
    # camera) wins over viewport/Main-take resolution. Without it a tag on
    # CamA would bind its Takes to whatever camera the viewport happens to
    # show — the multi-camera bug the per-camera tag is meant to fix. Absent
    # the option, behaviour is unchanged (legacy dialog path).
    source_cam = options.get("source_cam") or _resolve_source_camera(source_take, td, doc)
    # Source aperture (sensor width in mm) — used by Resize Canvas mode.
    # Standard 35mm-equivalent default = 36mm.
    src_aperture = 36.0
    src_focal = 36.0
    if source_cam:
        src_aperture = _read_real_param(
            source_cam, framing.CAMERAOBJECT_APERTURE, src_aperture)
        src_focal = _read_real_param(source_cam, framing.CAMERA_FOCUS, src_focal)

    composition_mode = options.get("composition_mode", COMPOSITION_MODE_NONE)
    update_existing = bool(options.get("update_existing", True))
    output_mode = options.get("output_mode", "subfolder")
    formats = options.get("formats") or []
    requested_formats = set(formats)
    name_prefix = options.get("name_prefix")
    film_offsets = options.get("film_offsets") or {}
    tag_link_writer = options.get("tag_link_writer")
    # Optional resolver(fmt_id) -> existing take, consulted BEFORE name lookup.
    # The Sentinel Frame tag passes a BaseLink-backed resolver so a re-run
    # re-finds its own Takes even after the take — or the host camera (the
    # name prefix) — was renamed, instead of orphaning them and creating
    # duplicates (KTD4 rename-safety). Absent → pure name matching (legacy).
    existing_take_resolver = options.get("existing_take_resolver")
    # When the caller already owns the undo block (the Sentinel Frame tag wraps
    # take generation + its own BaseLink/signature writes in one step so a
    # single Cmd+Z reverts everything), it passes external_undo=True and we must
    # NOT open a second nested StartUndo/EndUndo/EventAdd. Legacy dialog caller
    # omits it → the engine self-manages exactly as before.
    external_undo = bool(options.get("external_undo", False))
    report["composition_mode"] = composition_mode
    report["orphaned"] = sorted(
        _existing_prefixed_format_ids(td, name_prefix) - requested_formats
    )

    if not external_undo:
        doc.StartUndo()
    try:
        for fmt_id in formats:
            fmt_def = get_multiformat_def(fmt_id)
            if not fmt_def:
                report["errors"].append(f"Unknown format: {fmt_id}")
                continue

            take_name = _take_name_for_options(
                fmt_def, report["source_take_name"], name_prefix)

            # Prefer the tag's tracked Take (rename-safe) over name matching.
            existing = None
            if callable(existing_take_resolver):
                try:
                    linked = existing_take_resolver(fmt_id)
                except Exception:
                    linked = None
                if linked is not None:
                    existing = linked
                    # Re-sync a drifted name back to the canonical camera-scoped
                    # name so the take (and orphan detection) stays consistent.
                    try:
                        if existing.GetName() != take_name:
                            doc.AddUndo(c4d.UNDOTYPE_CHANGE, existing)
                            existing.SetName(take_name)
                    except Exception:
                        pass
            if existing is None:
                existing = _find_take_by_name(td, take_name)
            if existing and not update_existing:
                report["skipped"].append(take_name)
                continue

            # Create or reuse take
            if existing:
                take = existing
                is_update = True
            else:
                try:
                    take = td.AddTake(take_name, source_take, None)
                except Exception as e:
                    report["errors"].append(f"AddTake({take_name}) failed: {e}")
                    continue
                if not take:
                    report["errors"].append(f"AddTake({take_name}) returned None")
                    continue
                try:
                    doc.AddUndo(c4d.UNDOTYPE_NEW, take)
                except Exception:
                    pass
                is_update = False

            # Resolve / create render data for this take.
            # Only reuse the take's existing render data if it is an
            # engine-owned per-format clone (named "<source>_<fmt>"). A take
            # adopted via existing_take_resolver could point at the SHARED
            # source render data (or a foreign one); writing this format's
            # resolution/path onto that would corrupt the base settings. In
            # that case we fall through and clone a fresh dedicated render data.
            expected_rd_name = f"{source_rd.GetName()}_{fmt_id}"
            new_rd = None
            if is_update:
                try:
                    existing_rd = take.GetRenderData(td)
                    if existing_rd and existing_rd.GetName() == expected_rd_name:
                        new_rd = existing_rd
                        try:
                            doc.AddUndo(c4d.UNDOTYPE_CHANGE, new_rd)
                        except Exception:
                            pass
                except Exception:
                    pass

            if new_rd is None:
                try:
                    new_rd = source_rd.GetClone(c4d.COPYFLAGS_0)
                    new_rd.SetName(f"{source_rd.GetName()}_{fmt_id}")
                    doc.InsertRenderDataLast(new_rd)
                    take.SetRenderData(td, new_rd)
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_NEW, new_rd)
                    except Exception:
                        pass
                except Exception as e:
                    report["errors"].append(f"Render data clone failed for {take_name}: {e}")
                    continue

            # Bug fix (v1.5.5): explicitly assign the camera to the Take so
            # `take.GetCamera(td)` returns it. Without this, even though the
            # FOV override targets `source_cam`, the Take has no camera
            # assignment and renders fall back to scene defaults — and our
            # QC #12 cross-aspect check has no camera to project from.
            # `BaseTake.SetCamera` is the official Maxon SDK pattern
            # (see takesystem_cameras_r17.py).
            if source_cam is not None:
                try:
                    take.SetCamera(td, source_cam)
                except Exception as e:
                    report["errors"].append(f"SetCamera failed for {take_name}: {e}")

            # Apply format-specific overrides on render data
            try:
                new_rd[c4d.RDATA_XRES] = float(fmt_def["width"])
                new_rd[c4d.RDATA_YRES] = float(fmt_def["height"])
                new_path = compute_format_output_path(src_path, fmt_id, output_mode)
                new_rd[c4d.RDATA_PATH] = new_path
            except Exception as e:
                report["errors"].append(f"Render data setup failed for {take_name}: {e}")
                continue

            # Camera overrides — depend on composition_mode.
            #
            # "crop" (Sentinel Frame default): a TRUE inscribed crop that
            #   matches the viewport guides exactly (WYSIWYG). Scales the film
            #   gate (aperture) to the inscribed rect and pans with a gate-
            #   relative film offset, leaving focal length untouched so DOF and
            #   zoom animations are preserved. See framing.format_crop_values.
            # "none": camera unchanged (C4D keeps horizontal FOV, aspect changes
            #   vertical extent — wider formats crop, narrower ones EXTEND, so
            #   this does NOT match the crop guides for narrower formats). The
            #   nudge, if any, pans via a master-relative film offset.
            # "resize_canvas" / focal modes: legacy Multi-Format dialog paths.
            if source_cam:
                try:
                    try:
                        src_film_x = float(
                            source_cam[framing.CAMERAOBJECT_FILM_OFFSET_X])
                    except Exception:
                        src_film_x = 0.0
                    try:
                        src_film_y = float(
                            source_cam[framing.CAMERAOBJECT_FILM_OFFSET_Y])
                    except Exception:
                        src_film_y = 0.0
                    nudge = film_offsets.get(fmt_id)
                    tw = int(fmt_def["width"])
                    th = int(fmt_def["height"])

                    if composition_mode == COMPOSITION_MODE_CROP:
                        _reset_camera_dimensions_to_native(take, td, source_cam)
                        # TRUE inscribed crop via FOCAL LENGTH. Focal is the
                        # universal lever — it crops cleanly on standard AND
                        # Redshift cameras (verified live), unlike aperture which
                        # Redshift ignores. For a narrower target the focal is
                        # zoomed in; for wider/equal it comes back == src_focal
                        # and we skip the override (the resolution change alone
                        # crops top/bottom, which works on every camera).
                        focal, film_x, film_y = framing.format_crop_values(
                            src_focal, src_w, src_h, tw, th,
                            nudge, src_film_x, src_film_y)
                        if focal > src_focal + 1e-6:
                            _set_camera_override(
                                take, td, source_cam,
                                framing.CAMERA_FOCUS, focal)
                        # Film offset (pan) only when there is an actual offset —
                        # a spurious 0 override can disturb some cameras.
                        if (abs(film_x - src_film_x) > 1e-9
                                or abs(film_y - src_film_y) > 1e-9):
                            _set_camera_override(
                                take, td, source_cam,
                                framing.CAMERAOBJECT_FILM_OFFSET_X, float(film_x))
                            _set_camera_override(
                                take, td, source_cam,
                                framing.CAMERAOBJECT_FILM_OFFSET_Y, float(film_y))
                    elif composition_mode == COMPOSITION_MODE_RESIZE_CANVAS:
                        new_aperture = compute_target_aperture(
                            src_aperture, src_w, tw)
                        _set_camera_override(
                            take, td, source_cam,
                            framing.CAMERAOBJECT_APERTURE, new_aperture)
                    elif composition_mode in FOCAL_COMPOSITION_MODES:
                        _reset_camera_dimensions_to_native(take, td, source_cam)
                        new_focal = framing.compensated_focus(
                            src_focal, src_w, src_h, tw, th, composition_mode)
                        _set_camera_override(
                            take, td, source_cam, framing.CAMERA_FOCUS, new_focal)
                    else:  # "none" — camera unchanged; nudge pans (master-relative)
                        _reset_camera_dimensions_to_native(take, td, source_cam)
                        if nudge is not None:
                            _f, film_x, film_y = framing.format_camera_framing_values(
                                src_focal, src_w, src_h, tw, th,
                                framing.COMPENSATE_OFF, nudge,
                                src_film_x, src_film_y)
                            _set_camera_override(
                                take, td, source_cam,
                                framing.CAMERAOBJECT_FILM_OFFSET_X, float(film_x))
                            _set_camera_override(
                                take, td, source_cam,
                                framing.CAMERAOBJECT_FILM_OFFSET_Y, float(film_y))
                except Exception as e:
                    report["errors"].append(
                        f"Camera dimension setup failed for {take_name}: {e}")

            if is_update:
                report["updated"].append(take_name)
                if name_prefix:
                    report["adopted"].append(take_name)
            else:
                report["created"].append(take_name)

            if callable(tag_link_writer):
                try:
                    tag_link_writer(fmt_id, take)
                except Exception as e:
                    report["errors"].append(
                        f"Tag link writer failed for {take_name}: {e}")

        report["success"] = True
    except Exception as e:
        report["errors"].append(f"Orchestrator error: {e}")
    finally:
        if not external_undo:
            doc.EndUndo()
            c4d.EventAdd()

    return report
