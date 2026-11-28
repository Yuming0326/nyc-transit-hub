"""Y13: GET /api/transit/alerts over the Y9 subway and Y11 bus affected-alert normalizers."""
import re
from datetime import datetime, timezone

from flask import current_app
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from .mta_client import MTAError

FIELDS = ('id', 'header', 'description', 'route_ids', 'station_ids', 'stop_ids', 'scope', 'impact')
UNAVAILABLE = 'Live MTA data is temporarily unavailable. Please retry.'


def _single(args, key):
    values = args.getlist(key)
    if len(values) > 1:
        raise BadRequest(f'{key} must be supplied once.')
    if values and not values[0].strip():
        raise BadRequest(f'{key} must not be empty.')
    return values[0] if values else None


def _project(result, coverage, alerts):
    return {'mode': result['mode'], 'source': result['source'], 'updated_at': result['updated_at'],
            'coverage': coverage, 'alerts': [{key: alert[key] for key in FIELDS} for alert in alerts]}


def filter_subway_alerts(result, catalog, route_id=None, station_id=None):
    """Network notices always apply. A station is exact ("stop" coverage) only when an
    alert names it; route-scoped notices for the station's routes make coverage "route"."""
    station_routes = None
    if station_id is not None:
        station = next(s for s in catalog['stations'] if s['id'] == station_id)
        station_routes = set(station['routes'])
        if route_id is not None and route_id not in station_routes:
            raise BadRequest('The subway route does not serve this station in the catalog.')
    if route_id is None and station_id is None:
        return 'route', result['alerts']
    selected, route_level = [], False
    for alert in result['alerts']:
        if alert['scope'] == 'network':
            selected.append(alert)
            continue
        routes = set(alert['route_ids'])
        if route_id is not None and routes and route_id not in routes:
            continue
        if station_id is not None:
            if station_id in alert['station_ids']:
                selected.append(alert)
            elif alert['scope'] == 'route' and routes & station_routes:
                selected.append(alert)
                route_level = True
        elif route_id in routes:
            selected.append(alert)
    return ('stop' if station_id is not None and not route_level else 'route'), selected


def transit_alerts(args):
    mode = _single(args, 'mode')
    if mode not in ('subway', 'bus'):
        raise BadRequest('mode must be subway or bus.')
    route_id, station_id, stop_id = (_single(args, key) for key in ('route_id', 'station_id', 'stop_id'))
    if mode == 'subway' and stop_id is not None:
        raise BadRequest('stop_id is only valid for bus alerts; use station_id for subway.')
    if mode == 'bus' and station_id is not None:
        raise BadRequest('station_id is only valid for subway alerts; use stop_id for bus.')
    if mode == 'bus' and stop_id is not None and not re.fullmatch(r'MTA_\d+', stop_id):
        raise BadRequest('stop_id must be an MTA-qualified numeric ID.')
    if mode == 'bus' and route_id is not None and '_' not in route_id:
        raise BadRequest('route_id must be a full bus route ID.')
    if current_app.config['TRANSIT_MODE'] != 'live':
        return _demo(mode, route_id)
    try:
        if mode == 'subway':
            client = current_app.extensions['transit']['client']
            catalog = client.catalog
            if route_id is not None and route_id not in {r['id'] for r in catalog['routes']}:
                raise NotFound('Subway route not found.')
            if station_id is not None and station_id not in {s['id'] for s in catalog['stations']}:
                raise NotFound('Station not found')
            result = client.affected_alerts()
            coverage, alerts = filter_subway_alerts(result, catalog, route_id, station_id)
            return _project(result, coverage, alerts)
        client = current_app.extensions['bus']['alerts']
        # Validate against the catalog before any upstream request.
        if route_id is not None and route_id not in client.index.routes:
            raise NotFound('Bus route not found.')
        if stop_id is not None and stop_id not in client.index.stops:
            raise NotFound('Bus stop not found.')
        if route_id and stop_id and route_id not in client.index.stops[stop_id]['route_ids']:
            raise BadRequest('The bus route does not serve this stop in the catalog.')
        result = client.alerts(route_id=route_id, stop_id=stop_id)
        return _project(result, result['coverage'], result['alerts'])
    except MTAError as error:
        current_app.logger.warning('%s affected alerts unavailable: %s', mode, error)
        raise ServiceUnavailable(UNAVAILABLE) from error


def _demo(mode, route_id):
    route = 'R' if mode == 'subway' else 'MTA NYCT_B63'
    alerts = [{'id': 'demo-alert', 'header': 'Illustrative disruption (sample)',
               'description': 'Fictional notice for interface development. Check official MTA information.',
               'route_ids': [route], 'station_ids': [], 'stop_ids': [], 'scope': 'route', 'impact': 'disruption'}]
    return {'mode': mode, 'source': 'demo',
            'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(), 'coverage': 'route',
            'alerts': [a for a in alerts if route_id is None or route_id in a['route_ids']]}
