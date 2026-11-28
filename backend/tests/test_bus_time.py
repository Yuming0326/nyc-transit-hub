"""Y10: Bus Time stop arrivals and vehicle positions (adapter + API), offline."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests

from app import create_app
from app.services.bus_time import BusInputError, BusNotFound, BusTimeClient, BusUnavailable, compass_bearing

STOP, OTHER_STOP = 'MTA_308214', 'MTA_308215'
ROUTE, OTHER_ROUTE = 'MTA NYCT_B63', 'MTA NYCT_B61'
CATALOG = {
    'routes': [{'id': ROUTE, 'agency_id': 'MTA NYCT', 'name': 'Bay Ridge - Cobble Hill', 'short_name': 'B63'},
               {'id': OTHER_ROUTE, 'agency_id': 'MTA NYCT', 'name': 'Park Slope', 'short_name': 'B61'}],
    'stops': [{'id': STOP, 'name': '5 AV/UNION ST', 'latitude': 40.677, 'longitude': -73.98, 'route_ids': [ROUTE]},
              {'id': OTHER_STOP, 'name': 'OTHER', 'latitude': 40.6, 'longitude': -73.9, 'route_ids': [OTHER_ROUTE]}],
    'route_stop_ids': {ROUTE: [STOP], OTHER_ROUTE: [OTHER_STOP]},
}


def iso(seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')


def visit(vehicle='MTA NYCT_7582', eta=300, direction='1', route=ROUTE, recorded=-10, stop=STOP, trip='T1'):
    call = {'StopPointRef': stop, 'Extensions': {'Distances': {'PresentableDistance': '2 stops away'}}}
    if eta is not None:
        call['ExpectedArrivalTime'] = iso(eta)
    return {'RecordedAtTime': iso(recorded), 'MonitoredVehicleJourney': {
        'LineRef': route, 'DirectionRef': direction, 'PublishedLineName': ['B63'],
        'DestinationName': ['BAY RIDGE SHORE RD'], 'VehicleRef': vehicle, 'MonitoredCall': call,
        'FramedVehicleJourneyRef': {'DataFrameRef': '2026-11-25', 'DatedVehicleJourneyRef': trip}}}


def activity(vehicle='MTA NYCT_7582', lat=40.675, lon=-73.983, bearing=90.0, direction='1', route=ROUTE, recorded=-15):
    journey = {'LineRef': route, 'DirectionRef': direction, 'DestinationName': ['BAY RIDGE SHORE RD'],
               'VehicleRef': vehicle, 'Bearing': bearing, 'VehicleLocation': {'Latitude': lat, 'Longitude': lon}}
    return {'RecordedAtTime': iso(recorded) if recorded is not None else None, 'MonitoredVehicleJourney': journey}


def body(kind, items, age=5, **delivery):
    field = 'MonitoredStopVisit' if kind == 'StopMonitoringDelivery' else 'VehicleActivity'
    return {'Siri': {'ServiceDelivery': {kind: [{'ResponseTimestamp': iso(-age), field: items, **delivery}]}}}


def stops(items, **kwargs):
    return body('StopMonitoringDelivery', items, **kwargs)


def vehicles(items, **kwargs):
    return body('VehicleMonitoringDelivery', items, **kwargs)


def session(payload=None, status=200, error=None):
    response = Mock(status_code=status)
    response.json.return_value = payload
    return Mock(get=Mock(side_effect=error, return_value=response))


def client(payload=None, **kwargs):
    http = kwargs.pop('http', None) or session(payload)
    return BusTimeClient(CATALOG, 'secret', session=http, **kwargs), http


# --- adapter: arrivals -------------------------------------------------------

def test_arrival_contract_fields_and_request():
    adapter, http = client(stops([visit()]))
    result = adapter.arrivals(STOP)
    assert set(result) == {'mode', 'source', 'stop_id', 'updated_at', 'arrivals'}
    assert result['source'] == 'mta' and result['stop_id'] == STOP
    row = result['arrivals'][0]
    assert set(row) == {'id', 'route_id', 'route_name', 'direction_id', 'destination', 'arrival_time',
                        'vehicle_id', 'recorded_at', 'distance_text'}
    assert (row['route_id'], row['route_name'], row['direction_id'], row['destination'], row['distance_text']) == \
        (ROUTE, 'B63', '1', 'BAY RIDGE SHORE RD', '2 stops away')
    params = http.get.call_args.kwargs['params']
    assert params['OperatorRef'] == 'MTA' and params['MonitoringRef'] == '308214' and params['version'] == '2'
    assert http.get.call_args.kwargs['allow_redirects'] is False


def test_arrival_ids_are_stable_and_sorted_timed_first():
    payload = stops([visit('v3', eta=None, trip='c'), visit('v2', eta=600, trip='b'), visit('v1', eta=120, trip='a')])
    first = client(payload)[0].arrivals(STOP)['arrivals']
    second = client(payload)[0].arrivals(STOP)['arrivals']
    assert [a['vehicle_id'] for a in first] == ['v1', 'v2', 'v3']
    assert first[2]['arrival_time'] is None and first[2]['distance_text'] == '2 stops away'
    assert [a['id'] for a in first] == [a['id'] for a in second]


def test_arrival_filters_and_departed_predictions():
    payload = stops([visit('a', direction='0', trip='a'), visit('b', direction='1', trip='b'),
                     visit('gone', eta=-60, trip='c')])
    assert [a['vehicle_id'] for a in client(payload)[0].arrivals(STOP, ROUTE, '0')['arrivals']] == ['a']
    assert {a['vehicle_id'] for a in client(payload)[0].arrivals(STOP)['arrivals']} == {'a', 'b'}


def test_invalid_visits_omitted_but_all_invalid_is_unavailable():
    mixed = stops([visit('ok', trip='a'), visit('stale', recorded=-900, trip='b'),
                   visit('wrong-stop', stop=OTHER_STOP, trip='c'), visit('off-route', route=OTHER_ROUTE, trip='d')])
    assert [a['vehicle_id'] for a in client(mixed)[0].arrivals(STOP)['arrivals']] == ['ok']
    with pytest.raises(BusUnavailable):
        client(stops([visit(recorded=-900)]))[0].arrivals(STOP)


def test_distance_text_uses_v2_arrival_proximity_text():
    item = visit(eta=None)
    call = item['MonitoredVehicleJourney']['MonitoredCall']
    del call['Extensions']
    call['ArrivalProximityText'] = '1.2 miles away'
    assert client(stops([item]))[0].arrivals(STOP)['arrivals'][0]['distance_text'] == '1.2 miles away'


def test_valid_empty_delivery_is_empty_success():
    assert client(stops([]))[0].arrivals(STOP)['arrivals'] == []


@pytest.mark.parametrize('args,error', [
    (('308214',), BusInputError), (('MTA_999999999',), BusNotFound),
    ((STOP, 'B63'), BusInputError), ((STOP, 'MTA NYCT_X99'), BusNotFound),
    ((STOP, OTHER_ROUTE), BusInputError), ((STOP, None, 'north'), BusInputError)])
def test_arrival_request_validation_happens_before_upstream(args, error):
    adapter, http = client(stops([]))
    with pytest.raises(error):
        adapter.arrivals(*args)
    http.get.assert_not_called()


# --- adapter: vehicles -------------------------------------------------------

@pytest.mark.parametrize('source,expected', [(0, 90), (90, 0), (180, 270), (270, 180), (359.5, 90.5), (None, None)])
def test_bearing_converted_to_clockwise_from_north(source, expected):
    assert compass_bearing(source) == expected


def test_vehicle_contract_fields_and_bearing():
    adapter, http = client(vehicles([activity()]))
    result = adapter.vehicles(ROUTE)
    assert result['mode'] == 'bus' and result['source'] == 'mta'
    assert result['vehicles'] == [{'id': 'MTA NYCT_7582', 'route_id': ROUTE, 'direction_id': '1',
                                   'destination': 'BAY RIDGE SHORE RD', 'latitude': 40.675, 'longitude': -73.983,
                                   'bearing': 0.0, 'recorded_at': result['vehicles'][0]['recorded_at']}]
    assert http.get.call_args.kwargs['params']['LineRef'] == ROUTE
    assert http.get.call_args.args[0].endswith('/api/siri/vehicle-monitoring.json')
    assert http.get.call_args.kwargs['params']['version'] == '1'


def test_vehicle_rejections_filters_and_latest_position():
    payload = vehicles([activity('a', direction='0'), activity('b', recorded=-60, lat=40.6), activity('b', lat=40.7),
                        activity('stale', recorded=-900), activity('no-time', recorded=None),
                        activity('null-island', lat=0, lon=0), activity('far', lat=95), activity('bad-bearing', bearing=400)])
    result = client(payload)[0].vehicles(ROUTE)['vehicles']
    assert [(v['id'], v['latitude']) for v in result] == [('a', 40.675), ('b', 40.7)]
    assert [v['id'] for v in client(payload)[0].vehicles(ROUTE, '0')['vehicles']] == ['a']
    with pytest.raises(BusUnavailable):
        client(vehicles([activity(recorded=-900)]))[0].vehicles(ROUTE)
    assert client(vehicles([]))[0].vehicles(ROUTE)['vehicles'] == []


@pytest.mark.parametrize('args,error', [((None,), BusInputError), (('MTA NYCT_X99',), BusNotFound),
                                        ((ROUTE, '2'), BusInputError)])
def test_vehicle_request_validation(args, error):
    adapter, http = client(vehicles([]))
    with pytest.raises(error):
        adapter.vehicles(*args)
    http.get.assert_not_called()


# --- adapter: upstream failures and caching ----------------------------------

@pytest.mark.parametrize('kwargs', [
    {'http': session(error=requests.Timeout('key=secret'))},
    {'http': session(error=requests.ConnectionError('key=secret'))},
    {'http': session({}, status=403)}, {'http': session({'unexpected': True})},
    {'http': session(stops([], age=900))}, {'http': session(stops([], age=-300))},
    {'http': session(stops([], ErrorCondition={'OtherError': {'ErrorText': 'API key not authorized'}}))},
    {'http': session({'Siri': {'ServiceDelivery': {'StopMonitoringDelivery': []}}})}])
def test_upstream_failures_are_unavailable_without_leaking_key(kwargs):
    adapter, _ = client(**kwargs)
    with pytest.raises(BusUnavailable) as caught:
        adapter.arrivals(STOP)
    assert 'secret' not in str(caught.value)


def test_missing_key_is_unavailable_without_request():
    http = session(stops([]))
    with pytest.raises(BusUnavailable):
        BusTimeClient(CATALOG, '', session=http).arrivals(STOP)
    http.get.assert_not_called()


def test_success_cached_but_failures_not_cached():
    adapter, http = client(stops([visit()]))
    adapter.arrivals(STOP)
    adapter.arrivals(STOP)
    assert http.get.call_count == 1
    failing = session(error=requests.Timeout())
    adapter, _ = client(http=failing)
    for _ in range(2):
        with pytest.raises(BusUnavailable):
            adapter.arrivals(STOP)
    assert failing.get.call_count == 2


# --- API ---------------------------------------------------------------------

def live(payload=None, key='secret', http=None):
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live', 'MTA_BUS_TIME_API_KEY': key, 'BUS_CATALOG': CATALOG})
    app.extensions['bus']['client'].session = http or session(payload)
    return app.test_client()


def test_live_endpoints():
    response = live(stops([visit()])).get('/api/bus/stops/MTA_308214/arrivals?route_id=MTA%20NYCT_B63&direction_id=1')
    assert response.status_code == 200 and response.json['source'] == 'mta' and len(response.json['arrivals']) == 1
    response = live(vehicles([activity()])).get('/api/bus/vehicles?route_id=MTA%20NYCT_B63')
    assert response.status_code == 200 and response.json['vehicles'][0]['bearing'] == 0.0


@pytest.mark.parametrize('path,status', [
    ('/api/bus/stops/MTA_999999999/arrivals', 404), ('/api/bus/stops/308214/arrivals', 400),
    ('/api/bus/stops/MTA_308214/arrivals?direction_id=north', 400),
    ('/api/bus/stops/MTA_308214/arrivals?route_id=MTA%20NYCT_B63&route_id=MTA%20NYCT_B61', 400),
    ('/api/bus/vehicles', 400), ('/api/bus/vehicles?route_id=MTA%20NYCT_X99', 404)])
def test_live_request_errors(path, status):
    response = live(stops([])).get(path)
    assert response.status_code == status and set(response.json) == {'error'}


def test_live_failures_are_503_without_demo_fallback():
    for client_ in (live(key=''), live(http=session(error=requests.Timeout()))):
        response = client_.get('/api/bus/stops/MTA_308214/arrivals')
        assert response.status_code == 503
        assert response.json == {'error': 'Live bus data is temporarily unavailable. Please retry.'}


def test_demo_endpoints_are_labeled_and_bounded():
    demo = create_app({'TESTING': True, 'TRANSIT_MODE': 'demo'}).test_client()
    arrivals = demo.get('/api/bus/stops/MTA_308214/arrivals?direction_id=0').json
    assert arrivals['source'] == 'demo' and [a['direction_id'] for a in arrivals['arrivals']] == ['0']
    assert demo.get('/api/bus/vehicles?route_id=MTA%20NYCT_B63').json['source'] == 'demo'
    assert demo.get('/api/bus/stops/MTA_1/arrivals').status_code == 404
    assert demo.get('/api/bus/vehicles').status_code == 400


def test_bus_freshness_configuration_validated():
    with pytest.raises(ValueError):
        create_app({'TESTING': True, 'BUS_MAX_AGE_SECONDS': 0})
