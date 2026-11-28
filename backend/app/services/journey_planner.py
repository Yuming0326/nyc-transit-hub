"""Schedule-based journey planning (Y19-Y23) for POST /api/journeys.

Graph (Y19)
    Directed connections come only from retained GTFS trips: each trip is an
    ordered stop sequence with its route and direction. Trips with the same
    route, ordered stops and pickup/drop-off rules form a *pattern*; a trip only
    ever carries a rider forward along its own stop order, so direction is kept.
    Subway nodes are parent stations, bus nodes are public `MTA_` stop IDs merged
    across the bus feeds. Bus source stops without a public ID are traversed
    (a bus still passes them) but are never a boarding, alighting or walking
    point, and are left out of leg `stop_ids`. Trips whose route has no public ID
    are skipped.

Transfers (Y20)
    See TRANSFER_ASSUMPTIONS below; they are part of the API documentation.

Search (Y21/Y23)
    Round-based RAPTOR over scheduled trips departing in the 24 hours after the
    requested time (a vehicle must be boarded by then; it may arrive later). Round k finds the earliest arrival using at most k vehicles,
    so the result is the Pareto set over (transfers, arrival). Options arriving
    more than FEWER_TRANSFERS_SLACK_S after the earliest arrival are dropped.
    Journeys are ordered by transfers, then arrival, then id (fewest_transfers),
    at most three. Timing basis is the GTFS schedule only; no realtime rerouting.
"""
from array import array
from bisect import bisect_left
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from threading import Lock

from .schedule_service import EntityNotFound, _bus_catalog, _parse_imported
from .schedule_store import ScheduleUnavailable
from .service_calendar import ServiceDateOutOfRange, active_services
from .service_time import NEW_YORK, service_dates_between, service_day_origin, utc_iso

SUBWAY_CATALOG = Path(__file__).parents[1] / 'data' / 'generated' / 'catalog.json'
MODES = ('subway', 'bus')
SEARCH_SECONDS = 24 * 3600
MAX_VEHICLES = 5            # at most 4 transfers
MAX_JOURNEYS = 3
# A fewer-transfer journey is only offered if it arrives at most this long after the
# earliest-arriving journey found; otherwise a rare direct trip hours later would lead.
FEWER_TRANSFERS_SLACK_S = 3600

# --- Y20 transfer and walking assumptions --------------------------------------------------------
WALK_SPEED_MPS = 1.2        # conservative adult walking speed
WALK_DETOUR = 1.3           # street-grid detour over straight-line distance
BUS_WALK_RADIUS_M = 250     # bus stop <-> bus stop
CROSS_WALK_RADIUS_M = 300   # bus stop <-> subway station (station coordinates, not entrances)
BUS_WALK_BUFFER_S = 60      # added to every bus<->bus walk
STATION_WALK_BUFFER_S = 120 # added to every bus<->subway walk: entrances, stairs, fare control
BUS_SAME_STOP_CHANGE_S = 60
SUBWAY_DEFAULT_CHANGE_S = 180
TRANSFER_ASSUMPTIONS = {
    'subway_to_subway': 'MTA transfers.txt only: same-station rows give the change time, other rows are '
                        'in-complex transfers with their min_transfer_time; transfer_type 3 is never used. '
                        f'Stations without a row use {SUBWAY_DEFAULT_CHANGE_S} s.',
    'bus_same_stop': f'{BUS_SAME_STOP_CHANGE_S} s to change buses at the same stop.',
    'bus_to_bus': f'Walk between bus stops at most {BUS_WALK_RADIUS_M} m apart (straight line); MTA bus feeds '
                  'publish no transfers.',
    'bus_to_subway': f'Walk between a bus stop and a subway station at most {CROSS_WALK_RADIUS_M} m from the '
                     'station coordinates; enabled only when both modes are requested.',
    'walking_time': f'ceil(distance x {WALK_DETOUR} / {WALK_SPEED_MPS} m/s) plus {BUS_WALK_BUFFER_S} s (bus) or '
                    f'{STATION_WALK_BUFFER_S} s (station) buffer. Walks are not chained.',
}


