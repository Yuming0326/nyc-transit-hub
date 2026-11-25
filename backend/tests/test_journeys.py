"""Y19-Y25: schedule-based journey planning and POST /api/journeys."""
import csv
from io import StringIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from app import create_app
from app.services.journey_planner import (JourneyInputError, JourneyPlanner, TransferUnavailable,
                                          BUS_WALK_BUFFER_S, STATION_WALK_BUFFER_S)
from app.services.schedule_import import retain_schedule
from app.services.schedule_service import EntityNotFound
from app.services.schedule_store import ScheduleStore, ScheduleUnavailable

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
WHEN = '2026-11-25T13:00:00Z'          # Wednesday 08:00 in New York (EST)


def calendar(service_id, days):
    return {'service_id': service_id, **{d: '1' if d in days else '0' for d in DAYS},
            'start_date': '20261101', 'end_date': '20270515'}


def times(trip, *stops):
    return [{'trip_id': trip, 'stop_id': s, 'stop_sequence': str(i + 1), 'arrival_time': t, 'departure_time': t,
             'pickup_type': p, 'drop_off_type': '0'} for i, (s, t, p) in enumerate(stops)]


def go(trip, *stops):
    return times(trip, *[(s, t, '0') for s, t in stops])


# Parent stations with platform children; latitude 0.001 deg ~ 111 m.
STATIONS = {'A': (40.70, -73.99), 'B': (40.72, -73.99), 'C': (40.74, -73.99), 'D': (40.76, -73.99),
            'E': (40.72, -73.98), 'F': (40.72, -73.97), 'G': (40.80, -73.90), 'H': (40.721, -73.99)}
SUBWAY = {
    'agency': [{'agency_id': 'MTA NYCT', 'agency_timezone': 'America/New_York'}],
    'routes': [{'route_id': r, 'agency_id': 'MTA NYCT', 'route_short_name': r} for r in ('L1', 'L2', 'L3', 'L4', 'L5')],
    'stops': ([{'stop_id': s, 'stop_lat': str(c[0]), 'stop_lon': str(c[1]), 'parent_station': ''}
               for s, c in STATIONS.items()]
              + [{'stop_id': s + 'N', 'stop_lat': str(c[0]), 'stop_lon': str(c[1]), 'parent_station': s}
                 for s, c in STATIONS.items()]),
    'trips': [{'trip_id': t, 'route_id': r, 'service_id': 'Weekday', 'direction_id': '0'} for t, r in
              [('l1', 'L1'), ('l2fast', 'L2'), ('l2', 'L2'), ('l3', 'L3'), ('l4', 'L4'), ('l5', 'L5'),
               ('noboard', 'L4'), ('owl', 'L1')]],
    'stop_times': (go('l1', ('AN', '08:00:00'), ('BN', '08:10:00'), ('CN', '08:20:00'))
                   + go('l2fast', ('CN', '08:21:00'), ('DN', '08:28:00'))     # inside the 180 s change time
                   + go('l2', ('CN', '08:25:00'), ('DN', '08:35:00'))
                   + go('l3', ('AN', '08:05:00'), ('DN', '09:30:00'))         # slower, but no transfer
                   + go('l4', ('EN', '08:13:00'), ('FN', '08:20:00'))         # via the B->E transfer (120 s)
                   + go('l5', ('HN', '08:15:00'), ('GN', '08:30:00'))         # B->H is transfer_type 3
                   + times('noboard', ('FN', '09:00:00', '1'), ('AN', '09:10:00', '0'))
                   + go('owl', ('AN', '25:10:00'), ('BN', '25:20:00'))),
    'calendar': [calendar('Weekday', DAYS[:5])],
    'transfers': [{'from_stop_id': f, 'to_stop_id': t, 'transfer_type': k, 'min_transfer_time': m}
                  for f, t, k, m in [('C', 'C', '2', '180'), ('B', 'E', '2', '120'), ('B', 'H', '3', '')]],
    'feed_info': [{'feed_publisher_name': 'MTA', 'feed_start_date': '20261101', 'feed_end_date': '20270515'}],
}
# Bus stops: 101 and 102 are ~100 m apart; 100 is ~100 m from subway station D; 999 has no public ID.
BUS_STOPS = {'100': (40.7609, -73.99), '101': (40.65, -73.95), '102': (40.6509, -73.95), '103': (40.66, -73.95),
             '999': (40.648, -73.95), '104': (40.90, -73.80),
             '105': (40.91, -73.80)}
