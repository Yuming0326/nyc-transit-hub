"""Y11: MTA bus GTFS-realtime alerts mapped to the imported Y4 bus catalog.

Source: the official camsys bus-alerts GTFS-RT feed (no key). Its informed_entity
selectors use GTFS identifiers: agency_id "MTA NYCT"/"MTABC", route_id such as
"B63" or "Q53+", and numeric stop_id such as "308214". The catalog uses Bus Time
IDs, which are the same source values qualified by agency: "MTA NYCT_B63" and
"MTA_308214". Mapping only accepts IDs that exist in the catalog; anything else
is kept in unmapped_* lists, never guessed from names or text.

Selectors keep GTFS-RT semantics: fields within one selector are AND, separate
selectors are OR. route_ids/stop_ids are summaries; use `targets` for matching.
"""
import time

from google.protobuf.json_format import MessageToDict
from google.transit import gtfs_realtime_pb2 as rt

from ..cache import TTLCache
from .mta_client import BASE_URL, MTAError, fetch_feed, normalize_alerts, utc, validate_freshness

BUS_ALERTS_URL = BASE_URL + 'camsys%2Fbus-alerts'
SUPPORTED_FIELDS = {'agency_id', 'route_id', 'stop_id', 'direction_id'}
DISRUPTIVE = {getattr(rt.Alert, name, None) for name in (
    'NO_SERVICE', 'REDUCED_SERVICE', 'SIGNIFICANT_DELAYS', 'DETOUR', 'MODIFIED_SERVICE',
    'STOP_MOVED', 'ACCESSIBILITY_ISSUE')} - {None}
INFORMATIVE = {getattr(rt.Alert, name, None) for name in ('ADDITIONAL_SERVICE', 'NO_EFFECT')} - {None}


class BusCatalogIndex:
    """Exact source-ID lookups into the Y4 catalog."""

    def __init__(self, catalog):
        self.routes = {r['id']: r for r in catalog['routes']}
        self.stops = {s['id']: s for s in catalog['stops']}
        self.route_agencies = {r['agency_id'] for r in catalog['routes']}
        self.agencies = {a['id'] for a in catalog.get('agencies', [])} | self.route_agencies
        by_source = {}
        for route in catalog['routes']:
            by_source.setdefault(route['id'].split('_', 1)[1], []).append(route['id'])
        # Only unambiguous source route IDs may be resolved without an agency.
        self.unique_source_routes = {k: v[0] for k, v in by_source.items() if len(v) == 1}

    def route(self, agency_id, route_id):
        if not route_id:
            return None
        if route_id in self.routes:  # Already a qualified Bus Time ID.
            return route_id
        if agency_id:
            qualified = f'{agency_id}_{route_id}'
            return qualified if qualified in self.routes else None
        return self.unique_source_routes.get(route_id)

    def stop(self, stop_id):
        if not stop_id:
            return None
        qualified = stop_id if stop_id.startswith('MTA_') else f'MTA_{stop_id}'
        return qualified if qualified in self.stops else None


def alert_impact(alert):
    if not alert.HasField('effect'):
        return 'unknown'
    if alert.effect in DISRUPTIVE:
        return 'disruption'
    return 'information' if alert.effect in INFORMATIVE else 'unknown'


