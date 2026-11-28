"""Y15-Y18: scheduled departures, service days, DST and the /api/schedules contract."""
import csv
from datetime import datetime, timezone
import gzip
from io import StringIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from app import create_app
from app.services import schedule_service
from app.services.schedule_import import retain_schedule
from app.services.schedule_service import EntityNotFound, departures_between, scheduled_departures
from app.services.schedule_store import ScheduleStore, ScheduleUnavailable

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
GENERATED = Path(__file__).resolve().parents[1] / 'app/data/generated'


def calendar(service_id, days):
    return {'service_id': service_id, **{d: '1' if d in days else '0' for d in DAYS},
            'start_date': '20261101', 'end_date': '20270515'}


def stop_times(trip, *stops):
    return [{'trip_id': trip, 'stop_id': stop, 'stop_sequence': str(i + 1), 'arrival_time': time,
             'departure_time': time, 'pickup_type': pickup} for i, (stop, time, pickup) in enumerate(stops)]


SUBWAY = {
    'agency': [{'agency_id': 'MTA NYCT', 'agency_timezone': 'America/New_York'}],
    'routes': [{'route_id': r, 'agency_id': 'MTA NYCT', 'route_short_name': r} for r in ('R', 'A')],
    'stops': [{'stop_id': s, 'parent_station': p} for s, p in
              [('P', ''), ('PN', 'P'), ('PS', 'P'), ('Q', ''), ('QN', 'Q'), ('X', ''), ('Z', '')]],
    'trips': [{'trip_id': t, 'route_id': r, 'service_id': s, 'direction_id': d, 'trip_headsign': h}
              for t, r, s, d, h in [('wk1', 'R', 'Weekday', '0', 'Forest Hills'), ('wk2', 'R', 'Weekday', '1', ' '),
                                    ('owl', 'R', 'Weekday', '0', 'Forest Hills'), ('term', 'R', 'Weekday', '0', 'P'),
                                    ('noboard', 'R', 'Weekday', '0', ''), ('sun', 'A', 'Sunday', '0', 'Far Rockaway'),
                                    ('satowl', 'R', 'Saturday', '0', '')]],
    'stop_times': (stop_times('wk1', ('PN', '08:00:00', '0'), ('QN', '08:10:00', '0'), ('X', '08:20:00', '0'))
                   + stop_times('wk2', ('PS', '07:55:00', '0'), ('X', '08:05:00', '0'))
                   + stop_times('owl', ('PN', '25:05:00', '0'), ('X', '25:15:00', '0'))
                   + stop_times('term', ('QN', '09:00:00', '0'), ('PN', '09:10:00', '0'))
                   + stop_times('noboard', ('PN', '10:00:00', '1'), ('X', '10:10:00', '0'))
                   + stop_times('sun', ('PN', '09:00:00', '0'), ('X', '09:10:00', '0'))
                   + stop_times('satowl', ('PN', '26:30:00', '0'), ('X', '26:40:00', '0'))),
    'calendar': [calendar('Weekday', DAYS[:5]), calendar('Saturday', ['saturday']), calendar('Sunday', ['sunday'])],
    'calendar_dates': [{'service_id': 'Sunday', 'date': '20261126', 'exception_type': '1'},
                       {'service_id': 'Weekday', 'date': '20261126', 'exception_type': '2'}],
    'feed_info': [{'feed_publisher_name': 'MTA', 'feed_start_date': '20261101', 'feed_end_date': '20270515'}],
}

