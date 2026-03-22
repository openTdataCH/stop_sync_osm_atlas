from flask import Blueprint, jsonify

from backend.extensions import limiter
from backend.services.pipeline_status import get_status

system_bp = Blueprint("system", __name__)


@system_bp.route("/api/system/pipeline_status", methods=["GET"])
@limiter.limit("120/minute")
def pipeline_status():
    return jsonify(get_status())
