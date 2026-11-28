"""Match source selectors without inventing route/stop cross-products (B13/B17)."""
from flask import current_app
from werkzeug.exceptions import ServiceUnavailable

from .mta_client import MTAError
from .saved_targets import digest

REVISION_FIELDS = ('header', 'description', 'route_ids', 'station_ids', 'stop_ids', 'scope', 'impact')


def revision(alert):
    content = {key: sorted(set(alert.get(key, []))) if key.endswith('_ids') else alert.get(key, '')
               for key in REVISION_FIELDS}
    return digest(content)


def fetch_alerts(mode):
    if current_app.config['TRANSIT_MODE'] == 'demo':
        return {'mode': mode, 'source': 'demo',
                'updated_at': '2026-11-24T15:00:00+00:00', 'alerts': []}
    try:
        if mode == 'subway':
            return current_app.extensions['transit']['client'].affected_alerts()
        return current_app.extensions['bus']['alerts'].alerts()
    except MTAError as error:
        current_app.logger.warning('%s alerts unavailable (%s)', mode, type(error).__name__)
        raise ServiceUnavailable('Live alerts are temporarily unavailable. Please retry.') from error


def matches(alert, target):
    """AND within a source selector; OR across selectors. Direction is not restricted by Target."""
    if target['mode'] == 'bus':
        client = current_app.extensions['bus']['client']
        if client is None:
            return False
        routes, stops = client.routes, client.stops
        for row in alert.get('targets', []):
            route, stop, agency = row.get('route_id'), row.get('stop_id'), row.get('agency_id')
            if row.get('direction_id') not in (None, '0', '1'):
                continue
            if route and (route not in routes or (agency and routes[route]['agency_id'] != agency)):
                continue
            if stop and (stop not in stops or (route and route not in stops[stop]['route_ids'])):
                continue
            if agency and stop and not any(routes.get(r, {}).get('agency_id') == agency
                                           for r in stops[stop]['route_ids']):
                continue
            if route is None and stop is None:
                # Only explicit agency-wide selectors; unknown scope is not global.
                if alert.get('scope') != 'network' or not agency:
                    continue
                if target['type'] == 'route' and routes.get(target['id'], {}).get('agency_id') == agency:
                    return True
                if target['type'] == 'stop' and any(routes.get(r, {}).get('agency_id') == agency
                                                       for r in stops.get(target['id'], {}).get('route_ids', [])):
                    return True
                continue
            if target['type'] == 'stop':
                if stop == target['id'] and (not route or route in stops.get(stop, {}).get('route_ids', [])):
                    return True
            elif (not route or route == target['id']) and (
                    not stop or target['id'] in stops.get(stop, {}).get('route_ids', [])):
                return True
        return False
    client = current_app.extensions['transit']['client']
    if client is None:
        return False
    catalog = client.catalog
    stations = {s['id']: s for s in catalog['stations']}
    for row in alert.get('selectors', []):
        if not row or set(row) - {'agency_id', 'route_id', 'stop_id', 'direction_id'}:
            continue
        if row.get('agency_id') not in (None, 'MTASBWY') or row.get('direction_id') not in (None, 0, 1):
            continue
        if row == {'agency_id': 'MTASBWY'}:
            return True
        route, stop = row.get('route_id'), row.get('stop_id')
        station = stop if stop in stations else catalog['stops'].get(stop, {}).get('station_id')
        if stop and (station not in stations or (route and route not in stations[station]['routes'])):
            continue
        if target['type'] == 'station':
            if stop and station == target['id']:
                return True
        elif (not route or route == target['id']) and (
                (stop and target['id'] in stations[station]['routes']) or (route and not stop)):
            return True
    return False
