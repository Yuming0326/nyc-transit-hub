from flask import Blueprint, jsonify, request
from ..services.transit_service import list_stations
bp = Blueprint('stations', __name__)
@bp.get('/stations')
def stations():
    query = request.args.get('search', '').strip().casefold()
    return jsonify(stations=[s for s in list_stations() if query in (s['name'] + ' ' + ' '.join(s['routes'])).casefold()])
