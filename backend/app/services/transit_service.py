import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import current_app
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable
from ..cache import TTLCache
from .feed_cache import CachedFeedSession
from .mta_client import FEED_ROUTES, MTAClient, MTAError

DATA_DIR = Path(__file__).parents[1] / 'data'


def init_transit(app):
    mode = app.config['TRANSIT_MODE']
    if mode not in ('demo', 'live'):
        raise ValueError('TRANSIT_MODE must be demo or live')
    numeric = ('MTA_CONNECT_TIMEOUT_SECONDS', 'MTA_READ_TIMEOUT_SECONDS',
               'MTA_MAX_AGE_SECONDS', 'MTA_ALERTS_MAX_AGE_SECONDS')
    if any(app.config[key] <= 0 for key in numeric) or app.config['CACHE_TTL_SECONDS'] < 0:
        raise ValueError('MTA timeouts and freshness limits must be positive; cache TTL must be nonnegative')
    state = {'cache': TTLCache(), 'client': None}
    if mode == 'live':
        catalog = json.loads((DATA_DIR / 'generated' / 'catalog.json').read_text(encoding='utf-8'))
        state['stations'] = catalog['stations']
        state['client'] = MTAClient(
            catalog,
            timeout=(app.config['MTA_CONNECT_TIMEOUT_SECONDS'], app.config['MTA_READ_TIMEOUT_SECONDS']),
            max_age=app.config['MTA_MAX_AGE_SECONDS'],
            alerts_max_age=app.config['MTA_ALERTS_MAX_AGE_SECONDS'],
            session=CachedFeedSession(app.config['CACHE_TTL_SECONDS'],
                                      app.config['MTA_MAX_AGE_SECONDS'],
                                      app.config['MTA_ALERTS_MAX_AGE_SECONDS']))
    else:
        state['stations'] = json.loads((DATA_DIR / 'stations.json').read_text(encoding='utf-8'))
    state['by_id'] = {s['id']: s for s in state['stations']}
    app.extensions['transit'] = state


def list_stations():
    return current_app.extensions['transit']['stations']


def live_call(method, *args):
    try:
        return getattr(current_app.extensions['transit']['client'], method)(*args)
    except MTAError as error:
        current_app.logger.warning('MTA %s failed: %s', method, error)
        raise ServiceUnavailable('Live MTA data is temporarily unavailable. Please retry.') from error

def station_by_id(station_id):
    station = current_app.extensions['transit']['by_id'].get(station_id)
    if station is None:
        raise NotFound('Station not found')
    return station

def arrivals_for(station_id):
    station = station_by_id(station_id)
    if current_app.config['TRANSIT_MODE'] == 'live':
        return live_call('arrivals', station_id)
    def load():
        now = datetime.now(timezone.utc)
        return {'station_id': station_id, 'source': 'demo', 'updated_at': now.isoformat(), 'arrivals': [
            {'id': f'{station_id}-{index}', 'route_id': station['routes'][index % len(station['routes'])],
             'destination': 'Uptown (sample)' if index % 2 == 0 else 'Downtown (sample)',
             'direction': 'Uptown' if index % 2 == 0 else 'Downtown',
             'arrival_time': (now + timedelta(minutes=minutes)).isoformat()}
            for index, minutes in enumerate([2, 5, 8, 12])]}
    return current_app.extensions['transit']['cache'].get_or_load(
        ('demo', station_id), current_app.config['CACHE_TTL_SECONDS'], load)

def service_alerts(route_id=None):
    if route_id is not None:
        route_id = route_id.strip().upper()
        if route_id not in {r for routes in FEED_ROUTES.values() for r in routes}:
            raise BadRequest('Unknown or empty route_id')
    if current_app.config['TRANSIT_MODE'] == 'live':
        return live_call('alerts', route_id)
    alerts = [{'id': 'demo-1', 'header': 'Sample planned service change',
               'description': 'Fictional alert for interface development. Check official MTA information before traveling.',
               'route_ids': ['N', 'Q', 'R', 'W']}]
    return {'source': 'demo', 'alerts': [a for a in alerts if not route_id or route_id in a['route_ids']]}
