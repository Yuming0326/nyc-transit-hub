import gzip
import hashlib
import json
from pathlib import Path

import pytest
from scripts.check_data_artifacts import FEEDS, inventory, verify


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n')


@pytest.fixture
def data(tmp_path):
    meta={'sha256':'subway-source','imported_at':'2026-11-24T00:00:00Z'}
    busmeta={'snapshot_sha256':'bus-source','imported_at':'2026-11-24T00:00:00Z'}
    stations=[{'id':'R20'}]
    write(tmp_path/'catalog.json',{'stations':stations,'metadata':meta})
    write(tmp_path/'stations.json',stations)
    write(tmp_path/'geometry.json',{'type':'FeatureCollection','features':[{}],'metadata':meta})
    write(tmp_path/'bus/catalog.json',{'metadata':busmeta})
    write(tmp_path/'bus/geometry.json',{'type':'FeatureCollection','features':[{}],'metadata':busmeta})
    feeds={}
    for feed in FEEDS:
        payload=gzip.compress(('fixture '+feed).encode())
        path=tmp_path/'schedules'/(feed+'.sqlite.gz');path.parent.mkdir(exist_ok=True);path.write_bytes(payload)
        feeds[feed]={'artifact':path.name,'artifact_sha256':hashlib.sha256(payload).hexdigest(),'source_sha256':feed+'-source'}
    write(tmp_path/'schedules/manifest.json',{'feeds':feeds,'imported_at':meta['imported_at'],'bus_discovery_snapshot_sha256':'bus-source'})
    write(tmp_path/'data-manifest.json',inventory(tmp_path))
    return tmp_path


def test_clean_inventory_and_optional_schedule_hashes(data):
    verify(data,schedules=True)
    (data/'schedules/b.sqlite.gz').unlink()
    verify(data)  # A clone need not contain the ignored databases.
    with pytest.raises(OSError):verify(data,schedules=True)


def test_mismatched_source_provenance_cannot_be_relocked(data):
    payload=json.loads((data/'bus/geometry.json').read_text());payload['metadata']['snapshot_sha256']='other'
    write(data/'bus/geometry.json',payload)
    with pytest.raises(ValueError,match='provenance'):inventory(data)


def test_consistent_but_changed_files_fail_existing_lock(data):
    stations=[{'id':'R21'}]
    catalog=json.loads((data/'catalog.json').read_text());catalog['stations']=stations
    write(data/'catalog.json',catalog);write(data/'stations.json',stations)
    with pytest.raises(ValueError,match='manifest does not match'):verify(data)


def test_damaged_local_database_fails_hash_check(data):
    (data/'schedules/b.sqlite.gz').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Schedule artifact checksum'):verify(data,schedules=True)


def test_schedule_crosswalk_must_pin_bus_import(data):
    payload=json.loads((data/'schedules/manifest.json').read_text());payload['bus_discovery_snapshot_sha256']='different'
    write(data/'schedules/manifest.json',payload)
    with pytest.raises(ValueError,match='crosswalk'):inventory(data)


def test_manifest_write_does_not_publish_when_local_schedule_is_corrupt(data):
    import subprocess,sys
    lock=(data/'data-manifest.json').read_bytes()
    (data/'schedules/b.sqlite.gz').write_bytes(b'bad')
    script=Path(__file__).parents[1]/'scripts/check_data_artifacts.py'
    result=subprocess.run([sys.executable,str(script),'--data-dir',str(data),'--write-manifest','--schedules'],capture_output=True)
    assert result.returncode==1
    assert (data/'data-manifest.json').read_bytes()==lock


def test_windows_crlf_checkout_preserves_json_inventory(data):
    for path in data.rglob('*.json'):
        content=path.read_text().replace('\n','\r\n')
        assert '\r\n' in content
        path.write_bytes(content.encode('utf-8'))
    verify(data,schedules=True)
