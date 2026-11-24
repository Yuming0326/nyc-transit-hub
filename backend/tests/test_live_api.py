from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import time

import pytest
import requests
from google.transit import gtfs_realtime_pb2 as rt

from app import create_app
from app.services import feed_cache


def snapshot():
    feed = rt.FeedMessage()
    feed.header.gtfs_realtime_version = '2.0'
    feed.header.timestamp = int(time.time())
    update = feed.entity.add(id='train').trip_update
    update.trip.trip_id = 'live-test'
    update.trip.route_id = 'R'
    update.stop_time_update.add(stop_id='R20N').arrival.time = int(time.time()) + 300
    alert = feed.entity.add(id='notice').alert
    alert.header_text.translation.add(text='Test service change', language='en')
    alert.informed_entity.add(route_id='R')
    return feed


def response_for(feed):
    return Mock(content=feed.SerializeToString())


@pytest.fixture
def live(monkeypatch):
    fetch = Mock(side_effect=lambda *args, **kwargs: response_for(snapshot()))
    monkeypatch.setattr(feed_cache.requests, 'get', fetch)
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live'})
    return app, app.test_client(), fetch


def test_live_catalog_and_arrivals_contract(live):
    app, client, fetch = live
    stations = client.get('/api/stations').json['stations']
    catalog = app.extensions['transit']['client'].catalog
    assert stations == catalog['stations']
    assert len(stations) > 4
    response = client.get('/api/stations/R20/arrivals')
    assert response.status_code == 200
    data = response.json
    assert set(data) == {'station_id', 'source', 'updated_at', 'arrivals'}
    assert data['source'] == 'mta' and data['station_id'] == 'R20'
    assert data['updated_at'].endswith('+00:00')
    assert data['arrivals'][0]['direction'] == 'Northbound'
    assert set(data['arrivals'][0]) == {'id', 'route_id', 'destination', 'direction', 'arrival_time'}


def test_invalid_station_never_calls_upstream(live):
    _, client, fetch = live
    assert client.get('/api/stations/unknown/arrivals').status_code == 404
    fetch.assert_not_called()


def test_shared_feed_cache_across_stations(live):
    _, client, fetch = live
    assert client.get('/api/stations/R20/arrivals').status_code == 200
    assert client.get('/api/stations/R21/arrivals').status_code == 200
    assert fetch.call_count == 1


def test_alert_filters_share_one_snapshot(live):
    _, client, fetch = live
    first = client.get('/api/alerts?route_id=r')
    assert first.status_code == 200 and first.json['source'] == 'mta'
    assert first.json['alerts'][0]['id'] == 'notice'
    assert client.get('/api/alerts?route_id=A').json['alerts'] == []
    assert fetch.call_count == 1
    assert client.get('/api/alerts?route_id=invalid').status_code == 400
    assert client.get('/api/alerts?route_id=').status_code == 400
    assert fetch.call_count == 1


@pytest.mark.parametrize('path', ['/api/stations/R20/arrivals', '/api/alerts'])
@pytest.mark.parametrize('failure', ['timeout', 'stale', 'invalid', 'http'])
def test_upstream_errors_return_503_and_are_not_cached(live, path, failure):
    _, client, fetch = live
    if failure == 'timeout':
        fetch.side_effect = requests.Timeout('private diagnostic')
    elif failure == 'stale':
        feed = snapshot()
        feed.header.timestamp = int(time.time()) - 1000
        fetch.side_effect = lambda *args, **kwargs: response_for(feed)
    elif failure == 'invalid':
        fetch.side_effect = lambda *args, **kwargs: Mock(content=b'invalid protobuf')
    else:
        response = response_for(snapshot())
        response.raise_for_status.side_effect = requests.HTTPError('private diagnostic')
        fetch.side_effect = lambda *args, _response=response, **kwargs: _response
    for _ in range(2):
        response = client.get(path)
        assert response.status_code == 503 and set(response.json) == {'error'}
        assert 'private diagnostic' not in response.json['error']
    assert fetch.call_count == 2
    fetch.side_effect = lambda *args, **kwargs: response_for(snapshot())
    assert client.get(path).json['source'] == 'mta'


def test_expired_cache_refetches(live, monkeypatch):
    _, client, fetch = live
    from app import cache
    monkeypatch.setattr(cache, 'monotonic', lambda: 100)
    assert client.get('/api/alerts').status_code == 200
    monkeypatch.setattr(cache, 'monotonic', lambda: 131)
    assert client.get('/api/alerts').status_code == 200
    assert fetch.call_count == 2


@pytest.mark.parametrize('path,age', [('/api/stations/R20/arrivals', 125),
                                     ('/api/alerts?route_id=R', 605)])
def test_cached_feed_is_rechecked_for_freshness(live, monkeypatch, path, age):
    _, client, fetch = live
    from app.services import mta_client
    now = time.time()
    assert client.get(path).status_code == 200
    monkeypatch.setattr(mta_client.time, 'time', lambda: now + age)
    assert client.get(path).status_code == 503
    assert fetch.call_count == 1


def test_concurrent_requests_share_fetch(live):
    app, _, fetch = live
    def request(_):
        with app.test_client() as client:
            return client.get('/api/stations/R20/arrivals').status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(request, range(8))) == [200] * 8
    assert fetch.call_count == 1


def test_apps_do_not_share_modes_or_cache(live):
    _, client, _ = live
    demo = create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client()
    assert demo.get('/api/stations/R20/arrivals').json['source'] == 'demo'
    assert len(demo.get('/api/stations').json['stations']) == 4
    assert client.get('/api/stations/R20/arrivals').json['source'] == 'mta'


def test_timeout_and_freshness_configuration():
    app = create_app({'TRANSIT_MODE': 'live', 'MTA_CONNECT_TIMEOUT_SECONDS': 1,
                      'MTA_READ_TIMEOUT_SECONDS': 2, 'MTA_MAX_AGE_SECONDS': 60,
                      'MTA_ALERTS_MAX_AGE_SECONDS': 300})
    client = app.extensions['transit']['client']
    assert client.timeout == (1, 2) and client.max_age == 60 and client.alerts_max_age == 300
    with pytest.raises(ValueError):
        create_app({'TRANSIT_MODE': 'typo'})
    with pytest.raises(ValueError):
        create_app({'MTA_READ_TIMEOUT_SECONDS': 0})
