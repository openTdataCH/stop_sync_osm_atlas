"""Acceptance tests for evidence integrity, ownership and architecture policies."""
import ast
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from scripts import quality


def test_globs_include_direct_and_nested_files():
    assert quality.matches('backend/a.py', 'backend/**/*.py')
    assert quality.matches('backend/importing/a.py', 'backend/**/*.py')
    assert not quality.matches('static/a.js', 'backend/**/*.py')


def test_commonjs_scripts_are_in_the_ownership_inventory(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/check.cjs').write_text('module.exports = {};\n')
    assert quality.source_files(tmp_path, {'source_roots': ['scripts']}, []) == ['scripts/check.cjs']


def test_clone_budget_counts_extra_copies_but_not_repeated_analyzer_output():
    original = {'id': 'same-content-and-file-pair', 'kind': 'clone', 'locations': [
        {'file': 'app:a.js', 'start': 10, 'end': 20}, {'file': 'app:b.js', 'start': 30, 'end': 40}]}
    repeated = {**original, 'locations': list(reversed(original['locations']))}
    baseline = quality.occurrence_findings([original, repeated])
    assert len(baseline) == 1
    added = {**original, 'locations': [original['locations'][0], {'file': 'app:b.js', 'start': 70, 'end': 80}]}
    current = quality.occurrence_findings([original, repeated, added])
    assert len(current) == 2
    assert len({item['id'] for item in current} - {item['id'] for item in baseline}) == 1


def test_clone_identity_survives_line_movement_without_allowing_new_content():
    original = {'id': 'first-content', 'kind': 'clone', 'locations': [
        {'file': 'app:a.js', 'start': 10, 'end': 20}, {'file': 'app:a.js', 'start': 30, 'end': 40}]}
    shifted = {**original, 'locations': [{**item, 'start': item['start'] + 9, 'end': item['end'] + 9} for item in original['locations']]}
    assert quality.occurrence_findings([original])[0]['id'] == quality.occurrence_findings([shifted])[0]['id']
    changed = {**shifted, 'id': 'different-content'}
    assert quality.occurrence_findings([original])[0]['id'] != quality.occurrence_findings([changed])[0]['id']


def test_source_ownership_rejects_missing_or_duplicate_owner(tmp_path, monkeypatch):
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/a.py').write_text('answer = 42\n')
    (tmp_path / 'quality/exclusions.json').write_text('{"source": []}')
    catalog = {'source_roots': ['src'], 'modules': []}
    path = tmp_path / 'quality/modules.yml'
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'schema_validate', lambda *args: None)
    with pytest.raises(ValueError, match='exactly one owner'):
        quality.load_catalogs()
    catalog['modules'] = [{'id': name, 'paths': {'source': ['src/**']}} for name in ['first', 'second']]
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='exactly one owner'):
        quality.load_catalogs()


def test_python_coverage_requires_branch_measurement(tmp_path):
    with pytest.raises(ValueError, match='branch coverage'):
        quality.coverage_files({'meta': {'branch_coverage': False}}, tmp_path)


def test_javascript_coverage_counts_never_executed_statements(tmp_path):
    data = {'static/js/a.js': {'statementMap': {'0': {'start': {'line': 1}}, '1': {'start': {'line': 2}}}, 's': {'0': 1, '1': 0}, 'b': {'0': [1, 0]}}}
    result = quality.coverage_files(data, tmp_path, True)['static/js/a.js']
    assert result['lines'] == 2
    assert result['covered_lines'] == 1
    assert result['branches'] == 2
    assert result['covered_branches'] == 1


def test_architecture_rejects_hidden_engine_import(tmp_path):
    (tmp_path / 'app.py').write_text('def run():\n    from osm_public_transport_matcher import match\n')
    findings = quality.architecture({'app': tmp_path}, {('app', 'app.py'): 'app.query-api'})
    assert findings and findings[0]['line'] == 2


def test_core_architecture_resolves_relative_imports(tmp_path):
    file = tmp_path / 'src/osm_public_transport_matcher/core/matching.py'
    file.parent.mkdir(parents=True)
    file.write_text('from ..adapters import gtfs\n')
    assert quality.architecture({'engine': tmp_path}, {('engine', 'src/osm_public_transport_matcher/core/matching.py'): 'engine.core-matching'})


