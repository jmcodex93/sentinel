"""Pure engine for the project standard (v1.37).

Publishing derives the ruleset from a blessed, QC-passing scene instead of
asking anyone to type JSON; new shots start from the published standard
scene, placed by the declared folder pattern. No ``import c4d`` — everything
here is testable with plain pytest. The c4d-side adapter is
``sentinel.ui.standard_ops``.
"""
from __future__ import annotations

import os

from sentinel.versioning import parse_version_filename

STANDARD_SCENE_NAME = "sentinel_standard.c4d"

# Fixed copy for the "won't travel" block of the publish preview. Sidecars
# and file-version metadata never travel: they are the previous shot's
# residue, without ambiguity.
WONT_TRAVEL = (
    "version history, notes and TODOs",
    "the file's version number",
)


def derive_shot_pattern(scene_path, project_dir):
    """Derive ``shots/{shot}/{shot}_v001.c4d`` from where the blessed shot
    lives relative to the project folder.

    Directory components that exactly equal the shot's version-stripped base
    become ``{shot}``; everything else is kept verbatim. The filename always
    becomes ``{shot}_v001.c4d`` (a new shot starts at v001 regardless of the
    blessed shot's version). Returns ``None`` when the scene lives outside
    the project folder — the caller shows the pattern field empty and the
    supervisor types one.
    """
    try:
        rel = os.path.relpath(str(scene_path), str(project_dir))
    except ValueError:  # different drive on Windows
        return None
    rel = rel.replace("\\", "/")
    if rel.startswith(".."):
        return None
    parts = [p for p in rel.split("/") if p]
    if not parts:
        return None
    stem = parts[-1].rsplit(".", 1)[0]
    base, _version, _status = parse_version_filename(stem)
    dirs = ["{shot}" if d == base else d for d in parts[:-1]]
    return "/".join(dirs + ["{shot}_v001.c4d"])


def valid_shot_name(name):
    """A shot name is one valid cross-platform path segment: non-blank, no
    separators, and none of the Windows-hostile shapes rejected by
    ``rules.valid_path_segment`` (reserved device names, invalid characters,
    trailing dots/spaces)."""
    from sentinel.rules import valid_path_segment

    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or ":" in name:
        return False
    return valid_path_segment(name)


def shot_destination(pattern, project_dir, shot_name):
    """Absolute destination for a new shot. An empty pattern places the shot
    at the project root — no invented folders (spec: out of scope)."""
    rel = (pattern or "{shot}_v001.c4d").replace("{shot}", shot_name)
    return os.path.join(str(project_dir), *[p for p in rel.split("/") if p])


def derive_rules_payload(fps, start_frame, preset_names, pattern, author,
                         published_at):
    """The derived half of ``sentinel_rules.json``.

    ``approved_presets`` and ``required_presets`` both get the blessed
    scene's real preset names: from a blessed scene, what exists is both
    allowed and required. ``template_scene`` is always the relative
    ``sentinel_standard.c4d`` (anchored to the ruleset's folder, v1.36.9).
    """
    payload = {
        "standard_fps": int(fps),
        "start_frame": int(start_frame),
        "approved_presets": list(preset_names),
        "required_presets": list(preset_names),
        "template_scene": STANDARD_SCENE_NAME,
        "published": {"by": str(author or ""), "at": str(published_at)},
    }
    if pattern:
        payload["shot_pattern"] = pattern
    return payload


def merge_rules(existing_raw, derived):
    """Derived keys win; every other key in the existing file survives
    verbatim. Writing only derived keys (not defaults) is deliberate:
    explicit defaults would freeze them in the project file, and absent keys
    already fall back to defaults — that IS the defaults mechanism."""
    merged = dict(existing_raw or {})
    merged.update(derived)
    return merged


_DIFF_LABELS = {
    "standard_fps": "fps",
    "start_frame": "start frame",
    "shot_pattern": "shot pattern",
}


def republish_diff(existing, derived):
    """Human lines describing what a republish changes. Empty on first
    publish. The standard scene file is flagged whenever the existing file
    already declared one: the .c4d on disk is replaced even when the key
    text is identical."""
    if not existing:
        return []
    lines = []
    for key, label in _DIFF_LABELS.items():
        old, new = existing.get(key), derived.get(key)
        if old is not None and new is not None and old != new:
            lines.append(f"{label}: {old} → {new}")
    for key in ("approved_presets", "required_presets"):
        old, new = existing.get(key), derived.get(key)
        if old is None or new is None:
            continue
        added = [p for p in new if p not in old]
        removed = [p for p in old if p not in new]
        if added or removed:
            bits = [f"+{p}" for p in added] + [f"-{p}" for p in removed]
            lines.append(f"{key}: " + " ".join(bits))
    if existing.get("template_scene"):
        lines.append("the standard scene file will be replaced")
    return lines
