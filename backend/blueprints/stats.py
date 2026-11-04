from flask import Blueprint, request, jsonify, current_app as app
from backend.extensions import db, limiter
from backend.db_errors import is_missing_table_error
from backend.services.global_stats import compute_global_stats_payload

stats_bp = Blueprint('stats', __name__)


@stats_bp.route('/api/global_stats', methods=['GET'])
@limiter.limit("30/minute")
def get_global_stats():
    try:
        response_payload = compute_global_stats_payload(request.args, db.session)
        return jsonify(response_payload)
    except Exception as e:
        if is_missing_table_error(e):
            db.session.rollback()
            app.logger.warning("Global stats unavailable: matching tables are not initialized yet.")
            return jsonify({
                "total_atlas_stops": 0,
                "matched_atlas_stops": 0,
                "total_osm_stops": 0,
                "matched_osm_stops": 0,
                "total_osm_nodes": 0,
                "matched_osm_nodes": 0,
                "matched_pairs_count": 0,
                "unmatched_entities_count": 0,
            }), 200
        app.logger.error(f"Error in global_stats: {str(e)}")
        return jsonify({"error": str(e)}), 500
