"""Guard against real-c4d API namespace mistakes the permissive fake-c4d hides.

The conftest fakes `c4d` as an attribute-permissive module, so a call to a
non-existent name (e.g. `c4d.StatusSetText` after it moved to `c4d.gui` in
C4D 2025+) passes every runtime test yet raises AttributeError live. These
source-level asserts catch that class of bug without needing Cinema 4D.
"""

import pathlib
import re

PLUGIN = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "sentinel"

# name -> the correct C4D 2025+ namespace it must be called through.
# Status-bar helpers moved from top-level `c4d` to `c4d.gui` in C4D 2025.
GUI_ONLY_CALLS = ("StatusSetText", "StatusSetBar", "StatusClear", "StatusSetSpin")


def _py_sources():
    return [p for p in PLUGIN.rglob("*.py") if "__pycache__" not in p.parts]


def test_status_bar_calls_use_gui_namespace():
    offenders = []
    for path in _py_sources():
        src = path.read_text(encoding="utf-8")
        for name in GUI_ONLY_CALLS:
            # bare `c4d.StatusSetText(` not preceded by `.gui` — i.e. `c4d.Name(`
            # but NOT `c4d.gui.Name(`.
            for m in re.finditer(rf"(?<![.\w])c4d\.{name}\s*\(", src):
                start = m.start()
                if src[max(0, start - 4):start].endswith("gui."):
                    continue
                offenders.append(f"{path.relative_to(PLUGIN)}: c4d.{name}( -> use c4d.gui.{name}(")
    assert not offenders, "C4D 2025+ moved these to c4d.gui:\n" + "\n".join(offenders)
