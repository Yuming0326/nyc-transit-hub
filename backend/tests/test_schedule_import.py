import csv
import gzip
from io import StringIO
from pathlib import Path
import sqlite3
import sys
from zipfile import ZipFile

import pytest
from app.services.schedule_import import retain_schedule, seconds


@pytest.fixture
def tables():
    return {
        'agency': [{'agency_id':'MTA NYCT','agency_timezone':'America/New_York'}],
        'routes': [{'route_id':'R','agency_id':'MTA NYCT','route_short_name':'R'}],
        'stops': [{'stop_id':'P','parent_station':''},{'stop_id':'PN','parent_station':'P'}],
        'trips': [{'trip_id':'t','route_id':'R','service_id':'week','direction_id':'0','shape_id':'shape'}],
        'stop_times': [
            {'trip_id':'t','stop_id':'PN','stop_sequence':'10','arrival_time':'25:05:00','departure_time':'25:06:00','timepoint':'1','pickup_type':'1'},
            {'trip_id':'t','stop_id':'PN','stop_sequence':'2','arrival_time':'24:55:00','departure_time':'24:55:00','timepoint':'1','pickup_type':'0'}],
        'calendar': [{'service_id':'week','start_date':'20261101','end_date':'20270515',**{d:'1' for d in ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']}}],
        'calendar_dates': [{'service_id':'week','date':'20261126','exception_type':'2'}],
        'transfers': [{'from_stop_id':'PN','to_stop_id':'P','transfer_type':'3','min_transfer_time':''},
                      {'from_stop_id':'P','to_stop_id':'PN','transfer_type':'2','min_transfer_time':'120'}],
        'frequencies': [{'trip_id':'t','start_time':'24:00:00','end_time':'26:00:00','headway_secs':'600'}],
    }


def source(tmp_path,tables):
    path=tmp_path/'source.zip'
    with ZipFile(path,'w') as archive:
        for table,rows in tables.items():
            text=StringIO();writer=csv.DictWriter(text,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            archive.writestr(table+'.txt',text.getvalue())
    return path


def database(tmp_path,artifact):
    path=tmp_path/'read.sqlite';path.write_bytes(gzip.decompress(artifact.read_bytes()))
    return sqlite3.connect(path)


def test_overnight_order_calendars_transfer_restrictions_and_source_fields(tmp_path,tables):
    output=tmp_path/'result.gz';report=retain_schedule(source(tmp_path,tables),output,mode='subway')
    with database(tmp_path,output) as db:
        assert db.execute('SELECT stop_sequence,departure_time,departure_seconds FROM stop_times ORDER BY stop_sequence').fetchall()==[(2,'24:55:00',89700),(10,'25:06:00',90360)]
        assert db.execute('SELECT exception_type FROM calendar_dates').fetchone()==('2',)
        assert db.execute('SELECT transfer_type,min_transfer_time FROM transfers').fetchall()==[('3',''),('2','120')]
        assert db.execute('SELECT public_id FROM entity_links WHERE source_id="PN"').fetchone()==('P',)
        assert db.execute('SELECT shape_id FROM trips').fetchone()==('shape',)
    assert report['overnight_stop_times']==2 and report['transfers_present']


@pytest.mark.parametrize('table,field,value', [
    ('trips','route_id','missing'),('trips','service_id','missing'),('trips','route_id',''),
    ('stop_times','stop_id','missing'),('stop_times','trip_id','missing'),
    ('stop_times','arrival_time','25:70:00'),('stop_times','arrival_time',''),
    ('stop_times','stop_sequence','-1'),('calendar_dates','exception_type','9'),
    ('calendar','end_date','20260101'),('transfers','to_stop_id','missing'),
    ('transfers','min_transfer_time','-1'),('frequencies','headway_secs','0'),
])
def test_bad_sources_leave_previous_output_untouched(tmp_path,tables,table,field,value):
    tables[table][0][field]=value
    output=tmp_path/'result.gz';output.write_bytes(b'previous')
    with pytest.raises((ValueError,sqlite3.IntegrityError)):
        retain_schedule(source(tmp_path,tables),output,mode='subway')
    assert output.read_bytes()==b'previous'


def test_duplicate_trip_stop_sequence_rejected(tmp_path,tables):
    tables['stop_times'][1]['stop_sequence']='10'
    with pytest.raises(sqlite3.IntegrityError):retain_schedule(source(tmp_path,tables),tmp_path/'result.gz',mode='subway')


def test_date_only_service_and_missing_optional_transfers(tmp_path,tables):
    del tables['calendar'];del tables['transfers']
    tables['calendar_dates'][0]['exception_type']='1'
    output=tmp_path/'result.gz';report=retain_schedule(source(tmp_path,tables),output,mode='subway')
    assert not report['transfers_present']
    with database(tmp_path,output) as db:assert db.execute('SELECT service_id FROM services').fetchone()==('week',)


def test_untimed_intermediate_stops_preserved_without_interpolation(tmp_path,tables):
    tables['stop_times'][0].update(arrival_time='',departure_time='',timepoint='0')
    report=retain_schedule(source(tmp_path,tables),tmp_path/'result.gz',mode='subway')
    assert report['untimed_stop_times']==1


def test_bus_crosswalk_ambiguous_labels_remain_unresolved(tmp_path,tables):
    discovery={'routes':[{'id':'MTABC_Q6','agency_id':'MTA NYCT','short_name':'R'},
                         {'id':'MTABC_other','agency_id':'MTA NYCT','short_name':'R'}],
               'stops':[{'id':'MTA_P','code':'P'},{'id':'MTA_PN','code':'PN'}]}
    output=tmp_path/'result.gz';report=retain_schedule(source(tmp_path,tables),output,mode='bus',discovery=discovery)
    assert report['crosswalk']['unresolved_routes']==['R']
    with database(tmp_path,output) as db:
        assert db.execute('SELECT public_id FROM entity_links WHERE entity_type="route"').fetchone()==(None,)
        assert db.execute('SELECT public_id FROM entity_links WHERE source_id="PN"').fetchone()==('MTA_PN',)


def test_service_time_parser_never_wraps_hours():
    assert seconds('49:01:02')==176462 and seconds('') is None
    with pytest.raises(ValueError):seconds('10:61:00')


def test_cli_publishes_manifest_after_full_validation(tmp_path,tables):
    import subprocess,json
    archive=source(tmp_path,tables);output=tmp_path/'set'
    script=Path(__file__).parents[1]/'scripts/import_schedules.py'
    command=[sys.executable,str(script),'--feed','subway='+str(archive),'--output',str(output)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    manifest=json.loads((output/'manifest.json').read_text())
    assert manifest['feeds']['subway']['counts']['stop_times']==2
    cache=tmp_path/'archives';cache.mkdir()
    import shutil
    shutil.copyfile(archive,cache/'gtfs_subway.zip')
    replay=subprocess.run([sys.executable,str(script),'--from-manifest',str(output/'manifest.json'),
                           '--download-dir',str(cache),'--output',str(tmp_path/'replay')],capture_output=True,text=True)
    assert replay.returncode==0,replay.stderr
    previous={p.name:p.read_bytes() for p in output.iterdir()}
    tables['trips'][0]['service_id']='missing';source(tmp_path,tables)
    assert subprocess.run(command,capture_output=True).returncode!=0
    assert {p.name:p.read_bytes() for p in output.iterdir()}==previous
