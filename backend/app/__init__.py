from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from .config import Config

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    CORS(app, resources={r'/api/*': {'origins': app.config['FRONTEND_ORIGIN']}})
    from .routes import health, stations, arrivals, alerts, favorites
    for module in (health, stations, arrivals, alerts, favorites):
        app.register_blueprint(module.bp, url_prefix='/api')

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception('Unhandled API error')
        return jsonify(error='Internal server error'), 500
    return app
