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
        for op in ("panel/state_stamp", "panel/overview", "panel/open_form"):
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
