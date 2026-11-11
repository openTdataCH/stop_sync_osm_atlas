"""The dashboard page and its data: the evidence of the running commit, or a plain statement that there is none."""
import json

import pytest

from backend.blueprints import quality
from backend.services import quality_report
from tests.test_quality_report import CODE_MAP, SHA, _evidence


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """An empty checkout at commit SHA, for which GitHub has nothing."""
    monkeypatch.setattr(quality, '_repo_root', lambda: str(tmp_path))
    monkeypatch.setenv('APP_REVISION', SHA)
    return tmp_path


def test_page_loads_the_graph_library_and_dashboard(client):
    response = client.get('/quality')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'vendor/cytoscape/cytoscape.min.js' in html
    for script in ('code-map', 'rendering', 'dashboard'):
        assert 'js/quality/' + script + '.js' in html
    assert 'data-api-url="/api/quality"' in html
    assert 'nav-link active' in html.split('>Docs</a>')[0].rsplit('<a', 1)[1]


def test_page_offers_the_three_levels_with_the_search_the_module_list_and_the_result_sections(client):
    html = client.get('/quality').get_data(as_text=True)
    levels = [part.split('"', 1)[0] for part in html.split('data-level="')[1:]]
    assert levels == ['modules', 'files', 'symbols']
    assert '>Functions</button>' in html
    for control in ('id="qualityExplorer"', 'id="qualitySearch"', 'id="qualityEdgesToggle"', 'id="qualityLabelsToggle"', 'data-color-by="module"',
                    'data-color-by="coverage"', 'id="qualityCleanup"', 'id="qualityFindings"', 'id="qualityBlindSpots"', 'id="qualityTable"'):
        assert control in html
    # The result tables are hidden when a local map has no report.
    assert html.count('data-needs-report') == 2
    # The expand button is a class on the workspace, not the browser's full screen.
    assert 'id="qualityFullscreen" title="Expand the map to the window"' in html


def test_a_commit_without_published_results_is_unavailable_and_named(client, checkout):
    assert client.get('/api/quality').get_json() == {'available': False, 'revision': SHA, 'reason': 'no_results'}


def test_an_unknown_commit_is_unavailable(client, checkout, monkeypatch):
    monkeypatch.setattr(quality_report, 'app_revision', lambda: None)
    assert client.get('/api/quality').get_json() == {'available': False, 'revision': None, 'reason': 'unknown_commit'}


def test_serves_the_ci_evidence_of_the_running_commit_with_links_to_what_was_measured(client, checkout, monkeypatch):
    monkeypatch.setattr(quality_report, 'download', lambda revision: json.dumps(_evidence()).encode())
    data = client.get('/api/quality').get_json()
    assert (data['available'], data['source'], data['revision']) == (True, 'ci', SHA)
    assert data['code_map'] == CODE_MAP
    assert data['report']['modules']['app.test']['coverage']['status'] == 'measured'
    assert data['run_url'] == f'https://github.com/openTdataCH/stop_sync_osm_atlas/commit/{SHA}/checks'
    assert data['source_urls'] == {'app': f'https://github.com/openTdataCH/stop_sync_osm_atlas/blob/{SHA}/',
                                   'engine': f"https://github.com/openTdataCH/osm-public-transport-matcher/blob/{'b' * 40}/"}


def test_serves_a_local_map_without_a_report_and_links_to_this_checkout(client, checkout):
    (checkout / 'quality').mkdir()
    (checkout / 'quality/evidence.json').write_text(json.dumps(_evidence(report=None)))
    data = client.get('/api/quality').get_json()
    assert (data['available'], data['source'], data['report'], data['run_url']) == (True, 'local', None, None)
    assert data['code_map'] == CODE_MAP
    assert data['source_urls']['app'].endswith(f'/blob/{SHA}/')
    assert data['source_urls']['engine'] == quality.engine_blob_base()
