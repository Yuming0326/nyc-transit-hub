"""Shared canonical saved-item identities and catalog validation (B7/B8/B11)."""
import hashlib
import json
import re

from flask import current_app
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from .transit_service import station_by_id


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def target_id(target):
    return digest([target['mode'], target['type'], target['id']])


def private_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise BadRequest('Invalid record ID.')
    return value


def parse_target(value):
    if not isinstance(value, dict) or set(value) != {'type', 'mode', 'id'}:
        raise BadRequest('target must contain exactly type, mode and id.')
    if (value.get('mode'), value.get('type')) not in (
            ('subway', 'station'), ('subway', 'route'), ('bus', 'stop'), ('bus', 'route')):
        raise BadRequest('Invalid target mode/type combination.')
    ident = value['id']
    if not isinstance(ident, str) or not ident or ident != ident.strip() or len(ident) > 200 or '/' in ident:
        raise BadRequest('Invalid target id.')
    if value['mode'] == 'bus' and value['type'] == 'stop' and not re.fullmatch(r'MTA_\d+', ident):
        raise BadRequest('Bus stop id must be MTA_<digits>.')
    if value['mode'] == 'bus' and value['type'] == 'route' and '_' not in ident:
        raise BadRequest('Bus route id must include its agency namespace.')
    return dict(value)


def validate_target(target):
    if target['type'] == 'station':
        station_by_id(target['id'])
        return
    if target['mode'] == 'subway':
        client = current_app.extensions['transit']['client']
        if client is None:
            # Demo station membership supplies actual supported demo routes.
            routes = {r for s in current_app.extensions['transit']['stations'] for r in s['routes']}
        else:
            routes = {r['id'] for r in client.catalog['routes']}
        if target['id'] not in routes:
            raise NotFound('Subway route not found.')
        return
    client = current_app.extensions['bus']['client']
    if client is None:
        raise ServiceUnavailable('Bus saved items require the live catalog.')
    rows = client.routes if target['type'] == 'route' else client.stops
    if target['id'] not in rows:
        raise NotFound('Bus target not found.')
