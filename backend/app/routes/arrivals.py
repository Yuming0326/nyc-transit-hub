from flask import Blueprint, jsonify
from ..services.transit_service import arrivals_for
bp = Blueprint('arrivals', __name__)
@bp.get('/stations/<station_id>/arrivals')
def arrivals(station_id):
    return jsonify(arrivals_for(station_id))
