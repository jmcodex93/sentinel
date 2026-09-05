"""Run stabilization acceptance in a fresh c4dpy process, never Script Manager.

Use an absolute script path and ``c4dpy -g_console=true <this-file>``.
Creates and removes disposable documents/files; does not install the plugin
or touch the documents in an independently running Cinema 4D GUI session.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import runpy
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import c4d

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def document(folder=None, name="readiness_v001.c4d"):
    doc = c4d.documents.BaseDocument()
    c4d.documents.InsertBaseDocument(doc)
    c4d.documents.SetActiveDocument(doc)
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        doc.SetDocumentPath(str(folder))
    doc.SetDocumentName(name)
    try:
        yield doc
    finally:
        c4d.documents.KillDocument(doc)


def materials():
    from sentinel import matwire_c4d, matgraph_c4d
    from sentinel.checks.matgraph import check_rs_colorspace
    from sentinel.common.cache import check_cache
    from sentinel.fixes import fix_rs_colorspace
    from sentinel.matgraph import CS_SRGB, CS_RAW
    for kind in ("standard", "openpbr"):
        with document() as doc:
            doc.StartUndo()
            try:
                created = matwire_c4d.create_material_for_set(doc, tempfile.gettempdir(),
                    {"channels": {"normal": "texture_123.png"}}, "Readiness_" + kind, material=kind)
            finally:
                doc.EndUndo()
            assert created["ok"], created
            entry = matgraph_c4d.collect(doc)[0]
            assert not entry["error"], entry["error"]
            sampler = entry["samplers"][0]
            doc.StartUndo()
            try:
                written = matgraph_c4d.write_colorspaces(doc, [{"material": entry["material"],
                    "node_id": sampler["node_id"], "expected": CS_SRGB}])
            finally:
                doc.EndUndo()
            assert written["written"] == 1, written
            check_cache.clear()
            qc = check_rs_colorspace(doc, SimpleNamespace(params={}))
            assert len(qc.violations) == 1, qc.to_dict()
            assert qc.to_legacy()[0]["channel"] == "normal", qc.to_legacy()
            assert fix_rs_colorspace(doc)["written"] == 1
            assert matgraph_c4d.collect(doc)[0]["samplers"][0]["assigned"] == CS_RAW
            assert doc.DoUndo(), "undo failed"
            current = c4d.documents.GetActiveDocument()
            assert matgraph_c4d.collect(current)[0]["samplers"][0]["assigned"] == CS_SRGB
        print("PASS generic normal, RAW fix and one-step undo:", kind)


def collect_packages(root):
    from sentinel import manifest
    from sentinel.ui.flows import run_collect_pipeline
    for fail_manifest in (False, True):
        target = root / ("manifest_failure" if fail_manifest else "delivery")
        target.mkdir()
        with document(root / "source") as doc:
            obj = c4d.BaseObject(c4d.Onull)
            obj.SetName("Readiness")
            doc.InsertObject(obj)
            source = root / "source" / doc.GetDocumentName()
            assert c4d.documents.SaveDocument(doc, str(source),
                c4d.SAVEDOCUMENTFLAGS_NONE, c4d.FORMAT_C4DEXPORT)
            writer = manifest.write_manifest_json
            try:
                if fail_manifest:
                    manifest.write_manifest_json = lambda data, path: False
                result = run_collect_pipeline(doc, "Readiness", str(target), preflight_payload={})
            finally:
                manifest.write_manifest_json = writer
            if fail_manifest:
                assert result["success"] is False and result["error"] == "manifest_write_failed", result
            else:
                assert result["success"], result
                saved = json.loads(Path(result["manifest_path"]).read_text())
                assert saved["scene"] == result["delivery_filename"]
                assert (target / saved["scene"]).is_file()
                assert saved["scan_status"] == "ok", saved["scan_status"]
    collision = root / "occupied"
    collision.mkdir()
    occupied = collision / "occupied.c4d"
    occupied.write_bytes(b"preserve existing delivery")
    with document(root / "source") as doc:
        result = run_collect_pipeline(doc, "Readiness", str(collision), preflight_payload={})
        assert result["error"] == "scene_collision", result
        assert occupied.read_bytes() == b"preserve existing delivery"
    print("PASS real SaveProject, matching manifest, manifest failure and collision")


def notes(root):
    from sentinel.ui import web_ops
    with document(root / "notes", "shot_v001.c4d") as a:
        state = web_ops._op_form_notes_state({})
        assert state.get("context") and state.get("revision"), state
        draft = dict(state, notes_text="Scene A draft — café y composición", todos=[])
        with document(root / "notes", "other_v001.c4d"):
            assert web_ops._op_form_notes_submit(draft)["error"] == "scene_changed"
            assert not (root / "notes/other_notes.json").exists()
            c4d.documents.SetActiveDocument(a)
            a.SetDocumentName("shot_v002_2ND.c4d")
            assert web_ops._op_form_notes_submit(draft) == {"ok": True}
            state = web_ops._op_form_notes_state({})
            assert state["notes_text"] == draft["notes_text"], state
            sidecar = root / "notes/shot_notes.json"
            external = {"scene": "shot", "notes": "Another writer", "todos": []}
            sidecar.write_text(json.dumps(external))
            assert web_ops._op_form_notes_submit(dict(state, notes_text="Stale"))["error"] == "notes_changed"
            assert json.loads(sidecar.read_text()) == external
    print("PASS Notes scene switch, shared version base and concurrent edit guard")


def watch(root):
    from sentinel.snapshots import SnapshotWatch, run_snapshot_task
    from sentinel.ui.flows import prepare_snapshot_task
    source = root / "snapshots"
    source.mkdir()
    (source / "old.png").write_bytes(b"backlog")
    watcher = SnapshotWatch()
    with document(root / "project" / "scenes" / "shot") as doc:
        prepared_threads = []
        def prepare(path):
            prepared_threads.append(threading.get_ident())
            return prepare_snapshot_task(doc, "Readiness", path)
        def tick():
            watcher.tick(True, str(source), "scene A", prepare, run_snapshot_task)
        tick()
        tick()
        assert not prepared_threads
        (source / "new.png").write_bytes(b"new snapshot")
        tick()
        tick()
        deadline = time.monotonic() + 5
        while watcher.busy and time.monotonic() < deadline:
            time.sleep(.01)
        tick()
        assert not watcher.busy
        assert watcher.status()["state"] == "ready", watcher.status()
        assert prepared_threads == [threading.get_ident()]
        outputs = list(root.rglob("readiness_v001_snap_*.png"))
        assert len(outputs) == 1 and outputs[0].read_bytes() == b"new snapshot"
    print("PASS watch backlog/settle/worker with real C4D context capture")


def main():
    if "c4dpy" not in sys.executable.lower():
        raise RuntimeError("Run in a fresh c4dpy process, not a running GUI session")
    loader = runpy.run_path(str(ROOT / "tests/c4d_runner/run_fixtures.py"))
    loader["_load_sentinel"]()
    with tempfile.TemporaryDirectory(prefix="sentinel_readiness_") as tmp:
        root = Path(tmp)
        materials()
        collect_packages(root)
        notes(root)
        watch(root)
    print("PASS Sentinel product acceptance")


if __name__ == "__main__":
    # c4dpy treats a SystemExit(0) as a script exception on this host.
    main()