BUS = {
    'agency': [{'agency_id': 'MTA NYCT', 'agency_timezone': 'America/New_York'}],
    'routes': [{'route_id': r, 'agency_id': 'MTA NYCT', 'route_short_name': r} for r in ('B1', 'B9')],
    'stops': [{'stop_id': s} for s in ('100', '101', '900', '300')],
    'trips': [{'trip_id': 'b1', 'route_id': 'B1', 'service_id': 'Weekday', 'direction_id': '1',
               'trip_headsign': 'BAY RIDGE'}],
    'stop_times': stop_times('b1', ('100', '12:00:00', '0'), ('101', '12:05:00', '0'), ('900', '12:10:00', '0')),
    'calendar': [calendar('Weekday', DAYS[:5])],
    'calendar_dates': [{'service_id': 'Weekday', 'date': '20261126', 'exception_type': '2'}],
}
DISCOVERY = {'routes': [{'id': f'MTA NYCT_{r}', 'agency_id': 'MTA NYCT', 'short_name': r} for r in ('B1', 'B9')],
             'stops': [{'id': f'MTA_{s}', 'code': s} for s in ('100', '101', '900', '300')]}
CATALOG = {'stops': [{'id': s} for s in ('MTA_100', 'MTA_101', 'MTA_900', 'MTA_200')],
           'routes': [{'id': r} for r in ('MTA NYCT_B1', 'MTA NYCT_B102')]}


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
    directory = tmp_path_factory.mktemp('schedules')
    feeds = {}
    for feed, tables, mode in (('subway', SUBWAY, 'subway'), ('b', BUS, 'bus')):
        report = retain_schedule(archive(directory / f'{feed}.zip', tables), directory / f'{feed}.sqlite.gz',
                                 mode=mode, discovery=DISCOVERY)
        feeds[feed] = {'artifact': f'{feed}.sqlite.gz', 'artifact_sha256': report['artifact_sha256']}
    (directory / 'manifest.json').write_text(json.dumps(
        {'imported_at': '2026-11-25T04:02:13.603062+00:00', 'feeds': feeds}))
    return directory


@pytest.fixture
def store(schedule_dir, tmp_path, monkeypatch):
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps(CATALOG))
    monkeypatch.setattr(schedule_service, 'BUS_CATALOG', catalog)
    monkeypatch.setattr(schedule_service, '_catalogs', {})
    return ScheduleStore(schedule_dir)


@pytest.fixture
def client(store):
    return create_app({'TESTING': True, 'SCHEDULE_DIR': str(store.directory)}).test_client()


def summary(departures):
    return [(d.trip_id, d.service_time, d.to_dict()['departure_time']) for d in departures]


# --- Y15: departures by stop, route, direction and date -------------------------------------------

def test_weekday_station_departures_are_ordered_and_skip_arrivals_only(store):
    result = scheduled_departures(store, 'subway', '2026-11-25', 'P')
    assert summary(result) == [('wk2', '07:55:00', '2026-11-25T12:55:00Z'),
                               ('wk1', '08:00:00', '2026-11-25T13:00:00Z'),
                               ('owl', '25:05:00', '2026-11-26T06:05:00Z')]
    # 'term' ends at P and 'noboard' does not pick up there: neither is a departure.
    assert [d.stop_sequence for d in result] == [1, 1, 1]
    assert result[1].to_dict() == {
        'id': 'subway:20261125:wk1:1', 'trip_id': 'wk1', 'route_id': 'R', 'direction_id': '0',
        'destination': 'Forest Hills', 'stop_sequence': 1, 'service_time': '08:00:00',
        'departure_time': '2026-11-25T13:00:00Z'}
    assert result[0].destination is None       # blank headsign is unknown, not ''


def test_intermediate_stop_sequence_is_kept(store):
    result = scheduled_departures(store, 'subway', '2026-11-25', 'Q')
    assert [(d.trip_id, d.stop_sequence) for d in result] == [('wk1', 2), ('term', 1)]


def test_route_and_direction_filters(store):
    assert [d.trip_id for d in scheduled_departures(store, 'subway', '2026-11-25', 'P', direction_id='1')] == ['wk2']
    assert [d.trip_id for d in scheduled_departures(store, 'subway', '2026-11-25', 'P', route_id='R',
                                                    direction_id='0')] == ['wk1', 'owl']
    assert scheduled_departures(store, 'subway', '2026-11-25', 'P', route_id='A') == []


