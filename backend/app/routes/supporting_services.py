from flask import Blueprint, jsonify, request

from ..services.supporting_services import service_status, station_equipment

bp = Blueprint('supporting_services', __name__)


@bp.get('/service-status')
def status():
    return jsonify(service_status(request.args))


@bp.get('/stations/<station_id>/equipment')
def equipment(station_id):
    return jsonify(station_equipment(station_id))