class JourneyInputError(ValueError):
    """Malformed journey request (400)."""


class TransferUnavailable(ScheduleUnavailable):
    """The journey needs a transfer kind that has no supported data (503)."""


def _distance_m(a, b):
    lat = math.radians((a[0] + b[0]) / 2)
    dy = (a[0] - b[0]) * 111_320
    dx = (a[1] - b[1]) * 111_320 * math.cos(lat)
    return math.hypot(dx, dy)


def _walk_seconds(distance, buffer):
    return math.ceil(distance * WALK_DETOUR / WALK_SPEED_MPS) + buffer


def _coord(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return (lat, lon) if (lat, lon) != (0.0, 0.0) and -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _columns(connection, table):
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _tables(connection):
    return {name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# --- Y19 static graph: nodes, links, walking ------------------------------------------------------

class StaticGraph:
    """Nodes and walking/transfer links shared by every service day."""

    def __init__(self, store, *, cross_mode=True):
        self.keys, self.index, self.mode, self.public, self.coord = [], {}, [], [], []
        self.stop_nodes = {}       # feed -> {source stop_id: node}
        self.routes = {}           # feed -> {source route_id: public route_id}
        self.longest = {}          # feed -> max scheduled seconds
        self.change = []           # boarding change time after a vehicle arrival
        self.walks = {}            # node -> [(node, seconds, kind)]
        self.cross_mode = cross_mode
        subway_transfers = []
        for feed in store.manifest['feeds']:
            mode = 'subway' if feed == 'subway' else 'bus'
            with closing(store.connect(feed)) as connection:
                self._load_feed(feed, mode, connection)
                if mode == 'subway' and 'transfers' in _tables(connection):
                    columns = _columns(connection, 'transfers')
                    minimum = 'min_transfer_time' if 'min_transfer_time' in columns else 'NULL'
                    subway_transfers += connection.execute(
                        f'SELECT from_stop_id, to_stop_id, transfer_type, {minimum} FROM transfers').fetchall()
        self.change = [SUBWAY_DEFAULT_CHANGE_S if m == 'subway' else BUS_SAME_STOP_CHANGE_S for m in self.mode]
        self._subway_transfers(subway_transfers)
        self._proximity_walks()

    def node(self, key, mode, public, coord):
        if key not in self.index:
            self.index[key] = len(self.keys)
            self.keys.append(key); self.mode.append(mode); self.public.append(public); self.coord.append(coord)
        elif self.coord[self.index[key]] is None:
            self.coord[self.index[key]] = coord
        return self.index[key]

    def _load_feed(self, feed, mode, connection):
        links = dict(connection.execute(
            "SELECT source_id, public_id FROM entity_links WHERE entity_type = 'stop'").fetchall())
        self.routes[feed] = {s: p for s, p in connection.execute(
            "SELECT source_id, public_id FROM entity_links WHERE entity_type = 'route'") if p}
        columns = _columns(connection, 'stops')
        coords = {}
        if {'stop_lat', 'stop_lon'} <= columns:
            coords = {s: _coord(lat, lon) for s, lat, lon in
                      connection.execute('SELECT stop_id, stop_lat, stop_lon FROM stops')}
        nodes = {}
        for source in (s for (s,) in connection.execute('SELECT DISTINCT stop_id FROM stop_times')):
            public = links.get(source)
            if public:
                key = (mode, public)
                coord = coords.get(public) if mode == 'subway' and coords.get(public) else coords.get(source)
                nodes[source] = self.node(key, mode, public, coord)
            else:   # traversed only: no public ID, so never an endpoint or a walk point
                nodes[source] = self.node(('internal', feed, source), mode, None, None)
        self.stop_nodes[feed] = nodes
        self.longest[feed] = connection.execute(
            'SELECT max(max(coalesce(arrival_seconds, 0)), max(coalesce(departure_seconds, 0))) FROM stop_times'
        ).fetchone()[0] or 0

    def _add_walk(self, a, b, seconds, kind):
        self.walks.setdefault(a, []).append((b, seconds, kind))

    def _subway_transfers(self, rows):
        best = {}
        for source, target, kind, minimum in rows:
            a, b = self.index.get(('subway', source)), self.index.get(('subway', target))
            if a is None or b is None or str(kind) == '3':
                continue
            seconds = int(minimum) if str(minimum or '').isdigit() else SUBWAY_DEFAULT_CHANGE_S
            if a == b:
                self.change[a] = seconds
            else:
                best[(a, b)] = min(seconds, best.get((a, b), seconds))
        for (a, b), seconds in sorted(best.items()):
            self._add_walk(a, b, seconds, 'subway')

    def _proximity_walks(self):
        cell = 0.004                      # degrees; > both radii in latitude and longitude at NYC
        grid = {}
        for node, coord in enumerate(self.coord):
            if coord is not None and self.public[node] is not None:
                grid.setdefault((int(coord[0] // cell), int(coord[1] // cell)), []).append(node)
        for (gy, gx), members in grid.items():
            for a in members:
                if self.mode[a] != 'bus':
                    continue
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        for b in grid.get((gy + dy, gx + dx), ()):
                            if a == b:
                                continue
                            distance = _distance_m(self.coord[a], self.coord[b])
                            if self.mode[b] == 'bus' and distance <= BUS_WALK_RADIUS_M:
                                self._add_walk(a, b, _walk_seconds(distance, BUS_WALK_BUFFER_S), 'bus')
                            elif self.mode[b] == 'subway' and self.cross_mode and distance <= CROSS_WALK_RADIUS_M:
                                seconds = _walk_seconds(distance, STATION_WALK_BUFFER_S)
                                self._add_walk(a, b, seconds, 'cross')
                                self._add_walk(b, a, seconds, 'cross')
        for links in self.walks.values():
            links.sort()

    def target(self, node):
        mode = self.mode[node]
        return {'type': 'station' if mode == 'subway' else 'stop', 'mode': mode, 'id': self.public[node]}


# --- Y19 timetables: patterns of scheduled trips ---------------------------------------------------

@dataclass
class Pattern:
    mode: str
    route_id: str
    stops: tuple          # node per position
    board: bytes          # 1 if pickup allowed
    alight: bytes         # 1 if drop-off allowed
    trips: list           # (feed, service_date, trip_id) per trip column
    arr: array            # position-major: arr[pos * T + trip]
    dep: array

    @property
    def size(self):
        return len(self.trips)


def _load_day(graph, store, feed, day):
    """{pattern_key: [(trip_id, arr_seconds, dep_seconds)]} for one feed and service date."""
    mode = 'subway' if feed == 'subway' else 'bus'
    with closing(store.connect(feed)) as connection:
        services = active_services(connection, day).active
        if not services:
            return {}
        columns = _columns(connection, 'stop_times')
        pickup = "coalesce(st.pickup_type, '')" if 'pickup_type' in columns else "''"
        drop = "coalesce(st.drop_off_type, '')" if 'drop_off_type' in columns else "''"
        direction = 't.direction_id' if 'direction_id' in _columns(connection, 'trips') else 'NULL'
        rows = connection.execute(
            f'''SELECT st.trip_id, t.route_id, {direction}, st.stop_id, st.arrival_seconds, st.departure_seconds,
                       {pickup}, {drop}
                FROM stop_times st JOIN trips t ON t.trip_id = st.trip_id
                WHERE t.service_id IN ({",".join("?" * len(services))})
                ORDER BY st.trip_id, st.stop_sequence''', services)
        stop_nodes, routes, public = graph.stop_nodes[feed], graph.routes[feed], graph.public
        patterns, current, buffer = {}, None, []

        def flush():
            if current is None or len(buffer) < 2:
                return
            trip_id, route = current
            route_id = routes.get(route)
            if not route_id:
                return
            nodes, board, alight, arr, dep = [], bytearray(), bytearray(), array('i'), array('i')
            last = len(buffer) - 1
            for i, (stop, a, d, p, o) in enumerate(buffer):
                node = stop_nodes[stop]
                a = d if a is None else a
                d = a if d is None else d
                if a is None:
                    return              # untimed stop: the trip cannot be timed reliably
                linked = public[node] is not None
                nodes.append(node); arr.append(a); dep.append(d)
                board.append(1 if linked and i < last and p != '1' else 0)
                alight.append(1 if linked and i > 0 and o != '1' else 0)
            key = (mode, route_id, tuple(nodes), bytes(board), bytes(alight))
            patterns.setdefault(key, []).append((trip_id, arr, dep))

        for trip_id, route, _direction, stop, a, d, p, o in rows:
            if current is None or current[0] != trip_id:
                flush()
                current, buffer = (trip_id, route), []
            buffer.append((stop, a, d, p, o))
        flush()
    return patterns


class Timetable:
    """Patterns for an absolute time window, trips split so no trip overtakes another."""

    def __init__(self, graph, day_patterns, start, end):
        grouped = {}
        for feed, day, patterns in day_patterns:
            origin = int(service_day_origin(day).timestamp())
            for key, trips in patterns.items():
                for trip_id, arr, dep in trips:
                    if origin + arr[-1] < start or origin + dep[0] > end:
                        continue
                    grouped.setdefault(key, []).append(((feed, day, trip_id), origin, arr, dep))
        self.patterns, self.node_patterns = [], {}
        for key in sorted(grouped, key=lambda k: (k[1], k[2], k[3], k[4])):
            trips = sorted(grouped[key], key=lambda t: (t[1] + t[3][0], t[0][1], t[0][2]))
            for group in self._fifo(trips):
                self._add(key, group)

    @staticmethod
    def _fifo(trips):
        groups = []
        for trip in trips:
            for group in groups:
                last = group[-1]
                if all(trip[1] + trip[2][i] >= last[1] + last[2][i] and trip[1] + trip[3][i] >= last[1] + last[3][i]
                       for i in range(len(trip[2]))):
                    group.append(trip)
                    break
            else:
                groups.append([trip])
        return groups

    def _add(self, key, trips):
        mode, route_id, nodes, board, alight = key
        count = len(trips)
        arr, dep = array('q', bytes(8 * len(nodes) * count)), array('q', bytes(8 * len(nodes) * count))
        for column, (_, origin, a, d) in enumerate(trips):
            for position in range(len(nodes)):
                arr[position * count + column] = origin + a[position]
                dep[position * count + column] = origin + d[position]
        index = len(self.patterns)
        self.patterns.append(Pattern(mode, route_id, nodes, board, alight, [t[0] for t in trips], arr, dep))
        for position, node in enumerate(nodes):
            if board[position] or alight[position]:
                self.node_patterns.setdefault(node, []).append((index, position))


# --- Y21/Y23 search ---------------------------------------------------------------------------------

def raptor(graph, timetable, origin, destination, start, end, modes):
    """Return {vehicles: (arrival, legs)} for the Pareto set over (vehicles, arrival)."""
    allowed_walk = {'subway'} if modes == {'subway'} else {'bus'} if modes == {'bus'} else {'subway', 'bus', 'cross'}
    walks = graph.walks
    best = {origin: start}
    labels = [{origin: (start, 'origin', None)}]
    vehicle_labels = [{}]
    latest = {origin: (start, 0)}
    for target, seconds, kind in walks.get(origin, ()):
        if kind in allowed_walk and start + seconds < best.get(target, math.inf):
            best[target] = start + seconds
            labels[0][target] = (start + seconds, 'walk', (origin, seconds))
            latest[target] = (start + seconds, 0)
    marked = set(labels[0])
    results = {}
    if destination in labels[0]:
        results[0] = labels[0][destination][0]
    patterns, node_patterns = timetable.patterns, timetable.node_patterns
    for k in range(1, MAX_VEHICLES + 1):
        queue = {}
        for node in marked:
            for index, position in node_patterns.get(node, ()):
                if position < queue.get(index, math.inf):
                    queue[index] = position
        if not queue:
            break
        vehicles = {}
        for index, first in queue.items():
            pattern = patterns[index]
            if pattern.mode not in modes:
                continue
            count, stops, board, alight, arr, dep = (pattern.size, pattern.stops, pattern.board, pattern.alight,
                                                     pattern.arr, pattern.dep)
            trip, board_at, board_round = -1, -1, -1
            for position in range(first, len(stops)):
                node = stops[position]
                base = position * count
                if trip >= 0 and alight[position]:
                    arrival = arr[base + trip]
                    if arrival < best.get(node, math.inf) and arrival < best.get(destination, math.inf):
                        best[node] = arrival
                        vehicles[node] = (arrival, index, trip, board_at, position, board_round)
                if board[position]:
                    ready = latest.get(node)
                    if ready is not None and (trip < 0 or ready[0] <= dep[base + trip]):
                        column = bisect_left(dep, ready[0], base, base + count) - base
                        if column < count and (trip < 0 or column < trip) and dep[base + column] <= end:
                            trip, board_at, board_round = column, position, ready[1]
        round_labels = {node: (v[0], 'vehicle', None) for node, v in vehicles.items()}
        for node, v in vehicles.items():
            for target, seconds, kind in walks.get(node, ()):
                arrival = v[0] + seconds
                if kind in allowed_walk and arrival < best.get(target, math.inf) \
                        and arrival < best.get(destination, math.inf):
                    best[target] = arrival
                    round_labels[target] = (arrival, 'walk', (node, seconds))
        for node, (arrival, kind, _) in round_labels.items():
            latest[node] = (arrival + graph.change[node] if kind == 'vehicle' else arrival, k)
        labels.append(round_labels); vehicle_labels.append(vehicles)
        if destination in round_labels:
            results[k] = round_labels[destination][0]
        marked = set(round_labels)
        if not marked:
            break
    return {k: _legs(graph, timetable, labels, vehicle_labels, k, destination) for k in results}


def _legs(graph, timetable, labels, vehicle_labels, k, node):
    def walk(source, target, arrival, seconds):
        return {'kind': 'walk', 'from': source, 'to': target, 'departure': arrival - seconds, 'arrival': arrival}

    def ride(k, node):
        arrival, index, trip, board_at, alight_at, board_round = vehicle_labels[k][node]
        pattern = timetable.patterns[index]
        start = pattern.stops[board_at]
        leg = {'kind': 'ride', 'pattern': pattern, 'trip': trip, 'board': board_at, 'alight': alight_at,
               'from': start, 'to': node, 'departure': pattern.dep[board_at * pattern.size + trip],
               'arrival': arrival}
        return trace(board_round, start) + [leg]

    def trace(k, node):
        arrival, kind, info = labels[k][node]
        if kind == 'origin':
            return []
        if kind == 'walk':
            source, seconds = info
            return (ride(k, source) if k > 0 else []) + [walk(source, node, arrival, seconds)]
        return ride(k, node)

    return trace(k, node)


# --- Y22 legs and the response ----------------------------------------------------------------------

def _leg_dict(graph, leg):
    departure, arrival = leg['departure'], leg['arrival']
    item = {'mode': 'walk', 'route_id': None, 'from': graph.target(leg['from']), 'to': graph.target(leg['to']),
            'departure_time': utc_iso(datetime.fromtimestamp(departure, timezone.utc)),
            'arrival_time': utc_iso(datetime.fromtimestamp(arrival, timezone.utc)),
            'duration_seconds': arrival - departure, 'stop_ids': []}
    if leg['kind'] == 'ride':
        pattern = leg['pattern']
        item['mode'], item['route_id'] = pattern.mode, pattern.route_id
        item['stop_ids'] = [graph.public[n] for n in pattern.stops[leg['board']:leg['alight'] + 1]
                            if graph.public[n] is not None]
    return item


def _journey(graph, legs, start):
    """Leading walks end when the first vehicle leaves; later walks start on arrival."""
    rides = [i for i, leg in enumerate(legs) if leg['kind'] == 'ride']
    if rides:
        shift_to = legs[rides[0]]['departure']
        for leg in reversed(legs[:rides[0]]):
            seconds = leg['arrival'] - leg['departure']
            leg['arrival'], leg['departure'] = shift_to, shift_to - seconds
            shift_to = leg['departure']
    items = [_leg_dict(graph, leg) for leg in legs]
    signature = json.dumps([[leg['kind'], leg['pattern'].trips[leg['trip']][0],
                             leg['pattern'].trips[leg['trip']][1].isoformat(), leg['pattern'].trips[leg['trip']][2]]
                            if leg['kind'] == 'ride' else ['walk', graph.keys[leg['from']], graph.keys[leg['to']]]
                            for leg in legs] + [start], default=str)
    departure, arrival = (legs[0]['departure'], legs[-1]['arrival']) if legs else (start, start)
    return {'id': 'j-' + hashlib.sha256(signature.encode()).hexdigest()[:16],
            'departure_time': utc_iso(datetime.fromtimestamp(departure, timezone.utc)),
            'arrival_time': utc_iso(datetime.fromtimestamp(arrival, timezone.utc)),
            'duration_seconds': arrival - departure, 'transfers': max(0, len(rides) - 1), 'legs': items}


class JourneyPlanner:
    """Caches the static graph and recent timetables; thread-safe."""

    def __init__(self, store, *, cross_mode=True, slack=FEWER_TRANSFERS_SLACK_S, subway_catalog=None,
                 bus_catalog=_bus_catalog,
                 day_cache=24, window_cache=2):
        self.store, self.cross_mode, self.slack = store, cross_mode, slack
        self.subway_catalog = Path(subway_catalog or SUBWAY_CATALOG)
        self.bus_catalog = bus_catalog
        self._graph, self._subway_ids = None, None
        self._days, self._windows = OrderedDict(), OrderedDict()
        self._day_cache, self._window_cache = day_cache, window_cache
        self._lock = Lock()

    @property
    def graph(self):
        with self._lock:
            if self._graph is None:
                self._graph = StaticGraph(self.store, cross_mode=self.cross_mode)
            return self._graph

    def _known(self, target):
        if target['mode'] == 'bus':
            return target['id'] in self.bus_catalog()[0]
        if self._subway_ids is None:
            try:
                catalog = json.loads(self.subway_catalog.read_text(encoding='utf-8'))
                self._subway_ids = {s['id'] for s in catalog['stations']}
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ScheduleUnavailable('Subway catalog is unavailable') from error
        return target['id'] in self._subway_ids

    def _resolve(self, graph, target):
        node = graph.index.get((target['mode'], target['id']))
        if node is None:
            if not self._known(target):
                raise EntityNotFound(('Station' if target['mode'] == 'subway' else 'Stop') + ' not found.')
            raise ScheduleUnavailable(f'No scheduled trips are available for {target["type"]} {target["id"]}')
        return node

    def _day(self, graph, feed, day):
        key = (feed, day)
        with self._lock:
            if key in self._days:
                self._days.move_to_end(key)
                return self._days[key]
        patterns = _load_day(graph, self.store, feed, day)
        with self._lock:
            self._days[key] = patterns
            while len(self._days) > self._day_cache:
                self._days.popitem(last=False)
        return patterns

    def timetable(self, graph, modes, start):
        """Timetable for [hour(start), hour(start) + 25 h], shared by requests in the same hour."""
        window_start = start - start % 3600
        window_end = window_start + SEARCH_SECONDS + 3600
        key = (tuple(sorted(modes)), window_start)
        with self._lock:
            if key in self._windows:
                self._windows.move_to_end(key)
                return self._windows[key]
        requested = datetime.fromtimestamp(start, timezone.utc).astimezone(NEW_YORK).date()
        day_patterns = []
        for mode in sorted(modes):
            feeds = self.store.feeds(mode)
            if not feeds:
                raise ScheduleUnavailable(f'No {mode} schedules are available')
            for feed in feeds:
                lo = datetime.fromtimestamp(window_start, timezone.utc)
                hi = datetime.fromtimestamp(window_end, timezone.utc)
                for day in service_dates_between(lo, hi, graph.longest[feed]):
                    try:
                        day_patterns.append((feed, day, self._day(graph, feed, day)))
                    except ServiceDateOutOfRange as error:
                        if day == requested:   # the requested day itself is not published
                            raise ScheduleUnavailable(str(error)) from error
        timetable = Timetable(graph, day_patterns, window_start, window_end)
        with self._lock:
            self._windows[key] = timetable
            while len(self._windows) > self._window_cache:
                self._windows.popitem(last=False)
        return timetable

    def plan(self, request):
        origin, destination, departure, modes = parse_request(request)
        updated_at = utc_iso(_parse_imported(self.store.updated_at))
        envelope = {'source': 'mta', 'updated_at': updated_at, 'timing_basis': 'schedule',
                    'optimization': 'fewest_transfers'}
        graph = self.graph
        if origin['mode'] != destination['mode'] and not self.cross_mode:
            raise TransferUnavailable('Transfer data is unavailable for this journey.')
        start_node, end_node = self._resolve(graph, origin), self._resolve(graph, destination)
        start = int(departure.timestamp())
        if start_node == end_node:
            return {**envelope, 'journeys': [_journey(graph, [], start)], 'no_path_reason': None}
        timetable = self.timetable(graph, modes, start)
        found = raptor(graph, timetable, start_node, end_node, start, start + SEARCH_SECONDS, set(modes))
        journeys, seen = [], set()
        for vehicles in sorted(found):
            journey = _journey(graph, found[vehicles], start)
            if journey['id'] not in seen:
                seen.add(journey['id']); journeys.append(journey)
        if journeys and self.slack is not None:
            earliest = min(j['arrival_time'] for j in journeys)
            limit = utc_iso(datetime.fromisoformat(earliest.replace('Z', '+00:00')) + timedelta(seconds=self.slack))
            journeys = [j for j in journeys if j['arrival_time'] <= limit]
        journeys.sort(key=lambda j: (j['transfers'], j['arrival_time'], j['id']))
        journeys = journeys[:MAX_JOURNEYS]
        return {**envelope, 'journeys': journeys, 'no_path_reason': None if journeys else 'no_service_in_window'}


# --- request validation -------------------------------------------------------------------------------

def _target(value, name):
    if not isinstance(value, dict) or set(value) != {'type', 'mode', 'id'}:
        raise JourneyInputError(f'{name} must be a Target with type, mode and id.')
    kind, mode, identifier = value['type'], value['mode'], value['id']
    if (kind, mode) not in (('station', 'subway'), ('stop', 'bus')):
        raise JourneyInputError(f'{name} must be a subway station or a bus stop.')
    if not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip():
        raise JourneyInputError(f'{name}.id must be a non-empty string.')
    return value


def parse_request(body):
    if not isinstance(body, dict):
        raise JourneyInputError('Request body must be a JSON object.')
    unknown = set(body) - {'origin', 'destination', 'departure_time', 'modes', 'optimization'}
    if unknown:
        raise JourneyInputError(f'Unknown field {sorted(unknown)[0]}.')
    origin, destination = _target(body.get('origin'), 'origin'), _target(body.get('destination'), 'destination')
    modes = body.get('modes')
    if not isinstance(modes, list) or not modes or any(m not in MODES for m in modes) or len(set(modes)) != len(modes):
        raise JourneyInputError('modes must be a non-empty list of distinct values: subway, bus.')
    for name, target in (('origin', origin), ('destination', destination)):
        if target['mode'] not in modes:
            raise JourneyInputError(f'{name} mode must be included in modes.')
    if body.get('optimization', 'fewest_transfers') != 'fewest_transfers':
        raise JourneyInputError('optimization must be fewest_transfers.')
    text = body.get('departure_time')
    try:
        if not isinstance(text, str) or 'T' not in text:
            raise ValueError
        departure = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if departure.tzinfo is None or departure.utcoffset() is None:
            raise ValueError
    except ValueError as error:
        raise JourneyInputError('departure_time must be an ISO 8601 timestamp with a timezone.') from error
    return origin, destination, departure.astimezone(timezone.utc).replace(microsecond=0), modes
