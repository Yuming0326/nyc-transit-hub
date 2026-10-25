from flask import Blueprint, jsonify, request
from ..services.transit_service import service_alerts
bp = Blueprint('alerts', __name__)
@bp.get('/alerts')
def alerts():
    return jsonify(service_alerts(request.args.get('route_id')))
