from flask import Blueprint, jsonify, request

from ..services.bus_service import bus_arrivals, bus_vehicles

bp = Blueprint('bus', __name__)


@bp.get('/bus/stops/<stop_id>/arrivals')
def arrivals(stop_id):
    return jsonify(bus_arrivals(stop_id, request.args))


@bp.get('/bus/vehicles')
def vehicles():
    return jsonify(bus_vehicles(request.args))
