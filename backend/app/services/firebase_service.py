from functools import wraps
from flask import current_app, g, request
from werkzeug.exceptions import BadRequest, ServiceUnavailable, Unauthorized

def firebase_app():
    import firebase_admin
    from firebase_admin import credentials
    try:
        return firebase_admin.get_app()
    except ValueError:
        try:
            return firebase_admin.initialize_app(credentials.ApplicationDefault(),
                {'projectId': current_app.config['FIREBASE_PROJECT_ID']})
        except Exception as error:
            raise ServiceUnavailable('Firebase is not configured on the backend.') from error

def require_user(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer ') or not header[7:].strip():
            raise Unauthorized('Sign in to access favorites.')
        app = firebase_app()
        from firebase_admin import auth
        try:
            g.user_id = auth.verify_id_token(header[7:], app=app, check_revoked=True)['uid']
        except Exception as error:
            raise Unauthorized('Invalid or expired Firebase token.') from error
        return handler(*args, **kwargs)
    return wrapped

def favorites_collection():
    from firebase_admin import firestore
    try:
        return firestore.client(app=firebase_app()).collection('users').document(g.user_id).collection('favorites')
    except ServiceUnavailable:
        raise
    except Exception as error:
        raise ServiceUnavailable('Firestore is unavailable. Check backend credentials.') from error
