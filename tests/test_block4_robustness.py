# -*- coding: utf-8 -*-
"""Block-4 robustness: signature-based rules_context dispatch, registry
resolvability, malformed-TODO tolerance."""
import json

import pytest


# -- score._call: signature-based, no TypeError-text grep --------------------

class TestCallSignatureDispatch:
    def test_fn_accepting_rules_context_gets_it(self):
        from sentinel.qc import score
        captured = {}

        def fn(doc, rules_context=None):
            captured["rc"] = rules_context
            return "ok"

        assert score._call(fn, "doc", {}, rules_context="RC") == "ok"
        assert captured["rc"] == "RC"

    def test_fn_without_rules_context_skips_it(self):
        from sentinel.qc import score

        def fn(doc):
            return "plain"

        assert score._call(fn, "doc", {}, rules_context="RC") == "plain"

    def test_internal_typeerror_propagates(self):
        # The bug this fixes: an internal TypeError whose message contains
        # 'rules_context' used to be swallowed and retried without it.
        from sentinel.qc import score

        def fn(doc, rules_context=None):
            raise TypeError("rules_context is not a dict — internal bug")

        with pytest.raises(TypeError):
            score._call(fn, "doc", {}, rules_context="RC")


# -- registry resolvability ---------------------------------------------------

class TestRegistryResolvable:
    def test_full_registry_resolves(self, sentinel_module):
        from sentinel.qc.registry import validate_registry_resolvable
        failures = validate_registry_resolvable()
        assert failures == [], f"Unresolved registry fns: {failures}"


# -- notes.load_notes drops malformed TODOs -----------------------------------

class TestNotesTodoTolerance:
    def _write(self, tmp_path, todos):
        path = tmp_path / "shot_notes.json"
        path.write_text(json.dumps({"todos": todos}), encoding="utf-8")
        return str(path)

    def test_non_dict_todos_dropped(self, tmp_path):
        from sentinel.notes import load_notes
        path = self._write(tmp_path, [
            {"text": "fix lights", "done": False},
            "bare string",
            42,
            None,
            ["nested", "list"],
        ])
        data = load_notes(path)
        assert len(data["todos"]) == 1
        assert data["todos"][0]["text"] == "fix lights"

    def test_valid_todos_pass_through(self, tmp_path):
        from sentinel.notes import load_notes
        path = self._write(tmp_path, [{"text": "a", "done": True}])
        data = load_notes(path)
        assert data["todos"] == [{"text": "a", "done": True}]
