"""Web ops for the project standard (v1.37): publish + new shot.

Thin adapters in the panel_tools_ops mold: dialog-free (a MessageDialog in
the queue drain freezes C4D), JSON-serializable returns, and every mutation
re-derives against the LIVE scene — client rows are never trusted (the
Batch Rename / matwire contract). Pure logic lives in
``sentinel.projectstd``; this module only touches c4d."""
import json
import os
import shutil
import time

import c4d

from sentinel import projectstd
from sentinel import rules as rules_module
from sentinel.common.settings import GlobalSettings
from sentinel.ui import flows
from sentinel.ui import panel_ops


# ---------------------------------------------------------------- derivation

def _top_level_objects(doc):
    out, obj, index = [], doc.GetFirstObject(), 0
    while obj:
        out.append({"name": obj.GetName(), "index": index,
                    "children": obj.GetDown() is not None})
        obj = obj.GetNext()
        index += 1
    return out


def _preset_names(doc):
    names, rd = [], doc.GetFirstRenderData()
    while rd:
        names.append(rd.GetName())
        rd = rd.GetNext()
    return names


def _scene_block(doc):
    fps = int(doc.GetFps() or 25)
    return {
        "fps": fps,
        "start_frame": int(doc.GetMinTime().GetFrame(fps)),
        "presets": _preset_names(doc),
        "objects": _top_level_objects(doc),
    }


def _qc_block(doc):
    """``pass`` reflects ``passed == total`` from the shared scoring, which
    (repo-wide contract) counts an accepted-baseline violation as passing.
    A shot with accepted violations CAN publish the standard — by design,
    not an oversight; the baseline IS the record of "this is intentional
    here"."""
    _ctx, _results, report = panel_ops._run_qc_scoring(doc)
    score = report.get("score") or {}
    passed = int(score.get("passed") or 0)
    total = int(score.get("total") or 0)
    failing = [c.get("label") or c.get("id") or ""
               for c in report.get("checks") or []
               if c.get("status") == "fail"]
    return {"passed": passed, "total": total,
            "pass": total > 0 and passed == total, "failing": failing}


def _read_raw_rules(folder):
    """Raw JSON of an existing ruleset in ``folder``. Returns (raw|None,
    ok). ``ok=False`` means the file exists but cannot be read — publishing
    over it would destroy the supervisor's manual keys, so callers refuse."""
    path = os.path.join(folder, rules_module.RULES_FILENAME)
    if not os.path.exists(path):
        return None, True
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return (raw if isinstance(raw, dict) else None), isinstance(raw, dict)
    except Exception:
        return None, False


def _doc_scene_path(doc):
    path, name = doc.GetDocumentPath(), doc.GetDocumentName()
    if not path:
        return None
    return os.path.join(path, name)


# ------------------------------------------------------------------- gesture A

def _op_standard_preview(payload):
    doc = c4d.documents.GetActiveDocument()
    if doc is None:
        return {"ok": False, "error": "no_document"}
    scene_path = _doc_scene_path(doc)
    if not scene_path:
        return {"ok": False, "error": "unsaved"}
    folder = str((payload or {}).get("folder") or "").strip()
    pattern = None
    existing, diff = False, []
    if folder:
        if not os.path.isdir(folder):
            return {"ok": False, "error": "bad_folder"}
        pattern = projectstd.derive_shot_pattern(scene_path, folder)
        raw, readable = _read_raw_rules(folder)
        existing = raw is not None or not readable
        if raw is not None:
            derived = projectstd.derive_rules_payload(
                fps=doc.GetFps(), start_frame=_scene_block(doc)["start_frame"],
                preset_names=_preset_names(doc), pattern=pattern,
                author="", published_at="")
            diff = projectstd.republish_diff(raw, derived)
    return {
        "ok": True,
        "qc": _qc_block(doc),
        "scene": _scene_block(doc),
        "pattern": pattern,
        "existing_rules": existing,
        "diff": diff,
        "wont_travel": list(projectstd.WONT_TRAVEL),
    }


