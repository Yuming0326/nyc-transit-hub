from flask import Blueprint, jsonify

from ..services.firebase_service import require_user
from ..services import personalization as service

bp = Blueprint('personalization', __name__)


@bp.get('/v2/favorites')
@require_user
def favorites():
    return jsonify(service.list_favorites())


@bp.post('/v2/favorites')
@require_user
def add_favorite():
    return jsonify(service.add_favorite()), 201


@bp.delete('/v2/favorites/<ident>')
@require_user
def delete_favorite(ident):
    return jsonify(service.delete_favorite(ident))


@bp.get('/subscriptions')
@require_user
def subscriptions():
    return jsonify(service.list_subscriptions())


@bp.put('/subscriptions/<ident>')
@require_user
def put_subscription(ident):
    return jsonify(service.put_subscription(ident))


@bp.delete('/subscriptions/<ident>')
@require_user
def delete_subscription(ident):
    return jsonify(service.delete_subscription(ident))


@bp.post('/notifications/evaluate')
@require_user
def evaluate():
    return jsonify(service.evaluate_notifications())


@bp.get('/notifications')
@require_user
def notifications():
    return jsonify(service.list_notifications())


@bp.patch('/notifications/<ident>')
@require_user
def mark_read(ident):
    return jsonify(service.mark_notification(ident))