def test_bus_stop_departures_use_public_ids(store):
    result = scheduled_departures(store, 'bus', '2026-11-25', 'MTA_100')
    assert [(d.id, d.route_id, d.direction_id, d.destination) for d in result] == [
        ('b:20261125:b1:1', 'MTA NYCT_B1', '1', 'BAY RIDGE')]
    assert scheduled_departures(store, 'bus', '2026-11-25', 'MTA_900') == []   # terminal: arrivals only


@pytest.mark.parametrize('mode,target,route,error', [
    ('subway', 'NOPE', None, EntityNotFound), ('subway', 'P', 'NOPE', EntityNotFound),
    ('bus', 'MTA_999', None, EntityNotFound), ('bus', 'MTA_100', 'MTA NYCT_NOPE', EntityNotFound),
    ('bus', 'MTA_200', None, ScheduleUnavailable),              # known stop, no scheduled trips
    ('bus', 'MTA_100', 'MTA NYCT_B102', ScheduleUnavailable),   # known route, no scheduled trips
    ('bus', 'MTA_300', None, ScheduleUnavailable),              # in the feed's stops.txt, never served
    ('bus', 'MTA_100', 'MTA NYCT_B9', ScheduleUnavailable),     # in the feed's routes.txt, no trips
    ('subway', 'Z', None, ScheduleUnavailable),                 # station without scheduled stops
])
def test_unknown_ids_and_coverage_gaps_are_distinct(store, mode, target, route, error):
    with pytest.raises(error):
        scheduled_departures(store, mode, '2026-11-25', target, route_id=route)


# --- Y14 + Y18: weekday/weekend, exception, empty and out-of-period days ---------------------------

@pytest.mark.parametrize('day,trips', [
    ('2026-11-27', ['wk2', 'wk1', 'owl']),   # Friday after Thanksgiving: regular weekday
    ('2026-11-28', ['satowl']),              # Saturday
    ('2026-11-29', ['sun']),                 # Sunday
    ('2026-11-26', ['sun']),                 # Thanksgiving: weekday removed, Sunday added
])
def test_service_day_selection(store, day, trips):
    assert [d.trip_id for d in scheduled_departures(store, 'subway', day, 'P')] == trips


def test_exception_day_with_no_service_is_a_valid_empty_result(store):
    assert scheduled_departures(store, 'bus', '2026-11-26', 'MTA_100') == []
    assert scheduled_departures(store, 'bus', '2026-11-28', 'MTA_100') == []


@pytest.mark.parametrize('mode,target', [('subway', 'P'), ('bus', 'MTA_100')])
def test_dates_outside_the_feed_are_unavailable_not_empty(store, mode, target):
    with pytest.raises(ScheduleUnavailable, match='outside the feed service period'):
        scheduled_departures(store, mode, '2026-10-31', target)


# --- Y16: overnight trips and New York DST ---------------------------------------------------------

def test_overnight_trip_keeps_its_service_day(store):
    owl = scheduled_departures(store, 'subway', '2026-11-25', 'P', route_id='R')[-1]
    assert owl.service_date.isoformat() == '2026-11-25' and owl.service_time == '25:05:00'
    assert owl.to_dict()['departure_time'] == '2026-11-26T06:05:00Z'   # 01:05 EST on Nov 26


def test_window_after_midnight_returns_previous_service_day_trip(store):
    start = datetime(2026, 11, 26, 5, 0, tzinfo=timezone.utc)   # 00:00 EST Thanksgiving
    result = departures_between(store, 'subway', 'P', start, start.replace(hour=7))
    assert [(d.trip_id, d.service_date.isoformat(), d.id) for d in result] == [
        ('owl', '2026-11-25', 'subway:20261125:owl:1')]


