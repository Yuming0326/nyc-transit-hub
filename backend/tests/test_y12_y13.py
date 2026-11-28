"""Y12 bus request hardening and Y13 public discovery/detail/map/alert endpoints (offline)."""
import json
import threading
import time
from unittest.mock import Mock

import pytest
import requests

from app import create_app
from app.cache import TTLCache
from app.services import map_service
from app.services.mta_client import MTAError
from tests.test_bus_time import CATALOG, ROUTE, STOP, activity, session, stops, vehicles, visit


# --- Y12: cache ----------------------------------------------------------------

def test_cache_shares_one_load_per_key_without_blocking_other_keys():
    cache, calls, release = TTLCache(), [], threading.Event()

    def slow():
        calls.append('slow')
        release.wait(2)
        return 'slow'

    results = []
    workers = [threading.Thread(target=lambda: results.append(cache.get_or_load('a', 30, slow))) for _ in range(3)]
    for worker in workers:
        worker.start()
    time.sleep(0.05)
    started = time.monotonic()
    assert cache.get_or_load('b', 30, lambda: 'fast') == 'fast'
    assert time.monotonic() - started < 0.5  # 'b' is not blocked by the slow 'a' load
    release.set()
    for worker in workers:
        worker.join()
    assert results == ['slow'] * 3 and calls == ['slow']


def test_cache_failures_not_cached_evict_and_prune():
    cache = TTLCache()
    with pytest.raises(RuntimeError):
        cache.get_or_load('k', 30, Mock(side_effect=RuntimeError))
    assert cache.get_or_load('k', 30, lambda: 1) == 1
    cache.evict('k')
    assert cache.get_or_load('k', 30, lambda: 2) == 2
    cache.get_or_load('old', 0, lambda: 'x')
    cache.get_or_load('new', 30, lambda: 'y')
    assert 'old' not in cache._values


# --- Y12: bus request behavior ------------------------------------------------

def live_app(http, catalog=CATALOG, **config):
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live', 'MTA_BUS_TIME_API_KEY': 'secret',
                      'BUS_CATALOG': catalog, **config})
    app.extensions['bus']['client'].session = http
    return app


def test_filtered_views_share_one_upstream_request_per_stop_and_route():
    http = session(stops([visit('a', direction='0', trip='a'), visit('b', direction='1', trip='b')]))
    client = live_app(http).test_client()
    assert len(client.get('/api/bus/stops/MTA_308214/arrivals').json['arrivals']) == 2
    assert len(client.get('/api/bus/stops/MTA_308214/arrivals?direction_id=0').json['arrivals']) == 1
    both = client.get('/api/bus/stops/MTA_308214/arrivals?route_id=MTA%20NYCT_B63&direction_id=1')
    assert len(both.json['arrivals']) == 1
    assert http.get.call_count == 1 and 'DirectionRef' not in http.get.call_args.kwargs['params']
    http = session(vehicles([activity('a', direction='0'), activity('b', direction='1')]))
    client = live_app(http).test_client()
    for query in ('', '&direction_id=0', '&direction_id=1'):
        assert client.get(f'/api/bus/vehicles?route_id=MTA%20NYCT_B63{query}').status_code == 200
    assert http.get.call_count == 1


def test_unavailable_reason_is_logged_without_key(caplog):
    client = live_app(session(error=requests.Timeout('https://x/?key=secret'))).test_client()
    assert client.get('/api/bus/stops/MTA_308214/arrivals').status_code == 503
    assert 'timeout' in caplog.text and 'secret' not in caplog.text
    client = live_app(session({}, status=403)).test_client()
    client.get('/api/bus/stops/MTA_308214/arrivals')
    assert 'HTTP 403' in caplog.text


def test_timeouts_come_from_configuration():
    http = session(stops([]))
    live_app(http, MTA_CONNECT_TIMEOUT_SECONDS=1.5, MTA_READ_TIMEOUT_SECONDS=4).test_client() \
        .get('/api/bus/stops/MTA_308214/arrivals')
    assert http.get.call_args.kwargs['timeout'] == (1.5, 4.0)


# --- Y13: catalog discovery/detail ----------------------------------------------

@pytest.fixture(scope='module')
def live():
    return create_app({'TESTING': True, 'TRANSIT_MODE': 'live'}).test_client()


def test_station_detail(live):
    data = live.get('/api/stations/R20').json
    assert data['station']['id'] == 'R20' and data['source'] == 'mta' and data['updated_at']
    assert set(data['station']) == {'id', 'name', 'routes', 'latitude', 'longitude'}
    assert live.get('/api/stations/nope').status_code == 404
    demo = create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client().get('/api/stations/R20').json
    assert demo['source'] == 'demo' and demo['station']['id'] == 'R20'


