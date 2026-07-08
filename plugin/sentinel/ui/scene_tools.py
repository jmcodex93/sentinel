# -*- coding: utf-8 -*-
"""Scene-mutation tools for the Sentinel panel (Phase 4 extraction).

Handler bodies moved verbatim out of YSPanel into module functions taking
(doc, ...). UI layer: these open dialogs and mutate the scene; panel methods
are thin delegates. Panel-state updates (button relabels, preset caption)
are injected via optional ``update_ui``/``refresh`` callbacks.
"""
import c4d
from c4d import documents
import os

from sentinel import postrender
from sentinel.aovs import (
    _get_rs_videopost,
    _is_lg_active_on_beauty,
    _scan_light_groups,
    check_rs_aovs,
    force_aov_tier,
)
from sentinel.checks.render import normalize_preset_name
from sentinel.common.cache import check_cache
from sentinel.common.helpers import safe_print
from sentinel.common.settings import GlobalSettings
from sentinel.safe_areas import (
    is_object_marked_safe_area,
    mark_object_safe_area,
    unmark_object_safe_area,
)
from sentinel.ui.flows import _doc_full_path, snapshot_open_folder, snapshot_save_still

# Import Redshift module for AOV management
try:
    import redshift
    REDSHIFT_AVAILABLE = True
except ImportError:
    REDSHIFT_AVAILABLE = False

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _toggle_light_groups(doc):
    """Toggle Light Groups on Beauty AOV with diagnostic"""
    if not REDSHIFT_AVAILABLE:
        c4d.gui.MessageDialog("Redshift module not available.")
        return

    vprs = _get_rs_videopost(doc)
    if not vprs:
        c4d.gui.MessageDialog("Redshift VideoPost not found.")
        return

    groups, ungrouped = _scan_light_groups(doc)
    lg_active = _is_lg_active_on_beauty(doc)

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


def _force_aov_tier(doc, tier_list, tier_name):
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


def _handle_validate_render(doc):
    """Run on-demand post-render validation for a chosen folder."""
    folder = c4d.storage.LoadDialog(
        title="Select Render Output Folder",
        flags=c4d.FILESELECT_DIRECTORY,
    )
    if not folder:
        return
    if not os.path.isdir(folder):
        c4d.gui.MessageDialog("Render validation cancelled:\n\nSelected folder is not valid.")
        return

    try:
        findings = postrender.audit_render_folder(doc, folder)
        report = postrender.build_report(findings)
    except Exception as exc:
        safe_print(f"Render validation failed: {exc}")
        c4d.gui.MessageDialog(f"Render validation failed:\n\n{exc}")
        return

    doc_path = _doc_full_path(doc)
    report_path = postrender.report_path_for_doc(doc_path, folder)
    wrote_report = postrender.write_report_atomic(report_path, report)
    wrote_history = postrender.append_render_history(doc_path or folder, report)

    context = report.get("context") or {}
    version = context.get("version") or "current scene"
    frame_start = context.get("frame_start")
    frame_end = context.get("frame_end")
    if frame_start is not None and frame_end is not None:
        frame_text = f"range {frame_start}-{frame_end}"
    else:
        frame_text = "range unavailable"
    mode = context.get("frame_mode") or "Unknown"
    status = "PASSED" if report.get("passed") else "ISSUES FOUND"
    summary = report.get("summary") or {}

    msg = (
        f"Post-render validation {status}\n\n"
        f"Validating {version} · {frame_text} · mode {mode}\n"
        f"Failures: {summary.get('failures', 0)}\n"
        f"Warnings: {summary.get('warnings', 0)}\n"
        f"Streams checked: {summary.get('streams', 0)}\n\n"
    )
    if not doc_path:
        msg += "Scene is unsaved; report and render history were written to the render folder.\n"
    msg += f"Report: {report_path if wrote_report else 'could not write report'}\n"
    if not wrote_history:
        msg += "Render history could not be updated.\n"
    c4d.gui.MessageDialog(msg)


def _open_artist_folder(artist_name):
    """Open the artist's output folder"""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    snapshot_open_folder(doc, artist_name)


def _create_vibrate_null(doc):
    _merge_c4d_file(doc, "VibrateNull.c4d")


def _toggle_safe_area_mark(doc, refresh=None):
    """Mark / unmark the current selection as Safe Area Subjects.

    Drives the QC #12 Cross-Aspect Safe-Area check. Smart toggle:
      - All selected objects ALREADY marked  → unmark them all
      - Any selected object NOT marked       → mark them all
                                               (aligns toward "marked")
      - Empty selection                      → friendly hint dialog

    Marks persist as UserData boolean on each object — they survive
    save/reload and Cmd+Z reverts the operation as a single undo step.
    """
    if not doc:
        c4d.gui.MessageDialog("No active document.")
        return

    sel = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_CHILDREN) or []
    if not sel:
        c4d.gui.MessageDialog(
            "Select one or more objects first, then click again.\n\n"
            "Tip: mark important compositional elements (logo, title, "
            "character) so QC #12 can verify they stay inside the safe "
            "area of every multi-format delivery Take."
        )
        return

    # Detect current state
    all_marked = all(is_object_marked_safe_area(o) for o in sel)
    target_state = not all_marked  # toggle: marked→unmark, otherwise mark

    marked_count = 0
    unmarked_count = 0
    failed_count = 0

    doc.StartUndo()
    try:
        for obj in sel:
            if target_state:
                # Marking pass
                ok = mark_object_safe_area(obj, True, doc)
                if ok:
                    marked_count += 1
                else:
                    failed_count += 1
            else:
                # Unmarking pass — fully remove the UserData entry so the
                # object returns to a "never been marked" state. Avoids
                # leaving fossil UD checkboxes on objects.
                ok = unmark_object_safe_area(obj, doc)
                if ok:
                    unmarked_count += 1
                else:
                    failed_count += 1
    finally:
        doc.EndUndo()
        c4d.EventAdd()

    # Refresh the QC row immediately so the user sees the count update
    try:
        check_cache.clear()
        if refresh is not None:
            refresh()
    except Exception:
        pass

    # Brief feedback
    verb = "Marked" if target_state else "Unmarked"
    count = marked_count if target_state else unmarked_count
    msg = f"{verb} {count} object(s) as Safe Area Subject(s)"
    if failed_count:
        msg += f"\n({failed_count} failed — see Console for details)"
    safe_print(msg)