def test_window_spanning_a_day_merges_service_days_in_time_order(store):
    start = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    result = departures_between(store, 'subway', 'P', start, datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc))
    assert summary(result) == [('wk2', '07:55:00', '2026-11-25T12:55:00Z'),
                               ('wk1', '08:00:00', '2026-11-25T13:00:00Z'),
                               ('owl', '25:05:00', '2026-11-26T06:05:00Z'),
                               ('sun', '09:00:00', '2026-11-26T14:00:00Z')]


def test_window_limits(store):
    start = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        departures_between(store, 'subway', 'P', start, start.replace(day=28))
    with pytest.raises(ValueError):
        departures_between(store, 'subway', 'P', start.replace(tzinfo=None), start)


@pytest.mark.parametrize('day,trip,expected', [
    ('2026-11-01', 'sun', '2026-11-01T14:00:00Z'),      # fall-back Sunday: 09:00 EST
    ('2027-03-14', 'sun', '2027-03-14T13:00:00Z'),      # spring-forward Sunday: 09:00 EDT
    ('2027-03-13', 'satowl', '2027-03-14T07:30:00Z'),   # 26:30 Saturday service -> 03:30 EDT, not a missing 02:30
    ('2027-03-20', 'satowl', '2027-03-21T06:30:00Z'),   # same trip a week later in EDT -> 02:30 EDT
])
def test_dst_days(store, day, trip, expected):
    [departure] = [d for d in scheduled_departures(store, 'subway', day, 'P') if d.trip_id == trip]
    assert departure.to_dict()['departure_time'] == expected


# --- Y17: /api/schedules, labelled separately from realtime predictions ----------------------------

def test_schedule_endpoint_envelope(client):
    response = client.get('/api/schedules?mode=subway&date=2026-11-25&station_id=P&route_id=R&direction_id=0')
    assert response.status_code == 200
    body = response.get_json()
    assert {k: v for k, v in body.items() if k != 'departures'} == {
        'mode': 'subway', 'source': 'mta', 'updated_at': '2026-11-25T04:02:13Z', 'service_date': '2026-11-25',
        'timezone': 'America/New_York', 'timing_basis': 'schedule'}
    assert [d['trip_id'] for d in body['departures']] == ['wk1', 'owl']
    assert set(body['departures'][0]) == {'id', 'trip_id', 'route_id', 'direction_id', 'destination',
                                          'stop_sequence', 'service_time', 'departure_time'}


def test_schedule_endpoint_empty_bus_day(client):
    response = client.get('/api/schedules?mode=bus&date=2026-11-26&stop_id=MTA_100')
    assert response.status_code == 200 and response.get_json()['departures'] == []


@pytest.mark.parametrize('query', [
    '', 'mode=train&date=2026-11-25&station_id=P', 'mode=subway&station_id=P',
    'mode=subway&date=20261125&station_id=P', 'mode=subway&date=2026-11-31&station_id=P',
    'mode=subway&date=2026-11-25', 'mode=subway&date=2026-11-25&stop_id=P',
    'mode=subway&date=2026-11-25&station_id=P&stop_id=MTA_100', 'mode=bus&date=2026-11-25&station_id=P',
    'mode=subway&date=2026-11-25&station_id=%20', 'mode=subway&date=2026-11-25&station_id=P&route_id=',
    'mode=subway&date=2026-11-25&station_id=P&direction_id=2',
    'mode=subway&date=2026-11-25&station_id=P&station_id=Q',
])
def test_schedule_endpoint_rejects_invalid_requests(client, query):
    response = client.get('/api/schedules?' + query)
    assert response.status_code == 400 and set(response.get_json()) == {'error'}


@pytest.mark.parametrize('query,status', [
    ('mode=subway&date=2026-11-25&station_id=NOPE', 404),
    ('mode=bus&date=2026-11-25&stop_id=MTA_999', 404),
    ('mode=bus&date=2026-11-25&stop_id=MTA_200', 503),
    ('mode=bus&date=2026-11-25&stop_id=MTA_100&route_id=MTA%20NYCT_B102', 503),
    ('mode=subway&date=2027-05-16&station_id=P', 503),
])
def test_schedule_endpoint_missing_entities_and_coverage(client, query, status):
    response = client.get('/api/schedules?' + query)
    assert response.status_code == status and set(response.get_json()) == {'error'}


