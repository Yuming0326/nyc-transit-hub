from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, NotFound, ServiceUnavailable

from ..services.journey_planner import JourneyInputError, TransferUnavailable
from ..services.schedule_service import EntityNotFound
from ..services.schedule_store import ScheduleUnavailable

bp = Blueprint('journeys', __name__)
UNAVAILABLE = 'Schedule data is unavailable for this journey.'


@bp.post('/journeys')
def journeys():
    body = request.get_json(silent=True)
    if body is None:
        raise BadRequest('Request body must be JSON.')
    try:
        return jsonify(current_app.extensions['journeys'].plan(body))
    except JourneyInputError as error:
        raise BadRequest(str(error)) from error
    except EntityNotFound as error:
        raise NotFound(str(error)) from error
    except TransferUnavailable as error:
        raise ServiceUnavailable(str(error)) from error
    except ScheduleUnavailable as error:
        current_app.logger.warning('Journey planning unavailable: %s', error)
        raise ServiceUnavailable(UNAVAILABLE) from error