BUS = {
    'agency': [{'agency_id': 'MTA NYCT', 'agency_timezone': 'America/New_York'}],
    'routes': [{'route_id': r, 'agency_id': 'MTA NYCT', 'route_short_name': r} for r in ('B1', 'B2')],
    'stops': [{'stop_id': s, 'stop_lat': str(c[0]), 'stop_lon': str(c[1])} for s, c in BUS_STOPS.items()],
    'trips': [{'trip_id': t, 'route_id': r, 'service_id': 'Weekday', 'direction_id': '0'}
              for t, r in [('b1', 'B1'), ('b2', 'B2'), ('b3', 'B2')]],
    'stop_times': (go('b1', ('100', '08:00:00'), ('999', '08:03:00'), ('101', '08:05:00'))
                   + go('b2', ('102', '08:10:00'), ('103', '08:20:00'))
                   + go('b3', ('104', '08:00:00'), ('105', '08:10:00'))),
    'calendar': [calendar('Weekday', DAYS[:5])],
}
DISCOVERY = {'routes': [{'id': f'MTA NYCT_{r}', 'agency_id': 'MTA NYCT', 'short_name': r} for r in ('B1', 'B2')],
             'stops': [{'id': f'MTA_{s}', 'code': s} for s in ('100', '101', '102', '103', '104', '105')]}
BUS_CATALOG = ({f'MTA_{s}' for s in ('100', '101', '102', '103', '104', '105', '200')}, {'MTA NYCT_B1', 'MTA NYCT_B2'})


