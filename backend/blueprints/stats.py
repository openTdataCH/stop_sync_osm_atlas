from flask import Blueprint, request, jsonify, current_app as app
from backend.extensions import limiter
from backend.services.global_stats import compute_global_stats_payload

stats_bp = Blueprint('stats', __name__)


@stats_bp.route('/api/global_stats', methods=['GET'])
@limiter.limit("30/minute")
def get_global_stats():
    try:
        return jsonify(compute_global_stats_payload(request.args))
    except Exception as e:
        app.logger.error(f"Error in global_stats: {str(e)}")
        return jsonify({"error": str(e)}), 500
