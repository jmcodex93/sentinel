"""Run stabilization acceptance in a fresh c4dpy process, never Script Manager.

Use an absolute script path and ``c4dpy -g_console=true <this-file>``.
Creates and removes disposable documents/files; does not install the plugin
or touch the documents in an independently running Cinema 4D GUI session.
"""
from contextlib import contextmanager
from pathlib import Path
import array
import json
import math
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


def _write_height(path, height_at, size=64):
    """A real height map on disk: float RGB EXR, or 8-bit PNG (0..1 → 0..255)."""
    exr = path.suffix == ".exr"
    bmp = c4d.bitmaps.BaseBitmap()
    bmp.Init(size, size, 96 if exr else 24)
    for y in range(size):
        if exr:
            row = array.array("f")
            for x in range(size):
                row.extend((height_at(x, y),) * 3)
            bmp.SetPixelCnt(0, y, size, memoryview(bytearray(row.tobytes())), 12,
                            c4d.COLORMODE_RGBf, c4d.PIXELCNT_0)
        else:
            for x in range(size):
                g = int(round(max(0.0, min(1.0, height_at(x, y))) * 255))
                bmp.SetPixel(x, y, g, g, g)
    saved = bmp.Save(str(path), c4d.FILTER_EXR if exr else c4d.FILTER_PNG, None,
                     c4d.SAVEBIT_32BITCHANNELS if exr else c4d.SAVEBIT_0)
    assert saved == c4d.IMAGERESULT_OK, (path, saved)


def matwire_height_ranges(root):
    """Matwire's Displacement remap end to end through the panel ops: real
    files, the preview row and the range read back from the live graph.
    Integer png → centred; float maps by their pixels — zero-centred EXR
    (negatives) keeps 0..1, mid-grey EXR is centred, black-flat EXR keeps
    0..1 flagged unverified."""
    import maxon
    from sentinel import matwire_c4d
    from sentinel.ui import panel_tools_ops
    wave = lambda x, y: math.sin(x * math.pi / 8) * math.sin(y * math.pi / 8)
    cases = {
        "zc": (".exr", lambda x, y: 0.4 * wave(x, y), "zero_based", (0.0, 1.0)),
        "mg": (".exr", lambda x, y: 0.5 + 0.4 * wave(x, y), "centered", (-0.5, 0.5)),
        "bf": (".exr", lambda x, y: max(0.0, wave(x, y)), "unverified", (0.0, 1.0)),
        "pn": (".png", lambda x, y: 0.5 + 0.4 * wave(x, y), "centered", (-0.5, 0.5)),
    }
    folder = root / "matwire_heights"
    folder.mkdir()
    for name, (ext, height_at, _, _) in cases.items():
        _write_height(folder / (name + "_disp" + ext), height_at)
        _write_height(folder / (name + "_col.png"), lambda x, y: 0.7)
    disp_id = matwire_c4d._RS_CORE + "displacement"
    with document() as doc:
        preview = panel_tools_ops._op_matwire_preview({"folder": str(folder)})
        assert preview.get("ok"), preview
        rows = {s["name"]: {r["channel"]: r for r in s["channels"]} for s in preview["sets"]}
        got_rows = {name: rows[name]["height"]["range"] for name in cases}
        assert got_rows == {name: case[2] for name, case in cases.items()}, got_rows
        created = panel_tools_ops._op_matwire_create({"folder": str(folder)})
        assert created.get("ok") and created["created"] == len(cases), created
        remaps = {}
        mat = doc.GetFirstMaterial()
        while mat:
            graph = maxon.GraphDescription.GetGraph(
                mat, nodeSpaceId=maxon.NodeSpaceIdentifiers.RedshiftMaterial)
            nodes = []
            graph.GetViewRoot().GetChildren(nodes, maxon.NODE_KIND.NODE)
            disp = [n for n in nodes if disp_id in str(n.GetValue(matwire_c4d._ASSETID_ATTR) or "")]
            assert len(disp) == 1, (mat.GetName(), len(disp))
            inputs = disp[0].GetInputs()
            remaps[mat.GetName()] = tuple(
                float(inputs.FindChild(disp_id + "." + port).GetPortValue())
                for port in ("newrange_min", "newrange_max"))
            mat = mat.GetNext()
        assert remaps == {name: case[3] for name, case in cases.items()}, remaps
        stats = {name: matwire_c4d.height_float_stats(str(folder / (name + "_disp.exr")))
                 for name in ("zc", "mg", "bf")}
    print("PASS Matwire displacement remap via ops:", got_rows, remaps,
          {k: {m: round(v[m], 3) for m in ("min", "max", "mean")} for k, v in stats.items()})


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
        matwire_height_ranges(root)
        collect_packages(root)
        notes(root)
        watch(root)
    print("PASS Sentinel product acceptance")


if __name__ == "__main__":
    # c4dpy treats a SystemExit(0) as a script exception on this host.
    main()
