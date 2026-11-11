"""Code quality dashboard: the evidence of this code's commit and its code map, drawn as an interactive map."""
import os

from flask import Blueprint, jsonify, render_template

from backend.services.quality_report import EvidenceUnavailable, load_evidence
from backend.version import ENGINE_REPOSITORY_URL, engine_blob_base

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
        evidence, source, revision = load_evidence(_repo_root())
    except EvidenceUnavailable as error:
        return jsonify(available=False, revision=error.revision, reason=error.reason)
    # Source links go to the commits that were measured; a map built alone was read from this checkout.
    measured = (evidence['report'] or {}).get('revision', {})
    return jsonify(
        available=True,
        revision=revision,
        source=source,
        run_url=f'{APP_REPOSITORY_URL}/commit/{revision}/checks' if source == 'ci' else None,
        source_urls={
            'app': f"{APP_REPOSITORY_URL}/blob/{measured.get('app') or revision or 'main'}/",
            'engine': f"{ENGINE_REPOSITORY_URL}/blob/{measured['engine']}/" if measured.get('engine') else engine_blob_base(),
        },
        report=evidence['report'],
        code_map=evidence['code_map'],
    )
