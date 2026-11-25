from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.transit import gtfs_realtime_pb2 as rt

from app import create_app
from app.services.mta_client import FEED_ROUTES,MTAClient,MTAError,normalize_arrivals,normalize_alerts,translated_text
from app.services.subway_alerts import normalize_affected_alerts

NOW=1800000000


def feed(timestamp=NOW):
    f=rt.FeedMessage();f.header.gtfs_realtime_version='2.0';f.header.timestamp=timestamp
    return f


def catalog(routes):
    return {'stations':[{'id':'parent','name':'Station','routes':routes}],
            'stops':{'platformN':{'station_id':'parent','name':'Station','direction':'Northbound'},
                     'terminalS':{'station_id':'terminal','name':'Reported last stop','direction':'Southbound'}}}


def arrival(f,route='R'):
    e=f.entity.add(id=route);e.trip_update.trip.trip_id='trip-'+route;e.trip_update.trip.route_id=route
    e.trip_update.trip.start_date='20261125'
    s=e.trip_update.stop_time_update.add(stop_id='platformN',stop_sequence=1);s.arrival.time=NOW+100
    e.trip_update.stop_time_update.add(stop_id='terminalS',stop_sequence=2).arrival.time=NOW+300
    return e


@pytest.mark.parametrize('name,routes',list(FEED_ROUTES.items()))
def test_every_group_maps_to_its_official_url(monkeypatch,name,routes):
    from app.services import mta_client
    monkeypatch.setattr(mta_client.time,'time',lambda:NOW)
    f=feed();arrival(f,routes[0]);fetch=Mock(return_value=f)
    monkeypatch.setattr(mta_client,'fetch_feed',fetch)
    result=MTAClient(catalog([routes[0]])).arrivals('parent')
    assert fetch.call_count==1 and fetch.call_args.args[0].endswith('nyct%2F'+name)
    assert result['arrivals'][0]['route_id']==routes[0]
    assert result['arrivals'][0]['direction']=='Northbound'


def test_multi_group_oldest_timestamp_unique_trips_and_partial_failure(monkeypatch):
    from app.services import mta_client
    feeds=[]
    for route,age in [('A',2),('D',4),('R',6)]:
        f=feed(NOW-age);arrival(f,route);feeds.append(f)
    monkeypatch.setattr(mta_client.time,'time',lambda:NOW)
    fetch=Mock(side_effect=feeds);monkeypatch.setattr(mta_client,'fetch_feed',fetch)
    adapter=MTAClient(catalog(['A','D','R']))
    result=adapter.arrivals('parent')
    assert len(result['arrivals'])==3 and len({a['id'] for a in result['arrivals']})==3
    assert result['updated_at']==mta_client.utc(NOW-6)
    fetch.side_effect=[feeds[0],MTAError('Controlled group failure')]
    with pytest.raises(MTAError):adapter.arrivals('parent')


def test_arrival_unknown_platform_missing_absolute_time_deleted_entity_and_dedup():
    f=feed();e=arrival(f)
    e.trip_update.stop_time_update[0].stop_id='unmapped-platform'
    assert normalize_arrivals([f],'parent',catalog(['R']),now=NOW)['arrivals']==[]
    e.trip_update.stop_time_update[0].stop_id='platformN'
    e.trip_update.stop_time_update[0].ClearField('arrival')
    e.trip_update.stop_time_update[0].departure.delay=100
    assert normalize_arrivals([f],'parent',catalog(['R']),now=NOW)['arrivals']==[]
    e.trip_update.stop_time_update[0].departure.time=NOW+200
    assert len(normalize_arrivals([f,f],'parent',catalog(['R']),now=NOW)['arrivals'])==1
    e.is_deleted=True
    assert normalize_arrivals([f],'parent',catalog(['R']),now=NOW)['arrivals']==[]


def test_plain_english_wins_over_html():
    text=rt.TranslatedString();text.translation.add(language='en-html',text='<b>HTML</b>')
    text.translation.add(language='es',text='Spanish');text.translation.add(language='en-US',text='Regional')
    text.translation.add(language='en',text='Plain')
    assert translated_text(text)=='Plain'


