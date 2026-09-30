"""Acceptance against a normally loaded candidate in a fresh c4dpy process.

Start with -g_console=true -g_additionalModulePath=<candidate plugins folder>
and this script's absolute path. Never run in the user's GUI Script Manager.
Optional SENTINEL_ACCEPTANCE_OUTPUT selects the JSON evidence file.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
import traceback

import c4d
import sentinel


@contextmanager
def document(root, name):
    doc = c4d.documents.BaseDocument()
    c4d.documents.InsertBaseDocument(doc)
    c4d.documents.SetActiveDocument(doc)
    root.mkdir(parents=True, exist_ok=True)
    doc.SetDocumentPath(str(root))
    doc.SetDocumentName(name)
    try:
        yield doc
    finally:
        c4d.documents.KillDocument(doc)


def find_object(doc, name):
    def walk(obj):
        while obj is not None:
            if obj.GetName() == name:
                return obj
            child = walk(obj.GetDown())
            if child is not None:
                return child
            obj = obj.GetNext()
        return None
    found = walk(doc.GetFirstObject())
    assert found is not None, name
    return found


def exr_watch(root):
    from sentinel.snapshots import SnapshotWatch, run_snapshot_task, _find_system_python
    from sentinel.ui.flows import prepare_snapshot_task
    python = _find_system_python()
    assert python, 'No detected system Python with OpenEXR/numpy/Pillow'
    source = root / 'snapshots'
    source.mkdir()
    watcher = SnapshotWatch()
    with document(root / 'project' / 'scenes' / 'shot', 'beta_v001.c4d') as doc:
        def tick():
            watcher.tick(True, str(source), 'beta EXR',
                         lambda path: prepare_snapshot_task(doc, 'Acceptance', path), run_snapshot_task)
        tick()
        result = subprocess.run([python, '-c',
            'import OpenEXR, numpy as np, sys; '
            'p=np.tile(np.linspace(0,4,128,dtype=np.float32),(64,1)); '
            'OpenEXR.File({}, {"R":p,"G":p,"B":p}).write(sys.argv[1])',
            str(source / 'gradient.exr')], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        tick()
        tick()
        deadline = time.monotonic() + 30
        while watcher.busy and time.monotonic() < deadline:
            time.sleep(.02)
        tick()
        assert watcher.status()['state'] == 'ready', watcher.status()
        outputs = list(root.rglob('beta_v001_snap_*.png'))
        assert len(outputs) == 1, outputs
        verify = subprocess.run([python, '-c',
            'from PIL import Image; import sys,json; im=Image.open(sys.argv[1]); '
            'assert im.width==128 and im.height>=64,im.size; '
            'a,b,c=[im.convert("RGB").getpixel((x,20))[0] for x in (0,32,127)]; '
            'assert a<b<c<=255,(a,b,c); print(json.dumps({"size":im.size,"levels":[a,b,c]}))',
            str(outputs[0])], capture_output=True, text=True)
        assert verify.returncode == 0, verify.stderr
        tick()
        assert len(list(root.rglob('beta_v001_snap_*.png'))) == 1
        return {'python': python, 'image': json.loads(verify.stdout)}


def pin_restore(root):
    from sentinel.ui import pin_tag
    with document(root / 'pin', 'pin.c4d') as doc:
        cube = c4d.BaseObject(c4d.Ocube)
        cube.SetName('Pinned cube')
        cube.SetRelPos(c4d.Vector(10, 20, 30))
        doc.InsertObject(cube)
        doc.StartUndo()
        try:
            tag = pin_tag.pin_object(cube, doc)
        finally:
            doc.EndUndo()
        assert tag is not None and pin_tag._pin_is_filled(tag)
        cube.SetRelPos(c4d.Vector(80, 90, 100))
        report = pin_tag._restore(tag)
        assert cube.GetRelPos() == c4d.Vector(10, 20, 30), report
        assert len([t for t in cube.GetTags() if t.GetType() == pin_tag.SENTINEL_PIN_TAG_PLUGIN_ID]) == 2
        assert doc.DoUndo()
        cube = doc.GetFirstObject()
        assert cube.GetRelPos() == c4d.Vector(80, 90, 100)
        return {'restore': report, 'undo': 'one step'}


def variant_roundtrip(root):
    from sentinel.ui import variant_tag
    with document(root / 'variants', 'variants.c4d') as doc:
        cubes = []
        for index in range(2):
            cube = c4d.BaseObject(c4d.Ocube)
            cube.SetName('Piece ' + str(index))
            cube.SetRelPos(c4d.Vector(50 * index, 20, 30))
            doc.InsertObject(cube)
            cubes.append(cube)
        positions = {cube.GetName(): cube.GetMg().off for cube in cubes}
        created = variant_tag.create_variant_set(doc, cubes)
        assert created['ok'], created
        tag = created['tag']
        anchor_name = tag.GetObject().GetName()
        for cube in cubes:
            assert cube.GetMg().off == positions[cube.GetName()]
        duplicate = variant_tag.duplicate_active_option(tag)
        assert duplicate['ok'], duplicate
        assert variant_tag.read_state(tag)['active'] == 1
        switched = variant_tag.switch_to_option(tag, 0)
        assert switched['ok'], switched
        assert variant_tag.read_state(tag)['active'] == 0
        assert doc.DoUndo()
        tag = find_object(doc, anchor_name).GetTag(variant_tag.SENTINEL_VARIANT_TAG_PLUGIN_ID)
        assert variant_tag.read_state(tag)['active'] == 1, variant_tag.read_state(tag)
        scene = root / 'variants' / 'variants.c4d'
        assert c4d.documents.SaveDocument(doc, str(scene), c4d.SAVEDOCUMENTFLAGS_NONE, c4d.FORMAT_C4DEXPORT)
        loaded = c4d.documents.LoadDocument(str(scene), c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS, None)
        assert loaded is not None
        try:
            restored = find_object(loaded, anchor_name).GetTag(variant_tag.SENTINEL_VARIANT_TAG_PLUGIN_ID)
            state = variant_tag.read_state(restored)
            assert state['active'] == 1 and len(state['options']) == 2 and state['orphans'] == 0, state
            return state
        finally:
            c4d.documents.KillDocument(loaded)


def frame_sync(root):
    from sentinel.ui import frame_tag, scene_tools
    with document(root / 'frame', 'frame.c4d') as doc:
        camera = c4d.BaseObject(c4d.Ocamera)
        camera.SetName('Acceptance Camera')
        doc.InsertObject(camera)
        doc.SetActiveObject(camera, c4d.SELECTION_NEW)
        added = scene_tools._add_sentinel_frame_tag_core(doc)
        assert added['status'] == 'ok', added
        tag = camera.GetTag(frame_tag.SENTINEL_FRAME_TAG_PLUGIN_ID)
        assert tag is not None
        for index in range(frame_tag.FORMAT_ROW_COUNT):
            tag[frame_tag._format_ids(index)['enabled']] = index < 2
        camera.MakeTag(c4d.Tprotection)
        tag[frame_tag.ID_LINE_WIDTH] = 3.0
        original_formats = frame_tag._enabled_format_ids_from_params(tag)
        generated = frame_tag.run_full_sync(doc, tag)
        assert generated['ok'], generated
        targets = frame_tag.viewing_targets(tag)
        assert len(targets) >= 2, targets
        assert doc.GetTakeData().GetMainTake().GetDown() is not None
        assert doc.DoUndo()
        assert doc.GetTakeData().GetMainTake().GetDown() is None
        camera = find_object(doc, 'Acceptance Camera')
        tags_after_undo = [(t.GetType(), t.GetName()) for t in camera.GetTags()]
        tag = camera.GetTag(frame_tag.SENTINEL_FRAME_TAG_PLUGIN_ID)
        assert tag is not None, {'camera_type': camera.GetType(), 'tags_after_undo': tags_after_undo}
        assert frame_tag._enabled_format_ids_from_params(tag) == original_formats
        assert tag[frame_tag.ID_LINE_WIDTH] == 3.0
        assert camera.GetTag(c4d.Tprotection) is not None
        regenerated = frame_tag.run_full_sync(doc, tag)
        assert regenerated['ok'], regenerated
        return {'targets': frame_tag.viewing_targets(tag), 'undo': 'one step'}


def aov_undo(root):
    from sentinel import aovs
    from sentinel.ui import panel_render_ops
    with document(root / 'aovs', 'aovs.c4d') as doc:
        assert aovs._get_rs_videopost(doc) is not None
        before = aovs.get_rs_aovs(doc)
        response = panel_render_ops._op_panel_render_aov_tier({'tier': 'essentials'})
        assert response['ok'], response
        after = aovs.get_rs_aovs(doc)
        assert len(after) > len(before), (before, after)
        assert doc.DoUndo(), 'AOV action created no undo entry'
        assert aovs.get_rs_aovs(doc) == before, 'One Undo did not restore the original AOV list'
        return {'added': len(after) - len(before), 'undo': 'one step'}


def core_workflow(root):
    # Reuse the earlier acceptance operations, never its module-purge loader:
    # this process exercises the candidate registered normally at startup.
    checks = runpy.run_path(str(Path(__file__).with_name('run_product_checks.py')))
    checks['materials']()
    checks['collect_packages'](root)
    checks['notes'](root)
    return {'materials': 'Standard/OpenPBR + Undo', 'collect': 'SaveProject/rescan/manifest',
            'notes': 'scene/revision/UTF-8 guards'}


def main():
    if 'c4dpy' not in sys.executable.lower():
        raise RuntimeError('Use a fresh c4dpy process; do not run in the GUI')
    result = {'c4d': c4d.GetC4DVersion(), 'payload': sentinel.__file__, 'checks': {}}
    with tempfile.TemporaryDirectory(prefix='sentinel_beta_') as folder:
        for check in (exr_watch, pin_restore, variant_roundtrip, frame_sync, aov_undo, core_workflow):
            try:
                detail = check(Path(folder))
                result['checks'][check.__name__] = {'passed': True, 'detail': detail}
                print('PASS', check.__name__)
            except Exception:
                result['checks'][check.__name__] = {'passed': False, 'error': traceback.format_exc()}
                print('FAIL', check.__name__, result['checks'][check.__name__]['error'])
    result['passed'] = all(item['passed'] for item in result['checks'].values())
    output = os.environ.get('SENTINEL_ACCEPTANCE_OUTPUT')
    if output:
        Path(output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise RuntimeError('Beta acceptance failed; see per-check evidence')


if __name__ == '__main__':
    main()
