from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from .config import Config

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    from .services.transit_service import init_transit
    init_transit(app)
    from .services.map_service import init_map
    init_map(app)
    from .services.schedule_store import ScheduleStore
    app.extensions['schedules'] = ScheduleStore(app.config.get('SCHEDULE_DIR'))
    CORS(app, resources={r'/api/*': {'origins': app.config['FRONTEND_ORIGIN']}})
    from .routes import health, stations, arrivals, alerts, favorites, maps, schedules
    for module in (health, stations, arrivals, alerts, favorites, maps, schedules):
        app.register_blueprint(module.bp, url_prefix='/api')

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception('Unhandled API error')
        return jsonify(error='Internal server error'), 500
    return app
