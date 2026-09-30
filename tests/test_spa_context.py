"""Document/revision and dispatch snapshot regression contracts."""
import json
import pytest


@pytest.fixture
def notes_context(sentinel_module, monkeypatch, tmp_path):
    from sentinel.ui import web_ops
    class Doc:
        def __init__(self, name): self.name = name
        def GetDocumentName(self): return self.name
        def GetDocumentPath(self): return str(tmp_path)
    active = [Doc('shot_v001.c4d')]
    monkeypatch.setattr(web_ops.documents, 'GetActiveDocument', lambda: active[0])
    path = tmp_path / 'shot_notes.json'
    path.write_text(json.dumps({'scene':'shot', 'notes':'original', 'todos': []}))
    return web_ops, active, Doc, path


def test_notes_reject_cross_scene_and_missing_context(notes_context):
    ops, active, Doc, path = notes_context
    state = ops._op_form_notes_state({})
    assert 'context' in state and 'revision' in state
    payload = dict(state, notes_text='draft A')
    active[0] = Doc('other_v001.c4d')
    response = ops._op_form_notes_submit(payload)
    assert response == {'ok': False, 'error': 'scene_changed'}
    assert not (path.parent / 'other_notes.json').exists()
    active[0] = Doc('shot_v001.c4d')
    assert ops._op_form_notes_submit({'notes_text':'unsafe','todos':[]}) == {'ok':False,'error':'notes_context_required'}
    assert json.loads(path.read_text())['notes'] == 'original'


def test_notes_same_base_version_valid_but_concurrent_edit_rejected(notes_context):
    ops, active, Doc, path = notes_context
    state = ops._op_form_notes_state({})
    active[0] = Doc('shot_v002_TR.c4d')
    assert ops._op_form_notes_submit(dict(state, notes_text='new version draft')) == {'ok':True}
    stale = ops._op_form_notes_state({})
    external = {'scene':'shot','notes':'external writer','todos': []}
    path.write_text(json.dumps(external))
    assert ops._op_form_notes_submit(dict(stale, notes_text='stale draft')) == {'ok':False,'error':'notes_changed'}
    assert json.loads(path.read_text()) == external


@pytest.mark.parametrize('op', ['panel/overview','panel/qc','panel/render','panel/frame','panel/deliver','hub/inventory'])
def test_optional_snapshot_envelope_is_same_dispatch_and_uses_corresponding_stamp(sentinel_module, monkeypatch, op):
    from sentinel.ui import reports_dialog
    calls=[]
    def read(payload):
        calls.append('read')
        return {'value':'snapshot'}
    def stamp(payload):
        calls.append('stamp')
        return {'stamp':'scene|snapshot:ready:done'}
    monkeypatch.setitem(reports_dialog._OPS, op, read)
    stamp_op = 'hub/state_stamp' if op.startswith('hub/') else 'panel/state_stamp'
    monkeypatch.setitem(reports_dialog._OPS, stamp_op, stamp)
    assert reports_dialog._dispatch({'op':op}) == {'value':'snapshot'}
    calls.clear()
    assert reports_dialog._dispatch({'op':op,'with_stamp':'1'}) == {'data':{'value':'snapshot'},'stamp':'scene|snapshot:ready:done'}
    assert calls == ['read','stamp']


def test_snapshot_does_not_hide_error_envelope(sentinel_module, monkeypatch):
    from sentinel.ui import reports_dialog
    monkeypatch.setitem(reports_dialog._OPS,'panel/overview',lambda payload:{'error':'no_document'})
    assert reports_dialog._dispatch({'op':'panel/overview','with_stamp':'1'}) == {'error':'no_document'}


@pytest.mark.parametrize('raw', [b'{broken json', b'[]'])
def test_notes_unreadable_state_cannot_erase_existing_bytes(notes_context, raw):
    ops, active, Doc, path = notes_context
    original_state = ops._op_form_notes_state({})
    path.write_bytes(raw)
    assert ops._op_form_notes_state({}) == {'error':'notes_unreadable'}
    assert ops._op_form_notes_submit(dict(original_state, notes_text='replacement')) == {'ok':False,'error':'notes_unreadable'}
    assert path.read_bytes() == raw


def test_hub_selection_does_not_acknowledge_another_document_snapshot(sentinel_module, monkeypatch):
    from sentinel.ui import reports_dialog
    called=[]
    monkeypatch.setitem(reports_dialog._OPS,'hub/select_owner',lambda payload: called.append(payload) or {'ok':True,'stamp':'C'})
    monkeypatch.setitem(reports_dialog._OPS,'hub/state_stamp',lambda payload:{'stamp':'B'})
    assert reports_dialog._dispatch({'op':'hub/select_owner','key':'same','expected_stamp':'A'}) == {'ok':False,'error':'scene_changed'}
    assert not called
    assert reports_dialog._dispatch({'op':'hub/select_owner','key':'same','expected_stamp':'B'}) == {'ok':True,'stamp':'C'}