def _op_standard_publish(payload):
    payload = payload or {}
    doc = c4d.documents.GetActiveDocument()
    if doc is None:
        return {"ok": False, "error": "no_document"}
    scene_path = _doc_scene_path(doc)
    if not scene_path:
        return {"ok": False, "error": "unsaved"}
    folder = str(payload.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        return {"ok": False, "error": "bad_folder"}

    # A flaw inside the standard multiplies into every shot of the project:
    # publishing from a shot that does not pass the QC is refused (spec).
    qc = _qc_block(doc)
    if not qc["pass"]:
        return {"ok": False, "error": "qc_failing", "failing": qc["failing"]}

    existing_raw, readable = _read_raw_rules(folder)
    if not readable:
        return {"ok": False, "error": "rules_unreadable"}

    # Validate BEFORE writing anything. A client-provided pattern that
    # fails rules._validate_key would otherwise sail into the ruleset and
    # get silently rejected again at load time — a green toast and a
    # degraded project. A derived pattern is trusted (it comes from
    # ``derive_shot_pattern``, not the network), but it is still run
    # through the validator for normalization; if it somehow fails, the
    # key is omitted rather than the publish refused — a derivation bug
    # is ours, not the supervisor's typo to fix. In the real SPA flow the
    # derived pattern is seeded into the editable field and posted back as
    # a CLIENT pattern, so the strict ``bad_pattern`` branch is the one
    # that actually runs; the lenient branch only serves API callers that
    # omit ``pattern`` entirely.
    raw_pattern = payload.get("pattern")
    if raw_pattern is not None:
        raw_pattern = str(raw_pattern).strip() or None
    if raw_pattern is not None:
        valid, normalized, _reason = rules_module._validate_key(
            "shot_pattern", raw_pattern)
        if not valid:
            return {"ok": False, "error": "bad_pattern"}
        pattern = normalized
    else:
        derived_pattern = projectstd.derive_shot_pattern(scene_path, folder)
        pattern = None
        if derived_pattern is not None:
            valid, normalized, _reason = rules_module._validate_key(
                "shot_pattern", derived_pattern)
            pattern = normalized if valid else None

    # Re-derive the exclusion against the LIVE scene. Location identity
    # (name + sibling index), honored only when both still match — a stale
    # preview refuses instead of removing the wrong branch.
    excludes = []
    tops = _top_level_objects(doc)
    for entry in payload.get("exclude") or []:
        try:
            name, index = str(entry[0]), int(entry[1])
        except Exception:
            return {"ok": False, "error": "scene_changed"}
        if index >= len(tops) or tops[index]["name"] != name:
            return {"ok": False, "error": "scene_changed"}
        excludes.append(index)

    # Clone, strip the curated-out branches, save to a TEMP path. The live
    # document is never mutated — the standard is a cleaned COPY. Saving to
    # a tmp path (renamed into place only after the rules file is safely
    # written, see below) keeps the window where a half-published project
    # could exist as narrow as a single os.replace.
    clone = doc.GetClone(c4d.COPYFLAGS_NONE)
    if clone is None:
        return {"ok": False, "error": "save_failed"}
    scene_dest = os.path.join(folder, projectstd.STANDARD_SCENE_NAME)
    tmp_scene = scene_dest + ".tmp"
    try:
        clone_tops, obj = [], clone.GetFirstObject()
        while obj:
            clone_tops.append(obj)
            obj = obj.GetNext()
        if len(clone_tops) != len(tops):
            # The scene changed between the top-level snapshot and the
            # clone (an object was added/removed at the root) — the
            # exclude indices can no longer be trusted against this clone.
            return {"ok": False, "error": "scene_changed"}
        for index in excludes:
            clone_tops[index].Remove()
        saved = c4d.documents.SaveDocument(
            clone, tmp_scene,
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST, c4d.FORMAT_C4DEXPORT)
    finally:
        c4d.documents.KillDocument(clone)
    if not saved:
        # A refused/partial SaveDocument can still leave a stray tmp file
        # in the project folder — never litter a team's shared directory.
        try:
            os.remove(tmp_scene)
        except Exception:
            pass
        return {"ok": False, "error": "save_failed"}

    derived = projectstd.derive_rules_payload(
        fps=doc.GetFps(),
        start_frame=_scene_block(doc)["start_frame"],
        preset_names=_preset_names(doc),
        pattern=pattern,
        author=GlobalSettings.load_artist_name(),
        published_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    merged = projectstd.merge_rules(existing_raw, derived)
    rules_path = os.path.join(folder, rules_module.RULES_FILENAME)
    tmp_rules = rules_path + ".tmp"
    try:
        with open(tmp_rules, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_rules, rules_path)
    except Exception:
        try:
            os.remove(tmp_rules)
        except Exception:
            pass
        try:
            os.remove(tmp_scene)
        except Exception:
            pass
        return {"ok": False, "error": "write_failed"}

    # Rules are the source of truth and are now committed. Only the final
    # rename of the scene remains — the narrowest possible torn window.
    try:
        os.replace(tmp_scene, scene_dest)
    except Exception:
        # The rules ARE committed at this point (inverted torn state: new
        # rules, old scene) — invalidate so the plugin sees them, clean the
        # tmp, and report the scene failure honestly.
        rules_module.invalidate()
        try:
            os.remove(tmp_scene)
        except Exception:
            pass
        return {"ok": False, "error": "save_failed"}

    rules_module.invalidate()
    return {"ok": True, "scene_path": scene_dest, "rules_path": rules_path,
            "excluded": len(excludes)}


# ------------------------------------------------------------------- gesture B

def _resolve_standard(folder):
    """Locate the project standard from any folder inside the project.
    Returns a dict or an error dict. Uses the same discovery as scene rules
    (nearest sentinel_rules.json, up to 3 ancestors); the ruleset's own
    folder is the project dir and anchors the relative template path."""
    if not folder or not os.path.isdir(folder):
        return {"ok": False, "error": "bad_folder"}
    rules_path, _shadowed = rules_module.discover_rules_file(folder)
    if not rules_path:
        return {"ok": False, "error": "no_standard", "searched": folder}
    rules, _warnings = rules_module.load_rules(rules_path)
    template_rel = rules.get("template_scene") or ""
    if not template_rel:
        return {"ok": False, "error": "no_template", "rules_path": rules_path}
    project_dir = os.path.dirname(rules_path)
    if os.path.isabs(template_rel):
        template = os.path.normpath(template_rel)
    else:
        template = os.path.normpath(os.path.join(project_dir, template_rel))
    return {
        "ok": True,
        "rules_path": rules_path,
        "project_dir": project_dir,
        "template": template,
        "template_exists": os.path.exists(template),
        "pattern": rules.get("shot_pattern") or "",
        "published": rules.get("published") or None,
    }


def _op_newshot_preview(payload):
    return _resolve_standard(str((payload or {}).get("folder") or "").strip())


def _op_newshot_create(payload):
    payload = payload or {}
    std = _resolve_standard(str(payload.get("folder") or "").strip())
    if not std.get("ok"):
        return std
    name = str(payload.get("name") or "").strip()
    if not projectstd.valid_shot_name(name):
        return {"ok": False, "error": "bad_name"}
    if not std["template_exists"]:
        # Never falls back to the plugin's new.c4d: starting a whole shot
        # from the wrong standard is worse than not starting (spec).
        return {"ok": False, "error": "template_missing", "path": std["template"]}
    dest = projectstd.shot_destination(std["pattern"], std["project_dir"], name)
    if os.path.exists(dest):
        return {"ok": False, "error": "exists", "path": dest}
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(std["template"], dest)
    except Exception:
        return {"ok": False, "error": "copy_failed", "path": dest}
    result = flows.open_version_core(dest) or {}
    return {"ok": True, "path": dest, "opened": bool(result.get("ok"))}


STANDARD_OPS = {
    "panel/tools/standard_preview": _op_standard_preview,
    "panel/tools/standard_publish": _op_standard_publish,
    "panel/tools/newshot_preview": _op_newshot_preview,
    "panel/tools/newshot_create": _op_newshot_create,
}
