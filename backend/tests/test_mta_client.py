from io import BytesIO
from zipfile import ZipFile
from unittest.mock import Mock

import pytest
import requests
from google.transit import gtfs_realtime_pb2 as rt
from app.services.mta_client import (MTAClient, MTAError, StaleFeedError, fetch_feed,
                                     normalize_arrivals, normalize_alerts)
from app.services.static_gtfs import build_catalog

NOW = 1800000000


def feed():
    result = rt.FeedMessage()
    result.header.gtfs_realtime_version = '2.0'
    result.header.timestamp = NOW
    return result


@pytest.fixture
def catalog():
    data = BytesIO()
    with ZipFile(data, 'w') as archive:
        archive.writestr('stops.txt', 'stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\nR20,Union Sq,40.7,-73.9,1,\nR20N,Union Sq,40.7,-73.9,0,R20\nR20S,Union Sq,40.7,-73.9,0,R20\nR01N,Astoria,40.8,-73.8,0,R01\nR01,Astoria,40.8,-73.8,1,\n')
        archive.writestr('routes.txt', 'route_id\nN\n')
        archive.writestr('trips.txt', 'route_id,trip_id\nN,static-trip\n')
        archive.writestr('stop_times.txt', 'trip_id,stop_id\nstatic-trip,R20N\nstatic-trip,R01N\n')
    return build_catalog(data.getvalue())


def test_static_mapping(catalog):
    assert catalog['stations'][1]['routes'] == ['N']
    assert catalog['stops']['R20S']['station_id'] == 'R20'
    assert catalog['stops']['R20N']['direction'] == 'Northbound'


def test_arrivals(catalog):
    f = feed()
    entity = f.entity.add(id='train')
    update = entity.trip_update
    update.trip.trip_id = 'realtime-trip'
    update.trip.route_id = 'N'
    stop = update.stop_time_update.add(stop_id='R20N')
    stop.departure.time = NOW + 120
    update.stop_time_update.add(stop_id='R01N').arrival.time = NOW + 600
    result = normalize_arrivals([f], 'R20', catalog, now=NOW)
    assert result['source'] == 'mta'
    assert result['updated_at'].endswith('+00:00')
    assert result['arrivals'][0]['destination'] == 'Astoria'
    assert result['arrivals'][0]['direction'] == 'Northbound'
    stop.schedule_relationship = rt.TripUpdate.StopTimeUpdate.SKIPPED
    assert normalize_arrivals([f], 'R20', catalog, now=NOW)['arrivals'] == []
    stop.schedule_relationship = rt.TripUpdate.StopTimeUpdate.NO_DATA
    assert normalize_arrivals([f], 'R20', catalog, now=NOW)['arrivals'] == []
    stop.schedule_relationship = rt.TripUpdate.StopTimeUpdate.SCHEDULED
    update.trip.schedule_relationship = rt.TripDescriptor.CANCELED
    assert normalize_arrivals([f], 'R20', catalog, now=NOW)['arrivals'] == []
    update.trip.schedule_relationship = rt.TripDescriptor.SCHEDULED
    stop.departure.time = NOW - 1
    assert normalize_arrivals([f], 'R20', catalog, now=NOW)['arrivals'] == []


def test_alert_periods_translation_and_filters():
    f = feed()
    a = f.entity.add(id='alert').alert
    a.header_text.translation.add(text='Español', language='es')
    a.header_text.translation.add(text='Sample delay', language='en-US')
    a.description_text.translation.add(text='Description')
    a.informed_entity.add(route_id='N')
    period = a.active_period.add(start=NOW-1, end=NOW+1)
    assert normalize_alerts(f, 'N', now=NOW)['alerts'][0]['header'] == 'Sample delay'
    assert normalize_alerts(f, 'R', now=NOW)['alerts'] == []
    assert normalize_alerts(f, now=period.end)['alerts'] == []
    a.ClearField('informed_entity')
    assert len(normalize_alerts(f, 'R', now=NOW)['alerts']) == 1


