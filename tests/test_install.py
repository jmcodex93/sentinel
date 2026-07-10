# -*- coding: utf-8 -*-
"""Pure-function tests for the multi-version installer (install.py).

None of these run the CLI or touch the real machine — every helper takes an
explicit root path so we build fake macOS / Windows-style trees under tmp_path.
"""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_install():
    spec = importlib.util.spec_from_file_location(
        "sentinel_install_under_test", str(ROOT / "install.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


install = _load_install()


# ── version-label parsing ────────────────────────────────────────────────────
@pytest.mark.parametrize("dir_name,expected", [
    ("Maxon Cinema 4D 2026_9D810372", "2026"),
    ("Cinema 4D 2024B_E35286C3", "2024B"),
    ("Maxon Cinema 4D 2024_ABC123", "2024"),
    ("Maxon Cinema 4D 2026_9D810372_x", "2026"),
    ("Adobe After Effects 2025_DFE767FC", None),
    ("MxContentService", None),
    ("", None),
    (None, None),
])
def test_parse_version_label(dir_name, expected):
    assert install.parse_version_label(dir_name) == expected


# ── discovery over a fake macOS tree ─────────────────────────────────────────
def _make_mac_tree(root):
    for name in ("Maxon Cinema 4D 2026_9D810372",
                 "Cinema 4D 2024B_E35286C3",
                 "Adobe After Effects 2025_DFE767FC",
                 "MxContentService"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    # Only 2026 has a plugins folder already.
    os.makedirs(os.path.join(root, "Maxon Cinema 4D 2026_9D810372", "plugins"))


def test_discover_mac_layout(tmp_path):
    root = tmp_path / "Maxon"
    _make_mac_tree(str(root))
    installs = install.discover_c4d_installs(str(root))
    labels = [i["label"] for i in installs]
    assert labels == ["2026", "2024B"]  # sorted desc, non-C4D dirs excluded
    by_label = {i["label"]: i for i in installs}
    assert by_label["2026"]["plugins_exists"] is True
    assert by_label["2024B"]["plugins_exists"] is False
    assert by_label["2026"]["plugins_dir"].endswith(
        os.path.join("Maxon Cinema 4D 2026_9D810372", "plugins"))


def test_discover_windows_layout(tmp_path):
    # Windows APPDATA/Maxon looks the same structurally.
    root = tmp_path / "AppData" / "Roaming" / "Maxon"
    os.makedirs(str(root))
    os.makedirs(str(root / "Maxon Cinema 4D 2024_11112222" / "plugins"))
    os.makedirs(str(root / "Maxon Cinema 4D 2026_33334444"))
    installs = install.discover_c4d_installs(str(root))
    assert [i["label"] for i in installs] == ["2026", "2024"]


def test_discover_missing_root_is_empty(tmp_path):
    assert install.discover_c4d_installs(str(tmp_path / "nope")) == []


def test_discover_all_dedups(tmp_path):
    root = tmp_path / "Maxon"
    _make_mac_tree(str(root))
    combined = install.discover_all_installs([str(root), str(root)])
    assert [i["label"] for i in combined] == ["2026", "2024B"]


# ── payload verification ─────────────────────────────────────────────────────
def _make_complete_payload(dest):
    os.makedirs(os.path.join(dest, "sentinel", "ui"))
    os.makedirs(os.path.join(dest, "res"))
    os.makedirs(os.path.join(dest, "abc_retime"))
    Path(os.path.join(dest, "sentinel_panel.pyp")).write_text("x")
    Path(os.path.join(dest, "sentinel", "__init__.py")).write_text("x")
    Path(os.path.join(dest, "sentinel", "aovs.py")).write_text("x")
    Path(os.path.join(dest, "sentinel", "postrender.py")).write_text("x")
    Path(os.path.join(dest, "sentinel", "ui", "panel.py")).write_text("x")
    Path(os.path.join(dest, "res", "c4d_symbols.h")).write_text("x")
    Path(os.path.join(dest, "exr_converter_external.py")).write_text("x")


def test_verify_payload_complete(tmp_path):
    dest = str(tmp_path / "Sentinel")
    _make_complete_payload(dest)
    ok, missing = install.verify_payload(dest)
    assert ok is True
    assert missing == []


def test_verify_payload_missing_res(tmp_path):
    dest = str(tmp_path / "Sentinel")
    _make_complete_payload(dest)
    os.remove(os.path.join(dest, "res", "c4d_symbols.h"))
    ok, missing = install.verify_payload(dest)
    assert ok is False
    assert os.path.join("res", "c4d_symbols.h") in missing


def test_verify_payload_empty_dest(tmp_path):
    ok, missing = install.verify_payload(str(tmp_path / "empty"))
    assert ok is False
    assert len(missing) == len(install.CRITICAL_PAYLOAD_PATHS)


# ── legacy folder warning ────────────────────────────────────────────────────
def test_legacy_folder_warning(tmp_path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    assert install.legacy_folder_warning(str(plugins)) is None
    (plugins / "YS_Guardian").mkdir()
    warn = install.legacy_folder_warning(str(plugins))
    assert warn is not None and "YS_Guardian" in warn


# ── mirror copy (delete-orphans) ─────────────────────────────────────────────
def test_mirror_copy_prunes_orphans_and_skips_pycache(tmp_path):
    src = tmp_path / "plugin"
    (src / "sentinel").mkdir(parents=True)
    (src / "sentinel_panel.pyp").write_text("panel")
    (src / "sentinel" / "aovs.py").write_text("aovs")
    (src / "sentinel" / "__pycache__").mkdir()
    (src / "sentinel" / "__pycache__" / "aovs.pyc").write_text("junk")

    dest = tmp_path / "out" / "Sentinel"
    # Pre-existing orphan that must be pruned.
    dest.mkdir(parents=True)
    (dest / "stale_old_module.py").write_text("orphan")

    install.mirror_copy(str(src), str(dest))

    assert (dest / "sentinel_panel.pyp").read_text() == "panel"
    assert (dest / "sentinel" / "aovs.py").read_text() == "aovs"
    assert not (dest / "stale_old_module.py").exists()      # orphan pruned
    assert not (dest / "sentinel" / "__pycache__").exists()  # cache skipped


def test_install_to_reports_verification(tmp_path):
    src = tmp_path / "plugin"
    _make_complete_payload(str(src))
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    res = install.install_to(str(plugins), str(src))
    assert res["ok"] is True
    assert res["missing"] == []
    assert os.path.isdir(os.path.join(res["dest"]))
