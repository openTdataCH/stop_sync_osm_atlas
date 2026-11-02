"""The dashboard serves only the published evidence, and marks it stale when the running code changed."""
import json

import pytest

from backend.blueprints import quality
from backend.services import quality_report
from tests.test_quality_report import _example_report, _publish

CODE_MAP = {'schema_version': 1, 'modules': [], 'contracts': [], 'files': [], 'links': [], 'interface': {}}


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(quality, '_repo_root', lambda: str(tmp_path))
    return tmp_path


def _publish_with_map(root, report=None, code_map=CODE_MAP):
    _publish(root, report or _example_report())
    (root / quality_report.PUBLISHED / 'code-map.json').write_text(json.dumps(code_map))


def test_page_loads_the_graph_library_and_dashboard(client):
    response = client.get('/quality')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'vendor/cytoscape/cytoscape.min.js' in html
    assert 'js/quality/dashboard.js' in html
    assert 'data-api-url="/api/quality"' in html
    assert 'nav-link active' in html.split('>Docs</a>')[0].rsplit('<a', 1)[1]


def test_missing_evidence_is_unavailable(client, published):
    assert client.get('/api/quality').get_json() == {'available': False}


def test_malformed_code_map_is_unavailable(client, published):
    _publish_with_map(published, code_map={'schema_version': 2})
    assert client.get('/api/quality').get_json() == {'available': False}


def test_serves_report_map_and_measured_source_links(client, published):
    _publish_with_map(published)
    data = client.get('/api/quality').get_json()
    assert data['available'] and data['warning'] is None
    assert data['code_map'] == CODE_MAP
    assert data['report']['modules']['app.test']['coverage']['status'] == 'measured'
    assert data['run_url'] == 'https://github.com/example/actions/runs/1'
    assert data['source_urls']['app'].endswith('/blob/sha/')


def test_report_published_without_a_map_still_serves_the_evidence(client, published):
    _publish(published, _example_report())
    data = client.get('/api/quality').get_json()
    assert data['available'] and data['code_map'] is None


def test_changed_code_marks_every_result_stale(client, published):
    _publish_with_map(published)
    (published / 'backend/app.py').write_text('app = 2\n')
    data = client.get('/api/quality').get_json()
    assert 'the application code' in data['warning']
    assert data['report']['completeness'] == 'stale'
    assert data['report']['modules']['app.test']['tests']['status'] == 'stale'
