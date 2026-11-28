"""Resolve which GTFS services run on a selected service date (Y14).

Works on one retained per-feed schedule database (see schedule_import.py), so a
service is identified by (feed_id, service_id); callers keep the feed scope.

GTFS rule: a service runs on date D when a calendar row covers D with D's weekday
flag set and no calendar_dates exception_type=2 removes it, or when a
calendar_dates exception_type=1 adds it for D.

A *service date* is the GTFS service day, not a clock instant. Mapping a New York
timestamp (including after-midnight trips and DST) to service days is Y16, so a
datetime is rejected here rather than silently truncated.

Dates outside the feed's published period raise ServiceDateOutOfRange: missing
coverage is never reported as a normal day without service.
"""
from dataclasses import dataclass
from datetime import date as Date, datetime
import re

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
ADDED, REMOVED = '1', '2'


class ServiceDateError(ValueError):
    """The requested service date is not a valid calendar date."""


class ServiceDateOutOfRange(LookupError):
    """The feed does not publish service for the requested date."""

    def __init__(self, service_date, coverage):
        self.service_date, self.coverage = service_date, coverage
        super().__init__(f'{service_date.isoformat()} is outside the feed service period '
                         f'{coverage[0].isoformat()} to {coverage[1].isoformat()}')


@dataclass(frozen=True)
class ServiceDay:
    service_date: Date
    active: tuple      # every service_id running on the date, sorted
    added: tuple       # active only because of an exception_type=1 row
    removed: tuple     # regular calendar service cancelled by exception_type=2
    coverage: tuple    # (first, last) date the feed publishes service for

    def to_dict(self):
        return {'service_date': self.service_date.isoformat(), 'active_service_ids': list(self.active),
                'added_by_exception': list(self.added), 'removed_by_exception': list(self.removed),
                'feed_service_period': {'start': self.coverage[0].isoformat(), 'end': self.coverage[1].isoformat()}}


def parse_service_date(value):
    """Accept a date, 'YYYY-MM-DD' or GTFS 'YYYYMMDD'; reject clock times."""
    if isinstance(value, datetime):
        raise ServiceDateError('Expected a service date, not a timestamp')
    if isinstance(value, Date):
        return value
    text = value.strip() if isinstance(value, str) else ''
    for pattern, layout in ((r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'), (r'\d{8}', '%Y%m%d')):
        if re.fullmatch(pattern, text):
            try:
                return datetime.strptime(text, layout).date()
            except ValueError:
                break
    raise ServiceDateError('Invalid service date; use YYYY-MM-DD')


def _gtfs(value):
    return value.strftime('%Y%m%d')


def _tables(connection):
    return {name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def feed_coverage(connection):
    """Published service period: feed_info dates when given, else calendar extent per bound."""
    tables = _tables(connection)
    starts, ends = [], []
    if 'calendar' in tables:
        row = connection.execute('SELECT min(start_date), max(end_date) FROM calendar').fetchone()
        starts.append(row[0]); ends.append(row[1])
    if 'calendar_dates' in tables:
        row = connection.execute('SELECT min(date), max(date) FROM calendar_dates').fetchone()
        starts.append(row[0]); ends.append(row[1])
    starts, ends = [s for s in starts if s], [e for e in ends if e]
    start, end = (min(starts) if starts else None), (max(ends) if ends else None)
    if 'feed_info' in tables:
        columns = {c[1] for c in connection.execute('PRAGMA table_info(feed_info)')}
        for column in ('feed_start_date', 'feed_end_date'):
            if column in columns:
                values = {v for (v,) in connection.execute(f'SELECT "{column}" FROM feed_info') if v}
                if len(values) == 1:
                    if column == 'feed_start_date':
                        start = values.pop()
                    else:
                        end = values.pop()
    if not start or not end:
        raise LookupError('Feed has no service calendar')
    first, last = parse_service_date(start), parse_service_date(end)
    if first > last:
        raise LookupError('Feed service period is inverted')
    return first, last


def active_services(connection, service_date):
    """Return the ServiceDay for one feed database and service date."""
    day = parse_service_date(service_date)
    coverage = feed_coverage(connection)
    if not coverage[0] <= day <= coverage[1]:
        raise ServiceDateOutOfRange(day, coverage)
    tables, key = _tables(connection), _gtfs(day)
    regular = set()
    if 'calendar' in tables:
        weekday = WEEKDAYS[day.weekday()]
        regular = {s for (s,) in connection.execute(
            f'SELECT service_id FROM calendar WHERE start_date <= ? AND end_date >= ? AND "{weekday}" = ?',
            (key, key, '1'))}
    exceptions = {ADDED: set(), REMOVED: set()}
    if 'calendar_dates' in tables:
        for service_id, kind in connection.execute(
                'SELECT service_id, exception_type FROM calendar_dates WHERE date = ?', (key,)):
            exceptions[kind].add(service_id)
    active = (regular - exceptions[REMOVED]) | exceptions[ADDED]
    return ServiceDay(day, tuple(sorted(active)), tuple(sorted(exceptions[ADDED] - regular)),
                      tuple(sorted(exceptions[REMOVED] & regular)), coverage)
