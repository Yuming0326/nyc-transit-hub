import csv
from datetime import date, datetime
import gzip
from io import StringIO
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import pytest
from app.services.schedule_import import retain_schedule
from app.services.service_calendar import (ServiceDateError, ServiceDateOutOfRange, active_services,
                                           feed_coverage, parse_service_date)

DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
SUBWAY = Path(__file__).resolve().parents[1] / 'app/data/generated/schedules/subway.sqlite.gz'


def calendar_row(service_id, days, start='20261101', end='20270515'):
    return {'service_id': service_id, **{d: '1' if d in days else '0' for d in DAYS},
            'start_date': start, 'end_date': end}


def feed(calendar=(), exceptions=(), feed_info=None):
    """In-memory database shaped like a retained schedule (TEXT source columns)."""
    db = sqlite3.connect(':memory:')
    if calendar is not None:
        db.execute('CREATE TABLE calendar (service_id TEXT, monday TEXT, tuesday TEXT, wednesday TEXT, thursday TEXT,'
                   ' friday TEXT, saturday TEXT, sunday TEXT, start_date TEXT, end_date TEXT)')
        for row in calendar:
            db.execute('INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)',
                       [row['service_id'], *(row[d] for d in DAYS), row['start_date'], row['end_date']])
    if exceptions is not None:
        db.execute('CREATE TABLE calendar_dates (service_id TEXT, date TEXT, exception_type TEXT)')
        db.executemany('INSERT INTO calendar_dates VALUES (?,?,?)', exceptions)
    if feed_info is not None:
        db.execute('CREATE TABLE feed_info (feed_publisher_name TEXT, feed_start_date TEXT, feed_end_date TEXT)')
        db.execute('INSERT INTO feed_info VALUES (?,?,?)', ['MTA', *feed_info])
    return db


