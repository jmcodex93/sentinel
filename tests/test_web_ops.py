# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/web_ops.py.

Scope for now: the ``confirm_required`` contract gate in
``_op_palette_run`` — the two recommended gate tests from Phase 4 Task 4
(docs/superpowers/plans/2026-07-19-ui-phase4-forms.md): a
``requires_confirm`` action is rejected without ``confirm: true``, and
``confirm: true`` actually unlocks it past the gate.

Needs the fake-c4d harness (``sentinel_module`` fixture, tests/conftest.py)
because ``web_ops.py`` does ``import c4d`` at module scope (unlike
``webbridge.py``, whose own palette tests in test_webbridge.py need no such
harness) — so ``sentinel.ui.web_ops`` is imported lazily inside each test,
after the fixture has installed the fake ``c4d``/``c4d.documents``/etc.
modules into ``sys.modules`` (see test_qc_action_registry.py for the same
pattern with other c4d-touching modules).
"""


class TestPaletteRunConfirmGate:
    def test_requires_confirm_action_rejected_without_confirm_flag(self, sentinel_module):
        from sentinel.ui import web_ops

        # fix_materials is one of the two DECISIÓN-classified destructive
        # Quick Fix actions (delete unused materials) — requires_confirm is
        # True for it in webbridge.PALETTE_ACTIONS.
        response = web_ops._op_palette_run({"id": "fix_materials"})

        assert response == {"ok": False, "error": "confirm_required"}

    def test_confirm_true_passes_the_gate_and_reaches_real_dispatch(self, sentinel_module):
        from sentinel.ui import web_ops

        response = web_ops._op_palette_run({"id": "fix_materials", "confirm": True})

        # The fake harness's documents.GetActiveDocument() always returns
        # None, so the fix itself can't run end to end here — but the
        # response must NOT be the confirm_required rejection: it has to
        # reach the next real check ("No active document"), proving
        # confirm=True actually unlocked dispatch instead of being ignored.
        assert response != {"ok": False, "error": "confirm_required"}
        assert response == {"ok": False, "error": "No active document"}

    def test_non_confirm_action_never_gated(self, sentinel_module):
        """Sanity check the gate is confirm-specific: an action with no
        requires_confirm flag (rescan_qc) reaches real dispatch with no
        confirm payload at all."""
        from sentinel.ui import web_ops

        response = web_ops._op_palette_run({"id": "rescan_qc"})

        assert response != {"ok": False, "error": "confirm_required"}
        assert response == {"ok": False, "error": "No active document"}


class TestSettingsRenderNotify:
    """``render_notify`` across ``form/settings/state`` / ``form/settings/submit``
    (v1.30 Task 5). Same lazy-import + fake-c4d harness as the palette gate
    tests above; ``GlobalSettings`` is monkeypatched so no real
    ``sentinel_settings.json`` is read or written."""

    def _patch_settings(self, monkeypatch, store, set_calls):
        from sentinel.common.settings import GlobalSettings
        import sentinel.ui.flows as flows

        monkeypatch.setattr(
            GlobalSettings, "get",
            staticmethod(lambda key, default='': store.get(key, default)))
        monkeypatch.setattr(
            GlobalSettings, "set",
            staticmethod(lambda key, value: set_calls.append((key, value)) or True))
        # Keep the snapshot-dir auto-detect out of the picture (pure default
        # locks) — the fake harness has no RenderView cfg to parse anyway.
        monkeypatch.setattr(flows, "detect_rv_snapshot_dir", lambda: None)

    def test_state_includes_render_notify_default_true(self, sentinel_module, monkeypatch):
        from sentinel.ui import web_ops

        self._patch_settings(monkeypatch, store={}, set_calls=[])
        state = web_ops._op_form_settings_state({})

        assert state["render_notify"] is True

    def test_state_reflects_persisted_render_notify_off(self, sentinel_module, monkeypatch):
        from sentinel.ui import web_ops

        self._patch_settings(monkeypatch, store={"render_notify": 0}, set_calls=[])
        state = web_ops._op_form_settings_state({})

        assert state["render_notify"] is False

    def test_submit_render_notify_false_persists_zero(self, sentinel_module, monkeypatch):
        from sentinel.ui import web_ops

        set_calls = []
        self._patch_settings(monkeypatch, store={}, set_calls=set_calls)
        response = web_ops._op_form_settings_submit({"render_notify": False})

        assert response == {"ok": True}
        assert ("render_notify", 0) in set_calls