def test_affected_entities_preserve_and_selectors_and_explicit_parent_mapping():
    f=feed();a=f.entity.add(id='notice').alert
    a.header_text.translation.add(language='en',text='Notice')
    a.informed_entity.add(route_id='R',stop_id='platformN')
    a.informed_entity.add(route_id='A',stop_id='unknown-stop')
    a.effect=rt.Alert.SIGNIFICANT_DELAYS
    detail=normalize_affected_alerts(f,catalog(['R']),now=NOW)['alerts'][0]
    assert detail['station_ids']==['parent']
    assert detail['stop_ids']==['platformN','unknown-stop']
    assert detail['unmapped_stop_ids']==['unknown-stop']
    assert detail['selectors']==[{'route_id':'R','stop_id':'platformN'},{'route_id':'A','stop_id':'unknown-stop'}]
    assert detail['impact']=='disruption' and detail['scope']=='stop'
    legacy=normalize_alerts(f,now=NOW)
    assert set(legacy['alerts'][0])=={'id','header','description','route_ids'}


def test_unknown_scope_missing_effect_and_period_boundaries():
    f=feed();a=f.entity.add(id='trip-specific').alert;a.informed_entity.add(agency_id='NYCT').trip.trip_id='trip'
    a.active_period.add(start=NOW,end=NOW+1)
    response=normalize_affected_alerts(f,catalog(['R']),now=NOW)
    assert response['alerts'][0]['scope']=='unknown' and response['alerts'][0]['impact']=='unknown'
    assert normalize_affected_alerts(f,catalog(['R']),now=NOW+1)['alerts']==[]
    a.ClearField('active_period');a.ClearField('informed_entity')
    assert normalize_affected_alerts(f,catalog(['R']),now=NOW)['alerts'][0]['scope']=='unknown'


def test_stale_alert_at_http_boundary_remains_503(monkeypatch):
    from app.services import mta_client
    app=create_app({'TESTING':True,'TRANSIT_MODE':'live'})
    f=feed(NOW-601)
    app.extensions['transit']['client'].session=SimpleNamespace(get=lambda *a,**k:SimpleNamespace(content=f.SerializeToString(),raise_for_status=lambda:None))
    monkeypatch.setattr(mta_client.time,'time',lambda:NOW)
    response=app.test_client().get('/api/alerts?route_id=R')
    assert response.status_code==503 and set(response.json)=={'error'}


def test_observed_subway_agency_and_direction_preserve_scope():
    f=feed();a=f.entity.add(id='source').alert
    a.informed_entity.add(agency_id='MTASBWY',route_id='R',stop_id='platformN',direction_id=1)
    detail=normalize_affected_alerts(f,catalog(['R']),now=NOW)['alerts'][0]
    assert detail['scope']=='stop' and detail['selectors'][0]['direction_id']==1
    a.ClearField('informed_entity');a.informed_entity.add(agency_id='MTASBWY')
    assert normalize_affected_alerts(f,catalog(['R']),now=NOW)['alerts'][0]['scope']=='network'


def test_other_agency_cannot_reuse_a_subway_stop_identity():
    f=feed();a=f.entity.add(id='other-agency').alert
    a.informed_entity.add(agency_id='OTHER',route_id='R',stop_id='platformN')
    row=normalize_affected_alerts(f,catalog(['R']),now=NOW)['alerts'][0]
    assert row['station_ids']==[] and row['unmapped_stop_ids']==['platformN'] and row['scope']=='unknown'


def test_affected_alert_client_enforces_freshness(monkeypatch):
    from app.services import mta_client
    monkeypatch.setattr(mta_client.time,'time',lambda:NOW)
    f=feed();a=f.entity.add(id='notice').alert;a.informed_entity.add(stop_id='platformN')
    response=SimpleNamespace(content=f.SerializeToString(),raise_for_status=lambda:None)
    client=MTAClient(catalog(['R']),session=SimpleNamespace(get=lambda *args,**kwargs:response))
    assert client.affected_alerts()['alerts'][0]['station_ids']==['parent']
    f.header.timestamp=NOW-601;response.content=f.SerializeToString()
    with pytest.raises(MTAError):client.affected_alerts()