def test_expired_exceptions_fail(tmp_path, monkeypatch):
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/exceptions.json').write_text(json.dumps([{'module': 'test', 'finding': 'a', 'owner': 'maintainer', 'reason': 'temporary', 'expires': '2000-01-01'}]))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='expired'):
        quality.active_exceptions({'test'})


def test_fingerprint_changes_for_dirty_source_but_not_generated_output(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'source.py').write_text('answer = 41\n')
    before = quality.repository_fingerprint(tmp_path)
    (tmp_path / 'source.py').write_text('answer = 42\n')
    after = quality.repository_fingerprint(tmp_path)
    assert after != before
    (tmp_path / 'quality').mkdir()
    (tmp_path / 'quality/latest.json').write_text('{}')
    assert quality.repository_fingerprint(tmp_path) == after


def test_report_never_treats_missing_file_as_covered(tmp_path, monkeypatch):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    schema = Path(quality.ROOT / 'quality/latest.schema.json').read_text()
    (tmp_path / 'quality/latest.schema.json').write_text(schema)
    (tmp_path / 'a.py').write_text('pass\n')
    module = dict(id='app.test', criticality='high', owner='test', reviewed='2026-09-22', invariants=['Invariant'], docs={'explanation':['README.md']}, paths={'tests':[]})
    coverage = {'meta': {'branch_coverage': True}, 'files': {'backend/a.py': {'summary': {'num_statements': 1, 'covered_lines': 1, 'num_branches': 2, 'covered_branches': 1}, 'executed_lines': [1], 'missing_lines': []}}}
    (raw / 'app-python-coverage.json').write_text(json.dumps(coverage))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'architecture', lambda *args: [])
    monkeypatch.setattr(quality, 'revision', lambda *args: 'sha')
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda *args: 'fingerprint')
    (raw / 'checks.json').write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(), 'revision': {'app':'sha','engine':'sha'}, 'fingerprints': {'app':'fingerprint'}, 'checks': []}))
    result = quality.report({'app':tmp_path}, {'app':{'modules':[module]}}, {('app','backend/a.py'):'app.test', ('app','backend/untested.py'):'app.test'})
    cov = result['modules']['app.test']['coverage']
    assert cov['status'] == 'invalid'
    assert cov['missing_files'] == ['backend/untested.py']
    assert result['modules']['app.test']['tests']['status'] == 'not_measured'


def test_junit_skipped_scenarios_are_not_a_pass(tmp_path):
    path = tmp_path / 'tests.xml'
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_snapshot"><skipped/></testcase><testcase classname="tests.test_snapshot"><failure/></testcase></testsuite></testsuites>')
    rows = quality.test_results(path)
    assert rows[0]['skipped'] == 1
    assert rows[1]['failed'] is True


@pytest.mark.parametrize('inventory,python_status,javascript_status', [
    (['app:backend/app.py'], 'pass', 'not_applicable'),
    (None, 'not_measured', 'not_measured'),
    ({'app:backend/app.py': True}, 'invalid', 'invalid'),
])
def test_dead_code_results_require_recorded_python_analyzer_inputs(tmp_path, monkeypatch, inventory, python_status, javascript_status):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    (tmp_path / 'quality/latest.schema.json').write_text((quality.ROOT / 'quality/latest.schema.json').read_text())
    debt = {'schema_version': 1, 'findings': []}
    if inventory is not None:
        debt['analyzed_python_files'] = inventory
    (raw / 'debt.json').write_text(json.dumps(debt))
    (raw / 'checks.json').write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(),
        'revision': {'app': 'sha', 'engine': 'sha'}, 'fingerprints': {'app': 'fingerprint'}, 'checks': []}))
    modules = [dict(id=mid, criticality='high', owner='test', reviewed='2026-09-22', invariants=['Invariant'],
                    docs={'explanation': ['README.md']}, paths={'tests': []}) for mid in ('app.python', 'app.javascript')]
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'architecture', lambda *args: [])
    monkeypatch.setattr(quality, 'revision', lambda *args: 'sha')
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda *args: 'fingerprint')
    result = quality.report({'app': tmp_path}, {'app': {'modules': modules}}, {
        ('app', 'backend/app.py'): 'app.python', ('app', 'static/js/review.js'): 'app.javascript'})
    for module, status in [('app.python', python_status), ('app.javascript', javascript_status)]:
        lane = result['modules'][module]['dead_code']
        assert lane['status'] == status
        assert lane['analyzer'] == 'Vulture'
        assert lane['scope'] == 'Python'
        assert ('count' in lane) == (status == 'pass')
    assert '| Python dead code |' in (tmp_path / 'quality/report.md').read_text()


