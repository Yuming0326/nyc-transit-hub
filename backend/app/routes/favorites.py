from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest
from ..services.firebase_service import favorites_collection, require_user
from ..services.transit_service import station_by_id
bp = Blueprint('favorites', __name__)
@bp.get('/favorites')
@require_user
def list_favorites():
    return jsonify(favorites=[{'station_id': doc.id} for doc in favorites_collection().stream()])
@bp.post('/favorites')
@require_user
def add_favorite():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('station_id'), str):
        raise BadRequest('station_id must be a string.')
    station = station_by_id(body['station_id'])
    favorites_collection().document(station['id']).set({'station_id': station['id']})
    return jsonify(station_id=station['id']), 201
@bp.delete('/favorites/<station_id>')
@require_user
def delete_favorite(station_id):
    station_by_id(station_id)
    favorites_collection().document(station_id).delete()
    return jsonify(deleted=True)