def normalize_bus_alerts(feed, catalog, *, now=None, index=None):
    """Return active bus alerts with catalog-mapped affected routes/stops."""
    index = index or BusCatalogIndex(catalog)
    active = {a['id']: a for a in normalize_alerts(feed, now=now)['alerts']}
    results = []
    for entity in feed.entity:
        if entity.id not in active or entity.is_deleted or not entity.HasField('alert'):
            continue
        alert = entity.alert
        selectors = [MessageToDict(s, preserving_proto_field_name=True) for s in alert.informed_entity]
        targets, routes, stops, unmapped_routes, unmapped_stops = [], set(), set(), set(), set()
        uncertain = not selectors
        network = False
        for row in selectors:
            agency = row.get('agency_id')
            direction = row.get('direction_id')
            if not row or set(row) - SUPPORTED_FIELDS or (agency and agency not in index.agencies) \
                    or direction not in (None, 0, 1):
                uncertain = True
                continue
            route = index.route(agency, row.get('route_id'))
            stop = index.stop(row.get('stop_id'))
            if row.get('route_id') and route is None:
                unmapped_routes.add(row['route_id'])
            if row.get('stop_id') and stop is None:
                unmapped_stops.add(row['stop_id'])
            if (row.get('route_id') and route is None) or (row.get('stop_id') and stop is None):
                uncertain = True
                continue
            if set(row) == {'agency_id'}:
                # Agency-wide (MTA NYCT or MTABC bus) notice; not proof of any route's status.
                network = agency in index.route_agencies
                uncertain = uncertain or not network
                if network:
                    targets.append({'agency_id': agency, 'route_id': None, 'stop_id': None, 'direction_id': None})
                continue
            if route:
                routes.add(route)
            if stop:
                stops.add(stop)
            targets.append({'agency_id': agency, 'route_id': route, 'stop_id': stop,
                            'direction_id': None if direction is None else str(direction)})
        if uncertain:
            scope = 'unknown'
        elif network:
            scope = 'network'
        elif any(t['route_id'] and not t['stop_id'] for t in targets):
            scope = 'route'
        elif stops:
            scope = 'stop'
        else:
            scope = 'unknown'
        legacy = active[entity.id]
        results.append({'id': legacy['id'], 'header': legacy['header'], 'description': legacy['description'],
                        'route_ids': sorted(routes), 'station_ids': [], 'stop_ids': sorted(stops),
                        'scope': scope, 'impact': alert_impact(alert), 'targets': targets,
                        'unmapped_route_ids': sorted(unmapped_routes), 'unmapped_stop_ids': sorted(unmapped_stops),
                        'selectors': selectors})
    return {'mode': 'bus', 'source': 'mta', 'updated_at': utc(feed.header.timestamp),
            'alerts': sorted(results, key=lambda a: a['id'])}


def filter_bus_alerts(result, catalog, *, route_id=None, stop_id=None, index=None):
    """Apply the prepared /api/transit/alerts bus semantics to normalized alerts.

    Network-wide notices are always included. With stop_id, a notice is exact
    when a target names the stop; notices targeting a route that serves the stop
    without a stop restriction are route-relevant, so coverage becomes "route".
    Other notices are included only when one of their catalog-mapped targets
    matches; unmapped selectors never match anything.
    """
    index = index or BusCatalogIndex(catalog)
    if route_id is not None and route_id not in index.routes:
        raise KeyError('Unknown bus route')
    if stop_id is not None and stop_id not in index.stops:
        raise KeyError('Unknown bus stop')
    if route_id and stop_id and route_id not in index.stops[stop_id]['route_ids']:
        raise ValueError('The bus route does not serve this stop in the catalog.')
    if route_id is None and stop_id is None:
        return {**result, 'coverage': 'route'}
    stop_routes = set(index.stops[stop_id]['route_ids']) if stop_id else None
    selected, route_level = [], False
    for alert in result['alerts']:
        if alert['scope'] == 'network':
            selected.append(alert)
            continue
        match = None
        for target in alert['targets']:
            if target['route_id'] is None and target['stop_id'] is None:
                continue
            if route_id and target['route_id'] not in (None, route_id):
                continue
            if stop_id:
                if target['stop_id'] == stop_id:
                    match = 'stop'
                    break
                if target['stop_id'] is None and target['route_id'] in stop_routes:
                    match = match or 'route'
            elif target['route_id'] == route_id or (target['route_id'] is None and
                                                    route_id in index.stops[target['stop_id']]['route_ids']):
                match = 'route' if target['stop_id'] is None else (match or 'stop')
        if match:
            selected.append(alert)
            route_level = route_level or match == 'route'
    coverage = 'stop' if stop_id and not route_level else 'route'
    return {**result, 'coverage': coverage, 'alerts': selected}


class BusAlertsClient:
    """Fetches the bus alerts feed; validated snapshots are reused for `ttl` seconds
    and re-validated for freshness on every use. Failures are never cached."""

    def __init__(self, catalog, *, timeout=(3.05, 10), max_age=600, ttl=30, session=None):
        self.catalog = catalog
        self.index = BusCatalogIndex(catalog)
        self.timeout = timeout
        self.max_age = max_age
        self.ttl = ttl
        self.session = session
        self.cache = TTLCache()

    def feed(self, now=None):
        def load():
            return fetch_feed(BUS_ALERTS_URL, timeout=self.timeout, max_age=self.max_age, now=now,
                              session=self.session)
        feed = self.cache.get_or_load('bus-alerts', self.ttl, load)
        try:
            validate_freshness(feed, max_age=self.max_age, now=now)  # Recheck cached snapshots.
        except MTAError:
            self.cache.evict('bus-alerts')
            raise
        return feed

    def alerts(self, route_id=None, stop_id=None, *, now=None):
        now = time.time() if now is None else now
        result = normalize_bus_alerts(self.feed(now=now), self.catalog, now=now, index=self.index)
        return filter_bus_alerts(result, self.catalog, route_id=route_id, stop_id=stop_id, index=self.index)

