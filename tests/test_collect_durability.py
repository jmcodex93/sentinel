import os


class _Doc:
    def __init__(self, folder, name):
        self.folder = str(folder)
        self.name = name

    def GetDocumentPath(self):
        return self.folder

    def GetDocumentName(self):
        return self.name

    def SetDocumentPath(self, value):
        self.folder = value

    def SetDocumentName(self, value):
        self.name = value

    def GetTakeData(self):
        return None

    def GetChanged(self):
        return False

    def GetMaterials(self):
        return []


def _run_collect(sentinel_module, monkeypatch, tmp_path, manifest_ok=True,
                 preflight_payload=None):
    from sentinel import manifest
    from sentinel.ui import flows

    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    target = tmp_path / "Package"
    target.mkdir(exist_ok=True)
    doc = _Doc(source, "shot_v003_TR.c4d")
    rescanned = []

    def save_project(_doc, _flags, target_dir, assets, missing):
        (target / "Package.c4d").write_bytes(b"fresh-scene")
        return True

    monkeypatch.setattr(flows.c4d.documents, "SaveProject", save_project)
    monkeypatch.setattr(
        flows, "_rescan_collected_package",
        lambda path, root: (rescanned.append(path) or ([], "ok", [])))
    monkeypatch.setattr(manifest, "write_manifest_json",
                        lambda payload, path: manifest_ok)
    return (flows.run_collect_pipeline(
        doc, "Artist", str(target), preflight_payload=preflight_payload),
        target, rescanned)


def test_collect_collision_reports_and_manifests_fresh_effective_scene(
        sentinel_module, monkeypatch, tmp_path):
    target = tmp_path / "Package"
    target.mkdir()
    old_scene = target / "shot.c4d"
    old_scene.write_bytes(b"old-scene")
    source = tmp_path / "source"
    source.mkdir()
    notes = source / "shot_notes.json"
    history = source / "shot_history.json"
    baseline = source / "shot_baseline.json"
    notes.write_text('{"notes":"keep","todos":[]}', encoding="utf-8")
    history.write_text('{"versions":[]}', encoding="utf-8")
    baseline.write_text('{"schema":1,"entries":[]}', encoding="utf-8")

    result, target, rescanned = _run_collect(
        sentinel_module, monkeypatch, tmp_path,
        preflight_payload={"baseline_path": str(baseline)})

    assert old_scene.read_bytes() == b"old-scene"
    assert (target / "Package.c4d").read_bytes() == b"fresh-scene"
    assert rescanned == [str(target / "Package.c4d")]
    assert result["delivery_filename"] == "Package.c4d"
    assert result["manifest"]["scene"] == "Package.c4d"
    assert (target / "Package_notes.json").exists()
    assert (target / "Package_history.json").exists()
    assert (target / "Package_baseline.json").exists()
    assert not (target / "shot_notes.json").exists()


def test_collect_manifest_write_failure_returns_explicit_failure(
        sentinel_module, monkeypatch, tmp_path):
    result, _target, _rescanned = _run_collect(
        sentinel_module, monkeypatch, tmp_path, manifest_ok=False)

    assert result["success"] is False
    assert result["error"] == "manifest_write_failed"


