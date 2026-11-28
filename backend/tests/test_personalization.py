"""B5–B20 API/authorization/concurrency checks. Fake persistence is explicitly test-only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock
from unittest.mock import Mock

import pytest

from app import create_app
from app.services import firebase_service, personalization
from app.services.personal_store import COLLECTIONS
from app.services.saved_targets import target_id

STATION = {'type': 'station', 'mode': 'subway', 'id': 'R20'}
ROUTE = {'type': 'route', 'mode': 'subway', 'id': 'R'}
STOP = {'type': 'stop', 'mode': 'bus', 'id': 'MTA_308214'}
BUS = {'type': 'route', 'mode': 'bus', 'id': 'MTA NYCT_B63'}


class MemoryStore:
    def __init__(self):
        self.users, self.lock = {}, RLock()

    def run(self, uid, operation, *, write=False):
        with self.lock:
            state = deepcopy(self.users.get(uid, {name: {} for name in COLLECTIONS}))
            result = operation(state)
            if write:
                self.users[uid] = deepcopy(state)
            return deepcopy(result)


def feed(mode='subway', header='Disruption'):
    alert = {'id': 'notice-' + mode, 'header': header, 'description': 'Explicit test disruption',
             'scope': 'stop', 'impact': 'disruption',
             'route_ids': ['R'] if mode == 'subway' else ['MTA NYCT_B63'],
             'station_ids': ['R20'] if mode == 'subway' else [],
             'stop_ids': ['R20N'] if mode == 'subway' else ['MTA_308214']}
    if mode == 'subway':
        alert['selectors'] = [{'agency_id': 'MTASBWY', 'route_id': 'R', 'stop_id': 'R20N'}]
    else:
        alert['targets'] = [{'agency_id': 'MTA NYCT', 'route_id': 'MTA NYCT_B63',
                             'stop_id': 'MTA_308214', 'direction_id': None}]
    return {'mode': mode, 'source': 'mta', 'updated_at': '2026-11-28T00:00:00+00:00', 'alerts': [alert]}


@pytest.fixture
def setup(monkeypatch):
    from firebase_admin import auth
    monkeypatch.setattr(firebase_service, 'firebase_app', lambda: object())
    def verify(token, **kwargs):
        assert kwargs['check_revoked'] is True
        if token not in ('alice', 'bob'):
            raise ValueError('invalid token')
        return {'uid': token}
    monkeypatch.setattr(auth, 'verify_id_token', verify)
    store = MemoryStore()
    app = create_app({'TESTING': True, 'TRANSIT_MODE': 'live', 'PERSONAL_STORE': store,
                      'PAGINATION_SIGNING_KEY': 'test-only-secret'})
    return app, store


def call(app, method, path, body=None, user='alice'):
    with app.test_client() as client:
        headers = {'Authorization': 'Bearer ' + user} if user else {}
        return client.open(path, method=method, json=body, headers=headers)


def subscribe(app, target=STATION, enabled=True, user='alice'):
    return call(app, 'PUT', '/api/subscriptions/' + target_id(target),
                {'target': target, 'enabled': enabled}, user)


@pytest.mark.parametrize('method,path', [('GET','/api/v2/favorites'), ('POST','/api/v2/favorites'),
    ('DELETE','/api/v2/favorites/'+'a'*64), ('GET','/api/subscriptions'),
    ('PUT','/api/subscriptions/'+'a'*64), ('DELETE','/api/subscriptions/'+'a'*64),
    ('GET','/api/notifications'), ('POST','/api/notifications/evaluate'),
    ('PATCH','/api/notifications/'+'a'*64)])
@pytest.mark.parametrize('user', [None, 'invalid'])
def test_every_private_operation_requires_verified_token(setup, method, path, user):
    app, store = setup
    assert call(app, method, path, {}, user).status_code == 401
    assert store.users == {}


@pytest.mark.parametrize('target', [STATION, ROUTE, STOP, BUS])
def test_typed_favorites_upsert_and_user_isolation(setup, target):
    app, _ = setup
    for _ in range(2):
        r = call(app, 'POST', '/api/v2/favorites', {'target': target})
        assert r.status_code == 201 and r.json == {'id': target_id(target), 'target': target}
    assert len(call(app, 'GET', '/api/v2/favorites').json['favorites']) == 1
    assert call(app, 'GET', '/api/v2/favorites', user='bob').json['favorites'] == []
    # A different user's same opaque ID addresses only that user's namespace.
    assert call(app, 'DELETE', '/api/v2/favorites/' + target_id(target), user='bob').status_code == 200
    assert len(call(app, 'GET', '/api/v2/favorites').json['favorites']) == 1


def test_legacy_and_v2_station_writes_and_deletes_are_bidirectional(setup):
    app, store = setup
    assert call(app, 'POST', '/api/favorites', {'station_id': 'R20'}).status_code == 201
    assert call(app, 'GET', '/api/v2/favorites').json['favorites'] == [{'id': target_id(STATION), 'target': STATION}]
    assert call(app, 'DELETE', '/api/v2/favorites/' + target_id(STATION)).status_code == 200
    assert call(app, 'GET', '/api/favorites').json == {'favorites': []}
    call(app, 'POST', '/api/v2/favorites', {'target': STATION})
    assert call(app, 'GET', '/api/favorites').json == {'favorites': [{'station_id': 'R20'}]}
    call(app, 'DELETE', '/api/favorites/R20')
    assert call(app, 'GET', '/api/v2/favorites').json['favorites'] == []
    # Preserve/union existing legacy and typed data, including duplicate tuples.
    def seed(state):
        state['favorites']['R20'] = {'station_id': 'R20'}
        state['saved_items'][target_id(STATION)] = {'target': STATION}
    store.run('alice', seed, write=True)
    assert len(call(app, 'GET', '/api/v2/favorites').json['favorites']) == 1


def test_retired_favorites_remain_readable_and_removable(setup):
    app, store = setup
    retired = {**STATION, 'id': 'RETIRED'}
    store.run('alice', lambda state: state['favorites'].update({'RETIRED': {'station_id': 'RETIRED'}}), write=True)
    assert call(app, 'GET', '/api/v2/favorites').json['favorites'][0]['target'] == retired
    assert call(app, 'DELETE', '/api/v2/favorites/' + target_id(retired)).status_code == 200


@pytest.mark.parametrize('body,status', [({},400), ({'uid':'bob','target':STATION},400),
    ({'target':{'type':'stop','mode':'subway','id':'R20'}},400),
    ({'target':{**STOP,'id':'308214'}},400), ({'target':{**ROUTE,'id':'unknown'}},404),
    ({'target':{**STATION,'id':''}},400), ({'target':{**BUS,'id':'B63'}},400)])
def test_favorite_validation(setup, body, status):
    app, _ = setup
    assert call(app, 'POST', '/api/v2/favorites', body).status_code == status


def test_private_pagination_scopes_users_resources_and_filters(setup, monkeypatch):
    app, _ = setup
    for target in (STATION, ROUTE, STOP):
        call(app, 'POST', '/api/v2/favorites', {'target': target})
    first = call(app, 'GET', '/api/v2/favorites?limit=1').json
    cursor = first['next_cursor']
    second = call(app, 'GET', '/api/v2/favorites?limit=1&cursor=' + cursor).json
    assert first['favorites'][0]['id'] != second['favorites'][0]['id']
    assert call(app, 'GET', '/api/v2/favorites?cursor=' + cursor, user='bob').status_code == 400
    assert call(app, 'GET', '/api/subscriptions?cursor=' + cursor).status_code == 400
    for query in ('limit=0','limit=101','limit=-1','limit=abc','limit=1&limit=2','cursor=bad'):
        assert call(app, 'GET', '/api/v2/favorites?' + query).status_code == 400


def test_subscription_lifecycle_and_favorite_independence(setup):
    app, _ = setup
    first = subscribe(app).json
    assert subscribe(app).json == first
    assert subscribe(app, enabled=False).json['created_at'] == first['created_at']
    call(app, 'POST', '/api/v2/favorites', {'target': STATION})
    call(app, 'DELETE', '/api/v2/favorites/' + target_id(STATION))
    assert len(call(app, 'GET', '/api/subscriptions').json['subscriptions']) == 1
    for _ in range(2):
        assert call(app, 'DELETE', '/api/subscriptions/' + target_id(STATION)).status_code == 200


def test_subscription_validation_and_retired_disable(setup):
    app, store = setup
    assert call(app, 'PUT', '/api/subscriptions/'+'a'*64, {'target':STATION,'enabled':True}).status_code == 400
    assert subscribe(app, enabled='true').status_code == 400
    retired = {**STATION, 'id':'RETIRED'}
    value = {'id':target_id(retired),'target':retired,'enabled':True,'created_at':'old','updated_at':'old'}
    store.run('alice', lambda state: state['subscriptions'].update({value['id']:value}), write=True)
    assert subscribe(app, retired, False).status_code == 200
    assert subscribe(app, retired, True).status_code == 404


def test_notifications_deduplicate_preserve_read_and_create_material_revisions(setup, monkeypatch):
    app, _ = setup
    upstream = Mock(return_value=feed())
    monkeypatch.setattr(personalization, 'fetch_alerts', upstream)
    subscribe(app, STATION)
    subscribe(app, ROUTE)
    result = call(app, 'POST', '/api/notifications/evaluate', {}).json
    assert result['created'] == 1 and result['unread_count'] == 1
    first = call(app, 'GET', '/api/notifications').json['notifications'][0]
    assert len(first['targets']) == 2
    ident = first['id']
    assert call(app, 'PATCH', '/api/notifications/' + ident, {'read':True}, 'bob').status_code == 404
    read = call(app, 'PATCH', '/api/notifications/' + ident, {'read':True}).json
    assert read['read_at'] and read['read']
    assert call(app, 'PATCH', '/api/notifications/' + ident, {'read':True}).json['read_at'] == read['read_at']
    upstream.return_value['updated_at'] = '2026-11-28T01:00:00+00:00'
    assert call(app, 'POST', '/api/notifications/evaluate', {}).json['created'] == 0
    assert call(app, 'GET', '/api/notifications').json['unread_count'] == 0
    assert call(app, 'PATCH', '/api/notifications/' + ident, {'read':False}).json['read_at'] is None
    upstream.return_value = feed(header='Material change')
    assert call(app, 'POST', '/api/notifications/evaluate', {}).json['created'] == 1
    assert call(app, 'GET', '/api/notifications').json['unread_count'] == 2


def test_no_subscriptions_no_upstream_and_unsubscribe_stops_new_notifications(setup, monkeypatch):
    app, _ = setup
    upstream = Mock(return_value=feed())
    monkeypatch.setattr(personalization, 'fetch_alerts', upstream)
    assert call(app, 'POST', '/api/notifications/evaluate', {}).json['created'] == 0
    upstream.assert_not_called()
    subscribe(app)
    call(app, 'POST', '/api/notifications/evaluate', {})
    subscribe(app, enabled=False)
    upstream.reset_mock()
    assert call(app, 'POST', '/api/notifications/evaluate', {}).json['created'] == 0
    upstream.assert_not_called()
    assert len(call(app, 'GET', '/api/notifications').json['notifications']) == 1


def test_upstream_failure_rolls_back_entire_evaluation(setup, monkeypatch):
    from werkzeug.exceptions import ServiceUnavailable
    app, store = setup
    subscribe(app, STATION)
    subscribe(app, STOP)
    before = deepcopy(store.users)
    def fetch(mode):
        if mode == 'subway':
            raise ServiceUnavailable('upstream test outage')
        return feed(mode)
    monkeypatch.setattr(personalization, 'fetch_alerts', fetch)
    assert call(app, 'POST', '/api/notifications/evaluate', {}).status_code == 503
    assert store.users == before


def test_concurrent_evaluations_and_upserts_create_one_record(setup, monkeypatch):
    app, _ = setup
    monkeypatch.setattr(personalization, 'fetch_alerts', lambda mode: feed(mode))
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert all(r.status_code == 201 for r in workers.map(
            lambda _: call(app, 'POST', '/api/v2/favorites', {'target':STATION}), range(8)))
    subscribe(app)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: call(app,'POST','/api/notifications/evaluate',{}),range(8)))
    assert sum(r.json['created'] for r in results) == 1
    assert len(call(app, 'GET', '/api/v2/favorites').json['favorites']) == 1


def test_notification_unread_count_is_independent_of_page(setup, monkeypatch):
    app, _ = setup
    subscribe(app)
    for title in ('first','second','third'):
        monkeypatch.setattr(personalization, 'fetch_alerts', lambda mode, text=title: feed(header=text))
        call(app,'POST','/api/notifications/evaluate',{})
    page = call(app,'GET','/api/notifications?unread_only=true&limit=1').json
    assert page['unread_count'] == 3 and len(page['notifications']) == 1
    cursor = page['next_cursor']
    assert call(app,'GET','/api/notifications?unread_only=false&cursor='+cursor).status_code == 400
    assert call(app,'GET','/api/notifications?unread_only=1').status_code == 400


def test_new_matching_subscription_merges_targets_without_resetting_read(setup, monkeypatch):
    app, _ = setup
    monkeypatch.setattr(personalization,'fetch_alerts',lambda mode:feed(mode))
    subscribe(app, STATION)
    call(app,'POST','/api/notifications/evaluate',{})
    item = call(app,'GET','/api/notifications').json['notifications'][0]
    read = call(app,'PATCH','/api/notifications/'+item['id'],{'read':True}).json
    subscribe(app, ROUTE)
    assert call(app,'POST','/api/notifications/evaluate',{}).json['created'] == 0
    updated = call(app,'GET','/api/notifications').json['notifications'][0]
    assert len(updated['targets']) == 2 and updated['read_at'] == read['read_at']


def test_certificate_outage_is_503_not_invalid_user(setup, monkeypatch):
    from firebase_admin import auth
    app, _ = setup
    def fail(*args, **kwargs):
        raise auth.CertificateFetchError('test certificate outage', cause=RuntimeError('test'))
    monkeypatch.setattr(auth,'verify_id_token',fail)
    assert call(app,'GET','/api/v2/favorites').status_code == 503


def test_selectors_never_cross_product_or_broaden_stop_subscriptions(setup):
    app, _ = setup
    from app.services.alert_matching import matches, revision
    with app.app_context():
        alert = feed()['alerts'][0]
        alert['selectors'] = [{'route_id':'R'}, {'route_id':'A','stop_id':'A32N'}]
        assert matches(alert, ROUTE)
        assert not matches(alert, STATION)
        alert['selectors'] = [{'route_id':'A','stop_id':'R20N'}]
        assert not matches(alert, STATION)
        alert['selectors'] = [{'agency_id':'MTASBWY'}]
        assert matches(alert, STATION)
        alert['selectors'] = [{'agency_id':'other'}]
        assert not matches(alert, STATION)
        changed = deepcopy(alert)
        changed['route_ids'] = ['R','R']
        assert revision(alert) == revision(changed)
