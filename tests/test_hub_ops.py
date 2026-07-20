# -*- coding: utf-8 -*-
"""Tests for plugin/sentinel/ui/hub_ops.py — the Hub SPA op layer.

Uses the fake-c4d harness (``sentinel_module`` fixture): hub_ops imports c4d
at module scope, so it is imported lazily inside each test (same pattern as
tests/test_web_ops.py). GetActiveDocument() is None in the harness, so these
tests pin the no-document contract + the op-table shape; the payload logic
itself is pure and tested in tests/test_webbridge.py.
"""


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