def archive(path, tables):
    with ZipFile(path, 'w') as bundle:
        for table, rows in tables.items():
            text = StringIO()
            writer = csv.DictWriter(text, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
            bundle.writestr(table + '.txt', text.getvalue())
    return path


@pytest.fixture(scope='module')
def schedule_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp('journey-schedules')
    feeds = {}
    for feed, tables, mode in (('subway', SUBWAY, 'subway'), ('b', BUS, 'bus')):
        report = retain_schedule(archive(directory / f'{feed}.zip', tables), directory / f'{feed}.sqlite.gz',
                                 mode=mode, discovery=DISCOVERY)
        feeds[feed] = {'artifact': f'{feed}.sqlite.gz', 'artifact_sha256': report['artifact_sha256']}
    (directory / 'manifest.json').write_text(json.dumps(
        {'imported_at': '2026-11-25T04:02:13+00:00', 'feeds': feeds}))
    catalog = directory / 'subway-catalog.json'
    catalog.write_text(json.dumps({'stations': [{'id': s} for s in [*STATIONS, 'Z9']]}))
    return directory


def make_planner(schedule_dir, **options):
    return JourneyPlanner(ScheduleStore(schedule_dir), subway_catalog=schedule_dir / 'subway-catalog.json',
                          bus_catalog=lambda: BUS_CATALOG, **options)


@pytest.fixture(scope='module')
def planner(schedule_dir):
    return make_planner(schedule_dir)


def station(i):
    return {'type': 'station', 'mode': 'subway', 'id': i}


def stop(i):
    return {'type': 'stop', 'mode': 'bus', 'id': i}


def plan(planner, origin, destination, modes=('subway',), when=WHEN):
    return planner.plan({'origin': origin, 'destination': destination, 'departure_time': when,
                         'modes': list(modes), 'optimization': 'fewest_transfers'})


def rides(journey):
    return [(leg['mode'], leg['route_id'], leg['from']['id'], leg['to']['id']) for leg in journey['legs']]


# --- Y19 directed connections ----------------------------------------------------------------------

def test_single_trip_follows_stop_order_and_reports_parent_stations(planner):
    result = plan(planner, station('A'), station('C'))
    assert result['timing_basis'] == 'schedule' and result['optimization'] == 'fewest_transfers'
    assert result['source'] == 'mta' and result['updated_at'] == '2026-11-25T04:02:13Z'
    assert result['no_path_reason'] is None
    journey = result['journeys'][0]
    assert journey['transfers'] == 0
    assert journey['departure_time'] == '2026-11-25T13:00:00Z' and journey['arrival_time'] == '2026-11-25T13:20:00Z'
    assert journey['duration_seconds'] == 1200
    assert journey['legs'] == [{'mode': 'subway', 'route_id': 'L1', 'from': station('A'), 'to': station('C'),
                                'departure_time': '2026-11-25T13:00:00Z', 'arrival_time': '2026-11-25T13:20:00Z',
                                'duration_seconds': 1200, 'stop_ids': ['A', 'B', 'C']}]


def test_direction_is_kept(planner):
    result = plan(planner, station('C'), station('A'))
    assert result['journeys'] == [] and result['no_path_reason'] == 'no_service_in_window'


def test_no_pickup_stop_is_not_a_boarding_point(planner):
    assert plan(planner, station('F'), station('A'))['journeys'] == []


def test_overnight_service_time_belongs_to_previous_service_day(planner):
    journey = plan(planner, station('A'), station('B'), when='2026-11-26T06:00:00Z')['journeys'][0]
    assert journey['departure_time'] == '2026-11-26T06:10:00Z'   # Wednesday 25:10:00


def test_search_window_is_24_hours(planner):
    # Weekday-only service: after Friday's trips the next one is Monday, more than 24 h away.
    result = plan(planner, station('A'), station('D'), when='2026-11-27T14:00:01Z')
    assert result['journeys'] == [] and result['no_path_reason'] == 'no_service_in_window'
    monday = plan(planner, station('A'), station('D'), when='2026-11-29T14:00:00Z')['journeys']
    assert [j['departure_time'] for j in monday] == ['2026-11-30T13:05:00Z', '2026-11-30T13:00:00Z']


# --- Y20 transfers ---------------------------------------------------------------------------------

def test_change_time_is_respected_and_fewest_transfers_comes_first(planner):
    journeys = plan(planner, station('A'), station('D'))['journeys']
    assert [(j['transfers'], j['arrival_time']) for j in journeys] == [
        (0, '2026-11-25T14:30:00Z'), (1, '2026-11-25T13:35:00Z')]
    assert rides(journeys[1]) == [('subway', 'L1', 'A', 'C'), ('subway', 'L2', 'C', 'D')]  # not l2fast at 08:21


def test_much_later_fewer_transfer_option_is_dropped(schedule_dir):
    journeys = plan(make_planner(schedule_dir, slack=1800), station('A'), station('D'))['journeys']
    assert [(j['transfers'], j['arrival_time']) for j in journeys] == [(1, '2026-11-25T13:35:00Z')]


def test_in_complex_transfer_becomes_a_walk_leg(planner):
    journey = plan(planner, station('A'), station('F'))['journeys'][0]
    assert rides(journey) == [('subway', 'L1', 'A', 'B'), ('walk', None, 'B', 'E'), ('subway', 'L4', 'E', 'F')]
    walk = journey['legs'][1]
    assert walk['duration_seconds'] == 120 and walk['stop_ids'] == []
    assert walk['departure_time'] == '2026-11-25T13:10:00Z' and journey['transfers'] == 1


def test_prohibited_transfer_is_never_used(planner):
    # H is only reachable from B through a transfer_type 3 row; it is also 111 m away.
    assert plan(planner, station('A'), station('G'))['journeys'] == []


def test_bus_walk_between_nearby_stops_and_unlinked_stop_is_hidden(planner):
    journey = plan(planner, stop('MTA_100'), stop('MTA_103'), modes=['bus'])['journeys'][0]
    assert rides(journey) == [('bus', 'MTA NYCT_B1', 'MTA_100', 'MTA_101'), ('walk', None, 'MTA_101', 'MTA_102'),
                              ('bus', 'MTA NYCT_B2', 'MTA_102', 'MTA_103')]
    assert journey['legs'][0]['stop_ids'] == ['MTA_100', 'MTA_101']     # source stop 999 is traversed, not listed
    walk = journey['legs'][1]['duration_seconds']
    assert BUS_WALK_BUFFER_S < walk < BUS_WALK_BUFFER_S + 150 and journey['transfers'] == 1


def test_cross_mode_walk_only_with_both_modes(planner, schedule_dir):
    journey = plan(planner, stop('MTA_100'), station('D'), modes=['bus', 'subway'])['journeys'][0]
    assert rides(journey) == [('walk', None, 'MTA_100', 'D')] and journey['transfers'] == 0
    assert journey['duration_seconds'] > STATION_WALK_BUFFER_S
    with pytest.raises(JourneyInputError):
        plan(planner, stop('MTA_100'), station('D'), modes=['bus'])
    with pytest.raises(TransferUnavailable):
        plan(make_planner(schedule_dir, cross_mode=False), stop('MTA_100'), station('D'), modes=['bus', 'subway'])


def test_cross_mode_journey_rides_both_modes(planner):
    journey = plan(planner, station('A'), stop('MTA_100'), modes=['subway', 'bus'])['journeys'][0]
    assert rides(journey) == [('subway', 'L3', 'A', 'D'), ('walk', None, 'D', 'MTA_100')]


# --- Y21 endpoints and errors ------------------------------------------------------------------------

def test_same_endpoint_is_zero_duration(planner):
    result = plan(planner, station('A'), station('A'))
    assert result['journeys'] == [{'id': result['journeys'][0]['id'], 'departure_time': WHEN, 'arrival_time': WHEN,
                                   'duration_seconds': 0, 'transfers': 0, 'legs': []}]


def test_unknown_and_unscheduled_endpoints(planner):
    with pytest.raises(EntityNotFound):
        plan(planner, station('NOPE'), station('A'))
    with pytest.raises(EntityNotFound):
        plan(planner, stop('MTA_1'), stop('MTA_100'), modes=['bus'])
    with pytest.raises(ScheduleUnavailable):            # in the catalogs but no scheduled trips
        plan(planner, station('Z9'), station('A'))
    with pytest.raises(ScheduleUnavailable):
        plan(planner, stop('MTA_200'), stop('MTA_100'), modes=['bus'])


def test_known_stop_without_connections_is_no_path(planner):
    result = plan(planner, stop('MTA_104'), stop('MTA_100'), modes=['bus'])
    assert result == {**result, 'journeys': [], 'no_path_reason': 'no_service_in_window'}


def test_date_outside_published_schedule_is_unavailable(planner):
    with pytest.raises(ScheduleUnavailable):
        plan(planner, station('A'), station('C'), when='2028-01-05T13:00:00Z')


@pytest.mark.parametrize('change', [
    {'origin': {'type': 'route', 'mode': 'subway', 'id': 'L1'}},
    {'origin': {'type': 'station', 'mode': 'bus', 'id': 'A'}},
    {'origin': {'type': 'station', 'mode': 'subway', 'id': ''}},
    {'destination': None},
    {'modes': []}, {'modes': ['subway', 'subway']}, {'modes': ['ferry']}, {'modes': 'subway'},
    {'departure_time': '2026-11-25T08:00:00'}, {'departure_time': 'tomorrow'}, {'departure_time': 5},
    {'optimization': 'fastest'}, {'extra': 1}])
def test_invalid_requests(planner, change):
    body = {'origin': station('A'), 'destination': station('C'), 'departure_time': WHEN, 'modes': ['subway'],
            'optimization': 'fewest_transfers', **change}
    with pytest.raises(JourneyInputError):
        planner.plan(body)


def test_offset_timestamps_are_accepted(planner):
    journey = plan(planner, station('A'), station('C'), when='2026-11-25T08:00:00-05:00')['journeys'][0]
    assert journey['departure_time'] == '2026-11-25T13:00:00Z'


# --- Y22/Y23 journey shape --------------------------------------------------------------------------

def test_journeys_are_consistent(planner):
    for origin, destination, modes in [(station('A'), station('D'), ['subway']), (station('A'), station('F'), ['subway']),
                                       (stop('MTA_100'), stop('MTA_103'), ['bus'])]:
        journeys = plan(planner, origin, destination, modes)['journeys']
        assert journeys and len(journeys) <= 3
        assert journeys == sorted(journeys, key=lambda j: (j['transfers'], j['arrival_time'], j['id']))
        for journey in journeys:
            legs = journey['legs']
            assert legs[0]['from'] == origin and legs[-1]['to'] == destination
            assert journey['departure_time'] == legs[0]['departure_time']
            assert journey['arrival_time'] == legs[-1]['arrival_time']
            assert journey['transfers'] == sum(leg['mode'] != 'walk' for leg in legs) - 1
            for before, after in zip(legs, legs[1:]):
                assert before['to'] == after['from'] and before['arrival_time'] <= after['departure_time']
            assert journey['departure_time'] >= WHEN


# --- Y25 API ------------------------------------------------------------------------------------------

@pytest.fixture
def client(schedule_dir):
    app = create_app({'TESTING': True, 'SCHEDULE_DIR': str(schedule_dir)})
    app.extensions['journeys'] = make_planner(schedule_dir)
    return app.test_client()


def test_api_success_and_errors(client):
    body = {'origin': station('A'), 'destination': station('C'), 'departure_time': WHEN, 'modes': ['subway'],
            'optimization': 'fewest_transfers'}
    response = client.post('/api/journeys', json=body)
    assert response.status_code == 200 and response.get_json()['journeys'][0]['legs'][0]['route_id'] == 'L1'
    assert client.post('/api/journeys', json={**body, 'destination': station('NOPE')}).status_code == 404
    assert client.post('/api/journeys', json={**body, 'destination': station('Z9')}).status_code == 503
    assert client.post('/api/journeys', json={**body, 'modes': []}).status_code == 400
    assert client.post('/api/journeys', data='nope', content_type='application/json').status_code == 400
    assert client.post('/api/journeys', data='{}', content_type='text/plain').status_code == 400
    no_path = client.post('/api/journeys', json={**body, 'origin': station('C'), 'destination': station('A')})
    assert no_path.status_code == 200 and no_path.get_json()['no_path_reason'] == 'no_service_in_window'
    assert client.get('/api/journeys').status_code == 405


# --- retained MTA schedules (when generated locally) -------------------------------------------------

REAL = Path(__file__).resolve().parents[1] / 'app/data/generated/schedules'
ALL_FEEDS = REAL.joinpath('manifest.json').exists() and all(
    (REAL / f['artifact']).exists() for f in json.loads((REAL / 'manifest.json').read_text())['feeds'].values())


@pytest.mark.skipif(not ALL_FEEDS, reason='retained schedules not generated')
def test_retained_schedules_plan_subway_and_mixed_journeys():
    real = JourneyPlanner(ScheduleStore(REAL))
    subway = plan(real, station('R20'), station('A27'), when='2026-11-25T14:00:00Z')['journeys']
    assert subway and all(leg['mode'] in ('subway', 'walk') for j in subway for leg in j['legs'])
    mixed = plan(real, stop('MTA_308214'), station('R20'), modes=['bus', 'subway'], when='2026-11-25T14:00:00Z')
    assert mixed['journeys'] and mixed['no_path_reason'] is None
    for journey in subway + mixed['journeys']:
        assert journey['departure_time'] >= '2026-11-25T14:00:00Z'
        assert journey['legs'][-1]['to'] in (station('A27'), station('R20'))
        for leg in journey['legs']:
            assert (leg['mode'] == 'walk') == (leg['route_id'] is None)
            assert leg['mode'] == 'walk' or len(leg['stop_ids']) >= 2
