import math

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, ServiceUnavailable

from ..services.map_service import subway_map

bp = Blueprint('maps', __name__)


@bp.get('/map')
def map_data():
    for key in ('mode', 'route_id', 'bbox'):
        if len(request.args.getlist(key)) > 1:
            raise BadRequest(f'{key} must be supplied once.')
    mode = request.args.get('mode')
    if mode not in ('subway', 'bus'):
        raise BadRequest('mode must be subway or bus.')
    route_id = request.args.get('route_id')
    if route_id is not None and not route_id.strip():
        raise BadRequest('route_id must not be empty.')
    bbox = None
    if 'bbox' in request.args:
        try:
            bbox = tuple(float(value) for value in request.args['bbox'].split(','))
            if (len(bbox) != 4 or not all(math.isfinite(value) for value in bbox)
                    or not -180 <= bbox[0] < bbox[2] <= 180
                    or not -90 <= bbox[1] < bbox[3] <= 90):
                raise ValueError('Invalid bounds')
        except ValueError as error:
            raise BadRequest('bbox must be west,south,east,north with valid increasing bounds.') from error
    if mode == 'bus':
        raise ServiceUnavailable('Bus map geometry is not implemented yet.')
    return jsonify(subway_map(route_id, bbox))