def source(tmp_path, tables):
    path = tmp_path / 'source.zip'
    with ZipFile(path, 'w') as archive:
        for table, rows in tables.items():
            text = StringIO()
            writer = csv.DictWriter(text, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
            archive.writestr(table + '.txt', text.getvalue())
    return path


@pytest.fixture
def subway_like():
    """Mirrors the retained subway feed, including the Thanksgiving swap."""
    return feed([calendar_row('Weekday', DAYS[:5]), calendar_row('Saturday', ['saturday']),
                 calendar_row('Sunday', ['sunday'])],
                [('Sunday', '20261126', '1'), ('Weekday', '20261126', '2'),
                 ('Sunday', '20261225', '1'), ('Weekday', '20261225', '2')],
                ('20261101', '20270515'))


@pytest.mark.parametrize('day,expected', [
    ('2026-11-25', ('Weekday',)),    # Wednesday
    ('2026-11-27', ('Weekday',)),    # Friday after Thanksgiving: no exception
    ('2026-11-28', ('Saturday',)),
    ('2026-11-29', ('Sunday',)),
    ('2026-11-30', ('Weekday',)),
])
def test_regular_weekday_and_weekend_service(subway_like, day, expected):
    result = active_services(subway_like, day)
    assert result.active == expected and result.added == () and result.removed == ()


@pytest.mark.parametrize('day', ['2026-11-26', '20261225'])
def test_holiday_exceptions_replace_weekday_with_sunday_service(subway_like, day):
    result = active_services(subway_like, day)
    assert result.active == ('Sunday',)
    assert result.added == ('Sunday',) and result.removed == ('Weekday',)
    assert result.to_dict() == {
        'service_date': parse_service_date(day).isoformat(), 'active_service_ids': ['Sunday'],
        'added_by_exception': ['Sunday'], 'removed_by_exception': ['Weekday'],
        'feed_service_period': {'start': '2026-11-01', 'end': '2027-05-15'}}


def test_calendar_start_and_end_dates_are_inclusive():
    db = feed([calendar_row('Short', DAYS, '20261110', '20261112'), calendar_row('Long', DAYS, '20261101', '20261130')])
    assert active_services(db, '2026-11-09').active == ('Long',)
    assert active_services(db, '2026-11-10').active == ('Long', 'Short')
    assert active_services(db, '2026-11-12').active == ('Long', 'Short')
    assert active_services(db, '2026-11-13').active == ('Long',)


def test_exceptions_only_affect_their_own_date_and_service():
    db = feed([calendar_row('A', DAYS[:5]), calendar_row('B', DAYS[:5])],
              [('A', '20261124', '2'), ('Extra', '20261124', '1'), ('Never', '20261124', '2')])
    tuesday = active_services(db, '2026-11-24')
    assert tuesday.active == ('B', 'Extra')
    assert tuesday.removed == ('A',)          # removing a service that was not running is a no-op
    assert active_services(db, '2026-11-17').active == ('A', 'B')


def test_redundant_added_exception_is_not_reported_as_added():
    db = feed([calendar_row('A', DAYS)], [('A', '20261124', '1')])
    result = active_services(db, '2026-11-24')
    assert result.active == ('A',) and result.added == ()


def test_feed_with_only_calendar_dates():
    db = feed(None, [('Holiday', '20261126', '1'), ('Holiday', '20261225', '1')])
    assert active_services(db, '2026-11-26').active == ('Holiday',)
    assert active_services(db, '2026-12-01').active == ()
    assert feed_coverage(db) == (date(2026, 11, 26), date(2026, 12, 25))


def test_day_inside_published_period_without_service_is_empty():
    db = feed([calendar_row('Weekday', DAYS[:5])], [('Weekday', '20261127', '2')], ('20261101', '20261130'))
    result = active_services(db, '2026-11-27')
    assert result.active == () and result.removed == ('Weekday',)
    assert active_services(db, '2026-11-28').active == ()


@pytest.mark.parametrize('day', ['2026-10-31', '2027-05-16', '2025-11-26'])
def test_dates_outside_feed_period_are_explicitly_unavailable(subway_like, day):
    with pytest.raises(ServiceDateOutOfRange) as error:
        active_services(subway_like, day)
    assert error.value.coverage == (date(2026, 11, 1), date(2027, 5, 15))
    assert 'outside the feed service period' in str(error.value)


def test_feed_info_period_takes_precedence_over_calendar_extent():
    # Bus feeds: calendars start 20261008 but feed_info publishes from 20261012.
    db = feed([calendar_row('Weekday', DAYS[:5], '20261008', '20270102')], [], ('20261012', '20270102'))
    assert feed_coverage(db) == (date(2026, 10, 12), date(2027, 1, 2))
    with pytest.raises(ServiceDateOutOfRange):
        active_services(db, '2026-10-09')
    assert active_services(db, '2026-10-12').active == ('Weekday',)


def test_partial_feed_info_falls_back_to_calendar_for_missing_bound():
    db = feed([calendar_row('A', DAYS, '20261008', '20270102')], [], ('20261012', ''))
    assert feed_coverage(db) == (date(2026, 10, 12), date(2027, 1, 2))


def test_feed_without_any_calendar_is_rejected():
    with pytest.raises(LookupError):
        active_services(feed([], []), '2026-11-25')


@pytest.mark.parametrize('value,expected', [
    ('2026-11-26', date(2026, 11, 26)), ('20261126', date(2026, 11, 26)),
    (' 2026-11-26 ', date(2026, 11, 26)), (date(2026, 11, 26), date(2026, 11, 26)),
    ('2028-02-29', date(2028, 2, 29)),
])
def test_parse_service_date(value, expected):
    assert parse_service_date(value) == expected


@pytest.mark.parametrize('value', ['2026-02-30', '2027-02-29', '2026-13-01', '26-11-26', '2026/11/26', '',
                                   None, 20261126, datetime(2026, 11, 26, 0, 30)])
def test_invalid_service_dates_are_rejected(subway_like, value):
    with pytest.raises(ServiceDateError):
        active_services(subway_like, value)


def test_resolves_services_in_a_retained_schedule_database(tmp_path):
    tables = {
        'agency': [{'agency_id': 'MTA NYCT', 'agency_timezone': 'America/New_York'}],
        'routes': [{'route_id': 'R', 'agency_id': 'MTA NYCT', 'route_short_name': 'R'}],
        'stops': [{'stop_id': 'P', 'parent_station': ''}],
        'trips': [{'trip_id': 'w', 'route_id': 'R', 'service_id': 'Weekday'},
                  {'trip_id': 's', 'route_id': 'R', 'service_id': 'Sunday'}],
        'stop_times': [{'trip_id': t, 'stop_id': 'P', 'stop_sequence': '1', 'arrival_time': '08:00:00',
                        'departure_time': '08:00:00'} for t in ('w', 's')],
        'calendar': [calendar_row('Weekday', DAYS[:5]), calendar_row('Sunday', ['sunday'])],
        'calendar_dates': [{'service_id': 'Sunday', 'date': '20261126', 'exception_type': '1'},
                           {'service_id': 'Weekday', 'date': '20261126', 'exception_type': '2'}],
        'feed_info': [{'feed_publisher_name': 'MTA', 'feed_start_date': '20261101', 'feed_end_date': '20270515'}],
    }
    output = tmp_path / 'schedule.sqlite.gz'
    retain_schedule(source(tmp_path, tables), output, mode='subway')
    path = tmp_path / 'schedule.sqlite'
    path.write_bytes(gzip.decompress(output.read_bytes()))
    with sqlite3.connect(path) as db:
        assert active_services(db, '2026-11-25').active == ('Weekday',)
        assert active_services(db, '2026-11-26').active == ('Sunday',)
        assert active_services(db, '2026-11-28').active == ()


@pytest.mark.skipif(not SUBWAY.exists(), reason='retained subway schedule not generated locally')
def test_retained_subway_schedule_thanksgiving_runs_sunday_service(tmp_path):
    path = tmp_path / 'subway.sqlite'
    path.write_bytes(gzip.decompress(SUBWAY.read_bytes()))
    with sqlite3.connect(path) as db:
        coverage = feed_coverage(db)
        for day in ('2026-11-25', '2026-11-26', '2026-11-27', '2026-11-28', '2026-11-29'):
            if coverage[0] <= parse_service_date(day) <= coverage[1]:
                services = active_services(db, day).active
                assert services and set(services) <= {r for (r,) in db.execute('SELECT service_id FROM services')}
        if coverage[0] <= date(2026, 11, 26) <= coverage[1]:
            assert active_services(db, '2026-11-26').active == ('Sunday',)
