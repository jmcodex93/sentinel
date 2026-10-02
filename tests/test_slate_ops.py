# -*- coding: utf-8 -*-
"""panel/slate/* — the visual slate editor's server side."""
import json

import pytest


class _Doc:
    def __init__(self, scene_dir):
        self._dir = scene_dir

    def GetDocumentPath(self):
        return self._dir

    def GetDocumentName(self):
        return "shot_v001.c4d"


class _Ctx:
    def __init__(self, rules_path=None, params=None):
        self.rules_path = rules_path
        self.params = params or {"slate": False}
        self.field_sources = {}
        self.warnings = []


@pytest.fixture
def ops(sentinel_module, monkeypatch, tmp_path):
    import c4d
    from sentinel.ui import slate_ops

    def _forbid(*args, **kwargs):
        raise AssertionError("no dialog from an op path")

    monkeypatch.setattr(c4d.gui, "MessageDialog", _forbid)
    project = tmp_path / "ACME"
    scene = project / "shots" / "sh010" / "scenes"
    scene.mkdir(parents=True)
    state = {"ctx": _Ctx(), "doc": _Doc(str(scene))}
    monkeypatch.setattr(slate_ops, "_doc", lambda: state["doc"])
    monkeypatch.setattr(slate_ops, "_context", lambda doc: state["ctx"])
    state["ops"] = slate_ops.SLATE_OPS
    state["project"] = project
    state["scene"] = scene
    return state


def save(ops, **payload):
    return ops["ops"]["panel/slate/save"](payload)


def test_save_without_ruleset_asks_for_a_folder_within_discovery(ops, tmp_path):
    response = save(ops, style={"position": "overlay"}, enabled=True)
    assert response["error"] == "need_folder" and len(response["searched"]) == 4
    far = tmp_path
    response = save(ops, style={}, enabled=True, folder=str(far))
    assert response["error"] == "folder_out_of_reach"


def test_save_confirms_naming_file_and_changes_then_writes_only_the_difference(ops):
    project = ops["project"]
    payload = dict(style={"position": "overlay", "slots": {"center": ["ACME"]}},
                   enabled=True, folder=str(project))
    first = save(ops, **payload)
    assert first["error"] == "confirm_required"
    assert first["path"] == str(project / "sentinel_rules.json")
    assert first["confirm_label"].startswith("Save the slate to …/ACME/sentinel_rules.json")
    assert "\n• position: below → overlay" in first["confirm_label"]
    assert first["confirm_verb"] == "Save for the project"
    assert first["changes"] == ["slate: not set → on", "position: below → overlay",
                                "center: (empty) → ACME"]
    assert not (project / "sentinel_rules.json").exists()        # nothing before confirm
    done = save(ops, confirm=True, **payload)
    assert done["ok"] is True
    written = json.loads((project / "sentinel_rules.json").read_text())
    assert written == {"slate_style": {"position": "overlay", "slots": {"center": ["ACME"]}},
                       "slate": True}
    assert not (project / "sentinel_rules.json.tmp").exists()


def test_save_keeps_manual_keys_and_targets_the_active_ruleset(ops, tmp_path):
    rules = ops["project"] / "sentinel_rules.json"
    rules.write_text(json.dumps({"standard_fps": 24, "slate": True,
                                 "slate_style": {"size": 1.5}}))
    ops["ctx"] = _Ctx(rules_path=str(rules))
    response = save(ops, style={}, enabled=True, folder=str(tmp_path), confirm=True)
    assert response["ok"] is True and response["path"] == str(rules)   # client folder ignored
    assert response["changes"] == ["size: 1.5 → 1.0"]
    assert json.loads(rules.read_text()) == {"standard_fps": 24, "slate": True}


def test_unchanged_style_writes_nothing(ops):
    rules = ops["project"] / "sentinel_rules.json"
    rules.write_text(json.dumps({"slate": True}))
    ops["ctx"] = _Ctx(rules_path=str(rules))
    before = rules.stat().st_mtime_ns
    assert save(ops, style={}, enabled=True)["unchanged"] is True
    assert rules.stat().st_mtime_ns == before


