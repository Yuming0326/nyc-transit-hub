from flask import Blueprint, current_app, jsonify
bp = Blueprint('health', __name__)
@bp.get('/health')
def health():
    return jsonify(status='ok', transit_mode=current_app.config['TRANSIT_MODE'])