def test_subway_routes(live):
    data = live.get('/api/subway/routes?search=broadway').json
    assert data['mode'] == 'subway' and data['source'] == 'mta' and data['updated_at']
    assert data['routes'] and all(set(r) == {'id', 'name', 'short_name'} for r in data['routes'])
    assert {r['id'] for r in data['routes']} >= {'1', 'R'}
    assert live.get('/api/subway/routes?search=zzzz').json['routes'] == []
    detail = live.get('/api/subway/routes/R').json
    assert detail['route']['id'] == 'R' and any(s['id'] == 'R20' for s in detail['stations'])
    assert all('R' in s['routes'] for s in detail['stations'])
    assert live.get('/api/subway/routes/ZZ').status_code == 404


def test_bus_routes_and_stops(live):
    data = live.get('/api/bus/routes?search=b63').json
    assert set(data) == {'mode', 'source', 'routes'} and data['source'] == 'mta'
    assert [r['id'] for r in data['routes']] == ['MTA NYCT_B63']
    detail = live.get('/api/bus/routes/MTA%20NYCT_B63').json
    assert detail['route']['short_name'] == 'B63' and detail['updated_at']
    assert any(s['id'] == 'MTA_308214' for s in detail['stops'])
    assert all(set(s) == {'id', 'name', 'latitude', 'longitude'} for s in detail['stops'])
    assert live.get('/api/bus/routes/MTABC_Q53+').status_code == 200
    assert live.get('/api/bus/routes/MTA%20NYCT_X999').status_code == 404
    found = live.get('/api/bus/stops?route_id=MTA%20NYCT_B63&search=union').json
    assert found['route_id'] == 'MTA NYCT_B63' and any(s['id'] == 'MTA_308214' for s in found['stops'])
    assert live.get('/api/bus/stops?route_id=MTA%20NYCT_B63&search=308214').json['stops'][0]['id'] == 'MTA_308214'
    assert live.get('/api/bus/stops').status_code == 400
    assert live.get('/api/bus/stops?route_id=MTA%20NYCT_X999').status_code == 404
    stop = live.get('/api/bus/stops/MTA_308214').json
    assert stop['stop']['name'] == '5 AV/UNION ST' and stop['route_ids'] == ['MTA NYCT_B63']
    assert live.get('/api/bus/stops/MTA_1').status_code == 404


def test_catalog_endpoints_unavailable_in_demo():
    demo = create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client()
    for path in ('/api/subway/routes', '/api/bus/routes', '/api/bus/stops/MTA_308214',
                 '/api/bus/routes/MTA%20NYCT_B63'):
        response = demo.get(path)
        assert response.status_code == 503 and set(response.json) == {'error'}


# --- Y13: bus map ----------------------------------------------------------------

def test_bus_map_route_bbox_and_stops(live):
    data = live.get('/api/map?mode=bus&route_id=MTA%20NYCT_B63').json
    assert data['mode'] == 'bus' and data['source'] == 'mta' and data['stations'] == []
    features = data['geometry']['features']
    assert features and all(f['properties']['route_id'] == 'MTA NYCT_B63' for f in features)
    assert any(s['id'] == 'MTA_308214' for s in data['stops'])
    boxed = live.get('/api/map?mode=bus&route_id=MTA%20NYCT_B63&bbox=-73.99,40.67,-73.97,40.68').json
    assert 0 < len(boxed['stops']) < len(data['stops'])
    assert all(-73.99 <= s['longitude'] <= -73.97 and 40.67 <= s['latitude'] <= 40.68 for s in boxed['stops'])
    empty = live.get('/api/map?mode=bus&route_id=MTA%20NYCT_B63&bbox=10,10,11,11').json
    assert empty['geometry']['features'] == [] and empty['stops'] == []


def test_bus_map_rejects_mismatched_artifact(monkeypatch, tmp_path):
    path = tmp_path / 'geometry.json'
    path.write_text(json.dumps({'type': 'FeatureCollection', 'metadata': {'imported_at': 'other'}, 'features': []}))
    monkeypatch.setattr(map_service, 'BUS_GEOMETRY_PATH', path)
    client = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'}).test_client()
    assert client.get('/api/map?mode=bus').status_code == 503


# --- Y13: /api/transit/alerts ---------------------------------------------------

def subway_alert(alert_id, routes, stations, scope):
    return {'id': alert_id, 'header': 'h', 'description': 'd', 'route_ids': routes, 'station_ids': stations,
            'stop_ids': [], 'scope': scope, 'impact': 'unknown', 'selectors': [], 'unmapped_stop_ids': []}


