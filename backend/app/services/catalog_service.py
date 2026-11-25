"""Y13: public discovery/detail endpoints over the imported static catalogs.

Static catalogs come from validated official imports (Y2 subway, Y4 bus), so
responses use source "mta" and updated_at = catalog import time. Like the map,
they are served in live mode only; demo mode returns 503 instead of inventing data.
"""
from datetime import datetime, timezone

from flask import current_app
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from .transit_service import station_by_id

DEMO_UNAVAILABLE = 'Catalog data is unavailable in demo mode.'
STOP_FIELDS = ('id', 'name', 'latitude', 'longitude')


def _live():
    if current_app.config['TRANSIT_MODE'] != 'live':
        raise ServiceUnavailable(DEMO_UNAVAILABLE)


def _subway():
    _live()
    return current_app.extensions['transit']['client'].catalog


def _bus():
    _live()
    return current_app.extensions['bus']['client'].catalog


def _imported_at(catalog):
    value = (catalog.get('metadata') or {}).get('imported_at')
    if not value:
        raise ServiceUnavailable('Catalog provenance is unavailable. Please retry.')
    return value


def _search(args):
    values = args.getlist('search')
    if len(values) > 1:
        raise BadRequest('search must be supplied once.')
    return values[0].strip().casefold() if values else ''


def _route(route):
    return {key: route[key] for key in ('id', 'name', 'short_name')}


def _stop(stop):
    return {key: stop[key] for key in STOP_FIELDS}


def station_detail(station_id):
    station = station_by_id(station_id)
    if current_app.config['TRANSIT_MODE'] == 'live':
        return {'station': station, 'source': 'mta', 'updated_at': _imported_at(_subway())}
    return {'station': station, 'source': 'demo',
            'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat()}


def subway_routes(args):
    query = _search(args)
    catalog = _subway()
    routes = [_route(r) for r in catalog['routes']
              if query in f"{r['id']} {r['short_name']} {r['name']}".casefold()]
    return {'mode': 'subway', 'source': 'mta', 'updated_at': _imported_at(catalog), 'routes': routes}


def subway_route_detail(route_id):
    catalog = _subway()
    route = next((r for r in catalog['routes'] if r['id'] == route_id), None)
    if route is None:
        raise NotFound('Subway route not found.')
    return {'mode': 'subway', 'source': 'mta', 'updated_at': _imported_at(catalog), 'route': _route(route),
            'stations': [s for s in catalog['stations'] if route_id in s['routes']]}


def bus_routes(args):
    query = _search(args)
    catalog = _bus()
    return {'mode': 'bus', 'source': 'mta', 'routes': [
        _route(r) for r in catalog['routes'] if query in f"{r['short_name']} {r['name']}".casefold()]}


def _bus_route(catalog, route_id):
    route = next((r for r in catalog['routes'] if r['id'] == route_id), None)
    if route is None:
        raise NotFound('Bus route not found.')
    return route


def _route_stops(catalog, route_id):
    by_id = {s['id']: s for s in catalog['stops']}
    # route_stop_ids is membership in source order, not a universal travel order.
    return [_stop(by_id[stop_id]) for stop_id in catalog['route_stop_ids'].get(route_id, []) if stop_id in by_id]


def bus_route_detail(route_id):
    catalog = _bus()
    route = _bus_route(catalog, route_id)
    return {'mode': 'bus', 'source': 'mta', 'updated_at': _imported_at(catalog), 'route': _route(route),
            'stops': _route_stops(catalog, route_id)}


def bus_stops(args):
    route_ids = args.getlist('route_id')
    if len(route_ids) != 1 or not route_ids[0].strip():
        raise BadRequest('route_id is required once.')
    query = _search(args)
    catalog = _bus()
    route_id = route_ids[0]
    _bus_route(catalog, route_id)
    return {'mode': 'bus', 'source': 'mta', 'route_id': route_id, 'stops': [
        s for s in _route_stops(catalog, route_id) if query in f"{s['name']} {s['id']}".casefold()]}


def bus_stop_detail(stop_id):
    catalog = _bus()
    stop = next((s for s in catalog['stops'] if s['id'] == stop_id), None)
    if stop is None:
        raise NotFound('Bus stop not found.')
    return {'mode': 'bus', 'source': 'mta', 'updated_at': _imported_at(catalog), 'stop': _stop(stop),
            'route_ids': list(stop['route_ids'])}
