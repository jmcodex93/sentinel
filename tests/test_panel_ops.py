# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/panel_ops.py — the Panel SPA op layer
(Fase 6.0 Task 1: state stamp + overview + open_form).

Uses the fake-c4d harness (``sentinel_module`` fixture, tests/conftest.py):
``panel_ops.py`` does ``import c4d`` at module scope, same as ``hub_ops.py``/
``web_ops.py``, so it is imported lazily inside each test.
``documents.GetActiveDocument()`` is None in the harness, so these tests pin
the no-document contract + the op-table shape; the two payload-shaping
helpers that ARE pure (``_validate_form_page`` here,
``webbridge.top_qc_checks``) are tested directly without the harness.
"""


class TestPanelOpsTable:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import panel_ops
        for op in ("panel/state_stamp", "panel/overview", "panel/open_form",
                   "panel/qc", "panel/qc/select", "panel/qc/accept",
                   "panel/qc/fix_all"):
            assert op in panel_ops.PANEL_OPS

    def test_state_stamp_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops.PANEL_OPS["panel/state_stamp"]({}) == {"error": "no_document"}

    def test_overview_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops.PANEL_OPS["panel/overview"]({}) == {"error": "no_document"}

    def test_open_form_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        response = panel_ops.PANEL_OPS["panel/open_form"]({"page": "form/save_version"})
        assert response == {"ok": False, "error": "no_document"}

    def test_panel_qc_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops.PANEL_OPS["panel/qc"]({}) == {"error": "no_document"}

    def test_panel_qc_select_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        response = panel_ops.PANEL_OPS["panel/qc/select"]({"check_id": "lights"})
        assert response == {"ok": False, "error": "no_document"}

    def test_panel_qc_accept_without_document(self, sentinel_module):
        # Validation runs BEFORE the doc guard (per the plan's own ordering),
        # so a well-formed payload reaches the no_document branch.
        from sentinel.ui import panel_ops
        response = panel_ops.PANEL_OPS["panel/qc/accept"](
            {"check_id": "lights", "author": "Javier", "reason": "known issue"})
        assert response == {"ok": False, "error": "no_document"}

    def test_panel_qc_fix_all_without_document(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops.PANEL_OPS["panel/qc/fix_all"]({}) == {"ok": False, "error": "no_document"}


class TestValidateAcceptPayload:
    """Pure — reachable without the fake-c4d harness or a document (same
    convention as ``TestValidateFormPage``): validation runs BEFORE the doc
    guard for ``panel/qc/accept``, but is still split out and unit tested
    directly rather than only through the op.
    """

    def test_valid_payload_passes(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_accept_payload(
            {"check_id": "lights", "author": "Javier", "reason": "known issue"}) is None

    def test_missing_check_id_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_accept_payload(
            {"author": "Javier", "reason": "known issue"}) == "check_id_required"

    def test_missing_author_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_accept_payload(
            {"check_id": "lights", "author": "  ", "reason": "known issue"}) == "author_required"

    def test_missing_reason_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_accept_payload(
            {"check_id": "lights", "author": "Javier", "reason": ""}) == "reason_required"

    def test_empty_payload_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_accept_payload({}) == "check_id_required"

    def test_none_payload_never_raises(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_accept_payload(None) == "check_id_required"


class TestValidateSelectCheckId:
    """Pure — ``panel/qc/select`` is doc-guard-first, so the "unknown or
    non-selectable check_id" branch is unreachable through the op in the
    harness (``GetActiveDocument()`` is always ``None``); split out and
    tested directly, same convention as ``TestValidateFormPage``.
    """

    def test_selectable_check_ids_pass(self, sentinel_module):
        from sentinel.ui import panel_ops
        for check_id in ("lights", "vis", "keys", "cam", "unused_mats",
                          "names", "cross_aspect"):
            assert panel_ops._validate_select_check_id(check_id) is None

    def test_info_only_check_id_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_select_check_id("rdc") == "not_selectable"

    def test_unknown_check_id_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_select_check_id("nonexistent") == "not_selectable"
        assert panel_ops._validate_select_check_id(None) == "not_selectable"
        assert panel_ops._validate_select_check_id("") == "not_selectable"


class TestAdvanceCursor:
    """Pure — ``_advance_cursor`` is the cycle-one-per-click math behind
    ``panel/qc/select`` (live-caught fix #2: restores the native
    ``self._idx`` cycle that Fase 6.1 replaced with select-all). Mirrors
    the native ``if self._idx >= len(self._bad): self._idx = 0`` guard, plus
    resets to 0 when the flagged set's SIZE changed since the last click.
    """

    def test_first_click_starts_at_zero(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._advance_cursor(0, -1, 5) == 0

    def test_advances_within_bounds(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._advance_cursor(2, 5, 5) == 2

    def test_wraps_when_stored_pos_ran_off_the_end(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._advance_cursor(5, 5, 5) == 0

    def test_resets_when_flagged_set_size_changed(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._advance_cursor(3, 5, 4) == 0

    def test_zero_total_returns_zero(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._advance_cursor(0, -1, 0) == 0
        assert panel_ops._advance_cursor(2, 5, 0) == 0


class TestQcFlaggedItems:
    """Pure — the flagged-item list ``panel/qc/select`` cycles through."""

    def test_plain_check_returns_legacy_result_as_is(self, sentinel_module):
        from sentinel.ui import panel_ops
        objs = ["obj_a", "obj_b"]
        assert panel_ops._qc_flagged_items("lights", objs) == objs

    def test_cross_aspect_dedupes_by_object(self, sentinel_module):
        from sentinel.ui import panel_ops
        obj_a, obj_b = object(), object()
        violations = [
            {"object": obj_a, "format": "9x16"},
            {"object": obj_a, "format": "1x1"},
            {"object": obj_b, "format": "9x16"},
        ]
        assert panel_ops._qc_flagged_items("cross_aspect", violations) == [obj_a, obj_b]

    def test_none_legacy_result_returns_empty_list(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._qc_flagged_items("lights", None) == []
        assert panel_ops._qc_flagged_items("cross_aspect", None) == []


class TestQcAcceptUnsavedDocument:
    """``panel/qc/accept`` on an unsaved document (live-caught fix #1): the
    op used to return ``{"ok": True}`` even though
    ``_baseline_path_for_doc`` has nowhere to write (no ``.c4d`` path yet),
    silently losing the acceptance. Monkeypatches ``documents.GetActiveDocument``
    (the fake module the harness installs at ``c4d.documents``, imported by
    ``panel_ops`` as ``from c4d import documents``) to return a fake doc
    whose ``GetDocumentPath()`` is empty — same technique needed here as
    nowhere else in this file gets past the doc guard.
    """

    def test_unsaved_document_rejected_before_baseline_write(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        class _FakeDoc:
            def GetDocumentPath(self):
                return ""

        monkeypatch.setattr(panel_ops.documents, "GetActiveDocument", lambda: _FakeDoc())

        response = panel_ops.PANEL_OPS["panel/qc/accept"](
            {"check_id": "lights", "author": "Javier", "reason": "known issue"})
        assert response == {"ok": False, "error": "unsaved_document"}


class TestOverviewBlockIsolation:
    """``build_panel_overview`` (panel_ops.py) must isolate each of the 5
    card builders: one raising builder degrades to ``None`` for that key
    only, the other 4 still populate normally — mirrors the per-field
    ``try/except`` isolation ``ui/panel.py`` ``_sync_ui_from_doc`` uses
    (~985-1013). Tested via monkeypatched builders + a sentinel ``doc``
    object rather than a real ``c4d.documents.BaseDocument`` (the harness
    has none) — the aggregation/isolation logic itself doesn't care what
    ``doc`` actually is, only that it's threaded through unchanged.
    """

    def test_one_raising_block_becomes_null_others_survive(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        doc = object()
        monkeypatch.setattr(panel_ops, "_panel_scene_block", lambda d: {"name": "ok"})
        monkeypatch.setattr(panel_ops, "_panel_assets_block", lambda d: {"count": 1})
        monkeypatch.setattr(panel_ops, "_panel_render_block", lambda d: {"fps": 25})
        monkeypatch.setattr(panel_ops, "_panel_deliver_block", lambda d: {"todos_pending": 0})

        def _boom(d):
            raise RuntimeError("assets scan exploded")

        monkeypatch.setattr(panel_ops, "_panel_qc_block", _boom)

        result = panel_ops.build_panel_overview(doc)

        assert result["qc"] is None
        assert result["scene"] == {"name": "ok"}
        assert result["assets"] == {"count": 1}
        assert result["render"] == {"fps": 25}
        assert result["deliver"] == {"todos_pending": 0}

    def test_all_blocks_healthy_none_are_null(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        doc = object()
        for name in ("_panel_scene_block", "_panel_qc_block", "_panel_assets_block",
                     "_panel_render_block", "_panel_deliver_block"):
            monkeypatch.setattr(panel_ops, name, lambda d, name=name: {"probe": name})

        result = panel_ops.build_panel_overview(doc)

        assert None not in result.values()
        assert len(result) == 5

    def test_op_panel_overview_survives_a_block_exception(self, sentinel_module, monkeypatch):
        """End-to-end through the op itself would need a real document
        (blocked doc-guard-first in the harness), so this exercises
        ``_op_panel_overview``'s own aggregation call by monkeypatching
        ``documents.GetActiveDocument`` to return a truthy sentinel and
        ``build_panel_overview`` to simulate one failed block — proving the
        op returns the aggregated dict rather than propagating."""
        from sentinel.ui import panel_ops

        monkeypatch.setattr(panel_ops.documents, "GetActiveDocument", lambda: object())
        monkeypatch.setattr(
            panel_ops, "build_panel_overview",
            lambda d: {"scene": {}, "qc": None, "assets": {}, "render": {}, "deliver": {}})

        response = panel_ops.PANEL_OPS["panel/overview"]({})

        assert response["qc"] is None
        assert "error" not in response


class TestValidateFormPage:
    """Pure — reachable without the fake-c4d harness or a document, since
    ``panel/open_form`` itself is doc-guard-first (matching every sibling op
    in hub_ops.py/web_ops.py), which makes ``invalid_page`` unreachable
    through the op under the harness (GetActiveDocument() is always None).
    The validator is split out and tested directly instead.
    """

    def test_valid_pages_pass(self, sentinel_module):
        from sentinel.ui import panel_ops
        for page in ("form/save_version", "form/notes", "form/settings"):
            assert panel_ops._validate_form_page(page) is None

    def test_invalid_page_rejected(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._validate_form_page("form/gate") == "invalid_page"
        assert panel_ops._validate_form_page("hub") == "invalid_page"
        assert panel_ops._validate_form_page("") == "invalid_page"
        assert panel_ops._validate_form_page(None) == "invalid_page"


class TestVramLabelOrNone:
    """``_vram_label_or_none`` — pure decision behind the Assets card's
    ``vram_label``: ``None`` while the Hub's image-metadata cache is cold
    (``covered == 0``), a real formatted label once anything is covered."""

    def test_cold_cache_is_none(self, sentinel_module):
        from sentinel.ui import panel_ops
        assert panel_ops._vram_label_or_none(0, 12345) is None

    def test_zero_bytes_but_covered_is_a_real_label_not_none(self, sentinel_module):
        # Degenerate but distinct from "cold": something IS cached, it just
        # happens to sum to 0 bytes (e.g. a single unreadable image header).
        from sentinel.ui import panel_ops
        assert panel_ops._vram_label_or_none(1, 0) == "0 B"

    def test_warm_cache_formats_the_total(self, sentinel_module):
        from sentinel.ui import panel_ops
        from sentinel import assets as assets_engine
        assert panel_ops._vram_label_or_none(3, 3_300_000_000) == assets_engine.format_size(3_300_000_000)


class TestPanelAssetsBlockVram:
    """``_panel_assets_block`` must ask ``hub_ops._totals_from_cache`` about
    THIS scan's own resolved paths (not the Hub's ``_THUMB_PATHS`` memo, which
    can be empty even with a warm ``_META_CACHE`` if the Hub was opened on a
    different scene this session) and report ``None`` while that lookup is
    cold rather than the misleading "0 B"."""

    def _records(self):
        return [
            {"key": "a", "resolved_path": "/tex/a.png", "status": "ok",
             "asset_type": "texture", "size_bytes": 100},
            {"key": "b", "resolved_path": "/tex/b.png", "status": "ok",
             "asset_type": "texture", "size_bytes": 200},
        ]

    def _patch_scan(self, monkeypatch, records):
        import sentinel.ui.flows as flows
        monkeypatch.setattr(flows, "scan_scene_assets", lambda doc: (records, [], []))

    def test_cold_totals_cache_yields_none_vram_label(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        self._patch_scan(monkeypatch, self._records())
        monkeypatch.setattr(
            panel_ops, "_totals_from_cache",
            lambda paths: {"vram_bytes": 0, "vram_label": "0 B",
                            "disk_bytes": 0, "disk_label": "0 B",
                            "covered": 0, "total": 2})

        result = panel_ops._panel_assets_block(object())

        assert result["vram_label"] is None
        assert result["count"] == 2
        assert result["missing"] == 0

    def test_warm_totals_cache_yields_real_vram_label(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops
        from sentinel import assets as assets_engine

        self._patch_scan(monkeypatch, self._records())
        monkeypatch.setattr(
            panel_ops, "_totals_from_cache",
            lambda paths: {"vram_bytes": 3_300_000_000, "vram_label": "3.3 GB",
                            "disk_bytes": 300, "disk_label": "300 B",
                            "covered": 2, "total": 2})

        result = panel_ops._panel_assets_block(object())

        assert result["vram_label"] == assets_engine.format_size(3_300_000_000)


class TestPanelAssetsBlockCache:
    """``_panel_assets_block`` must NOT re-scan/re-stat on every call — an
    always-docked panel re-fetches ``panel/overview`` whenever
    ``panel/state_stamp`` changes, and that stamp bumps on ANY scene edit
    (``doc.GetDirty(DATA|CHILDREN)``), including plain geometry/animation
    work that never touches a material. ``_ASSETS_BLOCK_CACHE`` keyed by
    ``_assets_signature`` (materials-only: doc path + material count +
    summed material dirty) must make a second call with an unchanged
    signature reuse the cached payload instead of re-running
    ``scan_scene_assets``/``stat_sizes_batch``/``compute_totals``.
    """

    class _FakeMat:
        def __init__(self, dirty=0):
            self._dirty = dirty

        def GetDirty(self, flags):
            return self._dirty

    class _FakeDoc:
        def __init__(self, path="/scene.c4d", materials=None):
            self._path = path
            self._materials = materials or []

        def GetDocumentPath(self):
            return self._path

        def GetMaterials(self):
            return self._materials

    def setup_method(self):
        from sentinel.ui import panel_ops
        panel_ops._ASSETS_BLOCK_CACHE["signature"] = None
        panel_ops._ASSETS_BLOCK_CACHE["payload"] = None

    def _patch_scan_counting(self, monkeypatch, records):
        import sentinel.ui.flows as flows
        calls = {"n": 0}

        def _scan(doc):
            calls["n"] += 1
            if calls["n"] > 1:
                raise AssertionError(
                    "scan_scene_assets called again for an unchanged assets signature")
            return (records, [], [])

        monkeypatch.setattr(flows, "scan_scene_assets", _scan)
        return calls

    def test_second_call_same_signature_does_not_rescan(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops

        records = [{"key": "a", "resolved_path": "/tex/a.png", "status": "ok",
                    "asset_type": "texture", "size_bytes": 100}]
        calls = self._patch_scan_counting(monkeypatch, records)
        monkeypatch.setattr(panel_ops, "_totals_from_cache",
                             lambda paths: {"vram_bytes": 0, "covered": 0})

        doc = self._FakeDoc(materials=[self._FakeMat(dirty=0)])

        first = panel_ops._panel_assets_block(doc)
        second = panel_ops._panel_assets_block(doc)

        assert calls["n"] == 1
        assert second == first
        assert first["count"] == 1

    def test_material_dirty_change_invalidates_cache(self, sentinel_module, monkeypatch):
        from sentinel.ui import panel_ops
        import sentinel.ui.flows as flows

        records = [{"key": "a", "resolved_path": "/tex/a.png", "status": "ok",
                    "asset_type": "texture", "size_bytes": 100}]
        scans = {"n": 0}

        def _scan(doc):
            scans["n"] += 1
            return (records, [], [])

        monkeypatch.setattr(flows, "scan_scene_assets", _scan)
        monkeypatch.setattr(panel_ops, "_totals_from_cache",
                             lambda paths: {"vram_bytes": 0, "covered": 0})

        mat = self._FakeMat(dirty=0)
        doc = self._FakeDoc(materials=[mat])

        panel_ops._panel_assets_block(doc)
        mat._dirty = 1  # simulate a texture repath bumping material dirty
        panel_ops._panel_assets_block(doc)

        assert scans["n"] == 2

    def test_signature_none_for_a_doc_without_material_reads_never_caches(
            self, sentinel_module, monkeypatch):
        """Falls back to always-recompute (never raises, never caches)
        when ``doc`` doesn't support the reads the signature needs — same
        object used by ``TestPanelAssetsBlockVram`` above."""
        from sentinel.ui import panel_ops

        records = [{"key": "a", "resolved_path": "/tex/a.png", "status": "ok",
                    "asset_type": "texture", "size_bytes": 100}]
        scans = {"n": 0}

        import sentinel.ui.flows as flows

        def _scan(doc):
            scans["n"] += 1
            return (records, [], [])

        monkeypatch.setattr(flows, "scan_scene_assets", _scan)
        monkeypatch.setattr(panel_ops, "_totals_from_cache",
                             lambda paths: {"vram_bytes": 0, "covered": 0})

        panel_ops._panel_assets_block(object())
        panel_ops._panel_assets_block(object())

        assert scans["n"] == 2


class TestTopQcChecks:
    """Pure — no c4d import in webbridge.py, no harness needed."""

    def _check(self, check_id, label, count=None, new=None):
        return {"id": check_id, "label": label, "severity": "FAIL",
                "has_fix": False, "status": "fail" if (count or new) else "ok",
                "count": count, "new": new, "accepted": None, "details": []}

    def test_picks_worst_three_by_new_then_count(self):
        from sentinel import webbridge

        checks = [
            self._check("a", "A", count=1),
            self._check("b", "B", new=5),
            self._check("c", "C", count=0),
            self._check("d", "D", new=3),
            self._check("e", "E", count=2),
        ]
        top = webbridge.top_qc_checks(checks)
        assert top == [
            {"check_id": "b", "label": "B", "count": 5},
            {"check_id": "d", "label": "D", "count": 3},
            {"check_id": "e", "label": "E", "count": 2},
        ]

    def test_zero_and_none_counts_excluded(self):
        from sentinel import webbridge

        checks = [self._check("a", "A", count=0), self._check("b", "B")]
        assert webbridge.top_qc_checks(checks) == []

    def test_respects_custom_limit(self):
        from sentinel import webbridge

        checks = [self._check(str(i), str(i), count=i) for i in range(1, 6)]
        assert len(webbridge.top_qc_checks(checks, limit=2)) == 2
