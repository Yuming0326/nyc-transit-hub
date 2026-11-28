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
            raise Unauthorized('Sign in to access personalized features.')
        app = firebase_app()
        from firebase_admin import auth
        try:
            decoded = auth.verify_id_token(header[7:], app=app, check_revoked=True)
            uid = decoded.get('uid')
            if not isinstance(uid, str) or not uid or len(uid) > 128 or '/' in uid:
                raise ValueError('Invalid user identity')
            g.user_id = uid
        except auth.CertificateFetchError as error:
            raise ServiceUnavailable('Firebase token verification is temporarily unavailable.') from error
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
