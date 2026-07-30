"""panel/tools ops (Fase 6.4) — Tools section of the SPA panel.

Thin adapters over the scene_tools engines. Each tool that shows a
MessageDialog gets a dialog-free ``_<fn>_core`` (a MessageDialog inside the
panel's Timer drain freezes all of C4D — v1.21.0 pattern); the op calls the
core and returns its status dict, which the SPA renders as a toast. Tools
are action-only: no read op, no confirm (nothing destructive)."""
import c4d
import os
import webbrowser

from sentinel.ui import scene_tools


def _tool(core_call):
    """Run a tool core against the active document; ``no_document`` when
    there's none. ``core_call`` takes the doc and returns a status dict."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    return core_call(doc)


def _op_tool_hierarchy(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "nulls.c4d"))


def _op_tool_vibrate_null(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "VibrateNull.c4d"))


def _op_tool_cam_simple(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "cam_simple.c4d"))


def _op_tool_cam_shakel(payload):
    return _tool(lambda doc: scene_tools._merge_c4d_file_core(doc, "cam_w_shakel.c4d"))


def _op_tool_h_to_layers(payload):
    return _tool(scene_tools._hierarchy_to_layers_core)


def _op_tool_solo(payload):
    return _tool(scene_tools._solo_layers_core)


def _op_tool_drop_to_floor(payload):
    return _tool(scene_tools._drop_to_floor_core)


def _op_tool_abc_retime(payload):
    return _tool(scene_tools._apply_abc_retime_tag_core)


def _op_tool_mark_safe_area(payload):
    return _tool(scene_tools._toggle_safe_area_mark_core)


def _op_tool_delete_empty_nulls(payload):
    return _tool(scene_tools._delete_empty_nulls_core)


def _op_tool_clean_material_tags(payload):
    return _tool(scene_tools._clean_material_tags_core)


def _op_tool_keyframe_offset(payload):
    from sentinel import keyframes
    return _tool(lambda doc: keyframes.run_offset(doc, (payload or {}).get("frames")))


def _op_tool_keyframe_stagger(payload):
    from sentinel import keyframes
    return _tool(lambda doc: keyframes.run_stagger(doc, (payload or {}).get("frames")))


_EXTERNAL_URLS = {
    "github": "https://github.com/jmcodex93/sentinel",
    "bug": "https://github.com/jmcodex93/sentinel/issues/new",
}


def _op_open_external(payload):
    """Open a fixed help URL in the OS browser (GitHub / Report Bug).
    ``webbrowser.open`` is a non-blocking OS launch — safe in the drain."""
    target = (payload or {}).get("target")
    url = _EXTERNAL_URLS.get(target)
    if not url:
        return {"ok": False, "error": "bad_target"}
    webbrowser.open(url)
    return {"ok": True}


def _op_open_settings(payload):
    """Open the Settings form page in its own window (mirrors the native
    footer Settings button)."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    try:
        from sentinel.ui.reports_dialog import open_form
        open_form(doc, "form/settings")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def _op_open_palette(payload):
    """Open the Command Palette in its own window (the rail's 'commands'
    entry). Same async FormDialog host as Settings/Hub — non-blocking."""
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    try:
        from sentinel.ui.reports_dialog import open_form
        open_form(doc, "palette")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


PREVIEW_CAP = 500


def _rename_items(doc, source):
    """(items, nodes) in final order, or (None, None) on bad source.
    Objects follow the artist's SELECTION order (spec decision 3)."""
    if source == "objects":
        try:
            nodes = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_SELECTIONORDER) or []
        except Exception:
            nodes = []
    elif source == "materials":
        try:
            nodes = doc.GetActiveMaterials() or []
        except Exception:
            nodes = []
    else:
        return None, None
    items = []
    for node in nodes:
        parent = ""
        try:
            up = node.GetUp() if hasattr(node, "GetUp") else None
            parent = up.GetName() if up is not None else ""
        except Exception:
            parent = ""
        try:
            type_name = node.GetTypeName() or ""
        except Exception:
            type_name = ""
        items.append({"name": node.GetName() or "", "parent": parent,
                      "type_name": type_name})
    return items, nodes


def _rename_request(payload):
    """Shared front half: (doc, nodes, plan, ops) or an error dict."""
    from sentinel import renaming
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    payload = payload or {}
    ops = renaming.normalize_ops(payload.get("ops"))
    if renaming.ops_is_noop(ops):
        return {"ok": False, "error": "nothing_to_do"}
    items, nodes = _rename_items(doc, payload.get("source"))
    if items is None:
        return {"ok": False, "error": "bad_source"}
    if not items:
        return {"ok": False, "error": "no_selection"}
    return {"doc": doc, "nodes": nodes, "plan": renaming.rename_plan(items, ops)}


