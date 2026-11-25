"""Flask-facing Y10 bus realtime layer: stop arrivals and route vehicle positions.

Live mode uses the validated Y4 bus catalog plus Bus Time (bus_time.BusTimeClient).
Demo mode serves clearly labeled illustrative data for the fixture stop/route only.
"""
from datetime import datetime, timedelta, timezone

from flask import current_app
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from .bus_alerts import BusAlertsClient
from .bus_time import BusInputError, BusNotFound, BusTimeClient, BusUnavailable, load_catalog
from .transit_service import DATA_DIR

UNAVAILABLE = 'Live bus data is temporarily unavailable. Please retry.'
DEMO_STOP_ID = 'MTA_308214'
DEMO_ROUTE_ID = 'MTA NYCT_B63'


def init_bus(app):
    numeric = ('BUS_MAX_AGE_SECONDS', 'BUS_VEHICLE_MAX_AGE_SECONDS')
    if any(app.config[key] <= 0 for key in numeric):
        raise ValueError('Bus freshness limits must be positive')
    client = alerts = None
    if app.config['TRANSIT_MODE'] == 'live':
        catalog = app.config.get('BUS_CATALOG') or load_catalog(DATA_DIR / 'generated' / 'bus' / 'catalog.json')
        client = BusTimeClient(
            catalog, (app.config.get('MTA_BUS_TIME_API_KEY') or '').strip(),
            timeout=(app.config['MTA_CONNECT_TIMEOUT_SECONDS'], app.config['MTA_READ_TIMEOUT_SECONDS']),
            max_age=app.config['BUS_MAX_AGE_SECONDS'],
            vehicle_max_age=app.config['BUS_VEHICLE_MAX_AGE_SECONDS'],
            ttl=app.config['CACHE_TTL_SECONDS'])
        # Y11 internal catalog-aware bus alerts; /api/transit/alerts wiring is Y13.
        alerts = BusAlertsClient(
            catalog,
            timeout=(app.config['MTA_CONNECT_TIMEOUT_SECONDS'], app.config['MTA_READ_TIMEOUT_SECONDS']),
            max_age=app.config['MTA_ALERTS_MAX_AGE_SECONDS'], ttl=app.config['CACHE_TTL_SECONDS'])
    app.extensions['bus'] = {'client': client, 'alerts': alerts}


def _call(method, *args):
    try:
        return getattr(current_app.extensions['bus']['client'], method)(*args)
    except BusNotFound as error:
        raise NotFound(str(error)) from error
    except BusInputError as error:
        raise BadRequest(str(error)) from error
    except BusUnavailable as error:
        # Never log upstream URLs or exception text: request parameters hold the key.
        current_app.logger.warning('Bus Time %s unavailable: %s', method, error.reason)
        raise ServiceUnavailable(UNAVAILABLE) from error


def _single(args, key):
    values = args.getlist(key)
    if len(values) > 1:
        raise BadRequest(f'{key} must be supplied once.')
    return values[0] if values else None


def bus_arrivals(stop_id, args):
    route_id, direction_id = _single(args, 'route_id'), _single(args, 'direction_id')
    if current_app.config['TRANSIT_MODE'] == 'live':
        return _call('arrivals', stop_id, route_id, direction_id)
    return _demo_arrivals(stop_id, route_id, direction_id)


def bus_vehicles(args):
    route_id, direction_id = _single(args, 'route_id'), _single(args, 'direction_id')
    if current_app.config['TRANSIT_MODE'] == 'live':
        return _call('vehicles', route_id, direction_id)
    return _demo_vehicles(route_id, direction_id)


def _demo_filters(route_id, direction_id, *, required=False):
    if direction_id is not None and direction_id not in ('0', '1'):
        raise BadRequest('direction_id must be 0 or 1.')
    if route_id is None:
        if required:
            raise BadRequest('route_id is required.')
    elif not route_id.strip() or '_' not in route_id:
        raise BadRequest('route_id must be a full bus route ID.')
    elif route_id != DEMO_ROUTE_ID:
        raise NotFound('Bus route not found.')


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _demo_arrivals(stop_id, route_id, direction_id):
    _demo_filters(route_id, direction_id)
    if not stop_id.startswith('MTA_') or not stop_id[4:].isdigit():
        raise BadRequest('stop_id must be an MTA-qualified numeric ID.')
    if stop_id != DEMO_STOP_ID:
        raise NotFound('Bus stop not found.')
    now = _now()
    rows = [{'id': f'demo-bus-visit-{n}', 'route_id': DEMO_ROUTE_ID, 'route_name': 'B63',
             'direction_id': direction, 'destination': 'Illustrative destination (sample)',
             'arrival_time': (now + timedelta(minutes=minutes)).isoformat() if minutes else None,
             'vehicle_id': f'demo-vehicle-{n}', 'recorded_at': (now - timedelta(seconds=5)).isoformat(),
             'distance_text': distance}
            for n, (direction, minutes, distance) in enumerate(
                [('1', 3, '2 stops away'), ('0', 7, '5 stops away'), ('1', None, '9 stops away')], 1)]
    return {'mode': 'bus', 'source': 'demo', 'stop_id': stop_id, 'updated_at': now.isoformat(),
            'arrivals': [r for r in rows if direction_id is None or r['direction_id'] == direction_id]}


def _demo_vehicles(route_id, direction_id):
    _demo_filters(route_id, direction_id, required=True)
    now = _now()
    rows = [{'id': 'demo-vehicle-1', 'route_id': DEMO_ROUTE_ID, 'direction_id': '1',
             'destination': 'Illustrative destination (sample)', 'latitude': 40.675,
             'longitude': -73.983, 'bearing': 45.0, 'recorded_at': (now - timedelta(seconds=5)).isoformat()},
            {'id': 'demo-vehicle-2', 'route_id': DEMO_ROUTE_ID, 'direction_id': '0', 'destination': None,
             'latitude': 40.668, 'longitude': -73.99, 'bearing': None,
             'recorded_at': (now - timedelta(seconds=12)).isoformat()}]
    return {'mode': 'bus', 'source': 'demo', 'updated_at': now.isoformat(),
            'vehicles': [r for r in rows if direction_id is None or r['direction_id'] == direction_id]}
