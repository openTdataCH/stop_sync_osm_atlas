"""Review-app presentation configuration, independent of matching profiles."""

import json
import os
import re
from pathlib import Path

from flask import current_app


DEFAULTS = {
    "title": "OSM & ATLAS Synchronization", "source_label": "ATLAS",
    "source_id_label": "SLOID", "flag": "🇨🇭", "map_center": [46.8, 8.2], "map_zoom": 8,
    "map_bounds": [[45.5, 5.5], [48, 11]], "map_min_zoom": 8,
    "capabilities": {"routes": True, "gtfs_identity": True},
    "source_url_template": "https://atlas.app.sbb.ch/service-point-directory/service-points/{uic_ref}/traffic-point-elements",
    "route_search_normalization": "swiss_year",
}


def load_review_config(path=None):
    config = {**DEFAULTS, "capabilities": dict(DEFAULTS["capabilities"])}
    path = path or os.getenv("REVIEW_CONFIG")
    if path:
        with Path(path).open(encoding="utf-8") as handle:
            configured = json.load(handle)
        config.update(configured)
        config["capabilities"] = {**DEFAULTS["capabilities"], **configured.get("capabilities", {})}
    return config


def normalize_route_search_id(route_id):
    """Normalize user input for searching the app's already-normalized route IDs."""
    if not route_id:
        return None
    config = current_app.config.get("REVIEW_CONFIG", DEFAULTS)
    if config.get("route_search_normalization") == "swiss_year":
        return re.sub(r'-j\d+', '-jXX', str(route_id))
    return str(route_id)


def effective_review_config():
    """Limit configured views to capabilities exported by the active dataset."""
    from backend.services.data_meta import load_data_meta
    config = current_app.config['REVIEW_CONFIG']
    capabilities = dict(config['capabilities'])
    available = load_data_meta().get('source_capabilities')
    if isinstance(available, list):
        capabilities = {key: enabled and key in available for key, enabled in capabilities.items()}
    return {**config, 'capabilities': capabilities}