def test_fetch_timeout_decode_and_freshness():
    session = Mock()
    session.get.side_effect = requests.Timeout()
    with pytest.raises(MTAError):
        fetch_feed('https://example.test', session=session)
    session.get.side_effect = None
    session.get.return_value.content = b'not protobuf'
    with pytest.raises(MTAError):
        fetch_feed('https://example.test', session=session)
    f = feed()
    session.get.return_value.content = f.SerializeToString()
    assert fetch_feed('https://example.test', session=session, now=NOW).header.timestamp == NOW
    session.get.assert_called_with('https://example.test', timeout=(3.05, 10))
    for timestamp in (0, NOW-121, NOW+61):
        f.header.timestamp = timestamp
        session.get.return_value.content = f.SerializeToString()
        with pytest.raises(StaleFeedError):
            fetch_feed('https://example.test', session=session, now=NOW)
    f.header.timestamp = NOW
    f.header.incrementality = rt.FeedHeader.DIFFERENTIAL
    session.get.return_value.content = f.SerializeToString()
    with pytest.raises(MTAError):
        fetch_feed('https://example.test', session=session, now=NOW)


def test_client_unknown_station(catalog):
    with pytest.raises(ValueError):
        MTAClient(catalog).arrivals('unknown')


def test_client_feed_selection_and_failure(catalog, monkeypatch):
    from app.services import mta_client
    fetch = Mock(return_value=feed())
    monkeypatch.setattr(mta_client, 'fetch_feed', fetch)
    assert MTAClient(catalog).arrivals('R20')['arrivals'] == []
    assert fetch.call_count == 1
    assert fetch.call_args.args[0].endswith('nyct%2Fgtfs-nqrw')
    fetch.side_effect = MTAError('upstream unavailable')
    with pytest.raises(MTAError):
        MTAClient(catalog).arrivals('R20')


def test_http_error_is_not_empty_success():
    session = Mock()
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError('503')
    with pytest.raises(MTAError):
        fetch_feed('https://example.test', session=session, now=NOW)


@pytest.mark.parametrize('failure,diagnostic', [
    (requests.ConnectionError('private URL'), 'network/request failure (ConnectionError)'),
    (requests.ReadTimeout('private URL'), 'upstream timeout (ReadTimeout)'),
    (requests.HTTPError('private URL', response=Mock(status_code=503)), 'HTTP failure (status=503)'),
])
def test_request_diagnostics_distinguish_failures_without_private_details(failure, diagnostic):
    session = Mock()
    session.get.side_effect = failure
    with pytest.raises(MTAError, match=r'MTA') as caught:
        fetch_feed('https://example.test', session=session, now=NOW)
    assert diagnostic in str(caught.value)
    assert 'private' not in str(caught.value)
    assert caught.value.__cause__ is failure


def test_official_feed_group_regressions():
    from app.services.mta_client import FEED_ROUTES
    assert '7' in FEED_ROUTES['gtfs']
    assert 'FS' in FEED_ROUTES['gtfs-bdfm']
    assert 'H' in FEED_ROUTES['gtfs-ace']


def test_samples_match_api_contract():
    import json
    from pathlib import Path
    root = Path(__file__).parents[1] / 'app/data/samples'
    stations = json.loads((root / 'stations.json').read_text())
    assert set(stations) == {'stations'}
    assert all(set(s) == {'id', 'name', 'routes', 'latitude', 'longitude'}
               for s in stations['stations'])
    arrivals = json.loads((root / 'arrivals.json').read_text())
    assert set(arrivals) == {'station_id', 'source', 'updated_at', 'arrivals'}
    assert arrivals['source'] == 'demo'
    assert all(set(a) == {'id', 'route_id', 'destination', 'direction', 'arrival_time'}
               for a in arrivals['arrivals'])
    alerts = json.loads((root / 'alerts.json').read_text())
    assert set(alerts) == {'source', 'alerts'}
    assert alerts['source'] == 'demo'
    assert all(set(a) == {'id', 'header', 'description', 'route_ids'} for a in alerts['alerts'])
