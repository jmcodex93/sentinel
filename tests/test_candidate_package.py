# -*- coding: utf-8 -*-
"""Candidate archives come only from a committed tree and verify after extract."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        'sentinel_candidate_builder', str(ROOT / 'build_candidate.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args):
    return subprocess.check_output(
        ['git', *args], cwd=str(ROOT), text=False)


def test_candidate_uses_committed_source_and_verifies_after_extract(tmp_path):
    builder = _load_builder()
    output = tmp_path / 'sentinel-beta.zip'
    commit = _git('rev-parse', 'HEAD').decode('ascii').strip()
    committed_install = _git('show', '%s:install.py' % commit)

    result = builder.build_candidate(str(ROOT), str(output), source_ref='HEAD')

    assert result['commit'] == commit
    assert builder.verify_candidate_archive(str(output))['ok'] is True
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {'install.py', 'INSTALLATION_README.md',
                builder.CANDIDATE_MANIFEST_NAME} <= names
        assert any(name.startswith('plugin/') for name in names)
        assert archive.read('install.py') == committed_install
        manifest = json.loads(archive.read(builder.CANDIDATE_MANIFEST_NAME))
        assert manifest['commit'] == commit
        for path, record in manifest['files'].items():
            data = archive.read(path)
            assert record == {
                'sha256': hashlib.sha256(data).hexdigest(),
                'size': len(data),
            }


def test_candidate_verifier_rejects_tampered_archive(tmp_path):
    builder = _load_builder()
    output = tmp_path / 'sentinel-beta.zip'
    builder.build_candidate(str(ROOT), str(output), source_ref='HEAD')

    with zipfile.ZipFile(output) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries['install.py'] = b'tampered'
    with zipfile.ZipFile(output, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)

    result = builder.verify_candidate_archive(str(output))
    assert result['ok'] is False
    assert any('install.py' in issue for issue in result['issues'])
