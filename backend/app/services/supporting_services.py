"""B13–B16: conservative service status and official equipment snapshots."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import time
from zoneinfo import ZoneInfo

from flask import current_app
import requests
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from ..cache import TTLCache
from .alert_matching import fetch_alerts, matches
from .transit_service import station_by_id

EQUIPMENT_BASE = 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F'


def _single(args, key, required=False):
    values = args.getlist(key)
    if len(values) > 1 or (required and not values) or (values and not values[0].strip()):
        raise BadRequest(f'{key} must be supplied once and must not be empty.')
    return values[0] if values else None


def service_status(args):
    mode = _single(args, 'mode', required=True)
    if mode not in ('subway', 'bus'):
        raise BadRequest('mode must be subway or bus.')
    route_id = _single(args, 'route_id')
    if mode == 'subway':
        client = current_app.extensions['transit']['client']
        routes = sorted(r['id'] for r in client.catalog['routes']) if client else sorted({
            r for station in current_app.extensions['transit']['stations'] for r in station['routes']})
    else:
        client = current_app.extensions['bus']['client']
        if client is None:
            raise ServiceUnavailable('Bus service status requires the live catalog.')
        routes = sorted(client.routes)
    if route_id is not None:
        if route_id not in routes:
            raise NotFound('Route not found.')
        routes = [route_id]
    result = fetch_alerts(mode)
    statuses = []
    for route in routes:
        target = {'mode': mode, 'type': 'route', 'id': route}
        affected = [a for a in result['alerts'] if matches(a, target)]
        disruption = any(a['impact'] == 'disruption' for a in affected)
        statuses.append({'route_id': route, 'status': 'disruption' if disruption else 'unknown',
                         'basis': 'active_alerts' if disruption else 'insufficient_coverage',
                         'alert_ids': sorted({a['id'] for a in affected})})
    return {'mode': mode, 'source': result['source'], 'updated_at': result['updated_at'], 'statuses': statuses}


class EquipmentClient:
    def __init__(self, *, timeout, ttl=30, max_age=600):
        if max_age <= 0:
            raise ValueError('Equipment freshness limit must be positive')
        self.timeout, self.ttl, self.max_age = timeout, ttl, max_age
        self.cache = TTLCache()

    def _snapshot(self, name):
        def load():
            response = requests.get(EQUIPMENT_BASE + name, timeout=self.timeout)
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError('Invalid equipment snapshot')
            field = 'equipmentno' if name == 'nyct_ene_equipments.json' else 'equipment'
            if (field == 'equipmentno' and not rows) or any(
                    not isinstance(row.get(field), str) or not row[field] for row in rows):
                raise ValueError('Incomplete equipment snapshot')
            # This API has no publication timestamp in its payload. Preserve the
            # official response Date, not the local clock; document this limitation.
            stamp = parsedate_to_datetime(response.headers['Date'])
            if stamp.tzinfo is None:
                raise ValueError('Missing equipment response timezone')
            stamp = stamp.astimezone(timezone.utc)
            if not -60 <= time.time() - stamp.timestamp() <= self.max_age:
                raise ValueError('Stale equipment response')
            return rows, stamp
        rows, stamp = self.cache.get_or_load(name, self.ttl, load)
        if not -60 <= time.time() - stamp.timestamp() <= self.max_age:
            self.cache.evict(name)
            raise ValueError('Stale equipment response')
        return rows, stamp

    def for_station(self, station_id, catalog):
        try:
            inventory, inventory_time = self._snapshot('nyct_ene_equipments.json')
            outages, outage_time = self._snapshot('nyct_ene.json')
        except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError) as error:
            current_app.logger.warning('Equipment retrieval unavailable (%s)', type(error).__name__)
            raise ServiceUnavailable('MTA equipment data is temporarily unavailable. Please retry.') from error
        stamp = min(inventory_time, outage_time).isoformat()
        known = {s['id'] for s in catalog['stations']}
        active = {}
        for row in outages:
            start = _local_date(row.get('outagedate'))
            if row.get('isupcomingoutage') != 'N' or start is None or start.timestamp() > time.time():
                continue
            active[row['equipment']] = row
        equipment = {}
        for row in inventory:
            if row.get('isactive') != 'Y' or row.get('equipmenttype') not in ('EL', 'ES'):
                continue
            associations = set()
            for token in re.split(r'[,;/\s]+', str(row.get('elevatorsgtfsstopid', ''))):
                parent = token if token in known else catalog['stops'].get(token, {}).get('station_id')
                if parent in known:
                    associations.add(parent)
            if station_id not in associations:
                continue
            ident = row['equipmentno']
            outage = active.get(ident)
            returned = _local_date(outage.get('estimatedreturntoservice')) if outage else None
            equipment[ident] = {'id': ident, 'type': 'elevator' if row['equipmenttype'] == 'EL' else 'escalator',
                'description': row.get('serving') or row.get('shortdescription') or '',
                'station_ids': sorted(associations), 'status': 'reported_outage' if outage else 'unknown',
                'updated_at': stamp, 'return_to_service_at': returned.isoformat() if returned else None}
        return {'station_id': station_id, 'source': 'mta', 'updated_at': stamp,
                'coverage': 'partial' if equipment else 'unknown',
                'equipment': sorted(equipment.values(), key=lambda r: r['id'])}


def _local_date(value):
    if not value:
        return None
    try:
        local = datetime.strptime(value, '%m/%d/%Y %I:%M:%S %p')
        zone = ZoneInfo('America/New_York')
        # Reject ambiguous/nonexistent local times rather than inventing UTC.
        first, second = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            return None
        return first.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def station_equipment(station_id):
    station_by_id(station_id)
    transit = current_app.extensions['transit']['client']
    if transit is None:
        raise ServiceUnavailable('Equipment data requires live mode.')
    if 'equipment' not in current_app.extensions:
        current_app.extensions['equipment'] = EquipmentClient(
            timeout=(current_app.config['MTA_CONNECT_TIMEOUT_SECONDS'], current_app.config['MTA_READ_TIMEOUT_SECONDS']),
            ttl=current_app.config['CACHE_TTL_SECONDS'], max_age=current_app.config['EQUIPMENT_MAX_AGE_SECONDS'])
    return current_app.extensions['equipment'].for_station(station_id, transit.catalog)