def _create_hierarchy(doc):
    _merge_c4d_file(doc, "nulls.c4d")


def _merge_camera_file(doc, filename):
    _merge_c4d_file(doc, filename)


def _merge_c4d_file(doc, filename):
    """Merge camera setup from C4D file"""
    if not doc:
        return

    try:
        # Get path to the C4D file (in the same plugin directory)
        plugin_dir = _ROOT
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


def _get_template_path():
    return os.path.join(_ROOT, "c4d", "new.c4d")


def _force_render_settings(doc, update_ui=None):
    """Reset all 4 render presets from template file"""
    if not doc:
        return

    template_path = _get_template_path()
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
        if update_ui is not None:
            update_ui()
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


def _toggle_aspect(doc, update_ui=None):
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
        if update_ui is not None:
            update_ui()

        label = "16:9" if w > h else "9:16"
        safe_print(f"Aspect: {old_w}x{old_h} → {w}x{h} ({label})")

    except Exception as e:
        safe_print(f"Error toggling aspect: {e}")


def _add_sentinel_frame_tag(doc):
    """Add a Sentinel Frame tag to the active/selected camera, or select the
    existing one. The tag is the recommended per-camera multi-format entry
    point (live guides + one-click, rename-safe WYSIWYG-crop delivery Takes).
    """
    if doc is None:
        return
    try:
        from sentinel.ui.frame_tag import (
            SENTINEL_FRAME_TAG_PLUGIN_ID, is_valid_camera_host)
    except Exception as e:
        c4d.gui.MessageDialog(f"Sentinel Frame tag unavailable: {e}")
        return

    # Resolve a camera: the active selected object if it's a camera, else
    # the camera the viewport is looking through.
    cam = None
    active = doc.GetActiveObject()
    if active is not None and is_valid_camera_host(active.GetType()):
        cam = active
    if cam is None:
        try:
            bd = doc.GetActiveBaseDraw()
            scene_cam = bd.GetSceneCamera(doc) if bd else None
            if scene_cam is not None and is_valid_camera_host(scene_cam.GetType()):
                cam = scene_cam
        except Exception:
            cam = None
    if cam is None:
        c4d.gui.MessageDialog(
            "Select a camera (standard or Redshift), or look through one, "
            "then click 'Add Sentinel Frame to camera'.")
        return

    existing = None
    for t in cam.GetTags():
        if t.GetType() == SENTINEL_FRAME_TAG_PLUGIN_ID:
            existing = t
            break
    if existing is not None:
        try:
            doc.SetActiveTag(existing, c4d.SELECTION_NEW)
            c4d.EventAdd()
        except Exception:
            pass
        c4d.gui.MessageDialog(
            f"'{cam.GetName()}' already has a Sentinel Frame tag — "
            "selected it in the Attribute Manager.")
        return

    tag = None
    doc.StartUndo()
    try:
        tag = cam.MakeTag(SENTINEL_FRAME_TAG_PLUGIN_ID)
        if tag is not None:
            doc.AddUndo(c4d.UNDOTYPE_NEW, tag)
            try:
                doc.SetActiveTag(tag, c4d.SELECTION_NEW)
            except Exception:
                pass
    finally:
        doc.EndUndo()
        c4d.EventAdd()

    if tag is None:
        c4d.gui.MessageDialog("Could not create the Sentinel Frame tag.")
        return
    safe_print(f"Sentinel Frame tag added to '{cam.GetName()}'")


def _hierarchy_to_layers(doc):
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
        layer, is_new = _find_or_create_layer(doc, layer_root, null_name)

        if layer:
            # Assign null and all children to this layer
            _assign_to_layer_recursive(doc, null, layer)

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


def _find_or_create_layer(doc, layer_root, name):
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


def _solo_layers(doc):
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
        _unsolo_layers(doc)
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


def _unsolo_layers(doc):
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


def _assign_to_layer_recursive(doc, obj, layer):
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
        _assign_to_layer_recursive(doc, child, layer)
        child = child.GetNext()


def _drop_to_floor(doc):
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


def _take_renderview_snapshot(artist_name):
    """Take a snapshot from RenderView"""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        c4d.gui.MessageDialog("No active document!")
        return

    if not artist_name:
        c4d.gui.MessageDialog("Please set your artist name first!")
        return

    snapshot_save_still(doc, artist_name)


def _apply_abc_retime_tag():
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
