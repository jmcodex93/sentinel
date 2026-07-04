"""Build Sentinel QC fixture scenes inside Cinema 4D or c4dpy.

This script creates:
  tests/fixtures/violating.c4d
  tests/fixtures/clean.c4d

It does not freeze expected JSON. After running this builder, run
run_fixtures.py --freeze once inside Cinema 4D/c4dpy.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import math
import os
from pathlib import Path

import c4d
from c4d import documents


def _script_path() -> Path:
    try:
        return Path(__file__).resolve()
    except NameError:
        return Path(os.getcwd()).resolve() / "tests" / "c4d_runner" / "build_fixtures.py"


ROOT = _script_path().parents[2]
PLUGIN_PATH = ROOT / "plugin" / "sentinel_panel.pyp"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


def _load_sentinel():
    loader = importlib.machinery.SourceFileLoader(
        "sentinel_panel_fixture_builder", str(PLUGIN_PATH)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module.GlobalSettings.get_standard_fps = staticmethod(lambda: 25)
    module.check_cache.clear()
    return module


def _new_doc():
    try:
        return documents.BaseDocument()
    except AttributeError:
        return c4d.documents.BaseDocument()


def _set_doc_timing(doc, fps, start, end):
    doc.SetFps(int(fps))
    doc[c4d.DOCUMENT_MINTIME] = c4d.BaseTime(int(start), int(fps))
    doc[c4d.DOCUMENT_MAXTIME] = c4d.BaseTime(int(end), int(fps))
    doc[c4d.DOCUMENT_LOOPMINTIME] = c4d.BaseTime(int(start), int(fps))
    doc[c4d.DOCUMENT_LOOPMAXTIME] = c4d.BaseTime(int(end), int(fps))
    doc.SetTime(c4d.BaseTime(int(start), int(fps)))


def _setup_render_data(doc, name, fps, start, end, path, xres=1920, yres=1080):
    rd = doc.GetActiveRenderData()
    if rd is None:
        rd = documents.RenderData()
        doc.InsertRenderDataLast(rd)
        doc.SetActiveRenderData(rd)
    rd.SetName(name)
    rd[c4d.RDATA_FRAMERATE] = float(fps)
    rd[c4d.RDATA_FRAMESTEP] = 1
    rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(int(start), int(fps))
    rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(int(end), int(fps))
    rd[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_MANUAL
    rd[c4d.RDATA_PATH] = path
    rd[c4d.RDATA_XRES] = float(xres)
    rd[c4d.RDATA_YRES] = float(yres)
    return rd


def _insert(parent, child, doc):
    if parent is not None:
        child.InsertUnderLast(parent)
    else:
        doc.InsertObject(child)
    return child


def _make_object(type_id, name, doc, parent=None, pos=None):
    obj = c4d.BaseObject(type_id)
    obj.SetName(name)
    if pos is not None:
        obj.SetAbsPos(pos)
    _insert(parent, obj, doc)
    return obj


def _assign_material(obj, mat):
    tag = c4d.BaseTag(c4d.Ttexture)
    tag[c4d.TEXTURETAG_MATERIAL] = mat
    obj.InsertTag(tag)
    return tag


def _make_material(name, texture_path=None):
    mat = c4d.BaseMaterial(c4d.Mmaterial)
    mat.SetName(name)
    if texture_path:
        shader = c4d.BaseShader(c4d.Xbitmap)
        shader[c4d.BITMAPSHADER_FILENAME] = texture_path
        mat.InsertShader(shader)
        try:
            mat[c4d.MATERIAL_COLOR_SHADER] = shader
            mat[c4d.MATERIAL_USE_COLOR] = True
        except Exception:
            pass
    return mat


def _add_two_axis_position_tracks(obj, fps):
    for axis in (c4d.VECTOR_X, c4d.VECTOR_Y):
        desc_id = c4d.DescID(
            c4d.DescLevel(c4d.ID_BASEOBJECT_POSITION, c4d.DTYPE_VECTOR, 0),
            c4d.DescLevel(axis, c4d.DTYPE_REAL, 0),
        )
        track = c4d.CTrack(obj, desc_id)
        curve = track.GetCurve()
        key = curve.AddKey(c4d.BaseTime(0, fps))["key"]
        key.SetValue(curve, 0.0)
        obj.InsertTrackSorted(track)


def _build_violating(module):
    doc = _new_doc()
    _set_doc_timing(doc, 30, 0, 60)
    _setup_render_data(doc, "custom_preview", 30, 0, 60, "")

    # 1 lights: native light outside any light/lights/lighting group.
    _make_object(c4d.Olight, "stray_key_light", doc)

    # 2 visibility traps.
    vis = _make_object(c4d.Ocube, "hidden_in_editor_only", doc)
    vis[c4d.ID_BASEOBJECT_VISIBILITY_EDITOR] = c4d.OBJECT_OFF
    vis[c4d.ID_BASEOBJECT_VISIBILITY_RENDER] = c4d.OBJECT_ON

    # 3 multi-axis keyframes.
    keyed = _make_object(c4d.Onull, "animated_multi_axis", doc)
    _add_two_axis_position_tracks(keyed, 30)

    # 4 camera shift.
    cam = _make_object(c4d.Ocamera, "shifted_camera", doc)
    cam.SetAbsPos(c4d.Vector(0, 0, 0))
    cam[c4d.CAMERAOBJECT_FOV] = math.radians(90.0)
    cam[c4d.CAMERAOBJECT_FILM_OFFSET_X] = 0.1
    cam[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = -0.05
    try:
        doc.GetActiveBaseDraw().SetSceneCamera(cam)
    except Exception:
        pass

    # 6 textures + 7 unused materials.
    missing_abs = "/__sentinel_fixture_missing__/missing_albedo.exr"
    bad_mat = _make_material("missing_absolute_texture_mat", missing_abs)
    doc.InsertMaterial(bad_mat)

    # 8 default names.
    _make_object(c4d.Ocube, "Cube", doc)
    _make_object(c4d.Onull, "Null", doc)

    # 10 takes: child take with no camera and inherited tokenless/empty path.
    td = doc.GetTakeData()
    if td is not None:
        main = td.GetMainTake()
        td.AddTake("take_without_camera", main, None)

    # 12 cross-aspect safe area: marked subject inside camera view but outside
    # the 9:16 crop/safe area.
    subject = _make_object(
        c4d.Ocube,
        "safe_area_subject_too_far_right",
        doc,
        pos=c4d.Vector(600, 0, 1000),
    )
    module.mark_object_safe_area(subject, True, doc=None)
    if td is not None:
        try:
            td.GetMainTake().SetCamera(td, cam)
        except Exception:
            pass
    module.generate_multiformat_takes(
        doc,
        {
            "formats": ["16x9", "9x16", "1x1", "4x5", "21x9"],
            "output_mode": "subfolder",
            "composition_mode": module.COMPOSITION_MODE_NONE,
            "update_existing": True,
        },
    )

    return doc


def _build_clean(module):
    doc = _new_doc()
    _set_doc_timing(doc, 25, 1001, 1010)
    _setup_render_data(
        doc,
        "render",
        25,
        1001,
        1010,
        "renders/$prj_$take_$frame",
    )

    lights = _make_object(c4d.Onull, "lights", doc)
    _make_object(c4d.Olight, "key_light", doc, parent=lights)

    cam = _make_object(c4d.Ocamera, "shot_camera", doc, pos=c4d.Vector(0, 0, 0))
    cam[c4d.CAMERAOBJECT_FOV] = math.radians(60.0)
    cam[c4d.CAMERAOBJECT_FILM_OFFSET_X] = 0.0
    cam[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = 0.0
    try:
        doc.GetActiveBaseDraw().SetSceneCamera(cam)
    except Exception:
        pass
    td = doc.GetTakeData()
    if td is not None:
        try:
            td.GetMainTake().SetCamera(td, cam)
        except Exception:
            pass

    hero = _make_object(c4d.Ocube, "hero_geo", doc, pos=c4d.Vector(0, 0, 1000))
    mat = _make_material("hero_mat")
    doc.InsertMaterial(mat)
    _assign_material(hero, mat)

    return doc


def _save_doc(doc, name):
    path = FIXTURES_DIR / f"{name}.c4d"
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    ok = documents.SaveDocument(
        doc,
        str(path),
        c4d.SAVEDOCUMENTFLAGS_NONE,
        c4d.FORMAT_C4DEXPORT,
    )
    if not ok:
        raise RuntimeError(f"SaveDocument returned False for {path}")
    return path


def main():
    active_doc = documents.GetActiveDocument()
    module = _load_sentinel()
    built = []
    docs_to_kill = []
    try:
        for name, builder in (
            ("violating", _build_violating),
            ("clean", _build_clean),
        ):
            doc = builder(module)
            docs_to_kill.append(doc)
            built.append(_save_doc(doc, name))
    finally:
        for doc in docs_to_kill:
            try:
                documents.KillDocument(doc)
            except Exception:
                pass
        if active_doc is not None:
            try:
                documents.SetActiveDocument(active_doc)
            except Exception:
                pass
        c4d.EventAdd()

    print("PASS Sentinel fixture builder:")
    for path in built:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
