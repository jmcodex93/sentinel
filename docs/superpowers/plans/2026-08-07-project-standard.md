# El estándar del proyecto (v1.37) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two gestures on top of the v1.36.10 template machinery — (A) the supervisor publishes the project standard (`sentinel_rules.json` + a cleaned standard scene) from a QC-passing shot, with a curated preview and provenance; (B) the artist creates a new shot from that standard, placed by the declared folder pattern, with no leftovers from anyone's shot.

**Architecture:** A new pure engine `plugin/sentinel/projectstd.py` (no `import c4d`) owns pattern derivation, derived-rules payload, merge, and republish diff. A new thin adapter `plugin/sentinel/ui/standard_ops.py` owns the four web ops (`panel/tools/standard_preview|standard_publish|newshot_preview|newshot_create`), dialog-free, server-re-deriving on every mutation. Two new ruleset keys (`shot_pattern`, `published`) ride the existing per-key validation in `rules.py`. The SPA gets a "Project" group in Tools with two sub-views (Matwire/Rename idiom: preview-driven, `postHubPickPath` for folders).

**Tech Stack:** Python 3 (C4D 2026 plugin, pytest with the repo's fake-c4d harness), TypeScript/React (Vite + Tailwind, vitest), stdlib only.

**Spec:** `docs/superpowers/specs/2026-08-07-project-standard-design.md`

## Global Constraints

- Branch: `feat/project-standard`. Version bump: **v1.37.0** (last: v1.36.11, pytest 1486, vitest 224).
- **No dialogs in any op path** (`MessageDialog`/`QuestionDialog` forbidden — every op test includes the `_forbid_dialog` monkeypatch pattern from `tests/test_panel_tools_ops.py`).
- Op returns must be **JSON-serializable** (never a `BaseObject`/`BaseTag`/`BaseDocument`).
- Op error convention for `panel/tools/*`-style ops: `{"ok": False, "error": "<code>"}` (codes are snake_case; the SPA keys copy off `error`).
- **Mutations re-derive server-side** — client rows are never trusted (Batch Rename / matwire contract).
- Panel copy is **English** (the SPA surface's language).
- The standard scene file is named **`sentinel_standard.c4d`**, written next to `sentinel_rules.json`; `template_scene` is written as the **relative** string `"sentinel_standard.c4d"` (relative paths anchor to the ruleset's folder — v1.36.9).
- *Nuevo shot* **never falls back** to the plugin's `new.c4d` (spec: the fall is deliberately asymmetric — Reset All may, new-shot refuses).
- Ruleset writes are **atomic** (tmp + `os.replace`) and followed by `rules.invalidate()`.
- Publishing writes **only derived keys + provenance**, merged over the existing file's raw keys (existing non-derived keys are preserved verbatim). Deviation from the spec's literal "defaults para el resto", with reason: writing defaults explicitly would *freeze* them in the project file, so a later plugin default change would never reach the project; absent keys already fall back to defaults — that IS the defaults mechanism.
- Mutation verification: every new test is killed by its named mutation. On this Synology volume always run with `PYTHONDONTWRITEBYTECODE=1` and delete `__pycache__` between mutants (stale-`.pyc` lesson).
- SPA build (`cd web && npm run build`) must be run and `plugin/web/` committed with any web source change.
- Baselines after each task: pytest and vitest full suites green (`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q`, `cd web && npx vitest run`).

**Known-trap ledger (verbatim from spec, applies to live verification):** `SaveDocument` writes the file but does NOT bind the in-memory doc to that path — `GetDocumentPath()` stays empty and ruleset discovery has nowhere to start (`reason='unsaved'`). Anything that verifies ruleset discovery in live C4D must **save and reload**.

---

## File Structure

| File | Role |
|---|---|
| Create `plugin/sentinel/projectstd.py` | Pure engine: shot-pattern derivation, destination resolution, derived-rules payload, merge, republish diff, shot-name validation |
| Create `tests/test_projectstd.py` | Engine tests (pytest direct, no c4d) |
| Modify `plugin/sentinel/rules.py` | Two new keys in `DEFAULTS` + `_validate_key` branches: `shot_pattern`, `published` |
| Modify `tests/test_rules.py` | Validation tests for the two keys |
| Create `plugin/sentinel/ui/standard_ops.py` | The four ops + c4d-side derivation helpers + `STANDARD_OPS` dict |
| Create `tests/test_standard_ops.py` | Op contract tests (fakes + `_forbid_dialog`) |
| Modify `plugin/sentinel/ui/reports_dialog.py` | Merge `**STANDARD_OPS` into `_OPS` |
| Modify `web/src/types.ts`, `web/src/lib/api.ts` | Response types + 4 fetch/post helpers |
| Create `web/src/lib/panelStandard.ts` + `.test.ts` | Pure client logic: error copy, QC gate line, travel/diff formatting, exclude toggling |
| Create `web/src/components/panel/StandardSubview.tsx` | Supervisor gesture (publish) |
| Create `web/src/components/panel/NewShotSubview.tsx` | Artist gesture (new shot) |
| Modify `web/src/components/panel/ToolsSection.tsx` | View union + "Project" group with the two opener buttons |
| Modify `CLAUDE.md`, `ROADMAP.md`, version constants | v1.37.0 bump + docs |

---

### Task 1: Ruleset keys `shot_pattern` and `published`

**Files:**
- Modify: `plugin/sentinel/rules.py` (DEFAULTS at :25-57, `_validate_key` at :345)
- Test: `tests/test_rules.py`

**Interfaces:**
- Produces: ruleset keys `shot_pattern` (str, default `""`; when set: non-empty relative path string containing `{shot}`, `\` normalized to `/`, every segment Windows-safe) and `published` (dict, default `{}`; when set: dict with only string keys and string values, e.g. `{"by": "Javier", "at": "2026-08-07 12:00:00"}`). Also `rules.valid_path_segment(segment) -> bool` (public — Task 2's `valid_shot_name` imports it). Later tasks read the keys via `RulesContext.params` / `rules.load_rules`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_rules.py`, following its existing style for per-key validation — look at the existing `template_scene` tests in that file and mirror their fixture helpers):

```python
class TestShotPatternKey:
    def test_valid_pattern_is_accepted(self, tmp_path):
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"shot_pattern": "shots/{shot}/{shot}_v001.c4d"}))
        rules, warnings = load_rules(p)
        assert rules["shot_pattern"] == "shots/{shot}/{shot}_v001.c4d"
        assert warnings == []

    def test_pattern_without_shot_token_is_rejected_by_name(self, tmp_path):
        """A pattern with no {shot} placeholder can't name a shot — rejected,
        rest of the file still applies (house per-key contract)."""
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"shot_pattern": "shots/fixed_v001.c4d", "standard_fps": 24}))
        rules, warnings = load_rules(p)
        assert "shot_pattern" not in rules
        assert rules["standard_fps"] == 24
        assert any("shot_pattern" in w for w in warnings)

    def test_absolute_pattern_is_rejected(self, tmp_path):
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"shot_pattern": "/abs/{shot}.c4d"}))
        rules, warnings = load_rules(p)
        assert "shot_pattern" not in rules

    def test_non_string_is_rejected(self, tmp_path):
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"shot_pattern": 7}))
        rules, warnings = load_rules(p)
        assert "shot_pattern" not in rules

    def test_backslashes_normalize_to_forward_slashes(self, tmp_path):
        """A Windows supervisor pastes backslashes; accept and normalize
        (the Work Flow plugin's rule, studied 2026-08: both separators in,
        '/' out)."""
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"shot_pattern": "shots\\{shot}\\{shot}_v001.c4d"}))
        rules, warnings = load_rules(p)
        assert rules["shot_pattern"] == "shots/{shot}/{shot}_v001.c4d"

    def test_windows_hostile_segments_are_rejected(self, tmp_path):
        """Segments that cannot exist as Windows folders — reserved device
        names, invalid characters, trailing dots/spaces, '..' escapes — are
        rejected at validation time, not discovered on the artist's machine.
        Cross-platform is a project constraint."""
        for bad in ("shots/../{shot}.c4d", "CON/{shot}.c4d",
                    "sh<ot>/{shot}.c4d", "shots./{shot}.c4d"):
            p = tmp_path / "sentinel_rules.json"
            p.write_text(json.dumps({"shot_pattern": bad}))
            rules, warnings = load_rules(p)
            assert "shot_pattern" not in rules, bad


class TestPublishedKey:
    def test_valid_provenance_dict_is_accepted(self, tmp_path):
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"published": {"by": "Javier", "at": "2026-08-07 12:00:00"}}))
        rules, warnings = load_rules(p)
        assert rules["published"] == {"by": "Javier", "at": "2026-08-07 12:00:00"}
        assert warnings == []

    def test_non_dict_is_rejected_by_name(self, tmp_path):
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"published": "Javier", "standard_fps": 24}))
        rules, warnings = load_rules(p)
        assert "published" not in rules
        assert rules["standard_fps"] == 24

    def test_non_string_values_are_rejected(self, tmp_path):
        p = tmp_path / "sentinel_rules.json"
        p.write_text(json.dumps({"published": {"by": 3}}))
        rules, warnings = load_rules(p)
        assert "published" not in rules
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_rules.py -q -k "ShotPattern or Published"`
Expected: FAIL — `load_rules` rejects both keys as `"unknown key"` today, so the accept tests fail.

- [ ] **Step 3: Implement.** In `DEFAULTS` add (next to `"template_scene": ""`):

```python
    # v1.37: folder pattern for new shots, derived at publish time from where
    # the blessed shot lived relative to the project folder. "" = not declared.
    "shot_pattern": "",
    # v1.37: publish provenance — who published the standard and when. Replace
    # semantics (NOT in MAP_MERGE_KEYS): a republish is a new provenance, not
    # a merge of authors. Informational; no engine consumer reads it to decide.
    "published": {},
```

In `_validate_key`, before the final `return False, None, "unknown key"`:

```python
# Path-segment hygiene shared by shot_pattern validation and (via import in
# projectstd) shot names. Rules studied from the Work Flow plugin's structure
# editor (boghma.com, 2026-08 — concepts only, no code seen): a segment that
# cannot exist as a Windows folder is rejected at validation time instead of
# being discovered on the artist's machine. Cross-platform is a project
# constraint (macOS + Windows).
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_SEGMENT_CHARS = set('<>:"|?*')


def valid_path_segment(segment: str) -> bool:
    """True when ``segment`` can be a folder/file name on every platform we
    ship on. ``{shot}`` placeholders are stripped before judging so the
    pattern segment ``{shot}_v001.c4d`` is judged on its literal part."""
    literal = segment.replace("{shot}", "s")
    if not literal or literal in (".", ".."):
        return False
    if literal != literal.rstrip(". "):
        return False
    if any(ch in _INVALID_SEGMENT_CHARS for ch in literal):
        return False
    if literal.split(".")[0].upper() in _WINDOWS_RESERVED:
        return False
    return True
```

And the `_validate_key` branch:

```python
    if key == "shot_pattern":
        if not isinstance(value, str) or not value.strip():
            return False, None, "expected a non-empty pattern string"
        pattern = value.strip().replace("\\", "/")
        if "{shot}" not in pattern:
            return False, None, "pattern must contain {shot}"
        if pattern.startswith("/") or ":" in pattern.split("/")[0]:
            return False, None, "pattern must be relative to the project folder"
        segments = [s for s in pattern.split("/") if s]
        if not segments or not all(valid_path_segment(s) for s in segments):
            return False, None, "pattern contains an invalid path segment"
        return True, pattern, None
    if key == "published":
        if not isinstance(value, dict):
            return False, None, "expected an object"
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return False, None, "expected string keys and values"
        return True, dict(value), None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_rules.py -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Mutation check** (each mutation kills its named test): (a) delete the `"{shot}" not in pattern` guard → `test_pattern_without_shot_token_is_rejected_by_name` fails; (b) make `published` accept any value → `test_non_dict_is_rejected_by_name` fails; (c) make `valid_path_segment` return `True` unconditionally → `test_windows_hostile_segments_are_rejected` fails. Restore code, delete `__pycache__` between runs.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/rules.py tests/test_rules.py
git commit -m "feat(rules): claves shot_pattern y published para el estandar del proyecto (v1.37)"
```

---

### Task 2: Pure engine `projectstd.py`

**Files:**
- Create: `plugin/sentinel/projectstd.py`
- Test: `tests/test_projectstd.py`

**Interfaces:**
- Consumes: `sentinel.versioning.parse_version_filename(name_no_ext) -> (base, version|None, status|None)`; `sentinel.rules.valid_path_segment(segment) -> bool` (Task 1).
- Produces (exact signatures later tasks call):
  - `STANDARD_SCENE_NAME = "sentinel_standard.c4d"`
  - `derive_shot_pattern(scene_path: str, project_dir: str) -> str | None`
  - `valid_shot_name(name) -> bool`
  - `shot_destination(pattern: str, project_dir: str, shot_name: str) -> str`
  - `derive_rules_payload(fps, start_frame, preset_names, pattern, author, published_at) -> dict`
  - `merge_rules(existing_raw: dict | None, derived: dict) -> dict`
  - `republish_diff(existing: dict | None, derived: dict) -> list[str]`

- [ ] **Step 1: Write the failing tests** — create `tests/test_projectstd.py`:

```python
"""Pure-engine tests for the project standard (v1.37). No c4d import."""
import os

from sentinel import projectstd


class TestDeriveShotPattern:
    def test_shot_in_named_folder(self):
        pat = projectstd.derive_shot_pattern(
            "/prj/shots/SH010/SH010_v012.c4d", "/prj")
        assert pat == "shots/{shot}/{shot}_v001.c4d"

    def test_shot_at_project_root(self):
        pat = projectstd.derive_shot_pattern("/prj/SH010_v012_TR.c4d", "/prj")
        assert pat == "{shot}_v001.c4d"

    def test_folder_not_named_after_shot_is_kept_verbatim(self):
        pat = projectstd.derive_shot_pattern(
            "/prj/escenas/SH010_v012.c4d", "/prj")
        assert pat == "escenas/{shot}_v001.c4d"

    def test_scene_outside_project_returns_none(self):
        assert projectstd.derive_shot_pattern("/otro/SH010_v001.c4d", "/prj") is None

    def test_unversioned_filename_still_derives(self):
        pat = projectstd.derive_shot_pattern("/prj/shots/master/master.c4d", "/prj")
        assert pat == "shots/{shot}/{shot}_v001.c4d"


class TestShotDestination:
    def test_pattern_expansion(self):
        dest = projectstd.shot_destination(
            "shots/{shot}/{shot}_v001.c4d", "/prj", "SH020")
        assert dest == os.path.join("/prj", "shots", "SH020", "SH020_v001.c4d")

    def test_empty_pattern_places_at_project_root(self):
        """An absent shot_pattern places the shot at the project root — no
        invented folder structure (spec: out of scope), no refusal either
        (a missing pattern is missing placement info, not a wrong standard)."""
        dest = projectstd.shot_destination("", "/prj", "SH020")
        assert dest == os.path.join("/prj", "SH020_v001.c4d")


class TestValidShotName:
    def test_plain_name_ok(self):
        assert projectstd.valid_shot_name("SH020")

    def test_empty_and_separators_rejected(self):
        assert not projectstd.valid_shot_name("")
        assert not projectstd.valid_shot_name("a/b")
        assert not projectstd.valid_shot_name("a\\b")
        assert not projectstd.valid_shot_name("  ")

    def test_windows_hostile_names_rejected(self):
        """Same hygiene as shot_pattern segments (rules.valid_path_segment):
        a shot named AUX or 'SH01?' would create an impossible folder on a
        Windows station."""
        assert not projectstd.valid_shot_name("AUX")
        assert not projectstd.valid_shot_name("SH01?")
        assert not projectstd.valid_shot_name("SH01.")
        assert not projectstd.valid_shot_name("..")


class TestDeriveRulesPayload:
    def test_payload_shape(self):
        payload = projectstd.derive_rules_payload(
            fps=25, start_frame=1001,
            preset_names=["previz", "render"],
            pattern="shots/{shot}/{shot}_v001.c4d",
            author="Javier", published_at="2026-08-07 12:00:00")
        assert payload == {
            "standard_fps": 25,
            "start_frame": 1001,
            "approved_presets": ["previz", "render"],
            "required_presets": ["previz", "render"],
            "template_scene": "sentinel_standard.c4d",
            "shot_pattern": "shots/{shot}/{shot}_v001.c4d",
            "published": {"by": "Javier", "at": "2026-08-07 12:00:00"},
        }

    def test_no_pattern_key_when_underivable(self):
        payload = projectstd.derive_rules_payload(
            fps=25, start_frame=1001, preset_names=[],
            pattern=None, author="", published_at="t")
        assert "shot_pattern" not in payload


class TestMergeRules:
    def test_derived_wins_manual_keys_survive(self):
        existing = {"standard_fps": 24, "gates_enabled": True,
                    "safe_area_insets": {"9x16": [1, 2, 3, 4]}}
        derived = {"standard_fps": 25, "template_scene": "sentinel_standard.c4d"}
        merged = projectstd.merge_rules(existing, derived)
        assert merged["standard_fps"] == 25
        assert merged["gates_enabled"] is True
        assert merged["safe_area_insets"] == {"9x16": [1, 2, 3, 4]}

    def test_none_existing_is_just_derived(self):
        derived = {"standard_fps": 25}
        assert projectstd.merge_rules(None, derived) == derived


class TestRepublishDiff:
    def test_first_publish_has_no_diff(self):
        assert projectstd.republish_diff(None, {"standard_fps": 25}) == []

    def test_scalar_change_is_named(self):
        lines = projectstd.republish_diff(
            {"standard_fps": 25}, {"standard_fps": 24})
        assert lines == ["fps: 25 → 24"]

    def test_preset_add_remove_named(self):
        lines = projectstd.republish_diff(
            {"required_presets": ["previz", "stills"]},
            {"required_presets": ["previz", "cliente_9x16"],
             "approved_presets": ["previz", "cliente_9x16"]})
        assert any("+cliente_9x16" in l for l in lines)
        assert any("-stills" in l for l in lines)

    def test_unchanged_keys_produce_no_lines(self):
        same = {"standard_fps": 25, "required_presets": ["a"]}
        assert projectstd.republish_diff(dict(same), dict(same)) == []

    def test_template_replacement_always_flagged_when_existing_declares_one(self):
        """Republish overwrites sentinel_standard.c4d on disk even when the
        key text does not change — the supervisor must hear it."""
        lines = projectstd.republish_diff(
            {"template_scene": "sentinel_standard.c4d"},
            {"template_scene": "sentinel_standard.c4d"})
        assert lines == ["the standard scene file will be replaced"]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_projectstd.py -q`
Expected: FAIL — `ModuleNotFoundError: sentinel.projectstd` (or ImportError).

- [ ] **Step 3: Implement** — create `plugin/sentinel/projectstd.py`:

```python
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
```

Note for the implementer: `test_template_replacement_always_flagged_when_existing_declares_one` expects ONLY that line when nothing else changed — the implementation above satisfies it because scalar/preset loops emit nothing for equal values. `test_unchanged_keys_produce_no_lines` uses an existing dict **without** `template_scene`, so the flag line does not appear there.

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_projectstd.py -q`
Expected: PASS (16 tests).

- [ ] **Step 5: Mutation check** — (a) in `derive_shot_pattern` stop replacing dir components (`dirs = parts[:-1]`) → `test_shot_in_named_folder` fails; (b) in `merge_rules` swap update order (`derived` first, existing wins) → `test_derived_wins_manual_keys_survive` fails; (c) in `republish_diff` drop the template flag → `test_template_replacement_always_flagged_when_existing_declares_one` fails. Restore after each.

- [ ] **Step 6: Commit**

```bash
git add plugin/sentinel/projectstd.py tests/test_projectstd.py
git commit -m "feat(projectstd): motor puro del estandar del proyecto (v1.37)"
```

---

### Task 3: Ops A — `standard_preview` + `standard_publish`

**Files:**
- Create: `plugin/sentinel/ui/standard_ops.py`
- Modify: `plugin/sentinel/ui/reports_dialog.py` (imports at :57-63, `_OPS` at :317-330)
- Test: `tests/test_standard_ops.py`

**Interfaces:**
- Consumes: `panel_ops._run_qc_scoring(doc) -> (rules_context, registry_results, qc_report)`; `projectstd.*` (Task 2); `rules.invalidate()`; `GlobalSettings.load_artist_name()` (`plugin/sentinel/common/settings.py:78`).
- Produces:
  - `STANDARD_OPS` dict with `"panel/tools/standard_preview"` and `"panel/tools/standard_publish"` (Task 4 adds the newshot pair to the same dict).
  - Preview response: `{"ok": True, "qc": {"passed", "total", "pass", "failing": [labels]}, "scene": {"fps", "start_frame", "presets": [names], "objects": [{"name", "index", "children"}]}, "pattern": str|null, "existing_rules": bool, "diff": [lines], "wont_travel": [lines]}` or `{"ok": False, "error": "no_document"|"unsaved"|"bad_folder"}`.
  - Publish response: `{"ok": True, "scene_path", "rules_path", "excluded": N}` or `{"ok": False, "error": "no_document"|"unsaved"|"bad_folder"|"qc_failing"|"scene_changed"|"rules_unreadable"|"save_failed"|"write_failed"}` (`qc_failing` carries `"failing": [labels]`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_standard_ops.py`. Reuse the repo's fake-c4d harness idioms (see `tests/test_panel_render_ops.py` for fake docs with render data and `tests/test_panel_tools_ops.py` for `_forbid_dialog` / registration assertions). Core skeleton:

```python
"""Contract tests for panel/tools/standard_* (v1.37).

The fakes model exactly what the ops touch: document path/name, fps,
min time, render-data names, top-level object list, GetClone, and the
module-level SaveDocument. What they do NOT model is written in their
docstrings (real QC checks — scoring is monkeypatched; C4D file I/O)."""
import json
import os

import pytest

from sentinel.ui import standard_ops
from sentinel.ui import reports_dialog


class _FakeObj:
    def __init__(self, name, children=0):
        self._name, self._children = name, children
        self.removed = False
        self._next = None
    def GetName(self):
        return self._name
    def GetNext(self):
        return self._next
    def GetDown(self):
        return object() if self._children else None
    def Remove(self):
        self.removed = True


class _FakeRd:
    def __init__(self, name):
        self._name = name
        self._next = None
    def GetName(self):
        return self._name
    def GetNext(self):
        return self._next


def _link(nodes):
    for a, b in zip(nodes, nodes[1:]):
        a._next = b
    return nodes[0] if nodes else None


class _FakeTime:
    def __init__(self, frame):
        self._frame = frame
    def GetFrame(self, fps):
        return self._frame


class _FakeDoc:
    def __init__(self, path="/prj/shots/SH010", name="SH010_v012.c4d",
                 fps=25, start=1001, presets=("previz", "render"),
                 objects=()):
        self._path, self._name, self._fps, self._start = path, name, fps, start
        self._first_rd = _link([_FakeRd(p) for p in presets])
        self._objects = list(objects)
        self._first_obj = _link(self._objects)
        self.clone = None
    def GetDocumentPath(self):
        return self._path
    def GetDocumentName(self):
        return self._name
    def GetFps(self):
        return self._fps
    def GetMinTime(self):
        return _FakeTime(self._start)
    def GetFirstRenderData(self):
        return self._first_rd
    def GetFirstObject(self):
        return self._first_obj
    def GetClone(self, flags):
        self.clone = _FakeDoc(self._path, self._name, self._fps, self._start,
                              [], [])
        self.clone._objects = [_FakeObj(o.GetName(),
                                        1 if o.GetDown() else 0)
                               for o in self._objects]
        self.clone._first_obj = _link(self.clone._objects)
        return self.clone


def _passing_qc(monkeypatch, failing=()):
    checks = [{"label": lab, "status": "fail"} for lab in failing]
    passed = 12 - len(failing)
    report = {"score": {"passed": passed, "total": 12}, "checks": checks}
    monkeypatch.setattr(standard_ops.panel_ops, "_run_qc_scoring",
                        lambda doc: (None, None, report))


class TestStandardOps:
    @pytest.fixture(autouse=True)
    def _forbid_dialog(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")
        monkeypatch.setattr(standard_ops.c4d.gui, "MessageDialog", _boom)
        monkeypatch.setattr(standard_ops.c4d.gui, "QuestionDialog", _boom)

    def _setup(self, monkeypatch, doc, saved=True):
        monkeypatch.setattr(standard_ops.c4d.documents, "GetActiveDocument",
                            lambda: doc)
        monkeypatch.setattr(standard_ops.c4d.documents, "SaveDocument",
                            lambda d, p, f, fmt: saved)
        monkeypatch.setattr(standard_ops.c4d.documents, "KillDocument",
                            lambda d: None)

    def test_ops_registered(self):
        assert "panel/tools/standard_preview" in standard_ops.STANDARD_OPS
        assert "panel/tools/standard_publish" in reports_dialog._OPS

    def test_preview_no_document(self, monkeypatch):
        monkeypatch.setattr(standard_ops.c4d.documents, "GetActiveDocument",
                            lambda: None)
        assert standard_ops._op_standard_preview({}) == {
            "ok": False, "error": "no_document"}

    def test_preview_unsaved_doc_refuses(self, monkeypatch):
        doc = _FakeDoc(path="")
        self._setup(monkeypatch, doc)
        assert standard_ops._op_standard_preview({})["error"] == "unsaved"

    def test_preview_reports_scene_and_qc(self, monkeypatch, tmp_path):
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 2), _FakeObj("petals", 1)])
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch)
        out = standard_ops._op_standard_preview({"folder": str(tmp_path)})
        assert out["ok"] and out["qc"]["pass"]
        assert out["scene"]["fps"] == 25
        assert out["scene"]["start_frame"] == 1001
        assert out["scene"]["presets"] == ["previz", "render"]
        assert out["scene"]["objects"] == [
            {"name": "Cameras", "index": 0, "children": True},
            {"name": "petals", "index": 1, "children": True},
        ]
        assert out["existing_rules"] is False and out["diff"] == []

    def test_preview_failing_qc_lists_labels(self, monkeypatch, tmp_path):
        doc = _FakeDoc()
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch, failing=["Lights Organization"])
        out = standard_ops._op_standard_preview({"folder": str(tmp_path)})
        assert out["qc"]["pass"] is False
        assert out["qc"]["failing"] == ["Lights Organization"]

    def test_preview_diff_against_existing_rules(self, monkeypatch, tmp_path):
        (tmp_path / "sentinel_rules.json").write_text(
            json.dumps({"standard_fps": 24}))
        doc = _FakeDoc()
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch)
        out = standard_ops._op_standard_preview({"folder": str(tmp_path)})
        assert out["existing_rules"] is True
        assert any("fps" in l for l in out["diff"])

    def test_publish_refuses_failing_qc(self, monkeypatch, tmp_path):
        doc = _FakeDoc()
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch, failing=["Default Names"])
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out == {"ok": False, "error": "qc_failing",
                       "failing": ["Default Names"]}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_writes_scene_and_rules(self, monkeypatch, tmp_path):
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 1), _FakeObj("petals", 1)])
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch)
        monkeypatch.setattr(standard_ops.GlobalSettings, "load_artist_name",
                            staticmethod(lambda: "Javier"))
        out = standard_ops._op_standard_publish({
            "folder": str(tmp_path),
            "exclude": [["petals", 1]],
            "pattern": "shots/{shot}/{shot}_v001.c4d"})
        assert out["ok"]
        raw = json.loads((tmp_path / "sentinel_rules.json").read_text())
        assert raw["standard_fps"] == 25
        assert raw["template_scene"] == "sentinel_standard.c4d"
        assert raw["shot_pattern"] == "shots/{shot}/{shot}_v001.c4d"
        assert raw["published"]["by"] == "Javier"
        # the excluded branch was removed from the CLONE, not the live doc
        assert doc.clone._objects[1].removed is True
        assert doc._objects[1].removed is False

    def test_publish_preserves_manual_keys_on_republish(self, monkeypatch, tmp_path):
        (tmp_path / "sentinel_rules.json").write_text(
            json.dumps({"gates_enabled": True, "standard_fps": 24}))
        doc = _FakeDoc()
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch)
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out["ok"]
        raw = json.loads((tmp_path / "sentinel_rules.json").read_text())
        assert raw["gates_enabled"] is True      # manual key survives
        assert raw["standard_fps"] == 25         # derived key wins

    def test_publish_stale_exclude_refuses(self, monkeypatch, tmp_path):
        """Preview rows are never trusted: an exclude that no longer matches
        the live scene refuses instead of silently dropping."""
        doc = _FakeDoc(objects=[_FakeObj("Cameras", 1)])
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch)
        out = standard_ops._op_standard_publish({
            "folder": str(tmp_path), "exclude": [["gone", 5]]})
        assert out == {"ok": False, "error": "scene_changed"}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_save_failure_does_not_write_rules(self, monkeypatch, tmp_path):
        doc = _FakeDoc()
        self._setup(monkeypatch, doc, saved=False)
        _passing_qc(monkeypatch)
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out == {"ok": False, "error": "save_failed"}
        assert not (tmp_path / "sentinel_rules.json").exists()

    def test_publish_unreadable_rules_refuses(self, monkeypatch, tmp_path):
        (tmp_path / "sentinel_rules.json").write_text("{not json")
        doc = _FakeDoc()
        self._setup(monkeypatch, doc)
        _passing_qc(monkeypatch)
        out = standard_ops._op_standard_publish({"folder": str(tmp_path)})
        assert out == {"ok": False, "error": "rules_unreadable"}
        assert (tmp_path / "sentinel_rules.json").read_text() == "{not json"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_standard_ops.py -q`
Expected: FAIL — module `sentinel.ui.standard_ops` does not exist.

- [ ] **Step 3: Implement** — create `plugin/sentinel/ui/standard_ops.py`:

```python
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

    # Clone, strip the curated-out branches, save. The live document is
    # never mutated — the standard is a cleaned COPY.
    clone = doc.GetClone(c4d.COPYFLAGS_NONE)
    if clone is None:
        return {"ok": False, "error": "save_failed"}
    scene_dest = os.path.join(folder, projectstd.STANDARD_SCENE_NAME)
    try:
        clone_tops, obj = [], clone.GetFirstObject()
        while obj:
            clone_tops.append(obj)
            obj = obj.GetNext()
        for index in excludes:
            clone_tops[index].Remove()
        saved = c4d.documents.SaveDocument(
            clone, scene_dest,
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST, c4d.FORMAT_C4DEXPORT)
    finally:
        c4d.documents.KillDocument(clone)
    if not saved:
        return {"ok": False, "error": "save_failed"}

    pattern = payload.get("pattern")
    if pattern is not None:
        pattern = str(pattern).strip() or None
    if pattern is None:
        pattern = projectstd.derive_shot_pattern(scene_path, folder)
    derived = projectstd.derive_rules_payload(
        fps=doc.GetFps(),
        start_frame=_scene_block(doc)["start_frame"],
        preset_names=_preset_names(doc),
        pattern=pattern,
        author=GlobalSettings.load_artist_name(),
        published_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    merged = projectstd.merge_rules(existing_raw, derived)
    rules_path = os.path.join(folder, rules_module.RULES_FILENAME)
    tmp_path = rules_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, rules_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return {"ok": False, "error": "write_failed"}
    rules_module.invalidate()
    return {"ok": True, "scene_path": scene_dest, "rules_path": rules_path,
            "excluded": len(excludes)}


STANDARD_OPS = {
    "panel/tools/standard_preview": _op_standard_preview,
    "panel/tools/standard_publish": _op_standard_publish,
}
```

Then in `plugin/sentinel/ui/reports_dialog.py`: add `from sentinel.ui.standard_ops import STANDARD_OPS` next to the sibling imports (:57-63) and `**STANDARD_OPS,` inside `_OPS` (:317-330).

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_standard_ops.py tests/test_rules.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation check** — (a) remove the QC refusal (`if not qc["pass"]`) → `test_publish_refuses_failing_qc` fails; (b) apply excludes to `doc` instead of `clone` → `test_publish_writes_scene_and_rules` fails on the live-doc assertion; (c) drop the stale-exclude name check → `test_publish_stale_exclude_refuses` fails; (d) write rules before checking `saved` → `test_publish_save_failure_does_not_write_rules` fails; (e) replace `merge_rules` with plain `derived` → `test_publish_preserves_manual_keys_on_republish` fails.

- [ ] **Step 6: Run the full pytest suite** — `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q`. Expected: green (1486 + new).

- [ ] **Step 7: Commit**

```bash
git add plugin/sentinel/ui/standard_ops.py plugin/sentinel/ui/reports_dialog.py tests/test_standard_ops.py
git commit -m "feat(standard): publicar el estandar del proyecto desde un shot que pasa el QC (v1.37)"
```

---

### Task 4: Ops B — `newshot_preview` + `newshot_create`

**Files:**
- Modify: `plugin/sentinel/ui/standard_ops.py` (append; extend `STANDARD_OPS`)
- Test: `tests/test_standard_ops.py` (append)

**Interfaces:**
- Consumes: `rules_module.discover_rules_file(folder) -> (path|None, shadowed)`, `rules_module.load_rules(path) -> (rules, warnings)`, `flows.open_version_core(path)` (`plugin/sentinel/ui/flows.py:1056`), `projectstd.valid_shot_name` / `shot_destination`.
- Produces:
  - Newshot preview response: `{"ok": True, "rules_path", "project_dir", "template", "template_exists": bool, "pattern": str, "published": {..}|null}` or `{"ok": False, "error": "bad_folder"|"no_standard"|"no_template", "searched"?: str}`.
  - Create response: `{"ok": True, "path", "opened": bool}` or `{"ok": False, "error": "bad_folder"|"no_standard"|"no_template"|"template_missing"|"bad_name"|"exists"|"copy_failed", "path"?: str}`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_standard_ops.py`):

```python
class TestNewShotOps:
    @pytest.fixture(autouse=True)
    def _forbid_dialog(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("no dialog in op path")
        monkeypatch.setattr(standard_ops.c4d.gui, "MessageDialog", _boom)
        monkeypatch.setattr(standard_ops.c4d.gui, "QuestionDialog", _boom)

    def _project(self, tmp_path, pattern="shots/{shot}/{shot}_v001.c4d",
                 with_template=True):
        rules = {"template_scene": "sentinel_standard.c4d"}
        if pattern:
            rules["shot_pattern"] = pattern
        (tmp_path / "sentinel_rules.json").write_text(json.dumps(rules))
        if with_template:
            (tmp_path / "sentinel_standard.c4d").write_bytes(b"C4Dfake")
        return tmp_path

    def test_ops_registered(self):
        assert "panel/tools/newshot_preview" in standard_ops.STANDARD_OPS
        assert "panel/tools/newshot_create" in reports_dialog._OPS

    def test_preview_no_standard_names_where_it_searched(self, tmp_path):
        out = standard_ops._op_newshot_preview({"folder": str(tmp_path)})
        assert out["ok"] is False and out["error"] == "no_standard"
        assert out["searched"] == str(tmp_path)

    def test_preview_reports_standard(self, tmp_path):
        prj = self._project(tmp_path)
        out = standard_ops._op_newshot_preview({"folder": str(prj)})
        assert out["ok"] and out["template_exists"]
        assert out["pattern"] == "shots/{shot}/{shot}_v001.c4d"
        assert out["project_dir"] == str(prj)

    def test_preview_ruleset_without_template_refuses(self, tmp_path):
        (tmp_path / "sentinel_rules.json").write_text(json.dumps({"standard_fps": 25}))
        out = standard_ops._op_newshot_preview({"folder": str(tmp_path)})
        assert out["error"] == "no_template"

    def test_create_places_by_pattern_and_opens(self, monkeypatch, tmp_path):
        prj = self._project(tmp_path)
        opened = {}
        monkeypatch.setattr(standard_ops.flows, "open_version_core",
                            lambda p: opened.setdefault("path", p) or {"ok": True, "opened": True})
        out = standard_ops._op_newshot_create({"folder": str(prj), "name": "SH020"})
        dest = prj / "shots" / "SH020" / "SH020_v001.c4d"
        assert out["ok"] and out["path"] == str(dest)
        assert dest.read_bytes() == b"C4Dfake"
        assert opened["path"] == str(dest)

    def test_create_missing_template_refuses_no_fallback(self, monkeypatch, tmp_path):
        """The asymmetric fall (spec): Reset All may fall back to the
        plugin's new.c4d; starting a whole shot from the wrong standard is
        refused, naming the missing file."""
        prj = self._project(tmp_path, with_template=False)
        called = []
        monkeypatch.setattr(standard_ops.flows, "open_version_core",
                            lambda p: called.append(p))
        out = standard_ops._op_newshot_create({"folder": str(prj), "name": "SH020"})
        assert out["ok"] is False and out["error"] == "template_missing"
        assert out["path"].endswith("sentinel_standard.c4d")
        assert called == []

    def test_create_existing_shot_never_overwrites(self, monkeypatch, tmp_path):
        prj = self._project(tmp_path)
        dest = prj / "shots" / "SH020" / "SH020_v001.c4d"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"precious")
        monkeypatch.setattr(standard_ops.flows, "open_version_core",
                            lambda p: {"ok": True})
        out = standard_ops._op_newshot_create({"folder": str(prj), "name": "SH020"})
        assert out == {"ok": False, "error": "exists", "path": str(dest)}
        assert dest.read_bytes() == b"precious"

    def test_create_bad_name_refuses(self, tmp_path):
        prj = self._project(tmp_path)
        out = standard_ops._op_newshot_create({"folder": str(prj), "name": "a/b"})
        assert out == {"ok": False, "error": "bad_name"}

    def test_create_without_pattern_places_at_project_root(self, monkeypatch, tmp_path):
        prj = self._project(tmp_path, pattern=None)
        monkeypatch.setattr(standard_ops.flows, "open_version_core",
                            lambda p: {"ok": True, "opened": True})
        out = standard_ops._op_newshot_create({"folder": str(prj), "name": "SH020"})
        assert out["ok"] and out["path"] == str(prj / "SH020_v001.c4d")

    def test_create_discovers_ruleset_from_subfolder(self, monkeypatch, tmp_path):
        """The artist may pick any folder inside the project — discovery
        walks up (same mechanism as scene rules discovery)."""
        prj = self._project(tmp_path)
        sub = prj / "shots"
        sub.mkdir(exist_ok=True)
        monkeypatch.setattr(standard_ops.flows, "open_version_core",
                            lambda p: {"ok": True, "opened": True})
        out = standard_ops._op_newshot_create({"folder": str(sub), "name": "SH021"})
        assert out["ok"]
        assert out["path"] == str(prj / "shots" / "SH021" / "SH021_v001.c4d")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_standard_ops.py -q -k NewShot`
Expected: FAIL — `_op_newshot_preview` not defined.

- [ ] **Step 3: Implement** (append to `standard_ops.py`; add `from sentinel.ui import flows` to the imports):

```python
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
```

(Replace the Task 3 `STANDARD_OPS` dict with this four-entry one at the end of the file.)

- [ ] **Step 4: Run tests**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_standard_ops.py -q`
Expected: PASS (all classes).

- [ ] **Step 5: Mutation check** — (a) make `_op_newshot_create` fall back to copying nothing but still call `open_version_core` when template missing → `test_create_missing_template_refuses_no_fallback` fails; (b) replace the `os.path.exists(dest)` refusal with overwrite → `test_create_existing_shot_never_overwrites` fails; (c) resolve template against `folder` instead of the ruleset's dir → `test_create_discovers_ruleset_from_subfolder` fails.

- [ ] **Step 6: Full pytest** — `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q`. Expected: green.

- [ ] **Step 7: Commit**

```bash
git add plugin/sentinel/ui/standard_ops.py tests/test_standard_ops.py
git commit -m "feat(standard): nuevo shot desde el estandar del proyecto, sin fallback al new.c4d (v1.37)"
```

---

### Task 5: SPA pure logic + API helpers

**Files:**
- Modify: `web/src/types.ts` (append), `web/src/lib/api.ts` (append)
- Create: `web/src/lib/panelStandard.ts`, `web/src/lib/panelStandard.test.ts`

**Interfaces:**
- Consumes: `postForm<T>` / `isMock()` from `api.ts`; server shapes from Tasks 3-4.
- Produces (used by Task 6):
  - Types `StandardPreviewResponse`, `StandardPublishResponse`, `NewShotPreviewResponse`, `NewShotCreateResponse` in `types.ts` (mirror the op shapes in Tasks 3-4 verbatim; all failure fields optional).
  - `fetchStandardPreview(folder?: string)`, `postStandardPublish(folder: string, exclude: [string, number][], pattern: string | null)`, `fetchNewShotPreview(folder: string)`, `postNewShotCreate(folder: string, name: string)` in `api.ts` — each `postForm` to its `/api/panel/tools/...` path; mock returns `{ ok: false, error: "cancelled" }`-style inert values.
  - `panelStandard.ts` exports: `STANDARD_ERROR_COPY`, `NEWSHOT_ERROR_COPY` (Record<string,string>), `qcGateLine(qc)`, `toggleExclude(list, name, index)`, `publishDisabledReason(state)`.

- [ ] **Step 1: Write the failing vitest** — create `web/src/lib/panelStandard.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  NEWSHOT_ERROR_COPY,
  STANDARD_ERROR_COPY,
  publishDisabledReason,
  qcGateLine,
  toggleExclude,
} from "./panelStandard";

describe("qcGateLine", () => {
  it("passing QC reads as the green light", () => {
    expect(qcGateLine({ passed: 12, total: 12, pass: true, failing: [] }))
      .toBe("QC 12/12 — ready to publish");
  });
  it("failing QC names the blockers", () => {
    expect(qcGateLine({ passed: 10, total: 12, pass: false, failing: ["Default Names", "Output Paths"] }))
      .toBe("QC 10/12 — fix before publishing: Default Names, Output Paths");
  });
});

describe("toggleExclude", () => {
  it("adds when absent, removes when present, never mutates", () => {
    const a = toggleExclude([], "petals", 1);
    expect(a).toEqual([["petals", 1]]);
    const b = toggleExclude(a, "petals", 1);
    expect(b).toEqual([]);
    expect(a).toEqual([["petals", 1]]);
  });
  it("same name different index are distinct entries", () => {
    const a = toggleExclude([["null", 0]], "null", 2);
    expect(a).toEqual([["null", 0], ["null", 2]]);
  });
});

describe("publishDisabledReason", () => {
  it("needs a folder first", () => {
    expect(publishDisabledReason({ folder: "", qcPass: true })).toBe("Choose the project folder first.");
  });
  it("refuses on failing QC", () => {
    expect(publishDisabledReason({ folder: "/prj", qcPass: false }))
      .toBe("The scene must pass the QC before publishing.");
  });
  it("null when publishable", () => {
    expect(publishDisabledReason({ folder: "/prj", qcPass: true })).toBeNull();
  });
});

describe("error copy", () => {
  it("every server code the ops can return has copy", () => {
    for (const code of ["no_document", "unsaved", "bad_folder", "qc_failing",
      "scene_changed", "rules_unreadable", "save_failed", "write_failed"]) {
      expect(STANDARD_ERROR_COPY[code]).toBeTruthy();
    }
    for (const code of ["bad_folder", "no_standard", "no_template",
      "template_missing", "bad_name", "exists", "copy_failed"]) {
      expect(NEWSHOT_ERROR_COPY[code]).toBeTruthy();
    }
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run src/lib/panelStandard.test.ts`. Expected: FAIL (module not found).

- [ ] **Step 3: Implement** — create `web/src/lib/panelStandard.ts`:

```ts
/** Pure client logic for the Project standard sub-views (v1.37). */

export interface StandardQc {
  passed: number;
  total: number;
  pass: boolean;
  failing: string[];
}

export type ExcludeEntry = [string, number];

export function qcGateLine(qc: StandardQc): string {
  if (qc.pass) return `QC ${qc.passed}/${qc.total} — ready to publish`;
  return `QC ${qc.passed}/${qc.total} — fix before publishing: ${qc.failing.join(", ")}`;
}

export function toggleExclude(list: ExcludeEntry[], name: string, index: number): ExcludeEntry[] {
  const has = list.some(([n, i]) => n === name && i === index);
  if (has) return list.filter(([n, i]) => !(n === name && i === index));
  return [...list, [name, index]];
}

export function publishDisabledReason(state: { folder: string; qcPass: boolean }): string | null {
  if (!state.folder) return "Choose the project folder first.";
  if (!state.qcPass) return "The scene must pass the QC before publishing.";
  return null;
}

export const STANDARD_ERROR_COPY: Record<string, string> = {
  no_document: "No active document.",
  unsaved: "Save the scene first — the standard is published from a saved shot.",
  bad_folder: "That folder does not exist.",
  qc_failing: "The scene must pass the QC before publishing.",
  scene_changed: "The scene changed since the preview — review and publish again.",
  rules_unreadable: "The existing sentinel_rules.json cannot be read. Fix or remove it first.",
  save_failed: "Could not write the standard scene file.",
  write_failed: "Could not write sentinel_rules.json.",
};

export const NEWSHOT_ERROR_COPY: Record<string, string> = {
  bad_folder: "That folder does not exist.",
  no_standard: "No project standard found here (no sentinel_rules.json in this folder or its parents).",
  no_template: "This project's ruleset does not declare a standard scene.",
  template_missing: "The standard scene file is missing — ask the supervisor to republish.",
  bad_name: "Shot names cannot be empty or contain slashes.",
  exists: "A shot with that name already exists. Nothing was overwritten.",
  copy_failed: "Could not copy the standard scene to the destination.",
};
```

Then append types to `web/src/types.ts` and the four helpers to `web/src/lib/api.ts` following the `fetchMatwirePreview`/`postMatwireCreate` idiom at `api.ts:1362/1411` (POST via `postForm`, `isMock()` short-circuit).

- [ ] **Step 4: Run vitest** — `cd web && npx vitest run`. Expected: PASS (224 + new).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/panelStandard.ts web/src/lib/panelStandard.test.ts web/src/lib/api.ts web/src/types.ts
git commit -m "feat(spa): logica pura y helpers de API del estandar del proyecto (v1.37)"
```

---

### Task 6: Sub-views + Tools wiring + build

**Files:**
- Create: `web/src/components/panel/StandardSubview.tsx`, `web/src/components/panel/NewShotSubview.tsx`
- Modify: `web/src/components/panel/ToolsSection.tsx`
- Build: `cd web && npm run build` (commits `plugin/web/`)

**Interfaces:**
- Consumes: Task 5 helpers/types, `postHubPickPath(true, title)` (`api.ts:563`), `restoreFocus()` (`lib/focus.ts`), the shared `Button`/`SectionGroup` components used by `MatwireSubview.tsx` (mirror its imports).
- Produces: `StandardSubview({ onBack })`, `NewShotSubview({ onBack })`; `ToolsSection` view union becomes `"main" | "rename" | "matwire" | "standard" | "newshot"`.

- [ ] **Step 1: Wire ToolsSection.** Extend the sub-router (`ToolsSection.tsx:30-39`):

```tsx
const [view, setView] = useState<"main" | "rename" | "matwire" | "standard" | "newshot">("main");
if (view !== "main") {
  const back = () => {
    restoreFocus();
    setView("main");
  };
  if (view === "rename") return <RenameSubview onBack={back} />;
  if (view === "matwire") return <MatwireSubview onBack={back} />;
  if (view === "standard") return <StandardSubview onBack={back} />;
  return <NewShotSubview onBack={back} />;
}
```

And render a new group in the main view, after the existing sub-view opener buttons (mirror the exact markup around `ToolsSection.tsx:96-100`):

```tsx
{/* v1.37 — the project standard. Publish is the supervisor's once-per-
    project gesture; New shot is the artist's daily one. They live together:
    both are the same standard seen from its two sides. */}
<Button variant="secondary" onClick={() => setView("standard")}>
  Publish standard →
</Button>
<Button variant="secondary" onClick={() => setView("newshot")}>
  New shot →
</Button>
```

Group title: **"Project"** (a `SectionGroup` like the neighbors; follow how the "Authoring" group wraps the Rename/Matwire buttons in the current file — put the two buttons in their own `SectionGroup title="Project"`).

- [ ] **Step 2: Build `StandardSubview.tsx`.** Model directly on `MatwireSubview.tsx` (same fetch/seq/toast idioms). Structure:
  - Header row: `← Tools` back button (calls `onBack`).
  - Folder field + `Browse` (`postHubPickPath(true, "Choose the project folder")`); on pick, refetch preview with the folder.
  - On mount and after folder change: `fetchStandardPreview(folder)`; guard stale responses with a monotonic `seqRef` (Matwire idiom).
  - **QC gate banner**: `qcGateLine(preview.qc)` — warn tint when failing.
  - **"Will travel"** block: fps/start-frame line, presets line, pattern as an editable text input (seeded from `preview.pattern`, the supervisor corrects it here), and the top-level objects list with a checkbox per row (checked = travels; unchecking adds to `exclude` via `toggleExclude`).
  - **"Won't travel"** block: static lines from `preview.wont_travel`.
  - **Republish diff** block: rendered only when `preview.existing_rules`, listing `preview.diff` lines under a heading "Republish — what changes"; when `diff` is empty but `existing_rules` is true show "Republish — replaces the existing standard".
  - **Publish** primary button: disabled with inline reason from `publishDisabledReason({ folder, qcPass })`; on click `postStandardPublish(folder, exclude, patternText || null)`; success → toast `Standard published — <n> branches excluded` and refetch preview; failure → toast warn with `STANDARD_ERROR_COPY[error]`.
- [ ] **Step 3: Build `NewShotSubview.tsx`.** Structure:
  - `← Tools` back.
  - Folder field + Browse (`postHubPickPath(true, "Choose a folder inside the project")`); on pick, `fetchNewShotPreview(folder)`.
  - Standard summary when ok: project dir, pattern, `Published by <by> · <at>` when `published` present; template-missing state shows `NEWSHOT_ERROR_COPY.template_missing` inline.
  - Error states (`no_standard` etc.) as inline text (normal editing states, not toasts — Batch Rename lesson).
  - Shot name text input; **Create shot** primary button disabled until preview ok, template exists, and name non-empty; on click `postNewShotCreate(folder, name)`; success → toast `Shot created — <basename>` and `onBack()` (the scene just opened; the panel now shows the new doc); failure → toast warn with `NEWSHOT_ERROR_COPY[error]`.
- [ ] **Step 4: Verify types + tests + lint** — `cd web && npx tsc -b && npx vitest run && npx oxlint`. Expected: clean.
- [ ] **Step 5: Build and commit the bundle** — `cd web && npm run build`; verify `git status` shows `plugin/web/` changes.
- [ ] **Step 6: Commit**

```bash
git add web/src plugin/web
git commit -m "feat(spa): subvistas Publish standard y New shot en Tools → Project (v1.37)"
```

---

### Task 7: Version bump, docs, full verification

**Files:**
- Modify: version constants (grep `1.36.11` across `plugin/` — the version string lives in the `.pyp` header/plugin registration and `CLAUDE.md`), `CLAUDE.md`, `ROADMAP.md`

- [ ] **Step 1: Bump to v1.37.0** everywhere the current version string appears (`grep -rn "1\.36\.11" plugin/ CLAUDE.md README.md`).
- [ ] **Step 2: Update `CLAUDE.md`**: new "What Works" entry + Version History Summary entry for v1.37.0 (two gestures, the asymmetric fallback, derived-vs-JSON key split, merge-not-clobber on republish, QC gate, `sentinel_standard.c4d`, entry point Tools → Project). Update `ROADMAP.md` (mark the v1.37 phase in progress/done; QC #13 stays listed as its own future spec).
- [ ] **Step 3: Full suites** — `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q` and `cd web && npx vitest run`. Record the new counts in CLAUDE.md (expect pytest ≈1486+35, vitest ≈224+8).
- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: v1.37.0 — el estandar del proyecto: publicar + nuevo shot"
```

---

## Live verification (controller, in C4D — NOT a subagent task)

Run after all tasks, before merge. `sync.sh` + restart C4D first. Remember the **save-and-reload trap** (Global Constraints) for every ruleset-discovery assertion.

1. **Publish happy path**: open a QC-passing scene (the clean fixture or a real conforming shot), Tools → Project → Publish standard →, pick a scratch project folder, uncheck one top-level branch, publish. Verify on disk: `sentinel_standard.c4d` without that branch (open it), `sentinel_rules.json` with fps/start/presets/pattern/`published` and `template_scene: "sentinel_standard.c4d"`. Verify the LIVE scene still has the branch.
2. **QC gate**: open the violating fixture → the sub-view names the failing checks and Publish is disabled; force the op via HTTP → `qc_failing`.
3. **Republish**: change the scene fps, publish again to the same folder → diff block names the fps change and the scene replacement; manual key added by hand to the JSON beforehand survives.
4. **New shot happy path**: Tools → Project → New shot →, pick the project folder (and separately a SUBfolder — discovery must walk up), name `SH020` → file appears at the pattern path, opens in C4D, QC runs 12/12 (or the clean baseline), no `_history`/`_notes`/`_baseline` sidecars next to it, and the render output paths resolve to the new name via tokens.
5. **Refusals**: rename `sentinel_standard.c4d` away → New shot refuses naming the file, and Reset All (same ruleset) also refuses with `project_template_missing` (the asymmetry's other half stays intact); existing shot name → refused, file untouched.
6. **Cycle**: publish → new shot → QC on the new shot passes (criterion of done: the full circle).

## Self-review notes (spec ↔ plan)

- Spec preview mockup lists `proxies` and `luces` as dedicated lines; this plan folds them into the hierarchy rows (a proxy/light travels inside its top-level branch, which is the curation unit). Declared deviation — a dedicated informational asset listing would need the Hub scan pipeline and adds no curation power. Revisit if live use asks for it.
- Spec "claves derivadas + defaults para el resto" implemented as "derived keys only, absent keys fall back to defaults" — reasoned in Global Constraints.
- Provenance lives in the `published` ruleset key (validated, replace-semantics); republish overwrites it, which matches "un supervisor por proyecto y puede no ser el mismo".
- QC #13, ruleset hand-editing UI, standard versioning, inherited standards/library: out of scope per spec.
