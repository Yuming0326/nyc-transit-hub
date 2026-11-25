"""Scheduled departures by stop, route, direction and service date (Y15-Y17).

Scheduled times come only from the retained GTFS schedules and are labelled
`timing_basis: "schedule"`; they are never merged with realtime predictions
(`/api/arrivals`, bus arrivals). Coverage gaps are explicit:

- unknown station/stop/route -> NotFound;
- a known bus stop or route with no scheduled trips in the retained feeds, or a
  date outside a feed's published period -> ScheduleUnavailable;
- a covered day on which nothing runs at the stop -> an empty list.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path

from .schedule_store import ScheduleUnavailable
from .service_calendar import ServiceDateOutOfRange, active_services, parse_service_date
from .service_time import NEW_YORK, require_aware, service_dates_between, service_time_to_utc, utc_iso

BUS_CATALOG = Path(__file__).parents[1] / 'data' / 'generated' / 'bus' / 'catalog.json'
DIRECTIONS = ('0', '1')


class EntityNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Departure:
    feed: str
    trip_id: str
    route_id: str
    direction_id: object
    destination: object
    stop_id: str
    stop_sequence: int
    service_date: object
    service_time: str
    service_seconds: int

    @property
    def id(self):
        return f'{self.feed}:{self.service_date:%Y%m%d}:{self.trip_id}:{self.stop_sequence}'

    @property
    def departure_time(self):
        return service_time_to_utc(self.service_date, self.service_seconds)

    def to_dict(self):
        return {'id': self.id, 'trip_id': self.trip_id, 'route_id': self.route_id,
                'direction_id': self.direction_id, 'destination': self.destination,
                'stop_sequence': self.stop_sequence, 'service_time': self.service_time,
                'departure_time': utc_iso(self.departure_time)}


def _columns(connection, table):
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _sources(connection, kind, public_id):
    return [s for (s,) in connection.execute(
        'SELECT source_id FROM entity_links WHERE entity_type = ? AND public_id = ?', (kind, public_id))]


_catalogs = {}


def _bus_catalog():
    """Known discovery stop and route IDs, to tell coverage gaps from unknown IDs."""
    path = Path(BUS_CATALOG)
    if path not in _catalogs:
        try:
            catalog = json.loads(path.read_text(encoding='utf-8'))
            _catalogs[path] = ({s['id'] for s in catalog['stops']}, {r['id'] for r in catalog['routes']})
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ScheduleUnavailable('Bus catalog is unavailable') from error
    return _catalogs[path]


def _feed_departures(feed, connection, day, stops, routes, direction_id):
    """Departures at the given source stops on one service day of one feed."""
    try:
        services = active_services(connection, day).active
    except ServiceDateOutOfRange as error:
        raise ScheduleUnavailable(str(error)) from error
    if not services or not stops or routes == []:
        return []
    trips, stop_times = _columns(connection, 'trips'), _columns(connection, 'stop_times')
    direction = 't.direction_id' if 'direction_id' in trips else 'NULL'
    headsign = 't.trip_headsign' if 'trip_headsign' in trips else 'NULL'
    where, params = [], [*stops, *services]
    if 'pickup_type' in stop_times:
        where.append("coalesce(st.pickup_type, '') != '1'")   # no boarding: not a departure
    if routes is not None:
        where.append(f't.route_id IN ({",".join("?" * len(routes))})')
        params += routes
    if direction_id is not None:
        where.append(f'{direction} = ?')
        params.append(direction_id)
    sql = f'''SELECT st.trip_id, st.stop_id, st.stop_sequence, st.departure_time, st.departure_seconds,
                     coalesce(r.public_id, t.route_id), {direction}, {headsign}
              FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id
              LEFT JOIN entity_links r ON r.entity_type = 'route' AND r.source_id = t.route_id
              WHERE st.stop_id IN ({",".join("?" * len(stops))})
                AND t.service_id IN ({",".join("?" * len(services))})
                AND st.departure_seconds IS NOT NULL
                AND EXISTS (SELECT 1 FROM stop_times n WHERE n.trip_id = st.trip_id AND n.stop_sequence > st.stop_sequence)
                {"".join(" AND " + w for w in where)}'''
    return [Departure(feed, trip, route, (dir_ or None), ((sign or '').strip() or None), stop, sequence, day, text, secs)
            for trip, stop, sequence, text, secs, route, dir_, sign in connection.execute(sql, params)]


def _scheduled(connection, kind, public_id):
    """(known, scheduled) source IDs: linked to the public ID / actually used by trips."""
    known = _sources(connection, kind, public_id)
    if not known:
        return [], []
    table, column = ('stop_times', 'stop_id') if kind == 'stop' else ('trips', 'route_id')
    marks = ','.join('?' * len(known))
    used = {v for (v,) in connection.execute(f'SELECT DISTINCT {column} FROM {table} WHERE {column} IN ({marks})', known)}
    return known, [k for k in known if k in used]


def _resolve(store, mode, target, route_id, bus_catalog):
    """Open the feeds serving the target; return [(feed, connection, stops, routes)].

    Unknown IDs are NotFound; IDs that are known (linked in a feed or listed in the
    bus catalog) but have no scheduled trips are a coverage gap, not an empty day.
    """
    feeds = store.feeds(mode)
    if not feeds:
        raise ScheduleUnavailable(f'No {mode} schedules are available')
    opened = []
    stop_known = stop_scheduled = False
    route_known = route_scheduled = route_id is None
    try:
        for feed in feeds:
            connection = store.connect(feed)
            known_stops, stops = _scheduled(connection, 'stop', target)
            routes = None
            if route_id is not None:
                known_routes, routes = _scheduled(connection, 'route', route_id)
                route_known, route_scheduled = route_known or bool(known_routes), route_scheduled or bool(routes)
            stop_known, stop_scheduled = stop_known or bool(known_stops), stop_scheduled or bool(stops)
            if stops:
                opened.append((feed, connection, stops, routes))
            else:
                connection.close()
        if mode == 'bus':
            stop_known = stop_known or (not stop_scheduled and target in bus_catalog()[0])
            route_known = route_known or (not route_scheduled and route_id in bus_catalog()[1])
        noun = 'Station' if mode == 'subway' else 'Stop'
        if not stop_known:
            raise EntityNotFound(f'{noun} not found.')
        if not route_known:
            raise EntityNotFound('Route not found.')
        if not stop_scheduled:
            raise ScheduleUnavailable(f'No scheduled trips are available for {noun.lower()} {target}')
        if not route_scheduled:
            raise ScheduleUnavailable(f'No scheduled trips are available for route {route_id}')
    except Exception:
        for _, connection, _, _ in opened:
            connection.close()
        raise
    return opened


def scheduled_departures(store, mode, service_date, target, *, route_id=None, direction_id=None,
                         bus_catalog=_bus_catalog):
    """All departures for one service day, sorted by departure_time then id."""
    if mode not in ('subway', 'bus'):
        raise ValueError('mode must be subway or bus')
    if direction_id is not None and direction_id not in DIRECTIONS:
        raise ValueError('direction_id must be 0 or 1')
    day = parse_service_date(service_date)
    results = []
    for feed, connection, stops, routes in _resolve(store, mode, target, route_id, bus_catalog):
        with closing(connection):
            results += _feed_departures(feed, connection, day, stops, routes, direction_id)
    return sorted(results, key=lambda d: (d.departure_time, d.id))


def departures_between(store, mode, target, start, end, *, route_id=None, direction_id=None,
                       bus_catalog=_bus_catalog):
    """Departures whose real time falls in [start, end], across service days.

    A 25:30 trip on Monday's service day appears in a Tuesday 01:30 window and
    keeps Monday as its service_date.
    """
    start, end = require_aware(start), require_aware(end)
    if end - start > timedelta(days=2):
        raise ValueError('Window must be at most 48 hours')
    longest = 0
    for feed in store.feeds(mode):
        with closing(store.connect(feed)) as connection:
            longest = max(longest, connection.execute('SELECT max(departure_seconds) FROM stop_times').fetchone()[0] or 0)
    results = []
    for day in service_dates_between(start, end, longest):
        results += [d for d in scheduled_departures(store, mode, day, target, route_id=route_id,
                                                    direction_id=direction_id, bus_catalog=bus_catalog)
                    if start <= d.departure_time <= end]
    return sorted(results, key=lambda d: (d.departure_time, d.id))


def schedule_response(store, mode, service_date, target, **filters):
    """Y17 envelope: scheduled departures, labelled apart from realtime predictions."""
    day = parse_service_date(service_date)
    departures = scheduled_departures(store, mode, day, target, **filters)
    return {'mode': mode, 'source': 'mta', 'updated_at': utc_iso(_parse_imported(store.updated_at)),
            'service_date': day.isoformat(), 'timezone': NEW_YORK.key, 'timing_basis': 'schedule',
            'departures': [d.to_dict() for d in departures]}


def _parse_imported(value):
    try:
        return require_aware(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except (AttributeError, ValueError) as error:
        raise ScheduleUnavailable('Schedule manifest has no valid import time') from error
