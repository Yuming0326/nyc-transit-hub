import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import current_app
from werkzeug.exceptions import NotFound, ServiceUnavailable
from ..cache import TTLCache

STATIONS = json.loads((Path(__file__).parents[1] / 'data' / 'stations.json').read_text())
cache = TTLCache()

def station_by_id(station_id):
    station = next((s for s in STATIONS if s['id'] == station_id), None)
    if station is None:
        raise NotFound('Station not found')
    return station

def arrivals_for(station_id):
    station = station_by_id(station_id)
    if current_app.config['TRANSIT_MODE'] != 'demo':
        raise ServiceUnavailable('Live MTA integration is not implemented. Set TRANSIT_MODE=demo.')
    def load():
        now = datetime.now(timezone.utc)
        return {'station_id': station_id, 'source': 'demo', 'updated_at': now.isoformat(), 'arrivals': [
            {'id': f'{station_id}-{index}', 'route_id': station['routes'][index % len(station['routes'])],
             'destination': 'Uptown (sample)' if index % 2 == 0 else 'Downtown (sample)',
             'direction': 'Uptown' if index % 2 == 0 else 'Downtown',
             'arrival_time': (now + timedelta(minutes=minutes)).isoformat()}
            for index, minutes in enumerate([2, 5, 8, 12])]}
    return cache.get_or_load(('demo', station_id), current_app.config['CACHE_TTL_SECONDS'], load)

def service_alerts(route_id=None):
    if current_app.config['TRANSIT_MODE'] != 'demo':
        raise ServiceUnavailable('Live MTA integration is not implemented. Set TRANSIT_MODE=demo.')
    alerts = [{'id': 'demo-1', 'header': 'Sample planned service change',
               'description': 'Fictional alert for interface development. Check official MTA information before traveling.',
               'route_ids': ['N', 'Q', 'R', 'W']}]
    return {'source': 'demo', 'alerts': [a for a in alerts if not route_id or route_id in a['route_ids']]}