def test_collect_rename_failure_returns_explicit_failure_before_rescan(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel.ui import flows

    monkeypatch.setattr(
        flows.os, "rename",
        lambda source, target: (_ for _ in ()).throw(OSError("rename blocked")))

    result, _target, rescanned = _run_collect(
        sentinel_module, monkeypatch, tmp_path)

    assert result["success"] is False
    assert result["error"] == "scene_rename_failed"
    assert rescanned == []


def test_collect_saveproject_true_without_scene_returns_explicit_failure(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel import manifest
    from sentinel.ui import flows

    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "Package"
    target.mkdir()
    doc = _Doc(source, "shot_v003.c4d")
    rescanned = []

    monkeypatch.setattr(flows.c4d.documents, "SaveProject", lambda *args: True)
    monkeypatch.setattr(
        flows, "_rescan_collected_package",
        lambda path, root: (rescanned.append(path) or ([], "ok", [])))
    monkeypatch.setattr(
        manifest, "write_manifest_json",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not write manifest")))

    result = flows.run_collect_pipeline(doc, "Artist", str(target))

    assert result["success"] is False
    assert result["error"] == "scene_missing"
    assert rescanned == []


def test_collect_refuses_saveproject_when_its_output_path_already_exists(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel.ui import flows

    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "Package"
    target.mkdir()
    existing = target / "Package.c4d"
    existing.write_bytes(b"keep-existing")
    doc = _Doc(source, "shot_v003.c4d")

    monkeypatch.setattr(
        flows.c4d.documents, "SaveProject",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not write")))

    result = flows.run_collect_pipeline(doc, "Artist", str(target))

    assert result["success"] is False
    assert result["error"] == "scene_collision"
    assert existing.read_bytes() == b"keep-existing"


def test_queued_collect_rejects_document_switch_before_pipeline(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel.ui import flows, hub_ops

    doc_a = _Doc(tmp_path, "a_v001.c4d")
    doc_b = _Doc(tmp_path, "b_v001.c4d")
    monkeypatch.setattr(hub_ops.documents, "GetActiveDocument", lambda: doc_b)
    monkeypatch.setattr(
        flows, "run_collect_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not collect")))

    spec = {
        "document": doc_a,
        "document_path": os.path.join(str(tmp_path), "a_v001.c4d"),
        "target_dir": str(tmp_path / "delivery"),
        "preflight_payload": {"preflight_score": {"score": "13/13"}},
    }
    try:
        hub_ops._run_collect_for_job(spec, lambda message: None)
    except RuntimeError as exc:
        assert str(exc) == "stale_document"
    else:
        raise AssertionError("document switch was accepted")


def test_collect_job_without_bound_document_is_rejected(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel.ui import flows, hub_ops

    active = _Doc(tmp_path, "a_v001.c4d")
    monkeypatch.setattr(hub_ops.documents, "GetActiveDocument", lambda: active)
    monkeypatch.setattr(
        flows, "run_collect_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not collect")))

    try:
        hub_ops._run_collect_for_job(
            {"target_dir": str(tmp_path / "delivery")}, lambda message: None)
    except RuntimeError as exc:
        assert str(exc) == "stale_document"
    else:
        raise AssertionError("unbound Collect job was accepted")


def test_collect_start_binds_document_and_path_into_job_spec(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel import webbridge
    from sentinel.ui import hub_ops

    doc = _Doc(tmp_path, "a_v001.c4d")

    class _Rules:
        params = {"gates_enabled": False}

    old = webbridge.JOBS
    webbridge.JOBS = webbridge.JobRegistry()
    try:
        monkeypatch.setattr(hub_ops.documents, "GetActiveDocument", lambda: doc)
        monkeypatch.setattr(hub_ops, "active_rules_for_doc", lambda value: _Rules())
        monkeypatch.setattr(hub_ops, "run_all_checks", lambda *args: [])
        monkeypatch.setattr(hub_ops, "compute_score", lambda *args, **kwargs: {})
        monkeypatch.setattr(
            hub_ops, "_build_preflight_payload_for_collect", lambda *args, **kwargs: {})
        from sentinel.ui import flows
        monkeypatch.setattr(flows, "_baseline_path_for_doc", lambda *args, **kwargs: None)

        response = hub_ops._op_hub_collect_start({"target_dir": str(tmp_path / "out")})
        job_id, spec = webbridge.JOBS.take_pending()

        assert response == {"ok": True, "job_id": job_id}
        assert spec["document"] is doc
        assert spec["document_path"] == os.path.normcase(os.path.abspath(
            os.path.join(str(tmp_path), "a_v001.c4d")))
        assert spec["document_stamp"] == hub_ops._stamp_for(doc)
    finally:
        webbridge.JOBS = old


def test_queued_collect_rejects_scene_edit_after_preflight(
        sentinel_module, monkeypatch, tmp_path):
    from sentinel.ui import flows, hub_ops

    doc = _Doc(tmp_path, "a_v001.c4d")
    monkeypatch.setattr(hub_ops.documents, "GetActiveDocument", lambda: doc)
    monkeypatch.setattr(hub_ops, "_stamp_for", lambda value: "after")
    monkeypatch.setattr(
        flows, "run_collect_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not collect")))

    spec = {
        "document": doc,
        "document_path": os.path.join(str(tmp_path), "a_v001.c4d"),
        "document_stamp": "before",
        "target_dir": str(tmp_path / "delivery"),
    }
    try:
        hub_ops._run_collect_for_job(spec, lambda message: None)
    except RuntimeError as exc:
        assert str(exc) == "stale_document"
    else:
        raise AssertionError("scene edit after preflight was accepted")


def test_pump_jobs_marks_explicit_collect_failure_as_error(
        sentinel_module, monkeypatch):
    from sentinel import webbridge
    from sentinel.ui import hub_ops

    old = webbridge.JOBS
    webbridge.JOBS = webbridge.JobRegistry()
    try:
        job_id = webbridge.JOBS.start({"target_dir": "/tmp/x"})
        monkeypatch.setattr(
            hub_ops, "_run_collect_for_job",
            lambda spec, on_status: {
                "success": False, "error": "manifest_write_failed"})

        hub_ops.pump_jobs()

        status = webbridge.JOBS.status(job_id)
        assert status["state"] == "error"
        assert status["error"] == "manifest_write_failed"
    finally:
        webbridge.JOBS = old


def test_rescan_reads_scan_metadata_and_preserves_partial_status(sentinel_module, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from sentinel import textures
    from sentinel.ui import flows
    closed = []
    doc = SimpleNamespace(GetFirstObject=lambda: None, GetMaterials=lambda: [])
    monkeypatch.setattr(flows.c4d.documents, 'LoadDocument', lambda *args: doc)
    monkeypatch.setattr(flows.c4d.documents, 'KillDocument', lambda doc: closed.append(doc))
    monkeypatch.setattr(textures, 'scan_all_texture_paths', lambda doc: [])
    monkeypatch.setattr(textures, 'get_last_scan_meta', lambda: {'truncated': False})
    assert flows._rescan_collected_package(str(tmp_path / 'scene.c4d'), str(tmp_path)) == ([], 'ok', [])
    monkeypatch.setattr(textures, 'get_last_scan_meta', lambda: {'truncated': True})
    assert flows._rescan_collected_package(str(tmp_path / 'scene.c4d'), str(tmp_path)) == ([], 'partial', [])
    assert closed == [doc, doc]
