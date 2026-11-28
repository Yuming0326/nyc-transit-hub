"""User-scoped Firestore transactions; no browser storage or demo fallback."""
from copy import deepcopy

from flask import current_app, g
from google.api_core.exceptions import GoogleAPICallError, RetryError
from werkzeug.exceptions import ServiceUnavailable

from .firebase_service import firebase_app

COLLECTIONS = ('favorites', 'saved_items', 'subscriptions', 'notifications')
UNAVAILABLE = 'Personalized storage is temporarily unavailable. Please retry.'


class FirestorePersonalStore:
    def run(self, uid, operation, *, write=False):
        from firebase_admin import firestore
        try:
            db = firestore.client(app=firebase_app())
            user = db.collection('users').document(uid)

            @firestore.transactional
            def execute(transaction):
                # All mutations also update this guard: evaluation, unsubscribe,
                # read-state and legacy writes serialize for the same user.
                guard = user.get(transaction=transaction)
                before = {name: {doc.id: doc.to_dict() for doc in transaction.get(
                              user.collection(name).order_by('__name__'))}
                          for name in COLLECTIONS}
                state = deepcopy(before)
                result = operation(state)
                if write:
                    changes = [(name, key, rows.get(key)) for name, rows in state.items()
                               for key in rows.keys() | before[name].keys()
                               if rows.get(key) != before[name].get(key)]
                    # A single atomic Firestore commit, including the guard.
                    if len(changes) > 450:
                        raise ServiceUnavailable('Too many changes for one atomic notification refresh.')
                    if changes:
                        for name, key, value in changes:
                            reference = user.collection(name).document(key)
                            if value is None:
                                transaction.delete(reference)
                            else:
                                transaction.set(reference, value)
                        version = (guard.to_dict() or {}).get('personalization_version', 0)
                        transaction.set(user, {'personalization_version': version + 1}, merge=True)
                return result

            return execute(db.transaction())
        except (GoogleAPICallError, RetryError, OSError, ValueError) as error:
            current_app.logger.warning('Personalized storage unavailable (%s)', type(error).__name__)
            raise ServiceUnavailable(UNAVAILABLE) from error


def run_user(operation, *, write=False):
    # An injected store is exclusively for tests, never a production fallback.
    store = current_app.config.get('PERSONAL_STORE') if current_app.testing else None
    return (store or FirestorePersonalStore()).run(g.user_id, operation, write=write)
