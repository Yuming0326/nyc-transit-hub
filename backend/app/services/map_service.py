"""Serve imported static subway (Y3) and bus (Y4) shapes; never synthesize map geometry."""
import json
import math
from threading import Lock

from flask import current_app
from werkzeug.exceptions import NotFound, ServiceUnavailable

from .transit_service import DATA_DIR

GEOMETRY_PATH = DATA_DIR / 'generated' / 'geometry.json'
BUS_GEOMETRY_PATH = DATA_DIR / 'generated' / 'bus' / 'geometry.json'
UNAVAILABLE = 'Subway map geometry is unavailable. Please retry.'
BUS_UNAVAILABLE = 'Bus map geometry is unavailable. Please retry.'


def init_map(app):
    # Geometry is loaded once on the first map request, not for arrivals requests.
    app.extensions['subway_map'] = {'data': None, 'lock': Lock()}
    app.extensions['bus_map'] = {'data': None, 'lock': Lock()}


def _map_data(catalog, mode='subway'):
    state = current_app.extensions[f'{mode}_map']
    path, unavailable = (GEOMETRY_PATH, UNAVAILABLE) if mode == 'subway' else (BUS_GEOMETRY_PATH, BUS_UNAVAILABLE)
    with state['lock']:
        if state['data'] is None:
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(payload, dict) or not isinstance(payload.get('metadata'), dict)
                        or payload.get('metadata') != catalog.get('metadata')
                        or not payload['metadata'].get('imported_at')
                        or payload.get('type') != 'FeatureCollection' or not payload.get('features')):
                    raise ValueError('Missing geometry or mismatched provenance')
                indexed = []
                routes = {route['id'] for route in catalog['routes']}
                for feature in payload['features']:
                    properties = feature['properties']
                    coordinates = feature['geometry']['coordinates']
                    if (feature['type'] != 'Feature' or feature['geometry']['type'] != 'LineString'
                            or properties['mode'] != mode or properties['route_id'] not in routes
                            or properties['direction_id'] not in ('0', '1', None)
                            or not properties['id'] or len(coordinates) < 2):
                        raise ValueError('Invalid geometry feature')
                    for longitude, latitude in coordinates:
                        if not (math.isfinite(longitude) and math.isfinite(latitude)
                                and -180 <= longitude <= 180 and -90 <= latitude <= 90):
                            raise ValueError('Invalid geometry coordinate')
                    bounds = (min(p[0] for p in coordinates), min(p[1] for p in coordinates),
                              max(p[0] for p in coordinates), max(p[1] for p in coordinates))
                    indexed.append((feature, bounds))
                state['data'] = (indexed, payload['metadata']['imported_at'])
            except (OSError, ValueError, KeyError, TypeError) as error:
                current_app.logger.warning('%s map artifact unavailable (%s)', mode.title(), type(error).__name__)
                raise ServiceUnavailable(unavailable) from error
        return state['data']


def _point_inside(point, bbox):
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def _segment_intersects(start, end, bbox):
    # Intersect the segment's parameter interval with each rectangle axis slab.
    low, high = 0.0, 1.0
    for axis in (0, 1):
        delta = end[axis] - start[axis]
        if delta == 0:
            if not bbox[axis] <= start[axis] <= bbox[axis + 2]:
                return False
            continue
        entry, exit = sorted(((bbox[axis] - start[axis]) / delta,
                              (bbox[axis + 2] - start[axis]) / delta))
        low, high = max(low, entry), min(high, exit)
        if low > high:
            return False
    return True


def _intersects(feature, bounds, bbox):
    if bounds[2] < bbox[0] or bounds[0] > bbox[2] or bounds[3] < bbox[1] or bounds[1] > bbox[3]:
        return False
    coordinates = feature['geometry']['coordinates']
    return any(_segment_intersects(a, b, bbox) for a, b in zip(coordinates, coordinates[1:]))


def subway_map(route_id=None, bbox=None):
    if current_app.config['TRANSIT_MODE'] != 'live':
        raise ServiceUnavailable('Map geometry is unavailable in demo mode.')
    catalog = current_app.extensions['transit']['client'].catalog
    routes = {route['id'] for route in catalog.get('routes', [])}
    if not routes:
        raise ServiceUnavailable(UNAVAILABLE)
    if route_id is not None and route_id not in routes:
        raise NotFound('Subway route not found.')
    indexed, updated_at = _map_data(catalog)
    coverage = {feature['properties']['route_id'] for feature, _ in indexed}
    required = {route_id} if route_id is not None else routes
    if not required or not required.issubset(coverage):
        raise ServiceUnavailable(UNAVAILABLE)
    features = [feature for feature, bounds in indexed
                if (route_id is None or feature['properties']['route_id'] == route_id)
                and (bbox is None or _intersects(feature, bounds, bbox))]
    stations = [station for station in catalog['stations']
                if (route_id is None or route_id in station['routes'])
                and (bbox is None or _point_inside((station['longitude'], station['latitude']), bbox))]
    return {'mode': 'subway', 'source': 'mta', 'updated_at': updated_at,
            'geometry': {'type': 'FeatureCollection', 'features': features},
            'stations': stations, 'stops': []}


def bus_map(route_id=None, bbox=None):
    """Y13: bus route geometry and stops from the Y4 import, same rules as subway_map."""
    if current_app.config['TRANSIT_MODE'] != 'live':
        raise ServiceUnavailable('Map geometry is unavailable in demo mode.')
    catalog = current_app.extensions['bus']['client'].catalog
    routes = {route['id'] for route in catalog.get('routes', [])}
    if not routes:
        raise ServiceUnavailable(BUS_UNAVAILABLE)
    if route_id is not None and route_id not in routes:
        raise NotFound('Bus route not found.')
    indexed, updated_at = _map_data(catalog, 'bus')
    coverage = {feature['properties']['route_id'] for feature, _ in indexed}
    required = {route_id} if route_id is not None else routes
    if not required.issubset(coverage):
        raise ServiceUnavailable(BUS_UNAVAILABLE)
    features = [feature for feature, bounds in indexed
                if (route_id is None or feature['properties']['route_id'] == route_id)
                and (bbox is None or _intersects(feature, bounds, bbox))]
    member = set(catalog['route_stop_ids'][route_id]) if route_id is not None else None
    stops = [{key: stop[key] for key in ('id', 'name', 'latitude', 'longitude')} for stop in catalog['stops']
             if (member is None or stop['id'] in member)
             and (bbox is None or _point_inside((stop['longitude'], stop['latitude']), bbox))]
    return {'mode': 'bus', 'source': 'mta', 'updated_at': updated_at,
            'geometry': {'type': 'FeatureCollection', 'features': features},
            'stations': [], 'stops': stops}