def test_schedule_endpoint_does_not_call_realtime_feeds(client, monkeypatch):
    monkeypatch.setattr('requests.get', lambda *a, **k: pytest.fail('schedules must not call realtime feeds'))
    assert client.get('/api/schedules?mode=subway&date=2026-11-25&station_id=P').status_code == 200


# --- Runtime store -----------------------------------------------------------------------------------

def test_store_decompresses_once_and_opens_read_only(store):
    path = store.path('subway')
    assert path.name.startswith('subway.') and path.suffix == '.sqlite' and path.exists()
    assert store.path('subway') == path
    connection = store.connect('subway')
    with pytest.raises(Exception):
        connection.execute('DELETE FROM trips')
    connection.close()


def test_store_rejects_artifacts_that_do_not_match_the_manifest(tmp_path):
    (tmp_path / 'subway.sqlite.gz').write_bytes(gzip.compress(b'not a database'))
    (tmp_path / 'manifest.json').write_text(json.dumps({'imported_at': '2026-11-25T00:00:00Z', 'feeds': {
        'subway': {'artifact': 'subway.sqlite.gz', 'artifact_sha256': '0' * 64}}}))
    with pytest.raises(ScheduleUnavailable):
        ScheduleStore(tmp_path).connect('subway')


def test_missing_schedule_data_is_503(tmp_path):
    client = create_app({'TESTING': True, 'SCHEDULE_DIR': str(tmp_path)}).test_client()
    response = client.get('/api/schedules?mode=subway&date=2026-11-25&station_id=P')
    assert response.status_code == 503 and set(response.get_json()) == {'error'}


# --- Retained MTA data (runs only where the schedules were generated locally) --------------------

REAL = GENERATED / 'schedules'
ALL_FEEDS = REAL.joinpath('manifest.json').exists() and all(
    (REAL / f['artifact']).exists() for f in json.loads((REAL / 'manifest.json').read_text())['feeds'].values())


@pytest.mark.skipif(not (REAL / 'subway.sqlite.gz').exists(), reason='retained subway schedule not generated')
def test_retained_subway_r20_thanksgiving_runs_the_sunday_timetable(tmp_path):
    (tmp_path / 'subway.sqlite.gz').symlink_to(REAL / 'subway.sqlite.gz')
    manifest = json.loads((REAL / 'manifest.json').read_text())
    (tmp_path / 'manifest.json').write_text(json.dumps({**manifest, 'feeds': {'subway': manifest['feeds']['subway']}}))
    real = ScheduleStore(tmp_path)
    days = {d: scheduled_departures(real, 'subway', d, 'R20') for d in ('2026-11-25', '2026-11-26', '2026-11-29')}
    weekday, thanksgiving, sunday = days.values()
    assert weekday and len(thanksgiving) == len(sunday) != len(weekday)
    assert [d.service_time for d in thanksgiving] == [d.service_time for d in sunday]
    assert all(a.departure_time <= b.departure_time for a, b in zip(weekday, weekday[1:]))
    assert {d.route_id for d in weekday} <= {'N', 'Q', 'R', 'W'}


@pytest.mark.skipif(not ALL_FEEDS, reason='all retained bus schedules not generated')
def test_retained_bus_stop_from_fixture_has_b63_departures():
    real = ScheduleStore(REAL)
    result = scheduled_departures(real, 'bus', '2026-11-25', 'MTA_308214', route_id='MTA NYCT_B63')
    assert result and all(d.route_id == 'MTA NYCT_B63' for d in result)
    with pytest.raises(ScheduleUnavailable):
        scheduled_departures(real, 'bus', '2026-11-24', 'MTA_300012', route_id='MTA NYCT_B102')
