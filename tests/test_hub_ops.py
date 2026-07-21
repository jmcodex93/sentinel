# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/hub_ops.py — the Hub SPA op layer.

Uses the fake-c4d harness (``sentinel_module`` fixture): hub_ops imports c4d
at module scope, so it is imported lazily inside each test (same pattern as
tests/test_web_ops.py). GetActiveDocument() is None in the harness, so these
tests pin the no-document contract + the op-table shape; the payload logic
itself is pure and tested in tests/test_webbridge.py.
"""
import os

from test_imagemeta import make_png


class TestHubOpsTable:
    def test_read_ops_registered(self, sentinel_module):
        from sentinel.ui import hub_ops
        for op in ("hub/inventory", "hub/state_stamp", "hub/presets",
                   "hub/presets/save", "hub/preflight"):
            assert op in hub_ops.HUB_OPS

    def test_inventory_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/inventory"]({}) == {"error": "no_document"}

    def test_state_stamp_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/state_stamp"]({}) == {"error": "no_document"}

    def test_preflight_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/preflight"]({}) == {"error": "no_document"}


class TestHubMutationOps:
    def test_mutation_ops_registered(self, sentinel_module):
        from sentinel.ui import hub_ops
        for op in ("hub/apply_repath", "hub/select_owner", "hub/pick_path", "hub/thumb"):
            assert op in hub_ops.HUB_OPS

    def test_apply_repath_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        response = hub_ops.HUB_OPS["hub/apply_repath"]({"changes": [{"key": "k", "new_path": "/x"}]})
        assert response == {"ok": False, "error": "no_document"}

    def test_apply_repath_empty_changes_rejected(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/apply_repath"]({}) == {"ok": False, "error": "no_changes"}

    def test_select_owner_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/select_owner"]({"key": "k"}) == {"ok": False, "error": "no_document"}

    def test_thumb_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/thumb"]({"key": "k"}) == {"error": "no_document"}

    def test_match_folder_and_make_relative_registered(self, sentinel_module):
        from sentinel.ui import hub_ops
        for op in ("hub/match_folder", "hub/make_relative"):
            assert op in hub_ops.HUB_OPS

    def test_match_folder_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        response = hub_ops.HUB_OPS["hub/match_folder"]({"root": "/tmp/x"})
        assert response == {"ok": False, "error": "no_document"}

    def test_match_folder_requires_root(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/match_folder"]({}) == {"ok": False, "error": "no_root"}

    def test_make_relative_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/make_relative"]({}) == {"ok": False, "error": "no_document"}


class TestHubCollectJob:
    def test_collect_start_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        response = hub_ops.HUB_OPS["hub/collect_start"]({"target_dir": "/tmp/x"})
        assert response == {"ok": False, "error": "no_document"}

    def test_collect_start_requires_target(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/collect_start"]({}) == {"ok": False, "error": "no_target"}

    def test_pump_jobs_noop_when_no_pending(self, sentinel_module):
        from sentinel import webbridge
        from sentinel.ui import hub_ops
        # Fresh registry so other tests' jobs don't leak in.
        old = webbridge.JOBS
        webbridge.JOBS = webbridge.JobRegistry()
        try:
            assert hub_ops.pump_jobs() is None
        finally:
            webbridge.JOBS = old

    def test_pump_jobs_marks_job_failed_when_pipeline_raises(self, sentinel_module, monkeypatch):
        from sentinel import webbridge
        from sentinel.ui import hub_ops
        old = webbridge.JOBS
        webbridge.JOBS = webbridge.JobRegistry()
        try:
            job_id = webbridge.JOBS.start({"target_dir": "/tmp/x", "zip": False,
                                           "preflight_payload": None})
            monkeypatch.setattr(hub_ops, "_run_collect_for_job",
                                lambda spec, on_status: (_ for _ in ()).throw(RuntimeError("boom")))
            hub_ops.pump_jobs()
            st = webbridge.JOBS.status(job_id)
            assert st["state"] == "error" and "boom" in st["error"]
        finally:
            webbridge.JOBS = old


class TestBridgeWiring:
    def test_hub_ops_merged_into_dispatch_table(self, sentinel_module):
        from sentinel.ui import reports_dialog
        for op in ("hub/inventory", "hub/apply_repath", "hub/collect_start"):
            assert op in reports_dialog._OPS

    def test_api_entry_answers_job_status_without_queue(self, sentinel_module):
        from sentinel import webbridge
        from sentinel.ui import reports_dialog
        old = webbridge.JOBS
        webbridge.JOBS = webbridge.JobRegistry()
        try:
            job_id = webbridge.JOBS.start({})
            # No queue exists yet (_queue is None) — a queue round-trip would
            # crash; a direct registry answer succeeds.
            st = reports_dialog._api_entry({"op": "hub/job_status", "job_id": job_id})
            assert st["state"] == "pending"
            assert reports_dialog._api_entry({"op": "hub/job_status"}) == {"error": "unknown_job"}
        finally:
            webbridge.JOBS = old

    def test_hub_form_size_registered(self, sentinel_module):
        from sentinel.ui import reports_dialog
        assert reports_dialog._FORM_SIZES["hub"] == (1120, 700)


class TestThumbMemo:
    def test_remember_thumb_paths_replaces_not_merges(self, sentinel_module):
        """Live-verified (2026-07-20): ``hub/thumb`` re-scanning the scene
        on every request queued dozens of full scans while scrolling. The
        module-level memo is refreshed by every op that already runs a
        fresh scan, so ``hub/thumb`` can look the path up for free. A
        second call must REPLACE the memo (stale keys from a previous
        scene state must not linger), not merge into it."""
        from sentinel.ui import hub_ops

        hub_ops._remember_thumb_paths(
            [{"key": "a", "resolved_path": "/x"}, {"key": "b", "resolved_path": None}])
        assert hub_ops._THUMB_PATHS == {"a": "/x", "b": None}

        hub_ops._remember_thumb_paths([{"key": "c", "resolved_path": "/y"}])
        assert hub_ops._THUMB_PATHS == {"c": "/y"}


def _patched_settings(store):
    from sentinel.common import settings as settings_mod

    orig_load = settings_mod.GlobalSettings._load
    orig_save = settings_mod.GlobalSettings._save
    settings_mod.GlobalSettings._load = staticmethod(lambda: dict(store))

    def _save(data):
        store.clear()
        store.update(data)
        return True

    settings_mod.GlobalSettings._save = staticmethod(_save)
    return orig_load, orig_save


def _restore_settings(orig_load, orig_save):
    from sentinel.common import settings as settings_mod

    settings_mod.GlobalSettings._load = staticmethod(orig_load)
    settings_mod.GlobalSettings._save = staticmethod(orig_save)


class TestHubMetaOps:
    def test_meta_ops_registered(self, sentinel_module):
        from sentinel.ui import hub_ops
        for op in ("hub/meta", "hub/meta_totals", "hub/ui_state", "hub/ui_state/save"):
            assert op in hub_ops.HUB_OPS

    def test_meta_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/meta"]({"keys": ["a"]}) == {"error": "no_document"}

    def test_meta_totals_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops.HUB_OPS["hub/meta_totals"]({}) == {"error": "no_document"}

    def test_meta_over_batch_cap_still_doc_guarded_first(self, sentinel_module):
        # Doc-guard-first, same as every sibling op: the harness's
        # GetActiveDocument() is always None, so the no_document contract
        # wins even with an over-cap key list — the cap check itself sits
        # after the doc guard (sibling-consistent, see plan Task 2).
        from sentinel.ui import hub_ops
        response = hub_ops.HUB_OPS["hub/meta"]({"keys": ["k"] * 65})
        assert response == {"error": "no_document"}

    def test_meta_batch_cap_constant(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops._META_BATCH_CAP == 64


class TestHubMetaTotalsFromCache:
    """``_totals_from_cache`` is the pure helper behind ``hub/meta_totals``.
    ``hub/meta_totals`` itself always short-circuits on ``no_document`` in
    this harness (no fake c4d document), so the counting logic is tested
    directly against the helper."""

    def test_total_counts_images_only(self, sentinel_module, tmp_path):
        from sentinel.ui import hub_ops

        png_file = tmp_path / "tex.png"
        png_file.write_bytes(make_png(4, 4, 8, 2))
        png_path = str(png_file)
        abc_path = tmp_path / "cache.abc"
        abc_path.write_bytes(b"not an image")
        abc_path = str(abc_path)

        # Seed the cache for both paths as if a parse had already been
        # attempted — proves the .abc is excluded by extension, not just
        # because it lacks a cache entry.
        png_key, _ = hub_ops._stat_cache_key(png_path)
        abc_key, _ = hub_ops._stat_cache_key(abc_path)
        hub_ops._META_CACHE[png_key] = {"vram_bytes": 100, "disk_bytes": 10}
        hub_ops._META_CACHE[abc_key] = {"vram_bytes": 999, "disk_bytes": 999}
        try:
            result = hub_ops._totals_from_cache([png_path, abc_path])
        finally:
            hub_ops._META_CACHE.pop(png_key, None)
            hub_ops._META_CACHE.pop(abc_key, None)

        assert result["total"] == 1
        assert result["covered"] == 1
        assert result["vram_bytes"] == 100
        assert result["disk_bytes"] == 10

    def test_none_and_missing_paths_ignored(self, sentinel_module, tmp_path):
        from sentinel.ui import hub_ops

        missing_png = str(tmp_path / "gone.png")
        result = hub_ops._totals_from_cache([None, missing_png])
        assert result == {
            "vram_bytes": 0,
            "vram_label": hub_ops.assets_engine.format_size(0),
            "disk_bytes": 0,
            "disk_label": hub_ops.assets_engine.format_size(0),
            "covered": 0,
            "total": 0,
        }


class TestHubUiState:
    def test_ui_state_default_empty(self, sentinel_module):
        from sentinel.ui import hub_ops
        store = {}
        orig = _patched_settings(store)
        try:
            assert hub_ops.HUB_OPS["hub/ui_state"]({}) == {"state": {}}
        finally:
            _restore_settings(*orig)

    def test_ui_state_roundtrip(self, sentinel_module):
        from sentinel.ui import hub_ops
        store = {}
        orig = _patched_settings(store)
        try:
            state = {"col_widths": {"name": 200}, "sort": {"col": "size", "dir": "desc"}}
            result = hub_ops.HUB_OPS["hub/ui_state/save"]({"state": state})
            assert result == {"ok": True}
            assert hub_ops.HUB_OPS["hub/ui_state"]({}) == {"state": state}
        finally:
            _restore_settings(*orig)

    def test_ui_state_save_rejects_non_dict(self, sentinel_module):
        from sentinel.ui import hub_ops
        store = {}
        orig = _patched_settings(store)
        try:
            result = hub_ops.HUB_OPS["hub/ui_state/save"]({"state": "nope"})
            assert result == {"ok": False, "error": "invalid state"}
        finally:
            _restore_settings(*orig)

    def test_ui_state_save_rejects_missing_state(self, sentinel_module):
        from sentinel.ui import hub_ops
        store = {}
        orig = _patched_settings(store)
        try:
            result = hub_ops.HUB_OPS["hub/ui_state/save"]({})
            assert result == {"ok": False, "error": "invalid state"}
        finally:
            _restore_settings(*orig)


class TestMetaForCache:
    def test_meta_for_unreadable_path_returns_none(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops._meta_for("/no/such/file/anywhere.png") is None

    def test_meta_for_parses_and_enriches(self, sentinel_module, tmp_path):
        from sentinel.ui import hub_ops
        path = tmp_path / "tex.png"
        path.write_bytes(make_png(4096, 4096, 8, 2))  # RGB 8b
        meta = hub_ops._meta_for(str(path))
        assert meta["width"] == 4096
        assert meta["height"] == 4096
        assert meta["channels"] == 3
        assert meta["bit_depth"] == 8
        assert meta["res_tier"] == "4k"
        assert meta["res_label"] == "4K"
        assert meta["vram_bytes"] > 0
        assert meta["vram_label"]
        assert meta["disk_bytes"] == os.path.getsize(str(path))

    def test_meta_for_cache_hit_never_reparses(self, sentinel_module, tmp_path, monkeypatch):
        from sentinel.ui import hub_ops
        from sentinel import imagemeta

        path = tmp_path / "small.png"
        path.write_bytes(make_png(64, 64, 8, 2))
        first = hub_ops._meta_for(str(path))
        assert first is not None

        def _boom(_path):
            raise AssertionError("read_image_meta must not be called again on cache hit")

        monkeypatch.setattr(imagemeta, "read_image_meta", _boom)
        second = hub_ops._meta_for(str(path))
        assert second == first

    def test_meta_for_caches_unparseable_none_without_retry(self, sentinel_module, tmp_path, monkeypatch):
        from sentinel.ui import hub_ops
        from sentinel import imagemeta

        path = tmp_path / "garbage.dat"
        path.write_bytes(b"not an image")
        first = hub_ops._meta_for(str(path))
        assert first is None

        def _boom(_path):
            raise AssertionError("must not re-parse a cached-None entry")

        monkeypatch.setattr(imagemeta, "read_image_meta", _boom)
        assert hub_ops._meta_for(str(path)) is None


class TestHubShrinkAndCopyOps:
    def test_ops_registered(self, sentinel_module):
        from sentinel.ui import hub_ops
        for op in ("hub/shrink_start", "hub/copy_into_project"):
            assert op in hub_ops.HUB_OPS

    def test_shrink_start_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        response = hub_ops.HUB_OPS["hub/shrink_start"](
            {"keys": ["a"], "target_px": 2048})
        assert response == {"ok": False, "error": "no_document"}

    def test_copy_into_project_without_document(self, sentinel_module):
        from sentinel.ui import hub_ops
        response = hub_ops.HUB_OPS["hub/copy_into_project"]({"keys": ["a"]})
        assert response == {"ok": False, "error": "no_document"}

    def test_validate_shrink_payload_rejects_bad_target(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops._validate_shrink_payload(
            {"keys": ["a"], "target_px": 999}) == "invalid_target"

    def test_validate_shrink_payload_accepts_known_targets(self, sentinel_module):
        from sentinel.ui import hub_ops
        for target in (4096, 2048, 1024):
            assert hub_ops._validate_shrink_payload(
                {"keys": ["a"], "target_px": target}) is None

    def test_validate_shrink_payload_rejects_non_int_target(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops._validate_shrink_payload(
            {"keys": ["a"], "target_px": "2048"}) == "invalid_target"


class TestSettleRelinkResults:
    """Pure helper behind the writer-failure fix in ``_run_shrink_for_job``
    and ``_op_hub_copy_into_project``: a batch job must never report success
    for an item whose relink write actually failed (mirrors
    ``_op_hub_apply_repath``'s ``row_ok`` bookkeeping)."""

    def test_all_succeed_returns_everything_no_errors(self, sentinel_module):
        from sentinel.ui import hub_ops
        planned = [{"key": "a"}, {"key": "b"}]
        write_results = {"a": True, "b": True}
        succeeded, errors = hub_ops._settle_relink_results(planned, write_results)
        assert succeeded == planned
        assert errors == []

    def test_false_write_result_excluded_and_reported(self, sentinel_module):
        from sentinel.ui import hub_ops
        planned = [{"key": "a"}, {"key": "b"}]
        write_results = {"a": True, "b": False}
        succeeded, errors = hub_ops._settle_relink_results(planned, write_results)
        assert succeeded == [{"key": "a"}]
        assert errors == [{"key": "b", "error": "writer failed"}]

    def test_missing_write_result_treated_as_failed(self, sentinel_module):
        from sentinel.ui import hub_ops
        planned = [{"key": "a"}]
        succeeded, errors = hub_ops._settle_relink_results(planned, {})
        assert succeeded == []
        assert errors == [{"key": "a", "error": "writer failed"}]

    def test_empty_planned_returns_empty(self, sentinel_module):
        from sentinel.ui import hub_ops
        assert hub_ops._settle_relink_results([], {"a": True}) == ([], [])


class TestPumpJobsKindDispatch:
    def test_shrink_kind_dispatches_to_shrink_runner(self, sentinel_module, monkeypatch):
        from sentinel import webbridge
        from sentinel.ui import hub_ops
        old = webbridge.JOBS
        webbridge.JOBS = webbridge.JobRegistry()
        called = {}
        try:
            job_id = webbridge.JOBS.start({"kind": "shrink", "plan": {}})

            def _fake_shrink(jid, spec):
                called["job_id"] = jid
                called["spec"] = spec

            monkeypatch.setattr(hub_ops, "_run_shrink_for_job", _fake_shrink)
            hub_ops.pump_jobs()
            assert called["job_id"] == job_id
            assert called["spec"]["kind"] == "shrink"
        finally:
            webbridge.JOBS = old

    def test_kindless_spec_still_routes_to_collect_runner(self, sentinel_module, monkeypatch):
        """Backward compat: a spec with no ``kind`` key (the shape every
        pre-existing ``hub/collect_start`` job used before this task) must
        still dispatch to ``_run_collect_for_job`` — never break existing
        collect jobs."""
        from sentinel import webbridge
        from sentinel.ui import hub_ops
        old = webbridge.JOBS
        webbridge.JOBS = webbridge.JobRegistry()
        called = {}
        try:
            job_id = webbridge.JOBS.start({"target_dir": "/tmp/x", "zip": False,
                                           "preflight_payload": None})

            def _fake_collect(spec, on_status):
                called["spec"] = spec
                return {"manifest": {}, "manifest_path": ""}

            monkeypatch.setattr(hub_ops, "_run_collect_for_job", _fake_collect)
            hub_ops.pump_jobs()
            assert called["spec"]["target_dir"] == "/tmp/x"
            st = webbridge.JOBS.status(job_id)
            assert st["state"] == "done"
        finally:
            webbridge.JOBS = old


class TestOpenHubPalette:
    def test_palette_open_hub_still_registered(self, sentinel_module):
        """_palette_open_hub now tries the SPA hub (open_form) before
        falling back to the native AssetHubDialog (Task 12), but the
        no-document contract it shares with every other palette action
        must be unchanged: no active document is still the very first
        check, before either code path runs."""
        from sentinel.ui import web_ops

        response = web_ops._op_palette_run({"id": "open_hub"})

        assert response == {"ok": False, "error": "No active document"}
