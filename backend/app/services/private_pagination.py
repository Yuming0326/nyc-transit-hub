"""Signed cursors scoped to user, resource and filters; no Firestore indexes needed."""
import base64
import hashlib
import hmac
import json
import os

from flask import current_app, g
from werkzeug.exceptions import BadRequest


def _one(args, key, default=None):
    values = args.getlist(key)
    if len(values) > 1:
        raise BadRequest(f'{key} must be supplied once.')
    return values[0] if values else default


def _secret():
    supplied = current_app.config.get('PAGINATION_SIGNING_KEY')
    if supplied:
        return supplied.encode('utf-8')
    return current_app.extensions.setdefault('cursor_secret', os.urandom(32))


def _encode(payload):
    data = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    signature = hmac.new(_secret(), data, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + data).decode('ascii').rstrip('=')


def paginate(rows, args, resource, *, filters=None, notifications=False):
    raw_limit = _one(args, 'limit', '50')
    if not raw_limit.isascii() or not raw_limit.isdigit() or not 1 <= int(raw_limit) <= 100:
        raise BadRequest('limit must be an integer from 1 to 100.')
    limit = int(raw_limit)
    context = [g.user_id, resource, filters or {}]
    cursor = _one(args, 'cursor')
    rows = sorted(rows, key=lambda row: row['id'])
    if notifications:
        rows.sort(key=lambda row: row['created_at'], reverse=True)
    if cursor is not None:
        try:
            if len(cursor) > 4096:
                raise ValueError()
            raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
            signature, data = raw[:32], raw[32:]
            if not hmac.compare_digest(signature, hmac.new(_secret(), data, hashlib.sha256).digest()):
                raise ValueError()
            payload = json.loads(data)
            if payload['context'] != context:
                raise ValueError()
            position = payload['position']
            if notifications:
                stamp, ident = position
                if not isinstance(stamp, str) or not isinstance(ident, str):
                    raise ValueError()
                rows = [r for r in rows if r['created_at'] < stamp or
                        (r['created_at'] == stamp and r['id'] > ident)]
            else:
                if not isinstance(position, str):
                    raise ValueError()
                rows = [r for r in rows if r['id'] > position]
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            raise BadRequest('Invalid or mismatched cursor.') from error
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        position = [last['created_at'], last['id']] if notifications else last['id']
        next_cursor = _encode({'context': context, 'position': position})
    return page, next_cursor


def unread_filter(args):
    value = _one(args, 'unread_only', 'false')
    if value not in ('true', 'false'):
        raise BadRequest('unread_only must be true or false.')
    return value == 'true'
