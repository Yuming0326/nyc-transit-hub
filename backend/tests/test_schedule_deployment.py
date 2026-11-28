"""B22 publishing validates the entire artifact set before touching a destination."""
import hashlib
import json
import sys

import pytest

from scripts import prepare_schedule_artifacts as deployment


def data(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    manifest = {'feeds': {}}
    for name in ('subway','b'):
        payload = ('reviewed-' + name).encode()
        (source/(name+'.sqlite.gz')).write_bytes(payload)
        manifest['feeds'][name] = {'artifact':name+'.sqlite.gz',
            'artifact_sha256':hashlib.sha256(payload).hexdigest()}
    path = tmp_path/'reviewed.json'
    path.write_text(json.dumps(manifest),encoding='utf-8')
    return source,path,manifest


def test_deployment_preserves_reviewed_manifest(tmp_path,monkeypatch):
    source,manifest,_ = data(tmp_path)
    original = manifest.read_bytes()
    output = tmp_path/'deployed'
    monkeypatch.setattr(deployment,'MANIFEST',manifest)
    monkeypatch.setattr(sys,'argv',['prepare','--source-dir',str(source),'--output',str(output)])
    deployment.main()
    assert (output/'manifest.json').read_bytes() == original == manifest.read_bytes()
    deployment.verify(output,json.loads(original))


def test_missing_or_changed_artifact_never_partially_publishes(tmp_path,monkeypatch):
    source,manifest,_ = data(tmp_path)
    output = tmp_path/'deployed'
    output.mkdir()
    previous = output/'subway.sqlite.gz'
    previous.write_bytes(b'previous-working-version')
    (source/'b.sqlite.gz').write_bytes(b'changed')
    monkeypatch.setattr(deployment,'MANIFEST',manifest)
    monkeypatch.setattr(sys,'argv',['prepare','--source-dir',str(source),'--output',str(output)])
    with pytest.raises(ValueError):
        deployment.main()
    assert previous.read_bytes() == b'previous-working-version'
    assert not (output/'manifest.json').exists()


def test_manifest_cannot_reference_unexpected_artifact_paths(tmp_path):
    source,_,manifest = data(tmp_path)
    manifest['feeds']['subway']['artifact'] = '../unrelated.sqlite.gz'
    with pytest.raises(ValueError):
        deployment.verify(source,manifest)