def test_unreadable_ruleset_is_never_overwritten(ops):
    rules = ops["project"] / "sentinel_rules.json"
    rules.write_text("{ not json")
    ops["ctx"] = _Ctx(rules_path=str(rules))
    assert save(ops, style={}, enabled=True, confirm=True)["error"] == "rules_unreadable"
    assert rules.read_text() == "{ not json"


def test_bad_style_and_unsaved_scene_are_refused(ops):
    assert save(ops, style={"slots": {"left": ["{shoot}"]}}, enabled=True)["error"] == "bad_style"
    assert save(ops, style={}, enabled="yes")["error"] == "bad_style"
    ops["doc"] = _Doc("")
    assert save(ops, style={}, enabled=True)["error"] == "unsaved"


def test_state_reports_the_effective_slate(ops):
    from sentinel import slate
    ops["ctx"] = _Ctx(params={"slate": True, "slate_style": slate.default_style()})
    state = ops["ops"]["panel/slate/state"]({})
    assert state["ok"] and state["enabled"] is True and state["rules_path"] == ""
    assert state["style"] == slate.default_style() and "post" in state["tokens"]


def test_preview_renders_the_unsaved_style_as_a_data_uri(ops, monkeypatch, tmp_path):
    from sentinel import snapshot_c4d
    from sentinel.ui import flows, slate_ops
    seen = {}
    monkeypatch.setattr(slate_ops.GlobalSettings, "load_artist_name", lambda: "Artist")
    monkeypatch.setattr(snapshot_c4d, "ocio_available", lambda: True)
    monkeypatch.setattr(snapshot_c4d, "resolve_slate_font", lambda: ("font", "Inter-Regular"))
    monkeypatch.setattr(snapshot_c4d, "color_converter", lambda doc: "conv")
    monkeypatch.setattr(flows, "build_slate_data", lambda d, a, project="": {"shot": "sh010"})
    monkeypatch.setattr(flows, "get_effective_snapshot_dir", lambda: (str(tmp_path), "auto"))
    monkeypatch.setattr(flows, "_find_latest_exr", lambda d: (str(tmp_path / "a.exr"), None))

    def png(slate, font, style, exr_path=None, converter=None, max_width=None, enabled=True):
        seen.update(style=style, exr=exr_path, converter=converter, max_width=max_width, enabled=enabled)
        return b"\x89PNG", {"source": "snapshot", "notice": "RenderView post applied: RGB curve",
                             "post": "RGB curve", "strip_px": 39, "text_px": 20, "at_min": False}

    monkeypatch.setattr(snapshot_c4d, "preview_png", png)
    response = ops["ops"]["panel/slate/preview"]({"style": {"position": "overlay"}})
    assert response["ok"] and response["image"] == "data:image/png;base64,iVBORw=="
    assert seen["style"]["position"] == "overlay" and seen["style"]["badge"] is True
    assert seen["converter"] == "conv" and response["notice"].endswith("RGB curve")
    assert response["post"] == "RGB curve" and response["strip_px"] == 39 and seen["enabled"] is True
    assert seen["max_width"] == 1600     # sharp when the panel is made large
    opened = {}
    monkeypatch.setattr("sentinel.common.helpers.open_in_explorer", lambda p: opened.setdefault("p", p))
    import tempfile
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    full = ops["ops"]["panel/slate/preview"]({"style": {}, "enabled": False, "open": True})
    assert full["ok"] and "image" not in full and opened["p"] == str(tmp_path / "sentinel_slate_preview.png")
    assert seen["max_width"] is None and seen["enabled"] is False
    bad = ops["ops"]["panel/slate/preview"]({"style": {"size": 9}})
    assert bad["error"] == "bad_style" and "size" in bad["detail"]
    monkeypatch.setattr(snapshot_c4d, "ocio_available", lambda: False)
    assert ops["ops"]["panel/slate/preview"]({"style": {}})["error"] == "needs_2025_2"
