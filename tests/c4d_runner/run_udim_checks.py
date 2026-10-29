"""UDIM second delivery (v1.43) — host acceptance in a fresh c4dpy process.

Use an absolute script path: ``c4dpy -g_console=true <this-file>``.
Builds throwaway documents and tile files in a temp folder (``KillDocument``
in ``finally``); never touches a running GUI session or an artist's scene.

Proves, with real Redshift renders where placement matters:
- the material rules QC #14 relies on (last tag wins, a restriction to a
  missing selection covers nothing, a child's tag beats its parent's);
- QC #14 flags a tile without texture and stays quiet on the LOK layout;
- Shrink / Copy into project / Switch resolution per tile: files, relink,
  tiles still in place in the render, and one Cmd+Z back;
- Collect: SaveProject carries the tiles, the manifest records them and
  ``verify_package`` reports a tile lost afterwards.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import runpy
import sys
import tempfile
import time
from types import SimpleNamespace

import c4d

ROOT = Path(__file__).resolve().parents[2]
COLOURS = {1001: (255, 0, 0), 1002: (0, 255, 0), 1011: (0, 0, 255), 1005: (255, 255, 0)}


@contextmanager
def document(folder=None, name="udim_v001.c4d"):
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


def png(path, rgb, size=16):
    path.parent.mkdir(parents=True, exist_ok=True)
    bmp = c4d.bitmaps.BaseBitmap()
    bmp.Init(size, size)
    for y in range(size):
        for x in range(size):
            bmp.SetPixel(x, y, *rgb)
    assert bmp.Save(str(path), c4d.FILTER_PNG), path


def tiles(folder, pattern, sizes):
    """Tile files of ``pattern`` (``<UDIM>`` in the name), each its colour."""
    for tile, size in sizes.items():
        png(Path(folder) / pattern.replace("<UDIM>", str(tile)), COLOURS.get(tile, (90, 90, 90)), size)


def mesh(doc, uv_quads, name="Mesh", parent=None, selections=None):
    """One 2000-unit quad per UV rectangle, all on top of each other in
    front of the camera (renders use one quad per mesh)."""
    count = len(uv_quads)
    obj = c4d.PolygonObject(4 * count, count)
    uvw = c4d.UVWTag(count)
    for i, (u0, v0, u1, v1) in enumerate(uv_quads):
        for k, p in enumerate([(-1000, -1000), (-1000, 1000), (1000, 1000), (1000, -1000)]):
            obj.SetPoint(4 * i + k, c4d.Vector(p[0], p[1], 0))
        obj.SetPolygon(i, c4d.CPolygon(4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3))
        uvw.SetSlow(i, c4d.Vector(u0, v1, 0), c4d.Vector(u0, v0, 0),
                    c4d.Vector(u1, v0, 0), c4d.Vector(u1, v1, 0))
    obj.InsertTag(uvw)
    for sel_name, indices in (selections or {}).items():
        tag = c4d.SelectionTag(c4d.Tpolygonselection)
        tag.SetName(sel_name)
        for i in indices:
            tag.GetBaseSelect().Select(i)
        obj.InsertTag(tag)
    obj.SetName(name)
    obj.Message(c4d.MSG_UPDATE)
    if parent is not None:
        obj.InsertUnder(parent)
    else:
        doc.InsertObject(obj)
    return obj


def material(doc, folder, path, name):
    from sentinel import matwire_c4d
    made = matwire_c4d.create_material_for_set(
        doc, str(folder), {"channels": {"emission": path}}, name, material="standard")
    assert made["ok"], made
    return next(m for m in doc.GetMaterials() if m.GetName() == name)


def assign(obj, mat, restriction=""):
    tag = c4d.TextureTag()
    tag[c4d.TEXTURETAG_MATERIAL] = mat
    tag[c4d.TEXTURETAG_PROJECTION] = c4d.TEXTURETAG_PROJECTION_UVW
    tag[c4d.TEXTURETAG_RESTRICTION] = restriction
    obj.InsertTag(tag, obj.GetLastTag())
    return tag


def camera(doc):
    cam = c4d.BaseObject(c4d.Ocamera)
    cam.SetAbsPos(c4d.Vector(0, 0, -1500))
    doc.InsertObject(cam)
    doc.GetActiveBaseDraw().SetSceneCamera(cam)


def rendered_colour(doc):
    """Dominant colour at the frame centre: ``"red"``/``"green"``/``"blue"``/
    ``"yellow"``, or ``None`` for the grey of a material with no texture
    there (calibrated: no tile = 128,128,128; a tile = its channels at 255)."""
    rd = doc.GetActiveRenderData().GetClone()
    rd[c4d.RDATA_XRES] = 64
    rd[c4d.RDATA_YRES] = 64
    bmp = c4d.bitmaps.BaseBitmap()
    bmp.Init(64, 64)
    assert c4d.documents.RenderDocument(doc, rd.GetDataInstance(), bmp,
                                        c4d.RENDERFLAGS_EXTERNAL) == c4d.RENDERRESULT_OK
    r, g, b = bmp.GetPixel(32, 32)
    hot = tuple(c >= 250 for c in (r, g, b))
    return {(True, False, False): "red", (False, True, False): "green",
            (False, False, True): "blue", (True, True, False): "yellow"}.get(hot)


def sampler_paths(doc):
    """RS sampler paths without the ``relative:///`` scheme: the relink
    writer stores a project-relative path in that form, for a single file
    just the same (measured: ``tex/plain.png`` → ``relative:///tex/plain_1K.png``)."""
    from sentinel.textures import scan_all_texture_paths
    return sorted(r["current_path"].replace("relative:///", "")
                  for r in scan_all_texture_paths(doc) if r["source_type"] == "rs_node")


def undo_one_step(doc):
    c4d.CallCommand(12105)
    return c4d.documents.GetActiveDocument()


# ── QC #14 rules and verdicts ──────────────────────────────────────────

def material_rules(root):
    """Render-measured: the precedence rules udim_c4d resolves per polygon."""
    folder = root / "rules"
    tiles(folder, "rock.<UDIM>.png", {1001: 16, 1002: 16})
    cases = []
    with document() as doc:  # a restriction to a selection that doesn't exist
        camera(doc)
        red = material(doc, folder, "rock.1001.png", "Red")
        green = material(doc, folder, "rock.1002.png", "Green")
        obj = mesh(doc, [(0, 0, 1, 1)])
        assign(obj, red)
        assign(obj, green, "nope")
        cases.append(("missing selection covers nothing", rendered_colour(doc), "red"))
    with document() as doc:  # the later restricted tag wins on its selection
        camera(doc)
        red = material(doc, folder, "rock.1001.png", "Red")
        green = material(doc, folder, "rock.1002.png", "Green")
        obj = mesh(doc, [(0, 0, 1, 1)], selections={"sel": [0]})
        assign(obj, red)
        assign(obj, green, "sel")
        cases.append(("later restricted tag wins", rendered_colour(doc), "green"))
    with document() as doc:  # a child's own tag beats the inherited one
        camera(doc)
        red = material(doc, folder, "rock.1001.png", "Red")
        green = material(doc, folder, "rock.1002.png", "Green")
        group = c4d.BaseObject(c4d.Onull)
        doc.InsertObject(group)
        assign(group, green)
        obj = mesh(doc, [(0, 0, 1, 1)], parent=group)
        assign(obj, red)
        cases.append(("child tag beats parent", rendered_colour(doc), "red"))
    for label, got, want in cases:
        assert got == want, (label, got)
        print("PASS rule:", label, "->", got)


def qc_check(doc):
    from sentinel.checks.udim import check_udim_tiles
    from sentinel.common.cache import check_cache
    check_cache.clear()
    return check_udim_tiles(doc, SimpleNamespace(params={}))


def qc14(root):
    folder = root / "qc"
    tiles(folder, "body.<UDIM>.png", {1001: 16, 1002: 16})
    tiles(folder, "grip.<UDIM>.png", {1005: 16})
    with document() as doc:
        camera(doc)
        body = material(doc, folder, "body.<UDIM>.png", "Body")
        obj = mesh(doc, [(0, 0, 1, 1), (1, 0, 2, 1), (2, 0, 3, 1)], name="Plane")
        assign(obj, body)
        result = qc_check(doc)
        assert [v.message for v in result.violations] == [
            "Plane: tile 1003 has no texture (Body: 1 map) — renders black"], result.to_dict()
        print("PASS QC14 flags tile 1003:", result.violations[0].message)
    with document() as doc:  # the LOK layout: grip restricted to its own tile
        camera(doc)
        body = material(doc, folder, "body.<UDIM>.png", "LOK_cuerpo")
        grip = material(doc, folder, "grip.<UDIM>.png", "LOK_grip")
        obj = mesh(doc, [(0, 0, 1, 1), (1, 0, 2, 1), (4, 0, 5, 1)], name="LOK",
                   selections={"grip": [2]})
        assign(obj, body)
        grip_tag = assign(obj, grip, "grip")
        assert qc_check(doc).violations == []
        print("PASS QC14 LOK layout (grip restricted to 1005): no violation")
        grip_tag.Remove()
        result = qc_check(doc)
        assert [v.message for v in result.violations] == [
            "LOK: tile 1005 has no texture (LOK_cuerpo: 1 map) — renders black"], result.to_dict()
        print("PASS QC14 without the grip tag:", result.violations[0].message)
    with document() as doc:  # a primitive is read from its cache
        camera(doc)
        tiles(folder, "only.<UDIM>.png", {1002: 16})
        only = material(doc, folder, "only.<UDIM>.png", "Only1002")
        plane = c4d.BaseObject(c4d.Oplane)
        plane.SetName("Primitive")
        doc.InsertObject(plane)
        assign(plane, only)
        doc.ExecutePasses(None, False, False, True, c4d.BUILDFLAGS_NONE)
        result = qc_check(doc)
        assert [v.message for v in result.violations] == [
            "Primitive: tile 1001 has no texture (Only1002: 1 map) — renders black"], result.to_dict()
        print("PASS QC14 primitive read from its cache:", result.violations[0].message)
    with document() as doc:  # cost: a 500k-polygon mesh, then the cached pass
        body = material(doc, folder, "body.<UDIM>.png", "Body")
        sphere = c4d.BaseObject(c4d.Osphere)
        sphere[c4d.PRIM_SPHERE_SUB] = 1000
        doc.InsertObject(sphere)
        poly = c4d.utils.SendModelingCommand(c4d.MCOMMAND_CURRENTSTATETOOBJECT, [sphere], doc=doc)[0]
        sphere.Remove()
        doc.InsertObject(poly)
        assign(poly, body)
        t0 = time.perf_counter()
        first = qc_check(doc)
        t1 = time.perf_counter()
        second = qc_check(doc)
        t2 = time.perf_counter()
        assert first.violations == [] and second.violations == []
        print("PASS QC14 %d polygons: first %.2f s, unchanged %.2f s"
              % (poly.GetPolygonCount(), t1 - t0, t2 - t1))


# ── Hub actions per tile ───────────────────────────────────────────────

def _hub():
    from sentinel import webbridge
    from sentinel.bridge.runtime import JobRegistry
    from sentinel.ui import hub_ops
    webbridge.JOBS = JobRegistry()
    return hub_ops, webbridge


def _key_of(hub_ops, doc, needle):
    from sentinel.ui.flows import scan_scene_assets
    records, _tex, _skipped = scan_scene_assets(doc)
    rec = next(r for r in records if needle in r["path"])
    return rec["key"], rec


def _saved_scene(doc, folder):
    folder.mkdir(parents=True, exist_ok=True)
    doc.SetDocumentPath(str(folder))
    assert c4d.documents.SaveDocument(doc, str(folder / doc.GetDocumentName()),
                                      c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
                                      c4d.FORMAT_C4DEXPORT)


def _two_tile_scene(doc, path):
    """Two meshes on 1001 and 1002; the camera sees the first. ``path`` is
    relative to the scene (``tex/…``), like a project texture: Shrink plans
    only ``ok`` rows, and an absolute path classifies as ``absolute``."""
    camera(doc)
    mat = material(doc, "", path, "Rock")
    front = mesh(doc, [(0, 0, 1, 1)], name="Front")
    assign(front, mat)
    back = mesh(doc, [(1, 0, 2, 1)], name="Back")
    back.SetAbsPos(c4d.Vector(0, 0, 500))
    assign(back, mat)
    return front, back


def shrink(root):
    hub_ops, webbridge = _hub()
    folder = root / "shrink" / "tex"
    tiles(folder, "rock.<UDIM>.png", {1001: 2048, 1002: 512})
    with document(root / "shrink") as doc:
        _two_tile_scene(doc, "tex/rock.<UDIM>.png")
        _saved_scene(doc, root / "shrink")
        key, rec = _key_of(hub_ops, doc, "rock.<UDIM>")
        before = sampler_paths(doc)
        start = hub_ops.HUB_OPS["hub/shrink_start"]({"keys": [key], "target_px": 1024})
        assert start["ok"], start
        job_id, spec = webbridge.JOBS.take_pending()
        hub_ops._run_shrink_for_job(job_id, spec)
        status = webbridge.JOBS.status(job_id)
        assert status["state"] == "done" and status["result"]["errors"] == [], status
        shrunk = folder / "rock_1K.1001.png"
        copied = folder / "rock_1K.1002.png"
        bmp = c4d.bitmaps.BaseBitmap()
        assert bmp.InitWith(str(shrunk))[0] == c4d.IMAGERESULT_OK and bmp.GetBw() == 1024
        assert copied.read_bytes() == (folder / "rock.1002.png").read_bytes()
        after = sampler_paths(doc)
        assert after == [p.replace("rock.<UDIM>", "rock_1K.<UDIM>") for p in before], (before, after)
        assert rendered_colour(doc) == "red"
        print("PASS shrink: 1001 scaled to 1024, 1002 copied, sampler", after[0], "renders red")
        doc = undo_one_step(doc)
        assert sampler_paths(doc) == before, sampler_paths(doc)
        print("PASS shrink undone in one Cmd+Z:", before[0])


def copy_into_project(root):
    hub_ops, _webbridge = _hub()
    lib = root / "library"
    tiles(lib, "rock.<UDIM>.png", {1001: 16, 1002: 16, 1011: 16})
    project = root / "copy"
    with document(project) as doc:
        camera(doc)
        mat = material(doc, lib, "rock.<UDIM>.png", "Rock")
        obj = mesh(doc, [(0, -1, 1, 0)])  # tile 1011 (blue)
        assign(obj, mat)
        _saved_scene(doc, project)
        key, _rec = _key_of(hub_ops, doc, "rock.<UDIM>")
        before = sampler_paths(doc)
        res = hub_ops.HUB_OPS["hub/copy_into_project"]({"keys": [key]})
        assert (res["ok"], res["copied"], res["tiles_copied"], res["errors"]) == (True, 1, 3, []), res
        assert sorted(p.name for p in (project / "tex").iterdir()) == \
            ["rock.1001.png", "rock.1002.png", "rock.1011.png"]
        assert sampler_paths(doc) == ["tex/rock.<UDIM>.png"], sampler_paths(doc)
        assert rendered_colour(doc) == "blue"
        print("PASS copy into project: 3 tiles in tex/, sampler tex/rock.<UDIM>.png renders 1011 blue")
        doc = undo_one_step(doc)
        assert sampler_paths(doc) == before, sampler_paths(doc)
        print("PASS copy undone in one Cmd+Z")


def switch_res(root):
    hub_ops, _webbridge = _hub()
    folder = root / "switch" / "tex"
    tiles(folder, "rock_2k.<UDIM>.png", {1001: 32, 1002: 32})
    tiles(folder, "rock_1k.<UDIM>.png", {1001: 16})  # lacks 1002
    tiles(folder, "rock_4k.<UDIM>.png", {1001: 64, 1002: 64})
    with document(root / "switch") as doc:
        _two_tile_scene(doc, "tex/rock_2k.<UDIM>.png")
        _saved_scene(doc, root / "switch")
        key, _rec = _key_of(hub_ops, doc, "rock_2k.<UDIM>")
        res = hub_ops.HUB_OPS["hub/switch_res"]({"keys": [key], "target": 1024})
        assert res["skipped"] == [{"key": key, "reason": "incomplete_tiles", "missing": [1002]}], res
        print("PASS switch to 1k refused per row: missing", res["skipped"][0]["missing"])
        before = sampler_paths(doc)
        res = hub_ops.HUB_OPS["hub/switch_res"]({"keys": [key], "target": "highest"})
        assert res["switched"] == [key], res
        assert sampler_paths(doc) == [p.replace("rock_2k", "rock_4k") for p in before], sampler_paths(doc)
        assert rendered_colour(doc) == "red"
        print("PASS switch to highest:", sampler_paths(doc)[0], "renders red")
        doc = undo_one_step(doc)
        assert sampler_paths(doc) == before
        print("PASS switch undone in one Cmd+Z")


def collect(root):
    from sentinel import manifest
    from sentinel.ui.flows import run_collect_pipeline
    lib = root / "collect_lib"
    tiles(lib, "rock.<UDIM>.png", {1001: 16, 1002: 16, 1011: 16})
    with document(root / "collect_src", "shot_v003.c4d") as doc:
        camera(doc)
        mat = material(doc, lib, "rock.<UDIM>.png", "Rock")
        obj = mesh(doc, [(1, 0, 2, 1)])  # tile 1002 (green)
        assign(obj, mat)
        _saved_scene(doc, root / "collect_src")
        hub_ops, _webbridge = _hub()
        target = root / "Delivery"
        start = hub_ops.HUB_OPS["hub/collect_start"]({"target_dir": str(target)})
        assert start.get("error") != "udim_unsupported", start
        result = run_collect_pipeline(doc, "Runner", str(target))
        assert result.get("success"), result
    data = json.loads((target / "sentinel_manifest.json").read_text(encoding="utf-8"))
    (entry,) = [a for a in data["assets"] if "<UDIM>" in a["path"]]
    assert (entry["path"], entry["state"], entry["udim"]) == \
        ("tex/rock.<UDIM>.png", "collected", {"tiles": [1001, 1002, 1011]}), entry
    assert manifest.verify_package(data, str(target))["lost"] == []
    print("PASS collect: manifest records", entry["path"], entry["udim"])
    loaded = c4d.documents.LoadDocument(str(target / "shot.c4d"), c4d.SCENEFILTER_OBJECTS
                                        | c4d.SCENEFILTER_MATERIALS, None)
    c4d.documents.InsertBaseDocument(loaded)
    c4d.documents.SetActiveDocument(loaded)
    try:
        camera(loaded)
        assert rendered_colour(loaded) == "green"
    finally:
        c4d.documents.KillDocument(loaded)
    print("PASS delivered scene renders tile 1002 green from its own tex/")
    (target / "tex" / "rock.1011.png").unlink()
    lost = manifest.verify_package(data, str(target))["lost"]
    assert lost == ["tex/rock.1011.png"], lost
    print("PASS verify_package after deleting a tile:", lost)


def main():
    if "c4dpy" not in sys.executable.lower():
        raise RuntimeError("Run in a fresh c4dpy process, not a running GUI session")
    loader = runpy.run_path(str(ROOT / "tests/c4d_runner/run_fixtures.py"))
    loader["_load_sentinel"]()
    with tempfile.TemporaryDirectory(prefix="sentinel_udim_") as tmp:
        root = Path(tmp)
        material_rules(root)
        qc14(root)
        shrink(root)
        copy_into_project(root)
        switch_res(root)
        collect(root)
    print("PASS Sentinel UDIM acceptance")


if __name__ == "__main__":
    # c4dpy treats a SystemExit(0) as a script exception on this host.
    main()
