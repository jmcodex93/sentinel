# -*- coding: utf-8 -*-
"""C4D-aware rules resolution — the single home for `active_rules_for_doc`.

Companion to the pure `rules.py`: this module composes the project ruleset
(`rules.get_active_rules`, pure) with the machine-level settings
(`GlobalSettings`, which reads C4D prefs) for a given document. It was
previously copy-pasted into fixes.py, ui/flows.py, ui/dialogs.py,
ui/frame_tag.py and (partially) the check modules; those all import from here
now. Kept out of `rules.py` so that module stays c4d-free and unit-testable.
"""

from sentinel.common.settings import GlobalSettings
from sentinel.rules import get_active_rules


def doc_path_for_rules(doc):
    """Document folder path for rules discovery, or '' when unavailable."""
    if doc is None:
        return ""
    try:
        return doc.GetDocumentPath() or ""
    except Exception:
        return ""


def machine_rule_settings():
    """Machine-level rule overrides (currently just the studio standard FPS)."""
    try:
        return {"standard_fps": GlobalSettings.get_standard_fps()}
    except Exception:
        return {}


def active_rules_for_doc(doc):
    """Resolve the effective ruleset for `doc`: project rules > machine > defaults."""
    return get_active_rules(doc_path_for_rules(doc), machine_rule_settings())
