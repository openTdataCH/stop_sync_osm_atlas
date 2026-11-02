"""Code quality dashboard: the published report and code map, drawn as an interactive module graph."""
import os

from flask import Blueprint, jsonify, render_template

from backend.services.quality_report import load_published, stale_warning
from backend.version import ENGINE_REPOSITORY_URL

quality_bp = Blueprint('quality', __name__)

APP_REPOSITORY_URL = 'https://github.com/openTdataCH/stop_sync_osm_atlas'


def _repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


@quality_bp.route('/quality')
def quality_dashboard():
    return render_template('pages/quality.html')


@quality_bp.route('/api/quality')
def quality_data():
    """Everything the dashboard draws. Missing evidence is reported as unavailable, never as a pass."""
    try:
        report, code_map, publication, changed = load_published(_repo_root())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return jsonify(available=False)
    revisions = report.get('revision', {})
    return jsonify(
        available=True,
        warning=stale_warning(report, changed) if changed else None,
        run_url=publication.get('run_url'),
        source_urls={
            'app': f"{APP_REPOSITORY_URL}/blob/{revisions.get('app') or 'main'}/",
            'engine': f"{ENGINE_REPOSITORY_URL}/blob/{revisions.get('engine') or 'main'}/",
        },
        report=report,
        code_map=code_map,
    )