SUBWAY_ALERTS = {'mode': 'subway', 'source': 'mta', 'updated_at': '2026-11-25T14:00:00+00:00', 'alerts': [
    subway_alert('net', [], [], 'network'), subway_alert('r-route', ['R'], [], 'route'),
    subway_alert('r20-stop', ['R'], ['R20'], 'stop'), subway_alert('a-route', ['A'], [], 'route')]}


def live_alerts(monkeypatch, subway=SUBWAY_ALERTS):
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})
    monkeypatch.setattr(app.extensions['transit']['client'], 'affected_alerts', lambda: subway)
    return app


def ids(response):
    return sorted(a['id'] for a in response.json['alerts'])


def test_subway_transit_alerts(monkeypatch):
    client = live_alerts(monkeypatch).test_client()
    everything = client.get('/api/transit/alerts?mode=subway')
    assert everything.json['coverage'] == 'route' and len(everything.json['alerts']) == 4
    assert set(everything.json['alerts'][0]) == {'id', 'header', 'description', 'route_ids', 'station_ids',
                                                 'stop_ids', 'scope', 'impact'}
    assert ids(client.get('/api/transit/alerts?mode=subway&route_id=R')) == ['net', 'r-route', 'r20-stop']
    station = client.get('/api/transit/alerts?mode=subway&station_id=R20')
    assert ids(station) == ['net', 'r-route', 'r20-stop'] and station.json['coverage'] == 'route'
    assert client.get('/api/transit/alerts?mode=subway&station_id=R20&route_id=A').status_code == 400
    assert client.get('/api/transit/alerts?mode=subway&route_id=ZZ').status_code == 404
    assert client.get('/api/transit/alerts?mode=subway&station_id=nope').status_code == 404


def test_subway_station_exact_coverage(monkeypatch):
    only_stop = {**SUBWAY_ALERTS, 'alerts': [SUBWAY_ALERTS['alerts'][2]]}
    response = live_alerts(monkeypatch, only_stop).test_client().get('/api/transit/alerts?mode=subway&station_id=R20')
    assert response.json['coverage'] == 'stop' and ids(response) == ['r20-stop']


def test_bus_transit_alerts(monkeypatch):
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})
    calls = []

    def fake(route_id=None, stop_id=None, **_):
        calls.append((route_id, stop_id))
        return {'mode': 'bus', 'source': 'mta', 'updated_at': 'now', 'coverage': 'route', 'alerts': [
            {'id': 'x', 'header': 'h', 'description': 'd', 'route_ids': [ROUTE], 'station_ids': [], 'stop_ids': [],
             'scope': 'route', 'impact': 'unknown', 'targets': [], 'selectors': [], 'unmapped_route_ids': [],
             'unmapped_stop_ids': []}]}
    monkeypatch.setattr(app.extensions['bus']['alerts'], 'alerts', fake)
    client = app.test_client()
    response = client.get('/api/transit/alerts?mode=bus&route_id=MTA%20NYCT_B63&stop_id=MTA_308214')
    assert response.status_code == 200 and 'targets' not in response.json['alerts'][0]
    assert calls == [(ROUTE, STOP)]
    for path, status in [('/api/transit/alerts?mode=bus&route_id=MTA%20NYCT_X999', 404),
                         ('/api/transit/alerts?mode=bus&stop_id=MTA_1', 404),
                         ('/api/transit/alerts?mode=bus&stop_id=308214', 400),
                         ('/api/transit/alerts?mode=bus&route_id=B63', 400),
                         ('/api/transit/alerts?mode=bus&station_id=R20', 400),
                         ('/api/transit/alerts?mode=subway&stop_id=MTA_308214', 400),
                         ('/api/transit/alerts?mode=bus&route_id=MTABC_Q53%2B&stop_id=MTA_308214', 400),
                         ('/api/transit/alerts', 400), ('/api/transit/alerts?mode=ferry', 400),
                         ('/api/transit/alerts?mode=bus&mode=bus', 400)]:
        assert client.get(path).status_code == status, path
    assert len(calls) == 1  # invalid requests never reach upstream


def test_transit_alert_failures_are_503(monkeypatch):
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})
    monkeypatch.setattr(app.extensions['transit']['client'], 'affected_alerts', Mock(side_effect=MTAError('down')))
    monkeypatch.setattr(app.extensions['bus']['alerts'], 'alerts', Mock(side_effect=MTAError('down')))
    client = app.test_client()
    for mode in ('subway', 'bus'):
        response = client.get(f'/api/transit/alerts?mode={mode}')
        assert response.status_code == 503 and set(response.json) == {'error'}


def test_transit_alerts_demo_labeled():
    demo = create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client()
    data = demo.get('/api/transit/alerts?mode=bus').json
    assert data['source'] == 'demo' and data['alerts'][0]['route_ids'] == ['MTA NYCT_B63']
    assert demo.get('/api/transit/alerts?mode=subway&route_id=A').json['alerts'] == []