def test_junit_class_failures_belong_to_the_test_module(tmp_path):
    path = tmp_path / 'tests.xml'
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_validators.TestPagination" name="test_invalid"><failure/></testcase></testsuite></testsuites>')
    row = quality.test_results(path, root=tmp_path)[0]
    assert row['file'] == 'tests/test_validators.py'
    assert row['failed'] is True


def test_junit_prefers_existing_module_prefix_over_class_name(tmp_path):
    (tmp_path / 'scenarios').mkdir()
    (tmp_path / 'scenarios/contract.py').write_text('')
    assert quality.testcase_file({'classname': 'scenarios.contract.TestBundle.Nested'}, tmp_path) == 'scenarios/contract.py'
    assert quality.testcase_file({'classname': 'ignored.Class', 'file': 'explicit.py'}, tmp_path) == 'explicit.py'


@pytest.mark.parametrize('content', ['not JSON', 'null', '[]', '{}', '{"schema_version": 1, "tests_sha256": []}'])
def test_malformed_optional_mutation_evidence_is_invalid_without_breaking_report(tmp_path, content):
    artifact = tmp_path / 'mutation.json'
    artifact.write_text(content)
    assert quality.mutation_evidence(artifact, tmp_path)['status'] == 'invalid'


def test_mutation_evidence_is_measured_only_for_matching_sources_and_valid_totals(tmp_path):
    source = tmp_path / 'src/osm_public_transport_matcher/results/validation.py'
    test = tmp_path / 'tests/test_results.py'
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text('original source')
    test.write_text('original test')
    data = dict(schema_version=1, started_at=datetime.now(timezone.utc).isoformat(),
                source_path=source.relative_to(tmp_path).as_posix(), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                tests_sha256={test.relative_to(tmp_path).as_posix(): hashlib.sha256(test.read_bytes()).hexdigest()},
                scope='osm_public_transport_matcher.results.validation.*_position*', total_mutants=2, counts={'killed': 1, 'survived': 1})
    artifact = tmp_path / 'mutation.json'
    artifact.write_text(json.dumps(data))
    assert quality.mutation_evidence(artifact, tmp_path)['score'] == 50
    source.write_text('changed source')
    assert quality.mutation_evidence(artifact, tmp_path)['status'] == 'stale'
    data['counts'] = {'killed': 3, 'survived': -1}
    artifact.write_text(json.dumps(data))
    assert quality.mutation_evidence(artifact, tmp_path)['status'] == 'invalid'


def test_required_coverage_gate_rejects_missing_report(tmp_path, monkeypatch):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    (raw / 'checks.json').write_text(json.dumps({'fingerprints': {'app': 'current', 'engine': 'current'}}))
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda root: 'current')
    with pytest.raises(ValueError, match='Missing coverage artifact'):
        quality.coverage_sanity({'app': tmp_path, 'engine': tmp_path}, {})


def test_required_coverage_gate_rejects_source_changed_during_run(tmp_path, monkeypatch):
    raw = tmp_path / 'quality/raw'
    raw.mkdir(parents=True)
    (raw / 'checks.json').write_text('{"fingerprints": {"app": "before"}}')
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    monkeypatch.setattr(quality, 'repository_fingerprint', lambda root: 'after')
    with pytest.raises(ValueError, match='current source inputs'):
        quality.coverage_sanity({'app': tmp_path}, {})