def _op_rename_preview(payload):
    result = _rename_request(payload)
    if "error" in result:
        return result
    plan = result["plan"]
    return {"ok": True, "rows": plan[:PREVIEW_CAP],
            "truncated": len(plan) > PREVIEW_CAP, "total": len(plan)}


def _op_rename_apply(payload):
    # Re-derives the plan from the CURRENT selection + payload ops — any
    # client-side rows are ignored (a stale preview can never apply
    # misaligned names).
    result = _rename_request(payload)
    if "error" in result:
        return result
    doc, nodes, plan = result["doc"], result["nodes"], result["plan"]
    renamed = 0
    doc.StartUndo()
    try:
        for node, row in zip(nodes, plan):
            if row["old"] == row["new"]:
                continue
            try:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, node)
            except Exception:
                pass
            try:
                node.SetName(row["new"])
            except Exception:
                continue
            renamed += 1
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    return {"ok": True, "renamed": renamed,
            "collisions": sum(1 for r in plan if r["collision"]),
            "source": (payload or {}).get("source")}


def _existing_material_names(doc):
    """Material Manager names for dedupe — defensive, never raises."""
    names = []
    try:
        for mat in doc.GetMaterials() or []:
            try:
                names.append(mat.GetName() or "")
            except Exception:
                continue
    except Exception:
        pass
    return names


#: Recursion cap for the matwire folder walk — levels BELOW the root.
_MATWIRE_WALK_DEPTH = 5


def _list_folder_files(folder):
    """Recursive file lister shared by BOTH matwire ops (v1.32.1): paths
    RELATIVE to ``folder`` with "/" separators (the writer re-joins them
    per-platform via ``matwire_c4d._join``), walk capped at 5 levels below
    the root, dot-DIRS pruned, symlinks never followed, sorted for
    determinism. Dot-FILES are kept — flat-folder parity with the v1.32
    ``os.listdir`` behavior (.DS_Store still falls out downstream as
    ``bad_extension``, exactly as before)."""
    root = os.path.normpath(str(folder))
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == os.curdir else rel_dir.count(os.sep) + 1
        if depth >= _MATWIRE_WALK_DEPTH:
            dirnames[:] = []  # cap: never descend past level 5
        else:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            rel = name if rel_dir == os.curdir else os.path.join(rel_dir, name)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _matwire_request(payload):
    """Shared front half for the matwire ops: re-derives the scan from the
    FOLDER on every call (v1.31 rename-ops pattern — client rows are never
    trusted). Resolves the project ruleset's ``matwire_suffixes`` (lazy
    rules_context import, frame_tag style — defensive: any resolution
    failure degrades to no extras). Returns ``{doc, folder, scan,
    default_root, suffix_warnings}`` or an error dict."""
    from sentinel import matwire
    from sentinel import matwire_c4d
    doc = c4d.documents.GetActiveDocument()
    if not doc:
        return {"ok": False, "error": "no_document"}
    if not matwire_c4d.redshift_available():
        return {"ok": False, "error": "redshift_unavailable"}
    folder = str((payload or {}).get("folder") or "")
    if not folder or not os.path.isdir(folder):
        return {"ok": False, "error": "bad_folder"}
    try:
        files = _list_folder_files(folder)
    except OSError:
        return {"ok": False, "error": "bad_folder"}
    default_root = os.path.basename(folder.rstrip(os.sep)) or "material"
    extra, warnings = {}, []
    try:
        from sentinel.rules_context import active_rules_for_doc
        raw = (active_rules_for_doc(doc).params or {}).get("matwire_suffixes")
    except Exception:
        raw = None
    if raw:
        extra, warnings = matwire.validate_extra_suffixes(raw)
    scan = matwire.scan_texture_sets(files, default_root=default_root,
                                     extra_suffixes=extra or None)
    if not scan["sets"]:
        return {"ok": False, "error": "no_sets"}
    return {"doc": doc, "folder": folder, "scan": scan,
            "default_root": default_root, "suffix_warnings": warnings}


def _op_matwire_preview(payload):
    from sentinel import matwire
    result = _matwire_request(payload)
    if "error" in result:
        return result
    existing = _existing_material_names(result["doc"])
    out = matwire.preview_payload(result["scan"], existing)
    out["ok"] = True
    out["suffix_warnings"] = result["suffix_warnings"]
    out["leftovers"] = matwire.assign_leftovers(
        result["scan"].get("leftover_hints"),
        [s["name"] for s in result["scan"]["sets"]])
    return out


