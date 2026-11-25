from flask import Blueprint, jsonify, request

from ..services import catalog_service as catalog
from ..services.affected_alerts_service import transit_alerts

bp = Blueprint('catalog', __name__)


@bp.get('/stations/<station_id>')
def station_detail(station_id):
    return jsonify(catalog.station_detail(station_id))


@bp.get('/subway/routes')
def subway_routes():
    return jsonify(catalog.subway_routes(request.args))


@bp.get('/subway/routes/<route_id>')
def subway_route_detail(route_id):
    return jsonify(catalog.subway_route_detail(route_id))


@bp.get('/bus/routes')
def bus_routes():
    return jsonify(catalog.bus_routes(request.args))


@bp.get('/bus/routes/<route_id>')
def bus_route_detail(route_id):
    return jsonify(catalog.bus_route_detail(route_id))


@bp.get('/bus/stops')
def bus_stops():
    return jsonify(catalog.bus_stops(request.args))


@bp.get('/bus/stops/<stop_id>')
def bus_stop_detail(stop_id):
    return jsonify(catalog.bus_stop_detail(stop_id))


@bp.get('/transit/alerts')
def alerts():
    return jsonify(transit_alerts(request.args))