def test_map_resolves_calls_through_imports_and_reports_each_module_interface(tmp_path, monkeypatch):
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    sources = {
        'backend/__init__.py': '',
        'backend/services/__init__.py': 'from backend.services.store import save\n',
        'backend/services/store.py': 'def save():\n    return _private()\n\n\ndef _private():\n    return 1\n',
        'backend/api.py': 'from backend.services import store\nfrom backend.services import save as persist\n\n\ndef handle():\n    store.save()\n    return persist()\n',
        'static/js/shared.js': 'function formatValue(value) {\n    function inner() {}\n    return value;\n}\n',
        'static/js/page.js': 'formatValue(inner());\n',
    }
    for name, text in sources.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    store_files = {'backend/services/__init__.py', 'backend/services/store.py', 'static/js/shared.js'}
    ownership = {('app', name): 'app.store' if name in store_files else 'app.api' for name in sources}
    def module(mid, entrypoints=()):
        return dict(id=mid, title=mid, criticality='high', responsibility='r', owner='o', reviewed='2026-11-02', invariants=[],
                    entrypoints=list(entrypoints), dependencies=[], paths={'source': [], 'tests': []}, docs={})
    catalogs = {'app': {'modules': [module('app.api'), module('app.store', ['backend.services:save'])], 'contracts': []}}
    graph = quality.build_map({'app': tmp_path}, catalogs, ownership)
    edges = {(item['source'], item['target'], item['kind']) for item in graph['edges']}
    api, package = 'app:backend/api.py', 'app:backend/services/__init__.py'
    save = 'app:backend/services/store.py:save@1'
    assert (api, 'app:backend/services/store.py', 'imports') in edges
    # Importing a submodule does not import the package's __init__; importing a name from it does.
    assert [item['line'] for item in graph['edges'] if (item['source'], item['target'], item['kind']) == (api, package, 'imports')] == [2]
    assert (api, save, 'uses') in edges
    assert ('app:backend/api.py:handle@5', save, 'calls') in edges
    assert (save, 'app:backend/services/store.py:_private@5', 'calls') in edges
    # Only top-level browser declarations are visible to other scripts.
    assert ('app:static/js/page.js', 'app:static/js/shared.js:formatValue@1', 'uses') in edges
    assert not any(target.endswith(':inner@2') for _, target, kind in edges if kind == 'uses')

    code_map = json.loads((tmp_path / 'quality/code-map.json').read_text())
    assert [(row['name'], row['used_by']) for row in code_map['interface']['app.store']] == [('save', ['app.api']), ('formatValue', ['app.api'])]
    assert code_map['modules'][1]['entrypoints'] == [{'entry': 'backend.services:save', 'symbol': save}]
    assert {'source': api, 'target': 'app:backend/services/store.py', 'kind': 'calls', 'count': 2} in code_map['links']


