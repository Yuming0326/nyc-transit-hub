"""Opt-in real Firebase check using two temporary users; always attempts cleanup.

Run from backend: python scripts/verify_personalization.py --allow-test-writes --output report.json
No keys/tokens are logged. Notification delivery uses an explicitly synthetic disruption.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.services.firebase_service import firebase_app
from app.services.saved_targets import target_id
from app.services.personal_store import COLLECTIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-test-writes', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--frontend-env', type=Path, help='Optional ignored frontend .env output (public web config only)')
    args = parser.parse_args()
    if not args.allow_test_writes:
        parser.error('--allow-test-writes is required for temporary Firebase Auth/Firestore records')
    from firebase_admin import auth, firestore
    from google.auth.transport.requests import AuthorizedSession
    import requests
    app = create_app({'TRANSIT_MODE': 'live'})
    client = app.test_client()
    users, report = [], {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': [], 'cleanup': False,
        'notification_source': 'Explicitly synthetic disruption; real Firebase persistence and real signed ID tokens'}
    def record(name, condition):
        report['checks'].append({'name': name, 'passed': bool(condition)})
        print(name + ': ' + ('PASS' if condition else 'FAIL'), flush=True)
        if not condition:
            raise RuntimeError('Verification check failed: ' + name)
    try:
        with app.app_context():
            firebase = firebase_app()
            db = firestore.client(app=firebase)
            project = app.config['FIREBASE_PROJECT_ID']
            session = AuthorizedSession(firebase.credential.get_credential())
            response = session.get(f'https://firebase.googleapis.com/v1beta1/projects/{project}/webApps', timeout=20)
            response.raise_for_status()
            apps = response.json().get('apps', [])
            if not apps:
                raise RuntimeError('No existing Firebase web application found')
            response = session.get('https://firebase.googleapis.com/v1beta1/' + apps[0]['name'] + '/config', timeout=20)
            response.raise_for_status()
            config = response.json()
            if args.frontend_env:
                fields = {'VITE_FIREBASE_API_KEY': 'apiKey', 'VITE_FIREBASE_AUTH_DOMAIN': 'authDomain',
                          'VITE_FIREBASE_PROJECT_ID': 'projectId', 'VITE_FIREBASE_APP_ID': 'appId'}
                args.frontend_env.write_text('VITE_API_BASE_URL=http://127.0.0.1:5002\n' + ''.join(
                    key + '=' + config[field] + '\n' for key, field in fields.items()), encoding='utf-8')
            tokens = []
            for _ in range(2):
                uid = 'verify-zachary-' + uuid.uuid4().hex
                auth.create_user(uid=uid, display_name='Temporary backend verification', app=firebase)
                users.append(uid)
                custom = auth.create_custom_token(uid, app=firebase).decode('ascii')
                response = requests.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken',
                    params={'key': config['apiKey']}, json={'token': custom, 'returnSecureToken': True}, timeout=20)
                response.raise_for_status()
                tokens.append(response.json()['idToken'])
            def call(method, path, body=None, user=0):
                return app.test_client().open(path, method=method, json=body,
                    headers={'Authorization': 'Bearer ' + tokens[user]})
            station = {'mode': 'subway', 'type': 'station', 'id': 'R20'}
            targets = [station, {'mode':'subway','type':'route','id':'R'},
                       {'mode':'bus','type':'stop','id':'MTA_308214'},
                       {'mode':'bus','type':'route','id':'MTA NYCT_B63'}]
            for target in targets:
                response = call('POST', '/api/v2/favorites', {'target':target})
                record('save-' + target['mode'] + '-' + target['type'], response.status_code == 201)
                record('duplicate-' + target['mode'] + '-' + target['type'],
                       call('POST','/api/v2/favorites',{'target':target}).json == response.json)
            record('favorites-persist-across-app-restart', len(create_app({'TRANSIT_MODE':'live'}).test_client().get(
                '/api/v2/favorites', headers={'Authorization':'Bearer '+tokens[0]}).json['favorites']) == 4)
            record('second-user-isolated', call('GET','/api/v2/favorites',user=1).json['favorites'] == [])
            record('legacy-projects-v2-station', call('GET','/api/favorites').json['favorites'] == [{'station_id':'R20'}])
            direct = requests.get(f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/users/{users[0]}/favorites/R20',
                params={'key':config['apiKey']},headers={'Authorization':'Bearer '+tokens[0]},timeout=20)
            record('signed-in-browser-direct-firestore-denied', direct.status_code == 403)
            call('DELETE','/api/v2/favorites/'+target_id(station))
            record('v2-delete-visible-in-legacy', call('GET','/api/favorites').json['favorites'] == [])
            call('POST','/api/favorites',{'station_id':'R20'})
            record('legacy-create-visible-in-v2', len(call('GET','/api/v2/favorites').json['favorites']) == 4)
            ident = target_id(station)
            record('subscription-persist', call('PUT','/api/subscriptions/'+ident,
                   {'target':station,'enabled':True}).status_code == 200)
            fixture = {'mode':'subway','source':'demo','updated_at':datetime.now(timezone.utc).isoformat(),
                'alerts':[{'id':'verification-synthetic-disruption','header':'SYNTHETIC verification notice',
                    'description':'Not a real MTA event. Temporary backend verification only.',
                    'route_ids':['R'],'station_ids':['R20'],'stop_ids':['R20N'],'scope':'stop','impact':'disruption',
                    'selectors':[{'agency_id':'MTASBWY','route_id':'R','stop_id':'R20N'}]}]}
            with patch('app.services.personalization.fetch_alerts', return_value=fixture):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    concurrent = list(pool.map(lambda _: call('POST','/api/notifications/evaluate',{}),range(4)))
                record('concurrent-synthetic-notification-deduplicated',
                       all(r.status_code == 200 for r in concurrent) and sum(r.json['created'] for r in concurrent) == 1)
                row = call('GET','/api/notifications').json['notifications'][0]
                record('notification-other-user-inaccessible', call('PATCH','/api/notifications/'+row['id'],
                       {'read':True},user=1).status_code == 404)
                read = call('PATCH','/api/notifications/'+row['id'],{'read':True}).json
                record('read-state-persist', read['read'] and bool(read['read_at']))
                repeated = call('POST','/api/notifications/evaluate',{}).json
                record('dedup-and-read-preserved', repeated['created'] == 0 and repeated['unread_count'] == 0)
                call('PUT','/api/subscriptions/'+ident,{'target':station,'enabled':False})
                fixture['alerts'][0]['header'] = 'SYNTHETIC changed notice'
                record('disabled-no-new-notifications',call('POST','/api/notifications/evaluate',{}).json['created'] == 0)
            # Firebase revocation timestamps have one-second resolution.
            time.sleep(1.1)
            auth.revoke_refresh_tokens(users[0], app=firebase)
            record('revoked-token-rejected',call('GET','/api/v2/favorites').status_code == 401)
        report['passed'] = all(c['passed'] for c in report['checks'])
    except Exception as error:
        # requests exceptions may include credential-bearing URLs; log only type.
        report['passed'] = False
        report['error_type'] = type(error).__name__
        print('Verification stopped: ' + type(error).__name__, flush=True)
    finally:
        cleaned = True
        if users:
            with app.app_context():
                for uid in users:
                    try:
                        ref = db.collection('users').document(uid)
                        for collection in COLLECTIONS:
                            for doc in ref.collection(collection).stream():
                                doc.reference.delete()
                        ref.delete()
                        auth.delete_user(uid, app=firebase)
                    except Exception as error:
                        cleaned = False
                        print('Cleanup requires attention: ' + type(error).__name__, flush=True)
        report['cleanup'] = cleaned
        report['passed'] = report.get('passed', False) and cleaned
        if args.output:
            args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
