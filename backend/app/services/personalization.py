"""B8–B20: persistent favorites, subscriptions and atomic notification evaluation."""
from datetime import datetime, timezone

from flask import request
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from .alert_matching import fetch_alerts, matches, revision
from .personal_store import run_user
from .private_pagination import paginate, unread_filter
from .saved_targets import digest, parse_target, private_id, target_id, validate_target


def now():
    return datetime.now(timezone.utc).isoformat()


def body_fields(required):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != set(required):
        raise BadRequest('JSON body must contain exactly: ' + ', '.join(required))
    return body


def favorite_rows(state):
    rows = {}
    for station in state['favorites']:
        target = {'type': 'station', 'mode': 'subway', 'id': station}
        rows[target_id(target)] = {'id': target_id(target), 'target': target}
    for value in state['saved_items'].values():
        target = parse_target(value['target'])
        rows[target_id(target)] = {'id': target_id(target), 'target': target}
    return list(rows.values())


def list_favorites():
    def read(state):
        rows, cursor = paginate(favorite_rows(state), request.args, 'favorites')
        return {'favorites': rows, 'next_cursor': cursor}
    return run_user(read)


def add_favorite():
    target = parse_target(body_fields(('target',))['target'])
    validate_target(target)
    ident = target_id(target)
    def save(state):
        if target['type'] == 'station':
            state['favorites'][target['id']] = {'station_id': target['id']}
            state['saved_items'].pop(ident, None)
        else:
            state['saved_items'][ident] = {'target': target}
        return {'id': ident, 'target': target}
    return run_user(save, write=True)


def delete_favorite(ident):
    private_id(ident)
    def remove(state):
        for item in favorite_rows(state):
            if item['id'] == ident and item['target']['type'] == 'station':
                state['favorites'].pop(item['target']['id'], None)
        state['saved_items'].pop(ident, None)
        return {'deleted': True}
    return run_user(remove, write=True)


def list_subscriptions():
    def read(state):
        rows, cursor = paginate(list(state['subscriptions'].values()), request.args, 'subscriptions')
        return {'subscriptions': rows, 'next_cursor': cursor}
    return run_user(read)


def put_subscription(ident):
    private_id(ident)
    body = body_fields(('target', 'enabled'))
    target = parse_target(body['target'])
    if not isinstance(body['enabled'], bool) or target_id(target) != ident:
        raise BadRequest('enabled must be boolean and the subscription ID must match target.')
    def save(state):
        old = state['subscriptions'].get(ident)
        if body['enabled'] or old is None:
            validate_target(target)
        stamp = now()
        if old and old['enabled'] == body['enabled']:
            return old
        value = {'id': ident, 'target': target, 'enabled': body['enabled'],
                 'created_at': old['created_at'] if old else stamp, 'updated_at': stamp}
        state['subscriptions'][ident] = value
        return value
    return run_user(save, write=True)


def delete_subscription(ident):
    private_id(ident)
    def remove(state):
        state['subscriptions'].pop(ident, None)
        return {'deleted': True}
    return run_user(remove, write=True)


def _unread(state):
    return sum(not row['read'] for row in state['notifications'].values())


def list_notifications():
    unread_only = unread_filter(request.args)
    def read(state):
        rows = [row for row in state['notifications'].values() if not unread_only or not row['read']]
        page, cursor = paginate(rows, request.args, 'notifications',
                                filters={'unread_only': unread_only}, notifications=True)
        return {'notifications': page, 'unread_count': _unread(state), 'next_cursor': cursor}
    return run_user(read)


def mark_notification(ident):
    private_id(ident)
    read = body_fields(('read',))['read']
    if not isinstance(read, bool):
        raise BadRequest('read must be boolean.')
    def update(state):
        row = state['notifications'].get(ident)
        if row is None:
            raise NotFound('Notification not found.')
        if row['read'] != read:
            row['read'] = read
            row['read_at'] = now() if read else None
        return dict(row)
    return run_user(update, write=True)


def evaluate_notifications():
    body_fields(())
    subscriptions = run_user(lambda state: list(state['subscriptions'].values()))
    modes = {s['target']['mode'] for s in subscriptions if s['enabled']}
    # All required upstream calls finish before any persistent changes.
    feeds = {mode: fetch_alerts(mode) for mode in sorted(modes)}
    def evaluate(state):
        active = [s for s in state['subscriptions'].values() if s['enabled']]
        if any(s['target']['mode'] not in feeds for s in active):
            raise ServiceUnavailable('Subscriptions changed during evaluation. Please retry.')
        stamp, candidates = now(), {}
        for subscription in active:
            target = subscription['target']
            for alert in feeds[target['mode']]['alerts']:
                if alert.get('impact') != 'disruption' or not matches(alert, target):
                    continue
                rev = revision(alert)
                ident = digest([alert['id'], rev])
                row = candidates.setdefault(ident, {'id': ident, 'alert_id': alert['id'], 'revision': rev,
                    'title': alert['header'], 'body': alert['description'], 'targets': [],
                    'created_at': stamp, 'read': False, 'read_at': None})
                if target not in row['targets']:
                    row['targets'].append(target)
        created = 0
        for ident, row in candidates.items():
            if ident not in state['notifications']:
                row['targets'].sort(key=target_id)
                state['notifications'][ident] = row
                created += 1
            else:
                existing = state['notifications'][ident]
                combined = {target_id(t): t for t in existing['targets'] + row['targets']}
                existing['targets'] = [combined[key] for key in sorted(combined)]
            # Adding a new matching subscription never resets read/created_at.
        return {'created': created, 'unread_count': _unread(state), 'evaluated_at': stamp}
    return run_user(evaluate, write=True)
