import re

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from ..services.schedule_service import EntityNotFound, schedule_response
from ..services.schedule_store import ScheduleUnavailable
from ..services.service_calendar import ServiceDateError

bp = Blueprint('schedules', __name__)
UNAVAILABLE = 'Schedule data is unavailable for this request.'


@bp.get('/schedules')
def schedules():
    for key in ('mode', 'date', 'station_id', 'stop_id', 'route_id', 'direction_id'):
        if len(request.args.getlist(key)) > 1:
            raise BadRequest(f'{key} must be supplied once.')
    mode = request.args.get('mode')
    if mode not in ('subway', 'bus'):
        raise BadRequest('mode must be subway or bus.')
    service_date = request.args.get('date', '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', service_date):
        raise BadRequest('date must be YYYY-MM-DD.')
    target_key = 'station_id' if mode == 'subway' else 'stop_id'
    other_key = 'stop_id' if mode == 'subway' else 'station_id'
    target = request.args.get(target_key)
    if other_key in request.args or target is None or not target.strip():
        raise BadRequest(f'{mode} schedules require exactly one {target_key}.')
    route_id = request.args.get('route_id')
    if route_id is not None and not route_id.strip():
        raise BadRequest('route_id must not be empty.')
    direction_id = request.args.get('direction_id')
    if direction_id is not None and direction_id not in ('0', '1'):
        raise BadRequest('direction_id must be 0 or 1.')
    try:
        return jsonify(schedule_response(current_app.extensions['schedules'], mode, service_date, target,
                                         route_id=route_id, direction_id=direction_id))
    except ServiceDateError as error:
        raise BadRequest('date must be a valid calendar date.') from error
    except EntityNotFound as error:
        raise NotFound(str(error)) from error
    except ScheduleUnavailable as error:
        current_app.logger.warning('Schedule unavailable: %s', error)
        raise ServiceUnavailable(str(error) or UNAVAILABLE) from error