def test_map_links_requests_templates_and_browser_namespaces_and_reports_blind_spots(tmp_path, monkeypatch):
    monkeypatch.setattr(quality, 'ROOT', tmp_path)
    sources = {
        'backend/app.py': "from flask import Flask, render_template\n\napp = Flask(__name__)\n\n\n@app.route('/')\ndef index():\n"
                          "    return render_template('pages/index.html')\n",
        'backend/api.py': "from flask import Blueprint, url_for\n\napi_bp = Blueprint('api', __name__)\n\n\n"
                          "@api_bp.route('/api/items/<item_id>', methods=['GET', 'POST'])\ndef item(item_id):\n    return url_for('index')\n\n\n"
                          "@api_bp.get('/api/unused')\ndef unused():\n    return render_template(name)\n",
        'templates/layouts/base.html': '<script src="{{ url_for(\'static\', filename=\'js/page.js\') }}"></script>\n',
        'templates/pages/index.html': '{% extends "layouts/base.html" %}\n<a href="{{ url_for(\'index\') }}">Home</a>\n'
                                      '<div data-url="{{ url_for(\'api.item\', item_id=1) }}"></div>\n{% include "missing.html" %}\n',
        'static/js/page.js': "fetch('/api/items/' + id);\n$.ajax({ url: config.url });\nvar namespace = window.Shared = window.Shared || {};\n"
                             "namespace.Tool = function () {};\nvar gone = '/api/gone';\n",
        'static/js/other.js': 'Shared.Tool();\nhelper();\n// Shared.Missing() in a comment is no use.\n',
        'static/js/a.js': 'function helper() {}\n',
        'static/js/b.js': 'function helper() {}\n',
    }
    for name, text in sources.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    ownership = {('app', name): 'app.api' if name == 'backend/api.py' else 'app.web' for name in sources}
    def module(mid):
        return dict(id=mid, title=mid, criticality='high', responsibility='r', owner='o', reviewed='2026-11-04', invariants=[],
                    entrypoints=[], dependencies=[], paths={'source': [], 'tests': []}, docs={})
    catalogs = {'app': {'modules': [module('app.api'), module('app.web')], 'contracts': []}}
    graph = quality.build_map({'app': tmp_path}, catalogs, ownership)
    edges = {(item['source'], item['target'], item['kind']) for item in graph['edges']}
    index, item = 'app:backend/app.py:index@7', 'app:backend/api.py:item@7'
    page, home = 'app:static/js/page.js', 'app:templates/pages/index.html'

    assert {(route['pattern'], route['endpoint'], tuple(route['methods'])) for route in graph['routes']} == {
        ('/', 'index', ('GET',)), ('/api/items/<item_id>', 'api.item', ('GET', 'POST')), ('/api/unused', 'api.unused', ('GET',))}
    # A URL with a runtime part reaches its route; an API url_for is a request, a page url_for a link.
    assert (page, item, 'requests') in edges
    assert (home, item, 'requests') in edges
    assert (home, index, 'links') in edges
    assert ('app:backend/api.py:item@7', index, 'links') in edges
    assert (home, 'app:templates/layouts/base.html', 'extends') in edges
    assert (index, home, 'renders') in edges
    # A namespace member links to the script that defines it; a name in a comment does not.
    assert ('app:static/js/other.js', 'app:static/js/page.js:Shared.Tool@4', 'uses') in edges
    assert not any('Missing' in target for _, target, _ in edges)
    assert not any(source == 'app:static/js/other.js' and 'helper' in target for source, target, _ in edges)

    spots = graph['blind_spots']
    assert [(row['file'], row['line'], row['kind'], row['reference']) for row in spots['unmatched']] == [
        (page, 5, 'url', '/api/gone'), (home, 4, 'template', 'missing.html')]
    assert [(row['file'], row['line'], row['kind'], row['expression']) for row in spots['dynamic']] == [
        ('app:backend/api.py', 13, 'render_template', 'name'), (page, 2, 'request', 'config.url')]
    assert spots['shared_names'] == [{'name': 'helper', 'symbols': ['app:static/js/a.js:helper@1', 'app:static/js/b.js:helper@1']}]

    code_map = json.loads((tmp_path / 'quality/code-map.json').read_text())
    routes = {route['endpoint']: route for route in code_map['routes']}
    assert routes['api.item']['requested_by'] == [page, home]
    assert (routes['api.unused']['requested_by'], routes['api.unused']['linked_by']) == ([], [])
    assert routes['index']['linked_by'] == ['app:backend/api.py', home]
    # A request uses the view's code; following a link does not.
    assert [(row['name'], row['used_by']) for row in code_map['interface']['app.api']] == [('item', ['app.web'])]
    assert not any(row['name'] == 'index' for row in code_map['interface']['app.web'])
    # The function view gets every function and each link with a function at one end.
    assert {'id': item, 'name': 'item', 'file': 'app:backend/api.py', 'line': 7} in code_map['symbols']
    assert {'source': page, 'target': item, 'kind': 'requests', 'count': 1} in code_map['symbol_links']
    assert {'source': item, 'target': index, 'kind': 'links', 'count': 1} in code_map['symbol_links']
    assert {'source': index, 'target': home, 'kind': 'renders', 'count': 1} in code_map['symbol_links']


def test_route_table_matches_the_registered_flask_routes(app):
    found = set()
    for path in sorted((quality.ROOT / 'backend').rglob('*.py')):
        fid = 'app:' + path.relative_to(quality.ROOT).as_posix()
        found.update((route['pattern'], route['endpoint'], tuple(route['methods'])) for route in quality.flask_routes(fid, ast.parse(path.read_text())))
    registered = {(rule.rule, rule.endpoint, tuple(sorted(rule.methods - {'HEAD', 'OPTIONS'})))
                  for rule in app.url_map.iter_rules() if rule.endpoint != 'static'}
    assert found == registered


@pytest.mark.parametrize(('url', 'pattern'), [
    ('/api/report_progress/', '/api/report_progress/<task_id>'),
    ('/api/data?{}', '/api/data'),
    ('/docs/a/b', '/docs/<path:page>'),
    ('/docs/assets/x.png', '/docs/assets/<path:filename>'),
    ('/api/routes/{}/popup', None),
])
def test_urls_match_the_most_specific_route(url, pattern):
    routes = [dict(pattern=rule, regex=quality.route_regex(rule)) for rule in
              ('/api/report_progress/<task_id>', '/api/data', '/docs/<path:page>', '/docs/assets/<path:filename>', '/api/routes/gtfs/popup')]
    match = quality.match_route(url, routes)
    assert (match['pattern'] if match else None) == pattern