def _op_matwire_create(payload):
    """Wire every included set inside ONE StartUndo/EndUndo. The writer
    builds each graph OFF-document and inserts last (v1.32.1), so the only
    records inside the bracket are the N insertions — one Cmd+Z reverts the
    whole batch. Per-set failures are collected, never abort the batch."""
    from sentinel import matwire
    from sentinel import matwire_c4d
    result = _matwire_request(payload)
    if "error" in result:
        return result
    doc, folder, scan = result["doc"], result["folder"], result["scan"]
    payload = payload or {}
    exclude = {str(n) for n in payload.get("exclude") or []}
    names_map = payload.get("names") or {}
    included = [s for s in scan["sets"] if s["name"] not in exclude]
    if not included:
        return {"ok": False, "error": "no_sets"}
    import_leftovers = bool(payload.get("import_leftovers"))
    per_set = {}
    unassigned = []
    if import_leftovers:
        # Assignment runs against ALL set names (mirrors the preview): a
        # leftover whose home set is EXCLUDED is dropped with it — it never
        # leaks into the catch-all material.
        for row in matwire.assign_leftovers(
                scan.get("leftover_hints"),
                [s["name"] for s in scan["sets"]]):
            if row["set"] is None:
                unassigned.append(row["file"])
            else:
                per_set.setdefault(row["set"], []).append(row["file"])
    requested = [str(names_map.get(s["name"]) or s["name"]) for s in included]
    leftover_base = None
    if import_leftovers and unassigned:
        leftover_base = result["default_root"] + "_leftovers"
        requested.append(leftover_base)  # dedupes with the batch + manager
    final_names = matwire.dedupe_names(requested, _existing_material_names(doc))
    jobs = [(tex_set, name, per_set.get(tex_set["name"]))
            for tex_set, name in zip(included, final_names)]
    if leftover_base is not None:
        # Unassigned leftovers become ONE material from an EMPTY set — the
        # same creation path as any set (zero special cases in the writer).
        jobs.append(({"name": leftover_base, "channels": {},
                      "normal_flipy": False, "ignored": []},
                     final_names[-1], unassigned))
    materials = []
    errors = []
    doc.StartUndo()
    try:
        for tex_set, name, extra_files in jobs:
            try:
                if import_leftovers:
                    created = matwire_c4d.create_material_for_set(
                        doc, folder, tex_set, name,
                        leftover_files=extra_files)
                else:  # v1.32 call shape — the no-regression path
                    created = matwire_c4d.create_material_for_set(
                        doc, folder, tex_set, name)
            except Exception as exc:  # writer contract is no-raise; belt+braces
                errors.append([tex_set["name"], str(exc)])
                continue
            if created.get("ok"):
                materials.append(created.get("material_name") or name)
            else:
                errors.append([tex_set["name"], created.get("error") or "failed"])
    finally:
        doc.EndUndo()
        try:
            c4d.EventAdd()
        except Exception:
            pass
    return {"ok": True, "created": len(materials),
            "materials": materials, "errors": errors}


PANEL_TOOLS_OPS = {
    "panel/tools/hierarchy": _op_tool_hierarchy,
    "panel/tools/vibrate_null": _op_tool_vibrate_null,
    "panel/tools/cam_simple": _op_tool_cam_simple,
    "panel/tools/cam_shakel": _op_tool_cam_shakel,
    "panel/tools/h_to_layers": _op_tool_h_to_layers,
    "panel/tools/solo": _op_tool_solo,
    "panel/tools/drop_to_floor": _op_tool_drop_to_floor,
    "panel/tools/abc_retime": _op_tool_abc_retime,
    "panel/tools/mark_safe_area": _op_tool_mark_safe_area,
    "panel/tools/open_settings": _op_open_settings,
    "panel/tools/open_palette": _op_open_palette,
    "panel/open_external": _op_open_external,
    "panel/tools/delete_empty_nulls": _op_tool_delete_empty_nulls,
    "panel/tools/clean_material_tags": _op_tool_clean_material_tags,
    "panel/tools/keyframe_offset": _op_tool_keyframe_offset,
    "panel/tools/keyframe_stagger": _op_tool_keyframe_stagger,
    "panel/tools/rename_preview": _op_rename_preview,
    "panel/tools/rename_apply": _op_rename_apply,
    "panel/tools/matwire_preview": _op_matwire_preview,
    "panel/tools/matwire_create": _op_matwire_create,
}