def test_notes_transient_middle_read_never_becomes_an_editable_empty_draft(notes_context, monkeypatch):
    import builtins
    ops, active, Doc, path = notes_context
    original = {'scene':'shot','notes':'Keep this note','todos':[{'id':1,'text':'Keep this TODO','done':False}]}
    path.write_text(json.dumps(original), encoding='utf-8')
    real_open = builtins.open
    def failing_middle_read(file, mode='r', *args, **kwargs):
        if str(file) == str(path) and mode == 'r':
            raise OSError('transient NAS failure in the former tolerant middle read')
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', failing_middle_read)
    state = ops._op_form_notes_state({})
    if state.get('error'):
        assert state == {'error':'notes_unreadable'}
        assert json.loads(path.read_bytes()) == original
    else:
        assert state['notes_text'] == original['notes']
        assert state['todos'] == original['todos']
        assert ops._op_form_notes_submit(state) == {'ok':True}
        saved = json.loads(path.read_bytes())
        assert saved['notes'] == original['notes'] and saved['todos'] == original['todos']


def test_utf8_notes_state_submit_and_native_readers_ignore_cp1252_locale(notes_context, monkeypatch):
    import builtins
    from sentinel import notes, versioning
    ops, active, Doc, path = notes_context
    original = {'scene':'shot','notes':'café — revisión','todos':[{'id':1,'text':'iluminación','done':False}]}
    assert notes.save_notes(str(path), original)
    history_path = path.parent / 'shot_history.json'
    history = {'versions':[{'version':1,'comment':'café — revisión','artist':'José'}]}
    assert versioning.save_history(str(history_path), history)
    real_open = builtins.open
    def cp1252_default(file, mode='r', *args, **kwargs):
        if str(file) in (str(path), str(history_path)) and 'b' not in mode and 'encoding' not in kwargs:
            kwargs['encoding'] = 'cp1252'
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', cp1252_default)
    state = ops._op_form_notes_state({})
    assert state['notes_text'] == original['notes']
    assert ops._op_form_notes_submit(state) == {'ok':True}
    assert json.loads(path.read_bytes())['notes'] == original['notes']
    assert notes.load_notes(str(path))['notes'] == original['notes']
    assert versioning.load_history(str(history_path)) == history


def test_legacy_windows_cp1252_sidecars_survive_and_upgrade_to_utf8(notes_context, monkeypatch):
    import locale
    import sys
    from sentinel import notes, versioning
    ops, active, Doc, path = notes_context
    original = {'scene':'shot','notes':'café — revisión','todos':[{'id':1,'text':'iluminación','done':False}]}
    history = {'versions':[{'version':1,'comment':'café — revisión','artist':'José'}]}
    history_path = path.parent / 'shot_history.json'
    path.write_bytes(json.dumps(original, ensure_ascii=False).encode('cp1252'))
    history_path.write_bytes(json.dumps(history, ensure_ascii=False).encode('cp1252'))
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(locale, 'getpreferredencoding', lambda do_setlocale=True: 'cp1252')
    assert notes.load_notes(str(path))['notes'] == original['notes']
    assert versioning.load_history(str(history_path)) == history
    state = ops._op_form_notes_state({})
    assert state['notes_text'] == original['notes']
    assert state['todos'] == original['todos']
    assert ops._op_form_notes_submit(state) == {'ok':True}
    assert json.loads(path.read_bytes().decode('utf-8'))['notes'] == original['notes']
    assert notes.load_notes(str(path))['notes'] == original['notes']
    assert versioning.save_history(str(history_path), versioning.load_history(str(history_path)))
    assert json.loads(history_path.read_bytes().decode('utf-8')) == history
    assert versioning.load_history(str(history_path)) == history


def test_legacy_encoding_is_not_guessed_on_other_platforms(notes_context, monkeypatch):
    import locale
    import sys
    ops, active, Doc, path = notes_context
    raw = json.dumps({'scene':'shot','notes':'café','todos':[]},ensure_ascii=False).encode('cp1252')
    path.write_bytes(raw)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(locale, 'getpreferredencoding', lambda do_setlocale=True:'cp1252')
    assert ops._op_form_notes_state({}) == {'error':'notes_unreadable'}
    assert path.read_bytes() == raw
