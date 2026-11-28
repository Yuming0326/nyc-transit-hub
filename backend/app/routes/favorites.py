from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest
from ..services.firebase_service import require_user
from ..services.personal_store import run_user
from ..services.transit_service import station_by_id
bp = Blueprint('favorites', __name__)
@bp.get('/favorites')
@require_user
def list_favorites():
    return jsonify(run_user(lambda state: {'favorites': [{'station_id': ident} for ident in sorted(state['favorites'])]}))
@bp.post('/favorites')
@require_user
def add_favorite():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('station_id'), str):
        raise BadRequest('station_id must be a string.')
    station = station_by_id(body['station_id'])
    def save(state):
        state['favorites'][station['id']] = {'station_id': station['id']}
    run_user(save, write=True)
    return jsonify(station_id=station['id']), 201
@bp.delete('/favorites/<station_id>')
@require_user
def delete_favorite(station_id):
    station_by_id(station_id)
    def remove(state):
        state['favorites'].pop(station_id, None)
        # Also remove any typed station duplicate left by an older client.
        from ..services.saved_targets import target_id
        state['saved_items'].pop(target_id({'mode': 'subway', 'type': 'station', 'id': station_id}), None)
    run_user(remove, write=True)
    return jsonify(deleted=True)
